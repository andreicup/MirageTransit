import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from miragetransit.cli import main


class JournalCLITests(unittest.TestCase):
    def invoke(self, *arguments: str) -> tuple[int, dict[str, object], str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(arguments))
        return code, json.loads(out.getvalue()) if out.getvalue() else {}, err.getvalue()

    def test_demo_export_replay_and_import_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db, bundle, imported = (
                root / "demo.sqlite",
                root / "scenario.json",
                root / "import.sqlite",
            )
            code, _, err = self.invoke("journal-demo", "--db", str(db), "--run", "demo")
            self.assertEqual(code, 0, err)
            code, _, err = self.invoke(
                "run-export", "--db", str(db), "--run", "demo", "--output", str(bundle)
            )
            self.assertEqual(code, 0, err)
            code, replay, err = self.invoke("replay", "--input", str(bundle))
            self.assertEqual(code, 0, err)
            self.assertTrue(replay["verified"])
            code, restored, err = self.invoke(
                "run-import", "--db", str(imported), "--input", str(bundle)
            )
            self.assertEqual(code, 0, err)
            self.assertEqual(restored, replay)

    def test_command_retry_across_cli_invocations(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db = str(Path(folder) / "run.sqlite")
            self.invoke("run-start", "--db", db, "--run", "test")
            command = (
                "run-command",
                "--db",
                db,
                "--run",
                "test",
                "--command-id",
                "one",
                "--vehicle",
                "MT-001",
                "--operation",
                "set_throttle",
                "--value",
                "700",
            )
            code, first, _ = self.invoke(*command)
            self.assertEqual(code, 0)
            self.invoke("run-step", "--db", db, "--run", "test")
            code, duplicate, _ = self.invoke(*command)
            self.assertEqual(code, 0)
            self.assertEqual(first["sequence"], duplicate["sequence"])
            self.assertTrue(duplicate["duplicate"])
            code, events, _ = self.invoke("run-events", "--db", db, "--run", "test")
            self.assertEqual(code, 0)
            self.assertIn("events", events)

    def test_rejection_exit_code_and_recorded_reason(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db = str(Path(folder) / "run.sqlite")
            self.invoke("run-start", "--db", db, "--run", "test")
            code, result, _ = self.invoke(
                "run-command",
                "--db",
                db,
                "--run",
                "test",
                "--command-id",
                "bad",
                "--vehicle",
                "MT-001",
                "--operation",
                "set_throttle",
                "--value",
                "1001",
            )
            self.assertEqual(code, 2)
            self.assertEqual(result["reason_code"], "invalid_command")

    def test_invalid_import_does_not_create_database(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bad = root / "bad.json"
            bad.write_text('{"bundle_version": 1}')
            db = root / "new.sqlite"
            code, _, err = self.invoke("run-import", "--db", str(db), "--input", str(bad))
            self.assertEqual(code, 2)
            self.assertIn("bundle", err)
            self.assertFalse(db.exists())

    def test_cli_replaces_untrusted_origin(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db = str(root / "run.sqlite")
            self.invoke("run-start", "--db", db, "--run", "test")
            body = root / "command.json"
            body.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "run_id": "test",
                        "command_id": "one",
                        "vehicle_id": "MT-001",
                        "operation": "set_throttle",
                        "value": 700,
                        "scheduled_tick": None,
                        "origin": {"adapter": "spoofed", "session_id": "spoofed"},
                    }
                )
            )
            code, _, _ = self.invoke(
                "run-command", "--db", db, "--run", "test", "--input", str(body)
            )
            self.assertEqual(code, 0)
            _, result, _ = self.invoke("run-events", "--db", db, "--run", "test")
            received = next(
                event for event in result["events"] if event["event_type"] == "command.received"
            )
            self.assertEqual(
                received["payload"]["body"]["origin"], {"adapter": "cli", "session_id": "local"}
            )


if __name__ == "__main__":
    unittest.main()
