"""Synthetic demo client; the invocation captures its output instead of exposing credentials."""

import json
import socket
import sys
from pathlib import Path

from miragetransit.mqtt import packet, receive, text_field

config = json.loads((Path(sys.argv[1]) / "mqtt.json").read_bytes())
credentials = json.loads(sys.argv[2])
with socket.create_connection(("127.0.0.1", config["port"]), timeout=3) as sock:
    data = b"\x00\x04MQTT\x04\xc2\x00\x1e" + text_field("portfolio-client")
    data += text_field(credentials["username"]) + text_field(credentials["password"])
    sock.sendall(packet(0x10, data))
    if receive(sock) != (0x20, b"\x00\x00"):
        raise ValueError("MQTT demo authentication failed")
    body = json.dumps(
        {"command_id": "portfolio-brake", "operation": "set_brake", "value": 700}
    ).encode()
    data = text_field(f"mt/{config['run_id']}/fleet/MT-001/command") + b"\x00\x01" + body
    for header in (0x32, 0x3A):
        sock.sendall(packet(header, data))
        if receive(sock) != (0x40, b"\x00\x01"):
            raise ValueError("MQTT transport acknowledgment missing")
    sock.sendall(packet(0xE0))
