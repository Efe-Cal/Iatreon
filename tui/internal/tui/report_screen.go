package tui

import (
	"context"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/charmbracelet/bubbles/viewport"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/glamour"
	"github.com/charmbracelet/lipgloss"
)

type reportModel struct {
	report            string
	citations         []citation
	researchSessionID string
	userid            string
	worker            *Worker

	reportViewport   viewport.Model
	citationViewport viewport.Model
	citationTexts    map[int]string

	width, height   int
	showCitations   bool
	focusCitation   bool
	current         int
	loadingCitation int
	citationErr     string
	close           bool
}

type citationTextMsg struct {
	citationNum int
	text        string
	err         error
}

func newReportModel(report string, citations []citation, researchSessionID, userid string, worker *Worker) reportModel {
	sort.SliceStable(citations, func(i, j int) bool {
		return citations[i].CitationNumber < citations[j].CitationNumber
	})
	for i := range citations {
		if citations[i].CitationNumber == 0 {
			citations[i].CitationNumber = i + 1
		}
	}
	m := reportModel{
		report:            report,
		citations:         citations,
		researchSessionID: researchSessionID,
		userid:            userid,
		worker:            worker,
		reportViewport:    viewport.New(0, 0),
		citationViewport:  viewport.New(0, 0),
		citationTexts:     map[int]string{},
	}
	m.SetSize(100, 30)
	return m
}

var (
	reportStyle = lipgloss.NewStyle().
			Border(lipgloss.NormalBorder(), false, true, false, false).
			BorderForeground(colorBorder)

	reportFocusStyle = reportStyle.Copy().
				BorderForeground(colorPrimary)

	citationStyle = lipgloss.NewStyle().
			Border(lipgloss.NormalBorder(), false, false, false, true).
			BorderForeground(colorBorder)

	citationFocusStyle = citationStyle.Copy().
				BorderForeground(colorAccent)
)

func (m reportModel) Init() tea.Cmd { return nil }

func (m *reportModel) SetSize(w, h int) {
	m.width, m.height = w, h
	if w < 20 {
		w = 20
	}
	if h < 5 {
		h = 5
	}

	reportW := w
	reportH := h
	citationW := 0
	citationH := h
	if m.showCitations && len(m.citations) > 0 && w >= 80 {
		citationW = w / 3
		reportW = w - citationW - 1
	} else if m.showCitations && len(m.citations) > 0 {
		citationW = w
		reportH = h / 2
		citationH = h - reportH
	}

	m.reportViewport.Width = max(1, reportW-reportStyle.GetHorizontalFrameSize())
	m.reportViewport.Height = max(1, reportH-reportStyle.GetVerticalFrameSize())
	m.citationViewport.Width = max(1, citationW-citationStyle.GetHorizontalFrameSize())
	m.citationViewport.Height = max(1, citationH-citationStyle.GetVerticalFrameSize())
	m.refresh()
}

func (m *reportModel) refresh() {
	m.reportViewport.SetContent(renderReportMarkdown(formatReferences(m.report), m.reportViewport.Width))
	if len(m.citations) == 0 {
		m.citationViewport.SetContent("")
		return
	}
	if m.current < 0 {
		m.current = 0
	}
	if m.current >= len(m.citations) {
		m.current = len(m.citations) - 1
	}
	c := m.citations[m.current]
	full := m.citationTexts[c.CitationNumber]
	m.citationViewport.SetContent(renderReportMarkdown(citationMarkdown(c, full, m.loadingCitation == c.CitationNumber, m.citationErr), m.citationViewport.Width))
}

func renderReportMarkdown(s string, width int) string {
	if strings.TrimSpace(s) == "" {
		s = "_No content available._"
	}
	r, err := glamour.NewTermRenderer(glamour.WithAutoStyle(), glamour.WithWordWrap(max(20, width)))
	if err != nil {
		return s
	}
	out, err := r.Render(s)
	if err != nil {
		return s
	}
	return out
}

func formatReferences(s string) string {
	i := strings.Index(strings.ToLower(s), "## references")
	if i < 0 {
		return s
	}
	return s[:i] + regexp.MustCompile(`\s+(\[\d+\])`).ReplaceAllString(s[i:], "\n\n$1")
}

