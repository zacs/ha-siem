"""Fixtures for the Home Assistant tests: a small house of plain states and a loaded SIEM entry."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.auth import models
from homeassistant.core import callback
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed, async_mock_service

from custom_components.siem.config_flow import build_entity_meta
from custom_components.siem.const import DOMAIN

TRUSTED = "trusted-user"
UNTRUSTED = "untrusted-user"

# Entity id -> (state, attributes) before SIEM loads.
HOUSE_STATES: dict[str, tuple[str, dict[str, Any]]] = {
    "binary_sensor.kitchen_motion": ("off", {"device_class": "motion", "friendly_name": "Kitchen Motion"}),
    "binary_sensor.kitchen_presence": ("off", {"device_class": "presence", "friendly_name": "Kitchen Presence"}),
    "binary_sensor.back_door": ("off", {"device_class": "door", "friendly_name": "Back Door"}),
    "binary_sensor.fridge_door": ("off", {"device_class": "door", "friendly_name": "Fridge Door"}),
    "binary_sensor.front_door": ("off", {"device_class": "door", "friendly_name": "Front Door"}),
    "binary_sensor.front_door_csi": ("off", {"friendly_name": "Front Door Wi-Fi Motion"}),
    "binary_sensor.yard_gate": ("off", {"device_class": "door", "friendly_name": "Yard Gate"}),
    "light.kitchen": ("off", {"friendly_name": "Kitchen Light"}),
    "light.kitchen_2": ("off", {"friendly_name": "Kitchen Light 2"}),
    "sensor.coffee_power": ("0", {"device_class": "power", "unit_of_measurement": "W", "friendly_name": "Coffee Maker Power"}),
    "sensor.water_flow": ("0", {"friendly_name": "Water Flow"}),
    "sensor.house_power": ("300", {"device_class": "power", "unit_of_measurement": "W", "friendly_name": "House Power"}),
    "lock.front_door": ("locked", {"friendly_name": "Front Door Lock"}),
    "event.lcm_pat": ("unknown", {"code_slot": 3, "name": "Pat", "active": True, "friendly_name": "Pat credential used"}),
    "device_tracker.alice_phone": ("not_home", {"friendly_name": "Alice Phone"}),
    "person.alice": ("not_home", {"device_trackers": ["device_tracker.alice_phone"], "user_id": TRUSTED, "friendly_name": "Alice"}),
    "calendar.house": ("off", {"friendly_name": "House"}),
    "alarm_control_panel.house": ("disarmed", {"friendly_name": "House Alarm"}),
}

ROOMS = {
    "kitchen": {
        "name": "Kitchen",
        "occupancy": ["binary_sensor.kitchen_motion", "binary_sensor.kitchen_presence"],
        "perimeter": ["binary_sensor.back_door"],
        "interior_doors": ["binary_sensor.fridge_door"],
        "lights": ["light.kitchen", "light.kitchen_2"],
        "power": ["sensor.coffee_power"],
        "power_threshold": 30,
        "deter_lights": ["light.kitchen"],
    },
    "hall": {"name": "Hall", "perimeter": ["binary_sensor.front_door"], "power_threshold": 30},
    "yard": {"name": "Yard", "perimeter": ["binary_sensor.yard_gate"], "power_threshold": 30},
}
HOUSE = {
    "residents": ["person.alice"],
    "csi_sensors": ["binary_sensor.front_door_csi"],
    "csi_map": {"binary_sensor.front_door_csi": "binary_sensor.front_door"},
    "water_flow": ["sensor.water_flow"],
    "water_threshold": 1,
    "locks": ["lock.front_door"],
    "lcm_events": ["event.lcm_pat"],
    "calendar": "calendar.house",
    "trusted_user_ids": [TRUSTED],
    "night_start": "22:00:00",
    "night_end": "06:00:00",
    "deter_volume": 0.7,
    "restore_seconds": 30,
    "house_deter": ["script.house_deter"],
    "house_alarm": ["switch.siren"],
}
RESPONSES = {"notify_services": ["notify.test"], "alarm_panel": "alarm_control_panel.house", "digest_times": ["08:00"], "dry_run": True, "auto_arm": False, "auto_alarm": False}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load custom_components/siem."""
    return


@pytest.fixture(autouse=True)
async def users(hass):
    """Register the two users the contexts refer to."""
    for user_id, name in ((TRUSTED, "Alice"), (UNTRUSTED, "Mallory")):
        hass.auth._store._users[user_id] = models.User(name=name, is_owner=False, is_active=True, groups=[], id=user_id, perm_lookup=hass.auth._store._perm_lookup)


@pytest.fixture
def notify_calls(hass):
    """Capture the plain-text notify service."""
    return async_mock_service(hass, "notify", "test")


@pytest.fixture
def siem_events(hass):
    """Collect every siem_incident and siem_notification event."""
    events: list[tuple[str, dict[str, Any]]] = []
    for name in ("siem_incident", "siem_notification"):
        hass.bus.async_listen(name, callback(lambda event: events.append((event.event_type, dict(event.data)))))
    return events


def notifications(events, category: str | None = None) -> list[dict[str, Any]]:
    """Return the siem_notification payloads, optionally of one category."""
    return [data for kind, data in events if kind == "siem_notification" and category in (None, data["category"])]


def set_house_states(hass) -> None:
    for entity_id, (state, attributes) in HOUSE_STATES.items():
        hass.states.async_set(entity_id, state, attributes)


async def setup_siem(hass, *, house: dict | None = None, responses: dict | None = None, options: dict | None = None, rooms: dict | None = None) -> MockConfigEntry:
    """Create the house states and load SIEM on them in vacant mode."""
    set_house_states(hass)
    data = {"rooms": rooms or ROOMS, "house": {**HOUSE, **(house or {})}, "responses": {**RESPONSES, **(responses or {})}}
    data["entities"] = build_entity_meta(hass, data)
    entry = MockConfigEntry(domain=DOMAIN, title="SIEM", data=data, options=options or {}, version=1, minor_version=2)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def flip(hass, entity_id: str, state: str = "on", context=None) -> None:
    """Change a state the way its integration would: same attributes, new value."""
    old = hass.states.get(entity_id)
    hass.states.async_set(entity_id, state, dict(old.attributes) if old else {}, context=context)


async def tick(hass, freezer, seconds: float) -> None:
    """Move the clock forward and let every timer and task run."""
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def scored(entry) -> list[tuple[str, float, str | None]]:
    """Return (rule, points, entity) for every contribution in the open incident."""
    incident = entry.runtime_data.engine.current
    return [] if incident is None else [(c.rule_id, round(c.points, 1), c.entity_id) for c in incident.contributions]
