"""Shared FastAPI dependencies.

``get_current_user`` is the only place a request is turned into an identity, and
``get_owned_document`` is the only place a document is fetched by id.  Keeping
both single-sourced is what makes the ownership guarantee auditable: no route
can accidentally read another user's document, because no route loads documents
any other way.

Note the 404-instead-of-403 on a document owned by somebody else -- returning
403 would confirm the id exists, which leaks the fact that a given document is
in the system.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Path, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Document, User
from app.security import TokenError, decode_access_token

CREDENTIALS_HEADER = {"WWW-Authenticate": "Bearer"}


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
            headers=CREDENTIALS_HEADER,
        )

    token = authorization.split(" ", 1)[1].strip()
    try:
        claims = decode_access_token(token)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers=CREDENTIALS_HEADER,
        ) from exc

    user = db.get(User, claims["sub"])
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists or is disabled.",
            headers=CREDENTIALS_HEADER,
        )
    return user


def get_owned_document(
    document_id: str = Path(..., min_length=8, max_length=64),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Document:
    document = db.get(Document, document_id)
    if document is None or document.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found."
        )
    return document
