from __future__ import annotations
import argparse, hashlib, json, pathlib, time, re
from datetime import datetime, timezone
from urllib.parse import urlencode
import requests
import pandas as pd

BASE='https://tradeidds.censtatd.gov.hk'
REF_BASE='https://comtradeapi.un.org/files/v1/app/reference'
START='201201'; END='202606'
CONFIG={
 'A_import_origin_russia': {'ttype':'1','coclass':'C','co':'RU'},
 'B_import_consignment_russia': {'ttype':'1','ccclass':'C','cc':'RU'},
 'C_domestic_exports_russia': {'ttype':'2','ccclass':'C','cc':'RU'},
 'D_re_exports_russia': {'ttype':'3','ccclass':'C','cc':'RU'},
 'E_total_exports_russia': {'ttype':'4','ccclass':'C','cc':'RU'},
 'G_hk_world_imports': {'ttype':'1'},
}

def sha(data:bytes)->str: return hashlib.sha256(data).hexdigest()
def chunks(xs,n):
 for i in range(0,len(xs),n): yield xs[i:i+n]

def official_codes(session:requests.Session,out:pathlib.Path):
 refs={}; all4=set()
 for rev in ('H4','H5','H6'):
  u=f'{REF_BASE}/{rev}.json'; r=session.get(u,timeout=180); r.raise_for_status()
  raw=r.content; (out/f'official_{rev}.json').write_bytes(raw)
  js=r.json(); rows=js['results']; refs[rev]=rows
  all4.update(str(x['id']).zfill(4) for x in rows if int(x.get('aggrlevel',-1))==4 and str(x.get('id','')).isdigit())
 return refs,sorted(all4)

class Client:
 def __init__(self):
  self.s=requests.Session(); self.s.headers.update({'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36','Accept':'application/json,text/html,*/*','Accept-Language':'en-US,en;q=0.9'})
  self.reset()
 def reset(self):
  self.s.cookies.clear(); r=self.s.get(BASE+'/',timeout=120,allow_redirects=True); r.raise_for_status()
 def request(self,params,max_attempts=14):
  req_url=BASE+'/api/get?'+urlencode(params,safe=',')
  for attempt in range(max_attempts):
   try:
    r=self.s.get(BASE+'/api/get',params=params,timeout=240,allow_redirects=True)
    r.raise_for_status(); js=r.json(); st=js.get('header',{}).get('status',{}); name=st.get('name')
    if name=='Success': return js,req_url,r.url
    msgs=' | '.join(map(str,st.get('message',[]) if isinstance(st.get('message'),list) else [st.get('message','')]))
    if name=='Fail' and 'No record found' in msgs: return js,req_url,r.url
    if st.get('code') in (2,3,4) or name in ('Usage limit','Server busy','Access denied'):
     time.sleep(min(90,5*(attempt+1)))
     if st.get('code')==4: self.reset()
     continue
    return js,req_url,r.url
   except Exception:
    time.sleep(min(60,4*(attempt+1)))
    self.reset()
  raise RuntimeError(f'API retries exhausted: {params}')

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('extract_id',choices=sorted(CONFIG)); ap.add_argument('--out',default='acquired')
 args=ap.parse_args(); eid=args.extract_id
 root=pathlib.Path(args.out)/eid; rawdir=root/'raw_batches'; rawdir.mkdir(parents=True,exist_ok=True)
 c=Client(); refs,codes=official_codes(c.s,root)
 log=[]; records=[]; invalid=[]
 base={'lang':'EN','sv':'VCm','freq':'M','period':f'{START},{END}','codeclass':'HKHS4',**CONFIG[eid]}
 counter=0
 def fetch_group(group):
  nonlocal counter
  counter+=1; params={**base,'code':','.join(group)}
  js,requested,final=c.request(params)
  b=json.dumps(js,ensure_ascii=False,indent=2).encode(); fn=f'batch_{counter:04d}.json'; (rawdir/fn).write_bytes(b)
  st=js.get('header',{}).get('status',{}); msgs=' | '.join(map(str,st.get('message',[]) if isinstance(st.get('message'),list) else [st.get('message','')]))
  entry={'batch':counter,'codes':group,'params':params,'requested_url':requested,'final_url':final,'status':st,'records':len(js.get('dataSet',[])),'sha256':sha(b),'file':fn}
  log.append(entry)
  if st.get('name')=='Success': records.extend(js.get('dataSet',[])); return
  if 'No record found' in msgs: return
  if len(group)>1 and ('Commodity code' in msgs or 'Validation error' in str(st)):
   mid=len(group)//2; fetch_group(group[:mid]); fetch_group(group[mid:]); return
  invalid.extend(group)
 for group in chunks(codes,20): fetch_group(group)
 df=pd.DataFrame(records)
 if not df.empty:
  key=[x for x in ['freq','period','ttype','co','cc','codeclass','code','sv'] if x in df]
  dup=df.duplicated(key,keep=False)
  if dup.any(): raise RuntimeError(f'Duplicate Trade-IDDS records: {df.loc[dup,key].head().to_dict("records")}')
  df=df.sort_values([x for x in ['period','code','co','cc'] if x in df]).reset_index(drop=True)
 payload={'header':{'status':{'name':'Success','code':0,'description':'Combined from documented official Trade-IDDS API batches'},'title':eid,'count':{'noOfRecords':int(len(df))},'tablenote':['Combined author-side extract; each original official response is retained in raw_batches.','Trade-IDDS omits countries/commodities with nil records; verified zeros are constructed only against the complete official HS4 universe.']},'dataSet':df.to_dict('records')}
 combined=json.dumps(payload,ensure_ascii=False,indent=2).encode(); (root/f'{eid}.json').write_bytes(combined); df.to_csv(root/f'{eid}.csv',index=False)
 stable=set(x['id'] for x in refs['H4'] if int(x.get('aggrlevel',-1))==4)&set(x['id'] for x in refs['H5'] if int(x.get('aggrlevel',-1))==4)&set(x['id'] for x in refs['H6'] if int(x.get('aggrlevel',-1))==4)
 metadata={'extract_id':eid,'source':'Hong Kong Census and Statistics Department, Trade-IDDS','official_endpoint':BASE+'/api/get','period_requested':'2012-01 through 2026-06','frequency':'monthly','statistic':'Value (Monthly)','currency':'HKD','unit_in_api':"HK$ '000",'valuation_basis':'CIF' if CONFIG[eid]['ttype']=='1' else 'FOB','retrieved_at_utc':datetime.now(timezone.utc).isoformat(),'parameters_base':base,'official_code_sources':{k:f'official_{k}.json' for k in refs},'hs4_union_count':len(codes),'stable_hs4_intersection_count':len(stable),'invalid_codes':sorted(set(invalid)),'api_calls':len(log),'records':int(len(df)),'combined_sha256':sha(combined),'query_log':'query_log.json','zero_rule':'Missing commodity-month rows are verified_zero only after expansion to the complete queried official HS4 union; Trade-IDDS footnotes state nil records are omitted.'}
 (root/'query_log.json').write_text(json.dumps(log,ensure_ascii=False,indent=2),encoding='utf-8'); (root/f'{eid}.metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(metadata,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
