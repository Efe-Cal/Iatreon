package tui

import (
	"encoding/json"
	"strings"
	"testing"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

func TestDashboardHistoryOpensHistoryScreen(t *testing.T) {
	m := NewModel("ff6b65d2-bee0-4565-ad42-0d7ccb1f41a9", true)
	m.dashboard.cursor = 2

	updated, cmd := m.Update(testKey("enter"))
	got, ok := updated.(model)
	if !ok {
		t.Fatalf("updated model has type %T", updated)
	}
	if got.active != historyScreen {
		t.Fatalf("history card should open history screen, active=%v", got.active)
	}
	if cmd == nil {
		t.Fatal("history screen should start loading")
	}
}

func TestHistoryModelSelectionDiagnosisAndFullscreen(t *testing.T) {
	m := newHistoryModel("user-1", nil)
	m.loading = false
	m.sessions = []historySession{{
		ID: "12345678-1234-1234-1234-123456789012",
		Sections: []historySection{
			{Type: "intake", Title: "Intake", Content: json.RawMessage(`"## Intake\n\nSummary"`)},
			{Type: "diagnosis", Title: "Diagnosis", Content: json.RawMessage(`{"primary_diagnosis":"Migraine","confidence":"moderate","reasoning_summary":"Pattern fits."}`)},
		},
	}}
	m.SetSize(100, 24)

	if !strings.Contains(m.View(), "Intake") {
		t.Fatal("history view should include section names")
	}

	m.focus = historyFocusSections
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyDown})
	if m.sectionCursor != 1 {
		t.Fatalf("down should select diagnosis section, got %d", m.sectionCursor)
	}
	m.focus = historyFocusContent
	m.refreshContent()
	if !strings.Contains(m.content.View(), "Migraine") {
		t.Fatalf("diagnosis content should render through formatter:\n%s", m.content.View())
	}

	m, _ = m.Update(testKey("f"))
	if !m.fullscreen {
		t.Fatal("f should enable fullscreen")
	}
	if got := renderedWidth(m.View()); got != 100 {
		t.Fatalf("fullscreen width=%d, want 100", got)
	}
	if got := lipgloss.Height(m.View()); got != 24 {
		t.Fatalf("fullscreen height=%d, want 24", got)
	}
}

func TestHistoryEnterRequestsSelectedSessionResume(t *testing.T) {
	m := newHistoryModel("user-1", nil)
	m.loading = false
	m.sessions = []historySession{{ID: "session-1"}}

	if !strings.Contains(strings.Join(m.footer(), " "), "Enter Resume") {
		t.Fatal("sessions footer should advertise resume")
	}

	updated, cmd := m.Update(testKey("enter"))
	if !updated.resuming || cmd == nil {
		t.Fatal("enter on a session should start an asynchronous resume")
	}

	m.focus = historyFocusSections
	m.resuming = false
	updated, cmd = m.Update(testKey("enter"))
	if updated.resuming || cmd != nil {
		t.Fatal("enter outside the sessions panel should not resume")
	}
}

func TestHistoryResumeOpensExistingChat(t *testing.T) {
	m := newModel("user-1", true, true, true, nil)
	m.active = historyScreen
	m.history = newHistoryModel("user-1", nil)

	updated, _ := m.Update(historyResumedMsg{resume: historyResume{
		SessionID:      "session-1",
		ConversationID: "conversation-1",
		Agent:          "diagnosis",
		Messages: []resumedMessage{
			{Role: "user", Text: "My head hurts"},
			{Role: "ai", Text: "Tell me more"},
		},
	}})
	got := updated.(model)

	if got.active != chatScreen {
		t.Fatalf("resume should open chat, active=%v", got.active)
	}
	if got.chat.sessionID != "session-1" || got.chat.conversationID != "conversation-1" {
		t.Fatalf("resume lost session IDs: session=%q conversation=%q", got.chat.sessionID, got.chat.conversationID)
	}
	if got.chat.agent.Kind() != AgentDiagnosis || !got.chat.invokeAgentWithEnter {
		t.Fatal("diagnosis should resume at its existing continuation prompt")
	}
	if len(got.chat.history) != 3 || got.chat.history[0].text != "My head hurts" || got.chat.history[1].text != "Tell me more" {
		t.Fatalf("restored chat history is incomplete: %#v", got.chat.history)
	}
}
