"""Alerts: siem_notification events for escalations and break-glass, with the incident described for automations."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from homeassistant.core import Context, HomeAssistant
from homeassistant.util import dt as dt_util

from .const import CATEGORY_BREAK_GLASS, CONF_CAMERA, EVENT_NOTIFICATION, SNAPSHOT_DIR, SNAPSHOT_KEEP, SNAPSHOT_TIMEOUT_S
from .core.incident import EVENT_TIER_CHANGED, Incident, IncidentEvent
from .core.messages import alert_message, alert_title, timeline_line
from .core.rules import describe
from .core.scoring import TIER_VERIFY, tier_rank

if TYPE_CHECKING:
    from .coordinator import SiemCoordinator

_LOGGER = logging.getLogger(__name__)


def _prune(directory: Path) -> None:
    """Create the snapshot folder and keep only the newest snapshots."""
    directory.mkdir(parents=True, exist_ok=True)
    files = sorted(directory.glob("*.jpg"), key=lambda f: f.stat().st_mtime, reverse=True)
    for old in files[SNAPSHOT_KEEP - 1 :]:
        old.unlink(missing_ok=True)


class Alerts:
    """Describe incidents and fire the alert events. SIEM itself never acts on them."""

    def __init__(self, hass: HomeAssistant, coordinator: SiemCoordinator) -> None:
        """Bind to the coordinator."""
        self.hass = hass
        self.coordinator = coordinator
        self._root = Context()

    def context(self) -> Context:
        """Return a child of SIEM's own context; automations triggered by SIEM's events inherit it as a parent."""
        return Context(parent_id=self._root.id)

    def timeline(self, incident: Incident) -> list[dict[str, Any]]:
        """Return the incident timeline with local times, friendly names, room names and rule descriptions."""
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
        c = self.coordinator
        lines = []
        for entry in incident.timeline:
            at = dt_util.as_local(dt_util.utc_from_timestamp(entry["at"])).strftime("%H:%M")
            if entry.get("entity_id"):
                lines.append(timeline_line(at, c.entity_name(entry["entity_id"]), describe(c.rules, entry["rule"]), entry["points"]))
            else:
                lines.append(timeline_line(at, entry.get("detail") or describe(c.rules, entry["rule"]), None, entry["points"]))
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
            "area_id": incident.room,
            "mode": incident.mode,
            "house_mode": c.house_mode,
            "person": incident.person,
            "started": c.iso(incident.started),
            "closed": c.iso(incident.closed),
            "labels": list(incident.labels),
            "entities": incident.entity_ids(),
            "top_contributors": c.engine.top_contributors(now) if current else [],
            "timeline": self.timeline(incident),
        }

    def fire(self, category: str, title: str, message: str, **data: Any) -> None:
        """Fire ``siem_notification``; every field is always present so automations need no guards."""
        payload = {"incident": None, "snapshot": None, "again": False, "summary": None, **data}
        payload.update(category=category, title=title, message=message)
        self.hass.bus.async_fire(EVENT_NOTIFICATION, payload, context=self.context())

    async def async_handle(self, events: list[IncidentEvent], renotify: Incident | None) -> None:
        """Alert on upward tier changes, and again when a verify incident's score doubled.

        Verify is a heads-up, raised once per incident: once anything was announced, a score that dips below verify
        and comes back is not announced again. Deter and alarm are announced every time they are reached, since
        automations act on them.
        """
        for event in events:
            if event.kind != EVENT_TIER_CHANGED or tier_rank(event.tier) <= tier_rank(event.previous_tier):
                continue
            if event.tier == TIER_VERIFY and event.incident.notified_score is not None:
                continue
            await self._async_alert(event.incident, event.tier)
        if renotify is not None:
            await self._async_alert(renotify, TIER_VERIFY, again=True)

    async def _async_alert(self, incident: Incident, tier: str, again: bool = False) -> None:
        c = self.coordinator
        score = c.engine.score(c.now()) if incident is c.engine.current else incident.peak_score
        incident.notified_score = score
        snapshot = await self.async_snapshot(incident, tier)
        message = alert_message(score, c.house_mode, self.timeline_lines(incident), again=again)
        self.fire(tier, alert_title(tier, c.room_name(incident.room)), message, incident=self.incident_payload(incident), snapshot=snapshot, again=again)

    def break_glass(self, message: str) -> None:
        """Alert on what matters whatever the score: a hand unlock while vacant, a keypad lockout, a long outage."""
        c = self.coordinator
        incident = c.engine.current
        self.fire(CATEGORY_BREAK_GLASS, "SIEM break glass", f"{message}. House {c.house_mode}.", incident=self.incident_payload(incident) if incident else None)

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
                await self.hass.services.async_call("camera", "snapshot", {"entity_id": camera, "filename": str(path)}, blocking=True, context=self.context())
        except Exception as err:
            _LOGGER.warning("Snapshot of %s failed: %s", camera, err)
            return None
        return str(path)
