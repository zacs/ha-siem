"""Snapshots: an alert names a snapshot only when the file is there, so an automation never attaches a missing one."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.exceptions import HomeAssistantError
import pytest

from .conftest import ROOMS, flip, notifications, setup_siem

INCIDENT_ID = "abc1234f"


@pytest.fixture(autouse=True)
def noon(freezer):
    freezer.move_to("2026-10-19 12:00:00-07:00")


@pytest.fixture
def media(hass, tmp_path) -> Path:
    """The snapshot folder, under a media folder of the test's own."""
    hass.config.media_dirs = {"local": str(tmp_path)}
    return tmp_path / "siem"


@pytest.fixture
def debug_log(caplog):
    caplog.set_level(logging.DEBUG, logger="custom_components.siem.alerts")
    return caplog


def cameras(hass, behaviour: dict[str, str]) -> list[str]:
    """Stand in for camera.snapshot; each camera writes a picture, an empty file, nothing at all, or raises.

    "nothing" is what Home Assistant does for a camera that is unavailable: the call returns and no file appears.
    Returns the cameras asked for a snapshot, in order.
    """
    asked: list[str] = []

    async def snapshot(call) -> None:
        camera, path = call.data["entity_id"], Path(call.data["filename"])
        asked.append(camera)
        what = behaviour[camera]
        if what == "raise":
            raise HomeAssistantError("camera offline")
        if what in ("write", "empty"):
            await hass.async_add_executor_job(path.write_bytes, b"\xff\xd8 a picture" if what == "write" else b"")

    hass.services.async_register("camera", "snapshot", snapshot)
    return asked


async def alert_from_the_kitchen(hass, siem_events, camera: str | list[str] | None) -> dict:
    """Load SIEM with the kitchen's cameras, open the back door, and return the verify alert."""
    rooms = {**ROOMS, "kitchen": {**ROOMS["kitchen"], **({"camera": camera} if camera else {})}}
    entry = await setup_siem(hass, rooms=rooms)
    entry.runtime_data.engine._new_id = lambda: INCIDENT_ID
    flip(hass, "binary_sensor.back_door")
    for _ in range(3):
        await hass.async_block_till_done()
    return notifications(siem_events, "verify")[0]


async def test_a_snapshot_is_named_when_the_camera_writes_one(hass, siem_events, media):
    hass.states.async_set("camera.kitchen", "idle")
    asked = cameras(hass, {"camera.kitchen": "write"})
    alert = await alert_from_the_kitchen(hass, siem_events, ["camera.kitchen"])
    assert asked == ["camera.kitchen"]
    assert alert["snapshot"] == str(media / f"{INCIDENT_ID}_verify.jpg")
    assert (media / f"{INCIDENT_ID}_verify.jpg").stat().st_size > 0


async def test_no_snapshot_when_the_camera_is_unavailable(hass, siem_events, media, debug_log):
    hass.states.async_set("camera.kitchen", "unavailable")
    asked = cameras(hass, {"camera.kitchen": "nothing"})
    alert = await alert_from_the_kitchen(hass, siem_events, ["camera.kitchen"])
    assert "snapshot" not in alert
    assert asked == [], "an unavailable camera isn't asked"
    assert f"No snapshot for incident {INCIDENT_ID}: camera.kitchen unavailable" in debug_log.text


async def test_no_snapshot_when_the_capture_raises(hass, siem_events, media, debug_log):
    hass.states.async_set("camera.kitchen", "streaming")
    cameras(hass, {"camera.kitchen": "raise"})
    alert = await alert_from_the_kitchen(hass, siem_events, ["camera.kitchen"])
    assert "snapshot" not in alert
    assert f"Snapshot of camera.kitchen for incident {INCIDENT_ID} failed: camera offline" in debug_log.text


@pytest.mark.parametrize("what", ["nothing", "empty"])
async def test_no_snapshot_when_the_capture_leaves_no_picture(hass, siem_events, media, debug_log, what):
    """The capture returns without error but the file is missing or empty; a stale file from before doesn't count."""
    media.mkdir(parents=True)
    stale = media / f"{INCIDENT_ID}_verify.jpg"
    stale.write_bytes(b"an older picture")
    hass.states.async_set("camera.kitchen", "idle")
    cameras(hass, {"camera.kitchen": what})
    alert = await alert_from_the_kitchen(hass, siem_events, ["camera.kitchen"])
    assert "snapshot" not in alert
    assert f"Snapshot of camera.kitchen for incident {INCIDENT_ID} wrote nothing" in debug_log.text
    if what == "nothing":
        assert not stale.exists()


async def test_no_snapshot_key_for_a_room_without_a_camera(hass, siem_events, media, debug_log):
    alert = await alert_from_the_kitchen(hass, siem_events, None)
    assert "snapshot" not in alert
    assert f"No snapshot for incident {INCIDENT_ID}: its room has no camera" in debug_log.text


async def test_several_cameras_are_tried_until_one_writes_a_picture(hass, siem_events, media):
    for camera, state in (("camera.a", "unavailable"), ("camera.b", "idle"), ("camera.c", "idle"), ("camera.d", "idle"), ("camera.e", "idle")):
        hass.states.async_set(camera, state)
    asked = cameras(hass, {"camera.a": "write", "camera.b": "raise", "camera.c": "nothing", "camera.d": "write", "camera.e": "write"})
    alert = await alert_from_the_kitchen(hass, siem_events, ["camera.a", "camera.b", "camera.c", "camera.d", "camera.e"])
    assert asked == ["camera.b", "camera.c", "camera.d"], "skip the unavailable one, stop at the first picture"
    assert alert["snapshot"] == str(media / f"{INCIDENT_ID}_verify.jpg")


async def test_a_room_camera_picked_before_rooms_took_several(hass, siem_events, media):
    hass.states.async_set("camera.kitchen", "idle")
    cameras(hass, {"camera.kitchen": "write"})
    alert = await alert_from_the_kitchen(hass, siem_events, "camera.kitchen")
    assert alert["snapshot"] == str(media / f"{INCIDENT_ID}_verify.jpg")
