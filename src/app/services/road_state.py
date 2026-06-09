#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
road_state service

■ 役割
- 道路識別子の正規化
- 選択道路 / 除外道路状態の管理
- 道路表示名の整形
- 除外道路一覧の要約生成
"""

from __future__ import annotations

import re

import pandas as pd


INTEGER_LIKE_EDGE_ID_RE = re.compile(r"^(-?\d+)(?:\.0+)?$")


def normalize_edge_id_value(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass

    text = str(value).strip()
    if text == "" or text.lower() == "nan":
        return ""

    integer_like_match = INTEGER_LIKE_EDGE_ID_RE.fullmatch(text)
    if integer_like_match:
        return integer_like_match.group(1)

    return text


def normalize_edge_id(edge_id: tuple[object, object, object]) -> tuple[str, str, str]:
    u, v, key = edge_id
    return (
        normalize_edge_id_value(u),
        normalize_edge_id_value(v),
        normalize_edge_id_value(key),
    )


def normalize_edge_id_list(
    edge_ids: set[tuple[object, object, object]] | list[tuple[object, object, object]],
) -> list[tuple[str, str, str]]:
    normalized = [normalize_edge_id(x) for x in edge_ids]
    normalized.sort(key=lambda x: (x[0], x[1], x[2]))
    return normalized


def build_road_edge_id(row: pd.Series | dict[str, object]) -> tuple[str, str, str]:
    for col in ["u", "v", "key"]:
        if col not in row:
            raise ValueError(f"required road id column is missing: {col}")
    return normalize_edge_id((row["u"], row["v"], row["key"]))


def format_road_edge_id(edge_id: tuple[object, object, object] | None) -> str:
    if edge_id is None:
        return "未選択"
    u, v, key = normalize_edge_id(edge_id)
    return f"u={u}, v={v}, key={key}"


def is_missing_text_value(value: object) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except Exception:
        pass
    return str(value).strip() == ""


def is_road_in_set(
    edge_id: tuple[object, object, object] | None,
    road_ids: set[tuple[object, object, object]] | list[tuple[object, object, object]],
) -> bool:
    if edge_id is None:
        return False
    normalized_target = normalize_edge_id(edge_id)
    normalized_roads = {normalize_edge_id(x) for x in road_ids}
    return normalized_target in normalized_roads


def add_road_to_set(
    road_ids: set[tuple[object, object, object]] | list[tuple[object, object, object]],
    edge_id: tuple[object, object, object],
) -> set[tuple[str, str, str]]:
    updated = {normalize_edge_id(x) for x in road_ids}
    updated.add(normalize_edge_id(edge_id))
    return updated


def remove_road_from_set(
    road_ids: set[tuple[object, object, object]] | list[tuple[object, object, object]],
    edge_id: tuple[object, object, object],
) -> set[tuple[str, str, str]]:
    normalized_target = normalize_edge_id(edge_id)
    updated = {normalize_edge_id(x) for x in road_ids}
    return {x for x in updated if x != normalized_target}


def is_excluded_road(
    edge_id: tuple[object, object, object] | None,
    excluded_roads: set[tuple[object, object, object]] | list[tuple[object, object, object]],
) -> bool:
    return is_road_in_set(edge_id, excluded_roads)


def exclude_road(
    excluded_roads: set[tuple[object, object, object]] | list[tuple[object, object, object]],
    edge_id: tuple[object, object, object],
) -> set[tuple[str, str, str]]:
    return add_road_to_set(excluded_roads, edge_id)


def include_road(
    excluded_roads: set[tuple[object, object, object]] | list[tuple[object, object, object]],
    edge_id: tuple[object, object, object],
) -> set[tuple[str, str, str]]:
    return remove_road_from_set(excluded_roads, edge_id)


def get_road_row_by_edge_id(
    roads_gdf,
    edge_id: tuple[object, object, object] | None,
) -> dict[str, object] | None:
    if edge_id is None:
        return None

    normalized_target = normalize_edge_id(edge_id)

    for _, row in roads_gdf.iterrows():
        row_edge_id = build_road_edge_id(row)
        if row_edge_id == normalized_target:
            result = {
                "road_id_text": format_road_edge_id(normalized_target),
                "u": row_edge_id[0],
                "v": row_edge_id[1],
                "key": row_edge_id[2],
            }
            for optional_col in ["osmid", "name", "length", "highway"]:
                if optional_col in roads_gdf.columns:
                    result[optional_col] = row.get(optional_col)
            return result

    return None


def build_road_display_name(
    roads_gdf,
    edge_id: tuple[object, object, object] | None,
) -> str:
    base_text = format_road_edge_id(edge_id)
    road_info = get_road_row_by_edge_id(roads_gdf, edge_id)
    if road_info is None:
        return base_text

    name_value = road_info.get("name")
    if is_missing_text_value(name_value):
        return base_text

    return f"{name_value} / {base_text}"


def build_selectable_roads_df(
    roads_gdf,
    excluded_roads: set[tuple[object, object, object]] | list[tuple[object, object, object]],
) -> pd.DataFrame:
    required_cols = ["u", "v", "key", "geometry"]
    missing = [col for col in required_cols if col not in roads_gdf.columns]
    if missing:
        raise ValueError(f"road selection required columns are missing: {missing}")

    rows: list[dict[str, object]] = []
    for _, row in roads_gdf.iterrows():
        edge_id = build_road_edge_id(row)
        record = {
            "road_id_text": format_road_edge_id(edge_id),
            "u": edge_id[0],
            "v": edge_id[1],
            "key": edge_id[2],
            "is_excluded": is_excluded_road(edge_id, excluded_roads),
        }
        for optional_col in ["osmid", "name", "length", "highway"]:
            if optional_col in roads_gdf.columns:
                record[optional_col] = row.get(optional_col)
        rows.append(record)

    df = pd.DataFrame(rows)
    if len(df) == 0:
        return df

    return df.sort_values(["is_excluded", "road_id_text"], ascending=[True, True]).reset_index(drop=True)


def build_excluded_roads_summary(
    roads_gdf,
    excluded_roads: set[tuple[object, object, object]] | list[tuple[object, object, object]],
) -> list[dict[str, object]]:
    return build_roads_summary(roads_gdf, excluded_roads)


def build_roads_summary(
    roads_gdf,
    road_ids: set[tuple[object, object, object]] | list[tuple[object, object, object]],
) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []

    for edge_id in road_ids:
        row_info = get_road_row_by_edge_id(roads_gdf, edge_id)
        if row_info is None:
            summaries.append({"road_id_text": format_road_edge_id(edge_id)})
        else:
            summaries.append(row_info)

    summaries.sort(key=lambda x: str(x.get("road_id_text", "")))
    return summaries
