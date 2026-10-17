from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class DomainEvent:
    event_id: UUID
    occurred_at: datetime
    event_type: str
    version: int = 1


class EventPublisher(Protocol):
    async def publish(self, event: DomainEvent) -> None: ...
