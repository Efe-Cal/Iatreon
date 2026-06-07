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
)

type chatModel struct {
	username         string
	conversationID   string
	input            string
	messages         []string
	logout           bool
	streamingMessage string
	isStreaming      bool
}

func generateUUID() string {
	b := make([]byte, 16)
	_, err := rand.Read(b)
	if err != nil {
		return "12345678-1234-5678-1234-567812345678"
	}
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[0:4], b[4:6], b[6:8], b[8:10], b[10:])
}

func newChatModel(username string) chatModel {
	return chatModel{
		username:       username,
		conversationID: generateUUID(),
		messages: []string{
			"System: Welcome to the chat screen.",
			"System: Type a message and press enter.",
		},
	}
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

func streamMessage(conversationID, username, message string) tea.Cmd {
	return func() tea.Msg {
		ch := make(chan chunkMsg)
		go func() {
			defer close(ch)

			payload := struct {
				ConversationID string `json:"conversation_id"`
				Message        string `json:"message"`
			}{
				ConversationID: conversationID,
				Message:        message,
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
						ch <- chunkMsg{content: "\n\n[Intake Completed]", done: true}
						return
					case "message":
						if contentStr, ok := sseEvent.Content.(string); ok {
							ch <- chunkMsg{content: contentStr, ch: ch}
						}
					case "tool_start":
						ch <- chunkMsg{content: fmt.Sprintf("\n*(Running tool: %s...)*\n", sseEvent.Name), ch: ch}
					case "tool_end":
						ch <- chunkMsg{content: fmt.Sprintf("*(Tool %s completed)*\n\n", sseEvent.Name), ch: ch}
					}
				}
			}
		}()

		return <-ch
	}
}

func (m chatModel) Init() chatModel {
	return chatModel{conversationID: "ac530b9c-e0a3-4b7f-846a-5ceece647814"}
}

func (m chatModel) Update(msg tea.Msg) (chatModel, tea.Cmd) {
	switch msg := msg.(type) {
	case chunkMsg:
		if msg.err != nil {
			m.messages = append(m.messages, "System Error: "+msg.err.Error())
			m.isStreaming = false
			m.streamingMessage = ""
			return m, nil
		}
		if msg.done {
			if m.streamingMessage != "" {
				m.messages = append(m.messages, "AI: "+m.streamingMessage)
				m.streamingMessage = ""
			}
			if msg.content != "" {
				m.messages = append(m.messages, "System: "+msg.content)
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
				m.messages = append(m.messages, fmt.Sprintf("%s: %s", m.username, text))
				m.input = ""
				m.isStreaming = true
				return m, streamMessage(m.conversationID, m.username, text)
			}
		case "backspace":
			if len(m.input) > 0 {
				m.input = m.input[:len(m.input)-1]
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
	input := m.input
	if m.isStreaming {
		input = "[Streaming...]"
	} else if input == "" {
		input = "_"
	} else {
		input += "_"
	}

	lines := []string{
		"Chat",
		"Logged in as " + m.username,
		"Conversation ID: " + m.conversationID,
		"",
	}
	lines = append(lines, m.messages...)
	if m.streamingMessage != "" {
		lines = append(lines, "AI: "+m.streamingMessage)
	}
	lines = append(lines,
		"",
		"> "+input,
		"",
	)
	if m.isStreaming {
		lines = append(lines, "Waiting for response...")
	} else {
		lines = append(lines, "Press enter to send. Press esc to log out. Press ctrl+c to quit.")
	}

	return strings.Join(lines, "\n")
}
