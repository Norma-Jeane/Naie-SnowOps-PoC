#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
最終アプリ入口: 気象推論・道路選定・再計算統合

■ 目的
- map_click_component を本流アプリへ接続する
- component event の受信直後には st.rerun() を使わない
- bridge 受信を壊さずに state 更新が後続描画へ反映されるか確認する

■ 実行方法
cmd:
python -m streamlit run src/app/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add repository root to python search path for Streamlit Cloud
sys.path.append(str(Path(__file__).resolve().parents[2]))

from datetime import date, datetime, time, timedelta
import json
import logging
import math
import os

import geopandas as gpd
import pandas as pd
import streamlit as st

from src.app.components.map_click_component import render_map_click_component
from src.app.services.handoff import (
    build_d3_handoff_payload,
    build_d3_handoff_summary_rows,
    get_d3_recalculation_status,
    validate_d3_handoff_payload,
)
from src.app.services.io import (
    InputFileSpec,
    ensure_wgs84,
    load_geojson,
    load_required_inputs,
    summarize_gdf,
)
from src.app.services.map_display import (
    build_initial_view_state,
    build_roads_geojson,
    build_route_geojson,
    build_route_cycle_guide,
    normalize_route_segment_type,
    sanitize_gdf_for_geojson,
)
from src.app.services.recalculation import (
    build_recalculation_preview_rows,
    build_recalculation_request,
    run_recalculation,
)
from src.app.services.weather_prediction_pipeline import (
    WeatherPredictionPipelineConfig,
    run_weather_prediction_pipeline,
)
from src.app.services.weather_inference_input import (
    build_weather_inference_input_result,
)
from src.app.services.weather_prediction import (
    load_weather_prediction_model,
    predict_weather_level_single,
)
from src.app.services.road_state import (
    build_excluded_roads_summary,
    build_roads_summary,
    build_road_display_name,
    build_selectable_roads_df,
    format_road_edge_id,
    get_road_row_by_edge_id,
    is_excluded_road,
    is_road_in_set,
    normalize_edge_id,
    normalize_edge_id_list,
)
from src.app.services.start_point import (
    build_component_point,
    build_initial_start_point,
    cancel_candidate_start_point,
    confirm_candidate_start_point,
    format_point_text,
    init_session_state,
    validate_start_point_dict,
)

logger = logging.getLogger(__name__)


def setup_logging(verbose: bool = False) -> None:
    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(level=level, format="[%(levelname)s] %(message)s")


APP_TITLE = "奈井江町除雪計画支援アプリ"
APP_SUBTITLE = "気象推論・道路選定・再計算を統合した最終アプリ入口"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROAD_NETWORK_INPUT = PROJECT_ROOT / "Data" / "app_init" / "roads" / "road_network.geojson"
MANUAL_ADD_CANDIDATE_ROADS_INPUT = (
    PROJECT_ROOT / "Data" / "app_init" / "roads" / "manual_add_candidate_roads.geojson"
)

ROAD_UNSELECTED_LABEL = "未選択"


MAP_COMPONENT_KEY = "d3_map_click_component"
DEBUG_MODE_KEY = "app_debug_mode"
APP_DEBUG_MODE_ENV = "APP_ENABLE_DEBUG_MODE"
D3_DEBUG_INPUTS_ENV = "D3_ENABLE_DEBUG_INPUTS"
ROAD_SELECTION_WIDGET_KEY = "road_selection_selectbox_value"
ROAD_SELECTION_SYNC_KEY = "road_selection_selectbox_sync_value"
ROAD_SELECTION_LEVEL_WIDGET_KEY = "road_selection_level_selectbox_value"
ROAD_SELECTION_LEVEL_SYNC_KEY = "road_selection_level_selectbox_sync_value"
BASEMAP_DISPLAY_STATE_KEY = "basemap_display_enabled"
BASEMAP_DISPLAY_WIDGET_KEY = "basemap_display_widget_value"
LAST_HANDLED_COMPONENT_EVENT_KEY = "last_handled_component_event_key"
ROAD_BASELINE_STATE_KEYS = (
    ("excluded_roads", "recalculation_baseline_excluded_roads"),
    ("included_roads", "recalculation_baseline_included_roads"),
    ("confirmed_included_roads", "recalculation_baseline_confirmed_included_roads"),
    ("conditional_roads", "recalculation_baseline_conditional_roads"),
    ("failed_target_roads", "recalculation_baseline_failed_target_roads"),
    ("failed_partial_roads", "recalculation_baseline_failed_partial_roads"),
    ("failed_full_roads", "recalculation_baseline_failed_full_roads"),
    ("failed_included_roads", "recalculation_baseline_failed_included_roads"),
)
ROAD_SELECTION_LEVEL_TARGET_INPUTS = {
    0: PROJECT_ROOT / "Data" / "app_init" / "roads" / "priority_roads_level0.geojson",
    1: PROJECT_ROOT / "Data" / "app_init" / "roads" / "priority_roads_level1.geojson",
    2: PROJECT_ROOT / "Data" / "app_init" / "roads" / "priority_roads_level2.geojson",
    3: PROJECT_ROOT / "Data" / "app_init" / "roads" / "priority_roads_level3.geojson",
}
D3_TEST_FIXTURE_ENV = "D3_ENABLE_TEST_FIXTURE"
RED_DOTTED_TEST_FIXTURE_PATH = (
    PROJECT_ROOT
    / "Data"
    / "test_fixtures"
    / "d3_red_dotted"
    / "red_dotted_state.json"
)


def sync_basemap_display_enabled() -> None:
    st.session_state[BASEMAP_DISPLAY_STATE_KEY] = bool(
        st.session_state.get(BASEMAP_DISPLAY_WIDGET_KEY, True)
    )
LINE_STYLES_INPUT = (
    PROJECT_ROOT
    / "Data"
    / "app_init"
    / "map_display"
    / "line_styles.json"
)
DEFAULT_WEATHER_STATION_NUM = "a0044"
DEFAULT_WEATHER_STATION_NAME = "美唄"
DEFAULT_WEATHER_SELECTED_DATE = date(2026, 1, 29)
DEFAULT_WEATHER_SELECTED_HOUR = 23
WEATHER_MODEL_HORIZON_LABELS = {
    "3h": "3hモデル（準備中）",
    "6h": "6hモデル（準備中）",
    "12h": "12hモデル（利用可能）",
    "18h": "18hモデル（準備中）",
    "24h": "24hモデル（準備中）",
}
ACTIVE_WEATHER_MODEL_HORIZON = "12h"
LEVEL_INPUT_MODE_INFERENCE = "推論日を使用する"
LEVEL_INPUT_MODE_MANUAL = "レベルを指定する"
LEVEL_INPUT_MODE_OPTIONS = [LEVEL_INPUT_MODE_INFERENCE, LEVEL_INPUT_MODE_MANUAL]


def build_d3_input_specs(project_root: Path) -> list[InputFileSpec]:
    return [
        InputFileSpec(
            key="roads",
            label="road_network",
            path=ROAD_NETWORK_INPUT,
            required=True,
            description="D3 background and recalculation road network",
        ),
        InputFileSpec(
            key="priority_roads",
            label="priority_roads_level3",
            path=ROAD_SELECTION_LEVEL_TARGET_INPUTS[3],
            required=False,
            description="Default target road population for road_selection_level=3",
        ),
    ]


INPUT_SPECS = build_d3_input_specs(PROJECT_ROOT)


def normalize_road_selection_level(value: object) -> int:
    try:
        level = int(value)
    except (TypeError, ValueError):
        return 3
    return level if level in ROAD_SELECTION_LEVEL_TARGET_INPUTS else 3


def get_road_selection_level() -> int:
    level = normalize_road_selection_level(st.session_state.get("road_selection_level", 3))
    st.session_state["road_selection_level"] = level
    return level


def get_road_selection_target_input_path() -> Path:
    return ROAD_SELECTION_LEVEL_TARGET_INPUTS[get_road_selection_level()]


def queue_road_selection_level_widget_sync(level: object) -> None:
    st.session_state[ROAD_SELECTION_LEVEL_SYNC_KEY] = normalize_road_selection_level(level)


def sync_pending_road_selection_level_widget() -> None:
    pending_level_sync = st.session_state.pop(ROAD_SELECTION_LEVEL_SYNC_KEY, None)
    if pending_level_sync is not None:
        st.session_state[ROAD_SELECTION_LEVEL_WIDGET_KEY] = normalize_road_selection_level(
            pending_level_sync
        )
    elif (
        ROAD_SELECTION_LEVEL_WIDGET_KEY not in st.session_state
        or st.session_state[ROAD_SELECTION_LEVEL_WIDGET_KEY] not in [0, 1, 2, 3]
    ):
        st.session_state[ROAD_SELECTION_LEVEL_WIDGET_KEY] = get_road_selection_level()


def init_display_mode_state() -> None:
    if DEBUG_MODE_KEY not in st.session_state:
        st.session_state[DEBUG_MODE_KEY] = os.environ.get(APP_DEBUG_MODE_ENV, "").strip() == "1"


def is_debug_mode() -> bool:
    init_display_mode_state()
    return bool(st.session_state.get(DEBUG_MODE_KEY, False))


def render_debug_mode_control() -> bool:
    init_display_mode_state()
    return is_debug_mode()


@st.cache_data(show_spinner=False)
def cached_read_geojson_allow_empty(path_str: str) -> gpd.GeoDataFrame:
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(f"file not found: {path}")
    if not path.is_file():
        raise ValueError(f"path is not a file: {path}")

    gdf = gpd.read_file(path)
    if "geometry" not in gdf.columns:
        gdf = gpd.GeoDataFrame(gdf, geometry=[], crs="EPSG:4326")
    return ensure_wgs84(gdf)


def load_current_priority_roads() -> gpd.GeoDataFrame:
    return cached_read_geojson_allow_empty(str(get_road_selection_target_input_path()))


def is_debug_input_mode() -> bool:
    return os.environ.get(D3_DEBUG_INPUTS_ENV, "").strip() == "1"


def load_manual_add_candidate_roads(debug_mode: bool = False) -> gpd.GeoDataFrame | None:
    # Debug-only fixture. Normal route creation must not depend on this file.
    if not debug_mode:
        return None
    if not MANUAL_ADD_CANDIDATE_ROADS_INPUT.exists():
        return None
    return cached_read_geojson_allow_empty(str(MANUAL_ADD_CANDIDATE_ROADS_INPUT))


@st.cache_data(show_spinner=False)
def cached_load_line_styles_config(path_str: str) -> tuple[dict[str, object] | None, str]:
    path = Path(path_str)
    if not path.exists():
        return None, f"line styles config not found: {path}"

    try:
        with path.open("r", encoding="utf-8") as fp:
            payload = json.load(fp)
    except Exception as exc:
        return None, f"line styles config could not be read: {exc}"

    if not isinstance(payload, dict):
        return None, "line styles config root must be an object"

    line_styles = payload.get("lineStyles")
    if not isinstance(line_styles, dict):
        return None, "line styles config must contain a lineStyles object"

    return payload, ""


def build_operable_roads_gdf(
    roads_gdf: gpd.GeoDataFrame,
    priority_roads_gdf: gpd.GeoDataFrame,
    manual_add_candidate_roads_gdf: gpd.GeoDataFrame | None,
) -> gpd.GeoDataFrame:
    parts: list[gpd.GeoDataFrame] = []

    if priority_roads_gdf is not None and len(priority_roads_gdf) > 0:
        priority_part = ensure_wgs84(priority_roads_gdf.copy())
        priority_part["source_kind"] = "priority_target"
        parts.append(priority_part)

    if roads_gdf is not None and len(roads_gdf) > 0:
        road_network_part = ensure_wgs84(roads_gdf.copy())
        road_network_part["source_kind"] = "road_network_candidate"
        parts.append(road_network_part)

    if manual_add_candidate_roads_gdf is not None and len(manual_add_candidate_roads_gdf) > 0:
        manual_part = ensure_wgs84(manual_add_candidate_roads_gdf.copy())
        manual_part["source_kind"] = "manual_add_candidate"
        parts.append(manual_part)

    if not parts:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    combined = gpd.GeoDataFrame(
        pd.concat(parts, ignore_index=True, sort=False),
        geometry="geometry",
        crs=parts[0].crs,
    )
    if all(col in combined.columns for col in ["u", "v", "key"]):
        combined["_edge_id"] = combined.apply(
            lambda row: normalize_edge_id((row["u"], row["v"], row["key"])),
            axis=1,
        )
        combined = combined.drop_duplicates("_edge_id", keep="first").drop(
            columns=["_edge_id"]
        )
    return combined


def queue_road_selection_widget_sync(
    edge_id: tuple[object, object, object] | None,
) -> None:
    st.session_state[ROAD_SELECTION_SYNC_KEY] = (
        ROAD_UNSELECTED_LABEL if edge_id is None else format_road_edge_id(edge_id)
    )


def build_component_event_instance_key(event: dict[str, object] | None) -> str:
    if event is None:
        return ""

    component_instance_id = str(event.get("component_instance_id", "")).strip()
    event_nonce = str(event.get("event_nonce", "")).strip()
    if component_instance_id == "" or event_nonce == "":
        return ""

    return json.dumps(
        {
            "component_instance_id": component_instance_id,
            "event_nonce": event_nonce,
        },
        sort_keys=True,
        ensure_ascii=False,
    )


def get_pending_map_component_event() -> dict[str, object] | None:
    pending_value = st.session_state.get(MAP_COMPONENT_KEY)
    if isinstance(pending_value, dict):
        return pending_value
    return None


