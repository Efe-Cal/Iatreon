package tui

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"strings"
	"sync"
	"testing"
	"time"
)

type lockedWriteCloser struct {
	mu  sync.Mutex
	buf bytes.Buffer
}

func (w *lockedWriteCloser) Write(p []byte) (int, error) {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.buf.Write(p)
}

func (*lockedWriteCloser) Close() error { return nil }

func (w *lockedWriteCloser) lines() []Request {
	w.mu.Lock()
	defer w.mu.Unlock()
	var requests []Request
	for _, line := range bytes.Split(bytes.TrimSpace(w.buf.Bytes()), []byte{'\n'}) {
		var request Request
		if err := json.Unmarshal(line, &request); err == nil {
			requests = append(requests, request)
		}
	}
	return requests
}

func TestWorkerContextCancellationSendsControlRequest(t *testing.T) {
	stdin := &lockedWriteCloser{}
	w := &Worker{
		stdin:   stdin,
		pending: make(map[string]*pendingRequest),
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	if _, err := w.Stream(ctx, "chat/intake", map[string]string{}); err != nil {
		t.Fatal(err)
	}
	cancel()

	deadline := time.Now().Add(time.Second)
	for time.Now().Before(deadline) {
		requests := stdin.lines()
		if len(requests) == 2 {
			if requests[1].Action != "worker/cancel" {
				t.Fatalf("second request action = %q", requests[1].Action)
			}
			input, ok := requests[1].Input.(map[string]any)
			if !ok || input["request_id"] != requests[0].ID {
				t.Fatalf("cancelled %#v, want %q", input, requests[0].ID)
			}
			return
		}
		time.Sleep(time.Millisecond)
	}
	t.Fatalf("expected normal and cancel requests, got %#v", stdin.lines())
}

func TestWorkerReaderDoesNotBlockOnCancelledFullStream(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	responses := make(chan Response, 1)
	responses <- Response{ID: "old"}
	w := &Worker{
		scanner: bufio.NewScanner(strings.NewReader(`{"id":"1","ok":false,"error_code":"cancelled","done":true}` + "\n")),
		pending: map[string]*pendingRequest{
			"1": {ctx: ctx, cancel: cancel, ch: responses},
		},
		done: make(chan struct{}),
	}
	cancel()

	go w.readLoop()
	select {
	case <-w.done:
	case <-time.After(time.Second):
		t.Fatal("worker reader blocked delivering to a cancelled full stream")
	}
}

func TestEscCancelsActiveStreamAndIgnoresItsLateResponse(t *testing.T) {
	m := newChatModelForAgent(AgentIntake, "user-1", "session-1", nil)
	cancelled := false
	m.isStreaming = true
	m.streamGeneration = 1
	m.streamCancel = func() { cancelled = true }

	updated, _ := m.Update(testKey("esc"))
	if !cancelled || updated.isStreaming {
		t.Fatalf("Esc did not cancel stream: cancelled=%v streaming=%v", cancelled, updated.isStreaming)
	}
	before := len(updated.history)
	updated, _ = updated.Update(chunkMsg{streamID: 1, content: "late"})
	if len(updated.history) != before {
		t.Fatal("late stream response changed chat history")
	}
}
