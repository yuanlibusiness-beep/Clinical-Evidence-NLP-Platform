"""Section-aware, sentence-aligned chunking.

Design decisions and why:

* **Chunks never cross a section boundary.**  A window that straddles the end of
  Methods and the start of Results produces evidence that cannot be attributed
  to either -- exactly the kind of span that later fails grounding.
* **Chunks break on sentence boundaries.**  A quote that starts mid-sentence
  cannot be verified verbatim against the source, and reads as broken in the UI.
* **Windows overlap.**  A finding and its statistics are often split across two
  sentences; overlap keeps them retrievable together.
* **A single over-long sentence is emitted whole** rather than cut, because
  correctness of the span matters more than uniform chunk size.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.config import settings
from app.ingest.sectioniser import DetectedSection
from app.text_utils import count_tokens, split_sentences


@dataclass
class BuiltChunk:
    order_index: int
    section_name: str
    section_index: int
    text: str
    token_count: int
    char_start: int
    char_end: int
    page_no: int | None = None


PageMap = Sequence[tuple[int, int, int]]  # (char_start, char_end, page_no)


def _page_for(offset: int, page_map: PageMap | None) -> int | None:
    if not page_map:
        return None
    for start, end, page_no in page_map:
        if start <= offset < end:
            return page_no
    return page_map[-1][2] if page_map else None


def _build_chunk(
    window: list[tuple[int, int, str]],
    *,
    section: DetectedSection,
    section_index: int,
    order_index: int,
    page_map: PageMap | None,
) -> BuiltChunk | None:
    """Turn a window of sentences into a chunk, or ``None`` if it is empty.

    The chunk text is sliced out of the *source* rather than re-joined from the
    sentences, so ``raw_text[char_start:char_end] == chunk.text`` holds exactly.
    Grounding depends on that identity: a quote taken from a chunk has to be
    findable, character for character, in the document.
    """
    if not window:
        return None

    start = window[0][0]
    end = window[-1][1]
    raw = section.text[start - section.char_start : end - section.char_start]

    leading = len(raw) - len(raw.lstrip())
    trailing = len(raw) - len(raw.rstrip())
    start += leading
    end -= trailing
    text = raw.strip()
    if not text:
        return None

    return BuiltChunk(
        order_index=order_index,
        section_name=section.name,
        section_index=section_index,
        text=text,
        token_count=count_tokens(text),
        char_start=start,
        char_end=end,
        page_no=_page_for(start, page_map),
    )


def chunk_sections(
    sections: list[DetectedSection],
    *,
    page_map: PageMap | None = None,
    target_tokens: int | None = None,
    overlap_tokens: int | None = None,
) -> list[BuiltChunk]:
    target = target_tokens or settings.chunk_target_tokens
    overlap = overlap_tokens or settings.chunk_overlap_tokens
    if overlap >= target:
        raise ValueError("chunk overlap must be smaller than the target size")

    chunks: list[BuiltChunk] = []
    order = 0

    for section_index, section in enumerate(sections):
        # References add noise and never support a clinical claim.
        if section.name == "references":
            continue

        sentences = split_sentences(section.text, base_offset=section.char_start)
        if not sentences:
            continue

        window: list[tuple[int, int, str]] = []
        window_tokens = 0

        def flush(
            current: list[tuple[int, int, str]],
            *,
            # Bound as defaults, not captured: a closure over the loop variables
            # would read whatever section the loop had reached by call time.
            bound_section: DetectedSection = section,
            bound_index: int = section_index,
        ) -> None:
            """Emit ``current`` as one chunk and advance the running order."""
            nonlocal order
            built = _build_chunk(
                current,
                section=bound_section,
                section_index=bound_index,
                order_index=order,
                page_map=page_map,
            )
            if built is not None:
                chunks.append(built)
                order += 1

        for sentence in sentences:
            sentence_tokens = count_tokens(sentence[2])

            # A single sentence longer than the target is emitted whole: a
            # truncated sentence cannot be quoted verbatim later.
            if sentence_tokens >= target:
                flush(window)
                flush([sentence])
                window, window_tokens = [], 0
                continue

            if window_tokens + sentence_tokens > target and window:
                flush(window)
                # Carry the tail of the window forward as overlap.
                carried: list[tuple[int, int, str]] = []
                carried_tokens = 0
                for previous in reversed(window):
                    previous_tokens = count_tokens(previous[2])
                    if carried_tokens + previous_tokens > overlap:
                        break
                    carried.insert(0, previous)
                    carried_tokens += previous_tokens
                window, window_tokens = carried, carried_tokens

            window.append(sentence)
            window_tokens += sentence_tokens

        flush(window)
        window, window_tokens = [], 0

    return chunks