def make_display_df(rows: list[dict[str, object]]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    for col in df.columns:
        df[col] = df[col].astype(str)
    return df


def normalize_map_view_state(value: object) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None

    try:
        lat = float(value["lat"])
        lon = float(value["lon"])
        zoom = float(value["zoom"])
    except (KeyError, TypeError, ValueError):
        return None

    if not (math.isfinite(lat) and math.isfinite(lon) and math.isfinite(zoom)):
        return None

    return {
        "lat": lat,
        "lon": lon,
        "zoom": zoom,
    }


def get_persisted_map_view_state(
    default_view_state: dict[str, float],
) -> dict[str, float]:
    stored_view_state = normalize_map_view_state(st.session_state.get("last_map_view_state"))
    if stored_view_state is None:
        return default_view_state
    return stored_view_state


def init_debug_state() -> None:
    if "last_component_event" not in st.session_state:
        st.session_state["last_component_event"] = None

    if "last_component_event_type" not in st.session_state:
        st.session_state["last_component_event_type"] = ""

    if "last_component_event_count" not in st.session_state:
        st.session_state["last_component_event_count"] = 0

    if "last_component_event_nonce" not in st.session_state:
        st.session_state["last_component_event_nonce"] = ""

    if "last_component_event_status" not in st.session_state:
        st.session_state["last_component_event_status"] = ""

    if "duplicate_component_event_skip_count" not in st.session_state:
        st.session_state["duplicate_component_event_skip_count"] = 0

    if "bridge_component_raw_value" not in st.session_state:
        st.session_state["bridge_component_raw_value"] = None

    if "bridge_component_normalized_value" not in st.session_state:
        st.session_state["bridge_component_normalized_value"] = None

    if "bridge_component_normalize_error" not in st.session_state:
        st.session_state["bridge_component_normalize_error"] = ""

    if "last_map_view_state" not in st.session_state:
        st.session_state["last_map_view_state"] = None

    if "last_map_view_state_source" not in st.session_state:
        st.session_state["last_map_view_state_source"] = ""

    if LAST_HANDLED_COMPONENT_EVENT_KEY not in st.session_state:
        st.session_state[LAST_HANDLED_COMPONENT_EVENT_KEY] = ""


def init_recalculation_state() -> None:
    if "recalculation_status" not in st.session_state:
        st.session_state["recalculation_status"] = "未実行"

    if "recalculation_message" not in st.session_state:
        st.session_state["recalculation_message"] = ""

    if "recalculation_preview_rows" not in st.session_state:
        st.session_state["recalculation_preview_rows"] = []

    if "recalculation_selected_strategy" not in st.session_state:
        st.session_state["recalculation_selected_strategy"] = ""

    if "recalculation_metrics" not in st.session_state:
        st.session_state["recalculation_metrics"] = {}

    if "recalculation_result_summary_rows" not in st.session_state:
        st.session_state["recalculation_result_summary_rows"] = []

    if "recalculation_output_route_path" not in st.session_state:
        st.session_state["recalculation_output_route_path"] = ""

    if "recalculation_route_gdf" not in st.session_state:
        st.session_state["recalculation_route_gdf"] = None

    if "recalculation_output_summary_path" not in st.session_state:
        st.session_state["recalculation_output_summary_path"] = ""

    if "recalculation_applied_road_selection_level" not in st.session_state:
        st.session_state["recalculation_applied_road_selection_level"] = None

    if "recalculation_applied_target_input_path" not in st.session_state:
        st.session_state["recalculation_applied_target_input_path"] = ""

    if "recalculation_preview_call_count" not in st.session_state:
        st.session_state["recalculation_preview_call_count"] = 0

    if "recalculation_action_call_count" not in st.session_state:
        st.session_state["recalculation_action_call_count"] = 0

    if "road_selection_level" not in st.session_state:
        st.session_state["road_selection_level"] = 3

    if "route_refresh_notice" not in st.session_state:
        st.session_state["route_refresh_notice"] = ""

    if "recalculation_baseline_start_point" not in st.session_state:
        st.session_state["recalculation_baseline_start_point"] = None

    for _, baseline_key in ROAD_BASELINE_STATE_KEYS:
        if baseline_key not in st.session_state:
            st.session_state[baseline_key] = None

    if "recalculation_baseline_selected_road_id" not in st.session_state:
        st.session_state["recalculation_baseline_selected_road_id"] = None

    if "after_black_clear_roads" not in st.session_state:
        st.session_state["after_black_clear_roads"] = set()

    if "pending_instruction_sync_nonce" not in st.session_state:
        st.session_state["pending_instruction_sync_nonce"] = 0

    if "pending_recalculation_after_instruction_sync" not in st.session_state:
        st.session_state["pending_recalculation_after_instruction_sync"] = False

    if "last_instruction_sync_count" not in st.session_state:
        st.session_state["last_instruction_sync_count"] = 0


def request_pending_instruction_sync_for_recalculation() -> None:
    st.session_state["pending_instruction_sync_nonce"] = (
        int(st.session_state.get("pending_instruction_sync_nonce", 0)) + 1
    )
    st.session_state["pending_recalculation_after_instruction_sync"] = True
    st.session_state["recalculation_status"] = "instruction_sync_pending"
    st.session_state["recalculation_message"] = (
        "Pending map edits will be synced before recalculation."
    )


def init_weather_prediction_state() -> None:
    if "weather_demo_mode" not in st.session_state:
        st.session_state["weather_demo_mode"] = True

    if "level_input_mode" not in st.session_state:
        st.session_state["level_input_mode"] = LEVEL_INPUT_MODE_INFERENCE

    if "weather_selected_date" not in st.session_state:
        st.session_state["weather_selected_date"] = DEFAULT_WEATHER_SELECTED_DATE

    if "weather_selected_hour" not in st.session_state:
        st.session_state["weather_selected_hour"] = DEFAULT_WEATHER_SELECTED_HOUR

    if "weather_model_horizon" not in st.session_state:
        st.session_state["weather_model_horizon"] = ACTIVE_WEATHER_MODEL_HORIZON

    if "weather_pred_level" not in st.session_state:
        st.session_state["weather_pred_level"] = None

    if "weather_update_status" not in st.session_state:
        st.session_state["weather_update_status"] = "未実行"

    if "weather_update_message" not in st.session_state:
        st.session_state["weather_update_message"] = ""

    if "weather_prediction_updated_at" not in st.session_state:
        st.session_state["weather_prediction_updated_at"] = None

    if "weather_prediction_source" not in st.session_state:
        st.session_state["weather_prediction_source"] = ""

    if "weather_latest_datetime" not in st.session_state:
        st.session_state["weather_latest_datetime"] = None

    if "weather_target_datetime" not in st.session_state:
        st.session_state["weather_target_datetime"] = None

    if "weather_fetch_rows" not in st.session_state:
        st.session_state["weather_fetch_rows"] = None

    if "weather_feature_rows" not in st.session_state:
        st.session_state["weather_feature_rows"] = None

    if "weather_raw_pipeline_pred_level" not in st.session_state:
        st.session_state["weather_raw_pipeline_pred_level"] = None

    if "weather_station_num" not in st.session_state:
        st.session_state["weather_station_num"] = DEFAULT_WEATHER_STATION_NUM

    if "weather_station_name" not in st.session_state:
        st.session_state["weather_station_name"] = DEFAULT_WEATHER_STATION_NAME


def copy_start_point(point: object) -> dict[str, object] | None:
    if point is None:
        return None
    if isinstance(point, dict):
        return dict(point)
    return None


def normalize_road_state_set(values: object) -> set[tuple[object, object, object]]:
    return {normalize_edge_id(edge_id) for edge_id in set(values or set())}


def build_failed_display_roads(
    failed_target_roads: object,
    failed_included_roads: object,
) -> set[tuple[object, object, object]]:
    return normalize_road_state_set(failed_target_roads) | normalize_road_state_set(
        failed_included_roads
    )


def build_recalculation_included_roads() -> set[tuple[object, object, object]]:
    return (
        normalize_road_state_set(st.session_state.get("confirmed_included_roads", set()))
        | normalize_road_state_set(st.session_state.get("included_roads", set()))
        | normalize_road_state_set(st.session_state.get("failed_included_roads", set()))
    )


def get_failed_display_roads() -> set[tuple[object, object, object]]:
    return build_failed_display_roads(
        st.session_state.get("failed_target_roads", set()),
        st.session_state.get("failed_included_roads", set()),
    )


def build_suppressed_route_edge_ids_for_final_state(
    *,
    failed_display_roads: object,
    failed_partial_roads: object,
    pair_lookup: dict[tuple[str, str, str], tuple[str, str, str]] | None = None,
) -> set[tuple[object, object, object]]:
    suppressed_edge_ids = normalize_road_state_set(failed_display_roads)
    lookup = pair_lookup if pair_lookup is not None else build_failed_target_pair_lookup()

    for edge_id in normalize_road_state_set(failed_partial_roads):
        paired_edge_id = lookup.get(edge_id)
        if paired_edge_id is not None:
            suppressed_edge_ids.add(paired_edge_id)

    return suppressed_edge_ids


def build_suppressed_base_edge_ids_for_final_state(
    *,
    failed_partial_roads: object,
    pair_lookup: dict[tuple[str, str, str], tuple[str, str, str]] | None = None,
) -> set[tuple[object, object, object]]:
    suppressed_edge_ids: set[tuple[object, object, object]] = set()
    lookup = pair_lookup if pair_lookup is not None else build_failed_target_pair_lookup()

    for edge_id in normalize_road_state_set(failed_partial_roads):
        paired_edge_id = lookup.get(edge_id)
        if paired_edge_id is not None:
            suppressed_edge_ids.add(paired_edge_id)

    return suppressed_edge_ids


def is_false_like(value: object) -> bool:
    if isinstance(value, bool):
        return value is False
    return str(value).strip().lower() == "false"


def freeze_coords(value: object) -> tuple:
    if isinstance(value, (list, tuple)):
        return tuple(freeze_coords(x) for x in value)
    return value


def extract_linestring_coords(geometry: object) -> tuple | None:
    if not isinstance(geometry, dict):
        return None
    if geometry.get("type") != "LineString":
        return None
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list):
        return None
    return freeze_coords(coordinates)


def build_failed_target_pair_lookup(
    road_network_path: Path = ROAD_NETWORK_INPUT,
) -> dict[tuple[str, str, str], tuple[str, str, str]]:
    try:
        with road_network_path.open("r", encoding="utf-8") as fp:
            feature_collection = json.load(fp)
    except Exception as exc:
        logger.warning("failed target pair lookup unavailable: %s", exc)
        return {}

    rows: list[dict[str, object]] = []
    by_endpoints: dict[tuple[str, str], list[dict[str, object]]] = {}
    for feature in feature_collection.get("features", []):
        props = feature.get("properties", {})
        if not is_false_like(props.get("oneway")):
            continue
        try:
            edge_id = normalize_edge_id((props.get("u"), props.get("v"), props.get("key")))
        except Exception:
            continue
        coords = extract_linestring_coords(feature.get("geometry"))
        row = {
            "edge_id": edge_id,
            "u": edge_id[0],
            "v": edge_id[1],
            "coords": coords,
        }
        rows.append(row)
        by_endpoints.setdefault((edge_id[0], edge_id[1]), []).append(row)

    pair_lookup: dict[tuple[str, str, str], tuple[str, str, str]] = {}
    for row in rows:
        candidates = by_endpoints.get((str(row["v"]), str(row["u"])), [])
        if len(candidates) == 1:
            pair_lookup[row["edge_id"]] = candidates[0]["edge_id"]
            continue

        coords = row.get("coords")
        if not coords:
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


def build_road_state_edge_ids(
    edge_id: tuple[object, object, object],
    pair_lookup: dict[tuple[str, str, str], tuple[str, str, str]] | None = None,
) -> set[tuple[str, str, str]]:
    normalized_edge_id = normalize_edge_id(edge_id)
    lookup = pair_lookup if pair_lookup is not None else build_failed_target_pair_lookup()
    edge_ids = {normalized_edge_id}
    paired_edge_id = lookup.get(normalized_edge_id)
    if paired_edge_id is not None:
        edge_ids.add(paired_edge_id)
    return edge_ids


def add_road_state_edges(
    road_ids: object,
    edge_ids: set[tuple[object, object, object]],
) -> set[tuple[str, str, str]]:
    updated = normalize_road_state_set(road_ids)
    updated.update(normalize_edge_id(edge_id) for edge_id in edge_ids)
    return updated


def remove_road_state_edges(
    road_ids: object,
    edge_ids: set[tuple[object, object, object]],
) -> set[tuple[str, str, str]]:
    remove_lookup = {normalize_edge_id(edge_id) for edge_id in edge_ids}
    return {edge_id for edge_id in normalize_road_state_set(road_ids) if edge_id not in remove_lookup}


def classify_failed_target_roads(
    *,
    failed_target_roads: object,
    visited_target_edge_ids: object,
    pair_lookup: dict[tuple[str, str, str], tuple[str, str, str]] | None = None,
) -> tuple[set[tuple[str, str, str]], set[tuple[str, str, str]]]:
    normalized_failed = normalize_road_state_set(failed_target_roads)
    normalized_visited = normalize_road_state_set(visited_target_edge_ids)
    lookup = pair_lookup if pair_lookup is not None else build_failed_target_pair_lookup()

    failed_partial_roads: set[tuple[str, str, str]] = set()
    failed_full_roads: set[tuple[str, str, str]] = set()
    for edge_id in normalized_failed:
        paired_edge_id = lookup.get(edge_id)
        if paired_edge_id is not None and paired_edge_id in normalized_visited:
            failed_partial_roads.add(edge_id)
        else:
            failed_full_roads.add(edge_id)

    return failed_partial_roads, failed_full_roads


def normalize_optional_edge_id(
    edge_id: object,
) -> tuple[object, object, object] | None:
    if edge_id is None:
        return None
    return normalize_edge_id(edge_id)


def save_recalculation_baseline_state() -> None:
    st.session_state["recalculation_baseline_start_point"] = copy_start_point(
        st.session_state.get("current_start_point")
    )
    for current_key, baseline_key in ROAD_BASELINE_STATE_KEYS:
        st.session_state[baseline_key] = normalize_road_state_set(
            st.session_state.get(current_key, set())
        )
    st.session_state["recalculation_baseline_selected_road_id"] = normalize_optional_edge_id(
        st.session_state.get("selected_road_id")
    )
    st.session_state["after_black_clear_roads"] = set()


def ensure_recalculation_baseline_state() -> None:
    missing_road_baseline = any(
        st.session_state.get(baseline_key) is None
        for _, baseline_key in ROAD_BASELINE_STATE_KEYS
    )
    if (
        st.session_state.get("recalculation_baseline_start_point") is None
        or missing_road_baseline
    ):
        save_recalculation_baseline_state()


def restore_recalculation_baseline_state() -> bool:
    baseline_start_point = copy_start_point(
        st.session_state.get("recalculation_baseline_start_point")
    )
    if baseline_start_point is None:
        st.session_state["recalculation_status"] = "未実行"
        st.session_state["recalculation_message"] = (
            "設定をやり直すための基準状態がまだありません。"
        )
        return False

    st.session_state["previous_start_point"] = copy_start_point(
        st.session_state.get("current_start_point")
    )
    st.session_state["current_start_point"] = baseline_start_point
    st.session_state["start_point_source"] = "recalculation_baseline"
    st.session_state["candidate_start_point"] = None
    st.session_state["candidate_start_point_status"] = "none"
    st.session_state["candidate_start_point_message"] = ""
    st.session_state["start_point_operation_notice"] = (
        "出発点を最後に確定した状態へ戻しました。"
    )

    for current_key, baseline_key in ROAD_BASELINE_STATE_KEYS:
        st.session_state[current_key] = normalize_road_state_set(
            st.session_state.get(baseline_key, set())
        )
    st.session_state["failed_display_roads"] = get_failed_display_roads()

    st.session_state["after_black_clear_roads"] = set()

    baseline_selected_road_id = normalize_optional_edge_id(
        st.session_state.get("recalculation_baseline_selected_road_id")
    )
    st.session_state["selected_road_id"] = baseline_selected_road_id
    queue_road_selection_widget_sync(baseline_selected_road_id)
    st.session_state["road_operation_notice"] = (
        "道路差分指示を最後に確定した状態へ戻しました。"
    )
    st.session_state["recalculation_message"] = (
        "設定を最後に確定した状態へ戻しました。再計算結果そのものは維持しています。"
    )
    return True


def build_recalculation_ready_state() -> tuple[str, str]:
    return get_d3_recalculation_status(
        current_point=st.session_state.get("current_start_point"),
        candidate_status=str(st.session_state.get("candidate_start_point_status", "none")),
        validate_start_point_dict=validate_start_point_dict,
    )


def run_recalculation_preview(
    operable_roads_gdf: gpd.GeoDataFrame,
    additional_roads_source_gdf: gpd.GeoDataFrame | None = None,
) -> None:
    try:
        st.session_state["recalculation_preview_call_count"] = (
            int(st.session_state.get("recalculation_preview_call_count", 0)) + 1
        )
        result = build_recalculation_request(
            current_start_point=st.session_state.get("current_start_point"),
            excluded_roads=st.session_state.get("excluded_roads", set()),
            included_roads=build_recalculation_included_roads(),
            conditional_roads=st.session_state.get("conditional_roads", set()),
            additional_roads_source_gdf=(
                additional_roads_source_gdf
                if additional_roads_source_gdf is not None
                else operable_roads_gdf
            ),
            project_root=PROJECT_ROOT,
            target_input_path=get_road_selection_target_input_path(),
        )

        st.session_state["recalculation_preview_rows"] = build_recalculation_preview_rows(result)
        st.session_state["recalculation_output_route_path"] = str(result.request.output_route_path)
        st.session_state["recalculation_output_summary_path"] = str(result.request.output_summary_path)
        st.session_state["recalculation_status"] = "準備完了"
        st.session_state["recalculation_message"] = "再計算入力の準備が完了しました。"
        st.session_state["recalculation_selected_strategy"] = ""
        st.session_state["recalculation_metrics"] = {}
        st.session_state["recalculation_result_summary_rows"] = []

    except Exception as exc:
        st.session_state["recalculation_status"] = "失敗"
        st.session_state["recalculation_message"] = f"再計算入力準備に失敗しました: {exc}"
        st.session_state["recalculation_preview_rows"] = []
        st.session_state["recalculation_output_route_path"] = ""
        st.session_state["recalculation_output_summary_path"] = ""
        st.session_state["recalculation_selected_strategy"] = ""
        st.session_state["recalculation_metrics"] = {}
        st.session_state["recalculation_result_summary_rows"] = []


