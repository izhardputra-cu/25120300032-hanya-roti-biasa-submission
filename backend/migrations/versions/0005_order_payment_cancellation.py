"""Transfer reports, manual payment verification, and cancellation facts for T6."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

MAX_ORDER_TOTAL_RUPIAH = 50 * 999 * 1_000_000


def upgrade() -> None:
    op.add_column("orders", sa.Column("transfer_note", sa.String(200), nullable=True))
    op.add_column(
        "orders", sa.Column("transfer_reported_at", mysql.DATETIME(fsp=6), nullable=True)
    )
    op.add_column(
        "orders", sa.Column("transfer_reported_by_id", sa.Integer(), nullable=True)
    )
    op.add_column("orders", sa.Column("verified_at", mysql.DATETIME(fsp=6), nullable=True))
    op.add_column("orders", sa.Column("verified_by_id", sa.Integer(), nullable=True))
    op.add_column(
        "orders", sa.Column("payment_received_rupiah", sa.BigInteger(), nullable=True)
    )
    op.add_column("orders", sa.Column("cancelled_at", mysql.DATETIME(fsp=6), nullable=True))
    op.add_column("orders", sa.Column("cancelled_by_id", sa.Integer(), nullable=True))
    op.add_column("orders", sa.Column("cancellation_reason", sa.String(300), nullable=True))
    op.add_column("orders", sa.Column("refund_outcome", sa.String(24), nullable=True))

    op.create_foreign_key(
        "fk_orders_transfer_reported_by",
        "orders",
        "users",
        ["transfer_reported_by_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_orders_verified_by",
        "orders",
        "users",
        ["verified_by_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_orders_cancelled_by",
        "orders",
        "users",
        ["cancelled_by_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_check_constraint(
        "ck_orders_transfer_note_length",
        "orders",
        "transfer_note IS NULL OR CHAR_LENGTH(transfer_note) BETWEEN 3 AND 200",
    )
    op.create_check_constraint(
        "ck_orders_transfer_report_complete",
        "orders",
        "(transfer_note IS NULL AND transfer_reported_at IS NULL "
        "AND transfer_reported_by_id IS NULL) "
        "OR (transfer_note IS NOT NULL AND transfer_reported_at IS NOT NULL "
        "AND transfer_reported_by_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_orders_verification_complete",
        "orders",
        "(verified_at IS NULL AND verified_by_id IS NULL "
        "AND payment_received_rupiah IS NULL) "
        "OR (verified_at IS NOT NULL AND verified_by_id IS NOT NULL "
        f"AND payment_received_rupiah = total_rupiah "
        f"AND payment_received_rupiah BETWEEN 1000 AND {MAX_ORDER_TOTAL_RUPIAH})",
    )
    op.create_check_constraint(
        "ck_orders_cancellation_complete",
        "orders",
        "(cancelled_at IS NULL AND cancelled_by_id IS NULL "
        "AND cancellation_reason IS NULL) "
        "OR (cancelled_at IS NOT NULL AND cancelled_by_id IS NOT NULL "
        "AND cancellation_reason IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_orders_cancellation_reason_length",
        "orders",
        "cancellation_reason IS NULL "
        "OR CHAR_LENGTH(cancellation_reason) BETWEEN 3 AND 300",
    )
    op.create_check_constraint(
        "ck_orders_refund_outcome",
        "orders",
        "refund_outcome IS NULL "
        "OR refund_outcome IN ('refunded_manually', 'no_funds_received')",
    )
    op.create_check_constraint(
        "ck_orders_cancelled_status",
        "orders",
        "(status = 'batal' AND cancelled_at IS NOT NULL) "
        "OR (status <> 'batal' AND cancelled_at IS NULL)",
    )


def downgrade() -> None:
    for name in (
        "ck_orders_cancelled_status",
        "ck_orders_refund_outcome",
        "ck_orders_cancellation_reason_length",
        "ck_orders_cancellation_complete",
        "ck_orders_verification_complete",
        "ck_orders_transfer_report_complete",
        "ck_orders_transfer_note_length",
    ):
        op.drop_constraint(name, "orders", type_="check")
    for name in (
        "fk_orders_cancelled_by",
        "fk_orders_verified_by",
        "fk_orders_transfer_reported_by",
    ):
        op.drop_constraint(name, "orders", type_="foreignkey")
    for name in (
        "refund_outcome",
        "cancellation_reason",
        "cancelled_by_id",
        "cancelled_at",
        "payment_received_rupiah",
        "verified_by_id",
        "verified_at",
        "transfer_reported_by_id",
        "transfer_reported_at",
        "transfer_note",
    ):
        op.drop_column("orders", name)
