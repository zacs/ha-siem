"""Whether a state change physically happened, or Home Assistant caused it."""

from __future__ import annotations

from collections import OrderedDict


class ContextLRU:
    """Bounded, time-limited set of context ids, here the contexts of recent service calls."""

    def __init__(self, size: int = 200, ttl_s: float = 60.0) -> None:
        """Keep at most ``size`` ids, each for ``ttl_s`` seconds."""
        self._size = size
        self._ttl = ttl_s
        self._items: OrderedDict[str, float] = OrderedDict()

    def add(self, context_id: str, now: float) -> None:
        """Record ``context_id`` as seen at ``now``."""
        self._items.pop(context_id, None)
        self._items[context_id] = now
        while len(self._items) > self._size:
            self._items.popitem(last=False)

    def seen(self, context_id: str | None, now: float) -> bool:
        """Return True when ``context_id`` was recorded within the TTL."""
        if context_id is None:
            return False
        at = self._items.get(context_id)
        if at is None:
            return False
        if now - at > self._ttl:
            del self._items[context_id]
            return False
        return True


def is_physical(*, parent_id: str | None, user_id: str | None, context_id: str | None, caused: ContextLRU, now: float) -> bool:
    """Return True when a person or a device made this change, and Home Assistant did not.

    Anything Home Assistant does leaves a mark on the change's context: a parent id (an
    automation reacting to another change), a user id (someone in the app, a voice assistant
    through Home Assistant Cloud, an integration acting as its own user such as Presence
    Simulation), or the context of a service call. Every service call announces its context
    on the ``call_service`` event, which covers automations on any trigger, scripts, HomeKit
    Bridge, other integrations and the API. What is left happened in the house: a switch, a
    contact, a person in a room.
    """
    return not (parent_id or user_id or caused.seen(context_id, now))
