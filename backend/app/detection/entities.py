"""Detection result types. Values stay in memory for the lifetime of a single request."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DetectedEntity:
    entity_type: str
    start: int
    end: int
    score: float
    value: str
    recognizer: str
    low_confidence: bool = False
    normalized: bool = False  # found in the spoken-number normalized text (FR-15)

    @property
    def length(self) -> int:
        return self.end - self.start
