package tui

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/charmbracelet/bubbles/textinput"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

type providerSetupStep int

const (
	providerStepLLM providerSetupStep = iota
	providerStepLLMKey
	providerStepLLMBaseURL
	providerStepSearch
	providerStepSearchKey
	providerStepSearchBaseURL
	providerStepConfirm
)

var (
	llmProviders    = []string{"Iatreon AI", "OpenRouter", "Together AI", "Groq", "Fireworks AI", "DeepSeek", "xAI", "Gemini", "Cohere", "Perplexity"}
	searchProviders = []string{"Iatreon AI", "Exa"}
	llmBaseURLs     = map[string]string{
		"OpenRouter":   "https://openrouter.ai/api/v1",
		"Together AI":  "https://api.together.ai/v1",
		"Groq":         "https://api.groq.com/openai/v1",
		"Fireworks AI": "https://api.fireworks.ai/inference/v1",
		"DeepSeek":     "https://api.deepseek.com",
		"xAI":          "https://api.x.ai/v1",
		"Gemini":       "https://generativelanguage.googleapis.com/v1beta/openai/",
		"Cohere":       "https://api.cohere.ai/compatibility/v1",
		"Perplexity":   "https://api.perplexity.ai",
	}
)

type providerSetupModel struct {
	step   providerSetupStep
	userid string
	worker *Worker
	width  int
	height int
	cursor int

	llmProvider    string
	llmAPIKey      textinput.Model
	llmBaseURL     textinput.Model
	searchProvider string
	searchAPIKey   textinput.Model
	searchBaseURL  textinput.Model

	err        error
	submitted  bool
	submitting bool
}

type providerSubmittedMsg struct {
	err error
}

func newProviderSetupModel(userid string, worker *Worker) providerSetupModel {
	llmKey := textinput.New()
	llmKey.Placeholder = "API key"
	llmKey.CharLimit = 256
	llmKey.Width = 54
	llmKey.EchoMode = textinput.EchoPassword

	llmBase := textinput.New()
	llmBase.Placeholder = "Optional base URL"
	llmBase.CharLimit = 256
	llmBase.Width = 54

	searchKey := textinput.New()
	searchKey.Placeholder = "API key"
	searchKey.CharLimit = 256
	searchKey.Width = 54
	searchKey.EchoMode = textinput.EchoPassword

	searchBase := textinput.New()
	searchBase.Placeholder = "Optional base URL"
	searchBase.CharLimit = 256
	searchBase.Width = 54

	return providerSetupModel{
		step:           providerStepLLM,
		userid:         userid,
		worker:         worker,
		llmProvider:    llmProviders[0],
		llmAPIKey:      llmKey,
		llmBaseURL:     llmBase,
		searchProvider: searchProviders[0],
		searchAPIKey:   searchKey,
		searchBaseURL:  searchBase,
	}
}

func (m *providerSetupModel) SetSize(w, h int) {
	m.width = w
	m.height = h
	fieldWidth := w/2 + 10
	if fieldWidth < 30 {
		fieldWidth = 30
	}
	if fieldWidth > 60 {
		fieldWidth = 60
	}
	m.llmAPIKey.Width = fieldWidth
	m.llmBaseURL.Width = fieldWidth
	m.searchAPIKey.Width = fieldWidth
	m.searchBaseURL.Width = fieldWidth
}

func (m providerSetupModel) Init() tea.Cmd {
	return textinput.Blink
}

func (m providerSetupModel) footer() []string {
	if m.submitting {
		return []string{"Ctrl+C Quit"}
	}
	if m.step == providerStepLLM || m.step == providerStepSearch {
		return []string{"Up/Down Choose", "Enter Continue", "Ctrl+C Quit"}
	}
	if m.step == providerStepConfirm {
		return []string{"Enter Save", "Esc Back", "Ctrl+C Quit"}
	}
	return []string{"Enter Continue", "Esc Back", "Ctrl+C Quit"}
}

func submitProviderSetup(m providerSetupModel) tea.Cmd {
	return func() tea.Msg {
		if m.worker == nil {
			return providerSubmittedMsg{}
		}
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()

		err := m.worker.UpdateProviderSetup(ctx, providerSetupInput{
			UserID:         m.userid,
			LLMProvider:    m.llmProvider,
			LLMAPIKey:      m.llmAPIKeyValue(),
			LLMBaseURL:     m.llmBaseURLValue(),
			SearchProvider: m.searchProvider,
			SearchAPIKey:   m.searchAPIKeyValue(),
			SearchBaseURL:  m.searchBaseURLValue(),
		})
		return providerSubmittedMsg{err: err}
	}
}

