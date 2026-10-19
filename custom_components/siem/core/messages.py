"""Plain-text alert titles and bodies, carried on every siem_notification event."""

from __future__ import annotations

from collections.abc import Iterable

TIMELINE_LINES = 5


def timeline_line(time_text: str, name: str, description: str | None, points: float) -> str:
    """Render one scored event, e.g. ``14:02 Back Door: An exterior door or window opened (+40)``."""
    return f"{time_text} {name}: {description} ({points:+.0f})" if description else f"{time_text} {name} ({points:+.0f})"


def alert_title(level: str, room: str | None) -> str:
    """Return the title for an incident alert at ``level`` (verify, deter or alarm)."""
    return f"SIEM {level}: {room or 'the house'}"


def alert_message(score: float, mode: str, lines: Iterable[str], *, again: bool = False) -> str:
    """Return the body of an incident alert: score, house mode and the latest events."""
    head = f"Score {score:.0f}, house {mode}" + (", score doubled since the last alert." if again else ".")
    return "\n".join([head, *list(lines)[-TIMELINE_LINES:]])
