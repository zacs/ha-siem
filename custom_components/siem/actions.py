"""Responses: deterrence, alarm, arming, break-glass and the dry-run gate."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later

from . import const
from .core.arm import ARM_SERVICES
from .core.dryrun import DRY_RUN_PREFIX, Action, dry_run_message, restore_actions, room_deter_actions, whole_house_actions
from .core.incident import EVENT_TIER_CHANGED, Incident, IncidentEvent
from .core.scoring import TIER_ALARM, TIER_DETER, TIER_VERIFY, tier_rank

if TYPE_CHECKING:
    from .coordinator import SiemCoordinator

_LOGGER = logging.getLogger(__name__)
ALARM_TRIGGER_ENTITY = "binary_sensor.siem_alarm_trigger"


class Responder:
    """Turn incident transitions into notifications and actions."""

    def __init__(self, hass: HomeAssistant, coordinator: SiemCoordinator) -> None:
        """Bind to the coordinator."""
        self.hass = hass
        self.coordinator = coordinator
        # Our own actions carry a child context so the state changes they cause classify as automation and never score.
        self._root = Context()

    @property
    def dry_run(self) -> bool:
        """Return whether actions are only described."""
        return self.coordinator.toggles[const.CONF_DRY_RUN]

    async def async_handle(self, events: list[IncidentEvent], renotify: Incident | None) -> None:
        """Escalate on upward tier changes; re-verify when the score doubled."""
        for event in events:
            if event.kind == EVENT_TIER_CHANGED and tier_rank(event.tier) > tier_rank(event.previous_tier):
                try:
                    await self._async_escalate(event.incident, event.tier)
                except Exception:
                    _LOGGER.exception("Response for %s failed", event.tier)
        if renotify is not None:
            await self._async_verify(renotify, again=True)

    async def _async_escalate(self, incident: Incident, tier: str) -> None:
        if tier == TIER_VERIFY:
            await self._async_verify(incident)
        elif tier in (TIER_DETER, TIER_ALARM):
            await self._async_deter(incident, tier)

    def _camera(self, incident: Incident) -> str | None:
        return self.coordinator.rooms.get(incident.room or "", {}).get(const.CONF_CAMERA)

    async def _async_notify(self, incident: Incident, tier: str, message: str) -> None:
        notifier = self.coordinator.notifier
        await notifier.async_send(message, attachment=notifier.incident_attachment(incident, tier), camera=self._camera(incident), incident_id=incident.id)
        await notifier.async_send_actionable(incident, message)

    async def _async_verify(self, incident: Incident, again: bool = False) -> None:
        c = self.coordinator
        incident.notified_score = c.score
        message = f"Verify: score {c.score:.0f} in {c.room_name(incident.room) or 'the house'} ({incident.mode})" + (", score doubled" if again else "")
        await self._async_notify(incident, TIER_VERIFY, f"{DRY_RUN_PREFIX} {message}" if self.dry_run else message)

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

    async def _async_deter(self, incident: Incident, tier: str) -> None:
        c = self.coordinator
        actions = self.plan(incident, tier)
        message = f"{tier.capitalize()}: score {c.score:.0f} in {c.room_name(incident.room) or 'the house'} ({incident.mode})"
        if self.dry_run:
            await self._async_notify(incident, tier, dry_run_message(message, actions))
            return
        await self._async_notify(incident, tier, message)
        await self.async_run(actions)
        if incident.room and (room := c.rooms.get(incident.room)) and restore_actions(incident.room, room):
            delay = float(c.house.get(const.CONF_RESTORE_SECONDS, const.DEFAULT_RESTORE_SECONDS))
            async_call_later(self.hass, delay, callback(lambda _now: self.hass.async_create_task(self.async_run(restore_actions(incident.room, room)))))

    async def async_run(self, actions: list[Action]) -> None:
        """Execute a plan, one service call at a time, never raising."""
        for action in actions:
            if action.domain == const.DOMAIN:
                self._pulse_alarm_trigger()
                continue
            data = {**action.data}
            if action.entity_id:
                data["entity_id"] = action.entity_id
            try:
                await self.hass.services.async_call(action.domain, action.service, data, blocking=True, context=Context(parent_id=self._root.id))
            except Exception:
                _LOGGER.exception("Action %s failed", action.render())

    def _set_alarm_trigger(self, on: bool) -> None:
        self.coordinator.alarm_trigger_on = on
        self.coordinator.publish(force=True)

    def _pulse_alarm_trigger(self) -> None:
        self._set_alarm_trigger(True)
        async_call_later(self.hass, const.ALARM_TRIGGER_SECONDS, callback(lambda _now: self._set_alarm_trigger(False)))

    async def async_arm(self, recommendation: str) -> None:
        """Arm the panel when allowed, otherwise say what would have happened."""
        c = self.coordinator
        panel = c.responses.get(const.CONF_ALARM_PANEL)
        if c.toggles[const.CONF_AUTO_ARM] and not self.dry_run and panel:
            try:
                await self.hass.services.async_call("alarm_control_panel", ARM_SERVICES[recommendation], {"entity_id": panel}, blocking=True, context=Context(parent_id=self._root.id))
            except Exception:
                _LOGGER.exception("Arming %s as %s failed", panel, recommendation)
            return
        message = f"Would arm {panel or 'the alarm'} to {recommendation} (house mode {c.house_mode}{', night' if c.night else ''})"
        if self.dry_run:
            message = dry_run_message(message, [Action("alarm_control_panel", ARM_SERVICES[recommendation], panel)] if panel else [])
        await c.notifier.async_send(message)

    async def async_break_glass(self, message: str) -> None:
        """Fan out to both notify services."""
        c = self.coordinator
        services = [c.responses.get(const.CONF_NOTIFY) or const.DEFAULT_NOTIFY]
        if second := c.responses.get(const.CONF_NOTIFY_2):
            services.append(second)
        text = f"Break glass: {message} (house mode {c.house_mode})"
        if self.dry_run:
            text = f"{DRY_RUN_PREFIX} {text}"
        await c.notifier.async_send(text, attachment={"color": "#D32F2F", "title": "Break glass", "fields": [], "text": message}, services=services)
