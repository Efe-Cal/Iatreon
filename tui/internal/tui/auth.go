package tui

import (
	"bytes"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"sync"
	"time"

	"golang.org/x/crypto/pbkdf2"
)

const sessionKeyIterations = 210000

var ErrAuthRequired = errors.New("authentication required")

type AuthState struct {
	UserID                string    `json:"user_id"`
	Email                 string    `json:"email"`
	AccessToken           string    `json:"access_token"`
	RefreshToken          string    `json:"refresh_token"`
	AccessTokenExpiresAt  time.Time `json:"access_token_expires_at"`
	RefreshTokenExpiresAt time.Time `json:"refresh_token_expires_at"`
	HasProfile            bool      `json:"has_profile"`
	SessionKeyBase64      string    `json:"session_key_base64"`
}

type authResponse struct {
	UserID                string    `json:"user_id"`
	Email                 string    `json:"email"`
	AccessToken           string    `json:"access_token"`
	RefreshToken          string    `json:"refresh_token"`
	AccessTokenExpiresAt  time.Time `json:"access_token_expires_at"`
	RefreshTokenExpiresAt time.Time `json:"refresh_token_expires_at"`
	HasProfile            bool      `json:"has_profile"`
	SessionKeySalt        string    `json:"session_key_salt"`
}

type AuthStore struct {
	path string
}

func DefaultAuthStore() AuthStore {
	dir, err := os.UserConfigDir()
	if err != nil || dir == "" {
		dir = "."
	}
	return AuthStore{path: filepath.Join(dir, "iatreon", "auth.json")}
}

func NewAuthStore(path string) AuthStore {
	return AuthStore{path: path}
}

func (s AuthStore) Load() (AuthState, error) {
	data, err := os.ReadFile(s.path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return AuthState{}, ErrAuthRequired
		}
		return AuthState{}, err
	}
	var state AuthState
	if err := json.Unmarshal(data, &state); err != nil {
		return AuthState{}, err
	}
	if state.RefreshToken == "" || time.Now().After(state.RefreshTokenExpiresAt) {
		_ = s.Delete()
		return AuthState{}, ErrAuthRequired
	}
	return state, nil
}

