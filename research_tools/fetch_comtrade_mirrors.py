from __future__ import annotations
import hashlib, json, pathlib, time
from datetime import datetime, timezone
import requests, pandas as pd
OUT=pathlib.Path('acquired/mirrors'); RAW=OUT/'raw_queries'; RAW.mkdir(parents=True,exist_ok=True)
BASE='https://comtradeapi.un.org/public/v1/preview/C'
s=requests.Session(); s.headers.update({'User-Agent':'reproducible-academic-client/1.0','Accept':'application/json'})

def classification(year): return 'H4' if year<=2016 else ('H5' if year<=2021 else 'H6')
def sha(b): return hashlib.sha256(b).hexdigest()
def call(freq,cl,period,flow,cmd='AG4'):
 u=f'{BASE}/{freq}/{cl}'
 params={'period':period,'reporterCode':'643','flowCode':flow,'partnerCode':'344','partner2Code':'0','cmdCode':cmd,'maxRecords':'500'}
 for a in range(20):
  r=s.get(u,params=params,timeout=180)
  if r.status_code==429:
   wait=float(r.headers.get('Retry-After') or min(90,5*(a+1))); time.sleep(wait+0.5); continue
  if r.status_code>=500: time.sleep(min(60,4*(a+1))); continue
  r.raise_for_status(); j=r.json(); time.sleep(1.35); return r,j,params
 raise RuntimeError(f'Comtrade retries exhausted {freq} {period} {flow}')

log=[]; outputs={'J_mirror_ru_exports':[],'K_mirror_ru_imports':[]}; incomplete=[]
for year in range(2012,2027):
 cl=classification(year)
 last=6 if year==2026 else 12
 for month in range(1,last+1):
  per=f'{year}{month:02d}'
  for flow,eid in [('X','J_mirror_ru_exports'),('M','K_mirror_ru_imports')]:
   r,j,p=call('M',cl,per,flow)
   b=r.content; fn=f'{eid}_{per}_{cl}.json'; (RAW/fn).write_bytes(b)
   data=j.get('data',[]) if isinstance(j,dict) else []; count=j.get('count',len(data)) if isinstance(j,dict) else None
   entry={'extract_id':eid,'frequency':'M','period':per,'classification':cl,'params':p,'requested_url':r.url,'status':r.status_code,'count':count,'records':len(data),'sha256':sha(b),'file':fn}
   if len(data)>=500 or count==500:
    entry['complete']=False; incomplete.append(entry)
   else:
    entry['complete']=True
    for x in data: x['_extract_id']=eid; x['_classification_requested']=cl; x['_frequency_requested']='M'
    outputs[eid].extend(data)
   log.append(entry)
# Annual supplemental mirror queries through 2025.
annual=[]
for year in range(2012,2026):
 cl=classification(year)
 for flow,eid in [('X','J_mirror_ru_exports'),('M','K_mirror_ru_imports')]:
  r,j,p=call('A',cl,str(year),flow); b=r.content; fn=f'{eid}_{year}_{cl}_annual.json'; (RAW/fn).write_bytes(b); data=j.get('data',[]); count=j.get('count',len(data))
  complete=not (len(data)>=500 or count==500)
  for x in data: x['_extract_id']=eid; x['_classification_requested']=cl; x['_frequency_requested']='A'
  if complete: annual.extend(data)
  log.append({'extract_id':eid,'frequency':'A','period':str(year),'classification':cl,'params':p,'requested_url':r.url,'status':r.status_code,'count':count,'records':len(data),'complete':complete,'sha256':sha(b),'file':fn})
for eid,rows in outputs.items():
 df=pd.DataFrame(rows)
 if not df.empty:
  cols=[c for c in ['period','cmdCode','flowCode','reporterCode','partnerCode','primaryValue','netWgt','qty','qtyUnitAbbr','classificationCode','isReported','isAggregate','publicationDate'] if c in df]
  key=[c for c in ['period','cmdCode','flowCode','reporterCode','partnerCode','partner2Code','customsCode','motCode'] if c in df]
  if key and df.duplicated(key,keep=False).any(): raise RuntimeError(f'Duplicate Comtrade records for {eid}')
  df=df.sort_values([c for c in ['period','cmdCode'] if c in df])
 df.to_csv(OUT/f'{eid}.csv',index=False)
 meta={'extract_id':eid,'source':'United Nations Comtrade public API preview endpoint','reporter':'Russian Federation (643)','partner':'Hong Kong SAR, China (344)','frequency':'monthly','period_requested':'2012-01/2026-06','classification_rule':'H4 through 2016, H5 2017-2021, H6 2022 onward','completeness_rule':'A response is accepted only when returned record count is below the official 500-record preview ceiling; 500-record responses are excluded as truncated. Missing reporter submissions remain missing, not zero.','records':len(df),'nonempty_months':int(df['period'].astype(str).nunique()) if not df.empty and 'period' in df else 0,'truncated_queries':sum(1 for x in incomplete if x['extract_id']==eid),'csv_sha256':hashlib.sha256((OUT/f'{eid}.csv').read_bytes()).hexdigest(),'retrieved_at_utc':datetime.now(timezone.utc).isoformat()}
 (OUT/f'{eid}.metadata.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
pd.DataFrame(annual).to_csv(OUT/'mirror_annual_supplement.csv',index=False)
(OUT/'mirror_query_log.json').write_text(json.dumps(log,ensure_ascii=False,indent=2),encoding='utf-8'); (OUT/'mirror_incomplete_queries.json').write_text(json.dumps(incomplete,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'monthly':{k:len(v) for k,v in outputs.items()},'annual':len(annual),'incomplete':len(incomplete),'queries':len(log)},ensure_ascii=False,indent=2))
