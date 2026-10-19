from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Response

from app.api.deps import get_container, require_admin
from app.api.errors import ApiError
from app.container import Container
from app.policy.models import POLICY_ID_PATTERN, Policy, PolicyDefinition
from app.schemas.policy import (
    EntityCategoryListResponse,
    PolicyCreate,
    PolicyListResponse,
    PolicyUpdate,
    PolicyValidationResponse,
    ProfileInfo,
    ProfileListResponse,
)
from app.schemas.responses import ErrorResponse
from app.services.policy_service import PolicyConflictError, PolicyInvalidError

router = APIRouter(prefix="/policies", tags=["policies"])

PolicyId = Path(pattern=POLICY_ID_PATTERN)
ERRORS = {401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}}


def _invalid(exc: PolicyInvalidError) -> ApiError:
    return ApiError(
        422,
        "POLICY_INVALID",
        "The policy configuration is invalid and was not saved.",
        [{"msg": e, "type": "policy_error"} for e in exc.result.errors],
    )


def _definition(body: PolicyDefinition) -> PolicyDefinition:
    return PolicyDefinition.model_validate(body.model_dump(exclude={"policy_id"}))


@router.get("", response_model=PolicyListResponse)
def list_policies(container: Container = Depends(get_container)) -> PolicyListResponse:
    items = container.policy_service.list()
    return PolicyListResponse(items=items, policy_version=container.policy_service.version(), total=len(items))


@router.get("/profiles", response_model=ProfileListResponse)
def list_profiles(container: Container = Depends(get_container)) -> ProfileListResponse:
    return ProfileListResponse(
        items=[ProfileInfo(**profile.model_dump(), applicable_policies=count) for profile, count in container.policy_service.profiles()]
    )


@router.get("/entity-categories", response_model=EntityCategoryListResponse)
def entity_categories(container: Container = Depends(get_container)) -> EntityCategoryListResponse:
    return EntityCategoryListResponse(items=["ANY", *sorted(container.policy_service.known_categories)])


@router.post("/validate", response_model=PolicyValidationResponse)
def validate_policy(body: PolicyCreate, container: Container = Depends(get_container)) -> PolicyValidationResponse:
    """Validate a policy without saving it. Schema errors are returned as HTTP 422."""
    result = container.policy_service.validate(_definition(body), body.policy_id)
    return PolicyValidationResponse(valid=result.valid, errors=result.errors, warnings=result.warnings)


@router.post("/reset", response_model=PolicyListResponse, dependencies=[Depends(require_admin)], responses=ERRORS)
def reset_policies(container: Container = Depends(get_container)) -> PolicyListResponse:
    items = container.policy_service.reset_to_defaults()
    return PolicyListResponse(items=items, policy_version=container.policy_service.version(), total=len(items))


@router.post("", response_model=Policy, status_code=201, dependencies=[Depends(require_admin)], responses=ERRORS)
def create_policy(body: PolicyCreate, container: Container = Depends(get_container)) -> Policy:
    try:
        return container.policy_service.create(_definition(body), body.policy_id)
    except PolicyInvalidError as exc:
        raise _invalid(exc) from exc
    except PolicyConflictError as exc:
        raise ApiError(409, "POLICY_EXISTS", f"A policy with id '{exc}' already exists.") from exc


@router.get("/{policy_id}", response_model=Policy, responses=ERRORS)
def get_policy(policy_id: str = PolicyId, container: Container = Depends(get_container)) -> Policy:
    policy = container.policy_service.get(policy_id)
    if policy is None:
        raise ApiError(404, "POLICY_NOT_FOUND", "Policy not found.")
    return policy


@router.put("/{policy_id}", response_model=Policy, dependencies=[Depends(require_admin)], responses=ERRORS)
def update_policy(body: PolicyUpdate, policy_id: str = PolicyId, container: Container = Depends(get_container)) -> Policy:
    try:
        policy = container.policy_service.update(policy_id, _definition(body))
    except PolicyInvalidError as exc:
        raise _invalid(exc) from exc
    if policy is None:
        raise ApiError(404, "POLICY_NOT_FOUND", "Policy not found.")
    return policy


@router.delete("/{policy_id}", status_code=204, dependencies=[Depends(require_admin)], responses=ERRORS)
def delete_policy(policy_id: str = PolicyId, container: Container = Depends(get_container)) -> Response:
    if not container.policy_service.delete(policy_id):
        raise ApiError(404, "POLICY_NOT_FOUND", "Policy not found.")
    return Response(status_code=204)
