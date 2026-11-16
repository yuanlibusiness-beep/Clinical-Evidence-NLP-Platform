"""Prompts.

Kept in one module, versioned by ``PROMPT_VERSION``, because a prompt change
invalidates every stored evaluation number.  The version string is written onto
each ``EvalRun`` so two runs are never silently compared across a prompt edit.

The system prompt does four jobs, in this order of importance:

1. Forbids using anything outside the supplied excerpts.  The model is told it
   is reading *excerpts*, not the paper, so "the paper surely says X" is off the
   table.
2. Makes ``null`` the correct answer for anything not present.  Stated as a
   positive instruction ("null is a correct answer"), because a prohibition
   alone loses to the pull toward completing the pattern.
3. Requires a verbatim quote per field, and warns that quotes are checked
   against the source afterwards.  The check is real, so the warning is honest.
4. Requires a calibrated confidence, defined against observable properties of
   the evidence rather than a vague "how sure are you".
"""

from __future__ import annotations

from app.schemas import RetrievedChunk

PROMPT_VERSION = "v1.3.0"

SYSTEM_PROMPT = """\
You are an evidence-extraction engine for clinical literature reviews. You read \
excerpts from a single paper and return one JSON object describing what that \
paper reports.

Rules, in priority order:

1. GROUND EVERYTHING. You are reading excerpts, not the whole paper, and not the \
literature. Use only the text between the <excerpt> tags. Never use background \
knowledge about the drug, the disease, or what studies like this usually find.

2. NULL IS A CORRECT ANSWER. If the excerpts do not state something, set "value" \
to null. A review with eight well-grounded fields and ten nulls is more useful \
than one with eighteen fields where five were guessed. Do not infer a sample \
size from a percentage, a design from an author's affiliation, or a p-value from \
the word "significant".

3. QUOTE VERBATIM. For every field with a non-null value, "quote" must be an \
exact character-for-character substring of one excerpt - one sentence, copied, \
not paraphrased, not trimmed of its units, not stitched from two places. Every \
quote is automatically matched back against the source after you answer; a quote \
that does not match causes the field to be discarded.

4. CALIBRATE CONFIDENCE. Set "confidence" between 0 and 1 using the evidence, \
not your fluency:
   - 0.90-1.00: the excerpt states it explicitly and unambiguously.
   - 0.70-0.89: clearly stated but needs light normalisation (e.g. adding up arms).
   - 0.50-0.69: implied by the excerpt and a reasonable reader would agree.
   - below 0.50: uncertain - prefer null instead.

5. ONE ROW PER RESULT. A paper states its main result up to three times \
(abstract, results text, figure legend): report it once, quoting the results \
text where possible. Never quote figure axes, at-risk tables or running headers. \
A result restricted to part of the trial (e.g. "among patients receiving \
mechanical ventilation") has kind "subgroup" and names the subgroup.

Return only the JSON object. No prose, no markdown fence, no explanation.\
"""

SCHEMA_GUIDE = """\
Return exactly this JSON shape. Every "field" object is \
{"value": string|null, "quote": string|null, "confidence": number}.

{
  "pico": {
    "population":   field,   // who was studied
    "intervention": field,   // what was given to the index group
    "comparison":   field,   // control / comparator arm
    "outcome":      field    // the primary thing measured
  },
  "design": {
    "design":          field, // e.g. "randomised controlled trial"
    "randomised":      field, // "yes" / "no" / null
    "blinding":        field, // e.g. "double-blind", "open-label"
    "setting":         field, // e.g. "multicentre, 14 hospitals in Denmark"
    "duration":        field, // study or follow-up length
    "registration_id": field  // NCT / ISRCTN / ChiCTR / PROSPERO number
  },
  "population": {
    "sample_size":        field, // total randomised or analysed, as reported
    "age":                field,
    "sex_distribution":   field,
    "inclusion_criteria": field,
    "exclusion_criteria": field
  },
  "outcomes": [
    {
      "name": string,                    // what was measured
      "kind": "primary"|"secondary"|"safety"|"subgroup", // subgroup = a result restricted to part of the trial

      "measure": string|null,            // hazard ratio, mean difference, ...
      "effect_size": string|null,
      "confidence_interval": string|null,
      "p_value": string|null,
      "direction": "favours_intervention"|"favours_comparison"|"no_difference"|null,
      "quote": string|null,
      "confidence": number
    }
  ],
  "limitations": field,
  "conclusion":  field,
  "funding":     field
}\
"""


def build_user_prompt(
    *,
    title: str,
    journal: str | None,
    year: int | None,
    evidence: list[RetrievedChunk],
    field_hints: dict[str, list[int]] | None = None,
) -> str:
    """Assemble the excerpt window handed to the model.

    Excerpts are numbered and labelled with their IMRaD section, which lets the
    model use position as evidence ("this p-value is in Results") and lets us
    read back which excerpt a quote came from when grounding.
    """
    header_parts = [f"Title: {title}"]
    if journal:
        header_parts.append(f"Journal: {journal}")
    if year:
        header_parts.append(f"Year: {year}")
    header = "\n".join(header_parts)

    blocks = []
    for index, chunk in enumerate(evidence, start=1):
        page = f", page {chunk.page_no}" if chunk.page_no else ""
        blocks.append(
            f'<excerpt id="{index}" section="{chunk.section_name}"{page}>\n'
            f"{chunk.text}\n"
            f"</excerpt>"
        )

    hint_text = ""
    if field_hints:
        lines = [
            f"- {field}: excerpts {', '.join(str(i) for i in ids)}"
            for field, ids in field_hints.items()
            if ids
        ]
        if lines:
            hint_text = (
                "\n\nRetrieval suggested these excerpts per field (a hint, not a "
                "constraint):\n" + "\n".join(lines)
            )

    return (
        f"{header}\n\n"
        f"{SCHEMA_GUIDE}\n\n"
        f"--- SOURCE EXCERPTS ---\n\n"
        + "\n\n".join(blocks)
        + hint_text
        + "\n\n--- END OF EXCERPTS ---\n\n"
        "Extract the evidence review as JSON now."
    )
