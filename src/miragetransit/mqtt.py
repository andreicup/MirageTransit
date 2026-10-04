"""A bounded MQTT 3.1.1 lab broker subset: QoS 0/1, run ACLs, no retained commands.

Not a general-purpose broker: no persistence, wills, QoS 2 or arbitrary topic routing.
Telemetry and application acknowledgments are QoS 0. Inbound QoS 1 gets a transport PUBACK
separately from the JSON application receipt. Unsupported features close the connection.
"""

import hmac
import json
import socket
import socketserver
import struct
import threading
import time
from typing import Any

from miragetransit.core import canonical
from miragetransit.evidence import token_fingerprint
from miragetransit.models import identifier
from miragetransit.rpc import Client, new_session

MAX_PACKET = 4608


def text_field(value: str) -> bytes:
    data = value.encode("utf-8")
    if len(data) > 4096 or b"\x00" in data:
        raise ValueError("invalid MQTT string")
    return struct.pack("!H", len(data)) + data


def read_field(data: bytes, offset: int = 0) -> tuple[str, int]:
    if len(data) < offset + 2:
        raise ValueError("truncated string")
    length = struct.unpack_from("!H", data, offset)[0]
    end = offset + 2 + length
    if end > len(data) or length > 4096:
        raise ValueError("truncated or oversized string")
    value = data[offset + 2 : end].decode("utf-8")
    if "\x00" in value:
        raise ValueError("null MQTT string")
    return value, end


def packet(header: int, data: bytes = b"") -> bytes:
    length = len(data)
    encoded = bytearray()
    while True:
        digit = length % 128
        length //= 128
        encoded.append(digit | (128 if length else 0))
        if not length:
            break
    return bytes([header]) + encoded + data


def receive(sock: socket.socket) -> tuple[int, bytes]:
    first = sock.recv(1)
    if not first:
        raise EOFError
    length = 0
    for index in range(4):
        data = sock.recv(1)
        if not data:
            raise EOFError
        length += (data[0] & 127) * 128**index
        if not data[0] & 128:
            break
    else:
        raise ValueError("malformed remaining length")
    if length > MAX_PACKET:
        raise ValueError("MQTT packet too large")
    body = bytearray()
    while len(body) < length:
        chunk = sock.recv(length - len(body))
        if not chunk:
            raise EOFError
        body.extend(chunk)
    return first[0], bytes(body)


def publish(topic: str, value: object) -> bytes:
    return packet(0x30, text_field(topic) + canonical(value))


def match(filter: str, topic: str) -> bool:
    parts, actual = filter.split("/"), topic.split("/")
    return len(parts) == len(actual) and all(
        a == "+" or a == b for a, b in zip(parts, actual, strict=True)
    )


class Broker(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, address: tuple[str, int], client: Client, run_id: str) -> None:
        self.client = client
        self.run_id = run_id
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(address, MQTTHandler)

    def process_request(self, request: Any, address: Any) -> None:
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request: Any, address: Any) -> None:
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()

    def handle_error(self, request: Any, client_address: Any) -> None:
        pass


