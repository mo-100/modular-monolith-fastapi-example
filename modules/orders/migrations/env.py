from shared.alembic_support import run_module_migrations

from modules.orders.models import Base

run_module_migrations(
    Base.metadata,
    schema="orders",
    version_table="alembic_version_orders",
)
