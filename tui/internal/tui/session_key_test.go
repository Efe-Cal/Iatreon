package tui

import "testing"

func TestSessionKeyGetAndWipe(t *testing.T) {
	key := []byte{1, 2, 3}
	sessionKey := NewSessionKey(key)

	got := sessionKey.Get()
	if len(got) != 3 || got[0] != 1 {
		t.Fatalf("unexpected key: %v", got)
	}

	sessionKey.Wipe()
	for i, b := range key {
		if b != 0 {
			t.Fatalf("key byte %d was not wiped: %v", i, key)
		}
	}

	var nilKey *SessionKey
	if nilKey.Get() != nil {
		t.Fatal("nil session key should return nil bytes")
	}
	nilKey.Wipe()
}
