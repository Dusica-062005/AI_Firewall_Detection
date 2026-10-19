from __future__ import annotations

import pytest

from app.detection.entities import DetectedEntity
from app.security.redactor import RedactionError, Redactor, contains_value, rehydrate
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
    assert redactor.redact(DEMO_TRANSCRIPT, entities).text == (
        "My name is [PERSON_1], my patient ID is [PATIENT_ID_1], and I need help with my appointment."
    )


def test_same_value_gets_the_same_token(redactor):
    text = "Ann Lee 1234 ann lee Raj Kumar"
    entities = [
        entity(text, "Ann Lee", "PERSON"),
        entity(text, "1234", "PATIENT_ID"),
        entity(text, "ann lee", "PERSON"),
        entity(text, "Raj Kumar", "PERSON"),
    ]
    result = redactor.redact(text, entities)
    assert result.text == "[PERSON_1] [PATIENT_ID_1] [PERSON_1] [PERSON_2]"
    assert [t.token for t in result.tokens] == ["[PERSON_1]", "[PATIENT_ID_1]", "[PERSON_2]"]


def test_tokenized_text_contains_no_original_values(redactor):
    text = "Ravi Sharma, MRN 552210, phone 9876543210. Ravi Sharma will call back."
    entities = [
        entity(text, "Ravi Sharma", "PERSON"),
        entity(text, "552210", "PATIENT_ID"),
        entity(text, "9876543210", "PHONE_NUMBER"),
        entity(text, "Ravi Sharma", "PERSON", 1),
    ]
    result = redactor.redact(text, entities)
    assert not any(contains_value(result.text, e.value) for e in entities)


def test_rehydrate_restores_every_entity(redactor):
    entities = [entity(DEMO_TRANSCRIPT, "John Smith", "PERSON"), entity(DEMO_TRANSCRIPT, "48291", "PATIENT_ID")]
    result = redactor.redact(DEMO_TRANSCRIPT, entities)
    assert rehydrate(result.text, result.tokens) == DEMO_TRANSCRIPT


def test_rehydrate_handles_bare_tokens_and_ignores_unknown_ones(redactor):
    text = "Ann Lee and Bo Chen"
    result = redactor.redact(text, [entity(text, "Ann Lee", "PERSON"), entity(text, "Bo Chen", "PERSON")])
    summary = "- PERSON_1 spoke to [PERSON_2]; [PERSON_3] and PERSON_10 are not ours."
    assert rehydrate(summary, result.tokens) == "- Ann Lee spoke to Bo Chen; [PERSON_3] and PERSON_10 are not ours."


def test_no_entities_returns_text_unchanged(redactor):
    result = redactor.redact("hello", [])
    assert result.text == "hello" and result.tokens == ()


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
