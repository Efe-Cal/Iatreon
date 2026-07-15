package tui

import (
	"errors"
	"strings"
	"testing"
)

func TestExpiredSessionReturnsToPreservedChatAfterSignIn(t *testing.T) {
	const userID = "ff6b65d2-bee0-4565-ad42-0d7ccb1f41a9"
	m := newModel(userID, true, true, true, nil)
	m.active = chatScreen
	m.backendUsername = "alice"
	m.chat = newChatModelForAgent(AgentIntake, userID, "session", nil)
	m.chat.retryMessage = "still here"

	updated, _ := m.updateChat(chunkMsg{err: errors.New("expired"), authRequired: true})
	m = updated.(model)
	if m.active != backendAccountScreen || !m.reauthPending {
		t.Fatalf("expired session did not open sign-in: active=%v pending=%v", m.active, m.reauthPending)
	}
	if m.chat.retryMessage != "still here" || !m.chat.retryWithEnter {
		t.Fatal("pending chat request was not preserved")
	}

	m.backendAccount.username.SetValue("alice")
	updated, _ = m.updateBackendAccount(backendAccountSubmittedMsg{})
	m = updated.(model)
	if m.active != chatScreen || m.reauthPending {
		t.Fatalf("sign-in did not return to chat: active=%v pending=%v", m.active, m.reauthPending)
	}
	if !strings.Contains(m.chat.history[len(m.chat.history)-1].text, "Press Enter to retry") {
		t.Fatal("manual retry prompt missing after sign-in")
	}
}

func TestTemporaryAuthFailureStaysInChat(t *testing.T) {
	const userID = "ff6b65d2-bee0-4565-ad42-0d7ccb1f41a9"
	m := newModel(userID, true, true, true, nil)
	m.active = chatScreen
	m.chat = newChatModelForAgent(AgentIntake, userID, "session", nil)

	updated, _ := m.updateChat(chunkMsg{err: errors.New("temporarily unavailable"), recoverable: true})
	m = updated.(model)
	if m.active != chatScreen || m.reauthPending {
		t.Fatal("temporary auth failure incorrectly forced sign-in")
	}
	if !m.chat.retryWithEnter {
		t.Fatal("temporary auth failure should remain retryable")
	}
}
