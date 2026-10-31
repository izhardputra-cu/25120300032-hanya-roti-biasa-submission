import os
from collections.abc import Iterator
from datetime import datetime

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, delete, text
from sqlalchemy.engine import make_url

from app.config import Settings
from app.db import make_engine
from app.main import create_app
from app.models import Order, OrderItem, Product, Schedule, ScheduleOffer, Session, User

ORIGIN = "http://testserver"
SCHEMA_REBUILT = pytest.StashKey[bool]()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--rebuild-test-schema",
        action="store_true",
        help="Explicitly approved destructive rebuild of guarded local wad05_test only.",
    )


class MutableClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, 8, 0, 0)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def settings() -> Settings:
    url = os.environ["TEST_DATABASE_URL"]
    parsed = make_url(url)
    if not (
        parsed.drivername == "mysql+pymysql"
        and parsed.host == "127.0.0.1"
        and parsed.port == 3307
        and parsed.database == "wad05_test"
        and parsed.username == "wad05_test"
    ):
        pytest.fail("Refusing setup: TEST_DATABASE_URL is not the approved local test DB")
    return Settings(database_url=url, environment="test", allowed_origins=[ORIGIN])


@pytest.fixture(autouse=True)
def database(settings: Settings, request: pytest.FixtureRequest) -> Iterator[None]:
    # The settings fixture validates the exact test DSN before creating this engine.
    engine = make_engine(settings.database_url.get_secret_value())
    config = Config("alembic.ini")
    with engine.connect() as connection:
        config.attributes["connection"] = connection
        if request.config.getoption("--rebuild-test-schema") and not request.config.stash.get(
            SCHEMA_REBUILT, False
        ):
            if (
                connection.scalar(text("SELECT DATABASE()")) != "wad05_test"
                or connection.scalar(text("SELECT SUBSTRING_INDEX(CURRENT_USER(), '@', 1)"))
                != "wad05_test"
            ):
                pytest.fail("Refusing rebuild: connected database/user is not wad05_test")
            metadata = MetaData()
            metadata.reflect(bind=connection)
            expected = {
                "alembic_version", "users", "sessions", "products", "schedules",
                "schedule_offers", "orders", "order_items",
            }
            if not set(metadata.tables) <= expected:
                pytest.fail("Refusing rebuild: unexpected tables in approved test DB")
            # Explicit opt-in, never automatic error recovery. Respect FK drop order;
            # keep the database, privileges and foreign-key checks intact.
            metadata.drop_all(bind=connection)
            connection.commit()
            request.config.stash[SCHEMA_REBUILT] = True
        command.upgrade(config, "head")
        # MySQL DDL persists even if later DML rolls back. Persist its version too.
        connection.commit()
        connection.execute(delete(OrderItem))
        connection.execute(delete(Order))
        connection.execute(delete(ScheduleOffer))
        connection.execute(delete(Schedule))
        connection.execute(delete(Product))
        connection.execute(delete(Session))
        connection.execute(delete(User))
        connection.commit()
    yield
    with engine.begin() as connection:
        connection.execute(delete(OrderItem))
        connection.execute(delete(Order))
        connection.execute(delete(ScheduleOffer))
        connection.execute(delete(Schedule))
        connection.execute(delete(Product))
        connection.execute(delete(Session))
        connection.execute(delete(User))
    engine.dispose()


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as client:
        yield client


@pytest.fixture
def clocked_client(settings: Settings) -> Iterator[tuple[TestClient, MutableClock]]:
    clock = MutableClock()
    with TestClient(create_app(settings, clock=clock)) as client:
        yield client, clock
