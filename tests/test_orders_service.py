"""Orders depends only on Inventory's protocol.

These tests inject a hand-written contract implementation, proving Orders can
work after arbitrary internal Inventory refactoring (or with a remote adapter)
as long as the contract is honoured.
"""

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from modules.inventory.contract import InsufficientStock, Product, Reservation
from modules.inventory.service import SqlInventoryService
from modules.orders.models import Order, OrderStatus
from modules.orders.service import (
    OrderLineInput,
    OrdersService,
    UnknownProduct,
)
from shared.events import OrderCancelled, OrderPlaced, StockReleased

from .helpers import EventCollector


class FakeInventory:
    def __init__(self) -> None:
        self.available = {"SKU-1": 10, "SKU-2": 1}
        self.prices = {"SKU-1": Decimal("10.00"), "SKU-2": Decimal("5.00")}
        self.reservations: list[tuple[UUID, str, int]] = []
        self.releases: list[tuple[UUID, str]] = []

    async def get_product(self, sku: str) -> Product | None:
        if sku not in self.prices:
            return None
        return Product(
            sku=sku,
            name=f"Product {sku}",
            unit_price=self.prices[sku],
            available=self.available[sku],
        )

    async def check_availability(self, sku: str, quantity: int) -> bool:
        return sku in self.available and self.available[sku] >= quantity

    async def reserve(
        self, order_id: UUID, sku: str, quantity: int
    ) -> Reservation:
        if quantity > self.available.get(sku, 0):
            raise InsufficientStock(sku, quantity, self.available.get(sku, 0))
        self.available[sku] -= quantity
        self.reservations.append((order_id, sku, quantity))
        return Reservation(
            id=uuid4(), order_id=order_id, sku=sku, quantity=quantity
        )

    async def release_for_order(
        self, order_id: UUID, reason: str = "order_cancelled"
    ) -> int:
        released = [r for r in self.reservations if r[0] == order_id]
        self.reservations = [r for r in self.reservations if r[0] != order_id]
        for _, sku, quantity in released:
            self.available[sku] += quantity
        self.releases.append((order_id, reason))
        return len(released)


class FailingPersistenceOrdersService(OrdersService):
    async def _persist(self, order: Order) -> None:
        raise RuntimeError("orders database unavailable")


@pytest.fixture
def fake_inventory() -> FakeInventory:
    return FakeInventory()


async def test_create_order_uses_only_the_public_contract(
    session_factory, bus, fake_inventory: FakeInventory
) -> None:
    events = EventCollector()
    bus.subscribe(OrderPlaced, events)
    service = OrdersService(session_factory, bus, fake_inventory)

    order = await service.create_order(
        "alice", [OrderLineInput(sku="SKU-1", quantity=2)]
    )

    assert order.status == OrderStatus.PLACED
    assert order.total == Decimal("20.00")
    assert fake_inventory.reservations == [(order.id, "SKU-1", 2)]

    persisted = await service.get_order(order.id)
    assert persisted.id == order.id
    assert [(line.sku, line.quantity) for line in persisted.lines] == [
        ("SKU-1", 2)
    ]

    placed = events.of_type(OrderPlaced)
    assert len(placed) == 1
    assert placed[0].order_id == order.id
    assert placed[0].lines[0].sku == "SKU-1"


async def test_failure_after_reservation_compensates_stock(
    session_factory, bus, fake_inventory: FakeInventory
) -> None:
    service = FailingPersistenceOrdersService(
        session_factory, bus, fake_inventory
    )

    with pytest.raises(RuntimeError, match="orders database unavailable"):
        await service.create_order(
            "alice", [OrderLineInput(sku="SKU-1", quantity=3)]
        )

    assert fake_inventory.available["SKU-1"] == 10
    assert fake_inventory.releases[0][1] == "order_creation_failed"

    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(Order))
    assert count == 0


async def test_persistence_failure_with_real_inventory_releases_stock(
    session_factory, bus
) -> None:
    inventory = SqlInventoryService(session_factory, bus)
    await inventory.create_product("SKU-1", "Widget", Decimal("5.00"), 4)
    releases = EventCollector()
    bus.subscribe(StockReleased, releases)

    service = FailingPersistenceOrdersService(session_factory, bus, inventory)
    with pytest.raises(RuntimeError, match="orders database unavailable"):
        await service.create_order(
            "alice", [OrderLineInput(sku="SKU-1", quantity=2)]
        )

    assert (await inventory.get_product("SKU-1")).available == 4
    assert releases.of_type(StockReleased)[0].reason == "order_creation_failed"

    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(Order))
    assert count == 0


async def test_cancellation_releases_stock_and_is_idempotent(
    session_factory, bus, fake_inventory: FakeInventory
) -> None:
    events = EventCollector()
    bus.subscribe(OrderCancelled, events)
    service = OrdersService(session_factory, bus, fake_inventory)

    order = await service.create_order(
        "alice", [OrderLineInput(sku="SKU-1", quantity=2)]
    )
    cancelled = await service.cancel_order(order.id, reason="changed mind")

    assert cancelled.status == OrderStatus.CANCELLED
    assert cancelled.cancelled_at is not None
    assert fake_inventory.available["SKU-1"] == 10
    assert fake_inventory.releases == [(order.id, "order_cancelled")]
    assert events.of_type(OrderCancelled)[0].reason == "changed mind"

    # Second cancellation is a no-op: no extra release and no extra event.
    again = await service.cancel_order(order.id)
    assert again.status == OrderStatus.CANCELLED

    assert len(fake_inventory.releases) == 1
    assert len(events.of_type(OrderCancelled)) == 1


async def test_unknown_product_fails_before_reserving(
    session_factory, bus, fake_inventory: FakeInventory
) -> None:
    service = OrdersService(session_factory, bus, fake_inventory)

    with pytest.raises(UnknownProduct):
        await service.create_order(
            "alice", [OrderLineInput(sku="NOPE", quantity=1)]
        )

    assert fake_inventory.reservations == []
    assert fake_inventory.releases == []
