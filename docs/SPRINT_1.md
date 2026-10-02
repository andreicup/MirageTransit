# Sprint 1 — deterministic fleet core

Implemented: immutable validated State/Command/Profile types, closed synthetic route,
three-vehicle fleet, fixed 100 ms tick, FIFO command scheduling, bounded queue, CLI,
local JSON checkpoints, streaming trace hashes, tests, dependency lock and CI.

The simulation runs faster than wall time. This sprint is an offline core; it opens no
ports and requires no hardware, GPU, broker, CAN interface or external runtime dependency.
Dependencies for installation and development are fetched once; simulation itself works offline.

## Model

All dynamics use integer arithmetic. Throttle and brake use permille:

- Drive acceleration: 3000 × throttle / 1000 mm/s², only with ignition and fuel.
- Brake deceleration: 8000 × brake / 1000 mm/s².
- Drag while moving: 100 + speed / 100 mm/s².
- Speed integrates acceleration at 100 ms and clamps to 0–45000 mm/s.
- Distance integrates the mean of old/new speed over that tick.
- Fuel consumption with engine on: 1 + floor(9 × throttle / 1000) ml/s.

Divisions retain residuals for speed, distance and fuel. Speed residual resets at the
limits; fuel residual resets on exhaustion. Empty fuel turns ignition off after that tick.
Braking and drag still work without ignition.

The 4 km closed route has authoritative synthetic distances, integer coordinate interpolation
and predefined cardinal headings. Coordinates are illustrative; the route is not an actual
road and its turns have instantaneous heading changes. No tire, gear, lateral dynamics,
crash behavior, OEM ECU or fuel accuracy is modeled.

The seed controls small initial-fuel variations using sorted vehicle IDs. Trace hashes cover
model version, timestep, profile hash, seed, lifecycle status and every normalized snapshot.
The model has no wall-clock timestamps. The demo contains the initial snapshot plus 600 ticks.

## CLI lifecycle

See the README for commands. A local run is explicit: start creates a file; step advances it;
inspect reads it; stop freezes it and discards future commands. Stop is a simulation lifecycle
action, not a command to brake moving vehicles.

Use one process at a time per checkpoint. Writes use a temporary file, fsync and atomic
replacement; this is a convenience checkpoint, not a concurrent or transactional event store.
S2 adds the SQLite event store, command identity/deduplication, migrations and replay bundles.
Do not share editable checkpoints as trusted forensic evidence.

## Verification

Tested locally on Linux x86_64, CPython 3.12.14, uv 0.12.19:

- 28 unittest tests: physics properties, 3000 generated control steps, invalid input,
  queue capacity, ordering, route wrap, CLI lifecycle and checkpoint continuation.
- 20 identical 60-second demo runs; separate subprocesses with three Python hash seeds.
- Ruff lint/format and strict mypy source checks.
- pip-audit checked all six locked development packages plus setuptools 84.0.0 and uv 0.12.19 on 2026-10-02 UTC: no known vulnerabilities reported. This is a point-in-time advisory check, not a security guarantee.
- sdist/wheel build; fresh virtual environment outside checkout validates bundled profile
  and module entrypoint against the golden trace.

Golden trace SHA-256 (seed 42, 60 s):
`598421389befd84e873ad11306c68f53f8afd519cd3cb77beff90e61bf213b09`

| Vehicle | Final distance | Final speed | Final fuel |
| --- | --- | --- | --- |
| MT-001 | 952558 mm | 0 mm/s | 39728 ml |
| MT-002 | 1090527 mm | 0 mm/s | 39769 ml |
| MT-003 | 1212947 mm | 0 mm/s | 39744 ml |

GitHub CI runs the same checks on Ubuntu 24.04. Its observed outcome is recorded in the
pull request, separately from local verification. Full resource budgets, protocol lag,
containment and vCAN validation belong to later sprints.

## Next

S2: persist ordered command dispositions and per-tick snapshots atomically in SQLite,
then export/import versioned scenarios and prove replay from recorded inputs.
