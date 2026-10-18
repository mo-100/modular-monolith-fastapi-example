from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.inventory.models import Product, StockReservation


class InventoryRepository:
    """Inventory-private persistence. Never imported outside this module."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_product(self, sku: str) -> Product | None:
        return await self._session.get(Product, sku)

    async def get_product_for_update(self, sku: str) -> Product | None:
        return await self._session.get(Product, sku, with_for_update=True)

    async def list_products(self) -> list[Product]:
        result = await self._session.scalars(select(Product).order_by(Product.sku))
        return list(result)

    async def add_product(self, product: Product) -> None:
        self._session.add(product)

    async def active_reservations_for_order(
        self, order_id: UUID
    ) -> list[StockReservation]:
        result = await self._session.scalars(
            select(StockReservation)
            .where(
                StockReservation.order_id == order_id,
                StockReservation.released_at.is_(None),
            )
            # Deterministic lock order reduces deadlock risk during release.
            .order_by(StockReservation.sku)
            .with_for_update()
        )
        return list(result)

    def add_reservation(self, reservation: StockReservation) -> None:
        self._session.add(reservation)
