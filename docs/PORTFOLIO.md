# MirageTransit · reviewer guide

[Back to README](../README.md)

A transport security research lab built around one deterministic fleet state and verifiable command/event replay.

## Current delivery

**0.1.0.dev2 · deterministic core and replay delivered**  
**Stack:** Python · SQLite · uv · Typed contracts

The Sprint 2 report records 59 tests and 20 matching 600-tick replays. CI passes lint, strict typing, lock provenance, test execution, packaging and installed-wheel checks.

## Inspect the engineering

- [Fixed-step fleet core](../src/miragetransit/core.py): deterministic vehicle evolution and one authoritative state.
- [SQLite store](../src/miragetransit/storage.py) and [storage tests](../tests/test_storage.py): transactions, recovery and command identity.
- [Replay verifier](../src/miragetransit/replay.py) and [replay tests](../tests/test_replay.py): every tick, receipt and provenance check.
- [Committed scenario](../scenarios/normal-drive-v1.json): synthetic 600-tick regression bundle.

## Reproduce a short demonstration

Start with the README quick start. Run the committed replay scenario, then capture/export/import a SQLite journal demo. The replay checks every tick and command result without contacting external systems.

## Verification checkpoint

Portfolio presentation audited on **5 October 2026 (Europe/Bucharest)** against source commit [`9b3b22c`](https://github.com/zCooperHD/MirageTransit/commit/9b3b22c65647dd9665d67cd79d58f7ae34cd0454).

Latest observed successful source [CI run](https://github.com/zCooperHD/MirageTransit/actions/runs/37128169776): `9b3b22c`. This is a dated checkpoint; the [Actions page](https://github.com/zCooperHD/MirageTransit/actions) is the authority for later changes.

## Remaining acceptance gates

HTTP/MQTT decoys, analyst console, CAN adapters and contained deployment remain later milestones.

See [the detailed verification record](../docs/SPRINT_2.md) for test methods and limits. A passed build or synthetic fixture does not close physical or model-quality gates.
