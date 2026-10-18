"""Create the inventory schema and tables.

Revision ID: inventory_0001
Revises:
Create Date: 2026-10-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "inventory_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS inventory")

    op.create_table(
        "products",
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("quantity_on_hand", sa.Integer(), nullable=False),
        sa.Column("quantity_reserved", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "quantity_on_hand >= 0", name="ck_products_on_hand"
        ),
        sa.CheckConstraint(
            "quantity_reserved >= 0", name="ck_products_reserved"
        ),
        sa.CheckConstraint(
            "quantity_reserved <= quantity_on_hand",
            name="ck_products_reserved_within_on_hand",
        ),
        sa.PrimaryKeyConstraint("sku", name="pk_products"),
        schema="inventory",
    )

    op.create_table(
        "stock_reservations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "quantity > 0", name="ck_reservations_quantity_positive"
        ),
        sa.ForeignKeyConstraint(
            ["sku"],
            ["inventory.products.sku"],
            name="fk_reservations_product",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_stock_reservations"),
        schema="inventory",
    )
    op.create_index(
        "ix_stock_reservations_order_id",
        "stock_reservations",
        ["order_id"],
        unique=False,
        schema="inventory",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_stock_reservations_order_id",
        table_name="stock_reservations",
        schema="inventory",
    )
    op.drop_table("stock_reservations", schema="inventory")
    op.drop_table("products", schema="inventory")
    op.execute("DROP SCHEMA inventory")
