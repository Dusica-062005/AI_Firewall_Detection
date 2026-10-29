"""Operator controls (kill switch, privacy-utility dial) and signed receipts."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import timezone
from pathlib import Path as FsPath

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.engine import make_url
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_container, require_admin
from app.api.errors import ApiError
from app.config import BACKEND_ROOT
from app.container import Container
from app.db.models import ReceiptRecord
from app.policy.dial import DIAL_LABELS
from app.schemas.responses import ErrorResponse
from app.schemas.trust import (
    ControlsResponse,
    DialPositionInfo,
    DialRequest,
    KillSwitchRequest,
    ReceiptItem,
    ReceiptListResponse,
    SigningInfo,
    VerifyResponse,
)
from app.trust.controls import Controls

router = APIRouter(tags=["trust"])

VERIFIER = BACKEND_ROOT / "scripts" / "verify_chain.py"
DIAL_DESCRIPTIONS = {
    # The dial only changes values that policy leaves readable (with the default policies: health
    # terms and dates). Names, numbers and places that policy redacts stay redacted at every position.
    "max_privacy": "Also tokenizes what policy leaves readable, such as health terms and dates, and keeps processing on the local model.",
    "balanced": "Also tokenizes what policy leaves readable, such as health terms, but keeps dates and times readable so scheduling still works. The cloud stand-in is allowed.",
    "max_quality": "Tokenizes only what policy requires, so health terms and dates stay readable. The cloud stand-in is allowed.",
}


def _controls(c: Controls) -> ControlsResponse:
    def aware(value):
        return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value

    return ControlsResponse(
        kill_switch=c.kill_switch,
        cloud_path=c.cloud_path,  # type: ignore[arg-type]
        dial=c.dial,  # type: ignore[arg-type]
        kill_switch_updated_at=aware(c.kill_switch_updated_at),
        dial_updated_at=aware(c.dial_updated_at),
        dial_positions=[DialPositionInfo(id=k, label=v, description=DIAL_DESCRIPTIONS[k]) for k, v in DIAL_LABELS.items()],
    )


@router.get("/controls", response_model=ControlsResponse)
def get_controls(container: Container = Depends(get_container)) -> ControlsResponse:
    return _controls(container.controls.get())


@router.put("/controls/kill-switch", response_model=ControlsResponse, dependencies=[Depends(require_admin)])
def set_kill_switch(body: KillSwitchRequest, container: Container = Depends(get_container)) -> ControlsResponse:
    """Block (or restore) every cloud-bound path immediately. Local processing continues."""
    return _controls(container.controls.set_kill_switch(body.enabled))


@router.put("/controls/dial", response_model=ControlsResponse, dependencies=[Depends(require_admin)])
def set_dial(body: DialRequest, container: Container = Depends(get_container)) -> ControlsResponse:
    return _controls(container.controls.set_dial(body.position))


def _receipt(r: ReceiptRecord) -> ReceiptItem:
    created = r.created_at if r.created_at.tzinfo else r.created_at.replace(tzinfo=timezone.utc)
    return ReceiptItem(
        seq=r.seq, receipt_id=r.receipt_id, request_id=r.request_id, created_at=created, hash=r.hash,
        prev_hash=r.prev_hash, signed=r.signature is not None, key_id=r.key_id, body=json.loads(r.body),
    )


@router.get("/receipts", response_model=ReceiptListResponse)
def list_receipts(
    container: Container = Depends(get_container),
    page: int = Query(1, ge=1, le=10000),
    page_size: int = Query(25, ge=1, le=200),
) -> ReceiptListResponse:
    rows, total = container.receipts.list(page, page_size)
    status = container.receipts.key_status
    return ReceiptListResponse(
        items=[_receipt(r) for r in rows], total=total, page=page, page_size=page_size,
        signing=SigningInfo(status=status.status, message=status.message, key_id=container.receipts.key_id),
    )


@router.get("/receipts/public-key", response_class=PlainTextResponse)
def public_key(container: Container = Depends(get_container)) -> str:
    pem = container.receipts.public_key_pem
    if not pem:
        raise ApiError(404, "SIGNING_KEY_NOT_CONFIGURED", container.receipts.key_status.message)
    return pem


@router.get("/receipts/{receipt_id}", response_model=ReceiptItem, responses={404: {"model": ErrorResponse}})
def get_receipt(
    receipt_id: str = Path(pattern=r"^rcp-[a-f0-9]{16}$"), container: Container = Depends(get_container)
) -> ReceiptItem:
    row = container.receipts.get(receipt_id)
    if row is None:
        raise ApiError(404, "RECEIPT_NOT_FOUND", "Receipt not found.")
    return _receipt(row)


@router.post("/receipts/verify", response_model=VerifyResponse)
async def verify_receipts(
    tamper_demo: bool = Query(False, description="Verify a tampered COPY of the database to show detection."),
    container: Container = Depends(get_container),
) -> VerifyResponse:
    """Run the standalone offline verifier script (no project imports) against the database."""
    in_process = await run_in_threadpool(container.receipts.verify)
    url = make_url(container.settings.database_url)
    pubkey = container.settings.keys_dir / "receipt_public_key.pem"
    if url.get_backend_name() != "sqlite" or not url.database or not pubkey.exists() or not VERIFIER.exists():
        return VerifyResponse(
            ok=in_process.ok and not tamper_demo, verifier="in-process", tamper_demo=tamper_demo, exit_code=None,
            output=in_process.reason, in_process_ok=in_process.ok, in_process_reason=in_process.reason, count=in_process.count,
        )
    args = [sys.executable, str(VERIFIER), "--db", str(FsPath(url.database).resolve()), "--pubkey", str(pubkey)]
    if tamper_demo:
        args.append("--tamper-demo")

    def run() -> subprocess.CompletedProcess:
        return subprocess.run(args, capture_output=True, text=True, timeout=60, check=False)

    try:
        done = await run_in_threadpool(run)
    except (OSError, subprocess.TimeoutExpired):
        raise ApiError(503, "VERIFIER_FAILED", "The offline verifier could not be run.") from None
    return VerifyResponse(
        ok=done.returncode == 0, verifier="offline-script", tamper_demo=tamper_demo, exit_code=done.returncode,
        output=(done.stdout + done.stderr).strip(), in_process_ok=in_process.ok,
        in_process_reason=in_process.reason, count=in_process.count,
    )
