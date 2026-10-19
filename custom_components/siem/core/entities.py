"""Entity heuristics: strengths, interior doors, gates, residents."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .occupancy import STRENGTH_MEDIUM, STRENGTH_STRONG, STRENGTH_WEAK, STRENGTHS

OCCUPANCY_CLASSES: tuple[str, ...] = ("occupancy", "presence", "motion", "sound")
OPENING_CLASSES: tuple[str, ...] = ("door", "window", "opening", "garage_door")
INTERIOR_DOOR_KEYWORDS: tuple[str, ...] = (
    "fridge", "freezer", "refrigerator", "pantry", "cabinet", "cupboard", "drawer", "closet",
)
EXTERIOR_AREA_KEYWORDS: tuple[str, ...] = (
    "yard", "driveway", "porch", "patio", "outside", "outdoor", "exterior", "garden", "deck", "balcony", "pool",
)
BAYESIAN_PLATFORM = "bayesian"
STRENGTH_BY_CLASS = {"occupancy": STRENGTH_STRONG, "presence": STRENGTH_STRONG, "motion": STRENGTH_MEDIUM, "sound": STRENGTH_WEAK}

# The role an entity plays, stored per entity in the config entry's metadata dict.
(ROLE_OCCUPANCY, ROLE_PERIMETER, ROLE_INTERIOR_DOOR, ROLE_LIGHT, ROLE_POWER, ROLE_CAMERA, ROLE_CSI, ROLE_WATER, ROLE_LOAD, ROLE_AUTOMATED_LOAD,
 ROLE_LOCK, ROLE_LCM_EVENT, ROLE_PERSON, ROLE_TRACKER, ROLE_CALENDAR, ROLE_PANEL) = (
    "occupancy", "perimeter", "interior_door", "light", "power", "camera", "csi", "water", "load", "automated_load",
    "lock", "lcm_event", "person", "tracker", "calendar", "panel",
)
# Roles whose loss of contact is worth scoring as sensor_offline. Lights, plugs, cameras and helpers drop out too often.
SENSING_ROLES: frozenset[str] = frozenset({ROLE_OCCUPANCY, ROLE_PERIMETER, ROLE_INTERIOR_DOOR, ROLE_CSI, ROLE_LOCK})


@dataclass(frozen=True)
class EntityInfo:
    """The registry facts the heuristics look at."""

    entity_id: str
    domain: str
    device_class: str | None = None
    platform: str | None = None
    name: str | None = None
    area_id: str | None = None


def _mentions(keywords: Iterable[str], *names: str | None) -> bool:
    haystack = " ".join(n for n in names if n).casefold()
    return any(k in haystack for k in keywords)


def is_interior_door_name(*names: str | None) -> bool:
    """Return True when a name reads as a fridge, cabinet, drawer or closet."""
    return _mentions(INTERIOR_DOOR_KEYWORDS, *names)


def is_gate(*names: str | None) -> bool:
    """Return True when a perimeter contact is a gate."""
    return _mentions(("gate",), *names)


def is_person_detector(*names: str | None) -> bool:
    """Return True for camera person-detection sensors."""
    return _mentions(("person",), *names)


def is_exterior_area(name: str | None) -> bool:
    """Return True when an area name reads as outdoors."""
    return _mentions(EXTERIOR_AREA_KEYWORDS, name)


def derive_strength(device_class: str | None, platform: str | None) -> str:
    """Derive an occupancy source's strength from its class and platform."""
    if platform == BAYESIAN_PLATFORM:
        return STRENGTH_STRONG
    return STRENGTH_BY_CLASS.get(device_class or "", STRENGTH_WEAK)


def effective_strength(meta: Mapping[str, Any]) -> str:
    """Return the per-entity override when set, strong for a camera's person detection, else the derived strength."""
    override = meta.get("strength_override")
    if override in STRENGTHS:
        return override
    if meta.get("person_detector"):
        return STRENGTH_STRONG
    strength = meta.get("strength")
    return strength if strength in STRENGTHS else STRENGTH_WEAK


def split_openings(entities: Iterable[EntityInfo]) -> tuple[list[str], list[str]]:
    """Split opening sensors into perimeter and interior-door lists by name."""
    perimeter: list[str] = []
    interior: list[str] = []
    for info in entities:
        if info.device_class not in OPENING_CLASSES:
            continue
        (interior if is_interior_door_name(info.entity_id, info.name) else perimeter).append(info.entity_id)
    return perimeter, interior


def occupancy_candidates(entities: Iterable[EntityInfo]) -> list[str]:
    """Return the binary sensors whose class marks them as occupancy sources."""
    return [e.entity_id for e in entities if e.domain == "binary_sensor" and e.device_class in OCCUPANCY_CLASSES]


@dataclass
class ResidentSet:
    """Trackers and user ids expanded from person entities."""

    trackers: list[str] = field(default_factory=list)
    user_ids: list[str] = field(default_factory=list)


def expand_residents(person_attributes: Mapping[str, Mapping[str, Any]]) -> ResidentSet:
    """Read ``device_trackers`` and ``user_id`` from each person's attributes."""
    result = ResidentSet()
    for attrs in person_attributes.values():
        for tracker in attrs.get("device_trackers") or []:
            if isinstance(tracker, str) and tracker not in result.trackers:
                result.trackers.append(tracker)
        user_id = attrs.get("user_id")
        if isinstance(user_id, str) and user_id and user_id not in result.user_ids:
            result.user_ids.append(user_id)
    return result
