"""Bounded, declarative scenario bundles: no scripts, destinations or live network replay."""

import hashlib
import json
from pathlib import Path
from typing import Any

from miragetransit import checkpoint
from miragetransit.core import Fleet, canonical
from miragetransit.intents import evaluate
from miragetransit.models import MODEL_VERSION, TICK_MS, identifier, integer
from miragetransit.profile import object_fields
from miragetransit.provenance import runtime_stamp
from miragetransit.storage import MAX_ATTEMPTS, MAX_TICKS, Store

MAX_BUNDLE_BYTES = 16 * 1024 * 1024


def manifest(run_id: str, fleet: Fleet) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "model_version": MODEL_VERSION,
        "tick_ms": TICK_MS,
        **runtime_stamp(),
        "profile_sha256": fleet.snapshot()["profile_sha256"],
        "seed": fleet.seed,
    }


def checksum(bundle: dict[str, Any]) -> str:
    return hashlib.sha256(
        canonical({key: value for key, value in bundle.items() if key != "checksum_sha256"})
    ).hexdigest()


def export_bundle(store: Store, run_id: str, path: Path) -> dict[str, Any]:
    # Consistent WAL read snapshot even if another coordinator advances concurrently.
    store.connection.execute("BEGIN")
    try:
        row = store.connection.execute(
            "SELECT initial,checkpoint,provenance FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise ValueError("unknown run")
        initial = json.loads(row["initial"])
        fleet = checkpoint.from_payload(initial)
        bundle = {
            "bundle_version": 1,
            "manifest": {**manifest(run_id, fleet), **json.loads(row["provenance"])},
            "initial": initial,
            "actions": [
                json.loads(action["action"])
                for action in store.connection.execute(
                    "SELECT action FROM actions WHERE run_id=? ORDER BY sequence", (run_id,)
                )
            ],
            "expected_hashes": [
                state["state_hash"]
                for state in store.connection.execute(
                    "SELECT state_hash FROM snapshots WHERE run_id=? ORDER BY tick", (run_id,)
                )
            ],
            "final": json.loads(row["checkpoint"]),
        }
        bundle["checksum_sha256"] = checksum(bundle)
    finally:
        store.connection.rollback()
    verify(bundle)
    data = canonical(bundle) + b"\n"
    if len(data) > MAX_BUNDLE_BYTES:
        raise ValueError("bundle exceeds 16 MiB")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)
    return {"path": str(path), "checksum_sha256": bundle["checksum_sha256"]}


def load_bundle(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        data = stream.read(MAX_BUNDLE_BYTES + 1)
    if len(data) > MAX_BUNDLE_BYTES:
        raise ValueError("bundle exceeds 16 MiB")
    return validate(json.loads(data))


def validate(value: object) -> dict[str, Any]:
    bundle = object_fields(
        value,
        {
            "bundle_version",
            "manifest",
            "initial",
            "actions",
            "expected_hashes",
            "final",
            "checksum_sha256",
        },
        "bundle",
    )
    integer(bundle["bundle_version"], "bundle_version", 1, 1)
    if len(canonical(bundle)) > MAX_BUNDLE_BYTES:
        raise ValueError("bundle exceeds 16 MiB")
    if bundle["checksum_sha256"] != checksum(bundle):
        raise ValueError("bundle checksum mismatch")
    metadata = object_fields(
        bundle["manifest"],
        {
            "run_id",
            "model_version",
            "tick_ms",
            "runtime",
            "implementation",
            "engine_sha256",
            "dependency_lock_sha256",
            "profile_sha256",
            "seed",
        },
        "manifest",
    )
    identifier(metadata["run_id"], "run_id")
    initial = checkpoint.from_payload(bundle["initial"])
    fresh = Fleet(initial.profile, initial.seed)
    if canonical(bundle["initial"]) != canonical(checkpoint.to_payload(fresh)):
        raise ValueError("bundle must start from a fresh deterministic run")
    if canonical(metadata) != canonical(manifest(metadata["run_id"], initial)):
        raise ValueError("incompatible runtime, engine or profile manifest")
    actions = bundle["actions"]
    hashes = bundle["expected_hashes"]
    if not isinstance(actions, list) or len(actions) > MAX_TICKS + MAX_ATTEMPTS + 1:
        raise ValueError("too many actions")
    if not isinstance(hashes, list) or not 1 <= len(hashes) <= MAX_TICKS + 1:
        raise ValueError("invalid expected trace length")
    for value in hashes:
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)
        ):
            raise ValueError("invalid state hash")
    steps = 0
    attempts = 0
    stops = 0
    for action in actions:
        if not isinstance(action, dict) or action.get("kind") not in ("submit", "step", "stop"):
            raise ValueError("invalid action")
        if action["kind"] == "submit":
            object_fields(action, {"kind", "body", "receipt"}, "submit action")
            attempts += 1
        else:
            object_fields(action, {"kind"}, "lifecycle action")
            if action["kind"] == "step":
                steps += 1
            else:
                stops += 1
    if attempts > MAX_ATTEMPTS or stops > 1 or steps != len(hashes) - 1:
        raise ValueError("action/trace limits or lengths differ")
    if steps * len(initial.states) > 500_000:
        raise ValueError("replay exceeds simulation work budget")
    checkpoint.from_payload(bundle["final"])
    return bundle


def verify(value: object) -> dict[str, Any]:
    bundle = validate(value)
    fleet = checkpoint.from_payload(bundle["initial"])
    run_id = bundle["manifest"]["run_id"]
    known: dict[str, dict[str, Any]] = {}
    hashes = [fleet.state_hash()]
    applied = 0
    received = 0
    for action in bundle["actions"]:
        if action["kind"] == "submit":
            received += 1
            receipt, key, fingerprint = evaluate(fleet, run_id, action["body"], known)
            if canonical(receipt) != canonical(action["receipt"]):
                raise ValueError("replay command disposition mismatch")
            if key is not None:
                known[key] = {"fingerprint": fingerprint, "receipt": receipt}
        elif action["kind"] == "step":
            applied += sum(item.tick == fleet.tick + 1 for item in fleet.pending)
            fleet.advance()
            hashes.append(fleet.state_hash())
            if hashes[-1] != bundle["expected_hashes"][fleet.tick]:
                raise ValueError(f"replay state diverged at tick {fleet.tick}")
        else:
            if not fleet.running:
                raise ValueError("duplicate stop action")
            fleet.stop()
    if hashes != bundle["expected_hashes"]:
        raise ValueError("initial or normalized trace mismatch")
    if canonical(checkpoint.to_payload(fleet)) != canonical(bundle["final"]):
        raise ValueError("replay final checkpoint mismatch")
    return {
        "verified": True,
        "run_id": run_id,
        "ticks": fleet.tick,
        "commands_received": received,
        "commands_applied": applied,
        "trace_sha256": hashlib.sha256(canonical(hashes)).hexdigest(),
        "final_state_sha256": fleet.state_hash(),
    }


def import_bundle(store: Store, value: object) -> dict[str, Any]:
    result = verify(value)  # Full validation and re-execution precede any database mutation.
    bundle = validate(value)
    initial = checkpoint.from_payload(bundle["initial"])
    run_id = bundle["manifest"]["run_id"]
    with store._write():
        fleet = store._create(run_id, initial.profile, initial.seed)
        for action in bundle["actions"]:
            if action["kind"] == "submit":
                store._submit(run_id, fleet, action["body"])
            elif action["kind"] == "step":
                store._step(run_id, fleet)
            else:
                store._stop(run_id, fleet)
    return result
