"""End-to-end scenarios: a whole house, real days, and what SIEM should make of them.

Each test tells a short story (a family evening, a mail carrier, a cleaner, a burglary) against a house built
the way Home Assistant would have it: areas, devices and entities in the registries, SIEM set up from them.
Changes come either physically (a device reporting, with a fresh context) or from Home Assistant (a service
call: an automation, the app, a voice assistant, HomeKit Bridge, Presence Simulation). The assertions are the
outcome a person would expect: no alert, a verify, a deter, an alarm, a break-glass message, and whether the
alarm trigger for the panel turned on.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import Context, ServiceCall, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.siem.config_flow import build_entity_meta
from custom_components.siem.const import DOMAIN

from .conftest import RESIDENT, notifications, tick

INDOORS = {"living_room": "Living Room", "kitchen": "Kitchen", "bedroom": "Bedroom", "hallway": "Hallway", "garage": "Garage"}
OUTDOORS = {"front_porch": "Front Porch", "driveway": "Driveway", "backyard": "Backyard"}

# object id -> (area, device class, friendly name, initial state, SIEM room field)
ENTITIES: dict[str, tuple[str | None, str | None, str, str, str | None]] = {
    "binary_sensor.living_motion": ("living_room", "motion", "Living Room Motion", "off", "occupancy"),
    "light.living_ceiling": ("living_room", None, "Living Room Ceiling", "off", "lights"),
    "media_player.tv": ("living_room", None, "TV", "off", None),
    "sensor.tv_power": ("living_room", "power", "TV Power", "2", "power"),
    "binary_sensor.kitchen_presence": ("kitchen", "presence", "Kitchen Presence", "off", "occupancy"),
    "binary_sensor.back_door": ("kitchen", "door", "Back Door", "off", "perimeter"),
    "binary_sensor.fridge_door": ("kitchen", "door", "Fridge Door", "off", "interior_doors"),
    "light.kitchen": ("kitchen", None, "Kitchen Light", "off", "lights"),
    "sensor.kettle_power": ("kitchen", "power", "Kettle Power", "0", "power"),
    "binary_sensor.bedroom_motion": ("bedroom", "motion", "Bedroom Motion", "off", "occupancy"),
    "binary_sensor.bedroom_window": ("bedroom", "window", "Bedroom Window", "off", "perimeter"),
    "binary_sensor.closet_door": ("bedroom", "door", "Closet Door", "off", "interior_doors"),
    "light.bedroom": ("bedroom", None, "Bedroom Light", "off", "lights"),
    "binary_sensor.hall_motion": ("hallway", "motion", "Hall Motion", "off", "occupancy"),
    "binary_sensor.front_door": ("hallway", "door", "Front Door", "off", "perimeter"),
    "light.hallway": ("hallway", None, "Hallway Light", "off", "lights"),
    "binary_sensor.garage_door": ("garage", "garage_door", "Garage Door", "off", "perimeter"),
    "binary_sensor.garage_motion": ("garage", "motion", "Garage Motion", "off", "occupancy"),
    "cover.garage": ("garage", "garage", "Garage Door Opener", "closed", None),
    "binary_sensor.porch_person": ("front_porch", "occupancy", "Doorbell Person", "off", "occupancy"),
    "binary_sensor.porch_motion": ("front_porch", "motion", "Doorbell Motion", "off", "occupancy"),
    "light.porch_flood": ("front_porch", None, "Porch Floodlight", "off", "lights"),
    "binary_sensor.driveway_motion": ("driveway", "motion", "Driveway Motion", "off", "occupancy"),
    "binary_sensor.backyard_motion": ("backyard", "motion", "Backyard Motion", "off", "occupancy"),
    "binary_sensor.backyard_person": ("backyard", "occupancy", "Backyard Camera Person", "off", "occupancy"),
    "binary_sensor.side_gate": ("backyard", "door", "Side Gate", "off", "perimeter"),
    # A lamp on a smart plug: the device sits in the living room, its entities inherit the area.
    "switch.lamp_plug": (None, None, "Lamp Plug", "off", None),
    "sensor.lamp_plug_power": (None, "power", "Lamp Plug Power", "0", "power"),
    "binary_sensor.front_door_csi": (None, None, "Front Door Wi-Fi Motion", "off", None),
    "sensor.water_flow": (None, "volume_flow_rate", "Water Flow", "0", None),
    "lock.front_door": ("hallway", None, "Front Door Lock", "locked", None),
}
PEOPLE: dict[str, tuple[str, dict[str, Any]]] = {
    "device_tracker.alex_phone": ("home", {"friendly_name": "Alex Phone"}),
    "person.alex": ("home", {"device_trackers": ["device_tracker.alex_phone"], "user_id": RESIDENT, "friendly_name": "Alex"}),
    # Jordan does not use Home Assistant; their phone is seen by the router integration.
    "device_tracker.jordan_phone": ("home", {"friendly_name": "Jordan Phone"}),
    "event.lcm_cleaner": ("unknown", {"code_slot": 5, "name": "Cleaner", "active": True, "friendly_name": "Cleaner code used"}),
    "event.lcm_old_sitter": ("unknown", {"code_slot": 6, "name": "Old sitter", "active": False, "friendly_name": "Old sitter code used"}),
    "calendar.house": ("off", {"friendly_name": "House"}),
}


class House:
    """A loaded SIEM in a registry-backed house, and the ways things can happen in it."""

    def __init__(self, hass, freezer, entry: MockConfigEntry, events: list) -> None:
        self.hass, self.freezer, self.entry, self.events = hass, freezer, entry, events
        self.trigger_seen = False

        @callback
        def watch_trigger(event) -> None:
            if event.data["entity_id"] == "binary_sensor.siem_alarm_trigger" and event.data["new_state"].state == "on":
                self.trigger_seen = True

        hass.bus.async_listen("state_changed", watch_trigger)

    @property
    def coordinator(self):
        return self.entry.runtime_data

    async def physical(self, entity_id: str, state: str = "on") -> None:
        """A device reporting a change nothing in Home Assistant asked for."""
        old = self.hass.states.get(entity_id)
        self.hass.states.async_set(entity_id, state, dict(old.attributes), context=Context())
        await self.hass.async_block_till_done()

    async def pulse(self, *entity_ids: str) -> None:
        """Motion or a door: on, then back off."""
        for entity_id in entity_ids:
            await self.physical(entity_id, "on")
            await self.physical(entity_id, "off")

    async def ha(self, entity_id: str, state: str = "on", context: Context | None = None) -> None:
        """Home Assistant changing something through a service call, under the given context."""
        await self.hass.services.async_call("scenario", "set", {"entity_id": entity_id, "state": state}, blocking=True, context=context or Context())
        await self.hass.async_block_till_done()

    async def wait(self, seconds: float) -> None:
        await tick(self.hass, self.freezer, seconds)

    async def lock_event(self, label: str, slot: int = 0) -> None:
        """What the lock reports, as Lock Code Manager (or Z-Wave JS) relays it."""
        self.hass.bus.async_fire("lock_code_manager_lock_state_changed", {"entity_id": "lock.front_door", "action_text": label, "code_slot": slot})
        await self.hass.async_block_till_done()

    async def code(self, slot: int) -> None:
        """Someone types a code the lock accepts; Lock Code Manager's event entity fires for the slots it manages."""
        await self.lock_event("Keypad unlock operation", slot)
        event_entity = {5: "event.lcm_cleaner", 6: "event.lcm_old_sitter"}.get(slot)
        if event_entity:
            old = self.hass.states.get(event_entity)
            self.hass.states.async_set(event_entity, dt_util.utcnow().isoformat(), {**old.attributes, "operation": "unlock"})
        await self.physical("lock.front_door", "unlocked")

    async def leave(self, *trackers: str) -> None:
        for tracker in trackers:
            await self.physical(tracker, "not_home")
            if tracker == "device_tracker.alex_phone":
                await self.physical("person.alex", "not_home")

    async def arrive(self, *trackers: str) -> None:
        for tracker in trackers:
            await self.physical(tracker, "home")
            if tracker == "device_tracker.alex_phone":
                await self.physical("person.alex", "home")

    async def calendar(self, message: str, start: str, end: str) -> None:
        self.hass.states.async_set("calendar.house", "on", {"message": message, "start_time": start, "end_time": end, "friendly_name": "House"})
        await self.hass.async_block_till_done()

    async def vacation(self) -> None:
        """Everyone leaves and the half hour of grace for a forgotten phone runs out."""
        await self.leave("device_tracker.alex_phone", "device_tracker.jordan_phone")
        await self.wait(31 * 60)
        assert self.mode == "vacant"

    @property
    def mode(self) -> str:
        return self.hass.states.get("sensor.siem_house_mode").state

    @property
    def score(self) -> float:
        """The live score; the sensor is rate-limited to tier changes and moves of a point every 30 seconds."""
        return round(self.coordinator.engine.score(self.coordinator.now()), 1)

    @property
    def trigger(self) -> bool:
        return self.hass.states.get("binary_sensor.siem_alarm_trigger").state == "on"

    @property
    def alerts(self) -> list[str]:
        """The siem_notification categories so far, in order, digests aside."""
        return [n["category"] for n in notifications(self.events) if n["category"] != "digest"]

    def rules(self) -> list[str]:
        incident = self.coordinator.engine.current
        return [] if incident is None else [c.rule_id for c in incident.contributions]


