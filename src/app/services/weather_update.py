#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
気象データ差分更新サービス

■ 目的
- 既存の気象データCSVを読み込み、保存済み最終日を判定する
- API から不足日だけ取得するための日付範囲を決定する
- 新規取得データを既存データへ追記し、重複を除去する
- UI や CLI から再利用しやすい service として提供する

■ 方針
- API 呼び出し本体はこの service に固定実装しない
- fetcher callable を注入し、後で気象庁 API 実装を差し替えられるようにする
- まずは差分更新ロジックと保存処理を安定させる

■ 想定データ
- 日単位または日時単位の観測データ
- 少なくとも date_col で時系列順に並べられること
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

import pandas as pd


@dataclass(frozen=True)
class WeatherUpdateConfig:
    csv_path: Path
    date_col: str = "date"
    date_format: str | None = None
    encoding: str = "utf-8-sig"


@dataclass(frozen=True)
class WeatherUpdatePlan:
    local_last_date: date | None
    api_latest_date: date
    fetch_start_date: date | None
    fetch_end_date: date | None
    needs_update: bool


@dataclass(frozen=True)
class WeatherUpdateResult:
    local_last_date_before: date | None
    api_latest_date: date
    fetch_start_date: date | None
    fetch_end_date: date | None
    fetched_rows: int
    rows_before: int
    rows_after: int
    updated_last_date: date | None
    needs_update: bool
    saved_csv_path: Path
    status: str
    status_message: str


Fetcher = Callable[[date, date], pd.DataFrame]


def _normalize_to_date(value: object, *, date_format: str | None = None) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, str):
        text = value.strip()
        if text == "":
            raise ValueError("empty date string is not allowed")

        if date_format:
            return datetime.strptime(text, date_format).date()

        return pd.to_datetime(text).date()

    return pd.to_datetime(value).date()


def _ensure_date_column(df: pd.DataFrame, date_col: str, date_format: str | None) -> pd.DataFrame:
    if date_col not in df.columns:
        raise ValueError(f"required date column is missing: {date_col}")

    result = df.copy()
    result[date_col] = result[date_col].apply(
        lambda value: _normalize_to_date(value, date_format=date_format)
    )
    return result


def load_existing_weather_data(config: WeatherUpdateConfig) -> pd.DataFrame:
    if not config.csv_path.exists():
        return pd.DataFrame(columns=[config.date_col])

    if not config.csv_path.is_file():
        raise ValueError(f"weather csv path is not a file: {config.csv_path}")

    df = pd.read_csv(config.csv_path, encoding=config.encoding)
    if len(df) == 0:
        if config.date_col not in df.columns:
            df[config.date_col] = pd.Series(dtype="object")
        return df

    return _ensure_date_column(df, config.date_col, config.date_format)


def get_local_last_date(df: pd.DataFrame, date_col: str) -> date | None:
    if len(df) == 0:
        return None
    if date_col not in df.columns:
        return None

    series = df[date_col].dropna()
    if len(series) == 0:
        return None

    return max(series)


def build_weather_update_plan(
    *,
    local_last_date: date | None,
    api_latest_date: date,
) -> WeatherUpdatePlan:
    if not isinstance(api_latest_date, date):
        raise TypeError("api_latest_date must be date")

    if local_last_date is None:
        return WeatherUpdatePlan(
            local_last_date=None,
            api_latest_date=api_latest_date,
            fetch_start_date=api_latest_date,
            fetch_end_date=api_latest_date,
            needs_update=True,
        )

    fetch_start_date = local_last_date + timedelta(days=1)

    if fetch_start_date > api_latest_date:
        return WeatherUpdatePlan(
            local_last_date=local_last_date,
            api_latest_date=api_latest_date,
            fetch_start_date=None,
            fetch_end_date=None,
            needs_update=False,
        )

    return WeatherUpdatePlan(
        local_last_date=local_last_date,
        api_latest_date=api_latest_date,
        fetch_start_date=fetch_start_date,
        fetch_end_date=api_latest_date,
        needs_update=True,
    )


def normalize_fetched_weather_data(
    df: pd.DataFrame,
    *,
    date_col: str,
    date_format: str | None,
) -> pd.DataFrame:
    if not isinstance(df, pd.DataFrame):
        raise TypeError("fetched weather data must be DataFrame")

    if len(df) == 0:
        return pd.DataFrame(columns=[date_col])

    return _ensure_date_column(df, date_col, date_format)


def merge_weather_data(
    *,
    existing_df: pd.DataFrame,
    fetched_df: pd.DataFrame,
    date_col: str,
) -> pd.DataFrame:
    if len(existing_df) == 0 and len(fetched_df) == 0:
        return pd.DataFrame(columns=[date_col])

    if len(existing_df) == 0:
        merged = fetched_df.copy()
    elif len(fetched_df) == 0:
        merged = existing_df.copy()
    else:
        merged = pd.concat([existing_df, fetched_df], ignore_index=True)

    merged = merged.drop_duplicates()
    merged = merged.sort_values(by=[date_col]).reset_index(drop=True)
    return merged


