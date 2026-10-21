"""Constants for SIEM for Home Assistant."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "siem"
NAME = "SIEM"
MANUFACTURER = "@zacs"
VERSION = "0.0.2"
DOCS_SENSORS_URL = "https://github.com/zacs/ha-siem/blob/main/docs/sensors.md"
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
# An outdoor room (yard, porch, driveway): anything that happens there only means someone is outside.
CONF_OUTDOORS = "outdoors"
ADDITIONAL = "_additional"

# Whole-house fields.
CONF_RESIDENTS = "residents"
CONF_EXTRA_TRACKERS = "extra_trackers"
# Device trackers of guests (a Wi-Fi tracker of a regular visitor's phone): home means guest mode.
CONF_GUEST_TRACKERS = "guest_trackers"
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
# Bedtime sources, read only: the panel armed night, or a sensor (a binary sensor or a helper) that is on, means the
# household is in bed. Either one counts. Only with neither picked does the night window stand in for bedtime.
CONF_ALARM_PANEL = "alarm_panel"
CONF_ASLEEP_SENSOR = "asleep_sensor"
CONF_NIGHT_START = "night_start"
CONF_NIGHT_END = "night_end"

# Responses fields.
CONF_AI_TASK = "ai_task_entity"
CONF_DIGEST_TIMES = "digest_times"
CONF_DIGEST_EMPTY = "digest_post_when_empty"

# Settings removed before the first release, when SIEM became state and events only: no notifications, no alarm panel, no deterrence
# actions, no trusted-user list (every Home Assistant user is trusted) and no dry run or auto alarm switches.
REMOVED_SETTINGS = {
    "rooms": ("deter_lights", "deter_lights_additional", "deter_players", "deter_script"),
    "house": ("trusted_user_ids", "deter_sound", "deter_tts_entity", "deter_tts_message", "deter_volume", "restore_seconds", "house_deter", "house_deter_additional", "house_alarm", "house_alarm_additional"),
    "responses": ("notify_service", "notify_service_2", "target", "mobile_notify_service", "notify_services", "alarm_panel", "auto_arm", "dry_run", "auto_alarm"),
}
# Rules removed since: the HomeKit light rule (HomeKit is Home Assistant acting, like any app) and the camera person
# rules (person detection is now the strongest occupancy source, indoors or out).
REMOVED_RULES = ("untrusted_user", "light_homekit", "person_interior_camera", "person_exterior_camera")
REMOVED_SWITCHES = ("dry_run", "auto_arm", "auto_alarm")

# Options sections.
OPT_RULES = "rules"
OPT_ENGINE = "engine"
# Renamed before the first release; stored options and weights are migrated to the new names.
RENAMED_RULES = {"tv_power": "appliance_on"}
RENAMED_MODES = {"sitter": "guest"}

DEFAULT_POWER_THRESHOLD = 30
DEFAULT_WATER_THRESHOLD = 1.0
DEFAULT_LOAD_STEP = 100
DEFAULT_LOAD_SUSTAIN = 5
DEFAULT_NIGHT_START = "00:00:00"
DEFAULT_NIGHT_END = "05:30:00"
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
# The same entity (a light: the same room) scores the same rule at most once per cooldown: a door used to come in
# and to go out is one visit, a contact bouncing is one opening, a group of bulbs is one switch.
COOLDOWN_S = 300
CSI_CONTACT_WINDOW_S = 60
# Every service call announces its context before it runs; a state change carrying one of these, seen this
# recently, is Home Assistant acting. Refresh-only services are left out: what they report is still physical.
CAUSED_TTL_S = 120
READ_ONLY_SERVICES = frozenset(
    {("homeassistant", "update_entity"), ("zwave_js", "refresh_value"), ("zwave_js", "refresh_notifications"), ("camera", "snapshot")}
)
# A light Home Assistant was told to switch, reporting slowly; an appliance in a room where Home Assistant just
# switched something (a smart plug, a TV through its integration), whose power climbs a little later.
COMMANDED_LIGHT_S = 30
COMMANDED_POWER_S = 120
# Everything seen outside counts as one "someone is outside" window, credited again every fifteen minutes.
OUTSIDE_WINDOW_S = 900
# Covers that let people in when Home Assistant opens them; blinds and shades do not.
ENTRY_COVER_CLASSES = ("garage", "gate", "door")
# A resident arriving home explains everything scored in the ten minutes before.
ARRIVAL_EXPLAINS_S = 600
LET_IN_DEDUPE_S = 60
# The alarm trigger turns on once an incident has held the alarm tier this long.
ALARM_GRACE_S = 60
# Night mode: the household is in bed while the picked panel is armed night. While it is arming, pending or triggered
# it keeps what it was; any other armed or disarmed state means it is not. A bedtime source that is unavailable or
# unknown cannot tell, and the night window stands in for it until it can.
PANEL_ASLEEP = "armed_night"
PANEL_KEEPS = ("arming", "pending", "triggered")
# A door, window or gate that opens within two minutes of someone moving inside is someone going out; the yard and
# the doors are theirs for fifteen minutes after their last sign out there. So is a resident's arrival or a code.
NIGHT_INSIDE_FIRST_S = 120
# Someone is still up when an inside sensor that turned on in the last fifteen minutes is on; one on for longer is
# more likely a presence sensor watching people asleep.
NIGHT_UP_S = 900
NIGHT_FAMILY_OUTSIDE_S = 900
NIGHT_EXPECTED_S = 600
# Inside counts at night only this soon after an entry that counted: the intruder moving in.
NIGHT_AFTER_ENTRY_S = 300
AI_TASK_TIMEOUT_S = 20
SNAPSHOT_TIMEOUT_S = 10
