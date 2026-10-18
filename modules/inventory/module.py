import logging

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from modules.inventory.api import build_router
from modules.inventory.service import SqlInventoryService
from shared.event_bus import EventBus
from shared.events import OrderCancelled

logger = logging.getLogger(__name__)


class InventoryModule:
    name = "inventory"

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        bus: EventBus,
    ) -> None:
        self._bus = bus
        self.service = SqlInventoryService(session_factory, bus)
        self.router: APIRouter = build_router(self.service)

    def register(self) -> None:
        # Reconciliation safety net: Orders releases stock through the direct
        # contract call, but if a cancellation is observed through the event
        # stream with stock still reserved (for example after a partial
        # failure), Inventory cleans it up. Release is idempotent.
        self._bus.subscribe(OrderCancelled, self._on_order_cancelled)

    async def _on_order_cancelled(self, event: OrderCancelled) -> None:
        released = await self.service.release_for_order(
            event.order_id, reason="order_cancelled_event_safety_net"
        )
        if released:
            logger.warning(
                "Safety net released %d reservation(s) for cancelled order %s",
                released,
                event.order_id,
            )

    async def startup(self) -> None:
        logger.info("Inventory module started")

    async def shutdown(self) -> None:
        logger.info("Inventory module stopped")
