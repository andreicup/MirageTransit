import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from miragetransit.cli import main


class CLITests(unittest.TestCase):
    def invoke(self, *arguments: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = main(list(arguments))
        return result, out.getvalue(), err.getvalue()

    def test_start_step_inspect_stop_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state = str(Path(folder) / "run.json")
            result, out, _ = self.invoke("start", "--state", state)
            self.assertEqual(result, 0)
            self.assertEqual(json.loads(out)["snapshot"]["tick"], 0)
            result, out, _ = self.invoke(
                "step",
                "--state",
                state,
                "--ticks",
                "10",
                "--vehicle",
                "MT-001",
                "--ignition",
                "on",
                "--throttle",
                "700",
            )
            self.assertEqual(result, 0)
            self.assertGreater(json.loads(out)["snapshot"]["states"][0]["speed_mm_s"], 0)
            unchanged = Path(state).read_bytes()
            result, _, _ = self.invoke("inspect", "--state", state)
            self.assertEqual(result, 0)
            self.assertEqual(Path(state).read_bytes(), unchanged)
            result, out, _ = self.invoke("stop", "--state", state)
            self.assertEqual(result, 0)
            self.assertFalse(json.loads(out)["snapshot"]["running"])
            result, _, err = self.invoke("step", "--state", state)
            self.assertEqual(result, 2)
            self.assertIn("stopped", err)

    def test_invalid_command_does_not_rewrite_file(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state = str(Path(folder) / "run.json")
            self.invoke("start", "--state", state)
            original = Path(state).read_bytes()
            cases = [
                ("--throttle", "100"),
                ("--vehicle", "missing", "--throttle", "100"),
                ("--vehicle", "MT-001", "--throttle", "1001"),
                ("--ticks", "0"),
            ]
            for case in cases:
                result, _, _ = self.invoke("step", "--state", state, *case)
                self.assertEqual(result, 2)
                self.assertEqual(Path(state).read_bytes(), original)

    def test_start_does_not_overwrite_existing_run(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state = str(Path(folder) / "run.json")
            self.invoke("start", "--state", state)
            original = Path(state).read_bytes()
            result, _, err = self.invoke("start", "--state", state)
            self.assertEqual(result, 2)
            self.assertIn("already exists", err)
            self.assertEqual(Path(state).read_bytes(), original)

    def test_demo_trace_is_hashable_and_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            trace = Path(folder) / "trace.jsonl"
            result, out, _ = self.invoke("demo", "--trace", str(trace))
            self.assertEqual(result, 0)
            data = trace.read_bytes()
            self.assertEqual(len(data.splitlines()), 601)
            self.assertEqual(hashlib.sha256(data).hexdigest(), json.loads(out)["trace_sha256"])
            result, _, _ = self.invoke("demo", "--trace", str(trace))
            self.assertEqual(result, 2)
            self.assertEqual(trace.read_bytes(), data)

    def test_profile_errors_are_user_facing(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder) / "bad.json"
            profile.write_text('{"profile_id": "bad"}')
            result, _, err = self.invoke(
                "start", "--state", str(Path(folder) / "state.json"), "--profile", str(profile)
            )
            self.assertEqual(result, 2)
            self.assertIn("profile", err)

    def test_missing_state_is_user_facing(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            result, _, err = self.invoke("inspect", "--state", str(Path(folder) / "missing"))
            self.assertEqual(result, 2)
            self.assertIn("error:", err)


if __name__ == "__main__":
    unittest.main()
