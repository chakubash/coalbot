from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

OUT = Path('research/discovery_output')
OUT.mkdir(parents=True, exist_ok=True)
S = requests.Session()
S.headers.update({'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36','Accept':'application/json,text/plain,*/*','Accept-Language':'en-US,en;q=0.9'})
manifest=[]

def record(name,url,r):
    ct=r.headers.get('content-type','')
    ext='.json' if ('json' in ct or r.text.lstrip().startswith('{')) else '.html' if ('html' in ct or r.text.lstrip().startswith('<')) else '.bin'
    p=OUT/(name+ext); p.write_bytes(r.content)
    item={'name':name,'url':r.url,'requested_url':url,'status':r.status_code,'content_type':ct,'bytes':len(r.content),'sha256':hashlib.sha256(r.content).hexdigest(),'file':str(p),'history':[x.status_code for x in r.history]}
    try:
        j=r.json(); item['api_status']=j.get('header',{}).get('status',{}); item['count']=j.get('header',{}).get('count',{}).get('noOfRecords',j.get('count'))
        ds=j.get('dataSet',j.get('data',[])); item['sample']=ds[:2] if isinstance(ds,list) else None
    except Exception: pass
    manifest.append(item); print(json.dumps(item,ensure_ascii=False)[:1200])

def get(name,url,*,sleep=0,verify=True):
    if sleep: time.sleep(sleep)
    try:
        r=S.get(url,timeout=120,allow_redirects=True,verify=verify)
        record(name,url,r); return r
    except Exception as e:
        manifest.append({'name':name,'requested_url':url,'error':repr(e)}); print(name,'ERROR',repr(e)); return None

base='https://tradeidds.censtatd.gov.hk/api/get'
def tid(name,params): return get(name,base+'?'+urlencode(params,doseq=True),verify=False)

common={'lang':'EN','freq':'M','sv':'VCm'}
# Correct partner concepts, totals and full HS4 probes.
probes={
 'A_ru_origin_total_202501':{**common,'period':'202501','ttype':'1','coclass':'C','co':'RU'},
 'A_ru_origin_hs7108_202501':{**common,'period':'202501','ttype':'1','coclass':'C','co':'RU','codeclass':'HKHS4','code':'7108'},
 'A_ru_origin_hs4_all_202501':{**common,'period':'202501','ttype':'1','coclass':'C','co':'RU','codeclass':'HKHS4'},
 'B_ru_consignment_total_202501':{**common,'period':'202501','ttype':'1','ccclass':'C','cc':'RU'},
 'B_ru_consignment_hs4_all_202501':{**common,'period':'202501','ttype':'1','ccclass':'C','cc':'RU','codeclass':'HKHS4'},
 'C_domestic_to_ru_total_202501':{**common,'period':'202501','ttype':'2','ccclass':'C','cc':'RU'},
 'C_domestic_to_ru_hs4_all_202501':{**common,'period':'202501','ttype':'2','ccclass':'C','cc':'RU','codeclass':'HKHS4'},
 'D_reexport_to_ru_total_202501':{**common,'period':'202501','ttype':'3','ccclass':'C','cc':'RU'},
 'D_reexport_to_ru_hs4_all_202501':{**common,'period':'202501','ttype':'3','ccclass':'C','cc':'RU','codeclass':'HKHS4'},
 'E_total_to_ru_total_202501':{**common,'period':'202501','ttype':'4','ccclass':'C','cc':'RU'},
 'E_total_to_ru_hs4_all_202501':{**common,'period':'202501','ttype':'4','ccclass':'C','cc':'RU','codeclass':'HKHS4'},
 'F_reexport_to_ru_all_origins_hs4_202501':{**common,'period':'202501','ttype':'3','ccclass':'C','cc':'RU','coclass':'C','co':'ALL','codeclass':'HKHS4'},
 'G_world_import_hs4_all_202501':{**common,'period':'202501','ttype':'1','codeclass':'HKHS4'},
 'G_world_import_hs4_all_coall_202501':{**common,'period':'202501','ttype':'1','coclass':'C','co':'ALL','codeclass':'HKHS4'},
 # HS6 and quantity/value multi-statistic probes.
 'H_ru_origin_hs6_all_value_202501':{**common,'period':'202501','ttype':'1','coclass':'C','co':'RU','codeclass':'HKHS6'},
 'H_ru_origin_hs6_710812_value_202501':{**common,'period':'202501','ttype':'1','coclass':'C','co':'RU','codeclass':'HKHS6','code':'710812'},
 'H_ru_origin_hs6_710812_quantity_202501':{'lang':'EN','freq':'M','sv':'QCm','period':'202501','ttype':'1','coclass':'C','co':'RU','codeclass':'HKHS6','code':'710812'},
 'H_ru_origin_hs6_710812_both_202501':{'lang':'EN','freq':'M','sv':['VCm','QCm'],'period':'202501','ttype':'1','coclass':'C','co':'RU','codeclass':'HKHS6','code':'710812'},
}
for n,p in probes.items(): tid(n,p)

