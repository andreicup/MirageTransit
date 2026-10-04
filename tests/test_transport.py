import json
import tempfile
import unittest
from pathlib import Path

from miragetransit.can import Frame, MemoryBus, VCanBus, command_frame, decode, telemetry
from miragetransit.evidence import graph
from miragetransit.models import State
from miragetransit.mqtt import packet, read_field, text_field
from miragetransit.profile import load_profile
from miragetransit.service import initialize
from miragetransit.storage import Store


class TransportTests(unittest.TestCase):
    def test_can_golden_frame_and_quantization(self):
        from dataclasses import asdict

        frame = telemetry(
            asdict(
                State(
                    "MT-001",
                    speed_mm_s=12345,
                    throttle_permille=700,
                    brake_permille=300,
                    ignition=True,
                    fuel_ml=40099,
                )
            ),
            0,
        )
        self.assertEqual(frame.arbitration_id, 0x100)
        self.assertEqual(frame.data.hex(), "3930bc022c010164")
        self.assertEqual(decode(frame)["fuel_ml"], 40000)
        self.assertEqual(command_frame(0, "set_brake", 1000, 42).data.hex(), "02e8032a00000000")

    def test_invalid_can_frames_and_memory_backpressure(self):
        for can_id, data in ((0x800, b"\x00" * 8), (1, b"\x00" * 7), (True, b"\x00" * 8)):
            with self.assertRaises(ValueError):
                Frame(can_id, data)
        with self.assertRaises(ValueError):
            decode(Frame(0x100, b"\xff" * 8))
        with self.assertRaises(ValueError):
            VCanBus("can0")
        bus = MemoryBus(1)
        frame = Frame(0x100, b"\x00" * 8)
        bus.send(frame)
        with self.assertRaises(ValueError):
            bus.send(frame)
        self.assertEqual(bus.receive(), frame)
        self.assertIsNone(bus.receive())

    def test_mqtt_golden_packets_and_utf8_validation(self):
        self.assertEqual(packet(0xC0).hex(), "c000")
        self.assertEqual(packet(0x20, b"\x00\x00").hex(), "20020000")
        self.assertEqual(text_field("MQTT"), b"\x00\x04MQTT")
        self.assertEqual(read_field(text_field("MT-001")), ("MT-001", 8))
        for data in (b"\x00\x03x", b"\x00\x01\xff", b"\x00\x01\x00"):
            with self.assertRaises((ValueError, UnicodeError)):
                read_field(data)

    def test_observations_do_not_mutate_state_or_replay_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            with Store(Path(directory) / "test.sqlite") as store:
                store.create("test", load_profile())
                before = store.inspect("test")
                event = store.observe(
                    "test", "artifact.read", "http", "s-one", {"token_sha256": "a"}
                )
                used = store.observe("test", "canary.used", "mqtt", "s-two", {"token_sha256": "a"})
                self.assertEqual(store.inspect("test"), before)
                self.assertEqual(event["source_adapter"], "http")
                self.assertEqual(graph([event, used])["edges"][0]["confidence"], "high")
                self.assertEqual(
                    store.connection.execute("SELECT COUNT(*) FROM actions").fetchone()[0], 0
                )
                with self.assertRaises(ValueError):
                    store.observe("test", "command.applied", "http", "s-one", {})
                with self.assertRaises(ValueError):
                    store.observe("test", "artifact.read", "http", "s-one", {"text": "a" * 5000})

    def test_graph_requires_actual_issued_token_not_shared_address(self):
        events = [
            {
                "event_id": "one",
                "session_id": "s-one",
                "source_adapter": "http",
                "event_type": "session.opened",
                "payload": {"address": "same"},
            },
            {
                "event_id": "two",
                "session_id": "s-two",
                "source_adapter": "mqtt",
                "event_type": "canary.used",
                "payload": {"address": "same", "token_sha256": "unissued"},
            },
        ]
        self.assertEqual(graph(events)["edges"], [])

    def test_failed_coordinator_does_not_accept_unapplied_commands(self):
        from miragetransit.rpc import Coordinator
        from miragetransit.storage import StoragePaused

        with tempfile.TemporaryDirectory() as directory:
            with Store(Path(directory) / "lab.sqlite") as store:
                store.create("test", load_profile())
                owner = Coordinator(store, "test", "decoy", "analyst")
                owner.failure = "work budget reached"
                with self.assertRaises(StoragePaused):
                    owner.dispatch(
                        "decoy",
                        {
                            "operation": "command",
                            "adapter": "mqtt",
                            "session": "s-one",
                            "body": {
                                "command_id": "after-failure",
                                "vehicle_id": "MT-001",
                                "operation": "set_throttle",
                                "value": 1000,
                            },
                        },
                    )
                self.assertEqual(
                    store.connection.execute("SELECT COUNT(*) FROM actions").fetchone()[0], 0
                )

    def test_configuration_role_separation_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            initialize(path)
            decoy = json.loads((path / "decoy.json").read_bytes())
            self.assertNotIn("analyst_key", decoy)
            self.assertNotIn("db", decoy)
            self.assertNotIn("password", decoy)
            self.assertEqual((path / "core.json").stat().st_mode & 0o777, 0o600)
            with self.assertRaisesRegex(ValueError, "already configured"):
                initialize(path)


if __name__ == "__main__":
    unittest.main()
