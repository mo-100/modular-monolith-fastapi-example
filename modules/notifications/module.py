import logging

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from modules.inventory.contract import InventoryService
from modules.notifications.api import build_router
from modules.notifications.service import NotificationService
from shared.event_bus import EventBus
from shared.events import OrderPlaced

logger = logging.getLogger(__name__)


class NotificationsModule:
    name = "notifications"

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        bus: EventBus,
        inventory: InventoryService,
    ) -> None:
        self._bus = bus
        self.service = NotificationService(session_factory, inventory)
        self.router: APIRouter = build_router(self.service)

    def register(self) -> None:
        self._bus.subscribe(OrderPlaced, self.service.on_order_placed)

    async def startup(self) -> None:
        logger.info("Notifications module started")

    async def shutdown(self) -> None:
        logger.info("Notifications module stopped")
