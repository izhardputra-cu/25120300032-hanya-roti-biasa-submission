"""Delete expired session rows on demand.

Expired sessions are already rejected when read, so this command is only
physical housekeeping. It is never called at API startup and is safe to repeat.
"""

import argparse
from datetime import datetime
from typing import Any, cast

from sqlalchemy import delete
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session as DBSession

from app.config import Settings
from app.db import make_engine
from app.models import Session
from app.security import utc_now


def purge_expired_sessions(db: DBSession, now: datetime) -> int:
    result = cast("CursorResult[Any]", db.execute(delete(Session).where(Session.expires_at <= now)))
    db.commit()
    return result.rowcount


def main() -> int:
    parser = argparse.ArgumentParser(description="Operational maintenance commands.")
    parser.add_argument(
        "target",
        choices=["sessions"],
        help="sessions: delete rows whose expiry has passed",
    )
    parser.parse_args()

    settings = Settings()
    engine = make_engine(settings.sqlalchemy_url())
    try:
        with DBSession(engine) as db:
            deleted = purge_expired_sessions(db, utc_now())
    finally:
        engine.dispose()

    print(f"Deleted {deleted} expired session(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
