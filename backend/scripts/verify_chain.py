"""Offline verifier for the signed, hash-chained audit receipts (Feature 2, FR-14, NFR-4).

Deliberately independent: it imports nothing from the firewall code base and needs only the
SQLite database file and the Ed25519 public key. Anyone holding those two files can check
that no receipt was edited, removed or reordered.

    python scripts/verify_chain.py --db data/firewall.db --pubkey data/keys/receipt_public_key.pem
    python scripts/verify_chain.py --db data/firewall.db --pubkey data/keys/receipt_public_key.pem --tamper-demo

Exit codes: 0 chain intact, 1 tampering detected, 2 could not verify (missing files, no receipts).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.serialization import load_pem_public_key

GENESIS = "GENESIS"


def read_only(db_path: Path) -> sqlite3.Connection:
    # as_uri() percent-encodes spaces and other characters in the path.
    return sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)


def verify(db_path: Path, public_key) -> tuple[bool, int, str]:
    """Return (ok, receipt_count, message)."""
    connection = read_only(db_path)
    try:
        rows = connection.execute(
            "SELECT seq, body, prev_hash, hash, signature FROM receipts ORDER BY seq"
        ).fetchall()
    finally:
        connection.close()
    if not rows:
        return False, 0, "NO RECEIPTS: nothing to verify yet."

    previous = GENESIS
    for index, (seq, body_text, prev_hash, digest, signature) in enumerate(rows, start=1):
        try:
            body = json.loads(body_text)
        except ValueError:
            return False, len(rows), f"TAMPERED at receipt #{seq}: body is not valid JSON."
        if seq != index or body.get("seq") != seq:
            return False, len(rows), f"TAMPERED at receipt #{seq}: sequence gap or mismatch (a receipt was removed or reordered)."
        if body.get("prev_hash") != previous or prev_hash != previous:
            return False, len(rows), f"TAMPERED at receipt #{seq}: previous-hash link is broken."
        if hashlib.sha256(body_text.encode("utf-8")).hexdigest() != digest:
            return False, len(rows), f"TAMPERED at receipt #{seq}: hash does not match the body (the body was edited)."
        if not signature:
            return False, len(rows), f"TAMPERED at receipt #{seq}: receipt is unsigned."
        try:
            public_key.verify(base64.b64decode(signature), body_text.encode("utf-8"))
        except (InvalidSignature, ValueError):
            return False, len(rows), f"TAMPERED at receipt #{seq}: signature is not valid for this public key."
        previous = digest
    return True, len(rows), f"CHAIN OK ({len(rows)} receipts)"


def tamper_copy(db_path: Path, workdir: Path) -> tuple[Path, str]:
    """Copy the database (never the original) and silently edit one receipt in the copy."""
    copy = workdir / "tampered.db"
    source = read_only(db_path)
    target = sqlite3.connect(copy)
    try:
        source.backup(target)  # consistent copy, including WAL contents
    finally:
        source.close()
    try:
        rows = target.execute("SELECT seq, body FROM receipts ORDER BY seq").fetchall()
        if not rows:
            return copy, "nothing to tamper with"
        seq, body_text = rows[len(rows) // 2]
        body = json.loads(body_text)
        body["protected_values_left"] = not body.get("protected_values_left", False)
        edited = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        target.execute("UPDATE receipts SET body = ? WHERE seq = ?", (edited, seq))
        target.commit()
        return copy, f"flipped protected_values_left on receipt #{seq}"
    finally:
        target.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the signed, hash-chained receipt log offline.")
    parser.add_argument("--db", required=True, type=Path, help="Path to the SQLite database file.")
    parser.add_argument("--pubkey", required=True, type=Path, help="Path to the Ed25519 public key (PEM).")
    parser.add_argument("--tamper-demo", action="store_true", help="Verify a tampered COPY to show detection.")
    args = parser.parse_args()

    if not args.db.exists():
        print(f"ERROR: database not found: {args.db}")
        return 2
    if not args.pubkey.exists():
        print(f"ERROR: public key not found: {args.pubkey}")
        return 2
    public_key = load_pem_public_key(args.pubkey.read_bytes())

    if args.tamper_demo:
        workdir = Path(tempfile.mkdtemp(prefix="receipt-tamper-"))
        try:
            copy, change = tamper_copy(args.db, workdir)
            print(f"Tamper demo: copied the database and {change} (the original is untouched).")
            ok, count, message = verify(copy, public_key)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
    else:
        ok, count, message = verify(args.db, public_key)

    print(message)
    if count == 0:
        return 2
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
