"""Weight adjustment floor and cap."""

import pytest

from custom_components.siem.core.weights import apply_label, reset_weights, weight_for


def test_floor_and_cap():
    weights = {}
    for _ in range(40):
        apply_label(weights, ["a"], "false_alarm")
    assert weights["a"] == 0.3
    for _ in range(40):
        apply_label(weights, ["a"], "real")
    assert weights["a"] == 1.5


def test_each_label_moves_every_rule_once():
    weights = {}
    changes = apply_label(weights, ["a", "b", "a"], "thats_me")
    assert changes == {"a": (1.0, 0.9), "b": (1.0, 0.9)}
    assert apply_label(weights, ["a"], "sitter") == {"a": (0.9, 0.81)}
    assert weight_for(weights, "zzz") == 1.0
    reset_weights(weights)
    assert weights == {}
    with pytest.raises(ValueError):
        apply_label(weights, ["a"], "meh")
