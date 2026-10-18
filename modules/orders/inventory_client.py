"""Extraction seam: Inventory's public contract over HTTP.

This adapter implements ``InventoryService`` by calling Inventory's HTTP API.
``OrdersService`` is constructed with it exactly like the in-process
implementation, so business logic does not change when Inventory moves to its
own deployment. The client is supplied by the caller so transport, base URL,
timeouts and auth policy remain infrastructure concerns.
"""

from decimal import Decimal
from urllib.parse import quote
from uuid import UUID

import httpx

from modules.inventory.contract import (
    InsufficientStock,
    Product,
    ProductNotFound,
    Reservation,
)


class HttpInventoryClient:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def get_product(self, sku: str) -> Product | None:
        response = await self._client.get(f"/inventory/products/{quote(sku)}")
        if response.status_code == httpx.codes.NOT_FOUND:
            return None
        response.raise_for_status()
        body = response.json()
        return Product(
            sku=body["sku"],
            name=body["name"],
            unit_price=Decimal(str(body["unit_price"])),
            available=body["available"],
        )

    async def check_availability(self, sku: str, quantity: int) -> bool:
        response = await self._client.get(
            f"/inventory/availability/{quote(sku)}",
            params={"quantity": quantity},
        )
        response.raise_for_status()
        return bool(response.json()["available"])

    async def reserve(
        self, order_id: UUID, sku: str, quantity: int
    ) -> Reservation:
        response = await self._client.post(
            "/inventory/reservations",
            json={
                "order_id": str(order_id),
                "sku": sku,
                "quantity": quantity,
            },
        )
        if response.status_code == httpx.codes.CONFLICT:
            detail = response.json().get("detail", {})
            if detail.get("error") == "insufficient_stock":
                raise InsufficientStock(
                    detail["sku"], detail["requested"], detail["available"]
                )
        if response.status_code == httpx.codes.NOT_FOUND:
            raise ProductNotFound(sku)
        response.raise_for_status()
        body = response.json()
        return Reservation(
            id=UUID(body["reservation_id"]),
            order_id=UUID(body["order_id"]),
            sku=body["sku"],
            quantity=body["quantity"],
        )

    async def release_for_order(
        self, order_id: UUID, reason: str = "order_cancelled"
    ) -> int:
        response = await self._client.delete(
            f"/inventory/reservations/order/{order_id}",
            params={"reason": reason},
        )
        response.raise_for_status()
        return int(response.json()["released"])
