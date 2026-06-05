package main

import (
	"strings"

	tea "github.com/charmbracelet/bubbletea"
)

func keyInput(key tea.KeyMsg) string {
	switch key.Type {
	case tea.KeyRunes:
		return string(key.Runes)
	case tea.KeySpace:
		return " "
	default:
		return ""
	}
}

func renderFrame(body string, width int) string {
	if width <= 0 {
		width = 80
	}

	title := " Iatreon "
	border := strings.Repeat("-", max(0, width-2))
	if len(title) < len(border) {
		border = title + border[len(title):]
	}

	return "\n" + border + "\n\n" + body + "\n"
}
