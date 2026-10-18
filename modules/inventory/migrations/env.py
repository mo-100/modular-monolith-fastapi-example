from shared.alembic_support import run_module_migrations

from modules.inventory.models import Base

run_module_migrations(
    Base.metadata,
    schema="inventory",
    version_table="alembic_version_inventory",
)
