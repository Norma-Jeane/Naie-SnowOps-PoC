#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
D3 再計算サービス

■ 目的
- D3 の操作状態から app 内再計算 request を生成する
- current_start_point と excluded_roads を検証する
- 除外道路を反映した一時対象道路 GeoJSON を生成する
- C7 由来の現実的ルート生成ロジックを app 内で実行する
- route / summary / metrics を返す

■ 位置づけ
- D3-4: 再計算入力変換
- D3-5: 再計算接続
- Step C 側 test script を直接の接続先とはしない
- CLI / subprocess 前提は持たない

■ 備考
- 共通 IO は src.app.services.io を使う
- edge_id の正規化思想は src.app.services.road_state と整合を取る
- strategy は request に持つが、現時点では D3 UI には露出しない
- save_outputs=True の場合のみ route / summary を保存する
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import logging
from typing import Iterable

import geopandas as gpd
import networkx as nx
import pandas as pd
from shapely.geometry import LineString, Point

from src.app.services.io import ensure_wgs84, load_geojson
from src.app.services.road_state import normalize_edge_id


logger = logging.getLogger(__name__)


DEFAULT_TARGET_INPUT = Path("Data/app_init/roads/priority_roads_level3.geojson")
DEFAULT_NETWORK_INPUT = Path("Data/app_init/roads/road_network.geojson")
DEFAULT_RUNTIME_ROUTE_DIR = Path("Data/app_runtime/routes")
DEFAULT_OUTPUT_ROUTE = DEFAULT_RUNTIME_ROUTE_DIR / "latest_route.geojson"
DEFAULT_OUTPUT_SUMMARY = DEFAULT_RUNTIME_ROUTE_DIR / "latest_route_summary.csv"
DEFAULT_OUTPUT_TARGET_ROADS = DEFAULT_RUNTIME_ROUTE_DIR / "latest_target_roads.geojson"

REQUIRED_TARGET_COLS = ["u", "v", "key", "priority", "length", "geometry", "oneway"]
REQUIRED_NETWORK_COLS = ["u", "v", "key", "length", "geometry", "oneway"]
ROUTE_OUTPUT_COLS = [
    "segment_order",
    "segment_type",
    "target_order",
    "priority",
    "length",
    "pass_from_node",
    "pass_to_node",
    "u",
    "v",
    "key",
    "edge_id",
    "geometry",
]

STRATEGIES = ("distance", "priority", "return")

PRIORITY_BONUS_BY_STRATEGY = {
    "distance": {4: 150.0, 3: 90.0, 2: 40.0, 1: 0.0},
    "priority": {4: 260.0, 3: 160.0, 2: 70.0, 1: 0.0},
    "return": {4: 160.0, 3: 100.0, 2: 40.0, 1: 0.0},
}

RETURN_WEIGHT_BY_STRATEGY = {
    "distance": 0.25,
    "priority": 0.20,
    "return": 0.60,
}

ADJACENT_EXIT_TARGET_BONUS_METERS = 200.0
ADJACENT_REVERSE_TARGET_PENALTY_METERS = 130.0

ROUTE_SEGMENT_TYPE_TARGET = "target"
ROUTE_SEGMENT_TYPE_CONNECTOR = "connector"
ROUTE_SEGMENT_TYPE_LEGACY_ACCESS = "access"
ROUTE_SEGMENT_TYPE_RETURN = "return"


@dataclass(frozen=True)
class RecalculationPaths:
    target_input: Path
    network_input: Path
    output_route: Path
    output_summary: Path
    runtime_route_dir: Path
    output_target_roads: Path


@dataclass(frozen=True)
class RecalculationRequest:
    start_lat: float
    start_lon: float
    excluded_roads: tuple[tuple[str, str, str], ...]
    included_roads: tuple[tuple[str, str, str], ...]
    conditional_roads: tuple[tuple[str, str, str], ...]
    target_input_path: Path
    network_input_path: Path
    output_route_path: Path
    output_summary_path: Path
    strategy: str = "distance"
    save_outputs: bool = True


@dataclass(frozen=True)
class RecalculationPreparationResult:
    request: RecalculationRequest
    source_target_input_path: Path
    input_target_rows: int
    output_target_rows: int
    excluded_count: int
    included_count: int
    conditional_count: int
    added_target_rows: int


@dataclass(frozen=True)
class RecalculationRunResult:
    request: RecalculationRequest
    route_gdf: gpd.GeoDataFrame
    summary_df: pd.DataFrame
    metrics: dict[str, float]
    selected_strategy: str
    visited_target_edge_ids: tuple[tuple[str, str, str], ...]
    failed_target_edge_ids: tuple[tuple[str, str, str], ...] = tuple()
    failed_included_edge_ids: tuple[tuple[str, str, str], ...] = tuple()


@dataclass(frozen=True)
class EdgeId:
    u: object
    v: object
    key: object


@dataclass(frozen=True)
class EdgeRecord:
    edge_id: EdgeId
    u: object
    v: object
    key: object
    priority: int
    length: float
    geometry: object
    oneway: bool
    highway: str | None = None
    name: str | None = None


@dataclass(frozen=True)
class NetworkEdgeRecord:
    edge_id: EdgeId
    u: object
    v: object
    key: object
    length: float
    geometry: object
    oneway: bool
    highway: str | None = None
    name: str | None = None


@dataclass(frozen=True)
class ConnectorPlan:
    enter_node: object
    exit_node: object
    connector_path_nodes: list[object]
    connector_cost: float
    traverse_cost: float
    return_estimate: float
    priority_bonus: float
    total_score: float


def normalize_route_segment_type(segment_type: object) -> str:
    if not isinstance(segment_type, str):
        return ""

    normalized = segment_type.strip()
    if normalized == ROUTE_SEGMENT_TYPE_LEGACY_ACCESS:
        return ROUTE_SEGMENT_TYPE_CONNECTOR
    return normalized


def build_route_segment_mask(
    route_gdf: gpd.GeoDataFrame,
    segment_type: str,
) -> pd.Series:
    normalized_types = route_gdf["segment_type"].map(normalize_route_segment_type)
    return normalized_types == segment_type


def _normalize_edge_id(
    edge_id: tuple[object, object, object],
) -> tuple[str, str, str]:
    if not isinstance(edge_id, tuple):
        raise TypeError(f"edge_id must be tuple, got: {type(edge_id).__name__}")
    if len(edge_id) != 3:
        raise ValueError(f"edge_id must have length 3, got: {len(edge_id)}")

    return normalize_edge_id(edge_id)


def normalize_oneway_bool(value: object, *, source_name: str) -> bool:
    if isinstance(value, bool) or type(value).__name__ == "bool_":
        return bool(value)

    raise ValueError(
        f"{source_name} oneway must be bool True/False, "
        f"got {value!r} ({type(value).__name__})"
    )


def normalize_excluded_roads(
    excluded_roads: Iterable[tuple[object, object, object]] | None,
) -> tuple[tuple[str, str, str], ...]:
    if excluded_roads is None:
        return tuple()

    normalized = {_normalize_edge_id(edge_id) for edge_id in excluded_roads}
    return tuple(sorted(normalized))


