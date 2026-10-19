"""Lock notifications and Lock Code Manager slot bookkeeping."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

KIND_MANUAL_UNLOCK, KIND_KEYPAD_UNLOCK, KIND_KEYPAD_LOCKOUT = "manual_unlock", "keypad_unlock", "keypad_lockout"

# Z-Wave access-control labels that read as a lockout after repeated bad codes. A single wrong code is a
# typo, not an attack, so labels like "invalid code" do not count. Locks rarely send these; the rule is
# opportunistic and nothing depends on it.
LOCKOUT_HINTS: tuple[str, ...] = ("keypad temporarily disabled", "keypad disabled", "code limit", "attempts", "too many")


def classify_lock_notification(label: str | None, slot: Any) -> tuple[str | None, int | None]:
    """Map a lock event label and code slot to a lock event kind.

    Labels come from ``zwave_js_notification`` or Lock Code Manager's lock event: ZHA says "Manual unlock operation" like
    Z-Wave, Zigbee2MQTT sends ``manual_unlock`` or ``unlock`` with a slot, and Matter only ``unlocked`` with a slot.
    """
    label = (label or "").casefold().replace("_", " ")
    slot = int(slot) if isinstance(slot, int) and not isinstance(slot, bool) and slot > 0 else None
    if "manual unlock" in label:
        return KIND_MANUAL_UNLOCK, slot
    if "keypad unlock" in label or ("unlock" in label and slot):
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


def pin_disabled(slot: int | None, slots: Mapping[int, LcmSlot]) -> bool:
    """Return True only for a slot Lock Code Manager knows and marks disabled.

    The lock accepted the code, so whoever typed it was given it: any other code, a slot Lock Code Manager does not
    know or a lock without it, lets someone in.
    """
    return slot is not None and slot in slots and slots[slot].allowed is False
