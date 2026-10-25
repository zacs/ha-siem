"""Alarm arm recommendation from house mode and the night window."""

from __future__ import annotations

from .rules import MODE_FAMILY, MODE_GUEST, MODE_SERVICE, MODE_VACANT

ARMED_AWAY, ARMED_NIGHT, ARMED_HOME, DISARMED = "armed_away", "armed_night", "armed_home", "disarmed"
ARM_MODES: tuple[str, ...] = (ARMED_AWAY, ARMED_NIGHT, ARMED_HOME, DISARMED)


def recommend_arm_mode(mode: str, night: bool) -> str:
    """Return the alarm mode the house should be in. SIEM only publishes it; it never touches a panel.

    Vacant is always armed away. Family and guest (asleep or not) arm the
    perimeter inside the night window and stay disarmed by day because both
    move around inside. Service stays disarmed: contractors come and go
    through exterior doors. Only the window decides, never the panel itself,
    so an automation that follows this cannot lock a panel in armed night.
    """
    if mode == MODE_VACANT:
        return ARMED_AWAY
    if mode in (MODE_FAMILY, MODE_GUEST):
        return ARMED_NIGHT if night else DISARMED
    if mode == MODE_SERVICE:
        return DISARMED
    raise ValueError(f"unknown house mode {mode!r}")
