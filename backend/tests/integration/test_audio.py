"""Local transcription (FR-1). Unit tests use a transcriber stub, so no model download is needed.

The one test marked slow runs real faster-whisper on a synthetic fixture and is skipped when the
model is not in the local cache.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.audio.transcriber import Transcriber, Transcript, TranscriptionError, join_words
from app.detection.normalizer import normalize_numbers

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "audio"
SPOKEN = "Hello, my name is John Smith. My patient ID is P nine four eight two nine one three."


class TranscriberStub:
    """Returns a fixed transcript, or raises; records the temp files it was given."""

    status = "READY"
    message = "stub"

    def __init__(self, text: str = SPOKEN, error: TranscriptionError | None = None) -> None:
        self.text, self.error, self.paths = text, error, []

    def transcribe(self, path: Path, language: str | None = None) -> Transcript:
        self.paths.append(path)
        assert path.exists() and path.stat().st_size > 0  # the upload was written before transcription
        if self.error:
            raise self.error
        text, words = join_words([(w, i * 0.4, i * 0.4 + 0.35) for i, w in enumerate(self.text.split())])
        return Transcript(text=text, language="en", duration_s=5.6, model="stub", transcription_ms=12.5, words=words)


@pytest.fixture
def audio_harness(harness_factory, tmp_path):
    def factory(stub: TranscriberStub | None = None, **overrides):
        h = harness_factory(audio_temp_dir=tmp_path / "audio-tmp", **overrides)
        h.container.transcriber = stub or TranscriberStub()
        return h

    return factory


def upload(h, path: str = "/api/process-audio", name: str = "call.wav", data: bytes = b"RIFF-synthetic", **form):
    return h.client.post(path, files={"file": (name, data, "audio/wav")}, data=form)


def leftover_audio(h) -> list[Path]:
    folder = h.container.settings.audio_temp_dir
    return list(folder.iterdir()) if folder.exists() else []


def test_join_words_offsets_are_exact():
    text, words = join_words([(" Hello,", 0.0, 0.4), (" my", 0.4, 0.6), ("", 0.6, 0.7), (" name", 0.7, 1.0)])
    assert text == "Hello, my name"
    assert [text[w.char_start : w.char_end] for w in words] == ["Hello,", "my", "name"]


def test_transcript_goes_through_the_normal_pipeline(audio_harness):
    h = audio_harness()
    body = upload(h, profile="standard").json()
    assert body["decision"] == "REDACTED"
    assert {e["entity_type"] for e in body["entities"]} >= {"PERSON", "PATIENT_ID"}
    assert "four eight" not in body["redacted_transcript"]
    assert body["transcription"]["model"] == "stub" and body["transcription"]["format"] == "wav"
    assert body["latency"]["transcription_ms"] == 12.5
    assert body["transcription"]["words"][0] == {"word": "Hello,", "start_s": 0.0, "end_s": 0.35, "char_start": 0, "char_end": 6}
    sent = b"".join(r.content for r in h.receiver_transport.handoff_requests())
    assert b"John Smith" not in sent and b"nine four" not in sent


def test_receipt_and_audit_record_only_audio_facts(audio_harness):
    h = audio_harness()
    body = upload(h).json()
    receipt = json.loads(h.container.receipts.all()[-1].body)
    assert receipt["audio"] == {"format": "wav", "duration_s": 5.6, "model": "stub", "transcription_ms": 12.5}
    event = h.client.get(f"/api/audit/{body['event_id']}").json()
    assert event["latency_ms"]["transcription_ms"] == 12.5
    assert "John" not in json.dumps(event) and "John" not in json.dumps(receipt)


def test_transcribe_only_returns_text_and_sends_nothing(audio_harness):
    h = audio_harness()
    body = upload(h, path="/api/transcribe").json()
    assert body["transcript"].startswith("Hello, my name is John Smith")
    assert h.receiver_transport.requests == [] and h.container.receipts.all() == []


def test_transcript_is_withheld_when_values_are_not_exposed(audio_harness):
    body = upload(audio_harness(expose_detected_values=False)).json()
    assert body["transcription"]["transcript"] is None and body["transcription"]["words"] == []


def test_temp_file_is_deleted_after_success_and_after_failure(audio_harness):
    ok = TranscriberStub()
    h = audio_harness(ok)
    upload(h)
    assert ok.paths and not ok.paths[0].exists() and leftover_audio(h) == []

    failing = TranscriberStub(error=TranscriptionError("AUDIO_UNREADABLE", "The audio could not be decoded."))
    h.container.transcriber = failing
    assert upload(h).status_code == 422
    assert not failing.paths[0].exists() and leftover_audio(h) == []


@pytest.mark.parametrize(
    "error, status",
    [
        (TranscriptionError("AUDIO_UNREADABLE", "bad"), 422),
        (TranscriptionError("AUDIO_TOO_LONG", "long"), 422),
        (TranscriptionError("TRANSCRIPTION_UNAVAILABLE", "no model"), 503),
    ],
)
def test_transcription_failure_processes_and_sends_nothing(audio_harness, error, status):
    h = audio_harness(TranscriberStub(error=error))
    response = upload(h)
    assert response.status_code == status
    assert response.json()["error"]["code"] == error.code
    assert h.receiver_transport.requests == [] and h.ollama.prompts == [] and h.container.receipts.all() == []


def test_unexpected_transcriber_error_fails_closed(audio_harness):
    class Broken(TranscriberStub):
        def transcribe(self, path, language=None):
            raise RuntimeError("boom")

    h = audio_harness(Broken())
    assert upload(h).json()["error"]["code"] == "TRANSCRIPTION_FAILED"
    assert h.receiver_transport.requests == []


def test_oversized_audio_is_rejected_before_transcription(audio_harness):
    stub = TranscriberStub()
    h = audio_harness(stub, max_audio_bytes=2048)
    response = upload(h, data=b"x" * 4096)
    assert response.status_code == 413
    assert stub.paths == []


def test_other_routes_keep_the_small_body_limit(audio_harness):
    h = audio_harness()
    response = h.client.post("/api/process", content=b"x" * 70000, headers={"Content-Type": "application/json"})
    assert response.status_code == 413


@pytest.mark.parametrize("name, data, code", [("call.txt", b"abc", "UNSUPPORTED_AUDIO"), ("call.wav", b"", "AUDIO_EMPTY")])
def test_bad_uploads_are_rejected(audio_harness, name, data, code):
    response = upload(audio_harness(), name=name, data=data)
    assert response.status_code == 422 and response.json()["error"]["code"] == code


def test_silence_is_not_processed(audio_harness):
    h = audio_harness(TranscriberStub(text=""))
    assert upload(h).json()["error"]["code"] == "EMPTY_TRANSCRIPT"
    assert h.container.receipts.all() == []


def test_health_and_config_report_transcription_status(audio_harness):
    h = audio_harness()
    h.container.transcriber = Transcriber("base", "cpu", "int8", 300)
    assert h.client.get("/api/health").json()["components"]["transcription"]["status"] == "NOT_LOADED"
    config = h.client.get("/api/config").json()["transcription"]
    assert config["model"] == "base" and config["stores_audio"] is False


def test_spoken_digit_fragments_from_transcription_are_joined():
    # How faster-whisper writes a spoken phone number.
    assert normalize_numbers("call me back on 9 -8 -4 -5 -0 -123 -4 -5.").text == "call me back on 9845012345."
    assert normalize_numbers("Take 2 or 3 tablets for 10 - 11 days.").text == "Take 2 or 3 tablets for 10 - 11 days."


def whisper_available() -> bool:
    try:
        from faster_whisper.utils import download_model

        download_model("base", local_files_only=True)
        return True
    except Exception:  # noqa: BLE001 - not cached: skip rather than download in a test
        return False


@pytest.mark.slow
@pytest.mark.skipif(not whisper_available(), reason="faster-whisper 'base' model is not in the local cache")
def test_real_whisper_transcribes_a_synthetic_call(harness_factory):
    h = harness_factory()
    with (FIXTURES / "appointment.wav").open("rb") as handle:
        body = h.client.post("/api/process-audio", files={"file": ("appointment.wav", handle, "audio/wav")}).json()
    assert body["transcription"]["language"] == "en"
    assert "John Smith" in body["transcription"]["transcript"]
    assert {"PERSON", "PATIENT_ID"} <= {e["entity_type"] for e in body["entities"]}
    assert "John Smith" not in body["redacted_transcript"]
