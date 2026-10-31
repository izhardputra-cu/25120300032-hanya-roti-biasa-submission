"""Remove local E2E order rows so synthetic schedules/products can be cleaned.

This is test-only housekeeping for the approved local MySQL test database. It is
never imported by the application and never runs against development or cloud
databases.
"""

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from sqlalchemy import delete  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.orm import Session as DBSession  # noqa: E402

from app.db import make_engine  # noqa: E402
from app.models import Order, OrderItem  # noqa: E402


def main() -> None:
    url = os.environ["TEST_DATABASE_URL"]
    parsed = make_url(url)
    if not (
        parsed.drivername == "mysql+pymysql"
        and parsed.host == "127.0.0.1"
        and parsed.port == 3307
        and parsed.database == "wad05_test"
        and parsed.username == "wad05_test"
    ):
        raise SystemExit("Refusing cleanup: not the approved local test database")
    engine = make_engine(url)
    try:
        with DBSession(engine) as db:
            db.execute(delete(OrderItem))
            db.execute(delete(Order))
            db.commit()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
