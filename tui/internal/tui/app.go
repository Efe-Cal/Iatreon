package tui

import tea "github.com/charmbracelet/bubbletea"

type screen int

const (
	dashboardScreen screen = iota
	setupScreen
	chatScreen
)

type model struct {
	active    screen
	dashboard dashboardModel
	setup     setupModel
	chat      chatModel
	width     int
	height    int
	userid    string
}

func NewModel(userid string, hasProfile bool) model {
	dash := newDashboardModel(userid)
	setup := newSetupModel(userid)
	chat := newChatModel(userid)

	var active screen
	if hasProfile {
		active = dashboardScreen
	} else {
		active = setupScreen
	}

	return model{
		active:    active,
		dashboard: dash,
		setup:     setup,
		chat:      chat,
		userid:    userid,
	}
}

func (m model) Init() tea.Cmd {
	return m.setup.Init()
}

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	if wsm, ok := msg.(tea.WindowSizeMsg); ok {
		m.width = wsm.Width
		m.height = wsm.Height
		m.dashboard.SetSize(wsm.Width, wsm.Height)
		m.setup.SetSize(wsm.Width, wsm.Height)
		m.chat.SetSize(wsm.Width, wsm.Height)
		return m, nil
	}

	if key, ok := msg.(tea.KeyMsg); ok && key.String() == "ctrl+c" {
		return m, tea.Quit
	}

	switch m.active {
	case dashboardScreen:
		return m.updateDashboard(msg)
	case setupScreen:
		return m.updateSetup(msg)
	case chatScreen:
		return m.updateChat(msg)
	default:
		return m, nil
	}
}

func (m model) updateDashboard(msg tea.Msg) (tea.Model, tea.Cmd) {
	updated, cmd := m.dashboard.Update(msg)
	m.dashboard = updated

	if m.dashboard.startIntake {
		chat := newChatModel(m.userid)
		chat.SetSize(m.width, m.height)
		m.chat = chat
		m.dashboard = newDashboardModel(m.userid)
		m.dashboard.SetSize(m.width, m.height)
		m.active = chatScreen
		return m, chat.Init()
	}

	if m.dashboard.goToSetup {
		setup := newSetupModel(m.userid)
		setup.SetSize(m.width, m.height)
		m.setup = setup
		m.dashboard = newDashboardModel(m.userid)
		m.dashboard.SetSize(m.width, m.height)
		m.active = setupScreen
		return m, setup.Init()
	}

	return m, cmd
}

func (m model) updateSetup(msg tea.Msg) (tea.Model, tea.Cmd) {
	updated, cmd := m.setup.Update(msg)
	m.setup = updated

	if m.setup.submitted {
		dash := newDashboardModel(m.userid)
		dash.SetSize(m.width, m.height)
		m.dashboard = dash
		m.setup = newSetupModel(m.userid)
		m.setup.SetSize(m.width, m.height)
		m.active = dashboardScreen
		return m, nil
	}

	return m, cmd
}

func (m model) updateChat(msg tea.Msg) (tea.Model, tea.Cmd) {
	updated, cmd := m.chat.Update(msg)
	m.chat = updated

	if m.chat.logout {
		dash := newDashboardModel(m.userid)
		dash.SetSize(m.width, m.height)
		m.dashboard = dash
		m.chat = newChatModel("")
		m.active = dashboardScreen
		return m, nil
	}

	return m, cmd
}

func (m model) View() string {
	var body string
	switch m.active {
	case dashboardScreen:
		body = m.dashboard.View()
	case setupScreen:
		body = m.setup.View()
	case chatScreen:
		body = m.chat.View()
	default:
		body = "Unknown screen"
	}

	return body
}
