package tui

import (
	"encoding/base64"
	"errors"
	"testing"

	"github.com/zalando/go-keyring"
)

type fakeCredentialStore struct {
	value string
	err   error
	set   string
}

func (f *fakeCredentialStore) Get(service, user string) (string, error) {
	if f.err != nil {
		return "", f.err
	}
	return f.value, nil
}

func (f *fakeCredentialStore) Set(service, user, password string) error {
	f.set = password
	return nil
}

func TestLoadOrCreateWorkerKeyLoadsExistingKey(t *testing.T) {
	want := []byte("12345678901234567890123456789012")
	store := &fakeCredentialStore{value: base64.StdEncoding.EncodeToString(want)}

	got, err := loadOrCreateWorkerKey(store)
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != string(want) {
		t.Fatalf("unexpected key: %q", got)
	}
	if store.set != "" {
		t.Fatal("existing key should not be replaced")
	}
}

func TestLoadOrCreateWorkerKeyCreatesMissingKey(t *testing.T) {
	store := &fakeCredentialStore{err: keyring.ErrNotFound}

	got, err := loadOrCreateWorkerKey(store)
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 32 {
		t.Fatalf("unexpected key length: %d", len(got))
	}
	if store.set == "" {
		t.Fatal("new key was not stored")
	}
	decoded, err := base64.StdEncoding.DecodeString(store.set)
	if err != nil {
		t.Fatal(err)
	}
	if len(decoded) != 32 {
		t.Fatalf("stored key length: %d", len(decoded))
	}
}

func TestLoadOrCreateWorkerKeyRejectsBadStoredKey(t *testing.T) {
	for _, value := range []string{"not-base64", base64.StdEncoding.EncodeToString([]byte("short"))} {
		store := &fakeCredentialStore{value: value}
		if _, err := loadOrCreateWorkerKey(store); err == nil {
			t.Fatalf("expected error for %q", value)
		}
	}
}

func TestLoadOrCreateWorkerKeyReturnsCredentialErrors(t *testing.T) {
	want := errors.New("keychain unavailable")
	store := &fakeCredentialStore{err: want}

	if _, err := loadOrCreateWorkerKey(store); !errors.Is(err, want) {
		t.Fatalf("expected %v, got %v", want, err)
	}
}

func TestLoadOrCreateLocalUserIDLoadsExistingID(t *testing.T) {
	want := "ff6b65d2-bee0-4565-ad42-0d7ccb1f41a9"
	store := &fakeCredentialStore{value: want}

	got, err := loadOrCreateLocalUserID(store)
	if err != nil {
		t.Fatal(err)
	}
	if got != want {
		t.Fatalf("unexpected user id: %q", got)
	}
	if store.set != "" {
		t.Fatal("existing user id should not be replaced")
	}
}

func TestLoadOrCreateLocalUserIDCreatesMissingID(t *testing.T) {
	store := &fakeCredentialStore{err: keyring.ErrNotFound}

	got, err := loadOrCreateLocalUserID(store)
	if err != nil {
		t.Fatal(err)
	}
	if !isUUID(got) {
		t.Fatalf("new user id is not a UUID: %q", got)
	}
	if store.set != got {
		t.Fatalf("stored user id %q, want %q", store.set, got)
	}
}

func TestLoadOrCreateLocalUserIDRejectsBadStoredID(t *testing.T) {
	store := &fakeCredentialStore{value: "not-a-uuid"}

	if _, err := loadOrCreateLocalUserID(store); err == nil {
		t.Fatal("expected invalid user id error")
	}
}
