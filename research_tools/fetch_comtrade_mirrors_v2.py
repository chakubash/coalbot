from __future__ import annotations
import hashlib,json,pathlib,time
from datetime import datetime,timezone
import requests,pandas as pd
OUT=pathlib.Path('acquired/mirrors_v2'); RAW=OUT/'raw_queries'; RAW.mkdir(parents=True,exist_ok=True)
BASE='https://comtradeapi.un.org/public/v1/preview/C/M'
s=requests.Session(); s.headers.update({'User-Agent':'reproducible-academic-client/2.0','Accept':'application/json'})
def classification(year): return 'H4' if year<=2016 else ('H5' if year<=2021 else 'H6')
def sha(b): return hashlib.sha256(b).hexdigest()
query_counter=0; log=[]; incomplete=[]
def request(cl,periods,flow):
 global query_counter
 query_counter+=1; u=f'{BASE}/{cl}'; p={'period':','.join(periods),'reporterCode':'643','flowCode':flow,'partnerCode':'344','partner2Code':'0','cmdCode':'AG4','maxRecords':'500'}
 last=None
 for a in range(30):
  try:
   r=s.get(u,params=p,timeout=240); last=r
   if r.status_code==429:
    wait=float(r.headers.get('Retry-After') or min(180,10*(a+1))); time.sleep(wait+2); continue
   if r.status_code in (500,502,503,504): time.sleep(min(120,8*(a+1))); continue
   r.raise_for_status(); j=r.json(); time.sleep(4.2); return r,j,p
  except Exception:
   if a==29: break
   time.sleep(min(120,8*(a+1)))
 raise RuntimeError(f'Comtrade retries exhausted {cl} {periods[0]}..{periods[-1]} {flow}; status={None if last is None else last.status_code}')
def fetch_group(eid,cl,periods,flow,rows):
 try:
  r,j,p=request(cl,periods,flow)
 except Exception as e:
  if len(periods)>1:
   mid=len(periods)//2; fetch_group(eid,cl,periods[:mid],flow,rows); fetch_group(eid,cl,periods[mid:],flow,rows); return
  incomplete.append({'extract_id':eid,'period':periods[0],'classification':cl,'reason':repr(e)}); return
 data=j.get('data',[]) if isinstance(j,dict) else []; count=j.get('count',len(data)) if isinstance(j,dict) else None
 fn=f'{eid}_{periods[0]}_{periods[-1]}_{cl}_{query_counter:04d}.json'; (RAW/fn).write_bytes(r.content)
 entry={'extract_id':eid,'periods':periods,'classification':cl,'params':p,'requested_url':r.url,'status':r.status_code,'count':count,'records':len(data),'sha256':sha(r.content),'file':fn}
 if len(data)>=500 or count==500:
  entry['complete']=False; entry['action']='split' if len(periods)>1 else 'excluded_truncated_single_month'; log.append(entry)
  if len(periods)>1:
   mid=len(periods)//2; fetch_group(eid,cl,periods[:mid],flow,rows); fetch_group(eid,cl,periods[mid:],flow,rows)
  else: incomplete.append(entry)
  return
 entry['complete']=True; log.append(entry)
 for x in data:
  x['_extract_id']=eid; x['_classification_requested']=cl; x['_period_batch']=','.join(periods)
 rows.extend(data)
outputs={'J_mirror_ru_exports':[],'K_mirror_ru_imports':[]}
for year in range(2012,2027):
 cl=classification(year); last=6 if year==2026 else 12; periods=[f'{year}{m:02d}' for m in range(1,last+1)]
 for flow,eid in [('X','J_mirror_ru_exports'),('M','K_mirror_ru_imports')]: fetch_group(eid,cl,periods,flow,outputs[eid])
for eid,rows in outputs.items():
 df=pd.DataFrame(rows)
 if not df.empty:
  key=[c for c in ['period','cmdCode','flowCode','reporterCode','partnerCode','partner2Code','customsCode','motCode'] if c in df]
  if key and df.duplicated(key,keep=False).any(): raise RuntimeError(f'Duplicate records {eid}: {df.loc[df.duplicated(key,keep=False),key].head().to_dict("records")}')
  df=df.sort_values([c for c in ['period','cmdCode'] if c in df])
 path=OUT/f'{eid}.csv'; df.to_csv(path,index=False)
 meta={'extract_id':eid,'source':'United Nations Comtrade public API preview endpoint','reporter':'Russian Federation (643)','partner':'Hong Kong SAR, China (344)','frequency':'monthly','period_requested':'2012-01/2026-06','classification_rule':'H4 through 2016, H5 2017-2021, H6 2022 onward','completeness_rule':'Year batches are recursively split whenever the response reaches the 500-record preview ceiling; a single-month 500-row response is excluded as truncated. Missing reporter submissions remain missing, not zero.','records':len(df),'nonempty_months':int(df.period.astype(str).nunique()) if not df.empty and 'period' in df else 0,'incomplete_queries':sum(1 for x in incomplete if x.get('extract_id')==eid),'csv_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'retrieved_at_utc':datetime.now(timezone.utc).isoformat()}
 (OUT/f'{eid}.metadata.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'mirror_query_log.json').write_text(json.dumps(log,ensure_ascii=False,indent=2),encoding='utf-8'); (OUT/'mirror_incomplete_queries.json').write_text(json.dumps(incomplete,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'records':{k:len(v) for k,v in outputs.items()},'queries':query_counter,'incomplete':len(incomplete)},ensure_ascii=False,indent=2))
