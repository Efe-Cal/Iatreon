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
	reportScreen
)

type model struct {
	active     screen
	hasProfile bool
	dashboard  dashboardModel
	setup      setupModel
	chat       chatModel
	report     reportModel
	width      int
	height     int
	userid     string
	sessionKey *SessionKey
}

const headerFooterHeight = 3

var (
	dashboardFooter = []string{"↑/↓/←/→ Navigate", "Enter Select", "Esc Setup", "Ctrl+C Quit"}
	setupFooter     = []string{"Enter Continue", "Esc Back", "Ctrl+C Quit"}
)

func NewModel(userid string, hasProfile bool, sessionKey ...*SessionKey) model {
	var key *SessionKey
	if len(sessionKey) > 0 {
		key = sessionKey[0]
	}
	dash := newDashboardModel(userid)
	setup := newSetupModel(userid, key, hasProfile)

	var active screen
	if hasProfile {
		active = dashboardScreen
	} else {
		active = setupScreen
	}

	m := model{
		active:     active,
		hasProfile: hasProfile,
		dashboard:  dash,
		setup:      setup,
		userid:     userid,
		sessionKey: key,
	}

	return m
}

func (m model) Init() tea.Cmd {
	if m.active == setupScreen {
		return m.setup.Init()
	}
	return nil
}

func (m *model) wipeSessionKey() {
	m.sessionKey.Wipe()
}

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	if wsm, ok := msg.(tea.WindowSizeMsg); ok {
		chromeH := headerFooterHeight
		m.width = wsm.Width
		m.height = wsm.Height
		m.dashboard.SetSize(wsm.Width, wsm.Height-chromeH)
		m.setup.SetSize(wsm.Width, wsm.Height-chromeH)
		m.chat.SetSize(wsm.Width, wsm.Height-chromeH)
		m.report.SetSize(wsm.Width, wsm.Height-chromeH)
		return m, nil
	}

	if key, ok := msg.(tea.KeyMsg); ok && key.String() == "ctrl+c" {
		m.wipeSessionKey()
		return m, tea.Quit
	}

	switch m.active {
	case dashboardScreen:
		return m.updateDashboard(msg)
	case setupScreen:
		return m.updateSetup(msg)
	case chatScreen:
		return m.updateChat(msg)
	case reportScreen:
		return m.updateReport(msg)
	default:
		return m, nil
	}
}

func (m *model) initChat(cm chatModel) chatModel {
	cm.SetSize(m.width, m.height-headerFooterHeight)
	return cm
}

func (m *model) initDashboard(dm dashboardModel) dashboardModel {
	dm.SetSize(m.width, m.height-headerFooterHeight)
	return dm
}

func (m *model) initSetup(sm setupModel) setupModel {
	sm.SetSize(m.width, m.height-headerFooterHeight)
	return sm
}

func (m *model) initReport(rm reportModel) reportModel {
	rm.SetSize(m.width, m.height-headerFooterHeight)
	return rm
}

func (m model) updateDashboard(msg tea.Msg) (tea.Model, tea.Cmd) {
	updated, cmd := m.dashboard.Update(msg)
	m.dashboard = updated

	switch m.dashboard.action {
	case dashboardActionStartIntake:
		m.chat = m.initChat(newChatModelForAgent(AgentIntake, m.userid, "", m.sessionKey))
		m.dashboard = m.initDashboard(newDashboardModel(m.userid))
		m.active = chatScreen
		return m, m.chat.Init()
	case dashboardActionStartDoctor:
		m.chat = m.initChat(newChatModelForAgent(AgentDoctor, m.userid, "", m.sessionKey))
		m.dashboard = m.initDashboard(newDashboardModel(m.userid))
		m.active = chatScreen
		return m, m.chat.Init()
	case dashboardActionSetup:
		m.setup = m.initSetup(newSetupModel(m.userid, m.sessionKey, true))
		m.dashboard = m.initDashboard(newDashboardModel(m.userid))
		m.active = setupScreen
		return m, m.setup.Init()
	}

	return m, cmd
}

func (m model) updateSetup(msg tea.Msg) (tea.Model, tea.Cmd) {
	updated, cmd := m.setup.Update(msg)
	m.setup = updated

	if m.setup.cancelled {
		m.setup = m.initSetup(newSetupModel(m.userid, m.sessionKey, m.hasProfile))
		if m.hasProfile {
			m.dashboard = m.initDashboard(newDashboardModel(m.userid))
			m.active = dashboardScreen
		}
		return m, nil
	}

	if m.setup.submitted {
		m.hasProfile = true
		m.dashboard = m.initDashboard(newDashboardModel(m.userid))
		m.setup = m.initSetup(newSetupModel(m.userid, m.sessionKey, true))
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
		kind := AgentIntake
		if m.chat.agent != nil {
			kind = m.chat.agent.Kind()
		}
		m.chat = m.initChat(newChatModelForAgent(kind, m.userid, "", m.sessionKey))
		m.active = dashboardScreen
		return m, nil
	}

	if m.chat.reportReady {
		m.report = m.initReport(newReportModel(m.chat.report, m.chat.citations, m.chat.researchSessionID, m.userid, m.sessionKey))
		m.chat.reportReady = false
		m.active = reportScreen
		return m, m.report.Init()
	}

	return m, cmd
}

func (m model) updateReport(msg tea.Msg) (tea.Model, tea.Cmd) {
	updated, cmd := m.report.Update(msg)
	if report, ok := updated.(reportModel); ok {
		m.report = report
	}

	if m.report.close {
		m.chat.agent = newAgentHandler(AgentDiagnosis)
		m.chat.invokeAgentWithEnter = true
		m.chat.UpdateFooter("Enter Start Diagnosis agent", 0)
		m.report = m.initReport(newReportModel("", nil, "", m.userid, m.sessionKey))
		m.active = chatScreen
		return m, nil
	}

	return m, cmd
}

func (m model) View() string {
	headerText, footerActions := m.chrome()
	header := renderHeader(headerText, m.width)
	footer := renderFooter(footerActions, m.width)

	var body string
	switch m.active {
	case dashboardScreen:
		body = m.dashboard.View()
	case setupScreen:
		body = m.setup.View()
	case chatScreen:
		body = m.chat.View()
	case reportScreen:
		body = m.report.View()
	default:
		body = "Unknown screen"
	}

	return lipgloss.JoinVertical(lipgloss.Left,
		header,
		body,
		footer,
	)
}

func (m model) chrome() (string, []string) {
	switch m.active {
	case setupScreen:
		return "Iatreon - Profile Setup", m.setup.footer()
	case chatScreen:
		if m.chat.agent == nil {
			return "", nil
		}
		return m.chat.agent.Header(), m.chat.footerActions
	case reportScreen:
		return "Iatreon - Research Report", []string{"↑/↓ Scroll", "c Citations", "Tab Focus", "j/k Citation", "Esc Continue", "Ctrl+C Quit"}
	default:
		return "Iatreon - Dashboard", m.dashboard.footer()
	}
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
		action := strings.Split(a, " ")
		key := action[0]
		desc := strings.Join(action[1:], " ")
		styledKey := hintStyle.Copy().Bold(true).Render(key)
		styledDesc := hintStyle.Render(desc)
		styled = append(styled, lipgloss.JoinHorizontal(lipgloss.Left, styledKey, styledDesc))
	}
	return lipgloss.NewStyle().
		Width(width).
		Padding(0, 1).
		Align(lipgloss.Center).
		Render(strings.Join(styled, "  ·  "))
}