func (m providerSetupModel) Update(msg tea.Msg) (providerSetupModel, tea.Cmd) {
	if m.submitting {
		switch msg := msg.(type) {
		case providerSubmittedMsg:
			m.submitting = false
			if msg.err != nil {
				m.err = msg.err
				return m, nil
			}
			m.submitted = true
			return m, nil
		default:
			return m, nil
		}
	}

	switch msg := msg.(type) {
	case tea.KeyMsg:
		switch msg.String() {
		case "ctrl+c":
			return m, tea.Quit
		case "esc":
			return m.goBack()
		case "enter":
			return m.advance()
		case "up", "left", "shift+tab":
			if len(m.currentOptions()) > 0 {
				return m.moveCursor(-1), nil
			}
		case "down", "right", "tab":
			if len(m.currentOptions()) > 0 {
				return m.moveCursor(1), nil
			}
		}
	case error:
		m.err = msg
	}

	if input := m.currentInput(); input != nil {
		var cmd tea.Cmd
		*input, cmd = input.Update(msg)
		return m, cmd
	}

	return m, nil
}

func (m providerSetupModel) moveCursor(delta int) providerSetupModel {
	options := m.currentOptions()
	if len(options) == 0 {
		return m
	}
	m.cursor = (m.cursor + delta + len(options)) % len(options)
	return m
}

func (m providerSetupModel) currentOptions() []string {
	switch m.step {
	case providerStepLLM:
		return llmProviders
	case providerStepSearch:
		return searchProviders
	default:
		return nil
	}
}

func (m *providerSetupModel) currentInput() *textinput.Model {
	switch m.step {
	case providerStepLLMKey:
		return &m.llmAPIKey
	case providerStepLLMBaseURL:
		return &m.llmBaseURL
	case providerStepSearchKey:
		return &m.searchAPIKey
	case providerStepSearchBaseURL:
		return &m.searchBaseURL
	default:
		return nil
	}
}

func (m *providerSetupModel) focusCurrentInput() {
	for _, input := range []*textinput.Model{&m.llmAPIKey, &m.llmBaseURL, &m.searchAPIKey, &m.searchBaseURL} {
		input.Blur()
	}
	if input := m.currentInput(); input != nil {
		input.Focus()
	}
}

func (m providerSetupModel) advance() (providerSetupModel, tea.Cmd) {
	m.err = nil

	switch m.step {
	case providerStepLLM:
		m.llmProvider = llmProviders[m.cursor]
		m.cursor = 0
		if isIatreonProvider(m.llmProvider) {
			m.step = providerStepSearch
			return m, nil
		}
		m.step = providerStepLLMKey
	case providerStepLLMKey:
		if strings.TrimSpace(m.llmAPIKey.Value()) == "" {
			m.err = fmt.Errorf("API key is required for %s", m.llmProvider)
			return m, nil
		}
		if strings.TrimSpace(m.llmBaseURL.Value()) == "" {
			m.llmBaseURL.SetValue(defaultLLMBaseURL(m.llmProvider))
		}
		m.step = providerStepLLMBaseURL
	case providerStepLLMBaseURL:
		m.step = providerStepSearch
		m.cursor = 0
	case providerStepSearch:
		m.searchProvider = searchProviders[m.cursor]
		m.cursor = 0
		if isIatreonProvider(m.searchProvider) {
			m.step = providerStepConfirm
			return m, nil
		}
		m.step = providerStepSearchKey
	case providerStepSearchKey:
		if strings.TrimSpace(m.searchAPIKey.Value()) == "" {
			m.err = fmt.Errorf("API key is required for %s", m.searchProvider)
			return m, nil
		}
		m.step = providerStepSearchBaseURL
	case providerStepSearchBaseURL:
		m.step = providerStepConfirm
	case providerStepConfirm:
		m.submitting = true
		return m, submitProviderSetup(m)
	}

	m.focusCurrentInput()
	return m, textinput.Blink
}

func (m providerSetupModel) goBack() (providerSetupModel, tea.Cmd) {
	m.err = nil
	switch m.step {
	case providerStepLLM:
		return m, nil
	case providerStepLLMKey:
		m.step = providerStepLLM
	case providerStepLLMBaseURL:
		m.step = providerStepLLMKey
	case providerStepSearch:
		if isIatreonProvider(m.llmProvider) {
			m.step = providerStepLLM
		} else {
			m.step = providerStepLLMBaseURL
		}
	case providerStepSearchKey:
		m.step = providerStepSearch
	case providerStepSearchBaseURL:
		m.step = providerStepSearchKey
	case providerStepConfirm:
		if isIatreonProvider(m.searchProvider) {
			m.step = providerStepSearch
		} else {
			m.step = providerStepSearchBaseURL
		}
	}
	m.focusCurrentInput()
	return m, textinput.Blink
}

func isIatreonProvider(provider string) bool {
	return strings.EqualFold(provider, "Iatreon AI")
}

func defaultLLMBaseURL(provider string) string {
	return llmBaseURLs[provider]
}

func (m providerSetupModel) llmBaseURLValue() string {
	if isIatreonProvider(m.llmProvider) {
		return backendAPIURL() + "/v1"
	}
	value := strings.TrimSpace(m.llmBaseURL.Value())
	if value != "" {
		return value
	}
	return defaultLLMBaseURL(m.llmProvider)
}

func (m providerSetupModel) searchBaseURLValue() string {
	if isIatreonProvider(m.searchProvider) {
		return backendAPIURL() + "/v1/exa"
	}
	return strings.TrimSpace(m.searchBaseURL.Value())
}

