"""Digest: summarise the window through ai_task and announce it as an event."""

from __future__ import annotations

import asyncio
from datetime import datetime
import json
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import AI_TASK_TIMEOUT_S, CATEGORY_DIGEST, CONF_AI_TASK, CONF_DIGEST_EMPTY, CONF_DIGEST_TIMES, DEFAULT_DIGEST_TIMES
from .core.digest import fallback_text, is_due, summarize_window

if TYPE_CHECKING:
    from .coordinator import SiemCoordinator

_LOGGER = logging.getLogger(__name__)
INSTRUCTIONS = (
    "You are the daily security digest for a house. Below is JSON with the incidents, their labels and the rule "
    "weight changes since the previous digest. Write exactly five short lines: what happened, what was labelled, "
    "what changed in the weights, anything worth checking, and one sentence of overall assessment.\n\n"
)


class DigestRunner:
    """Run the digest on schedule or on demand."""

    def __init__(self, hass: HomeAssistant, coordinator: SiemCoordinator) -> None:
        """Bind to the coordinator."""
        self.hass = hass
        self.coordinator = coordinator
        self._running = False

    def _last_run(self) -> datetime | None:
        raw = self.coordinator.store.last_digest
        parsed = dt_util.parse_datetime(raw) if raw else None
        return dt_util.as_local(parsed) if parsed else None

    def due(self, now: datetime) -> bool:
        """Return True when a configured digest time passed since the last run."""
        times = self.coordinator.responses.get(CONF_DIGEST_TIMES) or DEFAULT_DIGEST_TIMES
        try:
            return not self._running and is_due(times, self._last_run(), dt_util.as_local(now))
        except ValueError:
            _LOGGER.warning("Invalid digest times %s", times)
            return False

    @property
    def running(self) -> bool:
        """Return True while a digest is being written."""
        return self._running

    async def async_run(self, manual: bool = False, ai_task: str | None = None, preview: bool = False) -> dict[str, Any] | None:
        """Summarise everything since the previous digest and post it; return what was written.

        ``ai_task`` writes this one digest with another AI task entity than the configured one. A ``preview`` posts
        nothing and leaves the digest period alone, so the same stretch of time can be summarised again, say by
        another model. Returns None when a digest is already running, a scheduled one had nothing to say, or it failed.
        """
        if self._running:
            return None
        self._running = True
        try:
            return await self._async_run(manual, ai_task, preview)
        except Exception:
            _LOGGER.exception("Digest failed")
            return None
        finally:
            self._running = False

    async def _async_run(self, manual: bool, ai_task: str | None, preview: bool) -> dict[str, Any] | None:
        c = self.coordinator
        now = dt_util.now()
        since = self._last_run()
        incidents = list(c.store.incidents) + ([c.engine.current.as_dict()] if c.engine.current else [])
        summary = summarize_window(incidents, c.store.weight_changes, since, now)
        if not preview:
            c.store.last_digest = now.isoformat()
            c.store.async_schedule_save()
        quiet = summary["incident_count"] == 0 and not summary["weight_changes"]
        if quiet and not manual and not c.responses.get(CONF_DIGEST_EMPTY, True):
            return None
        written_by = None
        if quiet:
            text = f"Quiet since {since.strftime('%Y-%m-%d %H:%M') if since else 'setup'}."
        else:
            text, written_by = await self._async_generate(summary, ai_task or c.responses.get(CONF_AI_TASK))
        counts = {key: summary[key] for key in ("since", "until", "incident_count", "labels")}
        forced = c.modes.override is not None
        digest = {
            **counts,
            "weight_changes": len(summary["weight_changes"]),
            "counts": fallback_text(summary),
            "house_mode": c.house_mode,
            "forced": forced,
            "forced_since": c.store.override_since if forced else None,
        }
        text = f"{text}\n\n{self._mode_line()}"
        if not preview:
            c.alerts.fire(CATEGORY_DIGEST, "SIEM digest", text, summary=digest)
        return {"message": text, "ai_task_entity": written_by, "summary": digest}

    def _mode_line(self) -> str:
        """Say what mode the house is in, and remind that a mode forced by hand stays until set back to auto."""
        c = self.coordinator
        if c.modes.override is None:
            return f"House mode: {c.house_mode}."
        since = dt_util.parse_datetime(c.store.override_since) if c.store.override_since else None
        local = dt_util.as_local(since) if since else None
        when = f" since {local:%b} {local.day}, {local:%H:%M}" if local else ""
        return f"House mode: {c.house_mode}, set by hand{when}. It stays that way until you set it back to auto."

    async def _async_generate(self, summary: dict[str, Any], entity: str | None) -> tuple[str, str | None]:
        """Return the digest text and the AI task entity that wrote it, or the raw counts and None."""
        if not entity:
            return fallback_text(summary), None
        data = {"task_name": "siem digest", "instructions": INSTRUCTIONS + json.dumps(summary, default=str), "entity_id": entity}
        try:
            async with asyncio.timeout(AI_TASK_TIMEOUT_S):
                result = await self.hass.services.async_call("ai_task", "generate_data", data, blocking=True, return_response=True)
            text = (result or {}).get("data")
            if text:
                return (text.strip() if isinstance(text, str) else json.dumps(text)), entity
        except Exception as err:
            _LOGGER.warning("ai_task digest with %s failed (%s); posting raw counts", entity, err)
        return fallback_text(summary), None
