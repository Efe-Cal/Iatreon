package tui

import (
	"github.com/charmbracelet/bubbles/textinput"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

type startModel struct {
	input textinput.Model
	ready bool
	err   error
}

func newStartModel() startModel {
	ti := textinput.New()
	ti.Placeholder = "username"
	ti.Focus()
	ti.CharLimit = 32
	ti.Width = 24

	return startModel{input: ti}
}

func (m startModel) Init() tea.Cmd {
	return textinput.Blink
}

// SetSize is called by the parent app when the window resizes so the input
// field can adapt to the available width.
func (m startModel) SetSize(w, h int) startModel {
	width := w/2 - 4
	if width < 8 {
		width = 8
	}
	m.input.Width = width
	return m
}

func (m startModel) Update(msg tea.Msg) (startModel, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.KeyMsg:
		switch msg.String() {
		case "enter":
			value := m.input.Value()
			if value == "" {
				return m, nil
			}
			m.ready = true
			return m, nil
		case "esc":
			m.input.SetValue("")
			return m, nil
		}
	case error:
		m.err = msg
	}
	var cmd tea.Cmd
	m.input, cmd = m.input.Update(msg)
	return m, cmd
}

func (m startModel) View() string {
	title := titleStyle.Render("Iatreon TUI")
	subtitle := systemStyle.Render("Sign in to begin your intake.")

	field := lipgloss.JoinHorizontal(
		lipgloss.Left,
		lipgloss.NewStyle().Bold(true).Render("Username: "),
		m.input.View(),
	)

	hint := hintStyle.Render("Press enter to continue · esc to clear · ctrl+c to quit")

	lines := []string{
		"",
		title,
		"",
		subtitle,
		"",
		"",
		field,
		"",
		"",
		hint,
	}

	if m.err != nil {
		lines = append(lines, "", errorStyle.Render("Error: "+m.err.Error()))
	}

	return lipgloss.JoinVertical(lipgloss.Left, lines...)
}
