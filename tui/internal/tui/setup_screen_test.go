package tui

import (
	"strings"
	"testing"

	tea "github.com/charmbracelet/bubbletea"
)

func testKey(name string) tea.KeyMsg {
	switch name {
	case "enter":
		return tea.KeyMsg{Type: tea.KeyEnter}
	case "esc":
		return tea.KeyMsg{Type: tea.KeyEsc}
	default:
		return tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune(name)}
	}
}

func TestSetupLandingKeys(t *testing.T) {
	m := newSetupModel("ff6b65d2-bee0-4565-ad42-0d7ccb1f41a9", nil, true)

	m, _ = m.Update(testKey("x"))
	if m.step != stepLanding || m.cancelled {
		t.Fatalf("random key should not leave landing: step=%v cancelled=%v", m.step, m.cancelled)
	}

	m, _ = m.Update(testKey("esc"))
	if !m.cancelled {
		t.Fatal("esc should cancel setup when cancellation is enabled")
	}

	m = newSetupModel("ff6b65d2-bee0-4565-ad42-0d7ccb1f41a9", nil, false)
	m, _ = m.Update(testKey("enter"))
	if m.step != stepAge {
		t.Fatalf("enter should start setup at age step, got %v", m.step)
	}
}

func TestSetupReviewRequiresExplicitSubmit(t *testing.T) {
	m := newSetupModel("ff6b65d2-bee0-4565-ad42-0d7ccb1f41a9", nil, false)
	m.step = stepExercise
	m.exercise.SetValue("Daily walking")

	m, cmd := m.Update(testKey("enter"))
	if m.step != stepConfirm {
		t.Fatalf("exercise enter should move to review, got %v", m.step)
	}
	if m.submitting {
		t.Fatal("setup should not submit before the review step is confirmed")
	}
	if cmd == nil {
		t.Fatal("expected blink command after moving to review")
	}

	m, cmd = m.Update(testKey("enter"))
	if !m.submitting {
		t.Fatal("review enter should submit the profile")
	}
	if cmd == nil {
		t.Fatal("expected submit command")
	}
}

func TestSetupViewAnchorDoesNotMove(t *testing.T) {
	m := newSetupModel("ff6b65d2-bee0-4565-ad42-0d7ccb1f41a9", nil, false)
	m.SetSize(100, 30)
	m.step = stepAge

	row, col := firstRenderedCell(m.View())

	m, _ = m.Update(testKey("5"))
	nextRow, nextCol := firstRenderedCell(m.View())
	if nextRow != row || nextCol != col {
		t.Fatalf("typing moved setup anchor from %d,%d to %d,%d", row, col, nextRow, nextCol)
	}

	m, _ = m.Update(testKey("enter"))
	nextRow, nextCol = firstRenderedCell(m.View())
	if nextRow != row || nextCol != col {
		t.Fatalf("next step moved setup anchor from %d,%d to %d,%d", row, col, nextRow, nextCol)
	}
}

func TestDashboardEscStartsSetup(t *testing.T) {
	m := NewModel("ff6b65d2-bee0-4565-ad42-0d7ccb1f41a9", true)

	updated, _ := m.Update(testKey("esc"))
	got, ok := updated.(model)
	if !ok {
		t.Fatalf("updated model has type %T", updated)
	}
	if got.active != setupScreen {
		t.Fatalf("esc should open setup from dashboard, active=%v", got.active)
	}
	if !got.setup.canCancel {
		t.Fatal("dashboard-launched setup should be cancellable")
	}
}

func firstRenderedCell(view string) (int, int) {
	for row, line := range strings.Split(view, "\n") {
		if strings.TrimSpace(line) == "" {
			continue
		}
		return row, len(line) - len(strings.TrimLeft(line, " "))
	}
	return -1, -1
}
