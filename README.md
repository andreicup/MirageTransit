# MirageTransit

**Cyber-Physical Deception Platform for Transportation Systems**

MirageTransit is a transport security research lab where a simulated fleet, decoy web portal, MQTT surface and virtual vehicle signals share one authoritative state. Suspicious interactions become observable simulation events and reproducible regression scenarios.

**Status:** Sprint 1 implemented: deterministic fleet core and local CLI. HTTP/MQTT decoys, analyst console, CAN adapters and deployment are planned in later sprints. See [Sprint 1 results and limitations](docs/SPRINT_1.md).

## First release

A synthetic three-vehicle fleet; bounded vehicle dynamics; decoy HTTP and MQTT interfaces; correlated event timeline; canary breadcrumbs; deterministic scenario replay; private analyst console; local Docker deployment. Everything runs without purchasing hardware.

The engineering contribution is cross-protocol consistency and reproducible cyber-to-physical traces. Novelty or improved attacker engagement is a hypothesis to evaluate, not an established result.

## Read the plan

- [Product and scope](docs/PRODUCT.md)
- [Architecture and decisions](docs/ARCHITECTURE.md)
- [Data and protocol contracts](docs/CONTRACTS.md)
- [Implementation roadmap](docs/ROADMAP.md)
- [Containment and threat model](docs/THREAT_MODEL.md)
- [Evaluation and portfolio demonstration](docs/EVALUATION.md)

Documentation is in English so reviewers can inspect the project directly. All sample organizations, vehicles and credentials must be synthetic. No license has been selected; public visibility does not itself grant an open-source license.

## Quick start — Sprint 1

Requires Python 3.12 (validated on 3.12.14) and uv 0.12.19. No hardware or GPU needed.

```bash
git clone https://github.com/zCooperHD/MirageTransit.git
cd MirageTransit
python -m pip install uv==0.12.19
uv sync --locked
uv run --locked miragetransit demo --seconds 60
```

The demo advances 60 seconds of simulation time without waiting a minute. It drives three
vehicles, applies braking, and returns the final state and normalized trace SHA-256.

```bash
uv run --locked miragetransit start --state runs/local.json --seed 42
uv run --locked miragetransit step --state runs/local.json --ticks 100 --vehicle MT-001 --ignition on --throttle 700
uv run --locked miragetransit inspect --state runs/local.json
uv run --locked miragetransit step --state runs/local.json --ticks 100 --vehicle MT-001 --throttle 0 --brake 1000
uv run --locked miragetransit stop --state runs/local.json
```

State files are explicit local checkpoints. Use one writer per file. Stop freezes the run;
it does not simulate braking. A stopped run rejects further commands. Choose a new file to start again.

Optional trace: `uv run --locked miragetransit demo --trace runs/demo.jsonl` (601 snapshots).
Existing state and trace files are never silently overwritten by start/demo.
Custom profiles: `start --profile path/to/profile.json --state runs/custom.json`.
Profile fields and synthetic dynamics are documented in [Sprint 1](docs/SPRINT_1.md).

## Development

```bash
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy src
uv run --locked python -m unittest discover -s tests -v
uv build
uv run --locked python scripts/check_wheel.py
```

Runtime uses only the standard library. The lockfile fixes development dependencies;
the build backend and CI actions are pinned. Initial installation needs package access.
No public honeypot exposure or real vehicle connection is part of this sprint.

