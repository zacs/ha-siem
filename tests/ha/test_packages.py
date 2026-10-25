"""The packages, loaded into Home Assistant from packages/ as plain YAML and driven by real SIEM events."""

from __future__ import annotations

from pathlib import Path

from homeassistant.config import merge_packages_config
from homeassistant.core import Context
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import load_yaml
import pytest
from pytest_homeassistant_custom_component.common import async_mock_service

from .conftest import flip, nudge, settle, setup_siem

PACKAGES = Path(__file__).resolve().parents[2] / "packages"


@pytest.fixture(autouse=True)
def noon(freezer):
    freezer.move_to("2026-10-19 12:00:00-07:00")


async def load_package(hass, name: str, **variables) -> None:
    """Load a package the way Home Assistant does, with any of its EDIT variables changed."""
    package = load_yaml(PACKAGES / f"{name}.yaml")
    package["automation"][0]["variables"].update(variables)
    config = await merge_packages_config(hass, {}, {name: package})
    for domain in ("script", "automation"):
        if domain in config:
            assert await async_setup_component(hass, domain, config)
    await hass.async_block_till_done()
    assert hass.states.get(f"automation.{package['automation'][0]['alias'].lower().replace(' ', '_')}").state == "on"


async def test_phone_package_labels_and_replaces(hass, freezer):
    pushes = async_mock_service(hass, "notify", "mobile_app_your_phone")
    entry = await setup_siem(hass)
    await load_package(hass, "siem_mobile_app")
    flip(hass, "binary_sensor.back_door")
    await settle(hass)
    push = pushes[0].data
    incident_id = entry.runtime_data.incident_id
    assert push["title"] == "SIEM verify: Kitchen"
    assert push["message"].startswith("Score 40, house vacant.")
    assert push["data"]["tag"] == f"siem-{incident_id}"
    assert push["data"]["push"] == {"interruption-level": "active"}
    assert [b["title"] for b in push["data"]["actions"]] == ["False alarm", "That's me", "Real", "Guest"]
    # The phone's app is logged in as Zac; the notification is replaced by who answered and how.
    hass.states.async_set("person.zac", "home", {"friendly_name": "Zac", "user_id": "abc123"})
    hass.bus.async_fire("mobile_app_notification_action", {"action": push["data"]["actions"][1]["action"]}, context=Context(user_id="abc123"))
    await settle(hass)
    assert entry.runtime_data.engine.current.labels == ["thats_me"]
    assert pushes[-1].data == {
        "title": "SIEM: That's me",
        "message": "Verify incident in Kitchen labelled That's me by Zac.",
        "data": {"tag": f"siem-{incident_id}", "group": "siem"},
    }
    # The digest isn't pushed unless asked for.
    await hass.services.async_call("siem", "run_digest", {}, blocking=True)
    await settle(hass)
    assert len(pushes) == 2


async def test_mattermost_package_buttons_label_through_siems_webhook(hass, freezer, hass_client):
    hass.config.internal_url = "http://homeassistant.local:8123"
    posts = async_mock_service(hass, "notify", "mattermost")
    entry = await setup_siem(hass)
    await load_package(hass, "siem_mattermost")
    flip(hass, "binary_sensor.back_door")
    await settle(hass)
    verify = posts[0].data
    incident_id = entry.runtime_data.incident_id
    assert verify["target"] == ["home_security"]
    assert verify["message"] == ""
    attachment = verify["data"]["attachments"][0]
    assert attachment["color"] == "#F5B700"
    assert attachment["fallback"] == "SIEM verify: Kitchen. Score 40, house vacant."
    assert [f["value"] for f in attachment["fields"]] == ["Kitchen", "vacant", "40", "exterior_door_opened"]
    assert attachment["text"] == "**SIEM verify: Kitchen** Score 40, house vacant.\n\n- 12:00:00: **exterior_door_opened** +40 Back Door opened"
    hook = entry.runtime_data.store.label_webhook
    real = attachment["actions"][2]["integration"]
    assert real == {"url": f"http://homeassistant.local:8123/api/webhook/{hook}", "context": {"incident_id": incident_id, "label": "real"}}
    client = await hass_client()
    response = await client.post(f"/api/webhook/{hook}", json={"user_name": "zacs", "context": real["context"]})
    assert await response.json() == {"ephemeral_text": f"Incident {incident_id} labelled Real."}
    await settle(hass)
    assert posts[-1].data["message"] == f"SIEM: incident `{incident_id}` (Kitchen) labelled **Real** by @zacs."

    await hass.services.async_call("siem", "run_digest", {}, blocking=True)
    await settle(hass)
    digest = posts[-1].data["data"]["attachments"][0]
    assert digest["text"] == "**SIEM digest** Quiet since 2026-10-19 12:00.\n\nHouse mode: vacant."
    assert "actions" not in digest