def run_recalculation_action(
    operable_roads_gdf: gpd.GeoDataFrame,
    additional_roads_source_gdf: gpd.GeoDataFrame | None = None,
    rerun_after: bool = True,
) -> None:
    try:
        st.session_state["recalculation_action_call_count"] = (
            int(st.session_state.get("recalculation_action_call_count", 0)) + 1
        )
        calculation_level = get_road_selection_level()
        target_input_path = get_road_selection_target_input_path()
        preparation = build_recalculation_request(
            current_start_point=st.session_state.get("current_start_point"),
            excluded_roads=st.session_state.get("excluded_roads", set()),
            included_roads=build_recalculation_included_roads(),
            conditional_roads=st.session_state.get("conditional_roads", set()),
            additional_roads_source_gdf=(
                additional_roads_source_gdf
                if additional_roads_source_gdf is not None
                else operable_roads_gdf
            ),
            project_root=PROJECT_ROOT,
            target_input_path=target_input_path,
        )

        run_result = run_recalculation(preparation.request)
        failed_target_roads = {
            normalize_edge_id(edge_id) for edge_id in run_result.failed_target_edge_ids
        }
        failed_included_roads = {
            normalize_edge_id(edge_id) for edge_id in run_result.failed_included_edge_ids
        }
        confirmed_included_roads = build_recalculation_included_roads() - failed_included_roads
        failed_partial_roads, failed_full_roads = classify_failed_target_roads(
            failed_target_roads=failed_target_roads,
            visited_target_edge_ids=run_result.visited_target_edge_ids,
        )
        st.session_state["failed_target_roads"] = failed_target_roads
        st.session_state["failed_partial_roads"] = failed_partial_roads
        st.session_state["failed_full_roads"] = failed_full_roads
        st.session_state["confirmed_included_roads"] = confirmed_included_roads
        st.session_state["failed_included_roads"] = failed_included_roads
        st.session_state["failed_display_roads"] = build_failed_display_roads(
            failed_target_roads,
            failed_included_roads,
        )
        st.session_state["included_roads"] = set()
        st.session_state["conditional_roads"] = set()

        st.session_state["recalculation_preview_rows"] = build_recalculation_preview_rows(preparation)
        st.session_state["recalculation_selected_strategy"] = run_result.selected_strategy
        st.session_state["recalculation_metrics"] = run_result.metrics
        st.session_state["recalculation_result_summary_rows"] = (
            run_result.summary_df.to_dict(orient="records")
        )
        st.session_state["recalculation_output_route_path"] = str(run_result.request.output_route_path)
        st.session_state["recalculation_route_gdf"] = ensure_wgs84(run_result.route_gdf.copy())
        st.session_state["recalculation_output_summary_path"] = str(run_result.request.output_summary_path)
        st.session_state["recalculation_applied_road_selection_level"] = calculation_level
        st.session_state["recalculation_applied_target_input_path"] = str(target_input_path)
        if len(run_result.route_gdf) == 0:
            st.session_state["recalculation_status"] = "対象なし"
            st.session_state["recalculation_message"] = (
                f"Level {calculation_level} は対象道路なしの空ルートとして計算が完了しました。"
            )
            st.session_state["route_refresh_notice"] = (
                f"地図を Level {calculation_level} の空ルートで更新しました。"
            )
        else:
            st.session_state["recalculation_status"] = "実行完了"
            st.session_state["recalculation_message"] = (
                f"Level {calculation_level} で計算が完了しました。"
            )
            st.session_state["route_refresh_notice"] = (
                f"地図を Level {calculation_level} の計算結果で更新しました。"
            )

        save_recalculation_baseline_state()

        cached_load_geojson.clear()
        cached_read_geojson_allow_empty.clear()
        if rerun_after:
            st.rerun()

    except Exception as exc:
        st.session_state["recalculation_status"] = "失敗"
        st.session_state["recalculation_message"] = f"再計算実行に失敗しました: {exc}"


def render_header() -> None:
    st.title(APP_TITLE)
    if is_debug_mode():
        st.info(
            "デバッグモード ON: D3 由来の開発確認表示を追加で表示しています。"
            "component event 受信直後には st.rerun() を使いません。"
        )


def render_input_spec_table() -> None:
    st.subheader("入力ファイル仕様")

    rows: list[dict[str, str]] = []
    for spec in INPUT_SPECS:
        rows.append(
            {
                "用途": spec.label,
                "必須": "必須" if spec.required else "任意",
                "想定パス": str(spec.path),
                "説明": spec.description,
            }
        )

    st.dataframe(make_display_df(rows), width="stretch", hide_index=True)


def render_input_status() -> bool:
    st.subheader("入力ファイル存在確認")

    missing_required = False

    for spec in INPUT_SPECS:
        exists = spec.path.exists() and spec.path.is_file()

        if exists:
            st.success(f"{spec.label}: OK")
            st.code(str(spec.path))
        else:
            if spec.required:
                missing_required = True
                st.error(f"{spec.label}: 必須ファイルが見つかりません")
            else:
                st.warning(f"{spec.label}: 任意ファイルが見つかりません")
            st.code(str(spec.path))

    if missing_required:
        st.warning("必須ファイル不足のため、後続処理には進めません。")
        return False

    st.info("必須ファイルがそろっているため、GeoJSON 読み込み処理へ進みます。")
    return True


def required_input_status() -> tuple[bool, list[str]]:
    missing_labels: list[str] = []
    for spec in INPUT_SPECS:
        exists = spec.path.exists() and spec.path.is_file()
        if spec.required and not exists:
            missing_labels.append(spec.label)
    return len(missing_labels) == 0, missing_labels


@st.cache_data(show_spinner=False)
def cached_load_geojson(path_str: str) -> gpd.GeoDataFrame:
    return load_geojson(path_str)


def resolve_active_route_gdf() -> tuple[gpd.GeoDataFrame, str, str]:
    memory_route_gdf = st.session_state.get("recalculation_route_gdf")
    output_route_path = st.session_state.get("recalculation_output_route_path", "")
    if isinstance(memory_route_gdf, gpd.GeoDataFrame):
        return (
            ensure_wgs84(memory_route_gdf.copy()),
            str(output_route_path),
            "d3_recalculation_memory",
        )

    return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326"), "", "route_not_created"


def ensure_initial_route_gdf(
    *,
    roads_gdf: gpd.GeoDataFrame,
    priority_roads_gdf: gpd.GeoDataFrame,
) -> None:
    if isinstance(st.session_state.get("recalculation_route_gdf"), gpd.GeoDataFrame):
        return

    if st.session_state.get("current_start_point") is None:
        initial_start_point = build_initial_start_point(priority_roads_gdf)
        if initial_start_point is not None:
            st.session_state["current_start_point"] = initial_start_point
            st.session_state["start_point_source"] = "initial_route_creation"

    if st.session_state.get("current_start_point") is None:
        st.session_state["recalculation_status"] = "譛ｪ菴懈・"
        st.session_state["recalculation_message"] = (
            "蛻晄悄繝ｫ繝ｼ繝医ｒ菴懈・縺吶ｋ蜃ｺ逋ｺ轤ｹ繧呈ｱｺ繧√ｉ繧後∪縺帙ｓ縲・"
        )
        return

    try:
        preparation = build_recalculation_request(
            current_start_point=st.session_state.get("current_start_point"),
            excluded_roads=st.session_state.get("excluded_roads", set()),
            included_roads=build_recalculation_included_roads(),
            conditional_roads=st.session_state.get("conditional_roads", set()),
            additional_roads_source_gdf=roads_gdf,
            project_root=PROJECT_ROOT,
            target_input_path=get_road_selection_target_input_path(),
        )
        run_result = run_recalculation(preparation.request)
    except Exception as exc:
        logger.warning("initial route creation failed: %s", exc)
        st.session_state["recalculation_status"] = "蛻晄悄菴懈・螟ｱ謨・"
        st.session_state["recalculation_message"] = f"蛻晄悄繝ｫ繝ｼ繝医・菴懈・縺ｫ螟ｱ謨励＠縺ｾ縺励◆: {exc}"
        return

    st.session_state["recalculation_preview_rows"] = build_recalculation_preview_rows(preparation)
    st.session_state["recalculation_route_gdf"] = ensure_wgs84(run_result.route_gdf.copy())
    st.session_state["recalculation_selected_strategy"] = run_result.selected_strategy
    st.session_state["recalculation_metrics"] = run_result.metrics
    st.session_state["recalculation_result_summary_rows"] = run_result.summary_df.to_dict(
        orient="records"
    )
    st.session_state["recalculation_output_route_path"] = str(run_result.request.output_route_path)
    st.session_state["recalculation_output_summary_path"] = str(
        run_result.request.output_summary_path
    )
    st.session_state["recalculation_status"] = "蛻晄悄菴懈・螳御ｺ・"
    st.session_state["recalculation_message"] = (
        "蛻晄悄繝ｫ繝ｼ繝医ｒ繧｢繝励Μ蜀・〒菴懈・縺励∪縺励◆縲・"
    )


def render_loaded_geojson_info() -> None:
    st.subheader("GeoJSON 読み込み結果")

    for spec in INPUT_SPECS:
        if not spec.path.exists() or not spec.path.is_file():
            continue

        with st.container():
            st.markdown(f"### {spec.label}")

            try:
                gdf = cached_load_geojson(str(spec.path))
                summary = summarize_gdf(gdf)

                st.success("読み込み成功")

                info_rows = [
                    {"項目": "行数", "値": summary["rows"]},
                    {"項目": "CRS", "値": summary["crs"]},
                    {"項目": "Geometry type", "値": ", ".join(summary["geometry_type"])},
                    {"項目": "Bounds", "値": str(summary["bounds"])},
                ]
                st.dataframe(make_display_df(info_rows), width="stretch", hide_index=True)

                with st.expander("列一覧"):
                    st.write(summary["columns"])

            except Exception as exc:
                st.error(f"読み込み失敗: {exc}")

            st.divider()


def set_current_start_point_immediately(new_point: dict[str, object]) -> None:
    current_point = st.session_state.get("current_start_point")
    if current_point is not None:
        st.session_state["previous_start_point"] = dict(current_point)

    st.session_state["current_start_point"] = dict(new_point)
    st.session_state["candidate_start_point"] = None
    st.session_state["candidate_start_point_status"] = "none"
    st.session_state["start_point_source"] = str(new_point.get("source", "map_click"))
    st.session_state["start_point_message"] = "出発点を更新済み"


def restore_recalculation_baseline_start_point() -> None:
    baseline_point = st.session_state.get("recalculation_baseline_start_point")
    if baseline_point is None:
        st.session_state["start_point_operation_notice"] = (
            "最後に再計算が正常完了した時点の出発点がないため復元しませんでした。"
        )
        return

    current_point = st.session_state.get("current_start_point")
    if current_point is not None:
        st.session_state["previous_start_point"] = dict(current_point)

    st.session_state["current_start_point"] = dict(baseline_point)
    st.session_state["candidate_start_point"] = None
    st.session_state["candidate_start_point_status"] = "none"
    st.session_state["start_point_source"] = "recalculation_baseline"
    st.session_state["start_point_message"] = (
        "最後に再計算が正常完了した時点の出発点へ戻しました。"
    )
    st.session_state["start_point_operation_notice"] = (
        "出発点を再計算成功時の基準点へ戻しました。"
    )


def restore_previous_start_point() -> None:
    previous_point = st.session_state.get("previous_start_point")
    if previous_point is None:
        st.session_state["start_point_operation_notice"] = "前回の出発点がないため復元しませんでした。"
        return

    current_point = st.session_state.get("current_start_point")
    if current_point is not None:
        st.session_state["previous_start_point"] = dict(current_point)

    st.session_state["current_start_point"] = dict(previous_point)
    st.session_state["candidate_start_point"] = None
    st.session_state["candidate_start_point_status"] = "none"
    st.session_state["start_point_source"] = str(previous_point.get("source", "restored"))
    st.session_state["start_point_message"] = "前回の出発点へ復元しました。"
    st.session_state["start_point_operation_notice"] = "出発点を前回値へ戻しました。"


def init_road_instruction_state() -> None:
    if "current_route_edge_display_states" not in st.session_state:
        st.session_state["current_route_edge_display_states"] = {}

    if "conditional_roads" not in st.session_state:
        st.session_state["conditional_roads"] = set()

    if "included_roads" not in st.session_state:
        st.session_state["included_roads"] = set()

    if "confirmed_included_roads" not in st.session_state:
        st.session_state["confirmed_included_roads"] = set()

    if "failed_target_roads" not in st.session_state:
        st.session_state["failed_target_roads"] = set()

    if "failed_partial_roads" not in st.session_state:
        st.session_state["failed_partial_roads"] = set()

    if "failed_full_roads" not in st.session_state:
        st.session_state["failed_full_roads"] = set()

    if "failed_included_roads" not in st.session_state:
        st.session_state["failed_included_roads"] = set()

    if "failed_display_roads" not in st.session_state:
        st.session_state["failed_display_roads"] = get_failed_display_roads()

    if "current_route_edge_ids" not in st.session_state:
        st.session_state["current_route_edge_ids"] = set()

    if "road_operation_notice" not in st.session_state:
        st.session_state["road_operation_notice"] = ""

    if "road_operation_message" not in st.session_state:
        st.session_state["road_operation_message"] = ""


def normalize_road_instruction_state_value(value: object) -> str | None:
    text = str(value).strip().lower()
    if text in {"none", "exclude", "conditional", "include", "include_failed"}:
        return text
    return None


def _is_valid_edge_id_value(value: object) -> bool:
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except Exception:
        pass

    text = str(value).strip()
    return text != "" and text.lower() != "nan"


def build_route_edge_id_set(route_gdf: gpd.GeoDataFrame) -> set[tuple[str, str, str]]:
    required_cols = ["u", "v", "key"]
    if any(col not in route_gdf.columns for col in required_cols):
        return set()

    route_edge_ids: set[tuple[str, str, str]] = set()
    for _, row in route_gdf.iterrows():
        if not all(_is_valid_edge_id_value(row[col]) for col in required_cols):
            continue
        edge_id = normalize_edge_id((row["u"], row["v"], row["key"]))
        route_edge_ids.add(edge_id)
    return route_edge_ids


def build_route_edge_display_state_map(
    route_gdf: gpd.GeoDataFrame,
) -> dict[tuple[str, str, str], str]:
    required_cols = ["u", "v", "key"]
    if any(col not in route_gdf.columns for col in required_cols):
        return {}

    priority = {"target": 3, "connector": 2, "return": 1}
    display_states: dict[tuple[str, str, str], str] = {}

    for _, row in route_gdf.iterrows():
        if not all(_is_valid_edge_id_value(row[col]) for col in required_cols):
            continue

        edge_id = normalize_edge_id((row["u"], row["v"], row["key"]))
        display_state = normalize_route_segment_type(row.get("segment_type"))
        current_display_state = display_states.get(edge_id)
        if current_display_state is None or priority.get(display_state, 0) > priority.get(
            current_display_state,
            0,
        ):
            display_states[edge_id] = display_state

    return display_states