# Latest-month probes across all required concepts.
for month in ['202602','202603','202604','202605','202606']:
    for key,p in {
      'A':{**common,'period':month,'ttype':'1','coclass':'C','co':'RU'},
      'B':{**common,'period':month,'ttype':'1','ccclass':'C','cc':'RU'},
      'C':{**common,'period':month,'ttype':'2','ccclass':'C','cc':'RU'},
      'D':{**common,'period':month,'ttype':'3','ccclass':'C','cc':'RU'},
      'E':{**common,'period':month,'ttype':'4','ccclass':'C','cc':'RU'},
      'G':{**common,'period':month,'ttype':'1'},
    }.items(): tid(f'latest_{key}_{month}',p)

# HKMA variants.
hkma_base='https://api.hkma.gov.hk/public/market-data-and-statistics/monthly-statistical-bulletin/er-ir/er-eeri-periodaverage'
for i,url in enumerate([
 hkma_base,
 hkma_base+'?pagesize=100&offset=0',
 hkma_base+'?from=2025-01&to=2025-02',
 hkma_base.replace('https://','http://')+'?pagesize=100&offset=0',
 'https://api.hkma.gov.hk/public/market-data-and-statistics/monthly-statistical-bulletin/er-ir/er-eeri?pagesize=100&offset=0',
]): get(f'hkma_variant_{i}',url,sleep=2)

# Parse official pages for downloadable HKMA resources.
for page in ['https://apidocs.hkma.gov.hk/documentation/market-data-and-statistics/monthly-statistical-bulletin/er-ir/er-eeri-periodaverage/','https://data.gov.hk/en-data/dataset/hk-hkma-monthly-statistical-bulletin']:
 r=get('page_'+str(abs(hash(page))),page)
 if r and r.status_code==200:
  soup=BeautifulSoup(r.text,'html.parser')
  links=[]
  for a in soup.find_all('a',href=True):
   h=a['href']; t=' '.join(a.get_text(' ',strip=True).split())
   if any(x in (h+' '+t).lower() for x in ['csv','xlsx','json','swagger','api.hkma']): links.append({'text':t,'href':h})
  (OUT/('links_'+str(abs(hash(page)))+'.json')).write_text(json.dumps(links,indent=2),encoding='utf-8')

# UN Comtrade spaced probes.
ct='https://comtradeapi.un.org/public/v1/preview/C/M/HS'
ctqs={
 'ct_hk_import_ru_total_202501':dict(reporterCode=344,period=202501,cmdCode='TOTAL',flowCode='M',partnerCode=643,maxRecords=500,includeDesc='true'),
 'ct_hk_export_ru_total_202501':dict(reporterCode=344,period=202501,cmdCode='TOTAL',flowCode='X',partnerCode=643,maxRecords=500,includeDesc='true'),
 'ct_ru_export_hk_total_202112':dict(reporterCode=643,period=202112,cmdCode='TOTAL',flowCode='X',partnerCode=344,maxRecords=500,includeDesc='true'),
 'ct_ru_export_hk_total_202501':dict(reporterCode=643,period=202501,cmdCode='TOTAL',flowCode='X',partnerCode=344,maxRecords=500,includeDesc='true'),
}
for n,p in ctqs.items(): get(n,ct+'?'+urlencode(p),sleep=12)

(OUT/'probe2_manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
