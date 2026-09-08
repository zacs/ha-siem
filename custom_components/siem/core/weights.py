"""Per-rule weights and the label adjustments that move them."""

from __future__ import annotations

from collections.abc import Iterable, MutableMapping

DEFAULT_WEIGHT = 1.0
WEIGHT_FLOOR = 0.3
WEIGHT_CAP = 1.5

LABEL_FALSE_ALARM, LABEL_THATS_ME, LABEL_SITTER, LABEL_REAL = "false_alarm", "thats_me", "sitter", "real"
LABELS: tuple[str, ...] = (LABEL_FALSE_ALARM, LABEL_THATS_ME, LABEL_SITTER, LABEL_REAL)
LABEL_FACTORS = {LABEL_FALSE_ALARM: 0.9, LABEL_THATS_ME: 0.9, LABEL_SITTER: 0.9, LABEL_REAL: 1.1}


def weight_for(weights: MutableMapping[str, float] | None, rule_id: str) -> float:
    """Return the weight of ``rule_id``, 1.0 when it was never adjusted."""
    return float((weights or {}).get(rule_id, DEFAULT_WEIGHT))


def apply_label(
    weights: MutableMapping[str, float], rule_ids: Iterable[str], label: str
) -> dict[str, tuple[float, float]]:
    """Multiply every rule in ``rule_ids`` by the label's factor, clamped.

    Returns ``{rule_id: (old, new)}`` for the rules that actually moved so the
    digest can report weight changes.
    """
    if label not in LABEL_FACTORS:
        raise ValueError(f"unknown label {label!r}")
    factor = LABEL_FACTORS[label]
    changes: dict[str, tuple[float, float]] = {}
    for rule_id in dict.fromkeys(rule_ids):
        old = weight_for(weights, rule_id)
        new = round(min(WEIGHT_CAP, max(WEIGHT_FLOOR, old * factor)), 4)
        if new != old:
            weights[rule_id] = new
            changes[rule_id] = (old, new)
    return changes


def reset_weights(weights: MutableMapping[str, float]) -> None:
    """Return every rule to weight 1.0."""
    weights.clear()
