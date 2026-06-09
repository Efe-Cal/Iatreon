package main

import (
	"flag"
	"fmt"
	"os"
	"tui/internal/ssh"
	"tui/internal/tui"

	tea "github.com/charmbracelet/bubbletea"
)

func main() {

	var port int
	sshEnabled := flag.Bool("ssh", false, "Enable SSH mode")

	flag.IntVar(&port, "port", 2222, "The port number to use")

	flag.Parse()

	if *sshEnabled {
		fmt.Printf("Starting SSH server on port %d...\n", port)
		ssh.StartSSHServer("127.0.0.1", port)
	} else {

		p := tea.NewProgram(tui.NewModel(""), tea.WithAltScreen())
		if _, err := p.Run(); err != nil {
			fmt.Fprintf(os.Stderr, "could not start TUI: %v\n", err)
			os.Exit(1)
		}
	}
}
