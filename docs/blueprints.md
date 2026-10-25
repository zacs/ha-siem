# Blueprints

SIEM never acts on its own. It fires events, and what happens next is an
automation of yours. The blueprints in
[`blueprints/automation/siem/`](../blueprints/automation/siem) are ready-made
versions of the automations most houses want. Import one, pick your phones or
lights, and save. You can edit or replace any of them later; SIEM doesn't
care where its events go.

| Blueprint | What it does | Import |
| --- | --- | --- |
| [SIEM alerts to phones](#siem-alerts-to-phones) | Pushes alerts to phones with label buttons | [![Import](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/create-link/?redirect=blueprint_import&blueprint_url=https%3A%2F%2Fgithub.com%2Fzacs%2Fha-siem%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fsiem%2Fmobile_app.yaml) |
| [SIEM escalation](#siem-escalation) | Tells more people when nobody answers | [![Import](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/create-link/?redirect=blueprint_import&blueprint_url=https%3A%2F%2Fgithub.com%2Fzacs%2Fha-siem%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fsiem%2Fescalation.yaml) |
| [SIEM deterrence](#siem-deterrence) | Turns the lights on at deter and alarm | [![Import](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/create-link/?redirect=blueprint_import&blueprint_url=https%3A%2F%2Fgithub.com%2Fzacs%2Fha-siem%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fsiem%2Fdeterrence.yaml) |
| [SIEM alerts to Mattermost](#siem-alerts-to-mattermost) | Posts alerts to a channel with label buttons | [![Import](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/create-link/?redirect=blueprint_import&blueprint_url=https%3A%2F%2Fgithub.com%2Fzacs%2Fha-siem%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fsiem%2Fmattermost.yaml) |

To import by hand, go to **Settings > Automations & scenes > Blueprints >
Import blueprint** and paste the blueprint's GitHub address. To pick up a
newer version later, open the blueprint's menu and choose **Re-import
blueprint**; automations made from it keep their settings.

Each blueprint needs Home Assistant 2026.10 or later.

## Labelling from a notification

A label is how you answer an incident: *False alarm*, *That's me*, *Real* or
*Guest*. SIEM uses it to learn, and the [escalation](#siem-escalation)
blueprint uses it to know someone has seen the alert.

Every alert the phone and Mattermost blueprints send carries the four labels
as buttons, and **each button labels the incident its own alert is about**.
The incident's id is written into the button itself, so it doesn't matter how
many alerts came since, or whether a new incident has opened, or whether Home
Assistant restarted in between. That is the difference from
`select.siem_label_last_incident` on the device page, which always labels the
open or most recent incident: fine when you're looking at it, risky when you
have three notifications in front of you.

What happens when you press one:

1. SIEM records the label on that incident. *False alarm* lowers the weights
   of the rules it scored by 10%, *Real* raises them by 10%; *That's me* and
   *Guest* change no weights. ([Why](scoring.md#labels).)
2. SIEM fires `siem_incident` with `kind: labelled`, the label, and who
   pressed it when it can tell: the person entity of the user the phone's app
   is logged in as, or the Mattermost user name.
3. The blueprints answer that event. On phones, the alert is replaced by one
   that says *Verify incident in Kitchen labelled That's me by Zac*, so you can
   see at a glance which alerts are answered. In Mattermost, the channel gets
   a line saying so.

Pressing a button twice, or pressing the same label on two phones, counts
once: a label an incident already has changes nothing, so weights can't be
pushed twice by accident. Pressing a different label adds it; the incident
then has both, and both count.

The phone buttons go to SIEM through the companion app, the same way any
actionable notification does. The Mattermost buttons go through a webhook SIEM
registers for itself; see [below](#the-label-webhook).

## SIEM alerts to phones

Pushes SIEM's alerts to phones running the Home Assistant companion app.

| Input | Default | What it does |
| --- | --- | --- |
| Phones | | Phones with the companion app. Each gets every alert. |
| Alerts | Verify, deter, alarm, break glass | Which categories to push. Add *Digest* for the daily summary. |

- Alerts about an incident carry the four label buttons. iOS shows all four
  when you long-press the notification; Android shows the first three
  (*False alarm*, *That's me*, *Real*).
- Each incident's alerts share one notification: a deter replaces the verify
  before it, so the latest is what you see. The notification's tag is
  `siem-<incident id>`.
- Alarm and break-glass alerts are *time-sensitive* on iOS and break through
  Focus. The rest arrive normally.
- When the room has a camera, the snapshot is attached.
- When the incident is labelled, from any phone, a chat button or the device
  page, the notification is replaced by one without buttons that says so.

**Which notify action.** The blueprint picks the device and works out its
notify action the way the companion app names it: `notify.mobile_app_` and the
phone's name as the app registered it. If you renamed the phone in the app
after setting it up and nothing arrives, check **Developer tools > Actions**
for the `notify.mobile_app_...` name and rename the device in Home Assistant to
match, or copy the blueprint and use the action directly.

## SIEM escalation

When nobody answers an incident, tells more people. An answer is any label on
the incident, from a phone, a chat button or the device page.

| Input | Default | What it does |
| --- | --- | --- |
| Escalate to | | Phones that are told when nobody answers. |
| Wait | 5 minutes | How long to wait for an answer before escalating. |
| Tiers | Verify, deter, alarm | Incidents that reach these tiers are escalated. Drop *Verify* to escalate only the serious ones. |
| Still unanswered | none | Actions to run if nobody answers within another wait after the escalation, such as a siren or a script that calls someone. |

How it runs, for each incident:

1. The incident first reaches a tier you picked. The clock starts.
2. If someone labels it within the wait, that's the end of it.
3. If it climbs to alarm while waiting, it escalates at once. An incident that
   reaches alarm straight away doesn't wait at all.
4. Otherwise, when the wait runs out, the escalation phones get the incident
   with its latest tier, room and the first few things that happened, plus the
   same label buttons. The title ends in *no answer*.
5. If you added *Still unanswered* actions, it waits once more. A label stops
   it; otherwise your actions run.
6. Once someone answers, the escalation phones' notification is replaced by
   one that says who answered and how, as on your own phones. Without *Still
   unanswered* actions, it watches for the answer for an hour.

Use it alongside the phone blueprint: your own phones get every alert at once,
and the escalation phones (a partner who doesn't want every verify, a
neighbour, a second phone) only hear about the ones you didn't answer.

SIEM itself still never calls anyone or sounds anything. Whatever you put in
*Still unanswered* is your automation acting on SIEM's events, like everything
else here.

## SIEM deterrence

Turns lights on when SIEM thinks someone is there.

| Input | Default | What it does |
| --- | --- | --- |
| Light the room at deter | on | At the deter tier, turn on every light in the incident's room. |
| Brightness | 100% | For every light it turns on. |
| Lights at alarm | every light | At the alarm tier, the lights to turn on. Leave empty for every light in the house. |
| More at deter | none | Anything else at deter, such as a sound on the room's speaker. |
| More at alarm | none | Anything else at alarm, such as a siren. |

The room is the Home Assistant area SIEM reports with each alert, so its
lights are the ones assigned to that area. At alarm, the room's lights come on
too.

SIEM ignores everything this blueprint does: lights Home Assistant turns on
never count, like anything else Home Assistant does. Watching SIEM's alerts for
a week or two before you turn this on is a good idea, so the first false alarm
doesn't light up the house at 3 a.m.

## SIEM alerts to Mattermost

Posts every alert, break glass and digest to a Mattermost channel as one
coloured box: the headline, the timeline, the room, the house mode, the score
and the top contributors, with the camera snapshot when the room has one.
Needs the [Mattermost component](https://github.com/cerebrate/ha-mattermost).

| Input | Default | What it does |
| --- | --- | --- |
| Channel | | The channel to post to, by name. |
| Notify action | `notify.mattermost` | The Mattermost notify action. |
| Label buttons | on | Add the four label buttons to each alert. |
| Home Assistant address for Mattermost | Home Assistant's own | The address your Mattermost server reaches Home Assistant at, such as `http://192.168.1.10:8123`. |

When someone presses a button, Mattermost shows them, and only them, a line
such as *Incident 3f9a1c2b labelled False alarm*, and the blueprint posts
*SIEM: incident `3f9a1c2b` (Kitchen) labelled **False alarm** by @zac* to the
channel for everyone else.

### Making the buttons work

Mattermost buttons work differently from phone buttons: when you press one,
**your Mattermost server** sends the label to Home Assistant. So:

1. **Mattermost must be able to reach Home Assistant.** The button posts to
   SIEM's [label webhook](#the-label-webhook) at the address in the alert's
   `label_url`, which is Home Assistant's network address from **Settings >
   System > Network**. If Mattermost reaches Home Assistant some other way
   (another IP address, a reverse proxy, a hostname inside Docker), put that
   in *Home Assistant address for Mattermost*.
2. **Mattermost must be allowed to.** Mattermost refuses to send button
   presses to private addresses such as `192.168.x.x` or `homeassistant.local`
   unless you allow them. In the System Console, go to **Environment >
   Developer** and add Home Assistant's host to *Allow untrusted internal
   connections to* (`ServiceSettings.AllowedUntrustedInternalConnections` in
   `config.json`), for example `192.168.1.10` or `homeassistant.local`.
3. **Mattermost Cloud** can't reach a private address at all. Use an address
   it can reach from the internet, such as your Nabu Casa or reverse-proxy
   address, in *Home Assistant address for Mattermost*.

If a button does nothing, or Mattermost says the action failed, look in
Mattermost's server log for the request it tried to make. If the request
reaches Home Assistant, SIEM's answer tells you what went wrong: *SIEM no
longer knows incident ...* for an incident older than its stored history, and
so on.

## The label webhook

SIEM registers one webhook, at `/api/webhook/<id>`, so chat buttons can
label incidents. The id is long and random, made the first time SIEM starts,
and kept. Each alert's `label_url` field holds the full address. A `POST` with
this body labels an incident:

```json
{"incident_id": "3f9a1c2b", "label": "false_alarm"}
```

The same two fields under `context`, which is how Mattermost and Slack-style
buttons send them, work too, and a `user_name` alongside is recorded as who
pressed it. The answer is `{"ephemeral_text": "..."}`, a line about what
happened.

The webhook is not limited to your home network, so Mattermost Cloud, or a
Mattermost server elsewhere, can reach it through Nabu Casa or your own
proxy. That means anyone who has the address can label your incidents. All a
label can do is nudge rule weights by 10% (never below 0.3 or above 1.5), and
the same label on the same incident counts once; it can't arm, disarm or turn
anything off. Treat the address like a password anyway: don't post it
anywhere public. The address only changes if you remove the integration and
add it again, which also clears SIEM's learned weights and incident history.

If you only use phones, the webhook sits unused.
