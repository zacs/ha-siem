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
- **Four house modes, and bedtime.** Family, guest, service and vacant, worked
  out from presence (yours and your guests'), a calendar or sensors, and lock
  codes. Bedtime, from your alarm panel, a sensor or the clock, turns a busy
  house into a watched one. The same open door means something different in
  each.
- **Plain Home Assistant state and events.** Sensors for the score, tier,
  incident and house mode, and an event for every alert.

## Requirements

- Door, window or motion sensors, assigned to areas.
- A device tracker for everyone who lives there, so SIEM knows when someone is
  home. Residents are person entities; anyone without a Home Assistant login
  can be an extra tracker, such as their phone seen by your router.
- Automations that do something with SIEM's alerts. The
  [blueprints and packages](#blueprints) are a starting point.

## Nice to haves

Each of these adds something. None of them is required.

| Add | What you get |
| --- | --- |
| An alarm panel, such as [Alarmo](https://github.com/nielsfaber/alarmo) | Add `binary_sensor.siem_alarm_trigger` to it and SIEM's alarm tier sets off your alarm. Pick it in setup and arming it night tells SIEM everyone's in bed; SIEM only reads it. |
| [Lock Code Manager](https://github.com/raman325/lock_code_manager) (LCM) | Codes and hand unlocks from any lock LCM supports, with the code's name on the incident, and an alert when a code LCM has switched off still opens the lock. Z-Wave JS locks report codes and hand unlocks without it. |
| A calendar, such as [Local Calendar](https://www.home-assistant.io/integrations/local_calendar/) | `Guest:` and `Service:` on event names set the house mode. |
| A [Workday](https://www.home-assistant.io/integrations/workday/) sensor, a schedule or a helper | Guest or service mode while it's on, such as on the cleaners' day. |
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
- **Whole house.** Residents, extra trackers, guests' device trackers, the
  water and power sensors, locks, Lock Code Manager event entities, the
  calendar and guest and service sensors, the alarm panel and a bedtime sensor
  to read bedtime from, the night window, and Wi-Fi motion sensors with the
  door each one watches.
- **Digest.** The AI task and the digest times.

You can change any of it later from the integration's **Configure** menu.
[Sensors, settings and scores](docs/sensors.md) explains what each setting is
for and why it sits where it does.

Two things live outside the flow:

- **Guest and service events.** On the calendar you picked, an event whose
  title starts with `Guest:` puts the house in guest mode, and `Service:` in
  service mode. A guest or service sensor that is on does the same, and
  either the calendar or a sensor is enough. Guest mode ends two hours after
  the event or the sensor, or later if the house hasn't been quiet for an
  hour by then. Service mode ends with the event or the sensor.
- **The alarm trigger.** To have SIEM set off your alarm, add
  `binary_sensor.siem_alarm_trigger` to your panel as an always-on sensor (in
  Alarmo, type *other*). It turns on once an incident has stayed at the alarm
  tier for a minute, which gives a phone that reports home a little late the
  time to call it off, and off when the incident drops below alarm.

## Blueprints

SIEM fires events; these turn them into notifications and lights. Import one,
pick your phones or lights, and save. [Blueprints](docs/blueprints.md) has
every input, and what Mattermost needs for its buttons to work. Prefer plain
YAML you keep under source control? The same four are in
[`packages/`](packages).

| Blueprint | What it does | Import |
| --- | --- | --- |
| SIEM alerts to phones | Pushes alerts to phones with label buttons; the notification updates when someone answers | [![Import](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/create-link/?redirect=blueprint_import&blueprint_url=https%3A%2F%2Fgithub.com%2Fzacs%2Fha-siem%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fsiem%2Fmobile_app.yaml) |
| SIEM escalation | Tells more phones, then runs your actions, when nobody answers in time | [![Import](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/create-link/?redirect=blueprint_import&blueprint_url=https%3A%2F%2Fgithub.com%2Fzacs%2Fha-siem%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fsiem%2Fescalation.yaml) |
| SIEM deterrence | Lights the room at deter and the house at alarm, plus a siren or anything else you add | [![Import](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/create-link/?redirect=blueprint_import&blueprint_url=https%3A%2F%2Fgithub.com%2Fzacs%2Fha-siem%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fsiem%2Fdeterrence.yaml) |
| SIEM alerts to Mattermost | Posts alerts, with the timeline and snapshot, to a channel with label buttons | [![Import](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/create-link/?redirect=blueprint_import&blueprint_url=https%3A%2F%2Fgithub.com%2Fzacs%2Fha-siem%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fsiem%2Fmattermost.yaml) |

**Answering an alert.** Each alert's buttons (*False alarm*, *That's me*,
*Real*, *Guest*) label the incident that alert is about, however many alerts
came since. Once it's labelled, the notification changes to say who answered
and how, so you know which ones are dealt with. SIEM learns from the label,
and the escalation blueprint stops.

## Alerts and events

SIEM keeps its state in entities and announces everything else as two events:

- `siem_notification` for every alert: verify, deter, alarm, break glass and
  the digest, with a title, a plain-text message and the incident.
- `siem_incident` when an incident opens, changes tier, closes or is
  labelled.

[Events](docs/events.md) lists every field, with an example automation.
Lights, speakers or anything else your automations change in response never
count against you: SIEM sees that Home Assistant did it.

## How scoring works

Every sensor event that physically happened adds points, which halve every
15 minutes. The sum is the score: verify from 20, deter from 50, alarm from
80. The points depend on the house mode, so a door opening scores 40 in an
empty house and nothing while the family is home and awake. Some events count
more after others (a door, then motion inside), and anything Home Assistant
did itself counts for nothing. Labels nudge the weights of the rules involved
up or down.

- [How scoring works](docs/scoring.md): the rules and their points, chains,
  suppressors, house modes and bedtime, in detail.
- [Sensors, settings and scores](docs/sensors.md): why each rule scores what
  it does, and what each setting is for.
- [In practice](docs/scenarios.md): about fifty end-to-end scenarios, from the
  mail carrier to a break-in at 3 a.m., and what SIEM does in each.

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
| `sensor.siem_incident` | The open incident's id, with `started`, `room`, `mode`, `person`, `entities` (every entity that has added to the score, recorded in history) and the `timeline` (not recorded) |
| `sensor.siem_house_mode` | Who is home: `vacant`, `guest`, `service` or `family` |
| `select.siem_house_mode_override` | Force a mode, or `auto` |
| `sensor.siem_recommended_alarm_mode` | `armed_away`, `armed_night`, `armed_home` or `disarmed` |
| `binary_sensor.siem_night` | On inside the night window |
| `binary_sensor.siem_bedtime` | On while whoever is home, family or guests, is in bed |
| `binary_sensor.siem_alarm_trigger` | On once an incident has held the alarm tier for a minute, until it drops |
| `select.siem_label_last_incident` | Label the open or most recent incident; a notification's buttons label their own |
| `event.siem_incident` | `opened`, `tier_changed`, `closed` and `labelled`, for automations built in the UI |

Actions: `siem.label_incident`, `siem.run_digest` (which can also try another
AI task, or preview without sending; see [the digest](docs/events.md#the-digest)),
`siem.reset_weights` and `siem.set_house_mode`.

## More

- [Blueprints](docs/blueprints.md): each blueprint, labelling from
  notifications, and SIEM's label webhook. [Packages](packages/README.md):
  the same automations as plain YAML.
- [Events](docs/events.md): every field of SIEM's events, labelling and the
  digest.
- [How scoring works](docs/scoring.md),
  [Sensors, settings and scores](docs/sensors.md) and
  [In practice](docs/scenarios.md).
- [Development](docs/development.md): running the tests, a dry run with a fake
  house, and adding a rule.

## License

MIT, see [`LICENSE`](LICENSE).
