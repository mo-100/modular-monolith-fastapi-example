"""A higher-level module reacting to Orders without Orders knowing about it.

It consumes ``OrderPlaced`` and also calls Inventory's public contract to
enrich the message with product names. Inventory and Orders are unchanged by
this module's existence.
"""

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from modules.inventory.contract import InventoryService
from modules.notifications.models import Notification
from shared.events import OrderPlaced

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        inventory: InventoryService,
    ) -> None:
        self._session_factory = session_factory
        self._inventory = inventory

    async def on_order_placed(self, event: OrderPlaced) -> None:
        descriptions: list[str] = []
        for line in event.lines:
            product = await self._inventory.get_product(line.sku)
            name = product.name if product is not None else line.sku
            descriptions.append(f"{line.quantity}x {name}")

        message = (
            f"Order {event.order_id} for {event.customer_id} placed: "
            + ", ".join(descriptions)
        )
        async with self._session_factory() as session, session.begin():
            session.add(Notification(order_id=event.order_id, message=message))
        logger.info(message)

    async def list_for_order(self, order_id: UUID) -> list[Notification]:
        async with self._session_factory() as session:
            result = await session.scalars(
                select(Notification)
                .where(Notification.order_id == order_id)
                .order_by(Notification.created_at)
            )
            return list(result)
