package tui

import (
	"crypto/rand"
	"encoding/base64"
	"errors"
	"fmt"
	"os"
	"path/filepath"

	"github.com/zalando/go-keyring"
)

const (
	localWorkerKeyService = "Iatreon"
	localWorkerKeyUser    = "local-worker-db-key"
)

type credentialStore interface {
	Get(service, user string) (string, error)
	Set(service, user, password string) error
}

type osCredentialStore struct{}

func (osCredentialStore) Get(service, user string) (string, error) {
	return keyring.Get(service, user)
}

func (osCredentialStore) Set(service, user, password string) error {
	return keyring.Set(service, user, password)
}

func loadOrCreateWorkerKey(store credentialStore) ([]byte, error) {
	encoded, err := store.Get(localWorkerKeyService, localWorkerKeyUser)
	if err == nil {
		key, err := base64.StdEncoding.DecodeString(encoded)
		if err != nil {
			return nil, fmt.Errorf("local worker database key is not valid base64: %w", err)
		}
		if len(key) != 32 {
			return nil, fmt.Errorf("local worker database key must be 32 bytes, got %d", len(key))
		}
		return key, nil
	}
	if !errors.Is(err, keyring.ErrNotFound) {
		return nil, err
	}

	key := make([]byte, 32)
	if _, err := rand.Read(key); err != nil {
		return nil, err
	}
	if err := store.Set(localWorkerKeyService, localWorkerKeyUser, base64.StdEncoding.EncodeToString(key)); err != nil {
		zeroBytes(key)
		return nil, err
	}
	return key, nil
}

func localWorkerDBPath() (string, error) {
	dir, err := os.UserConfigDir()
	if err != nil {
		return "", err
	}
	dir = filepath.Join(dir, "Iatreon")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return "", err
	}
	return filepath.Join(dir, "local_worker.sqlite3"), nil
}

func zeroBytes(b []byte) {
	for i := range b {
		b[i] = 0
	}
}
