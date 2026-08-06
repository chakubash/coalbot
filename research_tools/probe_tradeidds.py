from __future__ import annotations
import json, pathlib, re
from urllib.parse import urlencode
import requests

OUT=pathlib.Path('acquired/probe')
OUT.mkdir(parents=True,exist_ok=True)
BASE='https://tradeidds.censtatd.gov.hk'
s=requests.Session()
s.headers.update({'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36','Accept':'application/json,text/html,*/*','Accept-Language':'en-US,en;q=0.9'})
# Establish both web and API cookies.
for u in [BASE+'/', BASE+'/PageID/ApiSpec', BASE+'/MetadataLink/ApiSpec/API_eng.pdf']:
    try:
        r=s.get(u,timeout=90,allow_redirects=True)
        name=re.sub(r'[^A-Za-z0-9]+','_',u.replace(BASE,'')) or 'root'
        (OUT/f'{name}.bin').write_bytes(r.content)
        (OUT/f'{name}.meta.json').write_text(json.dumps({'requested':u,'final':r.url,'status':r.status_code,'headers':dict(r.headers),'history':[{'status':h.status_code,'url':h.url,'location':h.headers.get('location')} for h in r.history],'cookies':s.cookies.get_dict()},indent=2),encoding='utf-8')
    except Exception as e:
        (OUT/'page_errors.txt').write_text(repr(e),encoding='utf-8')

def q(name, **params):
    p={'lang':'EN','sv':'VCm','freq':'M','period':'202501,202501'}
    p.update({k:str(v) for k,v in params.items() if v is not None})
    u=BASE+'/api/get?'+urlencode(p,safe=',')
    try:
        r=s.get(u,timeout=120,allow_redirects=True)
        (OUT/f'{name}.bin').write_bytes(r.content)
        try: payload=r.json()
        except Exception: payload=None
        meta={'name':name,'params':p,'url':u,'final':r.url,'status':r.status_code,'history':[{'status':h.status_code,'url':h.url,'location':h.headers.get('location')} for h in r.history],'cookies':s.cookies.get_dict(),'json_status':(payload or {}).get('header',{}).get('status'),'title':(payload or {}).get('header',{}).get('title'),'count':(payload or {}).get('header',{}).get('count'),'dataset_head':((payload or {}).get('dataSet') or [])[:3],'text_head':r.text[:700]}
    except Exception as e:
        meta={'name':name,'params':p,'url':u,'error':repr(e)}
    (OUT/f'{name}.meta.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(meta,ensure_ascii=False))

# Trade types and partner concepts.
for t in [1,2,3,4,5]:
    q(f'ttype{t}_cc_ru_hs85',ttype=t,ccclass='C',cc='RU',codeclass='HKHS2',code='85')
q('import_origin_ru_hs71',ttype=1,coclass='C',co='RU',codeclass='HKHS2',code='71')
q('import_consignment_ru_hs71',ttype=1,ccclass='C',cc='RU',codeclass='HKHS2',code='71')
q('reexport_dest_ru_origin_cn',ttype=3,coclass='C',co='CN',ccclass='C',cc='RU')
q('reexport_dest_ru_origin_cn_hs85',ttype=3,coclass='C',co='CN',ccclass='C',cc='RU',codeclass='HKHS2',code='85')
q('reexport_dest_ru_by_origin',ttype=3,ccclass='C',cc='RU',coclass='C')
# All/world and code selection probes.
q('import_world_hs71_omit_partner',ttype=1,codeclass='HKHS2',code='71')
q('import_origin_all_hs71',ttype=1,coclass='C',co='ALL',codeclass='HKHS2',code='71')
q('import_origin_zz_hs71',ttype=1,coclass='C',co='ZZ',codeclass='HKHS2',code='71')
for code in [None,'ALL','*','01','0101','0101,0102','0101`0102','0101;0102']:
    q('codeprobe_'+re.sub(r'[^A-Za-z0-9]+','_',str(code)),ttype=1,coclass='C',co='RU',codeclass='HKHS4',code=code)
# Quantity statistics probes.
for sv in ['QNm','QN','VQm','VCm,QNm']:
    q('quantity_'+re.sub(r'[^A-Za-z0-9]+','_',sv),sv=sv,ttype=1,coclass='C',co='RU',codeclass='HKHS6',code='710812')
# Longer period and limits.
q('period_2012_2026_onecode',period='201201,202606',ttype=1,coclass='C',co='RU',codeclass='HKHS4',code='7108')
q('period_2025_all_hs4_omit_code',period='202501,202512',ttype=1,coclass='C',co='RU',codeclass='HKHS4')
(OUT/'summary.json').write_text(json.dumps({'cookies':s.cookies.get_dict()},indent=2),encoding='utf-8')
