"""A small asynchronous, in-process event bus.

Semantics, stated explicitly:

* subscriptions are keyed by the concrete event class;
* every consumer of an event is awaited in subscription order;
* a consumer failure is logged and does not affect other consumers, the
  publisher, or the surrounding request;
* publishing before ``start()`` is a wiring bug and raises;
* publishing after ``stop()`` is dropped with a warning (the bus is
  non-durable and shutdown is best-effort);
* nothing is persisted: events are lost if the process dies.

A production broker adapter would implement ``EventBus`` (or the narrower
``EventPublisher``) with at-least-once delivery, retries and a dead-letter
queue. That changes failure semantics; see README.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Protocol, TypeVar

from shared.events import DomainEvent

E = TypeVar("E", bound=DomainEvent)
EventHandler = Callable[[E], Awaitable[None]]


class BusState(Enum):
    CREATED = "created"
    RUNNING = "running"
    STOPPED = "stopped"


class EventBusNotStarted(RuntimeError):
    """Raised when an event is published before the bus has started."""


class EventPublisher(Protocol):
    """Narrow dependency for code that only publishes events.

    Business services depend on this rather than the full bus, so a broker
    adapter can be substituted when events leave the process.
    """

    async def publish(self, event: DomainEvent) -> None: ...


class EventBus(EventPublisher, Protocol):
    """Publishing, subscription and lifecycle surface."""

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    def subscribe(self, event_type: type[E], handler: EventHandler[E]) -> None: ...


def _handler_name(handler: Callable[..., object]) -> str:
    name = getattr(handler, "__qualname__", None) or type(handler).__qualname__
    module = getattr(handler, "__module__", None) or type(handler).__module__
    return f"{module}.{name}"


class InProcessEventBus:
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("shared.event_bus")
        self._handlers: dict[type[DomainEvent], list[EventHandler]] = defaultdict(list)
        self._state = BusState.CREATED

    @property
    def state(self) -> BusState:
        return self._state

    async def start(self) -> None:
        if self._state is BusState.RUNNING:
            return
        self._state = BusState.RUNNING
        self._logger.info("Event bus started")

    async def stop(self) -> None:
        if self._state is BusState.STOPPED:
            return
        self._state = BusState.STOPPED
        self._logger.info("Event bus stopped")

    def subscribe(self, event_type: type[E], handler: EventHandler[E]) -> None:
        if not issubclass(event_type, DomainEvent):
            raise TypeError(f"{event_type!r} is not a DomainEvent subclass")
        self._handlers[event_type].append(handler)
        self._logger.debug(
            "Subscribed %s to %s", _handler_name(handler), event_type.__name__
        )

    async def publish(self, event: DomainEvent) -> None:
        if self._state is BusState.CREATED:
            raise EventBusNotStarted(
                "Start the event bus before publishing "
                f"{type(event).__name__}"
            )
        if self._state is BusState.STOPPED:
            self._logger.warning(
                "Event bus is stopped; dropping %s (%s)",
                type(event).__name__,
                event.event_id,
            )
            return

        handlers = tuple(self._handlers.get(type(event), ()))
        if not handlers:
            self._logger.debug("No consumers for %s", type(event).__name__)
            return

        for handler in handlers:
            try:
                await handler(event)
            except Exception:
                # Isolation is the point: one bad reactor must not roll back a
                # committed business transaction or starve other consumers.
                self._logger.exception(
                    "Consumer %s failed handling %s",
                    _handler_name(handler),
                    type(event).__name__,
                )
