from __future__ import annotations
import gzip, hashlib, json, os, re, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
import numpy as np, pandas as pd, requests

CASE=os.environ['CASE']; START_END={'HS2012':('201201','201612'),'HS2017':('201701','202112'),'HS2022':('202201','202606')}; V='2026-08-05'
OUT=Path('research/smart_acquisition')/CASE; RAW=OUT/'raw'; CANON=OUT/'canonical'; REPORT=OUT/'reports'
for p in [RAW,CANON,REPORT]:p.mkdir(parents=True,exist_ok=True)
S=requests.Session();S.headers.update({'User-Agent':'Mozilla/5.0','Accept':'application/json,text/plain,*/*'}); BASE='https://tradeidds.censtatd.gov.hk/api/get'; manifest=[]
def sha(b):return hashlib.sha256(b).hexdigest()
def req(name,params):
 url=BASE+'?'+urlencode(params,doseq=True);last=None
 for a in range(10):
  try:
   r=S.get(url,timeout=600,allow_redirects=True,verify=False);j=r.json();st=j.get('header',{}).get('status',{});m=st.get('message','');mt=' '.join(map(str,m)) if isinstance(m,list) else str(m)
   if r.status_code==200 and st.get('name')=='Fail' and 'No record found' in mt:j={'header':{'status':{'name':'Success'},'count':{'noOfRecords':0},'title':j.get('header',{}).get('title')},'dataSet':[]};st=j['header']['status']
   if r.status_code==200 and st.get('name')=='Success':
    p=RAW/f'{name}.json.gz';p.parent.mkdir(parents=True,exist_ok=True)
    with gzip.open(p,'wb',9) as g:g.write(r.content)
    q=re.search(r'/api/([^/]+)/get',r.url);qid=q.group(1) if q else sha(url.encode())[:32]
    manifest.append({'name':name,'requested_url':url,'final_url':r.url,'query_id':qid,'records':len(j.get('dataSet',[])),'sha256':sha(r.content),'retrieved_at_utc':datetime.now(timezone.utc).isoformat(),'title':j.get('header',{}).get('title')});time.sleep(.35);return j.get('dataSet',[]),qid
   last=(r.status_code,st);time.sleep(10+5*a)
  except Exception as e:last=repr(e);time.sleep(5+5*a)
 raise RuntimeError(f'{name}: {last}')
def chunks(x,n=20):
 for i in range(0,len(x),n):yield i//n,x[i:i+n]
# Official HS structures.
refs={}; hs2={};hs4={};desc={}
for ed,code in [('HS2012','H4'),('HS2017','H5'),('HS2022','H6')]:
 r=requests.get(f'https://comtradeapi.un.org/files/v1/app/reference/{code}.json',timeout=180).json();refs[ed]=r;h2=[];h4=[]
 for x in r['results']:
  c=str(x.get('id',''));lev=int(x.get('aggrlevel') or 0)
  if lev==2 and len(c)==2 and c.isdigit() and c not in {'77','98','99'}:h2.append(c)
  if lev==4 and len(c)==4 and c.isdigit() and c!='9999':h4.append(c);desc[(ed,c)]=re.sub(r'^\s*'+re.escape(c)+r'\s*-+\s*','',str(x.get('text',''))).strip()
 hs2[ed]=sorted(set(h2));hs4[ed]=sorted(set(h4))

def query_level(tag,ed,period,extra,level,codes):
 rec=[];qmap={}
 for n,b in chunks(codes):
  rows,q=req(f'{tag}_{ed}_{level}_{n:03d}',{'lang':'EN','sv':'VCm','freq':'M','period':period,'codeclass':f'HKHS{level}','code':b,**extra});qmap.update({c:q for c in b})
  for x in rows:y=dict(x);y['_qid']=q;rec.append(y)
 return pd.DataFrame(rec),qmap

def active_chapters(tag,extra):
 result={}; totals=[]
 for ed,(s,e) in START_END.items():
  d,_=query_level(tag,ed,f'{s},{e}',extra,2,hs2[ed]);
  if d.empty:active=set()
  else:
   d['v']=pd.to_numeric(d.figure.astype(str).str.replace(',','',regex=False).replace('',0),errors='coerce').fillna(0);active=set(d.loc[d.v>0,'code'].astype(str).str.zfill(2))
   d['period']=d.period.astype(str);totals.append(d[['period','v']])
  result[ed]=active
 return result,totals

