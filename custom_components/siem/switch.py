"""Runtime toggles exposed as switches: dry run, auto arm, auto alarm."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import TOGGLES
from .coordinator import SiemConfigEntry
from .entity import SiemEntity

ICONS = {"dry_run": "mdi:test-tube", "auto_arm": "mdi:shield-lock", "auto_alarm": "mdi:alarm-light"}


async def async_setup_entry(hass: HomeAssistant, entry: SiemConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up the switches."""
    async_add_entities(SiemSwitch(entry.runtime_data, key) for key in TOGGLES)


class SiemSwitch(SiemEntity, SwitchEntity):
    """A toggle persisted in the SIEM store so a restart keeps it."""

    _attr_entity_category = EntityCategory.CONFIG

    @property
    def icon(self) -> str:
        """Return the icon for this toggle."""
        return ICONS[self.key]

    @property
    def is_on(self) -> bool:
        """Return the toggle state."""
        return self.coordinator.toggles[self.key]

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the toggle."""
        await self.coordinator.async_set_toggle(self.key, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the toggle."""
        await self.coordinator.async_set_toggle(self.key, False)
