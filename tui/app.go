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
	start := newStartModel()
	chat := newChatModel("")
	return model{
		active: startScreen,
		start:  start,
		chat:   chat,
	}
}

func (m model) Init() tea.Cmd {
	return m.start.Init()
}

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	if wsm, ok := msg.(tea.WindowSizeMsg); ok {
		m.width = wsm.Width
		m.height = wsm.Height
		switch m.active {
		case startScreen:
			m.start = m.start.SetSize(wsm.Width, wsm.Height)
		case chatScreen:
			m.chat.SetSize(wsm.Width, wsm.Height)
		}
		return m, nil
	}

	if key, ok := msg.(tea.KeyMsg); ok && key.String() == "ctrl+c" {
		return m, tea.Quit
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
	updated, cmd := m.start.Update(msg)
	m.start = updated

	if m.start.ready {
		// Move into chat with the entered username.
		chat := newChatModel(m.start.username())
		chat.SetSize(m.width, m.height)
		m.chat = chat
		m.start = newStartModel()
		m.start = m.start.SetSize(m.width, m.height)
		m.active = chatScreen
		return m, chat.Init()
	}

	return m, cmd
}

func (m model) updateChat(msg tea.Msg) (tea.Model, tea.Cmd) {
	updated, cmd := m.chat.Update(msg)
	m.chat = updated

	if m.chat.logout {
		start := newStartModel()
		start = start.SetSize(m.width, m.height)
		m.start = start
		m.chat = newChatModel("")
		m.active = startScreen
		return m, start.Init()
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

	return body
}
