"""Policy administration: CRUD with validation, seeding and profile discovery."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from app.db.repositories import PolicyRepository
from app.policy.engine import policy_set_version
from app.policy.loader import load_policy_file
from app.policy.models import Policy, PolicyDefinition, PolicyProfile
from app.policy.validation import PolicyCheckResult, check_policy


class PolicyConflictError(Exception):
    pass


class PolicyInvalidError(Exception):
    def __init__(self, result: PolicyCheckResult) -> None:
        super().__init__("Policy is invalid.")
        self.result = result


class PolicyService:
    def __init__(self, repository: PolicyRepository, seed_file: Path, known_categories: set[str]) -> None:
        self._repo = repository
        self._seed_file = seed_file
        self.known_categories = known_categories
        self._profiles: list[PolicyProfile] = []

    def initialize(self) -> None:
        """Load profile metadata and seed policies when the table is empty."""
        seed = load_policy_file(self._seed_file)
        self._profiles = list(seed.profiles)
        if self._repo.count() == 0:
            self._seed(seed)

    def _seed(self, seed) -> list[Policy]:
        items = []
        for p in seed.policies:
            definition = PolicyDefinition.model_validate(p.model_dump(exclude={"policy_id"}))
            result = check_policy(definition, self.known_categories, [])
            if not result.valid:
                raise PolicyInvalidError(result)
            items.append((p.policy_id, definition))
        return self._repo.replace_all(items)

    def reset_to_defaults(self) -> list[Policy]:
        seed = load_policy_file(self._seed_file)
        self._profiles = list(seed.profiles)
        return self._seed(seed)

    def list(self) -> list[Policy]:
        return self._repo.list()

    def get(self, policy_id: str) -> Policy | None:
        return self._repo.get(policy_id)

    def version(self) -> str:
        return policy_set_version(self._repo.list())

    def validate(self, definition: PolicyDefinition, policy_id: str | None = None) -> PolicyCheckResult:
        return check_policy(definition, self.known_categories, self._repo.list(), policy_id)

    def create(self, definition: PolicyDefinition, policy_id: str | None) -> Policy:
        result = self.validate(definition)
        if not result.valid:
            raise PolicyInvalidError(result)
        policy_id = policy_id or self._generate_id(definition.name)
        try:
            return self._repo.create(policy_id, definition)
        except KeyError as exc:
            raise PolicyConflictError(policy_id) from exc

    def update(self, policy_id: str, definition: PolicyDefinition) -> Policy | None:
        result = self.validate(definition, policy_id)
        if not result.valid:
            raise PolicyInvalidError(result)
        return self._repo.update(policy_id, definition)

    def delete(self, policy_id: str) -> bool:
        return self._repo.delete(policy_id)

    def _generate_id(self, name: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48] or "policy"
        if len(slug) < 3:
            slug = f"policy-{slug}"
        candidate = slug
        while self._repo.get(candidate) is not None:
            candidate = f"{slug}-{uuid.uuid4().hex[:4]}"
        return candidate

    def profiles(self) -> list[tuple[PolicyProfile, int]]:
        policies = self._repo.list()
        known = {p.id: p for p in self._profiles}
        for policy in policies:
            for profile_id in policy.conditions.profiles:
                known.setdefault(profile_id, PolicyProfile(id=profile_id, name=profile_id, description="Defined by policy conditions."))
        def applicable(profile_id: str) -> int:
            return sum(
                1 for p in policies if p.enabled and (not p.conditions.profiles or profile_id in p.conditions.profiles)
            )

        return [(profile, applicable(profile.id)) for profile in known.values()]
