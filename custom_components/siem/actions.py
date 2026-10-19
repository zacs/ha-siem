"""Responses: alerts, deterrence, alarm, arming, break-glass and the dry-run gate."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from homeassistant.core import CALLBACK_TYPE, Context, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later

from . import const
from .core.arm import ARM_SERVICES
from .core.dryrun import DRY_RUN_PREFIX, Action, restore_actions, room_deter_actions, whole_house_actions
from .core.incident import EVENT_TIER_CHANGED, Incident, IncidentEvent
from .core.messages import alert_message, alert_title
from .core.scoring import TIER_ALARM, TIER_DETER, TIER_VERIFY, tier_rank

if TYPE_CHECKING:
    from .coordinator import SiemCoordinator

_LOGGER = logging.getLogger(__name__)
ALARM_TRIGGER_ENTITY = "binary_sensor.siem_alarm_trigger"
# Speaker steps depend on each other (snapshot, volume, sound) and run in order; everything else runs at once.
MEDIA_DOMAINS = ("scene", "media_player", "tts")


class Responder:
    """Turn incident transitions into alerts and actions."""

    def __init__(self, hass: HomeAssistant, coordinator: SiemCoordinator) -> None:
        """Bind to the coordinator."""
        self.hass = hass
        self.coordinator = coordinator
        self._root = Context()
        # Rooms whose speakers are snapshotted and not yet restored, and the pending restore timers.
        self._deterring: set[str] = set()
        self._restores: dict[str, CALLBACK_TYPE] = {}

    def context(self) -> Context:
        """Return a child of SIEM's own context, so state changes SIEM causes classify as automation and never score."""
        return Context(parent_id=self._root.id)

    @property
    def dry_run(self) -> bool:
        """Return whether actions are only described."""
        return self.coordinator.toggles[const.CONF_DRY_RUN]

    async def async_handle(self, events: list[IncidentEvent], renotify: Incident | None) -> None:
        """Escalate on upward tier changes; alert again when a verify incident's score doubled."""
        for event in events:
            if event.kind == EVENT_TIER_CHANGED and tier_rank(event.tier) > tier_rank(event.previous_tier):
                try:
                    await self._async_escalate(event.incident, event.tier)
                except Exception:
                    _LOGGER.exception("Response for %s failed", event.tier)
        if renotify is not None:
            await self._async_alert(renotify, TIER_VERIFY, [], again=True)

    async def _async_escalate(self, incident: Incident, tier: str) -> None:
        actions = self.plan(incident, tier) if tier in (TIER_DETER, TIER_ALARM) else []
        if self.dry_run or not actions:
            await self._async_alert(incident, tier, actions)
            return
        c = self.coordinator
        room = incident.room
        restore = restore_actions(room, c.rooms[room]) if room in c.rooms else []
        if restore and room in self._deterring:
            # Still deterring from the last tier: keep the first snapshot, or the restore would bring the deter sound back.
            actions = [a for a in actions if (a.domain, a.service) != ("scene", "create")]
        elif restore:
            self._deterring.add(room)
        # Deterrence never waits for a camera or a slow notify service, and the alert never waits for a speaker.
        await asyncio.gather(self.async_run(actions), self._async_alert(incident, tier, actions))
        if restore:
            if cancel := self._restores.pop(room, None):
                cancel()

            @callback
            def _restore(_now: object) -> None:
                self._restores.pop(room, None)
                self._deterring.discard(room)
                self.hass.async_create_task(self.async_run(restore))

            self._restores[room] = async_call_later(self.hass, float(c.house.get(const.CONF_RESTORE_SECONDS, const.DEFAULT_RESTORE_SECONDS)), _restore)

    async def _async_alert(self, incident: Incident, tier: str, actions: list[Action], again: bool = False) -> None:
        c = self.coordinator
        score = c.engine.score(c.now()) if incident is c.engine.current else incident.peak_score
        if tier == TIER_VERIFY:
            incident.notified_score = score
        snapshot = await c.notifier.async_snapshot(incident, tier)
        rendered = [action.render() for action in actions]
        message = alert_message(score, c.house_mode, c.notifier.timeline_lines(incident), again=again, actions=rendered, dry_run=self.dry_run)
        title = alert_title(tier, c.room_name(incident.room))
        await c.notifier.async_notify(tier, title, message, incident=c.notifier.incident_payload(incident), actions=rendered, snapshot=snapshot, again=again)

    def plan(self, incident: Incident, tier: str) -> list[Action]:
        """Build the action list for ``tier``: room deterrence, whole house, alarm."""
        c = self.coordinator
        actions: list[Action] = []
        if incident.room and (room := c.rooms.get(incident.room)):
            actions += room_deter_actions(incident.room, room, c.house)
        actions += whole_house_actions(c.house_list(const.CONF_HOUSE_DETER))
        if tier == TIER_ALARM:
            actions += whole_house_actions(c.house_list(const.CONF_HOUSE_ALARM))
            if c.toggles[const.CONF_AUTO_ALARM]:
                actions.append(Action(const.DOMAIN, "alarm_trigger", ALARM_TRIGGER_ENTITY, {"seconds": const.ALARM_TRIGGER_SECONDS}))
        return actions

    async def async_run(self, actions: list[Action]) -> None:
        """Execute a plan, never raising: speaker steps in order, everything else in parallel."""

        async def in_order(items: list[Action]) -> None:
            for action in items:
                await self._async_call(action)

        media = [a for a in actions if a.domain in MEDIA_DOMAINS]
        await asyncio.gather(in_order(media), *(self._async_call(a) for a in actions if a.domain not in MEDIA_DOMAINS))

    async def _async_call(self, action: Action) -> bool:
        if action.domain == const.DOMAIN:
            self._pulse_alarm_trigger()
            return True
        data = {**action.data}
        if action.entity_id:
            data["entity_id"] = action.entity_id
        try:
            async with asyncio.timeout(const.ACTION_TIMEOUT_S):
                await self.hass.services.async_call(action.domain, action.service, data, blocking=True, context=self.context())
        except Exception:
            _LOGGER.exception("Action %s failed", action.render())
            return False
        return True

    def _set_alarm_trigger(self, on: bool) -> None:
        self.coordinator.alarm_trigger_on = on
        self.coordinator.publish(force=True)

    def _pulse_alarm_trigger(self) -> None:
        self._set_alarm_trigger(True)
        async_call_later(self.hass, const.ALARM_TRIGGER_SECONDS, callback(lambda _now: self._set_alarm_trigger(False)))

    async def async_arm(self, recommendation: str) -> None:
        """Arm or disarm the panel when auto arm is on, and say what happened (or would have)."""
        c = self.coordinator
        panel = c.responses.get(const.CONF_ALARM_PANEL)
        target = recommendation.replace("_", " ")
        where = c.entity_name(panel) if panel else "the alarm"
        if c.toggles[const.CONF_AUTO_ARM] and not self.dry_run and panel:
            armed = await self._async_call(Action("alarm_control_panel", ARM_SERVICES[recommendation], panel))
            message = f"Set {where} to {target}" if armed else f"Could not set {where} to {target}; see the log"
        else:
            armed = False
            message = f"Would set {where} to {target}"
        message += f" (house {c.house_mode}{', night' if c.night else ''})."
        if self.dry_run:
            message = f"{DRY_RUN_PREFIX} {message}"
        await c.notifier.async_notify(const.CATEGORY_ARM, "SIEM alarm mode", message, recommendation=recommendation, armed=armed, panel=panel)

    async def async_break_glass(self, message: str) -> None:
        """Alert on events that matter whatever the score: a hand unlock while vacant, a keypad lockout, a long outage."""
        c = self.coordinator
        text = f"{message}. House {c.house_mode}."
        if self.dry_run:
            text = f"{DRY_RUN_PREFIX} {text}"
        incident = c.engine.current
        await c.notifier.async_notify(const.CATEGORY_BREAK_GLASS, "SIEM break glass", text, incident=c.notifier.incident_payload(incident) if incident else None)
