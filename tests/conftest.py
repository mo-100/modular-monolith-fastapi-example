import asyncio
import os

import asyncpg
import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from main import AppContext, build_modules, create_app
from scripts.migrate import MODULES, upgrade_module
from shared.config import Settings
from shared.event_bus import InProcessEventBus

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:55432/modular_monolith_test",
)

TRUNCATE = text(
    "TRUNCATE notifications.messages, orders.order_lines, orders.orders, "
    "inventory.stock_reservations, inventory.products "
    "RESTART IDENTITY CASCADE"
)


async def _ensure_database(url: str) -> None:
    dsn = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    admin_dsn, database = dsn.rsplit("/", 1)
    connection = await asyncpg.connect(f"{admin_dsn}/postgres")
    try:
        exists = await connection.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", database
        )
        if not exists:
            await connection.execute(f'CREATE DATABASE "{database}"')
    finally:
        await connection.close()


@pytest.fixture(scope="session")
def database_url() -> str:
    try:
        asyncio.run(_ensure_database(TEST_DATABASE_URL))
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.exit(
            f"PostgreSQL is not reachable at {TEST_DATABASE_URL} ({exc}). "
            "Run `make db-up` first.",
            returncode=2,
        )
    # Tests exercise the real migrations, not metadata.create_all.
    for module in MODULES:
        upgrade_module(module, TEST_DATABASE_URL)
    return TEST_DATABASE_URL


@pytest.fixture
def settings(database_url: str) -> Settings:
    return Settings(database_url=database_url)


@pytest.fixture
async def engine(database_url: str) -> AsyncEngine:
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(TRUNCATE)
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def bus() -> InProcessEventBus:
    bus = InProcessEventBus()
    await bus.start()
    yield bus
    await bus.stop()


@pytest.fixture
def context(
    settings: Settings,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    bus: InProcessEventBus,
) -> AppContext:
    return AppContext(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        bus=bus,
    )


@pytest.fixture
async def app_client(context: AppContext):
    modules = build_modules(context)
    app = create_app(context, modules)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield app, client
