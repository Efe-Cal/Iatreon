package tui

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestFormatDiagnosisReport(t *testing.T) {
	raw := json.RawMessage(`{
		"primary_diagnosis": "Migraine",
		"confidence": "moderate",
		"differential": [{
			"condition": "Tension headache",
			"likelihood": "possible",
			"supporting_evidence": ["head pain"],
			"against_evidence": ["photophobia"]
		}],
		"reasoning_summary": "Pattern fits a primary headache syndrome.",
		"recommended_next_steps": ["Follow up with a clinician"],
		"red_flags_to_monitor": ["Worst headache of life"]
	}`)

	got := formatDiagnosisReport(raw)
	for _, want := range []string{"Migraine", "Tension headache", "Follow up with a clinician", "Worst headache of life"} {
		if !strings.Contains(got, want) {
			t.Fatalf("formatted report missing %q:\n%s", want, got)
		}
	}
}

func TestHandleCommonAgentEventError(t *testing.T) {
	msg, ok := handleCommonAgentEvent(sseEvent{Type: "error", Content: "provider unavailable", Recoverable: true})
	if !ok {
		t.Fatal("error event should be handled")
	}
	if msg.err == nil || !strings.Contains(msg.err.Error(), "provider unavailable") {
		t.Fatalf("unexpected error message: %v", msg.err)
	}
	if !msg.recoverable {
		t.Fatal("recoverable error event should stay recoverable")
	}
}

func TestRecoverableChatErrorEnablesRetry(t *testing.T) {
	m := newChatModelForAgent(AgentIntake, "user-1", "session-1", nil)
	m.retryMessage = "hello"
	m.isStreaming = true

	updated, _ := m.Update(chunkMsg{err: errTest("provider unavailable"), recoverable: true})
	if !updated.retryWithEnter {
		t.Fatal("recoverable error should enable enter-to-retry")
	}
	if updated.isStreaming {
		t.Fatal("recoverable error should stop the current stream")
	}

	updated, cmd := updated.Update(testKey("enter"))
	if updated.retryWithEnter {
		t.Fatal("enter should consume retry state")
	}
	if !updated.isStreaming {
		t.Fatal("retry should start streaming again")
	}
	if cmd == nil {
		t.Fatal("retry should return a stream command")
	}
}

type errTest string

func (e errTest) Error() string { return string(e) }
