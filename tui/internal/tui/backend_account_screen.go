package tui

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/charmbracelet/bubbles/textinput"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

type backendAccountStep int

const (
	backendAccountChoice backendAccountStep = iota
	backendAccountUsername
	backendAccountPassword
)

type backendAccountModel struct {
	step                  backendAccountStep
	userid                string
	worker                *Worker
	width, height, cursor int
	username, password    textinput.Model
	err                   error
	reason                string
	submitting, submitted bool
}

type backendAccountSubmittedMsg struct{ err error }

func newBackendAccountModel(userid string, worker *Worker) backendAccountModel {
	username := textinput.New()
	username.Placeholder = "Username"
	username.CharLimit = 128
	password := textinput.New()
	password.Placeholder = "Password"
	password.CharLimit = 1024
	password.EchoMode = textinput.EchoPassword
	return backendAccountModel{userid: userid, worker: worker, username: username, password: password}
}

func (m *backendAccountModel) requireSignIn(username, reason string) {
	m.reason = reason
	m.step = backendAccountPassword
	m.cursor = 0
	m.username.SetValue(username)
	m.username.Blur()
	m.password.Focus()
}

func (m *backendAccountModel) SetSize(w, h int) {
	m.width, m.height = w, h
	width := w/2 + 10
	if width < 30 {
		width = 30
	}
	if width > 60 {
		width = 60
	}
	m.username.Width, m.password.Width = width, width
}

func (m backendAccountModel) Init() tea.Cmd { return textinput.Blink }

func (m backendAccountModel) footer() []string {
	if m.step == backendAccountChoice {
		return []string{"Up/Down Choose", "Enter Continue", "Ctrl+C Quit"}
	}
	return []string{"Enter Continue", "Esc Back", "Ctrl+C Quit"}
}

func (m backendAccountModel) Update(msg tea.Msg) (backendAccountModel, tea.Cmd) {
	if result, ok := msg.(backendAccountSubmittedMsg); ok {
		m.submitting = false
		m.err = result.err
		m.submitted = result.err == nil
		return m, nil
	}
	if m.submitting {
		return m, nil
	}
	if key, ok := msg.(tea.KeyMsg); ok {
		switch key.String() {
		case "ctrl+c":
			return m, tea.Quit
		case "up", "down", "left", "right", "tab", "shift+tab":
			if m.step == backendAccountChoice {
				m.cursor = 1 - m.cursor
				return m, nil
			}
		case "esc":
			if m.step == backendAccountPassword {
				m.step = backendAccountUsername
				m.password.Blur()
				m.username.Focus()
			} else if m.step == backendAccountUsername {
				m.step = backendAccountChoice
				m.username.Blur()
			}
			return m, textinput.Blink
		case "enter":
			m.err = nil
			switch m.step {
			case backendAccountChoice:
				m.step = backendAccountUsername
				m.username.Focus()
				return m, textinput.Blink
			case backendAccountUsername:
				if strings.TrimSpace(m.username.Value()) == "" {
					m.err = fmt.Errorf("username is required")
					return m, nil
				}
				m.step = backendAccountPassword
				m.username.Blur()
				m.password.Focus()
				return m, textinput.Blink
			case backendAccountPassword:
				if len(m.password.Value()) < 8 {
					m.err = fmt.Errorf("password must be at least 8 characters")
					return m, nil
				}
				m.submitting = true
				return m, submitBackendAccount(m)
			}
		}
	}
	var cmd tea.Cmd
	if m.step == backendAccountUsername {
		m.username, cmd = m.username.Update(msg)
	}
	if m.step == backendAccountPassword {
		m.password, cmd = m.password.Update(msg)
	}
	return m, cmd
}

func submitBackendAccount(m backendAccountModel) tea.Cmd {
	return func() tea.Msg {
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		action := "token"
		if m.cursor == 1 {
			action = "register"
		}
		tokens, err := authenticateBackendAccount(ctx, backendAPIURL(), action, strings.TrimSpace(m.username.Value()), m.password.Value())
		if err == nil {
			if m.worker == nil {
				err = fmt.Errorf("encrypted local storage is unavailable")
			} else {
				err = m.worker.UpdateBackendSession(ctx, backendSessionUpdateInput{
					UserID: m.userid, Username: strings.TrimSpace(m.username.Value()),
					AccessToken: tokens.AccessToken, RefreshToken: tokens.RefreshToken,
				})
			}
		}
		return backendAccountSubmittedMsg{err: err}
	}
}

func backendAPIURL() string {
	value := strings.TrimSpace(os.Getenv("IATREON_BACKEND_API_URL"))
	if value == "" {
		value = "https://iatreon.efecal.hackclub.app"
	}
	return strings.TrimRight(value, "/")
}

func authenticateBackendAccount(ctx context.Context, baseURL, action, username, password string) (backendSession, error) {
	body, _ := json.Marshal(map[string]string{"username": username, "password": password})
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, strings.TrimRight(baseURL, "/")+"/auth/"+action, bytes.NewReader(body))
	if err != nil {
		return backendSession{}, err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return backendSession{}, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusCreated {
		return backendSession{}, fmt.Errorf("account request failed: %s", resp.Status)
	}
	var payload backendSession
	if err := json.NewDecoder(resp.Body).Decode(&payload); err != nil {
		return backendSession{}, err
	}
	if payload.AccessToken == "" || payload.RefreshToken == "" {
		return backendSession{}, fmt.Errorf("account request did not return a token pair")
	}
	return payload, nil
}

func (m backendAccountModel) View() string {
	if m.submitting {
		return lipgloss.Place(m.width, m.height, lipgloss.Center, lipgloss.Center, systemStyle.Render("Authenticating..."))
	}
	var content string
	switch m.step {
	case backendAccountChoice:
		choices := []string{"Sign in", "Create account"}
		lines := []string{systemStyle.Render("Connect your Iatreon account"), ""}
		for i, choice := range choices {
			marker := "  "
			if i == m.cursor {
				marker = "> "
			}
			lines = append(lines, marker+choice)
		}
		content = strings.Join(lines, "\n")
	case backendAccountUsername:
		content = systemStyle.Render("Username") + "\n\n" + m.username.View()
	case backendAccountPassword:
		content = systemStyle.Render("Password") + "\n\n" + m.password.View()
	}
	if m.err != nil {
		content += "\n\n" + errorStyle.Render("Error: "+m.err.Error())
	}
	if m.reason != "" {
		content = systemStyle.Render(m.reason) + "\n\n" + content
	}
	return lipgloss.Place(m.width, m.height, lipgloss.Center, lipgloss.Center, content)
}
