package tui

import (
	"strings"
	"testing"
	"time"

	"github.com/charmbracelet/bubbles/spinner"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/muesli/termenv"
)

func TestShimmerAdvancesOnSpinnerTick(t *testing.T) {
	profile := lipgloss.ColorProfile()
	lipgloss.SetColorProfile(termenv.TrueColor)
	t.Cleanup(func() { lipgloss.SetColorProfile(profile) })

	m := newChatModelForAgent(AgentIntake, "user-1", "session-1", nil)
	text := "Tool: search " + strings.Repeat("x", 67)
	before := m.shimmer(text, 0)

	updated, _ := m.Update(spinner.TickMsg{Time: m.shimmerStartedAt.Add(750 * time.Millisecond)})
	after := updated.shimmer(text, 0)

	if before == after {
		t.Fatal("shimmer did not advance after a spinner tick")
	}
}

func TestTypingDoesNotScrollChatViewport(t *testing.T) {
	m := newChatModelForAgent(AgentIntake, "user-1", "session-1", nil)
	m.SetSize(80, 10)
	m.viewport.SetContent(strings.Repeat("line\n", 30))
	m.viewport.GotoBottom()
	wantOffset := m.viewport.YOffset

	updated, _ := m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune("k")})

	if updated.viewport.YOffset != wantOffset {
		t.Fatalf("typing scrolled viewport: got offset %d, want %d", updated.viewport.YOffset, wantOffset)
	}
	if updated.input.Value() != "k" {
		t.Fatalf("typed character was not added to input: got %q", updated.input.Value())
	}
}