@pytest.fixture
async def house(hass, freezer, siem_events):
    """Build the registries and states, then a factory that loads SIEM on them."""
    freezer.move_to("2026-10-19 12:00:00-07:00")
    owner = MockConfigEntry(domain="scenario")
    owner.add_to_hass(hass)
    areas = ar.async_get(hass)
    for area_id, name in {**INDOORS, **OUTDOORS}.items():
        areas.async_create(name)
        assert areas.async_get_area(area_id) is not None, area_id
    plug = dr.async_get(hass).async_get_or_create(config_entry_id=owner.entry_id, identifiers={("scenario", "lamp_plug")}, name="Lamp Plug")
    dr.async_get(hass).async_update_device(plug.id, area_id="living_room")
    registry = er.async_get(hass)
    for entity_id, (area, device_class, name, state, _) in ENTITIES.items():
        domain, object_id = entity_id.split(".")
        device = plug.id if object_id.startswith("lamp_plug") else None
        entry = registry.async_get_or_create(domain, "scenario", object_id, suggested_object_id=object_id, original_name=name, original_device_class=device_class, device_id=device, config_entry=owner)
        assert entry.entity_id == entity_id
        if area:
            registry.async_update_entity(entity_id, area_id=area)
        attributes = {"friendly_name": name, **({"device_class": device_class} if device_class else {})}
        hass.states.async_set(entity_id, state, attributes)
    for entity_id, (state, attributes) in PEOPLE.items():
        hass.states.async_set(entity_id, state, attributes)

    async def integration(call: ServiceCall) -> None:
        """Any integration acting on a service call: the state it writes carries the call's context."""
        old = hass.states.get(call.data["entity_id"])
        hass.states.async_set(call.data["entity_id"], call.data["state"], dict(old.attributes) if old else {}, context=call.context)

    async def area_on(call: ServiceCall) -> None:
        """A scene or an automation targeting an area: the lights it switches carry the call's context, unnamed."""
        for entity_id, (area, *_) in ENTITIES.items():
            if area == call.data["area_id"] and entity_id.startswith("light."):
                hass.states.async_set(entity_id, "on", dict(hass.states.get(entity_id).attributes), context=call.context)

    def device(entity_id: str, state: str):
        async def handler(call: ServiceCall) -> None:
            hass.states.async_set(entity_id, state, dict(hass.states.get(entity_id).attributes), context=call.context)

        return handler

    hass.services.async_register("scenario", "set", integration)
    hass.services.async_register("scenario", "area_on", area_on)
    hass.services.async_register("lock", "unlock", device("lock.front_door", "unlocked"))
    hass.services.async_register("cover", "open_cover", device("cover.garage", "open"))

    async def load(*, trackers: tuple[str, ...] = ("device_tracker.jordan_phone",), weak: tuple[str, ...] = ()) -> House:
        rooms: dict[str, dict[str, Any]] = {}
        for area_id, name in {**INDOORS, **OUTDOORS}.items():
            rooms[area_id] = {"name": name, "outdoors": area_id in OUTDOORS, "power_threshold": 30}
        for entity_id, (area, _, _, _, field) in ENTITIES.items():
            if field:
                rooms[area or "living_room"].setdefault(field, []).append(entity_id)
        data = {
            "rooms": rooms,
            "house": {
                "residents": ["person.alex"],
                "extra_trackers": list(trackers),
                "csi_sensors": ["binary_sensor.front_door_csi"],
                "csi_map": {"binary_sensor.front_door_csi": "binary_sensor.front_door"},
                "water_flow": ["sensor.water_flow"],
                "water_threshold": 1,
                "locks": ["lock.front_door"],
                "lcm_events": ["event.lcm_cleaner", "event.lcm_old_sitter"],
                "calendar": "calendar.house",
                "night_start": "22:00:00",
                "night_end": "06:00:00",
            },
            "responses": {"digest_times": ["08:00"]},
        }
        data["entities"] = build_entity_meta(hass, data)
        for entity_id in weak:
            data["entities"][entity_id]["strength_override"] = "weak"
        entry = MockConfigEntry(domain=DOMAIN, title="SIEM", data=data, version=1, minor_version=5)
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        return House(hass, freezer, entry, siem_events)

    return load


