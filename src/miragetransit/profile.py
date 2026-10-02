"""Strict JSON profile loading with no executable or external references."""

import json
from dataclasses import asdict
from importlib.resources import files
from pathlib import Path
from typing import Any

from miragetransit.models import Profile, Waypoint


def object_fields(value: object, fields: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{name} requires exactly these fields: {sorted(fields)}")
    return value


def profile_from_dict(value: object) -> Profile:
    data = object_fields(
        value, {"profile_id", "vehicle_ids", "route", "initial_fuel_ml"}, "profile"
    )
    if not isinstance(data["vehicle_ids"], list) or not isinstance(data["route"], list):
        raise ValueError("vehicle_ids and route must be arrays")
    points = tuple(
        Waypoint(
            **object_fields(
                point, {"offset_mm", "latitude_e7", "longitude_e7", "heading_mdeg"}, "waypoint"
            )
        )
        for point in data["route"]
    )
    return Profile(data["profile_id"], tuple(data["vehicle_ids"]), points, data["initial_fuel_ml"])


def profile_to_dict(profile: Profile) -> dict[str, Any]:
    data = asdict(profile)
    data["vehicle_ids"] = list(profile.vehicle_ids)
    return data


def load_profile(path: Path | None = None) -> Profile:
    if path is None:
        text = files("miragetransit").joinpath("profiles/fleet.json").read_text()
    else:
        if path.stat().st_size > 1_048_576:
            raise ValueError("profile exceeds 1 MiB")
        text = path.read_text()
    return profile_from_dict(json.loads(text))
