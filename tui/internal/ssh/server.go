package ssh

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/log"

	"github.com/charmbracelet/ssh"
	"github.com/charmbracelet/wish"
	"github.com/charmbracelet/wish/activeterm"
	"github.com/charmbracelet/wish/bubbletea"
	"github.com/charmbracelet/wish/logging"
	gossh "golang.org/x/crypto/ssh"

	"tui/internal/tui"
)

type User struct {
	ID         string `json:"user_id"`
	HasProfile bool   `json:"has_profile"`
}

func getUserWithPubKey(ctx ssh.Context, key ssh.PublicKey) bool {
	authKeyBytes := gossh.MarshalAuthorizedKey(key)

	publicKeyStr := string(bytes.TrimSpace(authKeyBytes))

	jsonData := []byte(fmt.Sprintf(`{"ssh_key": "%s"}`, publicKeyStr))
	resp, err := http.Post("http://localhost:8000/user", "application/json", bytes.NewBuffer(jsonData))
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

func teaHandler(s ssh.Session) (tea.Model, []tea.ProgramOption) {
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
	hasProfileStr, _ := s.Permissions().Extensions["has_profile"]
	hasProfile := hasProfileStr == "true"

	model := tui.NewModel(userID, hasProfile)
	return model, []tea.ProgramOption{tea.WithAltScreen()}
}

func StartSSHServer(host string, port int) {

	s, err := wish.NewServer(
		wish.WithAddress(fmt.Sprintf("%s:%d", host, port)),
		wish.WithHostKeyPath("./ssh_host_key"),
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
