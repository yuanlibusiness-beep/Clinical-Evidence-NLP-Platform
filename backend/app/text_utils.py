"""Offset-preserving text utilities.

Everything downstream -- chunking, grounding, the UI highlight -- addresses text
by character offsets into ``Document.raw_text``.  So the rule in this module is:
never mutate the source string.  Normalisation happens on *copies* used for
comparison only; anything that returns a span returns offsets into the original.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

# Candidate sentence boundary: a terminator, optional closing punctuation, then
# whitespace and something that can start a sentence.  Python's ``re`` requires
# fixed-width look-behind, and the abbreviation list is anything but, so the
# abbreviation check is done in code (``_is_false_boundary``) rather than in the
# pattern.  Clearer to read, and easy to extend with a new abbreviation.
_ABBREVIATIONS = frozenset(
    {
        "vs", "e.g", "i.e", "cf", "al", "approx", "no", "nos", "fig", "figs",
        "tab", "eq", "dr", "prof", "mr", "mrs", "ms", "st", "ca", "ref", "refs",
        "sd", "se", "ci", "min", "max", "vol", "ed", "eds", "pp", "p", "n",
        "inc", "ltd", "dept", "univ", "jan", "feb", "mar", "apr", "jun", "jul",
        "aug", "sep", "sept", "oct", "nov", "dec",
    }
)
_SENTENCE_END = re.compile(r"([.!?][\"')\]]*)\s+(?=[A-Z0-9(\[\"'])")
_TRAILING_WORD = re.compile(r"([A-Za-z0-9.]+)\s*$")


def _is_false_boundary(text: str, terminator_index: int) -> bool:
    """Is this full stop part of an abbreviation, initial or decimal number?"""
    if text[terminator_index] != ".":
        return False  # '!' and '?' never abbreviate

    before = text[:terminator_index]
    match = _TRAILING_WORD.search(before)
    if not match:
        return False
    word = match.group(1).lower().rstrip(".")

    if word in _ABBREVIATIONS:
        return True
    # Single-letter initial: "J. Smith", "P. aeruginosa".
    if len(word) == 1 and word.isalpha():
        return True
    # A decimal that lost its digits to the split, e.g. "0.05" -> "0" + ".05".
    if word.isdigit() and terminator_index + 1 < len(text):
        return text[terminator_index + 1].isdigit()
    return False

_WORD = re.compile(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*|[^\sA-Za-z0-9]")
_WS = re.compile(r"\s+")


def count_tokens(text: str) -> int:
    """Model-agnostic token estimate.

    Uses ``tiktoken`` when installed (exact for OpenAI-family tokenisers) and
    falls back to a word/punctuation count scaled by 1.3, which tracks BPE
    length closely enough for chunk sizing.
    """
    try:  # pragma: no cover - optional dependency
        import tiktoken

        return len(tiktoken.get_encoding("cl100k_base").encode(text))
    except Exception:
        return int(len(_WORD.findall(text)) * 1.3) + 1


def normalise_for_match(text: str) -> str:
    """Aggressive normalisation used only for fuzzy quote matching."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("­", "")  # soft hyphen from PDF line-breaking
    text = re.sub(r"[‐-―]", "-", text)  # unicode dashes
    text = re.sub(r"[‘’ʼ]", "'", text)
    text = re.sub(r"[“”]", '"', text)
    text = _WS.sub(" ", text)
    return text.strip().lower()


def split_sentences(text: str, base_offset: int = 0) -> list[tuple[int, int, str]]:
    """Split into ``(char_start, char_end, sentence)`` triples.

    Offsets are absolute: ``base_offset`` is added so callers can pass a slice
    of the document and still get document-level coordinates back.
    """
    if not text.strip():
        return []

    spans: list[tuple[int, int, str]] = []
    cursor = 0
    for match in _SENTENCE_END.finditer(text):
        if _is_false_boundary(text, match.start()):
            continue
        # Keep the terminator (and any closing bracket/quote) with its sentence.
        end = match.end(1)
        piece = text[cursor:end]
        if piece.strip():
            spans.append((base_offset + cursor, base_offset + end, piece))
        cursor = match.end()

    tail = text[cursor:]
    if tail.strip():
        spans.append((base_offset + cursor, base_offset + len(text), tail))
    return spans


def clean_pdf_text(text: str) -> str:
    """Repair the two artefacts that break every PDF pipeline.

    * Words hyphen-split across a line break ("random-\\nised" -> "randomised").
    * Hard-wrapped lines inside a paragraph, which otherwise defeat sentence
      splitting and quote matching.

    Applied *before* the text is stored, so offsets stay consistent afterwards.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    # Join a line into the next one unless the break looks intentional
    # (blank line, list bullet, numbered heading, or a terminated sentence).
    text = re.sub(r"(?<![.!?:;])\n(?!\n)(?![\-•\d]\s)(?=[a-z(])", " ", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def truncate(text: str, limit: int, suffix: str = " ...") -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - len(suffix))].rstrip() + suffix


def unique_preserving(items: Iterable[str]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
