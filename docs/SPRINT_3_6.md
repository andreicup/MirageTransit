# Integrated local lab — S3–S6 implementation

## Implemented

- S3: one SQLite-owner coordinator; separate portal, MQTT and analyst processes; narrow role
  capabilities; versioned authoritative projections; run-specific signed-session breadcrumbs;
  MQTT 3.1.1 subset with ACLs, retained-command rejection, transport/application acknowledgment
  separation and command deduplication. [Stack decision](adr-003-lightweight-services.md).
- S4: portable bounded memory bus, synthetic [DBC](../schemas/miragetransit.dbc), command
  translation into the same durable envelopes, golden-frame tests, explicit vCAN-only socket
  adapter and a trace/bridge CLI. Speed, throttle, brake and ignition encode exactly; fuel floors
  to 400 ml (error less than 400 ml). IDs 0x100–0x102 telemetry, 0x200–0x202 command; DLC 8.
  Nonce becomes the durable CAN command ID; attribution is trace context, not a person.
- S5: private login with 15-minute sessions, HTTP-only/SameSite cookies, per-session CSRF,
  bounded login attempts, overview/vehicle control, cursor-based timeline and reconnecting SSE,
  cross-protocol credential-reuse graph, sanitized scenario download and per-tick replay.
- S6: supervisor quick start, clean installed wheel, five-container local Compose definition,
  role config generator, quotas/health checks, scripted demonstration, Linux measurements and
  browser checks. Release gates below are tracked separately from implementation.

## Run

```bash
uv sync --locked
uv run --locked miragetransit lab-init --directory runs/lab
uv run --locked miragetransit lab --directory runs/lab
```

Open portal http://127.0.0.1:8761 and analyst http://127.0.0.1:8762.
The generated console password is the `password` field in `runs/lab/analyst.json`; do not
commit the `runs` directory. Ctrl+C terminates all four processes. Restart resumes committed
state; stopping a run through the console freezes it permanently. Start a fresh directory
for a new experiment. Ports can be changed with `lab-init --base-port`.

Open the portal's maintenance document, use its synthetic credentials in an MQTT 3.1.1
client on port 8763, and subscribe to `mt/local-lab/fleet/+/telemetry` and
`mt/local-lab/fleet/+/ack`. Publish a non-retained command to
`mt/local-lab/fleet/MT-001/command`:

```json
{"command_id":"drive-001","operation":"set_ignition","value":true}
```

Then set throttle with a different ID. The graph links the document's HTTP session to the
MQTT session through the exact run-specific credential. It makes no person-identity claim.

Memory/CAN trace while the lab runs:

```bash
uv run --locked python scripts/can_bridge.py --output runs/can-trace.jsonl
```

Optional native vCAN: create a `vcan0` in an isolated network namespace outside application
containers, then use `--interface vcan0`. Physical `can0` is rejected. Electrical behavior,
real ECU compatibility and arbitration are not modeled. No native vCAN success is claimed
from this execution environment.

## Docker host workflow

Use a recent Docker Compose version supporting per-network `gw_priority`.

For a rootless Linux user, set `LOCAL_UID=$(id -u)` and `LOCAL_GID=$(id -g)` as shell variables,
export them, then run:

```bash
uv run --locked python deploy/prepare.py --uid "$LOCAL_UID" --gid "$LOCAL_GID"
docker compose up --build --wait
```

UID/GID must be nonzero. When preparing as root, the default owner is 1000:1000. Only core mounts
`runs/container/data`; each adapter sees only its role configuration. Core has no published
port. Portal and MQTT share an internal decoy network, while analyst uses a separate internal
network. All host bindings are 127.0.0.1. A separate fixed-target TCP ingress relay publishes those ports
on its own access bridge; its listeners bind only that bridge address. Core and adapters stay
on internal networks without external routes. The relay has no credentials or database mounts,
and cannot choose targets from request data. Decoy-to-relay analyst access is tested as denied.
No host networking or privileged application container.

Cleanup: `docker compose down` removes containers/networks and preserves the experiment database.
After exporting evidence, delete only the intended stopped experiment directory if you want
permanent removal. Per-run budgets are bounded; total disk space across unlimited experiments
is not globally quota-managed. The base image patch and multi-platform manifest digest are pinned.

## Verification and remaining gates

Local checks: 79 domain/CLI/protocol/transport tests pass; Ruff, strict mypy, lock fingerprint,
clean installed wheel with live services, and desktop/mobile browser acceptance pass.
See [machine-readable acceptance results](../benchmarks/acceptance.json).

The domain/protocol acceptance suite covers real four-process HTTP/MQTT/CAN interactions,
malformed/oversized inputs, retained rejection, run/topic ACLs, negative capability access,
CSRF, exact frozen-version HTTP/MQTT equality, tick progress under concurrent RPC requests,
stream ordering/reconnect, evidence edges, no address-only attribution and offline replay.

`npm ci`, then `npx playwright install chromium`, then `npm run test:browser` exercises real
login, controls, export/upload replay, logout and 390px/1440px layouts. Browser tooling is a
development-only dependency. No network is required by the running pages.

[Local measurement](../benchmarks/local-linux.json) records runtime environment, CPU, RSS sum,
RPC latency, tick rate, DB+WAL growth, six applied commands and twenty equal replay checks.
Numbers are observed on this container, not a server/hardware guarantee.

Docker build/runtime and negative reachability were verified in
[CI run 37242166020](https://github.com/andreicup/MirageTransit/actions/runs/37242166020): all services
healthy, loopback access, tick progress, non-root mounts, decoy/analyst separation, no external
default route from the decoy, relay-to-analyst bypass denied, and export replay all pass.
The code was integrated through [PR #3](https://github.com/andreicup/MirageTransit/pull/3).
A captioned 182-second real-browser walkthrough was recorded; its recorder is committed.

Native vCAN in a dedicated namespace and physical hardware are still unverified. The portable
CAN path is verified. A final release tag has not been created. S7–S11 remain separate
extensions (SSH, adaptive policy, railway, optional AI, bench hardware); no runtime claim is
made for those stages.
