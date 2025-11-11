"""Utility classes for managing chat subscriptions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Set


@dataclass
class SubscriptionRegistry:
    """Manage a set of chat IDs interested in a specific topic."""

    _subscribers: Set[int] = field(default_factory=set)

    def add(self, chat_id: int) -> None:
        self._subscribers.add(chat_id)

    def discard(self, chat_id: int) -> None:
        self._subscribers.discard(chat_id)

    def snapshot(self) -> Set[int]:
        return set(self._subscribers)

    def __bool__(self) -> bool:  # pragma: no cover - trivial
        return bool(self._subscribers)

    def __iter__(self) -> Iterable[int]:  # pragma: no cover - convenience
        return iter(self._subscribers)