# --- Somebody is home -------------------------------------------------------------------------------------------


async def test_a_family_evening_is_silent(house, freezer):
    """Everyone home: switches, the fridge, the kettle, the TV, the kids in and out of the back door."""
    freezer.move_to("2026-10-19 17:30:00-07:00")
    home = await house()
    assert home.mode == "family"
    for _ in range(6):
        await home.pulse("binary_sensor.kitchen_presence", "binary_sensor.fridge_door", "binary_sensor.back_door", "binary_sensor.backyard_motion")
        await home.physical("light.kitchen")
        await home.physical("sensor.kettle_power", "1800")
        await home.physical("sensor.tv_power", "120")
        await home.physical("sensor.water_flow", "6")
        await home.wait(600)
        for entity_id, idle in (("light.kitchen", "off"), ("sensor.kettle_power", "0"), ("sensor.tv_power", "2"), ("sensor.water_flow", "0")):
            await home.physical(entity_id, idle)
    assert home.alerts == [] and home.rules() == [] and not home.trigger_seen


async def test_a_business_trip_with_the_family_home_and_apple_home(house, freezer):
    """Alex leaves for a week. Jordan and the kids stay; Jordan never opens Home Assistant but uses Apple Home,
    which reaches the house through HomeKit Bridge. Jordan's phone is a router tracker, so the house stays family."""
    freezer.move_to("2026-10-19 07:00:00-07:00")
    home = await house()
    await home.leave("device_tracker.alex_phone")
    await home.wait(45 * 60)
    assert home.mode == "family"
    for hour in range(14):
        await home.ha("light.living_ceiling", "on" if hour % 2 else "off")  # Apple Home, through HomeKit Bridge
        await home.pulse("binary_sensor.living_motion", "binary_sensor.hall_motion", "binary_sensor.front_door", "binary_sensor.closet_door")
        await home.physical("light.bedroom", "on" if hour % 2 else "off")
        await home.wait(3600)
    assert home.alerts == [] and home.rules() == []


