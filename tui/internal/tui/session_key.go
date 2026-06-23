package tui

type SessionKey struct {
	key []byte
}

func NewSessionKey(key []byte) *SessionKey {
	return &SessionKey{key: key}
}

func (s *SessionKey) Get() []byte {
	if s == nil {
		return nil
	}
	return s.key
}

func (s *SessionKey) Wipe() {
	if s == nil {
		return
	}
	for i := range s.key {
		s.key[i] = 0
	}
}
