"""Local, offline CLI. JSON output is intended for both humans and future fixtures."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from miragetransit import __version__, checkpoint
from miragetransit.core import Fleet
from miragetransit.demo import demo
from miragetransit.models import Command
from miragetransit.profile import load_profile


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
    return root


def execute(args: argparse.Namespace) -> dict[str, Any]:
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
    except (ValueError, TypeError, KeyError, OSError, RecursionError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0