async def test_without_a_tracker_for_the_spouse_the_house_reads_vacant(house, freezer):
    """The same trip, but nothing tells SIEM that Jordan is home: once Alex's grace runs out, Jordan's own
    footsteps are an intruder's. This is why everyone who lives there needs a tracker, or the mode override."""
    freezer.move_to("2026-10-19 07:00:00-07:00")
    home = await house(trackers=())
    await home.leave("device_tracker.alex_phone")
    await home.wait(31 * 60)
    assert home.mode == "vacant"
    await home.pulse("binary_sensor.hall_motion")
    await home.physical("light.kitchen")
    await home.pulse("binary_sensor.kitchen_presence")
    assert home.alerts[0] == "verify" and "alarm" in home.alerts
    # Setting the mode by hand for the week is the fix when a tracker is not an option.
    await home.hass.services.async_call("siem", "set_house_mode", {"mode": "family"}, blocking=True)
    await home.wait(3 * 3600)
    before = list(home.alerts)
    await home.pulse("binary_sensor.hall_motion", "binary_sensor.fridge_door", "binary_sensor.back_door")
    assert home.alerts == before


async def test_kids_in_the_yard_and_through_the_gate(house, freezer):
    """Family home on a Saturday: an hour of backyard play, the side gate, the camera seeing people."""
    freezer.move_to("2026-10-24 14:00:00-07:00")
    home = await house()
    for _ in range(12):
        await home.pulse("binary_sensor.backyard_motion", "binary_sensor.backyard_person", "binary_sensor.side_gate", "binary_sensor.back_door")
        await home.wait(300)
    assert home.alerts == [] and home.rules() == []


async def test_a_keypad_lockout_at_night_with_the_family_asleep(house, freezer):
    """2 a.m., everyone in bed, someone keeps trying codes until the keypad locks out. One wrong code earlier was a typo."""
    freezer.move_to("2026-10-20 02:00:00-07:00")
    home = await house()
    await home.lock_event("Invalid code")
    assert home.alerts == []
    await home.wait(120)
    await home.lock_event("Keypad temporarily disabled")
    # keypad_lockout scores 30 with the family home: verify, and a break-glass message.
    assert home.rules() == ["keypad_lockout"]
    assert home.alerts == ["break_glass", "verify"]
    assert not home.trigger_seen


async def test_a_kid_comes_home_with_their_own_code(house, freezer):
    """A code Lock Code Manager does not manage (or no Lock Code Manager at all): the lock accepted it, so it is
    someone who was given a code."""
    freezer.move_to("2026-10-19 15:30:00-07:00")
    home = await house()
    await home.code(slot=3)
    await home.pulse("binary_sensor.front_door", "binary_sensor.hall_motion")
    assert home.alerts == [] and home.mode == "family"


