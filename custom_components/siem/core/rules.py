"""Rule definitions, per-mode point selection, chains and config validation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

MODE_VACANT, MODE_GUEST, MODE_SERVICE, MODE_FAMILY = "vacant", "guest", "service", "family"
MODES: tuple[str, ...] = (MODE_VACANT, MODE_GUEST, MODE_SERVICE, MODE_FAMILY)
TAG_EXTERIOR, TAG_INTERIOR, TAG_PERIMETER, TAG_TAMPER = "exterior", "interior", "perimeter", "tamper"

NIGHT_MULTIPLIER = 1.5


@dataclass(frozen=True)
class Rule:
    """A scoring rule: what it is called, what it is tagged, points per mode."""

    id: str
    tag: str
    points: Mapping[str, float]
    description: str = ""

    def points_for(self, mode: str, night: bool = False) -> float:
        """Return the points this rule scores in ``mode``; night only amplifies exterior rules."""
        base = float(self.points[mode])
        if night and self.tag == TAG_EXTERIOR:
            base *= NIGHT_MULTIPLIER
        return base


def _rule(rule_id: str, tag: str, pts: tuple[float, ...], description: str) -> Rule:
    return Rule(rule_id, tag, dict(zip(MODES, pts, strict=True)), description)


DEFAULT_RULES: dict[str, Rule] = {
    r.id: r
    for r in (
        # Points are (vacant, guest, service, family). With anyone trusted at home, SIEM stays quiet about what happens
        # in the house, which is what the house is for, and only speaks up about lock trouble.
        _rule("exterior_door_opened", TAG_EXTERIOR, (40, 0, 0, 0), "An exterior door or window opened"),
        _rule("gate_opened", TAG_EXTERIOR, (30, 0, 0, 0), "A gate opened"),
        _rule("door_csi_motion", TAG_EXTERIOR, (5, 0, 0, 0), "Someone was at a door that did not open"),
        _rule("exterior_occupied", TAG_EXTERIOR, (10, 0, 0, 0), "Someone is outside"),
        _rule("interior_occupied", TAG_INTERIOR, (50, 0, 0, 0), "Someone is in a room"),
        _rule("interior_door_opened", TAG_INTERIOR, (40, 0, 0, 0), "A fridge, cabinet, drawer or closet opened"),
        _rule("light_physical", TAG_INTERIOR, (45, 0, 0, 0), "A light was turned on at the switch"),
        _rule("appliance_on", TAG_INTERIOR, (35, 0, 0, 0), "An appliance turned on"),
        _rule("water_flow", TAG_INTERIOR, (30, 0, 0, 0), "Water is running"),
        _rule("load_residual", TAG_INTERIOR, (10, 0, 0, 0), "The house is drawing power nothing explains"),
        _rule("manual_unlock", TAG_PERIMETER, (60, 0, 0, 0), "A lock was unlocked by hand"),
        _rule("pin_not_allowed", TAG_PERIMETER, (30, 30, 30, 20), "A lock was unlocked with a code that is disabled"),
        _rule("keypad_lockout", TAG_PERIMETER, (40, 40, 40, 30), "A keypad locked out after bad codes"),
        _rule("sensor_offline", TAG_TAMPER, (20, 0, 0, 0), "A sensor went offline"),
    )
}

SUPPRESSOR_FAMILY_ARRIVAL = -60.0
SUPPRESSOR_LET_IN = -40.0
SUPPRESSOR_DESCRIPTIONS = {"family_arrival": "A resident arrived home", "let_in": "Someone was let in, with a code or from Home Assistant"}


def describe(rules: Mapping[str, Rule], rule_id: str) -> str:
    """Return the plain description of a rule or suppressor."""
    rule = rules.get(rule_id)
    return rule.description if rule else SUPPRESSOR_DESCRIPTIONS.get(rule_id, rule_id)


@dataclass(frozen=True)
class Chain:
    """A pair of rules that, fired in order within a window, amplify the second."""

    id: str
    first: frozenset[str]
    second: frozenset[str] | None
    factor: float

    def matches(self, previous: Iterable[str], rule_id: str) -> bool:
        """Return True when ``rule_id`` follows one of ``previous`` in this chain."""
        if self.second is not None and rule_id not in self.second:
            return False
        return any(p in self.first for p in previous)


DEFAULT_CHAINS: tuple[Chain, ...] = (
    Chain("entry_then_occupied", frozenset({"exterior_door_opened", "door_csi_motion"}), frozenset({"interior_occupied"}), 1.5),
    Chain("gate_then_entry", frozenset({"gate_opened"}), frozenset({"exterior_door_opened", "door_csi_motion"}), 1.5),
    Chain("occupied_then_activity", frozenset({"interior_occupied"}), frozenset({"light_physical", "appliance_on", "interior_door_opened"}), 1.5),
    Chain("manual_unlock_then_any", frozenset({"manual_unlock"}), None, 2.0),
)


def chain_factor(chains: Iterable[Chain], previous: Iterable[str], rule_id: str) -> float:
    """Return the strongest chain multiplier for ``rule_id`` given earlier rules."""
    previous = list(previous)
    return max((c.factor for c in chains if c.matches(previous, rule_id)), default=1.0)


@dataclass
class EngineSettings:
    """Tunables of the scoring engine. Half-life, thresholds and chain factors can be changed in the options flow."""

    half_life_min: float = 15.0
    thresholds: dict[str, float] = field(default_factory=lambda: {"verify": 20.0, "deter": 50.0, "alarm": 80.0})
    chain_factors: dict[str, float] = field(default_factory=lambda: {c.id: c.factor for c in DEFAULT_CHAINS})
    chain_window_s: float = 300.0
    join_window_s: float = 300.0
    close_after_s: float = 1800.0
    close_below: float = 5.0
    timeline_cap: int = 10
    publish_interval_s: float = 30.0
    publish_delta: float = 1.0

    def chains(self) -> tuple[Chain, ...]:
        """Return the default chains with this settings' factors applied."""
        return tuple(Chain(c.id, c.first, c.second, float(self.chain_factors.get(c.id, c.factor))) for c in DEFAULT_CHAINS)


