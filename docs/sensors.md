# Sensors, settings and scores

The setup flow keeps its labels short. This page is the long version: what
each setting is for, why it sits where it does, and why its rule scores what
it scores. [How scoring works](scoring.md) has the rules table
and the mechanics; this page explains the thinking behind them.

## Reading the points

Every event adds points, the points fade by half every 15 minutes, and the
sum is the score, capped at 100. Three thresholds turn the score into tiers:

| Tier | From | Meaning |
| --- | --- | --- |
| Verify | 20 | Worth a look. A notification, nothing more. |
| Deter | 50 | Worth turning the lights on. Someone is probably there. |
| Alarm | 80 | Worth the siren. Someone is almost certainly inside. |

The points were set backwards from those tiers, by asking how many signs it
should take to reach each one in an empty house:

- **One sign at the edge of the house is a verify.** A door or a window
  opening (40) is worth a look, but on its own it could be a sensor glitch,
  a gust, or someone with a key whose phone hasn't reported home yet.
- **One strong sign of someone inside is a deter.** A presence sensor in a
  room (50) is hard to explain away when nobody is home.
- **A sign at the edge and a sign inside is an alarm.** The door (40), then
  someone in the next room (50, times 1.5 for following an entry) is 115.
- **Outside on its own stays low.** People come to your door all the time.
  A visit from the mail carrier should not reach verify; someone hanging
  around for a quarter of an hour, or coming through the gate, should.

