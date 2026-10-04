"""Export synthetic memory frames, or explicitly bridge to a lab vCAN interface."""

import argparse
import json
import time
from pathlib import Path

from miragetransit.can import MemoryBus, VCanBus, ingest, telemetry
from miragetransit.rpc import Client


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("runs/lab/decoy.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--interface", help="optional, explicitly created vcanN interface only")
    parser.add_argument("--seconds", type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 60:
        raise ValueError("duration must be 1–60 seconds")
    config = json.loads(args.config.read_bytes())
    client = Client(config["core_url"], config["key"])
    memory = MemoryBus()
    virtual = VCanBus(args.interface) if args.interface else None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with args.output.open("x") as stream:
            deadline = time.monotonic() + args.seconds
            rejected = 0
            while time.monotonic() < deadline:
                projection = client.call("state")
                states = projection["snapshot"]["states"]
                for index, state in enumerate(states):
                    frame = telemetry(state, index)
                    memory.send(frame)
                    if virtual:
                        virtual.send(frame)
                while (frame := memory.receive()) is not None:
                    stream.write(
                        json.dumps(
                            {
                                "state_version": projection["snapshot"]["tick"],
                                "id": frame.arbitration_id,
                                "dlc": 8,
                                "data_hex": frame.data.hex(),
                            }
                        )
                        + "\n"
                    )
                if virtual:
                    import select

                    until = time.monotonic() + 0.5
                    # Bounded intake per sample prevents injected traffic starving telemetry.
                    for _ in range(16):
                        ready, _, _ = select.select(
                            [virtual.socket], [], [], max(0, until - time.monotonic())
                        )
                        if not ready:
                            break
                        try:
                            incoming = virtual.receive()
                            if 0x200 <= incoming.arbitration_id < 0x200 + len(states):
                                ingest(client, incoming, [s["vehicle_id"] for s in states])
                            elif not 0x100 <= incoming.arbitration_id < 0x100 + len(states):
                                raise ValueError("unknown frame id")
                        except ValueError:
                            if rejected < 20:
                                client.call(
                                    "observe",
                                    event_type="input.rejected",
                                    adapter="can",
                                    session="can-trace",
                                    payload={"reason": "invalid_vcan_frame"},
                                )
                                rejected += 1
                else:
                    time.sleep(0.5)
    finally:
        if virtual:
            virtual.close()


if __name__ == "__main__":
    main()
