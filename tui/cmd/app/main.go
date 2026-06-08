package main

import (
	"flag"
	"fmt"
	"os"
	"tui/internal/tui"

	tea "github.com/charmbracelet/bubbletea"
)

func main() {

	var port int
	sshEnabled := flag.Bool("ssh", false, "Enable SSH mode")

	flag.IntVar(&port, "port", 8080, "The port number to use")

	flag.Parse()

	if *sshEnabled {

	} else {

		p := tea.NewProgram(tui.NewModel(), tea.WithAltScreen())
		if _, err := p.Run(); err != nil {
			fmt.Fprintf(os.Stderr, "could not start TUI: %v\n", err)
			os.Exit(1)
		}
	}
}
