from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

OUT = Path("research_output/hkma_monthly_official")
OUT.mkdir(parents=True, exist_ok=True)
S = requests.Session()
S.headers.update({"User-Agent": "AcademicResearchBot/2.1 (+https://github.com/chakubash/coalbot)", "Accept": "application/json"})
BASE = "https://api.hkma.gov.hk/public/market-data-and-statistics"
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
manifest: list[dict[str, Any]] = []


def request_json(url: str, params: dict[str, Any], attempts: int = 6) -> dict[str, Any]:
    last: Exception | None = None
    for i in range(attempts):
        try:
            r = S.get(url, params=params, timeout=(20, 180))
            r.raise_for_status()
            payload = r.json()
            if not payload.get("header", {}).get("success", False):
                raise RuntimeError(str(payload.get("header")))
            return payload
        except Exception as exc:
            last = exc
            pause = min(30, 2 ** i)
            print(f"retry {i + 1}/{attempts}: {url} {params}: {exc}; pause={pause}", flush=True)
            time.sleep(pause)
    raise RuntimeError(f"request failed: {last}")


def fetch(name: str, endpoint: str, start: str, end: str, extra: dict[str, Any] | None = None) -> pd.DataFrame:
    url = f"{BASE}/{endpoint}"
    params: dict[str, Any] = {
        "choose": "end_of_month",
        "from": start,
        "to": end,
        "sortby": "end_of_month",
        "sortorder": "asc",
        "pagesize": 1000,
        "offset": 0,
    }
    if extra:
        params.update(extra)
    payload = request_json(url, params)
    records = payload.get("result", {}).get("records", []) or []
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    (OUT / f"{name}.json").write_bytes(raw)
    df = pd.DataFrame(records)
    if df.empty:
        raise ValueError(f"empty endpoint: {name}")
    raw_n = len(df)
    df["end_of_month"] = df["end_of_month"].astype(str)
    invalid = df.loc[~df["end_of_month"].map(lambda x: bool(MONTH_RE.match(x))), "end_of_month"].tolist()
    df = df[df["end_of_month"].map(lambda x: bool(MONTH_RE.match(x)))].copy()
    df = df.drop_duplicates(subset=["end_of_month"], keep="last").sort_values("end_of_month").reset_index(drop=True)
    if df.empty:
        raise ValueError(f"no valid monthly rows: {name}")
    df.to_csv(OUT / f"{name}.csv", index=False)
    manifest.append({
        "name": name,
        "url": url,
        "params": json.dumps(params, ensure_ascii=False),
        "raw_records": raw_n,
        "valid_months": len(df),
        "invalid_dates": json.dumps(invalid, ensure_ascii=False),
        "first": df["end_of_month"].iloc[0],
        "last": df["end_of_month"].iloc[-1],
        "sha256_json": hashlib.sha256(raw).hexdigest(),
        "retrieved_utc": datetime.now(timezone.utc).isoformat(),
    })
    print(f"{name}: raw={raw_n}, valid={len(df)}, {df['end_of_month'].iloc[0]}..{df['end_of_month'].iloc[-1]}, invalid={invalid}", flush=True)
    return df


def safe_fetch(*args: Any, **kwargs: Any) -> None:
    name = str(args[0]) if args else str(kwargs.get("name"))
    try:
        fetch(*args, **kwargs)
    except Exception as exc:
        manifest.append({"name": name, "status": "failed", "error": repr(exc), "retrieved_utc": datetime.now(timezone.utc).isoformat()})
        print(f"FAILED {name}: {exc}", flush=True)


def main() -> None:
    safe_fetch("banking_statistics", "monthly-statistical-bulletin/financial/banking-statistics", "1997-01", "2026-06")
    safe_fetch("monetary_statistics", "monthly-statistical-bulletin/financial/monetary-statistics", "1997-01", "2026-06")
    safe_fetch("loans_by_type_new", "monthly-statistical-bulletin/banking/loans-by-type-lb", "2020-01", "2026-06", {"segment": "new"})
    safe_fetch("loans_by_type_old", "monthly-statistical-bulletin/banking/loans-by-type-lb", "1997-01", "2019-12", {"segment": "old"})
    safe_fetch("mortgage_survey_new", "monthly-statistical-bulletin/banking/residential-mortgage-survey", "2017-01", "2026-06", {"segment": "new"})
    safe_fetch("mortgage_survey_old", "monthly-statistical-bulletin/banking/residential-mortgage-survey", "1997-01", "2019-12", {"segment": "old"})
    pd.DataFrame(manifest).to_csv(OUT / "manifest.csv", index=False)
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
