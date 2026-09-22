# SIEM for Home Assistant

A SIEM-style risk engine for a house. Every sensor event is a scored, decaying
contribution to an incident. Incidents climb through **verify**, **deter** and
**alarm** tiers, and each tier has a response: a Mattermost message, room and
whole-house deterrence, an alarm trigger. Labels you give incidents adjust the
weight of the rules that fired, so the engine learns which sensors you trust.

The scoring engine lives in `custom_components/siem/core/` and is pure Python
with no Home Assistant imports. The rest of the component is a thin adapter.

## Installation via HACS

1. In HACS, open **Integrations**, then the three-dot menu, then **Custom
   repositories**. Add `https://github.com/zacs/ha-siem` with category
   *Integration*.
2. Install **SIEM for Home Assistant** and restart Home Assistant.
3. Go to **Settings, Devices & services, Add integration** and pick
   *SIEM for Home Assistant*. The flow has four kinds of steps:
   - **Rooms**: pick the areas to protect.
   - **Room** (one per area): every field is pre-filled from the entity
     registry by area, falling back to the device's area. Each filtered field
     has an unfiltered *additional* companion for entities the filter misses.
   - **Whole house**: residents, trackers, CSI sensors, water flow, the load
     sensor, locks, Lock Code Manager event entities and the calendar, then
     trusted users, the night window and deterrence.
   - **Responses**: notify service, alarm panel, AI task, digest times and the
     safety toggles. Dry run defaults to on.

Everything can be revisited later from the integration's **Configure** menu:
rule points per mode, half-life, thresholds and chain factors, the learned
weights, any room step, the whole-house steps, the responses step, and
per-entity occupancy strength overrides.

## Hand setup

Things the component consumes but cannot create for you:

- **Lock Code Manager users with calendar conditions.** Give each guest or
  sitter an LCM user whose condition entity is a calendar. SIEM listens to the
  LCM per-user *credential used* event entities: an allowed PIN use flips the
  house to sitter mode, subtracts 40 points and stamps the incident with the
  LCM user name. A keypad unlock with a slot LCM does not know scores
  `pin_not_allowed`.
- **Calendar prefixes.** On the configured calendar, an event whose summary
  starts with `Sitter:` puts the house in sitter mode, and `Service:` in
  service mode. Sitter mode ends two hours after the event plus sixty quiet
  minutes; service mode ends with the event.
- **Register the alarm trigger sensor in Alarmo.** Add
  `binary_sensor.siem_alarm_trigger` to Alarmo as an *always on* sensor of type
  *other*. When auto alarm is on and dry run is off, an alarm-tier incident
  turns it on for 60 seconds.
- **Deter script.** Optional, per room and whole house. Room deterrence
  snapshots the room's media players, sets the deter lights to 100 %, sets the
  deter volume, plays the deter sound (or speaks the TTS message), runs the room
  script, then runs the whole-house deter scripts and switches. Players are
  restored after the configured seconds through a `scene.turn_on` of the
  snapshot.
- **Mattermost channel.** A `notify.mattermost` service (or any notify service
  that accepts `data.attachments`) and a target channel, default
  `home_security`. If the service rejects the rich payload, SIEM resends the
  plain message. Camera snapshots go to `/config/www/siem/<incident_id>.jpg`.
- **ai_task entity.** An `ai_task` entity that supports *generate data*. At
  each digest time SIEM asks it for five lines about the window since the
  previous digest, with a 20 second timeout and a raw-count fallback.
- **Presence Simulation.** If you run a presence simulation under its own user
  named `Presence Simulation`, that user is pre-filled into the trusted list so
  its actions never score.

## Entities

| Entity | Meaning |
| --- | --- |
| `sensor.siem_risk_score` | Live score, attributes `top_contributors` (max 5) and `incident_id` |
| `sensor.siem_tier` | `none`, `verify`, `deter` or `alarm` |
| `sensor.siem_incident` | Open incident id with `started`, `room`, `mode`, `person`, `timeline` (timeline is not recorded) |
| `sensor.siem_house_mode` | `vacant`, `sitter`, `service` or `family` |
| `select.siem_house_mode_override` | Force a mode, or `auto` |
| `sensor.siem_recommended_alarm_mode` | `armed_away`, `armed_night`, `armed_home` or `disarmed` |
| `binary_sensor.siem_night` | Inside the night window |
| `binary_sensor.siem_alarm_trigger` | Pulsed for 60 s on alarm when auto alarm is on |
| `switch.siem_dry_run`, `switch.siem_auto_arm`, `switch.siem_auto_alarm` | Runtime toggles, persisted |
| `select.siem_label_last_incident` | Label the open or most recent incident |
| `event.siem_incident` | `opened`, `tier_changed`, `closed` |