def make_extract(extract,extra,partner,pconcept,flow,etype,origin,cons,dest,val,active=None,restrict_codes=None,world_totals=None):
 frames=[]
 for ed,(s,e) in START_END.items():
  codes=hs4[ed] if restrict_codes is None else sorted(set(restrict_codes.get(ed,set())) & set(hs4[ed]))
  query_codes=[c for c in codes if active is None or c[:2] in active.get(ed,set())]
  d,qmap=query_level(extract,ed,f'{s},{e}',extra,4,query_codes) if query_codes else (pd.DataFrame(),{})
  if d.empty:d=pd.DataFrame(columns=['period','code','figure','_qid'])
  d['period']=d.get('period',pd.Series(dtype=str)).astype(str);d['code']=d.get('code',pd.Series(dtype=str)).astype(str).str.zfill(4);d['v']=pd.to_numeric(d.get('figure',pd.Series(dtype=str)).astype(str).str.replace(',','',regex=False).replace('',np.nan),errors='coerce');d['status']=np.where(d.v.isna(),'verified_zero','reported');d['v']=d.v.fillna(0)
  if len(d):d=d.groupby(['period','code'],as_index=False).agg(v=('v','sum'),status=('status',lambda x:'reported' if (x=='reported').any() else 'verified_zero'),query_id=('_qid','first'))
  months=[p.strftime('%Y%m') for p in pd.period_range(pd.Period(s,'M'),pd.Period(e,'M'),freq='M')];grid=pd.MultiIndex.from_product([months,codes],names=['period','hs_code']).to_frame(index=False);g=grid.merge(d,left_on=['period','hs_code'],right_on=['period','code'],how='left');g['v']=g.v.fillna(0);g['record_status']=g.status.fillna('verified_zero');g['query_id']=g.query_id.fillna(g.hs_code.map(qmap).fillna('HS2_VERIFIED_ZERO'));g['international_hs_edition']=ed;frames.append(g[['period','hs_code','v','record_status','query_id','international_hs_edition']])
 out=pd.concat(frames,ignore_index=True);out['period']=pd.to_datetime(out.period,format='%Y%m');out['reporter']='Hong Kong, China';out['partner']=partner;out['partner_concept']=pconcept;out['trade_flow']=flow;out['export_type']=etype;out['country_of_origin']=origin;out['country_of_consignment']=cons;out['country_of_destination']=dest;out['hs_level']=4;out['hkhs_vintage']=out.period.dt.year.astype(str);out['source']='Hong Kong C&SD Trade-IDDS';out['source_vintage']=V;out['currency']='HKD';out['valuation_basis']=val;out['quantity_unit']='not_applicable';out['trade_value_hkd']=out.v*1000;out['trade_value_usd']=np.nan;out['quantity']=np.nan;out['publication_date']=V;out['extract_id']=extract;out['hs_description']=[desc.get((e,c),'') for e,c in zip(out.international_hs_edition,out.hs_code)]
 if world_totals is not None:out=out.merge(world_totals,on='period',how='left',validate='many_to_one')
 cols=['period','reporter','partner','partner_concept','trade_flow','export_type','country_of_origin','country_of_consignment','country_of_destination','hs_level','hs_code','international_hs_edition','hkhs_vintage','source','source_vintage','currency','valuation_basis','quantity_unit','trade_value_hkd','trade_value_usd','quantity','record_status','query_id','publication_date','extract_id','hs_description']+(['world_total_hkd'] if world_totals is not None else [])
 p=CANON/f'{extract}.csv';out[cols].sort_values(['period','hs_code']).to_csv(p,index=False);return out
spec={
'A':({'ttype':'1','coclass':'C','co':'RU'},'A_import_origin_russia','Russian Federation','origin','import','not_applicable','Russian Federation','not_applicable','not_applicable','CIF'),
'B':({'ttype':'1','ccclass':'C','cc':'RU'},'B_import_consignment_russia','Russian Federation','consignment','import','not_applicable','not_applicable','Russian Federation','not_applicable','CIF'),
'C':({'ttype':'2','ccclass':'C','cc':'RU'},'C_domestic_exports_russia','Russian Federation','destination','domestic_export','domestic','not_applicable','not_applicable','Russian Federation','FOB'),
'D':({'ttype':'3','ccclass':'C','cc':'RU'},'D_re_exports_russia','Russian Federation','destination','re_export','re-export','not_applicable','not_applicable','Russian Federation','FOB'),
'E':({'ttype':'4','ccclass':'C','cc':'RU'},'E_total_exports_russia','Russian Federation','destination','total_export','total','not_applicable','not_applicable','Russian Federation','FOB')}
if CASE=='A_G':
 a_act,_=active_chapters('Ahs2',spec['A'][0]);a=make_extract(*spec['A'][1:],extra=spec['A'][0],active=a_act);active_codes={ed:set(a.loc[(a.international_hs_edition==ed)&(a.trade_value_hkd>0),'hs_code']) for ed in START_END}
 w_act,w_parts=active_chapters('Ghs2',{'ttype':'1'});wt=pd.concat(w_parts);wt['period']=pd.to_datetime(wt.period,format='%Y%m');wt=wt.groupby('period',as_index=False).v.sum().rename(columns={'v':'world_total_hkd'});wt.world_total_hkd*=1000
 make_extract('G_hk_world_imports',{'ttype':'1'},'World','origin','import','not_applicable','World','not_applicable','not_applicable','CIF',active=w_act,restrict_codes=active_codes,world_totals=wt)
elif CASE=='B':
 act,_=active_chapters('Bhs2',spec['B'][0]);make_extract(*spec['B'][1:],extra=spec['B'][0],active=act)
elif CASE=='CDE':
 act,_=active_chapters('Ehs2',spec['E'][0]);e=make_extract(*spec['E'][1:],extra=spec['E'][0],active=act);codes={ed:set(e.loc[(e.international_hs_edition==ed)&(e.trade_value_hkd>0),'hs_code']) for ed in START_END};make_extract(*spec['C'][1:],extra=spec['C'][0],active=act,restrict_codes=codes);make_extract(*spec['D'][1:],extra=spec['D'][0],active=act,restrict_codes=codes)
else:raise SystemExit(CASE)
(OUT/'source_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');print(CASE,[p.name for p in CANON.glob('*.csv')])
