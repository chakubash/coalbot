from __future__ import annotations

import gzip, hashlib, json, os, re, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import numpy as np
import pandas as pd
import requests

CASE=os.environ['CASE']
START_END={'HS2012':('201201','201612'),'HS2017':('201701','202112'),'HS2022':('202201','202606')}
SOURCE_VINTAGE='2026-08-05'
OUT=Path('research/parallel_acquisition')/CASE
RAW=OUT/'raw'; CANON=OUT/'canonical'; REPORT=OUT/'reports'; SUPPORT=OUT/'support'
for p in [RAW,CANON,REPORT,SUPPORT]:p.mkdir(parents=True,exist_ok=True)
S=requests.Session();S.headers.update({'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36','Accept':'application/json,text/plain,*/*'})
BASE='https://tradeidds.censtatd.gov.hk/api/get'
manifest=[]

def sha(b:bytes):return hashlib.sha256(b).hexdigest()
def get_json(name,url,attempts=10,timeout=600):
 last=None
 for a in range(attempts):
  try:
   r=S.get(url,timeout=timeout,allow_redirects=True,verify=False);j=r.json();st=j.get('header',{}).get('status',{})
   if r.status_code==200 and (not st or st.get('name')=='Success'):
    p=RAW/f'{name}.json.gz';p.parent.mkdir(parents=True,exist_ok=True)
    with gzip.open(p,'wb',compresslevel=9) as g:g.write(r.content)
    token=re.search(r'/api/([^/]+)/get',r.url);qid=token.group(1) if token else sha(url.encode())[:32]
    manifest.append({'name':name,'requested_url':url,'final_url':r.url,'query_id':qid,'record_count':j.get('header',{}).get('count',{}).get('noOfRecords',j.get('count')),'sha256_uncompressed':sha(r.content),'file':str(p),'retrieved_at_utc':datetime.now(timezone.utc).isoformat(),'title':j.get('header',{}).get('title')})
    time.sleep(.45);return j,qid
   last=(r.status_code,st)
   time.sleep(12+8*a)
  except Exception as e:last=repr(e);time.sleep(6+5*a)
 raise RuntimeError(f'{name}: {last}')

def download_ref(ed,code):
 url=f'https://comtradeapi.un.org/files/v1/app/reference/{code}.json'
 j,_=get_json('ref_'+ed,url,attempts=6,timeout=180)
 return j
refs={'HS2012':download_ref('HS2012','H4'),'HS2017':download_ref('HS2017','H5'),'HS2022':download_ref('HS2022','H6')}
codes_by_ed={};desc={}
for ed,j in refs.items():
 codes=[]
 for x in j['results']:
  c=str(x.get('id','')); level=int(x.get('aggrlevel') or 0)
  if level==4 and len(c)==4 and c.isdigit():
   codes.append(c);desc[(ed,c)]=re.sub(r'^\s*'+re.escape(c)+r'\s*-+\s*','',str(x.get('text',''))).strip()
 codes_by_ed[ed]=sorted(set(codes))

def chunks(xs,n=20):
 for i in range(0,len(xs),n):yield i//n,xs[i:i+n]

SPECS={
'A_import_origin_russia':({'ttype':'1','coclass':'C','co':'RU'},'Russian Federation','origin','import','not_applicable','Russian Federation','not_applicable','not_applicable','CIF'),
'B_import_consignment_russia':({'ttype':'1','ccclass':'C','cc':'RU'},'Russian Federation','consignment','import','not_applicable','not_applicable','Russian Federation','not_applicable','CIF'),
'C_domestic_exports_russia':({'ttype':'2','ccclass':'C','cc':'RU'},'Russian Federation','destination','domestic_export','domestic','not_applicable','not_applicable','Russian Federation','FOB'),
'D_re_exports_russia':({'ttype':'3','ccclass':'C','cc':'RU'},'Russian Federation','destination','re_export','re-export','not_applicable','not_applicable','Russian Federation','FOB'),
'E_total_exports_russia':({'ttype':'4','ccclass':'C','cc':'RU'},'Russian Federation','destination','total_export','total','not_applicable','not_applicable','Russian Federation','FOB'),
'G_hk_world_imports':({'ttype':'1'},'World','origin','import','not_applicable','World','not_applicable','not_applicable','CIF'),
}