def get_road_instruction_state(edge_id: tuple[object, object, object] | None) -> str:
    if edge_id is None:
        return "none"

    failed_display_roads = get_failed_display_roads()
    included_roads = st.session_state.get("included_roads", set())
    conditional_roads = st.session_state.get("conditional_roads", set())
    excluded_roads = st.session_state.get("excluded_roads", set())

    if is_excluded_road(edge_id, excluded_roads):
        return "exclude"
    if is_road_in_set(edge_id, failed_display_roads):
        return "include_failed"
    if is_road_in_set(edge_id, included_roads):
        return "include"
    if is_road_in_set(edge_id, conditional_roads):
        return "conditional"
    return "none"


def get_road_display_state(
    edge_id: tuple[object, object, object] | None,
    *,
    display_state_override: str | None = None,
) -> str:
    if edge_id is None:
        return "none"

    normalized_override = str(display_state_override).strip().lower()
    if normalized_override == "blue":
        return "target"
    if normalized_override == "gray":
        return "candidate"
    if normalized_override in {
        "target",
        "connector",
        "return",
        "candidate",
        "non_operable",
        "black",
        "orange",
        "magenta",
        "red",
        "transparent",
    }:
        return normalized_override

    instruction_state = get_road_instruction_state(edge_id)
    if instruction_state == "exclude":
        return "black"
    if instruction_state == "include_failed":
        return "red"
    if instruction_state == "include":
        return "magenta"
    if instruction_state == "conditional":
        return "orange"

    current_route_edge_display_states = st.session_state.get(
        "current_route_edge_display_states",
        {},
    )
    normalized_edge_id = normalize_edge_id(edge_id)
    if normalized_edge_id in current_route_edge_display_states:
        return str(current_route_edge_display_states[normalized_edge_id])

    current_route_edge_ids = st.session_state.get("current_route_edge_ids", set())
    return "target" if normalized_edge_id in current_route_edge_ids else "candidate"


def set_road_instruction_state(
    edge_id: tuple[object, object, object] | None,
    instruction_state: str,
) -> None:
    if edge_id is None:
        st.session_state["road_operation_notice"] = "道路が未選択です。"
        return

    normalized_edge_id = normalize_edge_id(edge_id)
    excluded_roads = st.session_state.get("excluded_roads", set())
    conditional_roads = st.session_state.get("conditional_roads", set())
    included_roads = st.session_state.get("included_roads", set())
    confirmed_included_roads = st.session_state.get("confirmed_included_roads", set())
    failed_target_roads = st.session_state.get("failed_target_roads", set())
    failed_partial_roads = st.session_state.get("failed_partial_roads", set())
    failed_full_roads = st.session_state.get("failed_full_roads", set())
    failed_included_roads = st.session_state.get("failed_included_roads", set())
    after_black_clear_roads = st.session_state.get("after_black_clear_roads", set())
    was_black = is_excluded_road(normalized_edge_id, excluded_roads)
    state_edge_ids = build_road_state_edge_ids(normalized_edge_id)

    if instruction_state == "exclude":
        excluded_roads = add_road_state_edges(excluded_roads, state_edge_ids)
        conditional_roads = remove_road_state_edges(conditional_roads, state_edge_ids)
        included_roads = remove_road_state_edges(included_roads, state_edge_ids)
        confirmed_included_roads = remove_road_state_edges(
            confirmed_included_roads,
            state_edge_ids,
        )
        failed_target_roads = remove_road_state_edges(failed_target_roads, state_edge_ids)
        failed_partial_roads = remove_road_state_edges(failed_partial_roads, state_edge_ids)
        failed_full_roads = remove_road_state_edges(failed_full_roads, state_edge_ids)
        failed_included_roads = remove_road_state_edges(failed_included_roads, state_edge_ids)
        after_black_clear_roads = remove_road_state_edges(after_black_clear_roads, state_edge_ids)
        notice = "道路を黒指示（除外 / 使用禁止）にしました。"
        message = f"道路を黒指示（除外 / 使用禁止）にしました: {format_road_edge_id(normalized_edge_id)}"
    elif instruction_state == "conditional":
        excluded_roads = remove_road_state_edges(excluded_roads, state_edge_ids)
        conditional_roads = add_road_state_edges(conditional_roads, state_edge_ids)
        included_roads = remove_road_state_edges(included_roads, state_edge_ids)
        confirmed_included_roads = remove_road_state_edges(
            confirmed_included_roads,
            state_edge_ids,
        )
        failed_target_roads = remove_road_state_edges(failed_target_roads, state_edge_ids)
        failed_partial_roads = remove_road_state_edges(failed_partial_roads, state_edge_ids)
        failed_full_roads = remove_road_state_edges(failed_full_roads, state_edge_ids)
        failed_included_roads = remove_road_state_edges(failed_included_roads, state_edge_ids)
        after_black_clear_roads = remove_road_state_edges(after_black_clear_roads, state_edge_ids)
        notice = "条件付き許可 / Orange に切り替えました。"
        message = f"条件付き許可 / Orange に切り替えました: {format_road_edge_id(normalized_edge_id)}"
    elif instruction_state == "include":
        excluded_roads = remove_road_state_edges(excluded_roads, state_edge_ids)
        conditional_roads = remove_road_state_edges(conditional_roads, state_edge_ids)
        included_roads = add_road_state_edges(included_roads, state_edge_ids)
        confirmed_included_roads = remove_road_state_edges(
            confirmed_included_roads,
            state_edge_ids,
        )
        failed_target_roads = remove_road_state_edges(failed_target_roads, state_edge_ids)
        failed_partial_roads = remove_road_state_edges(failed_partial_roads, state_edge_ids)
        failed_full_roads = remove_road_state_edges(failed_full_roads, state_edge_ids)
        failed_included_roads = remove_road_state_edges(failed_included_roads, state_edge_ids)
        after_black_clear_roads = remove_road_state_edges(after_black_clear_roads, state_edge_ids)
        notice = "道路を追加指示（マゼンダ）にしました。"
        message = f"道路を追加指示（マゼンダ）にしました: {format_road_edge_id(normalized_edge_id)}"
    elif instruction_state == "none":
        excluded_roads = remove_road_state_edges(excluded_roads, state_edge_ids)
        conditional_roads = remove_road_state_edges(conditional_roads, state_edge_ids)
        included_roads = remove_road_state_edges(included_roads, state_edge_ids)
        confirmed_included_roads = remove_road_state_edges(
            confirmed_included_roads,
            state_edge_ids,
        )
        failed_target_roads = remove_road_state_edges(failed_target_roads, state_edge_ids)
        failed_partial_roads = remove_road_state_edges(failed_partial_roads, state_edge_ids)
        failed_full_roads = remove_road_state_edges(failed_full_roads, state_edge_ids)
        failed_included_roads = remove_road_state_edges(failed_included_roads, state_edge_ids)
        if was_black:
            after_black_clear_roads = add_road_state_edges(after_black_clear_roads, state_edge_ids)
        else:
            after_black_clear_roads = remove_road_state_edges(
                after_black_clear_roads,
                state_edge_ids,
            )
        notice = "道路の差分指示を解除しました。"
        message = f"道路の差分指示を解除しました: {format_road_edge_id(normalized_edge_id)}"
    else:
        raise ValueError(f"unsupported instruction_state: {instruction_state}")

    st.session_state["selected_road_id"] = normalized_edge_id
    st.session_state["excluded_roads"] = excluded_roads
    st.session_state["conditional_roads"] = conditional_roads
    st.session_state["included_roads"] = included_roads
    st.session_state["confirmed_included_roads"] = confirmed_included_roads
    st.session_state["failed_target_roads"] = failed_target_roads
    st.session_state["failed_partial_roads"] = failed_partial_roads
    st.session_state["failed_full_roads"] = failed_full_roads
    st.session_state["failed_included_roads"] = failed_included_roads
    st.session_state["failed_display_roads"] = build_failed_display_roads(
        failed_target_roads,
        failed_included_roads,
    )
    st.session_state["after_black_clear_roads"] = after_black_clear_roads
    st.session_state["road_operation_notice"] = notice
    st.session_state["road_operation_message"] = message


def apply_road_click_transition(
    edge_id: tuple[object, object, object] | None,
    current_display_state: str | None = None,
    next_instruction_state: str | None = None,
) -> None:
    normalized_next_instruction_state = normalize_road_instruction_state_value(next_instruction_state)
    if normalized_next_instruction_state is not None:
        set_road_instruction_state(edge_id, normalized_next_instruction_state)
        return

    persisted_instruction_state = get_road_instruction_state(edge_id)
    if persisted_instruction_state != "none":
        display_state = get_road_display_state(edge_id)
    elif current_display_state is not None:
        display_state = get_road_display_state(edge_id, display_state_override=current_display_state)
    else:
        display_state = get_road_display_state(edge_id)

    if display_state == "black":
        next_instruction_state = "none"
    elif display_state == "red":
        next_instruction_state = "include"
    elif display_state == "magenta":
        next_instruction_state = "conditional"
    elif display_state == "orange":
        next_instruction_state = "exclude"
    else:
        next_instruction_state = "include"

    set_road_instruction_state(edge_id, next_instruction_state)


def handle_component_event(event: dict[str, object] | None) -> None:
    if event is None:
        return

    event_type = str(event.get("event_type", ""))
    event_nonce = str(event.get("event_nonce", "")).strip()
    event_sync_nonce = int(event.get("sync_nonce", 0) or 0)
    event_instance_key = build_component_event_instance_key(event)
    map_view_state = normalize_map_view_state(event.get("map_view_state"))

    st.session_state["last_component_event"] = event
    st.session_state["last_component_event_type"] = event_type
    st.session_state["last_component_event_nonce"] = event_nonce
    if map_view_state is not None:
        st.session_state["last_map_view_state"] = map_view_state
        st.session_state["last_map_view_state_source"] = event_type

    if (
        event_instance_key != ""
        and event_instance_key == st.session_state.get(LAST_HANDLED_COMPONENT_EVENT_KEY, "")
    ):
        st.session_state["last_component_event_status"] = "skipped_duplicate"
        st.session_state["duplicate_component_event_skip_count"] = (
            int(st.session_state.get("duplicate_component_event_skip_count", 0)) + 1
        )
        return

    st.session_state["last_component_event_status"] = "processed"
    st.session_state["last_component_event_count"] = (
        int(st.session_state.get("last_component_event_count", 0)) + 1
    )
    if event_instance_key != "":
        st.session_state[LAST_HANDLED_COMPONENT_EVENT_KEY] = event_instance_key

    if event_type == "map_view_update":
        return

    if event_type == "road_instructions_sync":
        instructions_payload = event.get("instructions")
        synced_count = 0
        if isinstance(instructions_payload, list):
            for item in instructions_payload:
                if not isinstance(item, dict):
                    continue
                edge_payload = item.get("edge_id")
                if not isinstance(edge_payload, dict):
                    continue
                instruction_state = normalize_road_instruction_state_value(
                    item.get("instruction_state")
                )
                if instruction_state is None or instruction_state == "include_failed":
                    continue
                selected_edge_id = normalize_edge_id(
                    (edge_payload.get("u"), edge_payload.get("v"), edge_payload.get("key"))
                )
                set_road_instruction_state(selected_edge_id, instruction_state)
                synced_count += 1

        st.session_state["last_instruction_sync_count"] = synced_count
        st.session_state["last_instruction_sync_event_nonce"] = event_nonce
        st.session_state["last_instruction_sync_nonce"] = event_sync_nonce
        return

    if event_type == "road_select":
        edge_payload = event.get("edge_id")
        if isinstance(edge_payload, dict):
            selected_edge_id = normalize_edge_id(
                (edge_payload.get("u"), edge_payload.get("v"), edge_payload.get("key"))
            )
            st.session_state["selected_road_id"] = selected_edge_id
            queue_road_selection_widget_sync(selected_edge_id)
            st.session_state["road_operation_notice"] = (
                f"道路を選択しました: {format_road_edge_id(selected_edge_id)}"
            )
        return

    if event_type == "start_point_set":
        lat = float(event["lat"])
        lon = float(event["lon"])
        new_point = {
            "lat": lat,
            "lon": lon,
            "source": "map_click_component",
            "snap_applied": False,
            "snap_reason": None,
        }
        set_current_start_point_immediately(new_point)
        st.session_state["start_point_operation_notice"] = "出発点を更新しました。"
        return

    if event_type == "road_toggle":
        edge_payload = event.get("edge_id")
        selected_edge_id = None
        if isinstance(edge_payload, dict):
            selected_edge_id = normalize_edge_id(
                (edge_payload.get("u"), edge_payload.get("v"), edge_payload.get("key"))
            )
            st.session_state["selected_road_id"] = selected_edge_id
            queue_road_selection_widget_sync(selected_edge_id)
        current_display_state = str(event.get("display_state", "")).strip().lower()
        next_instruction_state = normalize_road_instruction_state_value(
            event.get("next_instruction_state")
        )
        apply_road_click_transition(
            selected_edge_id,
            current_display_state=current_display_state if current_display_state != "" else None,
            next_instruction_state=next_instruction_state,
        )
        return

    if event_type == "road_clear":
        st.session_state["selected_road_id"] = None
        queue_road_selection_widget_sync(None)
        st.session_state["road_operation_notice"] = "道路選択を解除しました。"
        return

    if event_type == "start_point_restore":
        restore_previous_start_point()
        return

    if event_type == "start_point_restore_to_recalculation_baseline":
        restore_recalculation_baseline_start_point()
        return

    # component event 直後の st.rerun() は bridge 受信を壊すことが
    # 切り分け確認で判明したため、ここでは rerun しない。


def build_operation_summary_rows(
    *,
    operable_roads_gdf: gpd.GeoDataFrame,
) -> list[dict[str, object]]:
    current_point = st.session_state.get("current_start_point")
    previous_point = st.session_state.get("previous_start_point")
    candidate_point = st.session_state.get("candidate_start_point")
    selected_road_id = st.session_state.get("selected_road_id")
    excluded_roads = st.session_state.get("excluded_roads", set())
    conditional_roads = st.session_state.get("conditional_roads", set())
    included_roads = st.session_state.get("included_roads", set())
    failed_included_roads = st.session_state.get("failed_included_roads", set())
    excluded_count = len(excluded_roads)
    candidate_status = st.session_state.get("candidate_start_point_status", "none")
    start_source = st.session_state.get("start_point_source", "unknown")

    selected_state = "未選択"
    if selected_road_id is not None:
        selected_state = (
            "除雪対象外 / 使用禁止"
            if is_excluded_road(selected_road_id, excluded_roads)
            else "使用可"
        )

    selected_state = get_road_display_state(selected_road_id)
    selected_name = build_road_display_name(operable_roads_gdf, selected_road_id)

    return [
        {"項目": "現在の出発点", "値": format_point_text(current_point)},
        {"項目": "前回の出発点", "値": format_point_text(previous_point)},
        {"項目": "出発点の由来", "値": str(start_source)},
        {
            "項目": "候補点",
            "値": "なし" if candidate_point is None else format_point_text(candidate_point),
        },
        {"項目": "候補点状態", "値": str(candidate_status)},
        {"項目": "除雪対象外件数", "値": int(excluded_count)},
        {"項目": "選択中道路", "値": selected_name},
        {"項目": "選択中道路の状態", "値": selected_state},
    ]


def render_operation_summary_panel(
    operable_roads_gdf: gpd.GeoDataFrame,
    debug_mode: bool = False,
) -> None:
    st.subheader("操作結果サマリ")

    summary_rows = build_operation_summary_rows(
        operable_roads_gdf=operable_roads_gdf,
    )
    if debug_mode:
        st.dataframe(make_display_df(summary_rows), width="stretch", hide_index=True)

    current_point = st.session_state.get("current_start_point")
    previous_point = st.session_state.get("previous_start_point")
    candidate_point = st.session_state.get("candidate_start_point")
    excluded_count = len(st.session_state.get("excluded_roads", set()))
    col1, col2 = st.columns(2)
    with col1:
        st.metric("現在の出発点", "設定済み" if current_point is not None else "未設定")
        st.metric("候補点", "あり" if candidate_point is not None else "なし")
    with col2:
        st.metric("前回の出発点", "あり" if previous_point is not None else "なし")
        st.metric("除雪対象外件数", str(excluded_count))


