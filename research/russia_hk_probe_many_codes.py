from __future__ import annotations
import hashlib,json,os,re,time
from pathlib import Path
from urllib.parse import urlencode
import requests
N=int(os.environ['N']); PERIOD=os.environ.get('PERIOD','202501'); OUT=Path('research/probe_many_codes')/str(N);OUT.mkdir(parents=True,exist_ok=True)
S=requests.Session();S.headers.update({'User-Agent':'Mozilla/5.0','Accept':'application/json,text/plain,*/*'})
ref=S.get('https://comtradeapi.un.org/files/v1/app/reference/H6.json',timeout=120).json()
codes=sorted({str(x['id']) for x in ref['results'] if int(x.get('aggrlevel') or 0)==4 and str(x['id']).isdigit()})[:N]
params={'lang':'EN','sv':'VCm','freq':'M','period':PERIOD,'ttype':'1','coclass':'C','co':'RU','codeclass':'HKHS4','code':codes}
url='https://tradeidds.censtatd.gov.hk/api/get?'+urlencode(params,doseq=True)
try:
 r=S.get(url,timeout=600,allow_redirects=True,verify=False);(OUT/'response.bin').write_bytes(r.content)
 item={'N':N,'period':PERIOD,'status':r.status_code,'bytes':len(r.content),'requested_url_length':len(url),'final_url':r.url,'sha256':hashlib.sha256(r.content).hexdigest()}
 try:
  j=r.json();item['api_status']=j.get('header',{}).get('status');item['record_count']=j.get('header',{}).get('count',{}).get('noOfRecords');item['title']=j.get('header',{}).get('title');item['first']=j.get('dataSet',[])[:2]
 except Exception as e:item['parse_error']=repr(e);item['text']=r.text[:1000]
except Exception as e:item={'N':N,'error':repr(e),'requested_url_length':len(url)}
(OUT/'manifest.json').write_text(json.dumps(item,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(item,ensure_ascii=False)[:5000])
