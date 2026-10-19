"""The dry-run test package loads cleanly, its mirrors look physical, the walkthrough scores, and the simulation runs."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from homeassistant.components import persistent_notification as pn
from homeassistant.config import merge_packages_config
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from homeassistant.util.yaml import load_yaml
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.siem.config_flow import build_entity_meta
from custom_components.siem.const import DOMAIN

# The package's two-second template trigger is still scheduled when the test ends.
pytestmark = pytest.mark.parametrize("expected_lingering_timers", [True])

PACKAGE = Path(__file__).resolve().parents[2] / "dev" / "siem_test_entities.yaml"
MIRRORS = [
    "binary_sensor.test_kitchen_motion", "binary_sensor.test_kitchen_presence", "binary_sensor.test_kitchen_sound", "binary_sensor.test_kitchen_back_door",
    "binary_sensor.test_kitchen_window", "binary_sensor.test_kitchen_fridge_door", "binary_sensor.test_living_room_motion", "binary_sensor.test_front_door",
    "binary_sensor.test_backyard_gate", "binary_sensor.test_backyard_camera_person", "binary_sensor.test_front_door_csi",
]


@pytest.fixture(autouse=True)
def no_known_devices():
    """device_tracker.see would write known_devices.yaml into the shared test config."""
    with patch("homeassistant.components.device_tracker.legacy.update_config"):
        yield


async def load_package(hass, simulation: bool) -> None:
    config = await merge_packages_config(hass, {}, {"siem_test": load_yaml(PACKAGE)})
    for domain in ("persistent_notification", "notify", "scene", *config):
        assert await async_setup_component(hass, domain, config), domain
    await hass.async_block_till_done()
    # The test instance is already running; replay the start event the package's automation and universal player wait for.
    hass.bus.async_fire("homeassistant_start")
    await hass.async_block_till_done()
    if not simulation:
        await hass.services.async_call("input_boolean", "turn_off", {"entity_id": "input_boolean.test_simulation"}, blocking=True)
        await hass.async_block_till_done()


async def tick(hass, freezer, seconds: float) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def template_errors(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelname == "ERROR" and ("template" in r.name or "rendering" in r.getMessage())]


async def test_walkthrough_steps_one_and_two(hass, freezer, caplog):
    freezer.move_to("2026-10-19 12:00:00-07:00")
    await load_package(hass, simulation=False)
    await tick(hass, freezer, 3)
    for entity_id in [*MIRRORS, "light.test_kitchen_light", "lock.test_front_door_lock", "event.test_lcm_guest_credential_used", "person.test_alice", "sensor.test_house_load"]:
        assert hass.states.get(entity_id) is not None, entity_id
    rooms = {
        "kitchen": {"name": "Test Kitchen", "occupancy": ["binary_sensor.test_kitchen_motion"], "perimeter": ["binary_sensor.test_kitchen_back_door"], "power_threshold": 30},
    }
    data = {"rooms": rooms, "house": {"residents": ["person.test_alice", "person.test_bob"]}, "responses": {"dry_run": True}}
    data["entities"] = build_entity_meta(hass, data)
    assert data["entities"]["binary_sensor.test_kitchen_motion"]["strength"] == "medium"
    entry = MockConfigEntry(domain=DOMAIN, data=data, version=1, minor_version=2)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.siem_house_mode").state == "vacant"
    # The helpers are flipped from the UI with a user id; the mirrors re-render on a timer and look physical.
    for helper in ("input_boolean.test_kitchen_back_door", "input_boolean.test_kitchen_motion"):
        await hass.services.async_call("input_boolean", "turn_on", {"entity_id": helper}, blocking=True)
        await tick(hass, freezer, 2)
    # Back door 40, then medium motion 30 x 1.5 for the entry chain: 85, two seconds of decay later.
    assert float(hass.states.get("sensor.siem_risk_score").state) == pytest.approx(85, abs=0.5)
    assert hass.states.get("sensor.siem_tier").state == "alarm"
    # The package's own automation shows SIEM's alerts as persistent notifications.
    await hass.async_block_till_done()
    titles = [n["title"] for n in pn._async_get_or_create_notifications(hass).values()]
    assert "SIEM verify: Test Kitchen" in titles and "SIEM alarm: Test Kitchen" in titles
    assert not template_errors(caplog), template_errors(caplog)


async def test_simulation_runs_and_the_guest_visits(hass, freezer, caplog):
    freezer.move_to("2026-10-19 07:00:00-07:00")
    await load_package(hass, simulation=True)
    await tick(hass, freezer, 3)
    changes = dict.fromkeys(MIRRORS, 0)

    @callback
    def count(event):
        if event.data["old_state"] is not None and event.data["new_state"].state != event.data["old_state"].state:
            changes[event.data["entity_id"]] += 1

    async_track_state_change_event(hass, MIRRORS, count)
    await hass.services.async_call("input_number", "set_value", {"entity_id": "input_number.test_simulation_rate", "value": 10}, blocking=True)
    await hass.services.async_call("input_select", "select_option", {"entity_id": "input_select.test_sim_scene_override", "option": "morning"}, blocking=True)
    for _ in range(150):
        await tick(hass, freezer, 2)
    assert hass.states.get("sensor.test_sim_scene").state == "morning"
    assert hass.states.get("person.test_alice").state == "home"
    assert sum(changes.values()) >= 10, changes
    float(hass.states.get("sensor.test_house_load").state)
    # A weekday afternoon away: the guest eventually lets themselves in with a PIN.
    freezer.move_to(dt_util.as_utc(dt_util.now().replace(hour=14, minute=0, second=0)))
    await hass.services.async_call("input_select", "select_option", {"entity_id": "input_select.test_sim_scene_override", "option": "away"}, blocking=True)
    await tick(hass, freezer, 2)
    await tick(hass, freezer, 2)
    assert hass.states.get("person.test_alice").state == "not_home"
    before = hass.states.get("event.test_lcm_guest_credential_used").state
    for _ in range(3000):
        await tick(hass, freezer, 2)
        if hass.states.get("event.test_lcm_guest_credential_used").state != before:
            break
    event = hass.states.get("event.test_lcm_guest_credential_used")
    assert event.state != before and event.attributes["operation"] == "unlock" and event.attributes["name"] == "Test Guest"
    assert not template_errors(caplog), template_errors(caplog)
