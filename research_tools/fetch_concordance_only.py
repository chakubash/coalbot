from __future__ import annotations
import hashlib,json,pathlib,time
from datetime import datetime,timezone
import requests,pandas as pd
OUT=pathlib.Path('acquired/concordance'); OUT.mkdir(parents=True,exist_ok=True)
s=requests.Session(); s.headers.update({'User-Agent':'reproducible-academic-client/1.0'})
def get(u):
 for a in range(12):
  r=s.get(u,timeout=180)
  if r.status_code in (429,500,502,503,504): time.sleep(min(60,4*(a+1))); continue
  r.raise_for_status(); return r
 raise RuntimeError(u)
def sha(p): return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
refs={}
for rev in ('H4','H5','H6'):
 u=f'https://comtradeapi.un.org/files/v1/app/reference/{rev}.json'; r=get(u); p=OUT/f'L_official_{rev}.json'; p.write_bytes(r.content); refs[rev]=r.json()['results']
lookup={r:{str(x['id']):x for x in refs[r] if str(x.get('id','')).isdigit()} for r in refs}
all_ids=sorted(set().union(*[set(x) for x in lookup.values()]),key=lambda x:(len(x),x)); rows=[]
for code in all_ids:
 levels={int(lookup[r][code]['aggrlevel']) for r in refs if code in lookup[r]}
 if not levels or next(iter(levels)) not in (2,4,6): continue
 level=next(iter(levels)); row={'hs_code':code.zfill(level),'hs_level':level}
 for r,label in [('H4','HS2012'),('H5','HS2017'),('H6','HS2022')]:
  x=lookup[r].get(code); row[f'in_{label}']=bool(x); row[f'description_{label}']=None if not x else x.get('text'); row[f'unit_{label}']=None if not x else x.get('standardUnitAbbr')
 row['stable_all_three']=all(row[f'in_{x}'] for x in ('HS2012','HS2017','HS2022'))
 row['audit_action']='retain_native_and_stable' if row['stable_all_three'] else ('aggregate_to_hs2_or_exclude_from_longitudinal_hs6' if level in (4,6) else 'retain_hs2')
 rows.append(row)
aud=pd.DataFrame(rows); out=OUT/'L_hs_concordance.csv'; aud.to_csv(out,index=False)
meta={'extract_id':'L_hs_concordance','source':'United Nations Comtrade official classification reference files','files':{r:{'url':f'https://comtradeapi.un.org/files/v1/app/reference/{r}.json','sha256':sha(OUT/f'L_official_{r}.json')} for r in refs},'method':'Code-presence audit across HS2012/HS2017/HS2022; no fractional allocation. Non-stable HS4/HS6 are retained natively and excluded from stable longitudinal modules or aggregated to HS2.','records':len(aud),'stable_hs4':int(((aud.hs_level==4)&aud.stable_all_three).sum()),'stable_hs6':int(((aud.hs_level==6)&aud.stable_all_three).sum()),'csv_sha256':sha(out),'retrieved_at_utc':datetime.now(timezone.utc).isoformat()}
(OUT/'L_hs_concordance.metadata.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(meta,ensure_ascii=False,indent=2))