Services: `siem.label_incident`, `siem.run_digest`, `siem.reset_weights`,
`siem.set_house_mode`.

## How scoring works

Every state change is first classified by origin. A change with a
`parent_id` came from an automation and never scores. A change with a
`user_id` in the trusted list never scores; one from any other user scores
`untrusted_user`. A change with neither is HomeKit when its context id was
announced by `homekit_state_change` in the last 60 seconds, otherwise it is
physical.

`score = min(100, sum(points × weight × 0.5 ^ (age_min / half_life)))` with a
15 minute half-life; contributions under 0.5 are dropped. Tiers open at 20,
50 and 80. An incident opens on the first positive contribution, joins events
within 5 minutes of the latest one (or while it is still above the close
threshold), closes after 30 minutes below 5, and keeps the first 10 events in
its timeline. State publishes at most every 30 seconds and only on a change of
1 point or more; tier changes publish immediately.

Points are `{vacant, sitter, service, family}`. The night window multiplies
exterior-tagged rules by 1.5.

| Rule | Tag | Points | Fires when |
| --- | --- | --- | --- |
| `exterior_door_opened` | exterior | 40, 5, 5, 0 | A perimeter contact turns on |
| `gate_opened` | exterior | 30, 5, 5, 0 | A perimeter contact named *gate* turns on |
| `door_csi_motion` | exterior | 15, 2, 2, 0 | A CSI sensor turns on with no mapped contact opening within 60 s |
| `interior_occupied` | interior | 50, 5, 5, 0 | Room occupancy; strongest source in a 5 min window, two independent sources within 60 s ×1.3, a weak source alone never opens an incident in vacant |
| `interior_door_opened` | interior | 40, 0, 5, 0 | A fridge, cabinet, drawer or closet contact turns on |
| `light_physical` | interior | 45, 0, 0, 0 | A light turns on with physical origin |
| `light_homekit` | interior | 5, 0, 0, 0 | A light turns on through HomeKit |
| `untrusted_user` | account | 70, 50, 50, 30 | Any watched entity changed by a user outside the trusted list |
| `tv_power` | interior | 35, 0, 0, 0 | A power sensor rises above its threshold (default 30 W) |
| `water_flow` | interior | 30, 0, 10, 0 | Water flow rises above its threshold |
| `load_residual` | interior | 10, 0, 0, 0 | Optional: house load minus automated loads steps up by *step watts* and stays there for *sustain minutes* |
| `person_interior_camera` | interior | 40, 5, 5, 0 | An occupancy source named *person* in an interior room turns on |
| `person_exterior_camera` | exterior | 10, 5, 5, 2 | The same in an area named like a yard, driveway, porch or patio |
| `manual_unlock` | perimeter | 60, 40, 40, 0 | `zwave_js_notification` with an event label containing *Manual unlock* |
| `pin_not_allowed` | perimeter | 30, 30, 30, 20 | A keypad unlock whose slot is unknown to the LCM event entities or marked inactive |
| `keypad_lockout` | perimeter | 40, 40, 40, 30 | A lock notification reading as repeated bad codes or a disabled keypad. Most locks never send this; nothing depends on it |
| `sensor_offline` | tamper | 20, 5, 5, 0 | A watched entity becomes unavailable |

Occupancy source strength is derived in code: device class `occupancy` or
`presence` is strong, `motion` medium, `sound` weak, and anything from the
`bayesian` platform is strong. Override per entity in the options flow.

**Suppressors**, once per transition: a resident, a resident's tracker or an
additional tracker arriving home subtracts 60 and flips the house to family;
an allowed PIN use reported by an LCM event entity subtracts 40, flips the
house to sitter and sets the incident's person.

