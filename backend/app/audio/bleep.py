"""Audio bleeping (FR-16): replace protected words in the source audio with a tone or silence.

Each protected entity's character span is mapped to the transcript words it overlaps (their
char_start/char_end), and that time range, padded by PAD_MS on each side, is replaced by a
1 kHz tone at -20 dBFS or by silence. Every other sample is left byte-identical.

WAV (16-bit PCM) only, processed in memory: the bleeped audio is never written to disk.
"""

from __future__ import annotations

import io
import math
import wave
from collections.abc import Iterable

import numpy as np

from app.audio.transcriber import Word

PAD_MS = 50
TONE_HZ = 1000
TONE_DBFS = -20.0


class BleepError(Exception):
    """The audio cannot be bleeped (not 16-bit PCM WAV)."""


def check_wav(data: bytes) -> None:
    """Raise BleepError unless ``data`` is a 16-bit PCM WAV. Called before anything is processed."""
    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            params = wav.getparams()
    except (wave.Error, EOFError) as exc:
        raise BleepError("The audio is not a readable WAV file.") from exc
    if params.sampwidth != 2 or params.comptype != "NONE":
        raise BleepError("Only 16-bit PCM WAV audio can be bleeped.")


def bleep_ranges(words: list[Word], spans: Iterable[tuple[int, int]], duration_s: float,
                 pad_ms: int = PAD_MS) -> list[tuple[float, float]]:
    """Time ranges (seconds) covering every word that overlaps a protected character span, merged."""
    pad = pad_ms / 1000
    ranges = []
    for start, end in spans:
        hit = [w for w in words if w.char_start < end and start < w.char_end]
        if hit:
            ranges.append((max(0.0, min(w.start_s for w in hit) - pad), min(duration_s, max(w.end_s for w in hit) + pad)))
    merged: list[tuple[float, float]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return [(round(a, 3), round(b, 3)) for a, b in merged]


def bleep_wav(data: bytes, ranges: list[tuple[float, float]], style: str = "tone") -> bytes:
    check_wav(data)
    with wave.open(io.BytesIO(data), "rb") as wav:
        params = wav.getparams()
        frames = wav.readframes(params.nframes)

    samples = np.frombuffer(frames, dtype="<i2").reshape(-1, params.nchannels).copy()
    rate = params.framerate
    amplitude = 32767 * 10 ** (TONE_DBFS / 20)
    for start_s, end_s in ranges:
        first, last = int(start_s * rate), min(len(samples), int(math.ceil(end_s * rate)))
        if last <= first:
            continue
        if style == "silence":
            replacement = np.zeros(last - first)
        else:
            t = np.arange(first, last) / rate
            replacement = amplitude * np.sin(2 * np.pi * TONE_HZ * t)
        samples[first:last, :] = np.round(replacement).astype("<i2")[:, None]

    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(params.nchannels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(samples.astype("<i2").tobytes())
    return out.getvalue()
