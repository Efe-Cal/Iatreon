package tui

import (
	"fmt"
	"math"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

type Pmodel struct {
	frame            float64
	shimmerStartedAt time.Time
	now              time.Time
}

func (m Pmodel) Init() tea.Cmd {
	return tick()
}

func tick() tea.Cmd {
	return tea.Tick(time.Millisecond*60, func(t time.Time) tea.Msg {
		return tickMsg{}
	})
}

type tickMsg struct{}

func (m Pmodel) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg.(type) {
	case tickMsg:
		m.frame += 1
		m.now = time.Now()
		return m, tick()
	case tea.KeyMsg:
		return m, tea.Quit
	}

	return m, nil
}

func (m Pmodel) View() string {
	offset := getPhaseOffset("ff6b65d2-bee0-4565-ad42-0d7ccb1f41a9")
	offset2 := getPhaseOffset("asfasfasf-bee0-4565-ad42-sdaasdasdasd")

	return fmt.Sprintf("Offset 1: %d\nOffset 2: %d\n", offset, offset2) + m.shimmer("Loading response from assistant...Loading response from assistant...", 0.0) + "\n" + m.shimmer("Loading response...", 0.0) + "\n\npress any key to quit\n"
}

// const (
// 	shimmerCycle = 4 * time.Second
// 	shimmerSweep = 1200 * time.Millisecond
// )

func (m *Pmodel) shimmer(text string, delay time.Duration) string {
	runes := []rune(text)
	if len(runes) == 0 {
		return ""
	}

	const (
		baseBrightness = 118.0
		peakBrightness = 250.0

		sigma = 7.0
	)

	baseStyle := lipgloss.NewStyle().
		Foreground(lipgloss.Color("#767676"))

	elapsed := m.now.Sub(m.shimmerStartedAt) - delay
	if elapsed < 0 {
		return baseStyle.Render(text)
	}

	cyclePosition := elapsed % shimmerCycle

	if cyclePosition >= shimmerSweep {
		return baseStyle.Render(text)
	}

	progress := float64(cyclePosition) / float64(shimmerSweep)

	startPosition := -3 * sigma
	endPosition := float64(len(runes)-1) + 3*sigma

	center := startPosition +
		progress*(endPosition-startPosition)

	var builder strings.Builder

	for i, r := range runes {
		distance := (float64(i) - center) / sigma

		intensity := math.Exp(-0.5 * distance * distance)

		brightness := baseBrightness +
			(peakBrightness-baseBrightness)*intensity

		channel := int(math.Round(brightness))
		channel = max(0, min(255, channel))

		color := fmt.Sprintf(
			"#%02x%02x%02x",
			channel,
			channel,
			channel,
		)

		builder.WriteString(
			lipgloss.NewStyle().
				Foreground(lipgloss.Color(color)).
				Render(string(r)),
		)
	}

	return builder.String()
}

func NewPreviewModel() Pmodel {
	now := time.Now()

	return Pmodel{
		shimmerStartedAt: now,
		now:              now,
	}
}

func main() {
	p := tea.NewProgram(NewPreviewModel())
	if _, err := p.Run(); err != nil {
		panic(err)
	}
}
