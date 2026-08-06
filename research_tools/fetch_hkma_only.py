from __future__ import annotations
import hashlib,json,pathlib,time
from datetime import datetime,timezone
import requests,pandas as pd
OUT=pathlib.Path('acquired/hkma'); OUT.mkdir(parents=True,exist_ok=True)
URL='https://api.hkma.gov.hk/public/market-data-and-statistics/monthly-statistical-bulletin/er-ir/er-eeri-periodaverage'
s=requests.Session(); s.headers.update({'User-Agent':'reproducible-academic-client/1.0'})
pages=[]; records=[]; offset=0; page_size=100
for page_no in range(50):
 for a in range(15):
  try:
   r=s.get(URL,params={'offset':offset,'pagesize':page_size},timeout=180)
   if r.status_code in (429,500,502,503,504): time.sleep(min(90,4*(a+1))); continue
   r.raise_for_status(); j=r.json(); break
  except Exception:
   if a==14: raise
   time.sleep(min(90,4*(a+1)))
 if not j.get('header',{}).get('success'): raise RuntimeError(j.get('header'))
 part=j.get('result',{}).get('records',[]); pages.append({'offset':offset,'payload':j}); records.extend(part)
 if len(part)<page_size: break
 offset+=len(part)
raw=OUT/'I_hkma_hkd_usd.raw.json'; raw.write_text(json.dumps(pages,ensure_ascii=False,indent=2),encoding='utf-8')
df=pd.DataFrame(records)
if not {'end_of_month','usd'}<=set(df.columns): raise RuntimeError(f'Unexpected fields {df.columns.tolist()}')
fx=df[['end_of_month','usd']].rename(columns={'end_of_month':'period','usd':'hkd_per_usd'})
fx['period']=fx['period'].astype(str).str[:7]; fx['hkd_per_usd']=pd.to_numeric(fx.hkd_per_usd,errors='raise')
fx=fx[(fx.period>='2012-01')&(fx.period<='2026-06')].sort_values('period').drop_duplicates('period',keep=False)
expected=set(pd.period_range('2012-01','2026-06',freq='M').astype(str)); missing=sorted(expected-set(fx.period))
if missing: raise RuntimeError(f'HKMA calendar incomplete: {missing[:20]}')
out=OUT/'I_hkma_hkd_usd.csv'; fx.to_csv(out,index=False)
def sha(p): return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
meta={'extract_id':'I_hkma_hkd_usd','source':'Hong Kong Monetary Authority','endpoint':URL,'definition':'Monthly period-average HKD per 1 USD','formula':'USD=HKD/hkd_per_usd','period':'2012-01/2026-06','api_pagination':'offset/pagesize; full series retrieved then filtered','pages':len(pages),'records':len(fx),'raw_sha256':sha(raw),'csv_sha256':sha(out),'retrieved_at_utc':datetime.now(timezone.utc).isoformat()}
(OUT/'I_hkma_hkd_usd.metadata.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(meta,ensure_ascii=False,indent=2))
