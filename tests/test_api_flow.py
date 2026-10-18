import logging
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from shared.event_bus import BusState
from shared.events import (
    OrderCancelled,
    OrderPlaced,
    StockRejected,
    StockReleased,
    StockReserved,
)

from .helpers import EventCollector


async def _create_product(
    client, sku: str, quantity: int, price: str = "10.00"
) -> dict:
    response = await client.post(
        "/inventory/products",
        json={
            "sku": sku,
            "name": f"Product {sku}",
            "unit_price": price,
            "quantity": quantity,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _available(client, sku: str) -> int:
    response = await client.get(f"/inventory/products/{sku}")
    assert response.status_code == 200, response.text
    return response.json()["available"]


async def test_order_creation_notification_and_cancellation(
    app_client,
) -> None:
    app, client = app_client
    events = EventCollector()
    bus = app.state.context.bus
    for event_type in (
        OrderPlaced,
        OrderCancelled,
        StockReserved,
        StockReleased,
    ):
        bus.subscribe(event_type, events)

    await _create_product(client, "SKU-1", 5, "12.50")
    await _create_product(client, "SKU-2", 2, "3.00")

    response = await client.post(
        "/orders",
        json={
            "customer_id": "alice",
            "lines": [
                {"sku": "SKU-1", "quantity": 2},
                {"sku": "SKU-2", "quantity": 1},
            ],
        },
    )
    assert response.status_code == 201, response.text
    order = response.json()
    assert order["status"] == "placed"
    assert Decimal(order["total"]) == Decimal("28.00")
    assert await _available(client, "SKU-1") == 3
    assert await _available(client, "SKU-2") == 1

    assert len(events.of_type(StockReserved)) == 2
    placed = events.of_type(OrderPlaced)
    assert len(placed) == 1
    assert placed[0].order_id == UUID(order["id"])
    assert {event.sku for event in events.of_type(StockReserved)} == {
        "SKU-1",
        "SKU-2",
    }

    # Notifications is a third module that only subscribed to OrderPlaced.
    notifications = await client.get(f"/notifications/orders/{order['id']}")
    assert notifications.status_code == 200
    messages = notifications.json()
    assert len(messages) == 1
    assert "Product SKU-1" in messages[0]["message"]
    assert "Product SKU-2" in messages[0]["message"]

    cancel = await client.post(
        f"/orders/{order['id']}/cancel", params={"reason": "changed mind"}
    )
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()["status"] == "cancelled"
    assert await _available(client, "SKU-1") == 5
    assert await _available(client, "SKU-2") == 2

    released = events.of_type(StockReleased)
    assert len(released) == 2
    assert {event.reason for event in released} == {"order_cancelled"}
    cancelled = events.of_type(OrderCancelled)
    assert len(cancelled) == 1
    assert cancelled[0].reason == "changed mind"

    # Idempotent cancellation: no second release, no second event.
    again = await client.post(f"/orders/{order['id']}/cancel")
    assert again.status_code == 200
    assert len(events.of_type(StockReleased)) == 2
    assert len(events.of_type(OrderCancelled)) == 1


async def test_failed_second_reservation_compensates_the_first(
    app_client, caplog: pytest.LogCaptureFixture
) -> None:
    app, client = app_client
    events = EventCollector()
    bus = app.state.context.bus
    for event_type in (OrderPlaced, StockReserved, StockReleased, StockRejected):
        bus.subscribe(event_type, events)

    await _create_product(client, "SKU-1", 10)
    await _create_product(client, "SKU-2", 1)

    with caplog.at_level(logging.WARNING, logger="modules.orders.module"):
        response = await client.post(
            "/orders",
            json={
                "customer_id": "alice",
                "lines": [
                    {"sku": "SKU-1", "quantity": 2},
                    {"sku": "SKU-2", "quantity": 5},
                ],
            },
        )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["error"] == "insufficient_stock"
    assert await _available(client, "SKU-1") == 10
    assert await _available(client, "SKU-2") == 1

    reserved = events.of_type(StockReserved)
    released = events.of_type(StockReleased)
    rejected = events.of_type(StockRejected)
    assert [(event.sku, event.quantity) for event in reserved] == [("SKU-1", 2)]
    assert [(event.sku, event.quantity) for event in released] == [("SKU-1", 2)]
    assert released[0].reason == "order_creation_failed"
    assert rejected[0].sku == "SKU-2"
    assert events.of_type(OrderPlaced) == []

    # Orders consumes StockRejected for observability, not for state changes.
    assert "could not reserve SKU-2 x5" in caplog.text


async def test_failing_consumer_does_not_break_order_creation(
    app_client, caplog: pytest.LogCaptureFixture
) -> None:
    app, client = app_client
    bus = app.state.context.bus

    async def failing_notification(event: OrderPlaced) -> None:
        raise RuntimeError("notification backend unavailable")

    bus.subscribe(OrderPlaced, failing_notification)
    await _create_product(client, "SKU-1", 2)

    with caplog.at_level(logging.ERROR, logger="shared.event_bus"):
        response = await client.post(
            "/orders",
            json={
                "customer_id": "alice",
                "lines": [{"sku": "SKU-1", "quantity": 1}],
            },
        )

    assert response.status_code == 201, response.text
    assert "notification backend unavailable" in caplog.text

    # The real notification consumer still ran.
    notifications = await client.get(
        f"/notifications/orders/{response.json()['id']}"
    )
    assert len(notifications.json()) == 1


async def test_unknown_product_returns_404_without_reserving(app_client) -> None:
    app, client = app_client
    events = EventCollector()
    app.state.context.bus.subscribe(StockReserved, events)

    response = await client.post(
        "/orders",
        json={
            "customer_id": "alice",
            "lines": [{"sku": "NOPE", "quantity": 1}],
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "product_not_found"
    assert events.events == []


async def test_inventory_and_order_api_errors(app_client) -> None:
    _, client = app_client
    await _create_product(client, "SKU-1", 1)

    duplicate = await client.post(
        "/inventory/products",
        json={
            "sku": "SKU-1",
            "name": "Duplicate",
            "unit_price": "1.00",
            "quantity": 1,
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["error"] == "duplicate_sku"

    missing = await client.get("/inventory/products/MISSING")
    assert missing.status_code == 404

    missing_order = await client.get(f"/orders/{uuid4()}")
    assert missing_order.status_code == 404


async def test_shutdown_stops_the_event_bus(
    context, caplog: pytest.LogCaptureFixture
) -> None:
    from main import build_modules, create_app

    app = create_app(context, build_modules(context))
    async with app.router.lifespan_context(app):
        assert context.bus.state is BusState.RUNNING
    assert context.bus.state is BusState.STOPPED

    events = EventCollector()
    context.bus.subscribe(OrderCancelled, events)
    with caplog.at_level(logging.WARNING, logger="shared.event_bus"):
        await context.bus.publish(OrderCancelled(order_id=uuid4()))

    assert events.events == []
    assert "dropping OrderCancelled" in caplog.text
