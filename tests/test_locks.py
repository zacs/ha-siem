"""Lock notification classification and LCM slot handling."""

from custom_components.siem.core.locks import (
    KIND_KEYPAD_LOCKOUT,
    KIND_KEYPAD_UNLOCK,
    KIND_MANUAL_UNLOCK,
    classify_lock_notification,
    lcm_slots_from_attributes,
    pin_allowed,
)


def test_classification():
    assert classify_lock_notification("Manual unlock operation", None) == (KIND_MANUAL_UNLOCK, None)
    assert classify_lock_notification("Keypad unlock operation", {"userId": 3}) == (KIND_KEYPAD_UNLOCK, 3)
    assert classify_lock_notification("Keypad temporarily disabled", {}) == (KIND_KEYPAD_LOCKOUT, None)
    assert classify_lock_notification("Lock jammed", {"userId": "x"}) == (None, None)


def test_lcm_slots_and_allowance():
    slots = lcm_slots_from_attributes(
        {
            "event.sam": {"code_slot": 3, "name": "Sam", "active": True},
            "event.old": {"code_slot": 4, "name": "Old", "active": False},
            "event.nameless": {"code_slot": 5},
            "event.broken": {"code_slot": "7"},
        }
    )
    assert slots[3].name == "Sam" and pin_allowed(3, slots)
    assert not pin_allowed(4, slots)
    assert slots[5].name == "slot 5" and pin_allowed(5, slots)
    assert not pin_allowed(7, slots) and not pin_allowed(None, slots)
