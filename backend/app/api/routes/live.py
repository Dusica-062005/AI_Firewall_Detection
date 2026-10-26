"""Live redacted captions over a WebSocket: /api/live.

Protocol (JSON text frames, plus binary audio frames):

    client -> {"type": "start", "profile": "standard", "channel": "voice", "mode": "full", "bleep": true}
    server -> {"type": "ready", "chunk_seconds": 4.0, "max_seconds": 300}
    client -> binary frames: 16 kHz mono 16-bit little-endian PCM, any size
    server -> {"type": "caption", "index": 0, "text": "my name is [PERSON_1]", "withheld": false}
    server -> {"type": "status", "seconds": 12.0}
    client -> {"type": "stop"}
    server -> {"type": "result", "result": <AudioProcessResult>}   (the normal pipeline, once)
    server -> {"type": "error", "code": "...", "message": "..."}   (then the socket closes)

Captions are a local preview: they are never sent to the cloud, stored or audited. Only the
final pass runs the router, receipts and (if allowed) the cloud handoff. If the client
disconnects before "stop", nothing is processed and the audio is dropped.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

import regex
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from app.api.errors import ApiError
from app.api.routes.audio import finish_audio_call
from app.audio.live import LiveLimitError, LiveSession
from app.audio.transcriber import TranscriptionError
from app.container import Container
from app.detection.normalizer import map_span, normalize_numbers
from app.policy.dial import dial_protects
from app.policy.models import Action
from app.schemas.requests import ProcessingMode

logger = logging.getLogger(__name__)
router = APIRouter(tags=["live"])

PROFILE_MAX = 40
CHANNELS = {"voice", "chat", "email", "sms"}


LONG_NUMBER = regex.compile(r"\d(?:[\s,.\-]*\d)+")
LONG_NUMBER_DIGITS = 5


def number_spans(text: str) -> list[tuple[int, int, str]]:
    """Every run of 5+ digits (typed or spoken), mapped back to ``text``.

    Captions come from short chunks, where speech-to-text can drop a digit and a recognizer then
    misses the number. Captions are only a preview, so they hide every long number regardless.
    """
    n = normalize_numbers(text)
    spans = []
    for m in LONG_NUMBER.finditer(n.text):
        if sum(c.isdigit() for c in m.group()) >= LONG_NUMBER_DIGITS:
            start, end = map_span(n, m.start(), m.end()) if n.changed else m.span()
            spans.append((start, end, "NUMBER"))
    return spans


def make_protector(container: Container, profile: str, channel: str, dial: str):
    """Hide what the final pass would tokenize (non-ALLOW entities plus what the dial protects),
    and, stricter than the final pass, every long number."""
    settings = container.settings

    def protect(text: str) -> list[tuple[int, int, str]]:
        entities = container.analyzer.analyze(text, normalize=settings.normalize_numbers)
        decision = container.firewall.engine.evaluate(entities, container.policy_repository.list(), profile, channel)
        return [
            (d.entity.start, d.entity.end, d.entity.entity_type)
            for d in decision.entity_decisions
            if d.action is not Action.ALLOW or dial_protects(dial, d.entity.entity_type)
        ] + number_spans(text)

    return protect


async def _error(ws: WebSocket, code: str, message: str) -> None:
    await ws.send_json({"type": "error", "code": code, "message": message})
    await ws.close()


@router.websocket("/live")
async def live(ws: WebSocket) -> None:
    container: Container = ws.app.state.container
    settings = container.settings
    origin = ws.headers.get("origin")
    if origin and origin not in settings.cors_origin_list:
        await ws.close(code=1008)  # browsers do not apply CORS to WebSockets, so check the origin here
        return
    await ws.accept()

    try:
        start = await ws.receive_json()
    except (WebSocketDisconnect, ValueError, KeyError):
        return
    profile = str(start.get("profile", "standard"))[:PROFILE_MAX]
    channel = str(start.get("channel", "voice"))
    try:
        mode = ProcessingMode(start.get("mode", "full"))
    except ValueError:
        await _error(ws, "INVALID_MODE", "mode must be inspect, local or full.")
        return
    bleep = bool(start.get("bleep", False))
    if start.get("type") != "start" or channel not in CHANNELS:
        await _error(ws, "INVALID_START", "Send {\"type\": \"start\"} with a valid profile and channel first.")
        return
    if container.policy_status["status"] != "READY":
        await _error(ws, "POLICY_UNAVAILABLE", "Policy configuration is not loaded; processing is disabled.")
        return
    if profile not in {p.id for p, _ in container.policy_service.profiles()}:
        await _error(ws, "UNKNOWN_PROFILE", f"Unknown policy profile '{profile}'.")
        return

    dial = container.controls.get().dial
    session = LiveSession(
        container.transcriber.transcribe_array, make_protector(container, profile, channel, dial),
        settings.live_chunk_seconds, settings.live_window_chunks, settings.max_audio_seconds,
    )
    await ws.send_json({"type": "ready", "chunk_seconds": settings.live_chunk_seconds,
                        "max_seconds": settings.max_audio_seconds, "local_only": True})

    try:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                return  # nothing is processed; the audio is dropped with the session
            if message.get("bytes") is not None:
                session.add_audio(message["bytes"])
                while session.has_chunk():
                    for update in await run_in_threadpool(session.process_next):
                        await ws.send_json(update.as_message())
                    await ws.send_json({"type": "status", "seconds": session.seconds})
            elif message.get("text") is not None and '"stop"' in message["text"]:
                break
        for update in await run_in_threadpool(session.process_next, True):
            await ws.send_json(update.as_message())
    except LiveLimitError as exc:
        await _error(ws, "AUDIO_TOO_LONG", f"{exc} Nothing was processed.")
        return
    except TranscriptionError as exc:
        await _error(ws, exc.code, f"{exc.message} Nothing was processed.")
        return
    except WebSocketDisconnect:
        return

    if session.seconds < 0.5:
        await _error(ws, "AUDIO_EMPTY", "No audio was received. Nothing was processed.")
        return
    await _finish(ws, container, session, profile, channel, mode, bleep)


async def _finish(ws, container, session, profile, channel, mode, bleep) -> None:
    """The authoritative pass: transcribe the whole call, then the normal pipeline."""
    wav = session.wav_bytes()
    temp_dir = container.settings.audio_temp_dir
    if temp_dir is not None:
        temp_dir.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(suffix=".wav", dir=temp_dir)
    path = Path(name)
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(wav)
        try:
            transcript = await run_in_threadpool(container.transcriber.transcribe, path)
        except TranscriptionError as exc:
            await _error(ws, exc.code, f"{exc.message} Nothing was processed.")
            return
        except Exception:  # noqa: BLE001 - nothing is processed or sent
            await _error(ws, "TRANSCRIPTION_FAILED", "The call could not be transcribed. Nothing was processed.")
            return
    finally:
        path.unlink(missing_ok=True)
    if not transcript.text.strip():
        await _error(ws, "EMPTY_TRANSCRIPT", "No speech was recognized in the call. Nothing was processed.")
        return
    try:
        result = await finish_audio_call(container, transcript, "wav", profile, channel, mode, wav if bleep else None)
    except ApiError as exc:
        await _error(ws, exc.code, exc.message)
        return
    await ws.send_json({"type": "result", "result": result.model_dump(mode="json")})
    await ws.close()
