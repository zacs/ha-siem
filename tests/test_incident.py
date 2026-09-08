"""Incident lifecycle, chains, suppressors, labels and publishing."""

import itertools

import pytest

from custom_components.siem.core.incident import EVENT_CLOSED, EVENT_OPENED, EVENT_TIER_CHANGED, IncidentEngine
from custom_components.siem.core.rules import DEFAULT_RULES, SUPPRESSOR_ALLOWED_PIN, SUPPRESSOR_FAMILY_ARRIVAL, EngineSettings


@pytest.fixture
def engine():
    counter = itertools.count(1)
    return IncidentEngine(DEFAULT_RULES, EngineSettings(), {}, id_factory=lambda: f"inc{next(counter)}")


def test_opens_on_first_positive_contribution_only(engine):
    assert engine.add("exterior_door_opened", mode="family", now=0) is None
    assert engine.current is None
    contribution = engine.add("exterior_door_opened", mode="vacant", now=0, entity_id="binary_sensor.front", room="hall")
    assert contribution.points == 40
    assert engine.current.id == "inc1"
    assert engine.current.room == "hall"
    events = engine.evaluate(0)
    assert [e.kind for e in events] == [EVENT_OPENED, EVENT_TIER_CHANGED]
    assert events[1].tier == "verify"


def test_joins_within_window_and_opens_new_when_cold(engine):
    engine.add("gate_opened", mode="vacant", now=0)
    engine.add("exterior_door_opened", mode="vacant", now=200)
    assert len(engine.current.contributions) == 2
    # After the join window and once the score has decayed under the close threshold the next event is a new incident.
    engine.add("gate_opened", mode="vacant", now=200 + 6 * 3600)
    assert engine.current.id == "inc2"
    events = engine.evaluate(200 + 6 * 3600)
    assert [e.kind for e in events] == [EVENT_OPENED, EVENT_CLOSED, EVENT_OPENED, EVENT_TIER_CHANGED]


def test_still_hot_incident_keeps_joining_after_join_window(engine):
    engine.add("exterior_door_opened", mode="vacant", now=0)
    engine.add("light_physical", mode="vacant", now=600)
    assert engine.current.id == "inc1"


def test_closes_after_thirty_minutes_below_five(engine):
    engine.add("door_csi_motion", mode="vacant", now=0)  # 15 points
    engine.evaluate(0)
    assert engine.evaluate(30 * 60) == []
    low = 30 * 60
    while engine.score(low) >= 5:
        low += 60
    engine.evaluate(low)
    assert engine.evaluate(low + 29 * 60) == []
    events = engine.evaluate(low + 30 * 60)
    assert [e.kind for e in events] == [EVENT_CLOSED]
    assert engine.current is None
    assert engine.last_incident.closed == low + 30 * 60


def test_timeline_keeps_first_ten_events(engine):
    for i in range(14):
        engine.add("interior_occupied", mode="vacant", now=i, points=5, entity_id=f"binary_sensor.m{i}")
    assert len(engine.current.timeline) == 10
    assert engine.current.timeline[0]["entity_id"] == "binary_sensor.m0"
    assert len(engine.current.contributions) == 14


def test_chain_multipliers(engine):
    engine.add("exterior_door_opened", mode="vacant", now=0)
    occupied = engine.add("interior_occupied", mode="vacant", now=30)
    assert occupied.points == 75
    assert occupied.multiplier == 1.5
    light = engine.add("light_physical", mode="vacant", now=40)
    assert light.points == 45 * 1.5
    engine.add("manual_unlock", mode="vacant", now=50)
    tv = engine.add("tv_power", mode="vacant", now=60)
    assert tv.points == 70


def test_chain_only_inside_window(engine):
    engine.add("gate_opened", mode="vacant", now=0)
    late = engine.add("exterior_door_opened", mode="vacant", now=301)
    assert late.multiplier == 1.0


def test_suppressors_and_person(engine):
    assert engine.suppress("family_arrival", SUPPRESSOR_FAMILY_ARRIVAL, now=0) is None
    engine.add("exterior_door_opened", mode="vacant", now=0)
    engine.suppress("allowed_pin", SUPPRESSOR_ALLOWED_PIN, now=1, detail="PIN by Sam", person="Sam")
    assert engine.score(1) == 0
    assert engine.current.person == "Sam"
    assert engine.current.timeline[-1]["points"] == -40
    assert engine.current.last_event == 0


def test_labels_adjust_weights_of_incident_rules(engine):
    engine.add("exterior_door_opened", mode="vacant", now=0)
    engine.add("light_physical", mode="vacant", now=1)
    incident, changes = engine.label("false_alarm")
    assert incident.labels == ["false_alarm"]
    assert changes == {"exterior_door_opened": (1.0, 0.9), "light_physical": (1.0, 0.9)}
    assert engine.weights["light_physical"] == 0.9
    with pytest.raises(ValueError):
        engine.label("bogus")


def test_label_by_id_after_close(engine):
    engine.add("exterior_door_opened", mode="vacant", now=0)
    engine.add("gate_opened", mode="vacant", now=6 * 3600)
    incident, _ = engine.label("real", "inc1")
    assert incident.id == "inc1"
    with pytest.raises(LookupError):
        engine.label("real", "missing")


def test_publish_gating(engine):
    assert engine.should_publish(0, 0, "none")
    assert not engine.should_publish(10, 0.5, "none")
    assert engine.should_publish(10, 25, "verify")
    assert not engine.should_publish(20, 26, "verify")
    assert not engine.should_publish(50, 25.5, "verify")
    assert engine.should_publish(50, 27, "verify")


def test_unknown_rule_is_rejected(engine):
    with pytest.raises(ValueError):
        engine.add("nope", mode="vacant", now=0)
