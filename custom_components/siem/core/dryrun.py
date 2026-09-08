"""Deterrence action plans and their dry-run rendering."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

DRY_RUN_PREFIX = "[DRY RUN]"


@dataclass(frozen=True)
class Action:
    """One Home Assistant service call the responder would make."""

    domain: str
    service: str
    entity_id: str | None = None
    data: Mapping[str, Any] = field(default_factory=dict)

    def render(self) -> str:
        """Render the call as ``domain.service entity key=value``."""
        parts = [f"{self.domain}.{self.service}"]
        if self.entity_id:
            parts.append(self.entity_id)
        parts.extend(f"{k}={v}" for k, v in self.data.items())
        return " ".join(parts)


def room_deter_actions(room_key: str, room: Mapping[str, Any], house: Mapping[str, Any]) -> list[Action]:
    """Build the room deterrence plan: snapshot, lights, volume, sound, script."""
    actions: list[Action] = []
    players = list(room.get("deter_players") or [])
    if players:
        actions.append(Action("scene", "create", None, {"scene_id": f"siem_restore_{room_key}", "snapshot_entities": players}))
    for light in list(room.get("deter_lights") or []) + list(room.get("deter_lights_additional") or []):
        domain = light.split(".", 1)[0]
        actions.append(Action(domain, "turn_on", light, {"brightness_pct": 100} if domain == "light" else {}))
    volume = house.get("deter_volume")
    sound = house.get("deter_sound")
    tts_entity = house.get("deter_tts_entity")
    for player in players:
        if volume is not None:
            actions.append(Action("media_player", "volume_set", player, {"volume_level": volume}))
        if tts_entity:
            actions.append(
                Action("tts", "speak", tts_entity, {"media_player_entity_id": player, "message": house.get("deter_tts_message") or "Intruder detected"})
            )
        elif sound:
            actions.append(Action("media_player", "play_media", player, {"media_content_id": sound, "media_content_type": "music"}))
    if room.get("deter_script"):
        actions.append(Action("script", "turn_on", room["deter_script"]))
    return actions


def restore_actions(room_key: str, room: Mapping[str, Any]) -> list[Action]:
    """Build the plan that puts a room's players back after deterrence."""
    if not room.get("deter_players"):
        return []
    return [Action("scene", "turn_on", f"scene.siem_restore_{room_key}")]


def whole_house_actions(entity_ids: Iterable[str]) -> list[Action]:
    """Turn on whole-house scripts and switches."""
    return [Action(entity_id.split(".", 1)[0], "turn_on", entity_id) for entity_id in entity_ids]


def render_plan(actions: Iterable[Action]) -> list[str]:
    """Render every action, one line each."""
    return [a.render() for a in actions]


def dry_run_message(message: str, actions: Iterable[Action]) -> str:
    """Prefix ``message`` and append the concrete list of skipped actions."""
    lines = render_plan(actions)
    text = f"{DRY_RUN_PREFIX} {message}"
    if lines:
        text += "\nWould have run:\n" + "\n".join(f"- {line}" for line in lines)
    return text
