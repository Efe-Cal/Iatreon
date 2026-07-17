package tui

import (
	"testing"

	"github.com/charmbracelet/lipgloss"
)

func TestDashboardSettingsNavigation(t *testing.T) {
	m := NewModel("user-1", true)
	m.dashboard.cursor = 3

	updated, _ := m.Update(testKey("enter"))
	m = updated.(model)
	if m.active != settingsScreen {
		t.Fatalf("settings card should open settings screen, active=%v", m.active)
	}

	updated, _ = m.Update(testKey("esc"))
	m = updated.(model)
	if m.active != dashboardScreen {
		t.Fatalf("esc should return to dashboard, active=%v", m.active)
	}
}

func TestDashboardDescriptionDoesNotMoveLayout(t *testing.T) {
	m := newDashboardModel("ff6b65d2-bee0-4565-ad42-0d7ccb1f41a9")
	m.SetSize(100, 30)

	first := m.View()
	wantW := lipgloss.Width(first)
	wantH := lipgloss.Height(first)
	wantRow, wantCol := firstRenderedCell(first)

	for i := range dashboardCards {
		m.cursor = i
		view := m.View()
		gotW := lipgloss.Width(view)
		gotH := lipgloss.Height(view)
		gotRow, gotCol := firstRenderedCell(view)

		if gotW != wantW || gotH != wantH {
			t.Fatalf("cursor %d changed dashboard size from %dx%d to %dx%d", i, wantW, wantH, gotW, gotH)
		}
		if gotRow != wantRow || gotCol != wantCol {
			t.Fatalf("cursor %d moved dashboard anchor from %d,%d to %d,%d", i, wantRow, wantCol, gotRow, gotCol)
		}
	}
}
