"""Citation-level grounding: does this quote actually exist in the paper?

This is the check that turns "the model said so" into "the paper says so, at
character 14,203, page 6, in Results".  Nothing reaches the user ungrounded.

The hard part is that a model's quote is *nearly* verbatim.  It normalises a
unicode dash, drops a soft hyphen the PDF inserted mid-word, collapses a double
space, or re-cases a sentence start.  A strict ``in`` test rejects all of those
and would abstain on correct extractions; a loose fuzzy match accepts
paraphrases and defeats the point.  So grounding runs in three tiers:

1. **Exact** substring of the raw text -> score 1.0.
2. **Normalised exact**: match against a whitespace-collapsed, unicode-folded,
   lower-cased projection of the document that carries a character-level index
   back to the original offsets -> score 0.98.  This is where most real quotes
   land.
3. **Fuzzy**: ``SequenceMatcher`` against candidate sentences, accepted only
   above ``GROUNDING_MIN_SIMILARITY`` (default 0.82), and the span returned is
   the *matched source sentence*, never the model's wording.

Anything that fails all three is dropped and recorded as an abstention with
reason ``ungrounded``.  That is the mechanism behind the "hallucination rate"
the evaluator reports.
"""

from __future__ import annotations

import logging
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.config import settings
from app.schemas import RetrievedChunk
from app.text_utils import split_sentences

logger = logging.getLogger(__name__)

_DASHES = "‐‑‒–—―"
_QUOTES_SINGLE = "‘’ʼ`"
_QUOTES_DOUBLE = "“”„"


@dataclass
class GroundedSpan:
    quote: str          # the source text, not the model's paraphrase
    char_start: int
    char_end: int
    match_score: float
    method: str         # exact | normalised | fuzzy


class NormalisedIndex:
    """A folded projection of a document that can map offsets back.

    Built once per document per extraction; ``O(len(text))`` in time and space.
    """

    __slots__ = ("original", "normalised", "offsets")

    def __init__(self, text: str) -> None:
        self.original = text
        chars: list[str] = []
        offsets: list[int] = []
        previous_space = True  # collapses leading whitespace

        for index, raw_char in enumerate(text):
            char = unicodedata.normalize("NFKC", raw_char)
            if char == "­":  # soft hyphen
                continue
            if char in _DASHES:
                char = "-"
            elif char in _QUOTES_SINGLE:
                char = "'"
            elif char in _QUOTES_DOUBLE:
                char = '"'

            if char.isspace():
                if previous_space:
                    continue
                chars.append(" ")
                offsets.append(index)
                previous_space = True
                continue

            previous_space = False
            folded = char.lower()
            # NFKC can expand one char into several (e.g. ﬁ -> fi); every
            # produced char maps back to the same original index.
            for piece in folded:
                chars.append(piece)
                offsets.append(index)

        self.normalised = "".join(chars)
        self.offsets = offsets

    def to_original_span(self, start: int, end: int) -> tuple[int, int]:
        if not self.offsets:
            return 0, 0
        start = max(0, min(start, len(self.offsets) - 1))
        end = max(start + 1, min(end, len(self.offsets)))
        original_start = self.offsets[start]
        original_end = (
            self.offsets[end - 1] + 1 if end - 1 < len(self.offsets) else len(self.original)
        )
        return original_start, original_end


def normalise_query(text: str) -> str:
    """Fold a model-produced quote the same way the index folds the document."""
    chars: list[str] = []
    previous_space = True
    for raw_char in text:
        char = unicodedata.normalize("NFKC", raw_char)
        if char == "­":
            continue
        if char in _DASHES:
            char = "-"
        elif char in _QUOTES_SINGLE:
            char = "'"
        elif char in _QUOTES_DOUBLE:
            char = '"'
        if char.isspace():
            if previous_space:
                continue
            chars.append(" ")
            previous_space = True
            continue
        previous_space = False
        chars.extend(char.lower())
    return "".join(chars).strip()


def ground_quote(
    quote: str,
    index: NormalisedIndex,
    *,
    candidates: Sequence[RetrievedChunk] | None = None,
    min_similarity: float | None = None,
) -> GroundedSpan | None:
    """Locate ``quote`` in the source document, or return ``None``."""
    if not quote or len(quote.strip()) < 12:
        return None

    threshold = (
        settings.grounding_min_similarity if min_similarity is None else min_similarity
    )

    # --- tier 1: exact -----------------------------------------------------
    position = index.original.find(quote)
    if position != -1:
        return GroundedSpan(
            quote=quote,
            char_start=position,
            char_end=position + len(quote),
            match_score=1.0,
            method="exact",
        )

    # --- tier 2: normalised exact -----------------------------------------
    folded = normalise_query(quote)
    if len(folded) < 12:
        return None

    position = index.normalised.find(folded)
    if position != -1:
        start, end = index.to_original_span(position, position + len(folded))
        return GroundedSpan(
            quote=index.original[start:end],
            char_start=start,
            char_end=end,
            match_score=0.98,
            method="normalised",
        )

    # --- tier 3: fuzzy over candidate sentences ---------------------------
    sentences: list[tuple[int, int, str]] = []
    if candidates:
        for chunk in candidates:
            sentences.extend(split_sentences(chunk.text, base_offset=chunk.char_start))
    else:
        sentences.extend(split_sentences(index.original))

    best: GroundedSpan | None = None
    matcher = SequenceMatcher(autojunk=False)
    matcher.set_seq2(folded)

    for start, end, sentence in sentences:
        candidate = normalise_query(sentence)
        if not candidate:
            continue
        # Cheap length gate: a 3x length mismatch cannot clear 0.82.
        ratio = len(candidate) / len(folded)
        if ratio < 0.45 or ratio > 2.6:
            continue
        matcher.set_seq1(candidate)
        if matcher.real_quick_ratio() < threshold or matcher.quick_ratio() < threshold:
            continue
        score = matcher.ratio()
        if score >= threshold and (best is None or score > best.match_score):
            best = GroundedSpan(
                quote=sentence.strip(),
                char_start=start,
                char_end=end,
                match_score=round(score, 4),
                method="fuzzy",
            )

    return best


def locate_chunk(
    char_start: int, chunks: Sequence[RetrievedChunk]
) -> RetrievedChunk | None:
    """Which retrieved chunk contains this offset (for page + section labels)."""
    for chunk in chunks:
        if chunk.char_start <= char_start < chunk.char_end:
            return chunk
    return None
