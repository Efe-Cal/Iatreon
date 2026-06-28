package tui

import (
	"encoding/json"
	"strings"
	"testing"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

func TestParseCitationsMapAndList(t *testing.T) {
	fromMap := parseCitations(json.RawMessage(`{
		"2": {"title": "Second", "type": "article"},
		"1": {"title": "First", "type": "book_section", "citation_num": 7}
	}`))
	if len(fromMap) != 2 {
		t.Fatalf("expected map citations, got %d", len(fromMap))
	}
	if fromMap[0].Title == "Second" && fromMap[0].CitationNumber != 2 {
		t.Fatalf("map key should fill missing citation number: %+v", fromMap[0])
	}

	fromList := parseCitations(json.RawMessage(`[{"title": "Only", "citation_num": 3}]`))
	if len(fromList) != 1 || fromList[0].CitationNumber != 3 {
		t.Fatalf("expected list citation to survive parse: %+v", fromList)
	}
}

func TestReportModelSortsAndFillsCitationNumbers(t *testing.T) {
	m := newReportModel("Report [1]", []citation{
		{Title: "B", CitationNumber: 2},
		{Title: "A"},
	}, "research-1", "user-1", nil)

	if m.citations[0].Title != "A" || m.citations[0].CitationNumber != 1 {
		t.Fatalf("expected missing citation number to be filled after sort: %+v", m.citations)
	}
	if m.loadCitationText() != nil {
		t.Fatal("nil session key should not try to load citation text")
	}
}

func TestCitationMarkdownIncludesAvailableFields(t *testing.T) {
	got := citationMarkdown(citation{
		Title:          "Paper",
		Type:           "article",
		CitationNumber: 4,
		URL:            "https://example.test",
	}, "Full text", false, "")

	for _, want := range []string{"Citation [4]", "Paper", "article", "https://example.test", "Full Text", "Full text"} {
		if !strings.Contains(got, want) {
			t.Fatalf("citation markdown missing %q:\n%s", want, got)
		}
	}
}

func TestReportPanelFillsBodyWithoutCitations(t *testing.T) {
	m := newReportModel("# Header\n\nBody", nil, "", "user-1", nil)
	m.SetSize(100, 30)

	view := m.View()
	if got := renderedWidth(view); got != 100 {
		t.Fatalf("report panel width=%d, want 100", got)
	}
	if got := lipgloss.Height(view); got != 30 {
		t.Fatalf("report panel height=%d, want 30", got)
	}
}

func TestReportPanelsFillBodyWithSideBySideCitations(t *testing.T) {
	m := newReportModel("# Header\n\nBody", []citation{{Title: "Paper", CitationNumber: 1}}, "", "user-1", nil)
	m.showCitations = true
	m.SetSize(120, 30)

	view := m.View()
	if got := renderedWidth(view); got != 120 {
		t.Fatalf("side-by-side report width=%d, want 120", got)
	}
	if got := lipgloss.Height(view); got != 30 {
		t.Fatalf("side-by-side report height=%d, want 30", got)
	}
}

func TestReportPanelsFillBodyWithStackedCitations(t *testing.T) {
	m := newReportModel("# Header\n\nBody", []citation{{Title: "Paper", CitationNumber: 1}}, "", "user-1", nil)
	m.showCitations = true
	m.SetSize(70, 30)

	view := m.View()
	if got := renderedWidth(view); got != 70 {
		t.Fatalf("stacked report width=%d, want 70", got)
	}
	if got := lipgloss.Height(view); got != 30 {
		t.Fatalf("stacked report height=%d, want 30", got)
	}
}

func TestReportMarkdownHeadingsStayVisible(t *testing.T) {
	got := renderReportMarkdown("# Research Header\n\nBody", 80)
	if !strings.Contains(got, "Research Header") {
		t.Fatalf("rendered markdown should include heading text:\n%s", got)
	}
}

func TestReportScreenBodyHeightUsesWrappedFooter(t *testing.T) {
	m := NewModel("ff6b65d2-bee0-4565-ad42-0d7ccb1f41a9", true)
	m.active = reportScreen
	m.report = newReportModel("# Header\n\nBody", []citation{{Title: "Paper", CitationNumber: 1}}, "", "user-1", nil)
	m.report.showCitations = true

	updated, _ := m.Update(tea.WindowSizeMsg{Width: 70, Height: 30})
	got, ok := updated.(model)
	if !ok {
		t.Fatalf("updated model has type %T", updated)
	}

	header, footer := got.chromeFor(reportScreen)
	wantBodyH := 30 - lipgloss.Height(renderHeader(header, 70)) - lipgloss.Height(renderFooter(footer, 70))
	if got.report.height != wantBodyH {
		t.Fatalf("report body height=%d, want %d", got.report.height, wantBodyH)
	}
	if gotH := lipgloss.Height(got.View()); gotH != 30 {
		t.Fatalf("full report screen height=%d, want 30", gotH)
	}
}

func renderedWidth(s string) int {
	width := 0
	for _, line := range strings.Split(s, "\n") {
		width = max(width, lipgloss.Width(line))
	}
	return width
}
