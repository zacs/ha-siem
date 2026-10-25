# Packages

The same four automations as the [blueprints](../docs/blueprints.md), as plain
YAML [packages](https://www.home-assistant.io/docs/configuration/packages/).
Use these if you'd rather keep everything in your own configuration files,
under source control, where every line is yours to read and change. The
blueprints are easier to set up from the UI and to update; these are easier
to diff, review and pin.

| Package | What it does |
| --- | --- |
| [`siem_mobile_app.yaml`](siem_mobile_app.yaml) | Pushes alerts to phones with label buttons; the notification updates when someone answers |
| [`siem_escalation.yaml`](siem_escalation.yaml) | Tells more phones when nobody answers in time, then runs a script you fill in |
| [`siem_deterrence.yaml`](siem_deterrence.yaml) | Lights the room at deter and the house at alarm, with places marked for a siren or a sound |
| [`siem_mattermost.yaml`](siem_mattermost.yaml) | Posts alerts, with the timeline and snapshot, to a channel with label buttons |

## Installing

1. Turn on packages in `configuration.yaml`, if you haven't already:

   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```

2. Copy the packages you want into `<config>/packages/`, keeping their names.
3. In each one, change the lines marked `EDIT`: your phones' notify actions,
   the Mattermost channel, the escalation wait. Everything you'd set in the
   blueprint's form is a variable near the top of the automation.
4. Restart Home Assistant, or reload automations (and scripts, for
   escalation).

Use a package or its blueprint, not both, or every alert goes out twice.

## What to change

**Phones** (`siem_mobile_app.yaml`, `siem_escalation.yaml`). List each
phone's notify action, as **Developer tools > Actions** shows it:

```yaml
phones:
  - notify.mobile_app_pixel_9
  - notify.mobile_app_iphone
```

**Alerts** (`siem_mobile_app.yaml`). `categories` picks which alerts to push;
add `digest` for the daily summary.

**Escalation** (`siem_escalation.yaml`). `escalate_to` is the phones that hear
about unanswered incidents, `wait_minutes` how long to wait for an answer,
and `tiers` which incidents to escalate. When nobody answers the escalation
either, the package runs `script.siem_still_unanswered`, defined at the top of
the same file. Out of the box it only leaves a persistent notification; put
your siren or your call-someone script there.

**Deterrence** (`siem_deterrence.yaml`). `brightness`, the lights to turn on
at alarm (`all` by default), and commented-out examples for a sound at deter
and a siren at alarm.

**Mattermost** (`siem_mattermost.yaml`). `channel`, `notify_action`, `buttons`,
and `ha_url`: the address your Mattermost server reaches Home Assistant at,
when that's not Home Assistant's own network address. For the buttons to work,
Mattermost must be allowed to reach Home Assistant; see
[Making the buttons work](../docs/blueprints.md#making-the-buttons-work).

## Staying up to date

A package is yours once it's copied, so it won't change when SIEM does. When
you update SIEM, look at the
[history of this folder](https://github.com/zacs/ha-siem/commits/main/packages)
to see whether a package changed, and take what you want. Everything SIEM
sends the packages is described in [Events](../docs/events.md), so you can
also write your own from scratch.

How the label buttons, the escalation and the label webhook work is the same
for packages and blueprints, and is described in
[Blueprints](../docs/blueprints.md).
