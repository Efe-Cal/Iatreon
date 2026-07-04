package tui

import (
	"fmt"
	"strings"

	"github.com/charmbracelet/bubbles/textinput"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

type authMode int

const (
	authModeLogin authMode = iota
	authModeRegister
)

type authModel struct {
	mode       authMode
	client     *AuthClient
	email      textinput.Model
	password   textinput.Model
	confirm    textinput.Model
	focus      int
	width      int
	height     int
	submitting bool
	err        error
	succeeded  bool
	state      AuthState
}

type authFinishedMsg struct {
	state AuthState
	err   error
}

func newAuthModel(client *AuthClient) authModel {
	email := textinput.New()
	email.Placeholder = "email@example.com"
	email.CharLimit = 128
	email.Width = 36
	email.Focus()

	password := textinput.New()
	password.Placeholder = "password"
	password.CharLimit = 256
	password.Width = 36
	password.EchoMode = textinput.EchoPassword
	password.EchoCharacter = '*'

	confirm := textinput.New()
	confirm.Placeholder = "confirm password"
	confirm.CharLimit = 256
	confirm.Width = 36
	confirm.EchoMode = textinput.EchoPassword
	confirm.EchoCharacter = '*'

	return authModel{
		mode:     authModeLogin,
		client:   client,
		email:    email,
		password: password,
		confirm:  confirm,
	}
}

func (m authModel) Init() tea.Cmd {
	return textinput.Blink
}

func (m *authModel) SetSize(w, h int) {
	m.width = w
	m.height = h
	fieldWidth := max(24, min(48, w-12))
	m.email.Width = fieldWidth
	m.password.Width = fieldWidth
	m.confirm.Width = fieldWidth
}

func (m authModel) footer() []string {
	if m.submitting {
		return []string{"Ctrl+C Quit"}
	}
	if m.mode == authModeLogin {
		return []string{"Tab Field", "Ctrl+R Register", "Enter Login", "Ctrl+C Quit"}
	}
	return []string{"Tab Field", "Ctrl+R Login", "Enter Register", "Ctrl+C Quit"}
}

func (m authModel) Update(msg tea.Msg) (authModel, tea.Cmd) {
	if m.submitting {
		switch msg := msg.(type) {
		case authFinishedMsg:
			m.submitting = false
			if msg.err != nil {
				m.err = msg.err
				return m, nil
			}
			m.succeeded = true
			m.state = msg.state
			return m, nil
		case tea.KeyMsg:
			if msg.String() == "ctrl+c" {
				return m, tea.Quit
			}
		}
		return m, nil
	}

	switch msg := msg.(type) {
	case tea.KeyMsg:
		switch msg.String() {
		case "ctrl+c":
			return m, tea.Quit
		case "tab", "down":
			m.moveFocus(1)
			return m, textinput.Blink
		case "shift+tab", "up":
			m.moveFocus(-1)
			return m, textinput.Blink
		case "ctrl+r":
			m.toggleMode()
			return m, textinput.Blink
		case "enter":
			return m.submit()
		}
	}

	var cmd tea.Cmd
	switch m.focus {
	case 0:
		m.email, cmd = m.email.Update(msg)
	case 1:
		m.password, cmd = m.password.Update(msg)
	case 2:
		m.confirm, cmd = m.confirm.Update(msg)
	}
	return m, cmd
}

func (m *authModel) moveFocus(delta int) {
	count := m.fieldCount()
	m.focus = (m.focus + delta + count) % count
	m.applyFocus()
}

func (m *authModel) toggleMode() {
	if m.mode == authModeLogin {
		m.mode = authModeRegister
	} else {
		m.mode = authModeLogin
	}
	if m.focus >= m.fieldCount() {
		m.focus = m.fieldCount() - 1
	}
	m.err = nil
	m.applyFocus()
}

func (m *authModel) applyFocus() {
	m.email.Blur()
	m.password.Blur()
	m.confirm.Blur()
	switch m.focus {
	case 0:
		m.email.Focus()
	case 1:
		m.password.Focus()
	case 2:
		m.confirm.Focus()
	}
}

func (m authModel) fieldCount() int {
	if m.mode == authModeRegister {
		return 3
	}
	return 2
}

func (m authModel) submit() (authModel, tea.Cmd) {
	email := strings.TrimSpace(m.email.Value())
	password := m.password.Value()
	confirm := m.confirm.Value()

	if email == "" {
		m.err = fmt.Errorf("email is required")
		m.focus = 0
		m.applyFocus()
		return m, nil
	}
	if len(password) < 8 {
		m.err = fmt.Errorf("password must be at least 8 characters")
		m.focus = 1
		m.applyFocus()
		return m, nil
	}
	if m.mode == authModeRegister && password != confirm {
		m.err = fmt.Errorf("passwords do not match")
		m.focus = 2
		m.applyFocus()
		return m, nil
	}

	mode := m.mode
	client := m.client
	m.password.SetValue("")
	m.confirm.SetValue("")
	m.err = nil
	m.submitting = true

	return m, func() tea.Msg {
		var (
			state AuthState
			err   error
		)
		if mode == authModeRegister {
			state, err = client.Register(email, password)
		} else {
			state, err = client.Login(email, password)
		}
		return authFinishedMsg{state: state, err: err}
	}
}

func (m authModel) View() string {
	if m.width == 0 {
		return ""
	}
	modeText := "Login"
	action := "Sign in"
	helper := "Use your email and password to continue."
	if m.mode == authModeRegister {
		modeText = "Register"
		action = "Create account"
		helper = "Create an account to start your Iatreon profile."
	}

	var rows []string
	rows = append(rows,
		titleStyle.Render(modeText),
		systemStyle.Render(helper),
		"",
		m.renderField("Email", m.email.View(), m.focus == 0),
		m.renderField("Password", m.password.View(), m.focus == 1),
	)
	if m.mode == authModeRegister {
		rows = append(rows, m.renderField("Confirm", m.confirm.View(), m.focus == 2))
	}
	if m.err != nil {
		rows = append(rows, "", errorStyle.Render("Error: "+m.err.Error()))
	} else if m.submitting {
		rows = append(rows, "", systemStyle.Render(action+"..."))
	} else {
		rows = append(rows, "", hintStyle.Render("Press Enter to "+strings.ToLower(action)+"."), hintStyle.Render("Ctrl+R switches login/register."))
	}

	formWidth := max(32, min(58, m.width-8))
	box := lipgloss.NewStyle().
		Width(formWidth).
		Border(lipgloss.NormalBorder()).
		BorderForeground(colorBorder).
		Padding(1, 2).
		Render(lipgloss.JoinVertical(lipgloss.Left, rows...))

	return lipgloss.Place(
		m.width,
		m.height,
		lipgloss.Center,
		lipgloss.Center,
		box,
	)
}

func (m authModel) renderField(label, input string, focused bool) string {
	style := lipgloss.NewStyle().Bold(true).Foreground(colorSystem)
	if focused {
		style = style.Foreground(colorPrimary)
	}
	return lipgloss.JoinVertical(lipgloss.Left, style.Render(label), input)
}
