# Changelog

Changes since the last release. Earlier releases are described on the
[releases page](https://github.com/zacs/ha-siem/releases).

## Unreleased

### Changed

- **`snapshot` on `siem_notification` is now only set when the file exists.**
  The key is left out entirely (not null, not an empty string) when the room
  has no camera, every camera is unavailable, or the capture failed or wrote
  an empty or missing file. Before, an alert could name a snapshot that was
  never written, for example when the room's camera was unavailable, and an
  automation that attached it failed: `notify.mattermost` raised *File does
  not exist* and the whole alert was lost. Read it with
  `trigger.event.data.get('snapshot')`; the blueprints and packages do. With
  debug logging on, SIEM says why an alert has no snapshot.
- **A room can have several cameras.** SIEM skips the unavailable ones and
  tries the rest in the order picked, keeping the first picture actually
  saved. A camera picked before moves into the new list on its own.
- **Breaking: one night.** `binary_sensor.siem_night` now means night for this
  house: with the family home, the bedtime sensor or panel (the night window
  standing in); with only guests home, the night window, which a sensor or
  panel saying bed can start sooner; with nobody home, the night window.
  `binary_sensor.siem_bedtime` is removed, and incidents record `night`
  instead of `bedtime`. Scoring is unchanged with the default points.

### Fixed

- Incident ids are never all digits. Home Assistant templates turned an
  all-digit id into a number, so the escalation blueprint and package missed
  the answer for about one incident in fifty and escalated anyway.
