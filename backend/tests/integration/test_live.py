"""Live redacted captions over /api/live, with a transcriber stub (no model download)."""

from __future__ import annotations

import json
import re

import numpy as np
import pytest
from starlette.websockets import WebSocketDisconnect

from app.audio.live import WITHHELD, LiveSession
from app.audio.transcriber import Transcript, join_words

RATE = 16000
DIGIT_WORDS = re.compile(r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine)\b", re.IGNORECASE)


def tone(seconds: float = 1.0) -> bytes:
    """Non-silent synthetic audio (a 220 Hz tone), 16 kHz mono 16-bit PCM."""
    t = np.arange(int(seconds * RATE)) / RATE
    return (6000 * np.sin(2 * np.pi * 220 * t)).astype("<i2").tobytes()


def silence(seconds: float = 1.0) -> bytes:
    return bytes(int(seconds * RATE) * 2)


def transcript(text: str) -> Transcript:
    joined, words = join_words([(w, i * 0.3, i * 0.3 + 0.25) for i, w in enumerate(text.split())])
    return Transcript(text=joined, language="en", duration_s=1.0, model="stub", transcription_ms=5.0, words=words)


class LiveTranscriberStub:
    """Returns the next scripted chunk text live, and the whole script for the final pass."""

    status = "READY"
    message = "stub"

    def __init__(self, chunks: list[str]) -> None:
        self.chunks = list(chunks)
        self.calls = 0

    def transcribe_array(self, samples, language=None) -> Transcript:
        text = self.chunks[self.calls] if self.calls < len(self.chunks) else ""
        self.calls += 1
        return transcript(text)

    def transcribe(self, path, language=None) -> Transcript:
        return transcript(" ".join(self.chunks))


@pytest.fixture
def live_harness(harness_factory, tmp_path):
    def factory(chunks: list[str], **overrides):
        overrides.setdefault("live_chunk_seconds", 1.0)
        h = harness_factory(audio_temp_dir=tmp_path / "live-tmp", **overrides)
        h.container.transcriber = LiveTranscriberStub(chunks)
        return h

    return factory


def run_call(h, seconds: int, start: dict | None = None, audio=tone):
    """Stream ``seconds`` of audio, stop, and return (captions by index, all messages)."""
    messages = []
    with h.client.websocket_connect("/api/live") as ws:
        ws.send_json({"type": "start", "profile": "standard", "channel": "voice", "mode": "full", **(start or {})})
        messages.append(ws.receive_json())
        for _ in range(seconds):
            ws.send_bytes(audio(1.0))
        ws.send_json({"type": "stop"})
        while True:
            try:
                message = ws.receive_json()
            except WebSocketDisconnect:
                break
            messages.append(message)
            if message["type"] in ("result", "error"):
                break
    captions = {}
    for m in messages:
        if m["type"] == "caption":
            captions[m["index"]] = m["text"]
    return captions, messages


def test_captions_are_redacted_and_the_final_pass_runs_once(live_harness):
    h = live_harness(["Hello, my name is John Smith.", "I need my appointment moved to Monday."])
    captions, messages = run_call(h, 2)
    assert messages[0]["type"] == "ready" and messages[0]["local_only"] is True
    assert "[PERSON_1]" in captions[0] and "John Smith" not in json.dumps(captions)
    result = messages[-1]["result"]
    assert messages[-1]["type"] == "result" and result["decision"] == "REDACTED"
    assert "John Smith" not in result["redacted_transcript"]
    assert result["transcription"]["format"] == "wav"
    receipts = h.container.receipts.all()
    assert len(receipts) == 1 and json.loads(receipts[0].body)["audio"]["format"] == "wav"
    assert len(h.receiver_transport.handoff_requests()) == 1  # only the final pass may reach the cloud


def test_progress_shows_the_protected_transcript_before_the_model_calls(live_harness):
    h = live_harness(["Hello, my name is John Smith.", "I need my appointment moved to Monday."])
    _, messages = run_call(h, 2)
    progress = [m for m in messages if m["type"] == "progress"]
    assert [m["stage"] for m in progress] == ["transcribing", "protecting", "protected", "local_ai", "cloud"]
    preview = progress[2]
    assert "[PERSON_1]" in preview["redacted_transcript"] and "John Smith" not in json.dumps(progress)
    assert preview["redacted_transcript"] == messages[-1]["result"]["redacted_transcript"]
    assert messages.index(progress[-1]) < len(messages) - 1  # all progress comes before the result


def test_inspect_mode_reports_no_model_stages(live_harness):
    h = live_harness(["Hello, my name is John Smith."])
    _, messages = run_call(h, 1, start={"mode": "inspect"})
    assert [m["stage"] for m in messages if m["type"] == "progress"] == ["transcribing", "protecting", "protected"]
    assert messages[-1]["type"] == "result"


