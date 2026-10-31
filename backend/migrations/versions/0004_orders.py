"""Buyer orders and their immutable item snapshots for T5."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

MAX_ORDER_TOTAL_RUPIAH = 50 * 999 * 1_000_000
ORDER_STATUSES = (
    "menunggu_pembayaran",
    "menunggu_pemeriksaan",
    "terkonfirmasi",
    "siap_diambil",
    "selesai",
    "batal",
)


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "schedule_id",
            sa.Integer(),
            sa.ForeignKey("schedules.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("order_number", sa.String(32), nullable=False, unique=True),
        sa.Column("checkout_key", sa.String(64), nullable=False),
        sa.Column("checkout_fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "status",
            sa.String(24),
            nullable=False,
            server_default="menunggu_pembayaran",
        ),
        sa.Column("total_rupiah", sa.BigInteger(), nullable=False),
        sa.Column("pickup_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        ),
        sa.CheckConstraint(
            "status IN (" + ", ".join(f"'{status}'" for status in ORDER_STATUSES) + ")",
            name="ck_orders_status",
        ),
        sa.CheckConstraint(
            f"total_rupiah BETWEEN 1000 AND {MAX_ORDER_TOTAL_RUPIAH}",
            name="ck_orders_total_rupiah",
        ),
        sa.CheckConstraint(
            "CHAR_LENGTH(checkout_key) BETWEEN 8 AND 64",
            name="ck_orders_checkout_key_length",
        ),
        sa.UniqueConstraint(
            "user_id", "checkout_key", name="uq_orders_user_checkout_key"
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_as_cs",
    )
    op.create_index("ix_orders_schedule_id", "orders", ["schedule_id"])
    op.create_table(
        "order_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "order_id",
            sa.Integer(),
            sa.ForeignKey("orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "offer_id",
            sa.Integer(),
            sa.ForeignKey("schedule_offers.id", ondelete="RESTRICT"),
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
        sa.Column("unit_price_rupiah", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("line_total_rupiah", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("order_id", "offer_id", name="uq_order_items_order_offer"),
        sa.CheckConstraint(
            "unit_price_rupiah BETWEEN 1000 AND 1000000",
            name="ck_order_items_unit_price",
        ),
        sa.CheckConstraint("quantity BETWEEN 1 AND 999", name="ck_order_items_quantity"),
        sa.CheckConstraint(
            "line_total_rupiah = unit_price_rupiah * quantity",
            name="ck_order_items_line_total",
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_as_cs",
    )
    op.create_index("ix_order_items_offer_id", "order_items", ["offer_id"])


def downgrade() -> None:
    # Dropping the tables removes their indexes; dropping the FK-supporting
    # index first is refused by MySQL ("needed in a foreign key constraint").
    op.drop_table("order_items")
    op.drop_table("orders")
