"""Rule definitions, per-mode points, night multiplier and validation."""

import pytest

from custom_components.siem.core.rules import (
    DEFAULT_CHAINS,
    DEFAULT_RULES,
    MODES,
    TAG_EXTERIOR,
    EngineSettings,
    RuleConfigError,
    chain_factor,
    validate_rule_config,
    validate_settings,
)


def test_default_points_follow_the_design_table():
    assert DEFAULT_RULES["exterior_door_opened"].points == {"vacant": 40, "guest": 5, "service": 5, "family": 0}
    assert DEFAULT_RULES["pin_not_allowed"].points == {"vacant": 30, "guest": 30, "service": 30, "family": 20}
    assert "untrusted_user" not in DEFAULT_RULES
    assert DEFAULT_RULES["person_exterior_camera"].points["family"] == 2
    assert len(DEFAULT_RULES) == 16


@pytest.mark.parametrize("mode,expected", [("vacant", 40), ("guest", 5), ("service", 5), ("family", 0)])
def test_per_mode_point_selection(mode, expected):
    assert DEFAULT_RULES["exterior_door_opened"].points_for(mode) == expected


def test_night_multiplies_exterior_only():
    exterior = DEFAULT_RULES["exterior_door_opened"]
    interior = DEFAULT_RULES["interior_occupied"]
    perimeter = DEFAULT_RULES["manual_unlock"]
    assert exterior.tag == TAG_EXTERIOR
    assert exterior.points_for("vacant", night=True) == 60
    assert interior.points_for("vacant", night=True) == 50
    assert perimeter.points_for("vacant", night=True) == 60
    assert DEFAULT_RULES["person_exterior_camera"].points_for("family", night=True) == 3


def test_validation_merges_overrides():
    rules = validate_rule_config({"gate_opened": {"points": {"vacant": 10, "guest": 1, "service": 1, "family": 0}}})
    assert rules["gate_opened"].points_for("vacant") == 10
    assert rules["gate_opened"].tag == DEFAULT_RULES["gate_opened"].tag
    assert rules["exterior_door_opened"] is DEFAULT_RULES["exterior_door_opened"]


def test_validation_rejects_unknown_modes():
    with pytest.raises(RuleConfigError, match="unknown modes"):
        validate_rule_config({"gate_opened": {"points": {**dict.fromkeys(MODES, 1), "party": 5}}})


def test_validation_rejects_missing_points():
    with pytest.raises(RuleConfigError, match="missing points"):
        validate_rule_config({"gate_opened": {"points": {"vacant": 10}}})
    with pytest.raises(RuleConfigError, match="no points"):
        validate_rule_config({"gate_opened": {}})


def test_validation_rejects_unknown_rules_and_bad_numbers():
    with pytest.raises(RuleConfigError, match="unknown rule"):
        validate_rule_config({"nope": {"points": dict.fromkeys(MODES, 1)}})
    with pytest.raises(RuleConfigError, match="must be a number"):
        validate_rule_config({"gate_opened": {"points": {**dict.fromkeys(MODES, 1), "vacant": "x"}}})
    with pytest.raises(RuleConfigError, match="negative"):
        validate_rule_config({"gate_opened": {"points": {**dict.fromkeys(MODES, 1), "vacant": -1}}})


def test_chain_factor_picks_strongest_match():
    assert chain_factor(DEFAULT_CHAINS, ["exterior_door_opened"], "interior_occupied") == 1.5
    assert chain_factor(DEFAULT_CHAINS, ["manual_unlock"], "interior_occupied") == 2.0
    assert chain_factor(DEFAULT_CHAINS, ["gate_opened"], "interior_occupied") == 1.0
    assert chain_factor(DEFAULT_CHAINS, [], "interior_occupied") == 1.0


def test_settings_validation():
    settings = validate_settings({"half_life_min": 10, "verify": 15, "manual_unlock_then_any": 3})
    assert settings.half_life_min == 10
    assert settings.thresholds["verify"] == 15
    assert settings.chains()[-1].factor == 3
    assert EngineSettings().thresholds == {"verify": 20, "deter": 50, "alarm": 80}
    with pytest.raises(RuleConfigError, match="increase"):
        validate_settings({"verify": 90})
