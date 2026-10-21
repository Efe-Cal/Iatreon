package tui

import (
	"bufio"
	"context"
	"encoding/base64"
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
	"time"
)

type Request struct {
	ID     string `json:"id"`
	Action string `json:"action"`
	Input  any    `json:"input"`
}

type Response struct {
	ID        string          `json:"id"`
	OK        bool            `json:"ok"`
	Event     json.RawMessage `json:"event,omitempty"`
	Result    json.RawMessage `json:"result,omitempty"`
	Error     string          `json:"error,omitempty"`
	ErrorCode string          `json:"error_code,omitempty"`
	Done      bool            `json:"done,omitempty"`
}

type Worker struct {
	cmd     *exec.Cmd
	stdin   io.WriteCloser
	scanner *bufio.Scanner

	pendingMu sync.Mutex
	writeMu   sync.Mutex
	pending   map[string]*pendingRequest

	nextID atomic.Uint64
	done   chan struct{}
	err    error

	closeOnce sync.Once
	closeErr  error
}

type pendingRequest struct {
	ctx        context.Context
	cancel     context.CancelFunc
	cancelSent bool
	ch         chan Response
}

type workerInitInput struct {
	DBPath string `json:"db_path"`
	DBKey  string `json:"db_key"`
}

type profileStatusInput struct {
	UserID string `json:"user_id"`
}

type profileStatusResult struct {
	HasProfile bool `json:"has_profile"`
}

type providerStatusInput struct {
	UserID string `json:"user_id"`
}

type providerStatusResult struct {
	HasProviderSetup bool `json:"has_provider_setup"`
}

type backendSessionInput struct {
	UserID string `json:"user_id"`
}

type backendSession struct {
	Username     string `json:"username"`
	AccessToken  string `json:"access_token"`
	RefreshToken string `json:"refresh_token"`
}

type backendSessionUpdateInput struct {
	UserID       string `json:"user_id"`
	Username     string `json:"username"`
	AccessToken  string `json:"access_token"`
	RefreshToken string `json:"refresh_token"`
}

type providerSetupInput struct {
	UserID         string            `json:"user_id"`
	LLMProvider    string            `json:"llm_provider"`
	LLMAPIKey      string            `json:"llm_api_key"`
	LLMBaseURL     string            `json:"llm_base_url"`
	SearchProvider string            `json:"search_provider"`
	SearchAPIKey   string            `json:"search_api_key"`
	SearchBaseURL  string            `json:"search_base_url"`
	AgentModels    map[string]string `json:"agent_models"`
}

type providerModelsInput struct {
	UserID      string `json:"user_id"`
	LLMProvider string `json:"llm_provider"`
	LLMAPIKey   string `json:"llm_api_key"`
	LLMBaseURL  string `json:"llm_base_url"`
}

type providerModelsResult struct {
	Models     []string          `json:"models"`
	Defaults   map[string]string `json:"defaults"`
	FetchError string            `json:"fetch_error"`
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

	workerPath := filepath.Join(dir, "python-worker", name)

	cmd := exec.Command(workerPath)
	cmd.Env = append(os.Environ(), "IATREON_LOCAL_WORKER=1")
	return cmd, nil
}

func StartPythonWorker() (*Worker, error) {
	cmd, err := workerCommand()
	if err != nil {
		return nil, err
	}

	stdin, err := cmd.StdinPipe()
	if err != nil {
		return nil, err
	}

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return nil, err
	}

	cmd.Stderr = io.Discard

	if err := cmd.Start(); err != nil {
		return nil, err
	}

	scanner := bufio.NewScanner(stdout)
	scanner.Buffer(make([]byte, 1024), 10*1024*1024)

	w := &Worker{
		cmd:     cmd,
		stdin:   stdin,
		scanner: scanner,
		pending: make(map[string]*pendingRequest),
		done:    make(chan struct{}),
	}

	go w.readLoop()
	go func() {
		_ = cmd.Wait()
	}()

	key, err := loadOrCreateWorkerKey(osCredentialStore{})
	if err != nil {
		_ = w.Close()
		return nil, err
	}
	defer zeroBytes(key)

	dbPath, err := localWorkerDBPath()
	if err != nil {
		_ = w.Close()
		return nil, err
	}

	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	if _, err := w.Call(ctx, "worker/init", workerInitInput{
		DBPath: dbPath,
		DBKey:  base64.StdEncoding.EncodeToString(key),
	}); err != nil {
		_ = w.Close()
		return nil, err
	}

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
		pending := w.pending[resp.ID]
		if resp.Done {
			delete(w.pending, resp.ID)
		}
		w.pendingMu.Unlock()

		if pending != nil {
			select {
			case pending.ch <- resp:
			case <-pending.ctx.Done():
			}
			if resp.Done {
				close(pending.ch)
				pending.cancel()
			}
		}
	}

	if err := w.scanner.Err(); err != nil {
		w.err = err
	} else {
		w.err = errors.New("python worker stopped")
	}

	w.pendingMu.Lock()
	pending := w.pending
	w.pending = make(map[string]*pendingRequest)
	w.pendingMu.Unlock()
	for id, request := range pending {
		select {
		case request.ch <- Response{
			ID:    id,
			OK:    false,
			Error: w.err.Error(),
			Done:  true,
		}:
		default:
		}
		close(request.ch)
		request.cancel()
	}
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
	if ctx == nil {
		ctx = context.Background()
	}
	requestCtx, cancel := context.WithCancel(ctx)

	ch := make(chan Response, buffer)

	w.pendingMu.Lock()
	w.pending[id] = &pendingRequest{ctx: requestCtx, cancel: cancel, ch: ch}
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

	err = w.write(data)

	if err != nil {
		w.removePending(id)
		return nil, err
	}

	go w.cancelOnContext(id, requestCtx)

	select {
	case <-ctx.Done():
		return ch, nil
	default:
		return ch, nil
	}
}

