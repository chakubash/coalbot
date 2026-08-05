from __future__ import annotations
import hashlib,json,time
from pathlib import Path
from urllib.parse import urlencode
import requests
OUT=Path('research/probe3_output');OUT.mkdir(parents=True,exist_ok=True)
S=requests.Session();S.headers.update({'User-Agent':'Mozilla/5.0','Accept':'application/json,text/plain,*/*'})
manifest=[]
def q(name,params):
 url='https://tradeidds.censtatd.gov.hk/api/get?'+urlencode(params,doseq=True)
 try:
  r=S.get(url,timeout=180,allow_redirects=True,verify=False)
  p=OUT/(name+'.json');p.write_bytes(r.content)
  item={'name':name,'status':r.status_code,'url':r.url,'bytes':len(r.content),'sha256':hashlib.sha256(r.content).hexdigest()}
  try:
   j=r.json(); item['api_status']=j.get('header',{}).get('status');item['count']=j.get('header',{}).get('count',{}).get('noOfRecords');item['title']=j.get('header',{}).get('title'); ds=j.get('dataSet',[]);item['sample']=ds[:2]; item['keys']=list(ds[0]) if ds else []
  except Exception as e:item['parse_error']=repr(e)
  manifest.append(item);print(json.dumps(item,ensure_ascii=False)[:1500])
 except Exception as e:manifest.append({'name':name,'error':repr(e)});print(name,e)
base={'lang':'EN','freq':'M','sv':'VCm','period':'202501'}
queries={
'A_total':{**base,'ttype':'1','coclass':'C','co':'RU'},
'A_hs4_all':{**base,'ttype':'1','coclass':'C','co':'RU','codeclass':'HKHS4'},
'B_total':{**base,'ttype':'1','ccclass':'C','cc':'RU'},
'B_hs4_all':{**base,'ttype':'1','ccclass':'C','cc':'RU','codeclass':'HKHS4'},
'C_total':{**base,'ttype':'2','ccclass':'C','cc':'RU'},
'C_hs4_all':{**base,'ttype':'2','ccclass':'C','cc':'RU','codeclass':'HKHS4'},
'D_total':{**base,'ttype':'3','ccclass':'C','cc':'RU'},
'D_hs4_all':{**base,'ttype':'3','ccclass':'C','cc':'RU','codeclass':'HKHS4'},
'E_total':{**base,'ttype':'4','ccclass':'C','cc':'RU'},
'E_hs4_all':{**base,'ttype':'4','ccclass':'C','cc':'RU','codeclass':'HKHS4'},
'F_origin_all_hs4':{**base,'ttype':'3','ccclass':'C','cc':'RU','coclass':'C','co':'ALL','codeclass':'HKHS4'},
'G_world_hs4':{**base,'ttype':'1','codeclass':'HKHS4'},
'G_world_hs4_coall':{**base,'ttype':'1','coclass':'C','co':'ALL','codeclass':'HKHS4'},
'H_hs6_all_value':{**base,'ttype':'1','coclass':'C','co':'RU','codeclass':'HKHS6'},
'H_710812_value':{**base,'ttype':'1','coclass':'C','co':'RU','codeclass':'HKHS6','code':'710812'},
'H_710812_qty':{'lang':'EN','freq':'M','sv':'QCm','period':'202501','ttype':'1','coclass':'C','co':'RU','codeclass':'HKHS6','code':'710812'},
'H_710812_both':{'lang':'EN','freq':'M','sv':['VCm','QCm'],'period':'202501','ttype':'1','coclass':'C','co':'RU','codeclass':'HKHS6','code':'710812'},
}
for n,p in queries.items():q(n,p)
for month in ['202602','202603','202604']:
 for key,p in {
 'A':{'ttype':'1','coclass':'C','co':'RU'},
 'B':{'ttype':'1','ccclass':'C','cc':'RU'},
 'C':{'ttype':'2','ccclass':'C','cc':'RU'},
 'D':{'ttype':'3','ccclass':'C','cc':'RU'},
 'E':{'ttype':'4','ccclass':'C','cc':'RU'},
 'G':{'ttype':'1'},
 }.items():q(f'{key}_{month}',{'lang':'EN','freq':'M','sv':'VCm','period':month,**p})
(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
