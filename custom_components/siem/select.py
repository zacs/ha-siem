"""Selects: house mode override and labelling the last incident."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SiemConfigEntry, SiemCoordinator
from .core.house_mode import MODE_AUTO
from .core.rules import HOUSE_MODES
from .core.weights import LABELS
from .entity import SiemEntity

LABEL_NONE = "none"
OVERRIDE, LABEL = "house_mode_override", "label_last_incident"
OPTIONS = {OVERRIDE: [MODE_AUTO, *HOUSE_MODES], LABEL: [LABEL_NONE, *LABELS]}


PARALLEL_UPDATES = 0


async def async_setup_entry(hass: HomeAssistant, entry: SiemConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    """Set up the selects."""
    async_add_entities(SiemSelect(entry.runtime_data, key) for key in OPTIONS)


class SiemSelect(SiemEntity, SelectEntity):
    """Force a house mode (``auto`` derives it), or label the open or most recent incident."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: SiemCoordinator, key: str) -> None:
        """Create the select for ``key``."""
        super().__init__(coordinator, key)
        self._attr_options = OPTIONS[key]

    @property
    def current_option(self) -> str:
        """Return the forced mode, or the last label applied."""
        if self.key == OVERRIDE:
            return self.coordinator.modes.override or MODE_AUTO
        return self.coordinator.last_label or LABEL_NONE

    async def async_select_option(self, option: str) -> None:
        """Apply the override, or label the last incident unless ``none`` was chosen."""
        if self.key == OVERRIDE:
            self.coordinator.set_house_mode(option)
        elif option == LABEL_NONE:
            self.coordinator.last_label = None
            self.coordinator.publish(force=True)
        else:
            self.coordinator.label(option)
