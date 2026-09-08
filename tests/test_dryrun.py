"""Dry-run action list rendering."""

from custom_components.siem.core.dryrun import (
    Action,
    dry_run_message,
    render_plan,
    restore_actions,
    room_deter_actions,
    whole_house_actions,
)

ROOM = {
    "deter_lights": ["light.kitchen"],
    "deter_players": ["media_player.kitchen"],
    "deter_script": "script.kitchen_siren",
}
HOUSE = {"deter_volume": 0.8, "deter_sound": "media-source://media_source/local/dog.mp3", "restore_seconds": 30}


def test_room_plan_orders_snapshot_lights_volume_sound_script():
    lines = render_plan(room_deter_actions("kitchen", ROOM, HOUSE))
    assert lines == [
        "scene.create scene_id=siem_restore_kitchen snapshot_entities=['media_player.kitchen']",
        "light.turn_on light.kitchen brightness_pct=100",
        "media_player.volume_set media_player.kitchen volume_level=0.8",
        "media_player.play_media media_player.kitchen media_content_id=media-source://media_source/local/dog.mp3 media_content_type=music",
        "script.turn_on script.kitchen_siren",
    ]
    assert render_plan(restore_actions("kitchen", ROOM)) == ["scene.turn_on scene.siem_restore_kitchen"]
    assert restore_actions("den", {}) == []


def test_tts_replaces_media_url():
    house = {**HOUSE, "deter_tts_entity": "tts.piper", "deter_tts_message": "Leave now"}
    lines = render_plan(room_deter_actions("kitchen", ROOM, house))
    assert "tts.speak tts.piper media_player_entity_id=media_player.kitchen message=Leave now" in lines
    assert not any("play_media" in line for line in lines)


def test_whole_house_plan_and_message():
    actions = whole_house_actions(["script.flood_lights", "switch.siren"])
    assert render_plan(actions) == ["script.turn_on script.flood_lights", "switch.turn_on switch.siren"]
    message = dry_run_message("deter in kitchen", actions)
    assert message.startswith("[DRY RUN] deter in kitchen\nWould have run:\n- script.turn_on script.flood_lights")
    assert dry_run_message("nothing", []) == "[DRY RUN] nothing"
    assert Action("light", "turn_on").render() == "light.turn_on"
