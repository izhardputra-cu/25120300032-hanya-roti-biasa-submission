"""Pre-order schedules and their catalog-backed offers for T4."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pickup_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("order_cutoff_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        ),
        sa.CheckConstraint(
            "order_cutoff_at < pickup_at", name="ck_schedules_cutoff_before_pickup"
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_as_cs",
    )
    op.create_table(
        "schedule_offers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "schedule_id",
            sa.Integer(),
            sa.ForeignKey("schedules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey("products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("product_name", sa.String(80), nullable=False),
        sa.Column("selling_unit", sa.String(40), nullable=False),
        sa.Column("price_rupiah", sa.Integer(), nullable=False),
        sa.Column("quota", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        ),
        sa.UniqueConstraint(
            "schedule_id", "product_id", name="uq_schedule_offers_schedule_product"
        ),
        sa.CheckConstraint("quota BETWEEN 1 AND 999", name="ck_schedule_offers_quota"),
        sa.CheckConstraint(
            "price_rupiah BETWEEN 1000 AND 1000000",
            name="ck_schedule_offers_price_rupiah",
        ),
        sa.CheckConstraint(
            "CHAR_LENGTH(selling_unit) BETWEEN 2 AND 40",
            name="ck_schedule_offers_unit_length",
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_as_cs",
    )


def downgrade() -> None:
    op.drop_table("schedule_offers")
    op.drop_table("schedules")
