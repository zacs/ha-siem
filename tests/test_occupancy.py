"""Room corroboration and the weak-alone rule."""

import pytest

from custom_components.siem.core.incident import IncidentEngine
from custom_components.siem.core.occupancy import RoomOccupancy
from custom_components.siem.core.rules import DEFAULT_RULES, EngineSettings


def test_strongest_source_credits_once_per_window():
    rooms = RoomOccupancy()
    first = rooms.observe("kitchen", "binary_sensor.motion", "medium", 0, 50)
    assert first.points == 30
    assert first.strength == "medium"
    again = rooms.observe("kitchen", "binary_sensor.motion", "medium", 100, 50)
    assert again.points == 0
    later = rooms.observe("kitchen", "binary_sensor.motion", "medium", 400, 50)
    assert later.points == 30


def test_two_independent_sources_within_sixty_seconds_corroborate():
    rooms = RoomOccupancy()
    rooms.observe("kitchen", "binary_sensor.motion", "medium", 0, 50)
    second = rooms.observe("kitchen", "binary_sensor.presence", "strong", 30, 50)
    assert second.corroborated
    assert second.strength == "strong"
    assert second.points == pytest.approx(65 - 30)
    third = rooms.observe("den", "binary_sensor.a", "strong", 0, 50)
    fourth = rooms.observe("den", "binary_sensor.b", "strong", 61, 50)
    assert not fourth.corroborated
    assert third.points == 50 and fourth.points == 0


def test_weak_alone_never_opens_in_vacant():
    rooms = RoomOccupancy()
    engine = IncidentEngine(DEFAULT_RULES, EngineSettings(), {})
    result = rooms.observe("kitchen", "binary_sensor.sound", "weak", 0, 50)
    assert result.weak_alone
    assert engine.add("interior_occupied", mode="vacant", now=0, points=result.points, allow_open=not result.weak_alone) is None
    assert engine.current is None
    engine.add("exterior_door_opened", mode="vacant", now=1)
    joined = engine.add("interior_occupied", mode="vacant", now=2, points=result.points, allow_open=False)
    assert joined is not None and joined.points == pytest.approx(15 * 1.5)


def test_reset_and_unknown_strength():
    rooms = RoomOccupancy()
    rooms.observe("kitchen", "binary_sensor.m", "strong", 0, 50)
    rooms.reset("kitchen")
    assert rooms.observe("kitchen", "binary_sensor.m", "strong", 1, 50).points == 50
    with pytest.raises(ValueError):
        rooms.observe("kitchen", "binary_sensor.m", "huge", 1, 50)
