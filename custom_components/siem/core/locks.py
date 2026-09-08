"""Lock notifications and Lock Code Manager slot bookkeeping."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

KIND_MANUAL_UNLOCK, KIND_KEYPAD_UNLOCK, KIND_KEYPAD_LOCKOUT = "manual_unlock", "keypad_unlock", "keypad_lockout"

# Z-Wave access-control labels that read as a lockout. Locks rarely send
# these; the keypad_lockout rule is opportunistic and nothing depends on it.
LOCKOUT_HINTS: tuple[str, ...] = (
    "keypad temporarily disabled", "keypad disabled", "code limit", "attempts", "invalid code", "bad code",
    "wrong code", "too many",
)


def classify_lock_notification(event_label: str | None, parameters: Mapping[str, Any] | None) -> tuple[str | None, int | None]:
    """Map a ``zwave_js_notification`` label to a lock event kind and slot."""
    label = (event_label or "").casefold()
    slot = None
    if parameters and isinstance(parameters.get("userId"), int):
        slot = int(parameters["userId"])
    if "manual unlock" in label:
        return KIND_MANUAL_UNLOCK, slot
    if "keypad unlock" in label:
        return KIND_KEYPAD_UNLOCK, slot
    if any(hint in label for hint in LOCKOUT_HINTS):
        return KIND_KEYPAD_LOCKOUT, slot
    return None, slot


@dataclass(frozen=True)
class LcmSlot:
    """A code slot as described by a Lock Code Manager event entity."""

    slot: int
    name: str
    allowed: bool | None = None


def lcm_slots_from_attributes(attributes_by_entity: Mapping[str, Mapping[str, Any]]) -> dict[int, LcmSlot]:
    """Build the slot map from the state attributes of LCM event entities.

    Lock Code Manager publishes ``code_slot`` and ``name`` on its per-user
    event entity. ``active`` or ``enabled`` is honoured when present.
    """
    slots: dict[int, LcmSlot] = {}
    for attrs in attributes_by_entity.values():
        slot = attrs.get("code_slot")
        if not isinstance(slot, int) or isinstance(slot, bool):
            continue
        allowed: bool | None = None
        for key in ("active", "enabled"):
            if isinstance(attrs.get(key), bool):
                allowed = bool(attrs[key])
                break
        slots[slot] = LcmSlot(slot, str(attrs.get("name") or f"slot {slot}"), allowed)
    return slots


def pin_allowed(slot: int | None, slots: Mapping[int, LcmSlot]) -> bool:
    """Return True only for a known slot that is not marked disallowed."""
    if slot is None or slot not in slots:
        return False
    return slots[slot].allowed is not False
