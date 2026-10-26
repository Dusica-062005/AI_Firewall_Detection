"""Local transcription (FR-1): audio in, transcript out, then the normal firewall workflow.

Raw audio never leaves the machine and is never stored. The upload is written to a temp file,
transcribed locally and deleted in ``finally``, also when anything fails. If transcription
fails, nothing is processed or sent.
"""

from __future__ import annotations

import base64
import logging
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_container
from app.api.errors import ApiError
from app.api.routes.common import check_transcript_request
from app.audio.bleep import BleepError, bleep_ranges, bleep_wav, check_wav
from app.audio.transcriber import Transcript, TranscriptionError
from app.container import Container
from app.policy.dial import dial_protects
from app.policy.models import PROFILE_PATTERN, Channel
from app.schemas.audio import (
    AudioProcessResult,
    BleepInfo,
    BleepRange,
    TranscriptionInfo,
    TranscriptResponse,
    WordInfo,
)
from app.schemas.requests import ProcessingMode, ProcessRequest
from app.schemas.responses import ErrorResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["audio"])

AUDIO_PATHS = ("/api/transcribe", "/api/process-audio")
AUDIO_FORMATS = {".wav": "wav", ".mp3": "mp3", ".m4a": "m4a"}
CHUNK = 1024 * 1024
ERROR_STATUS = {"AUDIO_TOO_LONG": 422, "AUDIO_UNREADABLE": 422, "TRANSCRIPTION_UNAVAILABLE": 503}
ERRORS = {413: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}}


def _format(upload: UploadFile) -> str:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in AUDIO_FORMATS:
        raise ApiError(422, "UNSUPPORTED_AUDIO", "Upload a .wav, .mp3 or .m4a file.")
    return AUDIO_FORMATS[suffix]


async def _transcribe(
    upload: UploadFile, container: Container, keep: bytearray | None = None, before=None
) -> tuple[Transcript, str]:
    """Write the upload to a temp file, transcribe it and always delete the file.

    ``keep`` also collects the bytes in memory (for bleeping); ``before`` checks them before
    transcription, so an unusable file fails before anything is processed.
    """
    fmt = _format(upload)
    settings = container.settings
    temp_dir = settings.audio_temp_dir
    if temp_dir is not None:
        temp_dir.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(suffix=f".{fmt}", dir=temp_dir)
    path = Path(name)
    try:
        size = 0
        with os.fdopen(handle, "wb") as out:
            while chunk := await upload.read(CHUNK):
                size += len(chunk)
                if size > settings.max_audio_bytes:
                    raise ApiError(413, "AUDIO_TOO_LARGE", f"Audio exceeds {settings.max_audio_bytes} bytes.")
                out.write(chunk)
                if keep is not None:
                    keep.extend(chunk)
        if size == 0:
            raise ApiError(422, "AUDIO_EMPTY", "The uploaded audio file is empty.")
        if before is not None:
            before(bytes(keep))
        try:
            transcript = await run_in_threadpool(container.transcriber.transcribe, path)
        except TranscriptionError as exc:
            raise ApiError(ERROR_STATUS.get(exc.code, 422), exc.code, exc.message) from None
        except Exception:  # noqa: BLE001 - any failure: nothing is processed or sent
            logger.error("transcription failed unexpectedly")
            raise ApiError(422, "TRANSCRIPTION_FAILED", "The audio could not be transcribed. Nothing was processed.") from None
        if not transcript.text.strip():
            raise ApiError(422, "EMPTY_TRANSCRIPT", "No speech was recognized in the audio. Nothing was processed.")
        return transcript, fmt
    finally:
        path.unlink(missing_ok=True)


def _words(transcript: Transcript) -> list[WordInfo]:
    return [WordInfo(**asdict(w)) for w in transcript.words]


