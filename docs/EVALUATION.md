# Evaluation and portfolio evidence

## Questions
H1: Does shared state reduce cross-surface contradictions relative to independent static decoys?
H2: Can recorded command sequences reproduce normalized physical traces?
H3: Can canary breadcrumbs reconstruct a controlled interaction chain without overstating identity?
Attacker realism/engagement cannot be established from scripted clients alone. A future ethical study would need a separate protocol and adequate observations.

## Reproducible experiment
Use identical synthetic profiles and ten fixed scripted sessions for both baseline and coherent system. Baseline mode serves independent static projections while retaining the same request routes and logging. Scripts cover reads, throttle/brake, invalid commands, duplicates, stale adapters and reconnects.
Run each condition five times, save exact code/runtime/profile hashes, inputs and outputs. Report samples and distributions, not just averages. Control scheduled input ticks; report live timing separately.

| Metric | Definition | Initial release target |
| --- | --- | --- |
| State consistency | Mismatches among projections at same source version | 0 for supported fields |
| Replay equivalence | Matching normalized per-tick state hashes | 20/20 identical domain replays |
| Invalid command handling | Invalid fixture produces rejection without mutation | 100% of documented fixtures |
| Canary link accuracy | Expected token-linked edges vs graph output | Exact match on controlled ground truth |
| Tick timing | p50/p95/p99 wall duration and missed deadlines | p95 below 100 ms at specified load |
| Projection lag | Time from committed snapshot to adapter observation | p95 below 500 ms locally |
| Capture integrity | Expected accepted intents vs persisted events | No silent loss |
| Memory/disk | Peak RSS and growth for 30-minute three-vehicle run | Under 2 GiB RAM; within retention cap |

Targets are proposed acceptance thresholds, not measured results. Record hardware, background load, payload sizes and sampling method. If a target fails, publish actual results and fix or revise scope transparently.

## Required failure cases
Duplicate command, conflicting ID, wrong vehicle, out-of-range throttle, oversized JSON, out-of-order arrival, broker restart, retained command, full queue, database write failure, stale projection, unauthorized analyst action, invalid replay, and injected text rendered in console.
Physics properties: bounded speed/fuel, monotonic traveled distance, brake decreases moving speed under defined inputs, engine-off prevents drive acceleration, deterministic transition for identical state/input.

## Demo script (3–5 minutes)
Show clean setup and three vehicles; read the decoy fleet document; follow its synthetic MQTT breadcrumb with a controlled client; change throttle; inspect the resulting state and CAN projection if available; open correlated timeline; export and replay; show exact trace comparison and one invalid input rejection.
End with measured resource use and explicit model limitations. Separate live footage from prerecorded fixtures.

## Release artifacts
README quick start that works from fresh checkout; tagged code; architecture and threat model; automated test report; benchmark JSON/CSV and analysis; synthetic scenario bundle with checksums; screenshots and video; short technical retrospective explaining design tradeoffs and unresolved limitations.

## CV description template after implementation
“Built MirageTransit, a containerized transport deception lab integrating a deterministic fleet simulator, HTTP/MQTT decoys and [validated CAN adapter], with correlated evidence and reproducible scenario replay; demonstrated [measured consistency], [measured replay results] and [measured resource use].”
Fill brackets from release evidence only. Until then, describe as “designing/developing”, not completed. Do not claim an unprecedented invention without a literature/related-work review.

## Related-work task
Before research claims, compare primary documentation and papers for transport honeypots, cyber-physical deception, digital twins and CAN testbeds. Record which elements are reused, the specific integration contribution and gaps. This baseline has verified platform documentation, not a complete novelty survey.
