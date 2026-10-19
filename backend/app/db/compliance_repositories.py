"""Repositories for the compliance module (AI inventory, incidents, data-subject requests)."""

from __future__ import annotations

from typing import Generic, TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import AiSystemRecord, Base, DataRequestRecord, IncidentRecord

R = TypeVar("R", bound=Base)


class _Store(Generic[R]):
    model: type[R]
    order_column: str

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sessions = session_factory

    def add(self, record: R) -> None:
        with self._sessions.begin() as s:
            s.add(record)

    def save(self, record: R) -> None:
        """Persist changes made to a record previously returned by ``get`` or ``list``."""
        with self._sessions.begin() as s:
            s.merge(record)

    def get(self, record_id: str) -> R | None:
        with self._sessions() as s:
            return s.get(self.model, record_id)

    def list(self, limit: int = 500) -> list[R]:
        order = getattr(self.model, self.order_column)
        with self._sessions() as s:
            return list(s.scalars(select(self.model).order_by(order.desc()).limit(limit)).all())

    def count(self) -> int:
        with self._sessions() as s:
            return s.scalar(select(func.count()).select_from(self.model)) or 0


class AiSystemRepository(_Store[AiSystemRecord]):
    model = AiSystemRecord
    order_column = "created_at"


class IncidentRepository(_Store[IncidentRecord]):
    model = IncidentRecord
    order_column = "created_at"


class DataRequestRepository(_Store[DataRequestRecord]):
    model = DataRequestRecord
    order_column = "received_at"
