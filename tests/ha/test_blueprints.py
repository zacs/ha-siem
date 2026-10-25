"""The blueprints, loaded into Home Assistant from blueprints/ and driven by real SIEM events."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
import shutil

from homeassistant.core import Context
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed, async_mock_service

from .conftest import flip, setup_siem

BLUEPRINTS = Path(__file__).resolve().parents[2] / "blueprints"


@pytest.fixture(autouse=True)
def noon(freezer):
    freezer.move_to("2026-10-19 12:00:00-07:00")


@pytest.fixture(autouse=True)
def blueprints(hass, tmp_path):
    """Serve the repository's blueprints from a configuration folder of the test's own."""
    hass.config.config_dir = str(tmp_path)
    shutil.copytree(BLUEPRINTS, tmp_path / "blueprints")


async def settle(hass) -> None:
    """Let SIEM's response task fire its event, then the automation run."""
    for _ in range(3):
        await hass.async_block_till_done()


async def nudge(hass, freezer=None, seconds: float = 0) -> None:
    """Move the clock and let callbacks run, without waiting for an escalation that is itself waiting."""
    if seconds:
        freezer.tick(timedelta(seconds=seconds))
        async_fire_time_changed(hass)
    for _ in range(20):
        await asyncio.sleep(0)


async def use_blueprint(hass, name: str, inputs: dict) -> None:
    config = {"automation": [{"alias": name, "use_blueprint": {"path": f"siem/{name}.yaml", "input": inputs}}]}
    assert await async_setup_component(hass, "automation", config)
    await hass.async_block_till_done()
    assert hass.states.get(f"automation.{name}").state == "on", f"{name} did not load"


def phone(hass, name: str) -> str:
    """A companion-app phone in the device registry; its notify action is named after it."""
    owner = MockConfigEntry(domain="mobile_app", title=name)
    owner.add_to_hass(hass)
    return dr.async_get(hass).async_get_or_create(config_entry_id=owner.entry_id, identifiers={("mobile_app", name)}, name=name).id


async def test_phones_get_buttons_that_label_their_own_incident(hass, freezer):
    pushes = async_mock_service(hass, "notify", "mobile_app_your_phone")
    entry = await setup_siem(hass)
    await use_blueprint(hass, "mobile_app", {"phones": [phone(hass, "Your Phone")]})
    flip(hass, "binary_sensor.back_door")
    await settle(hass)
    push = pushes[0].data
    incident_id = entry.runtime_data.incident_id
    assert push["title"] == "SIEM verify: Kitchen"
    assert push["message"].startswith("Score 40, house vacant.")
    assert push["data"]["tag"] == f"siem-{incident_id}"
    assert push["data"]["push"] == {"interruption-level": "active"}
    assert [b["title"] for b in push["data"]["actions"]] == ["False alarm", "That's me", "Real", "Guest"]
    assert push["data"]["actions"][1]["action"] == f"SIEM_LABEL_THATS_ME|{incident_id}"
    # SIEM hears the button itself; the phone's notification is then replaced by the outcome.
    hass.bus.async_fire("mobile_app_notification_action", {"action": push["data"]["actions"][1]["action"]}, context=Context())
    await settle(hass)
    assert entry.runtime_data.engine.current.labels == ["thats_me"]
    assert pushes[-1].data == {
        "title": "SIEM: That's me",
        "message": "Verify incident in Kitchen labelled That's me.",
        "data": {"tag": f"siem-{incident_id}", "group": "siem"},
    }
    # The digest isn't pushed unless asked for.
    await hass.services.async_call("siem", "run_digest", {}, blocking=True)
    await settle(hass)
    assert len(pushes) == 2


async def test_mattermost_buttons_label_through_siems_webhook(hass, freezer, hass_client):
    hass.config.internal_url = "http://homeassistant.local:8123"
    posts = async_mock_service(hass, "notify", "mattermost")
    entry = await setup_siem(hass)
    await use_blueprint(hass, "mattermost", {"channel": "home_security"})
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
    assert [a["name"] for a in attachment["actions"]] == ["False alarm", "That's me", "Real", "Guest"]
    that_s_me = attachment["actions"][1]["integration"]
    assert that_s_me == {"url": f"http://homeassistant.local:8123/api/webhook/{hook}", "context": {"incident_id": incident_id, "label": "thats_me"}}
    # What Mattermost posts when the button is pressed.
    client = await hass_client()
    response = await client.post(f"/api/webhook/{hook}", json={"user_name": "zacs", "context": that_s_me["context"]})
    assert await response.json() == {"ephemeral_text": f"Incident {incident_id} labelled That's me."}
    await settle(hass)
    assert posts[-1].data["message"] == f"SIEM: incident `{incident_id}` (Kitchen) labelled **That's me** by @zacs."

    # The digest has no incident, so no buttons: its own text follows the headline.
    await hass.services.async_call("siem", "run_digest", {}, blocking=True)
    await settle(hass)
    digest = posts[-1].data["data"]["attachments"][0]
    assert digest["color"] == "#1976D2" and digest["fields"] == [] and "actions" not in digest
    assert digest["text"] == "**SIEM digest** Quiet since 2026-10-19 12:00.\n\nHouse mode: vacant."
    assert digest["fallback"] == "SIEM digest. Quiet since 2026-10-19 12:00."
    # A snapshot travels as data.file.path.
    hass.bus.async_fire("siem_notification", {"category": "verify", "title": "SIEM verify: Hall", "message": "Score 20, house vacant.", "incident": None, "snapshot": "/media/siem/abc_verify.jpg", "again": False, "summary": None, "label_url": None})
    await settle(hass)
    assert posts[-1].data["data"]["file"] == {"path": "/media/siem/abc_verify.jpg"}


