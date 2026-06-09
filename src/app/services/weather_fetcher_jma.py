#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
気象庁データ取得 fetcher

■ 目的
- 気象庁「過去の気象データ・ダウンロード」相当の HTTP 通信で CSV テキストを取得する
- 取得した CSV テキストを、多段ヘッダを考慮して DataFrame に変換する
- 後段の特徴量生成へ渡しやすい基本観測列
  (datetime / temp / precipitation / wind_speed / snow_depth)
  へ正規化する

■ 方針
- 生CSVは本線ではメモリ上の文字列として扱う
- C2b の確認用スクリプトを鉱脈とみなし、
  生CSV整形に有用なコアだけを service 側へ再配置する
- 6h差分や hour はこの module では作らない
- station_num は取得制御の主キー
- station_name は任意メタ情報として保持するが、処理の必須条件にはしない

■ 備考
- 差分更新ロジック本体は weather_update.py 側に置く
- 接続後の特徴量生成は別段で扱う
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from io import StringIO
import csv
import json
import re
from typing import Sequence

import pandas as pd
import requests


JMA_OBSDL_POST_URL = "https://www.data.jma.go.jp/risk/obsdl/show/table"
JMA_REFERER = "https://www.data.jma.go.jp/risk/obsdl/"
DEFAULT_TIMEOUT = 30.0

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": JMA_REFERER,
    "Origin": "https://www.data.jma.go.jp",
}

# C2a 実行方法メモ相当の既定値
DEFAULT_ELEMENT_NUM_LIST = [
    ["201", ""],  # 気温
    ["101", ""],  # 降水量
    ["503", ""],  # 風速
    ["301", ""],  # 積雪
    ["501", ""],  # 追加列候補
]

ENCODING_CANDIDATES = [
    "utf-8",
    "utf-8-sig",
    "cp932",
    "shift_jis",
]


@dataclass(frozen=True)
class JmaFetchConfig:
    station_num: str
    station_name: str | None = None
    timeout: float = DEFAULT_TIMEOUT
    encoding: str | None = None
    headers: dict[str, str] | None = None
    cookies: dict[str, str] | None = None


def infer_jma_latest_available_date(today: date | None = None) -> date:
    """
    現時点では公式ページの案内に合わせ、前日までを取得可能上限とみなす。
    """
    base = today or date.today()
    return base - timedelta(days=1)


def _normalize_form_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _build_form_data(
    *,
    station_num: str,
    start_date: date,
    end_date: date,
    element_num_list: list[list[str]] | None = None,
) -> dict[str, str]:
    elements = element_num_list or DEFAULT_ELEMENT_NUM_LIST

    payload = {
        "stationNumList": [station_num],
        "aggrgPeriod": 9,
        "elementNumList": elements,
        "interAnnualType": 1,
        "ymdList": [
            str(start_date.year),
            str(end_date.year),
            str(start_date.month),
            str(end_date.month),
            str(start_date.day),
            str(end_date.day),
        ],
        "optionNumList": [],
        "downloadFlag": True,
        "rmkFlag": 1,
        "disconnectFlag": 1,
        "youbiFlag": 0,
        "fukenFlag": 0,
        "kijiFlag": 0,
        "csvFlag": 1,
        "jikantaiFlag": 0,
        "jikantaiList": [1, 24],
        "ymdLiteral": 1,
    }

    return {k: _normalize_form_value(v) for k, v in payload.items()}


def fetch_jma_csv_text(
    *,
    config: JmaFetchConfig,
    start_date: date,
    end_date: date,
) -> str:
    if start_date > end_date:
        raise ValueError(f"start_date must be <= end_date: {start_date} > {end_date}")

    headers = DEFAULT_HEADERS.copy()
    if config.headers:
        headers.update(config.headers)

    response = requests.post(
        JMA_OBSDL_POST_URL,
        data=_build_form_data(
            station_num=config.station_num,
            start_date=start_date,
            end_date=end_date,
        ),
        headers=headers,
        cookies=config.cookies or {},
        timeout=config.timeout,
    )

    if response.status_code != 200:
        preview = response.text[:500] if response.text else ""
        raise RuntimeError(
            f"JMA fetch failed with status={response.status_code}\nresponse preview:\n{preview}"
        )

    if config.encoding:
        response.encoding = config.encoding

    text = response.text
    if not text.strip():
        raise RuntimeError("JMA response body is empty")

    _validate_response_looks_like_csv(response=response, text=text)
    return text