async def test_a_family_asleep_leaves_intruders_to_the_alarm_panel(house, freezer):
    """A known limit: with residents home SIEM scores nothing but lock trouble, at night too. An armed-night
    alarm panel covers a break-in while everyone sleeps; SIEM's job is the empty house."""
    freezer.move_to("2026-10-20 03:00:00-07:00")
    home = await house()
    await home.pulse("binary_sensor.side_gate", "binary_sensor.back_door", "binary_sensor.kitchen_presence")
    assert home.alerts == [] and home.rules() == []


# --- The house is empty ------------------------------------------------------------------------------------------


async def test_the_mail_carrier_rings_the_doorbell(house, freezer):
    """On vacation. Midday, the carrier walks up the drive, the doorbell sees a person, the floodlight's own
    sensor turns it on, the Wi-Fi motion at the door picks them up, nobody answers and they leave.

    Outside counts once: the person detection (strong, 10) corroborated by motion (x1.3) is 13, and the
    door that never opened adds 5. 18 is under verify."""
    home = await house()
    await home.vacation()
    freezer.move_to("2026-10-20 11:40:00-07:00")
    await home.pulse("binary_sensor.driveway_motion", "binary_sensor.porch_motion", "binary_sensor.porch_person")
    await home.physical("light.porch_flood")
    await home.pulse("binary_sensor.front_door_csi")
    assert home.score == pytest.approx(18, abs=0.5)
    await home.wait(90)
    await home.pulse("binary_sensor.porch_motion", "binary_sensor.driveway_motion")
    assert home.score < 18
    assert home.alerts == []


async def test_a_package_at_the_door_late_at_night(house, freezer):
    """The same visit at 11 p.m.: outside things count half again at night, 19.5 + 7.5 = 27, a verify."""
    home = await house()
    await home.vacation()
    freezer.move_to("2026-10-20 23:00:00-07:00")
    await home.pulse("binary_sensor.driveway_motion", "binary_sensor.porch_person", "binary_sensor.front_door_csi")
    assert home.score == pytest.approx(27, abs=0.5)
    assert home.alerts == ["verify"]


async def test_a_delivery_through_the_side_gate(house, freezer):
    """A driver opens the side gate to leave a parcel by the back door: gate 30 + someone outside 13 = 43, verify.
    The gate on the way out is the same visit."""
    home = await house()
    await home.vacation()
    freezer.move_to("2026-10-20 13:00:00-07:00")
    await home.pulse("binary_sensor.side_gate", "binary_sensor.backyard_person", "binary_sensor.backyard_motion")
    assert home.score == pytest.approx(43, abs=0.5)
    await home.wait(90)
    await home.pulse("binary_sensor.side_gate")
    assert home.alerts == ["verify"]
    assert home.rules() == ["gate_opened", "exterior_occupied", "exterior_occupied"]


async def test_someone_lingering_in_the_backyard_at_night(house, freezer):
    """1 a.m., someone hangs around the backyard for forty minutes without trying anything. Outside is credited
    once per fifteen minutes (19.5 at night with the camera and the motion agreeing), so lingering builds to a
    verify, announced once, and never past it."""
    home = await house()
    await home.vacation()
    freezer.move_to("2026-10-21 01:00:00-07:00")
    for _ in range(40):
        await home.pulse("binary_sensor.backyard_motion", "binary_sensor.backyard_person")
        await home.wait(60)
    assert home.alerts == ["verify"]
    assert 20 <= home.score < 50


async def test_a_prowler_through_the_gate_at_night(house, freezer):
    """1 a.m., someone comes through the side gate into the backyard: gate 45 + outside 19.5, a deter, so the
    deterrence automation lights the backyard up. The back door stays shut."""
    home = await house()
    await home.vacation()
    freezer.move_to("2026-10-21 01:00:00-07:00")
    await home.pulse("binary_sensor.side_gate", "binary_sensor.backyard_motion", "binary_sensor.backyard_person")
    assert home.alerts == ["verify", "deter"]
    assert not home.trigger_seen


async def test_a_daytime_burglary_through_the_back(house, freezer):
    """Side gate (30), someone in the backyard (13), the back door (40 x 1.5 after the gate), the kitchen
    (presence, strong 50 x 1.5 after the door): alarm, and a minute later the trigger for the panel."""
    home = await house()
    await home.vacation()
    freezer.move_to("2026-10-21 10:15:00-07:00")
    await home.pulse("binary_sensor.side_gate", "binary_sensor.backyard_person")
    await home.wait(20)
    await home.physical("binary_sensor.back_door")
    await home.pulse("binary_sensor.kitchen_presence")
    assert home.alerts == ["verify", "alarm"]
    assert not home.trigger
    await home.wait(30)
    assert not home.trigger
    await home.wait(30)
    assert home.trigger


