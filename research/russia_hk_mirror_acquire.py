from __future__ import annotations

import gzip
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import numpy as np
import pandas as pd
import requests

OUT = Path("research/mirror_acquisition")
RAW = OUT / "raw"
CANON = OUT / "canonical"
REPORTS = OUT / "reports"
for p in [RAW, CANON, REPORTS]: p.mkdir(parents=True, exist_ok=True)
S = requests.Session()
S.headers.update({"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36","Accept":"application/json,text/plain,*/*"})
SOURCE_VINTAGE="2026-08-05"
manifest=[]

def sha(data:bytes)->str:return hashlib.sha256(data).hexdigest()

def request_json(name:str,url:str,max_attempts:int=10)->dict:
    last=None
    for a in range(max_attempts):
        try:
            r=S.get(url,timeout=180,allow_redirects=True)
            if r.status_code==200:
                j=r.json()
                raw=RAW/f"{name}.json.gz";raw.parent.mkdir(parents=True,exist_ok=True)
                with gzip.open(raw,"wb",compresslevel=9) as g:g.write(r.content)
                manifest.append({"name":name,"requested_url":url,"final_url":r.url,"status":r.status_code,"bytes":len(r.content),"sha256_uncompressed":sha(r.content),"file":str(raw),"retrieved_at_utc":datetime.now(timezone.utc).isoformat(),"count":j.get("count")})
                return j
            last=f"HTTP {r.status_code} {r.text[:200]}"
            if r.status_code in {429,500,502,503,504}:time.sleep(15+10*a);continue
        except Exception as e:last=repr(e);time.sleep(10+5*a)
    raise RuntimeError(f"{name} failed: {last}")

# Data availability is preserved as documentation; fetches below deliberately stop at Dec 2021
# because detailed Russian monthly reporting after that date is not available in preview responses.
for endpoint in [
 "https://comtradeapi.un.org/public/v1/getDA/C/M/HS?reporterCode=643",
 "https://comtradeapi.un.org/public/v1/getMetadata/C/M/HS?reporterCode=643",
]:
    try: request_json("availability_"+hashlib.sha256(endpoint.encode()).hexdigest()[:8],endpoint)
    except Exception as e:manifest.append({"name":"availability","url":endpoint,"error":repr(e)})

periods=[p.strftime("%Y%m") for p in pd.period_range("2012-01","2021-12",freq="M")]
base="https://comtradeapi.un.org/public/v1/preview/C/M/HS"

def get_month(flow:str,period:str)->tuple[list[dict],str]:
    # Official wildcard for all four-digit headings. If the API does not accept it,
    # retain a total-only observation rather than fabricating HS4 detail.
    for cmd,label in [("????","hs4_wildcard"),("TOTAL","total_fallback")]:
        params={"reporterCode":"643","period":period,"cmdCode":cmd,"flowCode":flow,"partnerCode":"344","partner2Code":"0","customsCode":"C00","motCode":"0","maxRecords":"500","aggregateBy":"4" if cmd!="TOTAL" else None,"breakdownMode":"classic","includeDesc":"true"}
        params={k:v for k,v in params.items() if v is not None}
        url=base+"?"+urlencode(params)
        try:
            j=request_json(f"{flow}_{period}_{label}",url)
        except Exception:
            continue
        data=j.get("data",[])
        if data:
            if j.get("count",len(data))>=500 and cmd!="TOTAL":
                raise RuntimeError(f"Potential truncation at 500 records for {flow} {period}")
            return data,label
    return [],"no_data"

specs={
 "J_mirror_ru_exports":("X","total_export","total","FOB"),
 "K_mirror_ru_imports":("M","import","not_applicable","CIF"),
}
summary=[]
for extract_id,(flow,trade_flow,export_type,valuation) in specs.items():
    rows=[];methods={}
    for i,period in enumerate(periods):
        data,method=get_month(flow,period);methods[period]=method
        for r in data:
            r=dict(r);r["_method"]=method;rows.append(r)
        if i%12==0:print(extract_id,period,"records",len(rows),"method",method)
        time.sleep(1.15)
    f=pd.DataFrame(rows)
    if f.empty:
        out=pd.DataFrame(columns=[])
    else:
        code_col=next((c for c in ["cmdCode","cmdCode"] if c in f.columns),"cmdCode")
        value_col=next((c for c in ["primaryValue","TradeValue","primaryValue"] if c in f.columns),"primaryValue")
        f["hs_code"]=f[code_col].astype(str).str.replace(r"\.0$","",regex=True)
        agg_col=pd.to_numeric(f.get("aggrLevel",f["hs_code"].str.len()),errors="coerce")
        # Retain HS4 only. TOTAL fallback is documented but not inserted into HS4 panel.
        f=f[(f["hs_code"].str.fullmatch(r"\d{4}")) & agg_col.eq(4)].copy()
        period_series=pd.to_datetime(f["period"].astype(str),format="%Y%m",errors="raise")
        val=pd.to_numeric(f[value_col],errors="coerce")
        reported=~f.get("isReported",pd.Series(True,index=f.index)).astype(str).str.lower().isin(["false","0"])
        status=np.where(val.eq(0),"verified_zero","reported")
        out=pd.DataFrame({
          "period":period_series,"reporter":"Russian Federation","partner":"Hong Kong, China",
          "partner_concept":"mirror_reported_partner","trade_flow":trade_flow,"export_type":export_type,
          "country_of_origin":"not_applicable","country_of_consignment":"not_applicable","country_of_destination":"Hong Kong, China" if flow=="X" else "not_applicable",
          "hs_level":4,"hs_code":f["hs_code"],
          "international_hs_edition":period_series.dt.year.map(lambda y:"HS2012" if y<=2016 else "HS2017"),
          "hkhs_vintage":"not_applicable","source":"UN Comtrade","source_vintage":SOURCE_VINTAGE,
          "currency":"USD","valuation_basis":valuation,"quantity_unit":"not_applicable",
          "trade_value_hkd":np.nan,"trade_value_usd":val,"quantity":np.nan,
          "record_status":status,"query_id":f["_method"].astype(str)+"_"+f["period"].astype(str),
          "publication_date":SOURCE_VINTAGE,"extract_id":extract_id,
          "hs_description":f.get("cmdDesc",pd.Series("",index=f.index)).astype(str),
          "comtrade_is_reported":reported,"comtrade_legacy_estimation_flag":f.get("legacyEstimationFlag",pd.Series(np.nan,index=f.index)),
        })
        out=out.sort_values(["period","hs_code"])
    path=CANON/f"{extract_id}.csv";out.to_csv(path,index=False)
    (path.with_name(path.name+".metadata.json")).write_text(json.dumps({
      "extract_id":extract_id,"source":"UN Comtrade preview API","reporter":"Russian Federation","partner":"Hong Kong, China",
      "period_start":"2012-01","period_end":"2021-12","frequency":"monthly","classification":"HS as reported, filtered to aggregate level 4",
      "method_counts":pd.Series(methods).value_counts().to_dict(),"rows":len(out),"limitations":"No post-2021 detailed Russian reporter panel was inserted; preview API flags and reporting status are preserved. Mirror analysis is descriptive and pre-period only.",
      "sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
    },ensure_ascii=False,indent=2),encoding="utf-8")
    summary.append({"extract_id":extract_id,"rows":len(out),"period_min":None if out.empty else str(out.period.min().date()),"period_max":None if out.empty else str(out.period.max().date()),"methods":pd.Series(methods).value_counts().to_dict()})

(OUT/"source_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
(REPORTS/"mirror_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(summary,ensure_ascii=False,indent=2))
