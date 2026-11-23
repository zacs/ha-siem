# Changelog

Changes in each release, newest first. Releases before 0.0.5 are described on
the [releases page](https://github.com/zacs/ha-siem/releases).

## Unreleased

### Changed

- **Someone let in is inside until they go out.** With no resident home, a
  code typed at the keypad, or Home Assistant unlocking a lock, followed by a
  door opening for them, now holds guest mode until another exterior door
  opens. Then it holds for 30 minutes more, and for good if someone moves
  inside after the first five. Guests' phones dropping off the Wi-Fi, a quiet
  day, the night and a restart no longer end it; a resident coming home does.
  Only the first door to open is them coming in, so a visit of a minute and a
  half ends it too. A letting in with no door opening for five minutes, a
  garage door, gate or door cover opened from Home Assistant, and a code with
  the family home start the guest clock, as before: two hours, and an hour of
  quiet.
- **A phone rejoining the Wi-Fi no longer cancels an open incident.** Every
  tracker at home still counts for who is home, straight away; only taking
  the points off waits for a real arrival. That needs the tracker to have
  been away for ten minutes and not be back from unavailable, a resident's
  person entity to have left too, and, for a guest's phone, nobody let in
  with a code inside. Before, any phone rejoining took at least 60 points off
  the open incident and made the doors the household's for ten minutes, even
  at 3 a.m. while its owner slept inside.
- **Someone lingering outside builds to a verify by day too.** Outside is
  credited every ten minutes instead of fifteen, so about twenty minutes in
  the yard is a verify (about ten when a camera and a motion sensor agree).
  Before, by day it never got there. At night, half an hour of lingering now
  also sends a second verify once the score has doubled.
- **A forced service mode goes by the night window.** Inside it the house is
  vacant and watched, like an automatic service mode, and service again in
  the morning. Before, a forced service left the house unwatched all night.
- **With the family home, the guest clock ends at two hours.** Their own
  comings and goings no longer count as guests' activity, so the house no
  longer reads guest for half an hour after the family next leaves.
- **Breaking: the label webhook only answers the local network.** Chat buttons
  from Mattermost Cloud, or a server reaching Home Assistant through Nabu Casa
  or a proxy, no longer label anything.
- **`sensor_offline` counts once per incident,** however many sensors drop out
  and however spread out, and the same sensor at most once an hour. Before, a
  hub dying could take five sensors down a minute apart and reach alarm, and a
  flaky sensor scored every time.

### Added

- **Sheds, storage boxes and the mailbox.** A contact on something outside
  the house, in an outdoor room's *things you open*, is told apart by name. A
  shed or storage box opening scores the new `outbuilding_opened`, 30 points
  in an empty house. The mailbox's first opening of the day is the mail
  carrier and counts for nothing; any other is someone outside. Before, both
  only said someone was outside, and the setup form put them with the doors.
- **Do people leave through the garage door?** A whole-house setting, off by
  default. When it's on, the garage door opening counts like any exterior
  door when SIEM works out whether guests have gone out. Leave it off for a
  detached garage.

### Fixed

- A code Lock Code Manager has switched off no longer lets anyone in through
  its event entity. It scored `pin_not_allowed`, but the house still went to
  guest mode.
- `sensor.siem_house_mode`, `binary_sensor.siem_night` and
  `sensor.siem_recommended_alarm_mode` stayed stale when a sensor report was
  the first thing to see the change.
- Sensors already unavailable when Home Assistant starts or SIEM reloads are
  reported as offline.
- Installs from before the first release, 0.0.1, watch the alarm panel again.
  The settings migration had moved it without telling SIEM to follow it, so
  armed night went unseen until the house step was saved again. Migration 1.10
  rebuilds the entity list, keeping strength overrides.
- A light switched through an area, device, floor or label, or with
  `entity_id: all`, that reports late no longer counts as switched by hand.
- A weak sensor that couldn't open an incident no longer uses up its room:
  the next sensor there counts in full.
- An opening worth nothing (in service mode, or the household's at night) no
  longer stops the same contact counting for five minutes.
- One out-of-order power reading, such as an EV charger reporting before the
  house meter, no longer looks like an unexplained load.
- Lockouts are read before code unlocks, so "too many unlock attempts" with a
  slot is a lockout. Z-Wave JS's *Keypad temporary disabled* counts, a slot
  sent as digits is read, and "Unlock by RF with invalid user code" no longer
  lets anyone in.
- Alerts show the latest events, not the first ten.
- An incident still open at a digest comes back in the next with how it
  ended.
- A break-glass message follows the `opened` event of the incident it
  carries, so its tier is set.
- `select.siem_label_last_incident` shows the label of the incident it would
  label, not the last label given.
- An incident open when SIEM stops or reloads fires `closed`.
- *gateway* and *tailgate* no longer read as gates, nor *personal* as a person
  detector.
- The digest's fallback says "1 incident", not "1 incidents".

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
