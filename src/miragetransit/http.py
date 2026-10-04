"""Separate decoy and authenticated analyst processes; neither can access SQLite."""

import hmac
import json
import secrets
import time
from http.cookies import SimpleCookie
from importlib.resources import files
from typing import Any
from urllib.parse import parse_qs, urlsplit

from miragetransit.evidence import graph, sanitized_bundle, token_fingerprint
from miragetransit.models import identifier
from miragetransit.replay import MAX_BUNDLE_BYTES, verify
from miragetransit.rpc import Client, Handler, LimitedServer, new_session


def cookie_value(headers: Any, name: str) -> str:
    cookie = SimpleCookie()
    try:
        cookie.load(headers.get("Cookie", ""))
        return cookie[name].value if name in cookie else ""
    except Exception:
        return ""


def serve_decoy(address: tuple[str, int], client: Client, run_id: str, mqtt_port: int) -> None:
    class Decoy(Handler):
        def session(self) -> str:
            raw = cookie_value(self.headers, "mt_decoy")
            try:
                session, signature = raw.split(".", 1)
                identifier(session, "session")
                expected = hmac.digest(client.key.encode(), session.encode(), "sha256").hex()
                if hmac.compare_digest(signature, expected):
                    return session
            except ValueError:
                pass
            session = new_session()
            self.created_session = session
            client.call(
                "observe",
                event_type="session.opened",
                adapter="http",
                session=session,
                payload={"surface": "fleet-portal"},
            )
            return session

        def end_headers(self) -> None:
            session = getattr(self, "created_session", None)
            if session:
                signature = hmac.digest(client.key.encode(), session.encode(), "sha256").hex()
                self.send_header(
                    "Set-Cookie",
                    f"mt_decoy={session}.{signature}; "
                    "HttpOnly; SameSite=Strict; Path=/; Max-Age=900",
                )
            super().end_headers()

        def do_GET(self) -> None:
            try:
                path = urlsplit(self.path).path
                if path == "/healthz":
                    health = client.call("health")
                    self.reply(200 if health["healthy"] else 503, health)
                    return
                if path in ("/", "/app.js", "/style.css"):
                    filename = {
                        "/": "decoy.html",
                        "/app.js": "decoy.js",
                        "/style.css": "style.css",
                    }[path]
                    mime = {
                        "/": "text/html; charset=utf-8",
                        "/app.js": "text/javascript",
                        "/style.css": "text/css",
                    }[path]
                    self.reply(
                        200, files("miragetransit").joinpath("web", filename).read_bytes(), mime
                    )
                    return
                session = self.session()
                if path == "/fleet":
                    self.reply(200, client.call("state"))
                elif path.startswith("/vehicles/") and path.count("/") == 2:
                    vehicle = identifier(path.split("/")[2], "vehicle")
                    projection = client.call("state")
                    found = next(
                        (s for s in projection["snapshot"]["states"] if s["vehicle_id"] == vehicle),
                        None,
                    )
                    self.reply(
                        200 if found else 404,
                        {
                            "run_id": run_id,
                            "state_version": projection["snapshot"]["tick"],
                            "stale": projection["stale"],
                            "vehicle": found,
                        },
                    )
                elif path == "/documents/maintenance":
                    # Stable for this signed portal session; only synthetic credentials.
                    token = (
                        "c-"
                        + hmac.digest(
                            client.key.encode(), f"{run_id}:{session}".encode(), "sha256"
                        ).hex()[:24]
                    )
                    credentials = client.call("credentials", token=token)
                    client.call(
                        "observe",
                        event_type="artifact.read",
                        adapter="http",
                        session=session,
                        payload={
                            "artifact": "maintenance",
                            "token_sha256": token_fingerprint(token),
                        },
                    )
                    self.reply(
                        200,
                        {
                            "organization": "Mirage Fleet Lab (synthetic)",
                            "run_id": run_id,
                            "broker_port": mqtt_port,
                            "telemetry_topic": f"mt/{run_id}/fleet/+/telemetry",
                            "command_topic": f"mt/{run_id}/fleet/MT-001/command",
                            "credentials": credentials,
                            "note": "Synthetic maintenance gateway. Local research lab.",
                        },
                    )
                else:
                    self.reply(404, {"error": "not found"})
            except (ValueError, KeyError, TypeError, RecursionError):
                self.reply(400, {"error": "invalid request"})
            except OSError:
                self.reply(503, {"error": "coordinator unavailable"})

        def do_POST(self) -> None:
            try:
                path = urlsplit(self.path).path
                parts = path.strip("/").split("/")
                if len(parts) != 3 or parts[0] != "vehicles" or parts[2] != "commands":
                    self.reply(404, {"error": "not found"})
                    return
                vehicle = identifier(parts[1], "vehicle")
                body = self.body(4096)
                if not isinstance(body, dict) or set(body) - {
                    "command_id",
                    "operation",
                    "value",
                    "scheduled_tick",
                }:
                    raise ValueError("invalid command")
                receipt = client.call(
                    "command",
                    adapter="http",
                    session=self.session(),
                    body={**body, "vehicle_id": vehicle},
                )
                self.reply(202 if receipt["status"] == "accepted" else 422, receipt)
            except (ValueError, KeyError, TypeError, RecursionError):
                self.reply(400, {"error": "invalid command"})
            except OSError:
                self.reply(503, {"error": "coordinator unavailable"})

    with LimitedServer(address, Decoy) as server:
        server.serve_forever()


