from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
from pathlib import Path
import requests

OUT=Path('research/support_download');OUT.mkdir(parents=True,exist_ok=True)
S=requests.Session();S.headers.update({'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36'})
urls={
 'CMO-Historical-Data-Monthly.xlsx':'https://thedocs.worldbank.org/en/doc/5d903e848db1d1b83e0ec8f744e55570-0350012021/related/CMO-Historical-Data-Monthly.xlsx',
 'HS2017-HS2012-correlations.xlsx':'https://unstats.un.org/unsd/classifications/Econ/tables/HS2017toHS2012_and_HS2012toHS2017_correlations.xlsx',
 'HS2022-HS2017-correlations.xlsx':'https://unstats.un.org/unsd/classifications/Econ/tables/HS2022toHS2017_and_HS2017toHS2022_correlations.xlsx',
 'HS2012-reference.json':'https://comtradeapi.un.org/files/v1/app/reference/H4.json',
 'HS2017-reference.json':'https://comtradeapi.un.org/files/v1/app/reference/H5.json',
 'HS2022-reference.json':'https://comtradeapi.un.org/files/v1/app/reference/H6.json',
}
manifest=[]
for name,url in urls.items():
 try:
  r=S.get(url,timeout=180,allow_redirects=True);r.raise_for_status();p=OUT/name;p.write_bytes(r.content)
  manifest.append({'name':name,'requested_url':url,'final_url':r.url,'status':r.status_code,'bytes':len(r.content),'content_type':r.headers.get('content-type'),'sha256':hashlib.sha256(r.content).hexdigest(),'retrieved_at_utc':datetime.now(timezone.utc).isoformat()})
  print(name,len(r.content),r.url)
 except Exception as e:
  manifest.append({'name':name,'requested_url':url,'error':repr(e)});print(name,'ERROR',repr(e))
(OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
