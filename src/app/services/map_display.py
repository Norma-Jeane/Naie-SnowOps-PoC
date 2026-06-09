#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
map_display service

■ 役割
- GeoJSON 表示用データ加工
- 方向マーカー生成
- 初期表示状態計算
- 地図クリック署名生成

■ 表示方針
- 背景道路網は最下層
- 操作対象道路は背景道路網の上
- 現実的ルートは最前面
- 選択道路の色は「現在状態」ではなく「次操作」を示す
  - 選択中かつ ON  : 黒      （次に OFF にする対象）
  - 選択中かつ OFF : マゼンダ（次に ON に戻す対象）
"""

from __future__ import annotations

import json
import math
from collections import defaultdict

import numpy as np
import pandas as pd

ROUTE_SEGMENT_TYPE_COLORS: dict[str, list[int]] = {
    "target": [0, 0, 255, 255],
    "connector": [0, 255, 255, 255],
    "return": [0, 191, 255, 255],
}


def normalize_route_segment_type(segment_type: object) -> str:
    text = str(segment_type).strip().lower()
    if text == "access":
        return "connector"
    if text in {"target", "connector", "return"}:
        return text
    return "target"


def is_false_like(value: object) -> bool:
    if isinstance(value, bool):
        return value is False
    return str(value).strip().lower() == "false"


def route_segment_type_to_base_display_state(segment_type: object) -> str:
    return normalize_route_segment_type(segment_type)


def build_diff_display_state(instruction_state: str) -> str:
    if instruction_state == "exclude":
        return "black"
    if instruction_state == "conditional":
        return "orange"
    if instruction_state == "include_failed":
        return "red"
    if instruction_state == "include":
        return "magenta"
    return "transparent"


def build_operable_line_width(base_display_state: str, diff_display_state: str) -> int:
    if diff_display_state != "transparent":
        return 5
    if base_display_state == "candidate":
        return 2
    return 5


def reverse_edge_id(edge_id: tuple[object, object, object]) -> tuple[object, object, object]:
    u, v, key = edge_id
    return (v, u, key)


def build_bidirectional_edge_lookup(
    edge_ids: set[tuple[object, object, object]],
) -> set[tuple[object, object, object]]:
    lookup = set(edge_ids)
    lookup.update(reverse_edge_id(edge_id) for edge_id in edge_ids)
    return lookup


def normalize_edge_id_for_display(edge_id: tuple[object, object, object]) -> tuple[str, str, str]:
    u, v, key = edge_id
    return (str(u).strip(), str(v).strip(), str(key).strip())


def normalize_json_value(value: object) -> object:
    if value is None:
        return None

    if isinstance(value, np.ndarray):
        return [normalize_json_value(x) for x in value.tolist()]

    if isinstance(value, (np.integer,)):
        return int(value)

    if isinstance(value, (np.floating,)):
        if math.isnan(float(value)):
            return None
        return float(value)

    if isinstance(value, (np.bool_,)):
        return bool(value)

    if isinstance(value, (list, tuple)):
        return [normalize_json_value(x) for x in value]

    try:
        if pd.isna(value):
            return None
    except Exception:
        pass

    return value


def sanitize_gdf_for_geojson(gdf):
    sanitized = gdf.copy()
    for col in sanitized.columns:
        if col == "geometry":
            continue
        sanitized[col] = sanitized[col].apply(normalize_json_value)
    return sanitized


def build_roads_geojson(
    *,
    roads_gdf,
    operable_roads_gdf,
    selected_road_id,
    excluded_roads,
    conditional_roads,
    included_roads,
    failed_included_roads,
    failed_partial_roads=None,
    after_black_clear_roads=None,
    current_route_edge_ids,
    current_route_edge_display_states=None,
    ensure_wgs84,
    sanitize_gdf_for_geojson_fn,
    normalize_edge_id,
    is_excluded_road,
    is_road_in_set,
    suppressed_base_edge_ids=None,
) -> dict:
    roads_wgs84 = ensure_wgs84(roads_gdf.copy())
    operable_wgs84 = ensure_wgs84(operable_roads_gdf.copy())

    features: list[dict[str, object]] = []

    background = sanitize_gdf_for_geojson_fn(roads_wgs84)
    background_json = json.loads(background.to_json())
    for feature in background_json["features"]:
        props = feature.setdefault("properties", {})
        props["display_kind"] = "background"
        props["display_order"] = 0
        props["base_display_state"] = "non_operable"
        props["diff_display_state"] = "transparent"
        props["display_state"] = "non_operable"
        props["line_color"] = [220, 220, 220, 255]
        props["line_width"] = 2
        props["is_selected"] = False
        props["is_excluded"] = False
        props["is_conditional"] = False
        props["is_included"] = False
        props["is_failed_included"] = False
        props["is_failed_partial"] = False
        props["instruction_state"] = "none"
        props["no_instruction_cycle_hint"] = ""
        features.append(feature)

    operable = sanitize_gdf_for_geojson_fn(operable_wgs84)
    operable_json = json.loads(operable.to_json())

    selected_normalized = (
        normalize_edge_id(selected_road_id) if selected_road_id is not None else None
    )
    normalized_route_edge_ids = (
        {normalize_edge_id(edge_id) for edge_id in current_route_edge_ids}
        if current_route_edge_ids is not None
        else set()
    )
    normalized_route_edge_display_states = (
        {
            normalize_edge_id(edge_id): route_segment_type_to_base_display_state(display_state)
            for edge_id, display_state in dict(current_route_edge_display_states).items()
        }
        if current_route_edge_display_states is not None
        else {}
    )
    normalized_instruction_edge_ids = (
        {normalize_edge_id(edge_id) for edge_id in set(excluded_roads or set())}
        | {normalize_edge_id(edge_id) for edge_id in set(conditional_roads or set())}
        | {normalize_edge_id(edge_id) for edge_id in set(included_roads or set())}
        | {normalize_edge_id(edge_id) for edge_id in set(failed_included_roads or set())}
    )
    normalized_failed_partial_edge_ids = {
        normalize_edge_id(edge_id) for edge_id in set(failed_partial_roads or set())
    }
    normalized_suppressed_base_edge_ids = {
        normalize_edge_id(edge_id) for edge_id in set(suppressed_base_edge_ids or set())
    }
    normalized_after_black_clear_edge_ids = {
        normalize_edge_id(edge_id) for edge_id in set(after_black_clear_roads or set())
    }
    bidirectional_after_black_clear_edge_ids = build_bidirectional_edge_lookup(
        normalized_after_black_clear_edge_ids
    )
    route_display_edge_ids = set(normalized_route_edge_ids) | set(
        normalized_route_edge_display_states.keys()
    )
    derived_operable_edge_ids = (
        route_display_edge_ids
        | build_bidirectional_edge_lookup(
            normalized_instruction_edge_ids | normalized_after_black_clear_edge_ids
        )
    )
    existing_operable_edge_ids: set[tuple[object, object, object]] = set()

    def get_route_base_display_state(
        edge_id: tuple[object, object, object],
    ) -> str:
        return normalized_route_edge_display_states.get(
            edge_id,
            "target",
        )

    def get_instruction_state(
        edge_id: tuple[object, object, object],
    ) -> str:
        if is_excluded_road(edge_id, excluded_roads):
            return "exclude"
        if is_road_in_set(edge_id, failed_included_roads):
            return "include_failed"
        if is_road_in_set(edge_id, included_roads):
            return "include"
        if is_road_in_set(edge_id, conditional_roads):
            return "conditional"
        return "none"

    for feature in operable_json["features"]:
        props = feature.setdefault("properties", {})
        edge_id = normalize_edge_id((props.get("u"), props.get("v"), props.get("key")))
        existing_operable_edge_ids.add(edge_id)
        instruction_state = get_instruction_state(edge_id)
        excluded = instruction_state == "exclude"
        conditional = instruction_state == "conditional"
        included = instruction_state == "include"
        failed_included = instruction_state == "include_failed"
        failed_partial = edge_id in normalized_failed_partial_edge_ids
        is_selected = selected_normalized is not None and edge_id == selected_normalized
        is_on_current_route = (
            edge_id in normalized_route_edge_ids
            or edge_id in normalized_route_edge_display_states
        )

        base_display_state = normalized_route_edge_display_states.get(
            edge_id,
            "target" if is_on_current_route else "candidate",
        )
        diff_display_state = build_diff_display_state(instruction_state)
        display_state = (
            diff_display_state if diff_display_state != "transparent" else base_display_state
        )

        line_color = [105, 105, 105, 255]
        line_width = build_operable_line_width(base_display_state, diff_display_state)

        props["display_kind"] = "operable"
        props["display_order"] = 1
        props["base_display_state"] = base_display_state
        props["diff_display_state"] = diff_display_state
        props["line_color"] = line_color
        props["line_width"] = line_width
        props["is_selected"] = is_selected
        props["is_excluded"] = excluded
        props["is_conditional"] = conditional
        props["is_included"] = included
        props["is_failed_included"] = failed_included
        props["is_failed_partial"] = failed_partial
        props["is_base_suppressed_by_final_state"] = (
            edge_id in normalized_suppressed_base_edge_ids
        )
        props["is_on_current_route"] = is_on_current_route
        props["instruction_state"] = instruction_state
        props["no_instruction_cycle_hint"] = (
            "after_black_clear"
            if edge_id in bidirectional_after_black_clear_edge_ids
            else ""
        )
        props["display_state"] = display_state
        features.append(feature)

    for feature in background_json["features"]:
        props = feature.setdefault("properties", {})
        edge_id = normalize_edge_id((props.get("u"), props.get("v"), props.get("key")))
        if edge_id not in derived_operable_edge_ids:
            continue
        if edge_id in existing_operable_edge_ids:
            continue

        route_feature = {
            "type": feature.get("type", "Feature"),
            "geometry": feature.get("geometry"),
            "properties": dict(props),
        }
        route_props = route_feature.setdefault("properties", {})
        instruction_state = get_instruction_state(edge_id)
        diff_display_state = build_diff_display_state(instruction_state)
        base_display_state = (
            get_route_base_display_state(edge_id)
            if edge_id in route_display_edge_ids
            else "candidate"
        )
        display_state = (
            diff_display_state if diff_display_state != "transparent" else base_display_state
        )
        is_selected = selected_normalized is not None and edge_id == selected_normalized

        route_props["display_kind"] = "operable"
        route_props["display_order"] = 1
        route_props["base_display_state"] = base_display_state
        route_props["diff_display_state"] = diff_display_state
        route_props["line_color"] = [105, 105, 105, 255]
        route_props["line_width"] = build_operable_line_width(
            base_display_state,
            diff_display_state,
        )
        route_props["is_selected"] = is_selected
        route_props["is_excluded"] = instruction_state == "exclude"
        route_props["is_conditional"] = instruction_state == "conditional"
        route_props["is_included"] = instruction_state == "include"
        route_props["is_failed_included"] = instruction_state == "include_failed"
        route_props["is_failed_partial"] = edge_id in normalized_failed_partial_edge_ids
        route_props["is_base_suppressed_by_final_state"] = (
            edge_id in normalized_suppressed_base_edge_ids
        )
        route_props["is_on_current_route"] = edge_id in route_display_edge_ids
        route_props["instruction_state"] = instruction_state
        route_props["no_instruction_cycle_hint"] = (
            "after_black_clear"
            if edge_id in bidirectional_after_black_clear_edge_ids
            else ""
        )
        route_props["display_state"] = display_state
        route_props["source_kind"] = (
            "route_derived_operable"
            if edge_id in route_display_edge_ids
            else "instruction_derived_operable"
        )
        features.append(route_feature)

    return {
        "type": "FeatureCollection",
        "features": features,
    }


def build_route_geojson(
    *,
    route_gdf,
    suppressed_route_edge_ids=None,
    ensure_wgs84,
    sanitize_gdf_for_geojson_fn,
) -> dict:
    normalized_suppressed_route_edge_ids = {
        normalize_edge_id_for_display(edge_id)
        for edge_id in set(suppressed_route_edge_ids or set())
    }
    route_wgs84 = ensure_wgs84(route_gdf.copy())
    route_wgs84 = collapse_route_display_rows(route_wgs84)
    safe_gdf = sanitize_gdf_for_geojson_fn(route_wgs84)
    route_json = json.loads(safe_gdf.to_json())

    for feature in route_json["features"]:
        props = feature.setdefault("properties", {})
        edge_id = normalize_edge_id_for_display((props.get("u"), props.get("v"), props.get("key")))
        segment_type = normalize_route_segment_type(props.get("segment_type"))
        base_display_state = route_segment_type_to_base_display_state(segment_type)
        props["display_kind"] = "route"
        props["display_order"] = 2
        props["segment_type"] = segment_type
        props["base_display_state"] = base_display_state
        props["diff_display_state"] = "transparent"
        props["display_state"] = base_display_state
        props["line_color"] = ROUTE_SEGMENT_TYPE_COLORS.get(
            base_display_state,
            ROUTE_SEGMENT_TYPE_COLORS["target"],
        )
        props["line_width"] = 6
        props["is_route_suppressed_by_final_state"] = (
            edge_id in normalized_suppressed_route_edge_ids
        )

    return route_json


def collapse_route_display_rows(route_gdf):
    required_cols = {"u", "v", "key", "segment_type"}
    if not required_cols.issubset(route_gdf.columns):
        return route_gdf

    priority = {"target": 3, "connector": 2, "return": 1}
    selected_indexes: dict[tuple[str, str, str], int] = {}
    selected_priorities: dict[tuple[str, str, str], int] = {}

    for index, row in route_gdf.iterrows():
        edge_key = (str(row["u"]), str(row["v"]), str(row["key"]))
        if "oneway" in route_gdf.columns and is_false_like(row.get("oneway")):
            edge_key = tuple(sorted([str(row["u"]), str(row["v"])])) + (str(row["key"]),)
        segment_type = normalize_route_segment_type(row.get("segment_type"))
        segment_priority = priority.get(segment_type, 0)
        current_priority = selected_priorities.get(edge_key, -1)

        if segment_priority > current_priority:
            selected_indexes[edge_key] = index
            selected_priorities[edge_key] = segment_priority

    if len(selected_indexes) == len(route_gdf):
        return route_gdf

    return route_gdf.loc[list(selected_indexes.values())].copy()


def compute_arrow_angle_from_coords(x1: float, y1: float, x2: float, y2: float) -> float:
    dx = x2 - x1
    dy = y2 - y1
    if abs(dx) < 1e-12 and abs(dy) < 1e-12:
        return 0.0
    return math.degrees(math.atan2(dy, dx))


def iter_line_geometries(geom) -> list[object]:
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "LineString":
        return [geom]
    if geom.geom_type == "MultiLineString":
        return [g for g in geom.geoms if g is not None and not g.is_empty]
    return []


def sort_route_gdf(route_gdf, ensure_wgs84):
    route_wgs84 = ensure_wgs84(route_gdf.copy())
    ordered = route_wgs84.copy()
    if "segment_order" in ordered.columns:
        ordered = ordered.sort_values("segment_order").reset_index(drop=True)
    return ordered


def line_coords(line) -> list[tuple[float, float]]:
    coords = list(line.coords)
    return [(float(x), float(y)) for x, y in coords]


def append_path_coords(
    path: list[tuple[float, float]],
    coords: list[tuple[float, float]],
) -> None:
    if len(coords) == 0:
        return

    next_coords = orient_coords_for_path(path, coords)

    if path and path[-1] == next_coords[0]:
        path.extend(next_coords[1:])
        return
    if path and math.hypot(path[-1][0] - next_coords[0][0], path[-1][1] - next_coords[0][1]) < 1e-10:
        path.extend(next_coords[1:])
        return
    path.extend(next_coords)


def orient_coords_for_path(
    path: list[tuple[float, float]],
    coords: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    if not path or len(coords) < 2:
        return coords

    current_end = path[-1]
    forward_distance = math.hypot(current_end[0] - coords[0][0], current_end[1] - coords[0][1])
    reverse_distance = math.hypot(current_end[0] - coords[-1][0], current_end[1] - coords[-1][1])
    if reverse_distance < forward_distance:
        return list(reversed(coords))
    return coords


def build_point_dict(coord: tuple[float, float]) -> dict[str, float]:
    return {
        "lat": float(coord[1]),
        "lon": float(coord[0]),
    }


def build_path_points(coords: list[tuple[float, float]]) -> list[dict[str, float]]:
    return [build_point_dict(coord) for coord in coords]


def rounded_coord_key(coord: tuple[float, float]) -> str:
    return f"{coord[0]:.7f},{coord[1]:.7f}"


def row_edge_value(row, column: str) -> object | None:
    if column not in row.index:
        return None
    value = row.get(column)
    if pd.isna(value):
        return None
    return normalize_json_value(value)


def build_undirected_edge_key(row, coords: list[tuple[float, float]]) -> str:
    u = row_edge_value(row, "u")
    v = row_edge_value(row, "v")
    key = row_edge_value(row, "key")

    if u is not None and v is not None:
        a, b = sorted([str(u), str(v)])
        if key is not None:
            return f"uvk:{a}|{b}|{key}"
        return f"uv:{a}|{b}"

    if len(coords) >= 2:
        a, b = sorted([rounded_coord_key(coords[0]), rounded_coord_key(coords[-1])])
        return f"geom:{a}|{b}"

    return "geom:invalid"


def canonical_closed_coord_key(coords: list[tuple[float, float]]) -> str:
    coord_keys = [rounded_coord_key(coord) for coord in coords]
    if len(coord_keys) >= 2 and coord_keys[0] == coord_keys[-1]:
        coord_keys = coord_keys[:-1]
    if len(coord_keys) == 0:
        return "invalid"

    candidates: list[str] = []
    for values in (coord_keys, list(reversed(coord_keys))):
        for index in range(len(values)):
            candidates.append("|".join(values[index:] + values[:index]))
    return min(candidates)


def build_route_cycle_offset_group_key(segment: dict[str, object]) -> str:
    coords = segment.get("coords")
    if isinstance(coords, list) and len(coords) >= 2:
        first = coords[0]
        last = coords[-1]
        if rounded_coord_key(first) == rounded_coord_key(last):
            return "closed_geom:" + canonical_closed_coord_key(coords)
    return str(segment["undirected_edge_key"])


def edge_direction_for_coords(coords: list[tuple[float, float]]) -> str:
    if len(coords) < 2:
        return "forward"
    start_key = rounded_coord_key(coords[0])
    end_key = rounded_coord_key(coords[-1])
    canonical_start, canonical_end = sorted([start_key, end_key])
    if start_key == canonical_start and end_key == canonical_end:
        return "forward"
    return "reverse"


def closed_loop_direction_for_coords(coords: list[tuple[float, float]]) -> str:
    if len(coords) < 4 or rounded_coord_key(coords[0]) != rounded_coord_key(coords[-1]):
        return edge_direction_for_coords(coords)

    area = 0.0
    for current, nxt in zip(coords, coords[1:]):
        area += current[0] * nxt[1] - nxt[0] * current[1]
    if area > 0:
        return "closed_ccw"
    if area < 0:
        return "closed_cw"
    return "closed_flat"


def route_pass_node_value(row, column: str) -> object | None:
    if column not in row.index:
        return None
    value = row.get(column)
    if pd.isna(value):
        return None
    return normalize_json_value(value)


def route_pass_direction_key(segment: dict[str, object]) -> tuple[str, str]:
    pass_from_node = segment.get("pass_from_node")
    pass_to_node = segment.get("pass_to_node")
    coords = segment["coords"]
    if pass_from_node is not None and pass_to_node is not None and pass_from_node != pass_to_node:
        return ("pass_nodes", f"{pass_from_node}->{pass_to_node}")

    return ("geometry", closed_loop_direction_for_coords(coords))  # type: ignore[arg-type]


def route_display_edge_direction(segment: dict[str, object]) -> str:
    pass_from_node = segment.get("pass_from_node")
    pass_to_node = segment.get("pass_to_node")
    if pass_from_node is not None and pass_to_node is not None:
        pass_from_key = str(pass_from_node)
        pass_to_key = str(pass_to_node)
        return "forward" if pass_from_key <= pass_to_key else "reverse"

    coords = segment["coords"]
    return edge_direction_for_coords(coords)  # type: ignore[arg-type]


def coord_angle(
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    return float(compute_arrow_angle_from_coords(start[0], start[1], end[0], end[1]))


def terminal_path_angle(coords: list[tuple[float, float]]) -> float:
    if len(coords) < 2:
        return 0.0
    for index in range(len(coords) - 1, 0, -1):
        if coords[index] != coords[index - 1]:
            return coord_angle(coords[index - 1], coords[index])
    return 0.0


def route_segment_order_sort_value(value: object, fallback: int) -> tuple[float, int]:
    try:
        parsed = float(value)  # type: ignore[arg-type]
        if math.isfinite(parsed):
            return (parsed, fallback)
    except (TypeError, ValueError):
        pass
    return (float(fallback), fallback)


def summarize_route_cycle_segments(
    raw_segments: list[dict[str, object]],
) -> list[dict[str, object]]:
    representative_by_direction: dict[tuple[str, str], dict[str, object]] = {}
    grouped_by_direction: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)

    for index, segment in enumerate(raw_segments):
        edge_key = str(segment["undirected_edge_key"])
        pass_direction_kind, pass_direction_value = route_pass_direction_key(segment)
        edge_direction = route_display_edge_direction(segment)
        direction_key = (edge_key, f"{pass_direction_kind}:{pass_direction_value}")
        grouped_by_direction[direction_key].append(segment)

        current = representative_by_direction.get(direction_key)
        if current is None or route_segment_order_sort_value(
            segment.get("segment_order"),
            index,
        ) < route_segment_order_sort_value(
            current.get("segment_order"),
            int(current.get("_raw_index", index)),
        ):
            representative_by_direction[direction_key] = {
                **segment,
                "_raw_index": index,
                "edge_direction": edge_direction,
                "pass_direction_kind": pass_direction_kind,
                "pass_direction_value": pass_direction_value,
            }

    representatives = sorted(
        representative_by_direction.values(),
        key=lambda segment: route_segment_order_sort_value(
            segment.get("segment_order"),
            int(segment.get("_raw_index", 0)),
        ),
    )

    retained_direction_counts: dict[tuple[str, str], int] = defaultdict(int)
    for segment in representatives:
        edge_key = build_route_cycle_offset_group_key(segment)
        pass_direction_kind = str(segment.get("pass_direction_kind", "geometry"))
        pass_direction_value = str(
            segment.get("pass_direction_value", segment.get("edge_direction", "forward"))
        )
        retained_direction_counts[
            (edge_key, f"{pass_direction_kind}:{pass_direction_value}")
        ] += 1

    retained_edge_indexes: dict[tuple[str, str], int] = defaultdict(int)
    segments: list[dict[str, object]] = []
    for segment in representatives:
        original_edge_key = str(segment["undirected_edge_key"])
        edge_key = build_route_cycle_offset_group_key(segment)
        edge_direction = str(segment["edge_direction"])
        pass_direction_kind = str(segment.get("pass_direction_kind", "geometry"))
        pass_direction_value = str(segment.get("pass_direction_value", edge_direction))
        direction_key = (original_edge_key, f"{pass_direction_kind}:{pass_direction_value}")
        original_segments = grouped_by_direction[direction_key]
        offset_count_key = (edge_key, f"{pass_direction_kind}:{pass_direction_value}")
        retained_repeat_count = retained_direction_counts[offset_count_key]
        retained_repeat_index = retained_edge_indexes[offset_count_key]
        retained_edge_indexes[offset_count_key] += 1
        offset_lane = retained_repeat_index if retained_repeat_count >= 2 else 0
        coords = segment["coords"]

        segments.append(
            {
                "segment_order": segment["segment_order"],
                "segment_type": segment["segment_type"],
                "path": build_path_points(coords),  # type: ignore[arg-type]
                "pass_from_node": segment.get("pass_from_node"),
                "pass_to_node": segment.get("pass_to_node"),
                "undirected_edge_key": str(segment["undirected_edge_key"]),
                "offset_group_key": edge_key,
                "edge_direction": edge_direction,
                "pass_direction_kind": pass_direction_kind,
                "pass_direction_value": pass_direction_value,
                "edge_repeat_count": int(retained_repeat_count),
                "edge_repeat_index": int(retained_repeat_index),
                "direction_pass_count": 1,
                "direction_pass_index": 0,
                "offset_side": "left",
                "offset_lane": int(offset_lane),
                "original_pass_count": int(len(original_segments)),
                "original_segment_orders": [
                    original_segment["segment_order"] for original_segment in original_segments
                ],
                "original_segment_types": [
                    original_segment["segment_type"] for original_segment in original_segments
                ],
                "original_pass_from_nodes": [
                    original_segment.get("pass_from_node") for original_segment in original_segments
                ],
                "original_pass_to_nodes": [
                    original_segment.get("pass_to_node") for original_segment in original_segments
                ],
            }
        )

    return segments


def build_raw_pass_route_cycle_segments(
    raw_segments: list[dict[str, object]],
) -> list[dict[str, object]]:
    edge_counts: dict[tuple[str, str], int] = defaultdict(int)
    direction_counts: dict[tuple[str, str], int] = defaultdict(int)
    for segment in raw_segments:
        edge_key = build_route_cycle_offset_group_key(segment)
        pass_direction_kind, pass_direction_value = route_pass_direction_key(segment)
        direction_key = (edge_key, f"{pass_direction_kind}:{pass_direction_value}")
        edge_counts[direction_key] += 1
        direction_counts[direction_key] += 1

    edge_indexes: dict[tuple[str, str], int] = defaultdict(int)
    direction_indexes: dict[tuple[str, str], int] = defaultdict(int)
    segments: list[dict[str, object]] = []
    for segment in raw_segments:
        edge_key = build_route_cycle_offset_group_key(segment)
        edge_direction = route_display_edge_direction(segment)
        pass_direction_kind, pass_direction_value = route_pass_direction_key(segment)
        direction_key = (edge_key, f"{pass_direction_kind}:{pass_direction_value}")
        edge_repeat_count = edge_counts[direction_key]
        edge_repeat_index = edge_indexes[direction_key]
        edge_indexes[direction_key] += 1
        direction_pass_count = direction_counts[direction_key]
        direction_pass_index = direction_indexes[direction_key]
        direction_indexes[direction_key] += 1
        offset_lane = edge_repeat_index if edge_repeat_count >= 2 else 0
        coords = segment["coords"]
        u = segment.get("u")
        v = segment.get("v")
        key = segment.get("key")

        segments.append(
            {
                "segment_order": segment["segment_order"],
                "segment_type": segment["segment_type"],
                "path": build_path_points(coords),  # type: ignore[arg-type]
                "pass_from_node": segment.get("pass_from_node"),
                "pass_to_node": segment.get("pass_to_node"),
                "u": u,
                "v": v,
                "key": key,
                "edge_id": {"u": u, "v": v, "key": key}
                if u is not None and v is not None and key is not None
                else None,
                "length": segment.get("length"),
                "undirected_edge_key": str(segment["undirected_edge_key"]),
                "edge_group_key": edge_key,
                "offset_group_key": edge_key,
                "lane_group_key": direction_key[1],
                "edge_direction": edge_direction,
                "pass_direction_kind": pass_direction_kind,
                "pass_direction_value": pass_direction_value,
                "edge_repeat_count": int(edge_repeat_count),
                "edge_repeat_index": int(edge_repeat_index),
                "direction_pass_count": int(direction_pass_count),
                "direction_pass_index": int(direction_pass_index),
                "lane_count": int(edge_repeat_count),
                "lane_index": int(edge_repeat_index),
                "offset_side": "left",
                "offset_lane": int(offset_lane),
                "original_pass_count": 1,
                "original_segment_orders": [segment["segment_order"]],
                "original_segment_types": [segment["segment_type"]],
                "original_pass_from_nodes": [segment.get("pass_from_node")],
                "original_pass_to_nodes": [segment.get("pass_to_node")],
            }
        )

    return segments


def build_route_cycle_guide(
    *,
    route_gdf,
    ensure_wgs84,
) -> dict[str, object] | None:
    ordered = sort_route_gdf(route_gdf, ensure_wgs84)
    if len(ordered) == 0:
        return None

    path: list[tuple[float, float]] = []
    included_segment_types: set[str] = set()
    segment_orders: list[object] = []
    raw_segments: list[dict[str, object]] = []
    segment_count = 0

    for row_index, row in ordered.iterrows():
        segment_type = normalize_route_segment_type(row.get("segment_type"))
        segment_order = row.get("segment_order", row_index + 1)

        for line in iter_line_geometries(row.geometry):
            coords = line_coords(line)
            if len(coords) < 2:
                continue
            pass_from_node = route_pass_node_value(row, "pass_from_node")
            pass_to_node = route_pass_node_value(row, "pass_to_node")
            has_pass_direction = pass_from_node is not None and pass_to_node is not None
            oriented = coords if has_pass_direction else orient_coords_for_path(path, coords)
            segment_path = list(oriented)
            if path and path[-1] == oriented[0]:
                oriented_for_route = oriented[1:]
            elif (
                path
                and math.hypot(path[-1][0] - oriented[0][0], path[-1][1] - oriented[0][1]) < 1e-10
            ):
                oriented_for_route = oriented[1:]
            else:
                oriented_for_route = oriented
            if len(oriented_for_route) == 0:
                continue
            path.extend(oriented_for_route)
            included_segment_types.add(segment_type)
            segment_orders.append(segment_order)
            raw_segments.append(
                {
                    "segment_order": normalize_json_value(segment_order),
                    "segment_type": segment_type,
                    "coords": segment_path,
                    "pass_from_node": pass_from_node,
                    "pass_to_node": pass_to_node,
                    "u": row_edge_value(row, "u"),
                    "v": row_edge_value(row, "v"),
                    "key": row_edge_value(row, "key"),
                    "length": row_edge_value(row, "length"),
                    "undirected_edge_key": build_undirected_edge_key(row, segment_path),
                }
            )
            segment_count += 1

    if len(path) < 2:
        return None

    segments = summarize_route_cycle_segments(raw_segments)
    raw_pass_segments = build_raw_pass_route_cycle_segments(raw_segments)

    return {
        "kind": "route_cycle",
        "path": build_path_points(path),
        "segments": segments,
        "raw_pass_segments": raw_pass_segments,
        "start": build_point_dict(path[0]),
        "end": build_point_dict(path[-1]),
        "first_segment_order": normalize_json_value(segment_orders[0]) if segment_orders else None,
        "last_segment_order": normalize_json_value(segment_orders[-1]) if segment_orders else None,
        "segment_count": int(segment_count),
        "display_segment_count": int(len(segments)),
        "raw_pass_segment_count": int(len(raw_pass_segments)),
        "included_segment_types": sorted(included_segment_types),
    }


def build_initial_view_state(
    *,
    loaded,
    current_start_point,
    ensure_wgs84,
) -> dict[str, float]:
    route_gdf = loaded.get("route")

    if current_start_point is not None:
        return {
            "lat": float(current_start_point["lat"]),
            "lon": float(current_start_point["lon"]),
            "zoom": 14.0,
        }

    if route_gdf is not None and len(route_gdf) > 0:
        route_wgs84 = ensure_wgs84(route_gdf.copy())
        bounds = route_wgs84.total_bounds.tolist()
        return {
            "lat": float((bounds[1] + bounds[3]) / 2.0),
            "lon": float((bounds[0] + bounds[2]) / 2.0),
            "zoom": 12.0,
        }

    roads_gdf = loaded.get("roads")
    if roads_gdf is not None and len(roads_gdf) > 0:
        roads_wgs84 = ensure_wgs84(roads_gdf.copy())
        bounds = roads_wgs84.total_bounds.tolist()
        return {
            "lat": float((bounds[1] + bounds[3]) / 2.0),
            "lon": float((bounds[0] + bounds[2]) / 2.0),
            "zoom": 12.0,
        }

    return {
        "lat": 43.426,
        "lon": 141.886,
        "zoom": 12.0,
    }


def build_map_click_signature(event: dict[str, object]) -> str:
    lat = round(float(event["lat"]), 8)
    lon = round(float(event["lon"]), 8)
    return f"{lat:.8f},{lon:.8f}"
