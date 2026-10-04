# MirageTransit · reviewer guide

[Back to README](../README.md)

A transport security research lab built around one deterministic fleet state and verifiable command/event replay.

## Current delivery

**0.1.0.dev6 · integrated transport deception lab**  
**Stack:** Python · SQLite · HTTP/MQTT · Synthetic CAN · Verified replay

Local acceptance records 77 tests, desktop/mobile browser checks and twenty equal replay checks. Ruff, strict typing, lock provenance, packaging and installed-wheel live startup checks pass. HTTP/MQTT/CAN projections share the core state; the private console correlates planted credential reuse.

## Inspect the engineering

- [Fixed-step fleet core](../src/miragetransit/core.py): deterministic vehicle evolution and one authoritative state.
- [SQLite store](../src/miragetransit/storage.py) and [storage tests](../tests/test_storage.py): transactions, recovery and command identity.
- [Replay verifier](../src/miragetransit/replay.py) and [replay tests](../tests/test_replay.py): every tick, receipt and provenance check.
- [Committed scenario](../scenarios/normal-drive-v1.json): synthetic 600-tick regression bundle.

## Reproduce a short demonstration

Start with the README quick start. Run the committed replay scenario, then capture/export/import a SQLite journal demo. The replay checks every tick and command result without contacting external systems.

## Verification checkpoint

Portfolio presentation audited on **5 October 2026 (Europe/Bucharest)** against source commit [`9b3b22c`](https://github.com/andreicup/MirageTransit/commit/9b3b22c65647dd9665d67cd79d58f7ae34cd0454).

Latest observed successful source [CI run](https://github.com/andreicup/MirageTransit/actions/runs/37128169776): `9b3b22c`. This is a dated checkpoint; the [Actions page](https://github.com/andreicup/MirageTransit/actions) is the authority for later changes.

## Remaining acceptance gates

HTTP/MQTT, portable CAN, analyst console and local deployment tooling are implemented. Docker runtime validation is tracked in CI; native vCAN and physical hardware remain separate gates. S7–S11 remain extensions. See [S3–S6](SPRINT_3_6.md) and [acceptance](../benchmarks/acceptance.json).

See [the detailed verification record](../docs/SPRINT_2.md) for test methods and limits. A passed build or synthetic fixture does not close physical or model-quality gates.
