# Product definition

## Problem and intended audience
Disconnected honeypot surfaces can tell contradictory stories: a portal reports a parked vehicle while MQTT reports motion, or a command has no observable consequence. MirageTransit will investigate whether shared transport state makes decoy interactions more coherent and more useful for analysis.

Users: a transport-security student, a homelab researcher, and an interviewer reviewing a reproducible engineering demonstration.

## Core demonstration
1. Boot a synthetic fleet and a scripted normal drive.
2. A controlled lab client opens the decoy maintenance portal and retrieves a planted fleet document.
3. The document contains a synthetic MQTT breadcrumb unique to this run.
4. The client submits a bounded throttle command for vehicle MT-001.
5. The coordinator validates it, records its disposition, and changes the simulated vehicle gradually.
6. Portal telemetry, MQTT and virtual CAN reflect the same state version; analyst view links the events.
7. Export the session into a sanitized replay scenario.
8. Re-run the scenario offline and compare the normalized state trace.

The breadcrumb proves that the same token was used; IP proximity alone does not prove an actor identity. A decoy credential is never valid on the analyst interface.

## Release v0.1 scope
- One automotive fleet profile, three synthetic vehicles, one route represented by a local polyline.
- Speed, distance, position, heading, throttle, brake, ignition, fuel and simple fault flags.
- HTTP fleet/maintenance decoy and restricted MQTT command/telemetry surface.
- Bounded dynamics with explicit units and modeled limitations.
- Timeline, state inspection, run controls, correlation evidence and JSON export.
- Canaries in decoy documents/topics; explicit provenance for correlation.
- Deterministic local replay and a CI regression suite.
- Container packaging, localhost bindings, resource measurements and retention caps.

No remote code execution is needed to create the deception. Decoy shell commands, if added later, will be interpreted by an emulator.

## Subsequent releases
v0.2: Linux vCAN, synthetic DBC, gateway mappings and duplicate/out-of-order command scenarios.
v0.3: SSH emulator, scenario-driven adaptive responses and evidence graph.
v0.4: second transport profile (railway simulation), after automotive release and benchmark gates.
v0.5: optional CAN hardware-in-the-loop, after a documented bench-only electrical design.
Research extensions: offline AI-generated fleet stories and analyst summaries, constrained by schemas and verified against state.

The vCAN adapter may land in v0.1 if S4 completes, but it is not required to run the portable demonstration. v0.1 and v0.2 must be clearly distinguished in release notes.

## Product screens
Private analyst console: overview with run health; vehicle details with live state; interaction timeline with filters; correlation graph with confidence labels; scenario import/export and replay comparison; settings for profiles and retention.
Decoy portal: believable fleet overview, maintenance detail, synthetic documents and MQTT integration instructions. Its appearance and credentials are separate from the analyst console.

## Cost and workload
Software-first baseline: 0 RON of additional purchases on existing homelab. Electricity and optional later hosting are not free. No GPU or live LLM dependency.
Initial planning target: 2 CPU cores, 2 GiB RAM budget, capped 1 GiB run storage; measure on the actual server before claiming compatibility.
Estimated solo effort to v0.1: 70–110 focused hours, subject to protocol and packaging results. Scope reduction order: graph polish, optional vCAN, SSH, AI; preserve consistency and replay.

## Portfolio positioning
Demonstrate Linux networking, transport telemetry, state modeling, protocol adapters, security boundaries, automated testing and empirical evaluation. Describe this as a research prototype; do not claim production vehicle compatibility, ECU fidelity, certified safety or proven superiority.
