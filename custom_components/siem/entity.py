"""Base entity for SIEM for Home Assistant."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
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
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, coordinator.entry.entry_id)}, name=NAME, manufacturer=MANUFACTURER, model="Risk engine", sw_version=VERSION)
