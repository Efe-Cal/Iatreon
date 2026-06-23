package tui

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
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
	addSessionKeyHeader(req, sessionKey)
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
		return chunkMsg{content: ev.Content}
	case "tool_start":
		return chunkMsg{content: string(ev.Content), toolMessage: toolMessage{toolID: ev.ToolCallID, toolName: ev.Name, running: true}}
	case "tool_end":
		return chunkMsg{content: string(ev.Content), toolMessage: toolMessage{toolID: ev.ToolCallID, toolName: ev.Name, running: false}}
	case "session_started":
		return chunkMsg{sessionID: ev.SessionID, conversationID: ev.ConversationID}
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

func (*researchHandler) BuildRequest(conversationID, userid, message, sessionID string, sessionKey []byte) (*http.Request, error) {
	payload := struct {
		IntakeID  string `json:"intake_id"`
		SessionID string `json:"session_id"`
	}{
		IntakeID:  conversationID,
		SessionID: sessionID,
	}

	reqBytes, err := json.Marshal(payload)
	if err != nil {
		return nil, err
	}

	req, err := http.NewRequest(http.MethodPost, apiBaseURL+"/research", bytes.NewReader(reqBytes))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-User-ID", userid)
	addSessionKeyHeader(req, sessionKey)
	return req, nil
}

func (*researchHandler) HandleEvent(ev sseEvent) chunkMsg {
	switch ev.Type {
	case "research_complete":
		var data struct {
			Report    string          `json:"report"`
			Citations json.RawMessage `json:"citations"`
		}
		if err := json.Unmarshal(ev.Data, &data); err != nil {
			return chunkMsg{
				content: "\n\n❌ **Research complete.** Error occurred trying to unmarshal the response." + err.Error(),
				done:    true,
			}
		}
		content := "\n\n✅ **Research complete.** See the report below.\n\n**Report:**\n"
		if data.Report != "" {
			content += data.Report
		} else {
			content += "_(no report content)_"
		}
		// TODO: add citations
		// if len(data.Citations) > 0 {
		// 	content += "\n\n**Citations:**\n"
		// 	for _, c := range data.Citations {
		// 		content += fmt.Sprintf("- %s\n", string(c))
		// 	}
		// }
		return chunkMsg{content: content, done: true}

	case "message":
		return chunkMsg{content: ev.Content}
	case "tool_start":
		return chunkMsg{content: string(ev.Content), toolMessage: toolMessage{toolID: ev.ToolCallID, toolName: ev.Name, running: true}}
	case "tool_end":
		return chunkMsg{content: string(ev.Content), toolMessage: toolMessage{toolID: ev.ToolCallID, toolName: ev.Name, running: false}}
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

	reqBytes, err := json.Marshal(payload)
	if err != nil {
		return nil, err
	}

	req, err := http.NewRequest(http.MethodPost, apiBaseURL+"/diagnose", bytes.NewReader(reqBytes))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-User-ID", userid)
	addSessionKeyHeader(req, sessionKey)
	return req, nil
}

func (*diagnosisHandler) HandleEvent(ev sseEvent) chunkMsg {
	switch ev.Type {
	case "diagnosis_complete":
		var data struct {
			Report string `json:"report"`
		}
		if err := json.Unmarshal(ev.Data, &data); err != nil {
			return chunkMsg{
				content: "\n\n✅ **Diagnosis complete.** Error occurred trying to unmarshal the response.",
				done:    true,
			}
		}
		return chunkMsg{
			content: fmt.Sprintf("\n\n✅ **Diagnosis complete.** See the report below.\n\n**Report:**\n%s", data.Report),
			done:    true,
		}
	case "message":
		return chunkMsg{content: ev.Content}
	case "tool_start":
		return chunkMsg{content: string(ev.Content), toolMessage: toolMessage{toolID: ev.ToolCallID, toolName: ev.Name, running: true}}
	case "tool_end":
		return chunkMsg{content: string(ev.Content), toolMessage: toolMessage{toolID: ev.ToolCallID, toolName: ev.Name, running: false}}
	}

	if len(ev.Type) == 0 && len(ev.Content) > 0 {
		return chunkMsg{content: ev.Content}
	}
	return chunkMsg{}
}

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

	reqBytes, err := json.Marshal(payload)
	if err != nil {
		return nil, err
	}

	req, err := http.NewRequest(http.MethodPost, apiBaseURL+"/chat/doctor", bytes.NewReader(reqBytes))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-User-ID", userid)
	addSessionKeyHeader(req, sessionKey)
	return req, nil
}

func (*doctorHandler) HandleEvent(ev sseEvent) chunkMsg {
	switch ev.Type {
	case "session_started":
		return chunkMsg{sessionID: ev.SessionID, conversationID: ev.ConversationID}
	case "message":
		return chunkMsg{content: ev.Content}
	case "tool_start":
		return chunkMsg{content: string(ev.Content), toolMessage: toolMessage{toolID: ev.ToolCallID, toolName: ev.Name, running: true}}
	case "tool_end":
		return chunkMsg{content: string(ev.Content), toolMessage: toolMessage{toolID: ev.ToolCallID, toolName: ev.Name, running: false}}
	}

	if len(ev.Type) == 0 && len(ev.Content) > 0 {
		return chunkMsg{content: ev.Content}
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

func drainAndClose(body io.ReadCloser) {
	if body == nil {
		return
	}
	_, _ = io.Copy(io.Discard, body)
	_ = body.Close()
}
