"""Create the one controlled seller account for the demo.

The seed is deliberately explicit: importing or starting the API never creates
an account, and repeating the command never overwrites an existing password.
"""

import argparse
import os
import sys
from dataclasses import dataclass
from enum import Enum

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.config import Settings
from app.db import make_engine
from app.models import User
from app.security import password_hasher

DEMO_SELLER_NAME = "Penjual Hanya Roti Biasa"
DEMO_SELLER_EMAIL = "seller@example.com"
DEMO_SELLER_PASSWORD = "Demo-seller-2026!"
SEED_PASSWORD_ENV = "SEED_SELLER_PASSWORD"


class SeedOutcome(Enum):
    CREATED = "created"
    UNCHANGED = "unchanged"
    REFUSED_BUYER = "refused-buyer"


@dataclass(frozen=True)
class SeedResult:
    outcome: SeedOutcome
    email: str


def seed_seller(
    db: DBSession,
    *,
    name: str = DEMO_SELLER_NAME,
    email: str = DEMO_SELLER_EMAIL,
    password: str = DEMO_SELLER_PASSWORD,
) -> SeedResult:
    normalized_email = email.strip().lower()
    existing = db.scalar(select(User).where(User.email == normalized_email))
    if existing is not None:
        if existing.role == "seller":
            return SeedResult(SeedOutcome.UNCHANGED, normalized_email)
        return SeedResult(SeedOutcome.REFUSED_BUYER, normalized_email)

    user = User(
        name=name.strip(),
        email=normalized_email,
        password_hash=password_hasher.hash(password),
        role="seller",
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # A concurrent seed or registration won the unique email race.
        existing = db.scalar(select(User).where(User.email == normalized_email))
        if existing is not None and existing.role == "seller":
            return SeedResult(SeedOutcome.UNCHANGED, normalized_email)
        return SeedResult(SeedOutcome.REFUSED_BUYER, normalized_email)
    return SeedResult(SeedOutcome.CREATED, normalized_email)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the controlled demo seller account.")
    parser.add_argument("--name", default=DEMO_SELLER_NAME)
    parser.add_argument("--email", default=DEMO_SELLER_EMAIL)
    parser.add_argument(
        "--password",
        help=(
            "Password for the first creation only. Defaults to "
            f"${SEED_PASSWORD_ENV}, then the development demo password. "
            "Repeating the seed never changes an existing password."
        ),
    )
    args = parser.parse_args()

    password = args.password or os.environ.get(SEED_PASSWORD_ENV) or DEMO_SELLER_PASSWORD
    settings = Settings()
    if (
        settings.environment == "production"
        and password == DEMO_SELLER_PASSWORD
    ):
        print(
            "Refused: set an explicit seller password via --password or "
            f"${SEED_PASSWORD_ENV}; the development demo password is not used in production.",
            file=sys.stderr,
        )
        return 2

    engine = make_engine(settings.sqlalchemy_url())
    try:
        with DBSession(engine) as db:
            result = seed_seller(db, name=args.name, email=args.email, password=password)
    finally:
        engine.dispose()

    if result.outcome is SeedOutcome.REFUSED_BUYER:
        print(
            f"Refused: {result.email} is an existing buyer. Public buyers are never promoted.",
            file=sys.stderr,
        )
        return 1
    print(f"Seller seed {result.outcome.value}: {result.email}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
