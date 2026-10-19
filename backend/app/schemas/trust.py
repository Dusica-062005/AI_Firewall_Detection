"""Schemas for the trust layer: operator controls and signed receipts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class DialPositionInfo(BaseModel):
    id: str
    label: str
    description: str


class ControlsResponse(BaseModel):
    kill_switch: bool
    cloud_path: Literal["ACTIVE", "BLOCKED"]
    dial: Literal["max_privacy", "balanced", "max_quality"]
    kill_switch_updated_at: datetime | None
    dial_updated_at: datetime | None
    dial_positions: list[DialPositionInfo]


class KillSwitchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class DialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position: Literal["max_privacy", "balanced", "max_quality"]


class ReceiptItem(BaseModel):
    seq: int
    receipt_id: str
    request_id: str
    created_at: datetime
    hash: str
    prev_hash: str
    signed: bool
    key_id: str | None
    body: dict


class SigningInfo(BaseModel):
    status: str
    message: str
    key_id: str | None


class ReceiptListResponse(BaseModel):
    items: list[ReceiptItem]
    total: int
    page: int
    page_size: int
    signing: SigningInfo


class VerifyResponse(BaseModel):
    ok: bool
    verifier: Literal["offline-script", "in-process"]
    tamper_demo: bool
    exit_code: int | None
    output: str
    in_process_ok: bool
    in_process_reason: str
    count: int
