"""Arm recommendation per mode and night."""

import pytest

from custom_components.siem.core.arm import ARM_SERVICES, recommend_arm_mode


@pytest.mark.parametrize(
    "mode,night,expected",
    [
        ("vacant", False, "armed_away"),
        ("vacant", True, "armed_away"),
        ("family", False, "disarmed"),
        ("family", True, "armed_night"),
        ("sitter", False, "disarmed"),
        ("sitter", True, "armed_night"),
        ("service", False, "disarmed"),
        ("service", True, "disarmed"),
    ],
)
def test_recommendation(mode, night, expected):
    assert recommend_arm_mode(mode, night) == expected
    assert ARM_SERVICES[expected].startswith("alarm_")


def test_unknown_mode():
    with pytest.raises(ValueError):
        recommend_arm_mode("party", False)
