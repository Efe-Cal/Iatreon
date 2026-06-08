package main

import (
	"bufio"
	"bytes"
	"crypto/rand"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/glamour"
)

// message holds a single chat entry.
type message struct {
	role string // "user", "ai", or "system"
	text string
}

type chatModel struct {
	username         string
	conversationID   string
	input            string
	messages         []message
	logout           bool
	streamingMessage string
	isStreaming      bool
	width            int
	aiRenderer       *glamour.TermRenderer
	userRenderer     *glamour.TermRenderer
}

func generateUUID() string {
	b := make([]byte, 16)
	_, err := rand.Read(b)
	if err != nil {
		return "12345678-1234-5678-1234-567812345678"
	}
	b[6] = (b[6] & 0x0f) | 0x40
	b[8] = (b[8] & 0x3f) | 0x80
	return fmt.Sprintf("%08x-%04x-%04x-%04x-%012x", b[0:4], b[4:6], b[6:8], b[8:10], b[10:])
}

func newChatModel(username string) chatModel {
	aiRenderer, _ := glamour.NewTermRenderer(
		glamour.WithAutoStyle(),
		glamour.WithWordWrap(100),
	)
	userRenderer, _ := glamour.NewTermRenderer(
		glamour.WithAutoStyle(),
		glamour.WithWordWrap(100),
	)
	return chatModel{
		username:       username,
		conversationID: generateUUID(),
		messages: []message{
			{role: "system", text: "Welcome to Iatreon. Let's start by taking an intake."},
		},
		aiRenderer:   aiRenderer,
		userRenderer: userRenderer,
	}
}

// renderMarkdown renders markdown text, fallback to plain text on error.
func (m chatModel) renderMarkdown(text string, isUser bool) string {
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

func streamMessage(conversationID, username, msg string) tea.Cmd {
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
			req.Header.Set("X-User-ID", username)

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

func (m chatModel) Init() tea.Cmd {
	return nil
}

func (m chatModel) Update(msg tea.Msg) (chatModel, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width = msg.Width
		return m, nil

	case chunkMsg:
		if msg.err != nil {
			m.messages = append(m.messages, message{role: "system", text: "❌ **Error:** " + msg.err.Error()})
			m.isStreaming = false
			m.streamingMessage = ""
			return m, nil
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
			return m, nil
		}
		m.streamingMessage += msg.content
		return m, waitForChunk(msg.ch)

	case tea.KeyMsg:
		if m.isStreaming {
			return m, nil
		}
		switch msg.String() {
		case "enter":
			text := strings.TrimSpace(m.input)
			if text != "" {
				m.messages = append(m.messages, message{role: "user", text: text})
				m.input = ""
				m.isStreaming = true
				return m, streamMessage(m.conversationID, m.username, text)
			}
		case "backspace":
			if len([]rune(m.input)) > 0 {
				runes := []rune(m.input)
				m.input = string(runes[:len(runes)-1])
			}
		case "esc":
			m.logout = true
		default:
			m.input += keyInput(msg)
		}
	}

	return m, nil
}

func (m chatModel) View() string {
	var sb strings.Builder

	for _, msg := range m.messages {
		switch msg.role {
		case "user":
			label := "**" + m.username + ":**\n"
			rendered := m.renderMarkdown(label+msg.text, true)
			sb.WriteString(rendered)
		case "ai":
			rendered := m.renderMarkdown(msg.text, false)
			sb.WriteString(rendered)
		case "system":
			rendered := m.renderMarkdown(msg.text, false)
			sb.WriteString(rendered)
		}
	}

	// Live streaming AI response
	if m.streamingMessage != "" {
		rendered := m.renderMarkdown(m.streamingMessage, false)
		sb.WriteString(rendered)
	}

	// Input area
	sb.WriteString("\n")
	inputCursor := m.input + "_"
	if m.isStreaming {
		inputCursor = "⏳ Waiting for response…"
	}
	sb.WriteString("> ")
	sb.WriteString(inputCursor)
	sb.WriteString("\n\n")

	if !m.isStreaming {
		sb.WriteString("Enter to send · Esc to log out · Ctrl+C to quit\n")
	}

	return sb.String()
}
