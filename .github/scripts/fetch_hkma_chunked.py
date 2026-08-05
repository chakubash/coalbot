from __future__ import annotations

import hashlib
import json
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

OUT = Path("research_output/hkma_official_chunked")
CHUNKS = OUT / "chunks"
OUT.mkdir(parents=True, exist_ok=True)
CHUNKS.mkdir(parents=True, exist_ok=True)

S = requests.Session()
S.headers.update({
    "User-Agent": "AcademicResearchBot/2.0 (+https://github.com/chakubash/coalbot)",
    "Accept": "application/json",
})

BASE = "https://api.hkma.gov.hk/public/market-data-and-statistics"
MANIFEST: list[dict[str, Any]] = []


def request_json(url: str, params: dict[str, Any], attempts: int = 6) -> dict[str, Any]:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            r = S.get(url, params=params, timeout=(20, 180))
            r.raise_for_status()
            payload = r.json()
            if not payload.get("header", {}).get("success", False):
                raise RuntimeError(f"HKMA error: {payload.get('header')}")
            return payload
        except Exception as exc:
            last = exc
            pause = min(30, 2 ** attempt)
            print(f"attempt {attempt + 1}/{attempts} failed: {url} {params}: {exc}; pause={pause}", flush=True)
            time.sleep(pause)
    raise RuntimeError(f"HKMA request failed after {attempts} attempts: {last}")


def parse_date_value(value: str) -> date:
    if len(value) == 7:
        return datetime.strptime(value, "%Y-%m").date()
    return datetime.strptime(value, "%Y-%m-%d").date()


def fetch_chunk(
    *,
    dataset: str,
    url: str,
    choose: str,
    start: str,
    end: str,
    fields: str | None = None,
    extra: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "choose": choose,
        "from": start,
        "to": end,
        "sortby": choose,
        "sortorder": "asc",
        "pagesize": 1000,
        "offset": 0,
    }
    if fields:
        params["fields"] = fields
    if extra:
        params.update(extra)

    payload = request_json(url, params)
    result = payload.get("result", {})
    records = result.get("records", []) or []
    if not isinstance(records, list):
        raise TypeError(f"records is not a list for {dataset}")
    if int(result.get("datasize", len(records))) != len(records):
        raise RuntimeError(f"unexpected pagination for {dataset} {start}:{end}: datasize={result.get('datasize')}, records={len(records)}")
    if len(records) > 1000:
        raise RuntimeError(f"chunk too large for {dataset}: {len(records)}")

    lo = parse_date_value(start)
    hi = parse_date_value(end)
    for row in records:
        v = str(row[choose])
        d = parse_date_value(v)
        if not (lo <= d <= hi):
            raise RuntimeError(
                f"HKMA ignored range for {dataset}: requested {start}:{end}, got {v}"
            )

    path = CHUNKS / f"{dataset}_{start}_{end}.json"
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    path.write_bytes(raw)
    MANIFEST.append({
        "dataset": dataset,
        "url": url,
        "choose": choose,
        "from": start,
        "to": end,
        "records": len(records),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "retrieved_utc": datetime.now(timezone.utc).isoformat(),
        "params": json.dumps(params, ensure_ascii=False),
    })
    print(f"{dataset} {start}:{end} -> {len(records)}", flush=True)
    return records


def two_year_ranges(start_year: int, end_year: int, first_date: str, last_date: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    y = start_year
    while y <= end_year:
        y2 = min(end_year, y + 1)
        start = first_date if y == start_year else f"{y}-01-01"
        end = last_date if y2 == end_year else f"{y2}-12-31"
        out.append((start, end))
        y = y2 + 1
    return out


def assemble(dataset: str, rows: list[dict[str, Any]], key: str) -> None:
    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError(f"no records for {dataset}")
    df = df.drop_duplicates(subset=[key], keep="last").sort_values(key).reset_index(drop=True)
    df.to_csv(OUT / f"{dataset}.csv", index=False)
    print(f"assembled {dataset}: {len(df)} rows, {df[key].iloc[0]} to {df[key].iloc[-1]}", flush=True)


def main() -> None:
    last_daily = "2026-08-04"
    ranges = two_year_ranges(2005, 2026, "2005-05-18", last_daily)

    specs = [
        {
            "dataset": "interbank_liquidity_daily",
            "url": f"{BASE}/daily-monetary-statistics/daily-figures-interbank-liquidity",
            "choose": "end_of_date",
            "fields": "end_of_date,cu_weakside,cu_strongside,disc_win_base_rate,hibor_overnight,hibor_fixing_1m,opening_balance,closing_balance",
            "extra": {},
        },
        {
            "dataset": "monetary_base_daily",
            "url": f"{BASE}/daily-monetary-statistics/daily-figures-monetary-base",
            "choose": "end_of_date",
            "fields": "end_of_date,cert_of_indebt,gov_notes_coins_circulation,aggr_balance_bf_disc_win,aggr_balance_af_disc_win,outstanding_efbn,ow_lb_bf_disc_win,ow_lb_af_disc_win,mb_bf_disc_win_total",
            "extra": {},
        },
        {
            "dataset": "hibor_fixing_daily",
            "url": f"{BASE}/monthly-statistical-bulletin/er-ir/hk-interbank-ir-daily",
            "choose": "end_of_day",
            "fields": "end_of_day,ir_overnight,ir_1w,ir_1m,ir_3m,ir_6m,ir_12m",
            "extra": {"segment": "hibor.fixing"},
        },
    ]

    for spec in specs:
        all_rows: list[dict[str, Any]] = []
        for start, end in ranges:
            all_rows.extend(fetch_chunk(start=start, end=end, **spec))
            time.sleep(0.25)
        assemble(spec["dataset"], all_rows, spec["choose"])

    monthly_specs = [
        {
            "dataset": "banking_statistics_monthly",
            "url": f"{BASE}/monthly-statistical-bulletin/financial/banking-statistics",
            "choose": "end_of_month",
            "fields": None,
            "extra": {},
        },
        {
            "dataset": "monetary_statistics_monthly",
            "url": f"{BASE}/monthly-statistical-bulletin/financial/monetary-statistics",
            "choose": "end_of_month",
            "fields": None,
            "extra": {},
        },
    ]
    for spec in monthly_specs:
        rows = fetch_chunk(start="1997-01", end="2026-06", **spec)
        assemble(spec["dataset"], rows, spec["choose"])

    pd.DataFrame(MANIFEST).to_csv(OUT / "manifest.csv", index=False)
    (OUT / "manifest.json").write_text(json.dumps(MANIFEST, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
