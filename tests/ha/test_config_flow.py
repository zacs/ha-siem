"""Config flow, options flow and the 1.1 to 1.2 migration."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.siem.const import DOMAIN

from .conftest import TRUSTED, set_house_states, setup_siem


def suggested(result) -> dict:
    return {str(key): (key.description or {}).get("suggested_value") for key in result["data_schema"].schema}


def options_of(result, name: str) -> list:
    selector = next(value for key, value in result["data_schema"].schema.items() if str(key) == name)
    return selector.config["options"]


async def test_full_flow_prefills_rooms_and_trust(hass):
    set_house_states(hass)
    async_mock_service(hass, "notify", "mobile_app_phone")
    presence = await hass.auth.async_create_system_user("Presence Simulation")
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
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {k: v for k, v in room.items() if v})
    assert result["step_id"] == "house"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"residents": ["person.alice"], "csi_sensors": ["binary_sensor.front_door_csi"]})
    assert result["step_id"] == "csi_map"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"binary_sensor.front_door_csi": "binary_sensor.front_door"})
    assert result["step_id"] == "house_deter"
    assert sorted(suggested(result)["trusted_user_ids"]) == sorted([TRUSTED, presence.id])
    labels = {o["value"]: o["label"] for o in options_of(result, "trusted_user_ids")}
    assert labels[presence.id] == "Presence Simulation (system)" and labels[TRUSTED] == "Alice"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"trusted_user_ids": [TRUSTED, presence.id]})
    assert result["step_id"] == "responses"
    assert "notify.mobile_app_phone" in options_of(result, "notify_services")
    bad = await hass.config_entries.flow.async_configure(result["flow_id"], {"notify_services": ["mattermost"], "digest_times": ["8am"]})
    assert bad["errors"] == {"notify_services": "invalid_notify", "digest_times": "invalid_time"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"notify_services": ["notify.mobile_app_phone"], "digest_times": ["08:00"]})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.minor_version == 2
    assert entry.data["responses"]["notify_services"] == ["notify.mobile_app_phone"]
    assert entry.data["responses"]["dry_run"] is True
    assert entry.data["house"]["csi_map"] == {"binary_sensor.front_door_csi": "binary_sensor.front_door"}
    meta = entry.data["entities"]
    assert meta[ids["motion"]] == {"role": "occupancy", "room": kitchen.id, "strength": "medium", "person_detector": False, "exterior": False}
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
    assert suggested(result) == {"vacant": 35, "guest": 0, "service": 0, "family": 0}
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"vacant": 10, "guest": 0, "service": 0, "family": 0})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options["rules"] == {"appliance_on": {"points": {"vacant": 10, "guest": 0, "service": 0, "family": 0}}}
    assert entry.runtime_data.rules["appliance_on"].points_for("vacant") == 10

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "engine"})
    values = suggested(result)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {**values, "verify": 90})
    assert result["errors"] == {"base": "invalid_thresholds"}


async def test_migration_from_1_1(hass, hass_storage, freezer):
    set_house_states(hass)
    hass_storage["siem.storage"] = {"version": 1, "minor_version": 1, "key": "siem.storage", "data": {"weights": {"tv_power": 0.9, "light_physical": 0.81}}}
    old = {
        "rooms": {"kitchen": {"name": "Kitchen", "power": ["sensor.coffee_power"], "power_threshold": 30}},
        "house": {},
        "responses": {"notify_service": "notify.mattermost", "target": "home_security", "notify_service_2": "notify.mobile_app_phone", "mobile_notify_service": "notify.mobile_app_phone", "dry_run": True},
        "entities": {"sensor.coffee_power": {"role": "power", "room": "kitchen", "threshold": 30}},
    }
    options = {"rules": {"tv_power": {"points": {"vacant": 20, "sitter": 0, "service": 0, "family": 0}}, "gate_opened": {"points": {"vacant": 25, "sitter": 5, "service": 5, "family": 0}}}}
    entry = MockConfigEntry(domain=DOMAIN, title="SIEM", data=old, options=options, version=1, minor_version=1)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.minor_version == 2
    assert entry.data["responses"] == {"notify_services": ["notify.mattermost", "notify.mobile_app_phone"], "dry_run": True}
    assert entry.options["rules"] == {
        "appliance_on": {"points": {"vacant": 20, "guest": 0, "service": 0, "family": 0}},
        "gate_opened": {"points": {"vacant": 25, "guest": 5, "service": 5, "family": 0}},
    }
    coordinator = entry.runtime_data
    assert coordinator.rules["appliance_on"].points_for("vacant") == 20
    assert coordinator.store.weights == {"appliance_on": 0.9, "light_physical": 0.81}
