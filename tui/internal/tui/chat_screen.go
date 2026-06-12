package tui

import (
	"bufio"
	"crypto/rand"
	"encoding/json"
	"fmt"
	"net/http"
	"slices"
	"strings"

	"github.com/charmbracelet/bubbles/spinner"
	"github.com/charmbracelet/bubbles/textinput"
	"github.com/charmbracelet/bubbles/viewport"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/glamour"
	"github.com/charmbracelet/lipgloss"
)

// message holds a single chat entry.
type message struct {
	role string // "user", "ai", or "system"
	text string
}

type chatModel struct {
	agent          AgentHandler
	userid         string
	conversationID string

	input    textinput.Model
	viewport viewport.Model
	spinner  spinner.Model

	messages         []message
	streamingMessage string
	isStreaming      bool

	logout bool
	width  int
	height int

	aiRenderer   *glamour.TermRenderer
	userRenderer *glamour.TermRenderer

	headerText    string
	footerActions []string

	invokeAgentWithEnter bool
}

func (m *chatModel) SetHeader(h string)   { m.headerText = h }
func (m *chatModel) SetFooter(a []string) { m.footerActions = a }
func (m chatModel) GetHeader() string     { return m.headerText }
func (m chatModel) GetFooter() []string   { return m.footerActions }
func (m chatModel) UpdateFooter(a string, idx int) {
	m.footerActions = slices.Replace(m.footerActions, idx, idx+1, a)
}

func (m chatModel) Agent() AgentHandler { return m.agent }

func generateUUID() string {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		return "12345678-1234-5678-1234-567812345678"
	}
	b[6] = (b[6] & 0x0f) | 0x40
	b[8] = (b[8] & 0x3f) | 0x80
	return fmt.Sprintf("%08x-%04x-%04x-%04x-%012x", b[0:4], b[4:6], b[6:8], b[8:10], b[10:])
}

func newChatModel(userid string) chatModel {
	return newChatModelForAgent(AgentIntake, userid)
}

func newChatModelForAgent(kind AgentKind, userid string) chatModel {
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

	return chatModel{
		agent:          handler,
		userid:         userid,
		conversationID: generateUUID(),
		messages: []message{
			{role: "system", text: handler.Welcome()},
		},
		input:        ti,
		viewport:     vp,
		spinner:      sp,
		aiRenderer:   aiRenderer,
		userRenderer: userRenderer,
	}
}

