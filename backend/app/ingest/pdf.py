"""PDF text extraction with page provenance.

PyMuPDF is the extractor; the value this module adds is the ``page_map``.  Every
page contributes a ``(char_start, char_end, page_no)`` range into the single
concatenated document string, so a span found later can be reported as "page 7"
without re-parsing the file.

Two-column layouts are handled by asking PyMuPDF for text blocks and sorting
them into reading order, which stops a two-column paper from interleaving the
left and right columns line by line.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field

from app.text_utils import clean_pdf_text

logger = logging.getLogger(__name__)

MAX_PDF_BYTES = 40 * 1024 * 1024


class PdfParseError(RuntimeError):
    pass


@dataclass
class ParsedPdf:
    text: str
    page_count: int
    page_map: list[tuple[int, int, int]] = field(default_factory=list)
    title: str | None = None
    doi: str | None = None
    year: int | None = None


_DOI = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b")
_YEAR = re.compile(r"\b(19[89]\d|20[0-4]\d)\b")


def _blocks_in_reading_order(page) -> str:
    """Sort text blocks top-to-bottom within left-then-right column halves."""
    blocks = [b for b in page.get_text("blocks") if len(b) >= 5 and str(b[4]).strip()]
    if not blocks:
        return ""

    page_width = page.rect.width or 1.0
    midpoint = page_width / 2.0
    # A block belongs to the right column only if it starts past the midpoint
    # and does not span the full width (which would be a figure caption/header).
    def sort_key(block):
        x0, y0, x1, _y1 = block[0], block[1], block[2], block[3]
        spans_full_width = (x1 - x0) > page_width * 0.62
        column = 0 if (spans_full_width or x0 < midpoint) else 1
        return (column, round(y0, 1), round(x0, 1))

    ordered = sorted(blocks, key=sort_key)
    return "\n".join(str(block[4]).strip() for block in ordered)


def parse_pdf(data: bytes, *, filename: str = "document.pdf") -> ParsedPdf:
    if not data:
        raise PdfParseError("Empty file.")
    if len(data) > MAX_PDF_BYTES:
        raise PdfParseError(
            f"PDF is {len(data) / 1e6:.1f} MB; the limit is {MAX_PDF_BYTES / 1e6:.0f} MB."
        )
    if not data[:5].startswith(b"%PDF"):
        raise PdfParseError("File does not look like a PDF (missing %PDF header).")

    try:
        # PyMuPDF >= 1.24 prefers the `pymupdf` name; `fitz` still works but
        # warns, so try the modern import first.
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz  # type: ignore[no-redef]
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise PdfParseError("PyMuPDF is not installed.") from exc

    try:
        document = fitz.open(stream=io.BytesIO(data), filetype="pdf")
    except Exception as exc:
        raise PdfParseError(f"Could not open PDF: {exc}") from exc

    if document.needs_pass:
        document.close()
        raise PdfParseError("PDF is password protected.")

    pieces: list[str] = []
    page_map: list[tuple[int, int, int]] = []
    cursor = 0

    try:
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            page_text = _blocks_in_reading_order(page)
            page_text = clean_pdf_text(page_text)
            if page_index:
                pieces.append("\n\n")
                cursor += 2
            start = cursor
            pieces.append(page_text)
            cursor += len(page_text)
            page_map.append((start, cursor, page_index + 1))

        metadata = document.metadata or {}
        page_count = document.page_count
    finally:
        document.close()

    text = "".join(pieces).strip()
    if len(text) < 200:
        raise PdfParseError(
            "Almost no selectable text found. This looks like a scanned PDF; "
            "run OCR (e.g. ocrmypdf) before uploading."
        )

    doi_match = _DOI.search(text[:6000])
    title = (metadata.get("title") or "").strip() or _guess_title(text) or filename
    year = None
    year_match = _YEAR.search(text[:3000])
    if year_match:
        year = int(year_match.group(1))

    return ParsedPdf(
        text=text,
        page_count=page_count,
        page_map=page_map,
        title=title[:500],
        doi=doi_match.group(0) if doi_match else None,
        year=year,
    )


def _guess_title(text: str) -> str | None:
    """First plausible title-like line in the front matter."""
    for line in text.split("\n")[:15]:
        candidate = line.strip()
        if not (25 <= len(candidate) <= 300):
            continue
        if candidate.lower().startswith(("doi", "http", "www", "downloaded", "©")):
            continue
        letters = sum(character.isalpha() for character in candidate)
        if letters < len(candidate) * 0.6:
            continue
        return candidate
    return None
