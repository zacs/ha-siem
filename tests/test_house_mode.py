"""House mode transitions."""

import pytest

from custom_components.siem.core.house_mode import FAMILY_LINGER_S, SITTER_AFTER_END_S, SITTER_QUIET_S, HouseModeMachine


def test_family_lingers_thirty_minutes():
    machine = HouseModeMachine(0)
    assert machine.mode(0) == "vacant"
    machine.set_presence(True, 10)
    assert machine.mode(10) == "family"
    machine.set_presence(False, 100)
    assert machine.mode(100 + FAMILY_LINGER_S - 1) == "family"
    assert machine.mode(100 + FAMILY_LINGER_S) == "vacant"


def test_sitter_from_calendar_leaves_after_end_plus_two_hours_and_quiet():
    machine = HouseModeMachine(0)
    assert machine.set_calendar_event("Sitter: Sam", 100, 1000) == "sitter"
    assert machine.mode(500) == "sitter"
    machine.clear_calendar_event()
    machine.note_activity(1000)
    assert machine.mode(1000 + SITTER_AFTER_END_S - 1) == "sitter"
    machine.note_activity(1000 + SITTER_AFTER_END_S)
    assert machine.mode(1000 + SITTER_AFTER_END_S + SITTER_QUIET_S - 1) == "sitter"
    assert machine.mode(1000 + SITTER_AFTER_END_S + SITTER_QUIET_S) == "vacant"


def test_allowed_pin_flips_to_sitter():
    machine = HouseModeMachine(0)
    machine.allowed_pin(50)
    assert machine.mode(51) == "sitter"
    assert machine.mode(50 + SITTER_AFTER_END_S + SITTER_QUIET_S) == "vacant"


def test_service_only_during_event_and_precedence():
    machine = HouseModeMachine(0)
    assert machine.set_calendar_event("service: Plumber", 100, 200) == "service"
    assert machine.set_calendar_event("Dentist", 100, 200) is None
    assert machine.mode(150) == "service"
    assert machine.mode(200) == "vacant"
    machine.set_presence(True, 150)
    assert machine.mode(150) == "family"


def test_override():
    machine = HouseModeMachine(0)
    machine.set_override("sitter")
    assert machine.mode(0) == "sitter"
    machine.set_override("auto")
    assert machine.mode(0) == "vacant"
    with pytest.raises(ValueError):
        machine.set_override("party")
