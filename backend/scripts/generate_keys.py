"""Create the trust-layer secrets and store them in backend/.env (which git ignores).

    python scripts/generate_keys.py           # fills VAULT_KEY / RECEIPT_SIGNING_KEY only if empty
    python scripts/generate_keys.py --force   # rotate both keys

Rotating is destructive for existing data: vault entries encrypted with the old key can no
longer be re-hydrated, and receipts signed with the old key no longer verify. Delete
backend/data/ to start fresh after a rotation.
"""

from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

BACKEND = Path(__file__).resolve().parent.parent
ENV_FILE = BACKEND / ".env"
EXAMPLE_FILE = BACKEND / ".env.example"
PUBLIC_KEY_FILE = BACKEND / "data" / "keys" / "receipt_public_key.pem"


def read_env(lines: list[str]) -> dict[str, str]:
    values = {}
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def set_value(lines: list[str], key: str, value: str) -> list[str]:
    for i, line in enumerate(lines):
        if line.split("=", 1)[0].strip() == key and not line.lstrip().startswith("#"):
            lines[i] = f"{key}={value}"
            return lines
    return [*lines, f"{key}={value}"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="Replace keys that are already set.")
    args = parser.parse_args()

    if not ENV_FILE.exists():
        if not EXAMPLE_FILE.exists():
            print("ERROR: backend/.env and backend/.env.example are both missing.")
            return 1
        ENV_FILE.write_text(EXAMPLE_FILE.read_text(encoding="utf-8"), encoding="utf-8")
        print("Created backend/.env from .env.example.")

    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    current = read_env(lines)

    if args.force or not current.get("VAULT_KEY"):
        lines = set_value(lines, "VAULT_KEY", Fernet.generate_key().decode("ascii"))
        print("VAULT_KEY written to backend/.env.")
    else:
        print("VAULT_KEY already set; kept (use --force to rotate).")

    if args.force or not current.get("RECEIPT_SIGNING_KEY"):
        private = Ed25519PrivateKey.generate()
        raw = private.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        lines = set_value(lines, "RECEIPT_SIGNING_KEY", base64.b64encode(raw).decode("ascii"))
        print("RECEIPT_SIGNING_KEY written to backend/.env.")
    else:
        private = Ed25519PrivateKey.from_private_bytes(base64.b64decode(current["RECEIPT_SIGNING_KEY"]))
        print("RECEIPT_SIGNING_KEY already set; kept (use --force to rotate).")

    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")

    PUBLIC_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC_KEY_FILE.write_bytes(
        private.public_key().public_bytes(
            encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    print(f"Public key for the offline verifier: {PUBLIC_KEY_FILE.relative_to(BACKEND)}")
    print("Restart the backend to load the keys.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
