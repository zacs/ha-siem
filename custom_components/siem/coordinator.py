"""Coordinator: watches configured entities and events and drives the engine."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
import functools
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_HOME, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import const as c
from .actions import Responder
from .core import entities as ent
from .core.arm import recommend_arm_mode
from .core.house_mode import HouseModeMachine
from .core.incident import EVENT_CLOSED, IncidentEngine
from .core.locks import KIND_KEYPAD_LOCKOUT, KIND_KEYPAD_UNLOCK, KIND_MANUAL_UNLOCK, LcmSlot, classify_lock_notification, lcm_slots_from_attributes, pin_allowed
from .core.occupancy import RoomOccupancy
from .core.origin import ContextLRU, Origin, classify_origin
from .core.residual import LoadResidualDetector
from .core.rules import MODE_VACANT, SUPPRESSOR_ALLOWED_PIN, SUPPRESSOR_FAMILY_ARRIVAL, validate_rule_config, validate_settings
from .core.scoring import TIER_NONE, TIER_VERIFY
from .core.weights import reset_weights
from .digest import DigestRunner
from .notify import Notifier
from .store import SiemStore

_LOGGER = logging.getLogger(__name__)

type SiemConfigEntry = ConfigEntry[SiemCoordinator]


def _turned_on(old: State | None, new: State) -> bool:
    return new.state == STATE_ON and (old is None or old.state != STATE_ON)


def _number(state: State | None) -> float | None:
    if state is None:
        return None
    try:
        return float(state.state)
    except (TypeError, ValueError):
        return None


def _crossed_up(old: State | None, new: State, threshold: float) -> bool:
    value, previous = _number(new), _number(old)
    return value is not None and value >= threshold and (previous is None or previous < threshold)


def _parse_time(value: str, default: str) -> datetime.time:
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
        self.modes = HouseModeMachine(self.now())
        self.homekit_contexts = ContextLRU()
        step, sustain = float(self.house.get(c.CONF_LOAD_STEP, c.DEFAULT_LOAD_STEP)), float(self.house.get(c.CONF_LOAD_SUSTAIN, c.DEFAULT_LOAD_SUSTAIN))
        self.residual = LoadResidualDetector(step, sustain) if self.house.get(c.CONF_LOAD) else None
        self.lcm_slots: dict[int, LcmSlot] = {}
        self.residents = ent.ResidentSet()
        self.trusted: set[str] = set(self.house.get(c.CONF_TRUSTED_USERS) or [])
        self.toggles: dict[str, bool] = {key: bool(store.toggles.get(key, self.responses.get(key, key == c.CONF_DRY_RUN))) for key in c.TOGGLES}
        self.score = 0.0
        self.tier = TIER_NONE
        self.top: list[dict[str, Any]] = []
        self.house_mode = MODE_VACANT
        self.night = False
        self.recommended_arm: str | None = None
        self.alarm_trigger_on = False
        self.last_label: str | None = None
        self._offline_since: dict[str, float] = {}
        self._break_glass_sent: set[str] = set()
        self._last_arrival = 0.0
        self._contact_last_on: dict[str, float] = {}
        self._lock_devices: dict[str, str] = {}
        self._lock_seen: dict[tuple[str | None, str, int | None], float] = {}
        self._unsubs: list[Callable[[], None]] = []
        self._state_unsub: Callable[[], None] | None = None
        self.notifier = Notifier(hass, self)
        self.responder = Responder(hass, self)
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

    @property
    def incident_id(self) -> str | None:
        """Return the open incident's id."""
        return self.engine.current.id if self.engine.current else None

    def house_list(self, field: str) -> list[str]:
        """Return a whole-house entity list merged with its additional twin."""
        return list(self.house.get(field) or []) + list(self.house.get(field + c.ADDITIONAL) or [])

    async def async_start(self) -> None:
        """Subscribe to everything configured and publish the initial state."""
        registry = er.async_get(self.hass)
        for lock in self.house.get(c.CONF_LOCKS) or []:
            if (entry := registry.async_get(lock)) and entry.device_id:
                self._lock_devices[entry.device_id] = lock
        self._refresh_residents()
        self._refresh_lcm_slots()
        self._subscribe()
        for name in c.EVENTS_HOMEKIT:
            self._unsubs.append(self.hass.bus.async_listen(name, self._on_homekit))
        self._unsubs.append(self.hass.bus.async_listen(c.EVENT_ZWAVE_NOTIFICATION, self._on_zwave))
        self._unsubs.append(self.hass.bus.async_listen(c.EVENT_LCM_LOCK, self._on_lcm_lock))
        self._unsubs.append(self.hass.bus.async_listen(c.EVENT_MOBILE_ACTION, self._on_mobile_action))
        self._unsubs.append(async_track_time_interval(self.hass, self._tick, timedelta(seconds=c.TICK_SECONDS)))
        if self.store.last_digest is None:
            self.store.last_digest = dt_util.now().isoformat()
            self.store.async_schedule_save()
        now = self.now()
        if calendar := self.house.get(c.CONF_CALENDAR):
            self._apply_calendar(self.hass.states.get(calendar))
        self._update_presence(now)
        self._refresh_mode(now)
        self.recommended_arm = recommend_arm_mode(self.house_mode, self.night)
        self.publish(now, force=True)

    async def async_stop(self) -> None:
        """Drop every subscription and flush the store."""
        for unsub in filter(None, [*self._unsubs, self._state_unsub]):
            unsub()
        self._unsubs, self._state_unsub = [], None
        await self.store.async_save()

    def _subscribe(self) -> None:
        watched = set(self.meta) | set(self.residents.trackers)
        if self._state_unsub:
            self._state_unsub()
        self._state_unsub = async_track_state_change_event(self.hass, sorted(watched), self._on_state) if watched else None

    def _refresh_residents(self) -> None:
        attrs = {p: state.attributes for p in self.house.get(c.CONF_RESIDENTS) or [] if (state := self.hass.states.get(p))}
        self.residents = ent.expand_residents(attrs)
        self.trusted = set(self.house.get(c.CONF_TRUSTED_USERS) or []) | set(self.residents.user_ids)

    def _refresh_lcm_slots(self) -> None:
        attrs = {e: state.attributes for e in self.house_list("lcm_events") if (state := self.hass.states.get(e))}
        self.lcm_slots = lcm_slots_from_attributes(attrs)

    def _refresh_mode(self, now: float) -> None:
        local = dt_util.now().time()
        start = _parse_time(self.house.get(c.CONF_NIGHT_START), c.DEFAULT_NIGHT_START)
        end = _parse_time(self.house.get(c.CONF_NIGHT_END), c.DEFAULT_NIGHT_END)
        self.night = start <= local < end if start <= end else local >= start or local < end
        self.house_mode = self.modes.mode(now)

    def _update_presence(self, now: float) -> None:
        entities = list(self.house.get(c.CONF_RESIDENTS) or []) + self.residents.trackers + list(self.house.get(c.CONF_EXTRA_TRACKERS) or [])
        anyone = any((state := self.hass.states.get(e)) is not None and state.state == STATE_HOME for e in entities)
        self.modes.set_presence(anyone, now)

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
        self.async_set_updated_data({"score": score, "tier": tier, "mode": self.house_mode, "night": self.night, "incident_id": self.incident_id})

    def _process(self, now: float) -> None:
        """Advance the engine, publish, and hand transitions to the responder."""
        previous = (self.house_mode, self.night)
        self._refresh_mode(now)
        events = self.engine.evaluate(now)
        score = self.engine.score(now)
        for event in events:
            if event.kind == EVENT_CLOSED:
                self.store.add_incident(event.incident.as_dict())
            payload = {c.ATTR_INCIDENT_ID: event.incident.id, "tier": event.tier, "previous_tier": event.previous_tier, "score": round(score, 1)}
            async_dispatcher_send(self.hass, c.SIGNAL_INCIDENT_EVENT, event.kind, {**payload, "room": self.room_name(event.incident.room), "mode": event.incident.mode})
        changed = previous != (self.house_mode, self.night)
        if changed and (recommendation := recommend_arm_mode(self.house_mode, self.night)) != self.recommended_arm:
            self.recommended_arm = recommendation
            self.hass.async_create_task(self.responder.async_arm(recommendation))
        self.publish(now, force=bool(events) or changed)
        incident = self.engine.current
        renotify = incident is not None and incident.tier == TIER_VERIFY and incident.notified_score and score >= 2 * incident.notified_score
        if events or renotify:
            self.hass.async_create_task(self.responder.async_handle(events, incident if renotify else None))

    def _score(self, rule_id: str, now: float, entity_id: str | None, room: str | None, detail: str, points: float | None = None, allow_open: bool = True) -> None:
        self._refresh_mode(now)
        contribution = self.engine.add(rule_id, mode=self.house_mode, night=self.night, now=now, entity_id=entity_id, room=room, detail=detail, points=points, allow_open=allow_open)
        if contribution is None:
            return
        _LOGGER.debug("%s scored %.1f for %s (%s)", rule_id, contribution.points, entity_id, detail)
        if (rule_id == "manual_unlock" and self.house_mode == MODE_VACANT) or rule_id == "keypad_lockout":
            self.hass.async_create_task(self.responder.async_break_glass(f"{rule_id.replace('_', ' ')} on {entity_id}: {detail}"))
        self._process(now)

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
            if old is not None and old.state != STATE_UNAVAILABLE:
                self._offline_since[entity_id] = now
                self._score("sensor_offline", now, entity_id, room, "became unavailable")
            return
        self._offline_since.pop(entity_id, None)
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
        if role == ent.ROLE_TRACKER:
            self._on_arrival(old, new, now)
            return
        if role == ent.ROLE_CALENDAR:
            self._apply_calendar(new)
            self._process(now)
            return
        if role == ent.ROLE_LCM_EVENT:
            self._on_lcm_event(old, new, now)
            return
        ctx = event.context
        origin = classify_origin(
            parent_id=ctx.parent_id, user_id=ctx.user_id, context_id=ctx.id, trusted_user_ids=self.trusted, homekit_contexts=self.homekit_contexts, now=now
        )
        if origin is Origin.USER_UNTRUSTED:
            self._score("untrusted_user", now, entity_id, room, f"changed to {new.state} by user {ctx.user_id}")
            return
        if origin in (Origin.AUTOMATION, Origin.USER_TRUSTED):
            return
        self.modes.note_activity(now)
        self._refresh_mode(now)
        if role == ent.ROLE_OCCUPANCY and _turned_on(old, new):
            self._on_occupancy(entity_id, meta, room, now)
        elif role == ent.ROLE_PERIMETER and _turned_on(old, new):
            self._contact_last_on[entity_id] = now
            self._score("gate_opened" if meta.get("gate") else "exterior_door_opened", now, entity_id, room, f"{origin} open")
        elif role == ent.ROLE_INTERIOR_DOOR and _turned_on(old, new):
            self._score("interior_door_opened", now, entity_id, room, f"{origin} open")
        elif role == ent.ROLE_LIGHT and _turned_on(old, new):
            self._score("light_homekit" if origin is Origin.HOMEKIT else "light_physical", now, entity_id, room, f"{origin} on")
        elif role == ent.ROLE_POWER and _crossed_up(old, new, float(meta.get("threshold", 30))):
            self._score("tv_power", now, entity_id, room, f"{new.state} W")
        elif role == ent.ROLE_WATER and _crossed_up(old, new, float(meta.get("threshold", 1))):
            self._score("water_flow", now, entity_id, room, f"{new.state} flow")
        elif role == ent.ROLE_CSI and _turned_on(old, new):
            contact = (self.house.get(c.CONF_CSI_MAP) or {}).get(entity_id)
            contact_state = self.hass.states.get(contact) if contact else None
            recently = contact and now - self._contact_last_on.get(contact, -1e12) <= c.CSI_CONTACT_WINDOW_S
            if not recently and not (contact_state and contact_state.state == STATE_ON):
                self._score("door_csi_motion", now, entity_id, room, f"CSI motion, {contact or 'no contact'} closed")
        elif role in (ent.ROLE_LOAD, ent.ROLE_AUTOMATED_LOAD) and self.residual is not None:
            self._on_load(now)

    def _on_occupancy(self, entity_id: str, meta: dict[str, Any], room: str | None, now: float) -> None:
        if meta.get("person_detector"):
            rule = "person_exterior_camera" if meta.get("exterior") else "person_interior_camera"
            self._score(rule, now, entity_id, room, "person detected")
            return
        base = self.rules["interior_occupied"].points_for(self.house_mode)
        if base <= 0:
            return
        result = self.occupancy.observe(room or entity_id, entity_id, ent.effective_strength(meta), now, base)
        if result.points <= 0:
            return
        allow_open = not (result.weak_alone and self.house_mode == MODE_VACANT)
        detail = f"{result.strength} source" + (", corroborated" if result.corroborated else "")
        self._score("interior_occupied", now, entity_id, room, detail, points=result.points, allow_open=allow_open)

    def _on_load(self, now: float) -> None:
        load = _number(self.hass.states.get(self.house[c.CONF_LOAD]))
        if load is None:
            return
        automated = sum(_number(self.hass.states.get(e)) or 0.0 for e in self.house.get("automated_loads") or [])
        assert self.residual is not None
        if self.residual.update(load, automated, now):
            self._score("load_residual", now, self.house[c.CONF_LOAD], None, f"residual {self.residual.residual:.0f} W")

    def _on_arrival(self, old: State | None, new: State, now: float) -> None:
        self._update_presence(now)
        # A person and its tracker arrive together; the suppressor applies once per arrival.
        if new.state == STATE_HOME and (old is None or old.state != STATE_HOME) and now - self._last_arrival >= 60:
            self._last_arrival = now
            self.engine.suppress("family_arrival", SUPPRESSOR_FAMILY_ARRIVAL, now=now, detail=f"{new.entity_id} arrived home")
        self._process(now)

    def _on_lcm_event(self, old: State | None, new: State, now: float) -> None:
        self._refresh_lcm_slots()
        if old is None or old.state == new.state:
            return
        name = str(new.attributes.get("name") or "unknown user")
        if new.attributes.get("operation") == "lock":
            self.modes.note_activity(now)
            return
        self.modes.allowed_pin(now)
        self.engine.suppress("allowed_pin", SUPPRESSOR_ALLOWED_PIN, now=now, detail=f"allowed PIN use by {name}", person=name)
        self._process(now)
        self.publish(now, force=True)

    @callback
    def _on_homekit(self, event: Event) -> None:
        self.homekit_contexts.add(event.context.id, self.now())

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
        """Score a lock event from either source once, attributed to a configured lock."""
        locks = self.house.get(c.CONF_LOCKS) or []
        if lock is None and len(locks) == 1 and not self._lock_devices:
            lock = locks[0]
        if locks and lock not in locks:
            return
        kind, slot = classify_lock_notification(label, slot)
        now = self.now()
        if kind is None or now - self._lock_seen.get((lock, kind, slot), -1e12) < c.LOCK_EVENT_DEDUPE_S:
            return
        self._lock_seen[(lock, kind, slot)] = now
        self._refresh_lcm_slots()
        label = str(label or kind)
        if kind == KIND_MANUAL_UNLOCK:
            self._score("manual_unlock", now, lock, None, label)
        elif kind == KIND_KEYPAD_UNLOCK and not pin_allowed(slot, self.lcm_slots):
            self._score("pin_not_allowed", now, lock, None, f"{label}, slot {slot}")
        elif kind == KIND_KEYPAD_LOCKOUT:
            self._score("keypad_lockout", now, lock, None, label)

    @callback
    @_safe
    def _on_mobile_action(self, event: Event) -> None:
        action = str(event.data.get("action") or "")
        if action.startswith(c.MOBILE_ACTION_PREFIX):
            label, incident_id = action[len(c.MOBILE_ACTION_PREFIX) :].lower().split("|", 1)
            self.label(label, incident_id)

    async def _tick(self, _now: datetime) -> None:
        try:
            now = self.now()
            self._update_presence(now)
            if self.residual is not None:
                self._on_load(now)
            self._process(now)
            for entity_id, since in list(self._offline_since.items()):
                if self.house_mode == MODE_VACANT and now - since >= c.OFFLINE_BREAK_GLASS_S and entity_id not in self._break_glass_sent:
                    self._break_glass_sent.add(entity_id)
                    await self.responder.async_break_glass(f"{entity_id} unavailable for over 60 minutes while vacant")
            if self.digest.due(dt_util.now()):
                await self.digest.async_run()
        except Exception:
            _LOGGER.exception("Error in SIEM tick")

    def label(self, label: str, incident_id: str | None = None) -> None:
        """Label an incident and adjust the weights of its rules."""
        incident, changes = self.engine.label(label, incident_id)
        self.last_label = label
        self.store.record_weight_changes(changes, self.now(), label, incident.id)
        if incident.closed:
            self.store.add_incident(incident.as_dict())
        _LOGGER.info("Incident %s labelled %s; weights changed: %s", incident.id, label, changes)
        self.publish(self.now(), force=True)

    def set_house_mode(self, mode: str) -> None:
        """Force a house mode or return to automatic."""
        self.modes.set_override(mode)
        self._process(self.now())
        self.publish(self.now(), force=True)

    async def async_reset_weights(self) -> None:
        """Return every rule weight to 1.0."""
        reset_weights(self.store.weights)
        await self.store.async_save()
        self.publish(self.now(), force=True)

    async def async_set_toggle(self, key: str, value: bool) -> None:
        """Persist a runtime toggle."""
        self.toggles[key] = value
        self.store.toggles = dict(self.toggles)
        await self.store.async_save()
        self.publish(self.now(), force=True)
