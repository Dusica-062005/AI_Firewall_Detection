"""Loading of the vault key and the receipt-signing key.

Both come from environment variables (backend/.env), never from code. Create them with
``python scripts/generate_keys.py``. A production deployment would keep them in an HSM or TPM.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from dataclasses import dataclass

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


@dataclass(frozen=True)
class KeyStatus:
    status: str  # CONFIGURED | NOT_CONFIGURED | INVALID
    message: str


def load_fernet(value: str) -> tuple[Fernet | None, KeyStatus]:
    if not value:
        return None, KeyStatus("NOT_CONFIGURED", "VAULT_KEY is not set. Run scripts/generate_keys.py.")
    try:
        return Fernet(value.encode("ascii")), KeyStatus("CONFIGURED", "Vault key loaded.")
    except (ValueError, binascii.Error, UnicodeEncodeError):
        return None, KeyStatus("INVALID", "VAULT_KEY is not a valid Fernet key.")


def load_signing_key(value: str) -> tuple[Ed25519PrivateKey | None, KeyStatus]:
    if not value:
        return None, KeyStatus("NOT_CONFIGURED", "RECEIPT_SIGNING_KEY is not set. Run scripts/generate_keys.py.")
    try:
        raw = base64.b64decode(value, validate=True)
        return Ed25519PrivateKey.from_private_bytes(raw), KeyStatus("CONFIGURED", "Receipt signing key loaded.")
    except (ValueError, binascii.Error):
        return None, KeyStatus("INVALID", "RECEIPT_SIGNING_KEY is not a base64 Ed25519 private key.")


def public_key_pem(public_key: Ed25519PublicKey) -> str:
    return public_key.public_bytes(
        encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode("ascii")


def key_id(public_key: Ed25519PublicKey) -> str:
    raw = public_key.public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    return hashlib.sha256(raw).hexdigest()[:16]
