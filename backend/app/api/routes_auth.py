"""Registration, login, and "who am I".

Deliberately plain email/password with a signed JWT.  The seven-person prototype
this project reimplements used a hosted identity provider; owning the flow here
is a conscious trade -- fewer features, but the token lifecycle, the hashing
parameters and the failure modes are all inspectable in this repository, which
is the point of a portfolio rebuild.

Login returns the same 401 for "no such email" and "wrong password", so the
endpoint cannot be used to enumerate registered addresses.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.config import settings
from app.db import get_db
from app.models import User
from app.schemas import TokenOut, UserCreate, UserLogin, UserOut
from app.security import create_access_token, hash_password, verify_password

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


def _normalise_email(email: str) -> str:
    return email.strip().lower()


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: Session = Depends(get_db)) -> TokenOut:
    email = _normalise_email(payload.email)
    existing = db.scalar(select(User).where(func.lower(User.email) == email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists.",
        )

    user = User(
        email=email,
        hashed_password=hash_password(payload.password),
        full_name=(payload.full_name or "").strip() or None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    logger.info("Registered user %s", user.id)
    return TokenOut(
        access_token=create_access_token(user.id, extra_claims={"email": user.email}),
        expires_in_minutes=settings.access_token_ttl_minutes,
        user=UserOut.model_validate(user),
    )


@router.post("/login", response_model=TokenOut)
def login(payload: UserLogin, db: Session = Depends(get_db)) -> TokenOut:
    email = _normalise_email(payload.email)
    user = db.scalar(select(User).where(func.lower(User.email) == email))

    # Same response either way -- no account enumeration.
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="This account is disabled."
        )

    return TokenOut(
        access_token=create_access_token(user.id, extra_claims={"email": user.email}),
        expires_in_minutes=settings.access_token_ttl_minutes,
        user=UserOut.model_validate(user),
    )


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)
