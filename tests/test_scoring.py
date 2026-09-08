"""Decay, cap and tiers."""

from custom_components.siem.core.scoring import Contribution, compute_score, decay, tier_for, top_contributors

THRESHOLDS = {"verify": 20, "deter": 50, "alarm": 80}


def test_decay_halves_every_half_life():
    assert decay(40, 0, 15) == 40
    assert decay(40, 15 * 60, 15) == 20
    assert decay(40, 30 * 60, 15) == 10


def test_score_is_capped_at_100_and_floored_at_0():
    contributions = [Contribution("a", 70, 0), Contribution("b", 70, 0)]
    assert compute_score(contributions, {}, 0, 15) == 100
    assert compute_score([Contribution("s", -30, 0)], {}, 0, 15) == 0


def test_contributions_under_half_a_point_are_dropped():
    contributions = [Contribution("a", 0.6, 0)]
    assert compute_score(contributions, {}, 0, 15) == 0.6
    assert compute_score(contributions, {}, 15 * 60, 15) == 0


def test_weights_scale_points():
    assert compute_score([Contribution("a", 40, 0)], {"a": 0.5}, 0, 15) == 20


def test_tiers():
    assert tier_for(0, THRESHOLDS) == "none"
    assert tier_for(20, THRESHOLDS) == "verify"
    assert tier_for(79.9, THRESHOLDS) == "deter"
    assert tier_for(80, THRESHOLDS) == "alarm"


def test_top_contributors_rank_and_cap():
    contributions = [Contribution(f"r{i}", 10 + i, 0, entity_id=f"e{i}") for i in range(7)]
    top = top_contributors(contributions, {}, 0, 15, limit=5)
    assert [t["rule"] for t in top] == ["r6", "r5", "r4", "r3", "r2"]
    assert top[0]["entities"] == ["e6"]
