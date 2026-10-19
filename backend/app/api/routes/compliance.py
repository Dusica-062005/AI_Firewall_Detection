from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import PlainTextResponse

from app.api.deps import get_container, require_admin
from app.api.errors import ApiError
from app.compliance.controls import FRAMEWORKS
from app.compliance.data_requests import DataRequestCompletedError, InvalidReceivedDateError, UnknownSystemError
from app.compliance.incidents import IncidentClosedError, IncidentInputError
from app.compliance.report import render_markdown
from app.compliance.systems import UnknownCategoryError
from app.container import Container
from app.schemas.compliance import (
    AUDIT_EVENT_ID_PATTERN,
    DATA_REQUEST_ID_PATTERN,
    INCIDENT_ID_PATTERN,
    SYSTEM_ID_PATTERN,
    AiSystem,
    AiSystemCreate,
    AiSystemListResponse,
    AiSystemReview,
    ComplianceOverview,
    DataRequest,
    DataRequestCreate,
    DataRequestListResponse,
    DataRequestStatus,
    DataRequestSystemUpdate,
    EvidencePack,
    Incident,
    IncidentAdvance,
    IncidentCreate,
    IncidentListResponse,
    IncidentStatus,
    IncidentUpdate,
    Severity,
)
from app.schemas.responses import ErrorResponse

router = APIRouter(prefix="/compliance", tags=["compliance"])

ERRORS = {401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}}
admin = [Depends(require_admin)]

SystemId = Path(pattern=SYSTEM_ID_PATTERN)
IncidentId = Path(pattern=INCIDENT_ID_PATTERN)
DataRequestId = Path(pattern=DATA_REQUEST_ID_PATTERN)


def _not_found(code: str, what: str) -> ApiError:
    return ApiError(404, code, f"{what} not found.")


# ---- Overview and evidence ----------------------------------------------------------------


@router.get("/overview", response_model=ComplianceOverview)
def overview(container: Container = Depends(get_container)) -> ComplianceOverview:
    """Scores per framework, evaluated live against the current configuration and records."""
    return container.compliance.overview()


def _check_framework(framework: str) -> None:
    if framework not in FRAMEWORKS:
        raise ApiError(404, "FRAMEWORK_NOT_FOUND", "Unknown compliance framework.")


@router.get("/evidence/{framework}", response_model=EvidencePack, responses=ERRORS)
def evidence(framework: str, container: Container = Depends(get_container)) -> EvidencePack:
    _check_framework(framework)
    return container.compliance.evidence(framework)


@router.get("/evidence/{framework}/markdown", response_class=PlainTextResponse, responses=ERRORS)
def evidence_markdown(framework: str, container: Container = Depends(get_container)) -> PlainTextResponse:
    _check_framework(framework)
    return PlainTextResponse(render_markdown(container.compliance.evidence(framework)), media_type="text/markdown")


# ---- AI systems ---------------------------------------------------------------------------


@router.get("/systems", response_model=AiSystemListResponse)
def list_systems(container: Container = Depends(get_container)) -> AiSystemListResponse:
    items = container.ai_systems.list()
    return AiSystemListResponse(items=items, total=len(items))


@router.post("/systems", response_model=AiSystem, status_code=201, dependencies=admin, responses=ERRORS)
def create_system(body: AiSystemCreate, container: Container = Depends(get_container)) -> AiSystem:
    try:
        return container.ai_systems.create(body)
    except UnknownCategoryError as exc:
        raise ApiError(422, "UNKNOWN_CATEGORY", f"Unknown data categories: {exc}.") from exc


@router.post("/systems/{system_id}/review", response_model=AiSystem, dependencies=admin, responses=ERRORS)
def review_system(
    body: AiSystemReview | None = None, system_id: str = SystemId, container: Container = Depends(get_container)
) -> AiSystem:
    """Record that the system was reviewed today, optionally changing its approval status."""
    system = container.ai_systems.mark_reviewed(system_id, body.status if body else None)
    if system is None:
        raise _not_found("SYSTEM_NOT_FOUND", "AI system")
    return system


# ---- Incidents ----------------------------------------------------------------------------


@router.get("/incidents", response_model=IncidentListResponse)
def list_incidents(
    container: Container = Depends(get_container), status: IncidentStatus | None = None, severity: Severity | None = None
) -> IncidentListResponse:
    items = container.incidents.list(status, severity)
    return IncidentListResponse(items=items, total=len(items))


