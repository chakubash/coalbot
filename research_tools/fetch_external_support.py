from __future__ import annotations
import hashlib, json, pathlib, re
from datetime import datetime, timezone
from urllib.parse import urljoin
import requests, pandas as pd
from bs4 import BeautifulSoup
OUT=pathlib.Path('acquired/external_support'); OUT.mkdir(parents=True,exist_ok=True)
s=requests.Session(); s.headers.update({'User-Agent':'reproducible-academic-client/1.0'})
def sha(p): return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
# I: official HKMA period-average HKD per USD.
url='https://api.hkma.gov.hk/public/market-data-and-statistics/monthly-statistical-bulletin/er-ir/er-eeri-periodaverage'
records=[]; pages=[]; offset=0
while True:
 r=s.get(url,params={'from':'2012-01','to':'2026-06','pagesize':100,'offset':offset},timeout=180); r.raise_for_status(); j=r.json(); pages.append(j)
 if not j.get('header',{}).get('success'): raise RuntimeError(j.get('header'))
 part=j.get('result',{}).get('records',[]); records.extend(part)
 if len(part)<100: break
 offset+=len(part)
raw=OUT/'I_hkma_hkd_usd.raw.json'; raw.write_text(json.dumps(pages,ensure_ascii=False,indent=2),encoding='utf-8')
df=pd.DataFrame(records); fx=df[['end_of_month','usd']].rename(columns={'end_of_month':'period','usd':'hkd_per_usd'}); fx['period']=pd.to_datetime(fx['period']).dt.to_period('M').astype(str); fx['hkd_per_usd']=pd.to_numeric(fx['hkd_per_usd']); fx=fx.sort_values('period').drop_duplicates('period')
expected=pd.period_range('2012-01','2026-06',freq='M').astype(str)
if set(expected)-set(fx.period): raise RuntimeError('HKMA calendar incomplete')
fx.to_csv(OUT/'I_hkma_hkd_usd.csv',index=False)
(OUT/'I_hkma_hkd_usd.metadata.json').write_text(json.dumps({'extract_id':'I_hkma_hkd_usd','source':'Hong Kong Monetary Authority','endpoint':url,'definition':'Monthly period-average HKD per 1 USD','formula':'USD=HKD/hkd_per_usd','period':'2012-01/2026-06','records':len(fx),'raw_sha256':sha(raw),'csv_sha256':sha(OUT/'I_hkma_hkd_usd.csv'),'retrieved_at_utc':datetime.now(timezone.utc).isoformat()},indent=2),encoding='utf-8')
# L: official UN Comtrade HS2012/2017/2022 reference files and non-fractional stable-code audit.
refs={}
for rev in ('H4','H5','H6'):
 u=f'https://comtradeapi.un.org/files/v1/app/reference/{rev}.json'; r=s.get(u,timeout=180); r.raise_for_status(); p=OUT/f'L_official_{rev}.json'; p.write_bytes(r.content); refs[rev]=r.json()['results']
rows=[]
all_ids=sorted(set().union(*[{str(x['id']) for x in refs[r] if str(x.get('id','')).isdigit() and int(x.get('aggrlevel',-1)) in (2,4,6)} for r in refs]))
lookup={r:{str(x['id']):x for x in refs[r]} for r in refs}
for code in all_ids:
 levels=[int(lookup[r][code]['aggrlevel']) for r in refs if code in lookup[r]]; level=levels[0]
 row={'hs_code':code,'hs_level':level}
 for r,label in [('H4','HS2012'),('H5','HS2017'),('H6','HS2022')]:
  x=lookup[r].get(code); row[f'in_{label}']=bool(x); row[f'description_{label}']=None if not x else x.get('text'); row[f'unit_{label}']=None if not x else x.get('standardUnitAbbr')
 row['stable_all_three']=all(row[f'in_{x}'] for x in ('HS2012','HS2017','HS2022'))
 row['audit_action']='retain_native_and_stable' if row['stable_all_three'] else ('aggregate_to_hs2_or_exclude_from_longitudinal_hs6' if level in (4,6) else 'retain_hs2')
 rows.append(row)
