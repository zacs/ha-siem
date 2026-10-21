"""Config and options flows for SIEM for Home Assistant."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import copy
from typing import Any

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector as sel
import voluptuous as vol

from . import const as c
from .core import entities as ent
from .core.digest import parse_times
from .core.occupancy import STRENGTHS
from .core.rules import DEFAULT_CHAINS, DEFAULT_RULES, MODES, RuleConfigError, validate_rule_config, validate_settings

STRENGTH_AUTO = "auto"
FlowResult = config_entries.ConfigFlowResult


def _entity(domain: str | list[str] | None = None, device_class: Iterable[str] | None = None, multiple: bool = True) -> sel.EntitySelector:
    config: dict[str, Any] = {"multiple": multiple}
    if domain:
        flt: dict[str, Any] = {"domain": domain}
        if device_class:
            flt["device_class"] = list(device_class)
        config["filter"] = flt
    return sel.EntitySelector(sel.EntitySelectorConfig(**config))


def _number(minimum: float, maximum: float, step: float = 1, unit: str | None = None, mode: str = "box") -> sel.NumberSelector:
    config: dict[str, Any] = {"min": minimum, "max": maximum, "step": step, "mode": mode}
    if unit:
        config["unit_of_measurement"] = unit
    return sel.NumberSelector(sel.NumberSelectorConfig(**config))


def _text(multiple: bool = False) -> sel.TextSelector:
    return sel.TextSelector(sel.TextSelectorConfig(multiple=multiple))


def _select(options: list[Any], multiple: bool = False, custom_value: bool = False) -> sel.SelectSelector:
    return sel.SelectSelector(sel.SelectSelectorConfig(options=options, multiple=multiple, custom_value=custom_value, mode=sel.SelectSelectorMode.DROPDOWN))


def _merge(section: dict[str, Any], schema: vol.Schema, user_input: Mapping[str, Any]) -> None:
    """Replace every schema key in ``section`` with what was submitted; empty means absent."""
    for key in schema.schema:
        section.pop(str(key), None)
    section.update({k: v for k, v in user_input.items() if v not in (None, "", [])})


def prefill_room(hass: HomeAssistant, area_id: str) -> dict[str, Any]:
    """Pre-fill a room form from the entity registry: entity area, falling back to the device's area."""
    ent_reg, dev_reg = er.async_get(hass), dr.async_get(hass)
    infos: list[ent.EntityInfo] = []
    for entry in ent_reg.entities.values():
        area = entry.area_id
        if area is None and entry.device_id and (device := dev_reg.async_get(entry.device_id)):
            area = device.area_id
        if area == area_id and not entry.disabled_by:
            infos.append(ent.EntityInfo(entry.entity_id, entry.domain, entry.device_class or entry.original_device_class, entry.platform, entry.name or entry.original_name, area))
    perimeter, interior = ent.split_openings(i for i in infos if i.domain == "binary_sensor")
    cameras = [i.entity_id for i in infos if i.domain == "camera"]
    area = ar.async_get(hass).async_get_area(area_id)
    return {
        c.CONF_OUTDOORS: ent.is_exterior_area(area.name if area else area_id),
        c.CONF_OCCUPANCY: ent.occupancy_candidates(infos),
        c.CONF_PERIMETER: perimeter,
        c.CONF_INTERIOR_DOORS: interior,
        c.CONF_LIGHTS: [i.entity_id for i in infos if i.domain == "light"],
        c.CONF_POWER: [i.entity_id for i in infos if i.domain == "sensor" and i.device_class == "power"],
        c.CONF_POWER_THRESHOLD: c.DEFAULT_POWER_THRESHOLD,
        **({c.CONF_CAMERA: cameras[0]} if cameras else {}),
    }


