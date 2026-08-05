from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

OUT = Path("research_output/hk_monetary_windowed")
RAW = OUT / "raw"
RAW.mkdir(parents=True, exist_ok=True)
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 AcademicResearch/1.0",
    "Accept": "application/json",
})
MANIFEST: list[dict[str, Any]] = []


def save_manifest(name: str, url: str, status: str, rows: int | None = None, note: str = "") -> None:
    MANIFEST.append({
        "name": name,
        "url": url,
        "status": status,
        "rows": rows,
        "note": note,
        "retrieved_utc": datetime.now(timezone.utc).isoformat(),
    })


def get_json(url: str, params: dict[str, Any], timeout: int = 35) -> dict[str, Any]:
    last: Exception | None = None
    for attempt in range(3):
        try:
            r = SESSION.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            payload = r.json()
            header = payload.get("header", {})
            if header and header.get("success") is False:
                raise RuntimeError(f"HKMA error: {header}")
            return payload
        except Exception as exc:
            last = exc
            print(f"retry {attempt+1}/3 {url} {params}: {exc}", flush=True)
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"request failed: {last}")


def fetch_window(url: str, params: dict[str, Any], date_field: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    offset = 0
    while True:
        q = dict(params)
        q.update({
            "pagesize": 100,
            "offset": offset,
            "sortby": date_field,
            "sortorder": "asc",
        })
        payload = get_json(url, q)
        result = payload.get("result", {})
        page = result.get("records", []) or []
        if not isinstance(page, list):
            raise ValueError("records is not a list")
        records.extend(page)
        declared = result.get("datasize")
        print(
            f"window {params.get('from')}..{params.get('to')} offset={offset} "
            f"page={len(page)} total={len(records)} declared={declared}",
            flush=True,
        )
        if not page or len(page) < 100:
            break
        try:
            if declared is not None and len(records) >= int(declared):
                break
        except (TypeError, ValueError):
            pass
        offset += len(page)
        if offset > 5000:
            raise RuntimeError("window pagination guard")
        time.sleep(0.05)
    return records


def fetch_series(
    name: str,
    url: str,
    date_field: str,
    frequency: str,
    base_params: dict[str, Any] | None = None,
    start_year: int = 1990,
    end_year: int = 2026,
) -> None:
    base_params = dict(base_params or {})
    all_records: list[dict[str, Any]] = []
    errors: list[str] = []
    for year in range(start_year, end_year + 1):
        if frequency == "daily":
            start, end = f"{year}-01-01", f"{year}-12-31"
        else:
            start, end = f"{year}-01", f"{year}-12"
        params = {**base_params, "from": start, "to": end}
        try:
            page = fetch_window(url, params, date_field)
            all_records.extend(page)
            print(f"{name} {year}: +{len(page)}", flush=True)
        except Exception as exc:
            errors.append(f"{year}: {exc!r}")
            print(f"{name} {year} FAILED: {exc}", flush=True)
        time.sleep(0.08)

    df = pd.DataFrame(all_records).drop_duplicates()
    if date_field in df.columns:
        df[date_field] = pd.to_datetime(df[date_field], errors="coerce")
        df = df.sort_values(date_field)
    path = RAW / f"{name}.csv"
    df.to_csv(path, index=False)
    status = "ok" if not df.empty else "failed"
    save_manifest(name, url, status, len(df), json.dumps(errors, ensure_ascii=False))
    print(f"saved {name}: {len(df)} rows; errors={len(errors)}", flush=True)


def main() -> None:
    root = "https://api.hkma.gov.hk/public/market-data-and-statistics"
    specs = [
        ("hkma_interbank_liquidity_daily", f"{root}/daily-monetary-statistics/daily-figures-interbank-liquidity", "end_of_date", "daily", {}, 2001),
        ("hkma_monetary_base_daily", f"{root}/daily-monetary-statistics/daily-figures-monetary-base", "end_of_date", "daily", {}, 2001),
        ("hkma_hibor_fixing_daily", f"{root}/monthly-statistical-bulletin/er-ir/hk-interbank-ir-daily", "end_of_day", "daily", {"segment": "hibor.fixing"}, 1997),
        ("hkma_banking_statistics_monthly", f"{root}/monthly-statistical-bulletin/financial/banking-statistics", "end_of_month", "monthly", {}, 1990),
        ("hkma_monetary_statistics_monthly", f"{root}/monthly-statistical-bulletin/financial/monetary-statistics", "end_of_month", "monthly", {}, 1990),
        ("hkma_loans_by_type_lb_new", f"{root}/monthly-statistical-bulletin/banking/loans-by-type-lb", "end_of_month", "monthly", {"segment": "new"}, 1990),
        ("hkma_loans_by_type_lb_old", f"{root}/monthly-statistical-bulletin/banking/loans-by-type-lb", "end_of_month", "monthly", {"segment": "old"}, 1990),
        ("hkma_mortgage_survey_new", f"{root}/monthly-statistical-bulletin/banking/residential-mortgage-survey", "end_of_month", "monthly", {"segment": "new"}, 1990),
        ("hkma_mortgage_survey_old", f"{root}/monthly-statistical-bulletin/banking/residential-mortgage-survey", "end_of_month", "monthly", {"segment": "old"}, 1990),
    ]
    for name, url, date_field, freq, params, start_year in specs:
        fetch_series(name, url, date_field, freq, params, start_year=start_year)

    pd.DataFrame(MANIFEST).to_csv(OUT / "source_manifest.csv", index=False)
    (OUT / "source_manifest.json").write_text(
        json.dumps(MANIFEST, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
