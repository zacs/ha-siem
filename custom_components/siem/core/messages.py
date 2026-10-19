"""Plain-text notification titles and bodies, shared by every notify service."""

from __future__ import annotations

from collections.abc import Iterable

from .dryrun import DRY_RUN_PREFIX

TIMELINE_LINES = 5


def timeline_line(time_text: str, name: str, description: str | None, points: float) -> str:
    """Render one scored event, e.g. ``14:02 Back Door: An exterior door or window opened (+40)``."""
    return f"{time_text} {name}: {description} ({points:+.0f})" if description else f"{time_text} {name} ({points:+.0f})"


def alert_title(level: str, room: str | None) -> str:
    """Return the title for an incident alert at ``level`` (verify, deter or alarm)."""
    return f"SIEM {level}: {room or 'the house'}"


def alert_message(score: float, mode: str, lines: Iterable[str], *, again: bool = False, actions: Iterable[str] = (), dry_run: bool = False) -> str:
    """Return the body of an incident alert: score, house mode, the latest events and the actions."""
    head = f"Score {score:.0f}, house {mode}" + (", score doubled since the last alert." if again else ".")
    body = [head, *list(lines)[-TIMELINE_LINES:]]
    actions = list(actions)
    if actions:
        body.append("Would have run:" if dry_run else "Running:")
        body.extend(f"- {action}" for action in actions)
    text = "\n".join(body)
    return f"{DRY_RUN_PREFIX} {text}" if dry_run else text
