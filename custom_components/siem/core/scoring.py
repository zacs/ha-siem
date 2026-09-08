"""Decay, capping and tiering of contributions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

SCORE_CAP = 100.0
MIN_CONTRIBUTION = 0.5
TIER_NONE, TIER_VERIFY, TIER_DETER, TIER_ALARM = "none", "verify", "deter", "alarm"
TIERS: tuple[str, ...] = (TIER_NONE, TIER_VERIFY, TIER_DETER, TIER_ALARM)


@dataclass
class Contribution:
    """One scored event inside an incident. Negative points are suppressors."""

    rule_id: str
    points: float
    at: float
    entity_id: str | None = None
    room: str | None = None
    detail: str = ""
    multiplier: float = 1.0

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly view for timelines and storage."""
        return {
            "at": self.at,
            "rule": self.rule_id,
            "points": round(self.points, 1),
            "entity_id": self.entity_id,
            "room": self.room,
            "detail": self.detail,
        }


def decay(points: float, age_s: float, half_life_min: float) -> float:
    """Return ``points`` decayed exponentially with the given half-life."""
    if half_life_min <= 0:
        return points
    return points * 0.5 ** (max(age_s, 0.0) / (half_life_min * 60.0))


def contribution_value(points: float, weight: float, age_s: float, half_life_min: float) -> float:
    """Return the live value of a contribution, or 0 once it is below 0.5."""
    value = decay(points * weight, age_s, half_life_min)
    return value if abs(value) >= MIN_CONTRIBUTION else 0.0


def compute_score(
    contributions: Iterable[Contribution], weights: Mapping[str, float], now: float, half_life_min: float
) -> float:
    """Return ``min(100, sum(points * weight * decay))`` floored at zero."""
    total = sum(
        contribution_value(c.points, weights.get(c.rule_id, 1.0), now - c.at, half_life_min) for c in contributions
    )
    return max(0.0, min(SCORE_CAP, total))


def tier_for(score: float, thresholds: Mapping[str, float]) -> str:
    """Return the tier a score falls in."""
    tier = TIER_NONE
    for name in (TIER_VERIFY, TIER_DETER, TIER_ALARM):
        if score >= thresholds[name]:
            tier = name
    return tier


def tier_rank(tier: str) -> int:
    """Return the ordinal of a tier so tiers can be compared."""
    return TIERS.index(tier)


def top_contributors(
    contributions: Iterable[Contribution], weights: Mapping[str, float], now: float, half_life_min: float, limit: int = 5
) -> list[dict[str, Any]]:
    """Return up to ``limit`` rules ranked by their summed live contribution."""
    totals: dict[str, float] = {}
    entities: dict[str, list[str]] = {}
    for c in contributions:
        value = contribution_value(c.points, weights.get(c.rule_id, 1.0), now - c.at, half_life_min)
        if value == 0:
            continue
        totals[c.rule_id] = totals.get(c.rule_id, 0.0) + value
        if c.entity_id and c.entity_id not in entities.setdefault(c.rule_id, []):
            entities[c.rule_id].append(c.entity_id)
    ranked = sorted(totals, key=lambda r: abs(totals[r]), reverse=True)[:limit]
    return [{"rule": r, "points": round(totals[r], 1), "entities": entities.get(r, [])[:3]} for r in ranked]
