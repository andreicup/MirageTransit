# MirageTransit

**Cyber-Physical Deception Platform for Transportation Systems**

MirageTransit is a transport security research lab where a simulated fleet, decoy web portal, MQTT surface and virtual vehicle signals share one authoritative state. Suspicious interactions become observable simulation events and reproducible regression scenarios.

**Status:** planning baseline. No runtime, honeypot or deployment is implemented yet. Repository inspected on 2026-10-02 UTC: empty, public, default branch `main`.

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

## Planned quick start

Future release commands will be documented only after they exist and pass CI. Start with S1 in the roadmap; do not treat this planning baseline as runnable software.
