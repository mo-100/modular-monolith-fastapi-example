import logging
from uuid import uuid4

import pytest

from shared.event_bus import BusState, EventBusNotStarted, InProcessEventBus
from shared.events import OrderCancelled, OrderPlaced, StockReserved

from .helpers import EventCollector


async def test_multiple_consumers_receive_matching_events_only() -> None:
    bus = InProcessEventBus()
    await bus.start()
    calls: list[str] = []

    async def first(event: OrderCancelled) -> None:
        calls.append("first")

    async def second(event: OrderCancelled) -> None:
        calls.append("second")

    async def unrelated(event: OrderPlaced) -> None:
        calls.append("unrelated")

    bus.subscribe(OrderCancelled, first)
    bus.subscribe(OrderCancelled, second)
    bus.subscribe(OrderPlaced, unrelated)

    await bus.publish(OrderCancelled(order_id=uuid4()))

    assert calls == ["first", "second"]
    await bus.stop()


async def test_consumer_failure_is_logged_and_does_not_affect_others(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bus = InProcessEventBus()
    await bus.start()
    seen = EventCollector()

    async def failing(event: OrderCancelled) -> None:
        raise RuntimeError("consumer exploded")

    bus.subscribe(OrderCancelled, failing)
    bus.subscribe(OrderCancelled, seen)
    event = OrderCancelled(order_id=uuid4())

    with caplog.at_level(logging.ERROR, logger="shared.event_bus"):
        await bus.publish(event)

    assert seen.events == [event]
    assert "consumer exploded" in caplog.text
    assert "failed handling OrderCancelled" in caplog.text
    await bus.stop()


async def test_publish_before_start_is_a_wiring_error() -> None:
    bus = InProcessEventBus()
    with pytest.raises(EventBusNotStarted):
        await bus.publish(StockReserved(
            order_id=uuid4(),
            reservation_id=uuid4(),
            sku="SKU-1",
            quantity=1,
        ))


async def test_publish_after_stop_is_dropped_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bus = InProcessEventBus()
    await bus.start()
    seen = EventCollector()
    bus.subscribe(OrderCancelled, seen)
    await bus.stop()

    with caplog.at_level(logging.WARNING, logger="shared.event_bus"):
        await bus.publish(OrderCancelled(order_id=uuid4()))

    assert seen.events == []
    assert "dropping OrderCancelled" in caplog.text


async def test_lifecycle_is_idempotent() -> None:
    bus = InProcessEventBus()
    assert bus.state is BusState.CREATED
    await bus.start()
    await bus.start()
    assert bus.state is BusState.RUNNING
    await bus.stop()
    await bus.stop()
    assert bus.state is BusState.STOPPED