func citationMarkdown(c citation, full string, loading bool, loadErr string) string {
	var b strings.Builder
	if c.CitationNumber > 0 {
		fmt.Fprintf(&b, "# Citation [%d]\n\n", c.CitationNumber)
	} else {
		b.WriteString("# Citation\n\n")
	}
	for _, row := range [][2]string{
		{"Title", c.Title},
		{"Type", c.Type},
		{"Query", c.Query},
		{"DOI", c.DOI},
		{"URL", c.URL},
		{"ID", c.ID},
	} {
		if strings.TrimSpace(row[1]) != "" {
			fmt.Fprintf(&b, "**%s:** %s\n\n", row[0], row[1])
		}
	}
	if loading {
		b.WriteString("_Loading full text..._\n\n")
	}
	if loadErr != "" {
		fmt.Fprintf(&b, "_%s_\n\n", loadErr)
	}
	if strings.TrimSpace(full) != "" {
		fmt.Fprintf(&b, "## Full Text\n\n%s\n", full)
	}
	return b.String()
}

func (m reportModel) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	var cmd tea.Cmd

	if msg, ok := msg.(citationTextMsg); ok {
		if msg.err != nil {
			m.citationErr = msg.err.Error()
		} else {
			if strings.TrimSpace(msg.text) == "" {
				msg.text = "_No full text available._"
			}
			m.citationTexts[msg.citationNum] = msg.text
			m.citationErr = ""
		}
		m.loadingCitation = 0
		m.refresh()
		return m, nil
	}

	if key, ok := msg.(tea.KeyMsg); ok {
		switch key.String() {
		case "esc":
			m.close = true
			return m, nil
		case "c":
			m.showCitations = !m.showCitations
			m.focusCitation = m.showCitations
			m.SetSize(m.width, m.height)
			if m.showCitations {
				cmd := m.loadCitationText()
				return m, cmd
			}
			return m, nil
		case "tab":
			if m.showCitations {
				m.focusCitation = !m.focusCitation
			}
			return m, nil
		case "j":
			if m.focusCitation && m.current < len(m.citations)-1 {
				m.current++
				m.citationViewport.GotoTop()
				m.refresh()
				cmd := m.loadCitationText()
				return m, cmd
			}
		case "k":
			if m.focusCitation && m.current > 0 {
				m.current--
				m.citationViewport.GotoTop()
				m.refresh()
				cmd := m.loadCitationText()
				return m, cmd
			}
		}
	}

	if m.focusCitation && m.showCitations {
		m.citationViewport, cmd = m.citationViewport.Update(msg)
	} else {
		m.reportViewport, cmd = m.reportViewport.Update(msg)
	}
	return m, cmd
}

func (m *reportModel) loadCitationText() tea.Cmd {
	if len(m.citations) == 0 || m.researchSessionID == "" || m.worker == nil {
		return nil
	}
	num := m.citations[m.current].CitationNumber
	if num == 0 || m.citationTexts[num] != "" || m.loadingCitation == num {
		return nil
	}
	m.loadingCitation = num
	m.citationErr = ""
	m.refresh()

	return func() tea.Msg {
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		resp, err := m.worker.Call(ctx, "research/citation", struct {
			UserID            string `json:"user_id"`
			ResearchSessionID string `json:"research_session_id"`
			CitationNum       int    `json:"citation_num"`
		}{m.userid, m.researchSessionID, num})
		if err != nil {
			return citationTextMsg{citationNum: num, err: err}
		}
		var body struct {
			Text string `json:"text"`
		}
		if err := decodeWorkerResult(resp, &body); err != nil {
			return citationTextMsg{citationNum: num, err: err}
		}
		return citationTextMsg{citationNum: num, text: body.Text}
	}
}

func (m reportModel) View() string {
	reportPanel := reportStyle
	if !m.focusCitation {
		reportPanel = reportFocusStyle
	}
	reportPanelW := m.reportViewport.Width + reportPanel.GetHorizontalPadding()
	reportPanelH := m.reportViewport.Height + reportPanel.GetVerticalPadding()
	reportPanel = reportPanel.Width(reportPanelW).Height(reportPanelH)

	if !m.showCitations || len(m.citations) == 0 {
		return reportPanel.Render(m.reportViewport.View())
	}

	citationPanel := citationStyle
	if m.focusCitation {
		citationPanel = citationFocusStyle
	}
	citationPanelW := m.citationViewport.Width + citationPanel.GetHorizontalPadding()
	citationPanelH := m.citationViewport.Height + citationPanel.GetVerticalPadding()
	citationPanel = citationPanel.Width(citationPanelW).Height(citationPanelH)

	report := reportPanel.Render(m.reportViewport.View())
	citation := citationPanel.Render(m.citationViewport.View())
	if m.width < 80 {
		return lipgloss.JoinVertical(lipgloss.Left, report, citation)
	}
	return lipgloss.JoinHorizontal(lipgloss.Top, report, " ", citation)
}
