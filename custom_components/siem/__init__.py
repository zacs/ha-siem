"""SIEM for Home Assistant: a SIEM-style risk engine for a house."""

from __future__ import annotations

import copy
import logging

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType
import voluptuous as vol

from . import const as c
from .coordinator import SiemConfigEntry, SiemCoordinator
from .core.house_mode import MODE_AUTO
from .core.rules import MODES, RuleConfigError
from .core.weights import LABELS
from .store import SiemStore

_LOGGER = logging.getLogger(__name__)
CONFIG_SCHEMA = cv.config_entry_only_config_schema(c.DOMAIN)

LABEL_SCHEMA = vol.Schema({vol.Required(c.ATTR_LABEL): vol.In(LABELS), vol.Optional(c.ATTR_INCIDENT_ID): cv.string})
MODE_SCHEMA = vol.Schema({vol.Required(c.ATTR_MODE): vol.In([MODE_AUTO, *MODES])})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the services once; they act on the loaded entry."""

    def coordinator() -> SiemCoordinator:
        for entry in hass.config_entries.async_loaded_entries(c.DOMAIN):
            return entry.runtime_data
        raise ServiceValidationError(translation_domain=c.DOMAIN, translation_key="not_loaded")

    async def label_incident(call: ServiceCall) -> None:
        try:
            coordinator().label(call.data[c.ATTR_LABEL], call.data.get(c.ATTR_INCIDENT_ID))
        except LookupError as err:
            raise ServiceValidationError(translation_domain=c.DOMAIN, translation_key="no_incident") from err

    async def run_digest(call: ServiceCall) -> None:
        await coordinator().digest.async_run(manual=True)

    async def reset_weights(call: ServiceCall) -> None:
        await coordinator().async_reset_weights()

    async def set_house_mode(call: ServiceCall) -> None:
        coordinator().set_house_mode(call.data[c.ATTR_MODE])

    for name, handler, schema in (
        (c.SERVICE_LABEL_INCIDENT, label_incident, LABEL_SCHEMA),
        (c.SERVICE_RUN_DIGEST, run_digest, None),
        (c.SERVICE_RESET_WEIGHTS, reset_weights, None),
        (c.SERVICE_SET_HOUSE_MODE, set_house_mode, MODE_SCHEMA),
    ):
        hass.services.async_register(c.DOMAIN, name, handler, schema=schema)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SiemConfigEntry) -> bool:
    """Set up SIEM from a config entry."""
    store = SiemStore(hass)
    await store.async_load()
    try:
        coordinator = SiemCoordinator(hass, entry, store)
    except RuleConfigError as err:
        raise HomeAssistantError(f"Invalid SIEM options: {err}") from err
    entry.runtime_data = coordinator
    await coordinator.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, c.PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SiemConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, c.PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_stop()
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: SiemConfigEntry) -> None:
    """Delete the store when the entry is removed."""
    await SiemStore(hass).async_remove()


async def _async_update_listener(hass: HomeAssistant, entry: SiemConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: SiemConfigEntry) -> bool:
    """Migrate older 1.x entries: guest instead of sitter, appliance_on instead of tv_power, no notify or panel settings."""
    if entry.version > 1:
        return False
    if entry.minor_version < 3:
        data, options = copy.deepcopy(dict(entry.data)), copy.deepcopy(dict(entry.options))
        responses = data.setdefault(c.CONF_RESPONSES, {})
        for key in c.REMOVED_RESPONSES:
            responses.pop(key, None)
        rules = {c.RENAMED_RULES.get(rule_id, rule_id): value for rule_id, value in (options.get(c.OPT_RULES) or {}).items()}
        for value in rules.values():
            points = value.get("points") if isinstance(value, dict) else None
            if isinstance(points, dict):
                value["points"] = {c.RENAMED_MODES.get(mode, mode): pts for mode, pts in points.items()}
        if rules:
            options[c.OPT_RULES] = rules
        registry = er.async_get(hass)
        if entity_id := registry.async_get_entity_id("switch", c.DOMAIN, f"{entry.entry_id}_auto_arm"):
            registry.async_remove(entity_id)
        hass.config_entries.async_update_entry(entry, data=data, options=options, minor_version=3)
        _LOGGER.info("Migrated SIEM config entry to 1.3")
    return True
