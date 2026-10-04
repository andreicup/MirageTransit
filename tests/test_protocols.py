import concurrent.futures
import json
import socket
import time
import unittest

from lab_support import Lab

from miragetransit.can import Frame, command_frame, decode, ingest, telemetry
from miragetransit.mqtt import packet, read_field, receive, text_field
from miragetransit.replay import verify
from miragetransit.rpc import Client


class ProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.lab = Lab()
        cls.lab.login()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.lab.close()

    def client(self, analyst=False):
        config = self.lab.configs["analyst" if analyst else "decoy"]
        return Client(config["core_url"], config["key"])

    def mqtt_connect(self, credentials=None, wrong_run=False):
        if credentials is None:
            _, document = self.lab.request("decoy", "/documents/maintenance")
            credentials = document["credentials"]
        sock = socket.create_connection(("127.0.0.1", self.lab.base + 3), timeout=3)
        sock.settimeout(3)
        username = credentials["username"] if not wrong_run else "other:c-one"
        data = (
            b"\x00\x04MQTT\x04\xc2\x00\x1e"
            + text_field("test-client")
            + text_field(username)
            + text_field(credentials["password"])
        )
        sock.sendall(packet(0x10, data))
        header, result = receive(sock)
        self.assertEqual(header, 0x20)
        return sock, result

    def subscribe(self, sock, topic):
        sock.sendall(packet(0x82, b"\x00\x01" + text_field(topic) + b"\x00"))
        header, data = receive(sock)
        self.assertEqual(header, 0x90)
        return data[-1]

    def read_publish(self, sock):
        for _ in range(10):
            header, data = receive(sock)
            if header >> 4 == 3:
                topic, pos = read_field(data)
                return topic, json.loads(data[pos:])
        self.fail("no MQTT publication")

    def command(self, command_id, operation, value):
        return {"command_id": command_id, "operation": operation, "value": value}

    def test_http_command_then_mqtt_has_coherent_applied_state(self):
        sock, result = self.mqtt_connect()
        self.addCleanup(sock.close)
        self.assertEqual(result, b"\x00\x00")
        self.assertEqual(self.subscribe(sock, "mt/test-lab/fleet/MT-001/telemetry"), 0)
        status, receipt = self.lab.request(
            "decoy", "/vehicles/MT-001/commands", self.command("http-on", "set_ignition", True)
        )
        self.assertEqual(status, 202)
        self.assertFalse(receipt["duplicate"])
        self.lab.request(
            "decoy", "/vehicles/MT-001/commands", self.command("http-throttle", "set_throttle", 700)
        )
        for _ in range(10):
            _, telemetry = self.read_publish(sock)
            if (
                telemetry["vehicle"]["ignition"]
                and telemetry["vehicle"]["throttle_permille"] == 700
            ):
                break
        else:
            self.fail("HTTP input not reflected on MQTT")
        self.assertEqual(telemetry["vehicle"]["state_version"], telemetry["state_version"])
        events = self.client(True).call("events", limit=1000)
        applied = [
            e
            for e in events
            if e["event_type"] == "command.applied" and e["command_id"] == "http-throttle"
        ]
        self.assertEqual(len(applied), 1)
        accepted = [
            e
            for e in events
            if e["event_type"] == "command.accepted" and e["command_id"] == "http-throttle"
        ]
        self.assertEqual(accepted[0]["source_adapter"], "http")

    def test_mqtt_qos1_and_application_dedup(self):
        sock, result = self.mqtt_connect()
        self.addCleanup(sock.close)
        self.assertEqual(result, b"\x00\x00")
        self.subscribe(sock, "mt/test-lab/fleet/MT-002/ack")
        body = json.dumps(self.command("mqtt-brake", "set_brake", 600)).encode()
        data = text_field("mt/test-lab/fleet/MT-002/command") + b"\x00\x02" + body
        for header in (0x32, 0x3A):
            sock.sendall(packet(header, data))
            self.assertEqual(receive(sock), (0x40, b"\x00\x02"))
            topic, receipt = self.read_publish(sock)
            self.assertTrue(topic.endswith("/ack"))
            self.assertEqual(receipt["status"], "accepted")
            self.assertEqual(receipt["duplicate"], header == 0x3A)

    def test_retained_commands_rejected_without_intent(self):
        sock, result = self.mqtt_connect()
        self.addCleanup(sock.close)
        self.assertEqual(result, b"\x00\x00")
        self.subscribe(sock, "mt/test-lab/fleet/MT-003/ack")
        sock.sendall(
            packet(
                0x31,
                text_field("mt/test-lab/fleet/MT-003/command")
                + json.dumps(self.command("retained", "set_throttle", 900)).encode(),
            )
        )
        _, receipt = self.read_publish(sock)
        self.assertEqual(receipt["reason_code"], "retained_command")
        events = self.client(True).call("events", limit=1000)
        self.assertFalse(any(e.get("command_id") == "retained" for e in events))

    def test_mqtt_auth_and_topic_acl(self):
        sock, result = self.mqtt_connect({"username": "test-lab:c-one", "password": "wrong"})
        sock.close()
        self.assertEqual(result, b"\x00\x05")
        sock, result = self.mqtt_connect(wrong_run=True)
        sock.close()
        self.assertEqual(result, b"\x00\x05")
        sock, result = self.mqtt_connect()
        self.addCleanup(sock.close)
        self.assertEqual(result, b"\x00\x00")
        self.assertEqual(self.subscribe(sock, "mt/other/fleet/+/telemetry"), 0x80)
        self.assertEqual(self.subscribe(sock, "#"), 0x80)

    def test_decoy_capability_cannot_read_analyst_evidence_or_stop(self):
        for operation in ("events", "export", "evidence", "stop"):
            with self.assertRaisesRegex(ValueError, "capability denied"):
                self.client().call(operation)
        status, _ = self.lab.request("decoy", "/api/state")
        self.assertEqual(status, 404)
        config = self.lab.configs["decoy"]
        outsider = Client(config["core_url"], "wrong-key")
        with self.assertRaisesRegex(ValueError, "unauthorized"):
            outsider.call("state")

    def test_analyst_auth_csrf_and_sanitized_replay(self):
        import urllib.error
        import urllib.request

        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(f"http://127.0.0.1:{self.lab.base + 2}/api/state")
        self.assertEqual(error.exception.code, 401)
        error.exception.close()
        status, _ = self.lab.request(
            "analyst",
            "/api/commands",
            {"vehicle_id": "MT-003", **self.command("bad-csrf", "set_brake", 1000)},
        )
        self.assertEqual(status, 403)
        status, bundle = self.lab.request("analyst", "/api/export")
        self.assertEqual(status, 200)
        self.assertTrue(verify(bundle)["verified"])
        for action in bundle["actions"]:
            if action["kind"] == "submit":
                self.assertEqual(action["body"]["origin"]["session_id"], "sanitized-session")
        self.assertNotIn(self.lab.configs["decoy"]["key"], json.dumps(bundle))
        status, replay = self.lab.request(
            "analyst", "/api/replay", bundle, {"X-CSRF-Token": self.lab.csrf}
        )
        self.assertEqual(status, 200)
        self.assertTrue(replay["verified"])

    def test_canary_reuse_correlates_sessions_after_many_ticks(self):
        _, document = self.lab.request("decoy", "/documents/maintenance")
        sock, result = self.mqtt_connect(document["credentials"])
        self.addCleanup(sock.close)
        self.assertEqual(result, b"\x00\x00")
        status, evidence = self.lab.request("analyst", "/api/graph")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(evidence["edges"]), 1)
        edge = evidence["edges"][-1]
        self.assertEqual(edge["basis"], "token")
        self.assertNotEqual(edge["source_session"], edge["target_session"])
        self.assertNotIn(document["credentials"]["password"], json.dumps(evidence))

    def test_can_matches_authoritative_state_and_shared_intent(self):
        client = self.client()
        projection = client.call("state")
        ids = [s["vehicle_id"] for s in projection["snapshot"]["states"]]
        receipt = ingest(client, command_frame(2, "set_brake", 400, 123), ids)
        self.assertEqual(receipt["status"], "accepted")
        time.sleep(0.2)
        projection = client.call("state")
        for index, state in enumerate(projection["snapshot"]["states"]):
            decoded = decode(telemetry(state, index))
            for signal in ("speed_mm_s", "throttle_permille", "brake_permille", "ignition"):
                self.assertEqual(decoded[signal], state[signal])
            self.assertLess(state["fuel_ml"] - decoded["fuel_ml"], 400)
        with self.assertRaises(ValueError):
            ingest(client, Frame(0x555, b"\x00" * 8), ids)

    def test_malformed_oversized_network_input_and_flood_do_not_stop_ticks(self):
        before = self.client().call("state")["snapshot"]["tick"]
        sock = socket.create_connection(("127.0.0.1", self.lab.base + 3), timeout=3)
        sock.sendall(b"\x10\xff\xff\xff\x7f")
        self.assertEqual(sock.recv(1), b"")
        sock.close()

        def read(_):
            try:
                return self.client().call("state")["snapshot"]["tick"]
            except (ValueError, OSError):
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(read, range(100)))
        self.assertTrue(any(r is not None for r in results))
        time.sleep(0.2)
        self.assertGreater(self.client().call("state")["snapshot"]["tick"], before)
        status, _ = self.lab.request("decoy", "/vehicles/MT-001/commands", {"x": "a" * 5000})
        self.assertEqual(status, 400)
        status, response = self.lab.request(
            "decoy",
            "/vehicles/MT-001/commands",
            {**self.command("forged-origin", "set_brake", 0), "origin": {"adapter": "analyst"}},
        )
        self.assertEqual(status, 400)
        self.assertIn("error", response)

    def test_stream_order_and_reconnect_cursor(self):
        status, data = self.lab.request("analyst", "/api/stream?after=0&limit=10")
        self.assertEqual(status, 200)
        ids = [int(line[4:]) for line in data.decode().splitlines() if line.startswith("id: ")]
        self.assertEqual(ids, sorted(set(ids)))
        self.assertEqual(len(ids), 10)
        status, next_data = self.lab.request(
            "analyst", "/api/stream?after=0", headers={"Last-Event-ID": str(ids[-1])}
        )
        self.assertEqual(status, 200)
        following = [
            int(line[4:]) for line in next_data.decode().splitlines() if line.startswith("id: ")
        ]
        self.assertTrue(all(i > ids[-1] for i in following))
        status, response = self.lab.request("analyst", "/api/events?limit=1001")
        self.assertEqual(status, 400)
        self.assertIn("error", response)

    def test_z_stop_keeps_http_and_mqtt_exactly_coherent(self):
        status, _ = self.lab.request("analyst", "/api/stop", {}, {"X-CSRF-Token": self.lab.csrf})
        self.assertEqual(status, 200)
        sock, result = self.mqtt_connect()
        self.addCleanup(sock.close)
        self.assertEqual(result, b"\x00\x00")
        self.subscribe(sock, "mt/test-lab/fleet/MT-001/telemetry")
        _, mqtt = self.read_publish(sock)
        status, http = self.lab.request("decoy", "/vehicles/MT-001")
        self.assertEqual(status, 200)
        self.assertEqual(http["state_version"], mqtt["state_version"])
        self.assertEqual(http["vehicle"], mqtt["vehicle"])
        self.assertFalse(http["stale"])
        _, receipt = self.lab.request(
            "decoy", "/vehicles/MT-001/commands", self.command("after-stop", "set_throttle", 1000)
        )
        self.assertEqual(receipt["reason_code"], "run_stopped")


if __name__ == "__main__":
    unittest.main()
