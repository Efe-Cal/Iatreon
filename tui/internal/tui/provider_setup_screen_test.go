package tui

import "testing"

func TestProviderSetupDefaultPathSubmits(t *testing.T) {
	m := newProviderSetupModel("ff6b65d2-bee0-4565-ad42-0d7ccb1f41a9", nil)

	m, _ = m.Update(testKey("enter"))
	if m.step != providerStepSearch {
		t.Fatalf("default AI provider should skip credentials, got step %v", m.step)
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

func TestFirstRunStartsWithProviderSetup(t *testing.T) {
	m := NewModel("ff6b65d2-bee0-4565-ad42-0d7ccb1f41a9", false)
	if m.active != providerSetupScreen {
		t.Fatalf("new user should start at provider setup, active=%v", m.active)
	}
}
