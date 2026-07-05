package tui

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"sync"
	"sync/atomic"
)

type Request struct {
	ID     string `json:"id"`
	Action string `json:"action"`
	Input  any    `json:"input"`
}

type Response struct {
	ID     string          `json:"id"`
	OK     bool            `json:"ok"`
	Event  json.RawMessage `json:"event,omitempty"`
	Result json.RawMessage `json:"result,omitempty"`
	Error  string          `json:"error,omitempty"`
	Done   bool            `json:"done,omitempty"`
}

type Worker struct {
	cmd     *exec.Cmd
	stdin   io.WriteCloser
	scanner *bufio.Scanner

	pendingMu sync.Mutex
	writeMu   sync.Mutex
	pending   map[string]chan Response

	nextID atomic.Uint64
	done   chan struct{}
	err    error
}

func workerCommand() (*exec.Cmd, error) {
	if os.Getenv("APP_ENV") == "dev" {
		pythonPath := filepath.Join("..", "venv", "bin", "python")
		if runtime.GOOS == "windows" {
			pythonPath = filepath.Join("..", "venv", "Scripts", "python.exe")
		}

		workerScript := filepath.Join("..", "local_worker", "worker.py")

		cmd := exec.Command(pythonPath, workerScript)
		cmd.Env = append(os.Environ(), "IATREON_LOCAL_WORKER=1")
		return cmd, nil
	}

	exe, err := os.Executable()
	if err != nil {
		return nil, err
	}

	dir := filepath.Dir(exe)

	name := "python-worker"
	if runtime.GOOS == "windows" {
		name += ".exe"
	}

	workerPath := filepath.Join(dir, name)

	cmd := exec.Command(workerPath)
	cmd.Env = append(os.Environ(), "IATREON_LOCAL_WORKER=1")
	return cmd, nil
}

func StartPythonWorker() (*Worker, error) {
	cmd, err := workerCommand()
	if err != nil {
		return nil, err
	}

	// cmd := exec.Command(path)

	stdin, err := cmd.StdinPipe()
	if err != nil {
		return nil, err
	}

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return nil, err
	}

	cmd.Stderr = os.Stderr

	if err := cmd.Start(); err != nil {
		return nil, err
	}

	scanner := bufio.NewScanner(stdout)
	scanner.Buffer(make([]byte, 1024), 10*1024*1024)

	w := &Worker{
		cmd:     cmd,
		stdin:   stdin,
		scanner: scanner,
		pending: make(map[string]chan Response),
		done:    make(chan struct{}),
	}

	go w.readLoop()
	go func() {
		_ = cmd.Wait()
	}()

	return w, nil
}

func (w *Worker) readLoop() {
	defer close(w.done)

	for w.scanner.Scan() {
		var resp Response

		if err := json.Unmarshal(w.scanner.Bytes(), &resp); err != nil {
			continue
		}

		w.pendingMu.Lock()
		ch := w.pending[resp.ID]
		if resp.Done {
			delete(w.pending, resp.ID)
		}
		w.pendingMu.Unlock()

		if ch != nil {
			ch <- resp
			if resp.Done {
				close(ch)
			}
		}
	}

	if err := w.scanner.Err(); err != nil {
		w.err = err
	} else {
		w.err = errors.New("python worker stopped")
	}

	w.pendingMu.Lock()
	for id, ch := range w.pending {
		delete(w.pending, id)
		ch <- Response{
			ID:    id,
			OK:    false,
			Error: w.err.Error(),
			Done:  true,
		}
		close(ch)
	}
	w.pendingMu.Unlock()
}

func (w *Worker) Call(ctx context.Context, action string, input any) (Response, error) {
	ch, err := w.call(ctx, action, input, 1)
	if err != nil {
		return Response{}, err
	}

	for {
		select {
		case resp, ok := <-ch:
			if !ok {
				return Response{}, errors.New("python worker stopped")
			}
			if !resp.OK {
				return resp, errors.New(resp.Error)
			}
			if resp.Done {
				return resp, nil
			}
		case <-ctx.Done():
			return Response{}, ctx.Err()
		case <-w.done:
			return Response{}, errors.New("python worker stopped")
		}
	}
}

func (w *Worker) Stream(ctx context.Context, action string, input any) (<-chan Response, error) {
	return w.call(ctx, action, input, 32)
}

func (w *Worker) call(ctx context.Context, action string, input any, buffer int) (chan Response, error) {
	id := strconv.FormatUint(w.nextID.Add(1), 10)

	ch := make(chan Response, buffer)

	w.pendingMu.Lock()
	w.pending[id] = ch
	w.pendingMu.Unlock()

	req := Request{
		ID:     id,
		Action: action,
		Input:  input,
	}

	data, err := json.Marshal(req)
	if err != nil {
		w.removePending(id)
		return nil, err
	}

	w.writeMu.Lock()
	_, err = fmt.Fprintln(w.stdin, string(data))
	w.writeMu.Unlock()

	if err != nil {
		w.removePending(id)
		return nil, err
	}

	select {
	case <-ctx.Done():
		w.removePending(id)
		return nil, ctx.Err()
	default:
		return ch, nil
	}
}

func decodeWorkerResult[T any](resp Response, out *T) error {
	if len(resp.Result) == 0 || string(resp.Result) == "null" {
		return nil
	}
	return json.Unmarshal(resp.Result, out)
}

func (w *Worker) removePending(id string) {
	w.pendingMu.Lock()
	delete(w.pending, id)
	w.pendingMu.Unlock()
}

func (w *Worker) Close() error {
	_ = w.stdin.Close()

	if w.cmd.Process != nil {
		_ = w.cmd.Process.Kill()
	}

	<-w.done
	return nil
}
