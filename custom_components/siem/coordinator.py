"""Coordinator: watches configured entities and events and drives the engine."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from datetime import datetime, time, timedelta
import functools
import logging
from typing import Any

from homeassistant.components.lock import LockState
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_AREA_ID,
    ATTR_DEVICE_ID,
    ATTR_DOMAIN,
    ATTR_ENTITY_ID,
    ATTR_SERVICE,
    ATTR_SERVICE_DATA,
    ENTITY_MATCH_ALL,
    EVENT_CALL_SERVICE,
    STATE_HOME,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import const as c
from .alerts import Alerts
from .core import entities as ent
from .core.arm import recommend_arm_mode
from .core.house_mode import HouseModeMachine
from .core.incident import EVENT_CLOSED, IncidentEngine
from .core.locks import (
    KIND_KEYPAD_LOCKOUT,
    KIND_KEYPAD_UNLOCK,
    KIND_MANUAL_UNLOCK,
    LcmSlot,
    classify_lock_notification,
    lcm_slots_from_attributes,
    pin_disabled,
)
from .core.occupancy import STRENGTH_MEDIUM, STRENGTH_WEAK, RoomOccupancy
from .core.origin import ContextLRU, is_physical
from .core.residual import LoadResidualDetector
from .core.rules import (
    MODE_NIGHT,
    MODE_VACANT,
    SUPPRESSOR_FAMILY_ARRIVAL,
    SUPPRESSOR_LET_IN,
    TAG_EXTERIOR,
    TAG_INTERIOR,
    validate_rule_config,
    validate_settings,
)
from .core.scoring import TIER_ALARM, TIER_NONE, TIER_VERIFY
from .core.weights import reset_weights
from .digest import DigestRunner
from .store import SiemStore

_LOGGER = logging.getLogger(__name__)

type SiemConfigEntry = ConfigEntry[SiemCoordinator]


def _known(state: State | None) -> bool:
    """Return True for a state that reflects the device rather than startup or an outage."""
    return state is not None and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN)


def _turned_on(old: State | None, new: State) -> bool:
    # Only a real off-to-on transition counts. A missing or unavailable state before means HA started or the
    # integration reconnected, and the entity is reporting where it already was.
    return new.state == STATE_ON and _known(old) and old.state != STATE_ON


def _number(state: State | None) -> float | None:
    if state is None:
        return None
    try:
        return float(state.state)
    except (TypeError, ValueError):
        return None


def _crossed_up(old: State | None, new: State, threshold: float) -> bool:
    value, previous = _number(new), _number(old)
    return value is not None and previous is not None and previous < threshold <= value


def _ids(value: Any) -> list[str]:
    """Return a service call's entity, device or area target as a list."""
    if isinstance(value, str):
        return [value]
    return [v for v in value if isinstance(v, str)] if isinstance(value, (list, tuple, set)) else []


def _parse_time(value: str | None, default: str) -> time:
    return dt_util.parse_time(value or default) or dt_util.parse_time(default)


def _safe(func):
    """Log and swallow anything a listener raises; a bad entity must never take the component down."""

    @functools.wraps(func)
    def wrapper(self, event):
        try:
            func(self, event)
        except Exception:
            _LOGGER.exception("%s failed on %s", func.__name__, getattr(event, "data", event))

    return wrapper


class SiemCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Own the engine, the subscriptions and the published state."""

    def __init__(self, hass: HomeAssistant, entry: SiemConfigEntry, store: SiemStore) -> None:
        """Build the engine from the entry's data, options and store."""
        super().__init__(hass, _LOGGER, config_entry=entry, name=c.DOMAIN)
        self.entry = entry
        self.store = store
        self.rooms: dict[str, dict[str, Any]] = dict(entry.data.get(c.CONF_ROOMS, {}))
        self.house: dict[str, Any] = dict(entry.data.get(c.CONF_HOUSE, {}))
        self.responses: dict[str, Any] = dict(entry.data.get(c.CONF_RESPONSES, {}))
        self.meta: dict[str, dict[str, Any]] = dict(entry.data.get(c.CONF_ENTITIES, {}))
        self.rules = validate_rule_config(entry.options.get(c.OPT_RULES))
        self.settings = validate_settings(entry.options.get(c.OPT_ENGINE))
        self.engine = IncidentEngine(self.rules, self.settings, store.weights)
        self.occupancy = RoomOccupancy()
        self.outside = RoomOccupancy(window_s=c.OUTSIDE_WINDOW_S)
        self.outdoor_rooms = {r for r, room in self.rooms.items() if room.get(c.CONF_OUTDOORS, ent.is_exterior_area(room.get(c.CONF_NAME)))}
        # Indoor occupancy sources that say someone is up at night; weak ones may be the dog.
        self._inside_sources = [
            e for e, m in self.meta.items() if m.get("role") == ent.ROLE_OCCUPANCY and m.get("room") not in self.outdoor_rooms and ent.effective_strength(m) != STRENGTH_WEAK
        ]
        self.modes = HouseModeMachine(self.now())
        try:
            self.modes.set_override(store.override)
        except ValueError:
            store.override = None
        # Contexts of recent service calls, and when Home Assistant last switched a configured entity or something in a room.
        self.caused = ContextLRU(size=4096, ttl_s=c.CAUSED_TTL_S)
        self._commanded: dict[str, float] = {}
        step, sustain = float(self.house.get(c.CONF_LOAD_STEP, c.DEFAULT_LOAD_STEP)), float(self.house.get(c.CONF_LOAD_SUSTAIN, c.DEFAULT_LOAD_SUSTAIN))
        self.residual = LoadResidualDetector(step, sustain) if self.house.get(c.CONF_LOAD) else None
        self.lcm_slots: dict[int, LcmSlot] = {}
        self.residents = ent.ResidentSet()
        self.score = 0.0
        self.tier = TIER_NONE
        self.top: list[dict[str, Any]] = []
        self.house_mode = MODE_VACANT
        self.night = False
        self.recommended_arm: str | None = None
        self.alarm_trigger = False
        self._alarm_held = False
        self._alarm_timer: Callable[[], None] | None = None
        self._last_let_in = -1e12
        # Night mode: whether the panel says the household is in bed, and the order of events at night.
        self._panel_asleep = False
        self._last_inside = -1e12
        self._family_out_until = -1e12
        self._entry_at = -1e12
        self.last_label: str | None = None
        self._offline_since: dict[str, float] = {}
        self._offline_scored: set[str] = set()
        self._break_glass_sent: set[str] = set()
        self._cooldown: dict[tuple[str, str], float] = {}
        self._last_arrival = 0.0
        self._contact_last_on: dict[str, float] = {}
        self._lock_devices: dict[str, str] = {}
        self._lock_seen: dict[tuple[str | None, str, int | None], float] = {}
        self._unsubs: list[Callable[[], None]] = []
        self._state_unsub: Callable[[], None] | None = None
        self.alerts = Alerts(hass, self)
        self.digest = DigestRunner(hass, self)

    @staticmethod
    def now() -> float:
        """Return the current time as epoch seconds."""
        return dt_util.utcnow().timestamp()

    @staticmethod
    def iso(timestamp: float | None) -> str | None:
        """Render epoch seconds as local ISO time."""
        return dt_util.as_local(dt_util.utc_from_timestamp(timestamp)).isoformat() if timestamp else None

    def room_name(self, room_id: str | None) -> str | None:
        """Return the friendly name of a room key."""
        return None if room_id is None else (self.rooms.get(room_id, {}).get("name") or room_id)

    def entity_name(self, entity_id: str | None) -> str:
        """Return an entity's friendly name, falling back to its id."""
        if entity_id is None:
            return "House"
        state = self.hass.states.get(entity_id)
        return state.name if state else entity_id

    @property
    def incident_id(self) -> str | None:
        """Return the open incident's id."""
        return self.engine.current.id if self.engine.current else None

    def house_list(self, field: str) -> list[str]:
        """Return a whole-house entity list merged with its additional twin."""
        return list(self.house.get(field) or []) + list(self.house.get(field + c.ADDITIONAL) or [])

    def create_task(self, target: Coroutine[Any, Any, Any], name: str) -> None:
        """Run alert work as an entry task: unload waits for it instead of cutting it off."""
        self.entry.async_create_task(self.hass, target, name)

    async def async_start(self) -> None:
        """Subscribe to everything configured and publish the initial state."""
        registry = er.async_get(self.hass)
        for lock in self.house.get(c.CONF_LOCKS) or []:
            if (entry := registry.async_get(lock)) and entry.device_id:
                self._lock_devices[entry.device_id] = lock
        self._refresh_residents()
        self._refresh_lcm_slots()
        self._subscribe()
        listeners = [
            (EVENT_CALL_SERVICE, self._on_call_service),
            (c.EVENT_ZWAVE_NOTIFICATION, self._on_zwave),
            (c.EVENT_LCM_LOCK, self._on_lcm_lock),
            (c.EVENT_MOBILE_ACTION, self._on_mobile_action),
        ]
        self._unsubs += [self.hass.bus.async_listen(name, handler) for name, handler in listeners]
        self._unsubs.append(async_track_time_interval(self.hass, self._tick, timedelta(seconds=c.TICK_SECONDS)))
        if self.store.last_digest is None:
            self.store.last_digest = dt_util.now().isoformat()
            self.store.async_schedule_save()
        now = self.now()
        if calendar := self.house.get(c.CONF_CALENDAR):
            self._apply_calendar(self.hass.states.get(calendar))
        if panel := self.house.get(c.CONF_ALARM_PANEL):
            self._apply_panel(self.hass.states.get(panel))
        self._update_presence(now)
        self._refresh_mode(now)
        self.recommended_arm = recommend_arm_mode(self.house_mode, self.night)
        self.publish(now, force=True)

    async def async_stop(self) -> None:
        """Drop every subscription, keep an open incident in the history and flush the store."""
        for unsub in filter(None, [*self._unsubs, self._state_unsub, self._alarm_timer]):
            unsub()
        self._unsubs, self._state_unsub, self._alarm_timer = [], None, None
        if (incident := self.engine.current) is not None:
            self.store.add_incident({**incident.as_dict(), "closed": self.now()})
        await self.store.async_save()

    def _subscribe(self) -> None:
        # Cameras are only used for snapshots; their state churns with every token refresh.
        watched = {e for e, m in self.meta.items() if m.get("role") != ent.ROLE_CAMERA} | set(self.residents.trackers)
        if self._state_unsub:
            self._state_unsub()
        self._state_unsub = async_track_state_change_event(self.hass, sorted(watched), self._on_state) if watched else None

    def _refresh_residents(self) -> None:
        attrs = {p: state.attributes for p in self.house.get(c.CONF_RESIDENTS) or [] if (state := self.hass.states.get(p))}
        self.residents = ent.expand_residents(attrs)

    def _refresh_lcm_slots(self) -> None:
        attrs = {e: state.attributes for e in self.house_list(c.CONF_LCM_EVENTS) if (state := self.hass.states.get(e))}
        self.lcm_slots = lcm_slots_from_attributes(attrs)

    def _refresh_mode(self, now: float) -> None:
        local = dt_util.now().time()
        start = _parse_time(self.house.get(c.CONF_NIGHT_START), c.DEFAULT_NIGHT_START)
        end = _parse_time(self.house.get(c.CONF_NIGHT_END), c.DEFAULT_NIGHT_END)
        self.night = start <= local < end if start <= end else local >= start or local < end
        # The household is in bed while the panel is armed night, or, with no panel picked, inside the night window.
        self.modes.set_asleep(self._panel_asleep if self.house.get(c.CONF_ALARM_PANEL) else self.night)
        self.house_mode = self.modes.mode(now)

    @property
    def dark(self) -> bool:
        """Inside the night window or with the household in bed: exterior rules count 1.5 times."""
        return self.night or self.house_mode == MODE_NIGHT

    def _apply_panel(self, state: State | None) -> None:
        """Armed night means the household is in bed; pending or triggered keeps whatever it was."""
        if state is not None and state.state not in c.PANEL_KEEPS:
            self._panel_asleep = state.state == c.PANEL_ASLEEP

    def _update_presence(self, now: float) -> None:
        entities = list(self.house.get(c.CONF_RESIDENTS) or []) + self.residents.trackers + list(self.house.get(c.CONF_EXTRA_TRACKERS) or [])
        anyone = any((state := self.hass.states.get(e)) is not None and state.state == STATE_HOME for e in entities)
        self.modes.set_presence(anyone, now)
        guests = self.house.get(c.CONF_GUEST_TRACKERS) or []
        self.modes.set_guest_presence(any((state := self.hass.states.get(e)) is not None and state.state == STATE_HOME for e in guests), now)

    def _apply_calendar(self, state: State | None) -> None:
        if state is None or state.state != STATE_ON:
            self.modes.clear_calendar_event()
            return
        start = dt_util.parse_datetime(str(state.attributes.get("start_time", "")))
        end = dt_util.parse_datetime(str(state.attributes.get("end_time", "")))
        if start is None or end is None:
            return
        self.modes.set_calendar_event(state.attributes.get("message"), dt_util.as_utc(start).timestamp(), dt_util.as_utc(end).timestamp())

    def publish(self, now: float | None = None, force: bool = False) -> None:
        """Refresh the entities, subject to the rate limit unless forced."""
        now = self.now() if now is None else now
        score = self.engine.score(now)
        tier = self.engine.current.tier if self.engine.current else TIER_NONE
        if not force and not self.engine.should_publish(now, score, tier):
            return
        self.score, self.tier, self.top = score, tier, self.engine.top_contributors(now)
        self.async_set_updated_data(
            {"score": score, "tier": tier, "alarm_trigger": self.alarm_trigger, "mode": self.house_mode, "night": self.night, "incident_id": self.incident_id}
        )

    def _process(self, now: float, force: bool = False) -> None:
        """Advance the engine, publish, and announce transitions and alerts as events."""
        previous = (self.house_mode, self.night)
        self._refresh_mode(now)
        events = self.engine.evaluate(now)
        trigger = self._track_alarm()
        score = self.engine.score(now)
        for event in events:
            if event.kind == EVENT_CLOSED:
                self.store.add_incident(event.incident.as_dict())
            payload = {**self.alerts.incident_payload(event.incident), "kind": event.kind, "tier": event.tier, "previous_tier": event.previous_tier}
            self.hass.bus.async_fire(c.EVENT_INCIDENT, payload, context=self.alerts.context())
            light = {key: payload[key] for key in (c.ATTR_INCIDENT_ID, "tier", "previous_tier", "score", "room", "mode")}
            async_dispatcher_send(self.hass, c.SIGNAL_INCIDENT_EVENT, event.kind, light)
        changed = previous != (self.house_mode, self.night)
        if changed:
            # Published as a sensor only; acting on it, or not, is up to the user's own automations.
            self.recommended_arm = recommend_arm_mode(self.house_mode, self.night)
        self.publish(now, force=force or bool(events) or changed or trigger)
        incident = self.engine.current
        renotify = incident is not None and incident.tier == TIER_VERIFY and incident.notified_score and score >= 2 * incident.notified_score
        if events or renotify:
            self.create_task(self.alerts.async_handle(events, incident if renotify else None), "siem alerts")

    def _track_alarm(self) -> bool:
        """Hold the alarm trigger back until the incident has stayed at the alarm tier for ALARM_GRACE_S.

        A resident whose phone reports home a little after they walk in brings the score down with the arrival
        before the panel goes off. Returns True when the trigger changed.
        """
        at_alarm = self.engine.current is not None and self.engine.current.tier == TIER_ALARM
        if not at_alarm:
            if self._alarm_timer is not None:
                self._alarm_timer()
            self._alarm_timer, self._alarm_held = None, False
        elif self._alarm_timer is None and not self._alarm_held:
            self._alarm_timer = async_call_later(self.hass, c.ALARM_GRACE_S, self._alarm_due)
        previous, self.alarm_trigger = self.alarm_trigger, at_alarm and self._alarm_held
        return previous != self.alarm_trigger

    @callback
    def _alarm_due(self, _now: datetime) -> None:
        self._alarm_timer, self._alarm_held = None, True
        self._process(self.now())

    def _score(
        self, rule_id: str, now: float, entity_id: str | None, room: str | None, detail: str, points: float | None = None, allow_open: bool = True, gated: bool = False
    ) -> None:
        self._refresh_mode(now)
        if not gated and not self._night_gate(rule_id, now):
            return
        contribution = self.engine.add(rule_id, mode=self.house_mode, night=self.dark, now=now, entity_id=entity_id, room=room, detail=detail, points=points, allow_open=allow_open)
        if contribution is None:
            return
        if rule_id == "exterior_door_opened":
            self._entry_at = now
        _LOGGER.debug("%s scored %.1f for %s (%s)", rule_id, contribution.points, entity_id, detail)
        if (rule_id == "manual_unlock" and self.house_mode == MODE_VACANT) or rule_id == "keypad_lockout":
            message = f"{self.entity_name(entity_id)}: {self.rules[rule_id].description.lower()} ({detail})"
            self.alerts.break_glass(message)
        # An entity new to the incident is published now, not after the rate limit, so the incident's entities are current.
        earlier = self.engine.current.contributions[:-1] if self.engine.current else []
        self._process(now, force=entity_id is not None and all(c.entity_id != entity_id for c in earlier))

    def _night_gate(self, rule_id: str, now: float) -> bool:
        """Return whether ``rule_id`` counts now; only night mode holds anything back.

        With the household in bed the order of events tells one of them from an intruder: one of the family is up
        inside before a door opens, while an intruder is outside first, or nothing moves before it. A door or gate
        that opens soon after someone moved inside is someone going out, and the doors and the yard are theirs
        while they are out there; the same goes for a resident who just arrived or someone just let in. Inside
        counts only right after an entry that counted: the intruder moving in.
        """
        if self.house_mode != MODE_NIGHT:
            return True
        tag = self.rules[rule_id].tag
        if tag == TAG_INTERIOR:
            return now - self._entry_at <= c.NIGHT_AFTER_ENTRY_S
        if tag != TAG_EXTERIOR:
            return True
        expected = max(self._last_arrival, self._last_let_in) + c.NIGHT_EXPECTED_S
        if now < max(self._family_out_until, expected):
            self._family_out_until = max(self._family_out_until, now + c.NIGHT_FAMILY_OUTSIDE_S)
            return False
        inside_first = self._someone_up(now)
        if inside_first and rule_id in ("exterior_door_opened", "gate_opened"):
            self._family_out_until = now + c.NIGHT_FAMILY_OUTSIDE_S
            return False
        # A Wi-Fi motion sensor at a door also sees someone walking past it inside.
        return not (inside_first and rule_id == "door_csi_motion")

    def _someone_up(self, now: float) -> bool:
        """Return True when someone was moving inside in the last two minutes, or still is."""
        if now - self._last_inside <= c.NIGHT_INSIDE_FIRST_S:
            return True
        states = (self.hass.states.get(e) for e in self._inside_sources)
        return any(s is not None and s.state == STATE_ON and now - s.last_changed.timestamp() <= c.NIGHT_UP_S for s in states)

    def _cooldown_ok(self, rule_id: str, key: str, now: float) -> bool:
        """Let the same entity (or room) score a rule once per cooldown: contact bounce, groups of bulbs."""
        last = self._cooldown.get((rule_id, key))
        if last is not None and now - last < c.COOLDOWN_S:
            return False
        self._cooldown[(rule_id, key)] = now
        return True

    def _score_once(self, rule_id: str, key: str, now: float, entity_id: str, room: str | None, detail: str) -> None:
        if self._cooldown_ok(rule_id, key, now):
            self._score(rule_id, now, entity_id, room, detail)

    def _commanded_within(self, key: str | None, now: float, window_s: float) -> bool:
        return key is not None and now - self._commanded.get(key, -1e12) < window_s

    def _room_of(self, entity_id: str) -> str | None:
        """Return the configured room (an area) an entity or its device sits in."""
        entry = er.async_get(self.hass).async_get(entity_id)
        if entry is None:
            return None
        area = entry.area_id
        if area is None and entry.device_id and (device := dr.async_get(self.hass).async_get(entry.device_id)):
            area = device.area_id
        return area if area in self.rooms else None

    @callback
    @_safe
    def _on_call_service(self, event: Event) -> None:
        """Remember what Home Assistant is about to change, so the change is not taken for a person.

        Every service call announces its context here before it runs: automations on any trigger, scripts, the app,
        voice assistants, HomeKit Bridge, other integrations and the API.
        """
        data = event.data
        domain, service = data.get(ATTR_DOMAIN), data.get(ATTR_SERVICE)
        if (domain, service) in c.READ_ONLY_SERVICES:
            return
        now = self.now()
        self.caused.add(event.context.id, now)
        target = data.get(ATTR_SERVICE_DATA) or {}
        entities, rooms = _ids(target.get(ATTR_ENTITY_ID)), set(_ids(target.get(ATTR_AREA_ID))) & set(self.rooms)
        if ENTITY_MATCH_ALL in entities:
            rooms |= set(self.rooms)
        for entity_id in entities:
            if entity_id in self.meta:
                self._commanded[entity_id] = now
            if room := self._room_of(entity_id):
                rooms.add(room)
        devices = dr.async_get(self.hass)
        for device_id in _ids(target.get(ATTR_DEVICE_ID)):
            if (device := devices.async_get(device_id)) and device.area_id in self.rooms:
                rooms.add(device.area_id)
        for room in rooms:
            self._commanded[room] = now
        if opened := self._opened_by(domain, service, entities):
            self._let_in(now, f"{self.entity_name(opened)} opened from Home Assistant")

    def _opened_by(self, domain: Any, service: Any, entities: list[str]) -> str | None:
        """Return the configured lock, or the garage door, gate or door cover, a service call is opening.

        Home Assistant unlocking the door or opening the garage (from the app, a voice assistant, Apple Home or an
        automation) is someone being let in, like a code at the keypad. The door's own contact sensor reports the
        opening with no trace of the command, so this is where it is recognised.
        """
        locks = self.house.get(c.CONF_LOCKS) or []
        for entity_id in entities:
            state = self.hass.states.get(entity_id)
            if domain == "lock" and service in ("unlock", "open") and entity_id in locks:
                return entity_id
            entry_cover = domain == "cover" and state is not None and state.attributes.get("device_class") in c.ENTRY_COVER_CLASSES
            if entry_cover and (service == "open_cover" or (service == "toggle" and state.state in ("closed", "closing"))):
                return entity_id
        return None

    @callback
    @_safe
    def _on_state(self, event: Event[EventStateChangedData]) -> None:
        entity_id, old, new = event.data["entity_id"], event.data["old_state"], event.data["new_state"]
        if new is None:
            return
        now = self.now()
        meta = self.meta.get(entity_id) or ({"role": ent.ROLE_TRACKER} if entity_id in self.residents.trackers else None)
        if meta is None:
            return
        role, room = meta.get("role"), meta.get("room")
        if new.state == STATE_UNAVAILABLE:
            # Scored from the tick once it has lasted OFFLINE_GRACE_S, so a reload or restart passes quietly.
            if old is not None and old.state != STATE_UNAVAILABLE and role in ent.SENSING_ROLES:
                self._offline_since.setdefault(entity_id, now)
            return
        self._offline_since.pop(entity_id, None)
        self._offline_scored.discard(entity_id)
        self._break_glass_sent.discard(entity_id)
        if new.state == STATE_UNKNOWN:
            return
        if role == ent.ROLE_PERSON:
            attrs = ("device_trackers", "user_id")
            if old is None or any(old.attributes.get(a) != new.attributes.get(a) for a in attrs):
                self._refresh_residents()
                self._subscribe()
            self._on_arrival(old, new, now)
            return
        if role in (ent.ROLE_TRACKER, ent.ROLE_GUEST_TRACKER):
            self._on_arrival(old, new, now, guest=role == ent.ROLE_GUEST_TRACKER)
            return
        if role == ent.ROLE_CALENDAR:
            self._apply_calendar(new)
            self._process(now)
            return
        if role == ent.ROLE_PANEL:
            self._apply_panel(new)
            self._process(now)
            return
        if role == ent.ROLE_LCM_EVENT:
            self._on_lcm_event(old, new, now)
            return
        if role in (ent.ROLE_LOAD, ent.ROLE_AUTOMATED_LOAD):
            if self.residual is not None:
                self._on_load(now)
            return
        ctx = event.context
        # Users only matter for this: anything Home Assistant did (an automation, a script, a person in the app, a voice
        # assistant, HomeKit Bridge, Presence Simulation) is not evidence. What is left physically happened.
        physical = is_physical(parent_id=ctx.parent_id, user_id=ctx.user_id, context_id=ctx.id, caused=self.caused, now=now)
        if role == ent.ROLE_LOCK:
            # Locking and unlocking by hand are scored from the lock's notifications. An unlock Home Assistant made
            # (through an area or device target the service call did not name) lets someone in.
            if not physical and new.state == LockState.UNLOCKED and _known(old) and old.state != LockState.UNLOCKED:
                self._let_in(now, f"{new.name} opened from Home Assistant")
            return
        if not physical:
            return
        self._refresh_mode(now)
        outdoors = room in self.outdoor_rooms
        if not outdoors and role in (ent.ROLE_INTERIOR_DOOR, ent.ROLE_LIGHT, ent.ROLE_OCCUPANCY) and _turned_on(old, new):
            # Someone up and about inside, for night mode. A weak source may be the dog; a light may be a slow report
            # of something Home Assistant switched.
            weak = role == ent.ROLE_OCCUPANCY and ent.effective_strength(meta) == STRENGTH_WEAK
            if not weak and not (role == ent.ROLE_LIGHT and self._commanded_within(entity_id, now, c.COMMANDED_LIGHT_S)):
                self._last_inside = now
        if role == ent.ROLE_OCCUPANCY and _turned_on(old, new):
            if outdoors:
                self._on_outside(entity_id, ent.effective_strength(meta), room, now, "seen" if meta.get("person_detector") else "motion")
            else:
                self._on_occupancy(entity_id, meta, room, now)
        elif role == ent.ROLE_PERIMETER and _turned_on(old, new):
            self.modes.note_activity(now)
            self._contact_last_on[entity_id] = now
            self._score_once("gate_opened" if meta.get("gate") else "exterior_door_opened", entity_id, now, entity_id, room, "opened")
        elif role == ent.ROLE_INTERIOR_DOOR and _turned_on(old, new):
            # Outdoors, a shed or mailbox contact only says someone is outside.
            if outdoors:
                self._on_outside(entity_id, STRENGTH_MEDIUM, room, now, "opened")
                return
            self.modes.note_activity(now)
            self._score_once("interior_door_opened", entity_id, now, entity_id, room, "opened")
        elif role == ent.ROLE_LIGHT and _turned_on(old, new):
            # A light Home Assistant was just told to switch can report after its command's context has expired.
            if self._commanded_within(entity_id, now, c.COMMANDED_LIGHT_S):
                return
            # Outdoors, a light that turns itself on is a motion floodlight: someone is outside.
            if outdoors:
                self._on_outside(entity_id, STRENGTH_MEDIUM, room, now, "light on")
                return
            # One switch can turn on a whole group of bulbs, so lights count once per room.
            self.modes.note_activity(now)
            self._score_once("light_physical", room or entity_id, now, entity_id, room, "switched on")
        elif role == ent.ROLE_POWER and _crossed_up(old, new, float(meta.get("threshold", c.DEFAULT_POWER_THRESHOLD))):
            # A power reading has no context of its own: an appliance Home Assistant just switched on in the same
            # room (its smart plug, a TV through its integration) draws power a little later.
            if outdoors or self._commanded_within(room, now, c.COMMANDED_POWER_S):
                return
            self.modes.note_activity(now)
            self._score_once("appliance_on", entity_id, now, entity_id, room, f"{new.state} W")
        elif role == ent.ROLE_WATER and _crossed_up(old, new, float(meta.get("threshold", c.DEFAULT_WATER_THRESHOLD))):
            self.modes.note_activity(now)
            self._score_once("water_flow", entity_id, now, entity_id, room, f"flow {new.state}")
        elif role == ent.ROLE_CSI and _turned_on(old, new):
            contact = (self.house.get(c.CONF_CSI_MAP) or {}).get(entity_id)
            contact_state = self.hass.states.get(contact) if contact else None
            recently = contact and now - self._contact_last_on.get(contact, -1e12) <= c.CSI_CONTACT_WINDOW_S
            if not recently and not (contact_state and contact_state.state == STATE_ON):
                self._score_once("door_csi_motion", entity_id, now, entity_id, room, f"{self.entity_name(contact) if contact else 'no door'} stayed closed")

    def _on_occupancy(self, entity_id: str, meta: dict[str, Any], room: str | None, now: float) -> None:
        base = self.rules["interior_occupied"].points_for(self.house_mode)
        if base <= 0 or not self._night_gate("interior_occupied", now):
            return
        result = self.occupancy.observe(room or entity_id, entity_id, ent.effective_strength(meta), now, base)
        if result.points <= 0:
            return
        allow_open = not (result.weak_alone and self.house_mode in (MODE_VACANT, MODE_NIGHT))
        source = "person detected" if meta.get("person_detector") else f"{result.strength} source"
        detail = source + (", corroborated" if result.corroborated else "")
        self._score("interior_occupied", now, entity_id, room, detail, points=result.points, allow_open=allow_open, gated=True)

    def _on_outside(self, entity_id: str, strength: str, room: str | None, now: float, what: str) -> None:
        """Credit "someone is outside" once per window for the whole outdoors, at its strongest source."""
        base = self.rules["exterior_occupied"].points_for(self.house_mode, self.dark)
        if base <= 0 or not self._night_gate("exterior_occupied", now):
            return
        result = self.outside.observe("outside", entity_id, strength, now, base)
        if result.points <= 0:
            return
        detail = what + (", corroborated" if result.corroborated else "")
        self._score("exterior_occupied", now, entity_id, room, detail, points=result.points, allow_open=not result.weak_alone, gated=True)

    def _on_load(self, now: float) -> None:
        load = _number(self.hass.states.get(self.house[c.CONF_LOAD]))
        if load is None or self.residual is None:
            return
        automated = sum(_number(self.hass.states.get(e)) or 0.0 for e in self.house.get(c.CONF_AUTOMATED_LOADS) or [])
        if self.residual.update(load, automated, now):
            self._score("load_residual", now, self.house[c.CONF_LOAD], None, f"residual {self.residual.residual:.0f} W")

    def _on_arrival(self, old: State | None, new: State, now: float, guest: bool = False) -> None:
        self._update_presence(now)
        # A person and its tracker arrive together; the suppressor applies once per arrival. A phone can report home a
        # little after its owner walked in (a guest's Wi-Fi tracker usually does), so the arrival explains whatever was
        # scored in the minutes before it, a guest's as much as a resident's.
        if new.state == STATE_HOME and (old is None or old.state != STATE_HOME) and now - self._last_arrival >= 60:
            self._last_arrival = now
            rule = "guest_arrival" if guest else "family_arrival"
            self.engine.suppress(rule, SUPPRESSOR_FAMILY_ARRIVAL, now=now, detail=f"{new.name} arrived home", explain_s=c.ARRIVAL_EXPLAINS_S)
        self._process(now)

    def _let_in(self, now: float, detail: str, person: str | None = None) -> None:
        """Someone was let in: a code the lock accepted, or an unlock from Home Assistant. Starts the guest clock."""
        self.modes.let_in(now)
        if now - self._last_let_in >= c.LET_IN_DEDUPE_S:
            self._last_let_in = now
            self.engine.suppress("let_in", SUPPRESSOR_LET_IN, now=now, detail=detail, person=person)
        elif person and self.engine.current is not None:
            self.engine.current.person = person
        self._process(now)

    def _on_lcm_event(self, old: State | None, new: State, now: float) -> None:
        self._refresh_lcm_slots()
        # A never-fired event entity is unknown, so unknown to a timestamp is a real use; unavailable to a
        # timestamp is the entity coming back after a restart or reload with its old value.
        if old is None or old.state in (new.state, STATE_UNAVAILABLE):
            return
        self.modes.note_activity(now)
        if new.attributes.get("operation") == "lock":
            return
        name = str(new.attributes.get("name") or "unknown user")
        self._let_in(now, f"code used by {name}", person=name)

    @callback
    @_safe
    def _on_zwave(self, event: Event) -> None:
        data = event.data
        if data.get("command_class_name") == "Notification":
            self._lock_event(self._lock_devices.get(str(data.get("device_id"))), data.get("event_label"), (data.get("parameters") or {}).get("userId"))

    @callback
    @_safe
    def _on_lcm_lock(self, event: Event) -> None:
        self._lock_event(event.data.get("entity_id"), event.data.get("action_text"), event.data.get("code_slot"))

    def _lock_event(self, lock: str | None, label: Any, slot: Any) -> None:
        """Score a lock event from either source once, and only for a configured lock."""
        locks = self.house.get(c.CONF_LOCKS) or []
        if lock is None and len(locks) == 1 and not self._lock_devices:
            lock = locks[0]
        if lock not in locks:
            return
        kind, slot = classify_lock_notification(label, slot)
        now = self.now()
        if kind is None or now - self._lock_seen.get((lock, kind, slot), -1e12) < c.LOCK_EVENT_DEDUPE_S:
            return
        self._lock_seen[(lock, kind, slot)] = now
        self._refresh_lcm_slots()
        label = str(label or kind)
        if kind == KIND_MANUAL_UNLOCK:
            self.modes.note_activity(now)
            self._score("manual_unlock", now, lock, None, label)
        elif kind == KIND_KEYPAD_UNLOCK and pin_disabled(slot, self.lcm_slots):
            self._score("pin_not_allowed", now, lock, None, f"{label}, slot {slot} ({self.lcm_slots[slot].name})")
        elif kind == KIND_KEYPAD_UNLOCK:
            # The lock accepted the code, so whoever typed it was given it.
            self.modes.note_activity(now)
            known = self.lcm_slots.get(slot) if slot is not None else None
            self._let_in(now, f"code at {self.entity_name(lock)}" + (f", slot {slot}" if slot is not None else ""), person=known.name if known else None)
        elif kind == KIND_KEYPAD_LOCKOUT:
            self._score("keypad_lockout", now, lock, None, label)

    @callback
    @_safe
    def _on_mobile_action(self, event: Event) -> None:
        action = str(event.data.get("action") or "")
        if action.startswith(c.MOBILE_ACTION_PREFIX):
            label, incident_id = action[len(c.MOBILE_ACTION_PREFIX) :].lower().split("|", 1)
            self.label(label, incident_id)

    def _check_offline(self, now: float) -> None:
        """Score sensors that stayed unavailable past the grace period, all of them in one contribution."""
        due = [e for e, since in self._offline_since.items() if e not in self._offline_scored and now - since >= c.OFFLINE_GRACE_S]
        if due:
            self._offline_scored.update(due)
            names = ", ".join(self.entity_name(e) for e in due)
            if len(due) == 1:
                self._score("sensor_offline", now, due[0], self.meta.get(due[0], {}).get("room"), "unavailable")
            else:
                self._score("sensor_offline", now, None, None, f"{len(due)} sensors unavailable: {names}")
        if self.house_mode != MODE_VACANT:
            return
        stale = [e for e, since in self._offline_since.items() if e not in self._break_glass_sent and now - since >= c.OFFLINE_BREAK_GLASS_S]
        if stale:
            self._break_glass_sent.update(stale)
            names = ", ".join(self.entity_name(e) for e in stale)
            self.alerts.break_glass(f"{names} unavailable for over an hour while the house is vacant")

    async def _tick(self, _now: datetime) -> None:
        try:
            now = self.now()
            self._update_presence(now)
            if self.residual is not None:
                self._on_load(now)
            self._check_offline(now)
            self._process(now)
            if self.digest.due(dt_util.now()):
                await self.digest.async_run()
        except Exception:
            _LOGGER.exception("Error in SIEM tick")

    def label(self, label: str, incident_id: str | None = None) -> None:
        """Label an incident; false_alarm and real adjust the weights of its rules."""
        incident, changes = self.engine.label(label, incident_id)
        self.last_label = label
        self.store.record_weight_changes(changes, self.now(), label, incident.id)
        if incident.closed:
            self.store.add_incident(incident.as_dict())
        _LOGGER.info("Incident %s labelled %s; weights changed: %s", incident.id, label, changes)
        self.publish(self.now(), force=True)

    def set_house_mode(self, mode: str) -> None:
        """Force a house mode, or return to automatic; the choice survives restarts."""
        self.modes.set_override(mode)
        self.store.override = self.modes.override
        self.store.async_schedule_save()
        self._process(self.now())
        self.publish(self.now(), force=True)

    async def async_reset_weights(self) -> None:
        """Return every rule weight to 1.0."""
        reset_weights(self.store.weights)
        await self.store.async_save()
        self.publish(self.now(), force=True)
