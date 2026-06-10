package tui

import (
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

type screen int

const (
	dashboardScreen screen = iota
	setupScreen
	chatScreen
)

type screenChrome interface {
	GetHeader() string
	GetFooter() []string
}

type model struct {
	active    screen
	dashboard dashboardModel
	setup     setupModel
	chat      chatModel
	width     int
	height    int
	userid    string
}

const headerFooterHeight = 3

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

	m := model{
		active:    active,
		dashboard: dash,
		setup:     setup,
		chat:      chat,
		userid:    userid,
	}

	m.dashboard.SetHeader("Iatreon - Dashboard")
	m.dashboard.SetFooter([]string{"↑/↓/←/→ Navigate", "Enter Select", "Esc Setup", "Ctrl+C Quit"})
	m.setup.SetHeader("Iatreon - Profile Setup")
	m.setup.SetFooter([]string{"Enter Continue", "Esc Back", "Ctrl+C Quit"})
	m.chat.SetHeader("Iatreon - Chat")
	m.chat.SetFooter([]string{"Enter Send", "Esc Logout", "Ctrl+C Quit"})

	return m
}

func (m model) Init() tea.Cmd {
	return m.setup.Init()
}

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	if wsm, ok := msg.(tea.WindowSizeMsg); ok {
		chromeH := headerFooterHeight
		m.width = wsm.Width
		m.height = wsm.Height
		m.dashboard.SetSize(wsm.Width, wsm.Height-chromeH)
		m.setup.SetSize(wsm.Width, wsm.Height-chromeH)
		m.chat.SetSize(wsm.Width, wsm.Height-chromeH)
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

// initScreen applies chrome (header/footer) and size to a freshly created screen.
func (m *model) initChat(cm chatModel) chatModel {
	cm.SetHeader("Iatreon - Chat")
	cm.SetFooter([]string{"Enter Send", "Esc Logout", "Ctrl+C Quit"})
	cm.SetSize(m.width, m.height-headerFooterHeight)
	return cm
}

func (m *model) initDashboard(dm dashboardModel) dashboardModel {
	dm.SetHeader("Iatreon - Dashboard")
	dm.SetFooter([]string{"↑/↓/←/→ Navigate", "Enter Select", "Esc Setup", "Ctrl+C Quit"})
	dm.SetSize(m.width, m.height-headerFooterHeight)
	return dm
}

func (m *model) initSetup(sm setupModel) setupModel {
	sm.SetHeader("Iatreon - Profile Setup")
	sm.SetFooter([]string{"Enter Continue", "Esc Back", "Ctrl+C Quit"})
	sm.SetSize(m.width, m.height-headerFooterHeight)
	return sm
}

func (m model) updateDashboard(msg tea.Msg) (tea.Model, tea.Cmd) {
	updated, cmd := m.dashboard.Update(msg)
	m.dashboard = updated

	if m.dashboard.startIntake {
		m.chat = m.initChat(newChatModel(m.userid))
		m.dashboard = m.initDashboard(newDashboardModel(m.userid))
		m.active = chatScreen
		return m, m.chat.Init()
	}

	if m.dashboard.goToSetup {
		m.setup = m.initSetup(newSetupModel(m.userid))
		m.dashboard = m.initDashboard(newDashboardModel(m.userid))
		m.active = setupScreen
		return m, m.setup.Init()
	}

	return m, cmd
}

func (m model) updateSetup(msg tea.Msg) (tea.Model, tea.Cmd) {
	updated, cmd := m.setup.Update(msg)
	m.setup = updated

	if m.setup.submitted {
		m.dashboard = m.initDashboard(newDashboardModel(m.userid))
		m.setup = m.initSetup(newSetupModel(m.userid))
		m.active = dashboardScreen
		return m, nil
	}

	return m, cmd
}

func (m model) updateChat(msg tea.Msg) (tea.Model, tea.Cmd) {
	updated, cmd := m.chat.Update(msg)
	m.chat = updated

	if m.chat.logout {
		m.dashboard = m.initDashboard(newDashboardModel(m.userid))
		m.chat = m.initChat(newChatModel(""))
		m.active = dashboardScreen
		return m, nil
	}

	return m, cmd
}

func (m model) View() string {
	var chrome screenChrome
	switch m.active {
	case dashboardScreen:
		chrome = m.dashboard
	case setupScreen:
		chrome = m.setup
	case chatScreen:
		chrome = m.chat
	default:
		chrome = m.dashboard
	}

	header := renderHeader(chrome.GetHeader(), m.width)
	footer := renderFooter(chrome.GetFooter(), m.width)

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

	return lipgloss.JoinVertical(lipgloss.Left,
		header,
		body,
		footer,
	)
}

// renderHeader renders a styled header bar across the full width.
func renderHeader(text string, width int) string {
	sep := lipgloss.NewStyle().
		Foreground(colorBorder).
		Render(strings.Repeat("━", width))
	return lipgloss.JoinVertical(lipgloss.Left,
		titleStyle.Width(width).Render(text),
		sep,
	)
}

// renderFooter renders a hint bar across the full width.
func renderFooter(actions []string, width int) string {
	if len(actions) == 0 {
		return ""
	}
	var styled []string
	for _, a := range actions {
		styled = append(styled, hintStyle.Render(a))
	}
	return lipgloss.NewStyle().
		Width(width).
		Padding(0, 1).
		Align(lipgloss.Center).
		Render(strings.Join(styled, "  ·  "))
}