class MQTTHandler(socketserver.BaseRequestHandler):
    server: Broker
    request: socket.socket

    def handle(self) -> None:
        session = new_session()
        client, run = self.server.client, self.server.run_id
        sock = self.request
        sock.settimeout(2)
        subscriptions: set[str] = set()
        observations = 0
        try:
            header, data = receive(sock)
            if header != 0x10:
                raise ValueError("CONNECT required")
            protocol, pos = read_field(data)
            if protocol != "MQTT" or len(data) < pos + 4 or data[pos] != 4:
                raise ValueError("requires MQTT 3.1.1")
            flags = data[pos + 1]
            # Username/password, clean session, no will, no reserved bits.
            if flags != 0xC2:
                raise ValueError("unsupported CONNECT flags")
            keepalive = struct.unpack_from("!H", data, pos + 2)[0]
            client_id, pos = read_field(data, pos + 4)
            identifier(client_id, "client id")
            username, pos = read_field(data, pos)
            password, pos = read_field(data, pos)
            if pos != len(data) or not username.startswith(run + ":"):
                sock.sendall(packet(0x20, b"\x00\x05"))
                return
            token = identifier(username.split(":", 1)[1], "token")
            expected = client.call("credentials", token=token)
            if not hmac.compare_digest(password, expected["password"]):
                sock.sendall(packet(0x20, b"\x00\x05"))
                return
            client.call(
                "observe",
                event_type="session.opened",
                adapter="mqtt",
                session=session,
                payload={"surface": "mqtt-3.1.1"},
            )
            client.call(
                "observe",
                event_type="canary.used",
                adapter="mqtt",
                session=session,
                payload={"token_sha256": token_fingerprint(token)},
            )
            sock.sendall(packet(0x20, b"\x00\x00"))
            next_telemetry = time.monotonic()
            window, count = time.monotonic(), 0
            last_input = time.monotonic()
            idle_limit = min(60, max(3, keepalive * 1.5)) if keepalive else 60
            while True:
                now = time.monotonic()
                if now - last_input > idle_limit:
                    return
                if now >= next_telemetry and subscriptions:
                    projection = client.call("state")
                    for state in projection["snapshot"]["states"]:
                        topic = f"mt/{run}/fleet/{state['vehicle_id']}/telemetry"
                        if any(match(sub, topic) for sub in subscriptions):
                            sock.sendall(
                                publish(
                                    topic,
                                    {
                                        "run_id": run,
                                        "state_version": projection["snapshot"]["tick"],
                                        "tick": projection["snapshot"]["tick"],
                                        "stale": projection["stale"],
                                        "vehicle": state,
                                    },
                                )
                            )
                    next_telemetry = now + 0.5
                # select avoids losing a partly read packet at a short telemetry timeout.
                import select

                readable, _, _ = select.select([sock], [], [], 0.1)
                if not readable:
                    continue
                header, data = receive(sock)
                last_input = time.monotonic()
                if now - window >= 1:
                    window, count = now, 0
                count += 1
                if count > 10:
                    if observations < 20:
                        client.call(
                            "observe",
                            event_type="input.rejected",
                            adapter="mqtt",
                            session=session,
                            payload={"reason": "session_rate_limit"},
                        )
                    return
                kind = header >> 4
                if header == 0xC0 and not data:
                    sock.sendall(packet(0xD0))
                elif header == 0xE0 and not data:
                    return
                elif header == 0x82:
                    if len(data) < 5:
                        raise ValueError("empty SUBSCRIBE")
                    packet_id = data[:2]
                    if packet_id == b"\x00\x00":
                        raise ValueError("invalid packet identifier")
                    pos = 2
                    codes = bytearray()
                    while pos < len(data):
                        topic, pos = read_field(data, pos)
                        if pos >= len(data):
                            raise ValueError("missing subscription QoS")
                        qos = data[pos]
                        pos += 1
                        parts = topic.split("/")
                        valid = (
                            len(parts) == 5
                            and parts[:3] == ["mt", run, "fleet"]
                            and parts[4] in ("telemetry", "ack")
                            and qos in (0, 1)
                            and len(subscriptions) < 16
                        )
                        if valid:
                            if parts[3] != "+":
                                identifier(parts[3], "vehicle")
                            subscriptions.add(topic)
                            codes.append(0)  # Outbound QoS 0 is explicit in SUBACK.
                        else:
                            codes.append(0x80)
                    sock.sendall(packet(0x90, packet_id + codes))
                    next_telemetry = 0
                elif kind == 3:
                    qos = (header >> 1) & 3
                    if qos not in (0, 1) or (qos == 0 and header & 8):
                        raise ValueError("unsupported publish flags")
                    topic, pos = read_field(data)
                    packet_id = b""
                    if qos:
                        packet_id = data[pos : pos + 2]
                        pos += 2
                        if len(packet_id) != 2 or packet_id == b"\x00\x00":
                            raise ValueError("invalid packet identifier")
                    parts = topic.split("/")
                    allowed = (
                        len(parts) == 5
                        and parts[:3] == ["mt", run, "fleet"]
                        and parts[4] == "command"
                    )
                    reason = "retained_command" if header & 1 else "topic_acl"
                    if not allowed or header & 1:
                        receipt = {"status": "rejected", "reason_code": reason}
                    else:
                        vehicle = identifier(parts[3], "vehicle")
                        body = json.loads(data[pos:])
                        if not isinstance(body, dict) or set(body) - {
                            "command_id",
                            "operation",
                            "value",
                            "scheduled_tick",
                        }:
                            raise ValueError("invalid command body")
                        receipt = client.call(
                            "command",
                            adapter="mqtt",
                            session=session,
                            body={**body, "vehicle_id": vehicle},
                        )
                    if receipt["status"] == "rejected" and observations < 20:
                        client.call(
                            "observe",
                            event_type="input.rejected",
                            adapter="mqtt",
                            session=session,
                            payload={"reason": receipt["reason_code"]},
                        )
                        observations += 1
                    if qos:
                        sock.sendall(packet(0x40, packet_id))
                    if allowed:
                        ack_topic = f"mt/{run}/fleet/{parts[3]}/ack"
                        if any(match(sub, ack_topic) for sub in subscriptions):
                            sock.sendall(publish(ack_topic, receipt))
                else:
                    raise ValueError("unsupported packet")
        except (ValueError, KeyError, TypeError, UnicodeError, RecursionError, OSError, EOFError):
            # Bounded best-effort malformed-input evidence. Never store passwords or raw bytes.
            if observations < 20:
                try:
                    client.call(
                        "observe",
                        event_type="input.rejected",
                        adapter="mqtt",
                        session=session,
                        payload={"reason": "malformed_or_disconnected"},
                    )
                except (ValueError, OSError):
                    pass


def serve_mqtt(address: tuple[str, int], client: Client, run_id: str) -> None:
    with Broker(address, client, run_id) as broker:
        broker.serve_forever()
