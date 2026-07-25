package tui

import (
	"context"
	"fmt"
	"slices"
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
	providerStepModels
	providerStepModelPicker
	providerStepModelFilter
	providerStepModelManual
	providerStepConfirm
)

type agentModelSlot struct {
	key   string
	label string
}

var (
	llmProviders    = []string{"Iatreon AI", "OpenRouter", "Together AI", "Groq", "Fireworks AI", "DeepSeek", "xAI", "Gemini", "Cohere", "Perplexity", "OpenAI", "Hack Club AI"}
	searchProviders = []string{"Iatreon AI", "Exa"}
	agentModelSlots = []agentModelSlot{
		{key: "intake", label: "Intake"},
		{key: "doctor", label: "Doctor"},
		{key: "diagnosis", label: "Diagnosis"},
		{key: "inference", label: "Inference"},
		{key: "profiler", label: "Profile updater"},
		{key: "research_fast", label: "Research fast / web"},
		{key: "research_standard", label: "Research standard"},
		{key: "research_deep", label: "Research deep"},
	}
	iatreonAgentModels = map[string]string{
		"intake":            "google/gemini-3-flash-preview",
		"research_fast":     "google/gemini-3-flash-preview",
		"doctor":            "xiaomi/mimo-v2.5-pro",
		"diagnosis":         "xiaomi/mimo-v2.5-pro",
		"inference":         "xiaomi/mimo-v2.5-pro",
		"profiler":          "xiaomi/mimo-v2.5-pro",
		"research_standard": "xiaomi/mimo-v2.5-pro",
		"research_deep":     "xiaomi/mimo-v2.5-pro",
	}
	llmBaseURLs = map[string]string{
		"OpenAI":       "https://api.openai.com/v1",
		"Hack Club AI": "https://ai.hackclub.com/proxy/v1",
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

	llmProvider     string
	llmAPIKey       textinput.Model
	llmBaseURL      textinput.Model
	searchProvider  string
	searchAPIKey    textinput.Model
	searchBaseURL   textinput.Model
	agentModels     map[string]string
	availableModels []string
	modelDefaults   map[string]string
	activeModelKey  string
	modelFilter     textinput.Model
	manualModel     textinput.Model
	modelsLoading   bool
	modelsFetchErr  string
	modelsRequest   int

	err        error
	submitted  bool
	submitting bool
	editing    bool
	cancelled  bool
}

type providerSubmittedMsg struct {
	err error
}

type providerModelsLoadedMsg struct {
	provider string
	request  int
	result   providerModelsResult
	err      error
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

	modelFilter := textinput.New()
	modelFilter.Placeholder = "Filter models"
	modelFilter.CharLimit = 256
	modelFilter.Width = 54

	manualModel := textinput.New()
	manualModel.Placeholder = "Model ID"
	manualModel.CharLimit = 256
	manualModel.Width = 54

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
		agentModels:    map[string]string{},
		modelDefaults:  map[string]string{},
		modelFilter:    modelFilter,
		manualModel:    manualModel,
	}
}

func newProviderEditor(userid string, worker *Worker, values providerSetupInput) providerSetupModel {
	m := newProviderSetupModel(userid, worker)
	m.editing = true
	if values.LLMProvider != "" {
		m.llmProvider = values.LLMProvider
	}
	if values.SearchProvider != "" {
		m.searchProvider = values.SearchProvider
	}
	m.llmAPIKey.SetValue(values.LLMAPIKey)
	m.llmBaseURL.SetValue(values.LLMBaseURL)
	m.searchAPIKey.SetValue(values.SearchAPIKey)
	m.searchBaseURL.SetValue(values.SearchBaseURL)
	m.agentModels = cloneStringMap(values.AgentModels)
	m.cursor = max(0, slices.Index(llmProviders, m.llmProvider))
	return m
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
	m.modelFilter.Width = fieldWidth
	m.manualModel.Width = fieldWidth
}

func (m providerSetupModel) Init() tea.Cmd {
	return textinput.Blink
}

