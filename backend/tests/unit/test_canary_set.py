"""The committed canary set: format, coverage and deterministic generation."""

from __future__ import annotations

import importlib.util
import sys
from collections import Counter

import pytest

from app.canaries.models import CANARY_FILE, HOLDOUT_FILE, NUMERIC_TYPES, load_canary_set
from app.config import BACKEND_ROOT


def load_generator():
    spec = importlib.util.spec_from_file_location("generate_canaries", BACKEND_ROOT / "scripts" / "generate_canaries.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses in the script look their module up here
    spec.loader.exec_module(module)
    return module


def test_set_loads_and_every_span_is_exact():
    canary_set = load_canary_set()
    assert canary_set.version == "canaries-v1"
    for call in canary_set.calls:
        assert 1 <= len(call.planted) <= 4
        for value in call.planted:
            for start, end in value.spans:
                assert 0 <= start < end <= len(call.text)
                assert call.text[start:end].strip(), call.call_id


def test_coverage_minimums():
    calls = load_canary_set().calls
    assert 180 <= len(calls) <= 220
    assert sum(c.difficulty != "plain" for c in calls) / len(calls) >= 0.30
    languages = Counter(c.language for c in calls)
    for language in ("hinglish", "hi", "kn", "ta"):
        assert languages[language] >= 25, language
    for language in ("hi", "kn", "ta"):
        scripts = {c.script for c in calls if c.language == language}
        assert scripts == {"latin", "native"}, language
    types = {p.type for c in calls for p in c.planted}
    assert types == {"PERSON", "PATIENT_ID", "PHONE_NUMBER", "GOVERNMENT_ID", "DATE_OF_BIRTH", "EMAIL_ADDRESS"}


def test_split_ids_have_two_spans_and_values_are_clearly_fake():
    calls = load_canary_set().calls
    for call in calls:
        for value in call.planted:
            if call.difficulty in ("split_id", "mixed") and value.type == "PATIENT_ID":
                assert len(value.spans) == 2, call.call_id
            if value.type == "PATIENT_ID":
                assert value.canonical.startswith("P9")
            if value.type == "GOVERNMENT_ID":
                assert value.canonical.startswith("9999")
            if value.type in NUMERIC_TYPES and value.type != "PATIENT_ID":
                assert value.canonical.isdigit()


@pytest.mark.parametrize("name, path", [("main", CANARY_FILE), ("holdout", HOLDOUT_FILE)])
def test_generation_is_byte_identical_and_matches_the_committed_file(name, path):
    generator = load_generator()
    first = generator.render(generator.build_canary_set(name))
    second = generator.render(generator.build_canary_set(name))
    assert first == second
    assert path.read_bytes() == first.encode("utf-8")


def test_holdout_set_is_separate_and_covers_every_language():
    main, holdout = load_canary_set(), load_canary_set(HOLDOUT_FILE)
    assert holdout.version == "canaries-holdout-v1" and holdout.generated_with_seed == 20261117
    assert sum(c.difficulty != "plain" for c in holdout.calls) / len(holdout.calls) >= 0.30
    languages = Counter(c.language for c in holdout.calls)
    assert all(languages[lang] >= 15 for lang in ("hinglish", "hi", "kn", "ta"))
    # New templates: no call text is shared with the main set.
    assert not {c.text for c in holdout.calls} & {c.text for c in main.calls}
