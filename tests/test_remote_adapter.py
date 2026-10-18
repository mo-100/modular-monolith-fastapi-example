"""Proof that Inventory's contract can move over HTTP without touching Orders logic.

The exact same ``OrdersService`` class is constructed with ``HttpInventoryClient``
instead of the in-process implementation. Inventory runs as a separate ASGI app
with its own event bus, mirroring a future deployment boundary.
"""

from decimal import Decimal
from uuid import uuid4

import httpx
import pytest

from main import AppContext, create_app
from modules.inventory.contract import InsufficientStock
from modules.inventory.module import InventoryModule
from modules.orders.inventory_client import HttpInventoryClient
from modules.orders.service import OrderLineInput, OrdersService
from shared.event_bus import InProcessEventBus
from shared.events import StockReserved

from .helpers import EventCollector


async def test_http_adapter_replaces_in_process_contract(
    settings, engine, session_factory
) -> None:
    inventory_bus = InProcessEventBus()
    inventory_context = AppContext(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        bus=inventory_bus,
    )
    inventory_app = create_app(
        inventory_context, [InventoryModule(session_factory, inventory_bus)]
    )
    inventory_events = EventCollector()
    inventory_bus.subscribe(StockReserved, inventory_events)

    orders_bus = InProcessEventBus()
    await orders_bus.start()

    async with inventory_app.router.lifespan_context(inventory_app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=inventory_app),
            base_url="http://inventory",
        ) as http:
            created = await http.post(
                "/inventory/products",
                json={
                    "sku": "REMOTE-1",
                    "name": "Remote Widget",
                    "unit_price": "9.99",
                    "quantity": 3,
                },
            )
            assert created.status_code == 201, created.text

            adapter = HttpInventoryClient(http)
            service = OrdersService(session_factory, orders_bus, adapter)

            order = await service.create_order(
                "bob", [OrderLineInput(sku="REMOTE-1", quantity=2)]
            )
            assert order.total == Decimal("19.98")

            stock = await http.get("/inventory/products/REMOTE-1")
            assert stock.json()["available"] == 1

            # Inventory's events stayed inside the inventory application;
            # cross-service delivery would need a broker.
            assert len(inventory_events.of_type(StockReserved)) == 1

            with pytest.raises(InsufficientStock) as raised:
                await adapter.reserve(uuid4(), "REMOTE-1", 99)
            assert raised.value.available == 1

            await service.cancel_order(order.id, reason="remote cancel")
            stock = await http.get("/inventory/products/REMOTE-1")
            assert stock.json()["available"] == 3

    await orders_bus.stop()