def render_d3_handoff_panel() -> None:
    st.subheader("D3 受け渡し整理")

    payload = build_d3_handoff_payload(
        current_point=st.session_state.get("current_start_point"),
        candidate_point=st.session_state.get("candidate_start_point"),
        previous_point=st.session_state.get("previous_start_point"),
        excluded_roads=st.session_state.get("excluded_roads", set()),
        selected_road_id=st.session_state.get("selected_road_id"),
        start_source=str(st.session_state.get("start_point_source", "unknown")),
        candidate_status=str(st.session_state.get("candidate_start_point_status", "none")),
        direction_enabled=False,
        validate_start_point_dict=validate_start_point_dict,
        normalize_edge_id_list=normalize_edge_id_list,
        format_point_text=format_point_text,
        format_road_edge_id=format_road_edge_id,
        is_excluded_road=lambda edge_id: is_excluded_road(
            edge_id,
            st.session_state.get("excluded_roads", set()),
        ),
    )
    _, errors = validate_d3_handoff_payload(
        payload=payload,
        validate_start_point_dict=validate_start_point_dict,
    )

    summary_rows = build_d3_handoff_summary_rows(
        payload=payload,
        format_point_text=format_point_text,
    )
    st.dataframe(make_display_df(summary_rows), width="stretch", hide_index=True)

    conditions = payload.get("recalculation_conditions", {})
    recalculation_status = conditions.get("recalculation_status", "不明")
    recalculation_reason = conditions.get("recalculation_reason", "不明")

    if recalculation_status == "可":
        st.success(recalculation_reason)
    elif recalculation_status == "保留":
        st.warning(recalculation_reason)
    else:
        st.error(recalculation_reason)

    if errors:
        with st.expander("受け渡し整合チェック詳細"):
            for error in errors:
                st.write(f"- {error}")

    with st.expander("D3受け渡しペイロード（JSON）"):
        st.json(payload, expanded=False)


def normalize_weather_selected_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return pd.to_datetime(value).date()
    except Exception:
        return DEFAULT_WEATHER_SELECTED_DATE


def normalize_weather_selected_hour(value: object) -> int:
    try:
        hour = int(value)
    except (TypeError, ValueError):
        return DEFAULT_WEATHER_SELECTED_HOUR
    return hour if 0 <= hour <= 23 else DEFAULT_WEATHER_SELECTED_HOUR


def build_weather_prediction_until_datetime(
    result,
    target_datetime: datetime | pd.Timestamp,
) -> tuple[int, pd.Timestamp]:
    target_end = pd.Timestamp(target_datetime)
    feature_df = result.feature_df.copy()
    feature_df["datetime"] = pd.to_datetime(feature_df["datetime"], errors="coerce")
    target_feature_df = feature_df.loc[feature_df["datetime"] <= target_end].copy()

    if len(target_feature_df) == 0:
        raise ValueError(f"no weather feature rows found by target_datetime={target_end}")

    inference_input_result = build_weather_inference_input_result(target_feature_df)
    model_path = PROJECT_ROOT / "Data" / "models" / "rf_level_model.joblib"
    model = load_weather_prediction_model(model_path)
    pred_level = predict_weather_level_single(
        model,
        inference_input_result.model_input_df,
    )

    return pred_level, inference_input_result.latest_datetime


def apply_weather_pred_level_to_road_selection() -> bool:
    pred_level = st.session_state.get("weather_pred_level")
    if pred_level is None:
        st.session_state["weather_update_message"] = (
            "反映できる推定レベルがありません。先に気象レベルを推定してください。"
        )
        return False

    level = normalize_road_selection_level(pred_level)
    st.session_state["road_selection_level"] = level
    queue_road_selection_level_widget_sync(level)
    st.session_state["weather_update_message"] = (
        f"推定された除雪レベル Level {level} を表示対象レベルに反映しました。"
        "ルートを更新するには、下の再計算で変更を確定してください。"
    )
    return True


def run_weather_prediction_update(
    *,
    demo_mode: bool,
    selected_date: date,
    selected_hour: int,
) -> bool:
    station_num = str(
        st.session_state.get("weather_station_num", DEFAULT_WEATHER_STATION_NUM)
    ).strip()
    station_name = str(
        st.session_state.get("weather_station_name", DEFAULT_WEATHER_STATION_NAME)
    ).strip()
    if demo_mode:
        end_date = selected_date
        target_datetime = datetime.combine(
            selected_date,
            time(hour=normalize_weather_selected_hour(selected_hour)),
        )
        source = "weather_prediction_pipeline_demo_hour"
    else:
        end_date = date.today()
        target_datetime = None
        source = "weather_prediction_pipeline_latest_observation"
    fetch_start_date = end_date - timedelta(days=1)

    try:
        config = WeatherPredictionPipelineConfig(
            station_num=station_num or DEFAULT_WEATHER_STATION_NUM,
            station_name=station_name or None,
        )
        result = run_weather_prediction_pipeline(
            config=config,
            start_date=fetch_start_date,
            end_date=end_date,
            project_root=PROJECT_ROOT,
        )
        raw_pipeline_pred_level = normalize_road_selection_level(result.pred_level)
        if target_datetime is None:
            target_pred_level = raw_pipeline_pred_level
            target_latest_datetime = result.latest_datetime
        else:
            target_pred_level, target_latest_datetime = build_weather_prediction_until_datetime(
                result,
                target_datetime,
            )
        pred_level = normalize_road_selection_level(target_pred_level)

        st.session_state["weather_pred_level"] = pred_level
        st.session_state["weather_latest_datetime"] = target_latest_datetime
        st.session_state["weather_target_datetime"] = (
            target_latest_datetime if target_datetime is None else pd.Timestamp(target_datetime)
        )
        st.session_state["weather_fetch_rows"] = result.fetch_rows
        st.session_state["weather_feature_rows"] = result.feature_rows
        st.session_state["weather_raw_pipeline_pred_level"] = raw_pipeline_pred_level
        st.session_state["weather_prediction_updated_at"] = datetime.now().isoformat(
            timespec="seconds"
        )
        st.session_state["weather_prediction_source"] = source
        st.session_state["weather_update_status"] = "更新完了"
        st.session_state["weather_update_message"] = (
            f"推定された除雪レベルは Level {pred_level} です。"
            "表示対象レベルへ反映するには、反映ボタンを押してください。"
            "ルートを更新するには、その後に再計算してください。"
        )
        return True

    except Exception as exc:
        st.session_state["weather_update_status"] = "失敗"
        st.session_state["weather_update_message"] = (
            f"気象推定に失敗しました: {exc}。表示対象レベルは変更していません。"
        )
        st.session_state["weather_pred_level"] = None
        return False


def resolve_road_selection_level_for_calculation() -> bool:
    demo_mode = bool(st.session_state.get("weather_demo_mode", True))
    level_input_mode = st.session_state.get(
        "level_input_mode",
        LEVEL_INPUT_MODE_INFERENCE,
    )

    if demo_mode and level_input_mode == LEVEL_INPUT_MODE_MANUAL:
        level = normalize_road_selection_level(
            st.session_state.get(ROAD_SELECTION_LEVEL_WIDGET_KEY, get_road_selection_level())
        )
        st.session_state["road_selection_level"] = level
        st.session_state["weather_update_status"] = "手動指定"
        st.session_state["weather_prediction_source"] = ""
        st.session_state["weather_update_message"] = (
            f"指定された除雪レベル Level {level} で計算します。"
        )
        return True

    selected_date = normalize_weather_selected_date(
        st.session_state.get("weather_selected_date", DEFAULT_WEATHER_SELECTED_DATE)
    )
    selected_hour = normalize_weather_selected_hour(
        st.session_state.get("weather_selected_hour", DEFAULT_WEATHER_SELECTED_HOUR)
    )
    if not run_weather_prediction_update(
        demo_mode=demo_mode,
        selected_date=selected_date,
        selected_hour=selected_hour,
    ):
        st.session_state["recalculation_status"] = "失敗"
        st.session_state["recalculation_message"] = (
            "気象推論に失敗したため、計算を実行しませんでした。"
        )
        return False

    pred_level = st.session_state.get("weather_pred_level")
    if pred_level is None:
        st.session_state["recalculation_status"] = "失敗"
        st.session_state["recalculation_message"] = (
            "推定された除雪レベルを取得できなかったため、計算を実行しませんでした。"
        )
        return False

    level = normalize_road_selection_level(pred_level)
    st.session_state["road_selection_level"] = level
    queue_road_selection_level_widget_sync(level)
    st.session_state["weather_update_message"] = (
        f"推定された除雪レベル Level {level} で計算します。"
    )
    return True


def run_calculation_action(
    operable_roads_gdf: gpd.GeoDataFrame,
    additional_roads_source_gdf: gpd.GeoDataFrame | None = None,
    rerun_after: bool = True,
) -> None:
    if not resolve_road_selection_level_for_calculation():
        return

    run_recalculation_action(
        operable_roads_gdf,
        additional_roads_source_gdf=additional_roads_source_gdf,
        rerun_after=rerun_after,
    )


