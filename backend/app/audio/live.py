"""Live redacted captions (real-time privacy, post-call intelligence).

During a call, audio arrives in small pieces (16 kHz mono, 16-bit PCM). Every ``chunk_seconds`` of
new audio is transcribed locally, then the last few chunks are checked together, so an identifier
said across a chunk boundary ("P nine four ... eight two nine") is still caught. Captions are
shown with every protected value replaced by a token such as [PERSON_1].

Rules:
- Captions are a local preview for the agent. They are never sent to any cloud or stored.
- If protection cannot run for a chunk, its caption is withheld (fail closed).
- A value, once protected, stays protected in every later version of a caption.
- When the call ends, the full recording goes through the normal pipeline (summary, router,
  receipt, bleeping). That pass is authoritative; captions can differ from it.
"""

from __future__ import annotations

import io
import logging
import wave
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import regex

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
BYTES_PER_SECOND = SAMPLE_RATE * 2  # 16-bit mono
SILENCE_RMS = 200  # int16 RMS below this is treated as silence and not transcribed
WITHHELD = "[caption withheld: protection unavailable]"

# protector(text) -> [(start, end, category)] spans of ``text`` to hide. May raise: the caller
# then withholds the caption.
Protector = Callable[[str], list[tuple[int, int, str]]]


class LiveLimitError(Exception):
    """The live call exceeded the configured audio length."""


@dataclass
class CaptionUpdate:
    index: int
    text: str
    withheld: bool = False

    def as_message(self) -> dict:
        return {"type": "caption", "index": self.index, "text": self.text, "withheld": self.withheld}


class LiveSession:
    def __init__(self, transcribe_array, protector: Protector, chunk_seconds: float, window_chunks: int,
                 max_seconds: float) -> None:
        self._transcribe = transcribe_array
        self._protect = protector
        self._chunk_bytes = int(chunk_seconds * BYTES_PER_SECOND) // 2 * 2
        self._window = max(1, window_chunks)
        self._max_bytes = int(max_seconds * BYTES_PER_SECOND)
        self._audio = bytearray()  # the whole call, in memory only
        self._done = 0  # bytes already handed to transcription
        self._lines: list[str] = []  # raw caption text per chunk (never sent anywhere)
        self._starts: list[int] = []  # offset of each line in the joined text
        self._withheld: set[int] = set()
        self._spans: list[tuple[int, int, str]] = []  # protected spans in joined-text offsets
        self._rendered: list[str] = []
        self._tokens: dict[tuple[str, str], str] = {}
        self._counts: dict[str, int] = {}

    # ---- Audio ---------------------------------------------------------------------------------

    @property
    def seconds(self) -> float:
        return round(len(self._audio) / BYTES_PER_SECOND, 2)

    def add_audio(self, data: bytes) -> None:
        if len(self._audio) + len(data) > self._max_bytes:
            raise LiveLimitError(f"The call exceeds the {self._max_bytes // BYTES_PER_SECOND} s limit.")
        self._audio.extend(data[: len(data) // 2 * 2])

    def has_chunk(self) -> bool:
        return len(self._audio) - self._done >= self._chunk_bytes

    def wav_bytes(self) -> bytes:
        out = io.BytesIO()
        with wave.open(out, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(SAMPLE_RATE)
            wav.writeframes(bytes(self._audio))
        return out.getvalue()

    # ---- Captions ------------------------------------------------------------------------------

    def process_next(self, final: bool = False) -> list[CaptionUpdate]:
        """Transcribe the next chunk (or, when ``final``, whatever is left) and return caption updates."""
        end = len(self._audio) if final else self._done + self._chunk_bytes
        piece = bytes(self._audio[self._done:end])
        self._done = end
        if len(piece) < BYTES_PER_SECOND // 2:  # under half a second: nothing worth transcribing
            return []
        samples = np.frombuffer(piece, dtype="<i2").astype(np.float32)
        if float(np.sqrt(np.mean(samples**2))) < SILENCE_RMS:
            return []
        text = self._transcribe(samples / 32768.0).text.strip()
        if not text:
            return []
        self._add_line(text)
        return self._refresh()

    def _add_line(self, text: str) -> None:
        joined = self.text
        self._starts.append(len(joined) + (1 if joined else 0))
        self._lines.append(text)
        self._rendered.append("")

    @property
    def text(self) -> str:
        return " ".join(self._lines)

    def _refresh(self) -> list[CaptionUpdate]:
        first = max(0, len(self._lines) - self._window)
        window_start = self._starts[first]
        try:
            found = self._protect(self.text[window_start:])
            for start, end, category in found:
                self._add_span(window_start + start, window_start + end, category)
        except Exception as exc:  # noqa: BLE001 - fail closed: the new caption is withheld
            logger.error("live caption protection failed", extra={"error_type": type(exc).__name__})
            self._withheld.add(len(self._lines) - 1)
        updates = []
        for index in range(first, len(self._lines)):
            rendered = WITHHELD if index in self._withheld else self._render(index)
            if rendered != self._rendered[index]:
                self._rendered[index] = rendered
                updates.append(CaptionUpdate(index, rendered, index in self._withheld))
        return updates

    def _add_span(self, start: int, end: int, category: str) -> None:
        """Keep the union of protected spans; a value once protected stays protected."""
        merged: list[tuple[int, int, str]] = []
        for s, e, c in sorted([*self._spans, (start, end, category)]):
            if merged and s < merged[-1][1]:
                prev = merged[-1]
                merged[-1] = (prev[0], max(prev[1], e), prev[2])
            else:
                merged.append((s, e, c))
        self._spans = merged

    def _render(self, index: int) -> str:
        line_start = self._starts[index]
        line_end = line_start + len(self._lines[index])
        joined = self.text
        out, cursor = [], line_start
        for start, end, category in self._spans:
            if end <= line_start or start >= line_end:
                continue
            out.append(joined[cursor:max(start, line_start)])
            # The token appears where the value starts; its continuation on the next line is hidden.
            if start >= line_start:
                out.append(self._token(category, joined[start:end]))
            cursor = min(end, line_end)
        out.append(joined[cursor:line_end])
        return regex.sub(r"\s{2,}", " ", "".join(out)).strip()

    def _token(self, category: str, value: str) -> str:
        key = (category, regex.sub(r"\W+", "", value.lower()))
        if key not in self._tokens:
            self._counts[category] = self._counts.get(category, 0) + 1
            self._tokens[key] = f"[{category}_{self._counts[category]}]"
        return self._tokens[key]
