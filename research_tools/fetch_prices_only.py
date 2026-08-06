from __future__ import annotations
import hashlib,json,pathlib,time
from datetime import datetime,timezone
from urllib.parse import urljoin
import requests,pandas as pd
from bs4 import BeautifulSoup
OUT=pathlib.Path('acquired/prices'); OUT.mkdir(parents=True,exist_ok=True)
s=requests.Session(); s.headers.update({'User-Agent':'reproducible-academic-client/1.0'})
def get(u,attempts=10):
 for a in range(attempts):
  try:
   r=s.get(u,timeout=240,allow_redirects=True)
   if r.status_code in (429,500,502,503,504): time.sleep(min(60,4*(a+1))); continue
   r.raise_for_status(); return r
  except Exception:
   if a==attempts-1: raise
   time.sleep(min(60,4*(a+1)))
 raise RuntimeError(u)
def sha(p): return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
page='https://www.worldbank.org/en/research/commodity-markets'
candidates=['https://thedocs.worldbank.org/en/doc/5d903e848db1d1b83e0ec8f744e55570-0350012021/related/CMO-Historical-Data-Monthly.xlsx','https://thedocs.worldbank.org/en/doc/5d903e848db1d1b83e0ec8f744e55570-0350012021/related/CMO-Historical-Data-Monthly.xlsx?download=1']
try:
 pr=get(page); (OUT/'world_bank_commodity_page.html').write_bytes(pr.content); soup=BeautifulSoup(pr.text,'html.parser')
 for a in soup.find_all('a',href=True):
  h=urljoin(pr.url,a['href']); t=a.get_text(' ',strip=True).lower()
  if 'historical-data-monthly' in h.lower() or ('monthly' in t and ('xlsx' in h.lower() or 'historical' in t)): candidates.insert(0,h)
except Exception: pass
wb=None; wburl=None
for u in dict.fromkeys(candidates):
 try:
  r=get(u,attempts=5)
  if len(r.content)>50000 and (r.content[:2]==b'PK' or 'spreadsheet' in r.headers.get('content-type','').lower()): wb=r.content; wburl=r.url; break
 except Exception: continue
if wb is None: raise RuntimeError('World Bank monthly Pink Sheet workbook not found')
wbp=OUT/'M_world_bank_cmo_monthly.xlsx'; wbp.write_bytes(wb); xl=pd.ExcelFile(wbp)
sheet=next((x for x in xl.sheet_names if 'Monthly' in x and 'Price' in x),xl.sheet_names[0]); raw=pd.read_excel(wbp,sheet_name=sheet,header=None)
header_idx=None
for i in range(min(40,len(raw))):
 vals=' '.join(map(str,raw.iloc[i].tolist()))
 if 'Gold' in vals and ('Platinum' in vals or 'Silver' in vals): header_idx=i; break
if header_idx is None: raise RuntimeError(f'Pink Sheet header not found: {xl.sheet_names}')
df=pd.read_excel(wbp,sheet_name=sheet,header=header_idx); date_col=df.columns[0]; df=df.rename(columns={date_col:'period_raw'}); df['period']=pd.to_datetime(df.period_raw,errors='coerce').dt.to_period('M').astype(str)
needles={'Gold':'gold_usd_per_troy_oz','Silver':'silver_usd_per_troy_oz','Platinum':'platinum_usd_per_troy_oz'}; out=pd.DataFrame({'period':df.period}); found={}
for needle,new in needles.items():
 col=next((c for c in df.columns if needle.lower() in str(c).lower()),None)
 if col is not None: out[new]=pd.to_numeric(df[col],errors='coerce'); found[new]=str(col)
out=out[out.period.str.match(r'\d{4}-\d{2}',na=False)].drop_duplicates('period').sort_values('period'); out=out[(out.period>='2012-01')&(out.period<='2026-06')]
path=OUT/'M_key_commodity_prices.csv'; out.to_csv(path,index=False)
meta={'extract_id':'M_key_commodity_prices','source':'World Bank Commodity Price Data (Pink Sheet), CMO Historical Data Monthly','download_url':wburl,'sheet':sheet,'detected_columns':found,'period':'2012-01/2026-06','records':len(out),'workbook_sha256':sha(wbp),'csv_sha256':sha(path),'retrieved_at_utc':datetime.now(timezone.utc).isoformat()}
(OUT/'M_key_commodity_prices.metadata.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(meta,ensure_ascii=False,indent=2))
