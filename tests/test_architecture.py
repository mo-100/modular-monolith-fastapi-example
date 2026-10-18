"""Executable architecture boundaries.

These tests fail if a module reaches into another module's internals, if ORM or
framework concerns leak into contracts/business logic, or if database ownership
is violated.
"""

import ast
from pathlib import Path

import pytest

from modules.inventory.models import Base as InventoryBase
from modules.notifications.models import Base as NotificationsBase
from modules.orders.models import Base as OrdersBase

ROOT = Path(__file__).resolve().parents[1]
MODULES_DIR = ROOT / "modules"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _files(module: str) -> list[Path]:
    return sorted((MODULES_DIR / module).rglob("*.py"))


def _cross_module_violations(module: str, allowed: set[str]) -> list[str]:
    violations: list[str] = []
    for path in _files(module):
        for imported in _imports(path):
            if not imported.startswith("modules."):
                continue
            if imported == f"modules.{module}" or imported.startswith(
                f"modules.{module}."
            ):
                continue
            if any(
                imported == prefix or imported.startswith(f"{prefix}.")
                for prefix in allowed
            ):
                continue
            violations.append(f"{path.relative_to(ROOT)} imports {imported}")
    return violations


def test_inventory_never_imports_higher_level_modules() -> None:
    assert _cross_module_violations("inventory", set()) == []


def test_orders_only_imports_inventory_public_contract() -> None:
    assert (
        _cross_module_violations(
            "orders", {"modules.inventory", "modules.inventory.contract"}
        )
        == []
    )


def test_notifications_only_imports_inventory_public_contract() -> None:
    assert (
        _cross_module_violations(
            "notifications", {"modules.inventory", "modules.inventory.contract"}
        )
        == []
    )


def test_shared_never_imports_business_modules() -> None:
    violations = [
        f"{path.name} imports {name}"
        for path in (ROOT / "shared").glob("*.py")
        for name in _imports(path)
        if name.startswith("modules.")
    ]
    assert violations == []


def test_public_contract_is_free_of_framework_and_orm_imports() -> None:
    path = MODULES_DIR / "inventory" / "contract.py"
    forbidden = {"fastapi", "starlette", "sqlalchemy", "modules.inventory.models"}
    offenders = [
        name
        for name in _imports(path)
        if any(name == item or name.startswith(f"{item}.") for item in forbidden)
    ]
    assert offenders == []


def test_business_logic_is_independent_of_fastapi() -> None:
    candidates = [
        *(MODULES_DIR.glob("*/service.py")),
        *(MODULES_DIR.glob("*/repository.py")),
        *(MODULES_DIR.glob("*/models.py")),
        *(MODULES_DIR.glob("*/contract.py")),
        ROOT / "shared" / "event_bus.py",
        ROOT / "shared" / "events.py",
        ROOT / "shared" / "database.py",
    ]
    offenders: list[str] = []
    for path in candidates:
        for name in _imports(path):
            if name == "fastapi" or name.startswith("fastapi."):
                offenders.append(f"{path.relative_to(ROOT)} imports {name}")
            if name == "starlette" or name.startswith("starlette."):
                offenders.append(f"{path.relative_to(ROOT)} imports {name}")
    assert offenders == []


@pytest.mark.parametrize(
    ("base", "schema"),
    [
        (InventoryBase, "inventory"),
        (OrdersBase, "orders"),
        (NotificationsBase, "notifications"),
    ],
)
def test_each_module_owns_exactly_its_schema(base, schema: str) -> None:
    assert base.metadata.tables, "module should define tables"
    for table in base.metadata.tables.values():
        assert table.schema == schema
        for foreign_key in table.foreign_keys:
            assert foreign_key.column.table.schema == schema


def test_orders_does_not_import_inventory_orm_or_repository() -> None:
    forbidden = {
        "modules.inventory.models",
        "modules.inventory.repository",
        "modules.inventory.service",
        "modules.inventory.api",
        "modules.inventory.module",
    }
    offenders = [
        f"{path.relative_to(ROOT)} imports {name}"
        for path in _files("orders")
        for name in _imports(path)
        if any(name == item or name.startswith(f"{item}.") for item in forbidden)
    ]
    assert offenders == []
