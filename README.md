# <img src="custom_components/siem/brand/icon.png" width="90" height="90" alt="" align="middle"> SIEM Security

[![Tests](https://github.com/zacs/ha-siem/actions/workflows/tests.yaml/badge.svg)](https://github.com/zacs/ha-siem/actions/workflows/tests.yaml)
[![Hassfest](https://github.com/zacs/ha-siem/actions/workflows/hassfest.yaml/badge.svg)](https://github.com/zacs/ha-siem/actions/workflows/hassfest.yaml)
[![HACS](https://github.com/zacs/ha-siem/actions/workflows/hacs.yaml/badge.svg)](https://github.com/zacs/ha-siem/actions/workflows/hacs.yaml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Home Assistant is great at "if this, then that." It is not great at "huh,
that's weird." A door opening while you're out could be a friend with a key, a
delivery, or someone who shouldn't be there. Write one automation per sensor
and you end up with alerts for everything, or alerts you've learned to ignore.

SIEM (security information and event management) borrows an approach tech security
teams use to watch networks: nothing alerts on its own, but everything adds
up. Every sensor event becomes a bit of evidence with a score that fades over
a few minutes. A door opening while the house is empty is worth a look. The
back door, then motion in the kitchen, then the fridge, all inside five
minutes, is worth turning on every light and the siren.

It knows who's home, whether something physically happened or Home Assistant
did it, and whether it's 2 pm or 2 am. When it gets something wrong, you tell
it so, and it gets less jumpy about the sensors that misfired.

SIEM is a state machine: sensors go in, state and events come out. It never
turns on a light, sends a notification or touches your alarm panel. What
happens at each tier is up to your own automations, so you can watch its
alerts for a week before you let anything act on them.

- **Three tiers.** Verify, deter and alarm, each one an event your automations
  can act on.
- **Five house modes.** Family, night, guest, service and vacant, worked out
  from presence, bedtime, a calendar and lock codes. The same open door means
  something different in each.
- **Plain Home Assistant state and events.** Sensors for the score, tier,
  incident and house mode, and an event for every alert.

## Requirements

- Door, window or motion sensors, assigned to areas.
- A device tracker for everyone who lives there, so SIEM knows when someone is
  home. Residents are person entities; anyone without a Home Assistant login
  can be an extra tracker, such as their phone seen by your router.
- Automations that do something with SIEM's alerts. There are sample packages to be a
  starting point.

## Nice to haves

Each of these adds something. None of them is required.

| Add | What you get |
| --- | --- |
| An alarm panel, such as [Alarmo](https://github.com/nielsfaber/alarmo) | Add `binary_sensor.siem_alarm_trigger` to it and SIEM's alarm tier sets off your alarm. Pick it in setup and arming it night tells SIEM everyone's in bed; SIEM only reads it. |
| [Lock Code Manager](https://github.com/raman325/lock_code_manager) (LCM) | Codes and hand unlocks from any lock LCM supports, with the code's name on the incident, and an alert when a code LCM has switched off still opens the lock. Z-Wave JS locks report codes and hand unlocks without it. |
| A calendar, such as [Local Calendar](https://www.home-assistant.io/integrations/local_calendar/) | `Guest:` and `Service:` on event names set the house mode. |
| An [AI task](https://www.home-assistant.io/integrations/ai_task/) entity | A daily digest written in plain English instead of raw counts. OpenAI, Anthropic, Google and Ollama all provide one. |
| Cameras | A snapshot from the room's camera with each alert. |
| Wi-Fi motion sensors | Someone at a door that never opened. These are CSI (channel state information) sensors: an ESP32 running [ESP-CSI](https://github.com/espressif/esp-csi) or [ESPectre](https://github.com/francescopace/espectre) senses motion from changes in the Wi-Fi signal. |

## Install

1. In HACS, open the three-dot menu, then **Custom repositories**. Add
   `https://github.com/zacs/ha-siem` with the type *Integration*.
2. Install **SIEM Security** and restart Home Assistant.
3. Go to **Settings > Devices & services > Add integration** and pick
   *SIEM Security*.

## Setup

The setup flow walks through:

- **Rooms.** Pick the areas to protect.
- **Each room.** Pre-filled from your entities' and devices' areas. Check it
  and add anything it missed. Tick *Outdoors* for a yard, porch or driveway
  (rooms named like one start ticked): anything there only means someone is
  outside.
- **Whole house.** Residents, extra trackers, water and power sensors, locks,
  Lock Code Manager event entities, the calendar, the alarm panel to read
  bedtime from, the night window, and Wi-Fi motion sensors with the door each
  one watches.
- **Digest.** The AI task and the digest times.

You can change any of it later from the integration's **Configure** menu.

Two things live outside the flow:

- **Guest and service events.** On the calendar you picked, an event whose
  title starts with `Guest:` puts the house in guest mode, and `Service:` in
  service mode. Guest mode ends two hours after the event, or later if the
  house hasn't been quiet for an hour by then. Service mode ends with the
  event.
- **The alarm trigger.** To have SIEM set off your alarm, add
  `binary_sensor.siem_alarm_trigger` to your panel as an always-on sensor (in
  Alarmo, type *other*). It turns on once an incident has stayed at the alarm
  tier for a minute, which gives a phone that reports home a little late the
  time to call it off, and off when the incident drops below alarm.

## Alerts and events

SIEM keeps its state in entities and announces everything else as events.
Everything that happens next is an automation of your own.

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

Three ready-made packages live in [`packages/`](packages). Copy one into
`<config>/packages/`, edit anything marked at the top, and restart:

- [`siem_deterrence.yaml`](packages/siem_deterrence.yaml) turns on every light
  in the incident's room at the deter tier, and every light in the house at
  the alarm tier. Add speakers, sirens or scripts to taste.
- [`siem_mattermost.yaml`](packages/siem_mattermost.yaml) posts every alert to
  a Mattermost channel with colours, fields, the timeline and the snapshot.
- [`siem_mobile_app.yaml`](packages/siem_mobile_app.yaml) pushes alerts to a
  phone with label buttons. SIEM listens for the button presses itself.

Lights, speakers or anything else your automations change in response never
count against you: SIEM sees that Home Assistant did it.

### `siem_notification`

Fires for every alert. Every field is always present, so templates need no
guards.

| Field | Type | What it holds |
| --- | --- | --- |
| `category` | string | `verify`, `deter`, `alarm`, `break_glass` or `digest` |
| `title` | string | A short title, such as `SIEM verify: Kitchen` |
| `message` | string | The alert as plain text: score, house mode and the latest events |
| `incident` | object or null | The incident, described below. Set for verify, deter and alarm, and for break glass while an incident is open |
| `snapshot` | string or null | The path of the room camera's snapshot, when the room has a camera |
| `again` | boolean | True for a second verify alert, sent because the score doubled |
| `summary` | object or null | Digest only: `since`, `until`, `incident_count`, `labels`, `weight_changes` (a count) and `counts` (one line of totals) |

When each category fires:

- `verify` once per incident, when it first reaches the verify tier, and again
  with `again` set if its score doubles while it is still at verify.
- `deter` and `alarm` every time an incident climbs to that tier.
- `break_glass` whatever the score: a hand unlock while vacant, a keypad
  lockout, or a sensor unavailable for over an hour while vacant.
- `digest` at each digest time, or when you run `siem.run_digest`.

### `siem_incident`

Fires when an incident opens, changes tier or closes. It carries every field
of the incident object below, plus:

| Field | Type | What it holds |
| --- | --- | --- |
| `kind` | string | `opened`, `tier_changed` or `closed` |
| `tier` | string | The tier after this change |
| `previous_tier` | string | The tier before it |

`event.siem_incident` fires on the same changes for automations built in the
UI. Its attributes are `event_type` (the `kind`), `incident_id`, `tier`,
`previous_tier`, `score`, `room` and `mode`.

### The incident object

| Field | Type | What it holds |
| --- | --- | --- |
| `incident_id` | string | Eight hex characters, such as `3f9a1c2b` |
| `tier` | string | `none`, `verify`, `deter` or `alarm` |
| `peak_tier` | string | The highest tier it reached |
| `score` | number | The live score; 0 once closed |
| `peak_score` | number | The highest score it reached |
| `room` | string or null | The room it started in |
| `area_id` | string or null | That room's Home Assistant area id, for `area_entities()` and area targets |
| `mode` | string | The house mode when it opened |
| `house_mode` | string | The house mode now |
| `person` | string or null | The Lock Code Manager slot name, when a code it manages was used |
| `started` | string | When it opened, as local ISO 8601 time |
| `closed` | string or null | When it closed, as local ISO 8601 time |
| `labels` | list of strings | The labels given so far |
| `top_contributors` | list of objects | Up to five rules driving the score now, each with `rule`, `points` and `entities`. Empty once closed |
| `timeline` | list of objects | The first ten events, each described below |

Each timeline entry has:

| Field | Type | What it holds |
| --- | --- | --- |
| `at` | string | When it happened, as local ISO 8601 time |
| `rule` | string | The rule id, or `family_arrival` or `let_in` for a suppressor |
| `points` | number | Its points after chains, before weights and decay; negative for a suppressor |
| `entity_id` | string or null | The entity that set it off |
| `name` | string or null | That entity's friendly name |
| `room` | string or null | The room it happened in |
| `description` | string | The rule in plain words, such as `An exterior door or window opened` |
| `detail` | string | A short note, such as `opened` or `code used by Pat` |

Snapshots go to `siem/` in your media folder, newest 200 kept. You can see them
in the media browser after you log in.

## How scoring works

The scoring model is opinionated, and it lives in code: which rules exist,
what sets them off, how they chain, the suppressors, the house mode timings
and how labels learn. **Configure** lets you change a few numbers when the
defaults don't suit your house: each rule's points per house mode, the tier
thresholds, the half-life and the chain factors. Anything more means editing
`core/rules.py` (see [Adding a rule](#adding-a-rule)).

**What physically happened.** SIEM only cares about Home Assistant users for
one thing: telling what Home Assistant did from what happened in the house. A
hand on a switch, a door, a person in a room count. Anything Home Assistant
did never counts: an automation or script on any trigger, you in the app,
Alexa or Google Assistant through Home Assistant Cloud, Apple Home through
HomeKit Bridge, or an integration such as
[Presence Simulation](https://github.com/slashback100/presence_simulation).
Every one of those reaches the house through a service call, and every state
change it causes carries the call's context. Two kinds of change carry no
context of their own, so SIEM links them back: a light that reports back slowly
after Home Assistant switched it (within 30 seconds), and an appliance whose
power climbs after Home Assistant switched something in the same room (within
two minutes), like a lamp's smart plug or a TV through its integration.

**What never counts.** An entity coming back after a restart or a reconnect,
even if it comes back on; only a real off-to-on change counts. A sensor that
is unavailable for less than two minutes.

**The score.** Each event adds `points × weight`, halving every 15 minutes.
The score is the sum, capped at 100. Verify starts at 20, deter at 50 and
alarm at 80. An incident opens with the first event that scores, collects
every event within five minutes of the last one (or while its score is still
above 5), and closes after 30 minutes below 5. The same entity scores the same
rule at most once every five minutes, so a door used to come in and to go out
is one visit, and lights count once per room, because one switch can turn on a
whole group of bulbs.

**Rules.** Points are for the house modes vacant, guest, service, family and
night. With anyone trusted home and awake, SIEM stays out of the way: only lock
trouble scores. At night it watches the house again; see below. Rules marked
*exterior* score 1.5 times as much at night: inside the night window, or in
night mode.

| Rule | Points | Fires when |
| --- | --- | --- |
| `exterior_door_opened` | 40, 0, 0, 0, 40 | An exterior door or window opens (exterior) |
| `gate_opened` | 30, 0, 0, 0, 30 | A perimeter contact with *gate* in its name opens (exterior) |
| `door_csi_motion` | 5, 0, 0, 0, 5 | A Wi-Fi motion sensor sees someone at a door that is closed and hasn't opened in the last 60 seconds (exterior) |
| `exterior_occupied` | 10, 0, 0, 0, 10 | Someone is outside; see below (exterior) |
| `interior_occupied` | 50, 0, 0, 0, 50 | Someone is in a room; see below |
| `interior_door_opened` | 40, 0, 0, 0, 40 | A fridge, freezer, pantry, cabinet, cupboard, drawer or closet contact opens |
| `light_physical` | 45, 0, 0, 0, 45 | A light is turned on at the switch |
| `appliance_on` | 35, 0, 0, 0, 35 | A room's power sensor rises above its threshold (default 30 W) |
| `water_flow` | 30, 0, 0, 0, 30 | Water flow rises above its threshold |
| `load_residual` | 10, 0, 0, 0, 0 | House power, minus loads that run on their own, steps up and stays up |
| `manual_unlock` | 60, 0, 0, 0, 0 | A lock is unlocked by hand |
| `pin_not_allowed` | 30, 30, 30, 20, 20 | A code Lock Code Manager has switched off still opens a lock |
| `keypad_lockout` | 40, 40, 40, 30, 30 | A lock reports a keypad lockout after repeated bad codes; one wrong code does not count, and few locks send this |
| `sensor_offline` | 20, 0, 0, 0, 0 | A door, window, motion or Wi-Fi motion sensor, or a lock, stays unavailable for two minutes; several at once count once |

**Someone in a room.** Camera person detection (an occupancy sensor with
*person* in its name), occupancy, presence and Bayesian sensors are strong,
motion sensors medium (60% of the points), sound sensors weak (30%). You can
change an entity's strength in **Configure**. A room scores once per five
minutes at the level of its strongest sensor, times 1.3 when two sensors agree
within a minute. A weak sensor alone never opens an incident while the house
is vacant, which is what to do with motion sensors a pet sets off.

**Someone outside.** In an outdoor room, motion, person detection, a light
that turns itself on (a floodlight's own sensor) and contacts such as a shed or
mailbox all mean the same thing: someone is outside. The whole outdoors counts
once per fifteen minutes, at its strongest source, times 1.3 when two agree.
A visit to the front door is a few points; someone hanging around builds up
slowly; someone who also opens the gate or a door is another matter. Power
sensors in outdoor rooms are not used.

**At night.** With the family home and in bed (night mode), SIEM watches the
yard, the doors and the windows the way it watches an empty house, and tells
one of you from an intruder by the order of events. Someone moving inside first
and then a door or gate is one of you going out: inside means a sensor that
came on in the last two minutes, or one that came on in the last fifteen and is
still on, but not a weak one, which may be the dog. The doors and the yard are
then yours until fifteen minutes after your last sign out there. The same goes
for ten minutes after a resident arrives home or someone is let in. Anything
else that opens a door, window or gate counts in full. Inside (motion, lights,
the fridge, water) counts only in the five minutes after an entry that counted:
the intruder moving in. Hand unlocks, outages and power steps don't count at
night.

**Locks.** Lock Code Manager reports hand and code unlocks for every lock it
supports, and SIEM also reads Z-Wave JS lock notifications directly. Matter
locks report the code but not hand unlocks. A code the lock accepts lets
someone in: whoever typed it was given it, so SIEM doesn't need to know whose
it is. The same goes for Home Assistant unlocking a lock, or opening a garage
door, gate or door cover, from the app, a voice assistant, Apple Home or an
automation.

**Chains.** Some rules mean more after others, within five minutes in the
same incident: an entry (`exterior_door_opened` or `door_csi_motion`) then
`interior_occupied` scores 1.5 times; `gate_opened` then an entry 1.5 times;
`interior_occupied` then `light_physical`, `appliance_on` or
`interior_door_opened` 1.5 times; and anything after `manual_unlock` twice.

**Suppressors.** A resident or tracker arriving home switches the house to
family and takes off at least 60 points, or everything scored in the ten
minutes before if that is more: a phone that reports home a little after its
owner walked in explains what they set off. Letting someone in (a code, an
unlock or a garage opened from Home Assistant) takes 40 off, switches the house
to guest and records the code's name, when Lock Code Manager knows it, as the
incident's person.

**Labels.** Label an incident from `select.siem_label_last_incident`, the
`siem.label_incident` action, or the phone buttons. *False alarm* lowers the
weight of every rule in the incident by 10%, to no less than 0.3. *Real*
raises them by 10%, to no more than 1.5. *That's me* and *Guest* are recorded
and leave the weights alone: the sensors were right and presence detection was
late, and lowering the weights would only blunt the next real break-in.

**House mode.** Family while any resident or tracker is home and for 30
minutes after. Night instead of family while the household is in bed: while the
alarm panel you picked is armed night (pending or triggered keeps it), or, with
no panel picked, inside the night window, midnight to 5:30 unless you change
it. Guest during a `Guest:` event, or after someone was let in,
until two hours have passed and the house has been quiet for an hour. Quiet
means no doors, switches, water or appliances; motion doesn't count, so a pet
can't hold guest mode open. Service during a `Service:` event. Vacant
otherwise.
`select.siem_house_mode_override` forces a mode, and the choice survives
restarts.

**Recommended alarm mode.** Armed away while vacant, armed night inside the
night window when someone is home, and disarmed by day and during service
visits. It follows the clock, never the panel, so a panel that follows it
can't get stuck in armed night. SIEM only
publishes it, as `sensor.siem_recommended_alarm_mode`; it never arms or
disarms anything. If you want your panel to follow it, that's an automation
of your own.

**Alerts.** Verify raises an alert once per incident, and again if the score
doubles. Deter and alarm raise one every time the incident climbs to them. Break glass raises one
whatever the score: a hand unlock while vacant, a keypad lockout, or a sensor
unavailable for over an hour while vacant.

## In practice

These are the end-to-end scenarios in
[`tests/ha/test_scenarios.py`](tests/ha/test_scenarios.py), each run against a
whole house in a real Home Assistant. Points are the defaults, the house's night
window is 10 p.m. to 6 a.m., and the numbers in brackets are scores.

| What happens | House | What SIEM does |
| --- | --- | --- |
| A family evening: switches, the fridge, the kettle, the TV, kids in and out | Family | Nothing |
| A business trip: you away, your partner home using Apple Home, the kids home | Family: your partner's person entity follows their phone and watch | Nothing |
| The same trip with your partner not among the residents | Vacant | Alerts, until you set the mode to family |
| Kids in the yard and through the gate | Family | Nothing |
| Someone tries codes until the keypad locks out, 2 a.m. | Night | Verify and break glass |
| A kid comes home with their code | Family | Nothing |
| The mail carrier rings the doorbell | Vacant | Nothing (18) |
| A parcel at the door at 11 p.m. | Vacant | Verify (27) |
| A delivery through the side gate | Vacant | Verify (43) |
| Someone lingers in the backyard for 40 minutes at 1 a.m. | Vacant | Verify, once |
| Someone comes through the side gate at 1 a.m. | Vacant | Deter (64) |
| Gate, back door, kitchen, by day | Vacant | Alarm; the trigger a minute later |
| In through a window with no sensor: bedroom, hall, closet | Vacant | Verify, deter, alarm |
| The front door at 2 a.m., then the hall | Vacant | Deter, then alarm |
| A neighbor with a key nobody mentioned | Vacant | Break glass and alarm |
| Home through the garage, the phone 30 seconds late | Vacant, then family | Verify and alarm alerts, then the score drops to 0; the trigger never turns on |
| Home with the phone on time | Family | Nothing |
| Home at 11:30 p.m. with a code, the phone late | Vacant, then guest | Verify for someone on the porch at night, then nothing |
| The cleaner's code and three hours of cleaning | Guest | Nothing; vacant again an hour after they leave |
| A neighbor on the calendar as `Guest:` | Guest | Nothing |
| Unlocking for the plumber from the app | Guest | Nothing |
| Opening the garage from the app for a delivery | Guest | Nothing |
| The dog, on weak motion sensors, for six hours | Vacant | Nothing |
| The pet sitter leaves, then a break-in that night | Vacant | Alarm: the dog didn't hold guest mode open |
| Presence Simulation: lights, a smart plug, the TV | Vacant | Nothing |
| A sunset automation, a slow light, a scene by area | Vacant | Nothing |
| The app or Apple Home, from far away | Vacant | Nothing |
| A light switched by its own app, such as a Hue schedule | Vacant | Verify; see below |
| Z-Wave JS restarts | Vacant | Nothing |
| The Z-Wave stick dies on vacation | Vacant | Verify after two minutes, break glass after an hour |
| Someone lingers in the backyard at 1 a.m. while you sleep | Night | Verify, once |
| Someone comes through the side gate at 1 a.m. while you sleep | Night | Deter (64) |
| Gate, back door, kitchen, at 3 a.m. | Night | Alarm; the trigger a minute later |
| A window opens at 2:30 a.m. with nobody up, then motion in that room | Night | Deter, then alarm |
| Letting the dog out at 2 a.m. | Night | Nothing |
| Ten minutes in the kitchen, then out the back door | Night | Nothing |
| A kid up for water | Night | Nothing |
| Your partner home at 1 a.m., their phone on time | Night | Nothing |
| A teenager home at 11:45 p.m. with a code | Night | Verify for someone at the door in the dark, then nothing |
| A teenager sneaking out | Night | Nothing; see below |
| A burglar at the back door a minute after someone walked down the hall | Night | Nothing; see below |
| The panel armed night at 11:30 p.m. | Family, then night | Bedtime comes from the panel, not the clock |

## Known limits

- **Everyone who lives there needs a tracker.** If someone at home has none,
  the house reads vacant once the tracked people leave, and their footsteps
  are an intruder's. Add their phone as an extra tracker (a router or Wi-Fi
  integration works without the Home Assistant app), or set the mode by hand.
- **At night, the order of events is a judgment call.** Someone sneaking out
  reads as one of you going out, and so does a burglar who opens a door a
  minute after one of you walked down the hall. The other way round, one of you
  heading out without passing a sensor reads as someone coming in, so put a
  motion sensor on the way to each outside door. An armed-night alarm panel
  is still the backstop.
- **Late phones.** If your phone reports home after you're already inside, you
  get the alerts your arrival set off. The arrival cancels them, and the alarm
  trigger waits a minute for it, but a phone that's minutes late can still set
  off the panel. A larger home zone, or a Wi-Fi tracker too, helps.
- **Changes made outside Home Assistant** (a Hue or Lutron schedule, the
  vendor's app, Matter from another controller) leave no trace in Home
  Assistant and look like a hand on the switch. Make schedules in Home
  Assistant, or leave those lights out.
- **Power sensors are for appliances people switch on**: a TV, a kettle, a
  coffee maker. A fridge or a heater cycles on its own and will look like
  someone using it.
- **Pets** set off motion sensors. Set the ones they reach to weak.

## Entities and actions

| Entity | What it shows |
| --- | --- |
| `sensor.siem_risk_score` | The live score, with `top_contributors` and `incident_id` |
| `sensor.siem_tier` | `none`, `verify`, `deter` or `alarm` |
| `sensor.siem_incident` | The open incident's id, with `started`, `room`, `mode`, `person` and the `timeline` (not recorded) |
| `sensor.siem_house_mode` | `vacant`, `guest`, `service`, `family` or `night` |
| `select.siem_house_mode_override` | Force a mode, or `auto` |
| `sensor.siem_recommended_alarm_mode` | `armed_away`, `armed_night`, `armed_home` or `disarmed` |
| `binary_sensor.siem_night` | On inside the night window |
| `binary_sensor.siem_alarm_trigger` | On once an incident has held the alarm tier for a minute, until it drops |
| `select.siem_label_last_incident` | Label the open or most recent incident |
| `event.siem_incident` | `opened`, `tier_changed` and `closed`, for automations built in the UI |

Actions: `siem.label_incident`, `siem.run_digest`, `siem.reset_weights` and
`siem.set_house_mode`.

## Dry run with test entities

[`dev/siem_test_entities.yaml`](dev/siem_test_entities.yaml) is a package that
builds a fake house of `Test ...` entities: three rooms of sensors, lights and
power, a lock, a Lock Code Manager style event entity, two people, and scripts
that send Z-Wave lock notifications. It also has an automation that shows every
alert as a persistent notification. Copy it to `<config>/packages/`, restart,
create the three areas it names, and follow the setup answers at the top of
the file.

A simulated household then runs the house. Every two seconds each sensor rolls
dice, with odds that follow the time of day: quiet at night, a busy kitchen in
the morning, an empty house on weekdays with deliveries and a guest who lets
themselves in with a code, and a full house in the evening. Three helpers
control it: *Test Simulation* turns it off, *Test Sim Scene Override* forces a
time of day, and *Test Simulation Rate* speeds it up. Every sensor also has a
`(helper)` switch to force it on, and two scripts play a break-in and a
delivery. The file header walks through exact scores step by step.

## Adding a rule

1. In `core/rules.py`, add a `_rule(...)` line to `DEFAULT_RULES` with the
   id, the tag (`exterior` gets the night multiplier), points for vacant,
   guest, service, family and night, and a plain description. Add it to
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
in `tests/ha/` run the integration, the sample packages, the test package and
the end-to-end scenarios inside a real Home Assistant, pinned by
`pytest-homeassistant-custom-component`.
Without that plugin installed, only the core tests run. The badges track three
GitHub Actions workflows: tests, Home Assistant's hassfest checks, and HACS
validation.

## License

MIT, see [`LICENSE`](LICENSE).