func (s AuthStore) Save(state AuthState) error {
	if err := os.MkdirAll(filepath.Dir(s.path), 0700); err != nil {
		return err
	}
	data, err := json.MarshalIndent(state, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(s.path, data, 0600)
}

func (s AuthStore) Delete() error {
	err := os.Remove(s.path)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	return err
}

type AuthClient struct {
	mu     sync.Mutex
	client *http.Client
	store  AuthStore
	state  AuthState
}

var defaultAuthClient *AuthClient

func SetDefaultAuthClient(client *AuthClient) {
	defaultAuthClient = client
}

func NewAuthClient(state AuthState, store AuthStore) *AuthClient {
	return &AuthClient{
		client: http.DefaultClient,
		store:  store,
		state:  state,
	}
}

func (c *AuthClient) State() AuthState {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.state
}

func (c *AuthClient) SessionKeyBytes() ([]byte, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	return sessionKeyBytes(c.state)
}

func (c *AuthClient) Login(email, password string) (AuthState, error) {
	return c.authenticate("/auth/login", email, password)
}

func (c *AuthClient) Register(email, password string) (AuthState, error) {
	return c.authenticate("/auth/register", email, password)
}

func (c *AuthClient) authenticate(endpoint, email, password string) (AuthState, error) {
	body := map[string]string{"email": email, "password": password}
	var resp authResponse
	if err := postJSON(endpoint, body, &resp); err != nil {
		return AuthState{}, err
	}
	key, err := deriveSessionKey(password, resp.SessionKeySalt)
	if err != nil {
		return AuthState{}, err
	}
	state := authResponseToState(resp, base64.StdEncoding.EncodeToString(key))
	zeroBytes(key)

	c.mu.Lock()
	defer c.mu.Unlock()
	c.state = state
	if err := c.store.Save(state); err != nil {
		return AuthState{}, err
	}
	return state, nil
}

func (c *AuthClient) Do(req *http.Request) (*http.Response, error) {
	if err := c.ensureAccessToken(); err != nil {
		return nil, err
	}

	first, err := cloneRequest(req)
	if err != nil {
		return nil, err
	}
	c.attachAuth(first)
	resp, err := c.client.Do(first)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode != http.StatusUnauthorized {
		return resp, nil
	}
	resp.Body.Close()

	if err := c.refresh(); err != nil {
		return nil, err
	}
	retry, err := cloneRequest(req)
	if err != nil {
		return nil, err
	}
	c.attachAuth(retry)
	resp, err = c.client.Do(retry)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode == http.StatusUnauthorized {
		resp.Body.Close()
		_ = c.Clear()
		return nil, ErrAuthRequired
	}
	return resp, nil
}

func (c *AuthClient) Logout() error {
	c.mu.Lock()
	refreshToken := c.state.RefreshToken
	c.mu.Unlock()

	var requestErr error
	if refreshToken != "" {
		requestErr = postJSON("/auth/logout", map[string]string{"refresh_token": refreshToken}, nil)
	}
	clearErr := c.Clear()
	if requestErr != nil {
		return requestErr
	}
	return clearErr
}

func (c *AuthClient) Clear() error {
	c.mu.Lock()
	c.state = AuthState{}
	c.mu.Unlock()
	return c.store.Delete()
}

func (c *AuthClient) SetHasProfile(hasProfile bool) error {
	c.mu.Lock()
	c.state.HasProfile = hasProfile
	state := c.state
	c.mu.Unlock()
	return c.store.Save(state)
}

func (c *AuthClient) ensureAccessToken() error {
	c.mu.Lock()
	state := c.state
	c.mu.Unlock()

	if state.AccessToken == "" || state.RefreshToken == "" {
		return ErrAuthRequired
	}
	if time.Now().After(state.RefreshTokenExpiresAt) {
		_ = c.Clear()
		return ErrAuthRequired
	}
	if time.Until(state.AccessTokenExpiresAt) > time.Minute {
		return nil
	}
	return c.refresh()
}

func (c *AuthClient) refresh() error {
	c.mu.Lock()
	refreshToken := c.state.RefreshToken
	sessionKey := c.state.SessionKeyBase64
	c.mu.Unlock()

	if refreshToken == "" {
		return ErrAuthRequired
	}
	var resp authResponse
	err := postJSON("/auth/refresh", map[string]string{"refresh_token": refreshToken}, &resp)
	if err != nil {
		_ = c.Clear()
		return ErrAuthRequired
	}
	state := authResponseToState(resp, sessionKey)

	c.mu.Lock()
	c.state = state
	c.mu.Unlock()
	if err := c.store.Save(state); err != nil {
		return err
	}
	return nil
}

func (c *AuthClient) attachAuth(req *http.Request) {
	c.mu.Lock()
	state := c.state
	c.mu.Unlock()
	if state.AccessToken != "" {
		req.Header.Set("Authorization", "Bearer "+state.AccessToken)
	}
	if key, err := sessionKeyBytes(state); err == nil {
		addSessionKeyHeader(req, key)
		zeroBytes(key)
	}
}

func postJSON(endpoint string, payload any, out any) error {
	body, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	req, err := http.NewRequest(http.MethodPost, apiBaseURL+endpoint, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("server returned status: %s", resp.Status)
	}
	if out == nil {
		return nil
	}
	return json.NewDecoder(resp.Body).Decode(out)
}

func cloneRequest(req *http.Request) (*http.Request, error) {
	clone := req.Clone(req.Context())
	if req.Body != nil {
		if req.GetBody == nil {
			return nil, fmt.Errorf("request body cannot be retried")
		}
		body, err := req.GetBody()
		if err != nil {
			return nil, err
		}
		clone.Body = body
	}
	return clone, nil
}

func authResponseToState(resp authResponse, sessionKeyBase64 string) AuthState {
	return AuthState{
		UserID:                resp.UserID,
		Email:                 resp.Email,
		AccessToken:           resp.AccessToken,
		RefreshToken:          resp.RefreshToken,
		AccessTokenExpiresAt:  resp.AccessTokenExpiresAt,
		RefreshTokenExpiresAt: resp.RefreshTokenExpiresAt,
		HasProfile:            resp.HasProfile,
		SessionKeyBase64:      sessionKeyBase64,
	}
}

func deriveSessionKey(password, saltText string) ([]byte, error) {
	salt, err := decodeRawURLBase64(saltText)
	if err != nil {
		return nil, err
	}
	return pbkdf2.Key([]byte(password), salt, sessionKeyIterations, 32, sha256.New), nil
}

func sessionKeyBytes(state AuthState) ([]byte, error) {
	if state.SessionKeyBase64 == "" {
		return nil, ErrAuthRequired
	}
	return base64.StdEncoding.DecodeString(state.SessionKeyBase64)
}

func decodeRawURLBase64(value string) ([]byte, error) {
	if decoded, err := base64.RawURLEncoding.DecodeString(value); err == nil {
		return decoded, nil
	}
	return base64.URLEncoding.DecodeString(value)
}

func zeroBytes(value []byte) {
	for i := range value {
		value[i] = 0
	}
}
