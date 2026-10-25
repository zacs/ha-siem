# Development

## Running the tests

```
pip install -r requirements_test.txt
ruff check .
pytest
```

The tests in `tests/` cover the pure-Python engine in
`custom_components/siem/core/`, which never imports Home Assistant. The tests
in `tests/ha/` run the integration, the blueprints, the packages, the test package and
the end-to-end scenarios inside a real Home Assistant, pinned by
`pytest-homeassistant-custom-component`.
Without that plugin installed, only the core tests run. CI runs three
GitHub Actions workflows: tests, Home Assistant's hassfest checks, and HACS
validation.

The blueprint and package tests load the files in `blueprints/` and
`packages/` into Home Assistant and drive them with real SIEM events, so a
template that breaks shows up as a failing test rather than on someone's
phone. Each blueprint and its package are the same automation; change both
together.

## Dry run with test entities

[`dev/siem_test_entities.yaml`](../dev/siem_test_entities.yaml) is a package that
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
