"""Inventory must run in a deployment where Orders and Notifications do not exist.

A fresh interpreter blocks those packages (and the composition root) and then
starts Inventory, creates a product, reserves and releases stock.
"""

import subprocess
import sys
import textwrap
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def test_inventory_runs_with_orders_and_notifications_removed(
    database_url: str,
) -> None:
    sku = f"REMOVAL-{uuid4().hex[:10]}"
    script = textwrap.dedent(
        f"""
        import asyncio
        import importlib.abc
        import sys
        from decimal import Decimal
        from uuid import uuid4

        class RemovedPackages(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "main" or fullname.startswith(
                    ("modules.orders", "modules.notifications")
                ):
                    raise ModuleNotFoundError(fullname + " is not installed")
                return None

        sys.meta_path.insert(0, RemovedPackages())

        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from modules.inventory.module import InventoryModule
        from shared.event_bus import InProcessEventBus

        async def run():
            engine = create_async_engine({database_url!r})
            bus = InProcessEventBus()
            await bus.start()
            module = InventoryModule(
                async_sessionmaker(engine, expire_on_commit=False), bus
            )
            module.register()
            await module.startup()

            product = await module.service.create_product(
                {sku!r}, "Widget", Decimal("1.00"), 2
            )
            assert product.available == 2

            order_id = uuid4()
            await module.service.reserve(order_id, {sku!r}, 1)
            assert (await module.service.get_product({sku!r})).available == 1
            assert await module.service.release_for_order(order_id) == 1
            assert (await module.service.get_product({sku!r})).available == 2

            await module.shutdown()
            await bus.stop()
            await engine.dispose()

        asyncio.run(run())
        print("REMOVAL_OK")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr
    assert "REMOVAL_OK" in result.stdout