def test_nothing_is_sent_or_recorded_during_the_call(live_harness):
    h = live_harness(["Hello, my name is John Smith."])
    with h.client.websocket_connect("/api/live") as ws:
        ws.send_json({"type": "start", "profile": "standard"})
        ws.receive_json()
        ws.send_bytes(tone(1.0))
        caption = ws.receive_json()
        assert caption["type"] == "caption" and "[PERSON_1]" in caption["text"]
        assert h.receiver_transport.requests == [] and h.container.receipts.all() == []
    # Disconnecting without "stop": nothing is processed, recorded or sent.
    assert h.receiver_transport.requests == [] and h.container.receipts.all() == []


def test_an_id_split_across_chunks_is_caught_and_earlier_captions_are_corrected(live_harness):
    h = live_harness(["My patient ID is P nine four", "eight two nine one three, thanks."])
    captions, messages = run_call(h, 2)
    updates_line0 = [m["text"] for m in messages if m["type"] == "caption" and m["index"] == 0]
    assert len(updates_line0) == 2  # shown once, then corrected when the next chunk arrived
    assert not DIGIT_WORDS.search(captions[0]) and not DIGIT_WORDS.search(captions[1])
    assert "[PATIENT_ID_1]" in captions[0]


def test_long_numbers_are_hidden_in_captions_even_if_not_recognized():
    from app.api.routes.live import number_spans

    text = "Please call me back on 9 -8 -45 1 -2 -3 -4 -5, room 12."  # a dropped digit: not a valid phone
    spans = number_spans(text)
    assert len(spans) == 1 and text[spans[0][0]:spans[0][1]] == "9 -8 -45 1 -2 -3 -4 -5"
    spoken = "call nine eight four five zero one two"
    assert spoken[number_spans(spoken)[0][0]:] == "nine eight four five zero one two"
    assert number_spans("Take 2 tablets at 10 and 11.") == []


def test_protection_failure_withholds_the_caption(live_harness, monkeypatch):
    import app.api.routes.live as live_route

    def broken(*_args):
        def protect(_text):
            raise RuntimeError("detector down")
        return protect

    monkeypatch.setattr(live_route, "make_protector", broken)
    h = live_harness(["Hello, my name is John Smith."])
    captions, _ = run_call(h, 1)
    assert captions[0] == WITHHELD


def test_silence_gives_no_captions_and_nothing_is_processed(live_harness):
    h = live_harness([])
    captions, messages = run_call(h, 2, audio=silence)
    assert captions == {}
    assert messages[-1]["type"] == "error" and messages[-1]["code"] == "EMPTY_TRANSCRIPT"
    assert h.container.receipts.all() == []


def test_too_long_call_is_stopped_without_processing(live_harness):
    h = live_harness(["Hello."] * 10, max_audio_seconds=5)
    _, messages = run_call(h, 6)
    assert messages[-1]["code"] == "AUDIO_TOO_LONG"
    assert h.container.receipts.all() == [] and h.receiver_transport.requests == []


def test_unknown_profile_and_bad_start_are_rejected(live_harness):
    h = live_harness([])
    _, messages = run_call(h, 0, start={"profile": "nope"})
    assert messages[-1]["code"] == "UNKNOWN_PROFILE"
    with h.client.websocket_connect("/api/live") as ws:
        ws.send_json({"type": "hello"})
        assert ws.receive_json()["code"] == "INVALID_START"


def test_other_origins_are_refused(live_harness):
    h = live_harness([])
    with pytest.raises(WebSocketDisconnect):
        with h.client.websocket_connect("/api/live", headers={"origin": "http://evil.example"}) as ws:
            ws.receive_json()


def test_bleeped_audio_is_returned_when_requested(live_harness):
    h = live_harness(["Hello, my name is John Smith."])
    _, messages = run_call(h, 2, start={"bleep": True})
    assert messages[-1]["result"]["bleep"]["audio_base64"]


def test_session_reuses_tokens_and_never_unprotects():
    calls = iter(["My name is John Smith.", "Yes, John Smith again."])
    session = LiveSession(
        lambda _samples: transcript(next(calls)),
        lambda text: [(m.start(), m.end(), "PERSON") for m in re.finditer("John Smith", text)],
        chunk_seconds=1.0, window_chunks=1, max_seconds=60,
    )
    session.add_audio(tone(2.0))
    first = session.process_next()
    second = session.process_next()
    assert first[0].text == "My name is [PERSON_1]."
    assert second[-1].text == "Yes, [PERSON_1] again."  # same value, same token