def serve_analyst(address: tuple[str, int], client: Client, password: str) -> None:
    sessions: dict[str, tuple[float, str]] = {}
    # Local console has bounded short-lived authentication sessions and login attempts.
    attempts: dict[str, tuple[float, int]] = {}
    import threading

    lock = threading.Lock()

    class Analyst(Handler):
        def authorized(self, mutation: bool = False) -> bool:
            session = cookie_value(self.headers, "mt_analyst")
            with lock:
                data = sessions.get(session)
                if data is None or data[0] <= time.monotonic():
                    sessions.pop(session, None)
                    return False
            return not mutation or hmac.compare_digest(
                self.headers.get("X-CSRF-Token", ""), data[1]
            )

        def do_GET(self) -> None:
            try:
                parsed = urlsplit(self.path)
                path = parsed.path
                if path == "/healthz":
                    health = client.call("health")
                    self.reply(200 if health["healthy"] else 503, health)
                    return
                if path in ("/", "/app.js", "/style.css"):
                    filename = {
                        "/": "analyst.html",
                        "/app.js": "analyst.js",
                        "/style.css": "style.css",
                    }[path]
                    mime = {
                        "/": "text/html; charset=utf-8",
                        "/app.js": "text/javascript",
                        "/style.css": "text/css",
                    }[path]
                    self.reply(
                        200, files("miragetransit").joinpath("web", filename).read_bytes(), mime
                    )
                    return
                if not self.authorized():
                    self.reply(401, {"error": "unauthorized"})
                    return
                query = parse_qs(parsed.query)
                if path == "/api/session":
                    data = sessions[cookie_value(self.headers, "mt_analyst")]
                    self.reply(200, {"csrf": data[1]})
                elif path == "/api/state":
                    self.reply(200, client.call("state"))
                elif path in ("/api/events", "/api/stream"):
                    after = int(self.headers.get("Last-Event-ID") or query.get("after", ["0"])[0])
                    limit = int(query.get("limit", ["100"])[0])
                    events = client.call("events", after=after, limit=limit)
                    if path.endswith("stream"):
                        # Finite batches free the worker; EventSource reconnects with ordered IDs.
                        stream_data = "retry: 1000\n\n" + "".join(
                            f"id: {e['sequence']}\ndata: {json.dumps(e)}\n\n" for e in events
                        )
                        self.reply(200, stream_data.encode(), "text/event-stream")
                    else:
                        self.reply(
                            200,
                            {
                                "events": events,
                                "next_cursor": events[-1]["sequence"] if events else after,
                            },
                        )
                elif path == "/api/graph":
                    observations = []
                    after = 0
                    for _ in range(6):
                        batch = client.call("evidence", after=after)
                        observations.extend(batch)
                        if len(batch) < 1000:
                            break
                        after = batch[-1]["sequence"]
                    self.reply(200, graph(observations))
                elif path == "/api/export":
                    self.reply(200, sanitized_bundle(client.call("export")))
                else:
                    self.reply(404, {"error": "not found"})
            except (ValueError, KeyError, TypeError, RecursionError):
                self.reply(400, {"error": "invalid request"})
            except OSError:
                self.reply(503, {"error": "coordinator unavailable"})

        def do_POST(self) -> None:
            try:
                if self.path == "/api/login":
                    now = time.monotonic()
                    address = self.client_address[0]
                    with lock:
                        for key in list(attempts):
                            if now - attempts[key][0] > 60:
                                del attempts[key]
                        for key in list(sessions):
                            if sessions[key][0] <= now:
                                del sessions[key]
                        window, count = attempts.get(address, (now, 0))
                        if count >= 20 or len(attempts) >= 1024 or len(sessions) >= 256:
                            self.reply(429, {"error": "login rate exceeded"})
                            return
                        attempts[address] = (window, count + 1)
                    body = self.body(1024)
                    if (
                        not isinstance(body, dict)
                        or not isinstance(body.get("password"), str)
                        or not hmac.compare_digest(body["password"], password)
                    ):
                        self.reply(401, {"error": "invalid credentials"})
                        return
                    session, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                    with lock:
                        sessions[session] = (now + 900, csrf)
                    self.send_response(200)
                    data = json.dumps({"csrf": csrf}).encode()
                    self.send_header(
                        "Set-Cookie",
                        f"mt_analyst={session}; HttpOnly; SameSite=Strict; Path=/; Max-Age=900",
                    )
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if not self.authorized(mutation=True):
                    self.reply(403, {"error": "authorization or CSRF denied"})
                    return
                if self.path == "/api/logout":
                    with lock:
                        sessions.pop(cookie_value(self.headers, "mt_analyst"), None)
                    self.reply(200, {"logged_out": True})
                elif self.path == "/api/stop":
                    self.reply(200, client.call("stop"))
                elif self.path == "/api/commands":
                    self.reply(
                        200,
                        client.call(
                            "command",
                            adapter="analyst",
                            session="analyst-session",
                            body=self.body(4096),
                        ),
                    )
                elif self.path == "/api/replay":
                    self.reply(200, verify(self.body(MAX_BUNDLE_BYTES)))
                else:
                    self.reply(404, {"error": "not found"})
            except (ValueError, KeyError, TypeError, RecursionError):
                self.reply(400, {"error": "invalid request or replay"})
            except OSError:
                self.reply(503, {"error": "coordinator unavailable"})

    with LimitedServer(address, Analyst) as server:
        server.serve_forever()
