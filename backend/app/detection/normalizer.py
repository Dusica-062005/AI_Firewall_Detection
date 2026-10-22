"""Spoken-number normalizer (FR-15).

Callers say identifiers out loud: "patient ID P four eight two nine one three", "mera number
nau aath saat ...", or split them across sentences: "My patient ID is P48. Sorry, then 2913."
Detection runs on a normalized copy of the text where those become "P482913". Every
normalized character remembers the original characters it came from, so a detected span can
be mapped back and redacted in the ORIGINAL text.

A merged span maps back to everything between its first and last source character, including
filler words between split parts. Redacting that whole range is intentional (fail closed).
"""

from __future__ import annotations

from dataclasses import dataclass

import regex

ENGLISH_DIGITS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}
HINDI_DIGITS = {
    "shunya": "0", "ek": "1", "do": "2", "teen": "3", "char": "4", "chaar": "4",
    "paanch": "5", "panch": "5", "chhe": "6", "che": "6", "saat": "7", "aath": "8", "nau": "9",
}
# Also ordinary words ("do" is a verb): converted only inside a run of at least 3 digit words.
AMBIGUOUS = {"ek", "do"}
AMBIGUOUS_MIN_RUN = 3
MULTIPLIERS = {"double": 2, "triple": 3}
DIGIT_WORDS = {**ENGLISH_DIGITS, **HINDI_DIGITS}

# Devanagari, Kannada and Tamil digits -> ASCII. One character in, one character out.
NATIVE_DIGITS = str.maketrans(
    {chr(base + i): str(i) for base in (0x0966, 0x0CE6, 0x0BE6) for i in range(10)}
)

ID_CUES = {"id", "number", "patient", "mrn", "aadhaar", "phone", "mobile"}
CUE_WINDOW_WORDS = 6
SPLIT_MAX_GAP_WORDS = 8
# A first part shorter than this cannot be an identifier on its own, so a following digit
# group is treated as its continuation. Longer first parts are left alone.
SPLIT_MAX_FIRST_DIGITS = 3
SPLIT_MAX_TOTAL_DIGITS = 12

_TOKEN = regex.compile(r"[^\W\d_]+|\d+")
_WORD = regex.compile(r"\w+")
_RUN_GAP = regex.compile(r"[\s,\-]+")
_LETTER_GAP = regex.compile(r"\s+")
_GROUP = regex.compile(r"(?<![A-Za-z0-9])([A-Za-z]{0,3})(\d+)(?![A-Za-z0-9])")
_SENTENCE_END = regex.compile(r"[.!?।]")  # । is the Devanagari full stop


@dataclass(frozen=True)
class Normalized:
    text: str  # normalized text that detection runs on
    starts: list[int]  # starts[i] = original index of normalized char i
    ends: list[int]  # ends[i] = original end index (exclusive) of normalized char i
    changed: bool


def map_span(n: Normalized, start: int, end: int) -> tuple[int, int]:
    """Normalized span -> original span: (starts[start], ends[end - 1])."""
    if end <= start:
        raise ValueError("Span must not be empty.")
    return n.starts[start], n.ends[end - 1]


def normalize_numbers(text: str) -> Normalized:
    # Each piece is (char, original start, original end).
    chars = [(c, i, i + 1) for i, c in enumerate(text.translate(NATIVE_DIGITS))]
    chars = _convert_digit_words(chars)
    chars = _join_split_ids(chars)
    out = "".join(c for c, _, _ in chars)
    return Normalized(
        text=out,
        starts=[s for _, s, _ in chars],
        ends=[e for _, _, e in chars],
        changed=out != text,
    )


def _has_cue_before(text: str, position: int) -> bool:
    words = _WORD.findall(text[:position])[-CUE_WINDOW_WORDS:]
    return any(w.lower() in ID_CUES for w in words)


def _convert_digit_words(chars: list[tuple[str, int, int]]) -> list[tuple[str, int, int]]:
    text = "".join(c for c, _, _ in chars)
    tokens = [(m.start(), m.end(), m.group().lower()) for m in _TOKEN.finditer(text)]

    # Maximal runs of candidate words separated only by spaces, commas or hyphens.
    runs: list[list[int]] = []
    current: list[int] = []
    for index, (start, _, word) in enumerate(tokens):
        candidate = word in DIGIT_WORDS or word in MULTIPLIERS or word == "oh"
        joined = bool(current) and _RUN_GAP.fullmatch(text[tokens[current[-1]][1] : start] or "")
        if candidate and (not current or joined):
            current.append(index)
            continue
        if current:
            runs.append(current)
        current = [index] if candidate else []
    if current:
        runs.append(current)

    replacements: list[tuple[int, int, list[tuple[str, int, int]]]] = []
    for run in runs:
        for part in _split_ambiguous(run, tokens):
            converted = _convert_run(part, tokens, chars)
            if converted is None:
                continue
            start, end, digits = converted
            replacements.append((start, end, digits))

    if not replacements:
        return chars
    result: list[tuple[str, int, int]] = []
    cursor = 0
    for start, end, digits in replacements:
        result.extend(chars[cursor:start])
        result.extend(digits)
        cursor = end
    result.extend(chars[cursor:])
    return result


