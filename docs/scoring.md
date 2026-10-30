# How scoring works

The scoring model is opinionated, and it lives in code: which rules exist,
what sets them off, how they chain, the suppressors, the house mode timings
and how labels learn. **Configure** lets you change a few numbers when the
defaults don't suit your house: each rule's points per house mode, the tier
thresholds, the half-life and the chain factors. Anything more means editing
`core/rules.py` (see [Adding a rule](development.md#adding-a-rule)). To see
why something did or didn't score, turn on **Enable debug logging** on the
integration's page. The reasoning behind each rule's points is in [Sensors,
settings and scores](sensors.md).

## What physically happened

SIEM only cares about Home Assistant users for one thing: telling what Home
Assistant did from what happened in the house. A hand on a switch, a door, a
person in a room count. Anything Home Assistant did never counts: an
automation or script on any trigger, you in the app, Alexa or Google Assistant
through Home Assistant Cloud, Apple Home through HomeKit Bridge, or an
integration such as [Presence
Simulation](https://github.com/slashback100/presence_simulation). Every one of
those reaches the house through a service call, and every state change it
causes carries the call's context. Two kinds of change carry no context of
their own, so SIEM links them back: a light that reports back slowly after
Home Assistant switched it (within 30 seconds), and an appliance whose power
climbs after Home Assistant switched something in the same room (within two
minutes), like a lamp's smart plug or a TV through its integration.

## What never counts

An entity coming back after a restart or a reconnect, even if it comes back
on; only a real off-to-on change counts. A sensor that is unavailable for less
than two minutes.

## The score

Each event adds `points × weight`, halving every 15 minutes. The score is the
sum, capped at 100. Verify starts at 20, deter at 50 and alarm at 80. An
incident opens with the first event that scores, collects every event within
five minutes of the last one (or while its score is still above 5), and closes
after 30 minutes below 5. The same entity scores the same rule at most once
every five minutes, so a door used to come in and to go out is one visit, and
lights count once per room, because one switch can turn on a whole group of
bulbs.

## Rules

Points are for the house modes vacant, guest, service and family, and a fifth
column for [night](#night) with the family or guests home, when they are in
bed. With anyone trusted home and awake, SIEM stays out of the way: only lock
trouble scores. At night it watches the house again; see below. Rules marked
*exterior* score 1.5 times as much at night, whoever is home.

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

## Someone in a room

Camera person detection (an occupancy sensor with *person* in its name),
occupancy, presence and Bayesian sensors are strong, motion sensors medium
(60% of the points), sound sensors weak (30%). You can change an entity's
strength in **Configure**. A room scores once per five minutes at the level of
its strongest sensor, times 1.3 when two sensors agree within a minute. A weak
sensor alone never opens an incident while the house is vacant, which is what
to do with motion sensors a pet sets off.

## Someone outside

In an outdoor room, motion, person detection, a light that turns itself on (a
floodlight's own sensor) and contacts such as a shed or mailbox all mean the
same thing: someone is outside. The whole outdoors counts once per fifteen
minutes, at its strongest source, times 1.3 when two agree. A visit to the
front door is a few points; someone hanging around builds up slowly; someone
who also opens the gate or a door is another matter. Power sensors in outdoor
rooms are not used.

## At night, with someone home

At night with the family or guests home, they are in bed, and SIEM watches the
yard, the doors and the windows the way it watches an empty house. It tells
one of you from an intruder by the order of events. Someone moving inside first and then a
door or gate is one of you going out: inside means a sensor that came on in
the last two minutes, or one that came on in the last fifteen and is still on,
but not a weak one, which may be the dog. The doors and the yard are then
yours until fifteen minutes after your last sign out there. The same goes for
ten minutes after a resident or guest arrives home or someone is let in.
Anything else that opens a door, window or gate counts in full. Inside
(motion, lights, the fridge, water) counts only in the five minutes after an
entry that counted: the intruder moving in. Hand unlocks, outages and power
steps don't count. An empty house at night needs none of this: everything
counts, as it does by day, with the doors and the yard 1.5 times.

## Locks

Lock Code Manager reports hand and code unlocks for every lock it supports,
and SIEM also reads Z-Wave JS lock notifications directly. Matter locks report
the code but not hand unlocks. A code the lock accepts lets someone in:
whoever typed it was given it, so SIEM doesn't need to know whose it is. The
same goes for Home Assistant unlocking a lock, or opening a garage door, gate
or door cover, from the app, a voice assistant, Apple Home or an automation.

## Chains

Some rules mean more after others, within five minutes in the same incident:
an entry (`exterior_door_opened` or `door_csi_motion`) then
`interior_occupied` scores 1.5 times; `gate_opened` then an entry 1.5 times;
`interior_occupied` then `light_physical`, `appliance_on` or
`interior_door_opened` 1.5 times; and anything after `manual_unlock` twice.

## Suppressors

A resident or tracker arriving home switches the house to family and takes off
at least 60 points, or everything scored in the ten minutes before if that is
more: a phone that reports home a little after its owner walked in explains
what they set off. A guest's tracker arriving does the same and switches the
house to guest; a phone joining your Wi-Fi usually does so a little after its
owner walks in. Letting someone in (a code, an unlock or a garage opened from
Home Assistant) takes 40 off, switches the house to guest and records the
code's name, when Lock Code Manager knows it, as the incident's person.

## Labels

Label an incident from the buttons on its notifications, from
`select.siem_label_last_incident`, or with the `siem.label_incident` action
([all the ways](events.md#labelling)). *False alarm* lowers the weight of
every rule in the incident by 10%, to no less than 0.3. *Real* raises them by
10%, to no more than 1.5. *That's me* and *Guest* are recorded and leave the
weights alone: the sensors were right and presence detection was late, and
lowering the weights would only blunt the next real break-in.

An incident counts each label once. Pressing *False alarm* on two phones, or
twice on one, lowers the weights once. The changes, and which incident and
label made them, are kept (the last 200) and counted in the digest;
`siem.reset_weights` puts every weight back to 1.0.

## House mode

The house mode is who is home. Family while any resident or tracker is home
and for 30 minutes after. Guest while any guest's device tracker is home and
for 30 minutes after, the same grace a resident gets. Also guest during a
`Guest:` event or while a guest sensor is on, and after either one ends or
someone was let in, until two hours have passed and the house has been quiet
for an hour. Quiet means no doors, switches, water or appliances; motion
doesn't count, so a pet can't hold guest mode open. Service during a
`Service:` event or while a service sensor is on, but never inside the night
window: nobody works in the house at 2 a.m., so the house is vacant then. The
calendar and the sensors add up: either one is enough. Vacant otherwise.
`select.siem_house_mode_override` forces a mode, and the choice survives
restarts until you set it back to auto. Every digest ends with the house mode,
and says so while a mode is forced, with the date it was set.

## Night

Night isn't a house mode: it adjusts whichever mode the house is in, and
`binary_sensor.siem_night` shows it. Who is home decides where it comes from:

| Who is home | It is night while |
| --- | --- |
| The family | The bedtime sensor you picked is on, or the alarm panel you picked is armed night (either one counts; pending or triggered keeps the panel's). The night window stands in only when you picked neither, or for one that is unavailable. |
| Only guests | Inside the night window. Guests rarely have a bedtime sensor or arm the panel, so the clock decides; if the sensor is on or the panel is armed night, that only makes it night sooner, and nothing ends it before the window does. |
| Nobody, or a contractor | Inside the night window. Service mode never holds inside it, so the house is vacant then. |

The night window is your household's usual night hours, midnight to 5:30
unless you change it.

What night changes:

- **Outdoor rules count 1.5 times,** whoever is home.
- **With the family or guests home,** rules score their night points (the
  fifth column above) and the order of events decides what counts; see
  [At night, with someone home](#at-night-with-someone-home).
- **A weak sensor alone can't open an incident,** the same as in an empty
  house, so the dog padding about doesn't start one.

A forced mode says who is home, not that SIEM should stop watching: a forced
family or guest still has its night. A forced service or vacant stays exactly
that, with the night window deciding night.

## Recommended alarm mode

Armed away while vacant, armed night inside the night window when someone is
home, and disarmed by day and during service visits. It follows the night
window, not night: night with the family home follows the panel, and a panel
that followed a recommendation that follows the panel could get stuck in
armed night.
SIEM only publishes it, as `sensor.siem_recommended_alarm_mode`; it never arms
or disarms anything. If you want your panel to follow it, that's an automation
of your own.

## Alerts

Verify raises an alert once per incident, and again if the score doubles.
Deter and alarm raise one every time the incident climbs to them. Break glass
raises one whatever the score: a hand unlock while vacant, a keypad lockout,
or a sensor unavailable for over an hour while vacant.