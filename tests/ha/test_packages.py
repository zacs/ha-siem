"""The sample packages, loaded into Home Assistant and driven by real SIEM events."""

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

from .conftest import flip, setup_siem

PACKAGES = Path(__file__).resolve().parents[2] / "packages"


@pytest.fixture(autouse=True)
def noon(freezer):
    freezer.move_to("2026-10-19 12:00:00-07:00")


async def settle(hass) -> None:
    """Let SIEM's response task fire its event, then the package's automation run."""
    for _ in range(3):
        await hass.async_block_till_done()


async def load_package(hass, name: str) -> None:
    config = await merge_packages_config(hass, {}, {name: load_yaml(PACKAGES / f"{name}.yaml")})
    assert await async_setup_component(hass, "automation", config)
    await hass.async_block_till_done()


async def test_mattermost_package(hass, freezer):
    posts = async_mock_service(hass, "notify", "mattermost")
    await setup_siem(hass)
    await load_package(hass, "siem_mattermost")
    flip(hass, "binary_sensor.back_door")
    await settle(hass)
    verify = posts[0].data
    assert verify["target"] == ["home_security"]
    # Everything sits inside the attachment, headline first: the post has no text above it.
    assert verify["message"] == ""
    attachment = verify["data"]["attachments"][0]
    assert attachment["color"] == "#F5B700"
    assert attachment["fallback"] == "SIEM verify: Kitchen. Score 40, house vacant."
    assert [f["title"] for f in attachment["fields"]] == ["Room", "House mode", "Score", "Top contributors"]
    assert [f["value"] for f in attachment["fields"]] == ["Kitchen", "vacant", "40", "exterior_door_opened"]
    assert attachment["text"] == "**SIEM verify: Kitchen** Score 40, house vacant.\n\n- 12:00:00: **exterior_door_opened** +40 Back Door opened"
    assert "file" not in verify["data"]

    def text(post) -> str:
        return post.data["data"]["attachments"][0]["text"]

    hass.bus.async_fire("lock_code_manager_lock_state_changed", {"entity_id": "lock.front_door", "action_text": "Manual unlock operation", "code_slot": 0})
    await settle(hass)
    glass = next(p for p in posts if text(p).startswith("**SIEM break glass**"))
    # The incident was open, so its timeline follows the headline.
    assert text(glass).splitlines()[0] == "**SIEM break glass** Front Door Lock: a lock was unlocked by hand (Manual unlock operation). House vacant."
    assert text(glass).splitlines()[-1] == "- 12:00:00: **manual_unlock** +60 Front Door Lock Manual unlock operation"
    assert glass.data["data"]["attachments"][0]["color"] == "#D32F2F"
    alarm = next(p for p in posts if text(p).startswith("**SIEM alarm"))
    assert text(alarm).splitlines()[1:] == [
        "",
        "- 12:00:00: **exterior_door_opened** +40 Back Door opened",
        "- 12:00:00: **manual_unlock** +60 Front Door Lock Manual unlock operation",
    ]

    # The digest has no incident: its own text follows the headline.
    await hass.services.async_call("siem", "run_digest", {}, blocking=True)
    await settle(hass)
    assert posts[-1].data["message"] == ""
    assert posts[-1].data["data"]["attachments"][0] == {
        "color": "#1976D2",
        "fallback": "SIEM digest. Quiet since 2026-10-19 12:00.",
        "fields": [],
        "text": "**SIEM digest** Quiet since 2026-10-19 12:00.",
    }
    # A snapshot travels as data.file.path.
    hass.bus.async_fire("siem_notification", {"category": "verify", "title": "SIEM verify: Hall", "message": "Score 20, house vacant.", "incident": None, "snapshot": "/media/siem/abc_verify.jpg", "again": False, "summary": None})
    await settle(hass)
    assert posts[-1].data["data"]["file"] == {"path": "/media/siem/abc_verify.jpg"}


async def test_mobile_app_package_and_label_buttons(hass, freezer):
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
    hass.bus.async_fire("mobile_app_notification_action", {"action": push["data"]["actions"][2]["action"]}, context=Context())
    await settle(hass)
    assert entry.runtime_data.engine.current.labels == ["real"]
    # The digest and alarm-mode messages stay off the phone.
    await hass.services.async_call("siem", "run_digest", {}, blocking=True)
    await settle(hass)
    assert len(pushes) == 1


async def test_deterrence_package_lights_the_room_then_the_house(hass, freezer):
    # Lights assigned to the Kitchen area, which SIEM reports as the incident's area_id.
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