async def test_mattermost_package_uses_the_address_you_give(hass, freezer):
    hass.config.internal_url = "http://homeassistant.local:8123"
    posts = async_mock_service(hass, "notify", "mattermost")
    entry = await setup_siem(hass)
    await load_package(hass, "siem_mattermost", ha_url="http://192.168.1.10:8123/")
    flip(hass, "binary_sensor.back_door")
    await settle(hass)
    url = posts[0].data["data"]["attachments"][0]["actions"][0]["integration"]["url"]
    assert url == f"http://192.168.1.10:8123/api/webhook/{entry.runtime_data.store.label_webhook}"


async def test_deterrence_package_lights_the_room_then_the_house(hass, freezer):
    kitchen = ar.async_get(hass).async_get_or_create("Kitchen")
    registry = er.async_get(hass)
    for unique_id in ("kitchen", "kitchen_2"):
        light = registry.async_get_or_create("light", "test", unique_id, suggested_object_id=unique_id)
        registry.async_update_entity(light.entity_id, area_id=kitchen.id)
    calls = async_mock_service(hass, "light", "turn_on")
    await setup_siem(hass)
    await load_package(hass, "siem_deterrence")
    for entity_id in ("binary_sensor.back_door", "binary_sensor.kitchen_presence"):
        flip(hass, entity_id)
        await settle(hass)
    assert hass.states.get("sensor.siem_tier").state == "deter"
    assert [c.data for c in calls] == [{"entity_id": ["light.kitchen", "light.kitchen_2"], "brightness_pct": 100}]
    flip(hass, "binary_sensor.fridge_door")
    await settle(hass)
    assert hass.states.get("sensor.siem_tier").state == "alarm"
    assert [c.data["entity_id"] for c in calls[1:]] == [["light.kitchen", "light.kitchen_2"], "all"]


async def test_escalation_package_when_nobody_answers(hass, freezer):
    partner = async_mock_service(hass, "notify", "mobile_app_partner_phone")
    notes = async_mock_service(hass, "persistent_notification", "create")
    entry = await setup_siem(hass)
    await load_package(hass, "siem_escalation")
    flip(hass, "binary_sensor.back_door")
    await nudge(hass)
    incident_id = entry.runtime_data.incident_id
    await nudge(hass, freezer, 4 * 60)
    assert partner == []
    await nudge(hass, freezer, 61, until=lambda: partner)
    push = partner[0].data
    assert push["title"] == "SIEM verify: Kitchen, no answer"
    assert push["message"].startswith("Nobody has labelled this verify incident yet. Back Door.")
    assert push["data"]["actions"][0]["action"] == f"SIEM_LABEL_FALSE_ALARM|{incident_id}"
    # Still nobody: script.siem_still_unanswered runs.
    await nudge(hass, freezer, 5 * 60 + 1, until=lambda: notes)
    assert [n.data["message"] for n in notes] == [f"Nobody has labelled the verify incident in Kitchen ({incident_id})."]
    # An answer after all is still passed on.
    await hass.services.async_call("siem", "label_incident", {"label": "false_alarm", "incident_id": incident_id}, blocking=True)
    await nudge(hass, until=lambda: len(partner) == 2)
    assert partner[-1].data["message"] == "Verify incident in Kitchen labelled False alarm."


async def test_escalation_package_stops_at_an_answer(hass, freezer):
    partner = async_mock_service(hass, "notify", "mobile_app_partner_phone")
    notes = async_mock_service(hass, "persistent_notification", "create")
    entry = await setup_siem(hass)
    await load_package(hass, "siem_escalation")
    flip(hass, "binary_sensor.back_door")
    await nudge(hass)
    await nudge(hass, freezer, 60)
    await hass.services.async_call("siem", "label_incident", {"label": "thats_me", "incident_id": entry.runtime_data.incident_id}, blocking=True)
    await nudge(hass, freezer, 15 * 60)
    assert partner == [] and notes == []
    # Answered between the escalation and the script: the script never runs, and the partner hears who answered.
    await nudge(hass, freezer, 3600)
    flip(hass, "binary_sensor.front_door")
    await nudge(hass)
    incident_id = entry.runtime_data.incident_id
    await nudge(hass, freezer, 5 * 60 + 1, until=lambda: partner)
    assert partner[-1].data["title"] == "SIEM verify: Hall, no answer"
    hass.states.async_set("person.zac", "home", {"friendly_name": "Zac", "user_id": "abc123"})
    hass.bus.async_fire("mobile_app_notification_action", {"action": f"SIEM_LABEL_GUEST|{incident_id}"}, context=Context(user_id="abc123"))
    await nudge(hass, until=lambda: len(partner) == 2)
    assert partner[-1].data["message"] == "Verify incident in Hall labelled Guest by Zac."
    await nudge(hass, freezer, 10 * 60)
    assert notes == []
