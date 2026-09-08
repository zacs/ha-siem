"""Strength derivation, door heuristics and resident expansion."""

from custom_components.siem.core.entities import (
    EntityInfo,
    derive_strength,
    effective_strength,
    expand_residents,
    is_exterior_area,
    is_gate,
    is_interior_door_name,
    is_person_detector,
    occupancy_candidates,
    split_openings,
)


def test_strength_from_device_class_and_platform():
    assert derive_strength("occupancy", "mqtt") == "strong"
    assert derive_strength("presence", "esphome") == "strong"
    assert derive_strength("motion", "zha") == "medium"
    assert derive_strength("sound", "zha") == "weak"
    assert derive_strength("motion", "bayesian") == "strong"
    assert derive_strength(None, "template") == "weak"


def test_override_wins_only_when_valid():
    assert effective_strength({"strength": "medium"}) == "medium"
    assert effective_strength({"strength": "medium", "strength_override": "strong"}) == "strong"
    assert effective_strength({"strength": "medium", "strength_override": "huge"}) == "medium"
    assert effective_strength({}) == "weak"


def test_interior_door_heuristic_and_perimeter_exclusion():
    assert is_interior_door_name("binary_sensor.kitchen_fridge_door")
    assert is_interior_door_name("binary_sensor.contact_3", "Pantry Cupboard")
    assert not is_interior_door_name("binary_sensor.front_door", "Front Door")
    entities = [
        EntityInfo("binary_sensor.front_door", "binary_sensor", "door", "zha", "Front Door"),
        EntityInfo("binary_sensor.fridge", "binary_sensor", "door", "zha", "Fridge"),
        EntityInfo("binary_sensor.closet_3", "binary_sensor", "opening", "zha", "Contact 3"),
        EntityInfo("binary_sensor.garage", "binary_sensor", "garage_door", "zha", "Garage"),
        EntityInfo("binary_sensor.motion", "binary_sensor", "motion", "zha", "Motion"),
    ]
    perimeter, interior = split_openings(entities)
    assert perimeter == ["binary_sensor.front_door", "binary_sensor.garage"]
    assert interior == ["binary_sensor.fridge", "binary_sensor.closet_3"]
    assert occupancy_candidates(entities) == ["binary_sensor.motion"]


def test_gate_person_and_exterior_heuristics():
    assert is_gate("binary_sensor.side_gate")
    assert not is_gate("binary_sensor.front_door")
    assert is_person_detector("binary_sensor.driveway_person_occupancy")
    assert is_exterior_area("Back Yard") and is_exterior_area("Driveway")
    assert not is_exterior_area("Living Room")


def test_resident_expansion_reads_person_attributes():
    residents = expand_residents(
        {
            "person.alice": {"device_trackers": ["device_tracker.alice_phone", "device_tracker.car"], "user_id": "u-alice"},
            "person.bob": {"device_trackers": ["device_tracker.car"], "user_id": None},
            "person.kid": {},
        }
    )
    assert residents.trackers == ["device_tracker.alice_phone", "device_tracker.car"]
    assert residents.user_ids == ["u-alice"]
