package main

import (
	"flag"
	"fmt"
	"log"
	"os"
	"tui/internal/tui"

	tea "github.com/charmbracelet/bubbletea"
)

func main() {
	preview := flag.Bool("preview", false, "Run the preview mode")

	flag.Parse()

	file_path, err := tui.GetLogPath()
	if err != nil {
		log.Fatal(err)
	}

	f, err := tea.LogToFile(file_path, "debug")
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

	userID, err := tui.LocalUserID()
	if err != nil {
		fmt.Fprintf(os.Stderr, "could not load local user: %v\n", err)
		os.Exit(1)
	}

	p := tea.NewProgram(tui.NewLocalModel(userID), tea.WithAltScreen())
	if _, err := p.Run(); err != nil {
		fmt.Fprintf(os.Stderr, "could not start TUI: %v\n", err)
		os.Exit(1)
	}
}
