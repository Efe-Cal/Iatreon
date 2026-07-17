package tui

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestProviderSetupDefaultPathSubmits(t *testing.T) {
	t.Setenv("IATREON_BACKEND_API_URL", "http://backend.local/")
	m := newProviderSetupModel("ff6b65d2-bee0-4565-ad42-0d7ccb1f41a9", nil)

	m, _ = m.Update(testKey("enter"))
	if m.step != providerStepSearch {
		t.Fatalf("default AI provider should advance to search, got step %v", m.step)
	}

	m, _ = m.Update(testKey("enter"))
	if m.step != providerStepConfirm {
		t.Fatalf("default search provider should skip credentials, got step %v", m.step)
	}

	m, cmd := m.Update(testKey("enter"))
	if !m.submitting {
		t.Fatal("confirm enter should submit provider setup")
	}
	if cmd == nil {
		t.Fatal("expected submit command")
	}
	if got := m.llmBaseURLValue(); got != "http://backend.local/v1" {
		t.Fatalf("llm backend base URL = %q", got)
	}
	if got := m.searchBaseURLValue(); got != "http://backend.local/v1/exa" {
		t.Fatalf("search backend base URL = %q", got)
	}
	if m.llmAPIKeyValue() != "" || m.searchAPIKeyValue() != "" {
		t.Fatal("Iatreon JWT must not be copied into provider API-key fields")
	}
}

func TestProviderSetupCustomProviderRequiresAPIKey(t *testing.T) {
	m := newProviderSetupModel("ff6b65d2-bee0-4565-ad42-0d7ccb1f41a9", nil)

	m, _ = m.Update(testKey("down"))
	m, _ = m.Update(testKey("enter"))
	if m.step != providerStepLLMKey {
		t.Fatalf("custom provider should ask for API key, got step %v", m.step)
	}

	m, _ = m.Update(testKey("enter"))
	if m.err == nil {
		t.Fatal("empty custom provider API key should error")
	}
	if m.step != providerStepLLMKey {
		t.Fatalf("API key error should stay on key step, got %v", m.step)
	}
}

func TestProviderSetupCustomProviderDefaultsBaseURL(t *testing.T) {
	m := newProviderSetupModel("ff6b65d2-bee0-4565-ad42-0d7ccb1f41a9", nil)

	for _, provider := range llmProviders {
		if provider == "Hugging Face" {
			t.Fatal("Hugging Face should not be offered as an LLM provider")
		}
	}

	m, _ = m.Update(testKey("down"))
	m, _ = m.Update(testKey("enter"))
	m, _ = m.Update(testKey("sk-test"))
	m, _ = m.Update(testKey("enter"))

	if m.step != providerStepLLMBaseURL {
		t.Fatalf("custom provider should move to base URL, got step %v", m.step)
	}
	if got := m.llmBaseURL.Value(); got != "https://openrouter.ai/api/v1" {
		t.Fatalf("OpenRouter base URL default = %q", got)
	}
}

func TestProviderEditorPreservesSearchProviderAndCredentials(t *testing.T) {
	m := newProviderEditor("ff6b65d2-bee0-4565-ad42-0d7ccb1f41a9", nil, providerSetupInput{
		LLMProvider:    "OpenRouter",
		LLMAPIKey:      "llm-secret",
		LLMBaseURL:     "https://openrouter.ai/api/v1",
		SearchProvider: "Exa",
		SearchAPIKey:   "search-secret",
	})

	m, _ = m.Update(testKey("enter"))
	m, _ = m.Update(testKey("enter"))
	m, _ = m.Update(testKey("enter"))
	if m.step != providerStepSearch || searchProviders[m.cursor] != "Exa" {
		t.Fatalf("search step = %v cursor=%d provider=%q", m.step, m.cursor, searchProviders[m.cursor])
	}
	m, _ = m.Update(testKey("enter"))
	if m.searchProvider != "Exa" || m.searchAPIKey.Value() != "search-secret" {
		t.Fatalf("search config changed to provider=%q key=%q", m.searchProvider, m.searchAPIKey.Value())
	}
	m, _ = m.Update(testKey("esc"))
	if m.step != providerStepSearch || searchProviders[m.cursor] != "Exa" {
		t.Fatalf("back navigation lost search provider: step=%v cursor=%d", m.step, m.cursor)
	}
}

func TestFirstRunStartsWithProviderSetup(t *testing.T) {
	m := NewModel("ff6b65d2-bee0-4565-ad42-0d7ccb1f41a9", false)
	if m.active != backendAccountScreen {
		t.Fatalf("new user should start at backend account setup, active=%v", m.active)
	}
}

func TestAuthenticateBackendAccountReadsToken(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/auth/token" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		if r.Method != http.MethodPost {
			t.Fatalf("unexpected method: %s", r.Method)
		}
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, `{"access_token":"jwt-test","refresh_token":"refresh-test"}`)
	}))
	defer server.Close()

	tokens, err := authenticateBackendAccount(context.Background(), server.URL, "token", "alice", "password123")
	if err != nil {
		t.Fatal(err)
	}
	if tokens.AccessToken != "jwt-test" || tokens.RefreshToken != "refresh-test" {
		t.Fatalf("tokens = %+v", tokens)
	}
}

func TestBackendAPIURLDefaultsToHostedBackend(t *testing.T) {
	t.Setenv("IATREON_BACKEND_API_URL", "")

	if got := backendAPIURL(); got != "https://iatreon.efecal.hackclub.app" {
		t.Fatalf("backend base URL = %q", got)
	}
}

func TestBackendAccountOffersExplicitChoices(t *testing.T) {
	m := newBackendAccountModel("ff6b65d2-bee0-4565-ad42-0d7ccb1f41a9", nil)
	view := m.View()
	if !strings.Contains(view, "Sign in") || !strings.Contains(view, "Create account") {
		t.Fatalf("account choices missing from view: %q", view)
	}
}

func TestBackendAccountCanExplainRequiredSignIn(t *testing.T) {
	m := newBackendAccountModel("ff6b65d2-bee0-4565-ad42-0d7ccb1f41a9", nil)
	m.requireSignIn("alice", "Session expired.")
	if m.step != backendAccountPassword || m.username.Value() != "alice" {
		t.Fatalf("reauth state = step %v username %q", m.step, m.username.Value())
	}
	if !strings.Contains(m.View(), "Session expired.") {
		t.Fatal("reauth reason missing")
	}
}

func TestCreateAccountUsesRegisterEndpoint(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/auth/register" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		w.WriteHeader(http.StatusCreated)
		fmt.Fprint(w, `{"access_token":"jwt-created","refresh_token":"refresh-created"}`)
	}))
	defer server.Close()
	tokens, err := authenticateBackendAccount(context.Background(), server.URL, "register", "alice", "password123")
	if err != nil || tokens.AccessToken != "jwt-created" || tokens.RefreshToken != "refresh-created" {
		t.Fatalf("create account tokens=%+v err=%v", tokens, err)
	}
}
