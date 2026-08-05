from __future__ import annotations
import hashlib,json,os,time
from pathlib import Path
from urllib.parse import urlencode
import requests
case=os.environ['CASE']
out=Path('research/probe4_output')/case;out.mkdir(parents=True,exist_ok=True)
s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0','Accept':'application/json,text/plain,*/*'})
base='https://tradeidds.censtatd.gov.hk/api/get'
codes=['0101','0201','0301','0401','0501','0601','0701','0801','0901','1001','1101','1201','1301','1401','1501','1601','1701','1801','1901','2001']
params={'lang':'EN','sv':'VCm','freq':'M'}
if case=='long1':params|={'period':'201201,202606','ttype':'1','coclass':'C','co':'RU','codeclass':'HKHS4','code':'7108'}
elif case=='long20':params|={'period':'201201,202606','ttype':'1','coclass':'C','co':'RU','codeclass':'HKHS4','code':codes}
elif case=='six20':params|={'period':'202501,202506','ttype':'1','coclass':'C','co':'RU','codeclass':'HKHS4','code':codes}
elif case=='flows20':params|={'period':'201201,202606','ttype':'ALL','ccclass':'C','cc':'RU','codeclass':'HKHS4','code':codes}
elif case=='forigin1':params|={'period':'201201,202606','ttype':'3','ccclass':'C','cc':'RU','coclass':'C','co':'ALL','codeclass':'HKHS4','code':'8542'}
elif case=='world20':params|={'period':'201201,202606','ttype':'1','codeclass':'HKHS4','code':codes}
else:raise SystemExit(case)
url=base+'?'+urlencode(params,doseq=True)
r=s.get(url,timeout=600,allow_redirects=True,verify=False)
(out/'response.json').write_bytes(r.content)
item={'case':case,'requested_url':url,'url':r.url,'status':r.status_code,'bytes':len(r.content),'sha256':hashlib.sha256(r.content).hexdigest(),'headers':dict(r.headers)}
try:
 j=r.json();item['api_status']=j.get('header',{}).get('status');item['count']=j.get('header',{}).get('count',{}).get('noOfRecords');item['title']=j.get('header',{}).get('title');ds=j.get('dataSet',[]);item['first']=ds[:2];item['last']=ds[-2:];item['keys']=list(ds[0]) if ds else []
except Exception as e:item['parse_error']=repr(e)
(out/'manifest.json').write_text(json.dumps(item,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps(item,ensure_ascii=False)[:8000])
