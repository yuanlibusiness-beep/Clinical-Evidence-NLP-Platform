"""The extraction contract.

This module is the centre of the whole system.  Everything else -- the prompt,
the JSON-mode request, the grounding check, the calibrator, the evaluator and
the UI -- is generated from or validated against these models.  There is exactly
one definition of "what a completed evidence review looks like", and it is here.

Three properties are enforced structurally rather than requested politely in a
prompt:

1. **Every claim carries its own quote.**  ``ExtractedField`` cannot hold a
   value without a ``quote`` slot beside it, so an ungrounded value is a schema
   violation, not a stylistic lapse.
2. **Abstention is representable.**  ``value=None`` is a first-class, valid
   answer.  A model that has to choose between inventing a sample size and
   failing validation will invent one; giving "not reported" a legal encoding is
   what makes the abstain policy work at all.
3. **Confidence is a number the model must commit to**, per field, before we
   ever see it -- which gives the calibrator something to correct.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_QUOTE_CHARS = 600
MAX_VALUE_CHARS = 800


class ExtractedField(BaseModel):
    """One atomic claim: a value, the sentence it came from, and a confidence."""

    model_config = ConfigDict(extra="ignore")

    value: str | None = Field(
        default=None,
        description="The extracted answer, or null if the paper does not report it.",
    )
    quote: str | None = Field(
        default=None,
        description="Verbatim sentence from the source that supports the value.",
    )
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("value", "quote", mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            value = str(value)
        if not isinstance(value, str):
            value = str(value)
        stripped = value.strip()
        if not stripped:
            return None
        # Models like to write these instead of emitting null.
        if stripped.lower() in {
            "n/a", "na", "none", "null", "not reported", "not stated",
            "not specified", "unknown", "unclear", "-", "--",
        }:
            return None
        return stripped

    @field_validator("value")
    @classmethod
    def _cap_value(cls, value: str | None) -> str | None:
        return value[:MAX_VALUE_CHARS] if value else value

    @field_validator("quote")
    @classmethod
    def _cap_quote(cls, value: str | None) -> str | None:
        return value[:MAX_QUOTE_CHARS] if value else value

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, value: Any) -> float:
        if value is None:
            return 0.0
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.0
        # Accept 0-100 as well as 0-1; models produce both.
        if number > 1.0:
            number = number / 100.0
        return max(0.0, min(1.0, number))

    @property
    def is_answered(self) -> bool:
        return self.value is not None


def _empty() -> ExtractedField:
    return ExtractedField()


class PICO(BaseModel):
    """The framing question a clinical evidence review is built around."""

    model_config = ConfigDict(extra="ignore")

    population: ExtractedField = Field(default_factory=_empty)
    intervention: ExtractedField = Field(default_factory=_empty)
    comparison: ExtractedField = Field(default_factory=_empty)
    outcome: ExtractedField = Field(default_factory=_empty)


class StudyDesign(BaseModel):
    model_config = ConfigDict(extra="ignore")

    design: ExtractedField = Field(default_factory=_empty)
    randomised: ExtractedField = Field(default_factory=_empty)
    blinding: ExtractedField = Field(default_factory=_empty)
    setting: ExtractedField = Field(default_factory=_empty)
    duration: ExtractedField = Field(default_factory=_empty)
    registration_id: ExtractedField = Field(default_factory=_empty)


class PopulationDetail(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sample_size: ExtractedField = Field(default_factory=_empty)
    age: ExtractedField = Field(default_factory=_empty)
    sex_distribution: ExtractedField = Field(default_factory=_empty)
    inclusion_criteria: ExtractedField = Field(default_factory=_empty)
    exclusion_criteria: ExtractedField = Field(default_factory=_empty)


class Outcome(BaseModel):
    """One reported result.  ``quote`` grounds the whole row."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(description="What was measured.")
    kind: str = Field(
        default="primary", description="primary | secondary | safety | subgroup"
    )
    measure: str | None = Field(
        default=None, description="e.g. hazard ratio, mean difference, % responders"
    )
    effect_size: str | None = None
    confidence_interval: str | None = None
    p_value: str | None = None
    direction: str | None = Field(
        default=None, description="favours_intervention | favours_comparison | no_difference"
    )
    quote: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("kind", mode="before")
    @classmethod
    def _normalise_kind(cls, value: Any) -> str:
        text = str(value or "primary").strip().lower()
        if "second" in text:
            return "secondary"
        if "subgroup" in text or "sub-group" in text:
            return "subgroup"
        if any(word in text for word in ("safety", "adverse", "harm")):
            return "safety"
        return "primary"

    @field_validator("direction", mode="before")
    @classmethod
    def _normalise_direction(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip().lower().replace(" ", "_")
        allowed = {"favours_intervention", "favours_comparison", "no_difference"}
        if text in allowed:
            return text
        if "no" in text and ("differ" in text or "signific" in text):
            return "no_difference"
        if "interven" in text or "treat" in text:
            return "favours_intervention"
        if "control" in text or "compar" in text or "placebo" in text:
            return "favours_comparison"
        return None

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce(cls, value: Any) -> float:
        return ExtractedField._coerce_confidence(value)


class EvidenceReview(BaseModel):
    """The complete structured review of one paper."""

    model_config = ConfigDict(extra="ignore")

    pico: PICO = Field(default_factory=PICO)
    design: StudyDesign = Field(default_factory=StudyDesign)
    population: PopulationDetail = Field(default_factory=PopulationDetail)
    outcomes: list[Outcome] = Field(default_factory=list)
    limitations: ExtractedField = Field(default_factory=_empty)
    conclusion: ExtractedField = Field(default_factory=_empty)
    funding: ExtractedField = Field(default_factory=_empty)

    @field_validator("outcomes", mode="before")
    @classmethod
    def _cap_outcomes(cls, value: Any) -> Any:
        if isinstance(value, list):
            return value[:12]
        return []


# --------------------------------------------------------------------- paths
#: Dotted paths of every ``ExtractedField`` in the review, in report order.
#: Used by the grounder, the calibrator, the evaluator and the UI so all four
#: agree on what "a field" is.
FIELD_PATHS: list[str] = [
    "pico.population",
    "pico.intervention",
    "pico.comparison",
    "pico.outcome",
    "design.design",
    "design.randomised",
    "design.blinding",
    "design.setting",
    "design.duration",
    "design.registration_id",
    "population.sample_size",
    "population.age",
    "population.sex_distribution",
    "population.inclusion_criteria",
    "population.exclusion_criteria",
    "limitations",
    "conclusion",
    "funding",
]

#: Retrieval hint per field -> feeds ``section_priority`` and the query builder.
FIELD_TOPICS: dict[str, str] = {
    "pico.population": "population",
    "pico.intervention": "intervention",
    "pico.comparison": "comparison",
    "pico.outcome": "outcome",
    "design.design": "study_design",
    "design.randomised": "study_design",
    "design.blinding": "study_design",
    "design.setting": "study_design",
    "design.duration": "study_design",
    "design.registration_id": "study_design",
    "population.sample_size": "sample_size",
    "population.age": "sample_size",
    "population.sex_distribution": "sample_size",
    "population.inclusion_criteria": "population",
    "population.exclusion_criteria": "population",
    "limitations": "limitations",
    "conclusion": "conclusion",
}

_INDEX = re.compile(r"^(?P<name>\w+)\[(?P<index>\d+)\]$")


def get_by_path(review: EvidenceReview, path: str) -> Any | None:
    """Resolve ``pico.population`` or ``outcomes[2]`` against a review."""
    current: Any = review
    for part in path.split("."):
        match = _INDEX.match(part)
        if match:
            current = getattr(current, match.group("name"), None)
            if current is None:
                return None
            index = int(match.group("index"))
            if not isinstance(current, list) or index >= len(current):
                return None
            current = current[index]
        else:
            current = getattr(current, part, None)
        if current is None:
            return None
    return current


def iter_grounded_items(review: EvidenceReview):
    """Yield ``(field_path, value, quote, self_confidence)`` for every claim."""
    for path in FIELD_PATHS:
        item = get_by_path(review, path)
        if isinstance(item, ExtractedField):
            yield path, item.value, item.quote, item.confidence
    for index, outcome in enumerate(review.outcomes):
        summary = " | ".join(
            part
            for part in (
                outcome.name,
                outcome.measure,
                outcome.effect_size,
                outcome.confidence_interval,
                outcome.p_value,
            )
            if part
        )
        yield f"outcomes[{index}]", summary, outcome.quote, outcome.confidence


def json_schema_for_prompt() -> dict[str, Any]:
    """Compact schema handed to the model in JSON mode."""
    return EvidenceReview.model_json_schema()
