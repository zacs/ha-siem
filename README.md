# <img src="custom_components/siem/brand/icon.png" width="90" height="90" alt="" align="middle"> SIEM for Home Assistant

[![Tests](https://github.com/zacs/ha-siem/actions/workflows/tests.yaml/badge.svg)](https://github.com/zacs/ha-siem/actions/workflows/tests.yaml)
[![Hassfest](https://github.com/zacs/ha-siem/actions/workflows/hassfest.yaml/badge.svg)](https://github.com/zacs/ha-siem/actions/workflows/hassfest.yaml)
[![HACS](https://github.com/zacs/ha-siem/actions/workflows/hacs.yaml/badge.svg)](https://github.com/zacs/ha-siem/actions/workflows/hacs.yaml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Home Assistant is great at "if this, then that." It is not great at "huh,
that's weird." A door opening while you're out could be a friend with a key, a
delivery, or someone who shouldn't be there. Write one automation per sensor
and you end up with alerts for everything, or alerts you've learned to ignore.

SIEM (security information and event management) borrows the trick security
teams use to watch networks: nothing alerts on its own, but everything adds
up. Every sensor event becomes a bit of evidence with a score that fades over
a few minutes. A door opening while the house is empty is worth a look. The
back door, then motion in the kitchen, then the fridge, all inside five
minutes, is worth turning on every light and the siren.

It knows who's home, whether a change came from a person, an automation or a
wall switch, and whether it's 2 pm or 2 am. When it gets something wrong, you
tell it so, and it gets less jumpy about the sensors that misfired. Everything
starts in dry run, so you can watch what it would have done for a week before
you let it touch anything.

- **Three tiers.** Verify sends an alert. Deter turns on the room's lights,
  plays a sound and runs your scripts. Alarm adds sirens and your alarm panel.
- **Four house modes.** Family, guest, service and vacant, worked out from
  presence, a calendar and PIN codes. The same open door means something
  different in each.
- **Plain Home Assistant events.** Every alert is an event, so you can send it
  anywhere with an ordinary automation.

## Requirements

- Home Assistant 2025.8 or newer, and [HACS](https://www.hacs.xyz/docs/use/download/download/)
  (Home Assistant Community Store) to install it.
- Door, window or motion sensors, assigned to areas.
- People (person entities) with device trackers, so SIEM knows when someone is
  home.
- Somewhere for alerts to go: any notify service, one of the sample packages,
  or your own automation.

That's it. Everything below is optional.

## Nice to haves

Each of these adds something. None of them is required.

| Add | What you get |
| --- | --- |
| An alarm panel, such as [Alarmo](https://github.com/nielsfaber/alarmo) | A recommended alarm mode, optional auto arm and disarm, and a trigger sensor your panel can watch. Any `alarm_control_panel` works. |
| [Lock Code Manager](https://github.com/raman325/lock_code_manager) (LCM) | Guest mode when someone uses their PIN, and alerts for hand unlocks and unknown codes on any lock LCM supports. Z-Wave JS locks get the lock alerts without it. |
| [Mattermost](https://github.com/cerebrate/ha-mattermost) | Coloured alerts with the timeline, the actions and a camera snapshot, through `packages/siem_mattermost.yaml`. |
| The [companion app](https://companion.home-assistant.io/) | Push alerts with *False alarm*, *That's me*, *Real* and *Guest* buttons, through `packages/siem_mobile_app.yaml`. |
| A calendar, such as [Local Calendar](https://www.home-assistant.io/integrations/local_calendar/) | `Guest:` and `Service:` events set the house mode. |
| An [AI task](https://www.home-assistant.io/integrations/ai_task/) entity | A daily digest written in plain English instead of raw counts. OpenAI, Anthropic, Google and Ollama all provide one. |
| Cameras | A snapshot from the room's camera with each alert. |
| Lights, speakers, sirens, scripts | Deterrence: lights to full, a sound or a spoken warning, your own scripts. |
| [HomeKit Bridge](https://www.home-assistant.io/integrations/homekit/) | Lights switched from Apple Home score far lower than lights switched at the wall. |
| [Presence Simulation](https://github.com/slashback100/presence_simulation) | Its lights never count against you: its user is trusted from the start. |
| Wi-Fi motion sensors | Someone at a door that never opened. These are CSI (channel state information) sensors: an ESP32 running [ESP-CSI](https://github.com/espressif/esp-csi) or [ESPectre](https://github.com/francescopace/espectre) senses motion from changes in the Wi-Fi signal. |

## Install

1. In HACS, open the three-dot menu, then **Custom repositories**. Add
   `https://github.com/zacs/ha-siem` with the type *Integration*.
2. Install **SIEM for Home Assistant** and restart Home Assistant.
3. Go to **Settings > Devices & services > Add integration** and pick
   *SIEM for Home Assistant*.

## Setup

The setup flow walks through:

- **Rooms.** Pick the areas to protect.
- **Each room.** Pre-filled from your entities' and devices' areas. Check it
  and add anything it missed.
- **Whole house.** Residents, extra trackers, water and power sensors, locks,
  Lock Code Manager users, the calendar, and Wi-Fi motion sensors with the door
  each one watches.
- **Trust, night and deterrence.** Trusted users, the night window, the deter
  sound or message, and whole-house deter and alarm scripts.
- **Responses.** Plain-text notify services, the alarm panel, the AI task,
  digest times and the safety switches. Dry run is on until you turn it off.

You can change any of it later from the integration's **Configure** menu.

A few things live outside the flow:

- **Guest and service events.** On the calendar you picked, an event whose
  title starts with `Guest:` puts the house in guest mode, and `Service:` in
  service mode. Guest mode ends two hours after the event, or later if the
  house hasn't been quiet for an hour by then. Service mode ends with the
  event.
- **Lock Code Manager users.** Give each guest an LCM user; a calendar
  condition on that user limits when the PIN works. When a PIN opens the door,
  SIEM switches to guest mode and notes who it was. A code LCM doesn't know
  scores `pin_not_allowed`.
- **The alarm trigger.** For SIEM to set off your alarm, add
  `binary_sensor.siem_alarm_trigger` to your panel as an always-on sensor (in
  Alarmo, type *other*). With auto alarm on and dry run off, an alarm-tier
  incident turns it on for 60 seconds.
- **Trusted users.** Changes made by trusted users never count. Residents and
  a user named Presence Simulation are picked for you. Alexa and Google
  Assistant act through Home Assistant Cloud as the *Home Assistant Cloud*
  user, so trust that user if you use them.

## Alerts and events

The simplest setup needs no automations: pick one or more notify services in
the responses step, and SIEM sends every alert to them as plain text.

Every alert is also a Home Assistant event, so you can route it anywhere:

- **`siem_notification`** fires for every alert. `category` is `verify`,
  `deter`, `alarm`, `break_glass`, `arm` or `digest`. It also carries `title`,
  `message` (the plain text), `dry_run`, `incident` (when there is one),
  `actions` (what ran, or would have), `snapshot` (the camera snapshot's path)
  and `again` (a second verify alert because the score doubled).
- **`siem_incident`** fires when an incident opens, changes tier or closes,
  with `kind` set to `opened`, `tier_changed` or `closed`.

An incident carries `incident_id`, `tier`, `peak_tier`, `score`, `peak_score`,
`room`, `mode` (the house mode when it opened), `house_mode`, `person` (the
Lock Code Manager user, when a PIN was used), `started`, `closed`, `labels`,
`top_contributors` and `timeline`. Each timeline entry has `at`, `rule`,
`points`, `entity_id`, `name`, `description` and `detail`.

```yaml
automation:
  - alias: SIEM alarms to my phone
    triggers:
      - trigger: event
        event_type: siem_notification
        event_data:
          category: alarm
    actions:
      - action: notify.mobile_app_my_phone
        data:
          title: "{{ trigger.event.data.title }}"
          message: "{{ trigger.event.data.message }}"
```

Two ready-made packages live in [`packages/`](packages). Copy one into
`<config>/packages/`, edit the channel or phone at the top, and restart:

- [`siem_mattermost.yaml`](packages/siem_mattermost.yaml) posts every alert to
  a Mattermost channel with colours, fields, the timeline and the snapshot.
- [`siem_mobile_app.yaml`](packages/siem_mobile_app.yaml) pushes alerts to a
  phone with label buttons. SIEM listens for the button presses itself.

Snapshots go to `siem/` in your media folder, newest 200 kept. You can see them
in the media browser after you log in.

## How scoring works

The scoring model is opinionated, and it lives in code: which rules exist,
what sets them off, how they chain, the suppressors, the house mode timings
and how labels learn. **Configure** lets you change a few numbers when the
defaults don't suit your house: each rule's points per house mode, the tier
thresholds, the half-life and the chain factors. Anything more means editing
`core/rules.py` (see [Adding a rule](#adding-a-rule)).

**Where a change came from.** Every state change is classified first.
Anything an automation or script caused never counts, including ones started
by a time, sun or calendar trigger. A trusted user never counts, and any other
user scores `untrusted_user`. A light switched from Apple Home scores
`light_homekit`. Everything else is physical: a hand on a switch, a door, a
person in a room.

**What never counts.** SIEM's own actions. An entity coming back after a
restart or a reconnect, even if it comes back on; only a real off-to-on change
counts. A sensor that is unavailable for less than two minutes.

**The score.** Each event adds `points × weight`, halving every 15 minutes.
The score is the sum, capped at 100. Verify starts at 20, deter at 50 and
alarm at 80. An incident opens with the first event that scores, collects
every event within five minutes of the last one (or while its score is still
above 5), and closes after 30 minutes below 5. The same entity scores the same
rule at most once a minute, and lights count once a minute per room, because
one switch can turn on a whole group of bulbs.

**Rules.** Points are for the house modes vacant, guest, service and family.
Rules marked *exterior* score 1.5 times as much inside the night window.

| Rule | Points | Fires when |
| --- | --- | --- |
| `exterior_door_opened` | 40, 5, 5, 0 | An exterior door or window opens (exterior) |
| `gate_opened` | 30, 5, 5, 0 | A perimeter contact with *gate* in its name opens (exterior) |
| `door_csi_motion` | 15, 2, 2, 0 | A Wi-Fi motion sensor sees someone at a door that is closed and hasn't opened in the last 60 seconds (exterior) |
| `interior_occupied` | 50, 5, 5, 0 | Someone is in a room; see below |
| `interior_door_opened` | 40, 0, 5, 0 | A fridge, freezer, pantry, cabinet, cupboard, drawer or closet contact opens |
| `light_physical` | 45, 0, 0, 0 | A light is turned on at the switch |
| `light_homekit` | 5, 0, 0, 0 | A light is turned on from Apple Home |
| `untrusted_user` | 70, 50, 50, 30 | A watched entity is changed by a user you don't trust |
| `appliance_on` | 35, 0, 0, 0 | A room's power sensor rises above its threshold (default 30 W) |
| `water_flow` | 30, 0, 10, 0 | Water flow rises above its threshold |
| `load_residual` | 10, 0, 0, 0 | House power, minus loads that run on their own, steps up and stays up |
| `person_interior_camera` | 40, 5, 5, 0 | An occupancy sensor with *person* in its name turns on inside |
| `person_exterior_camera` | 10, 5, 5, 2 | The same in an area named like a yard, driveway, porch, patio, garden, deck or balcony (exterior) |
| `manual_unlock` | 60, 40, 40, 0 | A lock is unlocked by hand |
| `pin_not_allowed` | 30, 30, 30, 20 | A lock is unlocked with a code Lock Code Manager doesn't know, or marks inactive |
| `keypad_lockout` | 40, 40, 40, 30 | A Z-Wave lock reports a keypad lockout after bad codes; few locks send this |
| `sensor_offline` | 20, 5, 5, 0 | A door, window, motion or Wi-Fi motion sensor, or a lock, stays unavailable for two minutes; several at once count once |

**Someone in a room.** Occupancy and presence sensors are strong, motion
sensors medium (60% of the points), sound sensors weak (30%), and Bayesian
sensors strong. You can change an entity's strength in **Configure**. A room
scores once per five minutes at the level of its strongest sensor, times 1.3
when two sensors agree within a minute. A weak sensor alone never opens an
incident while the house is vacant.

**Locks.** Lock Code Manager reports hand and code unlocks for every lock it
supports, and SIEM also reads Z-Wave JS lock notifications directly. Matter
locks report the code but not hand unlocks.

**Chains.** Some rules mean more after others, within five minutes in the
same incident: an entry (`exterior_door_opened` or `door_csi_motion`) then
`interior_occupied` scores 1.5 times; `gate_opened` then an entry 1.5 times;
`interior_occupied` then `light_physical`, `appliance_on` or
`interior_door_opened` 1.5 times; and anything after `manual_unlock` twice.

**Suppressors.** A resident or tracker arriving home takes 60 points off the
open incident and switches the house to family. A PIN that Lock Code Manager
allows takes 40 off, switches the house to guest and names the person.

**Labels.** Label an incident from `select.siem_label_last_incident`, the
`siem.label_incident` action, or the phone buttons. *False alarm* lowers the
weight of every rule in the incident by 10%, to no less than 0.3. *Real*
raises them by 10%, to no more than 1.5. *That's me* and *Guest* are recorded
and leave the weights alone: the sensors were right and presence detection was
late, and lowering the weights would only blunt the next real break-in.

**House mode.** Family while any resident or tracker is home and for 30
minutes after. Guest during a `Guest:` event or after an allowed PIN.
Service during a `Service:` event. Vacant otherwise.
`select.siem_house_mode_override` forces a mode, and the choice survives
restarts.

**Arming.** The recommended alarm mode is armed away while vacant, armed night
at night when someone is home, and disarmed by day and during service visits.
With auto arm on and dry run off, SIEM sets your panel to match, both arming
and disarming. Disarming follows presence, so a phone that says it's home
disarms the panel; leave auto arm off if you'd rather not make that trade.

**Responses.** Verify alerts once, and again if the score doubles. Deter
alerts and runs the room's deterrence (lights to full, speakers to the deter
volume, the sound or spoken message, the room script, speakers restored
afterwards) and the whole-house deter scripts. Alarm adds the whole-house alarm
scripts and switches and, with auto alarm on, pulses the alarm trigger. Break
glass alerts whatever the score: a hand unlock while vacant, a keypad lockout,
or a sensor unavailable for over an hour while vacant. In dry run every alert
starts with `[DRY RUN]` and lists what would have run.

## Entities and actions

| Entity | What it shows |
| --- | --- |
| `sensor.siem_risk_score` | The live score, with `top_contributors` and `incident_id` |
| `sensor.siem_tier` | `none`, `verify`, `deter` or `alarm` |
| `sensor.siem_incident` | The open incident's id, with `started`, `room`, `mode`, `person` and the `timeline` (not recorded) |
| `sensor.siem_house_mode` | `vacant`, `guest`, `service` or `family` |
| `select.siem_house_mode_override` | Force a mode, or `auto` |
| `sensor.siem_recommended_alarm_mode` | `armed_away`, `armed_night`, `armed_home` or `disarmed` |
| `binary_sensor.siem_night` | On inside the night window |
| `binary_sensor.siem_alarm_trigger` | On for 60 seconds at the alarm tier, with auto alarm on |
| `switch.siem_dry_run`, `switch.siem_auto_arm`, `switch.siem_auto_alarm` | The safety switches; they survive restarts |
| `select.siem_label_last_incident` | Label the open or most recent incident |
| `event.siem_incident` | `opened`, `tier_changed` and `closed`, for automations built in the UI |

Actions: `siem.label_incident`, `siem.run_digest`, `siem.reset_weights` and
`siem.set_house_mode`.

## Dry run with test entities

[`dev/siem_test_entities.yaml`](dev/siem_test_entities.yaml) is a package that
builds a fake house of `Test ...` entities: three rooms of sensors, lights and
power, a speaker, a lock, a Lock Code Manager style event entity, two people,
an alarm panel, and scripts that send Z-Wave lock notifications. Copy it to
`<config>/packages/`, restart, create the three areas it names, and follow the
setup answers at the top of the file. It needs Home Assistant 2025.9 or newer.

A simulated household then runs the house. Every two seconds each sensor rolls
dice, with odds that follow the time of day: quiet at night, a busy kitchen in
the morning, an empty house on weekdays with deliveries and a guest who lets
themselves in with a PIN, and a full house in the evening. Three helpers
control it: *Test Simulation* turns it off, *Test Sim Scene Override* forces a
time of day, and *Test Simulation Rate* speeds it up. Every sensor also has a
`(helper)` switch to force it on, and two scripts play a break-in and a
delivery. The file header walks through exact scores step by step.

## Adding a rule

1. In `core/rules.py`, add a `_rule(...)` line to `DEFAULT_RULES` with the
   id, the tag (`exterior` gets the night multiplier), points for vacant,
   guest, service and family, and a plain description. Add it to
   `DEFAULT_CHAINS` if it should amplify or be amplified.
2. If it needs a new kind of entity, add the config key to `const.py`, the
   selector to the schema in `config_flow.py`, a role in `core/entities.py`,
   and a line in `build_entity_meta`. Per-entity details go in that metadata,
   so no config migration is needed.
3. In `coordinator.py`, handle the role in `_on_state` (or an event listener)
   and call `self._score("<rule id>", now, entity_id, room, detail)`.
4. Add the field's text to `translations/en.json`, and tests.

## Development

```
pip install -r requirements_test.txt
ruff check .
pytest
```

The tests in `tests/` cover the pure-Python engine in
`custom_components/siem/core/`, which never imports Home Assistant. The tests
in `tests/ha/` run the integration, the sample packages and the test package
inside a real Home Assistant, pinned by `pytest-homeassistant-custom-component`.
Without that plugin installed, only the core tests run. The badges track three
GitHub Actions workflows: tests, Home Assistant's hassfest checks, and HACS
validation.

## License

MIT, see [`LICENSE`](LICENSE).
