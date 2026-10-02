"""Fixed-timestep dynamics and a single in-memory authoritative fleet coordinator."""

import hashlib
import json
import random
from dataclasses import asdict, replace
from typing import Any

from miragetransit.models import (
    MAX_SPEED_MM_S,
    MODEL_VERSION,
    TICK_MS,
    Command,
    Profile,
    ScheduledCommand,
    State,
    integer,
)
from miragetransit.profile import profile_to_dict


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def step(state: State, profile: Profile) -> State:
    """Semi-implicit speed and trapezoidal distance; residuals retain sub-unit precision."""
    powered = state.ignition and state.fuel_ml > 0
    drive = 3000 * state.throttle_permille // 1000 if powered else 0
    braking = 8000 * state.brake_permille // 1000
    drag = 100 + state.speed_mm_s // 100 if state.speed_mm_s else 0
    delta, speed_residue = divmod((drive - braking - drag) * TICK_MS + state.speed_remainder, 1000)
    speed = max(0, min(MAX_SPEED_MM_S, state.speed_mm_s + delta))
    if speed in (0, MAX_SPEED_MM_S):
        speed_residue = 0
    distance_delta, distance_residue = divmod(
        (state.speed_mm_s + speed) * TICK_MS + state.distance_remainder, 2000
    )
    consumption, fuel_residue = divmod(
        (1 + 9 * state.throttle_permille // 1000) * TICK_MS + state.fuel_remainder
        if powered
        else state.fuel_remainder,
        1000,
    )
    fuel = max(0, state.fuel_ml - consumption)
    if fuel == 0:
        fuel_residue = 0
    distance = state.distance_mm + distance_delta
    offset, latitude, longitude, heading = profile.project(distance)
    return replace(
        state,
        tick=state.tick + 1,
        state_version=state.state_version + 1,
        speed_mm_s=speed,
        speed_remainder=speed_residue,
        distance_mm=distance,
        distance_remainder=distance_residue,
        fuel_ml=fuel,
        fuel_remainder=fuel_residue,
        ignition=state.ignition and fuel > 0,
        route_offset_mm=offset,
        latitude_e7=latitude,
        longitude_e7=longitude,
        heading_mdeg=heading,
    )


def apply(state: State, command: Command) -> State:
    if command.operation == "set_ignition":
        return replace(state, ignition=bool(command.value))
    if command.operation == "set_throttle":
        return replace(state, throttle_permille=int(command.value))
    return replace(state, brake_permille=int(command.value))


class Fleet:
    """Commands run in (tick, FIFO sequence) order before the tick's dynamics."""

    def __init__(self, profile: Profile, seed: int = 42) -> None:
        integer(seed, "seed", 0, 2**32 - 1)
        self.profile = profile
        self.seed = seed
        self.tick = 0
        self.running = True
        self._next_sequence = 1
        self._queue: list[ScheduledCommand] = []
        generator = random.Random(seed)
        self._states: dict[str, State] = {}
        for vehicle_id in sorted(profile.vehicle_ids):
            # Defined random() algorithm; sorted IDs make profile ordering irrelevant.
            fuel = max(0, profile.initial_fuel_ml - int(generator.random() * 100))
            offset, lat, lon, heading = profile.project(0)
            self._states[vehicle_id] = State(
                vehicle_id=vehicle_id,
                fuel_ml=fuel,
                route_offset_mm=offset,
                latitude_e7=lat,
                longitude_e7=lon,
                heading_mdeg=heading,
            )

    @property
    def states(self) -> tuple[State, ...]:
        return tuple(self._states[key] for key in sorted(self._states))

    @property
    def pending(self) -> tuple[ScheduledCommand, ...]:
        return tuple(sorted(self._queue, key=lambda item: (item.tick, item.sequence)))

    def submit(self, command: Command, tick: int | None = None) -> ScheduledCommand:
        if not self.running:
            raise ValueError("run is stopped")
        if command.vehicle_id not in self._states:
            raise ValueError("unknown vehicle")
        scheduled_tick = self.tick + 1 if tick is None else tick
        integer(scheduled_tick, "scheduled tick", self.tick + 1, 2**63 - 1)
        if len(self._queue) >= 10_000:
            raise ValueError("command queue is full")
        item = ScheduledCommand(scheduled_tick, self._next_sequence, command)
        self._next_sequence += 1
        self._queue.append(item)
        return item

    def advance(self, ticks: int = 1) -> None:
        integer(ticks, "ticks", 1, 36_000)
        if not self.running:
            raise ValueError("run is stopped")
        for _ in range(ticks):
            target_tick = self.tick + 1
            staged = dict(self._states)
            for item in self.pending:
                if item.tick == target_tick:
                    staged[item.command.vehicle_id] = apply(
                        staged[item.command.vehicle_id], item.command
                    )
            # Commit only when all transitions succeed.
            updated = {key: step(state, self.profile) for key, state in sorted(staged.items())}
            self._states = updated
            self.tick = target_tick
            self._queue = [item for item in self._queue if item.tick > target_tick]

    def stop(self) -> None:
        """Freeze this run, clear pending inputs; not a simulated vehicle braking command."""
        self.running = False
        self._queue.clear()

    def snapshot(self) -> dict[str, Any]:
        return {
            "model_version": MODEL_VERSION,
            "tick_ms": TICK_MS,
            "seed": self.seed,
            "tick": self.tick,
            "running": self.running,
            "profile_sha256": hashlib.sha256(canonical(profile_to_dict(self.profile))).hexdigest(),
            "states": [asdict(state) for state in self.states],
        }

    def state_hash(self) -> str:
        return hashlib.sha256(canonical(self.snapshot())).hexdigest()
