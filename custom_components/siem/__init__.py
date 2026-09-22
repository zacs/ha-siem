"""SIEM for Home Assistant: a SIEM-style risk engine for a house."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .const import (
    ATTR_INCIDENT_ID,
    ATTR_LABEL,
    ATTR_MODE,
    DOMAIN,
    PLATFORMS,
    SERVICE_LABEL_INCIDENT,
    SERVICE_RESET_WEIGHTS,
    SERVICE_RUN_DIGEST,
    SERVICE_SET_HOUSE_MODE,
)
from .coordinator import SiemConfigEntry, SiemCoordinator
from .core.house_mode import MODE_AUTO
from .core.rules import MODES, RuleConfigError
from .core.weights import LABELS
from .store import SiemStore

_LOGGER = logging.getLogger(__name__)
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

LABEL_SCHEMA = vol.Schema({vol.Required(ATTR_LABEL): vol.In(LABELS), vol.Optional(ATTR_INCIDENT_ID): cv.string})
MODE_SCHEMA = vol.Schema({vol.Required(ATTR_MODE): vol.In([MODE_AUTO, *MODES])})


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
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    _register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SiemConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_stop()
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: SiemConfigEntry) -> None:
    """Delete the store when the entry is removed."""
    await SiemStore(hass).async_remove()


async def _async_update_listener(hass: HomeAssistant, entry: SiemConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _coordinator(hass: HomeAssistant) -> SiemCoordinator:
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        return entry.runtime_data
    raise HomeAssistantError("SIEM is not loaded")


@callback
def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_LABEL_INCIDENT):
        return

    async def label_incident(call: ServiceCall) -> None:
        try:
            _coordinator(hass).label(call.data[ATTR_LABEL], call.data.get(ATTR_INCIDENT_ID))
        except (ValueError, LookupError) as err:
            raise HomeAssistantError(str(err)) from err

    async def run_digest(call: ServiceCall) -> None:
        await _coordinator(hass).digest.async_run(manual=True)

    async def reset_weights(call: ServiceCall) -> None:
        await _coordinator(hass).async_reset_weights()

    async def set_house_mode(call: ServiceCall) -> None:
        _coordinator(hass).set_house_mode(call.data[ATTR_MODE])

    services = ((SERVICE_LABEL_INCIDENT, label_incident, LABEL_SCHEMA), (SERVICE_RUN_DIGEST, run_digest, None), (SERVICE_RESET_WEIGHTS, reset_weights, None))
    for name, handler, schema in (*services, (SERVICE_SET_HOUSE_MODE, set_house_mode, MODE_SCHEMA)):
        hass.services.async_register(DOMAIN, name, handler, schema=schema)
