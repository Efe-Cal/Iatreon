package ssh

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/charmbracelet/log"
	"github.com/muesli/termenv"

	"github.com/charmbracelet/ssh"
	"github.com/charmbracelet/wish"
	"github.com/charmbracelet/wish/activeterm"
	"github.com/charmbracelet/wish/bubbletea"
	"github.com/charmbracelet/wish/logging"
	"golang.org/x/crypto/hkdf"
	gossh "golang.org/x/crypto/ssh"
	"golang.org/x/crypto/ssh/agent"

	"tui/internal/tui"
)

type User struct {
	ID         string `json:"user_id"`
	HasProfile bool   `json:"has_profile"`
}

type unlockResponse struct {
	Status     string `json:"status"`
	HasProfile bool   `json:"has_profile"`
}

const agentForwardingWait = 2 * time.Second

var apiBaseURL = func() string {
	if v := strings.TrimRight(os.Getenv("API_BASE_URL"), "/"); v != "" {
		return v
	}
	return "http://localhost:8000"
}()

func getUserWithPubKey(ctx ssh.Context, key ssh.PublicKey) bool {
	authKeyBytes := gossh.MarshalAuthorizedKey(key)

	publicKeyStr := string(bytes.TrimSpace(authKeyBytes))

	jsonData := []byte(fmt.Sprintf(`{"ssh_key": "%s"}`, publicKeyStr))
	resp, err := http.Post(apiBaseURL+"/user", "application/json", bytes.NewBuffer(jsonData))
	if err != nil {
		log.Printf("Error checking public key: %v", err)
		return false
	}
	defer resp.Body.Close()

	var user User
	if err := json.NewDecoder(resp.Body).Decode(&user); err != nil {
		log.Printf("Error decoding user data: %v", err)
		return false
	}

	// Store the user ID in the SSH context so teaHandler can retrieve it.
	if ctx.Permissions().Extensions == nil {
		ctx.Permissions().Extensions = make(map[string]string)
	}
	ctx.Permissions().Extensions["user_id"] = user.ID
	ctx.Permissions().Extensions["has_profile"] = fmt.Sprintf("%v", user.HasProfile)
	return true
}

func deriveSessionKEK(s ssh.Session, userID string) ([]byte, error) {
	if err := waitForAgentForwarding(s); err != nil {
		return nil, err
	}

	l, err := ssh.NewAgentListener()
	if err != nil {
		return nil, err
	}
	defer l.Close()
	go ssh.ForwardAgentConnections(l, s)

	conn, err := net.Dial("unix", l.Addr().String())
	if err != nil {
		return nil, err
	}
	defer conn.Close()

	client := agent.NewClient(conn)
	pub := s.PublicKey()
	keys, err := client.List()
	if err != nil {
		return nil, err
	}

	var agentKey *agent.Key
	for _, key := range keys {
		if bytes.Equal(key.Marshal(), pub.Marshal()) {
			agentKey = key
			break
		}
	}
	if agentKey == nil {
		return nil, fmt.Errorf("authenticated SSH key is not available in the forwarded agent")
	}

	pubHash := sha256.Sum256(pub.Marshal())
	challenge := []byte("iatreon:ssh-agent-kek:v1:" + userID + ":" + base64.RawURLEncoding.EncodeToString(pubHash[:]))

	sig1, err := client.Sign(agentKey, challenge)
	if err != nil {
		return nil, err
	}
	sig2, err := client.Sign(agentKey, challenge)
	if err != nil {
		return nil, err
	}
	sigBytes1 := gossh.Marshal(sig1)
	sigBytes2 := gossh.Marshal(sig2)
	if !bytes.Equal(sigBytes1, sigBytes2) {
		return nil, fmt.Errorf("SSH key produced non-deterministic signatures; use an Ed25519 or deterministic RSA agent key for database unlock")
	}
	if err := pub.Verify(challenge, sig1); err != nil {
		return nil, fmt.Errorf("agent signature verification failed: %w", err)
	}

	reader := hkdf.New(sha256.New, sigBytes1, pubHash[:], []byte("iatreon-db-kek-v1:"+userID))
	kek := make([]byte, 32)
	if _, err := io.ReadFull(reader, kek); err != nil {
		return nil, err
	}
	return kek, nil
}

