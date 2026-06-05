package main

import (
	"fmt"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
)

type chatModel struct {
	username string
	input    string
	messages []string
	logout   bool
}

func newChatModel(username string) chatModel {
	return chatModel{
		username: username,
		messages: []string{
			"System: welcome to the chat screen.",
			"System: type a message and press enter.",
		},
	}
}

func (m chatModel) Update(msg tea.Msg) (chatModel, tea.Cmd) {
	key, ok := msg.(tea.KeyMsg)
	if !ok {
		return m, nil
	}

	switch key.String() {
	case "enter":
		text := strings.TrimSpace(m.input)
		if text != "" {
			m.messages = append(m.messages, fmt.Sprintf("%s: %s", m.username, text))
			m.input = ""
		}
	case "backspace":
		if len(m.input) > 0 {
			m.input = m.input[:len(m.input)-1]
		}
	case "esc":
		m.logout = true
	default:
		m.input += keyInput(key)
	}

	return m, nil
}

func (m chatModel) View() string {
	input := m.input
	if input == "" {
		input = "_"
	} else {
		input += "_"
	}

	lines := []string{
		"Chat",
		"Logged in as " + m.username,
		"",
	}
	lines = append(lines, m.messages...)
	lines = append(lines,
		"",
		"> "+input,
		"",
		"Press enter to send. Press esc to log out. Press ctrl+c to quit.",
	)

	return strings.Join(lines, "\n")
}
