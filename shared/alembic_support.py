"""Generic Alembic runner used by each module's own ``migrations/env.py``.

Migrations stay module-owned: each module has its own ``versions/`` directory,
its own metadata, its own schema and its own version table. Only the async
boilerplate is shared.
"""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import MetaData, pool
from sqlalchemy.ext.asyncio import async_engine_from_config


def run_module_migrations(
    metadata: MetaData, *, schema: str, version_table: str
) -> None:
    def include_name(
        name: str | None, type_: str, parent_names: dict[str, str | None]
    ) -> bool:
        if type_ == "schema":
            # Only autogenerate against the module's own schema.
            return name is None or name == schema
        return True

    def configure(**kwargs: object) -> None:
        context.configure(
            target_metadata=metadata,
            include_schemas=True,
            include_name=include_name,
            compare_type=True,
            version_table=version_table,
            version_table_schema="public",
            **kwargs,
        )

    if context.is_offline_mode():
        configure(
            url=context.config.get_main_option("sqlalchemy.url"),
            literal_binds=True,
            dialect_opts={"paramstyle": "named"},
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    def run_sync_migrations(connection: object) -> None:
        configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()

    async def run_async_migrations() -> None:
        connectable = async_engine_from_config(
            context.config.get_section(context.config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )
        async with connectable.connect() as connection:
            await connection.run_sync(run_sync_migrations)
        await connectable.dispose()

    asyncio.run(run_async_migrations())
