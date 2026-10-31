"""Reject incomplete verification even when SQL comparisons evaluate UNKNOWN."""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # MySQL accepts UNKNOWN in CHECK constraints. The existing equality/bounds
    # check alone cannot reject a NULL amount when verification facts are set.
    op.create_check_constraint(
        "ck_orders_verified_amount_present",
        "orders",
        "verified_at IS NULL OR payment_received_rupiah IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_orders_verified_amount_present", "orders", type_="check")
