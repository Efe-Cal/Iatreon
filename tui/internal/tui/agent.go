package tui

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net/http"
	"strconv"
)

type AgentKind int

const (
	AgentIntake AgentKind = iota
	AgentDiagnosis
	AgentResearch
	AgentDoctor
)

type toolMessage struct {
	toolID   string
	toolName string
	running  bool
}

type diagnosisReport struct {
	PrimaryDiagnosis     string                      `json:"primary_diagnosis"`
	Confidence           string                      `json:"confidence"`
	Differential         []diagnosisDifferentialItem `json:"differential"`
	ReasoningSummary     string                      `json:"reasoning_summary"`
	RecommendedNextSteps []string                    `json:"recommended_next_steps"`
	RedFlagsToMonitor    []string                    `json:"red_flags_to_monitor"`
}

type diagnosisDifferentialItem struct {
	Condition          string   `json:"condition"`
	Likelihood         string   `json:"likelihood"`
	SupportingEvidence []string `json:"supporting_evidence"`
	AgainstEvidence    []string `json:"against_evidence"`
}

type AgentHandler interface {
	Kind() AgentKind

	Header() string

	Footer() []string

	Welcome() string

	AgentLabel() string

	BuildRequest(conversationID, userid, message, sessionID string, sessionKey []byte) (*http.Request, error)

	HandleEvent(ev sseEvent) chunkMsg
}

// sseEvent mirrors the JSON shape yielded by the FastAPI services:
//
//	{"type": "message",        "content": "..."}
//	{"type": "tool_start",     "name": "..."}
//	{"type": "tool_end",       "name": "..."}
//	{"type": "intake_complete","profile": {...}, "transcript": "..."}
type sseEvent struct {
	Type           string          `json:"type"`
	Content        string          `json:"content"`
	Name           string          `json:"name"`
	Profile        json.RawMessage `json:"profile"`
	Data           json.RawMessage `json:"data"`
	ToolCallID     string          `json:"tool_call_id"`
	SessionID      string          `json:"session_id"`
	ConversationID string          `json:"conversation_id"`
	Recoverable    bool            `json:"recoverable"`
}

func newAgentHandler(kind AgentKind) AgentHandler {
	switch kind {
	case AgentDiagnosis:
		return &diagnosisHandler{}
	case AgentResearch:
		return &researchHandler{}
	case AgentDoctor:
		return &doctorHandler{}
	default:
		return &intakeHandler{}
	}
}

