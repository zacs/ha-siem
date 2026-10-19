"""HA Store persistence: weights, incidents, digest timestamp, house mode override."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, REMOVED_RULES, RENAMED_MODES, RENAMED_RULES

STORAGE_KEY = f"{DOMAIN}.storage"
STORAGE_VERSION = 1
SAVE_DELAY = 5
MAX_INCIDENTS = 200
MAX_WEIGHT_CHANGES = 200
KEYS = ("weights", "incidents", "weight_changes", "last_digest", "override")


class SiemStore:
    """Everything SIEM remembers across restarts, in one storage file."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Bind to the storage file without loading it yet."""
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.weights: dict[str, float] = {}
        self.incidents: list[dict[str, Any]] = []
        self.weight_changes: list[dict[str, Any]] = []
        self.last_digest: str | None = None
        self.override: str | None = None

    async def async_load(self) -> None:
        """Load the file, tolerating a missing or partial one."""
        data = await self._store.async_load() or {}
        weights = (data.get("weights") or {}).items()
        self.weights = {RENAMED_RULES.get(k, k): float(v) for k, v in weights if k not in REMOVED_RULES}
        self.incidents = list(data.get("incidents") or [])[-MAX_INCIDENTS:]
        self.weight_changes = list(data.get("weight_changes") or [])[-MAX_WEIGHT_CHANGES:]
        self.last_digest = data.get("last_digest")
        self.override = RENAMED_MODES.get(data.get("override"), data.get("override"))

    def _data(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in KEYS}

    def async_schedule_save(self) -> None:
        """Save soon, coalescing bursts of changes."""
        self._store.async_delay_save(self._data, SAVE_DELAY)

    async def async_save(self) -> None:
        """Save now."""
        await self._store.async_save(self._data())

    def add_incident(self, incident: Mapping[str, Any]) -> None:
        """Remember a closed incident, keeping the last 200."""
        self.incidents = [i for i in self.incidents if i.get("id") != incident.get("id")]
        self.incidents = [*self.incidents, dict(incident)][-MAX_INCIDENTS:]
        self.async_schedule_save()

    def record_weight_changes(self, changes: Mapping[str, tuple[float, float]], at: float, label: str, incident_id: str) -> None:
        """Log what a label did to the weights, for the digest."""
        self.weight_changes += [{"at": at, "rule": r, "old": o, "new": n, "label": label, "incident_id": incident_id} for r, (o, n) in changes.items()]
        self.weight_changes = self.weight_changes[-MAX_WEIGHT_CHANGES:]
        self.async_schedule_save()

    async def async_remove(self) -> None:
        """Delete the storage file."""
        await self._store.async_remove()
