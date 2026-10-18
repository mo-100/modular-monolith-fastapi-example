"""Order workflows.

Cross-module transactions do not exist here. Creating an order is a small
saga:

1. price lines via Inventory's contract (read-only);
2. reserve each line; each reservation commits inside Inventory;
3. persist the order in the `orders` schema;
4. publish ``OrderPlaced`` only after the order commit.

If step 3 fails, step 2 is explicitly compensated through Inventory's public
``release_for_order`` operation. Cancellation releases stock directly (an
immediate result is needed) and then marks the order cancelled.

Compensation is retry-safe but not durable: if the compensation call itself
fails, the failure is logged and stock remains reserved until reconciled. A
production system would add a retry queue or transactional outbox.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from modules.inventory.contract import InventoryService
from modules.orders.models import Order, OrderLine, OrderStatus
from modules.orders.repository import OrdersRepository
from shared.event_bus import EventPublisher
from shared.events import OrderCancelled, OrderLinePayload, OrderPlaced

logger = logging.getLogger(__name__)


class UnknownProduct(Exception):
    def __init__(self, sku: str) -> None:
        self.sku = sku
        super().__init__(f"Unknown SKU {sku!r}")


class OrderNotFound(Exception):
    def __init__(self, order_id: UUID) -> None:
        self.order_id = order_id
        super().__init__(f"Order {order_id} does not exist")


class InvalidOrderState(Exception):
    def __init__(self, order_id: UUID, status: str) -> None:
        self.order_id = order_id
        self.status = status
        super().__init__(f"Order {order_id} cannot be cancelled from {status!r}")


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderLineInput:
    sku: str
    quantity: int


class OrdersService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        bus: EventPublisher,
        inventory: InventoryService,
    ) -> None:
        self._session_factory = session_factory
        self._bus = bus
        self._inventory = inventory

    async def create_order(
        self, customer_id: str, lines: list[OrderLineInput]
    ) -> Order:
        if not lines:
            raise ValueError("an order needs at least one line")

        order_id = uuid4()

        # Price first so a missing product fails before anything is reserved.
        priced: list[tuple[str, int, Decimal]] = []
        for line in lines:
            product = await self._inventory.get_product(line.sku)
            if product is None:
                raise UnknownProduct(line.sku)
            priced.append((line.sku, line.quantity, product.unit_price))

        total = sum(
            (unit_price * quantity for _, quantity, unit_price in priced),
            Decimal("0"),
        )
        order = Order(
            id=order_id,
            customer_id=customer_id,
            status=OrderStatus.PLACED,
            total=total,
            lines=[
                OrderLine(sku=sku, quantity=quantity, unit_price=unit_price)
                for sku, quantity, unit_price in priced
            ],
        )

        try:
            for sku, quantity, _ in priced:
                await self._inventory.reserve(order_id, sku, quantity)
        except Exception:
            # The failing line never committed; earlier lines did, and an
            # infrastructure failure may also leave them behind.
            await self._compensate(order_id, "order_creation_failed")
            raise

        try:
            await self._persist(order)
        except Exception:
            await self._compensate(order_id, "order_creation_failed")
            raise

        await self._bus.publish(
            OrderPlaced(
                order_id=order.id,
                customer_id=order.customer_id,
                total=order.total,
                lines=tuple(
                    OrderLinePayload(
                        sku=line.sku,
                        quantity=line.quantity,
                        unit_price=line.unit_price,
                    )
                    for line in order.lines
                ),
            )
        )
        return order

    async def get_order(self, order_id: UUID) -> Order:
        async with self._session_factory() as session:
            order = await OrdersRepository(session).get(order_id)
        if order is None:
            raise OrderNotFound(order_id)
        return order

    async def cancel_order(
        self, order_id: UUID, reason: str | None = None
    ) -> Order:
        order = await self.get_order(order_id)
        if order.status == OrderStatus.CANCELLED:
            return order
        if order.status != OrderStatus.PLACED:
            raise InvalidOrderState(order_id, order.status)

        # Direct call: cancellation needs an immediate, authoritative result.
        # If this fails nothing in Orders changes and the client can retry.
        await self._inventory.release_for_order(
            order_id, reason="order_cancelled"
        )

        order, changed = await self._mark_cancelled(order_id)
        if changed:
            await self._bus.publish(
                OrderCancelled(order_id=order_id, reason=reason)
            )
        return order

    async def _persist(self, order: Order) -> None:
        async with self._session_factory() as session, session.begin():
            await OrdersRepository(session).add(order)

    async def _mark_cancelled(self, order_id: UUID) -> tuple[Order, bool]:
        """Return the order and whether this call performed the transition."""
        async with self._session_factory() as session, session.begin():
            order = await OrdersRepository(session).get_for_update(order_id)
            if order is None:
                raise OrderNotFound(order_id)
            if order.status == OrderStatus.CANCELLED:
                return order, False
            if order.status != OrderStatus.PLACED:
                raise InvalidOrderState(order_id, order.status)
            order.status = OrderStatus.CANCELLED
            order.cancelled_at = datetime.now(UTC)
            return order, True

    async def _compensate(self, order_id: UUID, reason: str) -> None:
        try:
            released = await self._inventory.release_for_order(
                order_id, reason=reason
            )
            logger.warning(
                "Compensated failed order %s by releasing %d reservation(s)",
                order_id,
                released,
            )
        except Exception:
            # Never mask the original failure; surface the stuck reservation.
            logger.exception(
                "Compensation failed for order %s; stock may remain reserved",
                order_id,
            )
