"""Public catalog products for T3."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("selling_unit", sa.String(40), nullable=False),
        sa.Column("price_rupiah", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(400), nullable=False, server_default=""),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("archived_at", mysql.DATETIME(fsp=6)),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        ),
        sa.CheckConstraint(
            "price_rupiah BETWEEN 1000 AND 1000000", name="ck_products_price_rupiah"
        ),
        sa.CheckConstraint("CHAR_LENGTH(name) BETWEEN 2 AND 80", name="ck_products_name_length"),
        sa.CheckConstraint(
            "CHAR_LENGTH(selling_unit) BETWEEN 2 AND 40", name="ck_products_unit_length"
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_as_cs",
    )


def downgrade() -> None:
    op.drop_table("products")