if CASE in SPECS:
 pextra,partner,pconcept,flow,etype,origin,consignment,destination,valuation=SPECS[CASE]
 frames=[]
 for ed,(start,end) in START_END.items():
  recs=[];qmap={}
  for bn,batch in chunks(codes_by_ed[ed],20):
   params={'lang':'EN','sv':'VCm','freq':'M','period':f'{start},{end}','codeclass':'HKHS4','code':batch,**pextra}
   j,qid=get_json(f'{ed}_batch_{bn:03d}',BASE+'?'+urlencode(params,doseq=True))
   qmap.update({c:qid for c in batch})
   for x in j.get('dataSet',[]):
    y=dict(x);y['_query_id']=qid;recs.append(y)
  rec=pd.DataFrame(recs)
  if rec.empty:rec=pd.DataFrame(columns=['period','code','figure','codeDescEN','_query_id'])
  rec['period']=rec['period'].astype(str);rec['code']=rec['code'].astype(str).str.zfill(4)
  rec['value']=pd.to_numeric(rec['figure'].astype(str).str.replace(',','',regex=False).replace('',np.nan),errors='coerce')
  rec['status']=np.where(rec.value.isna(),'verified_zero','reported');rec['value']=rec.value.fillna(0)
  rec=rec.groupby(['period','code'],as_index=False).agg(value=('value','sum'),status=('status',lambda x:'reported' if (x=='reported').any() else 'verified_zero'),query_id=('_query_id','first'))
  grid=pd.MultiIndex.from_product([[p.strftime('%Y%m') for p in pd.period_range(pd.Period(start,freq='M'),pd.Period(end,freq='M'),freq='M')],codes_by_ed[ed]],names=['period','hs_code']).to_frame(index=False)
  g=grid.merge(rec,left_on=['period','hs_code'],right_on=['period','code'],how='left')
  g['value']=g.value.fillna(0);g['record_status']=g.status.fillna('verified_zero');g['query_id']=g.query_id.fillna(g.hs_code.map(qmap));g['international_hs_edition']=ed
  frames.append(g[['period','hs_code','value','record_status','query_id','international_hs_edition']])
 out=pd.concat(frames,ignore_index=True)
 out['period']=pd.to_datetime(out.period,format='%Y%m');out['reporter']='Hong Kong, China';out['partner']=partner;out['partner_concept']=pconcept;out['trade_flow']=flow;out['export_type']=etype;out['country_of_origin']=origin;out['country_of_consignment']=consignment;out['country_of_destination']=destination;out['hs_level']=4;out['hkhs_vintage']=out.period.dt.year.astype(str);out['source']='Hong Kong C&SD Trade-IDDS';out['source_vintage']=SOURCE_VINTAGE;out['currency']='HKD';out['valuation_basis']=valuation;out['quantity_unit']='not_applicable';out['trade_value_hkd']=out.value*1000;out['trade_value_usd']=np.nan;out['quantity']=np.nan;out['publication_date']=SOURCE_VINTAGE;out['extract_id']=CASE;out['hs_description']=[desc.get((e,c),'') for e,c in zip(out.international_hs_edition,out.hs_code)]
 cols=['period','reporter','partner','partner_concept','trade_flow','export_type','country_of_origin','country_of_consignment','country_of_destination','hs_level','hs_code','international_hs_edition','hkhs_vintage','source','source_vintage','currency','valuation_basis','quantity_unit','trade_value_hkd','trade_value_usd','quantity','record_status','query_id','publication_date','extract_id','hs_description']
 out=out[cols].sort_values(['period','hs_code'])
 path=CANON/f'{CASE}.csv';out.to_csv(path,index=False)
 # Direct monthly total for a hard completeness audit.
 total_params={'lang':'EN','sv':'VCm','freq':'M','period':'201201,202606',**pextra}
 tj,tqid=get_json('official_total',BASE+'?'+urlencode(total_params))
 total=pd.DataFrame(tj.get('dataSet',[]));total['period']=pd.to_datetime(total.period.astype(str),format='%Y%m');total['official_total_hkd']=pd.to_numeric(total.figure.astype(str).str.replace(',','',regex=False).replace('',0))*1000
 comp=out.groupby('period',as_index=False).trade_value_hkd.sum().merge(total[['period','official_total_hkd']],on='period',how='outer').fillna(0);comp['gap_hkd']=comp.trade_value_hkd-comp.official_total_hkd;comp.to_csv(REPORT/'hs4_total_completeness.csv',index=False)
 report={'extract_id':CASE,'rows':len(out),'period_start':str(out.period.min().date()),'period_end':str(out.period.max().date()),'codes_by_edition':{k:len(v) for k,v in codes_by_ed.items()},'max_abs_total_gap_hkd':float(comp.gap_hkd.abs().max()),'nonzero_total_gap_months_gt_1000hkd':int(comp.gap_hkd.abs().gt(1000).sum()),'canonical_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'official_total_query_id':tqid}
 (REPORT/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False,indent=2))