func (w *Worker) write(data []byte) error {
	w.writeMu.Lock()
	defer w.writeMu.Unlock()
	_, err := fmt.Fprintln(w.stdin, string(data))
	return err
}

func (w *Worker) cancelOnContext(id string, ctx context.Context) {
	<-ctx.Done()
	w.cancelRequest(id)
}

func (w *Worker) cancelRequest(id string) {
	w.pendingMu.Lock()
	pending := w.pending[id]
	if pending == nil || pending.cancelSent {
		w.pendingMu.Unlock()
		return
	}
	pending.cancelSent = true
	w.pendingMu.Unlock()

	data, err := json.Marshal(Request{
		ID:     strconv.FormatUint(w.nextID.Add(1), 10),
		Action: "worker/cancel",
		Input:  map[string]string{"request_id": id},
	})
	if err == nil {
		_ = w.write(data)
	}
}

func decodeWorkerResult[T any](resp Response, out *T) error {
	if len(resp.Result) == 0 || string(resp.Result) == "null" {
		return nil
	}
	return json.Unmarshal(resp.Result, out)
}

func (w *Worker) HasProfile(ctx context.Context, userid string) (bool, error) {
	resp, err := w.Call(ctx, "profile/status", profileStatusInput{UserID: userid})
	if err != nil {
		return false, err
	}

	var result profileStatusResult
	if err := decodeWorkerResult(resp, &result); err != nil {
		return false, err
	}
	return result.HasProfile, nil
}

func (w *Worker) HasProviderSetup(ctx context.Context, userid string) (bool, error) {
	resp, err := w.Call(ctx, "provider/status", providerStatusInput{UserID: userid})
	if err != nil {
		return false, err
	}

	var result providerStatusResult
	if err := decodeWorkerResult(resp, &result); err != nil {
		return false, err
	}
	return result.HasProviderSetup, nil
}

func (w *Worker) UpdateProviderSetup(ctx context.Context, input providerSetupInput) error {
	_, err := w.Call(ctx, "provider/update", input)
	return err
}

func (w *Worker) ProviderModels(ctx context.Context, input providerModelsInput) (providerModelsResult, error) {
	resp, err := w.Call(ctx, "provider/models", input)
	if err != nil {
		return providerModelsResult{}, err
	}
	var result providerModelsResult
	err = decodeWorkerResult(resp, &result)
	return result, err
}

func (w *Worker) LoadSettings(ctx context.Context, userid string) (settingsData, error) {
	resp, err := w.Call(ctx, "settings/get", struct {
		UserID string `json:"user_id"`
	}{UserID: userid})
	if err != nil {
		return settingsData{}, err
	}
	var result settingsData
	err = decodeWorkerResult(resp, &result)
	return result, err
}

