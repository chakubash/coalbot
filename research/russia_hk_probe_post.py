from __future__ import annotations
import hashlib,json,os
from pathlib import Path
import requests
MODE=os.environ['MODE'];N=int(os.environ['N']);OUT=Path('research/probe_post')/MODE;OUT.mkdir(parents=True,exist_ok=True)
S=requests.Session();S.headers.update({'User-Agent':'Mozilla/5.0','Accept':'application/json,text/plain,*/*'})
ref=S.get('https://comtradeapi.un.org/files/v1/app/reference/H6.json',timeout=120).json();codes=sorted({str(x['id']) for x in ref['results'] if int(x.get('aggrlevel') or 0)==4 and str(x['id']).isdigit()})[:N]
params={'lang':'EN','sv':'VCm','freq':'M','period':'202501','ttype':'1','coclass':'C','co':'RU','codeclass':'HKHS4','code':codes};url='https://tradeidds.censtatd.gov.hk/api/get'
try:
 if MODE=='form':r=S.post(url,data=params,timeout=600,allow_redirects=True,verify=False)
 elif MODE=='json':r=S.post(url,json=params,timeout=600,allow_redirects=True,verify=False)
 elif MODE=='query_post':r=S.post(url,params=params,timeout=600,allow_redirects=True,verify=False)
 else:raise SystemExit(MODE)
 (OUT/'response.bin').write_bytes(r.content);item={'mode':MODE,'N':N,'status':r.status_code,'url':r.url,'bytes':len(r.content),'content_type':r.headers.get('content-type'),'sha256':hashlib.sha256(r.content).hexdigest()}
 try:
  j=r.json();item['api_status']=j.get('header',{}).get('status');item['record_count']=j.get('header',{}).get('count',{}).get('noOfRecords');item['title']=j.get('header',{}).get('title');item['first']=j.get('dataSet',[])[:2]
 except Exception as e:item['parse_error']=repr(e);item['text']=r.text[:1000]
except Exception as e:item={'mode':MODE,'N':N,'error':repr(e)}
(OUT/'manifest.json').write_text(json.dumps(item,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(item,ensure_ascii=False)[:5000])
