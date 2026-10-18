from decimal import Decimal
from uuid import uuid4

import pytest

from modules.inventory.contract import InsufficientStock, ProductNotFound
from modules.inventory.module import InventoryModule
from modules.inventory.service import DuplicateSku, SqlInventoryService
from shared.events import (
    OrderCancelled,
    StockRejected,
    StockReleased,
    StockReserved,
)

from .helpers import EventCollector


@pytest.fixture
def inventory(session_factory, bus) -> SqlInventoryService:
    return SqlInventoryService(session_factory, bus)


async def test_reserve_and_release_update_availability(
    inventory: SqlInventoryService, bus
) -> None:
    events = EventCollector()
    bus.subscribe(StockReserved, events)
    bus.subscribe(StockReleased, events)

    await inventory.create_product("SKU-1", "Widget", Decimal("12.50"), 5)
    order_id = uuid4()

    reservation = await inventory.reserve(order_id, "SKU-1", 2)
    assert reservation.order_id == order_id
    assert (await inventory.get_product("SKU-1")).available == 3
    assert await inventory.check_availability("SKU-1", 3)
    assert not await inventory.check_availability("SKU-1", 4)

    assert await inventory.release_for_order(order_id) == 1
    assert (await inventory.get_product("SKU-1")).available == 5
    assert await inventory.release_for_order(order_id) == 0

    reserved = events.of_type(StockReserved)
    released = events.of_type(StockReleased)
    assert [(event.sku, event.quantity) for event in reserved] == [("SKU-1", 2)]
    assert [(event.sku, event.quantity) for event in released] == [("SKU-1", 2)]
    assert released[0].reason == "order_cancelled"


async def test_rejection_rolls_back_and_publishes_event(
    inventory: SqlInventoryService, bus
) -> None:
    events = EventCollector()
    bus.subscribe(StockRejected, events)
    await inventory.create_product("SKU-1", "Widget", Decimal("1.00"), 2)

    with pytest.raises(InsufficientStock) as raised:
        await inventory.reserve(uuid4(), "SKU-1", 3)

    assert raised.value.available == 2
    assert (await inventory.get_product("SKU-1")).available == 2
    rejection = events.of_type(StockRejected)[0]
    assert (rejection.sku, rejection.requested, rejection.available) == (
        "SKU-1",
        3,
        2,
    )


async def test_unknown_product_is_rejected_without_reserving(
    inventory: SqlInventoryService,
) -> None:
    with pytest.raises(ProductNotFound):
        await inventory.reserve(uuid4(), "MISSING", 1)


async def test_duplicate_sku_is_rejected(inventory: SqlInventoryService) -> None:
    await inventory.create_product("SKU-1", "Widget", Decimal("1.00"), 1)
    with pytest.raises(DuplicateSku):
        await inventory.create_product("SKU-1", "Other", Decimal("2.00"), 1)


async def test_inventory_consumes_order_cancelled_as_a_safety_net(
    session_factory, bus
) -> None:
    """Inventory consumes shared events without importing Orders.

    Orders normally releases stock through the direct contract call. This test
    bypasses that path and shows the reconciliation consumer still frees stock
    when a cancellation is observed on the event stream.
    """
    module = InventoryModule(session_factory, bus)
    module.register()
    released_events = EventCollector()
    bus.subscribe(StockReleased, released_events)

    await module.service.create_product(
        "SKU-1", "Widget", Decimal("1.00"), 3
    )
    order_id = uuid4()
    await module.service.reserve(order_id, "SKU-1", 2)
    assert (await module.service.get_product("SKU-1")).available == 1

    await bus.publish(OrderCancelled(order_id=order_id))

    assert (await module.service.get_product("SKU-1")).available == 3
    released = released_events.of_type(StockReleased)
    assert len(released) == 1
    assert released[0].reason == "order_cancelled_event_safety_net"
