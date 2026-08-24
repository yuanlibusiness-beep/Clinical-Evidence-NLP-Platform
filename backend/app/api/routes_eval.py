"""Evaluation endpoints.

Exposing the harness over HTTP is what lets the frontend show the quality
numbers next to the product.  A reviewer should not have to take "it is
accurate" on trust when they can press a button and read the precision, the
hallucination rate and the calibration error the system currently achieves --
including the fact that the bundled gold set is synthetic.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db import get_db
from app.evaluation.runner import load_dataset, run_evaluation
from app.models import EvalRun, User
from app.schemas import EvalRunOut, EvalRunRequest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/eval", tags=["evaluation"])


@router.get("/datasets/{name}")
def describe_dataset(name: str, _user: User = Depends(get_current_user)) -> dict:
    try:
        data = load_dataset(name)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return {
        "dataset": data.get("dataset"),
        "version": data.get("version"),
        "synthetic": data.get("synthetic", False),
        "notice": data.get("notice"),
        "n_cases": len(data.get("cases", [])),
        "case_ids": [case["id"] for case in data.get("cases", [])],
    }


@router.post("/run", response_model=EvalRunOut)
def run(
    payload: EvalRunRequest,
    rule_engine: bool = Query(
        default=False, description="Force the offline baseline engine."
    ),
    fit_calibration: bool = Query(default=False),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> EvalRunOut:
    try:
        result = run_evaluation(
            db,
            name=payload.name,
            dataset=payload.dataset,
            limit=payload.limit,
            force_rule_engine=rule_engine,
            fit_calibration=fit_calibration,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    db.commit()
    db.refresh(result)
    return EvalRunOut.model_validate(result)


@router.get("/runs", response_model=list[EvalRunOut])
def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[EvalRunOut]:
    rows = db.scalars(
        select(EvalRun).order_by(EvalRun.created_at.desc()).limit(limit)
    ).all()
    # The list view drops per_case to keep the payload small.
    out = []
    for row in rows:
        item = EvalRunOut.model_validate(row)
        item.per_case = None
        out.append(item)
    return out


@router.get("/runs/{run_id}", response_model=EvalRunOut)
def get_run(
    run_id: str, db: Session = Depends(get_db), _user: User = Depends(get_current_user)
) -> EvalRunOut:
    row = db.get(EvalRun, run_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Eval run not found."
        )
    return EvalRunOut.model_validate(row)