async def test_mattermost_buttons_use_the_address_you_give(hass, freezer):
    hass.config.internal_url = "http://homeassistant.local:8123"
    posts = async_mock_service(hass, "notify", "mattermost")
    entry = await setup_siem(hass)
    await use_blueprint(hass, "mattermost", {"channel": "home_security", "ha_url": "http://192.168.1.10:8123/"})
    flip(hass, "binary_sensor.back_door")
    await settle(hass)
    url = posts[0].data["data"]["attachments"][0]["actions"][0]["integration"]["url"]
    assert url == f"http://192.168.1.10:8123/api/webhook/{entry.runtime_data.store.label_webhook}"


async def test_deterrence_lights_the_room_then_the_house(hass, freezer):
    kitchen = ar.async_get(hass).async_get_or_create("Kitchen")
    registry = er.async_get(hass)
    for unique_id in ("kitchen", "kitchen_2"):
        light = registry.async_get_or_create("light", "test", unique_id, suggested_object_id=unique_id)
        registry.async_update_entity(light.entity_id, area_id=kitchen.id)
    calls = async_mock_service(hass, "light", "turn_on")
    sirens = async_mock_service(hass, "siren", "turn_on")
    await setup_siem(hass)
    await use_blueprint(hass, "deterrence", {"alarm_actions": [{"action": "siren.turn_on", "target": {"entity_id": "siren.hall"}}]})
    for entity_id in ("binary_sensor.back_door", "binary_sensor.kitchen_presence"):
        flip(hass, entity_id)
        await settle(hass)
    assert hass.states.get("sensor.siem_tier").state == "deter"
    assert [c.data for c in calls] == [{"entity_id": ["light.kitchen", "light.kitchen_2"], "brightness_pct": 100}]
    assert sirens == []
    flip(hass, "binary_sensor.fridge_door")
    await settle(hass)
    assert hass.states.get("sensor.siem_tier").state == "alarm"
    assert [c.data["entity_id"] for c in calls[1:]] == [["light.kitchen", "light.kitchen_2"], "all"]
    assert [c.data["entity_id"] for c in sirens] == [["siren.hall"]]


async def test_escalation_when_nobody_answers(hass, freezer):
    partner = async_mock_service(hass, "notify", "mobile_app_partner_phone")
    calls = async_mock_service(hass, "script", "call_the_neighbor")
    entry = await setup_siem(hass)
    inputs = {"escalate_to": [phone(hass, "Partner Phone")], "wait": 5, "still_unanswered": [{"action": "script.call_the_neighbor"}]}
    await use_blueprint(hass, "escalation", inputs)
    flip(hass, "binary_sensor.back_door")
    await nudge(hass)
    incident_id = entry.runtime_data.incident_id
    await nudge(hass, freezer, 4 * 60)
    assert partner == []
    await nudge(hass, freezer, 61)
    push = partner[0].data
    assert push["title"] == "SIEM verify: Kitchen, no answer"
    assert push["message"].startswith("Nobody has labelled this verify incident yet. Back Door.")
    assert push["data"]["tag"] == f"siem-{incident_id}"
    assert push["data"]["actions"][0]["action"] == f"SIEM_LABEL_FALSE_ALARM|{incident_id}"
    await nudge(hass, freezer, 5 * 60 + 1)
    assert len(calls) == 1, "still unanswered after the escalation too"


async def test_an_answer_stops_the_escalation_and_an_alarm_skips_the_wait(hass, freezer):
    partner = async_mock_service(hass, "notify", "mobile_app_partner_phone")
    entry = await setup_siem(hass)
    await use_blueprint(hass, "escalation", {"escalate_to": [phone(hass, "Partner Phone")], "wait": 5})
    flip(hass, "binary_sensor.back_door")
    await nudge(hass)
    await nudge(hass, freezer, 60)
    await hass.services.async_call("siem", "label_incident", {"label": "thats_me", "incident_id": entry.runtime_data.incident_id}, blocking=True)
    await nudge(hass, freezer, 10 * 60)
    assert partner == []
    # A new incident that climbs to alarm is escalated at once.
    await nudge(hass, freezer, 3600)
    for entity_id in ("binary_sensor.front_door", "binary_sensor.kitchen_presence", "binary_sensor.fridge_door"):
        flip(hass, entity_id)
        await nudge(hass)
    assert hass.states.get("sensor.siem_tier").state == "alarm"
    assert partner and partner[-1].data["title"] == "SIEM alarm: Hall, no answer"
    # Once someone answers, the escalation is replaced by who answered and how.
    hass.states.async_set("person.zac", "home", {"friendly_name": "Zac", "user_id": "abc123"})
    hass.bus.async_fire("mobile_app_notification_action", {"action": f"SIEM_LABEL_REAL|{entry.runtime_data.incident_id}"}, context=Context(user_id="abc123"))
    await nudge(hass)
    assert partner[-1].data["title"] == "SIEM: Real"
    assert partner[-1].data["message"] == "Alarm incident in Hall labelled Real by Zac."
    assert "actions" not in partner[-1].data["data"]
