package tui

import (
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

type dashboardModel struct {
	userid         string
	width          int
	height         int
	cursor         int
	action         dashboardAction
	placeholderMsg string
}

type dashboardAction int

const (
	dashboardActionNone dashboardAction = iota
	dashboardActionStartIntake
	dashboardActionStartDoctor
	dashboardActionHistory
)

type dashboardCard struct {
	title       string
	description string
	color       lipgloss.Color
}

var dashboardCards = []dashboardCard{
	{title: "Start Intake", description: "Begin a new patient intake conversation with the AI assistant.", color: colorPrimary},
	{title: "See the Doctor", description: "Get a differential diagnosis and clinical assessment.", color: lipgloss.Color("#7C3AED")},
	{title: "History", description: "Review saved chat sessions, sections, and reports.", color: lipgloss.Color("#0891B2")},
	{title: "Settings", description: "Configure your preferences and system settings.", color: lipgloss.Color("#D97706")},
}

func newDashboardModel(userid string) dashboardModel {
	return dashboardModel{
		userid: userid,
		cursor: 0,
	}
}

func (m *dashboardModel) SetSize(w, h int) {
	m.width = w
	m.height = h
}

func (m dashboardModel) Init() tea.Cmd { return nil }

func (m dashboardModel) footer() []string {
	if m.placeholderMsg != "" {
		return []string{"Enter Dismiss", "Ctrl+C Quit"}
	}
	return dashboardFooter
}

func (m dashboardModel) Update(msg tea.Msg) (dashboardModel, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.SetSize(msg.Width, msg.Height)
		return m, nil

	case tea.KeyMsg:
		if m.placeholderMsg != "" {
			switch msg.String() {
			case "ctrl+c":
				return m, tea.Quit
			case "enter", "esc":
				m.placeholderMsg = ""
				return m, nil
			}
		}

		switch msg.String() {
		case "ctrl+c":
			return m, tea.Quit
		case "tab", "right", "down":
			m.cursor = (m.cursor + 1) % len(dashboardCards)
			m.placeholderMsg = ""
			return m, nil
		case "shift+tab", "left", "up":
			m.cursor = (m.cursor - 1 + len(dashboardCards)) % len(dashboardCards)
			m.placeholderMsg = ""
			return m, nil
		case "enter":
			switch m.cursor {
			case 0:
				m.action = dashboardActionStartIntake
				return m, nil
			case 1:
				m.action = dashboardActionStartDoctor
				return m, nil
			case 2:
				m.action = dashboardActionHistory
				return m, nil
			case 3:
				m.placeholderMsg = "🚧 Settings are not yet available.\n\nFuture settings will include notification preferences,\ntheme options, and API configuration."
				return m, nil
			}
		}
	}

	return m, nil
}

func (m dashboardModel) View() string {
	if m.width == 0 {
		return ""
	}

	cards := m.renderCards()

	if m.placeholderMsg != "" {
		body := lipgloss.JoinVertical(lipgloss.Center,
			m.renderPlaceholder(),
		)
		body = lipgloss.NewStyle().Width(m.width).Align(lipgloss.Center).Render(body)
		pad := m.height - lipgloss.Height(body)
		if pad < 0 {
			pad = 0
		}
		return lipgloss.JoinVertical(lipgloss.Top,
			strings.Repeat("\n", pad/2),
			body,
		)
	}

	// Compute the maximum possible info height so the layout never shifts.
	maxInfoH := m.maxInfoHeight()
	infoPadded := m.renderInfoPadded(maxInfoH)

	body := lipgloss.JoinVertical(lipgloss.Center,
		"",
		cards,
		"",
		infoPadded,
	)
	body = lipgloss.NewStyle().Width(m.width).Align(lipgloss.Center).Render(body)
	bodyH := lipgloss.Height(body)
	pad := m.height - bodyH
	if pad < 0 {
		pad = 0
	}
	topPad := pad / 2
	bottomPad := pad - topPad

	return lipgloss.JoinVertical(lipgloss.Top,
		strings.Repeat("\n", topPad),
		body,
		strings.Repeat("\n", bottomPad),
	)
}

func (m dashboardModel) infoStyle() lipgloss.Style {
	return lipgloss.NewStyle().
		Width(m.infoWidth()).
		Padding(0, 1).
		Foreground(colorSystem).
		Italic(true)
}

func (m dashboardModel) infoWidth() int {
	return max(1, min(35, m.width-6))
}

// maxInfoHeight returns the tallest possible info description in lines.
func (m dashboardModel) maxInfoHeight() int {
	maxH := 0
	infoBox := m.infoStyle()
	for _, card := range dashboardCards {
		rendered := infoBox.Render(card.description)
		h := lipgloss.Height(rendered)
		if h > maxH {
			maxH = h
		}
	}
	return maxH
}

// renderInfoPadded renders the info description padded to a fixed height.
func (m dashboardModel) renderInfoPadded(targetH int) string {
	card := dashboardCards[m.cursor]
	return m.infoStyle().
		Height(targetH).
		Render(card.description)
}

func (m dashboardModel) renderCards() string {
	btnWidth := max(1, min(30, m.width-6))

	var renderedCards []string
	for i, card := range dashboardCards {
		renderedCards = append(renderedCards, m.renderCard(card, i, btnWidth))
	}

	containerStyle := lipgloss.NewStyle().
		Padding(0, 2).
		Border(lipgloss.RoundedBorder()).
		BorderForeground(colorBorder)

	return containerStyle.Render(
		lipgloss.JoinVertical(lipgloss.Center, renderedCards...),
	)
}

func (m dashboardModel) renderCard(card dashboardCard, index int, width int) string {
	isSelected := index == m.cursor

	btnStyle := lipgloss.NewStyle().
		Width(width).
		Padding(0, 2).
		Bold(isSelected)

	if isSelected {
		btnStyle = btnStyle.Foreground(card.color)
	} else {
		btnStyle = btnStyle.Foreground(colorMuted)
	}

	marker := "  "
	if isSelected {
		marker = "▸ "
	}

	title := btnStyle.Render(marker + card.title)

	// Add a thin separator between buttons (except after the last)
	if index < len(dashboardCards)-1 {
		sep := lipgloss.NewStyle().
			Width(width).
			Foreground(colorBorder).
			Render(strings.Repeat("─", width))
		return lipgloss.JoinVertical(lipgloss.Left, title, sep)
	}

	return title
}

func (m dashboardModel) renderPlaceholder() string {
	boxStyle := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(colorAccent).
		Padding(2, 4).
		Width(m.width - 8).
		Align(lipgloss.Center)

	content := lipgloss.JoinVertical(lipgloss.Center,
		boxStyle.Render(m.placeholderMsg),
		"",
		hintStyle.Render("Press Enter to dismiss · Esc to go back"),
	)

	return content
}
