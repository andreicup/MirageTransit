# Contracts baseline

S2 implemented the offline command/event and replay contracts. Exact current fields, ingress limits
and differences from these planned network interfaces are documented in [Sprint 2](SPRINT_2.md).

## State
State schema v1 has run_id, vehicle_id, tick, state_version, source_time_utc and:
speed_mm_s, distance_mm, route_offset_mm, heading_mdeg, throttle_permille, brake_permille, ignition (bool), fuel_ml, fault_flags.
Route projection additionally exposes latitude/longitude for display. The physics state uses integer units; presentation conversions never feed back into the model.

Initial model: speed updated from bounded drive acceleration, braking and drag, then clamped 0–45,000 mm/s. Distance uses an explicitly documented integer integration rule and residual accumulator. Engine-off prevents powered acceleration; braking always acts against motion; fuel never becomes negative. This is a pedagogical longitudinal model, not vehicle certification. Simulated ECU RPM is derived through documented synthetic ratios.

## Command envelope v1
```json
{
  "schema_version": 1,
  "command_id": "demo-command-001",
  "run_id": "demo-run-001",
  "vehicle_id": "MT-001",
  "operation": "set_throttle",
  "value": 350,
  "origin": {"adapter": "mqtt", "session_id": "session-001"},
  "observed_at_utc": "2026-10-02T23:21:00Z"
}
```
Origin metadata is assigned by the adapter, never trusted from the client payload.
Operations: set_throttle 0–1000; set_brake 0–1000; set_ignition boolean; inject_fault from a profile allowlist. Fault injection is lab-policy controlled. Reject missing IDs, unknown vehicles, invalid types, oversized payloads and unsupported operations.
Disposition: received, rejected, accepted, applied; reason_code and scheduled_tick are explicit.
Same command_id and same body returns previous result; same ID with different body is rejected.

## Event envelope
schema_version, event_id, run_id, sequence, tick, observed_at_utc, event_type, source_adapter, session_id, vehicle_id (nullable), command_id (nullable), state_version (nullable), payload, correlation_edges.
Event types: session.opened, artifact.read, canary.used, command.received/rejected/accepted/applied, state.updated, adapter.stale, run.paused, replay.completed.
Correlation edge has source_event_id, target_event_id, basis (token/session/command/shared_address), confidence and explanatory evidence. Address-only links are hypotheses. Do not combine all clients behind NAT into one attacker.

## Planned HTTP
Decoy: GET /fleet; GET /vehicles/{id}; GET /documents/{artifact}; POST /vehicles/{id}/commands.
Private analyst: POST /api/runs; GET /api/runs/{id}/state; GET /api/runs/{id}/events with cursor; POST /api/runs/{id}/pause; GET /api/runs/{id}/export; POST /api/replays.
Analyst stream: SSE with ordered event IDs and reconnect cursor.
Decoy reads use projections only. Analyst mutation endpoints require authenticated authorization and CSRF protection when cookie-based sessions are used.

## Planned MQTT
Topics: mt/{run}/fleet/{vehicle}/telemetry, mt/{run}/fleet/{vehicle}/command, mt/{run}/fleet/{vehicle}/ack.
Telemetry contains state_version and tick. Commands are non-retained; adapter rejects retained command delivery. Publish synthetic snapshots at 2 Hz; queue limits prevent telemetry from blocking commands.
Broker ACL scopes synthetic clients to their assigned run. Actual analyst control never travels on the decoy broker.

## CAN extension
Create a synthetic DBC with documented IDs, bit lengths, endianness, scales and signal ranges. Reserve separate IDs for telemetry and lab commands. DBC is generated for this project; it is not a Volkswagen/Golf or other OEM definition.
A CAN adapter projects authoritative snapshots and translates supported test frames into the same command envelope. Raw CAN frames carry no session identity; correlate by adapter run/trace context and label attribution limits.
Portable memory bus and Linux vCAN must have the same semantic contract. Real hardware remains disabled by default.

## Export
A versioned JSON bundle includes manifest, initial state, ordered input intents, events, normalized expected state hashes and checksums. Keep raw captures separate from sanitized public fixtures.
Import applies size/depth/event caps; no executable expressions, filesystem paths or external callback URLs. Invalid replay bundles fail before a run starts.

