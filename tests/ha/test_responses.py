"""What SIEM does in response: alert events and its own entities, and nothing else."""

from __future__ import annotations

import logging

from homeassistant.core import Context, ServiceCall, SupportsResponse
import pytest
import voluptuous as vol

from .conftest import RESIDENT, flip, notifications, scored, setup_siem, tick

# Domains SIEM must never call: it publishes state and events, and automations act on them.
ACTION_DOMAINS = {"light", "switch", "script", "scene", "media_player", "tts", "notify", "alarm_control_panel", "siren"}


@pytest.fixture(autouse=True)
def noon(freezer):
    freezer.move_to("2026-10-19 12:00:00-07:00")


async def break_in(hass) -> None:
    """Back door, then someone in the kitchen, then the fridge: verify, deter, then alarm."""
    for entity_id in ("binary_sensor.back_door", "binary_sensor.kitchen_presence", "binary_sensor.fridge_door"):
        flip(hass, entity_id)
        await hass.async_block_till_done()


async def test_a_break_in_raises_alerts_and_the_alarm_trigger_and_nothing_else(hass, freezer, siem_events, service_calls):
    entry = await setup_siem(hass)
    assert hass.states.get("binary_sensor.siem_alarm_trigger").state == "off"
    await break_in(hass)
    assert [r for r, _, _ in scored(entry)] == ["exterior_door_opened", "interior_occupied", "interior_door_opened"]
    assert [n["category"] for n in notifications(siem_events)] == ["verify", "deter", "alarm"]
    alarm = notifications(siem_events, "alarm")[0]
    assert alarm["title"] == "SIEM alarm: Kitchen"
    assert alarm["incident"]["area_id"] == "kitchen" and alarm["incident"]["room"] == "Kitchen"
    assert hass.states.get("sensor.siem_tier").state == "alarm"
    # The alarm trigger, for an alarm panel to watch, waits a minute at the alarm tier: time for a late phone to report home.
    assert hass.states.get("binary_sensor.siem_alarm_trigger").state == "off"
    await tick(hass, freezer, 59)
    assert hass.states.get("binary_sensor.siem_alarm_trigger").state == "off"
    await tick(hass, freezer, 1)
    assert hass.states.get("binary_sensor.siem_alarm_trigger").state == "on"
    assert not [call for call in service_calls if call[0] in ACTION_DOMAINS]
    while hass.states.get("sensor.siem_tier").state == "alarm":
        await tick(hass, freezer, 60)
    assert hass.states.get("binary_sensor.siem_alarm_trigger").state == "off"


async def test_changes_made_by_automations_on_siem_events_never_score(hass, freezer):
    entry = await setup_siem(hass)
    flip(hass, "binary_sensor.back_door")
    await hass.async_block_till_done()
    before = scored(entry)
    # An automation triggered by a SIEM event runs under a context whose parent is SIEM's.
    flip(hass, "light.kitchen", context=Context(parent_id=entry.runtime_data.alerts.context().id))
    await hass.async_block_till_done()
    assert scored(entry) == before


async def test_verify_alerts_again_when_the_score_doubles(hass, freezer, siem_events):
    # High deter and alarm thresholds keep the incident at verify while its score doubles.
    await setup_siem(hass, options={"engine": {"verify": 20, "deter": 90, "alarm": 95}})
    flip(hass, "binary_sensor.yard_gate")
    await hass.async_block_till_done()
    assert [n["message"].splitlines()[0] for n in notifications(siem_events, "verify")] == ["Score 30, house vacant."]
    flip(hass, "sensor.water_flow", "5")
    await hass.async_block_till_done()
    await tick(hass, freezer, 1)
    again = notifications(siem_events, "verify")
    assert len(again) == 2 and again[1]["again"] is True
    assert again[1]["message"].splitlines()[0] == "Score 60, house vacant, score doubled since the last alert."


async def test_the_alarm_panel_is_never_touched(hass, freezer, siem_events, service_calls):
    await setup_siem(hass)
    assert hass.states.get("sensor.siem_recommended_alarm_mode").state == "armed_away"
    hass.states.async_set("person.alice", "home", {"device_trackers": ["device_tracker.alice_phone"], "user_id": RESIDENT})
    await hass.async_block_till_done()
    assert hass.states.get("sensor.siem_house_mode").state == "family"
    assert hass.states.get("sensor.siem_recommended_alarm_mode").state == "disarmed"
    hass.states.async_set("person.alice", "not_home", {"device_trackers": ["device_tracker.alice_phone"], "user_id": RESIDENT})
    await hass.async_block_till_done()
    await tick(hass, freezer, 31 * 60)
    assert hass.states.get("sensor.siem_recommended_alarm_mode").state == "armed_away"
    # The recommendation is a sensor for your own automations; SIEM never calls the panel or a notify service.
    assert not [call for call in service_calls if call[0] in ACTION_DOMAINS]
    assert {n["category"] for n in notifications(siem_events)} <= {"verify", "deter", "alarm", "break_glass", "digest"}


