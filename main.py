"""Composition root: one app, one process, explicit module wiring.

Removing a module means deleting its package and its two lines here (import and
construction) plus its migrations. No other business module changes.

Run with: uvicorn main:create_app --factory --reload
"""

import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from modules.inventory.module import InventoryModule
from modules.notifications.module import NotificationsModule
from modules.orders.module import OrdersModule
from shared.config import Settings, get_settings
from shared.database import create_engine, create_session_factory
from shared.event_bus import InProcessEventBus
from shared.module import Module

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AppContext:
    """Shared infrastructure handed to modules by the composition root."""

    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    bus: InProcessEventBus


def create_context(settings: Settings | None = None) -> AppContext:
    settings = settings or get_settings()
    engine = create_engine(settings.database_url)
    return AppContext(
        settings=settings,
        engine=engine,
        session_factory=create_session_factory(engine),
        bus=InProcessEventBus(),
    )


def build_modules(context: AppContext) -> list[Module]:
    # Dependency direction is explicit at the composition root:
    # Orders and Notifications depend on Inventory's public contract.
    inventory = InventoryModule(context.session_factory, context.bus)
    orders = OrdersModule(context.session_factory, context.bus, inventory.service)
    notifications = NotificationsModule(context.session_factory, context.bus, inventory.service)
    return [inventory, orders, notifications]


def create_app(
    context: AppContext | None = None,
    modules: Sequence[Module] | None = None,
) -> FastAPI:
    context = context or create_context()
    installed = list(modules) if modules is not None else build_modules(context)

    # Subscription registration is explicit and happens once, before startup.
    for module in installed:
        module.register()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await context.bus.start()
        try:
            for module in installed:
                await module.startup()
            yield
        finally:
            # Reverse order, then stop the bus, then release DB connections.
            # One failing hook must not prevent the rest of shutdown.
            for module in reversed(installed):
                try:
                    await module.shutdown()
                except Exception:
                    logger.exception("Module %s failed during shutdown", module.name)
            await context.bus.stop()
            await context.engine.dispose()

    app = FastAPI(title="Modular Monolith", lifespan=lifespan)
    for module in installed:
        app.include_router(module.router)

    app.state.context = context
    app.state.modules = installed
    return app