**Chains** multiply the second rule when it fires within the chain window
(5 minutes) after the first, in the same incident: entry (`exterior_door_opened`
or `door_csi_motion`) then `interior_occupied` ×1.5; `gate_opened` then entry
×1.5; `interior_occupied` then `light_physical`, `tv_power` or
`interior_door_opened` ×1.5; `manual_unlock` then anything ×2.0.

**Weights** start at 1.0 per rule. Labels `false_alarm`, `thats_me` and
`sitter` multiply every rule in the incident by 0.9 (floor 0.3); `real`
multiplies by 1.1 (cap 1.5). Weights and the last 200 incidents live in the
Home Assistant store.

**House mode** is family while any resident or tracker is home and for 30
minutes after, sitter on a `Sitter:` calendar event or an allowed PIN use,
service on a `Service:` event, vacant otherwise. The override select forces a
mode.

**Arm recommendation**: vacant is armed away; family and sitter are armed
night inside the night window and disarmed by day; service is disarmed. With
auto arm on and dry run off the configured panel is armed; otherwise you get a
"would arm" message.

**Responses**: verify notifies once per incident and again if the score
doubles. Deter notifies, then runs room deterrence for the incident's room
and whole-house deterrence. Alarm adds the whole-house alarm scripts and
switches and, with auto alarm on, the alarm trigger pulse. Incidents without a
room run whole-house actions only. Break-glass events (`manual_unlock` while
vacant, `keypad_lockout`, or a watched entity unavailable for over 60 minutes
while vacant) fan out to both notify services. In dry run every message starts
with `[DRY RUN]` and ends with the concrete action list, entity by entity.

## Dry run with test entities

`dev/siem_test_entities.yaml` is a Home Assistant package that builds a fake
house of `Test ...` entities: three rooms of motion, presence, sound, door,
window, fridge and gate contacts, lights, power sensors, a camera-style person
detector per room, a universal media player, a lock, a Lock Code Manager style
event entity, two persons with device trackers, whole-house switches and
scripts, an alarm panel, and scripts that fire Z-Wave lock notifications.
Every watched entity is a template mirror of an `input_boolean` or
`input_number` helper, so the whole rig is driven from the UI. Copy the file
to `<config>/packages/`, restart, create the three areas it names, move the
room entities into them, and follow the suggested config flow answers and the
walkthrough in the file header.

The mirrors are trigger-based templates on a two second timer on purpose. A
helper toggled from the UI carries your user id, and the SIEM would classify
the change as a user action rather than a physical one; re-rendering on a
timer drops that context. Setting a mirror's state directly in Developer
tools exercises the user-origin path instead.

The file header lists what it cannot create: areas, the notify service
(use `notify.persistent_notification` or your real Mattermost service with a
test channel), a calendar (add a Local Calendar), a camera, an AI task entity,
the companion app notify service, a TTS entity, and a HomeKit-origin change.

## Adding a rule

1. In `core/rules.py`, add a `_rule(...)` line to `DEFAULT_RULES` with the id,
   tag and points per mode. Tag it `exterior` if the night multiplier should
   apply. Add it to a chain in `DEFAULT_CHAINS` if it should amplify or be
   amplified.
2. If the rule needs a new kind of entity, add the config key to `const.py`,
   the selector to the matching schema in `config_flow.py` (rooms use
   `ROOM_SCHEMA`, the house uses `HOUSE_SCHEMA`), a role constant in
   `core/entities.py`, and a line in `build_entity_meta` so the entity gets a
   role in the per-entity metadata dict. New per-entity fields go in that dict;
   no config entry migration is needed.
3. In `coordinator.py`, handle the role in `_handle_state` (or in the event
   listeners) and call `self._score("<rule id>", now, entity_id, room, detail)`.
4. Add the translation strings for the new field to `translations/en.json`
   and a test under `tests/` for the core behaviour.

## Development

```
pip install -r requirements_test.txt
pytest
ruff check .
```

Tests cover `core/` only and need no Home Assistant installation. The
brand icon HACS shows lives in `custom_components/siem/brand/`.

## License

MIT, see `LICENSE`.

Phase 2 (not built): an unknown-BLE baseline from the Bluetooth advertisement
stream. It will add `bluetooth` to the manifest dependencies when it lands.
