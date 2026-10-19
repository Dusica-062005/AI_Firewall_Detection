"""Token vault (Feature 1, FR-3).

Real values are stored Fernet-encrypted, keyed by request and token. Re-hydration reads them
back from the vault and decrypts them locally, so the round trip genuinely goes through the
vault rather than through request memory. Entries follow the audit retention period.
"""

from __future__ import annotations

from datetime import timedelta

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import VaultEntryRecord
from app.db.repositories import utcnow
from app.security.redactor import TokenInfo, rehydrate
from app.trust.keys import KeyStatus


class VaultUnavailable(Exception):
    """The vault key is missing or invalid, or an entry could not be decrypted."""


class TokenVault:
    def __init__(self, sessions: sessionmaker[Session], fernet: Fernet | None, key_status: KeyStatus) -> None:
        self._sessions = sessions
        self._fernet = fernet
        self.key_status = key_status

    @property
    def ready(self) -> bool:
        return self._fernet is not None

    def store(self, request_id: str, tokens: tuple[TokenInfo, ...]) -> int:
        if not tokens:
            return 0
        if self._fernet is None:
            raise VaultUnavailable(self.key_status.message)
        now = utcnow()
        with self._sessions.begin() as s:
            for t in tokens:
                s.add(
                    VaultEntryRecord(
                        request_id=request_id,
                        token=t.token,
                        entity_type=t.entity_type,
                        encrypted_value=self._fernet.encrypt(t.value.encode("utf-8")).decode("ascii"),
                        created_at=now,
                    )
                )
        return len(tokens)

    def load(self, request_id: str) -> tuple[TokenInfo, ...]:
        if self._fernet is None:
            raise VaultUnavailable(self.key_status.message)
        with self._sessions() as s:
            rows = s.scalars(select(VaultEntryRecord).where(VaultEntryRecord.request_id == request_id)).all()
        try:
            return tuple(
                TokenInfo(r.token, r.entity_type, self._fernet.decrypt(r.encrypted_value.encode("ascii")).decode("utf-8"))
                for r in rows
            )
        except InvalidToken as exc:
            raise VaultUnavailable("A vault entry could not be decrypted with the configured key.") from exc

    def rehydrate(self, request_id: str, text: str) -> str:
        return rehydrate(text, self.load(request_id))

    def purge_older_than(self, days: int) -> int:
        with self._sessions.begin() as s:
            result = s.execute(delete(VaultEntryRecord).where(VaultEntryRecord.created_at < utcnow() - timedelta(days=days)))
            return result.rowcount or 0

    def count(self) -> int:
        with self._sessions() as s:
            return s.scalar(select(func.count()).select_from(VaultEntryRecord)) or 0
