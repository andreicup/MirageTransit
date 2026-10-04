"""Measure a real local lab. Raw process metadata and credentials never enter the report."""

import argparse
import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from lab_support import Lab  # noqa: E402

from miragetransit.evidence import sanitized_bundle
from miragetransit.replay import verify
from miragetransit.rpc import Client


def lab_pids(directory: Path) -> list[int]:
    # Some execution environments expose host /proc alongside namespace-local PIDs.
    # Match only this fixture's own config paths, then read the exposed numeric PID.
    result = []
    marker = str(directory).encode()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / "cmdline").read_bytes()
            if marker in command and b"miragetransit" in command:
                result.append(int(entry.name))
        except OSError:
            continue
    return result


def usage(pids: list[int]) -> tuple[float, int]:
    cpu = 0.0
    memory = 0
    for pid in pids:
        try:
            stat = Path(f"/proc/{pid}/stat").read_text().split(")", 1)[1].split()
            cpu += (int(stat[11]) + int(stat[12])) / os.sysconf("SC_CLK_TCK")
            memory += int(Path(f"/proc/{pid}/statm").read_text().split()[1]) * os.sysconf(
                "SC_PAGE_SIZE"
            )
        except OSError:
            pass
    return cpu, memory


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--output", type=Path, default=Path("benchmarks/local.json"))
    args = parser.parse_args()
    if not 2 <= args.seconds <= 60:
        raise ValueError("benchmark duration must be 2–60 seconds")
    if args.output.exists():
        raise ValueError("report already exists; choose another output")
    lab = Lab()
    try:
        client = Client(lab.configs["analyst"]["core_url"], lab.configs["analyst"]["key"])
        for vehicle in ("MT-001", "MT-002", "MT-003"):
            for operation, value in (("set_ignition", True), ("set_throttle", 700)):
                client.call(
                    "command",
                    adapter="analyst",
                    session="benchmark",
                    body={
                        "command_id": f"bench-{vehicle}-{operation}",
                        "vehicle_id": vehicle,
                        "operation": operation,
                        "value": value,
                    },
                )
        pids = lab_pids(lab.directory)
        if len(pids) != 5:
            raise RuntimeError("cannot measure all five lab processes on this host")
        first_cpu, _ = usage(pids)
        start = time.monotonic()
        max_memory = 0
        latencies = []
        samples = []
        while time.monotonic() - start < args.seconds:
            before = time.monotonic()
            state = client.call("state")
            latencies.append((time.monotonic() - before) * 1000)
            samples.append(state["snapshot"]["tick"])
            _, memory = usage(pids)
            max_memory = max(max_memory, memory)
            time.sleep(0.05)
        elapsed = time.monotonic() - start
        final_cpu, _ = usage(pids)
        client.call("stop")
        health = client.call("health")
        bundle = sanitized_bundle(client.call("export"))
        replay_results = [verify(bundle)["trace_sha256"] for _ in range(20)]
        events = client.call("events", limit=1000)
        applied = len([event for event in events if event["event_type"] == "command.applied"])
        file_bytes = sum(path.stat().st_size for path in lab.directory.glob("lab.sqlite*"))
        report = {
            "environment": {
                "python": platform.python_version(),
                "system": platform.system(),
                "machine": platform.machine(),
                "logical_cpus": os.cpu_count(),
            },
            "measurement": "Linux container: three vehicles, four services and supervisor. "
            "RSS sum includes shared pages; not a hardware performance promise.",
            "duration_seconds": round(elapsed, 3),
            "process_count": len(pids),
            "cpu_percent_one_core": round((final_cpu - first_cpu) / elapsed * 100, 2),
            "peak_rss_sum_mib": round(max_memory / 1024**2, 2),
            "sqlite_including_wal_bytes": file_bytes,
            "rpc_latency_ms_mean": round(statistics.mean(latencies), 3),
            "rpc_latency_ms_p95": round(sorted(latencies)[int(len(latencies) * 0.95)], 3),
            "observed_tick_advance": samples[-1] - samples[0],
            "observed_tick_rate_hz": round((samples[-1] - samples[0]) / elapsed, 3),
            "commands_applied": applied,
            "expected_commands": 6,
            "twenty_replays_equal": len(set(replay_results)) == 1,
            "trace_sha256": replay_results[0],
            **client.call("metrics"),
            "healthy_after_stop": health["healthy"],
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
        print(json.dumps(report, indent=2))
    finally:
        lab.close()


if __name__ == "__main__":
    main()
