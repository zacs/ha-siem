"""Labelling incidents from notifications: SIEM's webhook, the labelled event, repeats and restarts."""

from __future__ import annotations

from homeassistant.core import Context, callback
import pytest

from .conftest import flip, notifications, setup_siem, tick


@pytest.fixture(autouse=True)
def noon(freezer):
    freezer.move_to("2026-10-19 12:00:00-07:00")


@pytest.fixture
def labelled(hass):
    """Collect the labelled incident events."""
    events = []
    hass.bus.async_listen("siem_incident", callback(lambda event: events.append(dict(event.data)) if event.data["kind"] == "labelled" else None))
    return events


async def test_a_chat_button_labels_its_own_incident(hass, freezer, hass_client, siem_events, labelled):
    hass.config.internal_url = "http://homeassistant.local:8123"
    entry = await setup_siem(hass)
    flip(hass, "binary_sensor.back_door")
    await hass.async_block_till_done()
    first = entry.runtime_data.incident_id
    alert = notifications(siem_events, "verify")[0]
    hook = entry.runtime_data.store.label_webhook
    assert alert["label_url"] == f"http://homeassistant.local:8123/api/webhook/{hook}"
    # A second incident opens later; the first notification's button still labels the first one.
    await tick(hass, freezer, 3 * 3600)
    flip(hass, "binary_sensor.front_door")
    await hass.async_block_till_done()
    assert entry.runtime_data.incident_id != first

    client = await hass_client()
    body = {"user_name": "zacs", "context": {"incident_id": first, "label": "false_alarm"}}
    response = await client.post(f"/api/webhook/{hook}", json=body)
    assert response.status == 200
    assert await response.json() == {"ephemeral_text": f"Incident {first} labelled False alarm."}
    assert entry.runtime_data.store.weights == {"exterior_door_opened": 0.9}
    assert entry.runtime_data.engine.current.labels == []
    assert [(e["incident_id"], e["label"], e["by"]) for e in labelled] == [(first, "false_alarm", "zacs")]
    # Pressed again: nothing changes twice.
    response = await client.post(f"/api/webhook/{hook}", json=body)
    assert await response.json() == {"ephemeral_text": f"Incident {first} was already labelled False alarm."}
    assert entry.runtime_data.store.weights == {"exterior_door_opened": 0.9}
    assert len(labelled) == 1
    response = await client.post(f"/api/webhook/{hook}", json={"context": {"incident_id": "deadbeef", "label": "real"}})
    assert await response.json() == {"ephemeral_text": "SIEM no longer knows incident deadbeef."}
    response = await client.post(f"/api/webhook/{hook}", json={"incident_id": first, "label": "maybe"})
    assert await response.json() == {"ephemeral_text": "SIEM doesn't know the label 'maybe'."}


async def test_a_phone_button_after_a_restart(hass, freezer, labelled):
    entry = await setup_siem(hass)
    flip(hass, "binary_sensor.back_door")
    await hass.async_block_till_done()
    incident_id = entry.runtime_data.incident_id
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.engine.find(incident_id) is None
    # The phone's app is logged in as Zac, whose person entity names who pressed it.
    hass.states.async_set("person.zac", "home", {"friendly_name": "Zac", "user_id": "abc123"})
    hass.bus.async_fire("mobile_app_notification_action", {"action": f"SIEM_LABEL_THATS_ME|{incident_id}"}, context=Context(user_id="abc123"))
    await hass.async_block_till_done()
    stored = next(i for i in entry.runtime_data.store.incidents if i["id"] == incident_id)
    assert stored["labels"] == ["thats_me"]
    assert labelled[0]["incident_id"] == incident_id and labelled[0]["entities"] == ["binary_sensor.back_door"]
    assert labelled[0]["by"] == "Zac"
    assert hass.states.get("event.siem_incident").attributes["event_type"] == "labelled"
