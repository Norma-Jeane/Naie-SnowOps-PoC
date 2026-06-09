#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
気象推論入力生成サービス

■ 目的
- JMA取得済みの時間単位気象データから、現行モデル推論に必要な最新1行入力を生成する
- weather_fetcher_jma.py と weather_features.py の橋渡しを行う

■ 対象
- 現行モデルが必要とする列
  temp
  precipitation
  wind_speed
  snow_depth
  snow_diff_6h
  hour

■ 方針
- 取得そのものは fetcher に委譲する
- 特徴量生成は weather_features.py に委譲する
- この service は「最新1行を推論入力へ整形する責務」に絞る
- snow_diff_12h は feature 側では保持してもよいが、現行推論入力には含めない

■ 非責務
- モデル読み込み
- モデル推論
- CSV保存
- UI表示
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


MODEL_FEATURE_COLUMNS = [
    "temp",
    "precipitation",
    "wind_speed",
    "snow_depth",
    "snow_diff_6h",
    "hour",
]


@dataclass(frozen=True)
class WeatherInferenceInputResult:
    """
    推論入力生成結果
    """

    latest_datetime: pd.Timestamp
    feature_df_rows: int
    model_input_rows: int
    model_input_df: pd.DataFrame


def validate_feature_dataframe_for_inference(
    df: pd.DataFrame,
) -> None:
    """
    推論入力へ使う前に、必要列が揃っているか確認する
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError("df must be pandas.DataFrame")

    if len(df) == 0:
        raise ValueError("feature dataframe is empty")

    required_cols = ["datetime", *MODEL_FEATURE_COLUMNS]
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        raise ValueError(f"feature dataframe missing required columns: {missing}")


def sort_feature_dataframe_for_inference(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """
    推論入力抽出用に datetime 昇順へ整列する
    """
    result = df.copy()
    result["datetime"] = pd.to_datetime(result["datetime"], errors="coerce")

    invalid_count = int(result["datetime"].isna().sum())
    if invalid_count > 0:
        raise ValueError(f"datetime contains invalid values: {invalid_count}")

    result = result.sort_values("datetime").reset_index(drop=True)
    return result


def build_latest_model_input_dataframe(
    feature_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    特徴量付きDataFrameから最新1行のモデル入力DataFrameを生成する
    """
    validate_feature_dataframe_for_inference(feature_df)

    sorted_df = sort_feature_dataframe_for_inference(feature_df)
    latest_row = sorted_df.tail(1).copy()

    model_input_df = latest_row[MODEL_FEATURE_COLUMNS].copy()
    return model_input_df


def build_weather_inference_input_result(
    feature_df: pd.DataFrame,
) -> WeatherInferenceInputResult:
    """
    特徴量付きDataFrameから推論入力生成結果を構築する
    """
    validate_feature_dataframe_for_inference(feature_df)

    sorted_df = sort_feature_dataframe_for_inference(feature_df)
    latest_row = sorted_df.tail(1).copy()
    latest_datetime = pd.Timestamp(latest_row.iloc[0]["datetime"])

    model_input_df = latest_row[MODEL_FEATURE_COLUMNS].copy()

    return WeatherInferenceInputResult(
        latest_datetime=latest_datetime,
        feature_df_rows=len(sorted_df),
        model_input_rows=len(model_input_df),
        model_input_df=model_input_df,
    )


def build_weather_inference_input_summary(
    result: WeatherInferenceInputResult,
) -> dict[str, object]:
    """
    確認用サマリを返す
    """
    return {
        "latest_datetime": result.latest_datetime,
        "feature_df_rows": result.feature_df_rows,
        "model_input_rows": result.model_input_rows,
        "model_input_columns": list(result.model_input_df.columns),
    }