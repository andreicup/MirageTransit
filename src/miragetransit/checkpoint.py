"""S1 local JSON checkpoints, not the S2 transactional event store."""

import json
import os
import tempfile
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

from miragetransit.core import Fleet, canonical
from miragetransit.models import Command, ScheduledCommand, State, integer
from miragetransit.profile import object_fields, profile_from_dict, profile_to_dict


def to_payload(fleet: Fleet) -> dict[str, Any]:
    return {
        "checkpoint_version": 1,
        "profile": profile_to_dict(fleet.profile),
        "snapshot": fleet.snapshot(),
        "next_sequence": fleet._next_sequence,
        "queue": [asdict(item) for item in fleet.pending],
    }


def save(fleet: Fleet, path: Path) -> None:
    payload = to_payload(fleet)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".mt-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical(payload) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load(path: Path) -> Fleet:
    if path.stat().st_size > 4_194_304:
        raise ValueError("checkpoint exceeds 4 MiB")
    return from_payload(json.loads(path.read_text()))


def from_payload(value: object) -> Fleet:
    data = object_fields(
        value,
        {"checkpoint_version", "profile", "snapshot", "next_sequence", "queue"},
        "checkpoint",
    )
    integer(data["checkpoint_version"], "checkpoint_version", 1, 1)
    profile = profile_from_dict(data["profile"])
    snapshot = object_fields(
        data["snapshot"],
        {"model_version", "tick_ms", "seed", "tick", "running", "profile_sha256", "states"},
        "snapshot",
    )
    fleet = Fleet(profile, snapshot["seed"])
    expected = fleet.snapshot()
    for key in ("model_version", "tick_ms", "profile_sha256"):
        if type(snapshot[key]) is not type(expected[key]) or snapshot[key] != expected[key]:
            raise ValueError(f"incompatible checkpoint {key}")
    tick = integer(snapshot["tick"], "tick", 0, 2**63 - 1)
    if type(snapshot["running"]) is not bool:
        raise ValueError("running must be boolean")
    if not isinstance(snapshot["states"], list):
        raise ValueError("states must be an array")
    states = [
        State(**object_fields(value, {field.name for field in fields(State)}, "state"))
        for value in snapshot["states"]
    ]
    if len(states) != len(profile.vehicle_ids) or {s.vehicle_id for s in states} != set(
        profile.vehicle_ids
    ):
        raise ValueError("checkpoint vehicle set differs from profile")
    for state in states:
        if state.tick != tick or state.state_version != tick:
            raise ValueError("state tick/version differs from fleet")
        projected = profile.project(state.distance_mm)
        actual = (state.route_offset_mm, state.latitude_e7, state.longitude_e7, state.heading_mdeg)
        if projected != actual:
            raise ValueError("state projection differs from route")
    if not isinstance(data["queue"], list) or len(data["queue"]) > 10_000:
        raise ValueError("queue must be an array with at most 10000 entries")
    queue: list[ScheduledCommand] = []
    for value in data["queue"]:
        item = object_fields(value, {"tick", "sequence", "command"}, "scheduled command")
        command = Command(
            **object_fields(item["command"], {"vehicle_id", "operation", "value"}, "command")
        )
        scheduled = ScheduledCommand(item["tick"], item["sequence"], command)
        if scheduled.tick <= tick or command.vehicle_id not in profile.vehicle_ids:
            raise ValueError("invalid queued command target")
        queue.append(scheduled)
    sequences = [item.sequence for item in queue]
    next_sequence = integer(data["next_sequence"], "next_sequence", 1, 2**63 - 1)
    if len(set(sequences)) != len(sequences) or next_sequence <= max(sequences, default=0):
        raise ValueError("invalid queue sequence")
    if not snapshot["running"] and queue:
        raise ValueError("stopped checkpoint has pending commands")
    fleet.tick = tick
    fleet.running = snapshot["running"]
    fleet._states = {state.vehicle_id: state for state in states}
    fleet._queue = queue
    fleet._next_sequence = next_sequence
    return fleet
