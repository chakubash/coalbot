from __future__ import annotations
import hashlib,json,time
from pathlib import Path
from urllib.parse import urlencode
import requests
OUT=Path('research/probe6_output');OUT.mkdir(parents=True,exist_ok=True)
S=requests.Session();S.headers.update({'User-Agent':'Mozilla/5.0','Accept':'application/json,text/plain,*/*'})
base='https://tradeidds.censtatd.gov.hk/api/get'
codes=['7108','7110','7102','7106','8542','8517','8471','8486','9013','9002','8703','3004','2710','0303','4407','7202','7601','8105','2503','2616']
common={'lang':'EN','sv':'VCm','freq':'M','period':'201201,202606','codeclass':'HKHS4','code':codes}
queries=[
 ('ttypeall',{**common,'ttype':'ALL','ccclass':'C','cc':'RU'}),
 ('forigin',{**common,'ttype':'3','ccclass':'C','cc':'RU','coclass':'C','co':'ALL'}),
 ('world',{**common,'ttype':'1'}),
]
manifest=[]
for name,p in queries:
 time.sleep(5)
 url=base+'?'+urlencode(p,doseq=True)
 try:
  r=S.get(url,timeout=600,allow_redirects=True,verify=False);(OUT/f'{name}.json').write_bytes(r.content)
  item={'name':name,'requested_url':url,'url':r.url,'status':r.status_code,'bytes':len(r.content),'sha256':hashlib.sha256(r.content).hexdigest()}
  try:
   j=r.json();item['api_status']=j.get('header',{}).get('status');item['count']=j.get('header',{}).get('count',{}).get('noOfRecords');item['title']=j.get('header',{}).get('title');ds=j.get('dataSet',[]);item['first']=ds[:3];item['last']=ds[-3:];item['keys']=list(ds[0]) if ds else []
  except Exception as e:item['parse_error']=repr(e)
 except Exception as e:item={'name':name,'requested_url':url,'error':repr(e)}
 manifest.append(item);print(json.dumps(item,ensure_ascii=False)[:12000])
(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