def save_weather_data(df: pd.DataFrame, config: WeatherUpdateConfig) -> None:
    config.csv_path.parent.mkdir(parents=True, exist_ok=True)

    save_df = df.copy()
    if config.date_col in save_df.columns:
        save_df[config.date_col] = save_df[config.date_col].apply(
            lambda d: d.isoformat() if isinstance(d, date) else str(d)
        )

    save_df.to_csv(config.csv_path, index=False, encoding=config.encoding)


def build_weather_runtime_status(
    *,
    updated_last_date: date | None,
    api_latest_date: date,
    used_fallback_local: bool = False,
) -> tuple[str, str]:
    if used_fallback_local:
        if updated_last_date is None:
            return ("error", "気象データを利用できません")
        return ("fallback_local", "手持ち最新データによる暫定推論")

    if updated_last_date is None:
        return ("error", "気象データを利用できません")

    if updated_last_date >= api_latest_date:
        return ("updated", "最新データ反映済み")

    return ("fallback_local", "手持ち最新データによる暫定推論")


def update_weather_data_by_diff(
    *,
    config: WeatherUpdateConfig,
    api_latest_date: date,
    fetcher: Fetcher,
) -> WeatherUpdateResult:
    if not callable(fetcher):
        raise TypeError("fetcher must be callable")

    existing_df = load_existing_weather_data(config)
    rows_before = len(existing_df)
    local_last_date_before = get_local_last_date(existing_df, config.date_col)

    plan = build_weather_update_plan(
        local_last_date=local_last_date_before,
        api_latest_date=api_latest_date,
    )

    if not plan.needs_update:
        updated_last_date = local_last_date_before
        save_weather_data(existing_df, config)
        return WeatherUpdateResult(
            local_last_date_before=local_last_date_before,
            api_latest_date=api_latest_date,
            fetch_start_date=None,
            fetch_end_date=None,
            fetched_rows=0,
            rows_before=rows_before,
            rows_after=len(existing_df),
            updated_last_date=updated_last_date,
            needs_update=False,
            saved_csv_path=config.csv_path,
            status="up_to_date",
            status_message="既に最新です",
        )

    assert plan.fetch_start_date is not None
    assert plan.fetch_end_date is not None

    fetched_raw_df = fetcher(plan.fetch_start_date, plan.fetch_end_date)
    fetched_df = normalize_fetched_weather_data(
        fetched_raw_df,
        date_col=config.date_col,
        date_format=config.date_format,
    )

    merged_df = merge_weather_data(
        existing_df=existing_df,
        fetched_df=fetched_df,
        date_col=config.date_col,
    )
    save_weather_data(merged_df, config)

    updated_last_date = get_local_last_date(merged_df, config.date_col)
    status, status_message = build_weather_runtime_status(
        updated_last_date=updated_last_date,
        api_latest_date=api_latest_date,
        used_fallback_local=False,
    )

    return WeatherUpdateResult(
        local_last_date_before=local_last_date_before,
        api_latest_date=api_latest_date,
        fetch_start_date=plan.fetch_start_date,
        fetch_end_date=plan.fetch_end_date,
        fetched_rows=len(fetched_df),
        rows_before=rows_before,
        rows_after=len(merged_df),
        updated_last_date=updated_last_date,
        needs_update=True,
        saved_csv_path=config.csv_path,
        status=status,
        status_message=status_message,
    )


def build_fallback_local_weather_result(
    *,
    config: WeatherUpdateConfig,
    api_latest_date: date,
) -> WeatherUpdateResult:
    existing_df = load_existing_weather_data(config)
    rows_before = len(existing_df)
    updated_last_date = get_local_last_date(existing_df, config.date_col)

    status, status_message = build_weather_runtime_status(
        updated_last_date=updated_last_date,
        api_latest_date=api_latest_date,
        used_fallback_local=True,
    )

    return WeatherUpdateResult(
        local_last_date_before=updated_last_date,
        api_latest_date=api_latest_date,
        fetch_start_date=None,
        fetch_end_date=None,
        fetched_rows=0,
        rows_before=rows_before,
        rows_after=rows_before,
        updated_last_date=updated_last_date,
        needs_update=False,
        saved_csv_path=config.csv_path,
        status=status,
        status_message=status_message,
    )


def build_weather_update_preview_rows(result: WeatherUpdateResult) -> list[dict[str, object]]:
    return [
        {"項目": "local_last_date_before", "値": result.local_last_date_before},
        {"項目": "api_latest_date", "値": result.api_latest_date},
        {"項目": "fetch_start_date", "値": result.fetch_start_date},
        {"項目": "fetch_end_date", "値": result.fetch_end_date},
        {"項目": "fetched_rows", "値": result.fetched_rows},
        {"項目": "rows_before", "値": result.rows_before},
        {"項目": "rows_after", "値": result.rows_after},
        {"項目": "updated_last_date", "値": result.updated_last_date},
        {"項目": "needs_update", "値": result.needs_update},
        {"項目": "status", "値": result.status},
        {"項目": "status_message", "値": result.status_message},
        {"項目": "saved_csv_path", "値": str(result.saved_csv_path)},
    ]