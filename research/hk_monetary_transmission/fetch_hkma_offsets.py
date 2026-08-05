from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

OUT = Path('research_output/hkma_offsets')
RAW = OUT / 'raw'
RAW.mkdir(parents=True, exist_ok=True)
BASE = 'https://api.hkma.gov.hk/public/market-data-and-statistics'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 AcademicResearch/1.0',
    'Accept': 'application/json',
}

SPECS = [
    {
        'name': 'hkma_interbank_liquidity_daily_full',
        'url': f'{BASE}/daily-monetary-statistics/daily-figures-interbank-liquidity',
        'date_field': 'end_of_date',
        'extra': {},
        'max_offset': 9000,
    },
    {
        'name': 'hkma_monetary_base_daily_full',
        'url': f'{BASE}/daily-monetary-statistics/daily-figures-monetary-base',
        'date_field': 'end_of_date',
        'extra': {},
        'max_offset': 9000,
    },
    {
        'name': 'hkma_hibor_fixing_daily_full',
        'url': f'{BASE}/monthly-statistical-bulletin/er-ir/hk-interbank-ir-daily',
        'date_field': 'end_of_day',
        'extra': {'segment': 'hibor.fixing'},
        'max_offset': 10000,
    },
]


def fetch_page(spec: dict[str, Any], offset: int) -> tuple[int, list[dict[str, Any]], str | None]:
    params = {
        **spec['extra'],
        'pagesize': 100,
        'offset': offset,
    }
    last = None
    for attempt in range(5):
        try:
            with requests.Session() as s:
                r = s.get(spec['url'], params=params, headers=HEADERS, timeout=60)
                r.raise_for_status()
                payload = r.json()
                if payload.get('header', {}).get('success') is False:
                    raise RuntimeError(str(payload.get('header')))
                result = payload.get('result', {})
                records = result.get('records', []) or []
                if not isinstance(records, list):
                    raise TypeError('records is not a list')
                return offset, records, None
        except Exception as exc:
            last = repr(exc)
            time.sleep(1.5 * (attempt + 1))
    return offset, [], last


def fetch_spec(spec: dict[str, Any]) -> dict[str, Any]:
    offsets = list(range(0, int(spec['max_offset']) + 1, 100))
    pages: dict[int, list[dict[str, Any]]] = {}
    errors: dict[int, str] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fetch_page, spec, off): off for off in offsets}
        for fut in as_completed(futures):
            off, records, error = fut.result()
            if error:
                errors[off] = error
                print(f"{spec['name']} offset={off} FAILED: {error}", flush=True)
            else:
                pages[off] = records
                print(f"{spec['name']} offset={off}: {len(records)}", flush=True)

    # Retry failed pages once sequentially.
    for off in sorted(errors):
        off2, records, error = fetch_page(spec, off)
        if not error:
            pages[off2] = records
            del errors[off]
            print(f"{spec['name']} offset={off} RECOVERED: {len(records)}", flush=True)

    records_all: list[dict[str, Any]] = []
    for off in sorted(pages):
        records_all.extend(pages[off])
    df = pd.DataFrame(records_all).drop_duplicates()
    date_field = spec['date_field']
    if date_field in df.columns:
        df[date_field] = pd.to_datetime(df[date_field], errors='coerce')
        df = df.sort_values(date_field).reset_index(drop=True)
    df.to_csv(RAW / f"{spec['name']}.csv", index=False)

    return {
        'name': spec['name'],
        'url': spec['url'],
        'rows': len(df),
        'min_date': str(df[date_field].min()) if date_field in df.columns and not df.empty else None,
        'max_date': str(df[date_field].max()) if date_field in df.columns and not df.empty else None,
        'nonempty_pages': sum(bool(v) for v in pages.values()),
        'empty_pages': sum(not bool(v) for v in pages.values()),
        'failed_offsets': errors,
        'retrieved_utc': datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    manifest = []
    for spec in SPECS:
        manifest.append(fetch_spec(spec))
    pd.DataFrame([{k: v if not isinstance(v, dict) else json.dumps(v) for k, v in x.items()} for x in manifest]).to_csv(OUT / 'manifest.csv', index=False)
    (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
