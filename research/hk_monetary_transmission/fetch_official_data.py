from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

OUT = Path("research_output/hk_monetary_transmission")
RAW = OUT / "raw"
RAW.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "AcademicResearchBot/2.0 (+https://github.com/chakubash/coalbot)",
    "Accept": "application/json,text/csv,text/plain,*/*",
})
MANIFEST: list[dict[str, Any]] = []


def log(message: str) -> None:
    print(message, flush=True)


def record(name: str, url: str, status: str, rows: int | None = None, note: str = "") -> None:
    MANIFEST.append({
        "name": name,
        "url": url,
        "status": status,
        "rows": rows,
        "note": note,
        "retrieved_utc": datetime.now(timezone.utc).isoformat(),
    })


def get(url: str, *, params: dict[str, Any] | None = None, timeout: int = 30, attempts: int = 4) -> requests.Response:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            response = SESSION.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            return response
        except Exception as exc:  # pragma: no cover - network retry path
            last = exc
            delay = min(10, 1.5 ** attempt)
            log(f"retry {attempt + 1}/{attempts}: {url} params={params}: {exc}")
            time.sleep(delay)
    raise RuntimeError(f"download failed: {url}; params={params}; last={last}")


def download(name: str, url: str, suffix: str = ".csv") -> Path:
    try:
        response = get(url, timeout=45, attempts=4)
        path = RAW / f"{name}{suffix}"
        path.write_bytes(response.content)
        record(name, url, "ok", None, f"bytes={len(response.content)}")
        log(f"downloaded {name}: {len(response.content)} bytes")
        return path
    except Exception as exc:
        record(name, url, "failed", None, repr(exc))
        log(f"FAILED {name}: {exc}")
        return RAW / f"{name}{suffix}"


def hkma_paged(
    name: str,
    url: str,
    *,
    fixed_params: dict[str, Any] | None = None,
    page_size: int = 20,
    max_pages: int = 300,
) -> pd.DataFrame:
    fixed_params = dict(fixed_params or {})
    rows: list[dict[str, Any]] = []
    seen_pages: set[str] = set()
    status = "ok"
    note = ""
    try:
        for page_no in range(max_pages):
            offset = page_no * page_size
            params = {**fixed_params, "pagesize": page_size, "offset": offset}
            try:
                response = get(url, params=params, timeout=35, attempts=4)
            except Exception:
                # Some HKMA endpoints are more stable when the default page size is used.
                params = {**fixed_params, "offset": offset}
                response = get(url, params=params, timeout=35, attempts=4)
            payload = response.json()
            if not payload.get("header", {}).get("success", False):
                raise ValueError(payload.get("header"))
            page = payload.get("result", {}).get("records", []) or []
            if not isinstance(page, list):
                raise TypeError("HKMA records is not a list")
            if not page:
                break
            signature = json.dumps(page, sort_keys=True, ensure_ascii=False)
            if signature in seen_pages:
                log(f"{name}: repeated page at offset {offset}; stopping")
                break
            seen_pages.add(signature)
            rows.extend(page)
            log(f"{name}: page={page_no + 1}, offset={offset}, received={len(page)}, accumulated={len(rows)}")
            if len(page) < page_size:
                break
            time.sleep(0.12)
        frame = pd.DataFrame(rows).drop_duplicates().reset_index(drop=True)
        if frame.empty:
            raise ValueError("empty HKMA dataset")
        frame.to_csv(RAW / f"{name}.csv", index=False)
        note = json.dumps(fixed_params, ensure_ascii=False)
        record(name, url, status, len(frame), note)
        return frame
    except Exception as exc:
        status = "failed"
        note = repr(exc)
        record(name, url, status, len(rows) if rows else None, note)
        log(f"FAILED HKMA {name}: {exc}")
        if rows:
            frame = pd.DataFrame(rows).drop_duplicates().reset_index(drop=True)
            frame.to_csv(RAW / f"{name}_partial.csv", index=False)
            return frame
        return pd.DataFrame()


def fetch_fred(series_id: str) -> None:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    try:
        response = get(url, timeout=30, attempts=3)
        text = response.text
        if "DATE" not in text.upper() or len(text) < 20:
            raise ValueError("response is not a FRED CSV")
        path = RAW / f"fred_{series_id}.csv"
        path.write_text(text, encoding="utf-8")
        record(f"fred_{series_id}", url, "ok", max(0, text.count("\n") - 1))
    except Exception as exc:
        record(f"fred_{series_id}", url, "failed", None, repr(exc))
        log(f"FAILED FRED {series_id}: {exc}")


def fetch_market(ticker: str, stub: str) -> None:
    try:
        import yfinance as yf

        frame = yf.download(
            ticker,
            start="2004-12-01",
            end="2026-08-06",
            auto_adjust=False,
            progress=False,
            threads=False,
            timeout=35,
        )
        if frame is None or frame.empty:
            raise ValueError("empty market series")
        if isinstance(frame.columns, pd.MultiIndex):
            frame.columns = ["__".join(str(x) for x in col if str(x)) for col in frame.columns]
        frame.reset_index().to_csv(RAW / f"market_{stub}.csv", index=False)
        record(f"market_{stub}", f"yfinance:{ticker}", "ok", len(frame))
    except Exception as exc:
        record(f"market_{stub}", f"yfinance:{ticker}", "failed", None, repr(exc))
        log(f"FAILED market {ticker}: {exc}")


