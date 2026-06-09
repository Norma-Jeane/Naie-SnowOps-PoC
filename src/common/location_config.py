#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path
import json


CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "locations.json"


def load_locations(config_path: Path | None = None) -> dict:
    path = config_path or CONFIG_PATH

    if not path.exists():
        raise FileNotFoundError(f"location config not found: {path}")
    if not path.is_file():
        raise ValueError(f"location config is not a file: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if "locations" not in data:
        raise ValueError("required key is missing in location config: locations")

    return data


def get_location(location_key: str, config_path: Path | None = None) -> dict:
    data = load_locations(config_path=config_path)
    locations = data["locations"]

    if location_key not in locations:
        raise ValueError(f"location key not found: {location_key}")

    location = locations[location_key]

    for key in ["name", "lat", "lon"]:
        if key not in location:
            raise ValueError(f"required location field is missing: {key}")

    return location


def get_location_lat_lon(
    location_key: str,
    config_path: Path | None = None,
) -> tuple[float, float]:
    location = get_location(location_key=location_key, config_path=config_path)
    return float(location["lat"]), float(location["lon"])