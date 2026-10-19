"""Operator controls: kill switch (Feature 3, FR-6) and privacy-utility dial (Feature 4, FR-7).

Values live in the database and are read on every request (and the kill switch again right
before any outbound send), so a change takes effect immediately and survives restarts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session, sessionmaker

from app.db.models import RuntimeControlRecord
from app.db.repositories import utcnow
from app.policy.dial import DIAL_POSITIONS

KILL_SWITCH = "kill_switch"
DIAL = "dial"


@dataclass(frozen=True)
class Controls:
    kill_switch: bool
    dial: str
    kill_switch_updated_at: datetime | None
    dial_updated_at: datetime | None

    @property
    def cloud_path(self) -> str:
        return "BLOCKED" if self.kill_switch else "ACTIVE"


class ControlsService:
    def __init__(self, sessions: sessionmaker[Session], default_dial: str) -> None:
        self._sessions = sessions
        self._default_dial = default_dial

    def get(self) -> Controls:
        with self._sessions() as s:
            kill = s.get(RuntimeControlRecord, KILL_SWITCH)
            dial = s.get(RuntimeControlRecord, DIAL)
        dial_value = dial.value if dial and dial.value in DIAL_POSITIONS else self._default_dial
        return Controls(
            kill_switch=bool(kill and kill.value == "on"),
            dial=dial_value,
            kill_switch_updated_at=kill.updated_at if kill else None,
            dial_updated_at=dial.updated_at if dial else None,
        )

    def kill_switch_on(self) -> bool:
        with self._sessions() as s:
            kill = s.get(RuntimeControlRecord, KILL_SWITCH)
        return bool(kill and kill.value == "on")

    def set_kill_switch(self, enabled: bool) -> Controls:
        self._set(KILL_SWITCH, "on" if enabled else "off")
        return self.get()

    def set_dial(self, position: str) -> Controls:
        if position not in DIAL_POSITIONS:
            raise ValueError(f"Unknown dial position {position}.")
        self._set(DIAL, position)
        return self.get()

    def _set(self, key: str, value: str) -> None:
        with self._sessions.begin() as s:
            record = s.get(RuntimeControlRecord, key)
            if record is None:
                s.add(RuntimeControlRecord(key=key, value=value, updated_at=utcnow()))
            else:
                record.value = value
                record.updated_at = utcnow()
