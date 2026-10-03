"""Shared live/replay intent validation and application-level idempotency."""

import hashlib
from typing import Any

from miragetransit.core import Fleet, canonical
from miragetransit.models import Command, identifier, integer
from miragetransit.profile import object_fields

MAX_INTENT_BYTES = 4096


def envelope(
    run_id: str,
    command_id: str,
    vehicle_id: str,
    operation: str,
    value: int | bool,
    scheduled_tick: int | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "command_id": command_id,
        "vehicle_id": vehicle_id,
        "operation": operation,
        "value": value,
        "scheduled_tick": scheduled_tick,
        "origin": {"adapter": "cli", "session_id": "local"},
    }


def preflight(body: object) -> None:
    if len(canonical(body)) > MAX_INTENT_BYTES:
        raise ValueError("intent exceeds 4096 bytes")


def evaluate(
    fleet: Fleet,
    run_id: str,
    body: object,
    known: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], str | None, str | None]:
    """Return receipt, identity and fingerprint; mutate fleet only on acceptance."""
    preflight(body)
    rejected: dict[str, Any] = {
        "status": "rejected",
        "reason_code": "invalid_command",
        "scheduled_tick": None,
        "sequence": None,
        "duplicate": False,
    }
    try:
        data = object_fields(
            body,
            {
                "schema_version",
                "run_id",
                "command_id",
                "vehicle_id",
                "operation",
                "value",
                "scheduled_tick",
                "origin",
            },
            "command envelope",
        )
        integer(data["schema_version"], "schema_version", 1, 1)
        identifier(data["command_id"], "command_id")
        identifier(data["vehicle_id"], "vehicle_id")
        if data["run_id"] != run_id:
            return dict(rejected, reason_code="wrong_run"), None, None
        origin = object_fields(data["origin"], {"adapter", "session_id"}, "origin")
        identifier(origin["adapter"], "adapter")
        identifier(origin["session_id"], "session_id")
        if data["scheduled_tick"] is not None:
            integer(data["scheduled_tick"], "scheduled_tick", 1, 36_000)
        command = Command(data["vehicle_id"], data["operation"], data["value"])
    except (ValueError, TypeError):
        return rejected, None, None
    key = f"{data['vehicle_id']}:{data['command_id']}"
    fingerprint = hashlib.sha256(
        canonical(
            {name: data[name] for name in ("vehicle_id", "operation", "value", "scheduled_tick")}
        )
    ).hexdigest()
    if key in known:
        old = known[key]
        if old["fingerprint"] != fingerprint:
            return dict(rejected, reason_code="id_conflict"), None, None
        return dict(old["receipt"], duplicate=True), None, None
    if not fleet.running:
        return dict(rejected, reason_code="run_stopped"), key, fingerprint
    if command.vehicle_id not in fleet.profile.vehicle_ids:
        return dict(rejected, reason_code="unknown_vehicle"), key, fingerprint
    try:
        scheduled = fleet.submit(command, data["scheduled_tick"])
    except ValueError:
        return dict(rejected, reason_code="invalid_schedule"), key, fingerprint
    return (
        {
            "status": "accepted",
            "reason_code": "ok",
            "scheduled_tick": scheduled.tick,
            "sequence": scheduled.sequence,
            "duplicate": False,
        },
        key,
        fingerprint,
    )