ROOM_SCHEMA = vol.Schema(
    {
        vol.Optional(c.CONF_OUTDOORS, default=False): sel.BooleanSelector(),
        vol.Optional(c.CONF_OCCUPANCY): _entity("binary_sensor", ent.OCCUPANCY_CLASSES),
        vol.Optional(c.CONF_OCCUPANCY + c.ADDITIONAL): _entity(),
        vol.Optional(c.CONF_PERIMETER): _entity("binary_sensor", ent.OPENING_CLASSES),
        vol.Optional(c.CONF_PERIMETER + c.ADDITIONAL): _entity(),
        vol.Optional(c.CONF_INTERIOR_DOORS): _entity("binary_sensor", ent.OPENING_CLASSES),
        vol.Optional(c.CONF_INTERIOR_DOORS + c.ADDITIONAL): _entity(),
        vol.Optional(c.CONF_LIGHTS): _entity("light"),
        vol.Optional(c.CONF_LIGHTS + c.ADDITIONAL): _entity(),
        vol.Optional(c.CONF_POWER): _entity("sensor", ["power"]),
        vol.Optional(c.CONF_POWER + c.ADDITIONAL): _entity(),
        vol.Optional(c.CONF_POWER_THRESHOLD, default=c.DEFAULT_POWER_THRESHOLD): _number(0, 5000, 1, "W"),
        vol.Optional(c.CONF_CAMERA): _entity("camera", multiple=False),
    }
)
HOUSE_SCHEMA = vol.Schema(
    {
        vol.Optional(c.CONF_RESIDENTS): _entity("person"),
        vol.Optional(c.CONF_EXTRA_TRACKERS): _entity("device_tracker"),
        vol.Optional(c.CONF_GUEST_TRACKERS): _entity("device_tracker"),
        vol.Optional(c.CONF_CSI): _entity("binary_sensor"),
        vol.Optional(c.CONF_WATER): _entity("sensor", ["volume_flow_rate"]),
        vol.Optional(c.CONF_WATER + c.ADDITIONAL): _entity(),
        vol.Optional(c.CONF_WATER_THRESHOLD, default=c.DEFAULT_WATER_THRESHOLD): _number(0, 1000, 0.1),
        vol.Optional(c.CONF_LOAD): _entity("sensor", ["power"], multiple=False),
        vol.Optional(c.CONF_AUTOMATED_LOADS): _entity("sensor", ["power"]),
        vol.Optional(c.CONF_LOAD_STEP, default=c.DEFAULT_LOAD_STEP): _number(10, 5000, 10, "W"),
        vol.Optional(c.CONF_LOAD_SUSTAIN, default=c.DEFAULT_LOAD_SUSTAIN): _number(1, 120, 1, "min"),
        vol.Optional(c.CONF_LOCKS): _entity("lock"),
        vol.Optional(c.CONF_LCM_EVENTS): _entity("event"),
        vol.Optional(c.CONF_CALENDAR): _entity("calendar", multiple=False),
        vol.Optional(c.CONF_ALARM_PANEL): _entity("alarm_control_panel", multiple=False),
        vol.Optional(c.CONF_NIGHT_START, default=c.DEFAULT_NIGHT_START): sel.TimeSelector(),
        vol.Optional(c.CONF_NIGHT_END, default=c.DEFAULT_NIGHT_END): sel.TimeSelector(),
    }
)
RESPONSES_SCHEMA = vol.Schema(
    {
        vol.Optional(c.CONF_AI_TASK): _entity("ai_task", multiple=False),
        vol.Optional(c.CONF_DIGEST_TIMES, default=c.DEFAULT_DIGEST_TIMES): _text(multiple=True),
        vol.Optional(c.CONF_DIGEST_EMPTY, default=True): sel.BooleanSelector(),
    }
)


ROOM_ROLES = ((c.CONF_OCCUPANCY, ent.ROLE_OCCUPANCY), (c.CONF_PERIMETER, ent.ROLE_PERIMETER), (c.CONF_INTERIOR_DOORS, ent.ROLE_INTERIOR_DOOR), (c.CONF_LIGHTS, ent.ROLE_LIGHT), (c.CONF_POWER, ent.ROLE_POWER))
HOUSE_ROLES = (
    (c.CONF_CSI, ent.ROLE_CSI), (c.CONF_WATER, ent.ROLE_WATER), (c.CONF_AUTOMATED_LOADS, ent.ROLE_AUTOMATED_LOAD), (c.CONF_LOCKS, ent.ROLE_LOCK),
    (c.CONF_LCM_EVENTS, ent.ROLE_LCM_EVENT), (c.CONF_RESIDENTS, ent.ROLE_PERSON), (c.CONF_EXTRA_TRACKERS, ent.ROLE_TRACKER),
    (c.CONF_GUEST_TRACKERS, ent.ROLE_GUEST_TRACKER),
)


