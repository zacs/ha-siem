"""Origin classification: who or what caused a state change."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

PRESENCE_SIMULATION_USER = "Presence Simulation"


class Origin(StrEnum):
    """Where a state change came from, in the order the classifier checks."""

    AUTOMATION = "automation"
    USER_TRUSTED = "user_trusted"
    USER_UNTRUSTED = "user_untrusted"
    HOMEKIT = "homekit"
    PHYSICAL = "physical"


class ContextLRU:
    """Bounded, time-limited set of context ids seen on HomeKit change events."""

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
    *,
    parent_id: str | None,
    user_id: str | None,
    context_id: str | None,
    trusted_user_ids: Iterable[str],
    homekit_contexts: ContextLRU,
    now: float,
) -> Origin:
    """Classify one state change from its context.

    An automation (``parent_id``) never scores, nor does a trusted user. An
    untrusted user scores the account rule. Without either id the change is
    HomeKit when its context was announced by ``homekit_state_change``,
    otherwise it is physical: a switch, a contact, a person in the room.
    """
    if parent_id:
        return Origin.AUTOMATION
    if user_id:
        return Origin.USER_TRUSTED if user_id in set(trusted_user_ids) else Origin.USER_UNTRUSTED
    if homekit_contexts.seen(context_id, now):
        return Origin.HOMEKIT
    return Origin.PHYSICAL


@dataclass(frozen=True)
class UserInfo:
    """The subset of a Home Assistant user the engine cares about."""

    id: str
    name: str | None = None
    system_generated: bool = False


def default_trusted_user_ids(resident_user_ids: Iterable[str | None], users: Iterable[UserInfo]) -> list[str]:
    """Return the residents' user ids plus any user named Presence Simulation."""
    trusted = [uid for uid in resident_user_ids if uid]
    for user in users:
        if (user.name or "").strip().casefold() == PRESENCE_SIMULATION_USER.casefold() and user.id not in trusted:
            trusted.append(user.id)
    return trusted
