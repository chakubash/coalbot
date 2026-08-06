from __future__ import annotations
import json, pathlib, requests, hashlib, re
from urllib.parse import urljoin
OUT=pathlib.Path('acquired/reference_probe'); OUT.mkdir(parents=True,exist_ok=True)
s=requests.Session(); s.headers.update({'User-Agent':'reproducible-academic-client/1.0'})
urls=[
 'https://comtradeapi.un.org/files/v1/app/reference/ListofReferences.json',
 'https://comtradeapi.un.org/files/v1/app/reference/country_area_code_iso.json',
]
for i,u in enumerate(urls):
 r=s.get(u,timeout=180); r.raise_for_status(); p=OUT/f'ref_{i}.json'; p.write_bytes(r.content)
 print(u,r.status_code,len(r.content),hashlib.sha256(r.content).hexdigest())
refs=json.loads((OUT/'ref_0.json').read_text(encoding='utf-8-sig'))['results']
(OUT/'reference_catalog.json').write_text(json.dumps(refs,ensure_ascii=False,indent=2),encoding='utf-8')
for x in refs:
 cat=str(x.get('category',''))
 if any(k in cat.upper() for k in ['H0','H1','H2','H3','H4','H5','H6','HS','CMD','CLASS']):
  print(json.dumps(x,ensure_ascii=False))
  u=x.get('fileuri')
  if u:
   try:
    r=s.get(u,timeout=180); r.raise_for_status()
    fn=re.sub(r'[^A-Za-z0-9._-]+','_',cat)+'.json'
    (OUT/fn).write_bytes(r.content)
   except Exception as e: print('DOWNLOAD_ERROR',cat,repr(e))
# Probe UN Comtrade monthly mirror endpoints.
endpoints=[
 'https://comtradeapi.un.org/public/v1/preview/C/M/HS?period=202501&reporterCode=643&flowCode=X&partnerCode=344&partner2Code=0&cmdCode=TOTAL&maxRecords=500&typeCode=C&freqCode=M&clCode=HS',
 'https://comtradeapi.un.org/public/v1/preview/C/M/HS?period=202501&reporterCode=643&flowCode=X&partnerCode=344&partner2Code=0&cmdCode=AG4&maxRecords=500&typeCode=C&freqCode=M&clCode=HS',
 'https://comtradeapi.un.org/public/v1/preview/C/M/H6?period=202501&reporterCode=643&flowCode=X&partnerCode=344&partner2Code=0&cmdCode=AG4&maxRecords=500',
 'https://comtradeapi.un.org/public/v1/preview/C/M/H5?period=201901&reporterCode=643&flowCode=X&partnerCode=344&partner2Code=0&cmdCode=AG4&maxRecords=500',
]
for i,u in enumerate(endpoints):
 try:
  r=s.get(u,timeout=180); (OUT/f'comtrade_probe_{i}.json').write_bytes(r.content)
  try: js=r.json(); info={'status':r.status_code,'url':r.url,'count':js.get('count'),'data_len':len(js.get('data',[])),'head':js.get('data',[])[:2],'error':js.get('error')}
  except Exception: info={'status':r.status_code,'url':r.url,'text':r.text[:500]}
 except Exception as e: info={'url':u,'exception':repr(e)}
 (OUT/f'comtrade_probe_{i}.meta.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(info,ensure_ascii=False))
