package tui

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestFormatDiagnosisReport(t *testing.T) {
	raw := json.RawMessage(`{
		"primary_diagnosis": "Migraine",
		"confidence": "moderate",
		"differential": [{
			"condition": "Tension headache",
			"likelihood": "possible",
			"supporting_evidence": ["head pain"],
			"against_evidence": ["photophobia"]
		}],
		"reasoning_summary": "Pattern fits a primary headache syndrome.",
		"recommended_next_steps": ["Follow up with a clinician"],
		"red_flags_to_monitor": ["Worst headache of life"]
	}`)

	got := formatDiagnosisReport(raw)
	for _, want := range []string{"Migraine", "Tension headache", "Follow up with a clinician", "Worst headache of life"} {
		if !strings.Contains(got, want) {
			t.Fatalf("formatted report missing %q:\n%s", want, got)
		}
	}
}
