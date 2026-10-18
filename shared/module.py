"""The tiny lifecycle contract every module exposes to the composition root.

The composition root (``main.py``) owns construction, registration order and
startup/shutdown. Modules never discover each other; all collaboration happens
through injected public contracts or the event bus.
"""

from typing import Protocol

from fastapi import APIRouter


class Module(Protocol):
    name: str
    router: APIRouter

    def register(self) -> None:
        """Register event subscriptions. Called once before startup."""
        ...

    async def startup(self) -> None:
        """Module-owned startup hook."""
        ...

    async def shutdown(self) -> None:
        """Module-owned shutdown hook."""
        ...