func buildAgentRequest(endpoint, userid string, sessionKey []byte, payload any) (*http.Request, error) {
	body, err := json.Marshal(payload)
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequest(http.MethodPost, apiBaseURL+endpoint, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-User-ID", userid)
	addSessionKeyHeader(req, sessionKey)
	return req, nil
}

func handleCommonAgentEvent(ev sseEvent) (chunkMsg, bool) {
	switch ev.Type {
	case "session_started":
		return chunkMsg{sessionID: ev.SessionID, conversationID: ev.ConversationID}, true
	case "message":
		return chunkMsg{content: ev.Content}, true
	case "tool_start":
		return chunkMsg{content: ev.Content, toolMessage: toolMessage{toolID: ev.ToolCallID, toolName: ev.Name, running: true}}, true
	case "tool_end":
		return chunkMsg{content: ev.Content, toolMessage: toolMessage{toolID: ev.ToolCallID, toolName: ev.Name, running: false}}, true
	case "error":
		return chunkMsg{err: fmt.Errorf("%s", ev.Content), recoverable: ev.Recoverable}, true
	}
	if ev.Type == "" && ev.Content != "" {
		return chunkMsg{content: ev.Content}, true
	}
	return chunkMsg{}, false
}

// ---------------
// Intake
// ---------------

type intakeHandler struct{}

func (*intakeHandler) Kind() AgentKind    { return AgentIntake }
func (*intakeHandler) Header() string     { return "Iatreon - Intake" }
func (*intakeHandler) Footer() []string   { return []string{"Enter Send", "Esc Logout", "Ctrl+C Quit"} }
func (*intakeHandler) Welcome() string    { return "Welcome to Iatreon. Let's start by taking an intake." }
func (*intakeHandler) AgentLabel() string { return "Iatreon:" }

func (*intakeHandler) BuildRequest(conversationID, userid, message, sessionID string, sessionKey []byte) (*http.Request, error) {
	payload := struct {
		ConversationID string `json:"conversation_id"`
		Message        string `json:"message"`
		SessionID      string `json:"session_id"`
	}{
		ConversationID: conversationID,
		Message:        message,
		SessionID:      sessionID,
	}
	return buildAgentRequest("/chat/intake", userid, sessionKey, payload)
}

func (*intakeHandler) HandleEvent(ev sseEvent) chunkMsg {
	switch ev.Type {
	case "intake_complete":
		return chunkMsg{
			content: "\n\n✅ **Intake completed.** Your profile has been saved.",
			done:    true,
		}
	}
	if msg, ok := handleCommonAgentEvent(ev); ok {
		return msg
	}
	return chunkMsg{}
}

// ---------------------
// Research
// ---------------------

type researchHandler struct{}

func (*researchHandler) Kind() AgentKind  { return AgentResearch }
func (*researchHandler) Header() string   { return "Iatreon - Research" }
func (*researchHandler) Footer() []string { return []string{"Enter Send", "Esc Logout", "Ctrl+C Quit"} }
func (*researchHandler) Welcome() string {
	return "Tell me what you'd like to research. I'll search the literature and the web."
}
func (*researchHandler) AgentLabel() string { return "Researcher:" }

type citation struct {
	Title          string `json:"title"`
	Type           string `json:"type"`
	ID             string `json:"id"`
	CitationNumber int    `json:"citation_num"`
	Query          string `json:"query"`
	URL            string `json:"url"`
	DOI            string `json:"doi"`
}

func parseCitations(raw json.RawMessage) []citation {
	if len(raw) == 0 || string(raw) == "null" {
		return nil
	}

	var byNumber map[string]citation
	if err := json.Unmarshal(raw, &byNumber); err == nil {
		citations := make([]citation, 0, len(byNumber))
		for key, c := range byNumber {
			if c.CitationNumber == 0 {
				if n, err := strconv.Atoi(key); err == nil {
					c.CitationNumber = n
				}
			}
			citations = append(citations, c)
		}
		return citations
	}

	var list []citation
	if err := json.Unmarshal(raw, &list); err == nil {
		return list
	}

	return nil
}

func (*researchHandler) BuildRequest(conversationID, userid, message, sessionID string, sessionKey []byte) (*http.Request, error) {
	payload := struct {
		IntakeID  string `json:"intake_id"`
		SessionID string `json:"session_id"`
	}{
		IntakeID:  conversationID,
		SessionID: sessionID,
	}

	return buildAgentRequest("/research", userid, sessionKey, payload)
}

func (*researchHandler) HandleEvent(ev sseEvent) chunkMsg {
	switch ev.Type {
	case "research_complete":
		var data struct {
			Report            string          `json:"report"`
			Citations         json.RawMessage `json:"citations"`
			ResearchSessionID string          `json:"research_session_id"`
		}
		if err := json.Unmarshal(ev.Data, &data); err != nil {
			return chunkMsg{
				content: "\n\n❌ **Research complete.** Error occurred trying to unmarshal the response." + err.Error(),
				done:    true,
			}
		}
		report := data.Report
		if report == "" {
			report = "_(no report content)_"
		}
		return chunkMsg{
			content:           "\n\n✅ **Research complete.** Opening report.",
			report:            report,
			citations:         parseCitations(data.Citations),
			researchSessionID: data.ResearchSessionID,
			done:              true,
		}

	}

	if msg, ok := handleCommonAgentEvent(ev); ok {
		return msg
	}
	return chunkMsg{}
}

// ---------------
// Diagnosis
// ---------------
//

type diagnosisHandler struct{}

func (*diagnosisHandler) Kind() AgentKind { return AgentDiagnosis }
func (*diagnosisHandler) Header() string  { return "Iatreon - Diagnosis" }
func (*diagnosisHandler) Footer() []string {
	return []string{"Enter Send", "Esc Logout", "Ctrl+C Quit"}
}
func (*diagnosisHandler) Welcome() string {
	return "Describe your symptoms and I'll work through a differential diagnosis."
}
func (*diagnosisHandler) AgentLabel() string { return "Diagnostician:" }

func (*diagnosisHandler) BuildRequest(conversationID, userid, message, sessionID string, sessionKey []byte) (*http.Request, error) {

	payload := struct {
		IntakeID  string `json:"intake_id"`
		SessionID string `json:"session_id"`
	}{
		IntakeID:  conversationID,
		SessionID: sessionID,
	}

	return buildAgentRequest("/diagnose", userid, sessionKey, payload)
}

func formatDiagnosisList(title string, items []string) string {
	if len(items) == 0 {
		return ""
	}
	var out string
	out += "\n## " + title + "\n"
	for _, item := range items {
		out += "- " + item + "\n"
	}
	return out
}

func formatDiagnosisInlineList(title string, items []string) string {
	if len(items) == 0 {
		return ""
	}
	out := "   - " + title + ":\n"
	for _, item := range items {
		out += "     - " + item + "\n"
	}
	return out
}

func formatDiagnosisReport(raw json.RawMessage) string {
	if len(raw) == 0 || string(raw) == "null" {
		return "_(no diagnosis content)_"
	}

	var text string
	if err := json.Unmarshal(raw, &text); err == nil {
		var nested json.RawMessage
		if err := json.Unmarshal([]byte(text), &nested); err == nil {
			return formatDiagnosisReport(nested)
		}
		return text
	}

	var report diagnosisReport
	if err := json.Unmarshal(raw, &report); err != nil {
		return string(raw)
	}

	out := "## Diagnosis\n\n"
	if report.PrimaryDiagnosis != "" {
		out += "**Primary diagnosis:** " + report.PrimaryDiagnosis + "\n\n"
	}
	if report.Confidence != "" {
		out += "**Confidence:** " + report.Confidence + "\n\n"
	}
	if report.ReasoningSummary != "" {
		out += "## Reasoning\n" + report.ReasoningSummary + "\n"
	}
	if len(report.Differential) > 0 {
		out += "\n## Differential Diagnoses\n"
		for i, item := range report.Differential {
			out += fmt.Sprintf("%d. **%s**", i+1, item.Condition)
			if item.Likelihood != "" {
				out += " (" + item.Likelihood + ")"
			}
			out += "\n"
			out += formatDiagnosisInlineList("Supporting evidence", item.SupportingEvidence)
			out += formatDiagnosisInlineList("Against evidence", item.AgainstEvidence)
		}
	}
	out += formatDiagnosisList("Recommended Next Steps", report.RecommendedNextSteps)
	out += formatDiagnosisList("Red Flags To Monitor", report.RedFlagsToMonitor)
	return out
}

func (*diagnosisHandler) HandleEvent(ev sseEvent) chunkMsg {
	switch ev.Type {
	case "diagnosis_complete":
		var data struct {
			Report json.RawMessage `json:"report"`
		}
		if err := json.Unmarshal(ev.Data, &data); err != nil {
			return chunkMsg{
				content: "\n\n✅ **Diagnosis complete.** Error occurred trying to unmarshal the response.",
				done:    true,
			}
		}
		return chunkMsg{
			content: "\n\n✅ **Diagnosis complete.**\n\n" + formatDiagnosisReport(data.Report),
			role:    "ai",
			done:    true,
		}
	}

	if msg, ok := handleCommonAgentEvent(ev); ok {
		return msg
	}
	return chunkMsg{}
}

// ---------------
// Doctor
// ---------------

type doctorHandler struct{}

func (*doctorHandler) Kind() AgentKind { return AgentDoctor }
func (*doctorHandler) Header() string  { return "Iatreon - Doctor" }
func (*doctorHandler) Footer() []string {
	return []string{"Enter Send", "Esc Logout", "Ctrl+C Quit"}
}
func (*doctorHandler) Welcome() string {
	return "You are now connected to a doctor. Please describe your symptoms."
}
func (*doctorHandler) AgentLabel() string { return "Doctor:" }

func (*doctorHandler) BuildRequest(conversationID, userid, message, sessionID string, sessionKey []byte) (*http.Request, error) {
	payload := struct {
		ConversationID string `json:"conversation_id"`
		Message        string `json:"message"`
		SessionID      string `json:"session_id"`
	}{
		ConversationID: conversationID,
		Message:        message,
		SessionID:      sessionID,
	}

	return buildAgentRequest("/chat/doctor", userid, sessionKey, payload)
}

func (*doctorHandler) HandleEvent(ev sseEvent) chunkMsg {
	if msg, ok := handleCommonAgentEvent(ev); ok {
		return msg
	}
	return chunkMsg{}
}

func addSessionKeyHeader(req *http.Request, sessionKey []byte) {
	if len(sessionKey) == 0 {
		return
	}
	req.Header.Set("X-Session-Key", base64.StdEncoding.EncodeToString(sessionKey))
}

func sharedHTTPDo(req *http.Request) (*http.Response, error) {
	client := &http.Client{}
	return client.Do(req)
}
