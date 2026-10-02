# Threat model and containment

## Assets and trust boundaries
Protect the host/homelab, analyst session, evidence integrity, run reproducibility and repository secrets. Treat all decoy requests, MQTT messages, artifacts and imported scenarios as untrusted.
The initial lab uses controlled clients and localhost bindings. Public attacker collection is a separate deployment decision and is not authorized or implemented by this planning baseline.

| Boundary | Main failure | Required control and test |
| --- | --- | --- |
| Decoy to host | Shell execution, filesystem escape, SSRF | No shell/subprocess execution from inputs; no arbitrary URL fetch; bounded parser; malformed input fixtures |
| Decoy to analyst | Credential reuse or network pivot | Separate credentials/routes/processes; negative reachability and login tests |
| Broker to core | Flood, duplication, retained command | ACL, bounded queue, rate limits, deduplication, retained delivery rejection |
| Evidence to console | Stored XSS or malicious filenames | Escaped text, content limits, safe export names, browser regression |
| Import to replay | Executable payload or external target | Strict declarative schema, caps, no network destinations |
| CAN to real systems | Unintended actuation | Synthetic memory/vCAN default; bench-only hardware profile |
| Container to homelab | Excess privilege or unrestricted egress | Non-root/read-only runtime where feasible; capability drop; quotas; reachability checks |

## Network plan
Use separate decoy, core and analyst networks with internal networking where appropriate. Publish local ports explicitly on 127.0.0.1 for the base demo. No Docker socket mounts, host networking or production volumes.
Adapters have only the internal endpoint needed to submit intents and read projections. Authenticate internal control endpoints; analyst mutations use a distinct authorization path.
For vCAN, a dedicated setup step creates a namespaced interface; application containers do not gain broad host privileges. Docker internal networks are one layer, not proof of isolation: test egress, DNS, host reachability and published port behavior on the actual deployment.

## Credentials and retention
Use only generated synthetic decoy credentials; use a separate generated analyst secret. Never commit secrets or log analyst credentials. Default storage cap target 1 GiB, raw event retention target seven days; implementation must specify rollover behavior and preserve selected replay fixtures.
Raw lab captures may include credential attempts and IP addresses. Keep raw evidence local; redact before public export. Log correlation basis and uncertainty. Hash/checksum exports for integrity without claiming forensic certification.

## Abuse handling and scope
Decoy commands are simulated bounded intents. Do not implement a general-purpose proxy, malware executor, exploit launcher or unconstrained SSH shell. SSH extension emulates a small allowlist and synthetic filesystem.
Captured inputs can become declarative test cases, never executable scripts. AI receives sanitized summaries only and cannot issue control actions.
No connection to the user's real Golf, campus network, public transit equipment or production services is required for the demo.

## Release gate
Exercise all boundaries with controlled lab fixtures. Record what was tested and what was unavailable. A failed containment gate blocks any wider exposure; it does not block continuing offline development.
