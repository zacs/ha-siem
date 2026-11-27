"""The logbook's "What happened": SIEM writes its states under the context of what caused them."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from homeassistant.core import Context
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.components.recorder.common import async_wait_recording_done

from .conftest import RESIDENT, flip, setup_siem, tick


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations):
    """The logbook reads the recorder, which has to start before Home Assistant does."""
    return


async def test_the_logbook_names_the_door_behind_an_incident(hass, hass_ws_client):
    """What the activity dialog asks the logbook for: the incident sensor's change, caused by the back door."""
    # The logbook only needs the frontend for its sidebar panel, and the frontend's files aren't installed for tests.
    hass.config.components.add("frontend")
    with patch("homeassistant.components.logbook.frontend.async_register_built_in_panel"):
        assert await async_setup_component(hass, "logbook", {})
    await setup_siem(hass)
    door = Context()
    flip(hass, "binary_sensor.back_door", context=door)
    await hass.async_block_till_done()
    await async_wait_recording_done(hass)
    client = await hass_ws_client()
    start = (dt_util.utcnow() - timedelta(hours=1)).isoformat()
    await client.send_json({"id": 1, "type": "logbook/get_events", "start_time": start, "entity_ids": ["sensor.siem_incident", "sensor.siem_tier"]})
    response = await client.receive_json()
    assert response["success"]
    changes = [e for e in response["result"] if e["state"] not in ("none", "unknown")]
    assert {e["entity_id"] for e in changes} == {"sensor.siem_incident", "sensor.siem_tier"}
    # The dialog shows this pair as the origin: Back Door, turned on.
    for change in changes:
        assert (change["context_entity_id"], change["context_state"]) == ("binary_sensor.back_door", "on")


async def test_each_change_carries_its_own_cause(hass, freezer):
    """The tier rises under the change that raised it; the alarm trigger, a minute later, under the change that took
    the incident to alarm; the house mode under the person who came home, or the action that forced it."""
    await setup_siem(hass)
    back, kitchen, front = Context(), Context(), Context()
    flip(hass, "binary_sensor.back_door", context=back)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.siem_tier").state == "verify"
    assert hass.states.get("sensor.siem_tier").context.id == back.id
    flip(hass, "binary_sensor.kitchen_presence", context=kitchen)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.siem_tier").state == "deter"
    assert hass.states.get("sensor.siem_tier").context.id == kitchen.id
    flip(hass, "binary_sensor.front_door", context=front)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.siem_tier").state == "alarm"
    await tick(hass, freezer, 61)
    trigger = hass.states.get("binary_sensor.siem_alarm_trigger")
    assert trigger.state == "on" and trigger.context.id == front.id, "a minute later, still the front door"

    home = Context()
    flip(hass, "device_tracker.alice_phone", "home", context=home)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.siem_house_mode").state == "family"
    assert hass.states.get("sensor.siem_house_mode").context.id == home.id

    asked = Context(user_id=RESIDENT)
    await hass.services.async_call("siem", "set_house_mode", {"mode": "guest"}, blocking=True, context=asked)
    assert hass.states.get("sensor.siem_house_mode").context.id == asked.id


async def test_a_change_with_no_cause_records_none(hass, freezer):
    """The clock alone (the score fading, an incident closing) has nothing to point at, and points at nothing."""
    await setup_siem(hass)
    door = Context()
    flip(hass, "binary_sensor.back_door", context=door)
    await hass.async_block_till_done()
    for _ in range(12):
        await tick(hass, freezer, 600)
    incident = hass.states.get("sensor.siem_incident")
    assert incident.state == "none" and incident.context.id != door.id
