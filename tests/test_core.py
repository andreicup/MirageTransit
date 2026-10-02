import json
import random
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path

from miragetransit import checkpoint
from miragetransit.core import Fleet, step
from miragetransit.demo import demo, schedule_normal_drive
from miragetransit.models import MAX_SPEED_MM_S, Command, State
from miragetransit.profile import load_profile, profile_from_dict, profile_to_dict


class DynamicsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = load_profile()

    def test_throttle_accelerates_gradually(self) -> None:
        initial = State("MT-001", ignition=True, throttle_permille=1000)
        following = step(initial, self.profile)
        self.assertEqual(following.speed_mm_s, 300)
        self.assertEqual(following.distance_mm, 15)
        self.assertEqual(initial.speed_mm_s, 0)

    def test_braking_stops_and_never_reverses(self) -> None:
        state = State("MT-001", speed_mm_s=20_000, brake_permille=1000)
        previous_distance = state.distance_mm
        for _ in range(100):
            previous_speed = state.speed_mm_s
            state = step(state, self.profile)
            self.assertLessEqual(state.speed_mm_s, previous_speed)
            self.assertGreaterEqual(state.distance_mm, previous_distance)
            previous_distance = state.distance_mm
        self.assertEqual(state.speed_mm_s, 0)

    def test_engine_off_cannot_accelerate(self) -> None:
        state = State("MT-001", throttle_permille=1000)
        for _ in range(100):
            state = step(state, self.profile)
        self.assertEqual(state.speed_mm_s, 0)
        self.assertEqual(state.fuel_ml, 40_000)

    def test_empty_tank_disables_engine(self) -> None:
        state = State("MT-001", ignition=True, throttle_permille=1000, fuel_ml=1)
        state = step(state, self.profile)
        self.assertEqual(state.fuel_ml, 0)
        self.assertFalse(state.ignition)
        for _ in range(100):
            state = step(state, self.profile)
        self.assertEqual(state.speed_mm_s, 0)

    def test_fractional_fuel_survives_ticks(self) -> None:
        state = State("MT-001", ignition=True)
        for _ in range(9):
            state = step(state, self.profile)
        self.assertEqual(state.fuel_ml, 40_000)
        self.assertEqual(step(state, self.profile).fuel_ml, 39_999)

    def test_speed_cap_and_residuals(self) -> None:
        state = State("MT-001", speed_mm_s=MAX_SPEED_MM_S, ignition=True, throttle_permille=1000)
        self.assertEqual(step(state, self.profile).speed_mm_s, MAX_SPEED_MM_S)
        self.assertEqual(step(state, self.profile).speed_remainder, 0)

    def test_small_speed_deceleration_does_not_stick(self) -> None:
        state = State("MT-001", speed_mm_s=1)
        self.assertEqual(step(state, self.profile).speed_mm_s, 0)

    def test_generated_drive_invariants(self) -> None:
        generator = random.Random(9)
        state = State("MT-001", fuel_ml=20)
        for _ in range(3000):
            previous_distance = state.distance_mm
            state = replace(
                state,
                ignition=bool(generator.getrandbits(1)),
                throttle_permille=generator.randrange(1001),
                brake_permille=generator.randrange(1001),
            )
            state = step(state, self.profile)
            self.assertTrue(0 <= state.speed_mm_s <= MAX_SPEED_MM_S)
            self.assertGreaterEqual(state.distance_mm, previous_distance)
            self.assertGreaterEqual(state.fuel_ml, 0)
            self.assertLess(state.route_offset_mm, self.profile.length_mm)

    def test_route_corners_and_wrap(self) -> None:
        self.assertEqual(self.profile.project(0), self.profile.project(self.profile.length_mm))
        self.assertEqual(self.profile.project(1_000_000)[3], 0)
        self.assertEqual(self.profile.project(2_000_000)[3], 270_000)


class FleetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = load_profile()
        self.fleet = Fleet(self.profile)

    def test_future_commands_and_fifo(self) -> None:
        self.fleet.submit(Command("MT-001", "set_ignition", True), 3)
        self.fleet.submit(Command("MT-001", "set_throttle", 100), 3)
        self.fleet.submit(Command("MT-001", "set_throttle", 800), 3)
        self.fleet.advance(2)
        self.assertEqual(self.fleet.states[0].speed_mm_s, 0)
        self.fleet.advance()
        self.assertEqual(self.fleet.states[0].throttle_permille, 800)
        self.assertEqual(self.fleet.states[0].speed_mm_s, 240)
        self.assertEqual(self.fleet.pending, ())

    def test_invalid_submission_has_no_mutation(self) -> None:
        before = self.fleet.state_hash()
        with self.assertRaises(ValueError):
            self.fleet.submit(Command("missing", "set_throttle", 1000))
        with self.assertRaises(ValueError):
            self.fleet.submit(Command("MT-001", "set_brake", 10), 0)
        self.assertEqual(self.fleet.state_hash(), before)
        self.assertFalse(self.fleet.pending)

    def test_stop_freezes_and_discards_pending_inputs(self) -> None:
        self.fleet.submit(Command("MT-001", "set_throttle", 500))
        self.fleet.stop()
        before = self.fleet.state_hash()
        with self.assertRaises(ValueError):
            self.fleet.advance()
        with self.assertRaises(ValueError):
            self.fleet.submit(Command("MT-001", "set_throttle", 500))
        self.assertEqual(self.fleet.state_hash(), before)
        self.assertFalse(self.fleet.pending)

    def test_seeds_and_profile_order(self) -> None:
        reordered = replace(self.profile, vehicle_ids=tuple(reversed(self.profile.vehicle_ids)))
        original = Fleet(self.profile, 123)
        other = Fleet(reordered, 123)
        self.assertEqual(original.states, other.states)
        self.assertNotEqual(original.states, Fleet(self.profile, 124).states)

    def test_snapshots_are_detached(self) -> None:
        snapshot = self.fleet.snapshot()
        snapshot["states"][0]["speed_mm_s"] = 99999
        self.assertEqual(self.fleet.states[0].speed_mm_s, 0)

    def test_invalid_types_and_bounds(self) -> None:
        for value in (True, -1, 1001, 0.5, "500"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Command("MT-001", "set_throttle", value)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            Command("MT-001", "set_ignition", 1)
        with self.assertRaises(ValueError):
            self.fleet.advance(True)

    def test_command_queue_is_bounded(self) -> None:
        for _ in range(10_000):
            self.fleet.submit(Command("MT-001", "set_throttle", 100))
        with self.assertRaises(ValueError):
            self.fleet.submit(Command("MT-001", "set_throttle", 100))

    def test_twenty_sixty_second_runs_match(self) -> None:
        hashes = {demo()["trace_sha256"] for _ in range(20)}
        self.assertEqual(len(hashes), 1)
        self.assertEqual(
            hashes,
            {"598421389befd84e873ad11306c68f53f8afd519cd3cb77beff90e61bf213b09"},
        )
        final = demo()["final_snapshot"]
        self.assertEqual(final["tick"], 600)
        self.assertEqual(len(final["states"]), 3)
        for state in final["states"]:
            self.assertGreater(state["distance_mm"], 0)
            self.assertEqual(state["speed_mm_s"], 0)
            self.assertFalse(state["ignition"])

    def test_invalid_profile(self) -> None:
        original = profile_to_dict(self.profile)
        for kind in ("duplicate_vehicle", "decreasing_offset", "extra_field", "open_route"):
            data = json.loads(json.dumps(original))
            if kind == "duplicate_vehicle":
                data["vehicle_ids"][1] = data["vehicle_ids"][0]
            elif kind == "decreasing_offset":
                data["route"][1]["offset_mm"] = 0
            elif kind == "extra_field":
                data["url"] = "https://example.com"
            else:
                data["route"][-1]["latitude_e7"] += 1
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                profile_from_dict(data)


class CheckpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "state.json"
        self.fleet = Fleet(load_profile(), 123)
        schedule_normal_drive(self.fleet)
        self.fleet.advance(230)
        checkpoint.save(self.fleet, self.path)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_restore_continuation_matches_uninterrupted(self) -> None:
        restored = checkpoint.load(self.path)
        self.assertEqual(restored.state_hash(), self.fleet.state_hash())
        self.assertEqual(restored.pending, self.fleet.pending)
        self.fleet.advance(370)
        restored.advance(370)
        self.assertEqual(restored.state_hash(), self.fleet.state_hash())
        self.assertEqual(
            [asdict(s) for s in restored.states], [asdict(s) for s in self.fleet.states]
        )

    def test_reject_malformed_checkpoint(self) -> None:
        original = json.loads(self.path.read_text())
        for kind in ("tick", "projection", "missing_vehicle", "model", "sequence", "past_command"):
            data = json.loads(json.dumps(original))
            if kind == "tick":
                data["snapshot"]["states"][0]["tick"] = 0
            elif kind == "projection":
                data["snapshot"]["states"][0]["latitude_e7"] = 0
            elif kind == "missing_vehicle":
                data["snapshot"]["states"].pop()
            elif kind == "model":
                data["snapshot"]["model_version"] = "unknown"
            elif kind == "sequence":
                data["next_sequence"] = 1
            else:
                data["queue"][0]["tick"] = 1
            self.path.write_text(json.dumps(data))
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                checkpoint.load(self.path)

    def test_stopped_run_round_trip(self) -> None:
        self.fleet.stop()
        checkpoint.save(self.fleet, self.path)
        restored = checkpoint.load(self.path)
        self.assertFalse(restored.running)
        self.assertEqual(restored.pending, ())


if __name__ == "__main__":
    unittest.main()
