package tui

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

const (
	settingsMinWidth  = 72
	settingsMinHeight = 12
)

type settingsFocus int

const (
	settingsSidebarFocus settingsFocus = iota
	settingsContentFocus
)

type settingsCategory int

const (
	settingsAccount settingsCategory = iota
	settingsProfile
	settingsProviders
	settingsDataCategory
)

type settingsAction int

const (
	settingsActionNone settingsAction = iota
	settingsActionEditProfile
	settingsActionEditProviders
)

type profileSettings struct {
	UserID         string            `json:"user_id"`
	Demographics   map[string]string `json:"demographics"`
	PMH            []string          `json:"pmh"`
	Medications    []string          `json:"medications"`
	Allergies      []string          `json:"allergies"`
	FamilyHistory  []string          `json:"family_history"`
	Social         map[string]string `json:"social"`
	MedicalSummary string            `json:"medical_summary"`
}

type settingsData struct {
	Profile       profileSettings    `json:"profile"`
	ProviderSetup providerSetupInput `json:"provider_setup"`
}

type settingsLoadedMsg struct {
	data settingsData
	err  error
}

type settingsBackupMsg struct {
	err          error
	authRequired bool
}

type settingsModel struct {
	userid   string
	username string
	worker   *Worker

	width  int
	height int

	focus          settingsFocus
	categoryCursor int
	action         settingsAction
	close          bool

	data    settingsData
	loading bool
	loadErr string

	backingUp    bool
	backupStatus string
	backupErr    string
	authRequired bool
}

var settingsCategories = []struct {
	name        string
	description string
}{
	{name: "Account", description: "Your signed-in Iatreon identity."},
	{name: "Medical Profile", description: "The health information used during intake and clinical analysis."},
	{name: "Providers", description: "AI and literature-search services used by Iatreon."},
	{name: "Data", description: "Encrypted storage and cloud backup."},
}

var (
	settingsPanelStyle = lipgloss.NewStyle().
				Border(lipgloss.NormalBorder()).
				BorderForeground(colorBorder)
	settingsFocusedPanelStyle = settingsPanelStyle.Copy().
					BorderForeground(colorPrimary)
	settingsSectionStyle = lipgloss.NewStyle().
				Bold(true).
				Foreground(colorPrimary)
)

func newSettingsModel(userid, username string, worker *Worker) settingsModel {
	return settingsModel{
		userid:   userid,
		username: username,
		worker:   worker,
		focus:    settingsSidebarFocus,
		loading:  true,
	}
}

func (m settingsModel) Init() tea.Cmd { return m.load() }

func (m *settingsModel) SetSize(w, h int) {
	m.width, m.height = w, h
}

func (m settingsModel) footer() []string {
	if m.isTerminalTooSmall() || m.loading {
		return []string{"Esc Back", "Ctrl+C Quit"}
	}
	if m.loadErr != "" {
		return []string{"r Retry", "Esc Back", "Ctrl+C Quit"}
	}
	actions := []string{"Up/Down Navigate", "Left/Right Focus", "Tab Focus"}
	if m.focus == settingsSidebarFocus || settingsCategory(m.categoryCursor) != settingsAccount {
		actions = append(actions, "Enter Select")
	}
	return append(actions, "Esc Back", "Ctrl+C Quit")
}

func (m settingsModel) load() tea.Cmd {
	return func() tea.Msg {
		if m.worker == nil {
			return settingsLoadedMsg{err: errors.New("encrypted local storage is unavailable")}
		}
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		data, err := m.worker.LoadSettings(ctx, m.userid)
		return settingsLoadedMsg{data: data, err: err}
	}
}

func (m settingsModel) backup() tea.Cmd {
	return func() tea.Msg {
		if m.worker == nil {
			return settingsBackupMsg{err: errors.New("encrypted local storage is unavailable")}
		}
		ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
		defer cancel()
		resp, err := m.worker.BackupData(ctx, m.userid)
		return settingsBackupMsg{
			err:          err,
			authRequired: resp.ErrorCode == "backend_auth_required",
		}
	}
}

