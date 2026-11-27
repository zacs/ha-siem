"""Base entity for SIEM for Home Assistant."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, NAME, VERSION
from .coordinator import SiemCoordinator


class SiemEntity(CoordinatorEntity[SiemCoordinator]):
    """An entity on the single SIEM device, named by translation key."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SiemCoordinator, key: str) -> None:
        """Bind to the coordinator under ``key``."""
        super().__init__(coordinator)
        self.key = key
        self._attr_translation_key = key
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)}, name=NAME, manufacturer=MANUFACTURER, model="ha-siem", sw_version=VERSION, entry_type=DeviceEntryType.SERVICE
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Write the new state under the context of what caused it, so the logbook can say what happened."""
        if (cause := self.coordinator.cause) is not None:
            self.async_set_context(cause)
        super()._handle_coordinator_update()
