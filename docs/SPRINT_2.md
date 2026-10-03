# Sprint 2 — durable commands, evidence and domain replay

Implemented in 0.1.0.dev2. The physics model and Sprint 1 golden trace remain unchanged.
SQLite and JSON parsing use the Python standard library; no runtime dependency was added.

## Durability and lifecycle

SQLite schema v1 is created inside a migration transaction. The store rejects unknown schema
versions and unversioned databases with unrelated tables. WAL, foreign keys and FULL synchronous
mode are enabled. Tables store runs, per-tick snapshots, semantic command identities, ordered
replay actions and ordered events. Initial state and the latest complete checkpoint are retained.

Each coordinator mutation takes BEGIN IMMEDIATE, reloads the committed state and commits all of
that mutation's changes together. A tick's applied events, snapshot, action and current checkpoint
are atomic. Multiple Store sessions serialize through SQLite and do not reuse stale Fleet objects.
A multi-tick CLI request commits one tick at a time; if tick N fails, preceding committed ticks
remain and tick N is rolled back.

A failed SQLite write raises StoragePaused and blocks further mutations through that Store
instance. Inspect still shows the committed state and the local paused indicator. The pause flag
is session-local: if storage cannot be written, a durable pause event cannot be guaranteed. Fix
the storage problem and explicitly reopen the coordinator to recover from its last committed tick.
CLI failures exit with code 2 and a pause message.

Runtime, source-engine and dependency-lock fingerprints are saved when the run is created.
Resuming or replaying under a different fingerprint fails explicitly. Dependency-lock fingerprint
is packaged with the wheel and checked against uv.lock in CI. Git enforces LF text endings so
source hashes do not depend on checkout newline conversion.

## Command contract

S2 envelope fields: schema_version (1), run_id, command_id, vehicle_id, operation, value,
scheduled_tick (integer or null), origin (adapter and session_id). CLI assigns its own origin
even when a JSON input file supplies another one. Future network adapters must assign trusted
origin metadata before calling the internal Store API.

Operations currently implemented: set_ignition, set_throttle, set_brake. Fault injection is a
later profile extension. Observation time is assigned by the event writer, not a client field.

Idempotency key: run + vehicle + command ID. Fingerprint: operation, value, vehicle and requested
tick. Transport/session metadata is not part of command identity. A matching retry returns the
original acceptance/rejection receipt with duplicate=true, even after application or restart.
A different valid body under the same key returns id_conflict. Acceptance is an immutable receipt;
command.applied events separately prove execution.

Malformed or unsupported bounded envelopes are recorded as rejected attempts without state
mutation. Oversized/non-JSON payloads fail the ingress preflight before recording raw content.
Null schedule means the next tick; an explicit schedule must be in the future. Ordering is
scheduled tick followed by FIFO acceptance sequence.

Events include run/sequence/tick/state version, observation time, source adapter, nullable
command/vehicle/session fields and an empty correlation_edges list for future S5 enrichment.
Evidence linking by command ID exists; actor/canary correlation is not implemented yet.

## Replay bundles

Version 1 bundles contain a manifest, deterministic initial checkpoint, ordered submit/step/stop
actions, all expected per-tick hashes, final checkpoint and whole-bundle checksum. Accepted,
rejected, duplicate and conflicting attempts are reproduced by the same intent evaluator.
Normal replay uses no database and opens no network connections.

Validation checks exact schemas, bounded payloads, matching runtime/engine/lock/profile, initial
seed-derived state, every command disposition, every tick hash and final queued/lifecycle state.
Recomputing a checksum cannot hide a semantically inconsistent trace. Checksums establish
integrity relative to the supplied data; they are not signatures or proof of trusted authorship.

Import verifies the entire scenario before any mutation, then reconstructs the complete run in
one database transaction. A write failure rolls back the whole imported run. The bundle's run ID
is preserved; an existing run is never replaced. Imported observation timestamps are new replay
observations, not the original wall-clock capture times.

Export uses a consistent SQLite read transaction, verifies its own output and refuses to overwrite
an existing file. Bundles retain bounded input bodies; the committed fixture is entirely synthetic.
General capture redaction and public evidence presentation remain S5 work.

## Limits and retention

- 4096 bytes per input intent; 1000 recorded command attempts per run.
- 36000 ticks per run and 500000 total vehicle/tick transitions.
- 16 MiB per replay bundle; event reads use a cursor and a maximum page of 1000.
- No automatic deletion. Active runs cannot be pruned. The explicit Store.prune API only removes
  stopped runs, with foreign-key cascade; physical SQLite file compaction is separate.

These are scenario/work limits. This sprint does not claim a globally bounded disk footprint
across arbitrarily many runs; deployment quotas and time-based retention remain S6 work.

## Verification

59 tests cover all previous physics/CLI behavior plus recovery, identity scope, duplicate/conflict
handling, event pagination, two writer sessions, readonly and injected mid-tick failures, migration
guards, changed provenance, active-run retention, malformed imports, whole-import rollback,
recomputed-checksum attacks, stopped/pending lifecycle and end-to-end CLI workflows.

Twenty replays of the same 600-tick scenario agree on every normalized state hash and result,
including 21 received attempts, 18 applied commands and invalid/duplicate/conflicting inputs.
Ruff, strict mypy, packaged lock validation and a fresh installed-wheel workflow pass locally.
GitHub CI repeats these checks; its observed result is reported with the PR.

The committed [synthetic scenario](../scenarios/normal-drive-v1.json) has 18 applied commands and
600 ticks. Replay trace SHA-256:
`1fa7e2d747bacf4fa535e22c11833b6df0716014c957adcb916690e94c062c25`.
S2 hashes a list of per-tick state hashes; S1 hashes snapshot JSONL bytes, so these trace digests
have different definitions. The final physical state is identical.

## Next

S3 builds decoy HTTP and MQTT adapters on this coordinator, with real protocol acknowledgments,
shared versioned projections and separate analyst/decoy trust boundaries.
