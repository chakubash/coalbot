from __future__ import annotations
import hashlib,json,os
from pathlib import Path
from urllib.parse import urlencode
import requests
case=os.environ['CASE'];out=Path('research/probe5_output')/case;out.mkdir(parents=True,exist_ok=True)
s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0','Accept':'application/json,text/plain,*/*'})
base='https://tradeidds.censtatd.gov.hk/api/get'
common={'lang':'EN','sv':'VCm','freq':'M','period':'201201,202606'}
q={
'allcode_A':{**common,'ttype':'1','coclass':'C','co':'RU','codeclass':'HKHS4','code':'ALL'},
'allcode_G':{**common,'ttype':'1','codeclass':'HKHS4','code':'ALL'},
'ttypeall_cc_20':{**common,'ttype':'ALL','ccclass':'C','cc':'RU','codeclass':'HKHS4','code':['7108','7110','7102','7106','8542','8517','8471','8486','9013','9002','8703','3004','2710','0303','4407','7202','7601','8105','2503','2616']},
'forigin20':{**common,'ttype':'3','ccclass':'C','cc':'RU','coclass':'C','co':'ALL','codeclass':'HKHS4','code':['7108','7110','7102','7106','8542','8517','8471','8486','9013','9002','8703','3004','2710','0303','4407','7202','7601','8105','2503','2616']},
'world20':{**common,'ttype':'1','codeclass':'HKHS4','code':['7108','7110','7102','7106','8542','8517','8471','8486','9013','9002','8703','3004','2710','0303','4407','7202','7601','8105','2503','2616']},
}
if case=='hkma':
 url='https://api.hkma.gov.hk/public/market-data-and-statistics/monthly-statistical-bulletin/er-ir/er-eeri-periodaverage?pagesize=1000&offset=0'
else:url=base+'?'+urlencode(q[case],doseq=True)
try:
 r=s.get(url,timeout=600,allow_redirects=True,verify=False);(out/'response.bin').write_bytes(r.content)
 item={'case':case,'requested_url':url,'url':r.url,'status':r.status_code,'bytes':len(r.content),'content_type':r.headers.get('content-type'),'sha256':hashlib.sha256(r.content).hexdigest()}
 try:
  j=r.json();(out/'response.json').write_text(json.dumps(j,ensure_ascii=False),encoding='utf-8');item['api_status']=j.get('header',{}).get('status');item['count']=j.get('header',{}).get('count',{}).get('noOfRecords',j.get('count'));item['title']=j.get('header',{}).get('title');ds=j.get('dataSet',j.get('result',{}).get('records',j.get('data',[])));item['first']=ds[:2] if isinstance(ds,list) else None;item['last']=ds[-2:] if isinstance(ds,list) else None;item['keys']=list(ds[0]) if isinstance(ds,list) and ds else []
 except Exception as e:item['parse_error']=repr(e);item['text_head']=r.text[:500]
except Exception as e:item={'case':case,'error':repr(e),'requested_url':url}
(out/'manifest.json').write_text(json.dumps(item,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(item,ensure_ascii=False)[:10000])
