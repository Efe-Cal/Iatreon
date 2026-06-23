import base64
import json
import os
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


KeyBuffer = bytes | bytearray


_session_kek: ContextVar[bytearray | None] = ContextVar('session_kek', default=None)


@dataclass(frozen=True)
class EncryptedEnvelope:
    alg: str
    nonce: str
    ciphertext: str


def set_session_kek(encoded_key: str):
    key = bytearray(base64.b64decode(encoded_key, validate=True))
    if len(key) != 32:
        zero_bytes(key)
        raise ValueError('session encryption key must be 32 bytes')
    return _session_kek.set(key)


def reset_session_kek(token) -> None:
    key = _session_kek.get()
    _session_kek.reset(token)
    zero_bytes(key)


def require_session_kek() -> bytearray:
    key = _session_kek.get()
    if key is None:
        raise ValueError('request encryption key missing')
    return key


def new_data_key() -> bytearray:
    return bytearray(os.urandom(32))


def zero_bytes(value: bytearray | None) -> None:
    if value is not None:
        value[:] = b'\x00' * len(value)


def _encode_envelope(nonce: bytes, ciphertext: bytes) -> str:
    envelope = EncryptedEnvelope(
        alg='AES-256-GCM',
        nonce=base64.b64encode(nonce).decode('ascii'),
        ciphertext=base64.b64encode(ciphertext).decode('ascii'),
    )
    return json.dumps(envelope.__dict__, separators=(',', ':'))


def _decode_envelope(value: str) -> tuple[bytes, bytes]:
    payload = json.loads(value)
    if payload.get('alg') != 'AES-256-GCM':
        raise ValueError('unsupported encryption envelope')
    return (
        base64.b64decode(payload['nonce'], validate=True),
        base64.b64decode(payload['ciphertext'], validate=True),
    )


def encrypt_bytes(key: KeyBuffer, plaintext: KeyBuffer, aad: bytes) -> str:
    nonce = os.urandom(12)
    ciphertext = AESGCM(bytes(key)).encrypt(nonce, bytes(plaintext), aad)
    return _encode_envelope(nonce, ciphertext)


def decrypt_bytes(key: KeyBuffer, envelope: str, aad: bytes) -> bytearray:
    nonce, ciphertext = _decode_envelope(envelope)
    return bytearray(AESGCM(bytes(key)).decrypt(nonce, ciphertext, aad))


def wrap_data_key(data_key: KeyBuffer, user_id: uuid.UUID) -> str:
    return encrypt_bytes(require_session_kek(), data_key, _aad('user-data-key', user_id))


def unwrap_data_key(encrypted_data_key: str, user_id: uuid.UUID) -> bytearray:
    return decrypt_bytes(require_session_kek(), encrypted_data_key, _aad('user-data-key', user_id))


def encrypt_json(data_key: KeyBuffer, user_id: uuid.UUID, purpose: str, value: dict[str, Any]) -> str:
    plaintext = bytearray(json.dumps(value, separators=(',', ':'), default=str).encode('utf-8'))
    try:
        return encrypt_bytes(data_key, plaintext, _aad(purpose, user_id))
    finally:
        zero_bytes(plaintext)


def decrypt_json(data_key: KeyBuffer, user_id: uuid.UUID, purpose: str, envelope: str) -> dict[str, Any]:
    plaintext = decrypt_bytes(data_key, envelope, _aad(purpose, user_id))
    try:
        return json.loads(bytes(plaintext).decode('utf-8'))
    finally:
        zero_bytes(plaintext)


def _aad(purpose: str, user_id: uuid.UUID) -> bytes:
    return f'iatreon:{purpose}:{user_id}'.encode('utf-8')
