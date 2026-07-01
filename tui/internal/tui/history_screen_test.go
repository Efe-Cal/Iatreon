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
