from shared.alembic_support import run_module_migrations

from modules.notifications.models import Base

run_module_migrations(
    Base.metadata,
    schema="notifications",
    version_table="alembic_version_notifications",
)
