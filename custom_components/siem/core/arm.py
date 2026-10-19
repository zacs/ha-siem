"""Alarm arm recommendation from house mode and the night window."""

from __future__ import annotations

from .rules import MODE_FAMILY, MODE_GUEST, MODE_SERVICE, MODE_VACANT

ARMED_AWAY, ARMED_NIGHT, ARMED_HOME, DISARMED = "armed_away", "armed_night", "armed_home", "disarmed"
ARM_MODES: tuple[str, ...] = (ARMED_AWAY, ARMED_NIGHT, ARMED_HOME, DISARMED)

# alarm_control_panel service that reaches each recommendation.
ARM_SERVICES = {
    ARMED_AWAY: "alarm_arm_away",
    ARMED_NIGHT: "alarm_arm_night",
    ARMED_HOME: "alarm_arm_home",
    DISARMED: "alarm_disarm",
}


def recommend_arm_mode(mode: str, night: bool) -> str:
    """Return the alarm mode the house should be in.

    Vacant is always armed away. Family and guest arm the perimeter at
    night and stay disarmed by day because both move around inside. Service
    stays disarmed: contractors come and go through exterior doors.
    """
    if mode == MODE_VACANT:
        return ARMED_AWAY
    if mode in (MODE_FAMILY, MODE_GUEST):
        return ARMED_NIGHT if night else DISARMED
    if mode == MODE_SERVICE:
        return DISARMED
    raise ValueError(f"unknown house mode {mode!r}")
