"""Inventory's public surface.

Only this package's contract is importable by other modules. The implementation
lives in ``service``, ``repository``, ``models``, ``api`` and ``module`` and is
private to Inventory.
"""

from modules.inventory.contract import (
    InsufficientStock,
    InventoryService,
    Product,
    ProductNotFound,
    Reservation,
)

__all__ = [
    "InsufficientStock",
    "InventoryService",
    "Product",
    "ProductNotFound",
    "Reservation",
]