def normalize_included_roads(
    included_roads: Iterable[tuple[object, object, object]] | None,
) -> tuple[tuple[str, str, str], ...]:
    if included_roads is None:
        return tuple()

    normalized = {_normalize_edge_id(edge_id) for edge_id in included_roads}
    return tuple(sorted(normalized))


def normalize_conditional_roads(
    conditional_roads: Iterable[tuple[object, object, object]] | None,
) -> tuple[tuple[str, str, str], ...]:
    if conditional_roads is None:
        return tuple()

    normalized = {_normalize_edge_id(edge_id) for edge_id in conditional_roads}
    return tuple(sorted(normalized))


def validate_current_start_point(
    current_start_point: dict[str, object] | None,
) -> tuple[float, float]:
    if current_start_point is None:
        raise ValueError("current_start_point is required")

    if not isinstance(current_start_point, dict):
        raise TypeError("current_start_point must be dict")

    if "lat" not in current_start_point or "lon" not in current_start_point:
        raise ValueError("current_start_point must include lat and lon")

    lat = float(current_start_point["lat"])
    lon = float(current_start_point["lon"])

    if not (-90.0 <= lat <= 90.0):
        raise ValueError(f"invalid current_start_point.lat: {lat}")
    if not (-180.0 <= lon <= 180.0):
        raise ValueError(f"invalid current_start_point.lon: {lon}")

    return lat, lon


def build_recalculation_paths(project_root: Path) -> RecalculationPaths:
    if not isinstance(project_root, Path):
        raise TypeError("project_root must be Path")

    target_input = project_root / DEFAULT_TARGET_INPUT
    network_input = project_root / DEFAULT_NETWORK_INPUT
    output_route = project_root / DEFAULT_OUTPUT_ROUTE
    output_summary = project_root / DEFAULT_OUTPUT_SUMMARY
    runtime_route_dir = project_root / DEFAULT_RUNTIME_ROUTE_DIR
    output_target_roads = project_root / DEFAULT_OUTPUT_TARGET_ROADS

    return RecalculationPaths(
        target_input=target_input,
        network_input=network_input,
        output_route=output_route,
        output_summary=output_summary,
        runtime_route_dir=runtime_route_dir,
        output_target_roads=output_target_roads,
    )


def load_target_roads(path: Path) -> gpd.GeoDataFrame:
    if not path.exists():
        raise FileNotFoundError(f"target roads file not found: {path}")
    if not path.is_file():
        raise ValueError(f"target roads path is not a file: {path}")

    with path.open("r", encoding="utf-8") as f:
        raw_geojson = json.load(f)
    if isinstance(raw_geojson, dict) and raw_geojson.get("features") == []:
        return gpd.GeoDataFrame(
            columns=list(REQUIRED_TARGET_COLS),
            geometry="geometry",
            crs="EPSG:4326",
        )

    gdf = ensure_wgs84(load_geojson(path))

    if len(gdf) == 0:
        empty_columns = list(REQUIRED_TARGET_COLS)
        return gpd.GeoDataFrame(columns=empty_columns, geometry="geometry", crs=gdf.crs)

    for col in REQUIRED_TARGET_COLS:
        if col not in gdf.columns:
            raise ValueError(f"required target road column is missing: {col}")

    if gdf["geometry"].isna().any():
        raise ValueError("target roads geometry contains null values")

    return gdf


def load_network_roads(path: Path) -> gpd.GeoDataFrame:
    if not path.exists():
        raise FileNotFoundError(f"network roads file not found: {path}")
    if not path.is_file():
        raise ValueError(f"network roads path is not a file: {path}")

    gdf = ensure_wgs84(load_geojson(path))

    for col in REQUIRED_NETWORK_COLS:
        if col not in gdf.columns:
            raise ValueError(f"required network road column is missing: {col}")

    if len(gdf) == 0:
        raise ValueError("network roads are empty")

    if gdf["geometry"].isna().any():
        raise ValueError("network roads geometry contains null values")

    return gdf


def filter_target_roads_by_excluded_roads(
    target_gdf: gpd.GeoDataFrame,
    excluded_roads: tuple[tuple[str, str, str], ...],
) -> gpd.GeoDataFrame:
    if len(target_gdf) == 0:
        return target_gdf.copy()

    if len(excluded_roads) == 0:
        return target_gdf.copy()

    excluded_set = _build_bidirectional_edge_lookup(excluded_roads)
    result = target_gdf.copy()

    keep_mask = []
    for row in result.itertuples(index=False):
        edge_id = _normalize_edge_id((row.u, row.v, row.key))
        keep_mask.append(edge_id not in excluded_set)

    filtered = result.loc[keep_mask].copy()

    if len(filtered) == 0:
        raise ValueError("all target roads were excluded; recalculation input became empty")

    return filtered


def filter_target_roads_by_conditional_roads(
    target_gdf: gpd.GeoDataFrame,
    conditional_roads: tuple[tuple[str, str, str], ...],
) -> gpd.GeoDataFrame:
    if len(target_gdf) == 0:
        return target_gdf.copy()

    if len(conditional_roads) == 0:
        return target_gdf.copy()

    conditional_set = _build_bidirectional_edge_lookup(conditional_roads)
    result = target_gdf.copy()

    keep_mask = []
    for row in result.itertuples(index=False):
        edge_id = _normalize_edge_id((row.u, row.v, row.key))
        keep_mask.append(edge_id not in conditional_set)

    filtered = result.loc[keep_mask].copy()

    if len(filtered) == 0:
        raise ValueError("all target roads became conditional; recalculation input became empty")

    return filtered


def _build_bidirectional_edge_lookup(
    edge_ids: tuple[tuple[str, str, str], ...],
) -> set[tuple[str, str, str]]:
    lookup = set(edge_ids)
    lookup.update((v, u, key) for u, v, key in edge_ids)
    return lookup


def _freeze_geometry_coords(geometry: object) -> tuple | None:
    if geometry is None or getattr(geometry, "is_empty", False):
        return None
    coords = getattr(geometry, "coords", None)
    if coords is None:
        return None
    try:
        return tuple(tuple(point) for point in coords)
    except Exception:
        return None


def _build_oneway_false_pair_lookup_from_gdf(
    source_gdf: gpd.GeoDataFrame,
) -> dict[tuple[str, str, str], tuple[str, str, str]]:
    rows: list[dict[str, object]] = []
    by_endpoints: dict[tuple[str, str], list[dict[str, object]]] = {}

    for row in source_gdf.itertuples(index=False):
        if normalize_oneway_bool(row.oneway, source_name="additional road source"):
            continue

        edge_id = _normalize_edge_id((row.u, row.v, row.key))
        item = {
            "edge_id": edge_id,
            "u": edge_id[0],
            "v": edge_id[1],
            "coords": _freeze_geometry_coords(row.geometry),
        }
        rows.append(item)
        by_endpoints.setdefault((edge_id[0], edge_id[1]), []).append(item)

    pair_lookup: dict[tuple[str, str, str], tuple[str, str, str]] = {}
    for row in rows:
        candidates = by_endpoints.get((str(row["v"]), str(row["u"])), [])
        if len(candidates) == 1:
            pair_lookup[row["edge_id"]] = candidates[0]["edge_id"]
            continue

        coords = row.get("coords")
        if coords is None:
            continue

        reversed_coords = tuple(reversed(coords))
        geometry_matches = [
            candidate
            for candidate in candidates
            if candidate.get("coords") == reversed_coords
        ]
        if len(geometry_matches) == 1:
            pair_lookup[row["edge_id"]] = geometry_matches[0]["edge_id"]

    return pair_lookup


