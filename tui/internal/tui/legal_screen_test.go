package tui

import (
	"strings"
	"testing"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

func TestLegalScreenNavigationAndSizing(t *testing.T) {
	m := newLegalModel()
	m.SetSize(80, 20)

	if view := m.View(); !strings.Contains(view, "Terms of Service") {
		t.Fatal("legal screen should open on the terms")
	}
	m, _ = m.Update(testKey("right"))
	if m.document != 1 || !strings.Contains(m.View(), "Privacy Policy") {
		t.Fatal("right should open the privacy policy")
	}
	m, _ = m.Update(testKey("left"))
	if m.document != 0 {
		t.Fatal("left should open the previous document")
	}
	m, _ = m.Update(testKey("esc"))
	if !m.close {
		t.Fatal("esc should close the legal screen")
	}

	for _, size := range []struct{ width, height int }{{80, 20}, {120, 36}} {
		m.SetSize(size.width, size.height)
		view := m.View()
		if lipgloss.Width(view) > size.width || lipgloss.Height(view) > size.height {
			t.Fatalf("legal view exceeds %dx%d", size.width, size.height)
		}
	}
}

func TestSettingsOpensLegalScreenAndReturns(t *testing.T) {
	m := newModel(settingsTestUserID, true, true, true, nil)
	m.active = settingsScreen
	m.settings = readySettingsModel()
	m.settings.categoryCursor = int(settingsLegal)
	m.settings.focus = settingsContentFocus

	updated, _ := m.Update(testKey("enter"))
	m = updated.(model)
	if m.active != legalScreen {
		t.Fatalf("legal settings action should open legal screen, active=%v", m.active)
	}
	updated, _ = m.Update(tea.WindowSizeMsg{Width: 80, Height: 24})
	m = updated.(model)
	if view := m.View(); lipgloss.Width(view) > 80 || lipgloss.Height(view) > 24 {
		t.Fatal("legal screen should fit inside 80x24 application chrome")
	}

	updated, _ = m.Update(testKey("esc"))
	m = updated.(model)
	if m.active != settingsScreen || settingsCategory(m.settings.categoryCursor) != settingsLegal {
		t.Fatalf("esc should return to legal settings, active=%v category=%v", m.active, settingsCategory(m.settings.categoryCursor))
	}
}
