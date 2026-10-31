import json
import os
import sys
from pathlib import Path

import uvicorn
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session as DBSession

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.config import Settings  # noqa: E402
from app.db import make_engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.seed import seed_seller  # noqa: E402

DEFAULT_ORIGINS = ["http://127.0.0.1:5173", "http://localhost:5173"]


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
        raise SystemExit("Refusing E2E server: TEST_DATABASE_URL is not the approved test DB")

    port = int(os.environ.get("E2E_PORT", "8010"))
    origins = json.loads(os.environ.get("E2E_ORIGINS", json.dumps(DEFAULT_ORIGINS)))
    frontend_dir = (
        str(BACKEND.parent / "frontend" / "dist")
        if os.environ.get("E2E_SERVE_FRONTEND") == "1"
        else None
    )
    settings = Settings(
        database_url=url,
        environment="test",
        allowed_origins=origins,
        frontend_dir=frontend_dir,
    )
    engine = make_engine(url)
    config = Config(str(BACKEND / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    with DBSession(engine) as db:
        seed_seller(db)
    engine.dispose()

    uvicorn.run(create_app(settings), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
