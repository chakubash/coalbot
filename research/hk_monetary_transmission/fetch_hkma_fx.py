from pathlib import Path
import json, time
import pandas as pd
import requests

out = Path('research_output/hkma_fx')
out.mkdir(parents=True, exist_ok=True)
url = 'https://api.hkma.gov.hk/public/market-data-and-statistics/monthly-statistical-bulletin/er-ir/er-eeri-daily'
s = requests.Session()
s.headers.update({'User-Agent':'AcademicResearchBot/1.0','Accept':'application/json'})
rows=[]
offset=0
pagesize=1000
while True:
    r=s.get(url,params={'offset':offset,'pagesize':pagesize,'sortby':'end_of_day','sortorder':'asc'},timeout=90)
    r.raise_for_status()
    payload=r.json()
    page=payload.get('result',{}).get('records',[]) or []
    print(offset,len(page),flush=True)
    if not page: break
    rows.extend(page)
    if len(page)<pagesize: break
    offset += pagesize
    time.sleep(.2)
df=pd.DataFrame(rows).drop_duplicates()
if 'end_of_day' in df.columns:
    df['end_of_day']=pd.to_datetime(df['end_of_day'])
    df=df.sort_values('end_of_day')
df.to_csv(out/'hkma_er_eeri_daily_full.csv',index=False)
(out/'manifest.json').write_text(json.dumps({'url':url,'rows':len(df)},indent=2),encoding='utf-8')
print(df.head(),df.tail(),df.columns.tolist(),len(df),flush=True)
