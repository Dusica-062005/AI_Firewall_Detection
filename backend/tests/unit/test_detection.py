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


def test_patient_id_with_a_space_after_the_prefix(analyzer):
    # "P 9482913": a spoken ID, or a live-transcription chunk boundary inside the ID.
    ids = by_type(analyzer.analyze("My patient ID is P 9482913, thanks."), "PATIENT_ID")
    assert [i.value for i in ids] == ["P 9482913"]


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


def test_north_american_phones_are_never_left_as_a_date(analyzer):
    # Presidio rejects these (555 demo numbers, an extension) and spaCy tags the digits as a
    # DATE_TIME, which policy allows to the cloud. The whole number must be a PHONE_NUMBER.
    cases = {
        "Agent: What's the best number? Caller: 416 555 0199.": "416 555 0199",
        "Reach me at 613-555-0142 extension 4471.": "613-555-0142 extension 4471",
        "Phone (613) 555-0142 after five.": "(613) 555-0142",
        "My number is +1.613.555.0142.": "+1.613.555.0142",
        "Hi, this is John Smith, call me on 555-0142.": "555-0142",
    }
    for text, phone in cases.items():
        entities = analyzer.analyze(text)
        assert [e.value for e in by_type(entities, "PHONE_NUMBER")] == [phone], text
        assert not any(phone in e.value or e.value in phone for e in by_type(entities, "DATE_TIME")), text


def test_phone_patterns_do_not_split_other_numbers(analyzer):
    for text in (
        "My card is 4111111111111111.",
        "My social security number is 512-44-7321.",
        "Mera Aadhaar number hai 2345 6789 0123.",
        "My account number is 00123456789.",
        "Order 555-0142 shipped on Monday.",  # seven digits without a phone cue
    ):
        assert not by_type(analyzer.analyze(text), "PHONE_NUMBER"), text


def test_spaced_card_number_is_a_whole_card_not_an_aadhaar(analyzer):
    # The grouped-Aadhaar pattern used to match the first twelve digits, label the card a
    # government ID and leave the last four digits in clear text.
    for text, card in (
        ("My card is 4111 1111 1111 1111.", "4111 1111 1111 1111"),
        ("Visa 4111 1111 1111 1111, CVV 123.", "4111 1111 1111 1111"),
        ("Card 5500-0000-0000-0004 expires 08/27.", "5500-0000-0000-0004"),
    ):
        entities = analyzer.analyze(text)
        assert [e.value for e in by_type(entities, "CREDIT_CARD")] == [card], text
        assert not by_type(entities, "GOVERNMENT_ID"), text


def test_spoken_email_is_one_whole_address(analyzer):
    # Speech-to-text writes addresses out in words. The whole address must be one EMAIL_ADDRESS,
    # never a name with the rest of the address left in clear text.
    for text, email in (
        ("My email is jane dot doe at example dot com.", "jane dot doe at example dot com"),
        ("Mera email priya dot sharma at the rate gmail dot com hai.", "priya dot sharma at the rate gmail dot com"),
        ("Send it to j doe at company dot co dot uk please.", "j doe at company dot co dot uk"),
    ):
        entities = analyzer.analyze(text)
        assert [e.value for e in by_type(entities, "EMAIL_ADDRESS")] == [email], text
        assert not any(e.start < text.index(email) + len(email) and text.index(email) < e.end
                       for e in entities if e.entity_type != "EMAIL_ADDRESS"), text


def test_ordinary_at_phrases_are_not_emails(analyzer):
    for text in ("Look at this dot com bubble.", "I'll call you back at home.", "She works at Mitel in Ottawa."):
        assert not by_type(analyzer.analyze(text), "EMAIL_ADDRESS"), text


def test_passport_and_drivers_licence_are_government_ids(analyzer):
    for text, value in (
        ("My passport number is AB1234567.", "AB1234567"),
        ("Passport no. C03005988 expires soon.", "C03005988"),
        ("Driver's licence S1234-56789-01234.", "S1234-56789-01234"),
        ("My driver’s license is D1234567, thanks.", "D1234567"),
        ("Drivers license 123 456 789 please.", "123 456 789"),
    ):
        ids = by_type(analyzer.analyze(text), "GOVERNMENT_ID")
        assert [e.value for e in ids] == [value], text


def test_passport_and_licence_need_a_number_after_the_cue(analyzer):
    for text in (
        "I need help with my passport renewal.",
        "I lost my driver's licence yesterday.",
        "The licence number on the car is ABC123.",
    ):
        assert not by_type(analyzer.analyze(text), "GOVERNMENT_ID"), text


def test_addresses_leave_no_street_number_or_postal_code_in_clear(analyzer):
    # Only "Kanata" used to be redacted; the house number, street and postal code went to the cloud.
    for text, must_cover in (
        ("I live at 350 Legget Drive, Kanata, Ontario K2K 2W7.", ["350 Legget Drive", "K2K 2W7"]),
        ("Ship it to 42 Wallaby Way, Apt 4B.", ["42 Wallaby Way, Apt 4B"]),
        ("I'm at 1600 Pennsylvania Avenue NW, Washington, DC 20500.", ["1600 Pennsylvania Avenue NW", "20500"]),
    ):
        locations = by_type(analyzer.analyze(text), "LOCATION")
        for part in must_cover:
            start = text.index(part)
            assert any(e.start <= start and start + len(part) <= e.end for e in locations), (text, part)


def test_numbers_that_are_not_addresses_stay_unflagged(analyzer):
    for text in ("I waited 20 minutes on hold.", "Order 20500 was shipped.", "I have 2 appointments with Dr Patel."):
        assert not by_type(analyzer.analyze(text), "LOCATION"), text


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
