"""PDF text extraction with page provenance.

PyMuPDF is the extractor; the value this module adds is the ``page_map``.  Every
page contributes a ``(char_start, char_end, page_no)`` range into the single
concatenated document string, so a span found later can be reported as "page 7"
without re-parsing the file.

Two-column layouts are handled by asking PyMuPDF for text blocks and sorting
them into reading order, which stops a two-column paper from interleaving the
left and right columns line by line.

Three kinds of page furniture are removed before the text is stored, because
every one of them surfaced as an extraction quote on the first real papers:

* running headers/footers ("n engl j med 383;8 nejm.org August 20, 2020") --
  any line repeated on a third or more of the pages once digits are ignored;
* figure panels and at-risk tables, which flatten into runs of bare numbers
  that nonetheless contain "Rate ratio, 0.83 (95% CI ...)" labels;
* journal mastheads, which were being reported as the paper's title.
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
#: Years that appear in a date or a publication notice.  "Coronavirus disease
#: 2019" is the reason the bare first-year-in-the-text rule is a fallback only.
_DATED_YEAR = re.compile(
    r"(?:\b(?:published|accepted|received|copyright|epub|revised)\b[^\n]{0,60}?|©\s*|"
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+"
    r"(?:\d{1,2},?\s+)?)"
    r"(19[89]\d|20[0-4]\d)\b",
    re.IGNORECASE,
)
_NOT_A_PUBLICATION_YEAR = re.compile(
    r"(?:disease|covid|ncov|sars-cov)[\s-]*$", re.IGNORECASE
)

#: Mastheads and article-type banners that sit above the real title.  Compared
#: with all whitespace removed, because NEJM's letter-spaced masthead extracts
#: as "The new engl and jour nal of medicine".
_MASTHEADS = (
    "thenewenglandjournalofmedicine", "newenglandjournalofmedicine", "nengljmed",
    "thelancet", "jama", "jamanetworkopen", "bmj", "thebmj", "bmjopen", "plosmedicine",
    "plosone", "naturemedicine", "annalsofinternalmedicine", "originalarticle",
    "researcharticle", "openaccess", "research", "articles", "article",
    "clinicaltrial", "peerreviewed",
)


def _squash(text: str) -> str:
    return re.sub(r"[^a-z]", "", text.lower())


def _is_masthead(line: str) -> bool:
    squashed = _squash(line)
    return not squashed or squashed in _MASTHEADS or any(
        squashed.startswith(name) and len(squashed) - len(name) <= 6 for name in _MASTHEADS[:4]
    )


def _furniture_key(line: str) -> str:
    """A running header with its page number and volume digits removed."""
    return re.sub(r"\s+", " ", re.sub(r"\d+", "#", line.strip().lower()))


def _is_numeric_block(text: str) -> bool:
    """A figure panel or table flattened into text: mostly bare numbers."""
    tokens = text.split()
    if len(tokens) < 12:
        return False
    numeric = sum(1 for token in tokens if re.fullmatch(r"[\d.,%()=–\-:;/<>±]+", token))
    return numeric / len(tokens) > 0.45


def _blocks_in_reading_order(page, furniture: frozenset[str] = frozenset()) -> str:
    """Sort text blocks top-to-bottom within left-then-right column halves."""
    blocks = []
    for block in page.get_text("blocks"):
        if len(block) < 5 or not str(block[4]).strip():
            continue
        # Block type 1 is an image; its "text" is a placeholder.
        if len(block) >= 7 and block[6] == 1:
            continue
        text = str(block[4])
        if furniture:
            kept = [line for line in text.split("\n") if _furniture_key(line) not in furniture]
            text = "\n".join(kept)
        if not text.strip() or _is_numeric_block(text):
            continue
        blocks.append((block[0], block[1], block[2], block[3], text))
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
        furniture = _running_furniture(document)
        heading_title = _title_from_fonts(document)
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            page_text = _blocks_in_reading_order(page, furniture)
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
    meta_title = (metadata.get("title") or "").strip()
    if meta_title and (_is_masthead(meta_title) or len(meta_title) < 15
                       or re.fullmatch(r"[\w.\-]+(?:\.pdf)?", meta_title)):
        meta_title = ""  # "nejmoa2021436", "Microsoft Word - draft3.docx", a masthead
    title = heading_title or meta_title or _guess_title(text) or filename
    year = _publication_year(text, metadata)

    return ParsedPdf(
        text=text,
        page_count=page_count,
        page_map=page_map,
        title=title[:500],
        doi=doi_match.group(0) if doi_match else None,
        year=year,
    )


def _running_furniture(document) -> frozenset[str]:
    """Lines that repeat across pages: running heads, footers, page stamps."""
    if document.page_count < 3:
        return frozenset()
    seen: dict[str, set[int]] = {}
    for page_index in range(document.page_count):
        page = document.load_page(page_index)
        height = page.rect.height or 1.0
        for block in page.get_text("blocks"):
            if len(block) < 5:
                continue
            # Only the top and bottom margins hold running heads.  Body text can
            # legitimately repeat (a table header, a recurring phrase) and must
            # never be learned as furniture.
            if not (block[3] < height * 0.10 or block[1] > height * 0.90):
                continue
            for line in str(block[4]).split("\n"):
                key = _furniture_key(line)
                if 3 <= len(key) <= 120:
                    seen.setdefault(key, set()).add(page_index)
    threshold = max(3, document.page_count // 3)
    return frozenset(key for key, pages in seen.items() if len(pages) >= threshold)


def _title_from_fonts(document) -> str | None:
    """The largest-type text on page 1 that is not a masthead.

    Font size is the one signal every publisher agrees on: the title is set
    bigger than anything else on the first page except, sometimes, the journal
    name -- which is why mastheads are excluded rather than trusted.
    """
    if document.page_count == 0:
        return None
    try:
        layout = document.load_page(0).get_text("dict")
    except Exception:  # pragma: no cover - defensive; text extraction succeeded
        return None

    lines: list[tuple[float, float, str]] = []  # (size, y0, text)
    for block in layout.get("blocks", []):
        for line in block.get("lines", []):
            spans = [span for span in line.get("spans", []) if span.get("text", "").strip()]
            if not spans:
                continue
            text = " ".join(span["text"].strip() for span in spans)
            size = max(float(span.get("size", 0)) for span in spans)
            lines.append((round(size, 1), float(line["bbox"][1]), re.sub(r"\s+", " ", text)))

    candidates = [
        line for line in lines
        if not _is_masthead(line[2]) and sum(ch.isalpha() for ch in line[2]) >= 4
    ]
    if not candidates:
        return None
    biggest = max(size for size, _y, _text in candidates)
    # A title wraps: take every consecutive line set at the top size.
    title_lines = sorted(
        (line for line in candidates if abs(line[0] - biggest) < 0.6), key=lambda line: line[1]
    )
    joined = " ".join(text for _size, _y, text in title_lines[:4]).strip()
    joined = re.sub(r"-\s+(?=[a-z])", "", joined)
    letters = sum(ch.isalpha() for ch in joined)
    if not (15 <= len(joined) <= 400) or letters < len(joined) * 0.55:
        return None
    return joined


def _publication_year(text: str, metadata: dict) -> int | None:
    head = text[:8000]
    for match in _DATED_YEAR.finditer(head):
        return int(match.group(1))
    for match in _YEAR.finditer(text[:3000]):
        if not _NOT_A_PUBLICATION_YEAR.search(text[max(0, match.start() - 25) : match.start()]):
            return int(match.group(1))
    created = re.search(r"(19[89]\d|20[0-4]\d)", metadata.get("creationDate") or "")
    return int(created.group(1)) if created else None


def _guess_title(text: str) -> str | None:
    """First plausible title-like line in the front matter."""
    for line in text.split("\n")[:15]:
        candidate = line.strip()
        if not (25 <= len(candidate) <= 300) or _is_masthead(candidate):
            continue
        if candidate.lower().startswith(("doi", "http", "www", "downloaded", "©")):
            continue
        letters = sum(character.isalpha() for character in candidate)
        if letters < len(candidate) * 0.6:
            continue
        return candidate
    return None
