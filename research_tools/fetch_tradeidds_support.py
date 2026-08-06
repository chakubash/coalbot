from __future__ import annotations
import hashlib, json, pathlib, time
from datetime import datetime, timezone
from urllib.parse import urlencode
import requests, pandas as pd
BASE='https://tradeidds.censtatd.gov.hk'; REF='https://comtradeapi.un.org/files/v1/app/reference'; START='201201'; END='202606'

def sha(b): return hashlib.sha256(b).hexdigest()
def chunks(xs,n):
 for i in range(0,len(xs),n): yield xs[i:i+n]
class Client:
 def __init__(self):
  self.s=requests.Session(); self.s.headers.update({'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36','Accept':'application/json,text/html,*/*','Accept-Language':'en-US,en;q=0.9'}); self.reset()
 def reset(self):
  self.s.cookies.clear(); self.s.get(BASE+'/',timeout=120).raise_for_status()
 def get(self,p):
  req=BASE+'/api/get?'+urlencode(p,safe=',')
  for a in range(15):
   try:
    r=self.s.get(BASE+'/api/get',params=p,timeout=240); r.raise_for_status(); j=r.json(); st=j.get('header',{}).get('status',{}); msg=' | '.join(map(str,st.get('message',[]) if isinstance(st.get('message'),list) else [st.get('message','')]))
    if st.get('name')=='Success' or 'No record found' in msg: return j,req,r.url
    if st.get('code') in (2,3,4): time.sleep(min(90,5*(a+1))); self.reset(); continue
    return j,req,r.url
   except Exception:
    time.sleep(min(60,4*(a+1))); self.reset()
  raise RuntimeError(str(p))

def get_refs(s,out):
 refs={}
 for rev in ('H4','H5','H6'):
  r=s.get(f'{REF}/{rev}.json',timeout=180); r.raise_for_status(); (out/f'official_{rev}.json').write_bytes(r.content); refs[rev]=r.json()['results']
 return refs

def main():
 root=pathlib.Path('acquired/tradeidds_support'); root.mkdir(parents=True,exist_ok=True); c=Client(); refs=get_refs(c.s,root)
 fp={'lang':'EN','sv':'VCm','freq':'M','period':f'{START},{END}','ttype':'3','coclass':'C','co':'ALL','ccclass':'C','cc':'RU'}
 fj,frq,ffinal=c.get(fp); fb=json.dumps(fj,ensure_ascii=False,indent=2).encode(); (root/'F_re_exports_origin.json').write_bytes(fb); fdf=pd.DataFrame(fj.get('dataSet',[])); fdf.to_csv(root/'F_re_exports_origin.csv',index=False)
 fmeta={'extract_id':'F_re_exports_origin','source':'Hong Kong C&SD Trade-IDDS','period':'2012-01/2026-06','requested_url':frq,'final_url':ffinal,'parameters':fp,'records':len(fdf),'sha256':sha(fb),'structural_limitation':'Trade-IDDS rejects re-export queries combining country of origin and HKHS/SITC commodity classification; F therefore measures origin by month, while D measures HS4 by month.'}
 (root/'F_re_exports_origin.metadata.json').write_text(json.dumps(fmeta,ensure_ascii=False,indent=2),encoding='utf-8')
 six=set(); byrev={}
 for rev,rows in refs.items():
  ids={str(x['id']) for x in rows if int(x.get('aggrlevel',-1))==6 and str(x.get('id','')).isdigit()}; byrev[rev]=ids; six|=ids
 import_prefixes=('7102','7106','7108','7110')
 export_prefixes=('8471','8473','8486','8504','8517','8523','8525','8528','8541','8542','8543','9001','9002','9013','9018','9027','9030','9031')
 modules=[('precious_import','1',{'coclass':'C','co':'RU'},sorted(x for x in six if x[:4] in import_prefixes)),('key_reexport','3',{'ccclass':'C','cc':'RU'},sorted(x for x in six if x[:4] in export_prefixes))]
 logs=[]; combined=[]; invalid=[]; n=0
 def fetch_group(module,ttype,partner,sv,group):
  nonlocal n
  n+=1; p={'lang':'EN','sv':sv,'freq':'M','period':f'{START},{END}','ttype':ttype,'codeclass':'HKHS6','code':','.join(group),**partner}
  j,req,final=c.get(p); b=json.dumps(j,ensure_ascii=False,indent=2).encode(); fn=f'H_batch_{n:04d}.json'; (root/fn).write_bytes(b)
  st=j.get('header',{}).get('status',{}); msg=' | '.join(map(str,st.get('message',[]) if isinstance(st.get('message'),list) else [st.get('message','')]))
  logs.append({'module':module,'stat':sv,'codes':group,'params':p,'requested_url':req,'final_url':final,'status':st,'records':len(j.get('dataSet',[])),'file':fn,'sha256':sha(b)})
  if st.get('name')=='Success':
   rows=j.get('dataSet',[])
   for x in rows: x['_module']=module
   combined.extend(rows); return
  if 'No record found' in msg: return
  if len(group)>1 and ('Commodity code' in msg or st.get('description')=='Validation error'):
   mid=len(group)//2; fetch_group(module,ttype,partner,sv,group[:mid]); fetch_group(module,ttype,partner,sv,group[mid:]); return
  invalid.extend(group)
 for module,ttype,partner,codes in modules:
  for sv in ('VCm','QCm'):
   for group in chunks(codes,20): fetch_group(module,ttype,partner,sv,group)
 hdf=pd.DataFrame(combined)
 if not hdf.empty:
  key=[x for x in ['_module','freq','period','ttype','co','cc','codeclass','code','sv','unitEN'] if x in hdf]
  if hdf.duplicated(key,keep=False).any(): raise RuntimeError('Duplicate H records')
  hdf=hdf.sort_values([x for x in ['_module','period','ttype','code','sv'] if x in hdf])
 hdf.to_csv(root/'H_key_hs_quantity.csv',index=False)
 hpayload={'header':{'status':{'name':'Success'},'count':{'noOfRecords':len(hdf)},'title':'H_key_hs_quantity combined official batches'},'dataSet':hdf.to_dict('records')}; hb=json.dumps(hpayload,ensure_ascii=False,indent=2).encode(); (root/'H_key_hs_quantity.json').write_bytes(hb)
 stable6=set.intersection(*[set(v) for v in byrev.values()])
 hmeta={'extract_id':'H_key_hs_quantity','source':'Hong Kong C&SD Trade-IDDS','period':'2012-01/2026-06','modules':{'precious_import':list(import_prefixes),'key_reexport':list(export_prefixes)},'statistics':['VCm','QCm'],'records':len(hdf),'api_calls':len(logs),'invalid_hs6_codes':sorted(set(invalid)),'stable_hs6_intersection_count':len(stable6),'combined_sha256':sha(hb),'retrieved_at_utc':datetime.now(timezone.utc).isoformat()}
 (root/'H_key_hs_quantity.metadata.json').write_text(json.dumps(hmeta,ensure_ascii=False,indent=2),encoding='utf-8'); (root/'H_query_log.json').write_text(json.dumps(logs,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'F':fmeta,'H':hmeta},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
