"""Real four-process lab fixture using ephemeral loopback ports."""

import http.cookiejar
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from miragetransit.service import initialize


def available_ports() -> int:
    for _ in range(100):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        base = sock.getsockname()[1]
        sock.close()
        if base > 65532:
            continue
        reservations = []
        try:
            for port in range(base, base + 4):
                reservation = socket.socket()
                reservations.append(reservation)
                reservation.bind(("127.0.0.1", port))
            return int(base)
        except OSError:
            pass
        finally:
            for reservation in reservations:
                reservation.close()
    raise RuntimeError("could not reserve local ports")


class Lab:
    def __init__(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.base = available_ports()
        initialize(self.directory, "test-lab", self.base)
        self.configs = {
            role: json.loads((self.directory / f"{role}.json").read_bytes())
            for role in ("core", "decoy", "mqtt", "analyst")
        }
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        self.process = subprocess.Popen(
            [sys.executable, "-m", "miragetransit", "lab", "--directory", str(self.directory)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=os.environ.copy(),
        )
        self.csrf = ""
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(self.process.stderr.read().decode())
            try:
                if self.request("analyst", "/healthz")[0] == 200:
                    self.request("decoy", "/healthz")
                    break
            except OSError:
                time.sleep(0.05)
        else:
            self.close()
            raise RuntimeError("lab startup timeout")

    def request(
        self, role: str, path: str, body: Any = None, headers: dict[str, str] | None = None
    ) -> tuple[int, Any]:
        headers = {"Content-Type": "application/json", **(headers or {})}
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.configs[role]['port']}{path}",
            json.dumps(body).encode() if body is not None else None,
            headers,
        )
        try:
            response = self.opener.open(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read()
            return response.code, json.loads(
                raw
            ) if response.headers.get_content_type() == "application/json" else raw

    def login(self) -> None:
        status, result = self.request(
            "analyst", "/api/login", {"password": self.configs["analyst"]["password"]}
        )
        if status != 200:
            raise RuntimeError("fixture login failed")
        self.csrf = result["csrf"]

    def close(self) -> None:
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        if self.process.stderr:
            self.process.stderr.close()
        self.temp.cleanup()
