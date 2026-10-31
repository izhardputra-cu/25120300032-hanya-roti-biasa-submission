import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from fastapi import Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.models import Session

COOKIE_NAME = "wad05_session"
SESSION_SECONDS = 24 * 60 * 60
TOKEN_PATTERN = re.compile(r"[a-f0-9]{64}")
password_hasher = PasswordHasher()


def utc_now() -> datetime:
    # MySQL DATETIME has no timezone; every stored timestamp represents UTC.
    return datetime.now(UTC).replace(tzinfo=None)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def find_session(request: Request, db: DBSession) -> Session | None:
    token = request.cookies.get(COOKIE_NAME, "")
    if not TOKEN_PATTERN.fullmatch(token):
        return None
    session = db.scalar(select(Session).where(Session.token_digest == token_digest(token)))
    if session is not None and session.expires_at <= request.app.state.clock():
        # Expiry denies access; physical cleanup is not part of this read operation.
        return None
    return session


def create_session(
    request: Request, response: Response, db: DBSession, user_id: int | None = None
) -> Session:
    token = secrets.token_hex(32)
    session = Session(
        token_digest=token_digest(token),
        csrf_token=secrets.token_hex(32),
        user_id=user_id,
        expires_at=request.app.state.clock() + timedelta(seconds=SESSION_SECONDS),
    )
    db.add(session)
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_SECONDS,
        httponly=True,
        secure=request.app.state.settings.secure_cookies(),
        samesite="lax",
        path="/",
    )
    return session


def clear_session_cookie(request: Request, response: Response) -> None:
    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        httponly=True,
        secure=request.app.state.settings.secure_cookies(),
        samesite="lax",
    )
