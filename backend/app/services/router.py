"""Sensitivity-based AI router (FR-13).

Decides whether the tokenized text may travel to the cloud stand-in or must stay local.
The first matching rule wins and every rule fails closed: anything other than an explicit
"cloud allowed" keeps the request local (or stops it entirely).

    1. Enforcement failed or policy BLOCK      -> NONE
    2. Inspect mode                            -> NONE
    3. Policy does not authorize the cloud     -> LOCAL
    4. Local-only processing mode              -> LOCAL
    5. Kill switch on                          -> LOCAL
    6. Dial at maximum privacy                 -> LOCAL
    7. Any low-confidence entity               -> LOCAL (a possible miss must not travel)
    8. Otherwise                               -> CLOUD

After the local model has run, ``hold_if_local_model_failed`` applies NFR-5: if the local
model was needed and is unavailable, cloud egress fails closed too, while detection and
redaction results stay available (degraded mode).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.detection.entities import DetectedEntity
from app.policy.dial import dial_allows_cloud
from app.policy.engine import PolicyDecision
from app.policy.models import Action
from app.schemas.requests import ProcessingMode


@dataclass(frozen=True)
class RouteDecision:
    route: str  # LOCAL | CLOUD | NONE
    reason: str
    message: str


def decide_route(
    *,
    failed: bool,
    decision: PolicyDecision | None,
    mode: ProcessingMode,
    kill_switch: bool,
    dial: str,
    entities: list[DetectedEntity],
    low_confidence_stays_local: bool,
) -> RouteDecision:
    if failed or decision is None:
        return RouteDecision("NONE", "enforcement_failed", "Enforcement did not complete; nothing is processed or sent.")
    if decision.action is Action.BLOCK:
        return RouteDecision("NONE", "policy_blocked", "Policy blocks AI processing for this request.")
    if mode is ProcessingMode.INSPECT:
        return RouteDecision("NONE", "mode_inspect", "Inspection mode: no model call and no outbound request.")
    if not decision.cloud_authorized:
        return RouteDecision("LOCAL", "policy_local_only", "Policy keeps this request on the local model.")
    if mode is ProcessingMode.LOCAL:
        return RouteDecision("LOCAL", "mode_local", "The selected mode processes locally only.")
    if kill_switch:
        return RouteDecision("LOCAL", "kill_switch", "Kill switch is on: the cloud path is blocked; local processing continues.")
    if not dial_allows_cloud(dial):
        return RouteDecision("LOCAL", "dial_max_privacy", "Privacy-utility dial is at maximum privacy: local only.")
    if low_confidence_stays_local and any(e.low_confidence for e in entities):
        return RouteDecision(
            "LOCAL", "low_confidence_entity",
            "A low-confidence detection could be a missed identifier, so the request stays local (fail closed).",
        )
    return RouteDecision("CLOUD", "policy_cloud", "Policy, controls and confidence allow the tokenized text to reach the cloud stand-in.")


def hold_if_local_model_failed(route: RouteDecision, local_model_failed: bool) -> RouteDecision:
    """NFR-5: an unavailable local model also stops cloud egress (fail closed)."""
    if route.route == "CLOUD" and local_model_failed:
        return RouteDecision(
            "LOCAL", "local_model_unavailable",
            "The local model is unavailable, so nothing is sent to the cloud (fail closed). "
            "Detection and redaction results remain available.",
        )
    return route