func (w *Worker) BackupData(ctx context.Context, userid string) (Response, error) {
	if w == nil {
		return Response{}, errors.New("encrypted local storage is unavailable")
	}

	sourcePath, err := localWorkerDBPath()
	if err != nil {
		return Response{}, err
	}
	key, err := loadOrCreateWorkerKey(osCredentialStore{})
	if err != nil {
		return Response{}, err
	}
	defer zeroBytes(key)

	temporary, err := os.CreateTemp("", "iatreon-backup-*.sqlite3")
	if err != nil {
		return Response{}, err
	}
	backupPath := temporary.Name()
	if err := temporary.Close(); err != nil {
		_ = os.Remove(backupPath)
		return Response{}, err
	}
	_ = os.Remove(backupPath)
	defer os.Remove(backupPath)

	return w.Call(ctx, "data/backup", struct {
		UserID     string `json:"user_id"`
		SourcePath string `json:"source_path"`
		BackupPath string `json:"backup_path"`
		DBKey      string `json:"db_key"`
	}{
		UserID:     userid,
		SourcePath: sourcePath,
		BackupPath: backupPath,
		DBKey:      base64.StdEncoding.EncodeToString(key),
	})
}

func (w *Worker) ListBackups(ctx context.Context, userid string) ([]backupMetadata, Response, error) {
	if w == nil {
		return nil, Response{}, errors.New("encrypted local storage is unavailable")
	}
	resp, err := w.Call(ctx, "data/backup/list", struct {
		UserID string `json:"user_id"`
	}{UserID: userid})
	if err != nil {
		return nil, resp, err
	}
	var backups []backupMetadata
	if err := decodeWorkerResult(resp, &backups); err != nil {
		return nil, resp, err
	}
	return backups, resp, nil
}

func (w *Worker) RestoreBackup(ctx context.Context, userid string, backup backupMetadata) (Response, error) {
	if w == nil {
		return Response{}, errors.New("encrypted local storage is unavailable")
	}
	if backup.ID == "" || backup.Checksum == "" {
		return Response{}, errors.New("backup metadata is incomplete")
	}
	dbPath, err := localWorkerDBPath()
	if err != nil {
		return Response{}, err
	}
	key, err := loadOrCreateWorkerKey(osCredentialStore{})
	if err != nil {
		return Response{}, err
	}
	defer zeroBytes(key)

	return w.Call(ctx, "data/backup/restore", struct {
		UserID   string `json:"user_id"`
		DBPath   string `json:"db_path"`
		BackupID string `json:"backup_id"`
		Checksum string `json:"checksum"`
		DBKey    string `json:"db_key"`
	}{
		UserID:   userid,
		DBPath:   dbPath,
		BackupID: backup.ID,
		Checksum: backup.Checksum,
		DBKey:    base64.StdEncoding.EncodeToString(key),
	})
}

func (w *Worker) BackendSession(ctx context.Context, userid string) (backendSession, error) {
	resp, err := w.Call(ctx, "backend-session/get", backendSessionInput{UserID: userid})
	if err != nil {
		return backendSession{}, err
	}
	var result backendSession
	err = decodeWorkerResult(resp, &result)
	return result, err
}

func (w *Worker) UpdateBackendSession(ctx context.Context, input backendSessionUpdateInput) error {
	_, err := w.Call(ctx, "backend-session/update", input)
	return err
}

func (w *Worker) EnsureBackendSession(ctx context.Context, userid string) (bool, error) {
	resp, err := w.Call(ctx, "backend-session/ensure", backendSessionInput{UserID: userid})
	if err != nil {
		if resp.ErrorCode == "backend_auth_required" {
			return false, nil
		}
		return false, err
	}
	return true, nil
}

func (w *Worker) RunProfilerForChatSession(ctx context.Context, userid string, chatSessionID string) error {
	_, err := w.Call(ctx, "medical-profile/upsert", struct {
		UserID        string `json:"user_id"`
		ChatSessionID string `json:"chat_session_id"`
	}{UserID: userid, ChatSessionID: chatSessionID})
	return err
}

func (w *Worker) removePending(id string) {
	w.pendingMu.Lock()
	pending := w.pending[id]
	delete(w.pending, id)
	w.pendingMu.Unlock()
	if pending != nil {
		pending.cancel()
	}
}

func (w *Worker) Close() error {
	if w == nil {
		return nil
	}
	w.closeOnce.Do(func() {
		w.pendingMu.Lock()
		ids := make([]string, 0, len(w.pending))
		requests := make([]*pendingRequest, 0, len(w.pending))
		for id, pending := range w.pending {
			ids = append(ids, id)
			requests = append(requests, pending)
		}
		w.pendingMu.Unlock()
		for _, pending := range requests {
			pending.cancel()
		}
		for _, id := range ids {
			w.cancelRequest(id)
		}

		if w.stdin != nil {
			_ = w.stdin.Close()
		}
		if w.done != nil {
			select {
			case <-w.done:
				return
			case <-time.After(2 * time.Second):
			}
		}
		if w.cmd != nil && w.cmd.Process != nil {
			w.closeErr = w.cmd.Process.Kill()
		}
	})
	return w.closeErr
}