def _validate_response_looks_like_csv(*, response: requests.Response, text: str) -> None:
    content_type = (response.headers.get("Content-Type") or "").lower()
    content_disposition = (response.headers.get("Content-Disposition") or "").lower()
    head = text[:1000].lstrip().lower()

    looks_html = (
        head.startswith("<!doctype html")
        or head.startswith("<html")
        or "<html" in head[:300]
        or "<body" in head[:300]
    )
    if looks_html:
        raise RuntimeError("JMA response looks like HTML, not CSV")

    if "html" in content_type:
        raise RuntimeError(f"JMA response content-type looks like HTML: {content_type}")

    if "csv" in content_type:
        return

    if "application/octet-stream" in content_type and ".csv" in content_disposition:
        return

    if "text/plain" in content_type or "application/vnd.ms-excel" in content_type:
        return


def split_csv_text_lines(text: str) -> list[str]:
    if not isinstance(text, str):
        raise TypeError("csv text must be str")

    if not text.strip():
        raise ValueError("csv text is empty")

    lines = text.splitlines()
    if len(lines) == 0:
        raise ValueError("csv text has no lines")

    return lines


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    text = text.replace("\n", "_")
    text = text.replace(" ", "")
    text = text.replace("　", "")
    return text


def detect_header_row(lines: Sequence[str]) -> int:
    """
    列名行（年月日時 を含む行）を推定する。
    見つからない場合は 1 を返す。
    """
    for idx, line in enumerate(lines):
        if "年月日時" in line or ",年月日時," in line or line.startswith("年月日時"):
            return idx
    return 1


def parse_csv_rows(lines: Sequence[str]) -> list[list[str]]:
    reader = csv.reader(lines)
    return [row for row in reader]


def is_datetime_like(value: object) -> bool:
    text = str(value).strip()
    if not text:
        return False
    dt = pd.to_datetime(text, errors="coerce")
    return not pd.isna(dt)


def detect_first_data_row(
    rows: Sequence[Sequence[str]],
    *,
    header_row: int,
    scan_rows: int = 20,
) -> int:
    """
    ヘッダ行の後ろから、最初の実データ行を推定する。
    先頭列が日時らしい行を最初の実データ行とみなす。
    """
    start = header_row + 1
    end = min(len(rows), start + scan_rows)

    for i in range(start, end):
        row = rows[i]
        if not row:
            continue
        first_value = row[0] if len(row) > 0 else ""
        if is_datetime_like(first_value):
            return i

    return header_row + 1


def build_dataframe_from_rows(
    *,
    rows: Sequence[Sequence[str]],
    header_row: int,
    first_data_row: int,
) -> pd.DataFrame:
    if header_row >= len(rows):
        raise ValueError(f"header_row out of range: {header_row}")

    if first_data_row <= header_row:
        raise ValueError(
            f"first_data_row must be greater than header_row: "
            f"{first_data_row} <= {header_row}"
        )

    header = [normalize_text(col) for col in rows[header_row]]
    auxiliary_rows = rows[header_row + 1:first_data_row]
    data_rows = rows[first_data_row:]

    if not data_rows:
        raise ValueError("no data rows found after first_data_row")

    max_len = max(
        len(header),
        max((len(r) for r in auxiliary_rows), default=0),
        max((len(r) for r in data_rows), default=0),
    )

    padded_header = header + [f"unnamed_{i}" for i in range(len(header), max_len)]

    padded_aux_rows: list[list[str]] = []
    for row in auxiliary_rows:
        padded = list(row) + [""] * (max_len - len(row))
        padded_aux_rows.append(padded[:max_len])

    unique_columns: list[str] = []
    for col_idx in range(max_len):
        base = normalize_text(padded_header[col_idx])

        aux_labels = []
        for aux_row in padded_aux_rows:
            value = normalize_text(aux_row[col_idx])
            if value:
                aux_labels.append(value)

        aux_text = "__".join(aux_labels)

        if aux_text:
            unique_name = f"{base}__{aux_text}"
        else:
            unique_name = f"{base}__value"

        unique_columns.append(unique_name)

    padded_rows: list[list[str]] = []
    for row in data_rows:
        padded = list(row) + [""] * (max_len - len(row))
        padded_rows.append(padded[:max_len])

    return pd.DataFrame(padded_rows, columns=unique_columns)


