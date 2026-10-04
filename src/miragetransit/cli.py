"""Local, offline CLI. JSON output is intended for both humans and future fixtures."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from miragetransit import __version__, checkpoint
from miragetransit.core import Fleet
from miragetransit.demo import demo, schedule_normal_drive
from miragetransit.intents import envelope
from miragetransit.models import Command, integer
from miragetransit.profile import load_profile
from miragetransit.replay import export_bundle, import_bundle, load_bundle, verify
from miragetransit.storage import StoragePaused, Store


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="miragetransit")
    root.add_argument("--version", action="version", version=__version__)
    commands = root.add_subparsers(dest="action", required=True)
    start = commands.add_parser("start", help="create a local run checkpoint")
    start.add_argument("--state", type=Path, required=True)
    start.add_argument("--seed", type=int, default=42)
    start.add_argument("--profile", type=Path)
    advance = commands.add_parser("step", help="advance simulation time without wall-clock waiting")
    advance.add_argument("--state", type=Path, required=True)
    advance.add_argument("--ticks", type=int, default=1)
    advance.add_argument("--vehicle")
    advance.add_argument("--throttle", type=int)
    advance.add_argument("--brake", type=int)
    advance.add_argument("--ignition", choices=("on", "off"))
    for name in ("inspect", "stop"):
        command = commands.add_parser(name)
        command.add_argument("--state", type=Path, required=True)
    fixture = commands.add_parser("demo", help="run the synthetic three-vehicle drive")
    fixture.add_argument("--seed", type=int, default=42)
    fixture.add_argument("--seconds", type=int, default=60)
    fixture.add_argument("--trace", type=Path)
    for name in (
        "run-start",
        "run-command",
        "run-step",
        "run-inspect",
        "run-events",
        "run-stop",
        "run-export",
        "journal-demo",
    ):
        command = commands.add_parser(name)
        command.add_argument("--db", type=Path, required=True)
        command.add_argument("--run", required=True)
        if name in ("run-start", "journal-demo"):
            command.add_argument("--seed", type=int, default=42)
        if name == "run-start":
            command.add_argument("--profile", type=Path)
        if name == "journal-demo":
            command.add_argument("--seconds", type=int, default=60)
        if name == "run-command":
            command.add_argument("--input", type=Path)
            command.add_argument("--command-id")
            command.add_argument("--vehicle")
            command.add_argument("--operation")
            command.add_argument("--value")
            command.add_argument("--at-tick", type=int)
        if name == "run-step":
            command.add_argument("--ticks", type=int, default=1)
        if name == "run-events":
            command.add_argument("--after", type=int, default=0)
            command.add_argument("--limit", type=int, default=100)
        if name == "run-export":
            command.add_argument("--output", type=Path, required=True)
    importer = commands.add_parser("run-import")
    importer.add_argument("--db", type=Path, required=True)
    importer.add_argument("--input", type=Path, required=True)
    replay = commands.add_parser("replay")
    replay.add_argument("--input", type=Path, required=True)
    for name in ("lab-init", "lab"):
        command = commands.add_parser(name, help="initialize or start the isolated local lab")
        command.add_argument("--directory", type=Path, default=Path("runs/lab"))
        if name == "lab-init":
            command.add_argument("--run", default="local-lab")
            command.add_argument("--base-port", type=int, default=8760)
    return root


def execute_journal(args: argparse.Namespace) -> dict[str, Any]:
    if args.action in ("replay", "run-import"):
        bundle = load_bundle(args.input)
        result = verify(bundle)
        if args.action == "replay":
            return result
        with Store(args.db) as store:
            return import_bundle(store, bundle)
    body: object = None
    if args.action == "run-command":
        supplied = any(
            value is not None
            for value in (args.command_id, args.vehicle, args.operation, args.value, args.at_tick)
        )
        if args.input is not None:
            if supplied:
                raise ValueError("--input cannot be combined with command fields")
            with args.input.open("rb") as stream:
                data = stream.read(4097)
            if len(data) > 4096:
                raise ValueError("intent exceeds 4096 bytes")
            body = json.loads(data)
            if isinstance(body, dict):
                body["origin"] = {"adapter": "cli", "session_id": "local"}
        else:
            if any(
                value is None
                for value in (args.command_id, args.vehicle, args.operation, args.value)
            ):
                raise ValueError("command-id, vehicle, operation and value are required")
            body = envelope(
                args.run,
                args.command_id,
                args.vehicle,
                args.operation,
                json.loads(args.value),
                args.at_tick,
            )
    if args.action == "journal-demo":
        integer(args.seconds, "seconds", 1, 3600)
    with Store(args.db) as store:
        if args.action == "run-start":
            return store.create(args.run, load_profile(args.profile), args.seed)
        if args.action == "run-command":
            return store.submit(args.run, body)
        if args.action == "run-step":
            return store.advance(args.run, args.ticks)
        if args.action == "run-inspect":
            return store.inspect(args.run)
        if args.action == "run-events":
            return {"run_id": args.run, "events": store.events(args.run, args.after, args.limit)}
        if args.action == "run-stop":
            return store.stop(args.run)
        if args.action == "run-export":
            return export_bundle(store, args.run, args.output)
        if args.action == "journal-demo":
            fixture = Fleet(load_profile(), args.seed)
            schedule_normal_drive(fixture)
            store.create(args.run, fixture.profile, fixture.seed)
            for item in fixture.pending:
                store.submit(
                    args.run,
                    envelope(
                        args.run,
                        f"demo-{item.sequence}",
                        item.command.vehicle_id,
                        item.command.operation,
                        item.command.value,
                        item.tick,
                    ),
                )
            return store.advance(args.run, args.seconds * 10)
    raise ValueError("unknown journal action")


def execute(args: argparse.Namespace) -> dict[str, Any]:
    if args.action == "lab-init":
        from miragetransit.service import initialize

        return initialize(args.directory, args.run, args.base_port)
    if args.action == "lab":
        from miragetransit.service import supervise

        supervise(args.directory)
        return {"status": "stopped"}
    if args.action.startswith("run-") or args.action in ("replay", "journal-demo"):
        return execute_journal(args)
    if args.action == "demo":
        return demo(args.seed, args.seconds, args.trace)
    if args.action == "start":
        if args.state.exists():
            raise ValueError("state file already exists; choose a new path")
        fleet = Fleet(load_profile(args.profile), args.seed)
    else:
        fleet = checkpoint.load(args.state)
    if args.action == "step":
        has_command = any(value is not None for value in (args.throttle, args.brake, args.ignition))
        if has_command and args.vehicle is None:
            raise ValueError("--vehicle is required when submitting commands")
        if args.vehicle is not None and not has_command:
            raise ValueError("--vehicle requires a throttle, brake or ignition command")
        if args.ignition is not None:
            fleet.submit(Command(args.vehicle, "set_ignition", args.ignition == "on"))
        if args.throttle is not None:
            fleet.submit(Command(args.vehicle, "set_throttle", args.throttle))
        if args.brake is not None:
            fleet.submit(Command(args.vehicle, "set_brake", args.brake))
        fleet.advance(args.ticks)
    elif args.action == "stop":
        fleet.stop()
    if args.action != "inspect":
        checkpoint.save(fleet, args.state)
    return {"state_sha256": fleet.state_hash(), "snapshot": fleet.snapshot()}


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = execute(args)
    except (
        ValueError,
        TypeError,
        KeyError,
        OSError,
        RecursionError,
        sqlite3.Error,
        StoragePaused,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, indent=2))
    return 2 if result.get("status") == "rejected" else 0