def expand_included_roads_with_oneway_false_pairs(
    source_gdf: gpd.GeoDataFrame,
    included_roads: tuple[tuple[str, str, str], ...],
    excluded_roads: tuple[tuple[str, str, str], ...],
) -> set[tuple[str, str, str]]:
    excluded_lookup = _build_bidirectional_edge_lookup(excluded_roads)
    expanded = {edge_id for edge_id in included_roads if edge_id not in excluded_lookup}
    pair_lookup = _build_oneway_false_pair_lookup_from_gdf(source_gdf)

    for edge_id in included_roads:
        if edge_id in excluded_lookup:
            continue
        paired_edge_id = pair_lookup.get(edge_id)
        if paired_edge_id is not None and paired_edge_id not in excluded_lookup:
            expanded.add(paired_edge_id)

    return expanded


def filter_network_roads_by_excluded_roads(
    network_gdf: gpd.GeoDataFrame,
    excluded_roads: tuple[tuple[str, str, str], ...],
) -> gpd.GeoDataFrame:
    if len(excluded_roads) == 0:
        return network_gdf.copy()

    excluded_lookup = _build_bidirectional_edge_lookup(excluded_roads)
    result = network_gdf.copy()

    keep_mask = []
    for row in result.itertuples(index=False):
        edge_id = _normalize_edge_id((row.u, row.v, row.key))
        keep_mask.append(edge_id not in excluded_lookup)

    filtered = result.loc[keep_mask].copy()

    if len(filtered) == 0:
        raise ValueError("all network roads were excluded; recalculation graph became empty")

    return filtered