def find_column(columns: list[str], patterns: list[str]) -> str | None:
    for col in columns:
        lowered = col.lower()
        for pattern in patterns:
            if re.search(pattern, lowered):
                return col
    return None


def build_column_mapping_for_fetcher(columns: list[str]) -> dict[str, str]:
    """
    service 用に絞った最小列マッピング。
    C2b の考え方を流用するが、station_name や補助分類には依存しない。
    """
    primary_columns = []
    for col in columns:
        if any(tag in col for tag in ["品質情報", "均質番号", "風向"]):
            continue
        primary_columns.append(col)

    dt_col = find_column(primary_columns, [r"年月日時", r"日時", r"date", r"datetime"])
    temp_col = find_column(primary_columns, [r"気温", r"temp"])
    precip_col = find_column(primary_columns, [r"降水量", r"precip"])
    wind_col = find_column(primary_columns, [r"風速", r"windspeed", r"wind_speed"])
    snow_col = find_column(primary_columns, [r"積雪", r"積雪深", r"snow"])

    mapping: dict[str, str] = {}
    if dt_col:
        mapping[dt_col] = "datetime"
    if temp_col:
        mapping[temp_col] = "temp"
    if precip_col:
        mapping[precip_col] = "precipitation"
    if wind_col:
        mapping[wind_col] = "wind_speed"
    if snow_col:
        mapping[snow_col] = "snow_depth"

    return mapping


def clean_numeric_column(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("--", "", regex=False)
        .str.replace("///", "", regex=False)
        .str.replace("×", "", regex=False)
        .str.replace("#", "", regex=False)
        .str.strip()
    )
    return pd.to_numeric(cleaned, errors="coerce")


def normalize_jma_dataframe_from_text(
    text: str,
) -> pd.DataFrame:
    lines = split_csv_text_lines(text)
    header_row = detect_header_row(lines)
    rows = parse_csv_rows(lines)
    first_data_row = detect_first_data_row(rows, header_row=header_row, scan_rows=20)

    df_raw = build_dataframe_from_rows(
        rows=rows,
        header_row=header_row,
        first_data_row=first_data_row,
    )

    mapping = build_column_mapping_for_fetcher(list(df_raw.columns))
    missing_targets = [
        logical_name
        for logical_name in ["datetime", "temp", "precipitation", "wind_speed", "snow_depth"]
        if logical_name not in mapping.values()
    ]
    if missing_targets:
        raise ValueError(f"required JMA columns could not be mapped: {missing_targets}")

    out = df_raw[list(mapping.keys())].rename(columns=mapping).copy()

    out["datetime"] = pd.to_datetime(out["datetime"], errors="coerce")
    out = out.dropna(subset=["datetime"]).reset_index(drop=True)

    for col in ["temp", "precipitation", "wind_speed", "snow_depth"]:
        out[col] = clean_numeric_column(out[col])

    out = out.sort_values("datetime").reset_index(drop=True)
    return out


def fetch_jma_weather_dataframe(
    *,
    config: JmaFetchConfig,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    text = fetch_jma_csv_text(
        config=config,
        start_date=start_date,
        end_date=end_date,
    )
    return normalize_jma_dataframe_from_text(text)