func (m settingsModel) Update(msg tea.Msg) (settingsModel, tea.Cmd) {
	switch msg := msg.(type) {
	case settingsLoadedMsg:
		m.loading = false
		if msg.err != nil {
			m.loadErr = msg.err.Error()
			return m, nil
		}
		m.data = msg.data
		m.loadErr = ""
		return m, nil

	case settingsBackupMsg:
		m.backingUp = false
		if msg.err != nil {
			m.backupStatus = ""
			m.backupErr = msg.err.Error()
			m.authRequired = msg.authRequired
			return m, nil
		}
		m.backupErr = ""
		m.backupStatus = "Backup uploaded successfully."
		return m, nil

	case tea.KeyMsg:
		switch msg.String() {
		case "ctrl+c":
			return m, tea.Quit
		case "esc":
			m.close = true
			return m, nil
		case "r":
			if m.loadErr != "" {
				m.loading = true
				m.loadErr = ""
				return m, m.load()
			}
		case "tab":
			if m.focus == settingsSidebarFocus {
				m.focus = settingsContentFocus
			} else {
				m.focus = settingsSidebarFocus
			}
			return m, nil
		case "shift+tab", "left":
			m.focus = settingsSidebarFocus
			return m, nil
		case "right":
			m.focus = settingsContentFocus
			return m, nil
		case "up", "k":
			m.move(-1)
			return m, nil
		case "down", "j":
			m.move(1)
			return m, nil
		case "enter":
			return m.activate()
		}
	}
	return m, nil
}

func (m *settingsModel) move(updown int) {
	if m.loading || m.loadErr != "" {
		return
	}
	if m.focus == settingsSidebarFocus {
		count := len(settingsCategories)
		m.categoryCursor = (m.categoryCursor + updown + count) % count
	}
}

func (m settingsModel) activate() (settingsModel, tea.Cmd) {
	if m.loading || m.loadErr != "" {
		return m, nil
	}
	if m.focus == settingsSidebarFocus {
		m.focus = settingsContentFocus
		return m, nil
	}

	switch settingsCategory(m.categoryCursor) {
	case settingsProfile:
		m.action = settingsActionEditProfile
	case settingsProviders:
		m.action = settingsActionEditProviders
	case settingsDataCategory:
		if !m.backingUp {
			m.backingUp = true
			m.backupStatus = ""
			m.backupErr = ""
			m.authRequired = false
			return m, m.backup()
		}
	}
	return m, nil
}

func (m settingsModel) isTerminalTooSmall() bool {
	return m.width > 0 && (m.width < settingsMinWidth || m.height < settingsMinHeight)
}

func (m settingsModel) View() string {
	if m.width == 0 {
		return ""
	}
	if m.isTerminalTooSmall() {
		message := lipgloss.JoinVertical(
			lipgloss.Center,
			settingsSectionStyle.Render("Terminal too small"),
			hintStyle.Render(fmt.Sprintf("Resize to at least %dx%d.", settingsMinWidth, settingsMinHeight)),
		)
		return lipgloss.Place(m.width, m.height, lipgloss.Center, lipgloss.Center, message)
	}

	sidebarW := min(24, max(18, m.width/4))
	contentW := max(1, m.width-sidebarW-1)
	return lipgloss.JoinHorizontal(
		lipgloss.Top,
		m.panel("Settings", m.sidebarView(), sidebarW, m.focus == settingsSidebarFocus),
		" ",
		m.panel(settingsCategories[m.categoryCursor].name, m.contentView(contentW-4), contentW, m.focus == settingsContentFocus),
	)
}

func (m settingsModel) panel(title, body string, width int, focused bool) string {
	style := settingsPanelStyle
	if focused {
		style = settingsFocusedPanelStyle
	}
	contentW := max(1, width-style.GetHorizontalFrameSize())
	contentH := max(1, m.height-style.GetVerticalFrameSize())
	content := lipgloss.JoinVertical(
		lipgloss.Left,
		settingsSectionStyle.Width(contentW).Render(title),
		"",
		body,
	)
	return style.Width(contentW).Height(contentH).Render(content)
}

