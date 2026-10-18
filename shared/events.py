"""Typed, implementation-independent event contracts.

Events are deliberately small, immutable value objects. They belong to the
shared vocabulary, not to any module's implementation, so publishers and
subscribers can evolve without importing each other.

`event_version` exists so incompatible payload changes can be versioned rather
than silently breaking existing consumers.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True, kw_only=True)
class DomainEvent:
    event_id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    event_version: int = 1


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderLinePayload:
    sku: str
    quantity: int
    unit_price: Decimal


# --- Published by Orders -------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderPlaced(DomainEvent):
    order_id: UUID
    customer_id: str
    total: Decimal
    lines: tuple[OrderLinePayload, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderCancelled(DomainEvent):
    order_id: UUID
    reason: str | None = None


# --- Published by Inventory ----------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class StockReserved(DomainEvent):
    order_id: UUID
    reservation_id: UUID
    sku: str
    quantity: int


@dataclass(frozen=True, slots=True, kw_only=True)
class StockReleased(DomainEvent):
    order_id: UUID
    reservation_id: UUID
    sku: str
    quantity: int
    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class StockRejected(DomainEvent):
    order_id: UUID
    sku: str
    requested: int
    available: int
