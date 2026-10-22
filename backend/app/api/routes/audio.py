"""Local transcription (FR-1): audio in, transcript out, then the normal firewall workflow.

Raw audio never leaves the machine and is never stored. The upload is written to a temp file,
transcribed locally and deleted in ``finally``, also when anything fails. If transcription
fails, nothing is processed or sent.
"""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_container
from app.api.errors import ApiError
from app.api.routes.common import check_transcript_request
from app.audio.transcriber import Transcript, TranscriptionError
from app.container import Container
from app.policy.models import PROFILE_PATTERN, Channel
from app.schemas.audio import AudioProcessResult, TranscriptionInfo, TranscriptResponse, WordInfo
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


async def _transcribe(upload: UploadFile, container: Container) -> tuple[Transcript, str]:
    """Write the upload to a temp file, transcribe it and always delete the file."""
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
        if size == 0:
            raise ApiError(422, "AUDIO_EMPTY", "The uploaded audio file is empty.")
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
    container: Container = Depends(get_container),
) -> AudioProcessResult:
    """Transcribe locally, then run the normal policy-controlled workflow on the transcript."""
    transcript, fmt = await _transcribe(file, container)
    request = ProcessRequest(transcript=transcript.text, profile=profile, channel=channel, mode=mode)
    request_id = check_transcript_request(request, container)
    audio = {
        "format": fmt, "duration_s": transcript.duration_s, "model": transcript.model,
        "transcription_ms": transcript.transcription_ms,
    }
    result = await container.processing.run(
        request_id=request_id, transcript=transcript.text, profile=profile, channel=channel, mode=mode,
        operation="PROCESS", audio=audio,
    )
    expose = container.settings.expose_detected_values
    return AudioProcessResult(
        **result.model_dump(),
        transcription=TranscriptionInfo(
            model=transcript.model, language=transcript.language, duration_s=transcript.duration_s,
            transcription_ms=transcript.transcription_ms, format=fmt,
            transcript=transcript.text if expose else None, words=_words(transcript) if expose else [],
        ),
    )
