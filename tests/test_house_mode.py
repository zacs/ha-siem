"""House mode transitions."""

import pytest

from custom_components.siem.core.house_mode import (
    FAMILY_LINGER_S,
    GUEST_AFTER_END_S,
    GUEST_DOORWAY_S,
    GUEST_LEFT_S,
    GUEST_LINGER_S,
    GUEST_QUIET_S,
    HouseModeMachine,
)


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


DAY = 24 * 3600


def test_a_guest_let_in_from_outside_is_inside_until_a_door_opens():
    machine = HouseModeMachine(0)
    machine.let_in(100, from_outside=True)
    assert machine.guests_inside and not machine.leaving
    machine.set_night_window(True)
    assert machine.mode(100 + 3 * DAY) == "guest", "quiet days and nights: the house-sitter is still inside"
    assert machine.night(100 + 3 * DAY), "and asleep at night"
    machine.set_night_window(False)
    machine.door_opened(5 * DAY)
    assert machine.leaving
    assert machine.mode(5 * DAY + GUEST_LEFT_S - 1) == "guest"
    assert machine.mode(5 * DAY + GUEST_LEFT_S) == "vacant", "half an hour after the door, with nobody moving inside"
    assert not machine.guests_inside and not machine.leaving


def test_someone_moving_inside_after_the_doorway_keeps_the_guests_inside():
    machine = HouseModeMachine(0)
    machine.let_in(100, from_outside=True)
    machine.door_opened(1000)
    assert not machine.someone_inside(1000 + GUEST_DOORWAY_S - 1), "whoever opened the door, still in the hall"
    assert machine.leaving
    assert machine.someone_inside(1000 + GUEST_DOORWAY_S), "one guest went out, the others are inside"
    assert not machine.leaving
    assert machine.mode(1000 + GUEST_LEFT_S + DAY) == "guest"
    assert not machine.someone_inside(1000 + DAY), "nothing to settle with no door open"


def test_a_tracker_or_the_guest_clock_still_holds_after_the_door():
    machine = HouseModeMachine(0)
    machine.let_in(100, from_outside=True)
    machine.set_guest_presence(True, 500)
    machine.door_opened(1000)
    assert machine.mode(1000 + GUEST_LEFT_S) == "guest", "a guest's phone is home"
    machine.set_guest_presence(False, 2000)
    assert machine.mode(2000 + GUEST_LINGER_S) == "vacant"


def test_a_door_means_nothing_until_someone_was_let_in():
    machine = HouseModeMachine(0)
    machine.door_opened(100)
    assert not machine.leaving and machine.mode(100) == "vacant"
    machine.let_in(200, from_outside=True)
    assert not machine.leaving, "the door before the code doesn't count"


def test_a_new_code_lets_someone_in_again():
    machine = HouseModeMachine(0)
    machine.let_in(100, from_outside=True)
    machine.door_opened(1000)
    machine.let_in(1000 + GUEST_LEFT_S - 60, from_outside=True)
    assert machine.mode(1000 + 2 * GUEST_LEFT_S) == "guest", "back before the half hour was up"
    machine.door_opened(10_000)
    assert machine.mode(10_000 + GUEST_LEFT_S) == "vacant"
    machine.let_in(20_000, from_outside=True)
    assert machine.mode(20_000 + DAY) == "guest", "and after it"


def test_with_the_family_home_a_code_only_starts_the_guest_clock():
    machine = HouseModeMachine(0)
    machine.set_presence(True, 10)
    machine.let_in(100, from_outside=True)
    assert not machine.guests_inside
    machine.set_presence(False, 200)
    assert machine.mode(200 + FAMILY_LINGER_S) == "guest", "the clock: two hours, then a quiet hour"
    assert machine.mode(100 + GUEST_AFTER_END_S + GUEST_QUIET_S) == "vacant"
    # Letting someone in other than from outside (a garage door opened from Home Assistant) is the clock too.
    away = HouseModeMachine(0)
    away.let_in(100)
    assert not away.guests_inside
    assert away.mode(100 + GUEST_AFTER_END_S + GUEST_QUIET_S) == "vacant"


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
