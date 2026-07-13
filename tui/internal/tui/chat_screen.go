package tui

import (
	"context"
	"crypto/rand"
	"encoding/json"
	"fmt"
	"log"
	"math"
	"slices"
	"strings"
	"time"

	"github.com/charmbracelet/bubbles/spinner"
	"github.com/charmbracelet/bubbles/textinput"
	"github.com/charmbracelet/bubbles/viewport"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/glamour"
	"github.com/charmbracelet/lipgloss"
)

// messageItem holds a single chat entry.
type messageItem struct {
	role  string // "user", "ai", or "system"
	text  string
	label string
	toolMessage
}

type chatModel struct {
	agent          AgentHandler
	userid         string
	conversationID string
	sessionID      string
	worker         *Worker

	input    textinput.Model
	viewport viewport.Model
	spinner  spinner.Model

	toolSpinner  spinner.Model
	shimmerFrame float64

	history          []messageItem
	streamingMessage string
	isStreaming      bool

	logout bool
	width  int
	height int

	aiRenderer   *glamour.TermRenderer
	userRenderer *glamour.TermRenderer

	footerActions []string

	invokeAgentWithEnter bool
	retryWithEnter       bool
	retryMessage         string
	reportReady          bool
	report               string
	citations            []citation
	researchSessionID    string
}

func (m chatModel) UpdateFooter(a string, idx int) {
	m.footerActions = slices.Replace(m.footerActions, idx, idx+1, a)
}

func generateUUID() string {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		return "12345678-1234-5678-1234-567812345678"
	}
	b[6] = (b[6] & 0x0f) | 0x40
	b[8] = (b[8] & 0x3f) | 0x80
	return fmt.Sprintf("%08x-%04x-%04x-%04x-%012x", b[0:4], b[4:6], b[6:8], b[8:10], b[10:])
}

func newChatModel(userid string, worker *Worker) chatModel {
	return newChatModelForAgent(AgentIntake, userid, "", worker)
}

func newChatModelForAgent(kind AgentKind, userid string, session_id string, worker *Worker) chatModel {
	aiRenderer, _ := glamour.NewTermRenderer(
		glamour.WithAutoStyle(),
		glamour.WithWordWrap(100),
	)
	userRenderer, _ := glamour.NewTermRenderer(
		glamour.WithAutoStyle(),
		glamour.WithWordWrap(100),
	)

	ti := textinput.New()
	ti.Placeholder = "Type a message…"
	ti.Prompt = "> "
	ti.CharLimit = 1024
	ti.Focus()

	vp := viewport.New(0, 0)
	// vp.SetContent(welcomeScreen())

	sp := spinner.New(spinner.WithSpinner(spinner.Dot))

	handler := newAgentHandler(kind)

	if session_id == "" {
		session_id = generateUUID()
		if worker != nil {
			ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			resp, err := worker.Call(ctx, "session/create", struct {
				UserID string `json:"user_id"`
			}{UserID: userid})
			cancel()
			if err != nil {
				log.Printf("Error creating worker session: %v", err)
			} else {
				var p struct {
					SessionID string `json:"session_id"`
				}
				if err := decodeWorkerResult(resp, &p); err != nil {
					log.Printf("Error decoding worker session response: %v", err)
				} else if p.SessionID != "" {
					session_id = p.SessionID
				}
			}
		}
	}

	return chatModel{
		agent:          handler,
		userid:         userid,
		conversationID: generateUUID(),
		history: []messageItem{
			{role: "system", text: handler.Welcome()},
		},
		input:         ti,
		viewport:      vp,
		spinner:       sp,
		aiRenderer:    aiRenderer,
		userRenderer:  userRenderer,
		toolSpinner:   spinner.New(spinner.WithSpinner(spinner.Points)),
		sessionID:     session_id,
		worker:        worker,
		footerActions: handler.Footer(),
	}
}

func (m *chatModel) Init() tea.Cmd {
	return tea.Batch(textinput.Blink, m.spinner.Tick, m.toolSpinner.Tick)
}

func (m *chatModel) SetSize(w, h int) {
	m.width, m.height = w, h

	inputH := lipgloss.Height(m.input.View()) // bubbles textinput knows its own height

	vpH := h - inputH
	if vpH < 3 {
		vpH = 3
	}
	vpW := w - 2
	if vpW < 10 {
		vpW = 10
	}
	m.viewport.Width = vpW
	m.viewport.Height = vpH
	m.input.Width = vpW
}

// renderMarkdown renders markdown text, falling back to plain text on error.
func (m *chatModel) renderMarkdown(text string, isUser bool) string {
	text = formatReferences(text)
	r := m.aiRenderer
	if isUser && m.userRenderer != nil {
		r = m.userRenderer
	}
	if r == nil {
		return text
	}
	out, err := r.Render(text)
	if err != nil {
		return text
	}
	return out
}

