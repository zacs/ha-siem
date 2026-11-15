# Changelog

Changes in each release, newest first. Releases before 0.0.5 are described on
the [releases page](https://github.com/zacs/ha-siem/releases).

## Unreleased

### Changed

- **Someone let in is inside until they go out.** With the family away, a
  code typed at the keypad, or Home Assistant unlocking a lock, now holds
  guest mode until an exterior door opens other than to let them in. Then it
  holds for 30 minutes more, and for good if someone moves inside after the
  first five. Guests' phones dropping off the Wi-Fi, a quiet day and the
  night no longer end it. Before, a code started the guest clock: two hours,
  and an hour of quiet. A garage door, gate or door cover opened from Home
  Assistant, or a code with the family home, still starts the clock.

### Added

- **Do people leave through the garage door?** A whole-house setting, off by
  default. When it's on, the garage door opening counts like any exterior
  door when SIEM works out whether guests have gone out. Leave it off for a
  detached garage.

## 0.0.5

### Changed

- **`snapshot` on `siem_notification` is now only set when the file exists.**
  Otherwise it is null, as it always was for a room without a camera: when
  every camera is unavailable, or the capture failed or left the file missing
  or empty. Before, an alert could name a snapshot that was never written,
  for example when the room's camera was unavailable, and an automation that
  attached it failed: `notify.mattermost` raised *File does not exist* and the
  whole alert was lost. With debug logging on, SIEM says why an alert has no
  snapshot.
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
