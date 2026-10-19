from __future__ import annotations

from app.detection.analyzer import REPEAT_RECOGNIZER, SensitiveDataAnalyzer
from app.detection.entities import DetectedEntity
from tests.conftest import DEMO_TRANSCRIPT


def by_type(entities, entity_type):
    return [e for e in entities if e.entity_type == entity_type]


def test_person_name_is_detected(analyzer):
    entities = analyzer.analyze(DEMO_TRANSCRIPT)
    people = by_type(entities, "PERSON")
    assert [p.value for p in people] == ["John Smith"]
    assert DEMO_TRANSCRIPT[people[0].start : people[0].end] == "John Smith"
    assert 0 < people[0].score <= 1


def test_patient_id_is_detected_with_exact_span(analyzer):
    entities = analyzer.analyze(DEMO_TRANSCRIPT)
    ids = by_type(entities, "PATIENT_ID")
    assert len(ids) == 1
    assert ids[0].value == "48291"
    assert DEMO_TRANSCRIPT[ids[0].start : ids[0].end] == "48291"
    assert ids[0].recognizer == "patient-id-contextual"


def test_bare_number_is_not_a_patient_id(analyzer):
    entities = analyzer.analyze("Please call me back in 48291 seconds about the order.")
    assert not by_type(entities, "PATIENT_ID")


def test_multiple_entities_in_one_transcript(analyzer):
    text = (
        "This is Maria Gonzalez, patient ID MRN-7781234. Call me on 416-555-0199 or email "
        "maria.gonzalez@example.com. My account number is 7730-1142-9981."
    )
    types = {e.entity_type for e in analyzer.analyze(text)}
    assert {"PERSON", "PATIENT_ID", "PHONE_NUMBER", "EMAIL_ADDRESS", "ACCOUNT_NUMBER"} <= types


def test_government_id_detected(analyzer):
    entities = analyzer.analyze("For verification my social security number is 512-44-7321.")
    ids = by_type(entities, "GOVERNMENT_ID")
    assert ids and ids[0].value == "512-44-7321"


def test_normal_transcript_has_no_entities(analyzer):
    assert analyzer.analyze("Hi, what are your support hours on Saturday?") == []


def test_results_are_non_overlapping_and_sorted(analyzer):
    text = "Email john.smith@example.com or call John Smith."
    entities = analyzer.analyze(text)
    for a, b in zip(entities, entities[1:]):
        assert a.end <= b.start
    # URL fragments inside the email must not survive as separate spans.
    assert all(e.entity_type != "URL" for e in entities)


def test_overlap_resolution_prefers_score_then_length(analyzer):
    low = DetectedEntity("LOCATION", 0, 10, 0.5, "John Smith", "presidio")
    high = DetectedEntity("PERSON", 0, 10, 0.85, "John Smith", "presidio")
    shorter = DetectedEntity("PERSON", 5, 10, 0.85, "Smith", "presidio")
    resolved = analyzer._resolve_overlaps([low, shorter, high])
    assert resolved == [high]


def test_repeated_values_are_propagated(analyzer):
    text = "My name is John Smith. Yes, john smith is correct."
    entities = analyzer.analyze(text)
    people = by_type(entities, "PERSON")
    assert len(people) == 2
    assert any(p.recognizer == REPEAT_RECOGNIZER or p.start > 20 for p in people)


def test_scan_ignores_placeholders(analyzer):
    assert analyzer.scan("My name is [PERSON] and my patient ID is [PATIENT_ID].") == []


def test_unloaded_analyzer_raises(analyzer):
    import pytest

    from app.detection.analyzer import DetectionError

    fresh = SensitiveDataAnalyzer(analyzer.config, "missing-model", 0.35, 0.6)
    with pytest.raises(DetectionError):
        fresh.analyze("text")
