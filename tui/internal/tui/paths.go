package tui

import (
	"fmt"
	"os"
	"path/filepath"
)

func getRootPath() (string, error) {
	root := os.Getenv("LOCALAPPDATA")

	if root == "" {
		var err error
		root, err = os.UserConfigDir()
		if err != nil {
			return "", fmt.Errorf("find user data directory: %w", err)
		}
	}
	dir := filepath.Join(root, "Iatreon")

	if err := os.MkdirAll(dir, 0o700); err != nil {
		return "", err
	}
	return dir, nil
}

func localWorkerDBPath() (string, error) {
	root, err := getRootPath()
	if err != nil {
		return "", err
	}

	dir := filepath.Join(root, "data")

	if err := os.MkdirAll(dir, 0o700); err != nil {
		return "", err
	}
	return filepath.Join(dir, "local_worker.sqlite3"), nil
}

func GetLogPath() (string, error) {
	root, err := getRootPath()
	if err != nil {
		return "", err
	}
	dir := filepath.Join(root, "logs")

	if err := os.MkdirAll(dir, 0o700); err != nil {
		return "", err
	}
	return filepath.Join(dir, "iatreon.log"), nil
}
