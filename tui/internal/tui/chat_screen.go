package tui

import (
	"bufio"
	"bytes"
	"crypto/rand"
	"encoding/json"
	"fmt"
	"net/http"
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

func newChatModel(userid string) chatModel {
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
	vp.SetContent(welcomeScreen())

	sp := spinner.New(spinner.WithSpinner(spinner.Dot))

	return chatModel{
		userid:         userid,
		conversationID: generateUUID(),
		messages: []message{
			{role: "system", text: "Welcome to Iatreon. Let's start by taking an intake."},
		},
		input:        ti,
		viewport:     vp,
		spinner:      sp,
		aiRenderer:   aiRenderer,
		userRenderer: userRenderer,
	}
}

func welcomeScreen() string {
	return titleStyle.Render("Iatreon") + "\n\n" +
		systemStyle.Render("Type a message below and press enter to chat with the intake agent.")
}

func (m *chatModel) Init() tea.Cmd {
	return tea.Batch(textinput.Blink, m.spinner.Tick)
}

func (m *chatModel) SetSize(w, h int) {
	m.width, m.height = w, h

	headerH := lipgloss.Height(titleStyle.Width(w - 2).Render("Iatreon"))
	statusH := lipgloss.Height(statusStyle.Width(w - 2).Render("Enter to send · Esc to log out · Ctrl+C to quit"))
	inputH := lipgloss.Height(m.input.View()) // bubbles textinput knows its own height

	vpH := h - headerH - inputH - statusH
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
		sb.WriteString(aiLabelStyle.Render("Iatreon:"))
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

func (m *chatModel) renderMessage(msg message) string {
	switch msg.role {
	case "user":
		label := userLabelStyle.Render("You :")
		body := m.renderMarkdown(msg.text, true)
		return lipgloss.JoinVertical(lipgloss.Left, label, body)
	case "ai":
		label := aiLabelStyle.Render("Iatreon:")
		body := m.renderMarkdown(msg.text, false)
		return lipgloss.JoinVertical(lipgloss.Left, label, body)
	case "system":
		return systemStyle.Render(msg.text)
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

const apiURL = "http://localhost:8000/chat/intake"

func waitForChunk(ch chan chunkMsg) tea.Cmd {
	return func() tea.Msg {
		return <-ch
	}
}

func streamMessage(conversationID, userid, msg string) tea.Cmd {
	return func() tea.Msg {
		ch := make(chan chunkMsg)
		go func() {
			defer close(ch)

			payload := struct {
				ConversationID string `json:"conversation_id"`
				Message        string `json:"message"`
			}{
				ConversationID: conversationID,
				Message:        msg,
			}
			reqBytes, err := json.Marshal(payload)
			if err != nil {
				ch <- chunkMsg{err: err}
				return
			}

			req, err := http.NewRequest("POST", apiURL, bytes.NewReader(reqBytes))
			if err != nil {
				ch <- chunkMsg{err: err}
				return
			}
			req.Header.Set("Content-Type", "application/json")
			req.Header.Set("X-User-ID", userid)

			client := &http.Client{}
			resp, err := client.Do(req)
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

				if strings.HasPrefix(line, "data: ") {
					dataStr := strings.TrimPrefix(line, "data: ")
					if dataStr == "" {
						continue
					}

					var sseEvent struct {
						Type    string      `json:"type"`
						Content interface{} `json:"content"`
						Name    string      `json:"name"`
					}
					if err := json.Unmarshal([]byte(dataStr), &sseEvent); err != nil {
						ch <- chunkMsg{content: dataStr, ch: ch}
						continue
					}

					switch sseEvent.Type {
					case "intake_complete":
						ch <- chunkMsg{content: "\n\n✅ **Intake completed.** Your profile has been saved.", done: true}
						return
					case "message":
						if contentStr, ok := sseEvent.Content.(string); ok {
							ch <- chunkMsg{content: contentStr, ch: ch}
						}
					case "tool_start":
						ch <- chunkMsg{content: fmt.Sprintf("\n> 🔍 *Running: %s…*\n", sseEvent.Name), ch: ch}
					case "tool_end":
						ch <- chunkMsg{content: fmt.Sprintf("\n> ✔ *%s done.*\n\n", sseEvent.Name), ch: ch}
					}
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
			}
			m.isStreaming = false
			m.refreshViewport()
			return *m, nil
		}
		m.streamingMessage += msg.content
		m.refreshViewport()
		return *m, waitForChunk(msg.ch)

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
			if text == "" {
				return *m, nil
			}
			m.messages = append(m.messages, message{role: "user", text: text})
			m.input.SetValue("")
			m.isStreaming = true
			m.refreshViewport()
			cmds = append(cmds, streamMessage(m.conversationID, m.userid, text))
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

	header := titleStyle.Width(m.width - 2).Render("Iatreon")

	// Update viewport content right before drawing so the live stream is
	// reflected even when the parent doesn't repaint on every chunk.
	m.viewport.SetContent(m.renderHistory())

	status := statusStyle.Width(m.width - 2).Render("Enter to send · Esc to log out · Ctrl+C to quit")

	body := lipgloss.JoinVertical(
		lipgloss.Left,
		header,
		m.viewport.View(),
		m.input.View(),
		status,
	)
	return body
}
