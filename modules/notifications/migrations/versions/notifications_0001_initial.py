"""Create the notifications schema and table.

Revision ID: notifications_0001
Revises:
Create Date: 2026-10-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "notifications_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS notifications")
    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_notification_messages"),
        schema="notifications",
    )
    op.create_index(
        "ix_notification_messages_order_id",
        "messages",
        ["order_id"],
        unique=False,
        schema="notifications",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notification_messages_order_id",
        table_name="messages",
        schema="notifications",
    )
    op.drop_table("messages", schema="notifications")
    op.execute("DROP SCHEMA notifications")