def build_entity_meta(hass: HomeAssistant, data: Mapping[str, Any], existing: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    """Derive the per-entity metadata dict from the rooms and house sections.

    Keyed by entity id so later fields need no config entry migration; the
    strength override set in the options flow survives a re-run.
    """
    ent_reg = er.async_get(hass)
    meta: dict[str, dict[str, Any]] = {}

    def registry(entity_id: str) -> tuple[str | None, str | None, str | None]:
        entry = ent_reg.async_get(entity_id)
        if entry is None:
            return None, None, None
        return entry.device_class or entry.original_device_class, entry.platform, entry.name or entry.original_name

    for room_id, room in data.get(c.CONF_ROOMS, {}).items():
        for key, role in ROOM_ROLES:
            for entity_id in list(room.get(key) or []) + list(room.get(key + c.ADDITIONAL) or []):
                device_class, platform, name = registry(entity_id)
                item: dict[str, Any] = {"role": role, "room": room_id}
                if role == ent.ROLE_OCCUPANCY:
                    item.update(strength=ent.derive_strength(device_class, platform), person_detector=ent.is_person_detector(entity_id, name))
                elif role == ent.ROLE_PERIMETER:
                    item["gate"] = ent.is_gate(entity_id, name)
                elif role == ent.ROLE_POWER:
                    item["threshold"] = room.get(c.CONF_POWER_THRESHOLD, c.DEFAULT_POWER_THRESHOLD)
                meta[entity_id] = item
        if camera := room.get(c.CONF_CAMERA):
            meta[camera] = {"role": ent.ROLE_CAMERA, "room": room_id}
    house = data.get(c.CONF_HOUSE, {})
    for key, role in HOUSE_ROLES:
        for entity_id in list(house.get(key) or []) + list(house.get(key + c.ADDITIONAL) or []):
            item = {"role": role, "room": None}
            if role == ent.ROLE_WATER:
                item["threshold"] = house.get(c.CONF_WATER_THRESHOLD, c.DEFAULT_WATER_THRESHOLD)
            meta[entity_id] = item
    for key, role in ((c.CONF_LOAD, ent.ROLE_LOAD), (c.CONF_CALENDAR, ent.ROLE_CALENDAR), (c.CONF_ALARM_PANEL, ent.ROLE_PANEL)):
        if house.get(key):
            meta[house[key]] = {"role": role, "room": None}
    for entity_id, old in (existing or {}).items():
        if entity_id in meta and old.get("strength_override"):
            meta[entity_id]["strength_override"] = old["strength_override"]
    return meta


class SiemStepsMixin:
    """Steps shared by the config flow and the options flow.

    Subclasses define ``_async_after_rooms``, ``_async_after_house`` and ``_async_finish``.
    """

    hass: HomeAssistant
    _data: dict[str, Any]
    _queue: list[str]
    _room: str

    async def async_step_rooms(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Pick the areas to protect."""
        errors: dict[str, str] = {}
        if user_input is not None:
            areas = list(user_input.get(c.CONF_ROOMS) or [])
            if not areas:
                errors[c.CONF_ROOMS] = "no_rooms"
            else:
                self._data[c.CONF_ROOMS] = {a: r for a, r in self._data[c.CONF_ROOMS].items() if a in areas}
                self._queue = areas
                return await self.async_step_room()
        schema = vol.Schema({vol.Required(c.CONF_ROOMS): sel.AreaSelector(sel.AreaSelectorConfig(multiple=True))})
        suggested = {c.CONF_ROOMS: list(self._data[c.CONF_ROOMS])}
        return self.async_show_form(step_id="rooms", data_schema=self.add_suggested_values_to_schema(schema, suggested), errors=errors)

    async def async_step_room(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Configure one room; repeats for every queued area."""
        areas = ar.async_get(self.hass)
        if user_input is not None:
            area = areas.async_get_area(self._room)
            room: dict[str, Any] = {c.CONF_NAME: area.name if area else self._room}
            _merge(room, ROOM_SCHEMA, user_input)
            room[c.CONF_POWER_THRESHOLD] = user_input.get(c.CONF_POWER_THRESHOLD, c.DEFAULT_POWER_THRESHOLD)
            room[c.CONF_OUTDOORS] = bool(user_input.get(c.CONF_OUTDOORS))
            self._data[c.CONF_ROOMS][self._room] = room
            self._queue = self._queue[1:]
            if not self._queue:
                return await self._async_after_rooms()
        self._room = self._queue[0]
        area = areas.async_get_area(self._room)
        stored = self._data[c.CONF_ROOMS].get(self._room)
        defaults = dict(stored) if stored else prefill_room(self.hass, self._room)
        return self.async_show_form(
            step_id="room",
            data_schema=self.add_suggested_values_to_schema(ROOM_SCHEMA, defaults),
            description_placeholders={"room": area.name if area else self._room, "remaining": str(len(self._queue) - 1)},
        )

    async def async_step_house(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Whole-house sources."""
        house = self._data[c.CONF_HOUSE]
        if user_input is not None:
            _merge(house, HOUSE_SCHEMA, user_input)
            if house.get(c.CONF_CSI):
                return await self.async_step_csi_map()
            house[c.CONF_CSI_MAP] = {}
            return await self._async_after_house()
        return self.async_show_form(step_id="house", data_schema=self.add_suggested_values_to_schema(HOUSE_SCHEMA, house))

    async def async_step_csi_map(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Map each CSI sensor to the perimeter contact it watches."""
        house = self._data[c.CONF_HOUSE]
        if user_input is not None:
            house[c.CONF_CSI_MAP] = {k: v for k, v in user_input.items() if v}
            return await self._async_after_house()
        schema = vol.Schema({vol.Optional(csi): _entity("binary_sensor", ent.OPENING_CLASSES, multiple=False) for csi in house.get(c.CONF_CSI, [])})
        return self.async_show_form(step_id="csi_map", data_schema=self.add_suggested_values_to_schema(schema, house.get(c.CONF_CSI_MAP, {})))

    async def async_step_responses(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """The AI task and the digest."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                parse_times(user_input.get(c.CONF_DIGEST_TIMES) or [])
            except ValueError:
                errors[c.CONF_DIGEST_TIMES] = "invalid_time"
            if not errors:
                _merge(self._data[c.CONF_RESPONSES], RESPONSES_SCHEMA, user_input)
                return await self._async_finish()
        schema = self.add_suggested_values_to_schema(RESPONSES_SCHEMA, user_input or self._data[c.CONF_RESPONSES])
        return self.async_show_form(step_id="responses", data_schema=schema, errors=errors)


class SiemConfigFlow(SiemStepsMixin, config_entries.ConfigFlow, domain=c.DOMAIN):
    """Initial setup: rooms, each room, the house, responses."""

    VERSION = 1
    MINOR_VERSION = 6

    def __init__(self) -> None:
        """Start with empty sections."""
        self._data = {c.CONF_ROOMS: {}, c.CONF_HOUSE: {}, c.CONF_RESPONSES: {}}
        self._queue = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Single instance; go straight to the rooms step."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        return await self.async_step_rooms()

    async def _async_after_rooms(self) -> FlowResult:
        return await self.async_step_house()

    async def _async_after_house(self) -> FlowResult:
        return await self.async_step_responses()

    async def _async_finish(self) -> FlowResult:
        self._data[c.CONF_ENTITIES] = build_entity_meta(self.hass, self._data)
        return self.async_create_entry(title=c.NAME, data=self._data)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> SiemOptionsFlow:
        """Return the options flow."""
        return SiemOptionsFlow()


class SiemOptionsFlow(SiemStepsMixin, config_entries.OptionsFlow):
    """Edit rules, engine, weights, rooms, house, responses and strengths."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Show the options menu."""
        entry = self.config_entry
        self._data = {k: copy.deepcopy(dict(entry.data.get(k, {}))) for k in (c.CONF_ROOMS, c.CONF_HOUSE, c.CONF_RESPONSES)}
        self._options = copy.deepcopy(dict(entry.options))
        self._queue = []
        return self.async_show_menu(step_id="init", menu_options=["rules", "engine", "weights", "rooms", "room_pick", "house", "responses", "strength_pick"])

    async def _async_after_rooms(self) -> FlowResult:
        return await self._async_finish()

    async def _async_after_house(self) -> FlowResult:
        return await self._async_finish()

    async def _async_finish(self) -> FlowResult:
        entry = self.config_entry
        data = {**entry.data, **self._data}
        data[c.CONF_ENTITIES] = build_entity_meta(self.hass, data, entry.data.get(c.CONF_ENTITIES))
        self.hass.config_entries.async_update_entry(entry, data=data)
        return self.async_create_entry(data=self._options)

    async def async_step_rules(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Pick the rule to edit."""
        if user_input is not None:
            self._rule = user_input["rule"]
            return await self.async_step_rule_points()
        options = [{"value": r.id, "label": f"{r.id} ({r.tag}): {r.description}"} for r in DEFAULT_RULES.values()]
        return self.async_show_form(step_id="rules", data_schema=vol.Schema({vol.Required("rule"): _select(options)}))

    async def async_step_rule_points(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Edit one rule's points per mode."""
        rules = validate_rule_config(self._options.get(c.OPT_RULES))
        if user_input is not None:
            self._options.setdefault(c.OPT_RULES, {})[self._rule] = {"points": {mode: user_input[mode] for mode in MODES}}
            try:
                validate_rule_config(self._options[c.OPT_RULES])
            except RuleConfigError:
                return self.async_abort(reason="invalid_rule")
            return self.async_create_entry(data=self._options)
        schema = vol.Schema({vol.Required(mode): _number(0, 100, 1) for mode in MODES})
        return self.async_show_form(
            step_id="rule_points",
            data_schema=self.add_suggested_values_to_schema(schema, dict(rules[self._rule].points)),
            description_placeholders={"rule": self._rule, "description": rules[self._rule].description},
        )

    async def async_step_engine(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Half-life, thresholds and chain factors."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                validate_settings(user_input)
            except RuleConfigError:
                errors["base"] = "invalid_thresholds"
            else:
                self._options[c.OPT_ENGINE] = user_input
                return self.async_create_entry(data=self._options)
        settings = validate_settings(self._options.get(c.OPT_ENGINE))
        schema = vol.Schema(
            {
                vol.Required("half_life_min"): _number(1, 240, 1, "min"),
                vol.Required("verify"): _number(1, 100, 1),
                vol.Required("deter"): _number(1, 100, 1),
                vol.Required("alarm"): _number(1, 100, 1),
                **{vol.Required(chain.id): _number(1, 5, 0.1) for chain in DEFAULT_CHAINS},
            }
        )
        defaults = {"half_life_min": settings.half_life_min, **settings.thresholds, **settings.chain_factors}
        return self.async_show_form(step_id="engine", data_schema=self.add_suggested_values_to_schema(schema, defaults), errors=errors)

    async def async_step_weights(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """View the learned weights and optionally reset them."""
        coordinator = self.config_entry.runtime_data
        if user_input is not None:
            if user_input.get("reset"):
                await coordinator.async_reset_weights()
            return self.async_create_entry(data=self._options)
        weights = ", ".join(f"{k}={v}" for k, v in sorted(coordinator.store.weights.items())) or "all rules at 1.0"
        schema = vol.Schema({vol.Optional("reset", default=False): sel.BooleanSelector()})
        return self.async_show_form(step_id="weights", data_schema=schema, description_placeholders={"weights": weights})

    async def async_step_room_pick(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Re-run a single room step."""
        if user_input is not None:
            self._queue = [user_input["room"]]
            return await self.async_step_room()
        options = [{"value": area, "label": room.get(c.CONF_NAME, area)} for area, room in self._data[c.CONF_ROOMS].items()]
        return self.async_show_form(step_id="room_pick", data_schema=vol.Schema({vol.Required("room"): _select(options)}))

    async def async_step_strength_pick(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Pick an occupancy source whose strength to override."""
        if user_input is not None:
            self._entity = user_input["entity"]
            return await self.async_step_strength()
        meta = self.config_entry.data.get(c.CONF_ENTITIES, {})
        options = [{"value": e, "label": f"{e} ({m.get('strength_override') or m.get('strength')})"} for e, m in meta.items() if m.get("role") == ent.ROLE_OCCUPANCY]
        return self.async_show_form(step_id="strength_pick", data_schema=vol.Schema({vol.Required("entity"): _select(options)}))

    async def async_step_strength(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Set or clear the override for the picked source."""
        meta = {k: dict(v) for k, v in self.config_entry.data.get(c.CONF_ENTITIES, {}).items()}
        if user_input is not None:
            if user_input["strength"] == STRENGTH_AUTO:
                meta[self._entity].pop("strength_override", None)
            else:
                meta[self._entity]["strength_override"] = user_input["strength"]
            self.hass.config_entries.async_update_entry(self.config_entry, data={**self.config_entry.data, c.CONF_ENTITIES: meta})
            return self.async_create_entry(data=self._options)
        current = meta[self._entity].get("strength_override", STRENGTH_AUTO)
        schema = vol.Schema({vol.Required("strength", default=current): _select([STRENGTH_AUTO, *STRENGTHS])})
        placeholders = {"entity": self._entity, "derived": meta[self._entity].get("strength", "")}
        return self.async_show_form(step_id="strength", data_schema=schema, description_placeholders=placeholders)
