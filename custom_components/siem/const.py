"""Constants for SIEM for Home Assistant."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "siem"
NAME = "SIEM"
MANUFACTURER = "@zacs"
VERSION = "0.1.0"
PLATFORMS = [Platform.BINARY_SENSOR, Platform.EVENT, Platform.SELECT, Platform.SENSOR, Platform.SWITCH]

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
CONF_DETER_LIGHTS = "deter_lights"
CONF_DETER_PLAYERS = "deter_players"
CONF_DETER_SCRIPT = "deter_script"
ADDITIONAL = "_additional"
ROOM_LIST_FIELDS = (CONF_OCCUPANCY, CONF_PERIMETER, CONF_INTERIOR_DOORS, CONF_LIGHTS, CONF_POWER, CONF_DETER_LIGHTS)

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
CONF_TRUSTED_USERS = "trusted_user_ids"
CONF_NIGHT_START = "night_start"
CONF_NIGHT_END = "night_end"
CONF_DETER_SOUND = "deter_sound"
CONF_DETER_TTS = "deter_tts_entity"
CONF_DETER_TTS_MESSAGE = "deter_tts_message"
CONF_DETER_VOLUME = "deter_volume"
CONF_RESTORE_SECONDS = "restore_seconds"
CONF_HOUSE_DETER = "house_deter"
CONF_HOUSE_ALARM = "house_alarm"

# Responses fields.
CONF_NOTIFY = "notify_service"
CONF_TARGET = "target"
CONF_ALARM_PANEL = "alarm_panel"
CONF_AI_TASK = "ai_task_entity"
CONF_DIGEST_TIMES = "digest_times"
CONF_DIGEST_EMPTY = "digest_post_when_empty"
CONF_DRY_RUN = "dry_run"
CONF_AUTO_ARM = "auto_arm"
CONF_AUTO_ALARM = "auto_alarm"
CONF_NOTIFY_2 = "notify_service_2"
CONF_MOBILE_NOTIFY = "mobile_notify_service"
TOGGLES = (CONF_DRY_RUN, CONF_AUTO_ARM, CONF_AUTO_ALARM)

# Options sections.
OPT_RULES = "rules"
OPT_ENGINE = "engine"

DEFAULT_POWER_THRESHOLD = 30
DEFAULT_WATER_THRESHOLD = 1.0
DEFAULT_LOAD_STEP = 100
DEFAULT_LOAD_SUSTAIN = 5
DEFAULT_NIGHT_START = "22:00:00"
DEFAULT_NIGHT_END = "06:00:00"
DEFAULT_DETER_VOLUME = 0.7
DEFAULT_RESTORE_SECONDS = 60
DEFAULT_NOTIFY = "notify.mattermost"
DEFAULT_TARGET = "home_security"
DEFAULT_DIGEST_TIMES = ["08:00"]

EVENT_ZWAVE_NOTIFICATION = "zwave_js_notification"
# Lock Code Manager normalises every provider's lock activity into this event.
EVENT_LCM_LOCK = "lock_code_manager_lock_state_changed"
LOCK_EVENT_DEDUPE_S = 5
# Core fires ``homekit_state_change``; the documented name is also watched.
EVENTS_HOMEKIT = ("homekit_state_change", "homekit_state_changed")
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

TIER_COLORS = {"verify": "#F5B700", "deter": "#F57C00", "alarm": "#D32F2F", "digest": "#1976D2"}
SNAPSHOT_SUBDIR = ("www", "siem")
TICK_SECONDS = 30
OFFLINE_BREAK_GLASS_S = 3600
ALARM_TRIGGER_SECONDS = 60
CSI_CONTACT_WINDOW_S = 60
AI_TASK_TIMEOUT_S = 20