class RuleConfigError(ValueError):
    """Raised when a rule or engine configuration is not usable."""


def _number(value: Any, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuleConfigError(f"{what} must be a number, got {value!r}")
    if value < 0:
        raise RuleConfigError(f"{what} must not be negative")
    return float(value)


def validate_rule_config(config: Mapping[str, Mapping[str, Any]] | None, base: Mapping[str, Rule] = DEFAULT_RULES) -> dict[str, Rule]:
    """Merge point overrides ``{rule_id: {"points": {mode: pts}}}`` onto ``base``.

    Unknown rules and modes are rejected, and every override must carry a
    value for every mode so a half-edited rule cannot silently score zero.
    """
    rules = dict(base)
    for rule_id, entry in (config or {}).items():
        if rule_id not in base:
            raise RuleConfigError(f"unknown rule {rule_id!r}")
        points = entry.get("points") if isinstance(entry, Mapping) else None
        if not isinstance(points, Mapping):
            raise RuleConfigError(f"rule {rule_id!r} has no points")
        if unknown := set(points) - set(MODES):
            raise RuleConfigError(f"rule {rule_id!r} has unknown modes {sorted(unknown)}")
        if missing := set(MODES) - set(points):
            raise RuleConfigError(f"rule {rule_id!r} is missing points for {sorted(missing)}")
        merged = {mode: _number(points[mode], f"{rule_id}.{mode}") for mode in MODES}
        rules[rule_id] = Rule(rule_id, base[rule_id].tag, merged, base[rule_id].description)
    return rules


def validate_settings(config: Mapping[str, Any] | None) -> EngineSettings:
    """Build :class:`EngineSettings` from a stored options mapping."""
    settings = EngineSettings()
    config = config or {}
    if "half_life_min" in config:
        settings.half_life_min = _number(config["half_life_min"], "half_life_min") or settings.half_life_min
    for tier in ("verify", "deter", "alarm"):
        if tier in config:
            settings.thresholds[tier] = _number(config[tier], tier)
    if list(settings.thresholds.values()) != sorted(settings.thresholds.values()):
        raise RuleConfigError("thresholds must increase from verify to alarm")
    for chain in DEFAULT_CHAINS:
        if chain.id in config:
            settings.chain_factors[chain.id] = _number(config[chain.id], chain.id)
    return settings
