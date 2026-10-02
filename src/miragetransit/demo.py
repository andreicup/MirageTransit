"""Normal-drive fixture and normalized streaming trace hashes."""

import hashlib
from pathlib import Path
from typing import Any

from miragetransit.core import Fleet, canonical
from miragetransit.models import TICK_MS, Command, integer
from miragetransit.profile import load_profile


def schedule_normal_drive(fleet: Fleet) -> None:
    for index, vehicle_id in enumerate(sorted(fleet.profile.vehicle_ids)):
        fleet.submit(Command(vehicle_id, "set_ignition", True), 1)
        fleet.submit(Command(vehicle_id, "set_throttle", 350 + index % 3 * 100), 1)
        fleet.submit(Command(vehicle_id, "set_throttle", 650), 200)
        fleet.submit(Command(vehicle_id, "set_throttle", 0), 400)
        fleet.submit(Command(vehicle_id, "set_brake", 1000), 400)
        fleet.submit(Command(vehicle_id, "set_ignition", False), 500)


def demo(seed: int = 42, seconds: int = 60, trace: Path | None = None) -> dict[str, Any]:
    integer(seconds, "seconds", 1, 3600)
    fleet = Fleet(load_profile(), seed)
    schedule_normal_drive(fleet)
    digest = hashlib.sha256()
    stream = None
    if trace is not None:
        trace.parent.mkdir(parents=True, exist_ok=True)
        stream = trace.open("xb")
    try:
        for index in range(seconds * 1000 // TICK_MS + 1):
            if index:
                fleet.advance()
            line = canonical(fleet.snapshot()) + b"\n"
            digest.update(line)
            if stream:
                stream.write(line)
    finally:
        if stream:
            stream.close()
    return {
        "simulated_seconds": seconds,
        "ticks": fleet.tick,
        "trace_sha256": digest.hexdigest(),
        "final_state_sha256": fleet.state_hash(),
        "final_snapshot": fleet.snapshot(),
    }
