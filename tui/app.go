package main

import tea "github.com/charmbracelet/bubbletea"

type screen int

const (
	startScreen screen = iota
	chatScreen
)

type model struct {
	active screen
	start  startModel
	chat   chatModel
	width  int
	height int
}

func newModel() model {
	return model{
		active: startScreen,
		start:  newStartModel(),
		chat:   newChatModel(""),
	}
}

func (m model) Init() tea.Cmd {
	return nil
}

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		return m, nil
	case tea.KeyMsg:
		if msg.String() == "ctrl+c" {
			return m, tea.Quit
		}
	}

	switch m.active {
	case startScreen:
		return m.updateStart(msg)
	case chatScreen:
		return m.updateChat(msg)
	default:
		return m, nil
	}
}

func (m model) updateStart(msg tea.Msg) (tea.Model, tea.Cmd) {
	start, cmd := m.start.Update(msg)
	m.start = start

	if start.ready {
		m.chat = newChatModel(start.username)
		m.start = newStartModel()
		m.active = chatScreen
	}

	return m, cmd
}

func (m model) updateChat(msg tea.Msg) (tea.Model, tea.Cmd) {
	chat, cmd := m.chat.Update(msg)
	m.chat = chat

	if chat.logout {
		m.chat = newChatModel("")
		m.active = startScreen
	}

	return m, cmd
}

func (m model) View() string {
	var body string
	switch m.active {
	case startScreen:
		body = m.start.View()
	case chatScreen:
		body = m.chat.View()
	default:
		body = "Unknown screen"
	}

	return renderFrame(body, m.width)
}
