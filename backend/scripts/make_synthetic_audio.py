"""Create short synthetic call recordings for tests and demos (FR-1).

    python scripts/make_synthetic_audio.py

Uses the offline Windows speech engine (SAPI) through pyttsx3: nothing is sent anywhere. Every
name and number is invented. Output is 16 kHz mono 16-bit WAV in tests/fixtures/audio/, small
enough to commit. On macOS or Linux pyttsx3 uses NSSpeechSynthesizer or eSpeak instead; the
voices differ, so transcripts may differ slightly.
"""

from __future__ import annotations

import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

BACKEND = Path(__file__).resolve().parent.parent
OUT_DIR = BACKEND / "tests" / "fixtures" / "audio"
TARGET_RATE = 16000

CLIPS = {
    # The spoken patient ID exercises the spoken-number normalizer after transcription.
    "appointment.wav": "Hello, my name is John Smith. My patient ID is P nine four eight two nine one three.",
    "contact.wav": "Please call me back on nine eight four five zero, one two three four five.",
    "clean.wav": "Hi, what are your support hours on Saturday?",
}


def to_16k_mono(source: Path, target: Path) -> None:
    with wave.open(str(source), "rb") as wav:
        rate, channels, width = wav.getframerate(), wav.getnchannels(), wav.getsampwidth()
        frames = wav.readframes(wav.getnframes())
    if width != 2:
        raise SystemExit(f"Expected 16-bit audio from the speech engine, got {8 * width}-bit.")
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float64)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    # Trim leading and trailing silence, keeping 0.15 s of padding, so the clips stay small.
    loud = np.flatnonzero(np.abs(samples) > 300)
    if loud.size:
        pad = int(0.15 * rate)
        samples = samples[max(0, loud[0] - pad) : loud[-1] + pad]
    count = int(len(samples) * TARGET_RATE / rate)
    resampled = np.interp(np.linspace(0, len(samples) - 1, count), np.arange(len(samples)), samples)
    with wave.open(str(target), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(TARGET_RATE)
        out.writeframes(np.clip(resampled, -32768, 32767).astype("<i2").tobytes())


def main() -> None:
    try:
        import pyttsx3
    except ImportError:
        sys.exit("pyttsx3 is not installed: pip install pyttsx3")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    engine = pyttsx3.init()
    engine.setProperty("rate", 175)  # words per minute; keeps every clip under 200 KB
    with tempfile.TemporaryDirectory() as tmp:
        raw = {name: Path(tmp) / name for name in CLIPS}
        for name, text in CLIPS.items():
            engine.save_to_file(text, str(raw[name]))
        engine.runAndWait()
        for name, path in raw.items():
            to_16k_mono(path, OUT_DIR / name)
            size = (OUT_DIR / name).stat().st_size
            print(f"Wrote tests/fixtures/audio/{name} ({size // 1024} KB): {CLIPS[name]}")


if __name__ == "__main__":
    main()
