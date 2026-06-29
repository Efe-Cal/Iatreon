package main

import (
	"flag"
	"fmt"
	"log"
	"os"
	"tui/internal/ssh"
	"tui/internal/tui"

	tea "github.com/charmbracelet/bubbletea"
)

func main() {
	var port int
	var host string
	sshEnabled := flag.Bool("ssh", false, "Enable SSH mode")

	flag.StringVar(&host, "host", "127.0.0.1", "The host address to bind")
	flag.IntVar(&port, "port", 2222, "The port number to use")

	preview := flag.Bool("preview", false, "Run the preview mode")

	flag.Parse()

	f, err := tea.LogToFile("debug.log", "debug")
	if err != nil {
		log.Fatal(err)
	}
	defer f.Close()

	log.Println("Debug logging started")

	if *preview {
		p := tea.NewProgram(tui.NewPreviewModel())
		if _, err := p.Run(); err != nil {
			fmt.Fprintf(os.Stderr, "could not start TUI: %v\n", err)
			os.Exit(1)
		}
		return
	}

	if *sshEnabled {
		fmt.Printf("Starting SSH server on port %d...\n", port)
		ssh.StartSSHServer(host, port)
	} else {
		p := tea.NewProgram(tui.NewModel("ff6b65d2-bee0-4565-ad42-0d7ccb1f41a9 ", true), tea.WithAltScreen())
		if _, err := p.Run(); err != nil {
			fmt.Fprintf(os.Stderr, "could not start TUI: %v\n", err)
			os.Exit(1)
		}
	}
}
