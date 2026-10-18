import logging

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from modules.inventory.contract import InventoryService
from modules.orders.api import build_router
from modules.orders.service import OrdersService
from shared.event_bus import EventBus
from shared.events import StockRejected

logger = logging.getLogger(__name__)


class OrdersModule:
    name = "orders"

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        bus: EventBus,
        inventory: InventoryService,
    ) -> None:
        self._bus = bus
        self.service = OrdersService(session_factory, bus, inventory)
        self.router: APIRouter = build_router(self.service)

    def register(self) -> None:
        # Observability reaction only. The authoritative rejection is the
        # synchronous contract exception; this consumer must not change state.
        self._bus.subscribe(StockRejected, self._on_stock_rejected)

    async def _on_stock_rejected(self, event: StockRejected) -> None:
        logger.warning(
            "Order %s could not reserve %s x%d (only %d available)",
            event.order_id,
            event.sku,
            event.requested,
            event.available,
        )

    async def startup(self) -> None:
        logger.info("Orders module started")

    async def shutdown(self) -> None:
        logger.info("Orders module stopped")
