import json
import tempfile
import unittest
from pathlib import Path

from miragetransit.core import Fleet
from miragetransit.demo import schedule_normal_drive
from miragetransit.intents import envelope
from miragetransit.profile import load_profile
from miragetransit.replay import checksum, export_bundle, import_bundle, load_bundle, verify
from miragetransit.storage import Store


class ReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.temp.name)
        with Store(cls.folder / "original.sqlite") as store:
            fleet = Fleet(load_profile())
            schedule_normal_drive(fleet)
            store.create("demo", fleet.profile)
            for item in fleet.pending:
                store.submit(
                    "demo",
                    envelope(
                        "demo",
                        f"command-{item.sequence}",
                        item.command.vehicle_id,
                        item.command.operation,
                        item.command.value,
                        item.tick,
                    ),
                )
            # Include accepted retries, invalid commands and ID conflicts in the replay fixture.
            store.submit("demo", envelope("demo", "command-1", "MT-001", "set_ignition", True, 1))
            store.submit("demo", {"invalid": "input"})
            store.submit("demo", envelope("demo", "command-1", "MT-001", "set_ignition", False, 1))
            store.advance("demo", 600)
            export_bundle(store, "demo", cls.folder / "bundle.json")
        cls.bundle = load_bundle(cls.folder / "bundle.json")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def copy(self) -> dict[str, object]:
        return json.loads(json.dumps(self.bundle))

    def test_twenty_replays_have_identical_per_tick_and_final_hashes(self) -> None:
        outputs = [verify(self.bundle) for _ in range(20)]
        self.assertTrue(all(result == outputs[0] for result in outputs))
        self.assertEqual(outputs[0]["ticks"], 600)
        self.assertEqual(outputs[0]["commands_applied"], 18)
        self.assertEqual(outputs[0]["commands_received"], 21)

    def test_import_is_atomic_and_reexport_matches(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            with Store(Path(folder) / "import.sqlite") as store:
                result = import_bundle(store, self.bundle)
                self.assertTrue(result["verified"])
                export_bundle(store, "demo", Path(folder) / "export.json")
                exported = load_bundle(Path(folder) / "export.json")
                self.assertEqual(exported, self.bundle)
                with self.assertRaisesRegex(ValueError, "already exists"):
                    import_bundle(store, self.bundle)

    def test_checksum_tampering_is_rejected(self) -> None:
        data = self.copy()
        data["checksum_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "checksum"):
            verify(data)

    def test_recomputed_checksum_cannot_hide_semantic_divergence(self) -> None:
        for kind in ("hash", "receipt", "initial", "final", "runtime", "engine", "action"):
            data = json.loads(json.dumps(self.bundle))
            if kind == "hash":
                data["expected_hashes"][10] = "0" * 64
            elif kind == "receipt":
                data["actions"][0]["receipt"]["sequence"] = 999
            elif kind == "initial":
                data["initial"]["snapshot"]["states"][0]["fuel_ml"] -= 1
            elif kind == "final":
                data["final"]["next_sequence"] += 1
            elif kind in ("runtime", "engine"):
                data["manifest"]["runtime" if kind == "runtime" else "engine_sha256"] = "unknown"
            else:
                data["actions"][0]["callback_url"] = "https://example.com"
            data["checksum_sha256"] = checksum(data)
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                verify(data)

    def test_malformed_import_changes_no_database_records(self) -> None:
        data = json.loads(json.dumps(self.bundle))
        data["actions"][0]["receipt"]["status"] = "rejected"
        data["checksum_sha256"] = checksum(data)
        with tempfile.TemporaryDirectory() as folder:
            with Store(Path(folder) / "import.sqlite") as store:
                with self.assertRaises(ValueError):
                    import_bundle(store, data)
                self.assertEqual(
                    store.connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 0
                )

    def test_failed_import_rolls_back_entire_run(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            with Store(Path(folder) / "import.sqlite") as store:
                store.connection.execute(
                    """CREATE TRIGGER fail_import BEFORE INSERT ON snapshots WHEN NEW.tick=3
                       BEGIN SELECT RAISE(ABORT,'injected import failure'); END"""
                )
                with self.assertRaises(RuntimeError):
                    import_bundle(store, self.bundle)
                for table in ("runs", "snapshots", "actions", "events", "identities"):
                    self.assertEqual(
                        store.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0
                    )

    def test_bundle_size_limit(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "large.json"
            path.write_bytes(b"x" * (16 * 1024 * 1024 + 1))
            with self.assertRaisesRegex(ValueError, "16 MiB"):
                load_bundle(path)

    def test_stopped_run_and_future_queue_replay(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with Store(root / "run.sqlite") as store:
                store.create("stop", load_profile())
                store.submit("stop", envelope("stop", "later", "MT-001", "set_throttle", 700, 200))
                store.advance("stop", 3)
                store.stop("stop")
                store.submit("stop", envelope("stop", "rejected", "MT-001", "set_throttle", 700))
                export_bundle(store, "stop", root / "bundle.json")
            result = verify(load_bundle(root / "bundle.json"))
            self.assertEqual(result["commands_applied"], 0)
            self.assertEqual(result["ticks"], 3)

    def test_export_never_overwrites_a_bundle(self) -> None:
        path = self.folder / "bundle.json"
        old = path.read_bytes()
        with Store(self.folder / "original.sqlite") as store:
            with self.assertRaises(FileExistsError):
                export_bundle(store, "demo", path)
        self.assertEqual(path.read_bytes(), old)

    def test_committed_synthetic_fixture_is_replayable(self) -> None:
        result = verify(load_bundle(Path("scenarios/normal-drive-v1.json")))
        self.assertEqual(result["ticks"], 600)
        self.assertEqual(result["commands_applied"], 18)
        self.assertEqual(
            result["trace_sha256"],
            "1fa7e2d747bacf4fa535e22c11833b6df0716014c957adcb916690e94c062c25",
        )


if __name__ == "__main__":
    unittest.main()
