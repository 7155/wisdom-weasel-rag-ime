from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


class DomainPolicyError(ValueError):
    """The requested Room transition violates a domain invariant."""


@dataclass(frozen=True)
class DomainEvent:
    event_id: str
    kind: str
    room_id: str
    root_id: str
    entity_id: str
    generation: int
    payload: Mapping[str, object]
