package main

import (
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

var (
	colorPrimary = lipgloss.Color("#2563EB")
	colorAccent  = lipgloss.Color("#0D9488")
	colorUser    = lipgloss.Color("#2563EB")
	colorAI      = lipgloss.Color("#0D9488")
	colorSystem  = lipgloss.Color("#64748B")
	colorError   = lipgloss.Color("#DC2626")
	colorMuted   = lipgloss.Color("#94A3B8")
	colorBorder  = lipgloss.Color("#CBD5E1")
)

// Shared lipgloss styles for the whole TUI.
var (
	titleStyle = lipgloss.NewStyle().
			Bold(true).
			Foreground(colorPrimary).
			Padding(0, 1).
			Align(lipgloss.Center)

	statusStyle = lipgloss.NewStyle().
			Foreground(colorMuted).
			Italic(true).
			Padding(0, 1)

	hintStyle = lipgloss.NewStyle().
			Foreground(colorMuted).
			Padding(0, 1)

	userLabelStyle = lipgloss.NewStyle().
			Bold(true).
			Foreground(colorUser)

	aiLabelStyle = lipgloss.NewStyle().
			Bold(true).
			Foreground(colorAI)

	systemStyle = lipgloss.NewStyle().
			Foreground(colorSystem).
			Italic(true)

	errorStyle = lipgloss.NewStyle().
			Foreground(colorError).
			Bold(true)

	toolRunningStyle = lipgloss.NewStyle().
				Foreground(colorAccent).
				Italic(true)

	toolDoneStyle = lipgloss.NewStyle().
			Foreground(colorAccent)
)

// keyInput translates a bubbletea key press into a string of printable
// characters. Non-character keys (arrows, function keys, etc.) return "".
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
