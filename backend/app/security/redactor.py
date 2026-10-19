"""Deterministic, reversible tokenization using Presidio Anonymizer, verified independently.

Each protected value is replaced with a numbered token such as ``[PERSON_1]``. The same value
(case-insensitive) always receives the same token within one request, so a model can still
tell that two mentions refer to the same person. The token -> value map stays in request
memory and, encrypted, in the local vault; it never leaves the firewall.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import regex

from app.detection.entities import DetectedEntity


class RedactionError(Exception):
    """Redaction could not be completed or verified. Callers must fail closed."""


def placeholder(entity_type: str, index: int) -> str:
    return f"[{entity_type}_{index}]"


@dataclass(frozen=True)
class TokenInfo:
    token: str  # e.g. "[PERSON_1]"
    entity_type: str
    value: str  # first surface form seen; held in memory only

    @property
    def bare(self) -> str:
        return self.token[1:-1]


@dataclass(frozen=True)
class TokenizedText:
    text: str
    tokens: tuple[TokenInfo, ...] = field(default_factory=tuple)


def _value_key(entity_type: str, value: str) -> tuple[str, str]:
    return entity_type, " ".join(value.split()).casefold()


def assign_tokens(entities: list[DetectedEntity]) -> dict[tuple[str, str], TokenInfo]:
    """Number tokens per category in order of first appearance."""
    counters: dict[str, int] = {}
    assigned: dict[tuple[str, str], TokenInfo] = {}
    for e in sorted(entities, key=lambda e: (e.start, e.end)):
        key = _value_key(e.entity_type, e.value)
        if key in assigned:
            continue
        counters[e.entity_type] = counters.get(e.entity_type, 0) + 1
        assigned[key] = TokenInfo(placeholder(e.entity_type, counters[e.entity_type]), e.entity_type, e.value)
    return assigned


class Redactor:
    def __init__(self) -> None:
        from presidio_anonymizer import AnonymizerEngine

        self._engine = AnonymizerEngine()

    def redact(self, text: str, entities: list[DetectedEntity]) -> TokenizedText:
        if not entities:
            return TokenizedText(text, ())
        self._check_spans(text, entities)
        assigned = assign_tokens(entities)
        try:
            from presidio_anonymizer.entities import OperatorConfig, RecognizerResult

            def operator_for(entity_type: str):
                return lambda value: assigned[_value_key(entity_type, value)].token

            results = [RecognizerResult(e.entity_type, e.start, e.end, e.score) for e in entities]
            operators = {
                t: OperatorConfig("custom", {"lambda": operator_for(t)}) for t in {e.entity_type for e in entities}
            }
            anonymized = self._engine.anonymize(
                text=text,
                analyzer_results=results,
                operators=operators,
                merge_entities_with_spaces=False,
            ).text
        except Exception as exc:  # noqa: BLE001
            raise RedactionError("Anonymizer failed.") from exc

        expected = self._reference_redaction(text, entities, assigned)
        if anonymized != expected:
            raise RedactionError("Anonymizer output did not match the expected span replacement.")
        self._verify_no_values_remain(anonymized, entities)
        return TokenizedText(anonymized, tuple(assigned.values()))

    @staticmethod
    def _check_spans(text: str, entities: list[DetectedEntity]) -> None:
        ordered = sorted(entities, key=lambda e: e.start)
        previous_end = -1
        for e in ordered:
            if e.start < 0 or e.end > len(text) or e.start >= e.end:
                raise RedactionError("Entity span is outside the transcript.")
            if e.start < previous_end:
                raise RedactionError("Entity spans overlap.")
            if text[e.start : e.end] != e.value:
                raise RedactionError("Entity span does not match the detected value.")
            previous_end = e.end

    @staticmethod
    def _reference_redaction(text: str, entities: list[DetectedEntity], assigned: dict) -> str:
        result = text
        for e in sorted(entities, key=lambda e: e.start, reverse=True):
            result = result[: e.start] + assigned[_value_key(e.entity_type, e.value)].token + result[e.end :]
        return result

    @staticmethod
    def _verify_no_values_remain(redacted: str, entities: list[DetectedEntity]) -> None:
        for e in entities:
            if contains_value(redacted, e.value):
                raise RedactionError("A redacted value is still present in the output.")


def rehydrate(text: str, tokens: tuple[TokenInfo, ...] | list[TokenInfo]) -> str:
    """Swap tokens back to real values, locally, for the agent-facing view.

    Models sometimes drop the brackets, so both ``[PERSON_1]`` and ``PERSON_1`` are restored.
    Only tokens issued for this request are touched.
    """
    if not tokens:
        return text
    by_bare = {t.bare: t.value for t in tokens}
    alternation = "|".join(regex.escape(b) for b in sorted(by_bare, key=len, reverse=True))
    pattern = regex.compile(r"\[?(?<![A-Za-z0-9_])(" + alternation + r")(?![A-Za-z0-9_])\]?")
    return pattern.sub(lambda m: by_bare[m.group(1)], text)


def contains_value(text: str, value: str) -> bool:
    """Case-insensitive whole-token search used by redaction and outbound checks."""
    value = value.strip()
    if len(value) < 3:
        return False
    pattern = regex.compile(r"(?<!\w)" + regex.escape(value) + r"(?!\w)", regex.IGNORECASE)
    return pattern.search(text) is not None
