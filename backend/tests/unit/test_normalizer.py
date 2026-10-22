"""Spoken-number normalizer (FR-15). All values are synthetic."""

from __future__ import annotations

import re

from app.detection.normalizer import map_span, normalize_numbers
from app.security.redactor import Redactor

SPOKEN_ID = "My patient ID is P four eight two nine one three, please check."
DIGIT_WORDS = re.compile(r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine)\b", re.IGNORECASE)


def by_type(entities, entity_type):
    return [e for e in entities if e.entity_type == entity_type]


def test_spoken_patient_id_is_detected_and_fully_redacted(analyzer):
    entities = analyzer.analyze(SPOKEN_ID, normalize=True)
    ids = by_type(entities, "PATIENT_ID")
    assert [e.value for e in ids] == ["P four eight two nine one three"]
    assert ids[0].normalized
    assert SPOKEN_ID[ids[0].start : ids[0].end] == ids[0].value

    result = Redactor().redact(SPOKEN_ID, ids)
    assert "[PATIENT_ID_1]" in result.text
    assert not DIGIT_WORDS.search(result.text)


def test_spoken_id_is_missed_without_normalization(analyzer):
    assert not by_type(analyzer.analyze(SPOKEN_ID), "PATIENT_ID")


def test_double_and_triple():
    assert normalize_numbers("call nine double five triple two one").text == "call 9552221"
    assert normalize_numbers("double five").text == "55"


def test_oh_only_between_digits():
    assert normalize_numbers("nine oh two").text == "902"
    assert normalize_numbers("Oh, nine two").text == "Oh, 92"


def test_ek_and_do_need_a_run_of_three():
    assert normalize_numbers("please do it").text == "please do it"
    assert normalize_numbers("do teen").text == "do teen"  # two words: "do" stays a word
    assert normalize_numbers("nau aath do ek").text == "9821"


def test_hinglish_spoken_mobile_number(analyzer):
    text = "Mera mobile number nau aath saat chhe paanch chaar teen do ek shunya hai."
    assert "9876543210" in normalize_numbers(text).text
    phones = by_type(analyzer.analyze(text, normalize=True), "PHONE_NUMBER")
    assert phones and phones[0].value.startswith("nau aath")


def test_native_digits_normalize():
    assert normalize_numbers("९८७६५ ४३२१०").text == "98765 43210"  # Devanagari
    assert normalize_numbers("೯೮೭೬೫").text == "98765"  # Kannada
    assert normalize_numbers("௯௮௭௬௫").text == "98765"  # Tamil


def test_native_digit_phone_is_detected_in_original_text(analyzer):
    text = "Mera mobile number ९८७६५ ४३२१० hai."
    phones = by_type(analyzer.analyze(text, normalize=True), "PHONE_NUMBER")
    assert [p.value for p in phones] == ["९८७६५ ४३२१०"]


def test_split_id_across_a_sentence_boundary(analyzer):
    text = "My patient ID is P48. Sorry, then 2913."
    assert "P482913" in normalize_numbers(text).text
    ids = by_type(analyzer.analyze(text, normalize=True), "PATIENT_ID")
    assert len(ids) == 1
    # The merged span covers both parts and the filler between them (fail closed).
    assert ids[0].value == "P48. Sorry, then 2913"


def test_split_join_stops_at_another_field():
    # Found by the canary runs: spoken digits followed by a date were glued to the date.
    text = "My number is nine four zero eight, date of birth 14 July 1999."
    assert normalize_numbers(text).text == "My number is 9408, date of birth 14 July 1999."


def test_split_join_needs_a_pause_and_an_id_cue():
    assert "141999" not in normalize_numbers("Patient ID 14 July 1999").text  # no pause between parts
    assert normalize_numbers("date of birth 14. Sorry, 1999").text == "date of birth 14. Sorry, 1999"


def test_letter_joins_only_after_an_id_cue():
    assert normalize_numbers("patient ID P four eight two").text == "patient ID P482"
    assert normalize_numbers("Plan A four five").text == "Plan A 45"


def test_formatted_numbers_are_not_rejoined():
    # Grouping spaces in a typed number are formatting, not a split ID.
    n = normalize_numbers("mobile +91 98765 43210")
    assert not n.changed


def test_map_span_is_identity_for_unchanged_text():
    text = "My patient ID is 48291."
    n = normalize_numbers(text)
    assert not n.changed and n.text == text
    assert map_span(n, 17, 22) == (17, 22)


def test_map_span_covers_merged_source_characters():
    text = "ID nine eight"
    n = normalize_numbers(text)
    assert n.text == "ID 98"
    assert map_span(n, 3, 5) == (3, len(text))


def test_normalization_off_keeps_milestone_a_behaviour(harness_factory):
    h = harness_factory(normalize_numbers=False)
    body = h.process(SPOKEN_ID).json()
    assert not any(e["entity_type"] == "PATIENT_ID" for e in body["entities"])


def test_normalization_on_protects_spoken_id_end_to_end(harness_factory):
    h = harness_factory()
    body = h.process(SPOKEN_ID).json()
    assert any(e["entity_type"] == "PATIENT_ID" for e in body["entities"])
    assert not DIGIT_WORDS.search(body["redacted_transcript"])
    sent = [r for r in h.receiver_transport.handoff_requests()]
    assert all(b"four eight" not in r.content for r in sent)


def test_receipt_records_normalize_on(harness_factory):
    import json

    h = harness_factory()
    h.process(SPOKEN_ID)
    body = json.loads(h.container.receipts.all()[-1].body)
    assert body["normalize_on"] is True
