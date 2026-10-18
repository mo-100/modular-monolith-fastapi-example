"""Create the orders schema and tables.

Revision ID: orders_0001
Revises:
Create Date: 2026-10-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "orders_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS orders")

    op.create_table(
        "orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("total", sa.Numeric(12, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("total >= 0", name="ck_orders_total_non_negative"),
        sa.CheckConstraint(
            "status IN ('placed', 'cancelled')", name="ck_orders_status"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_orders"),
        schema="orders",
    )

    op.create_table(
        "order_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.CheckConstraint(
            "quantity > 0", name="ck_order_lines_quantity_positive"
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.orders.id"],
            name="fk_order_lines_order",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_order_lines"),
        schema="orders",
    )
    op.create_index(
        "ix_order_lines_order_id",
        "order_lines",
        ["order_id"],
        unique=False,
        schema="orders",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_order_lines_order_id",
        table_name="order_lines",
        schema="orders",
    )
    op.drop_table("order_lines", schema="orders")
    op.drop_table("orders", schema="orders")
    op.execute("DROP SCHEMA orders")
