package tui

import tea "github.com/charmbracelet/bubbletea"

type screen int

const (
	setupScreen screen = iota
	chatScreen
)

type model struct {
	active     screen
	setup      setupModel
	chat       chatModel
	width      int
	height     int
	userid     string
	hasProfile bool
}

func NewModel(userid string, hasProfile bool) model {
	setup := newSetupModel(userid)
	chat := newChatModel(userid)
	var active screen
	if hasProfile {
		active = chatScreen
	} else {
		active = setupScreen
	}
	return model{
		active:     active,
		setup:      setup,
		chat:       chat,
		userid:     userid,
		hasProfile: hasProfile,
	}
}

func (m model) Init() tea.Cmd {
	return m.setup.Init()
}

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	if wsm, ok := msg.(tea.WindowSizeMsg); ok {
		m.width = wsm.Width
		m.height = wsm.Height
		switch m.active {
		case setupScreen:
			m.setup.SetSize(wsm.Width, wsm.Height)
		case chatScreen:
			m.chat.SetSize(wsm.Width, wsm.Height)
		}
		return m, nil
	}

	if key, ok := msg.(tea.KeyMsg); ok && key.String() == "ctrl+c" {
		return m, tea.Quit
	}

	switch m.active {
	case setupScreen:
		return m.updateSetup(msg)
	case chatScreen:
		return m.updateChat(msg)
	default:
		return m, nil
	}
}

func (m model) updateSetup(msg tea.Msg) (tea.Model, tea.Cmd) {
	updated, cmd := m.setup.Update(msg)
	m.setup = updated

	if m.setup.submitted {
		// Move into chat after profile is saved.
		chat := newChatModel(m.userid)
		chat.SetSize(m.width, m.height)
		m.chat = chat
		m.setup = newSetupModel(m.userid)
		m.setup.SetSize(m.width, m.height)
		m.active = chatScreen
		return m, chat.Init()
	}

	return m, cmd
}

func (m model) updateChat(msg tea.Msg) (tea.Model, tea.Cmd) {
	updated, cmd := m.chat.Update(msg)
	m.chat = updated

	if m.chat.logout {
		setup := newSetupModel(m.userid)
		setup.SetSize(m.width, m.height)
		m.setup = setup
		m.chat = newChatModel("")
		m.active = setupScreen
		return m, setup.Init()
	}

	return m, cmd
}

func (m model) View() string {
	var body string
	switch m.active {
	case setupScreen:
		body = m.setup.View()
	case chatScreen:
		body = m.chat.View()
	default:
		body = "Unknown screen"
	}

	return body
}
