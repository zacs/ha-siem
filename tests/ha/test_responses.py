"""Responses inside Home Assistant: deterrence, alarm, arming, digest, re-alerts and the mobile label buttons."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from homeassistant.core import Context
import pytest
from pytest_homeassistant_custom_component.common import async_mock_service

from .conftest import notifications, scored, setup_siem, tick


@pytest.fixture(autouse=True)
def noon(freezer):
    freezer.move_to("2026-10-19 12:00:00-07:00")


async def break_in(hass) -> None:
    """Back door, then someone in the kitchen, then the fridge: 40 + 75 + 60, alarm tier."""
    for entity_id in ("binary_sensor.back_door", "binary_sensor.kitchen_presence", "binary_sensor.fridge_door"):
        hass.states.async_set(entity_id, "on", {"friendly_name": hass.states.get(entity_id).name})
        await hass.async_block_till_done()


async def test_dry_run_describes_every_action(hass, freezer, siem_events):
    light_calls = async_mock_service(hass, "light", "turn_on")
    entry = await setup_siem(hass, responses={"auto_alarm": True})
    await break_in(hass)
    assert hass.states.get("sensor.siem_tier").state == "alarm"
    assert light_calls == []
    alarm = notifications(siem_events, "alarm")[0]
    assert alarm["actions"] == ["light.turn_on light.kitchen brightness_pct=100", "script.turn_on script.house_deter", "switch.turn_on switch.siren", "siem.alarm_trigger binary_sensor.siem_alarm_trigger seconds=60"]
    assert "Would have run:\n- light.turn_on light.kitchen brightness_pct=100" in alarm["message"]
    assert hass.states.get("binary_sensor.siem_alarm_trigger").state == "off"
    assert [r for r, _, _ in scored(entry)] == ["exterior_door_opened", "interior_occupied", "interior_door_opened"]


async def step(freezer, seconds: float, steps: int = 50) -> None:
    """Advance the frozen clock in small steps, yielding to the loop, without waiting on stuck tasks."""
    for _ in range(steps):
        freezer.tick(seconds / steps)
        for _ in range(10):
            await asyncio.sleep(0)


async def test_live_deterrence_runs_even_when_a_speaker_hangs(hass, freezer, siem_events, notify_calls):
    light_calls = async_mock_service(hass, "light", "turn_on")
    script_calls = async_mock_service(hass, "script", "turn_on")
    create_calls = async_mock_service(hass, "scene", "create")
    restore_calls = async_mock_service(hass, "scene", "turn_on")

    async def hang(call):
        await asyncio.Event().wait()

    hass.services.async_register("media_player", "volume_set", hang)
    play_calls = async_mock_service(hass, "media_player", "play_media")
    rooms = {"kitchen": {"name": "Kitchen", "perimeter": ["binary_sensor.back_door"], "occupancy": ["binary_sensor.kitchen_presence"], "interior_doors": ["binary_sensor.fridge_door"], "deter_lights": ["light.kitchen"], "deter_players": ["media_player.kitchen"], "power_threshold": 30}}
    with patch("custom_components.siem.const.ACTION_TIMEOUT_S", 1):
        await setup_siem(hass, rooms=rooms, house={"deter_sound": "media-source://media_source/local/dog.mp3"}, responses={"dry_run": False, "auto_alarm": True})
        # SIEM's own switch platform loads the real switch service, so the mock goes in afterwards.
        siren_calls = async_mock_service(hass, "switch", "turn_on")
        for entity_id in ("binary_sensor.back_door", "binary_sensor.kitchen_presence", "binary_sensor.fridge_door"):
            hass.states.async_set(entity_id, "on")
            await step(freezer, 0.1, 50)
        # Deter, then alarm: everything but the speaker has run while the volume step is still stuck.
        assert [n["category"] for n in notifications(siem_events) if n["category"] != "verify"] == ["deter", "alarm"]
        assert [c.data["entity_id"] for c in siren_calls] == ["switch.siren"]
        assert [c.data["entity_id"] for c in light_calls] == ["light.kitchen"] * 2
        assert [c.data["entity_id"] for c in script_calls] == ["script.house_deter"] * 2
        assert hass.states.get("binary_sensor.siem_alarm_trigger").state == "on"
        assert any(call.data["title"] == "SIEM alarm: Kitchen" for call in notify_calls)
        assert play_calls == []
        await step(freezer, 3)
    await hass.async_block_till_done()
    # The stuck volume steps timed out and the deter sound played after them, once per round.
    assert [c.data["media_content_id"] for c in play_calls] == ["media-source://media_source/local/dog.mp3"] * 2
    alarm = notifications(siem_events, "alarm")[0]
    assert alarm["dry_run"] is False and "Running:" in alarm["message"]
    await tick(hass, freezer, 61)
    assert hass.states.get("binary_sensor.siem_alarm_trigger").state == "off"
    # One snapshot before the first round, one restore after the last, so the speaker goes back to how it was.
    assert [c.data["scene_id"] for c in create_calls] == ["siem_restore_kitchen"]
    assert [c.data["entity_id"] for c in restore_calls] == ["scene.siem_restore_kitchen"]


async def test_own_actions_never_score(hass, freezer):
    entry = await setup_siem(hass, responses={"dry_run": False})
    hass.states.async_set("binary_sensor.back_door", "on")
    await hass.async_block_till_done()
    before = scored(entry)
    # A deter light switched on by SIEM's own context is an automation.
    hass.states.async_set("light.kitchen", "on", context=entry.runtime_data.responder.context())
    await hass.async_block_till_done()
    assert scored(entry) == before


async def test_verify_alerts_again_when_the_score_doubles(hass, freezer, siem_events):
    # High deter and alarm thresholds keep the incident at verify while its score doubles.
    await setup_siem(hass, options={"engine": {"verify": 20, "deter": 90, "alarm": 95}})
    hass.states.async_set("binary_sensor.yard_gate", "on")
    await hass.async_block_till_done()
    assert [n["message"].splitlines()[0] for n in notifications(siem_events, "verify")] == ["[DRY RUN] Score 30, house vacant."]
    hass.states.async_set("sensor.water_flow", "5")
    await hass.async_block_till_done()
    await tick(hass, freezer, 1)
    again = notifications(siem_events, "verify")
    assert len(again) == 2 and again[1]["again"] is True
    assert again[1]["message"].splitlines()[0] == "[DRY RUN] Score 60, house vacant, score doubled since the last alert."


async def test_arming_follows_the_house_mode(hass, freezer, siem_events):
    arm_calls = async_mock_service(hass, "alarm_control_panel", "alarm_arm_away")
    disarm_calls = async_mock_service(hass, "alarm_control_panel", "alarm_disarm")
    await setup_siem(hass, responses={"dry_run": False, "auto_arm": True})
    hass.states.async_set("person.alice", "home", {"device_trackers": ["device_tracker.alice_phone"], "user_id": "trusted-user"})
    await hass.async_block_till_done()
    assert hass.states.get("sensor.siem_house_mode").state == "family"
    assert [c.data["entity_id"] for c in disarm_calls] == ["alarm_control_panel.house"]
    hass.states.async_set("person.alice", "not_home", {"device_trackers": ["device_tracker.alice_phone"], "user_id": "trusted-user"})
    await hass.async_block_till_done()
    await tick(hass, freezer, 31 * 60)
    assert hass.states.get("sensor.siem_house_mode").state == "vacant"
    assert [c.data["entity_id"] for c in arm_calls] == ["alarm_control_panel.house"]
    messages = [n["message"] for n in notifications(siem_events, "arm")]
    assert messages == ["Set House Alarm to disarmed (house family).", "Set House Alarm to armed away (house vacant)."]


async def test_arming_in_dry_run_only_says_so(hass, freezer, siem_events):
    arm_calls = async_mock_service(hass, "alarm_control_panel", "alarm_disarm")
    await setup_siem(hass, responses={"auto_arm": True})
    hass.states.async_set("person.alice", "home", {"device_trackers": [], "user_id": "trusted-user"})
    await hass.async_block_till_done()
    assert arm_calls == []
    arm = notifications(siem_events, "arm")[0]
    assert arm["message"] == "[DRY RUN] Would set House Alarm to disarmed (house family)." and arm["armed"] is False


async def test_digest_falls_back_to_counts_without_an_ai_task(hass, freezer, siem_events, notify_calls):
    await setup_siem(hass)
    await tick(hass, freezer, 60)
    hass.states.async_set("binary_sensor.back_door", "on")
    await hass.async_block_till_done()
    await hass.services.async_call("siem", "run_digest", {}, blocking=True)
    digest = notifications(siem_events, "digest")[0]
    assert digest["title"] == "SIEM digest"
    assert digest["message"] == "1 incidents (1 verify), 0 weight changes"
    assert digest["summary"]["incident_count"] == 1


async def test_mobile_label_buttons(hass, freezer):
    entry = await setup_siem(hass)
    hass.states.async_set("binary_sensor.back_door", "on")
    await hass.async_block_till_done()
    incident_id = entry.runtime_data.incident_id
    hass.bus.async_fire("mobile_app_notification_action", {"action": f"SIEM_LABEL_REAL|{incident_id}"}, context=Context())
    await hass.async_block_till_done()
    assert entry.runtime_data.engine.current.labels == ["real"]
    assert entry.runtime_data.store.weights == {"exterior_door_opened": 1.1}