func (m providerSetupModel) llmAPIKeyValue() string {
	if isIatreonProvider(m.llmProvider) {
		return ""
	}
	return strings.TrimSpace(m.llmAPIKey.Value())
}

func (m providerSetupModel) searchAPIKeyValue() string {
	if isIatreonProvider(m.searchProvider) {
		return ""
	}
	return strings.TrimSpace(m.searchAPIKey.Value())
}

func (m providerSetupModel) View() string {
	if m.submitted {
		return m.renderAnchored(lipgloss.JoinVertical(
			lipgloss.Center,
			systemStyle.Render("Provider setup saved."),
			"",
			hintStyle.Render("Opening patient profile setup..."),
		))
	}
	if m.submitting {
		return m.renderAnchored(systemStyle.Render("Saving provider setup..."))
	}

	content := lipgloss.JoinVertical(
		lipgloss.Left,
		systemStyle.Render(m.stepTitle()),
		"",
		m.renderStep(),
		"",
		m.renderPrompt(),
	)
	return m.renderAnchored(content)
}

func (m providerSetupModel) renderAnchored(content string) string {
	paneWidth := m.width - 8
	if paneWidth < 30 {
		paneWidth = m.width
	}
	if paneWidth > 76 {
		paneWidth = 76
	}
	body := lipgloss.NewStyle().Width(paneWidth).Align(lipgloss.Left).Render(content)
	topPad := m.height / 5
	if topPad < 1 {
		topPad = 0
	}
	return lipgloss.Place(m.width, m.height, lipgloss.Center, lipgloss.Top, strings.Repeat("\n", topPad)+body)
}

func (m providerSetupModel) stepTitle() string {
	switch m.step {
	case providerStepLLM:
		return "Step 1 of 3 - Choose your AI provider"
	case providerStepSearch:
		return "Step 2 of 3 - Choose your search provider"
	case providerStepConfirm:
		return "Step 3 of 3 - Review provider setup"
	default:
		return "Provider credentials"
	}
}

func (m providerSetupModel) renderStep() string {
	switch m.step {
	case providerStepLLM:
		return m.renderOptions(llmProviders)
	case providerStepSearch:
		return m.renderOptions(searchProviders)
	case providerStepLLMKey:
		return m.renderInput("API key for "+m.llmProvider, m.llmAPIKey.View())
	case providerStepLLMBaseURL:
		return m.renderInput("Base URL for "+m.llmProvider, m.llmBaseURL.View())
	case providerStepSearchKey:
		return m.renderInput("API key for "+m.searchProvider, m.searchAPIKey.View())
	case providerStepSearchBaseURL:
		return m.renderInput("Base URL for "+m.searchProvider, m.searchBaseURL.View())
	case providerStepConfirm:
		return m.renderSummary()
	default:
		return ""
	}
}

func (m providerSetupModel) renderOptions(options []string) string {
	var lines []string
	for i, option := range options {
		marker := "  "
		style := lipgloss.NewStyle().Foreground(colorMuted)
		if i == m.cursor {
			marker = "> "
			style = style.Foreground(colorPrimary).Bold(true)
		}
		lines = append(lines, style.Render(marker+option))
	}
	return lipgloss.JoinVertical(lipgloss.Left, lines...)
}

func (m providerSetupModel) renderInput(label string, inputView string) string {
	return lipgloss.JoinVertical(
		lipgloss.Left,
		lipgloss.NewStyle().Bold(true).Foreground(colorPrimary).Render(label),
		inputView,
	)
}

func (m providerSetupModel) renderSummary() string {
	labelStyle := lipgloss.NewStyle().Bold(true).Foreground(colorPrimary)
	itemStyle := lipgloss.NewStyle().Foreground(colorAccent).PaddingLeft(2)

	llmURL := m.llmBaseURLValue()
	if llmURL == "" {
		llmURL = "Default"
	}
	searchURL := strings.TrimSpace(m.searchBaseURL.Value())
	if isIatreonProvider(m.searchProvider) {
		searchURL = m.searchBaseURLValue()
	} else if searchURL == "" {
		searchURL = "Default"
	}

	return lipgloss.JoinVertical(
		lipgloss.Left,
		labelStyle.Render("AI"),
		itemStyle.Render("Provider: "+m.llmProvider),
		itemStyle.Render("Base URL: "+llmURL),
		"",
		labelStyle.Render("Search"),
		itemStyle.Render("Provider: "+m.searchProvider),
		itemStyle.Render("Base URL: "+searchURL),
	)
}

func (m providerSetupModel) renderPrompt() string {
	if m.err != nil {
		return errorStyle.Render("Error: " + m.err.Error())
	}
	switch m.step {
	case providerStepLLM:
		return hintStyle.Render("Iatreon AI uses the built-in AI and search proxy.")
	case providerStepLLMBaseURL, providerStepSearchBaseURL:
		return hintStyle.Render("Leave blank to use the provider default.")
	case providerStepConfirm:
		return hintStyle.Render("Press Enter to save these providers.")
	default:
		return hintStyle.Render("Enter the requested provider detail.")
	}
}
