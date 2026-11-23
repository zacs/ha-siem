"""Load residual baseline."""

from custom_components.siem.core.residual import LoadResidualDetector


def test_sustained_step_fires_once_and_rebaselines():
    detector = LoadResidualDetector(step_watts=100, sustain_minutes=5)
    for t in range(0, 600, 30):
        assert not detector.update(250, 50, t)
    assert detector.baseline == 200
    fired = [detector.update(400, 50, 600 + t) for t in range(0, 301, 30)]
    assert fired.count(True) == 1
    assert fired.index(True) == len(fired) - 1
    assert detector.baseline == 350
    assert not any(detector.update(400, 50, 1000 + t) for t in range(0, 600, 30))


def test_short_blip_does_not_fire():
    detector = LoadResidualDetector(step_watts=100, sustain_minutes=5)
    detector.update(200, 0, 0)
    assert not detector.update(400, 0, 60)
    assert not detector.update(400, 0, 120)
    assert not detector.update(200, 0, 180)
    assert not detector.update(400, 0, 500)
    assert not detector.update(400, 0, 700)
    assert detector.residual == 400


def test_one_out_of_order_reading_is_not_a_step():
    """The charger reports 7 kW a moment before the house meter catches up: one dip, not a new baseline."""
    detector = LoadResidualDetector(step_watts=100, sustain_minutes=5)
    detector.update(1000, 0, 0)
    assert not detector.update(1000, 7000, 30)
    assert detector.baseline == 1000
    assert not any(detector.update(8000, 7000, 60 + t) for t in range(0, 900, 30))
    # Something big really going off moves the baseline down once it has lasted.
    for t in range(0, 331, 30):
        detector.update(400, 0, 1000 + t)
    assert detector.baseline == 400
    assert not detector.update(400, 0, 1400)


def test_automated_loads_are_subtracted():
    detector = LoadResidualDetector(step_watts=100, sustain_minutes=1)
    detector.update(200, 0, 0)
    assert not detector.update(400, 200, 30)
    assert not detector.update(400, 200, 90)