aud=pd.DataFrame(rows); aud.to_csv(OUT/'L_hs_concordance.csv',index=False)
(OUT/'L_hs_concordance.metadata.json').write_text(json.dumps({'extract_id':'L_hs_concordance','source':'United Nations Comtrade official classification reference files','files':{r:{'url':f'https://comtradeapi.un.org/files/v1/app/reference/{r}.json','sha256':sha(OUT/f'L_official_{r}.json')} for r in refs},'method':'Code-presence audit across HS2012/HS2017/HS2022; no fractional allocation. Non-stable HS4/HS6 are kept natively and excluded from stable longitudinal modules or aggregated to HS2.','records':len(aud),'stable_hs4':int(((aud.hs_level==4)&aud.stable_all_three).sum()),'stable_hs6':int(((aud.hs_level==6)&aud.stable_all_three).sum()),'csv_sha256':sha(OUT/'L_hs_concordance.csv')},ensure_ascii=False,indent=2),encoding='utf-8')
# M: World Bank Commodity Price Data (Pink Sheet), monthly historical workbook.
page='https://www.worldbank.org/en/research/commodity-markets'
candidates=[
 'https://thedocs.worldbank.org/en/doc/5d903e848db1d1b83e0ec8f744e55570-0350012021/related/CMO-Historical-Data-Monthly.xlsx',
 'https://thedocs.worldbank.org/en/doc/5d903e848db1d1b83e0ec8f744e55570-0350012021/related/CMO-Historical-Data-Monthly.xlsx?download=1',
]
try:
 pr=s.get(page,timeout=180); pr.raise_for_status(); (OUT/'world_bank_commodity_page.html').write_bytes(pr.content); soup=BeautifulSoup(pr.text,'html.parser')
 for a in soup.find_all('a',href=True):
  h=urljoin(pr.url,a['href']); t=a.get_text(' ',strip=True).lower()
  if 'historical-data-monthly' in h.lower() or ('monthly' in t and ('xlsx' in h.lower() or 'historical' in t)): candidates.insert(0,h)
except Exception: pass
wb=None; wburl=None
for u in dict.fromkeys(candidates):
 try:
  r=s.get(u,timeout=240,allow_redirects=True)
  if r.status_code==200 and len(r.content)>50000 and (r.content[:2]==b'PK' or 'spreadsheet' in r.headers.get('content-type','').lower()): wb=r.content; wburl=r.url; break
 except Exception: continue
if wb is None: raise RuntimeError('World Bank monthly Pink Sheet workbook not found')
wbp=OUT/'M_world_bank_cmo_monthly.xlsx'; wbp.write_bytes(wb)
# Detect monthly prices sheet and header.
xl=pd.ExcelFile(wbp); sheet=next((x for x in xl.sheet_names if 'Monthly' in x and 'Price' in x),xl.sheet_names[0]); rawdf=pd.read_excel(wbp,sheet_name=sheet,header=None)
header_idx=None
for i in range(min(20,len(rawdf))):
 vals=' '.join(map(str,rawdf.iloc[i].tolist()))
 if 'Gold' in vals and ('Platinum' in vals or 'Silver' in vals): header_idx=i; break
if header_idx is None: raise RuntimeError(f'Pink Sheet header not found: {xl.sheet_names}')
pd0=pd.read_excel(wbp,sheet_name=sheet,header=header_idx); date_col=pd0.columns[0]; pd0=pd0.rename(columns={date_col:'period_raw'}); pd0['period']=pd.to_datetime(pd0['period_raw'],errors='coerce').dt.to_period('M').astype(str)
cols={'Gold':'gold_usd_per_troy_oz','Silver':'silver_usd_per_troy_oz','Platinum':'platinum_usd_per_troy_oz'}
out=pd.DataFrame({'period':pd0['period']})
found={}
for needle,new in cols.items():
 c=next((x for x in pd0.columns if needle.lower() in str(x).lower()),None)
 if c is not None: out[new]=pd.to_numeric(pd0[c],errors='coerce'); found[new]=str(c)
out=out[out.period.str.match(r'\d{4}-\d{2}',na=False)].drop_duplicates('period').sort_values('period'); out=out[(out.period>='2012-01')&(out.period<='2026-06')]; out.to_csv(OUT/'M_key_commodity_prices.csv',index=False)
(OUT/'M_key_commodity_prices.metadata.json').write_text(json.dumps({'extract_id':'M_key_commodity_prices','source':'World Bank Commodity Price Data (Pink Sheet), CMO Historical Data Monthly','download_url':wburl,'sheet':sheet,'detected_columns':found,'period':'2012-01/2026-06','workbook_sha256':sha(wbp),'csv_sha256':sha(OUT/'M_key_commodity_prices.csv'),'records':len(out),'retrieved_at_utc':datetime.now(timezone.utc).isoformat()},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'I':len(fx),'L':len(aud),'M':len(out),'M_url':wburl,'M_columns':found},ensure_ascii=False,indent=2))
