"""Event entity announcing incident lifecycle transitions."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import SIGNAL_INCIDENT_EVENT
from .coordinator import SiemConfigEntry, SiemCoordinator
from .core.incident import INCIDENT_EVENT_TYPES
from .entity import SiemEntity


async def async_setup_entry(hass: HomeAssistant, entry: SiemConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up the incident event entity."""
    async_add_entities([SiemIncidentEvent(entry.runtime_data)])


class SiemIncidentEvent(SiemEntity, EventEntity):
    """Fires ``opened``, ``tier_changed`` and ``closed`` with the incident summary."""

    _attr_event_types = list(INCIDENT_EVENT_TYPES)
    _attr_icon = "mdi:shield-sync"

    def __init__(self, coordinator: SiemCoordinator) -> None:
        """Create the event entity."""
        super().__init__(coordinator, "incident")

    async def async_added_to_hass(self) -> None:
        """Subscribe to incident transitions from the coordinator."""
        await super().async_added_to_hass()
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_INCIDENT_EVENT, self._handle))

    @callback
    def _handle(self, kind: str, data: dict[str, Any]) -> None:
        self._trigger_event(kind, data)
        self.async_write_ha_state()
