"""Canary set file format (app/canaries/canaries.json). All values in it are synthetic."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CANARY_FILE = Path(__file__).resolve().parent / "canaries.json"

Language = Literal["en", "hinglish", "hi", "kn", "ta"]
Script = Literal["latin", "native"]
Difficulty = Literal["plain", "spelled_digits", "split_id", "hinglish", "mixed"]
PlantedType = Literal["PERSON", "PATIENT_ID", "PHONE_NUMBER", "GOVERNMENT_ID", "DATE_OF_BIRTH", "EMAIL_ADDRESS"]
# Types whose canonical value is a number, so leaks are also matched on digits alone.
NUMERIC_TYPES = frozenset({"PATIENT_ID", "PHONE_NUMBER", "GOVERNMENT_ID"})


class PlantedValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: PlantedType
    canonical: str = Field(min_length=1)
    # Exact [start, end) ranges in the call text of every surface part (split IDs have several).
    spans: list[tuple[int, int]] = Field(min_length=1)


class CanaryCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: str = Field(pattern=r"^can-\d{4}$")
    language: Language
    script: Script
    difficulty: Difficulty
    profile: str
    text: str = Field(min_length=1)
    planted: list[PlantedValue] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def _spans_in_range(self) -> "CanaryCall":
        for value in self.planted:
            for start, end in value.spans:
                if not 0 <= start < end <= len(self.text):
                    raise ValueError(f"{self.call_id}: span [{start}, {end}) is outside the text.")
        return self

    def surfaces(self, value: PlantedValue) -> list[str]:
        return [self.text[s:e] for s, e in value.spans]


class CanarySet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    generated_with_seed: int
    calls: list[CanaryCall] = Field(min_length=1)

    def summary(self) -> dict:
        return {
            "version": self.version,
            "calls": len(self.calls),
            "planted_values": sum(len(c.planted) for c in self.calls),
            "by_language": dict(sorted(Counter(c.language for c in self.calls).items())),
            "by_script": dict(sorted(Counter(f"{c.language}/{c.script}" for c in self.calls).items())),
            "by_difficulty": dict(sorted(Counter(c.difficulty for c in self.calls).items())),
            "by_type": dict(sorted(Counter(p.type for c in self.calls for p in c.planted).items())),
        }


def load_canary_set(path: Path = CANARY_FILE) -> CanarySet:
    return CanarySet.model_validate(json.loads(path.read_text(encoding="utf-8")))
