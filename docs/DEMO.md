# Portfolio demonstration — 3–5 minutes

1. **0:00–0:30 — concept:** explain that a synthetic fleet's portal, MQTT and CAN share one
   authoritative state. Show the architecture and point out the private analyst boundary.
2. **0:30–1:10 — effect:** log into the console, start ignition/throttle and show gradual speed
   change and vehicle position. Open the decoy fleet portal and compare state-version labels.
3. **1:10–2:00 — breadcrumb:** open maintenance configuration; connect an MQTT client with those
   synthetic credentials. Subscribe to telemetry and acknowledgments; show the credential-reuse
   edge and its attribution limitation. These credentials are synthetic and scoped to this run.
4. **2:00–2:45 — consistency:** publish a QoS 1 braking command. Show transport PUBACK, accepted
   JSON receipt, and command.applied timeline. Retry the same ID; it applies once. Show retained
   command rejection. Run the portable CAN trace and inspect the synthetic DBC.
5. **2:45–3:30 — reproducibility:** export a sanitized scenario, upload it in replay studio and show
   per-tick/final-hash verification. Point to the automated tests and measured resource report.
6. **3:30–4:00 — limits:** demonstrate unauthenticated analyst denial, then explain local bindings,
   isolated synthetic model, MQTT subset and unverified Docker/vCAN deployment gates.

CV description (only after confirming the corresponding CI results):

> Built MirageTransit, a cyber-physical transportation deception lab with a deterministic fleet
> simulator, coherent HTTP/MQTT/CAN surfaces, durable SQLite events, cross-protocol breadcrumb
> correlation and per-tick verified replay. Implemented a private analyst console, isolated
> role capabilities, bounded ingress and reproducible multi-process acceptance tests.

Screenshots and the demo script do not substitute for a recorded/narrated demonstration.

A captioned real-browser recording can be generated with:

```bash
uv run --locked python scripts/record_demo.py runs/portfolio/miragetransit-demo.webm
```

The script runs an ephemeral four-process lab, opens a planted document, reuses its credential
in a real MQTT client, demonstrates the evidence edge, and exports/replays the scenario. It
records about three minutes; run controls and evidence are live, not mock data.
