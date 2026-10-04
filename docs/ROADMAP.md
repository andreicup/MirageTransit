# Implementation roadmap

## Workflow
S0–S2 are complete. S3–S5 local implementations and S6 packaging/demo tooling are implemented;
see [verification and remaining release gates](SPRINT_3_6.md). Docker runtime, native vCAN,
the recorded portfolio video remain explicit verification/release gates.
No `v0.1.0` release is claimed yet. S7–S11 remain extensions. Each implementation ends with
tested code, updated run instructions and a reviewable commit/PR.

| Stage | Focus | Estimate | Depends on |
| --- | --- | --- | --- |
| S0 | Product, contracts, threat model, evaluation | This baseline | Repository |
| S1 | Deterministic core and runnable CLI | 12–18 h | S0 |
| S2 | Persistence, command/event contracts, replay | 12–18 h | S1 |
| S3 | Decoy HTTP + MQTT and process isolation | 16–24 h | S2 |
| S4 | Portable CAN adapter and optional vCAN | 8–14 h | S3 |
| S5 | Analyst console and evidence correlation | 14–22 h | S3 |
| S6 | Packaging, benchmarks, demo and release | 8–14 h | S4 portable path + S5 |

S1–S6 total estimate is 70–110 hours. These are estimates, not completion promises. Railway, SSH, AI and physical hardware are outside this budget.

## S1: make the simulation real
- Set up package, dependency lock, lint/type checks and CI; choose exact supported versions.
- Implement profile validation, units, fixed tick, state transitions and in-memory command queue.
- Three vehicles, local route fixtures and deterministic normal-drive script.
- CLI commands to start, step, inspect and stop a local run.
Acceptance: fresh checkout runs a 60-second simulation; throttle changes speed gradually; brake stops it; engine-off disables drive; no negative fuel or speed; repeated seeded runs produce identical normalized traces. No network or GPU required.

## S2: make it observable and reproducible
- SQLite schema/migrations with atomic events + snapshots.
- Command validation, deduplication, ordered tick scheduling and failure policy.
- Versioned JSON export/import and offline domain replay.
Acceptance: same bundle replayed 20 times has identical state hashes; duplicate command applies once; malformed import is rejected; restart restores committed state; forced write failure visibly pauses the run. Retention never deletes active-run records unexpectedly.

## S3: make deception coherent
- Decoy fleet portal, documents and synthetic run-specific MQTT breadcrumbs.
- Broker ACLs and bounded MQTT adapter; telemetry, command acknowledgments and version tags.
- Separate analyst and decoy routes, processes, credentials and network boundaries.
Acceptance: portal + MQTT snapshots agree at matching versions; a lab-issued command produces accepted/applied events and visible state change; retained commands are rejected; oversized/flood inputs cannot starve tick loop; decoy credentials cannot access analyst API. Complete negative reachability checks before any exposure.

## S4: make transport integration inspectable
- Synthetic DBC, memory bus adapter, encode/decode boundary tests.
- Optional Linux vCAN profile, isolated network namespace, trace export.
Acceptance: decoded telemetry matches authoritative snapshot within stated signal quantization; supported injected frames follow policy; invalid DLC/unknown IDs are logged/rejected; base demo runs without kernel privileges.
Optional vCAN gate: frame round trip on native Linux, no host networking/privileged application containers. If unavailable in CI, mark integration job skipped and attach a separate verified Linux result.

## S5: make evidence useful
- Private analyst login and authorization; console overview, vehicle view and ordered timeline.
- Canary correlation with confidence/evidence; inspectable session graph.
- Replay compare and sanitized export; pagination and stream reconnect.
Acceptance: full demo works in browser; correlation links the planted token; address-only evidence remains uncertain; decoy artifacts cannot inject scripts into analyst view; unauthorized control attempts fail; export can be replayed offline.

## S6: make it a portfolio release
- Compose deployment with explicit local bindings, health checks, quotas and cleanup.
- Measure CPU/RAM/disk, tick jitter, protocol lag, event loss and replay consistency.
- Clean checkout setup test; CI artifact containing sample run, checksums and results.
- 3–5 minute demo video, architecture diagram, limitations and CV-ready description.
Acceptance: one documented command starts local demo after dependencies are installed; scripted scenario completes; all critical tests pass; measured resource report is published; no secrets or raw sensitive captures enter public artifacts; tag v0.1.0.
Tag v0.2 only after native vCAN validation and documented CAN adapter limitations.

## Backlog after first release
S7: restricted SSH emulator and additional breadcrumbs.
S8: rule-based adaptation with logged policy version, bounded response templates and baseline comparisons.
S9: railway profile with explicitly synthetic signaling and state machines; no operational railway interface.
S10: optional offline AI profile generation/summary; schema and consistency checks, human-readable provenance, baseline without AI.
S11: bench-only ESP32/CAN integration and optional OBiCAN import, validated separately.

## Stop/reduce criteria
If runtime exceeds target, measure before adding services. If replay diverges, freeze new features and repair ordering/units. If isolation checks fail, keep localhost-only and block deployment. If cross-surface behavior is contradictory, prioritize projection/version handling over visual polish.

## Next verification task
Execute the local Compose deployment on a Docker-enabled Linux host, verify negative
reachability from decoy to analyst, capture the portfolio video.
Native vCAN verification remains a separate optional transport gate. The local four-process
lab, portable CAN and offline replay work without those external runtime capabilities.
