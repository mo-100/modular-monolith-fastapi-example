from typing import Any

from shared.events import DomainEvent


class EventCollector:
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    async def __call__(self, event: DomainEvent) -> None:
        self.events.append(event)

    def of_type(self, event_type: type[Any]) -> list[Any]:
        return [event for event in self.events if isinstance(event, event_type)]
