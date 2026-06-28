package tui

import (
	"encoding/json"
	"strings"
	"testing"
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
