"""Synthetic CAN definition, portable memory bus, and explicit vCAN-only transport."""

import socket
import struct
from collections import deque
from dataclasses import dataclass
from typing import Any

from miragetransit.models import integer
from miragetransit.rpc import Client

TELEMETRY_BASE = 0x100
COMMAND_BASE = 0x200


@dataclass(frozen=True)
class Frame:
    arbitration_id: int
    data: bytes

    def __post_init__(self) -> None:
        integer(self.arbitration_id, "standard CAN id", 0, 0x7FF)
        if not isinstance(self.data, bytes) or len(self.data) != 8:
            raise ValueError("synthetic frames require DLC 8")


def telemetry(state: dict[str, Any], index: int) -> Frame:
    integer(index, "vehicle index", 0, 99)
    return Frame(
        TELEMETRY_BASE + index,
        struct.pack(
            "<HHHBB",
            state["speed_mm_s"],
            state["throttle_permille"],
            state["brake_permille"],
            int(state["ignition"]),
            min(255, state["fuel_ml"] // 400),
        ),
    )


def decode(frame: Frame) -> dict[str, int | bool]:
    if not TELEMETRY_BASE <= frame.arbitration_id < TELEMETRY_BASE + 100:
        raise ValueError("unknown telemetry id")
    speed, throttle, brake, ignition, fuel = struct.unpack("<HHHBB", frame.data)
    integer(speed, "speed", 0, 45000)
    integer(throttle, "throttle", 0, 1000)
    integer(brake, "brake", 0, 1000)
    integer(ignition, "ignition", 0, 1)
    return {
        "speed_mm_s": speed,
        "throttle_permille": throttle,
        "brake_permille": brake,
        "ignition": bool(ignition),
        "fuel_ml": fuel * 400,
    }


def command_frame(index: int, operation: str, value: int | bool, nonce: int) -> Frame:
    integer(index, "vehicle index", 0, 99)
    codes = {"set_ignition": 0, "set_throttle": 1, "set_brake": 2}
    if operation not in codes:
        raise ValueError("unknown operation")
    if operation == "set_ignition":
        if type(value) is not bool:
            raise ValueError("ignition requires boolean")
    else:
        integer(value, "control", 0, 1000)
    integer(nonce, "command nonce", 1, 2**32 - 1)
    return Frame(COMMAND_BASE + index, struct.pack("<BHIx", codes[operation], int(value), nonce))


def ingest(client: Client, frame: Frame, vehicle_ids: list[str], session: str = "can-trace") -> Any:
    try:
        index = frame.arbitration_id - COMMAND_BASE
        if not 0 <= index < len(vehicle_ids):
            raise ValueError("unknown command id")
        code, value, nonce = struct.unpack("<BHIx", frame.data)
        if frame.data[-1] != 0 or not nonce or code not in (0, 1, 2):
            raise ValueError("invalid command fields")
        if code == 0:
            integer(value, "ignition", 0, 1)
        else:
            integer(value, "control", 0, 1000)
        return client.call(
            "command",
            adapter="can",
            session=session,
            body={
                "command_id": f"can-{nonce}",
                "vehicle_id": vehicle_ids[index],
                "operation": ("set_ignition", "set_throttle", "set_brake")[code],
                "value": bool(value) if code == 0 else value,
            },
        )
    except ValueError:
        client.call(
            "observe",
            event_type="input.rejected",
            adapter="can",
            session=session,
            payload={"reason": "invalid_can_frame", "id": frame.arbitration_id},
        )
        raise


class MemoryBus:
    def __init__(self, capacity: int = 256) -> None:
        integer(capacity, "capacity", 1, 4096)
        self.capacity = capacity
        self.frames: deque[Frame] = deque()

    def send(self, frame: Frame) -> None:
        if len(self.frames) >= self.capacity:
            raise ValueError("memory bus full")
        self.frames.append(frame)

    def receive(self) -> Frame | None:
        return self.frames.popleft() if self.frames else None


class VCanBus:
    def __init__(self, interface: str) -> None:
        # No access to physical CAN interfaces through this adapter.
        if not interface.startswith("vcan") or not interface[4:].isdigit():
            raise ValueError("only explicitly created vcan interfaces supported")
        self.socket = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        try:
            self.socket.settimeout(1)
            self.socket.bind((interface,))
        except BaseException:
            self.socket.close()
            raise

    def send(self, frame: Frame) -> None:
        self.socket.send(struct.pack("=IB3x8s", frame.arbitration_id, 8, frame.data))

    def receive(self) -> Frame:
        raw = self.socket.recv(16)
        if len(raw) != 16:
            raise ValueError("invalid socketCAN frame")
        can_id, dlc, data = struct.unpack("=IB3x8s", raw)
        if can_id > 0x7FF or dlc != 8:
            raise ValueError("extended/RTR/error frames or wrong DLC rejected")
        return Frame(can_id, data)

    def close(self) -> None:
        self.socket.close()
