import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from miragetransit.core import Fleet
from miragetransit.intents import envelope
from miragetransit.models import Command
from miragetransit.profile import load_profile
from miragetransit.storage import StoragePaused, Store


class StorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "runs.sqlite"
        self.store = Store(self.db)
        self.store.create("test", load_profile(), 42)

    def tearDown(self) -> None:
        self.store.connection.close()
        self.temp.cleanup()

    def command(self, command_id: str, operation: str, value: int | bool) -> dict[str, object]:
        return envelope("test", command_id, "MT-001", operation, value)

    def test_recovery_with_pending_inputs_matches_memory_core(self) -> None:
        self.store.submit("test", self.command("ignition", "set_ignition", True))
        self.store.submit("test", self.command("throttle", "set_throttle", 700))
        self.store.advance("test", 15)
        with Store(self.db) as restarted:
            restored = restarted.advance("test", 15)
        memory = Fleet(load_profile())
        memory.submit(Command("MT-001", "set_ignition", True))
        memory.submit(Command("MT-001", "set_throttle", 700))
        memory.advance(30)
        self.assertEqual(restored["state_sha256"], memory.state_hash())

    def test_duplicate_before_and_after_application_applies_once(self) -> None:
        body = self.command("ignition", "set_ignition", True)
        first = self.store.submit("test", body)
        second = self.store.submit("test", body)
        self.assertEqual(first["sequence"], second["sequence"])
        self.assertTrue(second["duplicate"])
        self.store.advance("test", 2)
        with Store(self.db) as restarted:
            third = restarted.submit("test", body)
        self.assertTrue(third["duplicate"])
        applied = [e for e in self.store.events("test") if e["event_type"] == "command.applied"]
        self.assertEqual(len(applied), 1)

    def test_conflicting_identity_does_not_mutate_queue(self) -> None:
        self.store.submit("test", self.command("same", "set_throttle", 700))
        result = self.store.submit("test", self.command("same", "set_throttle", 900))
        self.assertEqual(result["reason_code"], "id_conflict")
        self.store.advance("test")
        self.assertEqual(
            self.store.inspect("test")["snapshot"]["states"][0]["throttle_permille"], 700
        )

    def test_identity_is_scoped_by_vehicle_and_run(self) -> None:
        a = self.store.submit("test", self.command("same", "set_throttle", 700))
        b = self.store.submit("test", envelope("test", "same", "MT-002", "set_throttle", 800))
        self.store.create("other", load_profile())
        c = self.store.submit("other", envelope("other", "same", "MT-001", "set_throttle", 900))
        self.assertFalse(a["duplicate"] or b["duplicate"] or c["duplicate"])
        self.assertNotEqual(a["sequence"], b["sequence"])

    def test_invalid_inputs_are_recorded_without_state_mutation(self) -> None:
        before = self.store.inspect("test")["state_sha256"]
        cases = [
            {"hello": "world"},
            envelope("wrong", "one", "MT-001", "set_throttle", 700),
            envelope("test", "two", "missing", "set_throttle", 700),
            envelope("test", "three", "MT-001", "set_throttle", 1001),
        ]
        for body in cases:
            result = self.store.submit("test", body)
            self.assertEqual(result["status"], "rejected")
        self.assertEqual(before, self.store.inspect("test")["state_sha256"])
        self.assertEqual(len(self.store._fleet("test").pending), 0)
        self.assertEqual(
            sum(e["event_type"] == "command.rejected" for e in self.store.events("test")), 4
        )

    def test_schedule_is_tick_order_then_fifo(self) -> None:
        self.store.submit("test", envelope("test", "later", "MT-001", "set_throttle", 100, 5))
        self.store.submit("test", envelope("test", "early", "MT-001", "set_throttle", 700, 2))
        self.store.advance("test", 2)
        self.assertEqual(
            self.store.inspect("test")["snapshot"]["states"][0]["throttle_permille"], 700
        )
        self.store.advance("test", 3)
        self.assertEqual(
            self.store.inspect("test")["snapshot"]["states"][0]["throttle_permille"], 100
        )

    def test_partial_tick_failure_rolls_back_events_snapshot_and_queue(self) -> None:
        self.store.submit("test", self.command("ignition", "set_ignition", True))
        before = self.store.inspect("test")
        events = self.store.events("test")
        self.store.connection.execute(
            """CREATE TRIGGER fail_tick BEFORE INSERT ON snapshots
               WHEN NEW.tick=1 BEGIN SELECT RAISE(ABORT,'injected write failure'); END"""
        )
        with self.assertRaisesRegex(StoragePaused, "paused"):
            self.store.advance("test")
        self.assertTrue(self.store.paused)
        self.assertEqual(self.store.inspect("test")["state_sha256"], before["state_sha256"])
        self.assertEqual(self.store.events("test"), events)
        self.assertEqual(len(self.store._fleet("test").pending), 1)
        with self.assertRaises(StoragePaused):
            self.store.submit("test", self.command("throttle", "set_throttle", 500))
        self.store.connection.execute("DROP TRIGGER fail_tick")
        with Store(self.db) as recovered:
            recovered.advance("test")
            self.assertEqual(
                sum(e["event_type"] == "command.applied" for e in recovered.events("test")), 1
            )

    def test_readonly_failure_is_visible_and_no_intent_is_saved(self) -> None:
        self.store.connection.execute("PRAGMA query_only=ON")
        with self.assertRaises(StoragePaused):
            self.store.submit("test", self.command("throttle", "set_throttle", 500))
        self.assertTrue(self.store.inspect("test")["paused"])
        self.assertEqual(len(self.store.events("test")), 1)

    def test_two_sessions_reload_committed_state(self) -> None:
        with Store(self.db) as second:
            a = self.store.submit("test", self.command("ignition", "set_ignition", True))
            b = second.submit("test", self.command("throttle", "set_throttle", 500))
            self.assertEqual(b["sequence"], a["sequence"] + 1)
            second.advance("test")
        state = self.store.inspect("test")["snapshot"]["states"][0]
        self.assertGreater(state["speed_mm_s"], 0)
        self.assertEqual(state["tick"], 1)

    def test_event_cursor_and_sequence(self) -> None:
        self.store.advance("test", 3)
        first = self.store.events("test", limit=2)
        rest = self.store.events("test", after=first[-1]["sequence"], limit=2)
        self.assertEqual([e["sequence"] for e in first + rest], [1, 2, 3, 4])
        with self.assertRaises(ValueError):
            self.store.events("test", limit=1001)

    def test_retention_never_prunes_active_run(self) -> None:
        with self.assertRaises(ValueError):
            self.store.prune("test")
        self.assertEqual(self.store.inspect("test")["snapshot"]["tick"], 0)
        self.store.stop("test")
        self.store.prune("test")
        for table in ("runs", "actions", "identities", "events", "snapshots"):
            self.assertEqual(
                self.store.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0
            )

    def test_stop_cancels_pending_commands(self) -> None:
        self.store.submit("test", self.command("throttle", "set_throttle", 700))
        self.store.stop("test")
        self.assertEqual(self.store._fleet("test").pending, ())
        result = self.store.submit("test", self.command("new", "set_throttle", 700))
        self.assertEqual(result["reason_code"], "run_stopped")
        with self.assertRaises(ValueError):
            self.store.advance("test")

    def test_limits_reject_before_mutation(self) -> None:
        before = self.store.events("test")
        with self.assertRaises(ValueError):
            self.store.submit("test", {"body": "x" * 4096})
        with self.assertRaises(ValueError):
            self.store.advance("test", 36001)
        self.assertEqual(before, self.store.events("test"))

    def test_schema_version_and_wal(self) -> None:
        self.assertEqual(self.store.connection.execute("PRAGMA user_version").fetchone()[0], 1)
        self.assertEqual(self.store.connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        db = Path(self.temp.name) / "future.sqlite"
        with sqlite3.connect(db) as connection:
            connection.execute("PRAGMA user_version=99")
        with self.assertRaisesRegex(ValueError, "unsupported"):
            Store(db)

    def test_existing_unversioned_database_is_rejected(self) -> None:
        db = Path(self.temp.name) / "other.sqlite"
        with sqlite3.connect(db) as connection:
            connection.execute("CREATE TABLE business (data TEXT)")
        with self.assertRaisesRegex(ValueError, "unversioned"):
            Store(db)

    def test_changed_run_provenance_is_rejected_before_resuming(self) -> None:
        self.store.connection.execute(
            "UPDATE runs SET provenance=? WHERE run_id='test'", (json.dumps({}),)
        )
        with self.assertRaisesRegex(ValueError, "provenance"):
            self.store.advance("test")
        self.assertEqual(
            self.store.connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 1
        )


if __name__ == "__main__":
    unittest.main()
