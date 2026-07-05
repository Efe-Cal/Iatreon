package tui

import (
	"context"
	"encoding/json"
	"strings"
	"time"

	"github.com/charmbracelet/bubbles/viewport"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

type historyFocus int

const (
	historyFocusSessions historyFocus = iota
	historyFocusSections
	historyFocusContent
)

type historyModel struct {
	userid string
	worker *Worker

	sessions []historySession
	err      string
	loading  bool
	close    bool

	sessionCursor int
	sectionCursor int
	focus         historyFocus
	fullscreen    bool

	content viewport.Model
	width   int
	height  int
}

type historySession struct {
	ID        string           `json:"id"`
	CreatedAt string           `json:"created_at"`
	Sections  []historySection `json:"sections"`
}

type historySection struct {
	ID        string          `json:"id"`
	Type      string          `json:"type"`
	Title     string          `json:"title"`
	CreatedAt string          `json:"created_at"`
	Content   json.RawMessage `json:"content"`
}

type historyLoadedMsg struct {
	sessions []historySession
	err      error
}

var (
	historyPanelStyle = lipgloss.NewStyle().
				Border(lipgloss.NormalBorder()).
				BorderForeground(colorBorder)

	historyFocusStyle = historyPanelStyle.Copy().
				BorderForeground(colorPrimary)
)

func newHistoryModel(userid string, worker *Worker) historyModel {
	return historyModel{
		userid:  userid,
		worker:  worker,
		loading: true,
		focus:   historyFocusSessions,
		content: viewport.New(0, 0),
	}
}

func (m historyModel) Init() tea.Cmd {
	return m.load()
}

func (m *historyModel) SetSize(w, h int) {
	m.width, m.height = w, h
	m.content.Width = max(1, w-4)
	m.content.Height = max(1, h-4)
	m.refreshContent()
}

func (m historyModel) footer() []string {
	if m.fullscreen {
		return []string{"↑/↓ Navigate", "f Unfocus", "Esc Back", "Ctrl+C Quit"}
	}
	return []string{"↑/↓ Navigate", "←/→ Focus", "Tab Focus", "f Focus", "Esc Back", "Ctrl+C Quit"}
}

func (m historyModel) load() tea.Cmd {
	return func() tea.Msg {
		if m.worker == nil {
			return historyLoadedMsg{}
		}

		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		resp, err := m.worker.Call(ctx, "history/list", struct {
			UserID string `json:"user_id"`
		}{UserID: m.userid})
		if err != nil {
			return historyLoadedMsg{err: err}
		}

		var body struct {
			Sessions []historySession `json:"sessions"`
		}
		if err := decodeWorkerResult(resp, &body); err != nil {
			return historyLoadedMsg{err: err}
		}
		return historyLoadedMsg{sessions: body.Sessions}
	}
}

func (m historyModel) Update(msg tea.Msg) (historyModel, tea.Cmd) {
	var cmd tea.Cmd

	switch msg := msg.(type) {
	case historyLoadedMsg:
		m.loading = false
		if msg.err != nil {
			m.err = msg.err.Error()
		} else {
			m.sessions = msg.sessions
		}
		m.refreshContent()
		return m, nil

	case tea.KeyMsg:
		switch msg.String() {
		case "esc":
			if m.fullscreen {
				m.fullscreen = false
				return m, nil
			}
			m.close = true
			return m, nil
		case "f":
			m.fullscreen = !m.fullscreen
			m.refreshContent()
			return m, nil
		case "tab", "right":
			m.focus = (m.focus + 1) % 3
			return m, nil
		case "shift+tab", "left":
			m.focus = (m.focus + 2) % 3
			return m, nil
		case "up", "k":
			m.move(-1)
			return m, nil
		case "down", "j":
			m.move(1)
			return m, nil
		}
	}

	if m.focus == historyFocusContent {
		m.content, cmd = m.content.Update(msg)
	}
	return m, cmd
}

func (m *historyModel) move(delta int) {
	switch m.focus {
	case historyFocusSessions:
		if len(m.sessions) == 0 {
			return
		}
		m.sessionCursor = clamp(m.sessionCursor+delta, 0, len(m.sessions)-1)
		m.sectionCursor = 0
		m.content.GotoTop()
		m.refreshContent()
	case historyFocusSections:
		sections := m.sections()
		if len(sections) == 0 {
			return
		}
		m.sectionCursor = clamp(m.sectionCursor+delta, 0, len(sections)-1)
		m.content.GotoTop()
		m.refreshContent()
	case historyFocusContent:
		if delta < 0 {
			m.content.LineUp(1)
		} else {
			m.content.LineDown(1)
		}
	}
}

func (m historyModel) sections() []historySection {
	if len(m.sessions) == 0 || m.sessionCursor >= len(m.sessions) {
		return nil
	}
	return m.sessions[m.sessionCursor].Sections
}

func (m historyModel) selectedSection() *historySection {
	sections := m.sections()
	if len(sections) == 0 || m.sectionCursor >= len(sections) {
		return nil
	}
	return &sections[m.sectionCursor]
}

func (m *historyModel) refreshContent() {
	if m.content.Width <= 0 {
		return
	}
	text := "_Select a section to view its content._"
	if section := m.selectedSection(); section != nil {
		text = section.markdown()
	}
	m.content.SetContent(renderReportMarkdown(text, m.content.Width))
}

func (s historySection) markdown() string {
	if s.Type == "diagnosis" {
		return formatDiagnosisReport(s.Content)
	}
	var text string
	if err := json.Unmarshal(s.Content, &text); err == nil {
		if strings.TrimSpace(text) == "" {
			return "_No content available._"
		}
		return text
	}
	if len(s.Content) == 0 || string(s.Content) == "null" {
		return "_No content available._"
	}
	return string(s.Content)
}

func (m historyModel) View() string {
	if m.width == 0 {
		return ""
	}
	if m.loading {
		return historyPanelStyle.Width(max(1, m.width-2)).Height(max(1, m.height-2)).Render("Loading history...")
	}
	if m.err != "" {
		return historyPanelStyle.Width(max(1, m.width-2)).Height(max(1, m.height-2)).Render(errorStyle.Render(m.err))
	}

	if m.fullscreen {
		switch m.focus {
		case historyFocusSessions:
			return m.panel("Sessions", m.sessionList(m.width-4, m.height-4), m.width, m.height, true)
		case historyFocusSections:
			return m.panel("Sections", m.sectionList(m.width-4, m.height-4), m.width, m.height, true)
		default:
			m.content.Width = max(1, m.width-4)
			m.content.Height = max(1, m.height-4)
			m.refreshContent()
			return m.panel("Content", m.content.View(), m.width, m.height, true)
		}
	}

	sessionW := max(16, m.width/4)
	sectionW := max(18, m.width/4)
	contentW := m.width - sessionW - sectionW - 2
	if contentW < 20 {
		contentW = 20
		sectionW = max(12, m.width-sessionW-contentW-2)
	}

	m.content.Width = max(1, contentW-4)
	m.content.Height = max(1, m.height-4)
	m.refreshContent()

	return lipgloss.JoinHorizontal(
		lipgloss.Top,
		m.panel("Sessions", m.sessionList(sessionW-4, m.height-4), sessionW, m.height, m.focus == historyFocusSessions),
		" ",
		m.panel("Sections", m.sectionList(sectionW-4, m.height-4), sectionW, m.height, m.focus == historyFocusSections),
		" ",
		m.panel("Content", m.content.View(), contentW, m.height, m.focus == historyFocusContent),
	)
}

func (m historyModel) panel(title, body string, w, h int, focused bool) string {
	style := historyPanelStyle
	if focused {
		style = historyFocusStyle
	}
	contentW := max(1, w-style.GetHorizontalFrameSize())
	contentH := max(1, h-style.GetVerticalFrameSize())
	content := lipgloss.JoinVertical(lipgloss.Left, titleStyle.Width(contentW).Render(title), body)
	return style.Width(contentW).Height(contentH).Render(content)
}

func (m historyModel) sessionList(w, h int) string {
	if len(m.sessions) == 0 {
		return "_No saved chat sessions yet._"
	}
	rows := make([]string, 0, len(m.sessions))
	for i, session := range m.sessions {
		title := shortID(session.ID)
		if session.CreatedAt != "" {
			title += "  " + session.CreatedAt[:min(len(session.CreatedAt), 10)]
		}
		rows = append(rows, row(title, i == m.sessionCursor, w))
	}
	return visibleRows(rows, m.sessionCursor, h)
}

func (m historyModel) sectionList(w, h int) string {
	sections := m.sections()
	if len(sections) == 0 {
		return "_No saved sections in this session._"
	}
	rows := make([]string, 0, len(sections))
	for i, section := range sections {
		rows = append(rows, row(section.Title, i == m.sectionCursor, w))
	}
	return visibleRows(rows, m.sectionCursor, h)
}

func row(text string, selected bool, width int) string {
	prefix := "  "
	if selected {
		prefix = "> "
	}
	return clip(prefix+text, width)
}

func visibleRows(rows []string, cursor, height int) string {
	if height <= 0 || len(rows) <= height {
		return strings.Join(rows, "\n")
	}
	start := cursor - height/2
	if start < 0 {
		start = 0
	}
	if start+height > len(rows) {
		start = len(rows) - height
	}
	return strings.Join(rows[start:start+height], "\n")
}

func shortID(id string) string {
	if len(id) <= 8 {
		return id
	}
	return id[:8]
}

func clip(s string, width int) string {
	if width <= 0 {
		return ""
	}
	runes := []rune(s)
	if len(runes) <= width {
		return s
	}
	if width <= 1 {
		return string(runes[:width])
	}
	return string(runes[:width-1]) + "…"
}

func clamp(value, low, high int) int {
	if value < low {
		return low
	}
	if value > high {
		return high
	}
	return value
}