func (m providerSetupModel) footer() []string {
	if m.submitting {
		return []string{"Ctrl+C Quit"}
	}
	if m.modelsLoading {
		return []string{"Esc Back", "Ctrl+C Quit"}
	}
	switch m.step {
	case providerStepModels:
		actions := []string{"Up/Down Navigate", "Enter Select"}
		if !isIatreonProvider(m.llmProvider) {
			actions = append(actions, "m Manual")
			if m.modelsFetchErr != "" {
				actions = append(actions, "r Retry")
			}
		}
		return append(actions, "Esc Back", "Ctrl+C Quit")
	case providerStepModelPicker:
		return []string{"Up/Down Navigate", "Enter Select", "/ Filter", "m Manual", "Esc Back", "Ctrl+C Quit"}
	case providerStepModelFilter:
		return []string{"Type Filter", "Enter Apply", "Esc Clear", "Ctrl+C Quit"}
	case providerStepModelManual:
		return []string{"Enter Save", "Esc Back", "Ctrl+C Quit"}
	}
	if m.step == providerStepLLM || m.step == providerStepSearch {
		if m.editing && m.step == providerStepLLM {
			return []string{"Up/Down Choose", "Enter Continue", "Esc Settings", "Ctrl+C Quit"}
		}
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
			AgentModels:    cloneStringMap(m.agentModels),
		})
		return providerSubmittedMsg{err: err}
	}
}

