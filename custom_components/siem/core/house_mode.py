"""House mode: family, guest, service or vacant, with an override."""

from __future__ import annotations

from .rules import MODE_FAMILY, MODE_GUEST, MODE_NIGHT, MODE_SERVICE, MODE_VACANT, MODES

FAMILY_LINGER_S = 30 * 60
# A guest's tracker lingers the same half hour as a resident's: Wi-Fi trackers drop out while phones sleep.
GUEST_LINGER_S = FAMILY_LINGER_S
GUEST_AFTER_END_S = 2 * 3600
GUEST_QUIET_S = 60 * 60
GUEST_PREFIX = "Guest:"
SERVICE_PREFIX = "Service:"
MODE_AUTO = "auto"


class HouseModeMachine:
    """Derive the house mode from presence, bedtime, the calendar, guest and service sensors and people being let in.

    Precedence is override, family, guest, service, vacant; family is night
    while the household is in bed (the panel armed night, or the night
    window, as the coordinator decides). Family lingers
    thirty minutes after the last resident leaves. Guest is held while a
    guest's device tracker is home and for thirty minutes after, while a
    Guest calendar event runs or a guest sensor is on, and afterwards until
    two hours past its end and sixty quiet minutes have both elapsed; letting
    someone in (a code at the keypad, an unlock from Home Assistant) starts
    the same clock from the moment of the unlock. Motion does not count as
    activity, so a pet cannot hold guest mode open. Service is held while a
    Service calendar event runs or a service sensor is on, and ends with it.
    The calendar and the sensors add up: either one is enough.
    """

    def __init__(self, now: float) -> None:
        """Start vacant at ``now``."""
        self.override: str | None = None
        self._anyone_home = False
        self._asleep = False
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

    def set_asleep(self, asleep: bool) -> None:
        """Record whether the household is in bed, which turns family into night."""
        self._asleep = asleep

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
        elif mode in MODES:
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
        return self._service_sensor or bool(self._service_window and self._service_window[0] <= now < self._service_window[1])

    def mode(self, now: float) -> str:
        """Return the current house mode."""
        if self.override:
            return self.override
        if self._family(now):
            return MODE_NIGHT if self._asleep else MODE_FAMILY
        if self._guest(now):
            return MODE_GUEST
        if self._service(now):
            return MODE_SERVICE
        return MODE_VACANT
