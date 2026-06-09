#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
気象推論サービス

■ 目的
- 学習済みモデルを読み込み、気象推論入力から pred_level を返す
- weather_inference_input.py が生成した model_input_df を受けて推論する

■ 対象
- 現行モデルが必要とする列
  temp
  precipitation
  wind_speed
  snow_depth
  snow_diff_6h
  hour

■ 方針
- 推論入力の整形は weather_inference_input.py に委譲する
- この service は「モデル読み込み」と「推論実行」の責務に絞る
- 単一行推論を基本とするが、DataFrame の複数行推論も可能とする

■ 非責務
- 気象取得
- 特徴量生成
- 最新1行抽出
- CSV保存
- UI表示
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import joblib
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
class WeatherPredictionResult:
    """
    気象推論結果
    """

    input_rows: int
    pred_levels: list[int]


def validate_weather_model_input(df: pd.DataFrame) -> None:
    """
    モデル推論用入力の妥当性を確認する
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError("df must be pandas.DataFrame")

    if len(df) == 0:
        raise ValueError("model input dataframe is empty")

    missing = [col for col in MODEL_FEATURE_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"model input dataframe missing required columns: {missing}")


def load_weather_prediction_model(model_path: Path):
    """
    学習済みモデルを読み込む
    """
    if not isinstance(model_path, Path):
        model_path = Path(model_path)

    if not model_path.exists():
        raise FileNotFoundError(f"model not found: {model_path}")

    if not model_path.is_file():
        raise ValueError(f"model path is not a file: {model_path}")

    return joblib.load(model_path)


def predict_weather_levels(model, model_input_df: pd.DataFrame) -> WeatherPredictionResult:
    """
    モデル入力DataFrameに対して推論を実行する
    """
    validate_weather_model_input(model_input_df)

    X = model_input_df[MODEL_FEATURE_COLUMNS].copy()
    pred = model.predict(X)
    pred_levels = [int(x) for x in pred.tolist()]

    return WeatherPredictionResult(
        input_rows=len(model_input_df),
        pred_levels=pred_levels,
    )


def predict_weather_level_single(model, model_input_df: pd.DataFrame) -> int:
    """
    単一行推論を行い、pred_level を1つ返す
    """
    result = predict_weather_levels(model, model_input_df)

    if result.input_rows != 1:
        raise ValueError(
            f"single-row prediction requires exactly 1 input row, got {result.input_rows}"
        )

    return result.pred_levels[0]


def build_weather_prediction_summary(result: WeatherPredictionResult) -> dict[str, object]:
    """
    確認用サマリを返す
    """
    return {
        "input_rows": result.input_rows,
        "pred_levels": result.pred_levels,
    }