@router.post("/incidents", response_model=Incident, status_code=201, dependencies=admin, responses=ERRORS)
def create_incident(body: IncidentCreate, container: Container = Depends(get_container)) -> Incident:
    if body.ai_system_id and container.ai_systems.get(body.ai_system_id) is None:
        raise ApiError(422, "UNKNOWN_SYSTEM", "The selected AI system is not in the inventory.")
    if body.related_event_id and container.audit_service.get(body.related_event_id) is None:
        raise ApiError(422, "UNKNOWN_AUDIT_EVENT", "The linked audit event does not exist or has been purged.")
    return container.incidents.create(body)


@router.get("/incidents/{incident_id}", response_model=Incident, responses=ERRORS)
def get_incident(incident_id: str = IncidentId, container: Container = Depends(get_container)) -> Incident:
    incident = container.incidents.get(incident_id)
    if incident is None:
        raise _not_found("INCIDENT_NOT_FOUND", "Incident")
    return incident


@router.post("/incidents/{incident_id}/advance", response_model=Incident, dependencies=admin, responses=ERRORS)
def advance_incident(
    body: IncidentAdvance, incident_id: str = IncidentId, container: Container = Depends(get_container)
) -> Incident:
    """Move to the next stage: Reported, Contained, Root cause identified, Closed."""
    try:
        incident = container.incidents.advance(incident_id, body)
    except IncidentClosedError as exc:
        raise ApiError(409, "INCIDENT_CLOSED", "The incident is closed and cannot change.") from exc
    except IncidentInputError as exc:
        raise ApiError(422, f"INCIDENT_{exc.code}", exc.message) from exc
    if incident is None:
        raise _not_found("INCIDENT_NOT_FOUND", "Incident")
    return incident


@router.put("/incidents/{incident_id}", response_model=Incident, dependencies=admin, responses=ERRORS)
def update_incident(
    body: IncidentUpdate, incident_id: str = IncidentId, container: Container = Depends(get_container)
) -> Incident:
    if body.owner is None and body.severity is None:
        raise ApiError(422, "NOTHING_TO_UPDATE", "Provide an owner or a severity.")
    try:
        incident = container.incidents.update(incident_id, body)
    except IncidentClosedError as exc:
        raise ApiError(409, "INCIDENT_CLOSED", "The incident is closed and cannot change.") from exc
    if incident is None:
        raise _not_found("INCIDENT_NOT_FOUND", "Incident")
    return incident


# ---- Data-subject requests ----------------------------------------------------------------


@router.get("/data-requests", response_model=DataRequestListResponse)
def list_data_requests(
    container: Container = Depends(get_container), status: DataRequestStatus | None = None
) -> DataRequestListResponse:
    items = container.data_requests.list(status)
    return DataRequestListResponse(items=items, total=len(items))


@router.post("/data-requests", response_model=DataRequest, status_code=201, dependencies=admin, responses=ERRORS)
def create_data_request(body: DataRequestCreate, container: Container = Depends(get_container)) -> DataRequest:
    try:
        return container.data_requests.create(body)
    except UnknownSystemError as exc:
        raise ApiError(422, "UNKNOWN_SYSTEM", "One or more selected AI systems are not in the inventory.") from exc
    except InvalidReceivedDateError as exc:
        raise ApiError(422, "RECEIVED_IN_FUTURE", "The received date cannot be in the future.") from exc


@router.get("/data-requests/{request_id}", response_model=DataRequest, responses=ERRORS)
def get_data_request(request_id: str = DataRequestId, container: Container = Depends(get_container)) -> DataRequest:
    item = container.data_requests.get(request_id)
    if item is None:
        raise _not_found("DATA_REQUEST_NOT_FOUND", "Data request")
    return item


@router.put("/data-requests/{request_id}/systems/{system_id}", response_model=DataRequest, dependencies=admin, responses=ERRORS)
def update_data_request_system(
    body: DataRequestSystemUpdate,
    request_id: str = DataRequestId,
    system_id: str = SystemId,
    container: Container = Depends(get_container),
) -> DataRequest:
    """Mark one system's part of the request as done, not holding the data, or pending again."""
    try:
        item = container.data_requests.update_system(request_id, system_id, body)
    except DataRequestCompletedError as exc:
        raise ApiError(409, "DATA_REQUEST_COMPLETED", "The request is complete and cannot change.") from exc
    if item is None:
        raise _not_found("DATA_REQUEST_NOT_FOUND", "Data request or system entry")
    return item
