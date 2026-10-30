"""Config flow, options flow and migrations from older entries."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.siem.config_flow import build_entity_meta
from custom_components.siem.const import DOMAIN

from .conftest import HOUSE, RESPONSES, ROOMS, set_house_states, setup_siem


def suggested(result) -> dict:
    return {str(key): (key.description or {}).get("suggested_value") for key in result["data_schema"].schema}


async def test_full_flow_prefills_rooms(hass):
    set_house_states(hass)
    kitchen = ar.async_get(hass).async_get_or_create("Kitchen")
    registry = er.async_get(hass)
    ids = {}
    for unique_id, domain, device_class, name in (
        ("motion", "binary_sensor", "motion", "Kitchen Motion"),
        ("back", "binary_sensor", "door", "Back Door"),
        ("fridge", "binary_sensor", "door", "Fridge Door"),
        ("lamp", "light", None, "Kitchen Light"),
        ("plug", "sensor", "power", "Coffee Maker Power"),
    ):
        entry = registry.async_get_or_create(domain, "test", unique_id, original_name=name, original_device_class=device_class)
        registry.async_update_entity(entry.entity_id, area_id=kitchen.id)
        ids[unique_id] = entry.entity_id

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["step_id"] == "rooms"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"rooms": [kitchen.id]})
    assert result["step_id"] == "room"
    room = suggested(result)
    assert room["occupancy"] == [ids["motion"]]
    assert room["perimeter"] == [ids["back"]]
    assert room["interior_doors"] == [ids["fridge"]]
    assert room["lights"] == [ids["lamp"]]
    assert room["power"] == [ids["plug"]]
    assert room["outdoors"] is False
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {k: v for k, v in room.items() if v})
    assert result["step_id"] == "house"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"residents": ["person.alice"], "csi_sensors": ["binary_sensor.front_door_csi"], "night_start": "23:00:00", "night_end": "06:00:00"})
    assert result["step_id"] == "csi_map"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"binary_sensor.front_door_csi": "binary_sensor.front_door"})
    assert result["step_id"] == "responses"
    assert sorted(suggested(result)) == ["ai_task_entity", "digest_post_when_empty", "digest_times"]
    bad = await hass.config_entries.flow.async_configure(result["flow_id"], {"digest_times": ["8am"]})
    assert bad["errors"] == {"digest_times": "invalid_time"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"digest_times": ["08:00"]})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.minor_version == 8
    assert entry.data["responses"] == {"digest_times": ["08:00"], "digest_post_when_empty": True}
    assert entry.data["house"]["csi_map"] == {"binary_sensor.front_door_csi": "binary_sensor.front_door"}
    assert entry.data["house"]["night_start"] == "23:00:00"
    meta = entry.data["entities"]
    assert entry.data["rooms"][kitchen.id]["outdoors"] is False
    assert meta[ids["motion"]] == {"role": "occupancy", "room": kitchen.id, "strength": "medium", "person_detector": False}
    assert meta[ids["fridge"]]["role"] == "interior_door"
    await hass.async_block_till_done()
    assert hass.states.get("sensor.siem_house_mode").state == "vacant"

    again = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert again["type"] is FlowResultType.ABORT and again["reason"] == "single_instance_allowed"


async def test_options_edit_points_engine_and_strength(hass, freezer):
    entry = await setup_siem(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "rules"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"rule": "appliance_on"})
    assert suggested(result) == {"vacant": 35, "guest": 0, "service": 0, "family": 0, "night": 35}
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"vacant": 10, "guest": 0, "service": 0, "family": 0, "night": 5})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options["rules"] == {"appliance_on": {"points": {"vacant": 10, "guest": 0, "service": 0, "family": 0, "night": 5}}}
    assert entry.runtime_data.rules["appliance_on"].points_for("vacant") == 10

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "engine"})
    values = suggested(result)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {**values, "verify": 90})
    assert result["errors"] == {"base": "invalid_thresholds"}


async def test_migration_from_1_1(hass, hass_storage, freezer):
    set_house_states(hass)
    weights = {"tv_power": 0.9, "light_physical": 0.81, "light_homekit": 0.9}
    hass_storage["siem.storage"] = {"version": 1, "minor_version": 1, "key": "siem.storage", "data": {"weights": weights}}
    old = {
        "rooms": {"kitchen": {"name": "Kitchen", "power": ["sensor.coffee_power"], "power_threshold": 30}, "porch": {"name": "Front Porch", "power_threshold": 30}},
        "house": {"water_flow": ["sensor.water_main"], "water_flow_additional": ["sensor.water_pulse", "sensor.water_main"]},
        "responses": {
            "notify_service": "notify.mattermost",
            "target": "home_security",
            "notify_service_2": "notify.mobile_app_phone",
            "mobile_notify_service": "notify.mobile_app_phone",
            "dry_run": True,
            "alarm_panel": "alarm_control_panel.house",
        },
        "entities": {"sensor.coffee_power": {"role": "power", "room": "kitchen", "threshold": 30}},
    }
    options = {"rules": {"tv_power": {"points": {"vacant": 20, "sitter": 0, "service": 0, "family": 0}}, "gate_opened": {"points": {"vacant": 25, "sitter": 5, "service": 5, "family": 0}}}}
    entry = MockConfigEntry(domain=DOMAIN, title="SIEM", data=old, options=options, version=1, minor_version=1)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.minor_version == 8
    assert entry.data["responses"] == {}
    # The panel SIEM used to arm is kept, to be read for armed night; the second water flow field joins the first.
    assert entry.data["house"] == {"alarm_panel": "alarm_control_panel.house", "water_flow": ["sensor.water_main", "sensor.water_pulse"]}
    # Rooms named like the outdoors start out as outdoor rooms.
    assert entry.data["rooms"]["kitchen"]["outdoors"] is False and entry.data["rooms"]["porch"]["outdoors"] is True
    assert entry.runtime_data.outdoor_rooms == {"porch"}
    assert entry.options["rules"] == {
        "appliance_on": {"points": {"vacant": 20, "guest": 0, "service": 0, "family": 0, "night": 35}},
        "gate_opened": {"points": {"vacant": 25, "guest": 5, "service": 5, "family": 0, "night": 30}},
    }
    coordinator = entry.runtime_data
    assert coordinator.rules["appliance_on"].points_for("vacant") == 20
    assert coordinator.store.weights == {"appliance_on": 0.9, "light_physical": 0.81}


async def test_migration_drops_notify_panel_deterrence_and_trust_settings(hass, freezer):
    set_house_states(hass)
    data = {
        "rooms": {"kitchen": {"name": "Kitchen", "deter_lights": ["light.kitchen"], "deter_players": ["media_player.kitchen"], "deter_script": "script.kitchen", "power_threshold": 30}},
        "house": {"trusted_user_ids": ["abc"], "deter_volume": 0.7, "restore_seconds": 30, "house_deter": ["script.deter"], "house_alarm": ["switch.siren"], "night_start": "22:00:00"},
        "responses": {"notify_services": ["notify.mattermost"], "alarm_panel": "alarm_control_panel.house", "auto_arm": True, "auto_alarm": True, "dry_run": False, "digest_times": ["08:00"]},
        "entities": {},
    }
    points = {"vacant": 70, "guest": 50, "service": 50, "family": 30}
    options = {"rules": {rule: {"points": points} for rule in ("untrusted_user", "light_homekit", "person_interior_camera", "person_exterior_camera")}}
    entry = MockConfigEntry(domain=DOMAIN, title="SIEM", data=data, options=options, version=1, minor_version=3)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    orphans = [registry.async_get_or_create("switch", DOMAIN, f"{entry.entry_id}_{key}", config_entry=entry) for key in ("dry_run", "auto_arm", "auto_alarm")]
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.minor_version == 8
    assert entry.data["rooms"] == {"kitchen": {"name": "Kitchen", "power_threshold": 30, "outdoors": False}}
    assert entry.data["house"] == {"night_start": "22:00:00", "alarm_panel": "alarm_control_panel.house"}
    assert entry.data["responses"] == {"digest_times": ["08:00"]}
    assert "rules" not in entry.options
    assert all(registry.async_get(orphan.entity_id) is None for orphan in orphans)
    assert not hass.states.async_entity_ids("switch")


async def test_the_bedtime_sensor_from_0_0_4_is_removed(hass):
    """0.0.4 showed night with someone home as binary_sensor.siem_bedtime; binary_sensor.siem_night covers it now."""
    set_house_states(hass)
    data = {"rooms": ROOMS, "house": HOUSE, "responses": RESPONSES}
    data["entities"] = build_entity_meta(hass, data)
    entry = MockConfigEntry(domain=DOMAIN, title="SIEM", data=data, version=1, minor_version=7)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    bedtime = registry.async_get_or_create("binary_sensor", DOMAIN, f"{entry.entry_id}_bedtime", config_entry=entry, suggested_object_id="siem_bedtime")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.minor_version == 8
    assert registry.async_get(bedtime.entity_id) is None
    assert hass.states.get("binary_sensor.siem_night") is not None
