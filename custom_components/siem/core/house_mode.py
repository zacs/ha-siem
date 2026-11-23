"""House mode: who is home (family, guest, service or vacant), with an override; and whether it is night."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .rules import HOUSE_MODES, MODE_FAMILY, MODE_GUEST, MODE_SERVICE, MODE_VACANT

FAMILY_LINGER_S = 30 * 60
# A guest's tracker lingers the same half hour as a resident's: Wi-Fi trackers drop out while phones sleep.
GUEST_LINGER_S = FAMILY_LINGER_S
GUEST_AFTER_END_S = 2 * 3600
GUEST_QUIET_S = 60 * 60
# Someone let in from outside comes through a door within this long; if no door opens, perhaps nobody came in, and the
# guest clock takes over. Openings soon after the first are the same entry: a door that bounces, or one held for bags.
GUEST_ENTRY_S = 5 * 60
GUEST_SAME_ENTRY_S = 60
# Guests let in from outside are inside until a door opens. Then guest mode holds this long more, and holds on for good
# once someone moves inside: whoever went out has left the doorway by then.
GUEST_LEFT_S = 30 * 60
GUEST_DOORWAY_S = 5 * 60
DOOR_ENTRY, DOOR_EXIT = "entry", "exit"
GUEST_PREFIX = "Guest:"
SERVICE_PREFIX = "Service:"
MODE_AUTO = "auto"


class HouseModeMachine:
    """Derive who is home (the house mode) and whether it is night.

    The house mode is presence only. Precedence is override, family, guest,
    service, vacant. Family lingers thirty minutes after the last resident
    leaves. Guest is held while a guest's device tracker is home and for
    thirty minutes after, while a Guest calendar event runs or a guest sensor
    is on, and afterwards until two hours past its end and sixty quiet
    minutes have both elapsed; with the family home, the clock ends at the two
    hours, since their comings and goings say nothing about guests. Someone
    let in from outside with no resident home (a code at the keypad, a lock
    opened from Home Assistant) is inside once a door opens for them, and
    guest is held until another exterior door opens; then for thirty minutes
    more, and for good if someone moves inside after the doorway. If no door
    opens for them within five minutes, perhaps nobody came in, and the guest
    clock runs from the letting in instead; so it does for any other letting
    in (a garage opened from Home Assistant). A resident coming home ends it.
    Motion does not count as activity for the clock, so a pet cannot hold
    guest mode open. Service is held while a Service calendar event runs or
    a service sensor is on, and ends with it; it never holds inside the night
    window, when nobody works in the house, so the house is vacant then, a
    forced service included. The calendar and the sensors add up: either one
    is enough.

    Night adjusts the house mode, and who is home decides where it comes
    from. With the family home it is the bedtime sources: the panel armed
    night or a bedtime sensor, with the night window standing in when neither
    is picked or one can't tell, as the coordinator decides. With only
    guests home it is the night window, since guests rarely have a bedtime
    sensor or arm the panel; one that says bed only makes it night sooner.
    With nobody home it is the night window. A forced mode says who is home,
    so a forced family or guest still goes to bed.
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
        # Someone let in from outside: whether a door has opened for them yet, when they were let in and came through
        # it, and when a door opened since (perhaps everyone leaving).
        self.guests_inside = False
        self._entered = False
        self._let_in_at: float | None = None
        self._entry_at: float | None = None
        self._door_opened: float | None = None
        # Why guests let in stopped counting, for the coordinator's log.
        self.note: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return what a restart must not forget: whoever was let in, the guest clock, and the lingers."""
        return {
            "guests_inside": self.guests_inside,
            "entered": self._entered,
            "let_in_at": self._let_in_at,
            "entry_at": self._entry_at,
            "door_opened": self._door_opened,
            "guest_end": self._guest_end,
            "last_activity": self._last_activity,
            "last_home_seen": self._last_home_seen,
            "last_guest_seen": self._last_guest_seen,
        }

    def restore(self, data: Mapping[str, Any] | None) -> None:
        """Pick up from :meth:`as_dict` after a restart; what time alone decides is settled when the mode is read."""
        if not data:
            return

        def number(key: str) -> float | None:
            value = data.get(key)
            return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

        self.guests_inside, self._entered = data.get("guests_inside") is True, data.get("entered") is True
        self._let_in_at, self._entry_at, self._door_opened = number("let_in_at"), number("entry_at"), number("door_opened")
        self._guest_end, self._last_home_seen, self._last_guest_seen = number("guest_end"), number("last_home_seen"), number("last_guest_seen")
        if (activity := number("last_activity")) is not None:
            self._last_activity = activity
        if self.guests_inside and not self._entered and self._let_in_at is None:
            # Waiting for a door with no letting in to time it from: nothing to hold on to.
            self.guests_inside = False

    def set_presence(self, anyone_home: bool, now: float) -> None:
        """Record whether any resident or resident tracker is home; a resident coming home ends guests let in."""
        if anyone_home and not self._anyone_home and self.guests_inside:
            # Often it was their own code, the phone a little late; either way the family is home to say who is.
            self._end_latch("a resident came home")
        if anyone_home or self._anyone_home:
            self._last_home_seen = now
        self._anyone_home = anyone_home

    def set_guest_presence(self, anyone_here: bool, now: float) -> None:
        """Record whether any guest's device tracker is home."""
        if anyone_here or self._guest_here:
            self._last_guest_seen = now
        self._guest_here = anyone_here

    def set_in_bed(self, in_bed: bool) -> None:
        """Record whether the bedtime sources say the household is in bed, the night window standing in for them."""
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

    def let_in(self, now: float, *, from_outside: bool = False) -> None:
        """Someone was let in: start (or extend) the guest clock.

        ``from_outside`` is a lock opened for someone outside (a code, or an unlock from Home Assistant). With no
        resident home (a lingering family included: the house-sitter arriving as you drive off), the next door to open
        is them coming in, and from then on they are inside until another door opens, however quiet they are or
        whatever their phone does.
        """
        self._last_activity = now
        self._settle(now)
        if from_outside and not self._anyone_home:
            if not (self.guests_inside and self._entered and self._door_opened is None):
                # Nobody is known to be inside yet: this person still has to come through a door.
                self._entered = False
            self.guests_inside, self._door_opened = True, None
            self._let_in_at, self._entry_at = now, None
            return
        self._guest_end = max(self._guest_end or now, now)

    def door_opened(self, now: float) -> str | None:
        """An exterior door opened while guests let in are inside: someone coming in, or perhaps everyone leaving.

        Return ``entry`` for whoever was let in coming through it, ``exit`` for someone perhaps going out, and None
        when nobody let in is inside.
        """
        self._settle(now)
        if not self.guests_inside:
            return None
        if self._let_in_at is not None and now - self._let_in_at <= GUEST_ENTRY_S and (self._entry_at is None or now - self._entry_at <= GUEST_SAME_ENTRY_S):
            self._entered = True
            if self._entry_at is None:
                self._entry_at = now
            return DOOR_ENTRY
        self._door_opened = now
        return DOOR_EXIT

    def someone_inside(self, now: float) -> bool:
        """Someone moved inside; after a door opened, that means not everyone left. Return True if that settles it.

        Not settled first: a presence sensor that has been on since before the door opened is someone inside all along.
        """
        if self._door_opened is not None and now - self._door_opened >= GUEST_DOORWAY_S:
            self._door_opened = None
            return True
        return False

    def _end_latch(self, why: str) -> None:
        self.guests_inside, self._entered = False, False
        self._let_in_at = self._entry_at = self._door_opened = None
        self.note = why

    def _settle(self, now: float) -> None:
        """Apply what time alone decides: whoever was let in never came in, or went out; the guest clock ran out."""
        if self.guests_inside:
            if not self._entered and self._let_in_at is not None and now - self._let_in_at > GUEST_ENTRY_S:
                # No door opened for them: perhaps nobody came in. The guest clock runs from the letting in.
                self._guest_end = max(self._guest_end or self._let_in_at, self._let_in_at)
                self._end_latch(f"no door opened within {GUEST_ENTRY_S // 60} minutes of the letting in, so the guest clock runs instead")
            elif self._door_opened is not None and now - self._door_opened >= GUEST_LEFT_S:
                self._end_latch(f"nobody moved inside for {GUEST_LEFT_S // 60} minutes after a door opened")
        if self._guest_end is not None and self._anyone_home and now >= self._guest_end + GUEST_AFTER_END_S:
            # With the family home, their comings and goings say nothing about guests: the clock ends at the two hours.
            self._guest_end = None

    @property
    def leaving(self) -> bool:
        """Return True while guests let in may have left: a door opened and nobody has moved inside since."""
        return self.guests_inside and self._door_opened is not None

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
        if self.guests_inside:
            return True
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
        self._settle(now)
        if self.override:
            # A forced service goes by the night window like an automatic one: nobody works in the house at night.
            return MODE_VACANT if self.override == MODE_SERVICE and self._night_window else self.override
        if self._family(now):
            return MODE_FAMILY
        if self._guest(now):
            return MODE_GUEST
        if self._service(now):
            return MODE_SERVICE
        return MODE_VACANT

    def night(self, now: float) -> bool:
        """Return True at night: the family's bedtime sources, guests' or the clock, or the clock in an empty house."""
        mode = self.mode(now)
        if mode == MODE_FAMILY:
            return self._in_bed
        if mode == MODE_GUEST:
            return self._in_bed or self._night_window
        return self._night_window
