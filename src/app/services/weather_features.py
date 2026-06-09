#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
気象データ特徴量生成サービス

■ 目的
- JMA取得・整形後の基本観測列を入力として、
  推論入力および将来拡張向けの特徴量付き DataFrame を生成する

■ 入力前提
- 少なくとも以下の列を持つ DataFrame
  datetime
  temp
  precipitation
  wind_speed
  snow_depth

■ 出力
- 少なくとも以下の列を持つ DataFrame
  datetime
  temp
  precipitation
  wind_speed
  snow_depth
  hour
  snow_diff_6h
  snow_diff_12h

■ 方針
- CSV読み込みや保存は行わない
- datetime を正本として扱う
- 時系列整列後に特徴量を生成する
- datetime 重複は keep="last" で解消する
- hour は datetime から派生生成する
- snow_diff_6h / snow_diff_12h は snow_depth の時間差分として生成する
- 差分先頭行の NaN は 0.0 で埋める
  （初版運用上の扱いやすさを優先。必要に応じて後で方針変更可能）

■ 備考
- snow_diff_12h は現行推論の必須列ではないが、
  Step B のデータ整備・ラベル設計との整合のため保持する
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


REQUIRED_BASE_COLUMNS = [
    "datetime",
    "temp",
    "precipitation",
    "wind_speed",
    "snow_depth",
]

OUTPUT_COLUMNS = [
    "datetime",
    "temp",
    "precipitation",
    "wind_speed",
    "snow_depth",
    "hour",
    "snow_diff_6h",
    "snow_diff_12h",
]


@dataclass(frozen=True)
class WeatherFeatureConfig:
    """
    特徴量生成設定
    """

    datetime_col: str = "datetime"
    snow_depth_col: str = "snow_depth"
    duplicate_keep: str = "last"
    fill_initial_diff_with_zero: bool = True


def validate_weather_feature_input(
    df: pd.DataFrame,
    *,
    datetime_col: str = "datetime",
    snow_depth_col: str = "snow_depth",
) -> None:
    """
    入力DataFrameの必須列を確認する
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError("df must be pandas.DataFrame")

    required_cols = [
        datetime_col,
        "temp",
        "precipitation",
        "wind_speed",
        snow_depth_col,
    ]
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        raise ValueError(f"required columns are missing: {missing}")


def prepare_weather_datetime(
    df: pd.DataFrame,
    *,
    datetime_col: str = "datetime",
) -> pd.DataFrame:
    """
    datetime列を pandas datetime 型へ変換する
    """
    result = df.copy()
    result[datetime_col] = pd.to_datetime(result[datetime_col], errors="coerce")

    invalid_count = int(result[datetime_col].isna().sum())
    if invalid_count > 0:
        raise ValueError(f"{datetime_col} contains invalid datetime values: {invalid_count}")

    return result


def sort_and_deduplicate_weather(
    df: pd.DataFrame,
    *,
    datetime_col: str = "datetime",
    keep: str = "last",
) -> pd.DataFrame:
    """
    datetime昇順で整列し、重複日時を解消する
    """
    if keep not in {"first", "last"}:
        raise ValueError("keep must be 'first' or 'last'")

    result = df.copy()
    result = result.sort_values(datetime_col)
    result = result.drop_duplicates(subset=[datetime_col], keep=keep)
    result = result.reset_index(drop=True)
    return result


def add_hour_feature(
    df: pd.DataFrame,
    *,
    datetime_col: str = "datetime",
) -> pd.DataFrame:
    """
    datetime から hour を生成する
    """
    result = df.copy()
    result["hour"] = result[datetime_col].dt.hour
    return result


def add_snow_diff_feature(
    df: pd.DataFrame,
    *,
    hours: int,
    snow_depth_col: str = "snow_depth",
    fill_initial_with_zero: bool = True,
) -> pd.DataFrame:
    """
    snow_depth の時間差分特徴量を生成する
    """
    if hours <= 0:
        raise ValueError(f"hours must be positive: {hours}")

    result = df.copy()
    col_name = f"snow_diff_{hours}h"
    result[col_name] = result[snow_depth_col] - result[snow_depth_col].shift(hours)

    if fill_initial_with_zero:
        result[col_name] = result[col_name].fillna(0.0)

    return result


def build_weather_features(
    df: pd.DataFrame,
    *,
    config: WeatherFeatureConfig | None = None,
) -> pd.DataFrame:
    """
    気象特徴量付きDataFrameを生成する公開関数
    """
    cfg = config or WeatherFeatureConfig()

    validate_weather_feature_input(
        df,
        datetime_col=cfg.datetime_col,
        snow_depth_col=cfg.snow_depth_col,
    )

    result = prepare_weather_datetime(
        df,
        datetime_col=cfg.datetime_col,
    )

    result = sort_and_deduplicate_weather(
        result,
        datetime_col=cfg.datetime_col,
        keep=cfg.duplicate_keep,
    )

    result = add_hour_feature(
        result,
        datetime_col=cfg.datetime_col,
    )

    result = add_snow_diff_feature(
        result,
        hours=6,
        snow_depth_col=cfg.snow_depth_col,
        fill_initial_with_zero=cfg.fill_initial_diff_with_zero,
    )

    result = add_snow_diff_feature(
        result,
        hours=12,
        snow_depth_col=cfg.snow_depth_col,
        fill_initial_with_zero=cfg.fill_initial_diff_with_zero,
    )

    output_cols = [
        cfg.datetime_col,
        "temp",
        "precipitation",
        "wind_speed",
        cfg.snow_depth_col,
        "hour",
        "snow_diff_6h",
        "snow_diff_12h",
    ]
    result = result[output_cols].copy()

    if cfg.datetime_col != "datetime":
        result = result.rename(columns={cfg.datetime_col: "datetime"})

    if cfg.snow_depth_col != "snow_depth":
        result = result.rename(columns={cfg.snow_depth_col: "snow_depth"})

    return result


def build_weather_feature_summary(df: pd.DataFrame) -> dict[str, object]:
    """
    確認用サマリを返す
    """
    rows = len(df)

    return {
        "rows": rows,
        "columns": list(df.columns),
        "datetime_min": df["datetime"].min() if rows > 0 and "datetime" in df.columns else None,
        "datetime_max": df["datetime"].max() if rows > 0 and "datetime" in df.columns else None,
    }