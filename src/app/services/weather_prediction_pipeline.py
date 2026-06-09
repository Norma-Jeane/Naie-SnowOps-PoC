#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
気象推論パイプラインサービス

■ 目的
- JMA取得 → 特徴量生成 → 最新1行推論入力整形 → モデル推論
  を app 側から再利用しやすい 1 本の service として束ねる

■ 方針
- 取得は weather_fetcher_jma.py に委譲する
- 特徴量生成は weather_features.py に委譲する
- 最新1行入力整形は weather_inference_input.py に委譲する
- 推論は weather_prediction.py に委譲する
- この module は orchestration（つなぎ込み）に責務を絞る

■ 非責務
- UI表示
- CSV保存
- 日単位 update 管理
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from src.app.services.weather_fetcher_jma import (
    JmaFetchConfig,
    fetch_jma_weather_dataframe,
)
from src.app.services.weather_features import (
    build_weather_features,
)
from src.app.services.weather_inference_input import (
    build_weather_inference_input_result,
)
from src.app.services.weather_prediction import (
    load_weather_prediction_model,
    predict_weather_level_single,
)


@dataclass(frozen=True)
class WeatherPredictionPipelineConfig:
    """
    気象推論パイプライン設定
    """

    station_num: str
    station_name: str | None = None
    model_path: Path = Path("Data/models/rf_level_model.joblib")


@dataclass(frozen=True)
class WeatherPredictionPipelineResult:
    """
    気象推論パイプライン結果
    """

    station_num: str
    station_name: str | None
    start_date: date
    end_date: date
    fetch_rows: int
    feature_rows: int
    latest_datetime: pd.Timestamp
    pred_level: int
    model_input_df: pd.DataFrame
    feature_df: pd.DataFrame


def validate_weather_prediction_pipeline_inputs(
    *,
    config: WeatherPredictionPipelineConfig,
    start_date: date,
    end_date: date,
) -> None:
    if not isinstance(config, WeatherPredictionPipelineConfig):
        raise TypeError("config must be WeatherPredictionPipelineConfig")

    if not isinstance(start_date, date):
        raise TypeError("start_date must be date")

    if not isinstance(end_date, date):
        raise TypeError("end_date must be date")

    if start_date > end_date:
        raise ValueError(f"start_date must be <= end_date: {start_date} > {end_date}")

    if not str(config.station_num).strip():
        raise ValueError("station_num must not be empty")


def run_weather_prediction_pipeline(
    *,
    config: WeatherPredictionPipelineConfig,
    start_date: date,
    end_date: date,
    project_root: Path | None = None,
) -> WeatherPredictionPipelineResult:
    """
    気象取得から推論までを一括実行する
    """
    validate_weather_prediction_pipeline_inputs(
        config=config,
        start_date=start_date,
        end_date=end_date,
    )

    fetch_config = JmaFetchConfig(
        station_num=config.station_num,
        station_name=config.station_name,
    )

    fetch_df = fetch_jma_weather_dataframe(
        config=fetch_config,
        start_date=start_date,
        end_date=end_date,
    )

    feature_df = build_weather_features(fetch_df)
    inference_input_result = build_weather_inference_input_result(feature_df)

    resolved_model_path = config.model_path
    if project_root is not None:
        resolved_model_path = (project_root / resolved_model_path).resolve()

    model = load_weather_prediction_model(resolved_model_path)
    pred_level = predict_weather_level_single(
        model,
        inference_input_result.model_input_df,
    )

    return WeatherPredictionPipelineResult(
        station_num=config.station_num,
        station_name=config.station_name,
        start_date=start_date,
        end_date=end_date,
        fetch_rows=len(fetch_df),
        feature_rows=len(feature_df),
        latest_datetime=inference_input_result.latest_datetime,
        pred_level=pred_level,
        model_input_df=inference_input_result.model_input_df,
        feature_df=feature_df,
    )


def build_weather_prediction_pipeline_summary(
    result: WeatherPredictionPipelineResult,
) -> dict[str, object]:
    """
    確認用サマリを返す
    """
    return {
        "station_num": result.station_num,
        "station_name": result.station_name,
        "start_date": result.start_date,
        "end_date": result.end_date,
        "fetch_rows": result.fetch_rows,
        "feature_rows": result.feature_rows,
        "latest_datetime": result.latest_datetime,
        "pred_level": result.pred_level,
        "model_input_columns": list(result.model_input_df.columns),
    }