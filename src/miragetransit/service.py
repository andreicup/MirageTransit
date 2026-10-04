"""Local supervisor and role-specific service entry points."""

import argparse
import json
import os
import secrets
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

from miragetransit.http import serve_analyst, serve_decoy
from miragetransit.models import identifier, integer
from miragetransit.mqtt import serve_mqtt
from miragetransit.profile import load_profile
from miragetransit.rpc import Client, Coordinator
from miragetransit.storage import Store


def initialize(directory: Path, run_id: str = "local-lab", base_port: int = 8760) -> dict[str, Any]:
    identifier(run_id, "run_id")
    integer(base_port, "base_port", 1024, 65532)
    directory.mkdir(parents=True, exist_ok=True)
    names = ("core", "decoy", "mqtt", "analyst")
    if any((directory / f"{name}.json").exists() for name in names):
        raise ValueError("lab already configured; use existing files or a new directory")
    decoy_key, analyst_key, password = (secrets.token_urlsafe(32) for _ in range(3))
    configs = {
        "core": {
            "db": str((directory / "lab.sqlite").resolve()),
            "run_id": run_id,
            "port": base_port,
            "decoy_key": decoy_key,
            "analyst_key": analyst_key,
        },
        "decoy": {
            "core_url": f"http://127.0.0.1:{base_port}",
            "key": decoy_key,
            "run_id": run_id,
            "port": base_port + 1,
            "mqtt_port": base_port + 3,
        },
        "mqtt": {
            "core_url": f"http://127.0.0.1:{base_port}",
            "key": decoy_key,
            "run_id": run_id,
            "port": base_port + 3,
        },
        "analyst": {
            "core_url": f"http://127.0.0.1:{base_port}",
            "key": analyst_key,
            "port": base_port + 2,
            "password": password,
        },
    }
    for role, config in configs.items():
        path = directory / f"{role}.json"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(config, stream, indent=2)
            stream.write("\n")
    return {
        "directory": str(directory),
        "portal_url": f"http://127.0.0.1:{base_port + 1}",
        "analyst_url": f"http://127.0.0.1:{base_port + 2}",
        "password_file": str(directory / "analyst.json"),
        "mqtt_port": base_port + 3,
    }


def role_service(role: str, config_path: Path, host: str = "127.0.0.1") -> None:
    config = json.loads(config_path.read_bytes())
    address = (host, config["port"])
    if role == "core":
        with Store(Path(config["db"])) as store:
            if not store.connection.execute(
                "SELECT 1 FROM runs WHERE run_id=?", (config["run_id"],)
            ).fetchone():
                store.create(config["run_id"], load_profile())
            coordinator = Coordinator(
                store, config["run_id"], config["decoy_key"], config["analyst_key"]
            )
            for sig in (signal.SIGTERM, signal.SIGINT):
                signal.signal(sig, lambda *_: coordinator.shutdown.set())
            coordinator.serve(address)
    else:
        client = Client(config["core_url"], config["key"])
        if role == "decoy":
            serve_decoy(address, client, config["run_id"], config["mqtt_port"])
        elif role == "mqtt":
            serve_mqtt(address, client, config["run_id"])
        elif role == "analyst":
            serve_analyst(address, client, config["password"])
        else:
            raise ValueError("unknown role")


def supervise(directory: Path) -> None:
    config = json.loads((directory / "core.json").read_bytes())
    children: list[subprocess.Popen[bytes]] = []
    exiting = False

    def shutdown(*_: object) -> None:
        nonlocal exiting
        exiting = True

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, shutdown)
    try:
        for role in ("core", "decoy", "mqtt", "analyst"):
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "miragetransit.service",
                    "--role",
                    role,
                    "--config",
                    str(directory / f"{role}.json"),
                ]
            )
            children.append(process)
            if role == "core":
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline and not exiting:
                    if process.poll() is not None:
                        raise RuntimeError("core process exited during startup")
                    try:
                        with urllib.request.urlopen(
                            f"http://127.0.0.1:{config['port']}/healthz", timeout=0.3
                        ) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise RuntimeError("core readiness timed out")
        print(
            json.dumps(
                {
                    "status": "running",
                    "run_id": config["run_id"],
                    "portal_url": f"http://127.0.0.1:{config['port'] + 1}",
                    "analyst_url": f"http://127.0.0.1:{config['port'] + 2}",
                    "password_file": str(directory / "analyst.json"),
                }
            ),
            flush=True,
        )
        while not exiting:
            if any(process.poll() is not None for process in children):
                raise RuntimeError("service exited; stopping remaining lab processes")
            time.sleep(0.2)
    finally:
        for process in reversed(children):
            if process.poll() is None:
                process.terminate()
        for process in children:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=("core", "decoy", "mqtt", "analyst"), required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    role_service(args.role, args.config, args.host)


if __name__ == "__main__":
    main()
