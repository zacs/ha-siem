"""Incident lifecycle: open, join, close, chains, suppressors, labels."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass, field
import secrets
from typing import Any

from .rules import EngineSettings, Rule, chain_factor
from .scoring import TIER_NONE, Contribution, compute_score, contribution_value, tier_for, tier_rank, top_contributors
from .weights import LABELS, apply_label

EVENT_OPENED = "opened"
EVENT_TIER_CHANGED = "tier_changed"
EVENT_CLOSED = "closed"
INCIDENT_EVENT_TYPES: tuple[str, ...] = (EVENT_OPENED, EVENT_TIER_CHANGED, EVENT_CLOSED)


@dataclass
class Incident:
    """A cluster of correlated events and everything scored against it."""

    id: str
    started: float
    mode: str
    room: str | None = None
    person: str | None = None
    contributions: list[Contribution] = field(default_factory=list)
    timeline: list[dict[str, Any]] = field(default_factory=list)
    last_event: float = 0.0
    closed: float | None = None
    labels: list[str] = field(default_factory=list)
    peak_score: float = 0.0
    tier: str = TIER_NONE
    peak_tier: str = TIER_NONE
    low_since: float | None = None
    notified_score: float | None = None

    def rule_ids(self) -> list[str]:
        """Return the distinct positive rules in this incident, in order."""
        return list(dict.fromkeys(c.rule_id for c in self.contributions if c.points > 0))

    def entity_ids(self) -> list[str]:
        """Return the distinct entities that added points to this incident, in the order they first did."""
        return list(dict.fromkeys(c.entity_id for c in self.contributions if c.points > 0 and c.entity_id))

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly summary for storage and the digest."""
        data = {k: getattr(self, k) for k in ("id", "started", "closed", "mode", "room", "person", "tier", "peak_tier")}
        data.update(labels=list(self.labels), timeline=list(self.timeline), rules=self.rule_ids(), entities=self.entity_ids(), peak_score=round(self.peak_score, 1))
        return data


@dataclass(frozen=True)
class IncidentEvent:
    """A lifecycle transition the adapter publishes on ``event.siem_incident``."""

    kind: str
    incident: Incident
    tier: str
    previous_tier: str = TIER_NONE


