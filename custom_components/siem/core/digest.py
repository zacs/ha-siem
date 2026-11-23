"""Digest scheduling and window summaries."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, time, timedelta
from typing import Any


def parse_times(times: Iterable[str]) -> list[time]:
    """Parse ``HH:MM`` strings, rejecting anything else."""
    parsed: list[time] = []
    for raw in times:
        text = str(raw).strip()
        try:
            hour, minute = (int(p) for p in text.split(":", 1))
            parsed.append(time(hour, minute))
        except (TypeError, ValueError) as err:
            raise ValueError(f"invalid digest time {raw!r}") from err
    return sorted(set(parsed))


def scheduled_between(times: Iterable[str], start: datetime, end: datetime) -> list[datetime]:
    """Return the scheduled instants ``t`` with ``start < t <= end``."""
    slots = parse_times(times)
    if not slots or end <= start:
        return []
    due: list[datetime] = []
    day = start.date()
    while day <= end.date():
        for slot in slots:
            candidate = datetime.combine(day, slot, tzinfo=start.tzinfo)
            if start < candidate <= end:
                due.append(candidate)
        day += timedelta(days=1)
    return due


def is_due(times: Iterable[str], last_run: datetime | None, now: datetime) -> bool:
    """Return True when a digest time passed since ``last_run``.

    A restart does not lose the window: ``last_run`` is persisted, so a time
    that passed while Home Assistant was down is caught up on the next tick.
    With no ``last_run`` at all nothing is due; the caller seeds it.
    """
    if last_run is None:
        return False
    return bool(scheduled_between(times, last_run, now))


def summarize_window(
    incidents: Iterable[Mapping[str, Any]],
    weight_changes: Iterable[Mapping[str, Any]],
    since: datetime | None,
    until: datetime,
) -> dict[str, Any]:
    """Collect incidents, labels and weight changes inside the window as JSON-ready data.

    An incident belongs to the window it ended in, or, still open, the one it started in: one that was open at the
    last digest comes back in the next with how it ended.
    """
    since_ts = since.timestamp() if since else 0.0
    until_ts = until.timestamp()
    window_incidents = [i for i in incidents if since_ts < float(i.get("closed") or i.get("started") or 0) <= until_ts]
    changes = [c for c in weight_changes if since_ts < float(c.get("at", 0)) <= until_ts]
    return {
        "since": since.isoformat() if since else None,
        "until": until.isoformat(),
        "incident_count": len(window_incidents),
        "incidents": window_incidents,
        "labels": {i["id"]: i.get("labels", []) for i in window_incidents if i.get("labels")},
        "weight_changes": changes,
    }


def fallback_text(summary: Mapping[str, Any]) -> str:
    """Raw counts for when the AI task fails."""
    tiers: dict[str, int] = {}
    for incident in summary.get("incidents", []):
        tier = incident.get("peak_tier") or incident.get("tier") or "none"
        tiers[tier] = tiers.get(tier, 0) + 1
    parts = ", ".join(f"{count} {tier}" for tier, count in sorted(tiers.items())) or "no incidents"
    return f"{_count(summary.get('incident_count', 0), 'incident')} ({parts}), {_count(len(summary.get('weight_changes', [])), 'weight change')}"


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 else "s")
