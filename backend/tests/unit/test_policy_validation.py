from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.policy.loader import PolicyFileError, load_policy_file
from app.policy.models import PolicyDefinition
from app.policy.validation import check_policy

KNOWN = {"PERSON", "PATIENT_ID", "PHONE_NUMBER"}


def definition(**overrides):
    data = {
        "name": "Test policy",
        "entity_categories": ["PERSON"],
        "action": "REDACT",
        "destination": "CLOUD",
    }
    data.update(overrides)
    return PolicyDefinition.model_validate(data)


@pytest.mark.parametrize(
    "overrides",
    [
        {"action": "BLOCK", "destination": "CLOUD"},
        {"action": "LOCAL_ONLY", "destination": "CLOUD"},
        {"action": "ALLOW", "destination": "NONE"},
        {"entity_categories": []},
        {"entity_categories": ["ANY", "PERSON"]},
        {"priority": 0},
        {"name": "x"},
        {"conditions": {"profiles": ["Not Valid!"]}},
        {"conditions": {"min_confidence": 1.5}},
        {"unexpected": True},
    ],
)
def test_invalid_policy_schema_is_rejected(overrides):
    with pytest.raises(ValidationError):
        definition(**overrides)


def test_unknown_category_is_rejected():
    result = check_policy(definition(entity_categories=["SHOE_SIZE"]), KNOWN, [])
    assert not result.valid


def test_any_with_redact_is_rejected():
    result = check_policy(definition(entity_categories=["ANY"]), KNOWN, [])
    assert not result.valid


def test_allow_to_cloud_for_specific_category_warns():
    result = check_policy(definition(action="ALLOW"), KNOWN, [])
    assert result.valid and result.warnings


def test_invalid_yaml_file_is_rejected(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("policies: [ {policy_id: x, name: y, action: BLOCK, destination: CLOUD} ]", encoding="utf-8")
    with pytest.raises(PolicyFileError):
        load_policy_file(bad)
    broken = tmp_path / "broken.yaml"
    broken.write_text("policies: [unclosed", encoding="utf-8")
    with pytest.raises(PolicyFileError):
        load_policy_file(broken)