@router.post("/transcribe", response_model=TranscriptResponse, responses=ERRORS)
async def transcribe(file: UploadFile = File(...), container: Container = Depends(get_container)) -> TranscriptResponse:
    """Transcribe locally. Nothing is detected, processed or sent."""
    transcript, _ = await _transcribe(file, container)
    return TranscriptResponse(
        transcript=transcript.text, language=transcript.language, duration_s=transcript.duration_s,
        model=transcript.model, transcription_ms=transcript.transcription_ms, words=_words(transcript),
    )


@router.post("/process-audio", response_model=AudioProcessResult, responses=ERRORS)
async def process_audio(
    file: UploadFile = File(...),
    profile: str = Form("standard", pattern=PROFILE_PATTERN),
    channel: Channel = Form("voice"),
    mode: ProcessingMode = Form(ProcessingMode.FULL),
    bleep: bool = Query(False, description="Also return the WAV with every protected word bleeped (FR-16)."),
    container: Container = Depends(get_container),
) -> AudioProcessResult:
    """Transcribe locally, then run the normal policy-controlled workflow on the transcript."""
    audio_bytes: bytearray | None = None
    if bleep:
        if _format(file) != "wav":
            raise ApiError(422, "BLEEP_WAV_ONLY", "Bleeping needs a 16-bit PCM .wav file.")
        audio_bytes = bytearray()
    transcript, fmt = await _transcribe(file, container, audio_bytes, _check_wav if bleep else None)
    return await finish_audio_call(
        container, transcript, fmt, profile, channel, mode, bytes(audio_bytes) if bleep else None
    )


async def finish_audio_call(
    container: Container, transcript: Transcript, fmt: str, profile: str, channel: str,
    mode: ProcessingMode, bleep_wav_bytes: bytes | None, progress=None,
) -> AudioProcessResult:
    """Run a transcribed call through the normal workflow. Shared by uploads and live calls.

    ``bleep_wav_bytes`` (a 16-bit PCM WAV) also returns the recording with protected words bleeped.
    ``progress`` reports each stage as it starts (live calls).
    """
    request = ProcessRequest(transcript=transcript.text, profile=profile, channel=channel, mode=mode)
    request_id = check_transcript_request(request, container)
    audio = {
        "format": fmt, "duration_s": transcript.duration_s, "model": transcript.model,
        "transcription_ms": transcript.transcription_ms,
    }
    result = await container.processing.run(
        request_id=request_id, transcript=transcript.text, profile=profile, channel=channel, mode=mode,
        operation="PROCESS", audio=audio, progress=progress,
    )
    expose = container.settings.expose_detected_values
    return AudioProcessResult(
        **result.model_dump(),
        transcription=TranscriptionInfo(
            model=transcript.model, language=transcript.language, duration_s=transcript.duration_s,
            transcription_ms=transcript.transcription_ms, format=fmt,
            transcript=transcript.text if expose else None, words=_words(transcript) if expose else [],
        ),
        bleep=_bleep(bleep_wav_bytes, transcript, result, container.settings.bleep_style)
        if bleep_wav_bytes is not None else None,
    )


def _check_wav(data: bytes) -> None:
    try:
        check_wav(data)
    except BleepError as exc:
        raise ApiError(422, "BLEEP_WAV_ONLY", str(exc)) from None


def _bleep(data: bytes, transcript: Transcript, result, style: str) -> BleepInfo:
    """Bleep exactly what was tokenized in the text: non-ALLOW entities plus what the dial protects."""
    dial = result.routing.dial if result.routing else "max_quality"
    spans = [(e.start, e.end) for e in result.entities if e.action != "ALLOW" or dial_protects(dial, e.entity_type)]
    ranges = bleep_ranges(transcript.words, spans, transcript.duration_s)
    try:
        audio = bleep_wav(data, ranges, style)
    except BleepError as exc:
        raise ApiError(422, "BLEEP_FAILED", str(exc)) from None
    return BleepInfo(style=style, ranges=[BleepRange(start_s=a, end_s=b) for a, b in ranges],
                     audio_base64=base64.b64encode(audio).decode("ascii"))
