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
	localUserIDKeyUser    = "local-user-id"
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

func LocalUserID() (string, error) {
	return loadOrCreateLocalUserID(osCredentialStore{})
}

func loadOrCreateLocalUserID(store credentialStore) (string, error) {
	userID, err := store.Get(localWorkerKeyService, localUserIDKeyUser)
	if err == nil {
		if !isUUID(userID) {
			return "", fmt.Errorf("local user id is not a valid UUID: %q", userID)
		}
		return userID, nil
	}
	if !errors.Is(err, keyring.ErrNotFound) {
		return "", err
	}

	userID, err = newUUID()
	if err != nil {
		return "", err
	}
	if err := store.Set(localWorkerKeyService, localUserIDKeyUser, userID); err != nil {
		return "", err
	}
	return userID, nil
}

func newUUID() (string, error) {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", err
	}
	b[6] = (b[6] & 0x0f) | 0x40
	b[8] = (b[8] & 0x3f) | 0x80
	return fmt.Sprintf("%08x-%04x-%04x-%04x-%012x",
		b[0:4],
		b[4:6],
		b[6:8],
		b[8:10],
		b[10:16],
	), nil
}

func isUUID(value string) bool {
	if len(value) != 36 {
		return false
	}
	for i, c := range value {
		switch i {
		case 8, 13, 18, 23:
			if c != '-' {
				return false
			}
		default:
			if !('0' <= c && c <= '9') && !('a' <= c && c <= 'f') && !('A' <= c && c <= 'F') {
				return false
			}
		}
	}
	return true
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
