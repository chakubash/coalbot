from __future__ import annotations
import json, pathlib, re, hashlib, mimetypes
from urllib.parse import urlencode, urljoin
import requests
from bs4 import BeautifulSoup

OUT=pathlib.Path('acquired/probe2'); OUT.mkdir(parents=True,exist_ok=True)
BASE='https://tradeidds.censtatd.gov.hk'
s=requests.Session(); s.headers.update({'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36','Accept':'application/json,text/html,*/*','Accept-Language':'en-US,en;q=0.9'})
s.get(BASE+'/',timeout=90)

def fetch_api(name, params):
    p={'lang':'EN','sv':'VCm','freq':'M','period':'202501,202501'}; p.update(params)
    u=BASE+'/api/get?'+urlencode(p,safe=',`')
    r=s.get(u,timeout=180,allow_redirects=True); r.raise_for_status()
    (OUT/f'{name}.json').write_bytes(r.content)
    try: js=r.json()
    except Exception: js={}
    meta={'name':name,'params':p,'requested_url':u,'final_url':r.url,'status':r.status_code,'api_status':js.get('header',{}).get('status'),'count':js.get('header',{}).get('count'),'title':js.get('header',{}).get('title'),'tablenote':js.get('header',{}).get('tablenote'),'head':(js.get('dataSet') or [])[:5],'sha256':hashlib.sha256(r.content).hexdigest()}
    (OUT/f'{name}.meta.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(meta,ensure_ascii=False))

fetch_api('multi_backtick',{'ttype':'1','coclass':'C','co':'RU','codeclass':'HKHS4','code':'7108`7110'})
fetch_api('multi_comma',{'ttype':'1','coclass':'C','co':'RU','codeclass':'HKHS4','code':'7108,7110'})
fetch_api('stats_value_quantity',{'sv':'VCm`QCm','ttype':'1','coclass':'C','co':'RU','codeclass':'HKHS6','code':'710812'})
fetch_api('quantity_qcm',{'sv':'QCm','ttype':'1','coclass':'C','co':'RU','codeclass':'HKHS6','code':'710812'})
fetch_api('origin_all_reexport_ru',{'ttype':'3','coclass':'C','co':'ALL','ccclass':'C','cc':'RU'})
fetch_api('twenty_hs4',{'ttype':'1','coclass':'C','co':'RU','codeclass':'HKHS4','code':'7106`7108`7110`7102`2701`2709`2710`4403`4407`0306`0303`0402`1001`1512`2208`2402`2601`2603`7502`7601'})
fetch_api('month_202606_check',{'period':'202606,202606','ttype':'1','coclass':'C','co':'RU','codeclass':'HKHS4','code':'7108'})

# Download official HKHS publication/index pages and every spreadsheet/csv link.
PAGES=[
 'https://www.censtatd.gov.hk/en/EIndexbySubject.html?pcode=B2XX0023&scode=230',
 'https://www.censtatd.gov.hk/en/EIndexbySubject.html?pcode=B2XX0011&scode=230',
 'https://www.censtatd.gov.hk/en/EIndexbySubject.html?pcode=B2XX0012&scode=230',
]
all_links=[]
for idx,u in enumerate(PAGES):
    r=requests.get(u,timeout=120,headers={'User-Agent':s.headers['User-Agent']}); r.raise_for_status()
    (OUT/f'hkhs_page_{idx}.html').write_bytes(r.content)
    soup=BeautifulSoup(r.text,'html.parser')
    for a in soup.find_all('a',href=True):
        href=urljoin(r.url,a['href'])
        text=' '.join(a.get_text(' ',strip=True).split())
        if any(x in href.lower() for x in ['.xls','.xlsx','.csv','.zip','.pdf']) or any(x in text.lower() for x in ['excel','download','hkhs']):
            all_links.append({'page':u,'text':text,'href':href})
(OUT/'hkhs_links.json').write_text(json.dumps(all_links,ensure_ascii=False,indent=2),encoding='utf-8')
seen=set()
for i,item in enumerate(all_links):
    href=item['href']
    if href in seen: continue
    seen.add(href)
    try:
        r=requests.get(href,timeout=180,allow_redirects=True,headers={'User-Agent':s.headers['User-Agent']}); r.raise_for_status()
        ctype=r.headers.get('content-type','').lower()
        if len(r.content)<1000: continue
        # Keep spreadsheets, zip, pdf, or files whose content-disposition supplies a name.
        disp=r.headers.get('content-disposition','')
        m=re.search(r'filename\*?=(?:UTF-8\'\')?[\"\']?([^\"\';]+)',disp,re.I)
        fn=m.group(1) if m else pathlib.Path(r.url.split('?')[0]).name
        if not fn or fn in {'EIndexbySubject.html'}: fn=f'linked_{i}.bin'
        fn=re.sub(r'[^A-Za-z0-9._-]+','_',fn)
        if not (any(ext in fn.lower() for ext in ['.xls','.xlsx','.csv','.zip','.pdf']) or any(x in ctype for x in ['spreadsheet','excel','zip','pdf','csv','octet-stream'])):
            continue
        path=OUT/('hkhs_'+fn)
        if path.exists(): path=OUT/(f'hkhs_{i}_'+fn)
        path.write_bytes(r.content)
        item.update({'download_final':r.url,'download_status':r.status_code,'content_type':ctype,'content_disposition':disp,'saved_as':path.name,'bytes':len(r.content),'sha256':hashlib.sha256(r.content).hexdigest()})
    except Exception as e:
        item['download_error']=repr(e)
(OUT/'hkhs_download_report.json').write_text(json.dumps(all_links,ensure_ascii=False,indent=2),encoding='utf-8')
