"""AES-256-GCM envelope: random DEK per row, KEK from settings (KMS in prod)."""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _kek(kek_b64: str) -> bytes:
    raw = base64.b64decode(kek_b64)
    if len(raw) != 32:
        raise ValueError("KEK must decode to 32 bytes")
    return raw


def seal(plaintext: bytes, kek_b64: str) -> tuple[bytes, bytes, bytes]:
    """Returns (wrapped_dek, nonce, ciphertext). wrapped_dek = kek_nonce(12) + sealed_dek."""
    dek = os.urandom(32)
    nonce = os.urandom(12)
    ct = AESGCM(dek).encrypt(nonce, plaintext, None)
    kek_nonce = os.urandom(12)
    sealed_dek = AESGCM(_kek(kek_b64)).encrypt(kek_nonce, dek, None)
    return kek_nonce + sealed_dek, nonce, ct


def open_envelope(wrapped_dek: bytes, nonce: bytes, ciphertext: bytes, kek_b64: str) -> bytes:
    kek_nonce, sealed_dek = wrapped_dek[:12], wrapped_dek[12:]
    dek = AESGCM(_kek(kek_b64)).decrypt(kek_nonce, sealed_dek, None)
    return AESGCM(dek).decrypt(nonce, ciphertext, None)
