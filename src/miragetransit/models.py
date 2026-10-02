"""Validated immutable domain types; integers are deliberately strict (bool is not int)."""

from dataclasses import dataclass
from typing import Literal

TICK_MS = 100
MAX_SPEED_MM_S = 45_000
MODEL_VERSION = "longitudinal-v1"


def integer(value: object, name: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in [{low}, {high}]")
    return value


def identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 64:
        raise ValueError(f"{name} must be a nonempty identifier (maximum 64 characters)")
    if not all(c.isascii() and (c.isalnum() or c in "-_") for c in value):
        raise ValueError(f"{name} contains unsupported characters")
    return value


@dataclass(frozen=True)
class Waypoint:
    offset_mm: int
    latitude_e7: int
    longitude_e7: int
    heading_mdeg: int

    def __post_init__(self) -> None:
        integer(self.offset_mm, "offset_mm", 0, 1_000_000_000)
        integer(self.latitude_e7, "latitude_e7", -900_000_000, 900_000_000)
        integer(self.longitude_e7, "longitude_e7", -1_800_000_000, 1_800_000_000)
        integer(self.heading_mdeg, "heading_mdeg", 0, 359_999)


@dataclass(frozen=True)
class Profile:
    profile_id: str
    vehicle_ids: tuple[str, ...]
    route: tuple[Waypoint, ...]
    initial_fuel_ml: int = 40_000

    def __post_init__(self) -> None:
        identifier(self.profile_id, "profile_id")
        if not 1 <= len(self.vehicle_ids) <= 100:
            raise ValueError("profile requires 1–100 vehicles")
        for vehicle_id in self.vehicle_ids:
            identifier(vehicle_id, "vehicle_id")
        if len(set(self.vehicle_ids)) != len(self.vehicle_ids):
            raise ValueError("vehicle IDs must be unique")
        integer(self.initial_fuel_ml, "initial_fuel_ml", 0, 100_000)
        if not 2 <= len(self.route) <= 1000 or self.route[0].offset_mm != 0:
            raise ValueError("route requires 2–1000 waypoints and must start at offset 0")
        if any(
            b.offset_mm <= a.offset_mm for a, b in zip(self.route, self.route[1:], strict=False)
        ):
            raise ValueError("route offsets must be strictly increasing")
        first, last = self.route[0], self.route[-1]
        if (first.latitude_e7, first.longitude_e7) != (last.latitude_e7, last.longitude_e7):
            raise ValueError("S1 route must be a closed loop")

    @property
    def length_mm(self) -> int:
        return self.route[-1].offset_mm

    def project(self, distance_mm: int) -> tuple[int, int, int, int]:
        offset = distance_mm % self.length_mm
        for a, b in zip(self.route, self.route[1:], strict=False):
            if a.offset_mm <= offset < b.offset_mm:
                fraction = offset - a.offset_mm
                length = b.offset_mm - a.offset_mm
                lat = a.latitude_e7 + (b.latitude_e7 - a.latitude_e7) * fraction // length
                lon = a.longitude_e7 + (b.longitude_e7 - a.longitude_e7) * fraction // length
                return offset, lat, lon, a.heading_mdeg
        raise ValueError("offset outside route")


@dataclass(frozen=True)
class State:
    vehicle_id: str
    tick: int = 0
    state_version: int = 0
    speed_mm_s: int = 0
    distance_mm: int = 0
    route_offset_mm: int = 0
    latitude_e7: int = 0
    longitude_e7: int = 0
    heading_mdeg: int = 0
    throttle_permille: int = 0
    brake_permille: int = 0
    ignition: bool = False
    fuel_ml: int = 40_000
    speed_remainder: int = 0
    distance_remainder: int = 0
    fuel_remainder: int = 0

    def __post_init__(self) -> None:
        identifier(self.vehicle_id, "vehicle_id")
        for name in ("tick", "state_version", "distance_mm", "route_offset_mm"):
            integer(getattr(self, name), name, 0, 2**63 - 1)
        integer(self.speed_mm_s, "speed_mm_s", 0, MAX_SPEED_MM_S)
        integer(self.throttle_permille, "throttle_permille", 0, 1000)
        integer(self.brake_permille, "brake_permille", 0, 1000)
        integer(self.fuel_ml, "fuel_ml", 0, 100_000)
        integer(self.speed_remainder, "speed_remainder", 0, 999)
        integer(self.distance_remainder, "distance_remainder", 0, 1999)
        integer(self.fuel_remainder, "fuel_remainder", 0, 999)
        integer(self.latitude_e7, "latitude_e7", -900_000_000, 900_000_000)
        integer(self.longitude_e7, "longitude_e7", -1_800_000_000, 1_800_000_000)
        integer(self.heading_mdeg, "heading_mdeg", 0, 359_999)
        if type(self.ignition) is not bool:
            raise ValueError("ignition must be boolean")


Operation = Literal["set_throttle", "set_brake", "set_ignition"]


@dataclass(frozen=True)
class Command:
    vehicle_id: str
    operation: Operation
    value: int | bool

    def __post_init__(self) -> None:
        identifier(self.vehicle_id, "vehicle_id")
        if self.operation == "set_ignition":
            if type(self.value) is not bool:
                raise ValueError("set_ignition requires boolean value")
        elif self.operation in ("set_throttle", "set_brake"):
            integer(self.value, "command value", 0, 1000)
        else:
            raise ValueError("unsupported operation")


@dataclass(frozen=True)
class ScheduledCommand:
    tick: int
    sequence: int
    command: Command

    def __post_init__(self) -> None:
        integer(self.tick, "scheduled tick", 1, 2**63 - 1)
        integer(self.sequence, "sequence", 1, 2**63 - 1)