async def test_a_burglar_through_a_window_with_no_sensor(house, freezer):
    """No contact to trip: bedroom motion (30), the hall (30), then the closet (40 x 1.5 after someone was in a
    room). Medium motion sensors alone take three rooms to reach alarm."""
    home = await house()
    await home.vacation()
    freezer.move_to("2026-10-21 14:00:00-07:00")
    await home.pulse("binary_sensor.bedroom_motion")
    assert home.alerts == ["verify"]
    await home.pulse("binary_sensor.hall_motion")
    assert home.alerts == ["verify", "deter"]
    await home.pulse("binary_sensor.closet_door")
    assert home.alerts == ["verify", "deter", "alarm"]
    await home.wait(60)
    assert home.trigger


async def test_the_front_door_opening_at_night(house, freezer):
    """2 a.m.: the front door (60 at night) is a deter by itself; the hall motion after it makes it an alarm."""
    home = await house()
    await home.vacation()
    freezer.move_to("2026-10-21 02:00:00-07:00")
    await home.physical("binary_sensor.front_door")
    assert home.alerts == ["deter"]
    await home.pulse("binary_sensor.hall_motion")
    assert home.alerts[-1] == "alarm"


async def test_a_neighbor_with_a_key_nobody_told_siem_about(house, freezer):
    """A neighbor lets themselves in with a key to water the plants, and nobody put it on the calendar. A lock
    turned by hand while the house is empty is a break-glass message and, with the door, an alarm."""
    home = await house()
    await home.vacation()
    freezer.move_to("2026-10-21 18:00:00-07:00")
    await home.lock_event("Manual unlock operation")
    await home.physical("binary_sensor.front_door")
    assert home.alerts[0] == "break_glass" and "alarm" in home.alerts
    await home.wait(60)
    assert home.trigger


# --- Coming home --------------------------------------------------------------------------------------------------


async def test_coming_home_with_the_phone_a_little_late(house, freezer):
    """Back from the trip. Alex drives in and the garage opens before the phone reports home: the garage door (40)
    and the garage motion (30 x 1.5) reach alarm, and the alerts go out. Thirty seconds later the phone reports
    home; the arrival explains the minutes before it, the score drops to nothing, and the panel is never triggered."""
    home = await house()
    await home.vacation()
    freezer.move_to("2026-10-25 18:00:00-07:00")
    await home.pulse("binary_sensor.driveway_motion")
    await home.physical("binary_sensor.garage_door")
    await home.pulse("binary_sensor.garage_motion")
    assert home.alerts == ["verify", "alarm"]
    await home.wait(30)
    await home.arrive("device_tracker.alex_phone")
    assert home.score == 0 and home.mode == "family"
    await home.wait(120)
    assert not home.trigger_seen


async def test_coming_home_with_the_phone_on_time(house, freezer):
    """The phone reaches the home zone down the street: by the time the garage opens the house is family."""
    home = await house()
    await home.vacation()
    freezer.move_to("2026-10-25 18:00:00-07:00")
    await home.arrive("device_tracker.alex_phone")
    await home.pulse("binary_sensor.driveway_motion")
    await home.physical("binary_sensor.garage_door")
    await home.pulse("binary_sensor.garage_motion", "binary_sensor.hall_motion")
    assert home.alerts == [] and home.rules() == []


async def test_coming_home_late_at_night_with_a_code(house, freezer):
    """11:30 p.m., the phone has not caught up. Someone on the porch at night is worth a look (verify); the code
    the lock accepts lets them in, and everything after is quiet."""
    home = await house()
    await home.vacation()
    freezer.move_to("2026-10-25 23:30:00-07:00")
    await home.pulse("binary_sensor.driveway_motion", "binary_sensor.porch_person", "binary_sensor.front_door_csi")
    assert home.alerts == ["verify"]
    await home.code(slot=1)
    assert home.score == 0 and home.mode == "guest"
    await home.pulse("binary_sensor.front_door", "binary_sensor.hall_motion")
    await home.physical("light.hallway")
    await home.wait(60)
    await home.arrive("device_tracker.alex_phone")
    assert home.alerts == ["verify"] and not home.trigger_seen


# --- People we expect -----------------------------------------------------------------------------------------------


