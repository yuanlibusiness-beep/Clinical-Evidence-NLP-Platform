"""Evaluation metrics.

Four families, because "is the extraction good?" is four different questions:

**Extraction quality.**  Per field, compare prediction to gold.  Exact string
equality is too strict ("n = 1,204" vs "1204 patients") and substring matching
is too loose, so the comparator normalises numbers and units, then accepts on
containment *or* token-F1 above a threshold.  Every acceptance rule is in one
function so it can be argued with.

**Abstention behaviour.**  The metric that matters most here, and the one most
extraction demos omit.  Reporting only accuracy-over-answered rewards a system
that answers three fields confidently and abstains on fifteen.  So we report
coverage, precision-when-answered, and recall separately, plus the two error
types that actually hurt a reviewer:

* ``hallucination_rate`` -- gold says the paper does not report this, the system
  answered anyway.  This is the expensive error: a fabricated sample size in a
  systematic review is worse than a blank cell.
* ``missed_rate`` -- gold has a value, the system abstained.  Cheap error.

**Retrieval quality.**  Recall@k and nDCG@k against the gold evidence sentence
for each field.  If the supporting chunk never reaches the model, no amount of
prompt engineering will fix the field.

**Calibration.**  Expected Calibration Error over confidence bins: when the
system says 0.8, is it right about 80% of the time?
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.text_utils import normalise_for_match

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_TOKEN = re.compile(r"[a-z0-9.]+")

TOKEN_F1_ACCEPT = 0.60


# ------------------------------------------------------------------ comparison
def _canonical_numbers(text: str) -> list[str]:
    return [match.group(0).replace(",", "") for match in _NUMBER.finditer(text)]


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(normalise_for_match(text))


def token_f1(predicted: str, gold: str) -> float:
    predicted_tokens = Counter(_tokens(predicted))
    gold_tokens = Counter(_tokens(gold))
    if not predicted_tokens or not gold_tokens:
        return 0.0
    overlap = sum((predicted_tokens & gold_tokens).values())
    if overlap == 0:
        return 0.0
    precision = overlap / sum(predicted_tokens.values())
    recall = overlap / sum(gold_tokens.values())
    return 2 * precision * recall / (precision + recall)


def values_match(predicted: str | None, gold: str | None) -> bool:
    """Is this prediction an acceptable rendering of the gold answer?"""
    if predicted is None or gold is None:
        return predicted is None and gold is None

    left = normalise_for_match(predicted)
    right = normalise_for_match(gold)
    if not left or not right:
        return False
    if left == right:
        return True

    # Numeric fields: agreeing on the numbers is what counts.
    gold_numbers = _canonical_numbers(right)
    if gold_numbers:
        predicted_numbers = set(_canonical_numbers(left))
        if all(number in predicted_numbers for number in gold_numbers):
            return True

    if right in left or left in right:
        return True

    return token_f1(left, right) >= TOKEN_F1_ACCEPT


# ------------------------------------------------------------------ container
@dataclass
class FieldOutcome:
    field_path: str
    predicted: str | None
    gold: str | None
    correct: bool
    confidence: float = 0.0
    grounded: bool = False
    match_score: float = 0.0
    #: answered_correct | answered_wrong | hallucinated | missed | true_abstain
    verdict: str = "true_abstain"


@dataclass
class ExtractionScores:
    n_fields: int = 0
    coverage: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    accuracy_over_gold_present: float = 0.0
    hallucination_rate: float = 0.0
    missed_rate: float = 0.0
    grounded_ratio: float = 0.0
    mean_match_score: float = 0.0
    per_field: dict[str, dict[str, Any]] = field(default_factory=dict)


def score_extraction(outcomes: Sequence[FieldOutcome]) -> ExtractionScores:
    if not outcomes:
        return ExtractionScores()

    answered = [o for o in outcomes if o.predicted is not None]
    gold_present = [o for o in outcomes if o.gold is not None]
    gold_absent = [o for o in outcomes if o.gold is None]

    true_positive = sum(1 for o in answered if o.correct and o.gold is not None)
    hallucinated = sum(1 for o in gold_absent if o.predicted is not None)
    missed = sum(1 for o in gold_present if o.predicted is None)

    precision = true_positive / len(answered) if answered else 0.0
    recall = true_positive / len(gold_present) if gold_present else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    grounded = [o for o in answered if o.grounded]

    per_field: dict[str, dict[str, Any]] = {}
    for outcome in outcomes:
        per_field[outcome.field_path] = {
            "predicted": outcome.predicted,
            "gold": outcome.gold,
            "correct": outcome.correct,
            "verdict": outcome.verdict,
            "confidence": round(outcome.confidence, 4),
            "match_score": round(outcome.match_score, 4),
        }

    return ExtractionScores(
        n_fields=len(outcomes),
        coverage=round(len(answered) / len(outcomes), 4),
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
        accuracy_over_gold_present=round(
            (true_positive / len(gold_present)) if gold_present else 0.0, 4
        ),
        hallucination_rate=round(
            (hallucinated / len(gold_absent)) if gold_absent else 0.0, 4
        ),
        missed_rate=round((missed / len(gold_present)) if gold_present else 0.0, 4),
        grounded_ratio=round((len(grounded) / len(answered)) if answered else 0.0, 4),
        mean_match_score=round(
            (sum(o.match_score for o in grounded) / len(grounded)) if grounded else 0.0,
            4,
        ),
        per_field=per_field,
    )


def classify(predicted: str | None, gold: str | None, correct: bool) -> str:
    if predicted is None and gold is None:
        return "true_abstain"
    if predicted is None:
        return "missed"
    if gold is None:
        return "hallucinated"
    return "answered_correct" if correct else "answered_wrong"


# ------------------------------------------------------------------ retrieval
def recall_at_k(retrieved_texts: Sequence[str], gold_phrase: str, k: int) -> float:
    needle = normalise_for_match(gold_phrase)
    if not needle:
        return 0.0
    for text in retrieved_texts[:k]:
        if needle in normalise_for_match(text):
            return 1.0
    return 0.0


def ndcg_at_k(retrieved_texts: Sequence[str], gold_phrase: str, k: int) -> float:
    """Binary-relevance nDCG: only the chunk containing the gold sentence is
    relevant, so ideal DCG is 1 and this reduces to a rank-discounted hit."""
    needle = normalise_for_match(gold_phrase)
    if not needle:
        return 0.0
    for position, text in enumerate(retrieved_texts[:k], start=1):
        if needle in normalise_for_match(text):
            return 1.0 / math.log2(position + 1)
    return 0.0


def score_retrieval(
    per_field_hits: dict[str, list[str]], gold_evidence: dict[str, str], k: int = 3
) -> dict[str, float]:
    recalls: list[float] = []
    gains: list[float] = []
    for field_path, phrase in gold_evidence.items():
        texts = per_field_hits.get(field_path, [])
        recalls.append(recall_at_k(texts, phrase, k))
        gains.append(ndcg_at_k(texts, phrase, k))
    if not recalls:
        return {f"recall@{k}": 0.0, f"ndcg@{k}": 0.0, "n_queries": 0}
    return {
        f"recall@{k}": round(sum(recalls) / len(recalls), 4),
        f"ndcg@{k}": round(sum(gains) / len(gains), 4),
        "n_queries": len(recalls),
    }


# ------------------------------------------------------------------- outcomes
def score_outcomes(
    predicted: Sequence[dict[str, Any]], gold: Sequence[dict[str, Any]]
) -> dict[str, float]:
    """Recall of reported effect sizes and p-values.

    Outcome rows are scored separately from scalar fields because they are a
    *set*: the question is not "is this cell right" but "did we find the results
    the paper reports".  Matching is on the numeric value, since the label a
    system gives an outcome row is far more variable than the number attached
    to it.
    """
    if not gold:
        return {"effect_recall": 0.0, "p_value_recall": 0.0, "n_gold": 0, "n_predicted": len(predicted)}

    haystack = " | ".join(
        " ".join(
            str(value)
            for key, value in row.items()
            if key in ("effect_size", "confidence_interval", "p_value", "quote") and value
        )
        for row in predicted
    )
    numbers = set(_canonical_numbers(haystack))

    effect_hits = sum(
        1
        for row in gold
        if row.get("effect_size")
        and str(row["effect_size"]).replace(",", "").lstrip("-") .lstrip("+")
        in {number.lstrip("-") for number in numbers}
    )
    p_hits = sum(
        1
        for row in gold
        if row.get("p_value") and str(row["p_value"]).replace(",", "") in numbers
    )

    return {
        "effect_recall": round(effect_hits / len(gold), 4),
        "p_value_recall": round(p_hits / len(gold), 4),
        "n_gold": len(gold),
        "n_predicted": len(predicted),
    }


# ---------------------------------------------------------------- calibration
def expected_calibration_error(
    samples: Sequence[tuple[float, int]], n_bins: int = 10
) -> float:
    if not samples:
        return 0.0
    total = len(samples)
    error = 0.0
    for index in range(n_bins):
        low = index / n_bins
        high = (index + 1) / n_bins
        selected = [
            (score, label)
            for score, label in samples
            if (low <= score < high) or (index == n_bins - 1 and score == 1.0)
        ]
        if not selected:
            continue
        confidence = sum(score for score, _ in selected) / len(selected)
        accuracy = sum(label for _, label in selected) / len(selected)
        error += (len(selected) / total) * abs(confidence - accuracy)
    return round(error, 4)


def brier_score(samples: Sequence[tuple[float, int]]) -> float:
    if not samples:
        return 0.0
    return round(
        sum((score - label) ** 2 for score, label in samples) / len(samples), 4
    )
