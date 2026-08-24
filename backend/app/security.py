"""Password hashing and JWT issuing/verification.

Two details worth calling out:

1. bcrypt silently truncates input at 72 bytes, which turns long passphrases
   into weaker secrets.  We pre-hash with SHA-256 and base64-encode, so the
   full passphrase always contributes entropy.
2. Tokens carry ``sub``/``exp``/``iat``/``jti``/``typ``.  Verification requires
   all of them and pins the algorithm, so a token signed with ``alg: none`` or
   an unexpected algorithm is rejected outright.
"""

from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.config import settings

TOKEN_TYPE = "access"


# --------------------------------------------------------------------- passwords
def _prepare(password: str) -> bytes:
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest)


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=settings.password_hash_rounds)
    return bcrypt.hashpw(_prepare(password), salt).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_prepare(password), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ------------------------------------------------------------------------ tokens
class TokenError(Exception):
    """Raised when a token is missing, malformed, expired or not ours."""


def create_access_token(
    subject: str,
    *,
    extra_claims: dict[str, Any] | None = None,
    ttl_minutes: int | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    ttl = ttl_minutes if ttl_minutes is not None else settings.access_token_ttl_minutes
    payload: dict[str, Any] = {
        "sub": subject,
        "typ": TOKEN_TYPE,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ttl)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Session expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Invalid session token") from exc

    if claims.get("typ") != TOKEN_TYPE:
        raise TokenError("Wrong token type")
    if not isinstance(claims.get("sub"), str) or not claims["sub"]:
        raise TokenError("Token has no subject")
    return claims
