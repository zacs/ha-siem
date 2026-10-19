"""Sensors: risk score, tier, incident, house mode, arm recommendation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SiemConfigEntry, SiemCoordinator
from .core.arm import ARM_MODES
from .core.rules import MODES
from .core.scoring import TIERS
from .entity import SiemEntity


@dataclass(frozen=True, kw_only=True)
class SiemSensorDescription(SensorEntityDescription):
    """A sensor whose value and attributes are read from the coordinator."""

    value_fn: Callable[[SiemCoordinator], Any]
    attrs_fn: Callable[[SiemCoordinator], dict[str, Any]] = lambda _: {}


def _incident_attrs(coordinator: SiemCoordinator) -> dict[str, Any]:
    incident = coordinator.engine.current
    if incident is None:
        return {"started": None, "room": None, "mode": None, "person": None, "timeline": []}
    timeline = [{**e, "at": coordinator.iso(e["at"])} for e in incident.timeline]
    return {"started": coordinator.iso(incident.started), "room": coordinator.room_name(incident.room), "mode": incident.mode, "person": incident.person, "timeline": timeline}


DESCRIPTIONS: tuple[SiemSensorDescription, ...] = (
    SiemSensorDescription(
        key="risk_score", native_unit_of_measurement="points", state_class=SensorStateClass.MEASUREMENT, value_fn=lambda c: round(c.score, 1), attrs_fn=lambda c: {"top_contributors": c.top, "incident_id": c.incident_id}
    ),
    SiemSensorDescription(key="tier", device_class=SensorDeviceClass.ENUM, options=list(TIERS), value_fn=lambda c: c.tier),
    SiemSensorDescription(key="incident", value_fn=lambda c: c.incident_id or "none", attrs_fn=_incident_attrs),
    SiemSensorDescription(key="house_mode", device_class=SensorDeviceClass.ENUM, options=list(MODES), value_fn=lambda c: c.house_mode),
    SiemSensorDescription(
        key="recommended_alarm_mode", device_class=SensorDeviceClass.ENUM, options=list(ARM_MODES), value_fn=lambda c: c.recommended_arm
    ),
)


PARALLEL_UPDATES = 0


async def async_setup_entry(hass: HomeAssistant, entry: SiemConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    """Set up the sensors."""
    async_add_entities(SiemSensor(entry.runtime_data, description) for description in DESCRIPTIONS)


class SiemSensor(SiemEntity, SensorEntity):
    """A coordinator-backed sensor. The incident timeline is never recorded."""

    entity_description: SiemSensorDescription
    _unrecorded_attributes = frozenset({"timeline"})

    def __init__(self, coordinator: SiemCoordinator, description: SiemSensorDescription) -> None:
        """Create the sensor for ``description``."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Return the value read from the coordinator."""
        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the attributes read from the coordinator."""
        return self.entity_description.attrs_fn(self.coordinator)
