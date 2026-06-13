package shimmer

import (
	"fmt"
	"math"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

// Unique tick message for this widget
type TickMsg struct {
	id int
}

type Model struct {
	id        int
	frame     float64
	speed     float64
	frequency float64
	active    bool
}

func New(text string, speed float64, frequency float64) Model {
	return Model{
		id:        int(time.Now().UnixNano()),
		speed:     speed,
		frequency: frequency,
		active:    true,
	}
}

func (m Model) Init() tea.Cmd {
	return m.tick()
}

func (m Model) tick() tea.Cmd {
	return tea.Tick(time.Millisecond*50, func(time.Time) tea.Msg {
		return TickMsg{id: m.id}
	})
}

func (m Model) Update(msg tea.Msg) (Model, tea.Cmd) {
	if !m.active {
		return m, nil
	}
	switch msg := msg.(type) {
	case TickMsg:
		if msg.id == m.id {
			m.frame += m.speed
			return m, m.tick()
		}
	}
	return m, nil
}

func (m Model) View(text string) string {
	var builder strings.Builder
	for i, r := range text {
		wave := math.Sin(float64(i)*m.frequency - m.frame)
		brightness := int(150 + 105*wave)
		hexColor := fmt.Sprintf("#%02x%02x%02x", brightness, brightness, brightness)

		style := lipgloss.NewStyle().Foreground(lipgloss.Color(hexColor))
		builder.WriteString(style.Render(string(r)))
	}
	return builder.String()
}