def render_level_summary_card(label: str, value: str) -> None:
    st.markdown(
        f"""
        <div style="
            border: 1px solid rgba(128, 132, 149, 0.22);
            border-radius: 6px;
            padding: 0.38rem 0.55rem;
            min-height: 48px;
            background: rgba(128, 132, 149, 0.08);
        ">
            <div style="
                color: rgba(128, 132, 149, 0.86);
                font-size: 0.74rem;
                line-height: 1.2;
                margin-bottom: 0.2rem;
            ">{label}</div>
            <div style="
                color: inherit;
                font-size: 1rem;
                line-height: 1.25;
                font-weight: 550;
            ">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_weather_prediction_panel(debug_mode: bool = False) -> None:
    st.subheader("気象情報")

    demo_mode = bool(st.session_state.get("weather_demo_mode", True))
    sync_pending_road_selection_level_widget()

    model_label = WEATHER_MODEL_HORIZON_LABELS[ACTIVE_WEATHER_MODEL_HORIZON]
    st.selectbox(
        "推論モデル",
        options=[ACTIVE_WEATHER_MODEL_HORIZON],
        index=0,
        format_func=lambda horizon: WEATHER_MODEL_HORIZON_LABELS[horizon],
        key="weather_model_horizon",
        help="MVPでは12hモデルのみ利用可能です。",
    )
    st.caption("3h / 6h / 18h / 24h モデルは準備中です。実推論では12hモデルのみ使います。")

    current_level_input_mode = st.session_state.get(
        "level_input_mode",
        LEVEL_INPUT_MODE_INFERENCE,
    )
    if current_level_input_mode not in LEVEL_INPUT_MODE_OPTIONS:
        current_level_input_mode = LEVEL_INPUT_MODE_INFERENCE

    level_input_mode = st.radio(
        "除雪レベルの決め方",
        options=LEVEL_INPUT_MODE_OPTIONS,
        index=LEVEL_INPUT_MODE_OPTIONS.index(current_level_input_mode),
        key="level_input_mode",
    )
    effective_level_input_mode = (
        level_input_mode
        if demo_mode
        else LEVEL_INPUT_MODE_INFERENCE
    )
    if not demo_mode and level_input_mode == LEVEL_INPUT_MODE_MANUAL:
        st.caption("実運用モードでは、最新の気象データから除雪レベルを推定して計算します。")

    status = st.session_state.get("weather_update_status", "未実行")
    message = st.session_state.get("weather_update_message", "")
    pred_level = st.session_state.get("weather_pred_level")
    latest_datetime = st.session_state.get("weather_latest_datetime")
    target_datetime = st.session_state.get("weather_target_datetime")
    updated_at = st.session_state.get("weather_prediction_updated_at")
    current_level = get_road_selection_level()

    if effective_level_input_mode == LEVEL_INPUT_MODE_MANUAL:
        selected_level = st.selectbox(
            "除雪レベルの設定",
            options=[0, 1, 2, 3],
            index=[0, 1, 2, 3].index(current_level),
            format_func=lambda level: f"Level {level}",
            help="ここで指定したレベルを表示対象・再計算に使用します。",
            key=ROAD_SELECTION_LEVEL_WIDGET_KEY,
        )
        st.session_state["road_selection_level"] = normalize_road_selection_level(selected_level)
        current_level = get_road_selection_level()
        render_level_summary_card("現在選択中の除雪レベル", f"Level {current_level}")
        st.caption("指定した除雪レベルを使って表示対象道路と再計算を行います。")
    else:
        if demo_mode:
            selected_date = normalize_weather_selected_date(
                st.date_input(
                    "推論対象日",
                    key="weather_selected_date",
                    help="デモモードでは過去代表日を指定して除雪レベルを推定します。",
                )
            )
            selected_hour = normalize_weather_selected_hour(
                st.selectbox(
                    "推論対象時刻",
                    options=list(range(24)),
                    index=normalize_weather_selected_hour(
                        st.session_state.get("weather_selected_hour", DEFAULT_WEATHER_SELECTED_HOUR)
                    ),
                    format_func=lambda hour: f"{hour:02d}:00",
                    key="weather_selected_hour",
                )
            )
            fetch_end_date = selected_date
            target_text = f"{selected_date.isoformat()} {selected_hour:02d}:00 までの最新観測行"
            run_button_label = "対象日の気象レベルを推定"
        else:
            selected_date = date.today()
            selected_hour = DEFAULT_WEATHER_SELECTED_HOUR
            fetch_end_date = selected_date
            target_text = "取得できた最新の1時間単位観測時刻"
            run_button_label = "最新気象データで気象レベルを推定"

        fetch_start_date = fetch_end_date - timedelta(days=1)
        if debug_mode:
            st.caption(f"取得範囲: {fetch_start_date.isoformat()} 〜 {fetch_end_date.isoformat()}")
            st.caption(f"推論対象: {target_text}")
            if not demo_mode:
                st.caption("現在時刻そのものではなく、JMAから取得できた最新の1時間単位観測時刻を使います。")

        if st.button(run_button_label, width="stretch"):
            with st.spinner("気象データを取得して推論しています..."):
                if run_weather_prediction_update(
                    demo_mode=demo_mode,
                    selected_date=selected_date,
                    selected_hour=selected_hour,
                ):
                    st.rerun()
        st.caption("気象レベルだけ確認できます。ルート更新は下の「変更を確定して計算」で行います。")

        level_cols = st.columns(2)
        with level_cols[0]:
            render_level_summary_card("現在選択中の除雪レベル", f"Level {current_level}")
        with level_cols[1]:
            render_level_summary_card(
                "気象推論の推定レベル",
                "-" if pred_level is None else f"Level {pred_level}",
            )

        if debug_mode:
            apply_disabled = pred_level is None or status != "更新完了"
            if st.button(
                "この推定レベルを表示対象レベルに反映",
                width="stretch",
                disabled=apply_disabled,
            ):
                if apply_weather_pred_level_to_road_selection():
                    st.rerun()

    status_rows = [
        {"項目": "status", "値": status},
        {"項目": "station_num", "値": st.session_state.get("weather_station_num", "")},
        {"項目": "station_name", "値": st.session_state.get("weather_station_name", "")},
        {"項目": "model", "値": model_label},
        {"項目": "pred_level", "値": "" if pred_level is None else pred_level},
        {"項目": "current_road_selection_level", "値": current_level},
        {"項目": "target_datetime", "値": "" if target_datetime is None else target_datetime},
        {"項目": "latest_datetime", "値": "" if latest_datetime is None else latest_datetime},
        {"項目": "fetch_rows", "値": st.session_state.get("weather_fetch_rows", "")},
        {"項目": "feature_rows", "値": st.session_state.get("weather_feature_rows", "")},
        {"項目": "updated_at", "値": "" if updated_at is None else updated_at},
        {"項目": "source", "値": st.session_state.get("weather_prediction_source", "")},
    ]

    if debug_mode:
        st.dataframe(make_display_df(status_rows), width="stretch", hide_index=True)

    if debug_mode:
        st.caption(
            "気象推定 level は推奨値、road_selection_level は次のD3再計算に使う道路レベルです。"
            "通常表示では除雪レベルの決め方から操作します。"
        )

    if message:
        if status == "失敗":
            st.error(message)
        elif debug_mode:
            if status == "更新完了":
                st.success(message)
            else:
                st.info(message)
        elif status == "更新完了":
            st.caption("推定レベルは自動反映されません。")

    st.checkbox(
        "デモモードを使用する",
        key="weather_demo_mode",
        help="推論日を使用する場合に、デモ用の日付と時刻を指定できます。",
    )


def render_recalculation_panel(
    operable_roads_gdf: gpd.GeoDataFrame,
    additional_roads_source_gdf: gpd.GeoDataFrame | None = None,
    debug_mode: bool = False,
) -> None:
    st.subheader("計算")

    ready_status, ready_message = build_recalculation_ready_state()
    current_level = get_road_selection_level()
    current_target_input_path = get_road_selection_target_input_path()

    if (
        st.session_state.get("pending_recalculation_after_instruction_sync", False)
        and st.session_state.get("last_component_event_type") == "road_instructions_sync"
        and int(st.session_state.get("last_instruction_sync_nonce", 0) or 0)
        == int(st.session_state.get("pending_instruction_sync_nonce", 0) or 0)
    ):
        st.session_state["pending_recalculation_after_instruction_sync"] = False
        with st.spinner("Applying pending map changes before recalculation..."):
            run_calculation_action(
                operable_roads_gdf=operable_roads_gdf,
                additional_roads_source_gdf=additional_roads_source_gdf,
            )

    current_status = st.session_state.get("recalculation_status", "未実行")
    current_message = st.session_state.get("recalculation_message", "")

    if debug_mode:
        if ready_status == "可":
            st.success(ready_message)
        elif ready_status == "保留":
            st.warning(ready_message)
        else:
            st.error(ready_message)
        st.write({"状態": current_status})
        st.metric("再計算に使う除雪レベル", f"Level {current_level}")
        st.caption(f"target_input_path: {current_target_input_path}")
        if current_message:
            st.info(current_message)
    elif ready_status != "可":
        if ready_status == "保留":
            st.warning(ready_message)
        else:
            st.error(ready_message)
    elif current_message and current_status in {"実行完了", "対象なし", "失敗"}:
        if current_status == "失敗":
            st.error(current_message)
        elif current_status == "対象なし":
            st.info(current_message)
        else:
            st.success(current_message)

    action_col, reset_col = st.columns(2)

    with action_col:
        if st.button(
            "変更を確定して計算",
            width="stretch",
            disabled=(ready_status != "可"),
        ):
            with st.spinner("除雪レベルを決定して計算しています..."):
                if not debug_mode:
                    request_pending_instruction_sync_for_recalculation()
                    st.rerun()
                run_calculation_action(
                    operable_roads_gdf,
                    additional_roads_source_gdf=additional_roads_source_gdf,
                )
            if st.session_state.get("recalculation_status") == "失敗":
                st.error(st.session_state.get("recalculation_message", "計算に失敗しました。"))

    with reset_col:
        if st.button("設定をやり直す", width="stretch"):
            if restore_recalculation_baseline_state():
                st.rerun()

    if debug_mode:
        st.markdown("#### 開発者向け: 再計算入力")
        if st.button(
            "再計算入力を準備",
            width="stretch",
            disabled=(ready_status != "可"),
        ):
            run_recalculation_preview(
                operable_roads_gdf,
                additional_roads_source_gdf=additional_roads_source_gdf,
            )

    preview_rows = st.session_state.get("recalculation_preview_rows", [])
    if debug_mode and preview_rows:
        st.markdown("#### 再計算プレビュー")
        st.dataframe(make_display_df(preview_rows), width="stretch", hide_index=True)

    selected_strategy = st.session_state.get("recalculation_selected_strategy", "")
    if debug_mode and selected_strategy:
        st.markdown("#### 選択 strategy")
        st.write(selected_strategy)

    metrics = st.session_state.get("recalculation_metrics", {})
    if debug_mode and metrics:
        st.markdown("#### 再計算 metrics")
        metric_rows = [{"項目": key, "値": value} for key, value in metrics.items()]
        st.dataframe(make_display_df(metric_rows), width="stretch", hide_index=True)

    summary_rows = st.session_state.get("recalculation_result_summary_rows", [])
    if debug_mode and summary_rows:
        st.markdown("#### 再計算 summary")
        st.dataframe(make_display_df(summary_rows), width="stretch", hide_index=True)

    output_route_path = st.session_state.get("recalculation_output_route_path", "")
    output_summary_path = st.session_state.get("recalculation_output_summary_path", "")

    if debug_mode and (output_route_path or output_summary_path):
        st.markdown("#### 出力先")
        output_rows: list[dict[str, object]] = []
        if output_route_path:
            output_rows.append({"項目": "output_route_path", "値": output_route_path})
        if output_summary_path:
            output_rows.append({"項目": "output_summary_path", "値": output_summary_path})
        st.dataframe(make_display_df(output_rows), width="stretch", hide_index=True)


def is_d3_test_fixture_enabled() -> bool:
    return os.environ.get(D3_TEST_FIXTURE_ENV, "").strip() == "1"


def normalize_fixture_edge_set(
    payload: dict[str, object],
    key: str,
) -> set[tuple[str, str, str]]:
    raw_edges = payload.get(key, [])
    if raw_edges is None:
        return set()
    if not isinstance(raw_edges, list):
        raise ValueError(f"{key} must be a list")

    normalized_edges: set[tuple[str, str, str]] = set()
    for raw_edge in raw_edges:
        normalized_edges.add(normalize_edge_id(raw_edge))
    return normalized_edges


def normalize_fixture_selected_road_id(
    payload: dict[str, object],
) -> tuple[str, str, str] | None:
    raw_edge = payload.get("selected_road_id")
    if raw_edge is None:
        return None
    return normalize_edge_id(raw_edge)


def load_red_dotted_test_fixture(
    fixture_path: Path = RED_DOTTED_TEST_FIXTURE_PATH,
) -> dict[str, object]:
    with fixture_path.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)

    if not isinstance(payload, dict):
        raise ValueError("red dotted fixture must be a JSON object")

    failed_target_roads = normalize_fixture_edge_set(payload, "failed_target_roads")
    failed_partial_roads = normalize_fixture_edge_set(payload, "failed_partial_roads")
    failed_full_roads = normalize_fixture_edge_set(payload, "failed_full_roads")
    failed_included_roads = normalize_fixture_edge_set(payload, "failed_included_roads")
    selected_road_id = normalize_fixture_selected_road_id(payload)

    return {
        "description": str(payload.get("description", "")),
        "source_note": str(payload.get("source_note", "")),
        "failed_target_roads": failed_target_roads,
        "failed_partial_roads": failed_partial_roads,
        "failed_full_roads": failed_full_roads,
        "failed_included_roads": failed_included_roads,
        "selected_road_id": selected_road_id,
    }


def apply_red_dotted_test_fixture() -> dict[str, int]:
    fixture = load_red_dotted_test_fixture()
    failed_target_roads = fixture["failed_target_roads"]
    failed_partial_roads = fixture["failed_partial_roads"]
    failed_full_roads = fixture["failed_full_roads"]
    failed_included_roads = fixture["failed_included_roads"]
    selected_road_id = fixture["selected_road_id"]

    st.session_state["failed_target_roads"] = failed_target_roads
    st.session_state["failed_partial_roads"] = failed_partial_roads
    st.session_state["failed_full_roads"] = failed_full_roads
    st.session_state["failed_included_roads"] = failed_included_roads
    st.session_state["failed_display_roads"] = build_failed_display_roads(
        failed_target_roads,
        failed_included_roads,
    )
    st.session_state["selected_road_id"] = selected_road_id
    st.session_state["road_operation_notice"] = "Loaded D3 red dotted test fixture."

    return {
        "failed_target_roads": len(failed_target_roads),
        "failed_partial_roads": len(failed_partial_roads),
        "failed_full_roads": len(failed_full_roads),
        "failed_included_roads": len(failed_included_roads),
        "failed_display_roads": len(st.session_state["failed_display_roads"]),
    }


def render_red_dotted_test_fixture_controls() -> None:
    if not is_d3_test_fixture_enabled():
        return

    st.markdown("#### D3 red dotted test fixture")
    st.caption(
        f"Debug-only fixture controls are enabled by {D3_TEST_FIXTURE_ENV}=1."
    )
    st.info(
        "This is a display/session-state fixture, not a recalculation fixture. "
        "Use it to check red dotted display and route layer suppression immediately "
        "after loading. If you run recalculation, the artificial failed state is "
        "overwritten by the real result; with the current fixture edge, the red "
        "dotted state can disappear and return to normal route display."
    )
    st.write({"fixture_path": str(RED_DOTTED_TEST_FIXTURE_PATH)})

    if st.button("Load red dotted fixture", width="stretch"):
        try:
            counts = apply_red_dotted_test_fixture()
        except Exception as exc:
            st.error(f"Failed to load red dotted fixture: {exc}")
            return

        st.success("Loaded red dotted fixture.")
        st.write(counts)


def render_debug_panel() -> None:
    st.subheader("一時デバッグ情報")

    render_red_dotted_test_fixture_controls()

    selected_road_id = st.session_state.get("selected_road_id")
    excluded_roads = st.session_state.get("excluded_roads", set())
    included_roads = st.session_state.get("included_roads", set())
    failed_target_roads = st.session_state.get("failed_target_roads", set())
    failed_partial_roads = st.session_state.get("failed_partial_roads", set())
    failed_full_roads = st.session_state.get("failed_full_roads", set())
    failed_included_roads = st.session_state.get("failed_included_roads", set())
    failed_display_roads = get_failed_display_roads()
    selected_road_state = get_road_display_state(selected_road_id)

    debug_rows = [
        {"項目": "last_component_event_type", "値": st.session_state.get("last_component_event_type", "")},
        {"項目": "last_component_event_count", "値": st.session_state.get("last_component_event_count", 0)},
        {"項目": "selected_road_id", "値": format_road_edge_id(selected_road_id)},
        {"項目": "selected_road_state", "値": selected_road_state},
        {"項目": "last_map_view_state", "値": st.session_state.get("last_map_view_state")},
        {"項目": "last_map_view_state_source", "値": st.session_state.get("last_map_view_state_source", "")},
        {"項目": "excluded_roads_count", "値": len(excluded_roads)},
        {"項目": "recalculation_baseline_excluded_roads_count", "値": len(st.session_state.get("recalculation_baseline_excluded_roads", set()))},
        {"項目": "recalculation_baseline_included_roads_count", "値": len(st.session_state.get("recalculation_baseline_included_roads", set()))},
        {"項目": "recalculation_baseline_conditional_roads_count", "値": len(st.session_state.get("recalculation_baseline_conditional_roads", set()))},
        {"項目": "recalculation_baseline_failed_target_roads_count", "値": len(st.session_state.get("recalculation_baseline_failed_target_roads", set()))},
        {"項目": "recalculation_baseline_failed_partial_roads_count", "値": len(st.session_state.get("recalculation_baseline_failed_partial_roads", set()))},
        {"項目": "recalculation_baseline_failed_full_roads_count", "値": len(st.session_state.get("recalculation_baseline_failed_full_roads", set()))},
        {"項目": "recalculation_baseline_failed_included_roads_count", "値": len(st.session_state.get("recalculation_baseline_failed_included_roads", set()))},
        {"項目": "recalculation_baseline_selected_road_id", "値": format_road_edge_id(st.session_state.get("recalculation_baseline_selected_road_id"))},
        {"項目": "active_route_source", "値": st.session_state.get("active_route_source", "")},
        {"項目": "active_route_path", "値": st.session_state.get("active_route_path", "")},
        {"項目": "current_start_point", "値": format_point_text(st.session_state.get("current_start_point"))},
        {"項目": "recalculation_baseline_start_point", "値": format_point_text(st.session_state.get("recalculation_baseline_start_point"))},
        {"項目": "previous_start_point", "値": format_point_text(st.session_state.get("previous_start_point"))},
    ]
    debug_rows.extend(
        [
            {"項目": "recalculation_status", "値": st.session_state.get("recalculation_status", "")},
            {"項目": "recalculation_message", "値": st.session_state.get("recalculation_message", "")},
            {"項目": "recalculation_preview_rows_count", "値": len(st.session_state.get("recalculation_preview_rows", []))},
            {"項目": "recalculation_preview_call_count", "値": st.session_state.get("recalculation_preview_call_count", 0)},
            {"項目": "recalculation_action_call_count", "値": st.session_state.get("recalculation_action_call_count", 0)},
            {"項目": "recalculation_selected_strategy", "値": st.session_state.get("recalculation_selected_strategy", "")},
            {"項目": "road_selection_level", "値": get_road_selection_level()},
            {"項目": "recalculation_applied_road_selection_level", "値": st.session_state.get("recalculation_applied_road_selection_level", "")},
            {"項目": "road_selection_target_input_path", "値": str(get_road_selection_target_input_path())},
            {"項目": "recalculation_applied_target_input_path", "値": st.session_state.get("recalculation_applied_target_input_path", "")},
        ]
    )
    debug_rows.extend(
        [
            {"項目": "selected_road_instruction_state", "値": get_road_instruction_state(selected_road_id)},
            {"項目": "included_roads_count", "値": len(included_roads)},
            {"項目": "failed_target_roads_count", "値": len(failed_target_roads)},
            {"項目": "failed_partial_roads_count", "値": len(failed_partial_roads)},
            {"項目": "failed_full_roads_count", "値": len(failed_full_roads)},
            {"項目": "failed_included_roads_count", "値": len(failed_included_roads)},
            {"項目": "failed_display_roads_count", "値": len(failed_display_roads)},
        ]
    )
    st.dataframe(make_display_df(debug_rows), width="stretch", hide_index=True)
    st.write({"conditional_roads_count": len(st.session_state.get("conditional_roads", set()))})
    st.write(
        {
            "component_event_nonce": st.session_state.get("last_component_event_nonce", ""),
            "last_handled_component_event_key": st.session_state.get(
                LAST_HANDLED_COMPONENT_EVENT_KEY,
                "",
            ),
            "duplicate_component_event_skip_count": st.session_state.get(
                "duplicate_component_event_skip_count",
                0,
            ),
        }
    )

    st.markdown("#### bridge_component_raw_value")
    raw_value = st.session_state.get("bridge_component_raw_value")
    if raw_value is None:
        st.write("まだ raw value を受信していません。")
    else:
        if isinstance(raw_value, (dict, list)):
            st.json(raw_value, expanded=True)
        else:
            st.write(raw_value)

    st.markdown("#### bridge_component_normalized_value")
    normalized_value = st.session_state.get("bridge_component_normalized_value")
    if normalized_value is None:
        st.write("まだ normalized value を受信していません。")
    else:
        if isinstance(normalized_value, (dict, list)):
            st.json(normalized_value, expanded=True)
        else:
            st.write(normalized_value)

    st.markdown("#### bridge_component_normalize_error")
    normalize_error = st.session_state.get("bridge_component_normalize_error", "")
    if normalize_error:
        st.error(normalize_error)
    else:
        st.write("normalize error はありません。")

    st.markdown("#### last_component_event")
    event = st.session_state.get("last_component_event")
    if event is None:
        st.write("まだ event を受信していません。")
    else:
        st.json(event, expanded=True)


def build_edge_id_payload(edge_id: tuple[object, object, object] | None) -> dict[str, str] | None:
    if edge_id is None:
        return None
    u, v, key = normalize_edge_id(edge_id)
    return {"u": u, "v": v, "key": key}


def build_edge_id_payload_list(
    edge_ids: set[tuple[object, object, object]] | list[tuple[object, object, object]],
) -> list[dict[str, str]]:
    return [
        {"u": u, "v": v, "key": key}
        for u, v, key in normalize_edge_id_list(set(edge_ids or set()))
    ]


def build_gdf_content_signature(
    gdf: gpd.GeoDataFrame,
    *,
    columns: list[str],
    preserve_order: bool = False,
) -> list[dict[str, object]]:
    if gdf is None or len(gdf) == 0:
        return []

    rows: list[dict[str, object]] = []
    for row_index, row in gdf.iterrows():
        record: dict[str, object] = {"_row_index": int(row_index)}
        for column in columns:
            if column not in gdf.columns:
                continue
            value = row.get(column)
            try:
                if pd.isna(value):
                    value = None
            except Exception:
                pass
            record[column] = value

        geometry = row.get("geometry")
        if geometry is None or getattr(geometry, "is_empty", False):
            record["geometry_wkb"] = None
        else:
            record["geometry_wkb"] = getattr(geometry, "wkb_hex", str(geometry))
        rows.append(record)

    if preserve_order:
        return rows

    return sorted(rows, key=lambda item: json.dumps(item, sort_keys=True, default=str))


def build_map_geojson_versions(
    *,
    roads_gdf: gpd.GeoDataFrame,
    operable_roads_gdf: gpd.GeoDataFrame,
    route_gdf: gpd.GeoDataFrame,
) -> dict[str, str]:
    route_display_states = st.session_state.get("current_route_edge_display_states", {})
    route_display_state_items = [
        (normalize_edge_id(edge_id), str(display_state))
        for edge_id, display_state in dict(route_display_states or {}).items()
    ]
    route_display_state_items.sort(key=lambda x: (x[0][0], x[0][1], x[0][2], x[1]))

    failed_partial_roads = st.session_state.get("failed_partial_roads", set())
    failed_display_roads = get_failed_display_roads()
    road_signature = {
        "road_selection_level": get_road_selection_level(),
        "roads_count": int(len(roads_gdf)),
        "operable_roads_count": int(len(operable_roads_gdf)),
        "roads_signature": build_gdf_content_signature(
            roads_gdf,
            columns=["u", "v", "key", "length", "oneway", "highway", "name"],
        ),
        "operable_roads_signature": build_gdf_content_signature(
            operable_roads_gdf,
            columns=[
                "u",
                "v",
                "key",
                "length",
                "oneway",
                "highway",
                "name",
                "priority",
                "source_kind",
            ],
        ),
        "route_edges": normalize_edge_id_list(
            set(st.session_state.get("current_route_edge_ids", set()) or set())
        ),
        "route_display_states": [
            {"edge_id": edge_id, "display_state": display_state}
            for edge_id, display_state in route_display_state_items
        ],
        "suppressed_base_edges": build_edge_id_payload_list(
            build_suppressed_base_edge_ids_for_final_state(
                failed_partial_roads=failed_partial_roads,
            )
        ),
    }
    route_signature = {
        "route_feature_count": int(len(route_gdf)),
        "route_signature": build_gdf_content_signature(
            route_gdf,
            columns=[
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
            ],
            preserve_order=True,
        ),
        "route_edges": road_signature["route_edges"],
        "route_display_states": road_signature["route_display_states"],
        "suppressed_route_edges": build_edge_id_payload_list(
            build_suppressed_route_edge_ids_for_final_state(
                failed_display_roads=failed_display_roads,
                failed_partial_roads=failed_partial_roads,
            )
        ),
    }
    return {
        "roads_geojson_version": json.dumps(road_signature, sort_keys=True, default=str),
        "route_geojson_version": json.dumps(route_signature, sort_keys=True, default=str),
    }


def build_road_state_payload(
    *,
    roads_gdf: gpd.GeoDataFrame,
    operable_roads_gdf: gpd.GeoDataFrame,
    route_gdf: gpd.GeoDataFrame,
) -> dict[str, object]:
    instructions: list[dict[str, object]] = []
    instruction_sources = [
        ("exclude", st.session_state.get("excluded_roads", set())),
        ("include_failed", get_failed_display_roads()),
        ("include", st.session_state.get("included_roads", set())),
        ("conditional", st.session_state.get("conditional_roads", set())),
    ]

    seen_edge_ids: set[tuple[str, str, str]] = set()
    for instruction_state, edge_ids in instruction_sources:
        for edge_id in normalize_edge_id_list(set(edge_ids or set())):
            if edge_id in seen_edge_ids:
                continue
            seen_edge_ids.add(edge_id)
            instructions.append(
                {
                    "edge_id": build_edge_id_payload(edge_id),
                    "instruction_state": instruction_state,
                }
            )

    failed_partial_roads = st.session_state.get("failed_partial_roads", set())
    return {
        **build_map_geojson_versions(
            roads_gdf=roads_gdf,
            operable_roads_gdf=operable_roads_gdf,
            route_gdf=route_gdf,
        ),
        "selected_edge_id": build_edge_id_payload(
            st.session_state.get("selected_road_id")
        ),
        "instruction_sync_ack_nonce": int(
            st.session_state.get("last_instruction_sync_nonce", 0) or 0
        ),
        "instructions": instructions,
        "failed_partial_edge_ids": build_edge_id_payload_list(failed_partial_roads),
        "after_black_clear_edge_ids": build_edge_id_payload_list(
            st.session_state.get("after_black_clear_roads", set())
        ),
        "suppressed_base_edge_ids": build_edge_id_payload_list(
            build_suppressed_base_edge_ids_for_final_state(
                failed_partial_roads=failed_partial_roads,
            )
        ),
    }


def render_map_click_area(
    *,
    initial_view_state: dict[str, float],
    current_start_point: dict[str, float] | None,
    candidate_start_point: dict[str, float] | None,
    roads_geojson: dict,
    road_state: dict,
    route_geojson: dict,
    route_cycle_guide: dict[str, object] | None,
    show_route_cycle_guide: bool,
    show_route_cycle_order_debug: bool,
    debug_mode: bool,
    line_styles: dict[str, object] | None,
) -> None:
    if BASEMAP_DISPLAY_STATE_KEY not in st.session_state:
        st.session_state[BASEMAP_DISPLAY_STATE_KEY] = True
    if BASEMAP_DISPLAY_WIDGET_KEY not in st.session_state:
        st.session_state[BASEMAP_DISPLAY_WIDGET_KEY] = st.session_state[
            BASEMAP_DISPLAY_STATE_KEY
        ]

    show_basemap = bool(st.session_state.get(BASEMAP_DISPLAY_STATE_KEY, True))
    component_line_styles = dict(line_styles or {})
    component_line_styles["showBasemap"] = show_basemap

    component_value = render_map_click_component(
        key=MAP_COMPONENT_KEY,
        initial_view_state=initial_view_state,
        current_start_point=current_start_point,
        candidate_start_point=candidate_start_point,
        reset_view_nonce=int(st.session_state.get("reset_view_nonce", 0)),
        roads_geojson=roads_geojson,
        road_state=road_state,
        route_geojson=route_geojson,
        route_cycle_guide=route_cycle_guide,
        show_route_cycle_guide=show_route_cycle_guide,
        debug_mode=debug_mode,
        pending_sync_nonce=int(st.session_state.get("pending_instruction_sync_nonce", 0)),
        line_styles=component_line_styles,
        height=800,
    )

    st.session_state["bridge_component_raw_value"] = component_value
    st.session_state["bridge_component_normalized_value"] = component_value
    st.session_state["bridge_component_normalize_error"] = ""

    st.checkbox(
        "背景地図を表示",
        key=BASEMAP_DISPLAY_WIDGET_KEY,
        help="外部タイルを利用します。読み込めない場合も道路・ルートレイヤは表示されます。",
        on_change=sync_basemap_display_enabled,
    )


def render_map_display_controls(
    *,
    initial_view_state: dict[str, float],
    default_initial_view_state: dict[str, float],
    line_styles_warning: str,
    debug_mode: bool,
) -> tuple[dict[str, float], bool, bool]:
    st.subheader("地図表示")

    notice = st.session_state.pop("view_operation_notice", None)
    if notice:
        st.success(notice)

    route_refresh_notice = st.session_state.pop("route_refresh_notice", "")
    if route_refresh_notice:
        st.success(route_refresh_notice)

    selected_level = get_road_selection_level()
    applied_level_raw = st.session_state.get("recalculation_applied_road_selection_level")
    applied_level = (
        normalize_road_selection_level(applied_level_raw)
        if applied_level_raw is not None
        else None
    )
    active_route_source = st.session_state.get("active_route_source", "")
    if active_route_source == "d3_recalculation_memory" and applied_level is not None:
        st.caption(f"地図反映済み: Level {applied_level} の計算結果")
        if selected_level != applied_level:
            st.warning(
                f"現在選択中の除雪レベルは Level {selected_level} です。"
                "地図は前回計算した Level "
                f"{applied_level} の結果を表示しています。"
            )
    else:
        st.caption("地図反映済み: 初期ルート")

    if "route_cycle_guide_display_enabled" not in st.session_state:
        st.session_state["route_cycle_guide_display_enabled"] = True
    if "route_cycle_order_debug_enabled" not in st.session_state:
        st.session_state["route_cycle_order_debug_enabled"] = False

    control_cols = st.columns([1.15, 1])
    with control_cols[0]:
        if st.button("表示倍率初期化", width="stretch"):
            st.session_state["last_map_view_state"] = None
            st.session_state["last_map_view_state_source"] = "reset_view"
            initial_view_state = default_initial_view_state
            st.session_state["reset_view_nonce"] = (
                int(st.session_state.get("reset_view_nonce", 0)) + 1
            )
            st.session_state["view_operation_notice"] = "地図表示を基準倍率へ戻しました。"
    with control_cols[1]:
        show_route_cycle_guide = st.checkbox(
            "巡回補助線を表示",
            key="route_cycle_guide_display_enabled",
            help="現在ルートの進行方向を補助的に表示します。",
        )

    show_route_cycle_order_debug = False
    if debug_mode:
        st.caption(
            "component event 受信直後には rerun せず、"
            "state 更新が後続描画へ反映されるかを確認しています。"
        )
        if line_styles_warning:
            st.caption(f"line_styles.json fallback: {line_styles_warning}")
        show_route_cycle_order_debug = st.checkbox(
            "Order-label debug",
            key="route_cycle_order_debug_enabled",
            help="Temporary Chat2 visibility debug only. Keep off for integration candidates.",
        )

    return initial_view_state, show_route_cycle_guide, show_route_cycle_order_debug


def render_start_point_controls() -> None:
    st.subheader("出発点補助操作")

    notice = st.session_state.pop("start_point_operation_notice", None)
    if notice:
        st.success(notice)

    st.info("主操作は map custom component 側で行います。補助として従来ボタンも残しています。")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("候補点を確定", width="stretch"):
            try:
                confirm_candidate_start_point(st.session_state)
                st.session_state["start_point_operation_notice"] = "出発点を更新しました。"
            except Exception as exc:
                st.error(f"出発点更新に失敗しました: {exc}")

    with col2:
        if st.button("候補点を取消", width="stretch"):
            cancel_candidate_start_point(st.session_state)
            st.session_state["start_point_operation_notice"] = "出発点候補を取り消しました。"


def render_road_selection_controls(operable_roads_gdf: gpd.GeoDataFrame) -> None:
    st.subheader("道路補助操作")

    notice = st.session_state.pop("road_operation_notice", None)
    if notice:
        st.success(notice)

    selectable_df = build_selectable_roads_df(
        operable_roads_gdf,
        st.session_state.get("excluded_roads", set()),
    )
    if len(selectable_df) == 0:
        st.warning("操作対象道路がありません。")
        st.session_state["selected_road_id"] = None
        return

    option_labels = [ROAD_UNSELECTED_LABEL] + selectable_df["road_id_text"].tolist()
    option_map = {
        row["road_id_text"]: normalize_edge_id((row["u"], row["v"], row["key"]))
        for _, row in selectable_df.iterrows()
    }

    current_selected = st.session_state.get("selected_road_id")
    default_label = ROAD_UNSELECTED_LABEL
    if current_selected is not None:
        current_text = format_road_edge_id(current_selected)
        if current_text in option_map:
            default_label = current_text

    pending_widget_value = st.session_state.pop(ROAD_SELECTION_SYNC_KEY, None)
    if pending_widget_value in option_map or pending_widget_value == ROAD_UNSELECTED_LABEL:
        st.session_state[ROAD_SELECTION_WIDGET_KEY] = pending_widget_value
    elif (
        ROAD_SELECTION_WIDGET_KEY not in st.session_state
        or st.session_state[ROAD_SELECTION_WIDGET_KEY] not in option_labels
    ):
        st.session_state[ROAD_SELECTION_WIDGET_KEY] = default_label

    selected_label = st.selectbox(
        "対象道路を選択",
        options=option_labels,
        key=ROAD_SELECTION_WIDGET_KEY,
    )

    if selected_label == ROAD_UNSELECTED_LABEL:
        selected_edge_id = None
    else:
        selected_edge_id = option_map[selected_label]

    if selected_edge_id != current_selected:
        st.session_state["selected_road_id"] = selected_edge_id

    if selected_edge_id is None:
        st.caption("道路未選択です。")
    else:
        selected_info = get_road_row_by_edge_id(operable_roads_gdf, selected_edge_id)
        if selected_info is not None:
            st.markdown("#### 選択中道路")
            st.write(selected_info)

    current_is_excluded = is_excluded_road(
        selected_edge_id,
        st.session_state.get("excluded_roads", set()),
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button(
            "OFF にする",
            width="stretch",
            disabled=(selected_edge_id is None or current_is_excluded),
        ):
            set_road_instruction_state(selected_edge_id, "exclude")
            st.session_state["road_operation_notice"] = "選択道路を OFF にしました。"
            st.session_state["road_operation_message"] = (
                f"道路を OFF にしました: {format_road_edge_id(selected_edge_id)}"
            )
    with col2:
        if st.button(
            "ON に戻す",
            width="stretch",
            disabled=(selected_edge_id is None or not current_is_excluded),
        ):
            set_road_instruction_state(selected_edge_id, "none")
            st.session_state["road_operation_notice"] = "選択道路を ON に戻しました。"
            st.session_state["road_operation_message"] = (
                f"道路を ON に戻しました: {format_road_edge_id(selected_edge_id)}"
            )
    st.markdown("#### 差分指示ショートカット")
    st.write({"display_state": get_road_display_state(selected_edge_id)})

    quick_col1, quick_col2, quick_col3 = st.columns(3)
    with quick_col1:
        if st.button("黒指示", width="stretch", disabled=(selected_edge_id is None)):
            set_road_instruction_state(selected_edge_id, "exclude")

    with quick_col2:
        if st.button("追加指示", width="stretch", disabled=(selected_edge_id is None)):
            set_road_instruction_state(selected_edge_id, "include")

    with quick_col3:
        if st.button("指示解除", width="stretch", disabled=(selected_edge_id is None)):
            set_road_instruction_state(selected_edge_id, "none")


def render_start_point_status_panel() -> None:
    st.subheader("出発点補助情報")

    current = st.session_state.get("current_start_point")
    previous = st.session_state.get("previous_start_point")
    candidate = st.session_state.get("candidate_start_point")
    source = st.session_state.get("start_point_source")
    status = st.session_state.get("candidate_start_point_status")
    message = st.session_state.get("start_point_message")

    st.write("現在メッセージ")
    st.info(message)

    st.markdown("#### 現在の出発点")
    if current is None:
        st.warning("現在の出発点は未設定です。")
    else:
        st.write(
            {
                "lat": current.get("lat"),
                "lon": current.get("lon"),
                "source": source,
                "snap_applied": current.get("snap_applied"),
                "snap_reason": current.get("snap_reason"),
            }
        )

    st.markdown("#### 前回の出発点")
    if previous is None:
        st.write("前回の出発点なし")
    else:
        st.write({"lat": previous.get("lat"), "lon": previous.get("lon")})

    st.markdown("#### 出発点候補")
    if candidate is None:
        st.write("候補点なし")
    else:
        st.write(
            {
                "lat": candidate.get("lat"),
                "lon": candidate.get("lon"),
                "source": candidate.get("source"),
                "snap_applied": candidate.get("snap_applied"),
                "snap_reason": candidate.get("snap_reason"),
            }
        )

    st.markdown("#### 状態")
    st.write(
        {
            "candidate_start_point_status": status,
            "start_point_source": source,
            "reset_view_nonce": st.session_state.get("reset_view_nonce"),
        }
    )


def render_road_status_panel(operable_roads_gdf: gpd.GeoDataFrame) -> None:
    st.subheader("道路補助情報")

    selected_road_id = st.session_state.get("selected_road_id")
    road_message = st.session_state.get("road_operation_message", "")
    excluded_roads = st.session_state.get("excluded_roads", set())
    conditional_roads = st.session_state.get("conditional_roads", set())
    included_roads = st.session_state.get("included_roads", set())
    failed_target_roads = st.session_state.get("failed_target_roads", set())
    failed_partial_roads = st.session_state.get("failed_partial_roads", set())
    failed_full_roads = st.session_state.get("failed_full_roads", set())
    failed_included_roads = st.session_state.get("failed_included_roads", set())

    st.write("現在メッセージ")
    st.info(road_message)

    selected_state = (
        "除雪対象外 / 使用禁止"
        if is_excluded_road(selected_road_id, excluded_roads)
        else "使用可"
    )

    st.markdown("#### 選択中道路")
    st.write(
        {
            "selected_road_id": format_road_edge_id(selected_road_id),
            "road_state": get_road_display_state(selected_road_id),
        }
    )

    st.write({"road_display_state": get_road_display_state(selected_road_id)})

    excluded_summary = build_excluded_roads_summary(
        operable_roads_gdf,
        excluded_roads,
    )

    st.markdown("#### 除雪対象外 / 使用禁止 件数")
    st.write({"excluded_roads_count": len(excluded_summary)})

    st.markdown("#### 除雪対象外 / 使用禁止 道路一覧")
    if not excluded_summary:
        st.write("除雪対象外 / 使用禁止の道路はありません")
    else:
        st.dataframe(make_display_df(excluded_summary), width="stretch", hide_index=True)

    included_summary = build_roads_summary(operable_roads_gdf, included_roads)
    conditional_summary = build_roads_summary(operable_roads_gdf, conditional_roads)
    failed_target_summary = build_roads_summary(operable_roads_gdf, failed_target_roads)
    failed_partial_summary = build_roads_summary(operable_roads_gdf, failed_partial_roads)
    failed_full_summary = build_roads_summary(operable_roads_gdf, failed_full_roads)
    failed_included_summary = build_roads_summary(operable_roads_gdf, failed_included_roads)

    st.markdown("#### 追加指示 件数")
    st.write({"included_roads_count": len(included_summary)})

    st.markdown("#### 追加指示 一覧")
    if not included_summary:
        st.write("追加指示の道路はありません")
    else:
        st.dataframe(make_display_df(included_summary), width="stretch", hide_index=True)

    st.markdown("#### 追加不成立 件数")
    st.markdown("#### 条件付き許可 / Orange 件数")
    st.write({"conditional_roads_count": len(conditional_summary)})

    st.markdown("#### 条件付き許可 / Orange 一覧")
    if not conditional_summary:
        st.write("条件付き許可 / Orange の道路はありません")
    else:
        st.dataframe(make_display_df(conditional_summary), width="stretch", hide_index=True)

    st.write({"failed_target_roads_count": len(failed_target_summary)})
    st.write({"failed_partial_roads_count": len(failed_partial_summary)})
    st.write({"failed_full_roads_count": len(failed_full_summary)})

    st.write({"failed_included_roads_count": len(failed_included_summary)})

    st.markdown("#### 追加不成立 一覧")
    if not failed_included_summary:
        st.write("追加不成立の道路はありません")
    else:
        st.dataframe(make_display_df(failed_included_summary), width="stretch", hide_index=True)


def render_main_layout() -> None:
    debug_mode = render_debug_mode_control()

    if debug_mode:
        with st.expander("開発者向け: 入力ファイル確認", expanded=True):
            render_input_spec_table()
            st.divider()
            can_load = render_input_status()
    else:
        can_load, missing_labels = required_input_status()
        if not can_load:
            st.error(
                "必要な入力ファイルが不足しているため、アプリを開始できません。"
            )
            st.write({"missing_required_inputs": missing_labels})

    st.divider()

    if not can_load:
        return

    if debug_mode:
        with st.expander("開発者向け: GeoJSON 読み込み結果", expanded=False):
            render_loaded_geojson_info()
        st.divider()

    try:
        loaded = load_required_inputs(
            input_specs=INPUT_SPECS,
            load_geojson_fn=cached_load_geojson,
        )

        roads_gdf = ensure_wgs84(loaded["roads"].copy())
        priority_roads_gdf = load_current_priority_roads()
        initial_start_point = build_initial_start_point(priority_roads_gdf)
        init_session_state(st.session_state, initial_start_point)
        init_recalculation_state()
        init_weather_prediction_state()
        init_road_instruction_state()
        init_debug_state()
        ensure_recalculation_baseline_state()
        ensure_initial_route_gdf(
            roads_gdf=roads_gdf,
            priority_roads_gdf=priority_roads_gdf,
        )
        manual_add_candidate_roads_gdf = load_manual_add_candidate_roads(
            debug_mode=is_debug_input_mode()
        )
        operable_roads_gdf = build_operable_roads_gdf(
            roads_gdf=roads_gdf,
            priority_roads_gdf=priority_roads_gdf,
            manual_add_candidate_roads_gdf=manual_add_candidate_roads_gdf,
        )

        line_styles_config, line_styles_warning = cached_load_line_styles_config(str(LINE_STYLES_INPUT))
        pending_component_event = get_pending_map_component_event()
        pending_component_event_key = build_component_event_instance_key(pending_component_event)
        if pending_component_event is not None and (
            pending_component_event_key == ""
            or pending_component_event_key
            != st.session_state.get(LAST_HANDLED_COMPONENT_EVENT_KEY, "")
        ):
            handle_component_event(pending_component_event)

        if (
            st.session_state.get("pending_recalculation_after_instruction_sync", False)
            and st.session_state.get("last_component_event_type") == "road_instructions_sync"
            and int(st.session_state.get("last_instruction_sync_nonce", 0) or 0)
            == int(st.session_state.get("pending_instruction_sync_nonce", 0) or 0)
        ):
            st.session_state["pending_recalculation_after_instruction_sync"] = False
            run_calculation_action(
                operable_roads_gdf=operable_roads_gdf,
                additional_roads_source_gdf=roads_gdf,
                rerun_after=False,
            )

        route_gdf, active_route_path, active_route_source = resolve_active_route_gdf()
        st.session_state["active_route_source"] = active_route_source
        st.session_state["active_route_path"] = active_route_path
        st.session_state["current_route_edge_ids"] = build_route_edge_id_set(route_gdf)
        st.session_state["current_route_edge_display_states"] = build_route_edge_display_state_map(
            route_gdf
        )
        active_loaded = dict(loaded)
        active_loaded["route"] = route_gdf
        default_initial_view_state = build_initial_view_state(
            loaded=active_loaded,
            current_start_point=st.session_state.get("current_start_point"),
            ensure_wgs84=ensure_wgs84,
        )
        route_cycle_guide = (
            build_route_cycle_guide(
                route_gdf=route_gdf,
                ensure_wgs84=ensure_wgs84,
            )
            if len(route_gdf) > 0
            else None
        )
        initial_view_state = get_persisted_map_view_state(default_initial_view_state)

        left_col, right_col = st.columns([3, 1])

        with right_col:
            (
                initial_view_state,
                show_route_cycle_guide,
                show_route_cycle_order_debug,
            ) = render_map_display_controls(
                initial_view_state=initial_view_state,
                default_initial_view_state=default_initial_view_state,
                line_styles_warning=line_styles_warning,
                debug_mode=debug_mode,
            )
            st.divider()

        with left_col:
            if debug_mode:
                with st.expander("開発者向け: 道路補助操作", expanded=False):
                    render_road_selection_controls_v2(operable_roads_gdf)
                st.divider()

            roads_geojson = build_roads_geojson(
                roads_gdf=roads_gdf,
                operable_roads_gdf=operable_roads_gdf,
                selected_road_id=None,
                excluded_roads=set(),
                conditional_roads=set(),
                included_roads=set(),
                failed_included_roads=set(),
                failed_partial_roads=set(),
                after_black_clear_roads=set(),
                current_route_edge_ids=st.session_state.get("current_route_edge_ids", set()),
                current_route_edge_display_states=st.session_state.get(
                    "current_route_edge_display_states",
                    {},
                ),
                suppressed_base_edge_ids=build_suppressed_base_edge_ids_for_final_state(
                    failed_partial_roads=st.session_state.get("failed_partial_roads", set()),
                ),
                ensure_wgs84=ensure_wgs84,
                sanitize_gdf_for_geojson_fn=sanitize_gdf_for_geojson,
                normalize_edge_id=normalize_edge_id,
                is_excluded_road=is_excluded_road,
                is_road_in_set=is_road_in_set,
            )
            road_state = build_road_state_payload(
                roads_gdf=roads_gdf,
                operable_roads_gdf=operable_roads_gdf,
                route_gdf=route_gdf,
            )
            suppressed_route_edge_ids = build_suppressed_route_edge_ids_for_final_state(
                failed_display_roads=get_failed_display_roads(),
                failed_partial_roads=st.session_state.get("failed_partial_roads", set()),
            )
            route_geojson = build_route_geojson(
                route_gdf=route_gdf,
                suppressed_route_edge_ids=suppressed_route_edge_ids,
                ensure_wgs84=ensure_wgs84,
                sanitize_gdf_for_geojson_fn=sanitize_gdf_for_geojson,
            )

            render_map_click_area(
                initial_view_state=initial_view_state,
                current_start_point=build_component_point(st.session_state.get("current_start_point")),
                candidate_start_point=build_component_point(st.session_state.get("candidate_start_point")),
                roads_geojson=roads_geojson,
                road_state=road_state,
                route_geojson=route_geojson,
                route_cycle_guide=route_cycle_guide,
                show_route_cycle_guide=show_route_cycle_guide,
                show_route_cycle_order_debug=show_route_cycle_order_debug,
                debug_mode=debug_mode,
                line_styles=line_styles_config,
            )
            st.divider()
            if debug_mode:
                with st.expander("開発者向け: 出発点補助操作", expanded=False):
                    render_start_point_controls()

        with right_col:
            render_weather_prediction_panel(debug_mode=debug_mode)
            st.divider()
            render_recalculation_panel(
                operable_roads_gdf,
                additional_roads_source_gdf=roads_gdf,
                debug_mode=debug_mode,
            )
            if debug_mode:
                st.divider()
                with st.expander("開発者向け: 詳細な操作結果サマリ", expanded=False):
                    render_operation_summary_panel(
                        operable_roads_gdf=operable_roads_gdf,
                        debug_mode=True,
                    )
                st.divider()
                with st.expander("開発者向け: D3 受け渡し整理", expanded=False):
                    render_d3_handoff_panel()
                st.divider()
                with st.expander("開発者向け: 一時デバッグ情報", expanded=False):
                    render_debug_panel()
                st.divider()
                with st.expander("開発者向け: 出発点補助情報", expanded=False):
                    render_start_point_status_panel()
                st.divider()
                with st.expander("開発者向け: 道路補助情報", expanded=False):
                    render_road_status_panel(operable_roads_gdf)

    except Exception as exc:
        st.error(f"表示処理に失敗しました: {exc}")


def load_manual_md() -> str:
    manual_path = PROJECT_ROOT / "Docs" / "manual.md"
    if manual_path.exists():
        try:
            return manual_path.read_text(encoding="utf-8")
        except Exception as exc:
            return f"手順書ファイルの読み込みに失敗しました: {exc}"
    return "手順書ファイルが見つかりません。"


def main() -> None:
    st.set_page_config(
        page_title=APP_TITLE,
        page_icon="🧭",
        layout="wide",
    )

    setup_logging(verbose=False)

    with st.sidebar.expander("🧭 操作手順書 (ヘルプ)", expanded=False):
        st.markdown(load_manual_md())

    render_header()
    render_main_layout()

def render_road_selection_controls_v2(operable_roads_gdf: gpd.GeoDataFrame) -> None:
    st.subheader("道路補助操作")

    notice = st.session_state.pop("road_operation_notice", None)
    if notice:
        st.success(notice)

    st.info(
        "主操作は map custom component 側で行います。ここでは選択道路に対して "
        "Black / Magenta / Orange / Clear を補助的に指定できます。"
    )

    selectable_df = build_selectable_roads_df(
        operable_roads_gdf,
        st.session_state.get("excluded_roads", set()),
    )
    if len(selectable_df) == 0:
        st.warning("操作対象の候補道路が見つかりません。")
        st.session_state["selected_road_id"] = None
        return

    option_labels = [ROAD_UNSELECTED_LABEL] + selectable_df["road_id_text"].tolist()
    option_map = {
        row["road_id_text"]: normalize_edge_id((row["u"], row["v"], row["key"]))
        for _, row in selectable_df.iterrows()
    }

    current_selected = st.session_state.get("selected_road_id")
    default_label = ROAD_UNSELECTED_LABEL
    if current_selected is not None:
        current_text = format_road_edge_id(current_selected)
        if current_text in option_map:
            default_label = current_text

    pending_widget_value = st.session_state.pop(ROAD_SELECTION_SYNC_KEY, None)
    if pending_widget_value in option_map or pending_widget_value == ROAD_UNSELECTED_LABEL:
        st.session_state[ROAD_SELECTION_WIDGET_KEY] = pending_widget_value
    elif (
        ROAD_SELECTION_WIDGET_KEY not in st.session_state
        or st.session_state[ROAD_SELECTION_WIDGET_KEY] not in option_labels
    ):
        st.session_state[ROAD_SELECTION_WIDGET_KEY] = default_label

    selected_label = st.selectbox(
        "対象道路を選択",
        options=option_labels,
        key=ROAD_SELECTION_WIDGET_KEY,
    )

    selected_edge_id = None if selected_label == ROAD_UNSELECTED_LABEL else option_map[selected_label]
    if selected_edge_id != current_selected:
        st.session_state["selected_road_id"] = selected_edge_id

    if selected_edge_id is None:
        st.caption("道路未選択です。")
        return

    selected_info = get_road_row_by_edge_id(operable_roads_gdf, selected_edge_id)
    if selected_info is not None:
        st.markdown("#### 選択中の道路")
        st.write(selected_info)

    st.markdown("#### 現在の色状態")
    st.write(
        {
            "display_state": get_road_display_state(selected_edge_id),
            "instruction_state": get_road_instruction_state(selected_edge_id),
        }
    )

    quick_col1, quick_col2, quick_col3, quick_col4 = st.columns(4)
    with quick_col1:
        if st.button("Black", width="stretch", disabled=(selected_edge_id is None)):
            set_road_instruction_state(selected_edge_id, "exclude")
    with quick_col2:
        if st.button("Magenta", width="stretch", disabled=(selected_edge_id is None)):
            set_road_instruction_state(selected_edge_id, "include")
    with quick_col3:
        if st.button("Orange", width="stretch", disabled=(selected_edge_id is None)):
            set_road_instruction_state(selected_edge_id, "conditional")
    with quick_col4:
        if st.button("Clear", width="stretch", disabled=(selected_edge_id is None)):
            set_road_instruction_state(selected_edge_id, "none")


if __name__ == "__main__":
    main()