def save_target_roads_for_recalculation(
    target_gdf: gpd.GeoDataFrame,
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_gdf = normalize_target_roads_output_schema(target_gdf)
    normalized_gdf.to_file(output_path, driver="GeoJSON", encoding="utf-8")
    logger.info("saved recalculation target roads: %s", output_path)


def normalize_target_roads_output_schema(
    target_gdf: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    missing = [col for col in REQUIRED_TARGET_COLS if col not in target_gdf.columns]
    if missing:
        raise ValueError(f"target roads output is missing required columns: {missing}")

    normalized = target_gdf.copy()
    for col in ("u", "v", "key", "priority"):
        normalized[col] = pd.to_numeric(normalized[col], errors="raise").astype("int64")
    normalized["length"] = pd.to_numeric(normalized["length"], errors="raise").astype(float)
    normalized["oneway"] = normalized["oneway"].map(
        lambda value: normalize_oneway_bool(value, source_name="target roads output")
    )

    return gpd.GeoDataFrame(normalized, geometry="geometry", crs=target_gdf.crs)


def build_additional_target_roads(
    source_gdf: gpd.GeoDataFrame | None,
    included_roads: tuple[tuple[str, str, str], ...],
    excluded_roads: tuple[tuple[str, str, str], ...],
) -> gpd.GeoDataFrame:
    if len(included_roads) == 0:
        return gpd.GeoDataFrame(geometry=[], crs=None)

    if source_gdf is None:
        raise ValueError("additional road source is required when included_roads are specified")

    source_wgs84 = ensure_wgs84(source_gdf.copy())
    required_cols = ["u", "v", "key", "length", "geometry", "oneway"]
    missing = [col for col in required_cols if col not in source_wgs84.columns]
    if missing:
        raise ValueError(f"additional road source is missing required columns: {missing}")

    include_lookup = expand_included_roads_with_oneway_false_pairs(
        source_wgs84,
        included_roads,
        excluded_roads,
    )
    if len(include_lookup) == 0:
        return gpd.GeoDataFrame(geometry=[], crs=source_wgs84.crs)

    has_priority = "priority" in source_wgs84.columns
    has_highway = "highway" in source_wgs84.columns
    has_name = "name" in source_wgs84.columns
    rows: list[dict[str, object]] = []
    for row in source_wgs84.itertuples(index=False):
        edge_id = _normalize_edge_id((row.u, row.v, row.key))
        if edge_id not in include_lookup:
            continue

        priority_value = row.priority if has_priority else 1
        if pd.isna(priority_value):
            priority_value = 1

        rows.append(
            {
                "u": row.u,
                "v": row.v,
                "key": row.key,
                "priority": int(priority_value),
                "length": float(row.length),
                "geometry": row.geometry,
                "oneway": normalize_oneway_bool(
                    row.oneway,
                    source_name="additional road source",
                ),
                "highway": row.highway if has_highway else None,
                "name": row.name if has_name else None,
            }
        )

    if len(rows) == 0:
        raise ValueError("included_roads were specified but no matching roads were found")

    return gpd.GeoDataFrame(rows, geometry="geometry", crs=source_wgs84.crs)


def merge_target_roads_with_included_roads(
    target_gdf: gpd.GeoDataFrame,
    additional_target_gdf: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, int]:
    if len(additional_target_gdf) == 0:
        return target_gdf.copy(), 0

    existing_lookup = {
        _normalize_edge_id((row.u, row.v, row.key))
        for row in target_gdf.itertuples(index=False)
    }
    additional_rows = additional_target_gdf.copy()
    keep_mask = []
    for row in additional_rows.itertuples(index=False):
        edge_id = _normalize_edge_id((row.u, row.v, row.key))
        keep_mask.append(edge_id not in existing_lookup)

    appendable = additional_rows.loc[keep_mask].copy()
    if len(appendable) == 0:
        return target_gdf.copy(), 0

    for col in target_gdf.columns:
        if col not in appendable.columns:
            appendable[col] = None
    appendable = appendable[target_gdf.columns]

    merged = pd.concat([target_gdf.copy(), appendable], ignore_index=True)
    return gpd.GeoDataFrame(merged, geometry="geometry", crs=target_gdf.crs), len(appendable)


def build_recalculation_request(
    *,
    current_start_point: dict[str, object] | None,
    excluded_roads: Iterable[tuple[object, object, object]] | None,
    included_roads: Iterable[tuple[object, object, object]] | None = None,
    conditional_roads: Iterable[tuple[object, object, object]] | None = None,
    additional_roads_source_gdf: gpd.GeoDataFrame | None = None,
    project_root: Path,
    target_input_path: Path | str | None = None,
    strategy: str = "distance",
    save_outputs: bool = True,
) -> RecalculationPreparationResult:
    if strategy not in STRATEGIES:
        raise ValueError(f"unsupported strategy: {strategy}")

    start_lat, start_lon = validate_current_start_point(current_start_point)
    normalized_excluded = normalize_excluded_roads(excluded_roads)
    normalized_included = normalize_included_roads(included_roads)
    normalized_conditional = normalize_conditional_roads(conditional_roads)
    paths = build_recalculation_paths(project_root)
    resolved_target_input_path = (
        paths.target_input
        if target_input_path is None
        else Path(target_input_path)
    )
    if not resolved_target_input_path.is_absolute():
        resolved_target_input_path = project_root / resolved_target_input_path

    target_gdf = load_target_roads(resolved_target_input_path)
    filtered_target_gdf = filter_target_roads_by_excluded_roads(
        target_gdf=target_gdf,
        excluded_roads=normalized_excluded,
    )
    filtered_target_gdf = filter_target_roads_by_conditional_roads(
        target_gdf=filtered_target_gdf,
        conditional_roads=normalized_conditional,
    )
    additional_target_gdf = build_additional_target_roads(
        source_gdf=additional_roads_source_gdf,
        included_roads=normalized_included,
        excluded_roads=normalized_excluded,
    )
    merged_target_gdf, added_target_rows = merge_target_roads_with_included_roads(
        target_gdf=filtered_target_gdf,
        additional_target_gdf=additional_target_gdf,
    )
    save_target_roads_for_recalculation(
        target_gdf=merged_target_gdf,
        output_path=paths.output_target_roads,
    )

    request = RecalculationRequest(
        start_lat=start_lat,
        start_lon=start_lon,
        excluded_roads=normalized_excluded,
        included_roads=normalized_included,
        conditional_roads=normalized_conditional,
        target_input_path=paths.output_target_roads,
        network_input_path=paths.network_input,
        output_route_path=paths.output_route,
        output_summary_path=paths.output_summary,
        strategy=strategy,
        save_outputs=save_outputs,
    )

    return RecalculationPreparationResult(
        request=request,
        source_target_input_path=resolved_target_input_path,
        input_target_rows=len(target_gdf),
        output_target_rows=len(merged_target_gdf),
        excluded_count=len(normalized_excluded),
        included_count=len(normalized_included),
        conditional_count=len(normalized_conditional),
        added_target_rows=added_target_rows,
    )


def build_recalculation_preview_rows(
    result: RecalculationPreparationResult,
) -> list[dict[str, object]]:
    request = result.request

    return [
        {"項目": "start_lat", "値": request.start_lat},
        {"項目": "start_lon", "値": request.start_lon},
        {"項目": "excluded_count", "値": result.excluded_count},
        {"項目": "included_count", "値": result.included_count},
        {"項目": "conditional_count", "値": result.conditional_count},
        {"項目": "input_target_rows", "値": result.input_target_rows},
        {"項目": "output_target_rows", "値": result.output_target_rows},
        {"項目": "added_target_rows", "値": result.added_target_rows},
        {"項目": "source_target_input_path", "値": str(result.source_target_input_path)},
        {"項目": "target_input_path", "値": str(request.target_input_path)},
        {"項目": "network_input_path", "値": str(request.network_input_path)},
        {"項目": "output_route_path", "値": str(request.output_route_path)},
        {"項目": "output_summary_path", "値": str(request.output_summary_path)},
        {"項目": "strategy", "値": request.strategy},
        {"項目": "save_outputs", "値": str(request.save_outputs)},
    ]


def safe_optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text != "" else None


def _extract_endpoints(geometry: object) -> tuple[Point, Point]:
    if geometry is None:
        raise ValueError("geometry is required")

    geom_type = getattr(geometry, "geom_type", None)

    if geom_type == "LineString":
        coords = list(geometry.coords)
        return Point(coords[0]), Point(coords[-1])

    if geom_type == "MultiLineString":
        first = list(geometry.geoms[0].coords)
        last = list(geometry.geoms[-1].coords)
        return Point(first[0]), Point(last[-1])

    raise ValueError(f"unsupported geometry type for edge: {geom_type}")


def _reverse_linestring(line: LineString) -> LineString:
    return LineString(list(line.coords)[::-1])


def _node_ids_equal(left: object, right: object) -> bool:
    return str(left) == str(right)


def orient_linestring_by_traversal(
    line: LineString,
    edge_id: EdgeId,
    pass_from_node: object,
    pass_to_node: object,
) -> LineString:
    if _node_ids_equal(edge_id.u, pass_from_node) and _node_ids_equal(
        edge_id.v,
        pass_to_node,
    ):
        return line

    if _node_ids_equal(edge_id.u, pass_to_node) and _node_ids_equal(
        edge_id.v,
        pass_from_node,
    ):
        return _reverse_linestring(line)

    logger.warning(
        "route geometry orientation could not be inferred edge_id=%s pass_from_node=%s pass_to_node=%s",
        edge_id,
        pass_from_node,
        pass_to_node,
    )
    return line


def _reverse_path_nodes(path_nodes: list[object]) -> list[object]:
    return list(reversed(path_nodes))


def _build_shortest_path_cache(
    graph: nx.MultiDiGraph,
    source: object,
) -> tuple[dict[object, float], dict[object, list[object]]]:
    lengths, paths = nx.single_source_dijkstra(graph, source, weight="weight")
    return {node: float(length) for node, length in lengths.items()}, paths


def _require_cached_distance(
    distance_map: dict[object, float],
    node: object,
    *,
    source_name: str,
) -> float:
    if node not in distance_map:
        raise ValueError(f"no cached path from {source_name} to node={node}")
    return float(distance_map[node])


def _require_cached_path(
    path_map: dict[object, list[object]],
    node: object,
    *,
    source_name: str,
) -> list[object]:
    if node not in path_map:
        raise ValueError(f"no cached path from {source_name} to node={node}")
    return list(path_map[node])


def normalize_target_roads(
    gdf: gpd.GeoDataFrame,
) -> list[EdgeRecord]:
    rows: list[EdgeRecord] = []

    has_highway = "highway" in gdf.columns
    has_name = "name" in gdf.columns
    for row in gdf.itertuples(index=False):
        edge_id = EdgeId(row.u, row.v, row.key)
        rows.append(
            EdgeRecord(
                edge_id=edge_id,
                u=row.u,
                v=row.v,
                key=row.key,
                priority=int(row.priority),
                length=float(row.length),
                geometry=row.geometry,
                oneway=normalize_oneway_bool(row.oneway, source_name="target roads"),
                highway=safe_optional_str(row.highway if has_highway else None),
                name=safe_optional_str(row.name if has_name else None),
            )
        )

    return rows


def normalize_network_roads(
    gdf: gpd.GeoDataFrame,
) -> list[NetworkEdgeRecord]:
    rows: list[NetworkEdgeRecord] = []

    has_highway = "highway" in gdf.columns
    has_name = "name" in gdf.columns
    for row in gdf.itertuples(index=False):
        edge_id = EdgeId(row.u, row.v, row.key)
        rows.append(
            NetworkEdgeRecord(
                edge_id=edge_id,
                u=row.u,
                v=row.v,
                key=row.key,
                length=float(row.length),
                geometry=row.geometry,
                oneway=normalize_oneway_bool(row.oneway, source_name="network roads"),
                highway=safe_optional_str(row.highway if has_highway else None),
                name=safe_optional_str(row.name if has_name else None),
            )
        )

    if len(rows) == 0:
        raise ValueError("normalized network roads are empty")

    return rows


def build_network_graph(
    edges: list[NetworkEdgeRecord],
    conditional_roads: tuple[tuple[str, str, str], ...] = tuple(),
) -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    conditional_lookup = set(conditional_roads)
    conditional_lookup.update((v, u, key) for u, v, key in conditional_roads)

    for edge in edges:
        edge_id = _normalize_edge_id((edge.u, edge.v, edge.key))
        weight_multiplier = 8.0 if edge_id in conditional_lookup else 1.0
        graph.add_edge(
            edge.u,
            edge.v,
            key=edge.key,
            weight=float(edge.length) * weight_multiplier,
            length=float(edge.length),
            geometry=edge.geometry,
            edge_id=edge.edge_id,
            is_conditional=weight_multiplier > 1.0,
            oneway=edge.oneway,
            highway=edge.highway,
            name=edge.name,
        )

    if graph.number_of_edges() == 0:
        raise ValueError("network graph is empty")

    return graph


def build_node_points(
    network_edges: list[NetworkEdgeRecord],
) -> dict[object, Point]:
    node_points: dict[object, Point] = {}

    for edge in network_edges:
        start_point, end_point = _extract_endpoints(edge.geometry)
        node_points.setdefault(edge.u, start_point)
        node_points.setdefault(edge.v, end_point)

    if len(node_points) == 0:
        raise ValueError("node points are empty")

    return node_points


def nearest_node_to_point(
    node_points: dict[object, Point],
    point: Point,
) -> object:
    if len(node_points) == 0:
        raise ValueError("node_points are empty")

    return min(node_points.keys(), key=lambda node: node_points[node].distance(point))


def shortest_path_nodes(
    graph: nx.MultiDiGraph,
    src: object,
    dst: object,
) -> tuple[list[object], float]:
    if src == dst:
        return [src], 0.0

    try:
        path_nodes = nx.shortest_path(graph, src, dst, weight="weight")
        path_length = nx.shortest_path_length(graph, src, dst, weight="weight")
    except nx.NetworkXNoPath as exc:
        raise ValueError(f"no path between {src} and {dst}") from exc

    return path_nodes, float(path_length)


def _pick_shortest_multiedge(graph: nx.MultiDiGraph, u: object, v: object) -> dict:
    data = graph.get_edge_data(u, v)
    if not data:
        raise ValueError(f"edge data not found between {u} and {v}")

    return min(data.values(), key=lambda x: float(x.get("length", x.get("weight", 0.0))))


def path_nodes_to_lines(
    graph: nx.MultiDiGraph,
    path_nodes: list[object],
) -> list[tuple[LineString, float, EdgeId, object, object]]:
    if len(path_nodes) <= 1:
        return []

    result: list[tuple[LineString, float, EdgeId, object, object]] = []

    for u, v in zip(path_nodes[:-1], path_nodes[1:]):
        edge_data = _pick_shortest_multiedge(graph, u, v)
        geometry = edge_data.get("geometry")
        if geometry is None or getattr(geometry, "geom_type", None) != "LineString":
            start = Point(0, 0)
            end = Point(0, 0)
            try:
                start, end = _extract_endpoints(geometry)
            except Exception:
                pass
            geometry = LineString([start, end])

        length = float(edge_data.get("length", edge_data.get("weight", 0.0)))
        edge_id = edge_data.get("edge_id")
        if not isinstance(edge_id, EdgeId):
            edge_id = EdgeId(u, v, edge_data.get("key", 0))

        geometry = orient_linestring_by_traversal(
            geometry,
            edge_id,
            pass_from_node=u,
            pass_to_node=v,
        )
        result.append((geometry, length, edge_id, u, v))

    return result


def choose_connector_plan(
    edge: EdgeRecord,
    strategy: str,
    dist_from_current: dict[object, float],
    path_from_current: dict[object, list[object]],
    dist_to_start: dict[object, float],
) -> ConnectorPlan:
    if strategy not in STRATEGIES:
        raise ValueError(f"unsupported strategy: {strategy}")

    connector_cost_to_u = _require_cached_distance(
        dist_from_current,
        edge.u,
        source_name="current_node",
    )
    return_cost_from_v = _require_cached_distance(
        dist_to_start,
        edge.v,
        source_name="start_node",
    )

    connector_path_to_u = _require_cached_path(
        path_from_current,
        edge.u,
        source_name="current_node",
    )

    priority_bonus = PRIORITY_BONUS_BY_STRATEGY[strategy].get(edge.priority, 0.0)
    return_weight = RETURN_WEIGHT_BY_STRATEGY[strategy]

    return ConnectorPlan(
        enter_node=edge.u,
        exit_node=edge.v,
        connector_path_nodes=connector_path_to_u,
        connector_cost=connector_cost_to_u,
        traverse_cost=float(edge.length),
        return_estimate=return_cost_from_v,
        priority_bonus=priority_bonus,
        total_score=(
            connector_cost_to_u
            + float(edge.length)
            + return_weight * return_cost_from_v
            - priority_bonus
        ),
    )


def append_path_segments(
    route_records: list[dict[str, object]],
    graph: nx.MultiDiGraph,
    path_nodes: list[object],
    segment_order_start: int,
    segment_type: str,
    target_order: int | None,
    priority: int | None,
    *,
    unvisited_target_edges: dict[tuple[str, str, str], EdgeRecord] | None = None,
    visited_target_edges: list[EdgeId] | None = None,
    next_target_order: int | None = None,
) -> tuple[int, int | None]:
    segment_order = segment_order_start
    for geometry, length, edge_id, pass_from_node, pass_to_node in path_nodes_to_lines(
        graph,
        path_nodes,
    ):
        edge_key = _normalize_edge_id((edge_id.u, edge_id.v, edge_id.key))
        consumed_target_edge = (
            unvisited_target_edges.pop(edge_key, None)
            if unvisited_target_edges is not None
            else None
        )
        if consumed_target_edge is not None:
            current_segment_type = ROUTE_SEGMENT_TYPE_TARGET
            current_target_order = next_target_order
            current_priority = consumed_target_edge.priority
            current_length = float(consumed_target_edge.length)
            if visited_target_edges is not None:
                visited_target_edges.append(consumed_target_edge.edge_id)
            if next_target_order is not None:
                next_target_order += 1
        else:
            current_segment_type = segment_type
            current_target_order = target_order
            current_priority = priority
            current_length = float(length)

        route_records.append(
            {
                "segment_order": segment_order,
                "segment_type": current_segment_type,
                "target_order": current_target_order,
                "priority": current_priority,
                "length": current_length,
                "pass_from_node": pass_from_node,
                "pass_to_node": pass_to_node,
                "u": edge_id.u,
                "v": edge_id.v,
                "key": edge_id.key,
                "edge_id": f"{edge_id.u}-{edge_id.v}-{edge_id.key}",
                "geometry": geometry,
            }
        )
        segment_order += 1
    return segment_order, next_target_order


def oriented_target_geometry(
    edge: EdgeRecord,
    enter_node: object,
) -> LineString:
    geom = edge.geometry
    if getattr(geom, "geom_type", None) != "LineString":
        raise ValueError("target edge geometry must be LineString")

    return geom if enter_node == edge.u else _reverse_linestring(geom)


def build_adjacent_exit_target_score_adjustments(
    previous_target_edge: EdgeRecord | None,
    remaining_edges: list[EdgeRecord],
) -> dict[EdgeId, float]:
    if previous_target_edge is None or previous_target_edge.oneway:
        return {}

    exit_node = str(previous_target_edge.v)
    reverse_edge_key = (
        str(previous_target_edge.v),
        str(previous_target_edge.u),
        str(previous_target_edge.key),
    )

    reverse_edge: EdgeRecord | None = None
    forward_edges: list[EdgeRecord] = []
    for edge in remaining_edges:
        edge_key = (str(edge.u), str(edge.v), str(edge.key))
        if edge_key == reverse_edge_key and not edge.oneway:
            reverse_edge = edge
            continue

        if str(edge.u) == exit_node:
            forward_edges.append(edge)

    if reverse_edge is None or len(forward_edges) == 0:
        return {}

    adjustments: dict[EdgeId, float] = {
        reverse_edge.edge_id: ADJACENT_REVERSE_TARGET_PENALTY_METERS
    }
    for edge in forward_edges:
        adjustments[edge.edge_id] = -ADJACENT_EXIT_TARGET_BONUS_METERS

    return adjustments


def generate_candidate_route(
    graph: nx.MultiDiGraph,
    target_edges: list[EdgeRecord],
    start_node: object,
    strategy: str,
) -> tuple[gpd.GeoDataFrame, list[EdgeId]]:
    if strategy not in STRATEGIES:
        raise ValueError(f"unsupported strategy: {strategy}")

    logger.info(
        "generate_candidate_route: strategy=%s start target_edges=%d",
        strategy,
        len(target_edges),
    )

    reverse_graph = graph.reverse(copy=False)
    dist_to_start, _ = _build_shortest_path_cache(reverse_graph, start_node)
    logger.info(
        "generate_candidate_route: strategy=%s return-distance-cache nodes=%d",
        strategy,
        len(dist_to_start),
    )

    remaining = list(target_edges)
    current_node = start_node
    route_records: list[dict[str, object]] = []
    visited_target_edges: list[EdgeId] = []
    segment_order = 1
    target_order = 1
    previous_target_edge: EdgeRecord | None = None
    unvisited_target_edges = {
        _normalize_edge_id((edge.u, edge.v, edge.key)): edge for edge in remaining
    }

    while remaining:
        if target_order == 1 or target_order % 25 == 0:
            logger.info(
                "generate_candidate_route: strategy=%s progress target_order=%d remaining=%d",
                strategy,
                target_order,
                len(remaining),
            )

        dist_from_current, path_from_current = _build_shortest_path_cache(graph, current_node)

        best_edge: EdgeRecord | None = None
        best_plan: ConnectorPlan | None = None
        best_score: float | None = None
        score_adjustments = build_adjacent_exit_target_score_adjustments(
            previous_target_edge=previous_target_edge,
            remaining_edges=remaining,
        )

        unreachable_edges: list[EdgeRecord] = []
        for edge in remaining:
            try:
                plan = choose_connector_plan(
                    edge=edge,
                    strategy=strategy,
                    dist_from_current=dist_from_current,
                    path_from_current=path_from_current,
                    dist_to_start=dist_to_start,
                )
            except ValueError as exc:
                logger.info(
                    "generate_candidate_route: strategy=%s skip unreachable target edge_id=%s error=%s",
                    strategy,
                    _normalize_edge_id((edge.u, edge.v, edge.key)),
                    exc,
                )
                unreachable_edges.append(edge)
                continue

            adjusted_score = plan.total_score + score_adjustments.get(edge.edge_id, 0.0)
            if best_score is None or adjusted_score < best_score:
                best_edge = edge
                best_plan = plan
                best_score = adjusted_score

        if best_edge is None or best_plan is None:
            logger.info(
                "generate_candidate_route: strategy=%s no more reachable target edges remaining=%d",
                strategy,
                len(remaining),
            )
            break

        segment_order, target_order = append_path_segments(
            route_records=route_records,
            graph=graph,
            path_nodes=best_plan.connector_path_nodes,
            segment_order_start=segment_order,
            segment_type=ROUTE_SEGMENT_TYPE_CONNECTOR,
            target_order=target_order,
            priority=best_edge.priority,
            unvisited_target_edges=unvisited_target_edges,
            visited_target_edges=visited_target_edges,
            next_target_order=target_order,
        )

        best_edge_key = _normalize_edge_id((best_edge.u, best_edge.v, best_edge.key))
        if best_edge_key in unvisited_target_edges:
            route_records.append(
                {
                    "segment_order": segment_order,
                    "segment_type": ROUTE_SEGMENT_TYPE_TARGET,
                    "target_order": target_order,
                    "priority": best_edge.priority,
                    "length": float(best_edge.length),
                    "pass_from_node": best_plan.enter_node,
                    "pass_to_node": best_plan.exit_node,
                    "u": best_edge.u,
                    "v": best_edge.v,
                    "key": best_edge.key,
                    "edge_id": f"{best_edge.u}-{best_edge.v}-{best_edge.key}",
                    "geometry": oriented_target_geometry(best_edge, best_plan.enter_node),
                }
            )
            segment_order += 1
            target_order += 1
            visited_target_edges.append(best_edge.edge_id)
            unvisited_target_edges.pop(best_edge_key, None)

        current_node = best_plan.exit_node
        previous_target_edge = best_edge

        remaining = [
            edge
            for edge in remaining
            if _normalize_edge_id((edge.u, edge.v, edge.key)) in unvisited_target_edges
            and edge not in unreachable_edges
        ]

    logger.info("generate_candidate_route: strategy=%s building return path", strategy)
    return_path_nodes, _ = shortest_path_nodes(graph, current_node, start_node)

    append_path_segments(
        route_records=route_records,
        graph=graph,
        path_nodes=return_path_nodes,
        segment_order_start=segment_order,
        segment_type=ROUTE_SEGMENT_TYPE_RETURN,
        target_order=None,
        priority=None,
    )

    route_gdf = gpd.GeoDataFrame(route_records, geometry="geometry", crs="EPSG:4326")
    logger.info(
        "generate_candidate_route: strategy=%s done route_rows=%d visited=%d",
        strategy,
        len(route_gdf),
        len(visited_target_edges),
    )
    return route_gdf, visited_target_edges


def evaluate_route(
    route_gdf: gpd.GeoDataFrame,
) -> dict[str, float]:
    if len(route_gdf) == 0:
        return {
            "total_length": 0.0,
            "target_length": 0.0,
            "connector_length": 0.0,
            "return_length": 0.0,
            "target_segment_count": 0.0,
            "connector_segment_count": 0.0,
            "return_segment_count": 0.0,
            "route_score": 0.0,
        }

    target_mask = build_route_segment_mask(route_gdf, ROUTE_SEGMENT_TYPE_TARGET)
    connector_mask = build_route_segment_mask(route_gdf, ROUTE_SEGMENT_TYPE_CONNECTOR)
    return_mask = build_route_segment_mask(route_gdf, ROUTE_SEGMENT_TYPE_RETURN)

    total_length = float(route_gdf["length"].sum())
    target_length = float(route_gdf.loc[target_mask, "length"].sum())
    connector_length = float(route_gdf.loc[connector_mask, "length"].sum())
    return_length = float(route_gdf.loc[return_mask, "length"].sum())

    metrics = {
        "total_length": total_length,
        "target_length": target_length,
        "connector_length": connector_length,
        "return_length": return_length,
        "target_segment_count": float(target_mask.sum()),
        "connector_segment_count": float(connector_mask.sum()),
        "return_segment_count": float(return_mask.sum()),
        "route_score": total_length,
    }
    metrics["access_length"] = metrics["connector_length"]
    metrics["access_segment_count"] = metrics["connector_segment_count"]
    return metrics


def validate_target_coverage(
    input_edges: list[EdgeRecord],
    visited_target_edges: list[EdgeId],
) -> None:
    expected = {(str(edge.u), str(edge.v), str(edge.key)) for edge in input_edges}
    actual = {(str(edge.u), str(edge.v), str(edge.key)) for edge in visited_target_edges}

    missing = expected - actual
    if missing:
        raise ValueError(f"target coverage is incomplete: missing={sorted(missing)}")


def split_target_edges_by_requested_includes(
    target_edges: list[EdgeRecord],
    included_roads: tuple[tuple[str, str, str], ...],
) -> tuple[list[EdgeRecord], list[EdgeRecord]]:
    included_lookup = _build_bidirectional_edge_lookup(included_roads)
    mandatory_edges: list[EdgeRecord] = []
    requested_edges: list[EdgeRecord] = []

    for edge in target_edges:
        edge_id = _normalize_edge_id((edge.u, edge.v, edge.key))
        if edge_id in included_lookup:
            requested_edges.append(edge)
        else:
            mandatory_edges.append(edge)

    return mandatory_edges, requested_edges


def split_target_edges_by_reachability(
    graph: nx.MultiDiGraph,
    start_node: object,
    target_edges: list[EdgeRecord],
) -> tuple[list[EdgeRecord], list[EdgeRecord]]:
    if start_node not in graph:
        raise ValueError(f"start_node is not in graph: {start_node}")

    reachable_from_start = set(nx.descendants(graph, start_node))
    reachable_from_start.add(start_node)
    can_return_to_start = set(nx.ancestors(graph, start_node))
    can_return_to_start.add(start_node)
    reachable_edges: list[EdgeRecord] = []
    unreachable_edges: list[EdgeRecord] = []

    for edge in target_edges:
        if edge.u in reachable_from_start and edge.v in can_return_to_start:
            reachable_edges.append(edge)
        else:
            unreachable_edges.append(edge)

    return reachable_edges, unreachable_edges


def normalize_visited_target_edge_ids(
    visited_target_edges: list[EdgeId],
) -> set[tuple[str, str, str]]:
    return {_normalize_edge_id((edge.u, edge.v, edge.key)) for edge in visited_target_edges}


def build_failed_included_edge_ids(
    included_roads: tuple[tuple[str, str, str], ...],
    visited_target_edges: list[EdgeId],
) -> tuple[tuple[str, str, str], ...]:
    visited_lookup = normalize_visited_target_edge_ids(visited_target_edges)
    failed = [edge_id for edge_id in included_roads if edge_id not in visited_lookup]
    return tuple(sorted(failed))


def build_failed_target_edge_ids(
    target_edges: list[EdgeRecord],
    visited_target_edges: list[EdgeId],
) -> tuple[tuple[str, str, str], ...]:
    visited_lookup = normalize_visited_target_edge_ids(visited_target_edges)
    failed = []
    for edge in target_edges:
        edge_id = _normalize_edge_id((edge.u, edge.v, edge.key))
        if edge_id not in visited_lookup:
            failed.append(edge_id)
    return tuple(sorted(set(failed)))


def build_summary_df(
    route_gdf: gpd.GeoDataFrame,
    strategy: str,
    metrics: dict[str, float],
) -> pd.DataFrame:
    target_rows = route_gdf.loc[build_route_segment_mask(route_gdf, ROUTE_SEGMENT_TYPE_TARGET)]

    row = {
        "strategy": strategy,
        "total_length": metrics["total_length"],
        "target_length": metrics["target_length"],
        "connector_length": metrics["connector_length"],
        "return_length": metrics["return_length"],
        "target_segment_count": int(metrics["target_segment_count"]),
        "connector_segment_count": int(metrics["connector_segment_count"]),
        "return_segment_count": int(metrics["return_segment_count"]),
        "route_score": metrics["route_score"],
        "visited_target_edge_count": len(target_rows),
    }
    return pd.DataFrame([row])


def build_empty_route_gdf() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(columns=ROUTE_OUTPUT_COLS, geometry="geometry", crs="EPSG:4326")


def save_route_output(route_gdf: gpd.GeoDataFrame, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if len(route_gdf) == 0:
        output_path.write_text(
            json.dumps(
                {"type": "FeatureCollection", "features": []},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return

    route_gdf.to_file(output_path, driver="GeoJSON", encoding="utf-8")


def select_start_node(
    network_edges: list[NetworkEdgeRecord],
    start_lat: float,
    start_lon: float,
) -> object:
    node_points = build_node_points(network_edges)
    start_point = Point(start_lon, start_lat)
    return nearest_node_to_point(node_points=node_points, point=start_point)


def build_candidate_results(
    graph: nx.MultiDiGraph,
    target_edges: list[EdgeRecord],
    start_node: object,
    strategies: tuple[str, ...] = STRATEGIES,
) -> list[tuple[str, gpd.GeoDataFrame, list[EdgeId], dict[str, float]]]:
    candidate_results: list[tuple[str, gpd.GeoDataFrame, list[EdgeId], dict[str, float]]] = []

    logger.info(
        "build_candidate_results: start strategies=%s target_edges=%d",
        strategies,
        len(target_edges),
    )

    for strategy in strategies:
        logger.info("build_candidate_results: strategy=%s start", strategy)

        route_gdf, visited_target_edges = generate_candidate_route(
            graph=graph,
            target_edges=target_edges,
            start_node=start_node,
            strategy=strategy,
        )
        logger.info(
            "build_candidate_results: strategy=%s route generated route_rows=%d visited=%d",
            strategy,
            len(route_gdf),
            len(visited_target_edges),
        )

        logger.info(
            "build_candidate_results: strategy=%s coverage partial visited=%d target_edges=%d",
            strategy,
            len(visited_target_edges),
            len(target_edges),
        )

        metrics = evaluate_route(route_gdf)
        logger.info(
            "build_candidate_results: strategy=%s metrics evaluated route_score=%s",
            strategy,
            metrics.get("route_score"),
        )

        candidate_results.append((strategy, route_gdf, visited_target_edges, metrics))

    if len(candidate_results) == 0:
        raise ValueError("candidate_results are empty")

    logger.info("build_candidate_results: done count=%d", len(candidate_results))
    return candidate_results


def select_best_candidate(
    candidate_results: list[tuple[str, gpd.GeoDataFrame, list[EdgeId], dict[str, float]]],
    preferred_strategy: str,
) -> tuple[str, gpd.GeoDataFrame, list[EdgeId], dict[str, float]]:
    if preferred_strategy not in STRATEGIES:
        raise ValueError(f"unsupported preferred strategy: {preferred_strategy}")

    preferred_candidates = [x for x in candidate_results if x[0] == preferred_strategy]
    if preferred_candidates:
        return min(preferred_candidates, key=lambda x: x[3]["route_score"])

    return min(candidate_results, key=lambda x: x[3]["route_score"])


def run_recalculation(
    request: RecalculationRequest,
) -> RecalculationRunResult:
    if not isinstance(request, RecalculationRequest):
        raise TypeError("request must be RecalculationRequest")

    logger.info("run_recalculation: start")
    logger.info("run_recalculation: target_input_path=%s", request.target_input_path)
    logger.info("run_recalculation: network_input_path=%s", request.network_input_path)
    logger.info("run_recalculation: strategy=%s", request.strategy)

    logger.info("run_recalculation: loading target roads")
    target_gdf = load_target_roads(request.target_input_path)
    logger.info("run_recalculation: target roads loaded rows=%d", len(target_gdf))

    logger.info("run_recalculation: loading network roads")
    network_gdf = load_network_roads(request.network_input_path)
    logger.info("run_recalculation: network roads loaded rows=%d", len(network_gdf))

    logger.info(
        "run_recalculation: filtering network roads by excluded_roads count=%d",
        len(request.excluded_roads),
    )
    filtered_network_gdf = filter_network_roads_by_excluded_roads(
        network_gdf=network_gdf,
        excluded_roads=request.excluded_roads,
    )
    logger.info(
        "run_recalculation: network roads filtered rows=%d removed=%d",
        len(filtered_network_gdf),
        len(network_gdf) - len(filtered_network_gdf),
    )

    logger.info("run_recalculation: normalizing target roads")
    target_edges = normalize_target_roads(target_gdf)
    logger.info("run_recalculation: target roads normalized count=%d", len(target_edges))
    if len(target_edges) == 0:
        logger.info("run_recalculation: no target roads; returning empty route result")
        route_gdf = build_empty_route_gdf()
        metrics = evaluate_route(route_gdf)
        summary_df = build_summary_df(
            route_gdf=route_gdf,
            strategy=request.strategy,
            metrics=metrics,
        )

        if request.save_outputs:
            logger.info("run_recalculation: saving empty route outputs")
            request.output_summary_path.parent.mkdir(parents=True, exist_ok=True)
            save_route_output(route_gdf, request.output_route_path)
            summary_df.to_csv(request.output_summary_path, index=False, encoding="utf-8-sig")
            logger.info("run_recalculation: empty route outputs saved")

        return RecalculationRunResult(
            request=request,
            route_gdf=route_gdf,
            summary_df=summary_df,
            metrics=metrics,
            selected_strategy=request.strategy,
            visited_target_edge_ids=tuple(),
            failed_target_edge_ids=tuple(),
            failed_included_edge_ids=tuple(),
        )

    mandatory_target_edges, requested_target_edges = split_target_edges_by_requested_includes(
        target_edges=target_edges,
        included_roads=request.included_roads,
    )
    logger.info(
        "run_recalculation: target roads split mandatory=%d requested=%d",
        len(mandatory_target_edges),
        len(requested_target_edges),
    )

    logger.info("run_recalculation: normalizing network roads")
    network_edges = normalize_network_roads(filtered_network_gdf)
    logger.info("run_recalculation: network roads normalized count=%d", len(network_edges))

    logger.info("run_recalculation: building graph")
    graph = build_network_graph(
        network_edges,
        conditional_roads=request.conditional_roads,
    )
    logger.info(
        "run_recalculation: graph built nodes=%d edges=%d",
        graph.number_of_nodes(),
        graph.number_of_edges(),
    )

    logger.info("run_recalculation: selecting start node")
    start_node = select_start_node(
        network_edges=network_edges,
        start_lat=request.start_lat,
        start_lon=request.start_lon,
    )
    logger.info("run_recalculation: start node selected start_node=%s", start_node)

    reachable_target_edges, unreachable_target_edges = split_target_edges_by_reachability(
        graph=graph,
        start_node=start_node,
        target_edges=target_edges,
    )
    logger.info(
        "run_recalculation: target reachability reachable=%d unreachable=%d",
        len(reachable_target_edges),
        len(unreachable_target_edges),
    )
    if len(reachable_target_edges) == 0:
        raise ValueError("all target roads are unreachable from current start node")

    reachable_mandatory_target_edges, reachable_requested_target_edges = (
        split_target_edges_by_requested_includes(
            target_edges=reachable_target_edges,
            included_roads=request.included_roads,
        )
    )

    target_edges_for_validation = reachable_target_edges
    logger.info("run_recalculation: building candidate results")
    try:
        candidate_results = build_candidate_results(
            graph=graph,
            target_edges=reachable_target_edges,
            start_node=start_node,
            strategies=(request.strategy,),
        )
    except Exception as exc:
        if len(reachable_requested_target_edges) == 0:
            raise

        logger.info(
            "run_recalculation: retrying without requested included target edges after failure: %s",
            exc,
        )
        recalculable_requested_edges: list[EdgeRecord] = []
        for requested_edge in reachable_requested_target_edges:
            trial_target_edges = (
                reachable_mandatory_target_edges
                + recalculable_requested_edges
                + [requested_edge]
            )
            try:
                build_candidate_results(
                    graph=graph,
                    target_edges=trial_target_edges,
                    start_node=start_node,
                    strategies=(request.strategy,),
                )
            except Exception as trial_exc:
                logger.info(
                    "run_recalculation: requested included target edge is unreachable edge_id=%s error=%s",
                    _normalize_edge_id((requested_edge.u, requested_edge.v, requested_edge.key)),
                    trial_exc,
                )
                continue

            recalculable_requested_edges.append(requested_edge)

        target_edges_for_validation = reachable_mandatory_target_edges + recalculable_requested_edges
        candidate_results = build_candidate_results(
            graph=graph,
            target_edges=target_edges_for_validation,
            start_node=start_node,
            strategies=(request.strategy,),
        )
    logger.info("run_recalculation: candidate results built count=%d", len(candidate_results))

    logger.info("run_recalculation: selecting best candidate")
    selected_strategy, route_gdf, visited_target_edges, metrics = select_best_candidate(
        candidate_results=candidate_results,
        preferred_strategy=request.strategy,
    )
    logger.info(
        "run_recalculation: best candidate selected strategy=%s route_rows=%d",
        selected_strategy,
        len(route_gdf),
    )

    failed_target_edge_ids = build_failed_target_edge_ids(
        target_edges=target_edges,
        visited_target_edges=visited_target_edges,
    )
    logger.info(
        "run_recalculation: target coverage checked visited=%d failed=%d",
        len(visited_target_edges),
        len(failed_target_edge_ids),
    )
    failed_included_edge_ids = build_failed_included_edge_ids(
        included_roads=request.included_roads,
        visited_target_edges=visited_target_edges,
    )
    logger.info(
        "run_recalculation: failed included edges count=%d",
        len(failed_included_edge_ids),
    )

    logger.info("run_recalculation: building summary")
    summary_df = build_summary_df(
        route_gdf=route_gdf,
        strategy=selected_strategy,
        metrics=metrics,
    )
    logger.info("run_recalculation: summary built rows=%d", len(summary_df))

    if request.save_outputs:
        logger.info("run_recalculation: saving outputs")
        request.output_summary_path.parent.mkdir(parents=True, exist_ok=True)
        save_route_output(route_gdf, request.output_route_path)
        summary_df.to_csv(request.output_summary_path, index=False, encoding="utf-8-sig")
        logger.info("run_recalculation: outputs saved")

    logger.info("run_recalculation: done")

    return RecalculationRunResult(
        request=request,
        route_gdf=route_gdf,
        summary_df=summary_df,
        metrics=metrics,
        selected_strategy=selected_strategy,
        visited_target_edge_ids=tuple(
            sorted(
                _normalize_edge_id((edge.u, edge.v, edge.key))
                for edge in visited_target_edges
            )
        ),
        failed_target_edge_ids=failed_target_edge_ids,
        failed_included_edge_ids=failed_included_edge_ids,
    )
