from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_container
from app.api.routes.common import check_transcript_request
from app.container import Container
from app.schemas.requests import ProcessRequest
from app.schemas.responses import ErrorResponse, FirewallResult

router = APIRouter(tags=["firewall"])


@router.post(
    "/process",
    response_model=FirewallResult,
    responses={413: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def process(body: ProcessRequest, container: Container = Depends(get_container)) -> FirewallResult:
    """Run the full policy-controlled workflow. The mode can only narrow what policy allows."""
    request_id = check_transcript_request(body, container)
    return await container.processing.run(
        request_id=request_id,
        transcript=body.transcript,
        profile=body.profile,
        channel=body.channel,
        mode=body.mode,
        operation="PROCESS",
    )
