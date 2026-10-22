"""Custom deterministic recognizers for demo-specific identifiers."""

from __future__ import annotations

from pathlib import Path

import regex
import yaml
from presidio_analyzer import EntityRecognizer, RecognizerResult
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class DetectionConfigError(Exception):
    """The detection configuration file is missing or invalid."""


class CategoryInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    limitations: str


class CustomRecognizerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    entity: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,39}$")
    pattern: str = Field(min_length=3, max_length=3000)  # long enough for a name deny-list
    group: int = Field(default=0, ge=0, le=9)
    score: float = Field(default=0.85, gt=0.0, le=1.0)

    @field_validator("pattern")
    @classmethod
    def _compiles(cls, value: str) -> str:
        try:
            regex.compile(value)
        except regex.error as exc:
            raise ValueError(f"Invalid regular expression: {exc}") from exc
        return value


class DetectionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    categories: dict[str, CategoryInfo]
    presidio_entities: dict[str, str]
    custom_recognizers: list[CustomRecognizerConfig] = Field(default_factory=list)
    # spaCy PERSON spans made only of these words are dropped (Hinglish function words).
    person_stopwords: list[str] = Field(default_factory=list)

    def model_post_init(self, __context: object) -> None:
        known = set(self.categories)
        for target in self.presidio_entities.values():
            if target not in known:
                raise ValueError(f"Presidio mapping targets unknown category {target}.")
        for rec in self.custom_recognizers:
            if rec.entity not in known:
                raise ValueError(f"Recognizer {rec.name} targets unknown category {rec.entity}.")


def load_detection_config(path: Path) -> DetectionConfig:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return DetectionConfig.model_validate(raw)
    except FileNotFoundError as exc:
        raise DetectionConfigError("Detection configuration file not found.") from exc
    except (yaml.YAMLError, ValidationError, ValueError) as exc:
        raise DetectionConfigError("Detection configuration file is invalid.") from exc


class ContextualPatternRecognizer(EntityRecognizer):
    """Regex recognizer that reports only the configured capture group.

    Presidio's PatternRecognizer reports the full match. Returning the capture group lets
    a pattern require context such as "patient ID is" while redacting only the value.
    """

    def __init__(self, config: CustomRecognizerConfig) -> None:
        self._config = config
        self._regex = regex.compile(config.pattern, regex.IGNORECASE)
        super().__init__(supported_entities=[config.entity], name=config.name, supported_language="en")

    def load(self) -> None:  # nothing to load
        return None

    def analyze(self, text: str, entities: list[str], nlp_artifacts: object = None) -> list[RecognizerResult]:
        if self._config.entity not in entities:
            return []
        results: list[RecognizerResult] = []
        for match in self._regex.finditer(text, timeout=1.0):
            start, end = match.span(self._config.group)
            if start < 0 or end <= start:
                continue
            results.append(
                RecognizerResult(
                    entity_type=self._config.entity,
                    start=start,
                    end=end,
                    score=self._config.score,
                    recognition_metadata={
                        RecognizerResult.RECOGNIZER_NAME_KEY: self.name,
                        RecognizerResult.RECOGNIZER_IDENTIFIER_KEY: self.id,
                    },
                )
            )
        return results
