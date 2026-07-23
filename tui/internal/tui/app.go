package tui

import (
	"context"
	"log"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

type screen int

const (
	backendAccountScreen screen = iota
	dashboardScreen
	providerSetupScreen
	setupScreen
	chatScreen
	reportScreen
	historyScreen
	settingsScreen
)

type model struct {
	active            screen
	hasBackendSession bool
	hasProfile        bool
	hasProviderSetup  bool
	dashboard         dashboardModel
	providerSetup     providerSetupModel
	backendAccount    backendAccountModel
	setup             setupModel
	chat              chatModel
	report            reportModel
	history           historyModel
	settings          settingsModel
	width             int
	height            int
	userid            string
	worker            *Worker
	backendUsername   string
	reauthPending     bool
	reauthReturn      screen
	returnToSettings  bool
}

var (
	dashboardFooter = []string{"↑/↓/←/→ Navigate", "Enter Select", "Ctrl+C Quit"}
	setupFooter     = []string{"Enter Continue", "Esc Back", "Ctrl+C Quit"}
)

func NewModel(userid string, hasProfile bool) model {

	worker, err := StartPythonWorker()
	if err != nil {
		log.Printf("python worker unavailable: %v", err)
	}
	return newModel(userid, hasProfile, hasProfile, hasProfile, worker)
}

func NewLocalModel(userid string) model {
	worker, err := StartPythonWorker()
	if err != nil {
		log.Printf("python worker unavailable: %v", err)
		return newModel(userid, false, false, false, nil)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	hasProfile, err := worker.HasProfile(ctx, userid)
	if err != nil {
		log.Printf("could not load local profile status: %v", err)
	}
	hasProviderSetup, err := worker.HasProviderSetup(ctx, userid)
	if err != nil {
		log.Printf("could not load local provider status: %v", err)
	}
	session, err := worker.BackendSession(ctx, userid)
	if err != nil {
		log.Printf("could not load backend session: %v", err)
	}
	hasBackendSession := false
	if session.AccessToken != "" && session.RefreshToken != "" {
		hasBackendSession, err = worker.EnsureBackendSession(ctx, userid)
		if err != nil {
			log.Printf("could not refresh backend session: %v", err)
			hasBackendSession = true
		}
	}
	m := newModel(userid, hasProfile, hasProviderSetup, hasBackendSession, worker)
	m.backendUsername = session.Username
	m.settings.username = session.Username
	if !hasBackendSession && session.Username != "" {
		m.backendAccount.requireSignIn(session.Username, "Your saved session has expired. Please sign in again.")
	}
	return m
}

func newModel(userid string, hasProfile bool, hasProviderSetup bool, hasBackendSession bool, worker *Worker) model {
	dash := newDashboardModel(userid)
	backendAccount := newBackendAccountModel(userid, worker)
	providerSetup := newProviderSetupModel(userid, worker)
	setup := newSetupModel(userid, worker, hasProfile)
	settings := newSettingsModel(userid, "", worker)

	var active screen
	if !hasBackendSession {
		active = backendAccountScreen
	} else if !hasProviderSetup {
		active = providerSetupScreen
	} else if !hasProfile {
		active = setupScreen
	} else {
		active = dashboardScreen
	}

	m := model{
		active:            active,
		hasBackendSession: hasBackendSession,
		hasProfile:        hasProfile,
		hasProviderSetup:  hasProviderSetup,
		dashboard:         dash,
		providerSetup:     providerSetup,
		backendAccount:    backendAccount,
		setup:             setup,
		settings:          settings,
		userid:            userid,
		worker:            worker,
	}

	return m
}

func (m model) Init() tea.Cmd {
	if m.active == backendAccountScreen {
		return m.backendAccount.Init()
	}
	if m.active == providerSetupScreen {
		return m.providerSetup.Init()
	}
	if m.active == setupScreen {
		return m.setup.Init()
	}
	return nil
}

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	if wsm, ok := msg.(tea.WindowSizeMsg); ok {
		m.width = wsm.Width
		m.height = wsm.Height
		m.dashboard.SetSize(wsm.Width, m.bodyHeightFor(dashboardScreen))
		m.backendAccount.SetSize(wsm.Width, m.bodyHeightFor(backendAccountScreen))
		m.providerSetup.SetSize(wsm.Width, m.bodyHeightFor(providerSetupScreen))
		m.setup.SetSize(wsm.Width, m.bodyHeightFor(setupScreen))
		m.chat.SetSize(wsm.Width, m.bodyHeightFor(chatScreen))
		m.report.SetSize(wsm.Width, m.bodyHeightFor(reportScreen))
		m.history.SetSize(wsm.Width, m.bodyHeightFor(historyScreen))
		m.settings.SetSize(wsm.Width, m.bodyHeightFor(settingsScreen))
		return m, nil
	}

	if key, ok := msg.(tea.KeyMsg); ok && key.String() == "ctrl+c" {
		return m, tea.Quit
	}

	switch m.active {
	case backendAccountScreen:
		return m.updateBackendAccount(msg)
	case dashboardScreen:
		return m.updateDashboard(msg)
	case providerSetupScreen:
		return m.updateProviderSetup(msg)
	case setupScreen:
		return m.updateSetup(msg)
	case chatScreen:
		return m.updateChat(msg)
	case reportScreen:
		return m.updateReport(msg)
	case historyScreen:
		return m.updateHistory(msg)
	case settingsScreen:
		return m.updateSettings(msg)
	default:
		return m, nil
	}
}

func (m model) updateBackendAccount(msg tea.Msg) (tea.Model, tea.Cmd) {
	updated, cmd := m.backendAccount.Update(msg)
	m.backendAccount = updated
	if m.backendAccount.submitted {
		m.hasBackendSession = true
		m.backendUsername = strings.TrimSpace(m.backendAccount.username.Value())
		m.settings.username = m.backendUsername
		m.backendAccount = newBackendAccountModel(m.userid, m.worker)
		if m.reauthPending {
			m.reauthPending = false
			m.active = m.reauthReturn
			if m.active == chatScreen {
				m.chat.reauthenticated()
			} else if m.active == settingsScreen {
				m.settings.reauthenticated()
			}
			return m, nil
		}
		if !m.hasProviderSetup {
			m.active = providerSetupScreen
			return m, m.providerSetup.Init()
		}
		if !m.hasProfile {
			m.active = setupScreen
			return m, m.setup.Init()
		}
		m.active = dashboardScreen
	}
	return m, cmd
}

func (m *model) initChat(cm chatModel) chatModel {
	cm.SetSize(m.width, m.bodyHeightFor(chatScreen))
	return cm
}

func (m *model) initDashboard(dm dashboardModel) dashboardModel {
	dm.SetSize(m.width, m.bodyHeightFor(dashboardScreen))
	return dm
}

func (m *model) initProviderSetup(pm providerSetupModel) providerSetupModel {
	pm.SetSize(m.width, m.bodyHeightFor(providerSetupScreen))
	return pm
}

func (m *model) initSetup(sm setupModel) setupModel {
	sm.SetSize(m.width, m.bodyHeightFor(setupScreen))
	return sm
}

func (m *model) initReport(rm reportModel) reportModel {
	rm.SetSize(m.width, m.bodyHeightFor(reportScreen))
	return rm
}

func (m *model) initHistory(hm historyModel) historyModel {
	hm.SetSize(m.width, m.bodyHeightFor(historyScreen))
	return hm
}

func (m *model) initSettings(sm settingsModel) settingsModel {
	sm.SetSize(m.width, m.bodyHeightFor(settingsScreen))
	return sm
}

func (m *model) reopenSettings(category settingsCategory, reload bool) tea.Cmd {
	if reload {
		m.settings = newSettingsModel(m.userid, m.backendUsername, m.worker)
	}
	m.settings.categoryCursor = int(category)
	m.settings.focus = settingsContentFocus
	m.settings.action = settingsActionNone
	m.settings.close = false
	m.settings = m.initSettings(m.settings)
	m.active = settingsScreen
	if reload {
		return m.settings.Init()
	}
	return nil
}

func (m model) updateDashboard(msg tea.Msg) (tea.Model, tea.Cmd) {
	updated, cmd := m.dashboard.Update(msg)
	m.dashboard = updated

	switch m.dashboard.action {
	case dashboardActionStartIntake:
		m.chat = m.initChat(newChatModelForAgent(AgentIntake, m.userid, "", m.worker))
		m.dashboard = m.initDashboard(newDashboardModel(m.userid))
		m.active = chatScreen
		return m, m.chat.Init()
	case dashboardActionStartDoctor:
		m.chat = m.initChat(newChatModelForAgent(AgentDoctor, m.userid, "", m.worker))
		m.dashboard = m.initDashboard(newDashboardModel(m.userid))
		m.active = chatScreen
		return m, m.chat.Init()
	case dashboardActionHistory:
		m.history = m.initHistory(newHistoryModel(m.userid, m.worker))
		m.dashboard = m.initDashboard(newDashboardModel(m.userid))
		m.active = historyScreen
		return m, m.history.Init()
	case dashboardActionSettings:
		m.dashboard = m.initDashboard(newDashboardModel(m.userid))
		m.settings = m.initSettings(newSettingsModel(m.userid, m.backendUsername, m.worker))
		m.active = settingsScreen
		return m, m.settings.Init()
	}

	return m, cmd
}

func (m model) updateProviderSetup(msg tea.Msg) (tea.Model, tea.Cmd) {
	updated, cmd := m.providerSetup.Update(msg)
	m.providerSetup = updated
	if m.providerSetup.cancelled && m.returnToSettings {
		m.returnToSettings = false
		m.providerSetup = m.initProviderSetup(newProviderSetupModel(m.userid, m.worker))
		cmd := m.reopenSettings(settingsProviders, false)
		return m, cmd
	}

	if m.providerSetup.submitted {
		if m.returnToSettings {
			m.returnToSettings = false
			m.hasProviderSetup = true
			m.providerSetup = m.initProviderSetup(newProviderSetupModel(m.userid, m.worker))
			cmd := m.reopenSettings(settingsProviders, true)
			return m, cmd
		}
		m.hasProviderSetup = true
		m.providerSetup = m.initProviderSetup(newProviderSetupModel(m.userid, m.worker))
		if m.hasProfile {
			m.dashboard = m.initDashboard(newDashboardModel(m.userid))
			m.active = dashboardScreen
			return m, nil
		}
		m.setup = m.initSetup(newSetupModel(m.userid, m.worker, false))
		m.active = setupScreen
		return m, m.setup.Init()
	}

	return m, cmd
}

func (m model) updateSetup(msg tea.Msg) (tea.Model, tea.Cmd) {
	updated, cmd := m.setup.Update(msg)
	m.setup = updated

	if m.setup.cancelled {
		if m.returnToSettings {
			m.returnToSettings = false
			m.setup = m.initSetup(newSetupModel(m.userid, m.worker, true))
			cmd := m.reopenSettings(settingsProfile, false)
			return m, cmd
		}
		m.setup = m.initSetup(newSetupModel(m.userid, m.worker, m.hasProfile))
		if m.hasProfile {
			m.dashboard = m.initDashboard(newDashboardModel(m.userid))
			m.active = dashboardScreen
		}
		return m, nil
	}

	if m.setup.submitted {
		if m.returnToSettings {
			m.returnToSettings = false
			m.hasProfile = true
			m.setup = m.initSetup(newSetupModel(m.userid, m.worker, true))
			cmd := m.reopenSettings(settingsProfile, true)
			return m, cmd
		}
		m.hasProfile = true
		m.dashboard = m.initDashboard(newDashboardModel(m.userid))
		m.setup = m.initSetup(newSetupModel(m.userid, m.worker, true))
		m.active = dashboardScreen
		return m, nil
	}

	return m, cmd
}

func (m model) updateChat(msg tea.Msg) (tea.Model, tea.Cmd) {
	updated, cmd := m.chat.Update(msg)
	m.chat = updated
	if m.chat.authRequired {
		m.reauthPending = true
		m.reauthReturn = chatScreen
		m.backendAccount = newBackendAccountModel(m.userid, m.worker)
		m.backendAccount.requireSignIn(m.backendUsername, "Your session expired. Sign in to return to this chat.")
		m.active = backendAccountScreen
		return m, m.backendAccount.Init()
	}

	if m.chat.exit_chat {
		m.dashboard = m.initDashboard(newDashboardModel(m.userid))
		kind := AgentIntake
		if m.chat.agent != nil {
			kind = m.chat.agent.Kind()
		}
		m.chat = m.initChat(newChatModelForAgent(kind, m.userid, "", m.worker))
		m.active = dashboardScreen
		return m, nil
	}

	if m.chat.reportReady {
		m.report = m.initReport(newReportModel(m.chat.report, m.chat.citations, m.chat.researchSessionID, m.userid, m.worker))
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
		m.report = m.initReport(newReportModel("", nil, "", m.userid, m.worker))
		m.active = chatScreen
		return m, nil
	}

	return m, cmd
}

func (m model) updateHistory(msg tea.Msg) (tea.Model, tea.Cmd) {
	updated, cmd := m.history.Update(msg)
	m.history = updated

	if m.history.close {
		m.history = m.initHistory(newHistoryModel(m.userid, m.worker))
		m.dashboard = m.initDashboard(newDashboardModel(m.userid))
		m.active = dashboardScreen
		return m, nil
	}

	return m, cmd
}

func (m model) updateSettings(msg tea.Msg) (tea.Model, tea.Cmd) {
	updated, cmd := m.settings.Update(msg)
	m.settings = updated
	m.settings.SetSize(m.width, m.bodyHeightFor(settingsScreen))

	if m.settings.authRequired {
		m.settings.authRequired = false
		m.reauthPending = true
		m.reauthReturn = settingsScreen
		m.backendAccount = newBackendAccountModel(m.userid, m.worker)
		message := m.settings.authMessage
		if message == "" {
			message = "Your session expired. Sign in to continue."
		}
		m.backendAccount.requireSignIn(m.backendUsername, message)
		m.active = backendAccountScreen
		return m, m.backendAccount.Init()
	}

	switch m.settings.action {
	case settingsActionEditProfile:
		m.settings.action = settingsActionNone
		m.returnToSettings = true
		m.setup = m.initSetup(newProfileEditor(m.userid, m.worker, m.settings.data.Profile))
		m.active = setupScreen
		return m, m.setup.Init()
	case settingsActionEditProviders:
		m.settings.action = settingsActionNone
		m.returnToSettings = true
		m.providerSetup = m.initProviderSetup(newProviderEditor(m.userid, m.worker, m.settings.data.ProviderSetup))
		m.active = providerSetupScreen
		return m, m.providerSetup.Init()
	}

	if m.settings.close {
		m.settings.close = false
		m.active = dashboardScreen
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
	case backendAccountScreen:
		body = m.backendAccount.View()
	case dashboardScreen:
		body = m.dashboard.View()
	case providerSetupScreen:
		body = m.providerSetup.View()
	case setupScreen:
		body = m.setup.View()
	case chatScreen:
		body = m.chat.View()
	case reportScreen:
		body = m.report.View()
	case historyScreen:
		body = m.history.View()
	case settingsScreen:
		body = m.settings.View()
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
	return m.chromeFor(m.active)
}

func (m model) chromeFor(active screen) (string, []string) {
	switch active {
	case backendAccountScreen:
		return "Iatreon - Account", m.backendAccount.footer()
	case providerSetupScreen:
		return "Iatreon - Provider Setup", m.providerSetup.footer()
	case setupScreen:
		return "Iatreon - Profile Setup", m.setup.footer()
	case chatScreen:
		if m.chat.agent == nil {
			return "", nil
		}
		return m.chat.agent.Header(), m.chat.footerActions
	case reportScreen:
		return "Iatreon - Research Report", []string{"↑/↓ Scroll", "c Citations", "Tab Focus", "j/k Citation", "Esc Continue", "Ctrl+C Quit"}
	case historyScreen:
		return "Iatreon - History", m.history.footer()
	case settingsScreen:
		return "Iatreon - Settings", m.settings.footer()
	default:
		return "Iatreon - Dashboard", m.dashboard.footer()
	}
}

func (m model) bodyHeightFor(active screen) int {
	if m.height <= 0 {
		return 0
	}
	headerText, footerActions := m.chromeFor(active)
	chromeH := lipgloss.Height(renderHeader(headerText, m.width)) + lipgloss.Height(renderFooter(footerActions, m.width))
	bodyH := m.height - chromeH
	if bodyH < 0 {
		return 0
	}
	return bodyH
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
