"""Scoring inside Home Assistant: origins, startup, outages, cooldowns, guest mode, labels, locks."""

from __future__ import annotations

from homeassistant.core import Context
from homeassistant.exceptions import ServiceValidationError
import pytest

from .conftest import TRUSTED, UNTRUSTED, notifications, scored, setup_siem, tick


@pytest.fixture(autouse=True)
def noon(freezer):
    """Daytime on a weekday, outside the night window."""
    freezer.move_to("2026-10-19 12:00:00-07:00")


async def test_physical_door_opens_a_verify_incident(hass, freezer, service_calls, siem_events):
    entry = await setup_siem(hass)
    assert hass.states.get("sensor.siem_house_mode").state == "vacant"
    hass.states.async_set("binary_sensor.back_door", "on", {"device_class": "door", "friendly_name": "Back Door"})
    await hass.async_block_till_done()
    assert scored(entry) == [("exterior_door_opened", 40.0, "binary_sensor.back_door")]
    assert hass.states.get("sensor.siem_tier").state == "verify"
    incident_events = [data for kind, data in siem_events if kind == "siem_incident"]
    assert [e["kind"] for e in incident_events] == ["opened", "tier_changed"]
    assert incident_events[1]["tier"] == "verify" and incident_events[1]["room"] == "Kitchen"
    assert incident_events[1]["timeline"][0]["name"] == "Back Door"
    # The fields the README documents, no more and no fewer.
    incident_fields = {"incident_id", "tier", "peak_tier", "score", "peak_score", "room", "mode", "house_mode", "person", "started", "closed", "labels", "top_contributors", "timeline"}
    assert set(incident_events[1]) == incident_fields | {"kind", "previous_tier"}
    assert set(incident_events[1]["timeline"][0]) == {"at", "rule", "points", "entity_id", "name", "room", "description", "detail"}
    assert incident_events[1]["timeline"][0]["room"] == "Kitchen"
    assert set(incident_events[1]["top_contributors"][0]) == {"rule", "points", "entities"}
    event_entity = hass.states.get("event.siem_incident").attributes
    assert {"event_type", "incident_id", "tier", "previous_tier", "score", "room", "mode"} <= set(event_entity)
    alert = notifications(siem_events, "verify")[0]
    assert alert["title"] == "SIEM verify: Kitchen"
    assert alert["dry_run"] is True
    assert alert["message"].startswith("[DRY RUN] Score 40, house vacant.")
    assert alert["message"].endswith("12:00 Back Door: An exterior door or window opened (+40)")
    assert alert["incident"]["incident_id"] == entry.runtime_data.incident_id
    # Every field is present on every alert, and SIEM itself calls no notify service.
    assert set(alert) == {"category", "title", "message", "dry_run", "incident", "actions", "snapshot", "again", "summary"}
    assert alert["actions"] == [] and alert["snapshot"] is None and alert["summary"] is None
    assert not [call for call in service_calls if call[0] in ("notify", "alarm_control_panel")]


async def test_automations_users_and_homekit(hass, freezer, siem_events):
    entry = await setup_siem(hass)
    # A time-triggered automation has neither parent nor user; its context is announced by automation_triggered.
    run = Context()
    hass.bus.async_fire("automation_triggered", {"name": "Porch at sunset"}, context=run)
    hass.states.async_set("light.kitchen", "on", {"friendly_name": "Kitchen Light"}, context=run)
    # A state-triggered automation carries a parent id.
    hass.states.async_set("binary_sensor.fridge_door", "on", {"device_class": "door"}, context=Context(parent_id="trigger"))
    # A trusted user from the UI.
    hass.states.async_set("light.kitchen_2", "on", {"friendly_name": "Kitchen Light 2"}, context=Context(user_id=TRUSTED))
    await hass.async_block_till_done()
    assert scored(entry) == []
    # An untrusted user scores the account rule, named in the detail.
    hass.states.async_set("light.kitchen_2", "off", {"friendly_name": "Kitchen Light 2"}, context=Context(user_id=UNTRUSTED))
    await hass.async_block_till_done()
    assert scored(entry) == [("untrusted_user", 70.0, "light.kitchen_2")]
    assert entry.runtime_data.engine.current.contributions[0].detail == "set to off by Mallory"
    # A light switched from Apple Home scores the HomeKit rule.
    homekit = Context()
    hass.bus.async_fire("homekit_state_change", {"entity_id": "light.kitchen"}, context=homekit)
    hass.states.async_set("light.kitchen", "off", {}, context=Context(parent_id="x"))
    await hass.async_block_till_done()
    hass.states.async_set("light.kitchen", "on", {}, context=homekit)
    await hass.async_block_till_done()
    assert scored(entry)[-1] == ("light_homekit", 5.0, "light.kitchen")


async def test_startup_and_reconnects_are_not_events(hass, freezer):
    entry = await setup_siem(hass)
    # An integration reloading: unavailable, then back to where it was.
    hass.states.async_set("binary_sensor.back_door", "unavailable")
    await hass.async_block_till_done()
    hass.states.async_set("binary_sensor.back_door", "on", {"device_class": "door"})
    hass.states.async_set("sensor.coffee_power", "unknown")
    await hass.async_block_till_done()
    hass.states.async_set("sensor.coffee_power", "1200")
    # An entity that appears for the first time already on.
    hass.states.async_remove("light.kitchen")
    await hass.async_block_till_done()
    hass.states.async_set("light.kitchen", "on")
    await hass.async_block_till_done()
    await tick(hass, freezer, 30)
    assert scored(entry) == []


