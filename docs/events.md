# Events

SIEM keeps its state in entities and announces everything else as events.
Everything that happens next is an automation of your own: the
[blueprints](blueprints.md), or one you write.

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

Lights, speakers or anything else your automations change in response never
count against you: SIEM sees that Home Assistant did it.

## `siem_notification`

Fires for every alert. Every field is always present, so templates need no
guards.

| Field | Type | What it holds |
| --- | --- | --- |
| `category` | string | `verify`, `deter`, `alarm`, `break_glass` or `digest` |
| `title` | string | A short title, such as `SIEM verify: Kitchen` |
| `message` | string | The alert as plain text: score, house mode (with *at night* when it is) and the latest events |
| `incident` | object or null | The incident, described below. Set for verify, deter and alarm, and for break glass while an incident is open |
| `snapshot` | string or null | The path of the room camera's snapshot, when the room has a camera |
| `again` | boolean | True for a second verify alert, sent because the score doubled |
| `label_url` | string or null | Where a chat button posts a label for this alert's incident; see [the label webhook](blueprints.md#the-label-webhook). Set when `incident` is, and Home Assistant knows its own address |
| `summary` | object or null | Digest only: `since`, `until`, `incident_count`, `labels`, `weight_changes` (a count), `counts` (one line of totals), `house_mode`, `forced` (whether the mode was set by hand) and `forced_since` |

When each category fires:

- `verify` once per incident, when it first reaches the verify tier, and again
  with `again` set if its score doubles while it is still at verify.
- `deter` and `alarm` every time an incident climbs to that tier.
- `break_glass` whatever the score: a hand unlock while vacant, a keypad
  lockout, or a sensor unavailable for over an hour while vacant.
- `digest` at each digest time, or when you run `siem.run_digest` (but not
  for a preview).

Snapshots go to `siem/` in your media folder, newest 200 kept. You can see them
in the media browser after you log in, and a phone notification can show one
as `/media/local/siem/<file name>`.

## `siem_incident`

Fires when an incident opens, changes tier, closes or is labelled. It carries
every field of the incident object below, plus:

| Field | Type | What it holds |
| --- | --- | --- |
| `kind` | string | `opened`, `tier_changed`, `closed` or `labelled` |
| `tier` | string | The tier after this change |
| `previous_tier` | string | The tier before it; the same as `tier` for `labelled` |
| `label` | string | `labelled` only: `false_alarm`, `thats_me`, `guest` or `real` |
| `by` | string or null | `labelled` only: who gave the label, when SIEM can tell. For a phone button, the name of the person entity linked to the user the app is logged in as; for a chat button, the chat user name |

`labelled` fires once per new label. A label the incident already has, from a
second press or a second phone, fires nothing. It also fires for an incident
that closed long ago, or one from before a restart, as long as SIEM still has
it in its history (the last 200); its `score` is then 0, `top_contributors`
empty, and the rest is as it was stored.

`event.siem_incident` fires on the same changes for automations built in the
UI. Its attributes are `event_type` (the `kind`), `incident_id`, `tier`,
`previous_tier`, `score`, `room` and `mode`, plus `label` for `labelled`.

## The incident object

| Field | Type | What it holds |
| --- | --- | --- |
| `incident_id` | string | Eight hex characters, such as `3f9a1c2b` |
| `tier` | string | `none`, `verify`, `deter` or `alarm` |
| `peak_tier` | string | The highest tier it reached |
| `score` | number | The live score; 0 once closed |
| `peak_score` | number | The highest score it reached |
| `room` | string or null | The room it started in |
| `area_id` | string or null | That room's Home Assistant area id, for `area_entities()` and area targets |
| `mode` | string | The house mode when it opened: who was home |
| `night` | boolean | Whether it was [night](scoring.md#night) when it opened: with someone home, they were in bed |
| `house_mode` | string | The house mode now |
| `person` | string or null | The Lock Code Manager slot name, when a code it manages was used |
| `started` | string | When it opened, as local ISO 8601 time |
| `closed` | string or null | When it closed, as local ISO 8601 time |
| `labels` | list of strings | The labels given so far |
| `entities` | list of strings | Every entity that has added points to the incident, in the order it first did |
| `top_contributors` | list of objects | Up to five rules driving the score now, each with `rule`, `points` and `entities`. Empty once closed |
| `timeline` | list of objects | The first ten events, each described below |

Each timeline entry has:

| Field | Type | What it holds |
| --- | --- | --- |
| `at` | string | When it happened, as local ISO 8601 time |
| `rule` | string | The rule id, or `family_arrival`, `guest_arrival` or `let_in` for a suppressor |
| `points` | number | Its points after chains, before weights and decay; negative for a suppressor |
| `entity_id` | string or null | The entity that set it off |
| `name` | string or null | That entity's friendly name |
| `room` | string or null | The room it happened in |
| `description` | string | The rule in plain words, such as `An exterior door or window opened` |
| `detail` | string | A short note, such as `opened` or `code used by Pat` |

## Labelling

Four ways to label an incident, all with the same effect:

- A button on a notification from the [phone or Mattermost
  blueprints](blueprints.md#labelling-from-a-notification), which labels the
  incident that notification is about.
- `select.siem_label_last_incident` on the device page, which labels the open
  or most recent incident.
- The `siem.label_incident` action, with a `label` and an optional
  `incident_id` (the open or most recent incident without one).
- Your own actionable notification, with an action named
  `SIEM_LABEL_<LABEL>|<incident id>`, such as
  `SIEM_LABEL_FALSE_ALARM|3f9a1c2b`. SIEM listens for the companion app's
  `mobile_app_notification_action` event itself, so no automation has to
  catch the press.

What each label does to the weights is under
[How scoring works](scoring.md#labels).

## The digest

At each digest time, SIEM writes up everything since the previous digest and
sends it as a `digest` notification. With an AI task picked, it is written in
plain English; without one, it is raw counts. Either way it ends with the house
mode, and says so while a mode is forced, with the date it was set.

`siem.run_digest` writes one right away, sends it, and also returns it as the
action's response (with `message`, `ai_task_entity` and `summary`). Two
optional fields help compare AI models:

- `ai_task_entity` writes this one digest with another AI task than the
  configured one. The response's `ai_task_entity` says which one wrote it,
  and is empty when it fell back to raw counts.
- `preview: true` only returns the digest. Nothing is sent and the digest
  period doesn't move on, so you can have the same stretch written again by
  another model.

```yaml
action: siem.run_digest
data:
  ai_task_entity: ai_task.claude
  preview: true
response_variable: digest
```