class IncidentEngine:
    """Own the current incident and score events against it."""

    def __init__(
        self,
        rules: Mapping[str, Rule],
        settings: EngineSettings,
        weights: MutableMapping[str, float],
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        """Score with ``rules`` and ``weights`` under ``settings``."""
        self.rules = rules
        self.settings = settings
        self.weights = weights
        self._chains = settings.chains()
        self._new_id = id_factory or (lambda: secrets.token_hex(4))
        self.current: Incident | None = None
        self.recent: deque[Incident] = deque(maxlen=20)
        self._pending: list[IncidentEvent] = []
        self._last_publish: tuple[float, float, str] | None = None

    @property
    def last_incident(self) -> Incident | None:
        """Return the open incident, else the most recently closed one."""
        return self.find(None)

    def find(self, incident_id: str | None) -> Incident | None:
        """Return the incident with ``incident_id``, or the last one when None."""
        candidates = ([self.current] if self.current else []) + list(reversed(self.recent))
        return next((i for i in candidates if incident_id is None or i.id == incident_id), None)

    def score(self, now: float) -> float:
        """Return the live score of the open incident, 0 when there is none."""
        if self.current is None:
            return 0.0
        return compute_score(self.current.contributions, self.weights, now, self.settings.half_life_min)

    def top_contributors(self, now: float, limit: int = 5) -> list[dict[str, Any]]:
        """Return the rules driving the current score."""
        if self.current is None:
            return []
        return top_contributors(self.current.contributions, self.weights, now, self.settings.half_life_min, limit)

    def _incident_for(self, now: float, mode: str, room: str | None, allow_open: bool) -> Incident | None:
        current = self.current
        if current is not None:
            if now - current.last_event <= self.settings.join_window_s or self.score(now) >= self.settings.close_below:
                return current
            self._close(current, now)
        if not allow_open:
            return None
        incident = Incident(self._new_id(), now, mode, room, last_event=now)
        self.current = incident
        self._pending.append(IncidentEvent(EVENT_OPENED, incident, TIER_NONE))
        return incident

    def _append(self, incident: Incident, contribution: Contribution, now: float, extend: bool = True) -> None:
        incident.contributions.append(contribution)
        if extend:
            incident.last_event = now
        if len(incident.timeline) < self.settings.timeline_cap:
            incident.timeline.append(contribution.as_dict())

    def add(
        self,
        rule_id: str,
        *,
        mode: str,
        now: float,
        night: bool = False,
        entity_id: str | None = None,
        room: str | None = None,
        detail: str = "",
        points: float | None = None,
        allow_open: bool = True,
    ) -> Contribution | None:
        """Score ``rule_id`` against the open incident, opening one if needed.

        ``points`` overrides the per-mode selection when a caller has already
        shaped them (room corroboration does). Chain multipliers apply when an
        earlier rule of the chain fired inside the chain window. Returns None
        when the rule scores nothing in this mode or no incident may open.
        """
        if rule_id not in self.rules:
            raise ValueError(f"unknown rule {rule_id!r}")
        base = self.rules[rule_id].points_for(mode, night) if points is None else points
        if base <= 0:
            return None
        incident = self._incident_for(now, mode, room, allow_open)
        if incident is None:
            return None
        previous = [
            c.rule_id
            for c in incident.contributions
            if c.points > 0 and c.rule_id != rule_id and now - c.at <= self.settings.chain_window_s
        ]
        factor = chain_factor(self._chains, previous, rule_id)
        contribution = Contribution(rule_id, base * factor, now, entity_id, room, detail, factor)
        self._append(incident, contribution, now)
        if incident.room is None and room:
            incident.room = room
        return contribution

    def suppress(self, rule_id: str, points: float, *, now: float, detail: str = "", person: str | None = None, explain_s: float = 0.0) -> Contribution | None:
        """Apply a negative contribution to the open incident, if any.

        With ``explain_s`` the suppressor is at least as large as everything scored in the ``explain_s`` seconds
        before it: a resident arriving home explains the activity that led up to the arrival.
        """
        incident = self.current
        if incident is None:
            return None
        recent = sum(
            contribution_value(c.points, self.weights.get(c.rule_id, 1.0), now - c.at, self.settings.half_life_min)
            for c in incident.contributions
            if c.points > 0 and now - c.at <= explain_s
        )
        contribution = Contribution(rule_id, -max(abs(points), recent), now, None, None, detail)
        self._append(incident, contribution, now, extend=False)
        if person:
            incident.person = person
        return contribution

    def _close(self, incident: Incident, now: float) -> None:
        incident.closed = now
        self.recent.append(incident)
        self.current = None
        self._pending.append(IncidentEvent(EVENT_CLOSED, incident, incident.tier, incident.tier))

    def evaluate(self, now: float) -> list[IncidentEvent]:
        """Advance time: emit opened/tier/closed events and close stale incidents."""
        events, self._pending = self._pending, []
        incident = self.current
        if incident is None:
            return events
        score = self.score(now)
        incident.peak_score = max(incident.peak_score, score)
        tier = tier_for(score, self.settings.thresholds)
        if tier != incident.tier:
            events.append(IncidentEvent(EVENT_TIER_CHANGED, incident, tier, incident.tier))
            incident.tier = tier
            if tier_rank(tier) > tier_rank(incident.peak_tier):
                incident.peak_tier = tier
        if score < self.settings.close_below:
            if incident.low_since is None:
                incident.low_since = now
            elif now - incident.low_since >= self.settings.close_after_s:
                self._close(incident, now)
                events.extend(self._pending)
                self._pending = []
        else:
            incident.low_since = None
        return events

    def label(self, label: str, incident_id: str | None = None) -> tuple[Incident, dict[str, tuple[float, float]]]:
        """Attach ``label`` to an incident and adjust the weights of its rules."""
        if label not in LABELS:
            raise ValueError(f"unknown label {label!r}")
        incident = self.find(incident_id)
        if incident is None:
            raise LookupError("no incident to label")
        incident.labels.append(label)
        return incident, apply_label(self.weights, incident.rule_ids(), label)

    def should_publish(self, now: float, score: float, tier: str) -> bool:
        """Rate-limit state publishing: tier changes now, else 30 s and 1 point."""
        last = self._last_publish
        if last is not None and tier == last[2] and (now - last[0] < self.settings.publish_interval_s or abs(score - last[1]) < self.settings.publish_delta):
            return False
        self._last_publish = (now, score, tier)
        return True
