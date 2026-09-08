"""Binary sensors: night window and the alarm trigger pulse."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import SiemConfigEntry, SiemCoordinator
from .entity import SiemEntity

ICONS = {"night": "mdi:weather-night", "alarm_trigger": "mdi:bell-ring"}


async def async_setup_entry(hass: HomeAssistant, entry: SiemConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up the binary sensors."""
    async_add_entities([SiemBinarySensor(entry.runtime_data, "night"), SiemBinarySensor(entry.runtime_data, "alarm_trigger")])


class SiemBinarySensor(SiemEntity, BinarySensorEntity):
    """Night is on inside the configured window; alarm trigger pulses for 60 s."""

    def __init__(self, coordinator: SiemCoordinator, key: str) -> None:
        """Create the sensor for ``key``."""
        super().__init__(coordinator, key)
        self._attr_icon = ICONS[key]

    @property
    def is_on(self) -> bool:
        """Return the flag from the coordinator."""
        return self.coordinator.night if self.key == "night" else self.coordinator.alarm_trigger_on
