"""Local speech-to-text with faster-whisper (FR-1).

faster-whisper runs on CTranslate2 (no torch) and works on a normal CPU. The model is loaded on
first use; the first load downloads it once (WHISPER_MODEL "base" is about 145 MB) and later
runs work offline. Audio is read from a local temp file and never sent anywhere.

Every word keeps its audio time and its exact character offsets in the transcript text, so a
detected entity span can be mapped back to the audio (needed for bleeping, FR-16).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


class TranscriptionError(Exception):
    """The audio could not be transcribed. Callers must not process or send anything."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code  # AUDIO_TOO_LONG | AUDIO_UNREADABLE | TRANSCRIPTION_UNAVAILABLE | TRANSCRIPTION_FAILED
        self.message = message


@dataclass(frozen=True)
class Word:
    word: str
    start_s: float
    end_s: float
    char_start: int  # exact offsets into Transcript.text
    char_end: int


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str
    duration_s: float
    model: str
    transcription_ms: float
    words: list[Word] = field(default_factory=list)


def join_words(raw: list[tuple[str, float, float]]) -> tuple[str, list[Word]]:
    """Join (word, start, end) into one text with single spaces, recording exact offsets."""
    parts: list[str] = []
    words: list[Word] = []
    cursor = 0
    for text, start, end in raw:
        token = text.strip()
        if not token:
            continue
        if parts:
            parts.append(" ")
            cursor += 1
        parts.append(token)
        words.append(Word(token, round(start, 3), round(end, 3), cursor, cursor + len(token)))
        cursor += len(token)
    return "".join(parts), words


class Transcriber:
    def __init__(self, model_name: str, device: str, compute_type: str, max_seconds: int) -> None:
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.max_seconds = max_seconds
        self._model = None
        self._lock = threading.Lock()
        self.status = "NOT_LOADED"
        self.message = f"Whisper model '{model_name}' loads on first use (the first load downloads it once)."
        self.load_seconds: float | None = None

    def load(self) -> None:
        with self._lock:
            if self._model is not None:
                return
            started = time.perf_counter()
            try:
                from faster_whisper import WhisperModel

                self._model = WhisperModel(self.model_name, device=self.device, compute_type=self.compute_type)
                self.load_seconds = round(time.perf_counter() - started, 2)
                self.status = "READY"
                self.message = f"faster-whisper '{self.model_name}' loaded on {self.device} ({self.compute_type})."
            except Exception as exc:  # noqa: BLE001 - reported as unavailable; audio requests fail closed
                self.status = "UNAVAILABLE"
                self.message = (
                    f"Whisper model '{self.model_name}' could not be loaded ({type(exc).__name__}). "
                    "The first load needs internet access once to download the model."
                )
                logger.error("whisper failed to load", extra={"error_type": type(exc).__name__})
                raise TranscriptionError("TRANSCRIPTION_UNAVAILABLE", self.message) from exc

    def transcribe(self, path: Path, language: str | None = None) -> Transcript:
        self.load()
        started = time.perf_counter()
        try:
            segments, info = self._model.transcribe(str(path), language=language, word_timestamps=True, vad_filter=False)
            if info.duration > self.max_seconds:
                raise TranscriptionError(
                    "AUDIO_TOO_LONG", f"Audio is {info.duration:.0f} s long; the limit is {self.max_seconds} s."
                )
            raw = [(w.word, w.start, w.end) for segment in segments for w in (segment.words or [])]
        except TranscriptionError:
            raise
        except Exception as exc:  # noqa: BLE001 - undecodable or corrupt audio
            logger.error("transcription failed", extra={"error_type": type(exc).__name__})
            raise TranscriptionError("AUDIO_UNREADABLE", "The audio could not be decoded or transcribed.") from exc
        text, words = join_words(raw)
        return Transcript(
            text=text,
            language=info.language,
            duration_s=round(info.duration, 2),
            model=self.model_name,
            transcription_ms=round((time.perf_counter() - started) * 1000, 2),
            words=words,
        )

    def transcribe_array(self, samples, language: str | None = None) -> Transcript:
        """Transcribe one live chunk: float32 mono samples at 16 kHz, in memory (never written to disk).

        Voice-activity filtering skips silence, where Whisper would otherwise invent words.
        """
        self.load()
        started = time.perf_counter()
        try:
            segments, info = self._model.transcribe(
                samples, language=language, word_timestamps=True, vad_filter=True, condition_on_previous_text=False
            )
            raw = [(w.word, w.start, w.end) for segment in segments for w in (segment.words or [])]
        except Exception as exc:  # noqa: BLE001
            logger.error("live chunk transcription failed", extra={"error_type": type(exc).__name__})
            raise TranscriptionError("AUDIO_UNREADABLE", "A live audio chunk could not be transcribed.") from exc
        text, words = join_words(raw)
        return Transcript(
            text=text, language=info.language, duration_s=round(info.duration, 2), model=self.model_name,
            transcription_ms=round((time.perf_counter() - started) * 1000, 2), words=words,
        )
