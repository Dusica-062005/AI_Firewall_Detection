"""Schemas for local transcription (FR-1) and audio processing."""

from __future__ import annotations

from pydantic import BaseModel

from app.schemas.responses import FirewallResult


class WordInfo(BaseModel):
    word: str
    start_s: float
    end_s: float
    char_start: int  # exact offsets into the transcript text
    char_end: int


class TranscriptResponse(BaseModel):
    """POST /transcribe: the transcript only. Nothing is detected, processed or sent."""

    transcript: str
    language: str
    duration_s: float
    model: str
    transcription_ms: float
    words: list[WordInfo]


class TranscriptionInfo(BaseModel):
    model: str
    language: str
    duration_s: float
    transcription_ms: float
    format: str
    # The local transcript, for the Inspector view. Only returned when EXPOSE_DETECTED_VALUES is on.
    transcript: str | None
    words: list[WordInfo]


class AudioProcessResult(FirewallResult):
    transcription: TranscriptionInfo
