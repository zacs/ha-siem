"""Mattermost-shaped notify payloads, with a plain-message fallback."""

from __future__ import annotations

from collections.abc import Iterable
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant

from .const import CONF_MOBILE_NOTIFY, CONF_NOTIFY, CONF_TARGET, DEFAULT_NOTIFY, DEFAULT_TARGET, MOBILE_ACTION_PREFIX, SNAPSHOT_SUBDIR, TIER_COLORS
from .core.incident import Incident
from .core.weights import LABELS

if TYPE_CHECKING:
    from .coordinator import SiemCoordinator

_LOGGER = logging.getLogger(__name__)
LABEL_TITLES = {"false_alarm": "False alarm", "thats_me": "That's me", "sitter": "Sitter", "real": "Real"}


class Notifier:
    """Send SIEM messages through the configured notify services."""

    def __init__(self, hass: HomeAssistant, coordinator: SiemCoordinator) -> None:
        """Bind to the coordinator's response settings."""
        self.hass = hass
        self.coordinator = coordinator

    def incident_attachment(self, incident: Incident, tier: str) -> dict[str, Any]:
        """Build the attachment for an incident at ``tier``."""
        c = self.coordinator
        contributors = ", ".join(f"{t['rule']} {t['points']}" for t in c.top) or "none"
        timeline = "\n".join(
            f"- {c.iso(e['at'])}: **{e['rule']}** {e['points']:+} {e.get('entity_id') or ''} {e.get('detail') or ''}".rstrip()
            for e in incident.timeline
        )
        return {
            "color": TIER_COLORS[tier],
            "title": f"{tier} in {c.room_name(incident.room) or 'the house'}",
            "fields": [
                {"short": True, "title": title, "value": value}
                for title, value in (("Room", c.room_name(incident.room) or "-"), ("Mode", incident.mode), ("Score", f"{c.score:.0f}"), ("Top contributors", contributors))
            ],
            "text": timeline or "_no events yet_",
        }

    async def async_send(
        self,
        message: str,
        *,
        attachment: dict[str, Any] | None = None,
        services: Iterable[str] | None = None,
        camera: str | None = None,
        incident_id: str | None = None,
    ) -> None:
        """Send ``message`` with an optional attachment and camera snapshot."""
        data: dict[str, Any] = {}
        if attachment:
            data["attachments"] = [attachment]
        if camera and incident_id and (path := await self._async_snapshot(camera, incident_id)):
            data["file"] = {"path": path}
        payload = {"message": message, "target": [self.coordinator.responses.get(CONF_TARGET) or DEFAULT_TARGET]}
        if data:
            payload["data"] = data
        for service in services or [self.coordinator.responses.get(CONF_NOTIFY) or DEFAULT_NOTIFY]:
            await self._async_call(service, payload)

    async def async_send_actionable(self, incident: Incident, message: str) -> None:
        """Offer label buttons through the mobile notify service, when configured."""
        service = self.coordinator.responses.get(CONF_MOBILE_NOTIFY)
        if not service:
            return
        actions = [{"action": f"{MOBILE_ACTION_PREFIX}{label.upper()}|{incident.id}", "title": LABEL_TITLES[label]} for label in LABELS]
        await self._async_call(service, {"message": message, "title": "SIEM", "data": {"actions": actions}})

    async def _async_call(self, service: str, payload: dict[str, Any]) -> None:
        domain, name = service.split(".", 1)
        try:
            await self.hass.services.async_call(domain, name, payload, blocking=True)
        except Exception as err:
            _LOGGER.warning("%s rejected the rich payload (%s); sending a plain message", service, err)
            try:
                await self.hass.services.async_call(domain, name, {"message": payload["message"]}, blocking=True)
            except Exception:
                _LOGGER.exception("%s failed", service)

    async def _async_snapshot(self, camera: str, incident_id: str) -> str | None:
        path = Path(self.hass.config.path(*SNAPSHOT_SUBDIR, f"{incident_id}.jpg"))
        try:
            await self.hass.async_add_executor_job(lambda: path.parent.mkdir(parents=True, exist_ok=True))
            await self.hass.services.async_call("camera", "snapshot", {"entity_id": camera, "filename": str(path)}, blocking=True)
        except Exception as err:
            _LOGGER.warning("Snapshot of %s failed: %s", camera, err)
            return None
        return str(path)
