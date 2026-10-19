"""Origin classification: who or what caused a state change."""

from __future__ import annotations

from collections import OrderedDict
from enum import StrEnum


class Origin(StrEnum):
    """Where a state change came from, in the order the classifier checks."""

    AUTOMATION = "automation"
    USER = "user"
    HOMEKIT = "homekit"
    PHYSICAL = "physical"


class ContextLRU:
    """Bounded, time-limited set of context ids announced by an event (HomeKit changes, automation runs)."""

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


def classify_origin(
    *, parent_id: str | None, user_id: str | None, context_id: str | None, homekit_contexts: ContextLRU, now: float, automation_contexts: ContextLRU | None = None
) -> Origin:
    """Classify one state change from its context.

    A change with a ``parent_id`` was caused by something else (an automation
    reacting to a state change). A change with a ``user_id`` came from a Home
    Assistant user: someone in the app, a voice assistant through Home
    Assistant Cloud, or an integration acting as its own user, such as
    Presence Simulation. Automations started by a time, sun or calendar
    trigger have neither id, so their context ids are collected from
    ``automation_triggered`` and ``script_started`` events and matched here.
    None of those ever score. What is left is HomeKit when its context was
    announced by ``homekit_state_change``, otherwise physical: a switch, a
    contact, a person in the room.
    """
    if parent_id:
        return Origin.AUTOMATION
    if user_id:
        return Origin.USER
    if automation_contexts is not None and automation_contexts.seen(context_id, now):
        return Origin.AUTOMATION
    if homekit_contexts.seen(context_id, now):
        return Origin.HOMEKIT
    return Origin.PHYSICAL
