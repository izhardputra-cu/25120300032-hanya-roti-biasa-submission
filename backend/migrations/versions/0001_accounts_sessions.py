"""Accounts and server-side sessions for T1."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(10), nullable=False),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.CheckConstraint("role IN ('buyer', 'seller')", name="ck_users_role"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_as_cs",
    )
    op.create_table(
        "sessions",
        sa.Column("token_digest", sa.String(64), primary_key=True),
        sa.Column("csrf_token", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("expires_at", mysql.DATETIME(fsp=6), nullable=False),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_as_cs",
    )
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_table("sessions")
    op.drop_table("users")
