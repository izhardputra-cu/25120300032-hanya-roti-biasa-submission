"""Archive finished bake schedules without deleting order history.

The column is nullable and defaults to NULL (not archived), so every existing
schedule keeps its current behaviour. Nothing is backfilled or renamed.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "schedules",
        sa.Column("archived_at", mysql.DATETIME(fsp=6), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("schedules", "archived_at")
