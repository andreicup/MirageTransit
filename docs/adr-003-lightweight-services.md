# ADR 003 — standard-library local service stack

Status: accepted for the local research lab.

The planned FastAPI/Mosquitto/React stack in the architecture baseline was a proposal.
The implemented stack extends the dependency-free deterministic Python core with bounded
standard-library HTTP services and a deliberately limited MQTT 3.1.1 broker. The analyst
interface uses static HTML/CSS/JavaScript, with no frontend runtime framework or external assets.

This keeps clean-wheel deployment possible without additional Python dependencies. There are
four service processes: core, decoy portal, MQTT, and analyst. A local supervisor starts them;
Compose puts them in separate non-root containers. Only core receives the SQLite volume.
Decoy services receive a decoy capability key; analyst receives a different capability key.
Private operations require analyst capability even on the internal core API.

The MQTT implementation is explicitly a lab subset, not a replacement for Mosquitto:
clean-session CONNECT with username/password, QoS 0/1 input, outbound QoS 0 telemetry and
receipts, PING and DISCONNECT. No retained messages, wills, QoS 2, arbitrary routing or
persistent broker sessions. Run-scoped telemetry/ack subscriptions only; run-scoped command
publication only. Retained commands are rejected before submission. PUBACK is a transport
acknowledgment; JSON command receipt is acceptance; later command.applied is execution.

Limits: 16 concurrent workers per surface, 64 queued RPC requests, MQTT 10 packets/session/s,
16 subscriptions/session, 4608-byte MQTT packet, 4096-byte command. Core services tick work
before the next queued request. Malformed evidence records contain reasons, not raw captures.
The existing run caps remain: 36,000 ticks, 1,000 command attempts, 500,000 vehicle-ticks;
observations add a separate 5,000-record cap. Once budgets are exhausted, inputs fail explicitly.

Local OS processes share a user account; this is process and capability separation, not an OS
sandbox. The Compose topology adds filesystem/network separation. It is configured for loopback
only and must be exercised on a Docker host before claiming container reachability validation.
Future public honeypot work should use a reviewed production broker/HTTP ingress and containment
validation. The local lab remains fully usable with the current stack.

The contained Docker topology uses an additional fixed-target TCP ingress relay. Only the relay
joins the host-accessible bridge, with listeners restricted to that bridge IP; all application
services keep internal-only networks. This preserves published loopback access without giving
the decoy a default external route or a listener that bypasses analyst network separation.
Reference: https://docs.docker.com/compose/how-tos/networking/ .
