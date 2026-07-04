package tui

import (
	"encoding/base64"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	tea "github.com/charmbracelet/bubbletea"
)

func testAuthState() AuthState {
	return AuthState{
		UserID:                "user-1",
		Email:                 "user@example.com",
		AccessToken:           "access-1",
		RefreshToken:          "refresh-1",
		AccessTokenExpiresAt:  time.Now().Add(time.Hour),
		RefreshTokenExpiresAt: time.Now().Add(24 * time.Hour),
		HasProfile:            true,
		SessionKeyBase64:      base64.StdEncoding.EncodeToString([]byte("12345678901234567890123456789012")),
	}
}

func TestAuthStoreSaveLoadDelete(t *testing.T) {
	store := NewAuthStore(filepath.Join(t.TempDir(), "auth.json"))
	want := testAuthState()

	if err := store.Save(want); err != nil {
		t.Fatalf("save auth state: %v", err)
	}
	got, err := store.Load()
	if err != nil {
		t.Fatalf("load auth state: %v", err)
	}
	if got.UserID != want.UserID || got.RefreshToken != want.RefreshToken {
		t.Fatalf("loaded state mismatch: %+v", got)
	}
	if err := store.Delete(); err != nil {
		t.Fatalf("delete auth state: %v", err)
	}
	if _, err := os.Stat(store.path); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("auth state file should be deleted, err=%v", err)
	}
}

func TestAuthScreenSwitchesModeAndMasksPassword(t *testing.T) {
	m := newAuthModel(NewAuthClient(AuthState{}, NewAuthStore(filepath.Join(t.TempDir(), "auth.json"))))
	m.SetSize(100, 30)

	m, _ = m.Update(testKey("ctrl+r"))
	if m.mode != authModeRegister {
		t.Fatal("ctrl+r should switch to register mode")
	}
	m.moveFocus(1)
	m, _ = m.Update(teaRuneMsg("s"))
	m, _ = m.Update(teaRuneMsg("e"))
	m, _ = m.Update(teaRuneMsg("c"))
	m, _ = m.Update(teaRuneMsg("r"))
	m, _ = m.Update(teaRuneMsg("e"))
	m, _ = m.Update(teaRuneMsg("t"))
	m, _ = m.Update(teaRuneMsg("1"))
	m, _ = m.Update(teaRuneMsg("2"))

	view := m.View()
	if strings.Contains(view, "secret12") {
		t.Fatalf("password should be masked in auth view:\n%s", view)
	}
}

func TestAuthClientRefreshesAndAttachesHeaders(t *testing.T) {
	store := NewAuthStore(filepath.Join(t.TempDir(), "auth.json"))
	state := testAuthState()
	state.AccessToken = "old-access"
	state.RefreshToken = "old-refresh"
	state.AccessTokenExpiresAt = time.Now().Add(5 * time.Second)
	if err := store.Save(state); err != nil {
		t.Fatal(err)
	}

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/auth/refresh":
			var body map[string]string
			if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
				t.Fatal(err)
			}
			if body["refresh_token"] != "old-refresh" {
				t.Fatalf("unexpected refresh token: %q", body["refresh_token"])
			}
			_ = json.NewEncoder(w).Encode(authResponse{
				UserID:                state.UserID,
				Email:                 state.Email,
				AccessToken:           "new-access",
				RefreshToken:          "new-refresh",
				AccessTokenExpiresAt:  time.Now().Add(time.Hour),
				RefreshTokenExpiresAt: time.Now().Add(24 * time.Hour),
				HasProfile:            true,
				SessionKeySalt:        "AAAAAAAAAAAAAAAAAAAAAA",
			})
		case "/protected":
			if got := r.Header.Get("Authorization"); got != "Bearer new-access" {
				t.Fatalf("authorization header=%q", got)
			}
			if got := r.Header.Get("X-Session-Key"); got != state.SessionKeyBase64 {
				t.Fatalf("session key header=%q", got)
			}
			w.WriteHeader(http.StatusOK)
		default:
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
	}))
	defer server.Close()
	oldBaseURL := apiBaseURL
	apiBaseURL = server.URL
	defer func() { apiBaseURL = oldBaseURL }()

	client := NewAuthClient(state, store)
	req, err := http.NewRequest(http.MethodGet, server.URL+"/protected", nil)
	if err != nil {
		t.Fatal(err)
	}
	resp, err := client.Do(req)
	if err != nil {
		t.Fatalf("auth client request: %v", err)
	}
	resp.Body.Close()

	got := client.State()
	if got.AccessToken != "new-access" || got.RefreshToken != "new-refresh" {
		t.Fatalf("state was not refreshed: %+v", got)
	}
}

func TestAuthClientRefreshFailureClearsState(t *testing.T) {
	store := NewAuthStore(filepath.Join(t.TempDir(), "auth.json"))
	state := testAuthState()
	state.AccessTokenExpiresAt = time.Now().Add(5 * time.Second)
	if err := store.Save(state); err != nil {
		t.Fatal(err)
	}

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusUnauthorized)
	}))
	defer server.Close()
	oldBaseURL := apiBaseURL
	apiBaseURL = server.URL
	defer func() { apiBaseURL = oldBaseURL }()

	client := NewAuthClient(state, store)
	req, err := http.NewRequest(http.MethodGet, server.URL+"/protected", nil)
	if err != nil {
		t.Fatal(err)
	}
	_, err = client.Do(req)
	if !errors.Is(err, ErrAuthRequired) {
		t.Fatalf("expected auth required, got %v", err)
	}
	if _, err := store.Load(); !errors.Is(err, ErrAuthRequired) {
		t.Fatalf("store should be cleared after refresh failure, got %v", err)
	}
}

func teaRuneMsg(value string) tea.KeyMsg {
	return tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune(value)}
}
