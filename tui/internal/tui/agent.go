package tui

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
)

type AgentKind int

const (
	AgentIntake AgentKind = iota
	AgentDiagnosis
	AgentResearch
	AgentDoctor
)

func (k AgentKind) String() string {
	switch k {
	case AgentDiagnosis:
		return "diagnosis"
	case AgentResearch:
		return "research"
	case AgentDoctor:
		return "doctor"
	default:
		return "doctor"
	}
}

type AgentHandler interface {
	Kind() AgentKind

	Header() string

	Footer() []string

	Welcome() string

	AgentLabel() string

	BuildRequest(conversationID, userid, message string) (*http.Request, error)

	HandleEvent(ev sseEvent) chunkMsg
}

// sseEvent mirrors the JSON shape yielded by the FastAPI services:
//
//	{"type": "message",        "content": "..."}
//	{"type": "tool_start",     "name": "..."}
//	{"type": "tool_end",       "name": "..."}
//	{"type": "intake_complete","profile": {...}, "transcript": "..."}
type sseEvent struct {
	Type    string          `json:"type"`
	Content json.RawMessage `json:"content"`
	Name    string          `json:"name"`
	Profile json.RawMessage `json:"profile"`
}

func (e sseEvent) contentString() string {
	if len(e.Content) == 0 {
		return ""
	}
	var s string
	if err := json.Unmarshal(e.Content, &s); err == nil {
		return s
	}
	// Fall back to a compact JSON rendering for non-string content.
	var pretty bytes.Buffer
	if err := json.Indent(&pretty, e.Content, "", "  "); err == nil {
		return pretty.String()
	}
	return string(e.Content)
}

func newAgentHandler(kind AgentKind) AgentHandler {
	switch kind {
	case AgentDiagnosis:
		return &diagnosisHandler{}
	case AgentResearch:
		return &researchHandler{}
	default:
		return &intakeHandler{}
	}
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

func (*intakeHandler) BuildRequest(conversationID, userid, message string) (*http.Request, error) {
	payload := struct {
		ConversationID string `json:"conversation_id"`
		Message        string `json:"message"`
	}{
		ConversationID: conversationID,
		Message:        message,
	}
	reqBytes, err := json.Marshal(payload)
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequest(http.MethodPost, apiBaseURL+"/chat/intake", bytes.NewReader(reqBytes))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-User-ID", userid)
	return req, nil
}

func (*intakeHandler) HandleEvent(ev sseEvent) chunkMsg {
	switch ev.Type {
	case "intake_complete":
		return chunkMsg{
			content: "\n\n✅ **Intake completed.** Your profile has been saved.",
			done:    true,
		}
	case "message":
		return chunkMsg{content: ev.contentString()}
	case "tool_start":
		return chunkMsg{content: fmt.Sprintf("\n> 🔍 *Running: %s…*\n", ev.Name)}
	case "tool_end":
		return chunkMsg{content: fmt.Sprintf("\n> ✔ *%s done.*\n\n", ev.Name)}
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

func (*researchHandler) BuildRequest(conversationID, userid, message string) (*http.Request, error) {
	url := fmt.Sprintf("%s/research?intake_id=%s", apiBaseURL, conversationID)
	req, err := http.NewRequest(http.MethodPost, url, strings.NewReader(message))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "text/plain")
	req.Header.Set("X-User-ID", userid)
	return req, nil
}

func (*researchHandler) HandleEvent(ev sseEvent) chunkMsg {
	switch ev.Type {
	case "research_complete":
		return chunkMsg{
			content: "\n\n✅ **Research complete.** Citations are saved with the report.",
			done:    true,
		}
	case "message":
		return chunkMsg{content: ev.contentString()}
	case "tool_start":
		return chunkMsg{content: fmt.Sprintf("\n> 🔍 *Running: %s…*\n", ev.Name)}
	case "tool_end":
		return chunkMsg{content: fmt.Sprintf("\n> ✔ *%s done.*\n\n", ev.Name)}
	}
	if len(ev.Type) == 0 && len(ev.Content) > 0 {
		return chunkMsg{content: ev.contentString()}
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
func (*diagnosisHandler) AgentLabel() string { return "Doctor:" }

func (*diagnosisHandler) BuildRequest(conversationID, userid, message string) (*http.Request, error) {
	url := fmt.Sprintf("%s/diagnose?intake_id=%s", apiBaseURL, conversationID)
	req, err := http.NewRequest(http.MethodPost, url, strings.NewReader(message))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "text/plain")
	req.Header.Set("X-User-ID", userid)
	return req, nil
}

func (*diagnosisHandler) HandleEvent(ev sseEvent) chunkMsg {
	switch ev.Type {
	case "diagnosis_complete":
		return chunkMsg{
			content: "\n\n✅ **Diagnosis complete.** See the report above.",
			done:    true,
		}
	case "message":
		return chunkMsg{content: ev.contentString()}
	case "tool_start":
		return chunkMsg{content: fmt.Sprintf("\n> 🔍 *Running: %s…*\n", ev.Name)}
	case "tool_end":
		return chunkMsg{content: fmt.Sprintf("\n> ✔ *%s done.*\n\n", ev.Name)}
	}

	if len(ev.Type) == 0 && len(ev.Content) > 0 {
		return chunkMsg{content: ev.contentString()}
	}
	return chunkMsg{}
}

func sharedHTTPDo(req *http.Request) (*http.Response, error) {
	client := &http.Client{}
	return client.Do(req)
}

func drainAndClose(body io.ReadCloser) {
	if body == nil {
		return
	}
	_, _ = io.Copy(io.Discard, body)
	_ = body.Close()
}
