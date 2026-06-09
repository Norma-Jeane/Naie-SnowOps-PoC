#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Streamlit用マップ操作カスタムコンポーネントラッパー

■ 目的
- 本流アプリから map custom component を呼ぶ
- 最初の段階では start_point_set の受信安定化を優先する
- raw value をそのまま返し、normalize は行わない

■ 想定配置
src/app/components/map_click_component.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st
import streamlit.components.v1 as components


_COMPONENT_NAME = "step_d_map_click_component_pending_sync_v1"
_FRONTEND_DIR = (
    Path(__file__).resolve().parent / "map_click_component_frontend" / "dist"
)

if not _FRONTEND_DIR.exists():
    raise FileNotFoundError(
        "Custom Component frontend build directory is missing: "
        f"{_FRONTEND_DIR}"
    )

_render_component = components.declare_component(
    _COMPONENT_NAME,
    path=str(_FRONTEND_DIR),
)


def render_map_click_component(
    *,
    key: str,
    initial_view_state: dict[str, float],
    current_start_point: dict[str, float] | None,
    candidate_start_point: dict[str, float] | None,
    reset_view_nonce: int,
    roads_geojson: dict | None = None,
    road_state: dict | None = None,
    route_geojson: dict | None = None,
    route_cycle_guide: dict[str, object] | None = None,
    show_route_cycle_guide: bool = True,
    debug_mode: bool = False,
    pending_sync_nonce: int = 0,
    line_styles: dict[str, object] | None = None,
    height: int = 600,
) -> Any:
    """
    Step D / D3 用 map custom component を描画し、戻り値 raw value をそのまま返す。
    最小構成のため normalize は行わない。
    """
    component_value = _render_component(
        key=key,
        initial_view_state=initial_view_state,
        current_start_point=current_start_point,
        candidate_start_point=candidate_start_point,
        reset_view_nonce=reset_view_nonce,
        roads_geojson=roads_geojson,
        road_state=road_state,
        route_geojson=route_geojson,
        route_cycle_guide=route_cycle_guide,
        show_route_cycle_guide=show_route_cycle_guide,
        debug_mode=debug_mode,
        pending_sync_nonce=pending_sync_nonce,
        line_styles=line_styles,
        height=height,
        default=None,
    )

    st.session_state["bridge_component_raw_value"] = component_value
    st.session_state["bridge_component_normalized_value"] = component_value
    st.session_state["bridge_component_normalize_error"] = ""

    return component_value
