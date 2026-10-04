"""SQLite-backed single coordinator: every mutation is serialized and transactionally durable."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from miragetransit import checkpoint
from miragetransit.core import Fleet, canonical
from miragetransit.intents import evaluate, preflight
from miragetransit.models import Profile, identifier, integer
from miragetransit.provenance import runtime_stamp

SCHEMA_VERSION = 1
MAX_TICKS = 36_000
MAX_ATTEMPTS = 1000
MIGRATION_1 = (
    """CREATE TABLE runs (run_id TEXT PRIMARY KEY, checkpoint TEXT NOT NULL,
       initial TEXT NOT NULL, provenance TEXT NOT NULL)""",
    """CREATE TABLE snapshots (
       run_id TEXT NOT NULL REFERENCES runs ON DELETE CASCADE, tick INTEGER NOT NULL,
       snapshot TEXT NOT NULL, state_hash TEXT NOT NULL, PRIMARY KEY(run_id,tick))""",
    """CREATE TABLE identities (
       run_id TEXT NOT NULL REFERENCES runs ON DELETE CASCADE, identity TEXT NOT NULL,
       fingerprint TEXT NOT NULL, receipt TEXT NOT NULL, PRIMARY KEY(run_id,identity))""",
    """CREATE TABLE actions (
       run_id TEXT NOT NULL REFERENCES runs ON DELETE CASCADE, sequence INTEGER NOT NULL,
       action TEXT NOT NULL, PRIMARY KEY(run_id,sequence))""",
    """CREATE TABLE events (
       run_id TEXT NOT NULL REFERENCES runs ON DELETE CASCADE, sequence INTEGER NOT NULL,
       event TEXT NOT NULL, PRIMARY KEY(run_id,sequence))""",
)


class StoragePaused(RuntimeError):
    """The current coordinator session is blocked after a failed write."""


def encoded(value: object) -> str:
    return canonical(value).decode()


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, timeout=5, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.paused = False
        self.pause_reason: str | None = None
        try:
            self.connection.execute("PRAGMA foreign_keys=ON")
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA synchronous=FULL")
            self._migrate()
        except BaseException:
            self.connection.close()
            raise

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *args: object) -> None:
        self.connection.close()

    def _migrate(self) -> None:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            version = self.connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, SCHEMA_VERSION):
                raise ValueError(f"unsupported SQLite schema version {version}")
            if version == 0:
                existing = self.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
                if existing:
                    raise ValueError("unversioned database already contains tables")
                for statement in MIGRATION_1:
                    self.connection.execute(statement)
                self.connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise

    @contextmanager
    def _write(self) -> Iterator[None]:
        if self.paused:
            raise StoragePaused(f"coordinator paused: {self.pause_reason}")
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            yield
            self.connection.commit()
        except sqlite3.Error as error:
            self.connection.rollback()
            self.paused = True
            self.pause_reason = str(error)
            raise StoragePaused(
                "coordinator paused: SQLite write failed; last committed state preserved"
            ) from error
        except BaseException:
            self.connection.rollback()
            raise

    def _fleet(self, run_id: str) -> Fleet:
        identifier(run_id, "run_id")
        row = self.connection.execute(
            "SELECT checkpoint,provenance FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise ValueError("unknown run")
        if json.loads(row["provenance"]) != runtime_stamp():
            raise ValueError("run provenance differs from current runtime, engine or lock")
        return checkpoint.from_payload(json.loads(row["checkpoint"]))

    def _persist(self, run_id: str, fleet: Fleet) -> None:
        self.connection.execute(
            "UPDATE runs SET checkpoint=? WHERE run_id=?",
            (encoded(checkpoint.to_payload(fleet)), run_id),
        )

    def _event(
        self,
        run_id: str,
        fleet: Fleet,
        event_type: str,
        payload: object,
    ) -> dict[str, Any]:
        sequence = self.connection.execute(
            "SELECT COALESCE(MAX(sequence),0)+1 FROM events WHERE run_id=?", (run_id,)
        ).fetchone()[0]
        event = {
            "schema_version": 1,
            "event_id": f"{run_id}-event-{sequence}",
            "run_id": run_id,
            "sequence": sequence,
            "tick": fleet.tick,
            "observed_at_utc": datetime.now(UTC).isoformat(),
            "event_type": event_type,
            "state_version": fleet.tick,
            "payload": payload,
            "source_adapter": "coordinator",
            "session_id": None,
            "vehicle_id": None,
            "command_id": None,
            "correlation_edges": [],
        }
        if isinstance(payload, dict):
            body = payload.get("body", payload)
            if isinstance(body, dict):
                origin = body.get("origin")
                if isinstance(origin, dict):
                    event["source_adapter"] = origin.get("adapter", "coordinator")
                    event["session_id"] = origin.get("session_id")
                for name in ("vehicle_id", "command_id"):
                    try:
                        event[name] = identifier(body.get(name), name)
                    except ValueError:
                        pass
        self.connection.execute(
            "INSERT INTO events VALUES (?,?,?)", (run_id, sequence, encoded(event))
        )
        return event

    def observe(
        self, run_id: str, event_type: str, adapter: str, session_id: str, payload: object
    ) -> dict[str, Any]:
        """Bounded adapter evidence; observations never change replay inputs or physics."""
        identifier(adapter, "adapter")
        identifier(session_id, "session_id")
        if event_type not in ("session.opened", "artifact.read", "canary.used", "input.rejected"):
            raise ValueError("unsupported observation")
        if len(canonical(payload)) > 4096:
            raise ValueError("observation exceeds 4096 bytes")
        with self._write():
            count = self.connection.execute(
                "SELECT COUNT(*) FROM events WHERE run_id=? "
                "AND json_extract(event,'$.source_adapter')!='coordinator' "
                "AND json_extract(event,'$.event_type') IN "
                "('session.opened','artifact.read','canary.used','input.rejected')",
                (run_id,),
            ).fetchone()[0]
            if count >= 5000:
                raise ValueError("run observation budget reached")
            event = self._event(run_id, self._fleet(run_id), event_type, payload)
            event["source_adapter"] = adapter
            event["session_id"] = session_id
            self.connection.execute(
                "UPDATE events SET event=? WHERE run_id=? AND sequence=?",
                (encoded(event), run_id, event["sequence"]),
            )
            return event

    def _action(self, run_id: str, action: object) -> None:
        sequence = self.connection.execute(
            "SELECT COALESCE(MAX(sequence),0)+1 FROM actions WHERE run_id=?", (run_id,)
        ).fetchone()[0]
        self.connection.execute(
            "INSERT INTO actions VALUES (?,?,?)", (run_id, sequence, encoded(action))
        )

    def _create(self, run_id: str, profile: Profile, seed: int) -> Fleet:
        identifier(run_id, "run_id")
        fleet = Fleet(profile, seed)
        if self.connection.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone():
            raise ValueError("run already exists")
        payload = encoded(checkpoint.to_payload(fleet))
        self.connection.execute(
            "INSERT INTO runs VALUES (?,?,?,?)",
            (run_id, payload, payload, encoded(runtime_stamp())),
        )
        self.connection.execute(
            "INSERT INTO snapshots VALUES (?,?,?,?)",
            (run_id, 0, encoded(fleet.snapshot()), fleet.state_hash()),
        )
        self._event(run_id, fleet, "run.started", {"seed": seed})
        return fleet

    def create(self, run_id: str, profile: Profile, seed: int = 42) -> dict[str, Any]:
        with self._write():
            self._create(run_id, profile, seed)
        return self.inspect(run_id)

    def inspect(self, run_id: str) -> dict[str, Any]:
        fleet = self._fleet(run_id)
        return {
            "run_id": run_id,
            "paused": self.paused,
            "pause_reason": self.pause_reason,
            "state_sha256": fleet.state_hash(),
            "snapshot": fleet.snapshot(),
        }

    def _submit(self, run_id: str, fleet: Fleet, body: object) -> dict[str, Any]:
        attempts = self.connection.execute(
            "SELECT COUNT(*) FROM actions WHERE run_id=? "
            "AND json_extract(action,'$.kind')='submit'",
            (run_id,),
        ).fetchone()[0]
        if attempts >= MAX_ATTEMPTS:
            raise ValueError("run command-attempt limit reached")
        known = {
            row["identity"]: {
                "fingerprint": row["fingerprint"],
                "receipt": json.loads(row["receipt"]),
            }
            for row in self.connection.execute("SELECT * FROM identities WHERE run_id=?", (run_id,))
        }
        receipt, key, fingerprint = evaluate(fleet, run_id, body, known)
        if key is not None:
            self.connection.execute(
                "INSERT INTO identities VALUES (?,?,?,?)",
                (run_id, key, fingerprint, encoded(receipt)),
            )
        self._event(run_id, fleet, "command.received", {"body": body})
        self._event(
            run_id,
            fleet,
            f"command.{receipt['status']}",
            {"body": body, "receipt": receipt},
        )
        self._action(run_id, {"kind": "submit", "body": body, "receipt": receipt})
        self._persist(run_id, fleet)
        return receipt

    def submit(self, run_id: str, body: object) -> dict[str, Any]:
        preflight(body)
        with self._write():
            return self._submit(run_id, self._fleet(run_id), body)

    def _step(self, run_id: str, fleet: Fleet) -> None:
        if fleet.tick >= MAX_TICKS or (fleet.tick + 1) * len(fleet.states) > 500_000:
            raise ValueError("run exceeds simulation work budget")
        pending = [item for item in fleet.pending if item.tick == fleet.tick + 1]
        fleet.advance()
        for item in pending:
            identity = self.connection.execute(
                "SELECT identity FROM identities WHERE run_id=? "
                "AND json_extract(receipt,'$.sequence')=?",
                (run_id, item.sequence),
            ).fetchone()
            self._event(
                run_id,
                fleet,
                "command.applied",
                {
                    "sequence": item.sequence,
                    "vehicle_id": item.command.vehicle_id,
                    "command_id": identity["identity"].split(":", 1)[1] if identity else None,
                },
            )
        self._event(run_id, fleet, "state.updated", {"state_sha256": fleet.state_hash()})
        self._action(run_id, {"kind": "step"})
        self.connection.execute(
            "INSERT INTO snapshots VALUES (?,?,?,?)",
            (run_id, fleet.tick, encoded(fleet.snapshot()), fleet.state_hash()),
        )
        self._persist(run_id, fleet)

    def advance(self, run_id: str, ticks: int = 1) -> dict[str, Any]:
        integer(ticks, "ticks", 1, MAX_TICKS)
        initial = self._fleet(run_id)
        if initial.tick + ticks > MAX_TICKS:
            raise ValueError("run exceeds 36000 ticks")
        if (initial.tick + ticks) * len(initial.states) > 500_000:
            raise ValueError("run exceeds simulation work budget")
        for _ in range(ticks):
            with self._write():
                self._step(run_id, self._fleet(run_id))
        return self.inspect(run_id)

    def _stop(self, run_id: str, fleet: Fleet) -> None:
        if fleet.running:
            cancelled = [item.sequence for item in fleet.pending]
            fleet.stop()
            self._event(run_id, fleet, "run.stopped", {"cancelled_sequences": cancelled})
            self._action(run_id, {"kind": "stop"})
            self._persist(run_id, fleet)

    def stop(self, run_id: str) -> dict[str, Any]:
        with self._write():
            self._stop(run_id, self._fleet(run_id))
        return self.inspect(run_id)

    def events(self, run_id: str, after: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        self._fleet(run_id)
        integer(after, "after", 0, 2**63 - 1)
        integer(limit, "limit", 1, 1000)
        return [
            json.loads(row["event"])
            for row in self.connection.execute(
                "SELECT event FROM events WHERE run_id=? AND sequence>? ORDER BY sequence LIMIT ?",
                (run_id, after, limit),
            )
        ]

    def evidence(self, run_id: str, after: int = 0, limit: int = 1000) -> list[dict[str, Any]]:
        self._fleet(run_id)
        integer(after, "after", 0, 2**63 - 1)
        integer(limit, "limit", 1, 1000)
        return [
            json.loads(row["event"])
            for row in self.connection.execute(
                "SELECT event FROM events WHERE run_id=? AND sequence>? "
                "AND json_extract(event,'$.event_type') IN "
                "('session.opened','artifact.read','canary.used','input.rejected') "
                "ORDER BY sequence LIMIT ?",
                (run_id, after, limit),
            )
        ]

    def prune(self, run_id: str) -> None:
        with self._write():
            if self._fleet(run_id).running:
                raise ValueError("cannot prune an active run")
            self.connection.execute("DELETE FROM runs WHERE run_id=?", (run_id,))
