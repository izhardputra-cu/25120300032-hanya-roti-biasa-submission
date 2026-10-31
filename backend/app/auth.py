import secrets
from collections.abc import Iterator
from typing import Annotated

from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.models import Session, User
from app.schemas import LoginInput, LoginResult, RegisterInput, SessionContext, UserResult, UserView
from app.security import (
    TOKEN_PATTERN,
    clear_session_cookie,
    create_session,
    find_session,
    password_hasher,
)

router = APIRouter(prefix="/api")


def get_db(request: Request) -> Iterator[DBSession]:
    with request.app.state.session_factory() as db:
        yield db


DB = Annotated[DBSession, Depends(get_db)]


def require_csrf(request: Request, db: DB) -> Session:
    """Reject unsafe requests that do not come from a configured origin and session."""
    origin = request.headers.get("origin", "")
    if origin not in request.app.state.settings.allowed_origins:
        raise HTTPException(status_code=403, detail="Request verification failed")
    session = find_session(request, db)
    if session is None:
        raise HTTPException(status_code=403, detail="Request verification failed")
    sent_token = request.headers.get("x-csrf-token", "")
    if not TOKEN_PATTERN.fullmatch(sent_token) or not secrets.compare_digest(
        sent_token, session.csrf_token
    ):
        raise HTTPException(status_code=403, detail="Request verification failed")
    return session


CSRF = Annotated[Session, Depends(require_csrf)]


def current_user(request: Request, db: DB) -> User:
    session = find_session(request, db)
    if session is None or session.user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return session.user


USER = Annotated[User, Depends(current_user)]


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@router.get("/auth/session", response_model=SessionContext)
def session_context(request: Request, response: Response, db: DB) -> SessionContext:
    session = find_session(request, db)
    if session is None:
        session = create_session(request, response, db)
    db.commit()
    no_store(response)
    user = UserView.model_validate(session.user) if session.user is not None else None
    return SessionContext(user=user, csrf_token=session.csrf_token)


@router.post("/auth/register", status_code=201, response_model=UserResult)
def register(payload: RegisterInput, db: DB, _csrf: CSRF) -> UserResult:
    email = str(payload.email)
    if db.scalar(select(User).where(User.email == email)) is not None:
        raise HTTPException(status_code=409, detail="Email is already registered")
    user = User(
        name=payload.name,
        email=email,
        password_hash=password_hasher.hash(payload.password.get_secret_value()),
        role="buyer",
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email is already registered") from None
    return UserResult(user=UserView.model_validate(user))


@router.post("/auth/login", response_model=LoginResult)
def login(
    payload: LoginInput, request: Request, response: Response, db: DB, csrf_session: CSRF
) -> LoginResult:
    user = db.scalar(select(User).where(User.email == str(payload.email)))
    if user is None:
        raise HTTPException(status_code=401, detail="Email or password is incorrect")
    try:
        password_hasher.verify(user.password_hash, payload.password.get_secret_value())
    except (VerificationError, InvalidHashError):
        raise HTTPException(status_code=401, detail="Email or password is incorrect") from None
    if password_hasher.check_needs_rehash(user.password_hash):
        user.password_hash = password_hasher.hash(payload.password.get_secret_value())

    db.delete(csrf_session)
    db.flush()
    session = create_session(request, response, db, user_id=user.id)
    db.commit()
    no_store(response)
    return LoginResult(user=UserView.model_validate(user), csrf_token=session.csrf_token)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: DB, csrf_session: CSRF) -> None:
    db.delete(csrf_session)
    db.commit()
    clear_session_cookie(request, response)
    no_store(response)


@router.get("/me", response_model=UserView)
def me(response: Response, user: USER) -> UserView:
    no_store(response)
    return UserView.model_validate(user)


@router.get("/seller/profile", response_model=UserView)
def seller_profile(response: Response, user: USER) -> UserView:
    if user.role != "seller":
        raise HTTPException(status_code=403, detail="Seller access required")
    no_store(response)
    return UserView.model_validate(user)
