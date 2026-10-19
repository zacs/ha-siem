"""The sample packages, loaded into Home Assistant and driven by real SIEM events."""

from __future__ import annotations

from pathlib import Path

from homeassistant.config import merge_packages_config
from homeassistant.core import Context
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
    """Let SIEM's response task fire its event, then the package's automation run (a loop turn later on older cores)."""
    for _ in range(3):
        await hass.async_block_till_done()


async def load_package(hass, name: str) -> None:
    config = await merge_packages_config(hass, {}, {name: load_yaml(PACKAGES / f"{name}.yaml")})
    assert await async_setup_component(hass, "automation", config)
    await hass.async_block_till_done()


async def test_mattermost_package(hass, freezer):
    posts = async_mock_service(hass, "notify", "mattermost")
    await setup_siem(hass, responses={"notify_services": []})
    await load_package(hass, "siem_mattermost")
    flip(hass, "binary_sensor.back_door")
    await settle(hass)
    verify = posts[0].data
    assert verify["target"] == ["home_security"]
    assert verify["message"] == "**SIEM verify: Kitchen** [DRY RUN] Score 40, house vacant."
    attachment = verify["data"]["attachments"][0]
    assert attachment["color"] == "#F5B700"
    assert [f["title"] for f in attachment["fields"]] == ["Room", "House mode", "Score", "Top contributors"]
    assert [f["value"] for f in attachment["fields"]] == ["Kitchen", "vacant", "40", "exterior_door_opened"]
    assert attachment["text"] == "- 12:00:00: **exterior_door_opened** +40 Back Door opened"
    assert "file" not in verify["data"]

    hass.bus.async_fire("lock_code_manager_lock_state_changed", {"entity_id": "lock.front_door", "action_text": "Manual unlock operation", "code_slot": 0})
    await settle(hass)
    glass = next(p.data for p in posts if p.data["message"].startswith("**SIEM break glass**"))
    assert glass["message"] == "**SIEM break glass** [DRY RUN] Front Door Lock: a lock was unlocked by hand (Manual unlock operation). House vacant."
    assert glass["data"]["attachments"][0]["color"] == "#D32F2F"
    alarm = next(p.data for p in posts if p.data["message"].startswith("**SIEM deter") or p.data["message"].startswith("**SIEM alarm"))
    assert "Would have run:\n- `light.turn_on light.kitchen brightness_pct=100`" in alarm["data"]["attachments"][0]["text"]

    # The digest has no incident: its text is the attachment.
    await hass.services.async_call("siem", "run_digest", {}, blocking=True)
    await settle(hass)
    assert posts[-1].data["message"] == "**SIEM digest**"
    assert posts[-1].data["data"]["attachments"][0] == {"color": "#1976D2", "fields": [], "text": "Quiet since 2026-10-19 12:00."}
    # A snapshot travels as data.file.path.
    hass.bus.async_fire("siem_notification", {"category": "verify", "title": "SIEM verify: Hall", "message": "Score 20, house vacant.", "dry_run": False, "incident": None, "snapshot": "/media/siem/abc_verify.jpg"})
    await settle(hass)
    assert posts[-1].data["data"]["file"] == {"path": "/media/siem/abc_verify.jpg"}


async def test_mobile_app_package_and_label_buttons(hass, freezer):
    pushes = async_mock_service(hass, "notify", "mobile_app_your_phone")
    entry = await setup_siem(hass, responses={"notify_services": []})
    await load_package(hass, "siem_mobile_app")
    flip(hass, "binary_sensor.back_door")
    await settle(hass)
    push = pushes[0].data
    incident_id = entry.runtime_data.incident_id
    assert push["title"] == "SIEM verify: Kitchen"
    assert push["message"].startswith("[DRY RUN] Score 40, house vacant.")
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