async def test_the_cleaner_lets_themselves_in_with_their_code(house, freezer):
    """The cleaner's Lock Code Manager slot opens a guest window: three hours of doors, lights, water and every
    room, all quiet. After they lock up, guest mode ends once the house has been quiet for an hour, and SIEM is
    back on watch."""
    home = await house()
    await home.vacation()
    freezer.move_to("2026-10-21 09:00:00-07:00")
    await home.code(slot=5)
    assert home.mode == "guest"
    for _ in range(18):
        await home.pulse("binary_sensor.front_door", "binary_sensor.hall_motion", "binary_sensor.kitchen_presence", "binary_sensor.fridge_door")
        await home.pulse("binary_sensor.closet_door", "binary_sensor.bedroom_motion", "binary_sensor.living_motion")
        await home.physical("light.kitchen", "on")
        await home.physical("sensor.water_flow", "5")
        await home.wait(600)
        await home.physical("light.kitchen", "off")
        await home.physical("sensor.water_flow", "0")
    await home.lock_event("Keypad lock operation")
    assert home.alerts == [] and home.rules() in ([], ["let_in"])
    await home.wait(2 * 3600)
    assert home.mode == "vacant"
    await home.physical("binary_sensor.back_door")
    assert home.alerts == ["verify"]


async def test_a_neighbor_on_the_calendar(house, freezer):
    """'Guest: Neighbor feeds the cat' on the house calendar: the key, the door, lights and water are all expected."""
    home = await house()
    await home.vacation()
    freezer.move_to("2026-10-21 17:00:00-07:00")
    await home.calendar("Guest: Neighbor feeds the cat", "2026-10-21 17:00:00", "2026-10-21 17:30:00")
    await home.lock_event("Manual unlock operation")
    await home.pulse("binary_sensor.front_door", "binary_sensor.hall_motion", "binary_sensor.kitchen_presence")
    await home.physical("light.kitchen")
    await home.physical("sensor.water_flow", "3")
    assert home.alerts == [] and home.mode == "guest"


async def test_letting_the_plumber_in_from_the_app(house, freezer):
    """Alex, away, unlocks the front door from the app for the plumber. An unlock from Home Assistant lets
    someone in, like a code: the plumber's visit is quiet."""
    home = await house()
    await home.vacation()
    freezer.move_to("2026-10-21 10:00:00-07:00")
    await home.hass.services.async_call("lock", "unlock", {"entity_id": "lock.front_door"}, blocking=True, context=Context(user_id=RESIDENT))
    await home.hass.async_block_till_done()
    assert home.mode == "guest"
    await home.pulse("binary_sensor.front_door", "binary_sensor.hall_motion", "binary_sensor.kitchen_presence", "binary_sensor.fridge_door")
    await home.physical("sensor.water_flow", "8")
    assert home.alerts == []


async def test_opening_the_garage_from_the_app_for_a_delivery(house, freezer):
    """Alex, away, opens the garage from the app so a parcel can go inside. The garage door's own contact sensor
    reports the opening with no trace of the command; Home Assistant opening a garage door, gate or door lets
    someone in, like an unlock from the app."""
    home = await house()
    await home.vacation()
    freezer.move_to("2026-10-21 14:00:00-07:00")
    await home.hass.services.async_call("cover", "open_cover", {"entity_id": "cover.garage"}, blocking=True, context=Context(user_id=RESIDENT))
    await home.hass.async_block_till_done()
    assert home.mode == "guest"
    await home.physical("binary_sensor.garage_door")
    await home.pulse("binary_sensor.driveway_motion", "binary_sensor.garage_motion")
    await home.physical("binary_sensor.garage_door", "off")
    assert home.alerts == []


async def test_a_pet_on_weak_motion_sensors(house, freezer):
    """The dog is home alone between sitter visits. Its motion sensors are set to weak, which cannot open an
    incident on their own: six hours of a dog wandering is nothing."""
    pet_sensors = ("binary_sensor.living_motion", "binary_sensor.hall_motion", "binary_sensor.bedroom_motion")
    home = await house(weak=pet_sensors)
    await home.vacation()
    for _ in range(72):
        await home.pulse(*pet_sensors)
        await home.wait(300)
    assert home.alerts == [] and home.coordinator.engine.current is None


async def test_the_pet_sitter_leaves_and_the_dog_cannot_hold_guest_mode(house, freezer):
    """A Guest event for the sitter. After they leave, the dog's motion is not activity, so guest mode ends two
    hours after the event and an hour of quiet later; a break-in that night is scored as one."""
    pet_sensors = ("binary_sensor.living_motion", "binary_sensor.hall_motion")
    home = await house(weak=pet_sensors)
    await home.vacation()
    freezer.move_to("2026-10-21 08:00:00-07:00")
    await home.calendar("Guest: Pet sitter", "2026-10-21 08:00:00", "2026-10-21 08:30:00")
    await home.pulse("binary_sensor.front_door", "binary_sensor.kitchen_presence")
    await home.wait(30 * 60)
    home.hass.states.async_set("calendar.house", "off", {"friendly_name": "House"})
    for _ in range(40):
        await home.pulse(*pet_sensors)
        await home.wait(300)
    assert home.mode == "vacant"
    await home.physical("binary_sensor.back_door")
    await home.pulse("binary_sensor.kitchen_presence")
    assert home.alerts[-1] == "alarm"