def main() -> int:
    hkma = "https://api.hkma.gov.hk/public/market-data-and-statistics"

    # Pinned, reproducible daily panel assembled from HKMA, HKAB and FRED APIs.
    # It is retained as a transport mirror; primary-source definitions remain HKMA/HKAB/FRED.
    download(
        "daily_hkma_hkab_fred_mirror_2005_2025",
        "https://raw.githubusercontent.com/RianMehta21/hkd-peg-analysis/15e35810f4394c52492a2d8c0f9fc2e9b15b116d/data/master.csv",
    )
    download(
        "daily_mirror_readme",
        "https://raw.githubusercontent.com/RianMehta21/hkd-peg-analysis/15e35810f4394c52492a2d8c0f9fc2e9b15b116d/readme.md",
        ".md",
    )
    download(
        "daily_mirror_fetch_liquidity_code",
        "https://raw.githubusercontent.com/RianMehta21/hkd-peg-analysis/15e35810f4394c52492a2d8c0f9fc2e9b15b116d/scripts/get_liquidity.py",
        ".py",
    )

    monthly_specs = [
        ("hkma_monetary_statistics_monthly", f"{hkma}/monthly-statistical-bulletin/financial/monetary-statistics", {}),
        ("hkma_banking_statistics_monthly", f"{hkma}/monthly-statistical-bulletin/financial/banking-statistics", {}),
        ("hkma_economic_statistics_monthly", f"{hkma}/monthly-statistical-bulletin/financial/economic-statistics", {}),
        ("hkma_loans_by_type_lb_new", f"{hkma}/monthly-statistical-bulletin/banking/loans-by-type-lb", {"segment": "new"}),
        ("hkma_loans_by_type_lb_old", f"{hkma}/monthly-statistical-bulletin/banking/loans-by-type-lb", {"segment": "old"}),
        ("hkma_mortgage_survey_new", f"{hkma}/monthly-statistical-bulletin/banking/residential-mortgage-survey", {"segment": "new"}),
        ("hkma_mortgage_survey_old", f"{hkma}/monthly-statistical-bulletin/banking/residential-mortgage-survey", {"segment": "old"}),
    ]
    for name, url, params in monthly_specs:
        hkma_paged(name, url, fixed_params=params, page_size=20, max_pages=40)

    # Latest official daily pages are archived for date-by-date validation of the mirror.
    hkma_paged(
        "hkma_interbank_liquidity_latest",
        f"{hkma}/daily-monetary-statistics/daily-figures-interbank-liquidity",
        page_size=20,
        max_pages=2,
    )
    hkma_paged(
        "hkma_hibor_fixing_latest",
        f"{hkma}/monthly-statistical-bulletin/er-ir/hk-interbank-ir-daily",
        fixed_params={"segment": "hibor.fixing"},
        page_size=20,
        max_pages=2,
    )

    download("rvd_private_domestic_price_index", "https://www.rvd.gov.hk/datagovhk/1.4M.csv")
    download(
        "jk_fomc_shocks_event",
        "https://raw.githubusercontent.com/marekjarocinski/jkshocks_update_fed/main/shocks_fed_jk_t.csv",
    )
    download(
        "jk_fomc_shocks_monthly",
        "https://raw.githubusercontent.com/marekjarocinski/jkshocks_update_fed/main/shocks_fed_jk_m.csv",
    )
    download(
        "jk_readme",
        "https://raw.githubusercontent.com/marekjarocinski/jkshocks_update_fed/main/README.md",
        ".md",
    )

    fred_series = [
        "DFF", "EFFR", "DFEDTARU", "DFEDTARL", "SOFR", "DEXHKUS", "DEXCHUS",
        "DTWEXBGS", "DGS2", "DGS10", "VIXCLS", "SP500", "NASDAQCOM",
        "CHNPRINTO01IXPYM", "CHNCPIALLMINMEI", "CHNLOLITONOSTSAM",
        "IR3TIB01CNM156N", "INTDSRCNM193N",
    ]
    for series_id in fred_series:
        fetch_fred(series_id)

    for ticker, stub in [
        ("^HSI", "hsi"),
        ("^HSCE", "hscei"),
        ("000001.SS", "shanghai_composite"),
        ("CNH=X", "cnh_per_usd"),
        ("CNY=X", "cny_per_usd"),
        ("HKD=X", "hkd_per_usd_yahoo"),
    ]:
        fetch_market(ticker, stub)

    manifest = pd.DataFrame(MANIFEST)
    manifest.to_csv(OUT / "source_manifest.csv", index=False)
    (OUT / "source_manifest.json").write_text(
        json.dumps(MANIFEST, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    failures = manifest.loc[manifest["status"] != "ok"]
    log(f"sources={len(manifest)}, failures={len(failures)}")
    if not failures.empty:
        log(failures[["name", "note"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
