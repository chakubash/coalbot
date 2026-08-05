from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

OUT=Path('research_output/hkma_deposits_official'); OUT.mkdir(parents=True,exist_ok=True)
URL='https://api.hkma.gov.hk/public/market-data-and-statistics/monthly-statistical-bulletin/banking/customer-deposits-by-currency'
manifest=[]
for segment,start,end in [('old','1997-01','2019-12'),('new','2020-01','2026-06')]:
    params={'segment':segment,'choose':'end_of_month','from':start,'to':end,'sortby':'end_of_month','sortorder':'asc','pagesize':1000,'offset':0}
    r=requests.get(URL,params=params,headers={'User-Agent':'AcademicResearchBot/2.3'},timeout=(20,240)); r.raise_for_status()
    payload=r.json()
    if not payload.get('header',{}).get('success',False): raise RuntimeError(payload.get('header'))
    records=payload.get('result',{}).get('records',[]) or []
    df=pd.DataFrame(records).drop_duplicates('end_of_month',keep='last').sort_values('end_of_month')
    df.to_csv(OUT/f'deposits_{segment}.csv',index=False)
    (OUT/f'deposits_{segment}.json').write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
    rec={'segment':segment,'records':len(df),'first':df.end_of_month.iloc[0],'last':df.end_of_month.iloc[-1],'url':r.url,'retrieved_utc':datetime.now(timezone.utc).isoformat()}
    print(json.dumps(rec,ensure_ascii=False),flush=True); print(df.columns.tolist(),flush=True); manifest.append(rec)
pd.DataFrame(manifest).to_csv(OUT/'manifest.csv',index=False)