# --- Home Assistant doing things ----------------------------------------------------------------------------------


async def test_presence_simulation_on_vacation(house, freezer):
    """Presence Simulation replays an evening: lights, the lamp's smart plug (whose power reading follows the
    switch a little later with no context of its own) and the TV (whose separate plug sees the power)."""
    home = await house()
    await home.vacation()
    freezer.move_to("2026-10-21 18:30:00-07:00")
    simulation = await home.hass.auth.async_create_system_user("Presence Simulation")
    for _ in range(4):
        context = Context(user_id=simulation.id)
        await home.ha("light.living_ceiling", "on", context)
        await home.ha("switch.lamp_plug", "on", context)
        await home.ha("media_player.tv", "on", context)
        await home.wait(45)
        await home.physical("sensor.lamp_plug_power", "9")
        await home.physical("sensor.tv_power", "140")
        await home.wait(1800)
        for entity_id in ("light.living_ceiling", "switch.lamp_plug", "media_player.tv"):
            await home.ha(entity_id, "off", Context(user_id=simulation.id))
        await home.physical("sensor.lamp_plug_power", "0")
        await home.physical("sensor.tv_power", "2")
    assert home.alerts == [] and home.coordinator.engine.current is None


async def test_scheduled_automations_and_slow_lights(house, freezer):
    """A sunset automation turns on the porch flood and the hallway light; the hallway light reports back after
    twenty seconds, long after its command's context is stale. Later an evening scene lights the bedroom by
    area, naming no light; each light it switches carries the scene's context. None of it is a person."""
    home = await house()
    await home.vacation()
    freezer.move_to("2026-10-21 18:10:00-07:00")
    sunset = Context()
    await home.ha("light.porch_flood", "on", sunset)
    home.hass.bus.async_fire("call_service", {"domain": "light", "service": "turn_on", "service_data": {"entity_id": "light.hallway"}}, context=sunset)
    await home.wait(20)
    await home.physical("light.hallway")
    await home.wait(3600)
    await home.hass.services.async_call("scenario", "area_on", {"area_id": "bedroom"}, blocking=True, context=Context())
    await home.hass.async_block_till_done()
    assert home.hass.states.get("light.bedroom").state == "on"
    assert home.alerts == [] and home.coordinator.engine.current is None


async def test_apple_home_from_far_away(house, freezer):
    """Jordan, away too, turns on the bedroom light from Apple Home to check on things. HomeKit Bridge is Home
    Assistant acting on a service call, like the app or a voice assistant."""
    home = await house()
    await home.vacation()
    freezer.move_to("2026-10-21 20:00:00-07:00")
    await home.ha("light.bedroom", "on")
    await home.ha("light.living_ceiling", "on", Context(user_id=RESIDENT))
    assert home.alerts == [] and home.coordinator.engine.current is None


async def test_an_app_that_bypasses_home_assistant(house, freezer):
    """A known limit: a light switched by its own app or hub (a Hue schedule, Matter from another controller)
    leaves no trace in Home Assistant and looks like someone at the switch: a verify."""
    home = await house()
    await home.vacation()
    freezer.move_to("2026-10-21 19:00:00-07:00")
    await home.physical("light.bedroom")
    assert home.alerts == ["verify"]


# --- The house itself ---------------------------------------------------------------------------------------------


async def test_a_zwave_restart(house, freezer):
    """Z-Wave JS restarts: every sensor drops out for forty seconds and comes back where it was, the bedroom
    window included, which had been left open."""
    home = await house()
    await home.vacation()
    sensors = ("binary_sensor.back_door", "binary_sensor.front_door", "binary_sensor.bedroom_window", "binary_sensor.hall_motion", "binary_sensor.fridge_door")
    for entity_id in sensors:
        await home.physical(entity_id, "unavailable")
    await home.wait(40)
    for entity_id in sensors:
        await home.physical(entity_id, "on" if entity_id == "binary_sensor.bedroom_window" else "off")
    await home.wait(300)
    assert home.alerts == [] and home.coordinator.engine.current is None


async def test_a_long_outage_on_vacation(house, freezer):
    """The Z-Wave stick dies on the second day away: one verify for all the sensors after two minutes, and one
    break-glass message an hour in."""
    home = await house()
    await home.vacation()
    for entity_id in ("binary_sensor.back_door", "binary_sensor.front_door", "binary_sensor.hall_motion"):
        await home.physical(entity_id, "unavailable")
    await home.wait(150)
    assert home.alerts == ["verify"]
    await home.wait(3 * 3600)
    assert home.alerts == ["verify", "break_glass"]
