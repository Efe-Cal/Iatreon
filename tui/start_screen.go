package main

import (
	"strings"

	tea "github.com/charmbracelet/bubbletea"
)

type startModel struct {
	username string
	ready    bool
}

func newStartModel() startModel {
	return startModel{}
}

func (m startModel) Update(msg tea.Msg) (startModel, tea.Cmd) {
	key, ok := msg.(tea.KeyMsg)
	if !ok {
		return m, nil
	}

	switch key.String() {
	case "enter":
		m.username = strings.TrimSpace(m.username)
		if m.username != "" {
			m.ready = true
		}
	case "backspace":
		if len(m.username) > 0 {
			m.username = m.username[:len(m.username)-1]
		}
	case "esc":
		m.username = ""
	default:
		m.username += keyInput(key)
	}

	return m, nil
}

func (m startModel) View() string {
	name := m.username
	if name == "" {
		name = "_"
	} else {
		name += "_"
	}

	return strings.Join([]string{
		"Iatreon TUI",
		"",
		"Login",
		"",
		"Username: " + name,
		"",
		"Press enter to continue. Press esc to clear. Press ctrl+c to quit.",
	}, "\n")
}