func (m *chatModel) agentLabel() string {
	if m.agent == nil {
		return aiLabelStyle.Render("Iatreon:")
	}
	return aiLabelStyle.Render(m.agent.AgentLabel())
}

func (m *chatModel) renderHistory() string {
	var sb strings.Builder
	for _, msg := range m.history {
		sb.WriteString(m.renderMessage(msg))
		sb.WriteString("\n")
	}
	if m.streamingMessage != "" {
		// Show the partial response as it streams in.
		if !m.hasAgentLabelInCurrent() {
			sb.WriteString(m.agentLabel())
			sb.WriteString("\n")
		}
		sb.WriteString(m.renderMarkdown(m.streamingMessage, false))
		sb.WriteString("\n")
	}
	if m.isStreaming {
		sb.WriteString(m.spinner.View())
		sb.WriteString(" waiting for response…\n")
	}
	return sb.String()
}

func (m *chatModel) shimmer(text string, offset float64) string {
	runes := []rune(text)

	var builder strings.Builder

	cycleFrames := 80.0 + offset
	activeFrames := 0.65 * cycleFrames //65.0
	bandWidth := 5.0

	cyclePos := math.Mod(m.shimmerFrame, cycleFrames)

	if cyclePos > activeFrames {
		style := lipgloss.NewStyle().
			Foreground(lipgloss.Color("#787878"))

		return style.Render(text)
	}

	progress := cyclePos / activeFrames

	center := -bandWidth + progress*(float64(len(runes))+bandWidth*2)

	for i, r := range runes {
		dist := math.Abs(float64(i) - center)

		intensity := 0.0

		if dist < bandWidth {
			x := 1.0 - dist/bandWidth
			intensity = math.Sin(x * math.Pi / 2)
		}

		brightness := int(150 + 120*intensity)

		hexColor := fmt.Sprintf("#%02x%02x%02x", brightness, brightness, brightness)
		style := lipgloss.NewStyle().Foreground(lipgloss.Color(hexColor))

		builder.WriteString(style.Render(string(r)))
	}
	return builder.String()
}

func (m *chatModel) renderAgentSeperator(agent string) string {
	agentLabel := "  " + lipgloss.NewStyle().Foreground(lipgloss.Color("255")).Render(agent+" Done  ")
	half_sep := lipgloss.NewStyle().Foreground(colorBorder).Render(strings.Repeat("─", (m.width-lipgloss.Width(agentLabel))/2-2))
	return lipgloss.JoinHorizontal(lipgloss.Left,
		half_sep,
		agentLabel,
		half_sep,
	)
}

func getPhaseOffset(toolID string) float64 {
	if toolID == "" {
		return 0
	}
	var sum int
	for _, r := range toolID {
		sum += int(r)
	}
	return 0.0
	// return float64(sum%100) / 5.0
}

func (m *chatModel) renderToolMessage(toolMsg messageItem) string {
	// log.Printf("Rendering tool message: %+v\n", toolMsg)
	rawText := "Tool: " + toolMsg.toolName + " " + toolMsg.text

	if toolMsg.toolMessage.running {
		offset := getPhaseOffset(toolMsg.toolMessage.toolID)
		shimmeringText := m.shimmer(rawText, offset)
		return lipgloss.JoinHorizontal(lipgloss.Left, m.toolSpinner.View(), " ", shimmeringText)
	}
	completedStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("240"))
	return completedStyle.Render("✓ " + rawText)
}

func (m *chatModel) renderMessage(msg messageItem) string {
	// log.Printf("Rendering message: %+v\n", msg)
	switch msg.role {
	case "user":
		body := m.renderMarkdown(msg.text, true)
		return lipgloss.NewStyle().Foreground(lipgloss.Color("12")).Render("> " + body)
	case "ai":
		label := msg.label
		if msg.text == "" {
			return label
		}
		body := m.renderMarkdown(msg.text, false)
		return lipgloss.JoinVertical(lipgloss.Left, label, body)
	case "ai_body":
		return m.renderMarkdown(msg.text, false)
	case "system":
		if strings.Contains(strings.ToLower(msg.text), "error") {
			return errorStyle.Render(msg.text)
		}
		return systemStyle.Render(msg.text)
	case "seperator":
		return m.renderAgentSeperator(msg.text)
	case "tool":
		return m.renderToolMessage(msg)
	default:
		return msg.text
	}
}

func (m *chatModel) hasAgentLabelInCurrent() bool {
	for i := len(m.history) - 1; i >= 0; i-- {
		switch m.history[i].role {
		case "ai":
			return true
		case "user", "system", "seperator":
			return false
		}
	}
	return false
}