func (m *chatModel) Init() tea.Cmd {
	return tea.Batch(textinput.Blink, m.spinner.Tick)
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

// agentLabel returns the styled AI label for the active agent.
func (m *chatModel) agentLabel() string {
	if m.agent == nil {
		return aiLabelStyle.Render("Iatreon:")
	}
	return aiLabelStyle.Render(m.agent.AgentLabel())
}

// renderHistory turns the current message list into a single string for the
// viewport. The live streaming chunk is appended at the end.
func (m *chatModel) renderHistory() string {
	var sb strings.Builder
	for _, msg := range m.messages {
		sb.WriteString(m.renderMessage(msg))
		sb.WriteString("\n")
	}
	if m.streamingMessage != "" {
		// Show the partial response as it streams in.
		sb.WriteString(m.agentLabel())
		sb.WriteString("\n")
		sb.WriteString(m.renderMarkdown(m.streamingMessage, false))
		sb.WriteString("\n")
	}
	if m.isStreaming {
		sb.WriteString(m.spinner.View())
		sb.WriteString(" waiting for response…\n")
	}
	return sb.String()
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

func (m *chatModel) renderMessage(msg message) string {
	switch msg.role {
	case "user":
		label := userLabelStyle.Render("You :")
		body := m.renderMarkdown(msg.text, true)
		return lipgloss.JoinVertical(lipgloss.Left, label, body)
	case "ai":
		label := m.agentLabel()
		body := m.renderMarkdown(msg.text, false)
		return lipgloss.JoinVertical(lipgloss.Left, label, body)
	case "system":
		return systemStyle.Render(msg.text)
	case "seperator":
		return m.renderAgentSeperator(msg.text)
	default:
		return msg.text
	}
}

func (m *chatModel) refreshViewport() {
	m.viewport.SetContent(m.renderHistory())
	m.viewport.GotoBottom()
}

type chunkMsg struct {
	content string
	err     error
	done    bool
	ch      chan chunkMsg
}

type continueAgent struct {
	agentKind AgentKind
}

func continueFromAgent(agentKind AgentKind) tea.Cmd {
	return func() tea.Msg {
		return continueAgent{agentKind: agentKind}
	}
}

// apiBaseURL is the FastAPI host. Per-agent paths are owned by each
// AgentHandler implementation.
const apiBaseURL = "http://localhost:8000"

func waitForChunk(ch chan chunkMsg) tea.Cmd {
	return func() tea.Msg {
		return <-ch
	}
}

func streamMessage(agent AgentHandler, conversationID, userid, msg string) tea.Cmd {
	return func() tea.Msg {
		ch := make(chan chunkMsg)
		go func() {
			defer close(ch)

			req, err := agent.BuildRequest(conversationID, userid, msg)
			if err != nil {
				ch <- chunkMsg{err: err}
				return
			}

			resp, err := sharedHTTPDo(req)
			if err != nil {
				ch <- chunkMsg{err: err}
				return
			}
			defer resp.Body.Close()

			if resp.StatusCode != http.StatusOK {
				ch <- chunkMsg{err: fmt.Errorf("server returned status: %d %s", resp.StatusCode, resp.Status)}
				return
			}

			reader := bufio.NewReader(resp.Body)
			for {
				line, err := reader.ReadString('\n')
				if err != nil {
					ch <- chunkMsg{done: true}
					return
				}

				line = strings.TrimSpace(line)
				if line == "" {
					continue
				}

				if !strings.HasPrefix(line, "data: ") {
					continue
				}
				dataStr := strings.TrimPrefix(line, "data: ")
				if dataStr == "" {
					continue
				}

				var ev sseEvent
				if err := json.Unmarshal([]byte(dataStr), &ev); err != nil {
					ch <- chunkMsg{content: dataStr, ch: ch}
					continue
				}

				out := agent.HandleEvent(ev)
				if out.done || out.err != nil {
					ch <- out
					return
				}
				if out.content != "" {
					out.ch = ch
					ch <- out
				}
			}
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
		if m.isStreaming {
			m.refreshViewport()
		}
		cmds = append(cmds, cmd)
		return *m, tea.Batch(cmds...)

	case chunkMsg:
		if msg.err != nil {
			m.messages = append(m.messages, message{role: "system", text: "❌ **Error:** " + msg.err.Error()})
			m.isStreaming = false
			m.streamingMessage = ""
			m.refreshViewport()
			return *m, nil
		}
		if msg.done {
			if m.streamingMessage != "" {
				m.messages = append(m.messages, message{role: "ai", text: m.streamingMessage})
				m.streamingMessage = ""
			}
			if msg.content != "" {
				m.messages = append(m.messages, message{role: "system", text: msg.content})
				m.isStreaming = false
				m.messages = append(m.messages, message{role: "seperator", text: m.agent.AgentLabel()})
				m.messages = append(m.messages, message{role: "system", text: "Press Enter to continue to the next step."})
				m.refreshViewport()
				return *m, continueFromAgent(m.agent.Kind())
			}
			m.isStreaming = false
			m.refreshViewport()
			return *m, nil
		}
		m.streamingMessage += msg.content
		m.refreshViewport()
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
			if m.invokeAgentWithEnter {
				m.invokeAgentWithEnter = false
				m.messages = append(m.messages, message{role: "system", text: "Starting " + m.agent.AgentLabel() + "..."})
				m.refreshViewport()
				return *m, streamMessage(m.agent, m.conversationID, m.userid, "")
			}
			text := strings.TrimSpace(m.input.Value())
			if text == "" {
				return *m, nil
			}
			m.messages = append(m.messages, message{role: "user", text: text})
			m.input.SetValue("")
			m.isStreaming = true
			m.refreshViewport()
			cmds = append(cmds, streamMessage(m.agent, m.conversationID, m.userid, text))
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
