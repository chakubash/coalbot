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
    "User-Agent": "AcademicResearchBot/1.0 (+https://github.com/chakubash/coalbot)",
    "Accept": "application/json,text/csv,text/plain,*/*",
})

MANIFEST: list[dict[str, Any]] = []


def log(msg: str) -> None:
    print(msg, flush=True)


def save_manifest(name: str, url: str, status: str, rows: int | None = None, note: str = "") -> None:
    MANIFEST.append({
        "name": name,
        "url": url,
        "status": status,
        "rows": rows,
        "note": note,
        "retrieved_utc": datetime.now(timezone.utc).isoformat(),
    })


def request(url: str, timeout: int = 90) -> requests.Response:
    last: Exception | None = None
    for attempt in range(5):
        try:
            r = SESSION.get(url, timeout=timeout)
            r.raise_for_status()
            return r
        except Exception as exc:  # pragma: no cover - network retries
            last = exc
            sleep_s = 2 ** attempt
            log(f"retry {attempt + 1}/5 for {url}: {exc}; sleep={sleep_s}s")
            time.sleep(sleep_s)
    raise RuntimeError(f"Failed to download {url}: {last}")


def fetch_hkma(name: str, base_url: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
    params = dict(params or {})
    pagesize = 1000
    offset = 0
    records: list[dict[str, Any]] = []
    while True:
        q = dict(params)
        q.update({"pagesize": pagesize, "offset": offset})
        r = SESSION.get(base_url, params=q, timeout=90)
        r.raise_for_status()
        payload = r.json()
        result = payload.get("result", {})
        page = result.get("records", []) or []
        if not isinstance(page, list):
            raise ValueError(f"Unexpected HKMA response for {name}: records not a list")
        records.extend(page)
        log(f"HKMA {name}: offset={offset}, page={len(page)}, total={len(records)}")
        if len(page) < pagesize:
            break
        offset += pagesize
        if offset > 200000:
            raise RuntimeError(f"Pagination guard triggered for {name}")
        time.sleep(0.15)
    df = pd.DataFrame(records)
    path = RAW / f"{name}.csv"
    df.to_csv(path, index=False)
    save_manifest(name, base_url, "ok", len(df), json.dumps(params, ensure_ascii=False))
    return df


def fetch_binary_or_text(name: str, url: str, suffix: str) -> Path:
    r = request(url)
    path = RAW / f"{name}{suffix}"
    path.write_bytes(r.content)
    save_manifest(name, url, "ok", None, f"bytes={len(r.content)}")
    log(f"downloaded {name}: {len(r.content)} bytes")
    return path


def fetch_fred(series_id: str) -> None:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    try:
        r = request(url)
        text = r.text
        if "DATE" not in text.upper() or len(text) < 20:
            raise ValueError("FRED response does not look like CSV")
        path = RAW / f"fred_{series_id}.csv"
        path.write_text(text, encoding="utf-8")
        rows = max(0, text.count("\n") - 1)
        save_manifest(f"fred_{series_id}", url, "ok", rows)
        log(f"FRED {series_id}: rows~{rows}")
    except Exception as exc:
        save_manifest(f"fred_{series_id}", url, "failed", None, repr(exc))
        log(f"FRED {series_id} FAILED: {exc}")


def fetch_yfinance(ticker: str, file_stub: str) -> None:
    try:
        import yfinance as yf
        df = yf.download(
            ticker,
            start="2004-12-01",
            end="2026-08-06",
            auto_adjust=False,
            progress=False,
            threads=False,
            timeout=60,
        )
        if df is None or df.empty:
            raise ValueError("empty yfinance response")
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = ["__".join(str(x) for x in col if str(x)) for col in df.columns]
        df.reset_index().to_csv(RAW / f"market_{file_stub}.csv", index=False)
        save_manifest(f"market_{file_stub}", f"yfinance:{ticker}", "ok", len(df))
        log(f"market {ticker}: {len(df)} rows")
    except Exception as exc:
        save_manifest(f"market_{file_stub}", f"yfinance:{ticker}", "failed", None, repr(exc))
        log(f"market {ticker} FAILED: {exc}")


def main() -> int:
    hkma_base = "https://api.hkma.gov.hk/public/market-data-and-statistics"

    hkma_specs = [
        ("hkma_interbank_liquidity_daily", f"{hkma_base}/daily-monetary-statistics/daily-figures-interbank-liquidity", {}),
        ("hkma_monetary_base_daily", f"{hkma_base}/daily-monetary-statistics/daily-figures-monetary-base", {}),
        ("hkma_hibor_fixing_daily", f"{hkma_base}/monthly-statistical-bulletin/er-ir/hk-interbank-ir-daily", {"segment": "hibor.fixing"}),
        ("hkma_banking_statistics_monthly", f"{hkma_base}/monthly-statistical-bulletin/financial/banking-statistics", {}),
        ("hkma_monetary_statistics_monthly", f"{hkma_base}/monthly-statistical-bulletin/financial/monetary-statistics", {}),
        ("hkma_loans_by_type_lb_new", f"{hkma_base}/monthly-statistical-bulletin/banking/loans-by-type-lb", {"segment": "new"}),
        ("hkma_loans_by_type_lb_old", f"{hkma_base}/monthly-statistical-bulletin/banking/loans-by-type-lb", {"segment": "old"}),
        ("hkma_mortgage_survey_new", f"{hkma_base}/monthly-statistical-bulletin/banking/residential-mortgage-survey", {"segment": "new"}),
        ("hkma_mortgage_survey_old", f"{hkma_base}/monthly-statistical-bulletin/banking/residential-mortgage-survey", {"segment": "old"}),
        ("hkma_loans_by_sector_ais_new", f"{hkma_base}/monthly-statistical-bulletin/banking/loans-by-sector-ais", {"segment": "new"}),
        ("hkma_loans_by_sector_ais_old", f"{hkma_base}/monthly-statistical-bulletin/banking/loans-by-sector-ais", {"segment": "old"}),
    ]

    for name, url, params in hkma_specs:
        try:
            fetch_hkma(name, url, params)
        except Exception as exc:
            save_manifest(name, url, "failed", None, repr(exc))
            log(f"HKMA {name} FAILED: {exc}")

    downloads = [
        ("rvd_private_domestic_price_index", "https://www.rvd.gov.hk/datagovhk/1.4M.csv", ".csv"),
        ("csd_gdp_real_growth", "https://www.censtatd.gov.hk/en/web_table.html?id=310-30001&full_series=1&download_csv=1", ".csv"),
        ("csd_unemployment", "https://www.censtatd.gov.hk/en/web_table.html?id=210-06103&full_series=1&download_csv=1", ".csv"),
        ("csd_cpi", "https://www.censtatd.gov.hk/en/web_table.html?id=510-60001&full_series=1&download_csv=1", ".csv"),
        ("csd_retail_sales", "https://www.censtatd.gov.hk/en/web_table.html?id=620-67001&full_series=1&download_csv=1", ".csv"),
        ("jk_fomc_shocks_event", "https://raw.githubusercontent.com/marekjarocinski/jkshocks_update_fed/main/shocks_fed_jk_t.csv", ".csv"),
        ("jk_fomc_shocks_monthly", "https://raw.githubusercontent.com/marekjarocinski/jkshocks_update_fed/main/shocks_fed_jk_m.csv", ".csv"),
        ("jk_readme", "https://raw.githubusercontent.com/marekjarocinski/jkshocks_update_fed/main/README.md", ".md"),
    ]
    for name, url, suffix in downloads:
        try:
            fetch_binary_or_text(name, url, suffix)
        except Exception as exc:
            save_manifest(name, url, "failed", None, repr(exc))
            log(f"download {name} FAILED: {exc}")

    # Official Federal Reserve / FRED series and globally used controls.
    fred_series = [
        "DFF", "EFFR", "DFEDTARU", "DFEDTARL", "SOFR",
        "DEXHKUS", "DEXCHUS", "DTWEXBGS", "DGS2", "DGS10",
        "VIXCLS", "SP500", "NASDAQCOM",
    ]
    for sid in fred_series:
        fetch_fred(sid)

    # Market-price series. These are auxiliary commercial-market data, not official statistics.
    for ticker, stub in [
        ("^HSI", "hsi"),
        ("^HSCE", "hscei"),
        ("000001.SS", "shanghai_composite"),
        ("CNH=X", "cnh_usd"),
        ("HKD=X", "hkd_usd_yahoo"),
    ]:
        fetch_yfinance(ticker, stub)

    manifest_path = OUT / "source_manifest.csv"
    pd.DataFrame(MANIFEST).to_csv(manifest_path, index=False)
    (OUT / "source_manifest.json").write_text(
        json.dumps(MANIFEST, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    failed = [x for x in MANIFEST if x["status"] != "ok"]
    log(f"completed: {len(MANIFEST)} sources, failed={len(failed)}")
    if failed:
        log(json.dumps(failed, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
