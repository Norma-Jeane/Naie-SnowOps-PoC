#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
start_point service

■ 役割
- 出発点状態の初期化
- 候補点の作成
- 候補点の確定 / 取消
- 出発点辞書の検証
- 表示用の点データ整形
"""

from __future__ import annotations


SESSION_DEFAULTS = {
    "current_start_point": None,
    "candidate_start_point": None,
    "start_point_source": "initial",
    "candidate_start_point_status": "none",
    "previous_start_point": None,
    "start_point_message": "初期出発点を表示中",
    "start_point_operation_notice": None,
    "view_operation_notice": None,
    "reset_view_nonce": 0,
    "last_handled_map_click_signature": None,
    "excluded_roads": set(),
    "selected_road_id": None,
    "road_operation_message": "除外道路はまだありません。",
    "road_operation_notice": None,
    "route_direction_display_enabled": True,
}


def build_initial_start_point(route_gdf) -> dict[str, object] | None:
    if len(route_gdf) == 0:
        return None

    ordered = route_gdf.copy()
    if "segment_order" in ordered.columns:
        ordered = ordered.sort_values("segment_order").reset_index(drop=True)

    first_geom = ordered.geometry.iloc[0]
    if first_geom is None or first_geom.is_empty:
        return None

    if not hasattr(first_geom, "coords"):
        return None

    first_coord = list(first_geom.coords)[0]

    return {
        "lat": float(first_coord[1]),
        "lon": float(first_coord[0]),
        "source": "initial",
        "snap_applied": False,
        "snap_reason": None,
    }


def init_session_state(session_state, initial_start_point: dict[str, object] | None) -> None:
    for key, value in SESSION_DEFAULTS.items():
        if key not in session_state:
            session_state[key] = value if not isinstance(value, set) else set()

    if session_state["current_start_point"] is None and initial_start_point is not None:
        session_state["current_start_point"] = initial_start_point
        session_state["start_point_source"] = "initial"
        session_state["candidate_start_point_status"] = "none"
        session_state["start_point_message"] = "初期出発点を表示中"


def validate_start_point_dict(point: dict[str, object] | None) -> None:
    if point is None:
        raise ValueError("start point is None")

    required_keys = ["lat", "lon"]
    missing_keys = [key for key in required_keys if key not in point]
    if missing_keys:
        raise ValueError(f"required keys are missing: {missing_keys}")

    lat = point["lat"]
    lon = point["lon"]

    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        raise ValueError("lat/lon must be numeric")

    if not (-90.0 <= float(lat) <= 90.0):
        raise ValueError(f"invalid latitude: {lat}")
    if not (-180.0 <= float(lon) <= 180.0):
        raise ValueError(f"invalid longitude: {lon}")


def build_candidate_start_point(
    lat: float,
    lon: float,
    source: str = "map_click",
    snap_applied: bool = False,
    snap_reason: str | None = None,
) -> dict[str, object]:
    candidate = {
        "lat": float(lat),
        "lon": float(lon),
        "source": source,
        "snap_applied": bool(snap_applied),
        "snap_reason": snap_reason,
    }
    validate_start_point_dict(candidate)
    return candidate


def set_candidate_start_point(session_state, candidate: dict[str, object]) -> None:
    validate_start_point_dict(candidate)
    session_state["candidate_start_point"] = candidate
    session_state["candidate_start_point_status"] = "candidate"
    session_state["start_point_message"] = (
        "出発点候補を仮選択中。確定すると現在の出発点へ反映されます。"
    )


def confirm_candidate_start_point(session_state) -> None:
    candidate = session_state.get("candidate_start_point")
    validate_start_point_dict(candidate)

    current = session_state.get("current_start_point")
    if current is not None:
        session_state["previous_start_point"] = current

    session_state["current_start_point"] = candidate
    session_state["start_point_source"] = "map_click"
    session_state["candidate_start_point_status"] = "confirmed"
    session_state["candidate_start_point"] = None
    session_state["start_point_message"] = "出発点を更新済み"

    snap_applied = bool(candidate.get("snap_applied", False))
    if snap_applied:
        session_state["start_point_message"] += "（最近傍道路上の点へ補正済み）"


def cancel_candidate_start_point(session_state) -> None:
    session_state["candidate_start_point"] = None
    session_state["candidate_start_point_status"] = "none"
    session_state["start_point_message"] = (
        "出発点候補を取り消しました。現在の出発点は変更していません。"
    )


def build_component_point(point: dict[str, object] | None) -> dict[str, float] | None:
    if point is None:
        return None
    validate_start_point_dict(point)
    return {
        "lat": float(point["lat"]),
        "lon": float(point["lon"]),
    }


def format_point_text(point: dict[str, object] | None) -> str:
    if point is None:
        return "未設定"
    validate_start_point_dict(point)
    return f"{float(point['lat']):.6f}, {float(point['lon']):.6f}"