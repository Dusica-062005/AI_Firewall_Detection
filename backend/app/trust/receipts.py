"""Signed, hash-chained audit receipts (Feature 2, FR-5, FR-14).

Each receipt body is canonical JSON (sorted keys, no spaces). Its SHA-256 is the receipt
hash, and the body is signed with Ed25519. Every body includes the previous receipt's hash
(``GENESIS`` for the first), so deleting, reordering or editing any receipt breaks the chain.

Bodies hold categories, counts and decisions only: never transcript text or entity values.
``scripts/verify_chain.py`` re-implements verification with no project imports, so the chain
can be checked offline with only the database file and the public key.
"""

from __future__ import annotations

import base64
import hashlib
import json
import threading
import uuid
from dataclasses import asdict, dataclass, field

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import ReceiptRecord
from app.db.repositories import utcnow
from app.trust.keys import KeyStatus, key_id, public_key_pem

GENESIS = "GENESIS"
RECEIPT_SCHEMA = "receipt/1"


def canonical_json(body: dict) -> str:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


@dataclass(frozen=True)
class ReceiptFacts:
    """What happened to one request. No field can hold transcript text or entity values."""

    request_id: str
    event_id: str | None
    operation: str
    decision: str
    policy_version: str
    entity_counts: dict[str, int]
    tokens_created: int
    route: str  # LOCAL | CLOUD | NONE
    route_reason: str
    local_model: str | None
    cloud_model: str | None
    cloud_sent: bool
    protected_values_left: bool
    allowed_categories_sent: list[str] = field(default_factory=list)
    kill_switch: bool = False
    dial: str = "max_quality"
    normalize_on: bool = False
    # Audio calls only: {"format", "duration_s", "model", "transcription_ms"}. Never audio or text.
    audio: dict | None = None


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    count: int
    failed_seq: int | None
    reason: str


class ReceiptService:
    def __init__(
        self, sessions: sessionmaker[Session], signing_key: Ed25519PrivateKey | None, key_status: KeyStatus
    ) -> None:
        self._sessions = sessions
        self._signing_key = signing_key
        self.key_status = key_status
        self._lock = threading.Lock()
        self.public_key: Ed25519PublicKey | None = signing_key.public_key() if signing_key else None
        self.key_id = key_id(self.public_key) if self.public_key else None

    @property
    def public_key_pem(self) -> str | None:
        return public_key_pem(self.public_key) if self.public_key else None

    def append(self, facts: ReceiptFacts) -> ReceiptRecord:
        with self._lock, self._sessions.begin() as s:
            last = s.scalars(select(ReceiptRecord).order_by(ReceiptRecord.seq.desc()).limit(1)).first()
            seq = (last.seq + 1) if last else 1
            prev_hash = last.hash if last else GENESIS
            now = utcnow()
            body = {
                "schema": RECEIPT_SCHEMA,
                "receipt_id": f"rcp-{uuid.uuid4().hex[:16]}",
                "seq": seq,
                "timestamp": now.isoformat(),
                "prev_hash": prev_hash,
                **asdict(facts),
            }
            text = canonical_json(body)
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            signature = (
                base64.b64encode(self._signing_key.sign(text.encode("utf-8"))).decode("ascii")
                if self._signing_key
                else None
            )
            record = ReceiptRecord(
                seq=seq,
                receipt_id=body["receipt_id"],
                request_id=facts.request_id,
                created_at=now,
                body=text,
                prev_hash=prev_hash,
                hash=digest,
                signature=signature,
                key_id=self.key_id if signature else None,
            )
            s.add(record)
        return record

    def list(self, page: int, page_size: int) -> tuple[list[ReceiptRecord], int]:
        with self._sessions() as s:
            total = s.scalar(select(func.count()).select_from(ReceiptRecord)) or 0
            rows = s.scalars(
                select(ReceiptRecord).order_by(ReceiptRecord.seq.desc()).offset((page - 1) * page_size).limit(page_size)
            ).all()
        return list(rows), total

    def get(self, receipt_id: str) -> ReceiptRecord | None:
        with self._sessions() as s:
            return s.scalars(select(ReceiptRecord).where(ReceiptRecord.receipt_id == receipt_id)).first()

    def all(self) -> list[ReceiptRecord]:
        with self._sessions() as s:
            return list(s.scalars(select(ReceiptRecord).order_by(ReceiptRecord.seq)).all())

    def verify(self) -> VerifyResult:
        """In-process chain check. The offline script performs the same checks independently."""
        rows = self.all()
        if self.public_key is None:
            return VerifyResult(False, len(rows), None, "No signing key is configured, so signatures cannot be checked.")
        prev = GENESIS
        for index, row in enumerate(rows, start=1):
            try:
                body = json.loads(row.body)
            except ValueError:
                return VerifyResult(False, len(rows), row.seq, "Receipt body is not valid JSON.")
            if body.get("seq") != row.seq or row.seq != index:
                return VerifyResult(False, len(rows), row.seq, "Sequence gap or mismatch: a receipt was removed or reordered.")
            if body.get("prev_hash") != prev:
                return VerifyResult(False, len(rows), row.seq, "Previous-hash link does not match the preceding receipt.")
            if hashlib.sha256(row.body.encode("utf-8")).hexdigest() != row.hash:
                return VerifyResult(False, len(rows), row.seq, "Receipt hash does not match its body: the body was edited.")
            if not row.signature:
                return VerifyResult(False, len(rows), row.seq, "Receipt is unsigned.")
            try:
                self.public_key.verify(base64.b64decode(row.signature), row.body.encode("utf-8"))
            except (InvalidSignature, ValueError):
                return VerifyResult(False, len(rows), row.seq, "Signature is not valid for this body and public key.")
            prev = row.hash
        return VerifyResult(True, len(rows), None, f"Chain intact: {len(rows)} receipt(s) verified.")
