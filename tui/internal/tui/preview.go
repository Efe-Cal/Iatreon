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
	frame float64
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
		return m, tick()
	case tea.KeyMsg:
		return m, tea.Quit
	}

	return m, nil
}

func (m Pmodel) View() string {
	offset := getPhaseOffset2("ff6b65d2-bee0-4565-ad42-0d7ccb1f41a9")
	offset2 := getPhaseOffset2("asfasfasf-bee0-4565-ad42-sdaasdasdasd")

	return fmt.Sprintf("Offset 1: %.2f\nOffset 2: %.2f\n", offset, offset2) + m.shimmer("Loading response from assistant...", offset) + "\n" + m.shimmer("Loading response...", offset2) + "\n\npress any key to quit\n"
}

func getPhaseOffset2(toolID string) float64 {
	if toolID == "" {
		return 0
	}
	var sum int
	for _, r := range toolID {
		sum += int(r)
	}
	return float64(sum%100) / 5.0
}

func (m *Pmodel) shimmer(text string, offset float64) string {
	runes := []rune(text)

	var builder strings.Builder

	cycleFrames := 80.0 + offset
	activeFrames := 0.65 * cycleFrames //65.0
	bandWidth := 5.0

	cyclePos := math.Mod(m.frame, cycleFrames)

	if cyclePos > activeFrames {
		style := lipgloss.NewStyle().
			Foreground(lipgloss.Color("#787878"))

		return style.Render(text)
	}

	progress := cyclePos / activeFrames

	center := -bandWidth + progress*(float64(len(runes))+bandWidth*2)

	for i, r := range runes {
		dist := math.Abs(float64(i) - center)

		intensity := 0.0

		if dist < bandWidth {
			x := 1.0 - dist/bandWidth
			intensity = math.Sin(x * math.Pi / 2)
		}

		brightness := int(120 + 120*intensity)

		hexColor := fmt.Sprintf("#%02x%02x%02x", brightness, brightness, brightness)
		style := lipgloss.NewStyle().Foreground(lipgloss.Color(hexColor))

		builder.WriteString(style.Render(string(r)))
	}

	return builder.String()
}

func NewPreviewModel() Pmodel {
	return Pmodel{}
}

func main() {
	p := tea.NewProgram(NewPreviewModel())
	if _, err := p.Run(); err != nil {
		panic(err)
	}
}
