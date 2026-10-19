"""Binary sensors: night window and the alarm trigger."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SiemConfigEntry
from .core.scoring import TIER_ALARM
from .entity import SiemEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(hass: HomeAssistant, entry: SiemConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    """Set up the binary sensors."""
    async_add_entities([SiemBinarySensor(entry.runtime_data, "night"), SiemBinarySensor(entry.runtime_data, "alarm_trigger")])


class SiemBinarySensor(SiemEntity, BinarySensorEntity):
    """Night is on inside the configured window; the alarm trigger while the open incident is at the alarm tier.

    Add the alarm trigger to your alarm panel (in Alarmo, as an always-on sensor) if you want SIEM to set it off.
    """

    @property
    def is_on(self) -> bool:
        """Return the flag from the coordinator."""
        return self.coordinator.night if self.key == "night" else self.coordinator.tier == TIER_ALARM