func loadProviderModels(m providerSetupModel) tea.Cmd {
	return func() tea.Msg {
		if m.worker == nil {
			return providerModelsLoadedMsg{
				provider: m.llmProvider,
				request:  m.modelsRequest,
				err:      fmt.Errorf("encrypted local storage is unavailable"),
			}
		}
		ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
		defer cancel()
		result, err := m.worker.ProviderModels(ctx, providerModelsInput{
			UserID:      m.userid,
			LLMProvider: m.llmProvider,
			LLMAPIKey:   m.llmAPIKeyValue(),
			LLMBaseURL:  m.llmBaseURLValue(),
		})
		return providerModelsLoadedMsg{provider: m.llmProvider, request: m.modelsRequest, result: result, err: err}
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
	case providerModelsLoadedMsg:
		if msg.provider != m.llmProvider || msg.request != m.modelsRequest || m.step != providerStepModels {
			return m, nil
		}
		m.modelsLoading = false
		m.availableModels = msg.result.Models
		m.modelDefaults = cloneStringMap(msg.result.Defaults)
		if msg.err != nil {
			m.modelsFetchErr = msg.err.Error()
		} else {
			m.modelsFetchErr = msg.result.FetchError
		}
		for _, slot := range agentModelSlots {
			if strings.TrimSpace(m.agentModels[slot.key]) == "" {
				m.agentModels[slot.key] = m.modelDefaults[slot.key]
			}
		}
		return m, nil
	case tea.KeyMsg:
		if m.modelsLoading {
			switch msg.String() {
			case "ctrl+c":
				return m, tea.Quit
			case "esc":
				return m.goBack()
			default:
				return m, nil
			}
		}
		switch msg.String() {
		case "ctrl+c":
			return m, tea.Quit
		case "r":
			if m.step == providerStepModels && m.modelsFetchErr != "" && !isIatreonProvider(m.llmProvider) {
				m.modelsLoading = true
				m.modelsFetchErr = ""
				m.modelsRequest++
				return m, loadProviderModels(m)
			}
		case "/":
			if m.step == providerStepModelPicker {
				m.step = providerStepModelFilter
				m.modelFilter.Focus()
				return m, textinput.Blink
			}
		case "m":
			if (m.step == providerStepModels && m.cursor < len(agentModelSlots) && !isIatreonProvider(m.llmProvider)) ||
				m.step == providerStepModelPicker {
				if m.step == providerStepModels {
					m.activeModelKey = agentModelSlots[m.cursor].key
				}
				m.step = providerStepModelManual
				m.manualModel.SetValue(m.agentModels[m.activeModelKey])
				m.manualModel.Focus()
				return m, textinput.Blink
			}
		case "esc":
			return m.goBack()
		case "enter":
			return m.advance()
		case "up", "left", "shift+tab":
			if m.optionCount() > 0 {
				return m.moveCursor(-1), nil
			}
		case "down", "right", "tab":
			if m.optionCount() > 0 {
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
	count := m.optionCount()
	if count == 0 {
		return m
	}
	m.cursor = (m.cursor + delta + count) % count
	return m
}

func (m providerSetupModel) optionCount() int {
	switch m.step {
	case providerStepModels:
		return len(agentModelSlots) + 1
	case providerStepModelPicker:
		return len(m.filteredModels())
	default:
		return len(m.currentOptions())
	}
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
	case providerStepModelFilter:
		return &m.modelFilter
	case providerStepModelManual:
		return &m.manualModel
	default:
		return nil
	}
}

func (m *providerSetupModel) focusCurrentInput() {
	for _, input := range []*textinput.Model{
		&m.llmAPIKey, &m.llmBaseURL, &m.searchAPIKey, &m.searchBaseURL, &m.modelFilter, &m.manualModel,
	} {
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
		selected := llmProviders[m.cursor]
		if selected != m.llmProvider {
			m.llmAPIKey.SetValue("")
			m.llmBaseURL.SetValue("")
			m.agentModels = map[string]string{}
			m.availableModels = nil
			m.modelDefaults = map[string]string{}
			m.modelsFetchErr = ""
		}
		m.llmProvider = selected
		m.cursor = max(0, slices.Index(searchProviders, m.searchProvider))
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
		m.cursor = max(0, slices.Index(searchProviders, m.searchProvider))
	case providerStepSearch:
		selected := searchProviders[m.cursor]
		if selected != m.searchProvider {
			m.searchAPIKey.SetValue("")
			m.searchBaseURL.SetValue("")
		}
		m.searchProvider = selected
		m.cursor = 0
		if isIatreonProvider(m.searchProvider) {
			return m.prepareModelStep()
		}
		m.step = providerStepSearchKey
	case providerStepSearchKey:
		if strings.TrimSpace(m.searchAPIKey.Value()) == "" {
			m.err = fmt.Errorf("API key is required for %s", m.searchProvider)
			return m, nil
		}
		m.step = providerStepSearchBaseURL
	case providerStepSearchBaseURL:
		return m.prepareModelStep()
	case providerStepModels:
		if m.cursor == len(agentModelSlots) {
			for _, slot := range agentModelSlots {
				if strings.TrimSpace(m.agentModels[slot.key]) == "" {
					m.err = fmt.Errorf("select a model for %s", slot.label)
					return m, nil
				}
			}
			m.step = providerStepConfirm
			return m, nil
		}
		if isIatreonProvider(m.llmProvider) {
			return m, nil
		}
		m.activeModelKey = agentModelSlots[m.cursor].key
		if len(m.availableModels) == 0 {
			m.step = providerStepModelManual
			m.manualModel.SetValue(m.agentModels[m.activeModelKey])
		} else {
			m.step = providerStepModelPicker
			m.cursor = max(0, slices.Index(m.filteredModels(), m.agentModels[m.activeModelKey]))
		}
	case providerStepModelPicker:
		models := m.filteredModels()
		if len(models) == 0 {
			m.err = fmt.Errorf("no models match the filter")
			return m, nil
		}
		m.agentModels[m.activeModelKey] = models[m.cursor]
		m.step = providerStepModels
		m.cursor = m.agentModelSlotIndex(m.activeModelKey)
	case providerStepModelFilter:
		m.step = providerStepModelPicker
		m.cursor = 0
	case providerStepModelManual:
		value := strings.TrimSpace(m.manualModel.Value())
		if value == "" {
			m.err = fmt.Errorf("model ID is required")
			return m, nil
		}
		m.agentModels[m.activeModelKey] = value
		m.step = providerStepModels
		m.cursor = m.agentModelSlotIndex(m.activeModelKey)
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
		if m.editing {
			m.cancelled = true
		}
		return m, nil
	case providerStepLLMKey:
		m.step = providerStepLLM
		m.cursor = max(0, slices.Index(llmProviders, m.llmProvider))
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
		m.cursor = max(0, slices.Index(searchProviders, m.searchProvider))
	case providerStepSearchBaseURL:
		m.step = providerStepSearchKey
	case providerStepModels:
		if isIatreonProvider(m.searchProvider) {
			m.step = providerStepSearch
			m.cursor = max(0, slices.Index(searchProviders, m.searchProvider))
		} else {
			m.step = providerStepSearchBaseURL
		}
		m.modelsLoading = false
	case providerStepModelPicker:
		m.step = providerStepModels
		m.cursor = m.agentModelSlotIndex(m.activeModelKey)
	case providerStepModelFilter:
		m.modelFilter.SetValue("")
		m.step = providerStepModelPicker
		m.cursor = 0
	case providerStepModelManual:
		if len(m.availableModels) > 0 {
			m.step = providerStepModelPicker
			m.cursor = max(0, slices.Index(m.filteredModels(), m.agentModels[m.activeModelKey]))
		} else {
			m.step = providerStepModels
			m.cursor = m.agentModelSlotIndex(m.activeModelKey)
		}
	case providerStepConfirm:
		m.step = providerStepModels
		m.cursor = len(agentModelSlots)
	}
	m.focusCurrentInput()
	return m, textinput.Blink
}

func (m providerSetupModel) prepareModelStep() (providerSetupModel, tea.Cmd) {
	m.step = providerStepModels
	m.cursor = 0
	m.err = nil
	m.activeModelKey = ""
	m.modelFilter.SetValue("")
	if isIatreonProvider(m.llmProvider) {
		m.agentModels = cloneStringMap(iatreonAgentModels)
		m.availableModels = nil
		m.modelsFetchErr = ""
		m.modelsLoading = false
		return m, nil
	}
	m.modelsLoading = true
	m.modelsFetchErr = ""
	m.modelsRequest++
	return m, loadProviderModels(m)
}

func (m providerSetupModel) agentModelSlotIndex(key string) int {
	for i, slot := range agentModelSlots {
		if slot.key == key {
			return i
		}
	}
	return 0
}

func (m providerSetupModel) filteredModels() []string {
	query := strings.ToLower(strings.TrimSpace(m.modelFilter.Value()))
	if query == "" {
		return m.availableModels
	}
	filtered := make([]string, 0, len(m.availableModels))
	for _, model := range m.availableModels {
		if strings.Contains(strings.ToLower(model), query) {
			filtered = append(filtered, model)
		}
	}
	return filtered
}

func cloneStringMap(values map[string]string) map[string]string {
	cloned := make(map[string]string, len(values))
	for key, value := range values {
		cloned[key] = value
	}
	return cloned
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
	paneWidth := m.paneWidth()
	body := lipgloss.NewStyle().Width(paneWidth).Align(lipgloss.Left).Render(content)
	topPad := m.height / 5
	if m.step >= providerStepModels {
		topPad = 1
	}
	if topPad < 1 {
		topPad = 0
	}
	return lipgloss.Place(m.width, m.height, lipgloss.Center, lipgloss.Top, strings.Repeat("\n", topPad)+body)
}

func (m providerSetupModel) paneWidth() int {
	paneWidth := m.width - 8
	if paneWidth < 30 {
		paneWidth = m.width
	}
	return min(76, paneWidth)
}

func (m providerSetupModel) stepTitle() string {
	switch m.step {
	case providerStepLLM:
		return "Step 1 of 4 - Choose your AI provider"
	case providerStepSearch:
		return "Step 2 of 4 - Choose your search provider"
	case providerStepModels:
		return "Step 3 of 4 - Configure agent models"
	case providerStepModelPicker, providerStepModelFilter, providerStepModelManual:
		return "Step 3 of 4 - Choose model for " + m.agentModelLabel(m.activeModelKey)
	case providerStepConfirm:
		return "Step 4 of 4 - Review provider setup"
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
	case providerStepModels:
		return m.renderModelOverview()
	case providerStepModelPicker:
		return m.renderModelPicker()
	case providerStepModelFilter:
		return m.renderInput("Filter available models", m.modelFilter.View())
	case providerStepModelManual:
		return m.renderInput("Enter a model ID", m.manualModel.View())
	case providerStepConfirm:
		return m.renderSummary()
	default:
		return ""
	}
}

func (m providerSetupModel) renderModelOverview() string {
	if m.modelsLoading {
		return systemStyle.Render("Loading available models...")
	}
	rows := make([]string, 0, len(agentModelSlots)+1)
	width := max(1, m.paneWidth()-2)
	for i, slot := range agentModelSlots {
		marker := "  "
		style := lipgloss.NewStyle().Foreground(colorMuted)
		if i == m.cursor {
			marker = "> "
			style = style.Foreground(colorPrimary).Bold(true)
		}
		value := strings.TrimSpace(m.agentModels[slot.key])
		if value == "" {
			value = "Not selected"
		}
		suffix := ""
		if isIatreonProvider(m.llmProvider) {
			suffix = " (fixed)"
		}
		rows = append(rows, style.Render(clip(marker+slot.label+": "+value+suffix, width)))
	}
	continueStyle := lipgloss.NewStyle().Foreground(colorAccent)
	continueMarker := "  "
	if m.cursor == len(agentModelSlots) {
		continueMarker = "> "
		continueStyle = continueStyle.Bold(true).Foreground(colorPrimary)
	}
	rows = append(rows, continueStyle.Render(continueMarker+"Continue"))
	return visibleRows(rows, m.cursor, max(1, m.height-7))
}

func (m providerSetupModel) renderModelPicker() string {
	models := m.filteredModels()
	if len(models) == 0 {
		return hintStyle.Render("No models match this filter. Press / to change it or m to enter an ID.")
	}
	rows := make([]string, 0, len(models))
	for i, model := range models {
		marker := "  "
		style := lipgloss.NewStyle().Foreground(colorMuted)
		if i == m.cursor {
			marker = "> "
			style = style.Foreground(colorPrimary).Bold(true)
		}
		rows = append(rows, style.Render(clip(marker+model, max(1, m.paneWidth()-2))))
	}
	return visibleRows(rows, m.cursor, max(1, m.height-7))
}

func (m providerSetupModel) agentModelLabel(key string) string {
	for _, slot := range agentModelSlots {
		if slot.key == key {
			return slot.label
		}
	}
	return "agent"
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

	lines := []string{
		labelStyle.Render("AI"),
		itemStyle.Render(clip("Provider: "+m.llmProvider, m.paneWidth()-2)),
		itemStyle.Render(clip("Base URL: "+llmURL, m.paneWidth()-2)),
		labelStyle.Render("Search"),
		itemStyle.Render(clip("Provider: "+m.searchProvider, m.paneWidth()-2)),
		itemStyle.Render(clip("Base URL: "+searchURL, m.paneWidth()-2)),
		labelStyle.Render("Models"),
	}
	for _, slot := range agentModelSlots {
		lines = append(lines, itemStyle.Render(clip(slot.label+": "+m.agentModels[slot.key], m.paneWidth()-2)))
	}
	return lipgloss.JoinVertical(lipgloss.Left, lines...)
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
	case providerStepModels:
		if m.modelsLoading {
			return hintStyle.Render("Contacting " + m.llmProvider + "...")
		}
		if m.modelsFetchErr != "" {
			return errorStyle.Render("Could not load models: " + m.modelsFetchErr)
		}
		if isIatreonProvider(m.llmProvider) {
			return hintStyle.Render("Iatreon AI uses fixed models for each operation.")
		}
		return hintStyle.Render("Select an agent to change its model.")
	case providerStepModelPicker:
		if query := strings.TrimSpace(m.modelFilter.Value()); query != "" {
			return hintStyle.Render("Filter: " + query)
		}
		return hintStyle.Render("Choose a model returned by " + m.llmProvider + ".")
	case providerStepModelFilter:
		return hintStyle.Render("Matching is case-insensitive.")
	case providerStepModelManual:
		return hintStyle.Render("Enter the exact model identifier accepted by the provider.")
	case providerStepConfirm:
		return hintStyle.Render("Press Enter to save providers and models.")
	default:
		return hintStyle.Render("Enter the requested provider detail.")
	}
}