async def test_outages_score_once_after_a_grace_period(hass, freezer, siem_events):
    entry = await setup_siem(hass)
    for entity_id in ("binary_sensor.back_door", "binary_sensor.kitchen_motion", "binary_sensor.fridge_door", "light.kitchen", "sensor.coffee_power"):
        hass.states.async_set(entity_id, "unavailable", {"friendly_name": hass.states.get(entity_id).name})
    await hass.async_block_till_done()
    await tick(hass, freezer, 90)
    assert scored(entry) == [], "a reload or restart must pass quietly"
    await tick(hass, freezer, 60)
    # Three sensing entities, one contribution; the light and the plug are not sensors.
    assert scored(entry) == [("sensor_offline", 20.0, None)]
    assert entry.runtime_data.engine.current.contributions[0].detail.startswith("3 sensors unavailable: Back Door, Kitchen Motion, Fridge Door")
    await tick(hass, freezer, 3600)
    glass = notifications(siem_events, "break_glass")
    assert len(glass) == 1 and "unavailable for over an hour while the house is vacant" in glass[0]["message"]
    await tick(hass, freezer, 3600)
    assert len(notifications(siem_events, "break_glass")) == 1


async def test_one_switch_lighting_a_room_and_contact_bounce_count_once(hass, freezer):
    entry = await setup_siem(hass)
    hass.states.async_set("light.kitchen", "on")
    hass.states.async_set("light.kitchen_2", "on")
    for state in ("on", "off", "on"):
        hass.states.async_set("binary_sensor.yard_gate", state, {"device_class": "door", "friendly_name": "Yard Gate"})
        await hass.async_block_till_done()
    rules = [rule for rule, _, _ in scored(entry)]
    assert rules.count("light_physical") == 1
    assert rules.count("gate_opened") == 1


async def test_appliance_and_water_cross_their_thresholds(hass, freezer):
    entry = await setup_siem(hass)
    for value in ("5", "1100", "1200"):
        hass.states.async_set("sensor.coffee_power", value)
        await hass.async_block_till_done()
    hass.states.async_set("sensor.water_flow", "4")
    await hass.async_block_till_done()
    assert [r for r, _, _ in scored(entry)] == ["appliance_on", "water_flow"]


async def test_guest_mode_from_a_pin_ends_even_with_busy_power_sensors(hass, freezer):
    await setup_siem(hass)
    hass.states.async_set("event.lcm_pat", "2026-10-19T19:00:00+00:00", {"code_slot": 3, "name": "Pat", "operation": "unlock"})
    await hass.async_block_till_done()
    assert hass.states.get("sensor.siem_house_mode").state == "guest"
    # A plug reporting every minute is not activity; only real events keep guest mode alive.
    for minute in range(4 * 60):
        hass.states.async_set("sensor.coffee_power", str(minute % 3))
        hass.states.async_set("sensor.house_power", str(300 + minute % 7))
        await tick(hass, freezer, 60)
    assert hass.states.get("sensor.siem_house_mode").state == "vacant"


async def test_people_labels_leave_weights_alone(hass, freezer):
    entry = await setup_siem(hass)
    hass.states.async_set("binary_sensor.back_door", "on")
    await hass.async_block_till_done()
    await hass.services.async_call("siem", "label_incident", {"label": "thats_me"}, blocking=True)
    await hass.services.async_call("siem", "label_incident", {"label": "guest"}, blocking=True)
    assert entry.runtime_data.store.weights == {}
    await hass.services.async_call("siem", "label_incident", {"label": "false_alarm"}, blocking=True)
    assert entry.runtime_data.store.weights == {"exterior_door_opened": 0.9}
    assert hass.states.get("select.siem_label_last_incident").state == "false_alarm"


async def test_lock_events_only_for_configured_locks(hass, freezer, siem_events):
    entry = await setup_siem(hass)
    hass.bus.async_fire("lock_code_manager_lock_state_changed", {"entity_id": "lock.shed", "action_text": "Manual unlock operation", "code_slot": 0})
    await hass.async_block_till_done()
    assert scored(entry) == []
    hass.bus.async_fire("lock_code_manager_lock_state_changed", {"entity_id": "lock.front_door", "action_text": "Keypad unlock operation", "code_slot": 3})
    await hass.async_block_till_done()
    assert scored(entry) == [], "slot 3 belongs to an LCM user"
    hass.bus.async_fire("lock_code_manager_lock_state_changed", {"entity_id": "lock.front_door", "action_text": "Keypad unlock operation", "code_slot": 9})
    hass.bus.async_fire("lock_code_manager_lock_state_changed", {"entity_id": "lock.front_door", "action_text": "Manual unlock operation", "code_slot": 0})
    await hass.async_block_till_done()
    assert [r for r, _, _ in scored(entry)] == ["pin_not_allowed", "manual_unlock"]
    glass = notifications(siem_events, "break_glass")
    assert len(glass) == 1 and glass[0]["message"].startswith("[DRY RUN] Front Door Lock: a lock was unlocked by hand")


async def test_override_survives_a_reload(hass, freezer):
    entry = await setup_siem(hass)
    await hass.services.async_call("siem", "set_house_mode", {"mode": "guest"}, blocking=True)
    assert hass.states.get("select.siem_house_mode_override").state == "guest"
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.siem_house_mode").state == "guest"
    assert hass.states.get("select.siem_house_mode_override").state == "guest"


async def test_label_errors_are_validation_errors(hass, freezer):
    await setup_siem(hass)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call("siem", "label_incident", {"label": "real"}, blocking=True)