func (m *chatModel) addStreamingMsgToHistory() {
	if m.streamingMessage == "" {
		return
	}
	role := "ai"
	if m.hasAgentLabelInCurrent() {
		role = "ai_body"
	}
	m.history = append(m.history, messageItem{role: role, label: m.agent.AgentLabel(), text: m.streamingMessage})
	m.streamingMessage = ""
}

func (m *chatModel) refreshViewport(scrollToBottom ...bool) {
	m.viewport.SetContent(m.renderHistory())
	if len(scrollToBottom) > 0 && scrollToBottom[0] {
		m.viewport.GotoBottom()
	}
}

func (m *chatModel) addRecoverableRetryPrompt() {
	m.retryWithEnter = true
	m.history = append(m.history, messageItem{role: "system", text: "Press Enter to retry."})
}

type chunkMsg struct {
	content           string
	err               error
	done              bool
	role              string
	report            string
	citations         []citation
	researchSessionID string
	sessionID         string
	conversationID    string
	recoverable       bool
	ch                chan chunkMsg
	toolMessage
}

type continueAgent struct {
	agentKind AgentKind
}

func continueFromAgent(agentKind AgentKind) tea.Cmd {
	return func() tea.Msg {
		return continueAgent{agentKind: agentKind}
	}
}

func waitForChunk(ch chan chunkMsg) tea.Cmd {
	return func() tea.Msg {
		if ch == nil {
			return chunkMsg{done: true}
		}
		msg, ok := <-ch
		if !ok {
			return chunkMsg{done: true}
		}
		return msg
	}
}

func (m *chatModel) streamMessage(agent AgentHandler, conversationID, userid, msg string) tea.Cmd {
	return func() tea.Msg {
		ch := make(chan chunkMsg)
		go func() {
			defer close(ch)

			if m.worker == nil {
				ch <- chunkMsg{err: fmt.Errorf("python worker is not available")}
				return
			}

			responses, err := m.worker.Stream(
				context.Background(),
				agent.Action(),
				agent.BuildInput(conversationID, userid, msg, m.sessionID),
			)
			if err != nil {
				ch <- chunkMsg{err: err}
				return
			}

			for resp := range responses {
				if !resp.OK {
					ch <- chunkMsg{err: fmt.Errorf("%s", resp.Error)}
					return
				}
				if len(resp.Event) == 0 {
					if resp.Done {
						ch <- chunkMsg{done: true}
						return
					}
					continue
				}
				var ev sseEvent
				if err := json.Unmarshal(resp.Event, &ev); err != nil {
					ch <- chunkMsg{content: string(resp.Event), ch: ch}
					continue
				}

				out := agent.HandleEvent(ev)
				out.recoverable = ev.Recoverable
				if out.done || out.err != nil {
					ch <- out
					return
				}
				if out.content != "" || out.toolMessage.toolID != "" || out.sessionID != "" || out.conversationID != "" {
					out.ch = ch
					ch <- out
				}
			}
			ch <- chunkMsg{done: true}
		}()

		return <-ch
	}
}

