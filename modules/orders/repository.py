from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from modules.orders.models import Order


class OrdersRepository:
    """Orders-private persistence. Never imported outside this module."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, order_id: UUID) -> Order | None:
        return await self._session.get(Order, order_id)

    async def get_for_update(self, order_id: UUID) -> Order | None:
        return await self._session.get(Order, order_id, with_for_update=True)

    async def add(self, order: Order) -> None:
        self._session.add(order)
