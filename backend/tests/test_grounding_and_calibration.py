"""Grounding and calibration -- the two mechanisms the product's honesty rests on.

If grounding accepts a paraphrase, the platform starts attributing sentences to
papers that never contained them.  If it rejects a correctly-quoted sentence
because a PDF inserted a soft hyphen, the platform abstains on work it did
correctly.  These tests pin both edges.
"""

from __future__ import annotations

import math

from app.evaluation.metrics import expected_calibration_error, values_match
from app.extraction.calibration import (
    Calibrator,
    PlattScaler,
    fit_platt,
    raw_score,
    reliability_bins,
)
from app.extraction.grounding import NormalisedIndex, ground_quote, normalise_query
from app.extraction.schema import EvidenceReview, ExtractedField, iter_grounded_items

SOURCE = (
    "Methods\nA total of 248 patients with delayed sleep phase disorder were randomly "
    "assigned (1:1) to receive melatonin 2 mg nightly or matching placebo. The mean age "
    "was 24.6 years (SD 4.2).\n\nResults\nSleep onset latency fell by 34 minutes "
    "(95% CI -31 to -15, p < 0.001)."
)


class TestGrounding:
    def setup_method(self):
        self.index = NormalisedIndex(SOURCE)

    def test_exact_quote_scores_one(self):
        quote = "The mean age was 24.6 years (SD 4.2)."
        span = ground_quote(quote, self.index)
        assert span is not None
        assert span.method == "exact"
        assert span.match_score == 1.0
        assert SOURCE[span.char_start : span.char_end] == quote

    def test_whitespace_and_case_differences_still_ground(self):
        span = ground_quote("the mean age  was 24.6 YEARS (SD 4.2).", self.index)
        assert span is not None
        assert span.method == "normalised"
        # The stored quote is the source text, not the model's rewording.
        assert "The mean age was 24.6 years" in span.quote

    def test_unicode_dash_is_folded(self):
        span = ground_quote("95% CI –31 to –15", self.index)
        assert span is not None

    def test_paraphrase_is_rejected(self):
        span = ground_quote(
            "Roughly two hundred and fifty people took part in the trial.", self.index
        )
        assert span is None

    def test_invented_quote_is_rejected(self):
        span = ground_quote(
            "The intervention halved mortality at five years in every subgroup.",
            self.index,
        )
        assert span is None

    def test_too_short_quotes_are_rejected(self):
        assert ground_quote("248", self.index) is None

    def test_returned_offsets_are_usable(self):
        span = ground_quote("Sleep onset latency fell by 34 minutes", self.index)
        assert span is not None
        assert SOURCE[span.char_start : span.char_end].startswith("Sleep onset latency")

    def test_normalise_query_collapses_whitespace(self):
        assert normalise_query("  A   B \n C ") == "a b c"


class TestSchemaAbstention:
    def test_placeholder_strings_become_null(self):
        for placeholder in ("N/A", "not reported", "unknown", "  ", "-"):
            assert ExtractedField(value=placeholder).value is None

    def test_percentage_confidence_is_rescaled(self):
        assert ExtractedField(value="x", confidence=85).confidence == 0.85

    def test_confidence_is_clamped(self):
        assert ExtractedField(value="x", confidence=-3).confidence == 0.0
        # Anything above 1 is read as a percentage first, then clamped -- so 300
        # becomes 1.0, and a bare 3 is interpreted as 3%, not as "very sure".
        assert ExtractedField(value="x", confidence=300).confidence == 1.0
        assert ExtractedField(value="x", confidence=3).confidence == 0.03

    def test_iter_covers_every_declared_field(self):
        review = EvidenceReview()
        paths = [path for path, _v, _q, _c in iter_grounded_items(review)]
        assert "pico.population" in paths
        assert "design.registration_id" in paths
        assert len(paths) == len(set(paths))


class TestCalibration:
    def test_grounding_dominates_a_confident_guess(self):
        grounded = raw_score(self_reported=0.5, grounding=1.0, retrieval=0.8)
        boasted = raw_score(self_reported=1.0, grounding=0.0, retrieval=0.8)
        assert grounded > boasted

    def test_score_is_bounded(self):
        assert 0.0 <= raw_score(self_reported=2, grounding=2, retrieval=2) <= 1.0

    def test_unfitted_scaler_is_the_identity(self):
        assert PlattScaler().apply(0.42) == 0.42

    def test_too_few_samples_refuses_to_fit(self):
        assert not fit_platt([(0.8, 1)] * 5).fitted

    def test_fitting_reduces_calibration_error(self):
        # A systematically over-confident system: says 0.9, right 50% of the time.
        samples = [(0.9, i % 2) for i in range(200)]
        before = expected_calibration_error(samples)
        scaler = fit_platt(samples)
        assert scaler.fitted
        after = expected_calibration_error(
            [(scaler.apply(score), label) for score, label in samples]
        )
        assert after < before

    def test_calibrator_returns_a_probability(self):
        value = Calibrator(PlattScaler()).score(
            self_reported=0.8, grounding=1.0, retrieval=0.7, section_prior=1.25
        )
        assert 0.0 <= value <= 1.0
        assert not math.isnan(value)

    def test_reliability_bins_cover_the_unit_interval(self):
        bins = reliability_bins([(0.05, 0), (0.55, 1), (1.0, 1)], n_bins=10)
        assert len(bins) == 10
        assert sum(b["count"] for b in bins) == 3


class TestValueMatching:
    def test_numeric_equivalence(self):
        assert values_match("1,204 patients", "1204")

    def test_containment(self):
        assert values_match("double-blind, placebo controlled", "double-blind")

    def test_unrelated_values_do_not_match(self):
        assert not values_match("cohort study", "randomised controlled trial")

    def test_both_null_counts_as_agreement(self):
        assert values_match(None, None)

    def test_answering_a_null_gold_is_not_a_match(self):
        assert not values_match("something", None)
