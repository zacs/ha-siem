"""House mode transitions."""

import pytest

from custom_components.siem.core.house_mode import FAMILY_LINGER_S, GUEST_AFTER_END_S, GUEST_LINGER_S, GUEST_QUIET_S, HouseModeMachine


def test_family_lingers_thirty_minutes():
    machine = HouseModeMachine(0)
    assert machine.mode(0) == "vacant"
    machine.set_presence(True, 10)
    assert machine.mode(10) == "family"
    machine.set_presence(False, 100)
    assert machine.mode(100 + FAMILY_LINGER_S - 1) == "family"
    assert machine.mode(100 + FAMILY_LINGER_S) == "vacant"


def test_a_guest_tracker_is_guest_mode_and_lingers_half_an_hour():
    machine = HouseModeMachine(0)
    machine.set_guest_presence(True, 10)
    assert machine.mode(10) == "guest"
    machine.set_presence(True, 20)
    assert machine.mode(20) == "family", "residents come first"
    machine.set_presence(False, 30)
    machine.set_guest_presence(False, 100)
    assert machine.mode(30 + FAMILY_LINGER_S) == "guest", "the resident's half hour is up, the guest's is not"
    assert machine.mode(100 + GUEST_LINGER_S - 1) == "guest"
    assert machine.mode(100 + GUEST_LINGER_S) == "vacant"


def test_night_with_the_family_home_is_their_bedtime_sources():
    machine = HouseModeMachine(0)
    machine.set_presence(True, 10)
    machine.set_in_bed(True)
    assert machine.mode(10) == "family" and machine.night(10), "night is an adjustment, not a mode"
    machine.set_in_bed(False)
    machine.set_night_window(True)
    assert not machine.night(10), "the bedtime sources say someone is up, whatever the clock says"


def test_night_with_only_guests_home_is_the_clock_and_a_source_can_only_start_it_sooner():
    machine = HouseModeMachine(0)
    machine.set_guest_presence(True, 10)
    assert machine.mode(10) == "guest" and not machine.night(10)
    machine.set_night_window(True)
    assert machine.night(10), "guests rarely have a bedtime sensor or arm the panel: the night window decides"
    machine.set_night_window(False)
    machine.set_in_bed(True)
    assert machine.night(10), "a house-sitter arming night at 10 p.m. starts it sooner"
    machine.set_in_bed(False)
    machine.set_night_window(True)
    assert machine.night(10), "nothing ends it inside the window"


def test_night_in_an_empty_house_is_the_clock():
    machine = HouseModeMachine(0)
    machine.set_in_bed(True)
    assert machine.mode(0) == "vacant" and not machine.night(0), "nobody home to be in bed: the clock decides"
    machine.set_night_window(True)
    assert machine.night(0)


def test_service_never_holds_at_night():
    machine = HouseModeMachine(0)
    machine.set_mode_sensors(False, True, 10)
    machine.set_night_window(True)
    assert machine.mode(10) == "vacant" and machine.night(10), "nobody works in the house at 2 a.m."
    machine.set_night_window(False)
    assert machine.mode(10) == "service" and not machine.night(10)


def test_a_forced_family_or_guest_still_goes_to_bed():
    machine = HouseModeMachine(0)
    machine.set_night_window(True)
    machine.set_override("guest")
    assert machine.mode(0) == "guest" and machine.night(0)
    machine.set_override("family")
    assert machine.mode(0) == "family" and not machine.night(0), "the family's sources say they are up"
    machine.set_in_bed(True)
    assert machine.night(0)
    with pytest.raises(ValueError):
        machine.set_override("night")


def test_guest_from_calendar_leaves_after_end_plus_two_hours_and_quiet():
    machine = HouseModeMachine(0)
    assert machine.set_calendar_event("Guest: Pat", 100, 1000) == "guest"
    assert machine.mode(500) == "guest"
    machine.clear_calendar_event()
    machine.note_activity(1000)
    assert machine.mode(1000 + GUEST_AFTER_END_S - 1) == "guest"
    machine.note_activity(1000 + GUEST_AFTER_END_S)
    assert machine.mode(1000 + GUEST_AFTER_END_S + GUEST_QUIET_S - 1) == "guest"
    assert machine.mode(1000 + GUEST_AFTER_END_S + GUEST_QUIET_S) == "vacant"


def test_letting_someone_in_flips_to_guest():
    machine = HouseModeMachine(0)
    machine.let_in(50)
    assert machine.mode(51) == "guest"
    assert machine.mode(50 + GUEST_AFTER_END_S + GUEST_QUIET_S) == "vacant"


def test_service_only_during_event_and_precedence():
    machine = HouseModeMachine(0)
    assert machine.set_calendar_event("service: Plumber", 100, 200) == "service"
    assert machine.set_calendar_event("Dentist", 100, 200) is None
    assert machine.mode(150) == "service"
    assert machine.mode(200) == "vacant"
    machine.set_presence(True, 150)
    assert machine.mode(150) == "family"


def test_service_sensor_holds_service_mode_and_adds_to_the_calendar():
    machine = HouseModeMachine(0)
    machine.set_mode_sensors(False, True, 10)
    assert machine.mode(10) == "service"
    machine.set_mode_sensors(False, False, 100)
    assert machine.mode(100) == "vacant", "service ends with the sensor"
    # Either one is enough: the calendar's event outlasts the sensor, and the sensor outlasts the event.
    machine.set_calendar_event("Service: Plumber", 100, 200)
    machine.set_mode_sensors(False, True, 100)
    machine.set_mode_sensors(False, False, 150)
    assert machine.mode(150) == "service"
    machine.set_mode_sensors(False, True, 190)
    assert machine.mode(250) == "service"
    machine.set_presence(True, 250)
    assert machine.mode(250) == "family", "residents come first"


def test_guest_sensor_lingers_like_the_end_of_a_guest_event():
    machine = HouseModeMachine(0)
    machine.set_mode_sensors(True, False, 10)
    assert machine.mode(10_000) == "guest"
    machine.note_activity(10_000)
    machine.set_mode_sensors(False, False, 10_000)
    assert machine.mode(10_000 + GUEST_AFTER_END_S - 1) == "guest"
    assert machine.mode(10_000 + GUEST_AFTER_END_S) == "vacant", "two hours on, and quiet for an hour"
    # A guest sensor that was never on starts no clock.
    fresh = HouseModeMachine(0)
    fresh.set_mode_sensors(False, False, 10)
    assert fresh.mode(10) == "vacant"


def test_guest_comes_before_service():
    machine = HouseModeMachine(0)
    machine.set_mode_sensors(True, True, 10)
    assert machine.mode(10) == "guest"


def test_override():
    machine = HouseModeMachine(0)
    machine.set_override("guest")
    assert machine.mode(0) == "guest"
    machine.set_override("auto")
    assert machine.mode(0) == "vacant"
    with pytest.raises(ValueError):
        machine.set_override("party")
