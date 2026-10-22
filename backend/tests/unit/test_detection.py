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
    assert analyzer.analyze("Hi, what are your support hours?") == []


def test_concrete_dates_are_kept_and_vague_ones_dropped(analyzer):
    dates = by_type(analyzer.analyze("What are your support hours on Saturday?"), "DATE_TIME")
    assert [d.value for d in dates] == ["Saturday"]


def test_indian_identifiers_are_detected(analyzer):
    entities = analyzer.analyze("Mera Aadhaar number hai 2345 6789 0123 aur mobile +91 98765 43210 hai.")
    assert [e.value for e in by_type(entities, "GOVERNMENT_ID")] == ["2345 6789 0123"]
    assert [e.value for e in by_type(entities, "PHONE_NUMBER")] == ["+91 98765 43210"]


def test_custom_recognizer_wins_overlaps_so_no_fragment_leaks(analyzer):
    # spaCy tags "+91" as a place and "12345" as a date; the full number must still win.
    entities = analyzer.analyze("Hello, mera number +91 98450 12345 hai.")
    assert [(e.entity_type, e.value) for e in entities] == [("PHONE_NUMBER", "+91 98450 12345")]


def test_bare_grouped_aadhaar_is_low_confidence(analyzer):
    ids = by_type(analyzer.analyze("The reference is 2345 6789 0123 for the file."), "GOVERNMENT_ID")
    assert ids and ids[0].low_confidence


def test_date_of_birth_and_health_terms(analyzer):
    entities = analyzer.analyze("My date of birth is 14/03/1986 and I have diabetes, my sugar ki bimari is worse.")
    assert [e.value for e in by_type(entities, "DATE_OF_BIRTH")] == ["14/03/1986"]
    assert {e.value.lower() for e in by_type(entities, "HEALTH_TERM")} == {"diabetes", "sugar ki bimari"}


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
    assert analyzer.scan("My name is [PERSON_1] and my patient ID is [PATIENT_ID_1].") == []
    assert analyzer.scan("PERSON_1 called about PATIENT_ID_1.") == []


def hinglish_sample() -> str:
    from app.samples import SAMPLES

    return next(s for s in SAMPLES if s.id == "hinglish-triage").transcript


def test_hinglish_function_words_are_not_names(analyzer):
    for normalize in (False, True):
        entities = analyzer.analyze(hinglish_sample(), normalize=normalize)
        assert [e.value for e in by_type(entities, "PERSON")] == ["Priya Sharma"]


def test_hinglish_sample_keeps_every_other_identifier(analyzer):
    entities = analyzer.analyze(hinglish_sample(), normalize=True)
    found = {(e.entity_type, e.value) for e in entities}
    assert {
        ("DATE_OF_BIRTH", "14/03/1986"),
        ("PATIENT_ID", "P9048213"),
        ("PHONE_NUMBER", "+91 98450 12345"),
        ("HEALTH_TERM", "diabetes"),
    } <= found


def test_stopwords_are_trimmed_from_name_edges(analyzer):
    people = by_type(analyzer.analyze("main bol raha hoon, mera naam Arjun Mehta hai"), "PERSON")
    assert [p.value for p in people] == ["Arjun Mehta"]


def test_partial_denylist_match_never_shortens_a_name(analyzer):
    # The deny-list knows "Priya"; the whole name must still be protected (fail closed).
    people = by_type(analyzer.analyze("Hello, main Priya Kapadia bol rahi hoon."), "PERSON")
    assert [p.value for p in people] == ["Priya Kapadia"]


def test_name_denylist_never_splits_an_email_address(analyzer):
    # A custom PERSON match on "kavya" would win the overlap and leave the rest of the email in
    # clear text. Found by the leak-canary tests.
    entities = analyzer.analyze("Send the report to kavya.iyer42@example.org please.")
    assert [(e.entity_type, e.value) for e in entities] == [("EMAIL_ADDRESS", "kavya.iyer42@example.org")]


def test_introduction_needs_a_capitalised_name(analyzer):
    assert not by_type(analyzer.analyze("Main bol rahi hoon, this is about my report."), "PERSON")
    assert not by_type(analyzer.analyze("This is Thursday, not Friday."), "PERSON")


def test_custom_person_spans_are_never_stopword_filtered(analyzer):
    # "Main" is a stop word, but the introduction recognizer's span is the name itself.
    people = by_type(analyzer.analyze("Main Kavya Iyer, mujhe report chahiye."), "PERSON")
    assert [p.value for p in people] == ["Kavya Iyer"]


import pytest  # noqa: E402


@pytest.mark.parametrize(
    "text, value",
    [
        ("He was born on 2 March 1979 in Pune.", "2 March 1979"),
        ("Uska janam 16 January 1950 ko hua tha.", "16 January 1950"),
        ("Her birthday is 05/06/2012, she is turning eleven.", "05/06/2012"),
        ("मेरी जन्म तिथि ११-०२-१९९९ है।", "११-०२-१९९९"),
        ("ನನ್ನ ಜನ್ಮ ದಿನಾಂಕ 23-10-1940, ವೈದ್ಯರನ್ನು ಭೇಟಿ ಮಾಡಬೇಕು.", "23-10-1940"),
        ("என் பிறந்த தேதி 09-11-1963, மருத்துவரைப் பார்க்க வேண்டும்.", "09-11-1963"),
        ("My number is nine four zero eight, date of birth 14 July 1999.", "14 July 1999"),
    ],
)
def test_date_of_birth_cues(analyzer, text, value):
    assert [e.value for e in by_type(analyzer.analyze(text, normalize=True), "DATE_OF_BIRTH")] == [value]


@pytest.mark.parametrize(
    "text",
    ["I was born in Delhi and moved in 1999.", "Please book the appointment on 14/03/2026.", "Janam se yahin rehta hoon."],
)
def test_date_of_birth_needs_a_cue_and_a_date(analyzer, text):
    assert not by_type(analyzer.analyze(text, normalize=True), "DATE_OF_BIRTH")


@pytest.mark.parametrize(
    "text, value",
    [
        ("नमस्ते, मेरा नाम अर्जुन मेहता है। मुझे समय चाहिए।", "अर्जुन मेहता"),
        ("ನಮಸ್ಕಾರ, ನನ್ನ ಹೆಸರು ಅರ್ಜುನ್ ಗೌಡ. ನನಗೆ ಅಪಾಯಿಂಟ್ಮೆಂಟ್ ಬೇಕು.", "ಅರ್ಜುನ್ ಗೌಡ"),
        ("வணக்கம், என் பெயர் அர்ஜுன் கிருஷ்ணன். சந்திப்பு வேண்டும்.", "அர்ஜுன் கிருஷ்ணன்"),
    ],
)
def test_native_script_names_after_an_introduction(analyzer, text, value):
    assert [e.value for e in by_type(analyzer.analyze(text), "PERSON")] == [value]


def test_native_name_cue_without_a_name_is_not_a_person(analyzer):
    assert not by_type(analyzer.analyze("आपका नाम क्या है?"), "PERSON")


def test_unloaded_analyzer_raises(analyzer):
    import pytest

    from app.detection.analyzer import DetectionError

    fresh = SensitiveDataAnalyzer(analyzer.config, "missing-model", 0.35, 0.6)
    with pytest.raises(DetectionError):
        fresh.analyze("text")
