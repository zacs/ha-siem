"""Alert events: a siem_notification for every alert, with the incident described for automations."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import CONF_CAMERA, CONF_DRY_RUN, EVENT_NOTIFICATION, SNAPSHOT_DIR, SNAPSHOT_KEEP, SNAPSHOT_TIMEOUT_S
from .core.incident import Incident
from .core.messages import timeline_line
from .core.rules import describe

if TYPE_CHECKING:
    from .coordinator import SiemCoordinator

_LOGGER = logging.getLogger(__name__)


def _prune(directory: Path) -> None:
    """Create the snapshot folder and keep only the newest snapshots."""
    directory.mkdir(parents=True, exist_ok=True)
    files = sorted(directory.glob("*.jpg"), key=lambda f: f.stat().st_mtime, reverse=True)
    for old in files[SNAPSHOT_KEEP - 1 :]:
        old.unlink(missing_ok=True)


class Notifier:
    """Describe incidents and fire the alert events."""

    def __init__(self, hass: HomeAssistant, coordinator: SiemCoordinator) -> None:
        """Bind to the coordinator's response settings."""
        self.hass = hass
        self.coordinator = coordinator

    def timeline(self, incident: Incident) -> list[dict[str, Any]]:
        """Return the incident timeline with local times, friendly names and rule descriptions."""
        c = self.coordinator
        return [
            {
                **entry,
                "at": c.iso(entry["at"]),
                "room": c.room_name(entry.get("room")),
                "name": c.entity_name(entry.get("entity_id")) if entry.get("entity_id") else None,
                "description": describe(c.rules, entry["rule"]),
            }
            for entry in incident.timeline
        ]

    def timeline_lines(self, incident: Incident) -> list[str]:
        """Render the timeline as plain lines; events without an entity read from their detail."""
        lines = []
        for entry in incident.timeline:
            at = dt_util.as_local(dt_util.utc_from_timestamp(entry["at"])).strftime("%H:%M")
            if entry.get("entity_id"):
                lines.append(timeline_line(at, self.coordinator.entity_name(entry["entity_id"]), describe(self.coordinator.rules, entry["rule"]), entry["points"]))
            else:
                lines.append(timeline_line(at, entry.get("detail") or describe(self.coordinator.rules, entry["rule"]), None, entry["points"]))
        return lines

    def incident_payload(self, incident: Incident) -> dict[str, Any]:
        """Return everything an automation needs to describe ``incident``."""
        c = self.coordinator
        now = c.now()
        current = incident is c.engine.current
        return {
            "incident_id": incident.id,
            "tier": incident.tier,
            "peak_tier": incident.peak_tier,
            "score": round(c.engine.score(now), 1) if current else 0.0,
            "peak_score": round(incident.peak_score, 1),
            "room": c.room_name(incident.room),
            "mode": incident.mode,
            "house_mode": c.house_mode,
            "person": incident.person,
            "started": c.iso(incident.started),
            "closed": c.iso(incident.closed),
            "labels": list(incident.labels),
            "top_contributors": c.engine.top_contributors(now) if current else [],
            "timeline": self.timeline(incident),
        }

    async def async_alert(self, category: str, title: str, message: str, **data: Any) -> None:
        """Fire ``siem_notification``; every field is always present so automations need no guards."""
        c = self.coordinator
        payload = {"incident": None, "actions": [], "snapshot": None, "again": False, "summary": None, **data}
        payload.update(category=category, title=title, message=message, dry_run=c.toggles[CONF_DRY_RUN])
        self.hass.bus.async_fire(EVENT_NOTIFICATION, payload, context=c.responder.context())

    def snapshot_dir(self) -> Path:
        """Return the snapshot folder: under the local media folder, which needs a login to browse."""
        media = self.hass.config.media_dirs
        root = media.get("local") or next(iter(media.values()), None) or self.hass.config.path("media")
        return Path(root) / SNAPSHOT_DIR

    async def async_snapshot(self, incident: Incident, tier: str) -> str | None:
        """Save a snapshot from the incident room's camera, if it has one; give up after a few seconds."""
        camera = self.coordinator.rooms.get(incident.room or "", {}).get(CONF_CAMERA)
        if not camera:
            return None
        directory = self.snapshot_dir()
        path = directory / f"{incident.id}_{tier}.jpg"
        try:
            await self.hass.async_add_executor_job(_prune, directory)
            async with asyncio.timeout(SNAPSHOT_TIMEOUT_S):
                await self.hass.services.async_call("camera", "snapshot", {"entity_id": camera, "filename": str(path)}, blocking=True, context=self.coordinator.responder.context())
        except Exception as err:
            _LOGGER.warning("Snapshot of %s failed: %s", camera, err)
            return None
        return str(path)
