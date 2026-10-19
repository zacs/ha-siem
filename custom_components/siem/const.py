"""Constants for SIEM for Home Assistant."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "siem"
NAME = "SIEM"
MANUFACTURER = "@zacs"
VERSION = "0.2.0"
PLATFORMS = [Platform.BINARY_SENSOR, Platform.EVENT, Platform.SELECT, Platform.SENSOR]

# Config entry data sections.
CONF_ROOMS = "rooms"
CONF_HOUSE = "house"
CONF_RESPONSES = "responses"
CONF_ENTITIES = "entities"

# Per-room fields. Filtered fields carry an unfiltered "_additional" twin.
CONF_NAME = "name"
CONF_OCCUPANCY = "occupancy"
CONF_PERIMETER = "perimeter"
CONF_INTERIOR_DOORS = "interior_doors"
CONF_LIGHTS = "lights"
CONF_POWER = "power"
CONF_POWER_THRESHOLD = "power_threshold"
CONF_CAMERA = "camera"
ADDITIONAL = "_additional"

# Whole-house fields.
CONF_RESIDENTS = "residents"
CONF_EXTRA_TRACKERS = "extra_trackers"
CONF_CSI = "csi_sensors"
CONF_CSI_MAP = "csi_map"
CONF_WATER = "water_flow"
CONF_WATER_THRESHOLD = "water_threshold"
CONF_LOAD = "load_sensor"
CONF_AUTOMATED_LOADS = "automated_loads"
CONF_LOAD_STEP = "load_step_watts"
CONF_LOAD_SUSTAIN = "load_sustain_minutes"
CONF_LOCKS = "locks"
CONF_LCM_EVENTS = "lcm_events"
CONF_CALENDAR = "calendar"
CONF_NIGHT_START = "night_start"
CONF_NIGHT_END = "night_end"

# Responses fields.
CONF_AI_TASK = "ai_task_entity"
CONF_DIGEST_TIMES = "digest_times"
CONF_DIGEST_EMPTY = "digest_post_when_empty"

# Settings removed in 0.2, when SIEM became state and events only: no notifications, no alarm panel, no deterrence
# actions, no trusted-user list (every Home Assistant user is trusted) and no dry run or auto alarm switches.
REMOVED_SETTINGS = {
    "rooms": ("deter_lights", "deter_lights_additional", "deter_players", "deter_script"),
    "house": ("trusted_user_ids", "deter_sound", "deter_tts_entity", "deter_tts_message", "deter_volume", "restore_seconds", "house_deter", "house_deter_additional", "house_alarm", "house_alarm_additional"),
    "responses": ("notify_service", "notify_service_2", "target", "mobile_notify_service", "notify_services", "alarm_panel", "auto_arm", "dry_run", "auto_alarm"),
}
REMOVED_RULES = ("untrusted_user",)
REMOVED_SWITCHES = ("dry_run", "auto_arm", "auto_alarm")

# Options sections.
OPT_RULES = "rules"
OPT_ENGINE = "engine"
# Renamed in 0.2; stored options and weights are migrated to the new names.
RENAMED_RULES = {"tv_power": "appliance_on"}
RENAMED_MODES = {"sitter": "guest"}

DEFAULT_POWER_THRESHOLD = 30
DEFAULT_WATER_THRESHOLD = 1.0
DEFAULT_LOAD_STEP = 100
DEFAULT_LOAD_SUSTAIN = 5
DEFAULT_NIGHT_START = "22:00:00"
DEFAULT_NIGHT_END = "06:00:00"
DEFAULT_DIGEST_TIMES = ["08:00"]

# Events SIEM fires for automations to build on.
EVENT_INCIDENT = "siem_incident"
EVENT_NOTIFICATION = "siem_notification"
CATEGORY_BREAK_GLASS, CATEGORY_DIGEST = "break_glass", "digest"

# Events SIEM listens to.
EVENT_ZWAVE_NOTIFICATION = "zwave_js_notification"
# Lock Code Manager normalises every provider's lock activity into this event.
EVENT_LCM_LOCK = "lock_code_manager_lock_state_changed"
LOCK_EVENT_DEDUPE_S = 5
# Core fires ``homekit_state_change``; the documented name is also watched.
EVENTS_HOMEKIT = ("homekit_state_change", "homekit_state_changed")
# Fired with the context an automation or script runs under, so its state changes are not mistaken for physical ones.
EVENTS_AUTOMATION = ("automation_triggered", "script_started")
EVENT_MOBILE_ACTION = "mobile_app_notification_action"
MOBILE_ACTION_PREFIX = "SIEM_LABEL_"

SERVICE_LABEL_INCIDENT = "label_incident"
SERVICE_RUN_DIGEST = "run_digest"
SERVICE_RESET_WEIGHTS = "reset_weights"
SERVICE_SET_HOUSE_MODE = "set_house_mode"
ATTR_INCIDENT_ID = "incident_id"
ATTR_LABEL = "label"
ATTR_MODE = "mode"

SIGNAL_INCIDENT_EVENT = f"{DOMAIN}_incident_event"

SNAPSHOT_DIR = "siem"
SNAPSHOT_KEEP = 200
TICK_SECONDS = 30
# A sensor must stay unavailable this long before it scores, so an integration reload or restart does not.
OFFLINE_GRACE_S = 120
OFFLINE_BREAK_GLASS_S = 3600
# The same entity (a light: the same room) scores the same rule at most once per cooldown.
COOLDOWN_S = 60
CSI_CONTACT_WINDOW_S = 60
AI_TASK_TIMEOUT_S = 20
SNAPSHOT_TIMEOUT_S = 10
