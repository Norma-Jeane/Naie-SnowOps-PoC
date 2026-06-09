#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
io service

■ 役割
- 入力ファイル仕様の定義
- GeoJSON 読み込み
- CRS 補正
- 読み込み結果要約
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd


@dataclass(frozen=True)
class InputFileSpec:
    key: str
    label: str
    path: Path
    required: bool
    description: str


def build_input_specs(project_root: Path) -> list[InputFileSpec]:
    return [
        InputFileSpec(
            key="roads",
            label="背景道路網",
            path=project_root / "data" / "interim" / "C1_roads.geojson",
            required=True,
            description="奈井江町の道路網表示に使う背景GeoJSON",
        ),
        InputFileSpec(
            key="route",
            label="現実的ルート",
            path=project_root / "data" / "interim" / "C7_realistic_route.geojson",
            required=True,
            description="Step C-7 の出力ルートGeoJSON",
        ),
        InputFileSpec(
            key="priority_roads",
            label="優先度付き道路（任意）",
            path=project_root / "data" / "interim" / "C5_priority_roads_level3.geojson",
            required=False,
            description="道路 ON/OFF 操作用の優先度付き道路GeoJSON",
        ),
    ]


def load_geojson(path_str: str) -> gpd.GeoDataFrame:
    path = Path(path_str)

    if not path.exists():
        raise FileNotFoundError(f"file not found: {path}")
    if not path.is_file():
        raise ValueError(f"path is not a file: {path}")

    gdf = gpd.read_file(path)

    if len(gdf) == 0:
        raise ValueError(f"GeoJSON is empty: {path}")
    if "geometry" not in gdf.columns:
        raise ValueError(f"geometry column is missing: {path}")
    if gdf.geometry.isna().all():
        raise ValueError(f"all geometry values are null: {path}")

    return gdf


def load_required_inputs(
    input_specs: list[InputFileSpec],
    load_geojson_fn,
) -> dict[str, gpd.GeoDataFrame]:
    loaded: dict[str, gpd.GeoDataFrame] = {}

    for spec in input_specs:
        if not spec.path.exists() or not spec.path.is_file():
            if spec.required:
                raise FileNotFoundError(f"required file missing: {spec.path}")
            continue
        loaded[spec.key] = load_geojson_fn(str(spec.path))

    return loaded


def ensure_wgs84(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if gdf.crs is None:
        return gdf.set_crs(epsg=4326)
    if str(gdf.crs).upper() != "EPSG:4326":
        return gdf.to_crs(epsg=4326)
    return gdf


def summarize_gdf(gdf: gpd.GeoDataFrame) -> dict[str, object]:
    bounds = gdf.total_bounds.tolist() if len(gdf) > 0 else []

    return {
        "rows": int(len(gdf)),
        "columns": list(gdf.columns),
        "crs": str(gdf.crs) if gdf.crs is not None else "None",
        "geometry_type": sorted(gdf.geometry.geom_type.dropna().unique().tolist()),
        "bounds": bounds,
    }