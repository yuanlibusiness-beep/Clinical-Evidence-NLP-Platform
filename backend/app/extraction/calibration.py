"""Confidence calibration.

A language model's self-reported confidence is not a probability.  It is fluent,
correlated-with-nothing-in-particular, and systematically too high -- which
makes it useless as an abstain threshold on its own.  This module turns it into
something that can be thresholded.

Two stages:

**Stage 1 - evidence-weighted raw score.**  Combine four observable signals into
one number in [0, 1]:

===============  ======  ===================================================
signal           weight  why it predicts correctness
===============  ======  ===================================================
self-reported     0.30   weak but non-zero signal; heavily shrunk
grounding score   0.34   a verbatim match is the strongest single predictor
retrieval score   0.18   was the supporting chunk actually ranked well?
section prior     0.10   a sample size found in Methods beats one in Discussion
rule agreement    0.08   an independent regex reaching the same answer
===============  ======  ===================================================

Weights are hand-set priors, not fitted -- and they are documented as such.

**Stage 2 - Platt scaling (optional, fitted).**  Given labelled outcomes from an
evaluation run, fit a one-dimensional logistic map ``sigma(a * logit(s) + b)``
and persist ``(a, b)``.  After that the numbers mean something: among fields
scored 0.8, roughly 80% should be correct.  ``expected_calibration_error`` in
``evaluation/metrics.py`` is what verifies the claim rather than asserting it.

Without a fitted scaler the raw score is returned unchanged, so the system is
honest about being uncalibrated until it has been calibrated.
"""

from __future__ import annotations

import json
import logging
import math
import os
from collections.abc import Sequence
from dataclasses import asdict, dataclass

logger = logging.getLogger(__name__)

CALIBRATION_PATH = os.getenv("CALIBRATION_PATH", "data/calibration.json")

WEIGHTS: dict[str, float] = {
    "self_reported": 0.30,
    "grounding": 0.34,
    "retrieval": 0.18,
    "section": 0.10,
    "rule_agreement": 0.08,
}

_EPSILON = 1e-6


@dataclass
class PlattScaler:
    a: float = 1.0
    b: float = 0.0
    n_samples: int = 0
    fitted: bool = False

    def apply(self, probability: float) -> float:
        if not self.fitted:
            return probability
        probability = min(max(probability, _EPSILON), 1 - _EPSILON)
        logit = math.log(probability / (1 - probability))
        return 1.0 / (1.0 + math.exp(-(self.a * logit + self.b)))


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exponent = math.exp(value)
    return exponent / (1.0 + exponent)


def raw_score(
    *,
    self_reported: float,
    grounding: float,
    retrieval: float,
    section_prior: float = 1.0,
    rule_agreement: float = 0.0,
) -> float:
    """Stage 1: blend the observable signals."""
    # Shrink the model's self-report toward 0.5 -- it is over-confident, and
    # treating 0.99 as meaningfully different from 0.85 is not supportable.
    shrunk_self = 0.5 + (min(max(self_reported, 0.0), 1.0) - 0.5) * 0.65
    # section_prior arrives as a multiplier around 1.0 (see sectioniser).
    section = min(1.0, max(0.0, (section_prior - 0.9) / 0.5))

    score = (
        WEIGHTS["self_reported"] * shrunk_self
        + WEIGHTS["grounding"] * min(max(grounding, 0.0), 1.0)
        + WEIGHTS["retrieval"] * min(max(retrieval, 0.0), 1.0)
        + WEIGHTS["section"] * section
        + WEIGHTS["rule_agreement"] * min(max(rule_agreement, 0.0), 1.0)
    )
    return min(1.0, max(0.0, score))


def load_scaler(path: str | None = None) -> PlattScaler:
    target = path or CALIBRATION_PATH
    if not os.path.exists(target):
        return PlattScaler()
    try:
        with open(target, encoding="utf-8") as handle:
            payload = json.load(handle)
        return PlattScaler(
            a=float(payload.get("a", 1.0)),
            b=float(payload.get("b", 0.0)),
            n_samples=int(payload.get("n_samples", 0)),
            fitted=bool(payload.get("fitted", False)),
        )
    except Exception as exc:  # pragma: no cover - corrupt file
        logger.warning("Could not read calibration file %s: %s", target, exc)
        return PlattScaler()


def save_scaler(scaler: PlattScaler, path: str | None = None) -> None:
    target = path or CALIBRATION_PATH
    os.makedirs(os.path.dirname(os.path.abspath(target)) or ".", exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(asdict(scaler), handle, indent=2)


def fit_platt(
    samples: Sequence[tuple[float, int]],
    *,
    iterations: int = 400,
    learning_rate: float = 0.35,
) -> PlattScaler:
    """Fit ``(a, b)`` by gradient descent on the log-loss.

    Two parameters over (usually) a few hundred labelled fields: batch gradient
    descent is the right tool -- no dependency, deterministic, and converges in
    milliseconds.  Below ~30 labelled samples the fit would be noise, so we
    refuse and stay uncalibrated rather than overfit.
    """
    clean = [
        (min(max(score, _EPSILON), 1 - _EPSILON), 1 if label else 0)
        for score, label in samples
        if score is not None
    ]
    if len(clean) < 30:
        logger.info("Only %d labelled samples; skipping calibration fit.", len(clean))
        return PlattScaler(n_samples=len(clean), fitted=False)

    logits = [math.log(score / (1 - score)) for score, _ in clean]
    labels = [float(label) for _, label in clean]

    a, b = 1.0, 0.0
    n = len(clean)
    for _ in range(iterations):
        gradient_a = 0.0
        gradient_b = 0.0
        for logit, label in zip(logits, labels, strict=True):
            prediction = _sigmoid(a * logit + b)
            error = prediction - label
            gradient_a += error * logit
            gradient_b += error
        a -= learning_rate * gradient_a / n
        b -= learning_rate * gradient_b / n

    return PlattScaler(a=a, b=b, n_samples=n, fitted=True)


class Calibrator:
    """Bundles the stage-1 blend with an optional fitted stage-2 scaler."""

    def __init__(self, scaler: PlattScaler | None = None) -> None:
        self.scaler = scaler or load_scaler()

    @property
    def is_fitted(self) -> bool:
        return self.scaler.fitted

    def score(
        self,
        *,
        self_reported: float,
        grounding: float,
        retrieval: float,
        section_prior: float = 1.0,
        rule_agreement: float = 0.0,
    ) -> float:
        raw = raw_score(
            self_reported=self_reported,
            grounding=grounding,
            retrieval=retrieval,
            section_prior=section_prior,
            rule_agreement=rule_agreement,
        )
        return round(self.scaler.apply(raw), 4)


def reliability_bins(
    samples: Sequence[tuple[float, int]], n_bins: int = 10
) -> list[dict[str, float]]:
    """Bucket predictions for a reliability diagram / ECE."""
    bins: list[dict[str, float]] = []
    for index in range(n_bins):
        low = index / n_bins
        high = (index + 1) / n_bins
        selected = [
            (score, label)
            for score, label in samples
            if (low <= score < high) or (index == n_bins - 1 and score == 1.0)
        ]
        if not selected:
            bins.append(
                {"bin_low": low, "bin_high": high, "count": 0, "confidence": 0.0, "accuracy": 0.0}
            )
            continue
        confidence = sum(score for score, _ in selected) / len(selected)
        accuracy = sum(label for _, label in selected) / len(selected)
        bins.append(
            {
                "bin_low": low,
                "bin_high": high,
                "count": len(selected),
                "confidence": round(confidence, 4),
                "accuracy": round(accuracy, 4),
            }
        )
    return bins
