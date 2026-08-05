from __future__ import annotations
import gzip,hashlib,json,time
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlencode
import pandas as pd
import requests
OUT=Path('research/totals_audit');OUT.mkdir(parents=True,exist_ok=True)
S=requests.Session();S.headers.update({'User-Agent':'Mozilla/5.0','Accept':'application/json,text/plain,*/*'})
base='https://tradeidds.censtatd.gov.hk/api/get'
specs={
'A_import_origin_russia':{'ttype':'1','coclass':'C','co':'RU'},
'B_import_consignment_russia':{'ttype':'1','ccclass':'C','cc':'RU'},
'C_domestic_exports_russia':{'ttype':'2','ccclass':'C','cc':'RU'},
'D_re_exports_russia':{'ttype':'3','ccclass':'C','cc':'RU'},
'E_total_exports_russia':{'ttype':'4','ccclass':'C','cc':'RU'},
'G_hk_world_imports':{'ttype':'1'},
}
rows=[];manifest=[]
for extract,p in specs.items():
 params={'lang':'EN','sv':'VCm','freq':'M','period':'201201,202606',**p}
 url=base+'?'+urlencode(params)
 last=None
 for a in range(8):
  try:
   r=S.get(url,timeout=300,allow_redirects=True,verify=False);j=r.json();status=j.get('header',{}).get('status',{})
   if r.status_code==200 and status.get('name')=='Success':break
   last=(r.status_code,status);time.sleep(10+5*a)
  except Exception as e:last=repr(e);time.sleep(5+5*a)
 else:raise RuntimeError(f'{extract}: {last}')
 raw=OUT/f'{extract}.json.gz'
 with gzip.open(raw,'wb',compresslevel=9) as g:g.write(r.content)
 token=r.url.split('/api/')[1].split('/')[0] if '/api/' in r.url else hashlib.sha256(url.encode()).hexdigest()[:32]
 for x in j.get('dataSet',[]):
  val=pd.to_numeric(str(x.get('figure','')).replace(',',''),errors='coerce')
  rows.append({'extract_id':extract,'period':pd.to_datetime(str(x['period']),format='%Y%m'),'total_hkd':float(val)*1000 if pd.notna(val) else 0.0,'record_status':'reported' if pd.notna(val) else 'verified_zero','query_id':token})
 manifest.append({'extract_id':extract,'requested_url':url,'final_url':r.url,'query_id':token,'record_count':len(j.get('dataSet',[])),'sha256':hashlib.sha256(r.content).hexdigest(),'retrieved_at_utc':datetime.now(timezone.utc).isoformat(),'title':j.get('header',{}).get('title')})
 time.sleep(1)
pd.DataFrame(rows).to_csv(OUT/'official_monthly_totals.csv',index=False)
(OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(pd.DataFrame(rows).groupby('extract_id').agg(n=('period','size'),start=('period','min'),end=('period','max'),total=('total_hkd','sum')))
