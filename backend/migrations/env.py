from alembic import context

from app import models  # noqa: F401
from app.config import Settings
from app.db import Base, make_engine

config = context.config


def run_migrations() -> None:
    # Tests supply a guarded connection; CLI reads DATABASE_URL without logging it.
    connection = config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = make_engine(Settings().sqlalchemy_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations()