func (m *chatModel) Update(msg tea.Msg) (chatModel, tea.Cmd) {
	var (
		cmd  tea.Cmd
		cmds []tea.Cmd
	)

	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.SetSize(msg.Width, msg.Height)
		return *m, nil

	case spinner.TickMsg:
		m.spinner, cmd = m.spinner.Update(msg)
		cmds = append(cmds, cmd)

		m.toolSpinner, cmd = m.toolSpinner.Update(msg)
		cmds = append(cmds, cmd)

		m.shimmerFrame += 0.25

		m.refreshViewport()
		return *m, tea.Batch(cmds...)

	case chunkMsg:
		if msg.sessionID != "" {
			m.sessionID = msg.sessionID
		}
		if msg.conversationID != "" {
			m.conversationID = msg.conversationID
		}
		if msg.err == nil && !msg.done && msg.content == "" && msg.toolMessage.toolID == "" {
			return *m, waitForChunk(msg.ch)
		}
		if msg.err != nil {
			m.addStreamingMsgToHistory()
			m.history = append(m.history, messageItem{role: "system", text: "❌ **Error:** " + msg.err.Error()})
			if msg.recoverable {
				m.addRecoverableRetryPrompt()
			}
			m.isStreaming = false
			m.streamingMessage = ""
			m.refreshViewport(true)
			return *m, nil
		}
		if msg.done {
			m.addStreamingMsgToHistory()
			if msg.report != "" {
				m.report = msg.report
				m.citations = msg.citations
				m.researchSessionID = msg.researchSessionID
				m.reportReady = true
				m.isStreaming = false
				m.refreshViewport(true)
				return *m, nil
			}
			if msg.content != "" {
				role := msg.role
				if role == "" {
					role = "system"
				}
				m.history = append(m.history, messageItem{role: role, text: msg.content})
				m.isStreaming = false
				m.history = append(m.history, messageItem{role: "seperator", text: m.agent.AgentLabel()})
				m.history = append(m.history, messageItem{role: "system", text: "Press Enter to continue to the next step."})
				m.refreshViewport(true)
				return *m, continueFromAgent(m.agent.Kind())
			}
			m.isStreaming = false
			m.refreshViewport(true)
			return *m, nil
		}
		if msg.toolMessage.toolID == "" {
			m.streamingMessage += msg.content
		} else {
			m.addStreamingMsgToHistory()
			if !m.hasAgentLabelInCurrent() {
				m.history = append(m.history, messageItem{role: "ai", label: m.agent.AgentLabel()})
			}

			found := false
			// log.Printf("Rendering tool message: %+v\n", msg.toolMessage)
			for i := range m.history {
				if m.history[i].toolMessage.toolID == msg.toolMessage.toolID {
					m.history[i].toolMessage = msg.toolMessage
					m.history[i].text = msg.content
					found = true
					break // Stop searching once found
				}
			}
			if !found {
				// log.Printf("Adding new tool message: %+v\n", msg.toolMessage)
				m.history = append(m.history, messageItem{role: "tool", text: msg.content, toolMessage: msg.toolMessage})
			}
		}
		m.refreshViewport(true)
		return *m, waitForChunk(msg.ch)

	case continueAgent:
		switch msg.agentKind {
		case AgentIntake:
			m.agent = newAgentHandler(AgentResearch)
			m.invokeAgentWithEnter = true
			m.UpdateFooter("Enter Start Research agent", 0)
			return *m, nil
		case AgentResearch:
			m.agent = newAgentHandler(AgentDiagnosis)
			m.invokeAgentWithEnter = true
			m.UpdateFooter("Enter Start Diagnosis agent", 0)
			return *m, nil
		case AgentDiagnosis:
			m.agent = newAgentHandler(AgentDoctor)
			m.invokeAgentWithEnter = true
			m.UpdateFooter("Enter Start Doctor agent", 0)
			return *m, nil
		}

	case tea.KeyMsg:
		if m.isStreaming {
			// Let viewport keep scrolling (pgup/pgdown) but ignore typing.
			m.viewport, cmd = m.viewport.Update(msg)
			cmds = append(cmds, cmd)
			return *m, tea.Batch(cmds...)
		}
		switch msg.String() {
		case "enter":
			text := strings.TrimSpace(m.input.Value())
			if m.retryWithEnter && text == "" {
				m.retryWithEnter = false
				m.history = append(m.history, messageItem{role: "system", text: "Retrying..."})
				m.isStreaming = true
				m.refreshViewport(true)
				return *m, m.streamMessage(m.agent, m.conversationID, m.userid, m.retryMessage)
			}
			m.retryWithEnter = false
			if m.invokeAgentWithEnter {
				m.invokeAgentWithEnter = false
				m.history = append(m.history, messageItem{role: "system", text: "Starting " + m.agent.AgentLabel() + "..."})
				m.refreshViewport(true)
				m.retryMessage = ""
				return *m, m.streamMessage(m.agent, m.conversationID, m.userid, "")
			}
			if text == "" {
				return *m, nil
			}
			m.history = append(m.history, messageItem{role: "user", text: text})
			m.input.SetValue("")
			m.retryMessage = text
			m.isStreaming = true
			m.refreshViewport(true)
			cmds = append(cmds, m.streamMessage(m.agent, m.conversationID, m.userid, text))
			cmds = append(cmds, m.spinner.Tick)
			return *m, tea.Batch(cmds...)
		case "esc":
			m.logout = true
			return *m, nil
		}
	}

	// Forward navigation keys to the viewport so messages are scrollable.
	m.viewport, cmd = m.viewport.Update(msg)
	cmds = append(cmds, cmd)

	// Forward all other messages (typing) to the text input.
	m.input, cmd = m.input.Update(msg)
	cmds = append(cmds, cmd)
	return *m, tea.Batch(cmds...)
}

func (m *chatModel) View() string {
	if m.width == 0 {
		return ""
	}

	// Update viewport content right before drawing so the live stream is
	// reflected even when the parent doesn't repaint on every chunk.
	m.viewport.SetContent(m.renderHistory())

	body := lipgloss.JoinVertical(
		lipgloss.Left,
		m.viewport.View(),
		m.input.View(),
	)
	return body
}