Points are given per house mode, in the order vacant, guest, service,
family, and a fifth column for night with the family or guests home, when
they are in bed. Most rules score only when the house is vacant or at night;
see [the other modes](#why-the-other-modes-score-almost-nothing).
Rules tagged *exterior* (doors, gates, the Wi-Fi motion at a door, someone
outside) count 1.5 times at night: someone at your back door at 3 a.m. is
more unusual than at 3 p.m. Rules about the inside of the house don't get the
multiplier, because someone inside an empty house is just as wrong at noon.

Labels move the weight of each rule between 0.3 and 1.5: *false alarm*
lowers every rule in the incident by 10%, *real* raises them. *That's me* and
*guest* change nothing, because the sensors were right; it was presence
detection that was late, and lowering the weights would blunt the next real
break-in.

## Room settings

Each room is a Home Assistant area. Everything picked for a room scores in
that room, and the room is what alerts are named after and what the
deterrence package lights up.

### Outdoors

A tick for yards, porches, driveways and the like. Rooms named like one
(yard, porch, patio, driveway, garden, deck, balcony, pool, outside) start
ticked. In an outdoor room, motion, person detection, a light that turns
itself on (a floodlight's own sensor) and contacts such as a shed door or a
mailbox all mean one thing: someone is outside.

That is the `exterior_occupied` rule, 10 points, and it counts once per
fifteen minutes for the whole outdoors, however many outdoor sensors fire,
at the level of the strongest one and times 1.3 when two agree. Treating the
outdoors as one place is what keeps a delivery quiet: the driveway, the
doorbell camera and the porch light are one visit, not three. Someone who
stays outside keeps getting credited every fifteen minutes and builds up to a
verify.

Power sensors in outdoor rooms are not used. Outdoor loads (pool pumps,
fountains, heaters) run on their own.

### Occupancy sources

Motion, occupancy, presence and sound sensors, and camera person detection
(any occupancy sensor with *person* in its name). They score
`interior_occupied`, 50 points, scaled by the source's strength:

| Strength | Share | Sources |
| --- | --- | --- |
| Strong | 100% | Person detection, occupancy and presence sensors (mmWave and the like), Bayesian sensors |
| Medium | 60% | Motion sensors |
| Weak | 30% | Sound sensors |

Strength is about how sure a source is that a *person* is there. A presence
sensor that sees someone breathing, or a camera that sees a person, is close
to certain. A PIR motion sensor sees a cat as readily as a burglar. A sound
sensor hears the dishwasher.

A room counts once per five minutes, at its strongest source, and times 1.3
when two sources agree within a minute. A weak source alone never opens an
incident in an empty house, which is what makes *weak* the right setting for
any sensor a pet can reach: the dog alone can never start an incident, but
its sensors still add to one a door has already started. You can change any
source's strength in **Configure**.

### Exterior doors, windows and gates

Contacts on the outside of the house. A door or window scores
`exterior_door_opened`, 40 points: a verify alone, and the start of most
alarms. A contact with *gate* in its name scores `gate_opened`, 30 instead,
because a gate is outside the house itself, and a gate followed by a door
within five minutes makes that door count 1.5 times.

The same contact scores at most once every five minutes, so a door used to
come in and to go out is one visit, and a bouncing contact is one opening.

### Fridge, cabinet, drawer and closet contacts

Contacts inside the house, recognised by name (fridge, freezer,
refrigerator, pantry, cabinet, cupboard, drawer, closet). They score
`interior_door_opened`, 40 points. Nobody opens your fridge or your bedroom
closet while the house is empty, a pet can't, and a burglar going through
drawers is exactly what this catches. After someone was seen in a room, these
count 1.5 times.

### Lights

`light_physical`, 45 points, when a light is switched on at the wall. It sits
just under deter because a light is strong evidence of a hand on a switch,
but not quite proof: a light can also be switched by something Home Assistant
never sees, such as a Hue or Lutron schedule or the vendor's app. One switch
can light a whole group of bulbs, so lights count once per room.

Anything Home Assistant switched never counts, including a light that reports
back slowly after a command and lights in an outdoor room (those count as
someone outside instead).

### Appliance power sensors

`appliance_on`, 35 points, when a room's power sensor rises above its
threshold (30 W by default). Pick sensors on things people switch on by hand:
a TV, a kettle, a coffee maker, a hair dryer. Don't pick a fridge, a freezer,
a heater or a dehumidifier: they cycle on their own and would look like
someone using them.

A power reading carries no record of what caused it, so SIEM links it back:
when Home Assistant switched anything in the same room in the two minutes
before (a lamp's smart plug, a TV through its integration), the rise is
Home Assistant's doing and doesn't count.

### Camera

Only for snapshots: when an alert names a room with a camera, a snapshot goes
with it. The camera entity itself never scores. Person detection comes from
the person-detection sensor your camera integration provides, picked as an
occupancy source.

## Whole-house settings

These settings belong to the house rather than to a room: either the device
measures the whole house, or what it tells SIEM changes how the whole house
is read.

### Residents, extra trackers and guests' trackers

These decide the house mode, so they decide what everything else means.

- **Residents** are person entities. SIEM reads each person's device
  trackers from the person and follows them as you add or remove trackers.
- **Extra trackers** are device trackers that also mean a resident is home
  without belonging to a person: a car's tracker, a phone seen by the
  router.
- **Guests' trackers** are device trackers of people who don't live there, a
  regular visitor's phone on your Wi-Fi for example. While one is home the
  house is in guest mode.

Any resident home is family mode, and it lingers 30 minutes after the last
one leaves, so a phone that drops off Wi-Fi or a quick run to the shop
doesn't leave an empty house. Guests' trackers get the same 30 minutes.

An arrival also cancels what was scored in the ten minutes before it (at
least 60 points), because a phone often reports home a little after its
owner walked in. A resident's or a guest's phone joining the Wi-Fi in the
hallway explains the door and the hall motion that came just before.

Everyone who lives there needs a tracker. If someone at home has none, the
house reads empty once everyone tracked has left, and their footsteps look
like an intruder's.

### Wi-Fi (CSI) motion sensors

A CSI sensor (an ESP32 running ESP-CSI or ESPectre) notices motion from
changes in the Wi-Fi signal between two points. Placed at a door, it notices
someone standing there.

These are whole-house settings, each one paired with the door contact it
watches, because a CSI sensor watches a doorway, not a room. Its signal
crosses the door, so it sees people on both sides of it; picked as room
occupancy, it would call a delivery on the porch "someone in the hall". What
it's for is the one thing a contact can't tell you: someone at a door that
did not open.

`door_csi_motion` fires only when the paired door is closed and hasn't opened
in the last minute, and it scores 5 points. That is deliberately small:
someone at your front door is ordinary (deliveries, neighbours, canvassers).
It matters in combination. Someone at the door, and then a window round the
side opening, is an incident; and at night, with nobody up inside, those 5
points count 1.5 times.

### Water flow sensor

A flow meter on the main supply (a Flume, a Phyn, a Moen Flo, a pulse meter)
measures the whole house, so it's a whole-house setting. Water running above
the threshold scores `water_flow`, 30 points: in an empty house, someone is
running a tap, a shower or a toilet.

One field is enough, and it should only hold meters people's use shows up
on. Leave out irrigation meters: sprinklers run on schedules, so they'd only
ever look like someone at the tap.

### Whole-house power and loads that run on their own

An optional whole-house power sensor (from a CT clamp, a smart meter, an
energy monitor) catches what the room power sensors miss: something switched
on that isn't instrumented, like an oven, a space heater or a hair dryer.
The trouble is that a house is full of things that switch themselves on.

So you list the power sensors of **loads that run on their own** (an EV
charger, a heat pump, a pool pump, a water heater) and SIEM subtracts them.
They are never used for detection; they are what lets the rest be used.
What's left, the residual, is watched for a step up of at least 100 W
(*unexplained power step*) that lasts at least five minutes (*step must
last*). That scores `load_residual`, 10 points, once per step.

It scores low because it's indirect: a fridge's defrost cycle or a dryer you
forgot to list can produce the same step. On its own it never alerts; it
backs up other signs.

### Locks

Locks are whole-house settings for three reasons:

- **What a lock reports arrives as an event, not as room state.** Hand
  unlocks, code unlocks and lockouts come from Z-Wave JS notifications and
  Lock Code Manager events, which name the lock (or its device) and nothing
  else.
- **What a lock says is about the house, not a room.** "Someone used a code"
  or "someone turned the lock by hand" matters wherever the lock happens to
  be.
- **Its results change the house mode.** A code the lock accepts, or Home
  Assistant unlocking it, lets someone in and puts the house in guest mode.

How each lock event scores:

- **A hand unlock** (a key from outside, or the thumb turn from inside)
  while the house is empty scores `manual_unlock`, 60 points, and sends a
  break-glass message. Either a resident whose phone is
  late, or someone with a key you didn't tell SIEM about, or someone who
  shouldn't have one. Everything in the next five minutes counts twice.
- **A code the lock accepts** lets someone in: whoever typed it was given
  it, so SIEM doesn't need to know whose it is. The house goes to guest mode
  and 40 points come off the open incident.
- **A keypad lockout** after repeated bad codes scores `keypad_lockout`, 40
  (30 with the family home), and sends a break-glass message. A single
  wrong code is a typo and doesn't count. Few locks report lockouts.

Lock state changes themselves don't score; the lock's own reports are more
precise.

### Lock Code Manager event entities

Optional. Lock Code Manager's per-slot "credential used" entities give SIEM
the name of whoever's code was used, for the incident's `person`, and they
say when a slot has been switched off. A disabled code that still opens the
lock scores `pin_not_allowed`, 30 points (20 with the family home): codes are
usually removed from the lock when switched off, so this means the lock and
Lock Code Manager disagree.

### Calendar, guest sensors and service sensors

Optional. These are how you tell SIEM about the cleaner, the pet sitter, the
plumber. Guests' trackers and lock codes do the same without either.

- **Calendar:** an event whose title starts with `Guest:` puts the house in
  guest mode for the event, then until two hours after it and an hour of
  quiet; `Service:` puts it in service mode for the event only.
- **Guest and service sensors:** any binary sensor, helper or schedule that
  is on while guests are staying or someone is working in the house. A guest
  sensor works like a `Guest:` event that lasts while it's on, so guest mode
  carries on for two hours after it turns off, and an hour of quiet. A
  service sensor works like a `Service:` event and ends when it turns off.
  One that is unavailable counts as off, so the house is watched again.

**They are a union.** Pick a calendar and sensors and either one is enough:
a `Service:` event for the plumber and a cleaners'-day sensor both put the
house in service mode, each for its own stretch. If you pick several sensors,
any one on counts.

**A Workday sensor is on all day.** The
[Workday](https://www.home-assistant.io/integrations/workday/) integration set
to the cleaners' weekday is a simple way to say when they come, and it skips
holidays. But it's on from midnight to midnight. Service mode waits for the
night window to end, since nobody cleans at 2 a.m., but from then until
midnight the house is in service mode, and in service mode only lock trouble
scores: the house isn't watched that day, before or after they leave. If they
come for a morning, a
[schedule](https://www.home-assistant.io/integrations/schedule/) helper set
to their hours keeps the rest of the day watched. To keep Workday's holidays
too, a template binary sensor can combine the two:

```yaml
template:
  - binary_sensor:
      - name: Cleaners here
        state: >-
          {{ is_state('binary_sensor.cleaners_day', 'on')
             and today_at('09:00') <= now() < today_at('13:00') }}
```

### Night: the alarm panel, a bedtime sensor and the night window

These three decide when it is night, which `binary_sensor.siem_night` shows.
Night isn't a house mode: the house stays whatever it is, and night adjusts
how it is scored. Who is home decides which of the three count.

- **Alarm panel:** armed night means everyone is in bed. Pending or triggered
  keeps whatever it was, so a break-in in progress doesn't end the night.
  SIEM only reads it; it never arms or disarms anything.
- **Bedtime sensor:** any binary sensor or helper of your own that is on when
  everyone is in bed, for example one that weighs bedroom presence, the time
  and the lights.
- **Night window:** your household's usual night hours, midnight to 5:30
  unless you change it.

**With the family home, the panel and the sensor are a union, and the night
window is a fallback.** If you pick both, either one saying bed is enough.
The night window decides only when you pick neither, or in place of one that
is unavailable until it's back. It never adds to a source that can tell: with
a bedtime sensor that says everyone is up at 1 a.m., it isn't night, whatever
the clock says.

**With only guests home, the night window counts as well,** since your
bedtime sensor probably follows your own household and nothing says when
guests go to bed. Watching the house at night still lets people move about
inside, so a house-sitter up at 3 a.m. for water isn't an intruder; someone
coming in from outside with nobody up first is.

**With nobody home, the night window decides alone.** Nobody is in bed, but
someone at your back door at 3 a.m. is still more unusual than at 3 p.m.

The night window also does two things whoever is home:

- It sets the recommended alarm mode: armed night inside it when someone is
  home. It follows the window rather than night, because night with the
  family home follows the panel, and a panel that followed a recommendation
  that follows the panel could get stuck in armed night.
- Service mode doesn't hold inside it: nobody works in the house at night, so
  a calendar event or a service sensor that is still on (a Workday sensor
  turns on at midnight) leaves the house vacant until the window ends.

## How night reads a house with someone home

At night with the family or guests home, they are in bed. SIEM watches the
yard, the doors and the windows the way it watches an empty house, and
ignores the inside, where they are. It tells one of you from an intruder by
the order of events:

- **Someone moving inside, then a door or gate, is one of you going out.**
  "Moving inside" means an inside sensor that came on in the last two
  minutes, or one that came on in the last fifteen and is still on. Weak
  sources don't count, since they may be the dog, and neither does a source
  that has been on for hours, like a bedroom presence sensor watching people
  sleep. The doors and the yard are then yours until fifteen minutes after
  your last sign out there.
- **Outside first, or nothing at all, then a door or window, is someone
  coming in,** and it counts in full.
- **The inside counts only in the five minutes after an entry that counted:**
  the intruder moving in.
- A resident or guest arriving home, or someone let in, makes the doors and
  the yard theirs for ten minutes.

Put a motion sensor on the way to each outside door. Without one, one of you
letting the dog out looks like someone coming in.

## What never scores

- **Anything Home Assistant did.** Automations, scripts, you in the app,
  voice assistants, Apple Home through HomeKit Bridge, Presence Simulation.
  Each reaches the house through a service call whose context the resulting
  state changes carry. Users only matter to SIEM for this one distinction.
- **An entity coming back** after a restart or a reconnect, even if it comes
  back on, and a sensor unavailable for less than two minutes. A sensor that
  stays unavailable longer scores `sensor_offline`, 20 points in an empty
  house, all of them together as one, and if the house is still empty an hour
  later, a break-glass message.
- **Lock state changes, cameras, and power sensors in outdoor rooms,** for
  the reasons above.

## Why the other modes score almost nothing

With anyone trusted at home and awake (family, guest or service mode), the
house is supposed to be busy. Doors open, lights go on, the fridge gets
raided. Scoring that would only teach you to ignore SIEM, so in those modes
only lock trouble scores: a disabled code, a keypad lockout. Guest and
service modes are how you tell SIEM that the activity is expected even with
everyone away. Night is the exception, described above, because whoever is
home is no longer watching: the family or guests in bed are watched for like
an empty house. Service mode never lasts into the night, so a house with only
a contractor's day on the calendar is vacant, and watched, after dark.

## Seeing it happen

Turn on **Enable debug logging** on the integration's page, and SIEM logs one
line for each thing it weighs: a door opening, motion starting, a light
switched on, a power sensor crossing its threshold. Raw readings that change
nothing, such as a power sensor ticking along below its threshold, aren't
logged. Each line says what scored, or why it didn't:

```
binary_sensor.back_door scored exterior_door_opened +40.0 (opened)
binary_sensor.back_door not scored as exterior_door_opened: already counted in the last 5 minutes
light.kitchen not scored: Home Assistant made the change
binary_sensor.fridge_door not scored as interior_door_opened: guest mode gives it 0 points
binary_sensor.back_door not scored as exterior_door_opened: night, and someone was up inside first: someone going out
binary_sensor.kitchen_presence not scored as interior_occupied: night, and the inside only counts right after an entry
House mode vacant -> guest
Night starts (guest mode)
```
