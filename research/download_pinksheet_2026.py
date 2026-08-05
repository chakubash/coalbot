from pathlib import Path
import hashlib, json, requests
from datetime import datetime, timezone
url='https://thedocs.worldbank.org/en/doc/74e8be41ceb20fa0da750cda2f6b9e4e-0050012026/related/CMO-Historical-Data-Monthly.xlsx'
out=Path('research/pinksheet_2026');out.mkdir(parents=True,exist_ok=True)
r=requests.get(url,headers={'User-Agent':'Mozilla/5.0'},timeout=180);r.raise_for_status()
p=out/'CMO-Historical-Data-Monthly-2026.xlsx';p.write_bytes(r.content)
meta={'requested_url':url,'final_url':r.url,'status':r.status_code,'bytes':len(r.content),'sha256':hashlib.sha256(r.content).hexdigest(),'retrieved_at_utc':datetime.now(timezone.utc).isoformat(),'content_type':r.headers.get('content-type')}
(out/'manifest.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
print(meta)
