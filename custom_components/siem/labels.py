"""Label incidents from a chat button: SIEM's own webhook, posted to with the incident and the label."""

from __future__ import annotations

from aiohttp import web
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .core.weights import LABEL_NAMES, LABELS


async def async_handle_label(hass: HomeAssistant, webhook_id: str, request: web.Request) -> web.Response:
    """Label the incident a button names, and answer in words the person who pressed it will see.

    Takes ``{"incident_id": ..., "label": ...}``, either as the whole body or under ``context``, which is how
    Mattermost and Slack-style interactive buttons send it. The answer is ``{"ephemeral_text": ...}``, which
    Mattermost shows only to whoever pressed the button.
    """
    try:
        data = await request.json()
    except ValueError:
        data = {}
    data = data if isinstance(data, dict) else {}
    context = data["context"] if isinstance(data.get("context"), dict) else data
    label, incident_id = str(context.get("label") or ""), context.get("incident_id")
    coordinator = next((entry.runtime_data for entry in hass.config_entries.async_loaded_entries(DOMAIN)), None)
    if coordinator is None:
        text = "SIEM is not running."
    elif label not in LABELS:
        text = f"SIEM doesn't know the label {label!r}."
    else:
        try:
            labelled, new = coordinator.label(label, str(incident_id) if incident_id else None, by=data.get("user_name"))
        except LookupError:
            text = f"SIEM no longer knows incident {incident_id}."
        else:
            text = f"Incident {labelled} {'labelled' if new else 'was already labelled'} {LABEL_NAMES[label]}."
    return web.json_response({"ephemeral_text": text})
