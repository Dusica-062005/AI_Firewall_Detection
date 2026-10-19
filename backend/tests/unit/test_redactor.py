from __future__ import annotations

import pytest

from app.detection.entities import DetectedEntity
from app.security.redactor import RedactionError, Redactor
from tests.conftest import DEMO_TRANSCRIPT


@pytest.fixture(scope="module")
def redactor():
    return Redactor()


def entity(text, value, entity_type, occurrence=0):
    start = -1
    for _ in range(occurrence + 1):
        start = text.index(value, start + 1)
    return DetectedEntity(entity_type, start, start + len(value), 0.9, value, "test")


def test_redaction_replaces_the_correct_spans(redactor):
    entities = [entity(DEMO_TRANSCRIPT, "John Smith", "PERSON"), entity(DEMO_TRANSCRIPT, "48291", "PATIENT_ID")]
    assert redactor.redact(DEMO_TRANSCRIPT, entities) == (
        "My name is [PERSON], my patient ID is [PATIENT_ID], and I need help with my appointment."
    )


def test_redaction_of_adjacent_and_repeated_values(redactor):
    text = "Ann Lee 1234 Ann Lee"
    entities = [entity(text, "Ann Lee", "PERSON"), entity(text, "1234", "PATIENT_ID"), entity(text, "Ann Lee", "PERSON", 1)]
    assert redactor.redact(text, entities) == "[PERSON] [PATIENT_ID] [PERSON]"


def test_no_entities_returns_text_unchanged(redactor):
    assert redactor.redact("hello", []) == "hello"


def test_overlapping_spans_are_rejected(redactor):
    text = "John Smith"
    with pytest.raises(RedactionError):
        redactor.redact(text, [
            DetectedEntity("PERSON", 0, 10, 0.9, "John Smith", "t"),
            DetectedEntity("PERSON", 5, 10, 0.9, "Smith", "t"),
        ])


def test_mismatched_span_is_rejected(redactor):
    with pytest.raises(RedactionError):
        redactor.redact("John Smith", [DetectedEntity("PERSON", 0, 4, 0.9, "Jane", "t")])


def test_value_remaining_after_redaction_is_rejected(redactor):
    # Only the first occurrence is supplied, so the verifier must refuse the output.
    text = "John Smith called. John Smith again."
    with pytest.raises(RedactionError):
        redactor.redact(text, [entity(text, "John Smith", "PERSON")])
