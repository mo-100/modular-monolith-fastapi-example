from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from modules.inventory.contract import (
    InsufficientStock,
    Product,
    ProductNotFound,
    Reservation,
)
from modules.inventory.models import Product as ProductModel
from modules.inventory.models import StockReservation
from modules.inventory.repository import InventoryRepository
from shared.event_bus import EventPublisher
from shared.events import StockRejected, StockReleased, StockReserved


class DuplicateSku(Exception):
    """Inventory-internal error surfaced by its HTTP API."""

    def __init__(self, sku: str) -> None:
        self.sku = sku
        super().__init__(f"Product {sku!r} already exists")


class SqlInventoryService:
    """SQLAlchemy implementation of Inventory's public contract.

    This class is private to Inventory. Consumers depend on the
    ``InventoryService`` protocol, which this class satisfies structurally.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        bus: EventPublisher,
    ) -> None:
        self._session_factory = session_factory
        self._bus = bus

    async def get_product(self, sku: str) -> Product | None:
        async with self._session_factory() as session:
            product = await InventoryRepository(session).get_product(sku)
            return None if product is None else _to_contract(product)

    async def list_products(self) -> list[Product]:
        async with self._session_factory() as session:
            products = await InventoryRepository(session).list_products()
            return [_to_contract(product) for product in products]

    async def check_availability(self, sku: str, quantity: int) -> bool:
        product = await self.get_product(sku)
        return product is not None and product.available >= quantity

    async def create_product(
        self,
        sku: str,
        name: str,
        unit_price: Decimal,
        quantity: int,
    ) -> Product:
        try:
            async with self._session_factory() as session, session.begin():
                repository = InventoryRepository(session)
                if await repository.get_product(sku) is not None:
                    raise DuplicateSku(sku)
                product = ProductModel(
                    sku=sku,
                    name=name,
                    unit_price=unit_price,
                    quantity_on_hand=quantity,
                )
                await repository.add_product(product)
        except IntegrityError as exc:
            # Concurrent create: the primary key is the final arbiter.
            raise DuplicateSku(sku) from exc
        return _to_contract(product)

    async def reserve(
        self, order_id: UUID, sku: str, quantity: int
    ) -> Reservation:
        if quantity <= 0:
            raise ValueError("quantity must be positive")

        try:
            async with self._session_factory() as session, session.begin():
                repository = InventoryRepository(session)
                product = await repository.get_product_for_update(sku)
                if product is None:
                    raise ProductNotFound(sku)
                if product.available < quantity:
                    raise InsufficientStock(sku, quantity, product.available)

                reservation = StockReservation(
                    order_id=order_id, sku=sku, quantity=quantity
                )
                product.quantity_reserved += quantity
                repository.add_reservation(reservation)
        except InsufficientStock as exc:
            # Publish after the failed transaction has rolled back. Consumers
            # see the rejection even though the caller receives an exception.
            await self._bus.publish(
                StockRejected(
                    order_id=order_id,
                    sku=exc.sku,
                    requested=exc.requested,
                    available=exc.available,
                )
            )
            raise

        await self._bus.publish(
            StockReserved(
                order_id=order_id,
                reservation_id=reservation.id,
                sku=sku,
                quantity=quantity,
            )
        )
        return _to_reservation(reservation)

    async def release_for_order(
        self, order_id: UUID, reason: str = "order_cancelled"
    ) -> int:
        released: list[StockReservation] = []
        async with self._session_factory() as session, session.begin():
            repository = InventoryRepository(session)
            reservations = await repository.active_reservations_for_order(order_id)
            now = datetime.now(UTC)
            for reservation in reservations:
                product = await repository.get_product_for_update(reservation.sku)
                if product is None:  # Defensive: FK prevents this.
                    continue
                product.quantity_reserved -= reservation.quantity
                reservation.released_at = now
                released.append(reservation)

        for reservation in released:
            await self._bus.publish(
                StockReleased(
                    order_id=order_id,
                    reservation_id=reservation.id,
                    sku=reservation.sku,
                    quantity=reservation.quantity,
                    reason=reason,
                )
            )
        return len(released)


def _to_contract(product: ProductModel) -> Product:
    return Product(
        sku=product.sku,
        name=product.name,
        unit_price=product.unit_price,
        available=product.available,
    )


def _to_reservation(reservation: StockReservation) -> Reservation:
    return Reservation(
        id=reservation.id,
        order_id=reservation.order_id,
        sku=reservation.sku,
        quantity=reservation.quantity,
    )
