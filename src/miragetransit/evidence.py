"""Inspectable evidence edges; token reuse is evidence of access, not person identity."""

import hashlib
from typing import Any

from miragetransit.core import canonical
from miragetransit.replay import checksum, verify


def graph(events: list[dict[str, Any]]) -> dict[str, Any]:
    issuances: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    sessions: dict[str, dict[str, Any]] = {}
    for event in events:
        session = event.get("session_id")
        if session:
            sessions.setdefault(
                session,
                {
                    "id": session,
                    "adapter": event["source_adapter"],
                    "first_event": event["event_id"],
                    "events": 0,
                },
            )
            sessions[session]["events"] += 1
        payload = event.get("payload", {})
        token = payload.get("token_sha256") if isinstance(payload, dict) else None
        if event["event_type"] == "artifact.read" and token:
            issuances[token] = event
        if event["event_type"] == "canary.used" and token in issuances:
            source = issuances[token]
            edges.append(
                {
                    "source_event_id": source["event_id"],
                    "target_event_id": event["event_id"],
                    "source_session": source["session_id"],
                    "target_session": session,
                    "basis": "token",
                    "confidence": "high",
                    "evidence": "Exact run-specific planted credential reused; "
                    "supports artifact access, not a person's identity.",
                }
            )
    return {
        "sessions": list(sessions.values()),
        "edges": edges,
        "attribution_limit": "Shared addresses and raw CAN do not identify a person.",
    }


def sanitized_bundle(value: dict[str, Any]) -> dict[str, Any]:
    import json

    bundle: dict[str, Any] = json.loads(canonical(value))
    for action in bundle["actions"]:
        if action["kind"] == "submit" and isinstance(action["body"], dict):
            origin = action["body"].get("origin")
            if isinstance(origin, dict):
                origin["session_id"] = "sanitized-session"
    bundle["checksum_sha256"] = checksum(bundle)
    verify(bundle)
    return bundle


def token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