elif CASE=='SUPPORT':
 # F: origin decomposition at total commodity level.
 fparams={'lang':'EN','sv':'VCm','freq':'M','period':'201201,202606','ttype':'3','ccclass':'C','cc':'RU','coclass':'C','co':'ALL'}
 fj,fqid=get_json('F_re_exports_origin',BASE+'?'+urlencode(fparams));f=pd.DataFrame(fj.get('dataSet',[]))
 if not f.empty:
  val=pd.to_numeric(f.figure.astype(str).str.replace(',','',regex=False).replace('',np.nan),errors='coerce');period=pd.to_datetime(f.period.astype(str),format='%Y%m')
  fo=pd.DataFrame({'period':period,'reporter':'Hong Kong, China','partner':'Russian Federation','partner_concept':'destination','trade_flow':'re_export','export_type':'re-export','country_of_origin':f.coDescEN.astype(str),'country_of_consignment':'not_applicable','country_of_destination':'Russian Federation','hs_level':0,'hs_code':'TOTAL','international_hs_edition':period.dt.year.map(lambda y:'HS2012' if y<=2016 else 'HS2017' if y<=2021 else 'HS2022'),'hkhs_vintage':period.dt.year.astype(str),'source':'Hong Kong C&SD Trade-IDDS','source_vintage':SOURCE_VINTAGE,'currency':'HKD','valuation_basis':'FOB','quantity_unit':'not_applicable','trade_value_hkd':val.fillna(0)*1000,'trade_value_usd':np.nan,'quantity':np.nan,'record_status':np.where(val.isna(),'verified_zero','reported'),'query_id':fqid,'publication_date':SOURCE_VINTAGE,'extract_id':'F_re_exports_origin','hs_description':'Total re-exports'})
  fo.to_csv(CANON/'F_re_exports_origin.csv',index=False)
 # H: official precious-metal value and quantity; edition-native codes.
 hframes=[]
 for ed,(start,end) in START_END.items():
  hs6=sorted({str(x['id']) for x in refs[ed]['results'] if int(x.get('aggrlevel') or 0)==6 and str(x['id'])[:4] in {'7102','7106','7108','7110'}})
  for bn,batch in chunks(hs6,20):
   hp={'lang':'EN','sv':['VCm','QCm'],'freq':'M','period':f'{start},{end}','ttype':'1','coclass':'C','co':'RU','codeclass':'HKHS6','code':batch}
   hj,hqid=get_json(f'H_{ed}_{bn:03d}',BASE+'?'+urlencode(hp,doseq=True));hr=pd.DataFrame(hj.get('dataSet',[]))
   if not hr.empty:hr['_query_id']=hqid;hr['_edition']=ed;hframes.append(hr)
 if hframes:
  h=pd.concat(hframes,ignore_index=True);h['period']=h.period.astype(str);h['code']=h.code.astype(str).str.zfill(6);h['figure_num']=pd.to_numeric(h.figure.astype(str).str.replace(',','',regex=False).replace('',np.nan),errors='coerce')
  v=h[h.sv.eq('VCm')].groupby(['period','code'],as_index=False).agg(value=('figure_num','sum'),query_id=('_query_id','first'),edition=('_edition','first'),desc=('codeDescEN','first'))
  q=h[h.sv.eq('QCm')].groupby(['period','code','unitEN'],as_index=False).agg(quantity=('figure_num','sum'))
  hp=v.merge(q,on=['period','code'],how='inner').dropna(subset=['value','quantity']);per=pd.to_datetime(hp.period,format='%Y%m')
  ho=pd.DataFrame({'period':per,'reporter':'Hong Kong, China','partner':'Russian Federation','partner_concept':'origin','trade_flow':'import','export_type':'not_applicable','country_of_origin':'Russian Federation','country_of_consignment':'not_applicable','country_of_destination':'not_applicable','hs_level':6,'hs_code':hp.code,'international_hs_edition':hp.edition,'hkhs_vintage':per.dt.year.astype(str),'source':'Hong Kong C&SD Trade-IDDS','source_vintage':SOURCE_VINTAGE,'currency':'HKD','valuation_basis':'CIF','quantity_unit':hp.unitEN.astype(str),'trade_value_hkd':hp.value*1000,'trade_value_usd':np.nan,'quantity':hp.quantity,'record_status':'reported','query_id':hp.query_id,'publication_date':SOURCE_VINTAGE,'extract_id':'H_key_hs_quantity','hs_description':hp.desc})
  ho.to_csv(CANON/'H_key_hs_quantity.csv',index=False)
 print({'support_files':[p.name for p in CANON.glob('*.csv')]})
else:raise SystemExit(CASE)
(OUT/'source_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