async def test_digest_falls_back_to_counts_without_an_ai_task(hass, freezer, siem_events):
    await setup_siem(hass)
    await tick(hass, freezer, 60)
    flip(hass, "binary_sensor.back_door")
    await hass.async_block_till_done()
    await hass.services.async_call("siem", "run_digest", {}, blocking=True)
    digest = notifications(siem_events, "digest")[0]
    assert digest["title"] == "SIEM digest"
    assert digest["message"] == "1 incidents (1 verify), 0 weight changes\n\nHouse mode: vacant."
    assert digest["summary"]["incident_count"] == 1
    assert set(digest["summary"]) == {"since", "until", "incident_count", "labels", "weight_changes", "counts", "house_mode", "forced", "forced_since"}
    assert digest["incident"] is None and digest["snapshot"] is None


async def test_digest_on_demand_with_another_ai_task_and_previews(hass, freezer, siem_events):
    """Comparing models: previews of the same stretch from two AI tasks, then the real digest from the configured one."""

    async def generate(call: ServiceCall):
        return {"data": f"Five lines from {call.data['entity_id']}."}

    hass.services.async_register("ai_task", "generate_data", generate, supports_response=SupportsResponse.ONLY)
    entry = await setup_siem(hass, responses={"ai_task_entity": "ai_task.everyday"})
    await tick(hass, freezer, 60)
    flip(hass, "binary_sensor.back_door")
    await hass.async_block_till_done()
    period = entry.runtime_data.store.last_digest
    for ai_task in ("ai_task.small_model", "ai_task.big_model"):
        preview = await hass.services.async_call("siem", "run_digest", {"ai_task_entity": ai_task, "preview": True}, blocking=True, return_response=True)
        assert preview["message"] == f"Five lines from {ai_task}.\n\nHouse mode: vacant."
        assert preview["ai_task_entity"] == ai_task
        assert preview["summary"]["incident_count"] == 1
    # Previews send nothing and leave the digest period alone.
    assert notifications(siem_events, "digest") == []
    assert entry.runtime_data.store.last_digest == period
    result = await hass.services.async_call("siem", "run_digest", {}, blocking=True, return_response=True)
    assert result["ai_task_entity"] == "ai_task.everyday"
    assert [n["message"] for n in notifications(siem_events, "digest")] == ["Five lines from ai_task.everyday.\n\nHouse mode: vacant."]
    assert entry.runtime_data.store.last_digest != period
    with pytest.raises(vol.Invalid):
        await hass.services.async_call("siem", "run_digest", {"ai_task_entity": "light.kitchen"}, blocking=True)


async def test_the_digest_reminds_you_of_a_mode_set_by_hand(hass, freezer, siem_events):
    entry = await setup_siem(hass)
    await hass.services.async_call("siem", "set_house_mode", {"mode": "guest"}, blocking=True)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await tick(hass, freezer, 4 * 86400)
    digest = await hass.services.async_call("siem", "run_digest", {"preview": True}, blocking=True, return_response=True)
    assert digest["message"].endswith("House mode: guest, set by hand since Oct 19, 12:00. It stays that way until you set it back to auto.")
    assert digest["summary"]["house_mode"] == "guest" and digest["summary"]["forced"] is True
    assert digest["summary"]["forced_since"].startswith("2026-10-19T12:00")
    await hass.services.async_call("siem", "set_house_mode", {"mode": "auto"}, blocking=True)
    digest = await hass.services.async_call("siem", "run_digest", {"preview": True}, blocking=True, return_response=True)
    assert digest["message"].endswith("\n\nHouse mode: vacant.")
    assert digest["summary"]["forced"] is False and digest["summary"]["forced_since"] is None


async def test_debug_log_says_why_nothing_scored(hass, freezer, caplog):
    caplog.set_level(logging.DEBUG, logger="custom_components.siem")
    await setup_siem(hass)
    flip(hass, "binary_sensor.back_door")
    await hass.async_block_till_done()
    flip(hass, "binary_sensor.back_door", "off")
    flip(hass, "binary_sensor.back_door")
    hass.states.async_set("light.kitchen", "on", {}, context=Context(user_id=RESIDENT))
    await hass.services.async_call("siem", "set_house_mode", {"mode": "guest"}, blocking=True)
    flip(hass, "binary_sensor.fridge_door")
    await hass.async_block_till_done()
    lines = [r.getMessage() for r in caplog.records if r.name.startswith("custom_components.siem")]
    assert "binary_sensor.back_door scored exterior_door_opened +40.0 (opened)" in lines
    assert "binary_sensor.back_door not scored as exterior_door_opened: already counted in the last 5 minutes" in lines
    assert "light.kitchen not scored: Home Assistant made the change" in lines
    assert "House mode vacant -> guest" in lines
    assert "binary_sensor.fridge_door not scored as interior_door_opened: guest mode gives it 0 points" in lines


async def test_mobile_label_buttons(hass, freezer):
    entry = await setup_siem(hass)
    flip(hass, "binary_sensor.back_door")
    await hass.async_block_till_done()
    incident_id = entry.runtime_data.incident_id
    hass.bus.async_fire("mobile_app_notification_action", {"action": f"SIEM_LABEL_REAL|{incident_id}"}, context=Context())
    await hass.async_block_till_done()
    assert entry.runtime_data.engine.current.labels == ["real"]
    assert entry.runtime_data.store.weights == {"exterior_door_opened": 1.1}
