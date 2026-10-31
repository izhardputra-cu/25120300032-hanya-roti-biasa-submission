from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase

# One uvicorn worker per instance, so the database sees at most this many
# application connections per instance: max instances x (POOL_SIZE + MAX_OVERFLOW).
POOL_SIZE = 5
MAX_OVERFLOW = 0


class Base(DeclarativeBase):
    pass


def make_engine(url: str) -> Engine:
    parsed = make_url(url)
    if parsed.drivername != "mysql+pymysql":
        raise ValueError("Database must use MySQL with PyMySQL")
    return create_engine(
        parsed,
        pool_pre_ping=True,
        pool_size=POOL_SIZE,
        max_overflow=MAX_OVERFLOW,
        hide_parameters=True,
        connect_args={"init_command": "SET time_zone = '+00:00'"},
    )
