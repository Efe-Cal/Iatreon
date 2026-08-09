package tui

import (
	"strings"
	"testing"
	"time"

	"github.com/charmbracelet/bubbles/spinner"
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
