# MirageTransit · reviewer guide

[Back to README](../README.md)

A transport security research lab built around one deterministic fleet state and verifiable command/event replay.

## Current delivery

**0.1.0.dev6 · integrated transport deception lab**  
**Stack:** Python · SQLite · HTTP/MQTT · Synthetic CAN · Verified replay

Local acceptance records 79 tests, desktop/mobile browser checks and twenty equal replay checks. Ruff, strict typing, lock provenance, packaging and installed-wheel live startup checks pass. HTTP/MQTT/CAN projections share the core state; the private console correlates planted credential reuse.

## Inspect the engineering

- [Fixed-step fleet core](../src/miragetransit/core.py): deterministic vehicle evolution and one authoritative state.
- [SQLite store](../src/miragetransit/storage.py) and [storage tests](../tests/test_storage.py): transactions, recovery and command identity.
- [Replay verifier](../src/miragetransit/replay.py) and [replay tests](../tests/test_replay.py): every tick, receipt and provenance check.
- [Committed scenario](../scenarios/normal-drive-v1.json): synthetic 600-tick regression bundle.

## Reproduce a short demonstration

Start with the README quick start. Run the committed replay scenario, then capture/export/import a SQLite journal demo. The replay checks every tick and command result without contacting external systems.

## Verification checkpoint

Implementation verified on **5 October 2026 (Europe/Bucharest)** against source commit
[`50615de`](https://github.com/andreicup/MirageTransit/commit/50615de2a7e2bf5d5a7b68551737f1613a253952)
and integrated through [PR #3](https://github.com/andreicup/MirageTransit/pull/3).

[CI run 37242166020](https://github.com/andreicup/MirageTransit/actions/runs/37242166020) passes
core/package checks, 79 tests, desktop/mobile browser acceptance and Docker runtime/isolation.
This is a dated checkpoint; [Actions](https://github.com/andreicup/MirageTransit/actions) remains
the authority for later changes.

## Remaining acceptance gates

HTTP/MQTT, portable CAN, analyst console and local deployment tooling are implemented. Docker runtime and isolation are verified in CI; native vCAN and physical hardware remain separate gates. S7–S11 remain extensions. See [S3–S6](SPRINT_3_6.md) and [acceptance](../benchmarks/acceptance.json).

See [the detailed verification record](../docs/SPRINT_2.md) for test methods and limits. A passed build or synthetic fixture does not close physical or model-quality gates.
