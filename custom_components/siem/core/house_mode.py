"""House mode: who is home (family, guest, service or vacant), with an override; and whether they are in bed."""

from __future__ import annotations

from .rules import HOUSE_MODES, MODE_FAMILY, MODE_GUEST, MODE_SERVICE, MODE_VACANT

FAMILY_LINGER_S = 30 * 60
# A guest's tracker lingers the same half hour as a resident's: Wi-Fi trackers drop out while phones sleep.
GUEST_LINGER_S = FAMILY_LINGER_S
GUEST_AFTER_END_S = 2 * 3600
GUEST_QUIET_S = 60 * 60
GUEST_PREFIX = "Guest:"
SERVICE_PREFIX = "Service:"
MODE_AUTO = "auto"


class HouseModeMachine:
    """Derive who is home (the house mode) and whether they are in bed (bedtime).

    The house mode is presence only. Precedence is override, family, guest,
    service, vacant. Family lingers thirty minutes after the last resident
    leaves. Guest is held while a guest's device tracker is home and for
    thirty minutes after, while a Guest calendar event runs or a guest sensor
    is on, and afterwards until two hours past its end and sixty quiet
    minutes have both elapsed; letting someone in (a code at the keypad, an
    unlock from Home Assistant) starts the same clock from the moment of the
    unlock. Motion does not count as activity, so a pet cannot hold guest
    mode open. Service is held while a Service calendar event runs or a
    service sensor is on, and ends with it; it never holds inside the night
    window, when nobody works in the house, so the house is vacant then. The
    calendar and the sensors add up: either one is enough.

    Bedtime adjusts the family and guest modes: anyone home and in bed. With
    the family home it follows the bedtime sources (the panel armed night, a
    bedtime sensor, or the night window standing in, as the coordinator
    decides); with only guests home the night window counts as well, since
    nothing says when guests go to bed. A forced mode says who is home, so a
    forced family or guest still goes to bed.
    """

    def __init__(self, now: float) -> None:
        """Start vacant at ``now``."""
        self.override: str | None = None
        self._anyone_home = False
        self._in_bed = False
        self._night_window = False
        self._last_home_seen: float | None = None
        self._guest_here = False
        self._last_guest_seen: float | None = None
        self._guest_window: tuple[float, float] | None = None
        self._guest_end: float | None = None
        self._service_window: tuple[float, float] | None = None
        self._guest_sensor = False
        self._service_sensor = False
        self._last_activity = now

    def set_presence(self, anyone_home: bool, now: float) -> None:
        """Record whether any resident or resident tracker is home."""
        if anyone_home or self._anyone_home:
            self._last_home_seen = now
        self._anyone_home = anyone_home

    def set_guest_presence(self, anyone_here: bool, now: float) -> None:
        """Record whether any guest's device tracker is home."""
        if anyone_here or self._guest_here:
            self._last_guest_seen = now
        self._guest_here = anyone_here

    def set_bedtime_sources(self, in_bed: bool) -> None:
        """Record whether the bedtime sources say the household is in bed."""
        self._in_bed = in_bed

    def set_night_window(self, inside: bool) -> None:
        """Record whether the clock is inside the night window."""
        self._night_window = inside

    def note_activity(self, now: float) -> None:
        """Record something only a person does (a door, a switch, a tap), which keeps guest mode alive."""
        self._last_activity = now

    def set_calendar_event(self, summary: str | None, start: float, end: float) -> str | None:
        """Apply the active calendar event; return the mode it selects, if any."""
        summary = (summary or "").strip().casefold()
        if summary.startswith(GUEST_PREFIX.casefold()):
            self._guest_window = (start, end)
            self._guest_end = max(self._guest_end or end, end)
            return MODE_GUEST
        if summary.startswith(SERVICE_PREFIX.casefold()):
            self._service_window = (start, end)
            return MODE_SERVICE
        return None

    def clear_calendar_event(self) -> None:
        """Forget the running calendar event; the guest clock keeps running."""
        self._guest_window = None
        self._service_window = None

    def set_mode_sensors(self, guest: bool, service: bool, now: float) -> None:
        """Record whether any guest or service sensor is on; a guest sensor turning off starts the guest clock."""
        if self._guest_sensor and not guest:
            self._guest_end = max(self._guest_end or now, now)
        self._guest_sensor = guest
        self._service_sensor = service

    def let_in(self, now: float) -> None:
        """Someone was let in, with a code or from Home Assistant: start (or extend) the guest clock."""
        self._guest_end = max(self._guest_end or now, now)
        self._last_activity = now

    def set_override(self, mode: str | None) -> None:
        """Force ``mode``; ``None`` or ``auto`` returns to automatic."""
        if mode in (None, MODE_AUTO):
            self.override = None
        elif mode in HOUSE_MODES:
            self.override = mode
        else:
            raise ValueError(f"unknown house mode {mode!r}")

    def _family(self, now: float) -> bool:
        if self._anyone_home:
            return True
        return self._last_home_seen is not None and now - self._last_home_seen < FAMILY_LINGER_S

    def _guest(self, now: float) -> bool:
        if self._guest_here or (self._last_guest_seen is not None and now - self._last_guest_seen < GUEST_LINGER_S):
            return True
        if self._guest_sensor or (self._guest_window and self._guest_window[0] <= now < self._guest_window[1]):
            return True
        if self._guest_end is None:
            return False
        if now < self._guest_end + GUEST_AFTER_END_S or now - self._last_activity < GUEST_QUIET_S:
            return True
        self._guest_end = None
        return False

    def _service(self, now: float) -> bool:
        if self._night_window:
            return False
        return self._service_sensor or bool(self._service_window and self._service_window[0] <= now < self._service_window[1])

    def mode(self, now: float) -> str:
        """Return the current house mode."""
        if self.override:
            return self.override
        if self._family(now):
            return MODE_FAMILY
        if self._guest(now):
            return MODE_GUEST
        if self._service(now):
            return MODE_SERVICE
        return MODE_VACANT

    def bedtime(self, now: float) -> bool:
        """Return True while anyone home is in bed: the family by the bedtime sources, guests by those or the clock."""
        mode = self.mode(now)
        if mode == MODE_FAMILY:
            return self._in_bed
        if mode == MODE_GUEST:
            return self._in_bed or self._night_window
        return False
