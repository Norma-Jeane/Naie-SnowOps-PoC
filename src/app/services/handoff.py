#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
D3 handoff service

■ 役割
- D2/D3 境界の受け渡し状態を整理する
- 再計算実行状態（可 / 保留 / 不可）を判定する
- D3 向け payload を生成する
- payload の整合確認を行う
"""

from __future__ import annotations

from typing import Callable


def get_d3_recalculation_status(
    current_point: dict[str, object] | None,
    candidate_status: str,
    validate_start_point_dict: Callable[[dict[str, object] | None], None],
) -> tuple[str, str]:
    if current_point is None:
        return "不可", "現在の出発点が未設定です。"

    try:
        validate_start_point_dict(current_point)
    except Exception as exc:
        return "不可", f"現在の出発点が不正です: {exc}"

    if candidate_status == "candidate":
        return "保留", "出発点候補が未確定です。"

    return "可", "D3 へ渡す最小入力状態は成立しています。"


def build_d3_handoff_payload(
    *,
    current_point: dict[str, object] | None,
    candidate_point: dict[str, object] | None,
    previous_point: dict[str, object] | None,
    excluded_roads: set[tuple[object, object, object]] | list[tuple[object, object, object]],
    selected_road_id: tuple[object, object, object] | None,
    start_source: str,
    candidate_status: str,
    direction_enabled: bool,
    validate_start_point_dict: Callable[[dict[str, object] | None], None],
    normalize_edge_id_list: Callable[
        [set[tuple[object, object, object]] | list[tuple[object, object, object]]],
        list[tuple[str, str, str]],
    ],
    format_point_text: Callable[[dict[str, object] | None], str],
    format_road_edge_id: Callable[[tuple[object, object, object] | None], str],
    is_excluded_road: Callable[[tuple[object, object, object] | None], bool],
) -> dict[str, object]:
    recalculation_status, recalculation_reason = get_d3_recalculation_status(
        current_point=current_point,
        candidate_status=candidate_status,
        validate_start_point_dict=validate_start_point_dict,
    )

    normalized_excluded = normalize_edge_id_list(excluded_roads)

    return {
        "current_start_point": current_point,
        "excluded_roads": [
            {"u": edge_id[0], "v": edge_id[1], "key": edge_id[2]}
            for edge_id in normalized_excluded
        ],
        "recalculation_conditions": {
            "recalculation_status": recalculation_status,
            "recalculation_reason": recalculation_reason,
            "has_current_start_point": current_point is not None,
            "excluded_roads_normalized": True,
            "candidate_status": candidate_status,
            "route_direction_display_enabled": direction_enabled,
        },
        "operation_summary": {
            "current_start_point_text": format_point_text(current_point),
            "previous_start_point_text": format_point_text(previous_point),
            "candidate_start_point_text": format_point_text(candidate_point),
            "excluded_roads_count": len(normalized_excluded),
            "selected_road_id_text": format_road_edge_id(selected_road_id),
            "selected_road_is_excluded": is_excluded_road(selected_road_id),
            "route_direction_display_enabled": direction_enabled,
            "candidate_start_point_status": candidate_status,
            "start_point_source": str(start_source),
        },
    }


def validate_d3_handoff_payload(
    payload: dict[str, object],
    validate_start_point_dict: Callable[[dict[str, object] | None], None],
) -> tuple[bool, list[str]]:
    errors: list[str] = []

    current_point = payload.get("current_start_point")
    excluded_roads = payload.get("excluded_roads")
    conditions = payload.get("recalculation_conditions")

    if not isinstance(excluded_roads, list):
        errors.append("除外道路集合が list 形式ではありません。")
    else:
        for idx, road in enumerate(excluded_roads):
            if not isinstance(road, dict):
                errors.append(f"除外道路 {idx} が dict 形式ではありません。")
                continue

            missing_keys = [key for key in ["u", "v", "key"] if key not in road]
            if missing_keys:
                errors.append(f"除外道路 {idx} に必須キー不足があります: {missing_keys}")

    if not isinstance(conditions, dict):
        errors.append("再計算実行条件が dict 形式ではありません。")
    else:
        if "recalculation_status" not in conditions:
            errors.append("再計算実行状態がありません。")
        if "recalculation_reason" not in conditions:
            errors.append("再計算実行理由がありません。")

    if current_point is not None:
        try:
            validate_start_point_dict(current_point)
        except Exception as exc:
            errors.append(f"現在の出発点が不正です: {exc}")

    return len(errors) == 0, errors


def build_d3_handoff_summary_rows(
    payload: dict[str, object],
    format_point_text: Callable[[dict[str, object] | None], str],
) -> list[dict[str, object]]:
    current_point = payload.get("current_start_point")
    excluded_roads = payload.get("excluded_roads", [])
    conditions = payload.get("recalculation_conditions", {})
    operation_summary = payload.get("operation_summary", {})

    current_point_dict = current_point if isinstance(current_point, dict) else None

    return [
        {
            "項目": "D3へ渡す出発点",
            "値": format_point_text(current_point_dict),
        },
        {
            "項目": "D3へ渡す除外道路件数",
            "値": len(excluded_roads) if isinstance(excluded_roads, list) else "不正",
        },
        {
            "項目": "再計算実行可否",
            "値": conditions.get("recalculation_status", "不明"),
        },
        {
            "項目": "理由",
            "値": conditions.get("recalculation_reason", "不明"),
        },
        {
            "項目": "候補点状態",
            "値": operation_summary.get("candidate_start_point_status", "不明"),
        },
        {
            "項目": "出発点の由来",
            "値": operation_summary.get("start_point_source", "不明"),
        },
    ]