"""The automatic evaluation harness.

Run it with ``python -m app.evaluation.runner`` or through
``POST /api/v1/eval/run``.  For each case in the gold set it ingests the text
exactly the way a user's upload is ingested -- same sectioniser, same chunker,
same embedder, same retriever, same engine -- then scores four things:

* **extraction**   precision / recall / F1, plus the abstention breakdown
* **retrieval**    recall@3 and nDCG@3 against the gold evidence sentence
* **grounding**    what fraction of answered fields carry a verified span
* **calibration**  ECE and Brier over the calibrated confidences

Running the *whole* pipeline rather than calling the engine directly is the
point.  A harness that stubs retrieval measures the prompt; this one measures
the product, so a regression in chunking or fusion shows up as a drop in F1
where it belongs.

``--fit-calibration`` additionally fits the Platt scaler from this run's
outcomes and writes it to ``data/calibration.json``.  Fit on one run, evaluate
on another: fitting and reporting ECE in the same run would report the training
error, which is not a calibration claim anybody should believe.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import init_db, session_scope
from app.evaluation import metrics
from app.extraction.calibration import (
    Calibrator,
    fit_platt,
    reliability_bins,
    save_scaler,
)
from app.extraction.engines import RuleEngine, build_engine
from app.extraction.pipeline import ExtractionPipeline
from app.extraction.schema import FIELD_PATHS
from app.ingest.pipeline import create_document_from_text, index_document
from app.llm.factory import get_llm
from app.models import EvalRun, User
from app.security import hash_password

logger = logging.getLogger(__name__)

DATASET_DIR = os.path.join(os.path.dirname(__file__), "datasets")
EVAL_USER_EMAIL = "eval-harness@localhost"


def load_dataset(name: str = "gold_v1") -> dict[str, Any]:
    path = os.path.join(DATASET_DIR, f"{name}.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"No gold dataset at {path}")
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _eval_user(db: Session) -> User:
    user = db.scalar(select(User).where(User.email == EVAL_USER_EMAIL))
    if user is None:
        user = User(
            email=EVAL_USER_EMAIL,
            hashed_password=hash_password(os.urandom(16).hex()),
            full_name="Evaluation harness",
            is_active=False,  # cannot be logged into
        )
        db.add(user)
        db.flush()
    return user


def _dig(payload: dict[str, Any], path: str) -> str | None:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
        if current is None:
            return None
    if isinstance(current, dict):
        value = current.get("value")
        return value if isinstance(value, str) else None
    return current if isinstance(current, str) else None


def evaluate_case(
    db: Session,
    case: dict[str, Any],
    *,
    user: User,
    pipeline: ExtractionPipeline,
) -> tuple[dict[str, Any], list[tuple[float, int]]]:
    document = create_document_from_text(
        db,
        user_id=user.id,
        title=case["title"],
        text=case["text"],
        source_type="eval",
        source_label=f"gold:{case['id']}",
        journal=case.get("journal"),
        year=case.get("year"),
    )
    index_document(db, document)

    context, retrieval_scores = pipeline._build_context(document)  # noqa: SLF001
    engine_result = pipeline.engine.run(context)
    payload, confidence, abstentions, spans = pipeline._post_process(  # noqa: SLF001
        document, engine_result, context, retrieval_scores
    )

    gold: dict[str, Any] = case.get("gold", {})
    span_by_field = {span.field_path: span for span in spans}

    outcomes: list[metrics.FieldOutcome] = []
    calibration_samples: list[tuple[float, int]] = []

    for path in FIELD_PATHS:
        predicted = _dig(payload, path)
        expected = gold.get(path)
        correct = metrics.values_match(predicted, expected)
        span = span_by_field.get(path)
        score = confidence.get(path, 0.0)

        outcomes.append(
            metrics.FieldOutcome(
                field_path=path,
                predicted=predicted,
                gold=expected,
                correct=correct,
                confidence=score,
                grounded=span is not None,
                match_score=span.match_score if span else 0.0,
                verdict=metrics.classify(predicted, expected, correct),
            )
        )
        if predicted is not None:
            calibration_samples.append((score, 1 if correct else 0))

    extraction_scores = metrics.score_extraction(outcomes)

    per_field_hits = {
        path: [chunk.text for chunk in chunks]
        for path, chunks in context.per_field.items()
    }
    retrieval_scores_summary = metrics.score_retrieval(
        per_field_hits, case.get("gold_evidence", {}), k=3
    )
    outcome_scores = metrics.score_outcomes(
        payload.get("outcomes", []), case.get("gold_outcomes", [])
    )

    # Evaluation documents are scratch data; do not leave them in the user's
    # library.
    db.delete(document)
    db.flush()

    return (
        {
            "case_id": case["id"],
            "design_family": case.get("design_family"),
            "title": case["title"],
            "extraction": extraction_scores.__dict__,
            "retrieval": retrieval_scores_summary,
            "outcomes": outcome_scores,
            "abstentions": abstentions,
            "engine": {
                "provider": engine_result.provider,
                "model": engine_result.model,
                "prompt_version": engine_result.prompt_version,
                "latency_ms": engine_result.latency_ms,
                "prompt_tokens": engine_result.prompt_tokens,
                "completion_tokens": engine_result.completion_tokens,
            },
        },
        calibration_samples,
    )


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def run_evaluation(
    db: Session,
    *,
    name: str = "ad-hoc run",
    dataset: str = "gold_v1",
    limit: int | None = None,
    force_rule_engine: bool = False,
    fit_calibration: bool = False,
) -> EvalRun:
    started = time.perf_counter()
    data = load_dataset(dataset)
    cases = data["cases"][:limit] if limit else data["cases"]

    engine = RuleEngine() if force_rule_engine else build_engine(get_llm())
    pipeline = ExtractionPipeline(db, engine=engine, calibrator=Calibrator())
    user = _eval_user(db)

    per_case: list[dict[str, Any]] = []
    calibration_samples: list[tuple[float, int]] = []

    for case in cases:
        try:
            result, samples = evaluate_case(db, case, user=user, pipeline=pipeline)
            per_case.append(result)
            calibration_samples.extend(samples)
        except Exception as exc:
            logger.exception("Case %s failed", case.get("id"))
            per_case.append({"case_id": case.get("id"), "error": str(exc)})

    scored = [case for case in per_case if "extraction" in case]

    aggregate = {
        "extraction": {
            "precision": _mean([c["extraction"]["precision"] for c in scored]),
            "recall": _mean([c["extraction"]["recall"] for c in scored]),
            "f1": _mean([c["extraction"]["f1"] for c in scored]),
            "coverage": _mean([c["extraction"]["coverage"] for c in scored]),
            "hallucination_rate": _mean(
                [c["extraction"]["hallucination_rate"] for c in scored]
            ),
            "missed_rate": _mean([c["extraction"]["missed_rate"] for c in scored]),
            "grounded_ratio": _mean([c["extraction"]["grounded_ratio"] for c in scored]),
            "mean_match_score": _mean(
                [c["extraction"]["mean_match_score"] for c in scored]
            ),
        },
        "retrieval": {
            "recall@3": _mean([c["retrieval"].get("recall@3", 0.0) for c in scored]),
            "ndcg@3": _mean([c["retrieval"].get("ndcg@3", 0.0) for c in scored]),
        },
        "outcomes": {
            "effect_recall": _mean([c["outcomes"]["effect_recall"] for c in scored]),
            "p_value_recall": _mean([c["outcomes"]["p_value_recall"] for c in scored]),
        },
        "calibration": {
            "ece": metrics.expected_calibration_error(calibration_samples),
            "brier": metrics.brier_score(calibration_samples),
            "n_samples": len(calibration_samples),
            "bins": reliability_bins(calibration_samples),
            "scaler_fitted": pipeline.calibrator.is_fitted,
        },
        "runtime": {
            "seconds": round(time.perf_counter() - started, 2),
            "n_cases": len(scored),
            "n_failed": len(per_case) - len(scored),
            "dataset_is_synthetic": bool(data.get("synthetic")),
        },
    }

    if fit_calibration:
        scaler = fit_platt(calibration_samples)
        if scaler.fitted:
            save_scaler(scaler)
            aggregate["calibration"]["fitted_now"] = {
                "a": round(scaler.a, 4),
                "b": round(scaler.b, 4),
                "n_samples": scaler.n_samples,
            }

    run = EvalRun(
        name=name,
        provider=engine.provider,
        model=engine.model,
        dataset=dataset,
        n_cases=len(scored),
        metrics=aggregate,
        per_case=per_case,
    )
    db.add(run)
    db.flush()
    return run


def _print_report(run: EvalRun) -> None:
    extraction = run.metrics["extraction"]
    retrieval = run.metrics["retrieval"]
    calibration = run.metrics["calibration"]

    print(f"\n{'=' * 62}")
    print(f" {run.name}  |  {run.provider} / {run.model}")
    print(f" dataset: {run.dataset}  |  cases: {run.n_cases}")
    print("=" * 62)
    print(" EXTRACTION")
    print(f"   precision            {extraction['precision']:.3f}")
    print(f"   recall               {extraction['recall']:.3f}")
    print(f"   F1                   {extraction['f1']:.3f}")
    print(f"   coverage             {extraction['coverage']:.3f}")
    print(f"   hallucination rate   {extraction['hallucination_rate']:.3f}   (lower is better)")
    print(f"   missed rate          {extraction['missed_rate']:.3f}")
    print(" GROUNDING")
    print(f"   grounded ratio       {extraction['grounded_ratio']:.3f}")
    print(f"   mean match score     {extraction['mean_match_score']:.3f}")
    print(" RETRIEVAL")
    print(f"   recall@3             {retrieval['recall@3']:.3f}")
    print(f"   nDCG@3               {retrieval['ndcg@3']:.3f}")
    print(" CALIBRATION")
    print(f"   ECE                  {calibration['ece']:.3f}   (lower is better)")
    print(f"   Brier                {calibration['brier']:.3f}")
    print(f"   scaler fitted        {calibration['scaler_fitted']}")
    print("=" * 62 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the evaluation harness.")
    parser.add_argument("--name", default="cli run")
    parser.add_argument("--dataset", default="gold_v1")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--rule-engine",
        action="store_true",
        help="Force the offline rule engine (the baseline the LLM is measured against).",
    )
    parser.add_argument(
        "--fit-calibration",
        action="store_true",
        help="Fit the Platt scaler from this run and write data/calibration.json.",
    )
    parser.add_argument("--json", action="store_true", help="Print raw JSON metrics.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    init_db()

    with session_scope() as db:
        run = run_evaluation(
            db,
            name=args.name,
            dataset=args.dataset,
            limit=args.limit,
            force_rule_engine=args.rule_engine,
            fit_calibration=args.fit_calibration,
        )
        db.flush()
        if args.json:
            # stdout must stay parseable when piped, so nothing else is printed.
            print(json.dumps(run.metrics, indent=2))
        else:
            _print_report(run)
            print(f"Stored as eval run {run.id} (environment: {settings.environment})")


if __name__ == "__main__":
    main()
