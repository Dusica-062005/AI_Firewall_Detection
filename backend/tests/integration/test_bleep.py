"""Audio bleeping (FR-16) on generated WAV audio and through POST /process-audio?bleep=true."""

from __future__ import annotations

import base64
import io
import wave

import numpy as np
import pytest

from app.audio.bleep import BleepError, bleep_ranges, bleep_wav
from app.audio.transcriber import join_words
from tests.integration.test_audio import SPOKEN, TranscriberStub

RATE = 16000


def make_wav(seconds: float = 4.0, channels: int = 1) -> bytes:
    t = np.arange(int(seconds * RATE)) / RATE
    voice = (8000 * np.sin(2 * np.pi * 220 * t)).astype("<i2")
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(np.repeat(voice[:, None], channels, axis=1).tobytes())
    return out.getvalue()


def samples(data: bytes) -> np.ndarray:
    with wave.open(io.BytesIO(data), "rb") as wav:
        return np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").reshape(-1, wav.getnchannels())


def words_for(text: str):
    return join_words([(w, i * 0.4, i * 0.4 + 0.35) for i, w in enumerate(text.split())])


def test_ranges_cover_every_overlapping_word_with_padding_and_merge():
    text, words = words_for("my name is John Smith ok")
    start = text.index("John Smith")
    assert bleep_ranges(words, [(start, start + 10)], duration_s=4.0) == [(1.15, 2.0)]  # words 3-4, 50 ms padding
    assert bleep_ranges(words, [(start, start + 4), (start + 5, start + 10)], 4.0) == [(1.15, 2.0)]  # merged
    assert bleep_ranges(words, [], 4.0) == []


@pytest.mark.parametrize("style", ["tone", "silence"])
@pytest.mark.parametrize("channels", [1, 2])
def test_only_the_protected_range_changes(style, channels):
    original = make_wav(channels=channels)
    bleeped = bleep_wav(original, [(1.0, 2.0)], style)
    before, after = samples(original), samples(bleeped)
    first, last = RATE * 1, RATE * 2
    assert np.array_equal(before[:first], after[:first]) and np.array_equal(before[last:], after[last:])
    region = after[first:last]
    if style == "silence":
        assert not region.any()
    else:
        assert abs(int(region.max()) - 3277) <= 2  # 1 kHz tone at -20 dBFS
        assert not np.array_equal(region, before[first:last])


def test_no_entities_means_unchanged_audio():
    original = make_wav()
    assert np.array_equal(samples(bleep_wav(original, [])), samples(original))


def test_non_pcm_wav_is_refused():
    with pytest.raises(BleepError):
        bleep_wav(b"not a wav file", [(0.0, 1.0)])


@pytest.fixture
def bleep_harness(harness_factory, tmp_path):
    h = harness_factory(audio_temp_dir=tmp_path / "audio-tmp")
    h.container.transcriber = TranscriberStub()
    return h


def post(h, data: bytes, name: str = "call.wav"):
    return h.client.post("/api/process-audio?bleep=true", files={"file": (name, data, "audio/wav")})


def test_process_audio_returns_bleeped_wav_for_protected_words(bleep_harness):
    original = make_wav(seconds=7.0)
    body = post(bleep_harness, original).json()
    _, words = words_for(SPOKEN)
    protected = [e for e in body["entities"] if e["entity_type"] in ("PERSON", "PATIENT_ID")]
    expected = bleep_ranges(words, [(e["start"], e["end"]) for e in protected], 5.6)
    assert [(r["start_s"], r["end_s"]) for r in body["bleep"]["ranges"]] == expected
    after = samples(base64.b64decode(body["bleep"]["audio_base64"]))
    before = samples(original)
    first = int(expected[0][0] * RATE)
    assert np.array_equal(before[:first], after[:first])  # untouched before the first protected word
    assert not np.array_equal(before, after)
    assert list(bleep_harness.container.settings.audio_temp_dir.iterdir()) == []  # nothing stored


def test_bleep_needs_wav_and_fails_before_processing(bleep_harness):
    h = bleep_harness
    for name, data in (("call.mp3", b"ID3fake"), ("call.wav", b"RIFF-not-really-a-wav")):
        response = post(h, data, name)
        assert response.status_code == 422 and response.json()["error"]["code"] == "BLEEP_WAV_ONLY"
    assert h.container.transcriber.paths == [] or all(not p.exists() for p in h.container.transcriber.paths)
    assert h.receiver_transport.requests == [] and h.container.receipts.all() == []


def test_without_bleep_no_audio_is_returned(bleep_harness):
    body = bleep_harness.client.post("/api/process-audio", files={"file": ("call.wav", make_wav(), "audio/wav")}).json()
    assert body["bleep"] is None
