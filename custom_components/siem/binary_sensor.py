"""Binary sensors: night and the alarm trigger."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SiemConfigEntry
from .entity import SiemEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(hass: HomeAssistant, entry: SiemConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    """Set up the binary sensors."""
    async_add_entities([SiemBinarySensor(entry.runtime_data, key) for key in ("night", "alarm_trigger")])


class SiemBinarySensor(SiemEntity, BinarySensorEntity):
    """Night and the alarm trigger, as on/off.

    Night is on while it is night for this house: the family's bedtime sources, with the night window standing in;
    with only guests home, the night window, which a source saying bed can start sooner; with nobody home, the night
    window. The alarm trigger is on once the open incident has held the alarm tier for a
    minute. Add the alarm trigger to your alarm panel (in Alarmo, as an always-on sensor) if you want SIEM to set it off.
    """

    @property
    def is_on(self) -> bool:
        """Return the flag from the coordinator."""
        return bool(getattr(self.coordinator, self.key))
