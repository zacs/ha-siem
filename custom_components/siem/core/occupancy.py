"""Room corroboration for occupancy sources."""

from __future__ import annotations

from dataclasses import dataclass, field

STRENGTH_STRONG, STRENGTH_MEDIUM, STRENGTH_WEAK = "strong", "medium", "weak"
STRENGTHS: tuple[str, ...] = (STRENGTH_WEAK, STRENGTH_MEDIUM, STRENGTH_STRONG)
STRENGTH_MULTIPLIER = {STRENGTH_STRONG: 1.0, STRENGTH_MEDIUM: 0.6, STRENGTH_WEAK: 0.3}
CORROBORATION_FACTOR = 1.3


@dataclass(frozen=True)
class OccupancyResult:
    """What one occupancy observation adds to its room's current window."""

    points: float
    strength: str
    corroborated: bool
    weak_alone: bool


@dataclass
class _Window:
    started: float = 0.0
    observations: list[tuple[str, str, float]] = field(default_factory=list)
    credited: float = 0.0


class RoomOccupancy:
    """Track occupancy sources per room over a sliding window.

    A window opens on the first observation and lasts ``window_s``. Within
    it the room is credited once, at the level of its strongest source; a
    stronger source later tops the credit up rather than adding a second full
    contribution. Two distinct sources inside the corroboration interval
    multiply the credit by 1.3. Continuous occupancy re-credits every window.
    """

    def __init__(self, window_s: float = 300.0, corroboration_s: float = 60.0) -> None:
        """Use a ``window_s`` dedupe window and ``corroboration_s`` pairing interval."""
        self._window_s = window_s
        self._corroboration_s = corroboration_s
        self._rooms: dict[str, _Window] = {}

    def observe(self, room: str, entity_id: str, strength: str, now: float, base_points: float) -> OccupancyResult:
        """Record ``entity_id`` firing in ``room`` and return the points to credit now."""
        if strength not in STRENGTH_MULTIPLIER:
            raise ValueError(f"unknown strength {strength!r}")
        window = self._rooms.setdefault(room, _Window(now))
        if not window.observations or now - window.started > self._window_s:
            window.started, window.observations, window.credited = now, [], 0.0
        window.observations.append((entity_id, strength, now))
        strongest = max((o[1] for o in window.observations), key=STRENGTHS.index)
        recent = {o[0] for o in window.observations if now - o[2] <= self._corroboration_s}
        corroborated = len(recent) >= 2
        target = base_points * STRENGTH_MULTIPLIER[strongest] * (CORROBORATION_FACTOR if corroborated else 1.0)
        points = max(0.0, target - window.credited)
        window.credited = max(window.credited, target)
        return OccupancyResult(points, strongest, corroborated, strongest == STRENGTH_WEAK)

    def reset(self, room: str | None = None) -> None:
        """Forget the windows of one room, or of every room."""
        if room is None:
            self._rooms.clear()
        else:
            self._rooms.pop(room, None)
