from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

OUT = Path('research_output/hkma_banking_only')
OUT.mkdir(parents=True, exist_ok=True)
url = 'https://api.hkma.gov.hk/public/market-data-and-statistics/monthly-statistical-bulletin/financial/banking-statistics'
params = {
    'choose': 'end_of_month',
    'from': '1997-01',
    'to': '2026-06',
    'sortby': 'end_of_month',
    'sortorder': 'asc',
    'pagesize': 1000,
    'offset': 0,
}
r = requests.get(url, params=params, headers={'User-Agent':'AcademicResearchBot/2.2'}, timeout=(20,240))
r.raise_for_status()
payload = r.json()
if not payload.get('header',{}).get('success',False):
    raise RuntimeError(payload.get('header'))
records = payload.get('result',{}).get('records',[]) or []
(OUT/'banking_statistics.json').write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
df = pd.DataFrame(records)
pattern = re.compile(r'^\d{4}-(0[1-9]|1[0-2])$')
invalid = df.loc[~df['end_of_month'].astype(str).map(lambda x: bool(pattern.match(x))),'end_of_month'].astype(str).tolist()
df = df[df['end_of_month'].astype(str).map(lambda x: bool(pattern.match(x)))].copy()
df = df.drop_duplicates('end_of_month',keep='last').sort_values('end_of_month')
df.to_csv(OUT/'banking_statistics.csv',index=False)
manifest = {
    'url':url,'params':params,'raw_records':len(records),'valid_months':len(df),
    'invalid_dates':invalid,'first':df['end_of_month'].iloc[0],'last':df['end_of_month'].iloc[-1],
    'retrieved_utc':datetime.now(timezone.utc).isoformat(),
}
(OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(manifest,ensure_ascii=False),flush=True)
print(df.columns.tolist(),flush=True)