def _split_ambiguous(run: list[int], tokens: list[tuple[int, int, str]]) -> list[list[int]]:
    """'ek' and 'do' count as digits only in a run of at least three digit words."""
    if len(run) >= AMBIGUOUS_MIN_RUN or not any(tokens[i][2] in AMBIGUOUS for i in run):
        return [run]
    parts: list[list[int]] = [[]]
    for i in run:
        if tokens[i][2] in AMBIGUOUS:
            parts.append([])
        else:
            parts[-1].append(i)
    return [p for p in parts if p]


def _convert_run(
    run: list[int], tokens: list[tuple[int, int, str]], chars: list[tuple[str, int, int]]
) -> tuple[int, int, list[tuple[str, int, int]]] | None:
    """Return (start, end, digit pieces) in ``chars`` positions, or None to leave the run alone."""
    run = list(run)
    # "oh" is a digit only between digits; a multiplier needs a digit after it.
    while run and (tokens[run[0]][2] == "oh"):
        run.pop(0)
    while run and (tokens[run[-1]][2] in ("oh", *MULTIPLIERS)):
        run.pop()
    if not run:
        return None

    digits: list[tuple[str, int, int]] = []
    pending: tuple[int, int] | None = None  # (count, start of the multiplier word)
    for i in run:
        start, end, word = tokens[i]
        if word in MULTIPLIERS:
            pending = (MULTIPLIERS[word], chars[start][1])
            continue
        digit = "0" if word == "oh" else DIGIT_WORDS[word]
        src_start, src_end = chars[start][1], chars[end - 1][2]
        if pending:
            count, multiplier_start = pending
            digits.extend((digit, multiplier_start, src_end) for _ in range(count))
            pending = None
        else:
            digits.append((digit, src_start, src_end))
    if len(digits) < 2:
        return None  # a lone "one" in a sentence is not an identifier

    run_start, run_end = tokens[run[0]][0], tokens[run[-1]][1]
    text = "".join(c for c, _, _ in chars)
    # A single letter right before the run joins it when an ID cue precedes it: "P four eight".
    before = text[:run_start]
    letter = regex.search(r"(?<![\w])([A-Za-z])(\s+)$", before)
    if letter and _has_cue_before(text, letter.start(1)):
        letter_index = letter.start(1)
        prefix = chars[letter_index]
        return letter_index, run_end, [prefix, *digits]
    return run_start, run_end, digits


def _join_split_ids(chars: list[tuple[str, int, int]]) -> list[tuple[str, int, int]]:
    """Join "P48. Sorry, then 2913" into "P482913" when an ID cue precedes the first part."""
    text = "".join(c for c, _, _ in chars)
    groups = list(_GROUP.finditer(text))
    drops: list[tuple[int, int]] = []  # gaps (in chars positions) to remove
    used: set[int] = set()
    for i, first in enumerate(groups[:-1]):
        if i in used or len(first.group(2)) > SPLIT_MAX_FIRST_DIGITS:
            continue
        if not _has_cue_before(text, first.start()):
            continue
        second = groups[i + 1]
        if second.group(1):  # the continuation must be digits only
            continue
        gap = text[first.end() : second.start()]
        if _RUN_GAP.fullmatch(gap):
            continue  # "+91 98765" is formatting, not a split; the recognizers handle it as is
        if len(_WORD.findall(gap)) > SPLIT_MAX_GAP_WORDS or len(_SENTENCE_END.findall(gap)) > 1:
            continue
        if len(first.group(2)) + len(second.group(2)) > SPLIT_MAX_TOTAL_DIGITS:
            continue
        drops.append((first.end(), second.start()))
        used.update({i, i + 1})
    if not drops:
        return chars
    result: list[tuple[str, int, int]] = []
    cursor = 0
    for start, end in drops:
        result.extend(chars[cursor:start])
        cursor = end
    result.extend(chars[cursor:])
    return result
