"""IMRaD section detection.

Why bother?  Because *where* a sentence sits in a paper is strong evidence about
what it can support.  A sample size belongs in Methods; a p-value belongs in
Results; a limitation belongs in Discussion.  The retriever uses the section
label as a prior (``app.retrieval.hybrid``), the extractor restricts candidate
evidence by section (``app.extraction.pipeline``), and the evaluator reports
accuracy per section.  A flat bag of text loses all of that.

Detection is deliberately conservative: a line is only promoted to a heading if
it is short, sits on its own, and matches a known clinical-paper heading.  When
nothing matches -- an abstract-only record, say -- the whole document becomes a
single ``body`` section rather than a wrong guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CANONICAL_SECTIONS = (
    "title",
    "abstract",
    "background",
    "methods",
    "results",
    "discussion",
    "conclusion",
    "references",
    "supplementary",
    "body",
)

# Ordered: the first pattern that matches wins, so put the specific ones first.
_HEADING_RULES: list[tuple] = [
    ("abstract", r"^(structured\s+)?abstract$|^summary$"),
    (
        "background",
        r"^(1\s*\.?\s*)?(introduction|background|introduction\s+and\s+background)$",
    ),
    (
        "methods",
        r"^(\d\s*\.?\s*)?((materials?|patients?|subjects?|participants?|study\s+population)"
        r"\s+and\s+methods?|methods?|methodology|study\s+design|design|"
        r"data\s+(collection|sources?)|statistical\s+analysis)$",
    ),
    ("results", r"^(\d\s*\.?\s*)?(results?|findings?|outcomes?)$"),
    (
        "discussion",
        r"^(\d\s*\.?\s*)?(discussion|interpretation|limitations?|"
        r"strengths?\s+and\s+limitations?)$",
    ),
    ("conclusion", r"^(\d\s*\.?\s*)?(conclusions?|concluding\s+remarks?)$"),
    (
        "references",
        r"^(references?|bibliography|works\s+cited|literature\s+cited)$",
    ),
    (
        "supplementary",
        r"^(supplementary(\s+(material|information|data))?|appendix|"
        r"acknowledge?ments?|funding|conflicts?\s+of\s+interest|"
        r"author\s+contributions?|data\s+availability|ethics(\s+statement)?)$",
    ),
]

_COMPILED = [(name, re.compile(pattern, re.IGNORECASE)) for name, pattern in _HEADING_RULES]

_MAX_HEADING_LEN = 90
_TRAILING_JUNK = re.compile(r"[\s:.\-–—]+$")


@dataclass
class DetectedSection:
    name: str
    heading: str | None
    order_index: int
    char_start: int
    char_end: int
    text: str


def _canonicalise(line: str) -> str | None:
    candidate = _TRAILING_JUNK.sub("", line.strip())
    if not candidate or len(candidate) > _MAX_HEADING_LEN:
        return None
    # A heading is not a sentence: reject anything with internal punctuation
    # typical of prose.
    if candidate.count(".") > 1 or candidate.endswith(("?", "!")):
        return None
    for name, pattern in _COMPILED:
        if pattern.match(candidate):
            return name
    return None


def detect_sections(raw_text: str, *, title: str | None = None) -> list[DetectedSection]:
    """Return non-overlapping sections covering ``raw_text``."""
    if not raw_text.strip():
        return []

    boundaries: list[tuple] = []  # (char_start_of_heading, char_start_of_body, name, heading)
    offset = 0
    for line in raw_text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped:
            name = _canonicalise(stripped)
            if name:
                boundaries.append((offset, offset + len(line), name, stripped))
        offset += len(line)

    boundaries, abstract_end = _fold_structured_abstract(raw_text, boundaries)

    sections: list[DetectedSection] = []
    order = 0

    if title and raw_text.lstrip().startswith(title.strip()[:60]):
        start = raw_text.index(title.strip()[:60])
        end = start + len(title)
        sections.append(
            DetectedSection("title", None, order, start, end, raw_text[start:end])
        )
        order += 1

    if not boundaries:
        start = sections[-1].char_end if sections else 0
        sections.append(
            DetectedSection(
                "body", None, order, start, len(raw_text), raw_text[start:]
            )
        )
        return sections

    # Text before the first heading: front matter (title block, authors).
    first_heading_start = boundaries[0][0]
    lead_start = sections[-1].char_end if sections else 0
    if first_heading_start > lead_start and raw_text[lead_start:first_heading_start].strip():
        sections.append(
            DetectedSection(
                "title" if not sections else "body",
                None,
                order,
                lead_start,
                first_heading_start,
                raw_text[lead_start:first_heading_start],
            )
        )
        order += 1

    for index, (_h_start, body_start, name, heading) in enumerate(boundaries):
        body_end = (
            boundaries[index + 1][0] if index + 1 < len(boundaries) else len(raw_text)
        )
        tail_start = None
        if abstract_end is not None and body_start < abstract_end < body_end:
            # The last abstract subsection stops at the abstract's end; what
            # follows up to the next real heading is the unheaded introduction.
            body_end, tail_start = abstract_end, abstract_end
        body = raw_text[body_start:body_end]
        if body.strip():
            sections.append(
                DetectedSection(name, heading, order, body_start, body_end, body)
            )
            order += 1
        if tail_start is not None:
            tail_end = (
                boundaries[index + 1][0] if index + 1 < len(boundaries) else len(raw_text)
            )
            if raw_text[tail_start:tail_end].strip():
                sections.append(
                    DetectedSection(
                        "background", None, order, tail_start, tail_end,
                        raw_text[tail_start:tail_end],
                    )
                )
                order += 1

    return sections


_ABSTRACT_PARTS = {"background", "methods", "results", "conclusion"}
_ABSTRACT_WINDOW = 8000
_ABSTRACT_PART_MAX = 2500
#: The end of an abstract's last paragraph: a sentence (or a closing
#: parenthetical such as NEJM's "(Funded by ...; ClinicalTrials.gov number,
#: NCT04381936.)") followed by a line break.
_PARAGRAPH_END = re.compile(r"[.!?][)\]]?[ \t]*\n")


def _fold_structured_abstract(
    raw_text: str, boundaries: list[tuple]
) -> tuple[list[tuple], int | None]:
    """Relabel a structured abstract's sub-headings as ``abstract``.

    NEJM, JAMA and BMJ abstracts carry BACKGROUND / METHODS / RESULTS /
    CONCLUSIONS headings of their own.  Taken at face value they open real
    sections, and the abstract's CONCLUSIONS then runs on through the unheaded
    introduction until the paper's own Methods heading -- which is how an
    introduction paragraph ended up quoted as the paper's conclusion.

    A run is folded only when it is unambiguous: two or more abstract-type
    headings near the top of the paper, each with a short body, and at least
    one of Methods/Results heading the paper again later.
    """
    if len(boundaries) < 3:
        return boundaries, None

    start = 0
    if boundaries[0][2] == "abstract":
        start = 1
    run_end = start
    seen: set[str] = set()
    while (
        run_end < len(boundaries)
        and boundaries[run_end][2] in _ABSTRACT_PARTS
        and boundaries[run_end][2] not in seen  # a repeat is the paper's own heading
        and boundaries[run_end][0] < _ABSTRACT_WINDOW
    ):
        seen.add(boundaries[run_end][2])
        run_end += 1
    run = boundaries[start:run_end]
    if len(run) < 2:
        return boundaries, None
    later = {b[2] for b in boundaries[run_end:]}
    if not ({"methods", "results"} & later):
        return boundaries, None
    # Every subsection but the last must be abstract-sized.
    for index in range(start, run_end - 1):
        if boundaries[index + 1][0] - boundaries[index][1] > _ABSTRACT_PART_MAX:
            return boundaries, None

    last_body = boundaries[run_end - 1][1]
    next_heading = boundaries[run_end][0] if run_end < len(boundaries) else len(raw_text)
    window_end = min(next_heading, last_body + _ABSTRACT_PART_MAX)
    match = _PARAGRAPH_END.search(raw_text, last_body + 40, window_end)
    abstract_end = match.end() if match else None
    if abstract_end is None or abstract_end >= next_heading:
        abstract_end = None

    folded = list(boundaries)
    for index in range(start, run_end):
        h_start, body_start, name, heading = folded[index]
        # The abstract's CONCLUSIONS paragraph *is* the authors' conclusion,
        # and once trimmed at the abstract's end it is the cleanest statement
        # of it in the paper -- so it keeps its label.
        if name != "conclusion":
            folded[index] = (h_start, body_start, "abstract", heading)
    return folded, abstract_end


def section_priority(section_name: str, field: str) -> float:
    """Prior on how likely a section is to answer a given extraction field.

    Used as a small multiplicative boost during retrieval fusion -- it nudges,
    it does not override lexical or semantic evidence.
    """
    table = {
        "population": {"methods": 1.25, "abstract": 1.15, "results": 1.05},
        "intervention": {"methods": 1.25, "abstract": 1.15},
        "comparison": {"methods": 1.25, "abstract": 1.1},
        "outcome": {"results": 1.25, "abstract": 1.15, "methods": 1.05},
        "study_design": {"methods": 1.3, "abstract": 1.15},
        "sample_size": {"methods": 1.25, "results": 1.2, "abstract": 1.1},
        "effect": {"results": 1.35, "abstract": 1.1},
        "limitations": {"discussion": 1.4, "conclusion": 1.1},
        "conclusion": {"conclusion": 1.35, "abstract": 1.15, "discussion": 1.1},
    }
    return table.get(field, {}).get(section_name, 1.0)