func (m settingsModel) sidebarView() string {
	rows := make([]string, 0, len(settingsCategories))
	for i, category := range settingsCategories {
		selected := i == m.categoryCursor
		marker := "  "
		style := lipgloss.NewStyle().Foreground(colorMuted)
		if selected {
			marker = "> "
			style = style.Bold(true).Foreground(colorPrimary)
			if m.focus != settingsSidebarFocus {
				style = style.Foreground(colorSystem)
			}
		}
		rows = append(rows, style.Render(marker+category.name))
	}
	return strings.Join(rows, "\n")
}

func (m settingsModel) contentView(width int) string {
	if m.loading {
		return systemStyle.Align(lipgloss.Center).Render("Loading settings...")
	}
	if m.loadErr != "" {
		return lipgloss.JoinVertical(
			lipgloss.Left,
			errorStyle.Render("Could not load settings."),
			"",
			lipgloss.NewStyle().Width(width).Render(m.loadErr),
			"",
			hintStyle.Render("Press r to retry."),
		)
	}

	description := lipgloss.NewStyle().Width(width).Foreground(colorSystem).Render(
		settingsCategories[m.categoryCursor].description,
	)
	return lipgloss.JoinVertical(lipgloss.Left, description, "", m.categoryContent(width))
}

func (m settingsModel) categoryContent(width int) string {
	selected := m.focus == settingsContentFocus
	switch settingsCategory(m.categoryCursor) {
	case settingsAccount:
		username := strings.TrimSpace(m.username)
		if username == "" {
			username = "Unknown"
		}
		return lipgloss.JoinVertical(
			lipgloss.Left,
			m.valueRow("Signed in as", username, width, selected),
			"",
			hintStyle.Render("Account management is handled by Iatreon."),
		)

	case settingsProfile:
		age := strings.TrimSpace(m.data.Profile.Demographics["age"])
		gender := strings.TrimSpace(m.data.Profile.Demographics["gender"])
		if age == "" {
			age = "Not set"
		}
		if gender == "" {
			gender = "Not set"
		}
		return lipgloss.JoinVertical(
			lipgloss.Left,
			m.valueRow("Age", age, width, false),
			m.valueRow("Gender", gender, width, false),
			"",
			m.actionRow("Edit profile", width, selected),
		)

	case settingsProviders:
		llm := strings.TrimSpace(m.data.ProviderSetup.LLMProvider)
		search := strings.TrimSpace(m.data.ProviderSetup.SearchProvider)
		if llm == "" {
			llm = "Not configured"
		}
		if search == "" {
			search = "Not configured"
		}
		return lipgloss.JoinVertical(
			lipgloss.Left,
			m.valueRow("AI provider", llm, width, false),
			m.valueRow("Search provider", search, width, false),
			"",
			m.actionRow("Edit providers", width, selected),
		)

	case settingsDataCategory:
		label := "Back Up Now"
		if m.backingUp {
			label = "Processing backup..."
		}
		lines := []string{
			m.actionRow(label, width, selected && !m.backingUp),
			"",
			hintStyle.Render("Creates an encrypted snapshot and uploads it to your Iatreon account."),
		}
		if m.backupStatus != "" {
			lines = append(lines, "", lipgloss.NewStyle().Foreground(colorAccent).Render(m.backupStatus))
		}
		if m.backupErr != "" {
			message := m.backupErr
			if m.authRequired {
				message = "Sign in again, then run Back Up Now once more."
			}
			lines = append(lines, "", errorStyle.Render(message))
		}
		return lipgloss.JoinVertical(lipgloss.Left, lines...)
	}
	return ""
}

func (m settingsModel) valueRow(label, value string, width int, selected bool) string {
	line := fmt.Sprintf("%-18s %s", label, value)
	style := lipgloss.NewStyle().Width(max(1, width)).Foreground(colorSystem)
	if selected {
		style = style.Foreground(colorPrimary).Bold(true)
		line = "> " + line
	} else {
		line = "  " + line
	}
	return style.Render(line)
}

func (m settingsModel) actionRow(label string, width int, selected bool) string {
	marker := "  "
	style := lipgloss.NewStyle().Width(max(1, width)).Foreground(colorAccent)
	if selected {
		marker = "> "
		style = style.Foreground(colorPrimary).Bold(true)
	}
	return style.Render(marker + label)
}
