"""Inventory's stable public Python contract.

Other modules receive an object satisfying ``InventoryService``. They never see
ORM models, sessions, repositories or the `inventory` schema. The contract is
transport-agnostic: an HTTP adapter can implement the same protocol when
Inventory is extracted into a service (see ``modules/orders/inventory_client.py``).

Keep this file free of SQLAlchemy, FastAPI and Inventory implementation imports;
it is the versionable seam between modules.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True, kw_only=True)
class Product:
    sku: str
    name: str
    unit_price: Decimal
    available: int


@dataclass(frozen=True, slots=True, kw_only=True)
class Reservation:
    id: UUID
    order_id: UUID
    sku: str
    quantity: int


class InventoryError(Exception):
    """Base class for contract-level failures."""


class ProductNotFound(InventoryError):
    def __init__(self, sku: str) -> None:
        self.sku = sku
        super().__init__(f"Product {sku!r} does not exist")


class InsufficientStock(InventoryError):
    def __init__(self, sku: str, requested: int, available: int) -> None:
        self.sku = sku
        self.requested = requested
        self.available = available
        super().__init__(
            f"Insufficient stock for {sku!r}: requested {requested}, "
            f"available {available}"
        )


class InventoryService(Protocol):
    """The only Python dependency other modules may take on Inventory."""

    async def get_product(self, sku: str) -> Product | None: ...

    async def check_availability(self, sku: str, quantity: int) -> bool: ...

    async def reserve(
        self, order_id: UUID, sku: str, quantity: int
    ) -> Reservation: ...

    async def release_for_order(
        self, order_id: UUID, reason: str = "order_cancelled"
    ) -> int:
        """Release active reservations for an order; idempotent.

        Returns the number of reservations released.
        """
        ...