func waitForAgentForwarding(s ssh.Session) error {
	if ssh.AgentRequested(s) {
		return nil
	}

	timer := time.NewTimer(agentForwardingWait)
	defer timer.Stop()
	ticker := time.NewTicker(25 * time.Millisecond)
	defer ticker.Stop()

	for {
		select {
		case <-s.Context().Done():
			return s.Context().Err()
		case <-timer.C:
			return fmt.Errorf("SSH agent forwarding is required; reconnect with ssh -A and make sure your local ssh-agent is running with the login key loaded")
		case <-ticker.C:
			if ssh.AgentRequested(s) {
				return nil
			}
		}
	}
}

func unlockUserSession(userID string, sessionKEK []byte) (bool, error) {
	req, err := http.NewRequest(http.MethodPost, apiBaseURL+"/user/session?user_id="+userID, nil)
	if err != nil {
		return false, err
	}
	req.Header.Set("X-Session-Key", base64.StdEncoding.EncodeToString(sessionKEK))

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return false, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return false, fmt.Errorf("unlock failed: %s", resp.Status)
	}

	var payload unlockResponse
	if err := json.NewDecoder(resp.Body).Decode(&payload); err != nil {
		return false, err
	}
	return payload.HasProfile, nil
}

func teaHandler(s ssh.Session) (tea.Model, []tea.ProgramOption) {
	os.Setenv("TERM", "xterm-256color")
	os.Setenv("COLORTERM", "truecolor")
	os.Setenv("FORCE_COLOR", "1")

	lipgloss.SetColorProfile(termenv.TrueColor)
	lipgloss.SetHasDarkBackground(true)

	_, _, active := s.Pty()

	if !active {
		wish.Fatalln(s, "Error: Terminal session (PTY) required.")
		return nil, nil
	}

	userID, ok := s.Permissions().Extensions["user_id"]
	if !ok || userID == "" {
		wish.Fatalln(s, "Error: No user ID in session context.")
		return nil, nil
	}

	sessionKEK, err := deriveSessionKEK(s, userID)
	if err != nil {
		wish.Fatalln(s, "Error: "+err.Error())
		return nil, nil
	}
	hasProfile, err := unlockUserSession(userID, sessionKEK)
	if err != nil {
		for i := range sessionKEK {
			sessionKEK[i] = 0
		}
		wish.Fatalln(s, "Error: "+err.Error())
		return nil, nil
	}
	sessionKeyObj := tui.NewSessionKey(sessionKEK)
	go func() {
		<-s.Context().Done()
		sessionKeyObj.Wipe()
	}()

	model := tui.NewModel(userID, hasProfile, sessionKeyObj)
	return model, []tea.ProgramOption{tea.WithAltScreen()}
}

func StartSSHServer(host string, port int) {

	s, err := wish.NewServer(
		wish.WithAddress(fmt.Sprintf("%s:%d", host, port)),
		wish.WithHostKeyPath("/data/ssh/ssh_host_key"),
		wish.WithPublicKeyAuth(func(ctx ssh.Context, key ssh.PublicKey) bool {
			return getUserWithPubKey(ctx, key)
		}),
		wish.WithMiddleware(
			logging.Middleware(),
			activeterm.Middleware(),
			bubbletea.Middleware(teaHandler),
		),
	)
	if err != nil {
		log.Fatal("Failed to create SSH server: ", "err", err)
	}

	done := make(chan os.Signal, 1)
	signal.Notify(done, os.Interrupt, syscall.SIGINT, syscall.SIGTERM)
	log.Printf("Starting SSH server on %s:%d", host, port)

	go func() {
		if err = s.ListenAndServe(); err != nil {
			log.Fatal("Failed to start SSH server: ", "err", err)
		}
	}()

	<-done
	log.Print("Stopping SSH server...")
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	if err := s.Shutdown(ctx); err != nil {
		log.Fatal("Failed to shutdown SSH server: ", "err", err)
	}
}
