"""Bounded internal RPC, capability keys, and a single SQLite owner."""

import hashlib
import hmac
import json
import queue
import secrets
import statistics
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import Future
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from miragetransit.core import canonical
from miragetransit.intents import envelope
from miragetransit.models import identifier
from miragetransit.replay import export_bundle
from miragetransit.storage import StoragePaused, Store

MAX_REQUEST = 8192


class LimitedServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 16

    def __init__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler]) -> None:
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(address, handler)

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try:
            request.settimeout(3)
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request: Any, client_address: Any) -> None:
        # No raw requests, bearer keys, or client payloads in process logs.
        pass


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, format: str, *args: object) -> None:
        pass

    def reply(self, status: int, value: object, mime: str = "application/json") -> None:
        data = value if isinstance(value, bytes) else canonical(value)
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def body(self, limit: int = MAX_REQUEST) -> Any:
        if self.headers.get("Transfer-Encoding"):
            raise ValueError("transfer encoding unsupported")
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= limit:
            raise ValueError("invalid content length")
        raw = self.rfile.read(size)
        if len(raw) != size:
            raise ValueError("incomplete body")
        return json.loads(raw)


class Client:
    def __init__(self, url: str, key: str) -> None:
        self.url = url.rstrip("/")
        self.key = key

    def call(self, operation: str, **arguments: Any) -> Any:
        request = urllib.request.Request(
            self.url + "/rpc",
            canonical({"operation": operation, **arguments}),
            {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise ValueError(json.loads(error.read()).get("error", "RPC rejected")) from error


class Coordinator:
    def __init__(self, store: Store, run_id: str, decoy_key: str, analyst_key: str) -> None:
        self.store = store
        self.run_id = run_id
        self.keys = {"decoy": decoy_key, "analyst": analyst_key}
        self.queue: queue.Queue[tuple[str, dict[str, Any], Future[Any]]] = queue.Queue(64)
        self.shutdown = threading.Event()
        self.failure: str | None = None
        self.tick_delays_ms: list[float] = []
        self.last_tick = time.monotonic()

    def dispatch(self, role: str, request: dict[str, Any]) -> Any:
        operation = request.get("operation")
        allowed = {"state", "command", "observe", "credentials", "health"}
        if role == "analyst":
            allowed |= {"events", "evidence", "export", "stop", "metrics"}
        if operation not in allowed:
            raise ValueError("capability denied")
        if operation == "health":
            state = self.store.inspect(self.run_id)
            return {
                "healthy": self.failure is None and not state["paused"],
                "running": state["snapshot"]["running"],
                "failure": self.failure,
            }
        if operation == "metrics":
            delays = self.tick_delays_ms
            return {
                "ticks_measured": len(delays),
                "tick_deadline_lateness_ms_mean": round(statistics.mean(delays), 3)
                if delays
                else 0,
                "tick_deadline_lateness_ms_p95": round(sorted(delays)[int(len(delays) * 0.95)], 3)
                if delays
                else 0,
                "tick_deadline_lateness_ms_max": round(max(delays), 3) if delays else 0,
            }
        if operation == "state":
            result = self.store.inspect(self.run_id)
            result["age_ms"] = round((time.monotonic() - self.last_tick) * 1000)
            result["stale"] = self.failure is not None or (
                result["snapshot"]["running"] and result["age_ms"] > 1500
            )
            result["route"] = [
                asdict(point) for point in self.store._fleet(self.run_id).profile.route
            ]
            return result
        if operation == "command":
            adapter = request.get("adapter")
            if adapter not in ("http", "mqtt", "can", "analyst"):
                raise ValueError("unknown adapter")
            if role == "decoy" and adapter == "analyst":
                raise ValueError("capability denied")
            body = request.get("body")
            if not isinstance(body, dict) or set(body) - {
                "command_id",
                "vehicle_id",
                "operation",
                "value",
                "scheduled_tick",
            }:
                raise ValueError("invalid adapter command")
            intent = envelope(
                self.run_id,
                body["command_id"],
                body["vehicle_id"],
                body["operation"],
                body["value"],
                body.get("scheduled_tick"),
            )
            intent["origin"] = {
                "adapter": adapter,
                "session_id": identifier(request.get("session"), "session"),
            }
            return self.store.submit(self.run_id, intent)
        if operation == "observe":
            if role == "decoy" and request.get("adapter") not in ("http", "mqtt", "can"):
                raise ValueError("capability denied")
            return self.store.observe(
                self.run_id,
                request["event_type"],
                request["adapter"],
                request["session"],
                request["payload"],
            )
        if operation == "credentials":
            token = identifier(request.get("token"), "token")
            secret = hmac.new(
                self.keys["decoy"].encode(), f"{self.run_id}:{token}".encode(), hashlib.sha256
            ).hexdigest()
            return {"username": f"{self.run_id}:{token}", "password": secret}
        if operation == "events":
            return self.store.events(
                self.run_id, request.get("after", 0), request.get("limit", 100)
            )
        if operation == "evidence":
            return self.store.evidence(self.run_id, request.get("after", 0))
        if operation == "stop":
            return self.store.stop(self.run_id)
        if operation == "export":
            # Temporary file has no user-selected path and is always removed.
            import tempfile

            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "scenario.json"
                export_bundle(self.store, self.run_id, path)
                return json.loads(path.read_bytes())
        raise ValueError("unknown operation")

    def serve(self, address: tuple[str, int], realtime: bool = True) -> None:
        owner = self

        class RPCHandler(Handler):
            def do_GET(self) -> None:
                if self.path == "/healthz":
                    self.reply(
                        200 if owner.failure is None else 503, {"healthy": owner.failure is None}
                    )
                else:
                    self.reply(404, {"error": "not found"})

            def do_POST(self) -> None:
                try:
                    if self.path != "/rpc":
                        self.reply(404, {"error": "not found"})
                        return
                    supplied = self.headers.get("Authorization", "").removeprefix("Bearer ")
                    role = next(
                        (
                            role
                            for role, key in owner.keys.items()
                            if hmac.compare_digest(supplied, key)
                        ),
                        None,
                    )
                    if role is None:
                        self.reply(401, {"error": "unauthorized"})
                        return
                    body = self.body()
                    if not isinstance(body, dict):
                        raise ValueError("invalid request")
                    future: Future[Any] = Future()
                    owner.queue.put_nowait((role, body, future))
                    self.reply(200, future.result(timeout=2.5))
                except TimeoutError:
                    future.cancel()
                    self.reply(503, {"error": "coordinator response timed out; retry command ID"})
                except queue.Full:
                    self.reply(429, {"error": "coordinator queue full"})
                except (ValueError, KeyError, TypeError, RecursionError) as error:
                    self.reply(400, {"error": str(error)[:200]})
                except (StoragePaused, OSError):
                    self.reply(503, {"error": "coordinator unavailable"})

        server = LimitedServer(address, RPCHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        next_tick = time.monotonic() + 0.1
        try:
            while not self.shutdown.is_set():
                now = time.monotonic()
                if realtime and now >= next_tick and self.failure is None:
                    try:
                        if self.store.inspect(self.run_id)["snapshot"]["running"]:
                            self.store.advance(self.run_id)
                            self.last_tick = time.monotonic()
                            if len(self.tick_delays_ms) < 36_000:
                                self.tick_delays_ms.append(max(0.0, (now - next_tick) * 1000))
                    except (StoragePaused, ValueError) as error:
                        self.failure = str(error)
                    # No unbounded catch-up burst following stalls.
                    next_tick = max(next_tick + 0.1, time.monotonic())
                try:
                    role, body, future = self.queue.get(timeout=0.01)
                except queue.Empty:
                    continue
                if future.set_running_or_notify_cancel():
                    try:
                        future.set_result(self.dispatch(role, body))
                    except Exception as error:
                        future.set_exception(error)
        finally:
            server.shutdown()
            server.server_close()


def new_session() -> str:
    return "s-" + secrets.token_hex(12)
