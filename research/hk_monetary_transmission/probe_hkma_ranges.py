from __future__ import annotations

import json
from pathlib import Path

import requests

OUT = Path('research_output/hkma_probe')
OUT.mkdir(parents=True, exist_ok=True)
S = requests.Session()
S.headers.update({'User-Agent': 'AcademicResearchBot/1.2'})

BASE = 'https://api.hkma.gov.hk/public/market-data-and-statistics'
TESTS = [
    ('liq_from_to', f'{BASE}/daily-monetary-statistics/daily-figures-interbank-liquidity', {'from':'2022-01-01','to':'2022-01-31','offset':0}),
    ('liq_from_to_pagesize20', f'{BASE}/daily-monetary-statistics/daily-figures-interbank-liquidity', {'from':'2022-01-01','to':'2022-01-31','offset':0,'pagesize':20}),
    ('liq_from_to_pagesize100', f'{BASE}/daily-monetary-statistics/daily-figures-interbank-liquidity', {'from':'2022-01-01','to':'2022-01-31','offset':0,'pagesize':100}),
    ('hibor_from_to', f'{BASE}/monthly-statistical-bulletin/er-ir/hk-interbank-ir-daily', {'segment':'hibor.fixing','from':'2022-01-01','to':'2022-01-31','offset':0}),
    ('bank_from_to', f'{BASE}/monthly-statistical-bulletin/financial/banking-statistics', {'from':'2020-01','to':'2022-12','offset':0}),
    ('bank_date_from_to', f'{BASE}/monthly-statistical-bulletin/financial/banking-statistics', {'from':'2020-01-01','to':'2022-12-31','offset':0}),
]

rows=[]
for name,url,params in TESTS:
    rec={'name':name,'url':url,'params':params}
    try:
        r=S.get(url,params=params,timeout=45)
        rec['status_code']=r.status_code
        rec['final_url']=r.url
        rec['bytes']=len(r.content)
        rec['text_head']=r.text[:500]
        if r.ok:
            j=r.json()
            rec['success']=j.get('header',{}).get('success')
            rec['datasize']=j.get('result',{}).get('datasize')
            records=j.get('result',{}).get('records',[]) or []
            rec['n_records']=len(records)
            rec['first_record']=records[0] if records else None
            rec['last_record']=records[-1] if records else None
        else:
            rec['success']=False
    except Exception as exc:
        rec['error']=repr(exc)
    print(json.dumps(rec,ensure_ascii=False),flush=True)
    rows.append(rec)

(OUT/'probe_results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
