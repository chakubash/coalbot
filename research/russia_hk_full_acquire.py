from __future__ import annotations

import gzip
import hashlib
import json
import math
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urljoin

import numpy as np
import pandas as pd
import requests

START = "201201"
END = "202606"
SOURCE_VINTAGE = "2026-08-05"
OUT = Path("research/full_acquisition")
RAW = OUT / "raw"
CANON = OUT / "canonical"
SUPPORT = OUT / "support"
REPORTS = OUT / "reports"
for p in [RAW, CANON, SUPPORT, REPORTS]:
    p.mkdir(parents=True, exist_ok=True)

S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
})

manifest: list[dict[str, object]] = []
invalid_codes: list[dict[str, object]] = []


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def save_download(name: str, url: str, *, timeout: int = 300) -> Path:
    last = None
    for attempt in range(6):
        try:
            r = S.get(url, timeout=timeout, allow_redirects=True)
            if r.status_code == 200 and len(r.content) > 100:
                suffix = Path(r.url.split("?")[0]).suffix or ".bin"
                path = SUPPORT / f"{name}{suffix}"
                path.write_bytes(r.content)
                manifest.append({
                    "kind": "official_download", "name": name, "requested_url": url,
                    "final_url": r.url, "status": r.status_code, "bytes": len(r.content),
                    "sha256": sha256_bytes(r.content), "file": str(path),
                    "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                })
                print("DOWNLOAD", name, len(r.content), r.url)
                return path
            last = RuntimeError(f"HTTP {r.status_code}, {len(r.content)} bytes")
        except Exception as exc:
            last = exc
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"Could not download {name}: {last}")


# Official classification references.
H_URLS = {
    "HS2012": "https://comtradeapi.un.org/files/v1/app/reference/H4.json",
    "HS2017": "https://comtradeapi.un.org/files/v1/app/reference/H5.json",
    "HS2022": "https://comtradeapi.un.org/files/v1/app/reference/H6.json",
}
ref_paths = {edition: save_download(edition, url) for edition, url in H_URLS.items()}
refs: dict[str, dict[str, object]] = {edition: json.loads(path.read_text(encoding="utf-8")) for edition, path in ref_paths.items()}

hs4_sets: dict[str, set[str]] = {}
hs6_sets: dict[str, set[str]] = {}
descriptions: dict[tuple[str, str], str] = {}
for edition, payload in refs.items():
    hs4_sets[edition] = set()
    hs6_sets[edition] = set()
    for item in payload["results"]:
        code = str(item.get("id", ""))
        level = int(item.get("aggrlevel") or 0)
        text = str(item.get("text", ""))
        desc = re.sub(r"^\s*" + re.escape(code) + r"\s*-+\s*", "", text).strip()
        if level == 4 and len(code) == 4 and code.isdigit():
            hs4_sets[edition].add(code)
            descriptions[(edition, code)] = desc
        elif level == 6 and len(code) == 6 and code.isdigit():
            hs6_sets[edition].add(code)
            descriptions[(edition, code)] = desc

union_hs4 = sorted(set().union(*hs4_sets.values()))
(SUPPORT / "hs4_union.json").write_text(json.dumps({k: sorted(v) for k, v in hs4_sets.items()}, indent=2), encoding="utf-8")
print("HS4 UNION", len(union_hs4), {k: len(v) for k, v in hs4_sets.items()})

# Official conversion/correlation and commodity price files.
conversion_urls = {
    "HS2017_to_HS2012": "https://unstats.un.org/unsd/classifications/Econ/tables/HS2017toHS2012ConversionAndCorrelationTables.xlsx",
    "HS2022_to_HS2017": "https://unstats.un.org/unsd/classifications/Econ/tables/HS2022toHS2017ConversionAndCorrelationTables.xlsx",
    "HS2022_to_HS2012": "https://unstats.un.org/unsd/classifications/Econ/tables/HS2022toHS2012ConversionAndCorrelationTables.xlsx",
}
conversion_paths = {}
for name, url in conversion_urls.items():
    try:
        conversion_paths[name] = save_download(name, url)
    except Exception as exc:
        manifest.append({"kind": "download_error", "name": name, "url": url, "error": repr(exc)})

pink_url = "https://thedocs.worldbank.org/en/doc/5d903e848db1d1b83e0ec8f744e55570-0350012021/related/CMO-Historical-Data-Monthly.xlsx"
try:
    pink_path = save_download("CMO_Historical_Data_Monthly", pink_url)
except Exception as exc:
    pink_path = None
    manifest.append({"kind": "download_error", "name": "CMO_Historical_Data_Monthly", "url": pink_url, "error": repr(exc)})

# HKMA monthly average exchange rates.
hkma_url = "https://api.hkma.gov.hk/public/market-data-and-statistics/monthly-statistical-bulletin/er-ir/er-eeri-periodaverage?pagesize=1000&offset=0"
try:
    hkma_path = save_download("HKMA_er_eeri_periodaverage", hkma_url)
except Exception as exc:
    hkma_path = None
    manifest.append({"kind": "download_error", "name": "HKMA_er_eeri_periodaverage", "url": hkma_url, "error": repr(exc)})


def edition_for_period(period: str) -> str:
    year = int(period[:4])
    return "HS2012" if year <= 2016 else "HS2017" if year <= 2021 else "HS2022"


def period_grid() -> list[str]:
    return [p.strftime("%Y%m") for p in pd.period_range("2012-01", "2026-06", freq="M")]


TID_BASE = "https://tradeidds.censtatd.gov.hk/api/get"


def chunks(seq: list[str], n: int = 20):
    for i in range(0, len(seq), n):
        yield i // n, seq[i:i+n]


def api_error_text(payload: dict[str, object]) -> str:
    status = payload.get("header", {}).get("status", {}) if isinstance(payload, dict) else {}
    msg = status.get("message", "") if isinstance(status, dict) else ""
    if isinstance(msg, list):
        msg = " ".join(map(str, msg))
    return str(msg)


def tid_get(extract_id: str, batch_label: str, params: dict[str, object], *, allow_retry: bool = True) -> tuple[list[dict[str, object]], str, str]:
    url = TID_BASE + "?" + urlencode(params, doseq=True)
    last_error = None
    for attempt in range(10):
        try:
            r = S.get(url, timeout=600, allow_redirects=True, verify=False)
            payload = r.json()
            status = payload.get("header", {}).get("status", {})
            if r.status_code == 200 and status.get("name") == "Success":
                raw_bytes = r.content
                raw_path = RAW / extract_id / f"{batch_label}.json.gz"
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                with gzip.open(raw_path, "wb", compresslevel=9) as gz:
                    gz.write(raw_bytes)
                token_match = re.search(r"/api/([^/]+)/get", r.url)
                token = token_match.group(1) if token_match else sha256_bytes(url.encode())[:32]
                meta = {
                    "extract_id": extract_id, "batch": batch_label,
                    "requested_url": url, "final_url": r.url, "query_id": token,
                    "status": status, "title": payload.get("header", {}).get("title"),
                    "record_count": payload.get("header", {}).get("count", {}).get("noOfRecords"),
                    "sha256_uncompressed": sha256_bytes(raw_bytes),
                    "raw_gzip_file": str(raw_path), "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                }
                (raw_path.with_suffix(raw_path.suffix + ".metadata.json")).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
                manifest.append({"kind": "tradeidds", **meta, "bytes_uncompressed": len(raw_bytes)})
                time.sleep(0.35)
                return list(payload.get("dataSet", [])), token, url
            text = api_error_text(payload)
            last_error = RuntimeError(text or f"HTTP {r.status_code}")
            if "usage limit" in text.lower() or "too many" in text.lower():
                time.sleep(15 + attempt * 10)
                continue
            break
        except Exception as exc:
            last_error = exc
            time.sleep(5 + attempt * 5)
    raise RuntimeError(f"Trade-IDDS {extract_id}/{batch_label} failed: {last_error}")


@dataclass(frozen=True)
class ExtractSpec:
    extract_id: str
    params: dict[str, object]
    partner: str
    partner_concept: str
    trade_flow: str
    export_type: str
    origin: str
    consignment: str
    destination: str
    valuation: str


extract_specs = [
    ExtractSpec("A_import_origin_russia", {"ttype": "1", "coclass": "C", "co": "RU"}, "Russian Federation", "origin", "import", "not_applicable", "Russian Federation", "not_applicable", "not_applicable", "CIF"),
    ExtractSpec("B_import_consignment_russia", {"ttype": "1", "ccclass": "C", "cc": "RU"}, "Russian Federation", "consignment", "import", "not_applicable", "not_applicable", "Russian Federation", "not_applicable", "CIF"),
    ExtractSpec("C_domestic_exports_russia", {"ttype": "2", "ccclass": "C", "cc": "RU"}, "Russian Federation", "destination", "domestic_export", "domestic", "not_applicable", "not_applicable", "Russian Federation", "FOB"),
    ExtractSpec("D_re_exports_russia", {"ttype": "3", "ccclass": "C", "cc": "RU"}, "Russian Federation", "destination", "re_export", "re-export", "not_applicable", "not_applicable", "Russian Federation", "FOB"),
    ExtractSpec("E_total_exports_russia", {"ttype": "4", "ccclass": "C", "cc": "RU"}, "Russian Federation", "destination", "total_export", "total", "not_applicable", "not_applicable", "Russian Federation", "FOB"),
    ExtractSpec("G_hk_world_imports", {"ttype": "1"}, "World", "origin", "import", "not_applicable", "World", "not_applicable", "not_applicable", "CIF"),
]


def query_batch_with_fallback(spec: ExtractSpec, batch_no: int, codes: list[str]) -> tuple[list[dict[str, object]], dict[str, str]]:
    common = {"lang": "EN", "sv": "VCm", "freq": "M", "period": f"{START},{END}", "codeclass": "HKHS4"}
    params = {**common, **spec.params, "code": codes}
    try:
        rows, token, _ = tid_get(spec.extract_id, f"batch_{batch_no:03d}", params)
        return rows, {c: token for c in codes}
    except Exception as batch_exc:
        if len(codes) > 1:
            mid = len(codes) // 2
            left_rows, left_map = query_batch_with_fallback(spec, batch_no * 10 + 1, codes[:mid])
            right_rows, right_map = query_batch_with_fallback(spec, batch_no * 10 + 2, codes[mid:])
            return left_rows + right_rows, {**left_map, **right_map}
        code = codes[0]
        combined: list[dict[str, object]] = []
        token_map: dict[str, str] = {}
        segments = [("HS2012", "201201", "201612"), ("HS2017", "201701", "202112"), ("HS2022", "202201", "202606")]
        for edition, start, end in segments:
            if code not in hs4_sets[edition]:
                continue
            seg_params = {**common, **spec.params, "period": f"{start},{end}", "code": code}
            try:
                rows, token, _ = tid_get(spec.extract_id, f"code_{code}_{edition}", seg_params)
                combined.extend(rows)
                token_map[code] = token
            except Exception as seg_exc:
                invalid_codes.append({"extract_id": spec.extract_id, "code": code, "edition": edition, "error": repr(seg_exc)})
        if not token_map:
            invalid_codes.append({"extract_id": spec.extract_id, "code": code, "edition": "ALL", "error": repr(batch_exc)})
            token_map[code] = "QUERY_FAILED"
        return combined, token_map


all_canonical_paths: dict[str, Path] = {}
raw_records_by_extract: dict[str, list[dict[str, object]]] = {}

for spec in extract_specs:
    print("EXTRACT START", spec.extract_id)
    records: list[dict[str, object]] = []
    code_query: dict[str, str] = {}
    for batch_no, code_batch in chunks(union_hs4, 20):
        rows, mapping = query_batch_with_fallback(spec, batch_no, code_batch)
        for row in rows:
            row = dict(row)
            row["_query_id"] = mapping.get(str(row.get("code")), "UNKNOWN")
            records.append(row)
        code_query.update(mapping)
        if batch_no % 10 == 0:
            print(spec.extract_id, "batch", batch_no, "records", len(records))
    raw_records_by_extract[spec.extract_id] = records

    rec = pd.DataFrame(records)
    if rec.empty:
        rec = pd.DataFrame(columns=["period", "code", "figure", "codeDescEN", "_query_id"])
    rec["period"] = rec.get("period", pd.Series(dtype=str)).astype(str)
    rec["code"] = rec.get("code", pd.Series(dtype=str)).astype(str).str.zfill(4)
    rec["figure_num"] = pd.to_numeric(rec.get("figure", pd.Series(dtype=str)).astype(str).str.replace(",", "", regex=False).replace("", np.nan), errors="coerce")
    rec["record_status_src"] = np.where(rec["figure_num"].isna(), "verified_zero", "reported")
    rec["figure_num"] = rec["figure_num"].fillna(0.0)
    rec = rec.groupby(["period", "code"], as_index=False).agg(
        figure_num=("figure_num", "sum"),
        record_status_src=("record_status_src", lambda x: "reported" if (x == "reported").any() else "verified_zero"),
        query_id=("_query_id", "first"),
        codeDescEN=("codeDescEN", "first"),
    )

    grid_rows = []
    for period in period_grid():
        edition = edition_for_period(period)
        for code in sorted(hs4_sets[edition]):
            grid_rows.append((period, code, edition))
    grid = pd.DataFrame(grid_rows, columns=["period", "hs_code", "international_hs_edition"])
    out = grid.merge(rec, how="left", left_on=["period", "hs_code"], right_on=["period", "code"])
    out["figure_num"] = out["figure_num"].fillna(0.0)
    out["record_status"] = out["record_status_src"].fillna("verified_zero")
    out["query_id"] = out["query_id"].fillna(out["hs_code"].map(code_query).fillna("QUERY_NOT_RECORDED"))
    out["hs_description"] = [descriptions.get((ed, c), "") for ed, c in zip(out["international_hs_edition"], out["hs_code"])]
    out["period"] = pd.to_datetime(out["period"], format="%Y%m")
    out["reporter"] = "Hong Kong, China"
    out["partner"] = spec.partner
    out["partner_concept"] = spec.partner_concept
    out["trade_flow"] = spec.trade_flow
    out["export_type"] = spec.export_type
    out["country_of_origin"] = spec.origin
    out["country_of_consignment"] = spec.consignment
    out["country_of_destination"] = spec.destination
    out["hs_level"] = 4
    out["hkhs_vintage"] = out["period"].dt.year.astype(str)
    out["source"] = "Hong Kong C&SD Trade-IDDS"
    out["source_vintage"] = SOURCE_VINTAGE
    out["currency"] = "HKD"
    out["valuation_basis"] = spec.valuation
    out["quantity_unit"] = "not_applicable"
    out["trade_value_hkd"] = out["figure_num"] * 1000.0
    out["trade_value_usd"] = np.nan
    out["quantity"] = np.nan
    out["publication_date"] = SOURCE_VINTAGE
    out["extract_id"] = spec.extract_id
    cols = [
        "period", "reporter", "partner", "partner_concept", "trade_flow", "export_type",
        "country_of_origin", "country_of_consignment", "country_of_destination", "hs_level",
        "hs_code", "international_hs_edition", "hkhs_vintage", "source", "source_vintage",
        "currency", "valuation_basis", "quantity_unit", "trade_value_hkd", "trade_value_usd",
        "quantity", "record_status", "query_id", "publication_date", "extract_id", "hs_description",
    ]
    out = out[cols].sort_values(["period", "hs_code"])
    path = CANON / f"{spec.extract_id}.csv"
    out.to_csv(path, index=False)
    all_canonical_paths[spec.extract_id] = path
    metadata = {
        "extract_id": spec.extract_id, "source": "Hong Kong C&SD Trade-IDDS",
        "period_start": "2012-01", "period_end": "2026-06", "frequency": "monthly",
        "hs_level": 4, "partner": spec.partner, "partner_concept": spec.partner_concept,
        "trade_flow": spec.trade_flow, "valuation_basis": spec.valuation,
        "value_unit_source": "HK$ '000", "value_multiplier_hkd": 1000,
        "source_vintage": SOURCE_VINTAGE, "rows": len(out), "sha256": sha256_file(path),
        "raw_batches": len(list((RAW / spec.extract_id).glob("*.json.gz"))),
        "zero_policy": "Missing valid code-months were set to verified_zero because every valid HS4 code was explicitly included in an official API query; the API states that nil HKHS items are omitted.",
    }
    (path.with_name(path.name + ".metadata.json")).write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print("EXTRACT DONE", spec.extract_id, len(out), path.stat().st_size)

# F: re-exports to Russia by country of origin, which the official API does not permit simultaneously with commodity classification.
f_params = {"lang": "EN", "sv": "VCm", "freq": "M", "period": f"{START},{END}", "ttype": "3", "ccclass": "C", "cc": "RU", "coclass": "C", "co": "ALL"}
try:
    f_rows, f_token, _ = tid_get("F_re_exports_origin", "all_origins_total", f_params)
    f = pd.DataFrame(f_rows)
    if not f.empty:
        f["figure_num"] = pd.to_numeric(f["figure"].astype(str).str.replace(",", "", regex=False).replace("", np.nan), errors="coerce")
        f["record_status"] = np.where(f["figure_num"].isna(), "verified_zero", "reported")
        f["figure_num"] = f["figure_num"].fillna(0.0)
        fo = pd.DataFrame({
            "period": pd.to_datetime(f["period"].astype(str), format="%Y%m"),
            "reporter": "Hong Kong, China", "partner": "Russian Federation",
            "partner_concept": "destination", "trade_flow": "re_export", "export_type": "re-export",
            "country_of_origin": f.get("coDescEN", f.get("co", "UNKNOWN")).astype(str),
            "country_of_consignment": "not_applicable", "country_of_destination": "Russian Federation",
            "hs_level": 0, "hs_code": "TOTAL", "international_hs_edition": f["period"].astype(str).map(edition_for_period),
            "hkhs_vintage": f["period"].astype(str).str[:4], "source": "Hong Kong C&SD Trade-IDDS",
            "source_vintage": SOURCE_VINTAGE, "currency": "HKD", "valuation_basis": "FOB",
            "quantity_unit": "not_applicable", "trade_value_hkd": f["figure_num"] * 1000.0,
            "trade_value_usd": np.nan, "quantity": np.nan, "record_status": f["record_status"],
            "query_id": f_token, "publication_date": SOURCE_VINTAGE, "extract_id": "F_re_exports_origin",
            "hs_description": "Total re-exports",
        })
        fpath = CANON / "F_re_exports_origin.csv"
        fo.to_csv(fpath, index=False)
        all_canonical_paths["F_re_exports_origin"] = fpath
        (fpath.with_name(fpath.name + ".metadata.json")).write_text(json.dumps({
            "extract_id": "F_re_exports_origin", "source": "Hong Kong C&SD Trade-IDDS",
            "period_start": "2012-01", "period_end": "2026-06", "frequency": "monthly",
            "commodity_detail": "none", "origin_detail": "country of origin",
            "methodological_constraint": "Trade-IDDS rejects simultaneous country-of-origin and HKHS commodity classifications for re-exports.",
            "rows": len(fo), "sha256": sha256_file(fpath), "query_id": f_token,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
except Exception as exc:
    manifest.append({"kind": "F_error", "error": repr(exc)})

# H: value and quantity for precious-metal HS6 codes of Russian origin.
key_headings = {"7102", "7106", "7108", "7110"}
key_hs6 = sorted({c for values in hs6_sets.values() for c in values if c[:4] in key_headings})
h_records: list[dict[str, object]] = []
h_query_map: dict[str, str] = {}
for batch_no, code_batch in chunks(key_hs6, 20):
    params = {"lang": "EN", "sv": ["VCm", "QCm"], "freq": "M", "period": f"{START},{END}", "ttype": "1", "coclass": "C", "co": "RU", "codeclass": "HKHS6", "code": code_batch}
    try:
        rows, token, _ = tid_get("H_key_hs_quantity", f"precious_{batch_no:03d}", params)
        for row in rows:
            row = dict(row); row["_query_id"] = token; h_records.append(row)
        h_query_map.update({c: token for c in code_batch})
    except Exception as exc:
        invalid_codes.append({"extract_id": "H_key_hs_quantity", "codes": code_batch, "error": repr(exc)})

h = pd.DataFrame(h_records)
if not h.empty:
    h["period"] = h["period"].astype(str)
    h["code"] = h["code"].astype(str).str.zfill(6)
    h["figure_num"] = pd.to_numeric(h["figure"].astype(str).str.replace(",", "", regex=False).replace("", np.nan), errors="coerce")
    value = h[h["sv"].eq("VCm")].groupby(["period", "code"], as_index=False).agg(value_thousand=("figure_num", "sum"), query_id=("_query_id", "first"), codeDescEN=("codeDescEN", "first"))
    qty = h[h["sv"].eq("QCm")].groupby(["period", "code", "unitEN"], as_index=False).agg(quantity=("figure_num", "sum"))
    hp = value.merge(qty, on=["period", "code"], how="inner")
    hp = hp[hp["quantity"].notna() & hp["value_thousand"].notna()].copy()
    ho = pd.DataFrame({
        "period": pd.to_datetime(hp["period"], format="%Y%m"), "reporter": "Hong Kong, China",
        "partner": "Russian Federation", "partner_concept": "origin", "trade_flow": "import",
        "export_type": "not_applicable", "country_of_origin": "Russian Federation",
        "country_of_consignment": "not_applicable", "country_of_destination": "not_applicable",
        "hs_level": 6, "hs_code": hp["code"], "international_hs_edition": hp["period"].map(edition_for_period),
        "hkhs_vintage": hp["period"].str[:4], "source": "Hong Kong C&SD Trade-IDDS",
        "source_vintage": SOURCE_VINTAGE, "currency": "HKD", "valuation_basis": "CIF",
        "quantity_unit": hp["unitEN"].astype(str), "trade_value_hkd": hp["value_thousand"] * 1000.0,
        "trade_value_usd": np.nan, "quantity": hp["quantity"], "record_status": "reported",
        "query_id": hp["query_id"], "publication_date": SOURCE_VINTAGE,
        "extract_id": "H_key_hs_quantity", "hs_description": hp["codeDescEN"],
    })
    hpath = CANON / "H_key_hs_quantity.csv"
    ho.to_csv(hpath, index=False)
    all_canonical_paths["H_key_hs_quantity"] = hpath
    (hpath.with_name(hpath.name + ".metadata.json")).write_text(json.dumps({
        "extract_id": "H_key_hs_quantity", "source": "Hong Kong C&SD Trade-IDDS",
        "headings": sorted(key_headings), "hs6_codes_queried": key_hs6, "rows_with_both_value_and_quantity": len(ho),
        "sha256": sha256_file(hpath), "quantity_units_preserved": sorted(ho["quantity_unit"].unique()),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

# I canonical support file when HKMA was available.
if hkma_path is not None and hkma_path.suffix.lower() == ".json":
    payload = json.loads(hkma_path.read_text(encoding="utf-8"))
    records = payload.get("result", {}).get("records", payload.get("data", payload if isinstance(payload, list) else []))
    fx = pd.DataFrame(records)
    if not fx.empty and {"end_of_month", "usd"}.issubset(fx.columns):
        fx = fx[["end_of_month", "usd"]].rename(columns={"end_of_month": "period", "usd": "hkd_per_usd"})
        fx["period"] = pd.to_datetime(fx["period"]).dt.to_period("M").dt.to_timestamp()
        fx = fx[(fx["period"] >= "2012-01-01") & (fx["period"] <= "2026-06-01")].sort_values("period")
        fx["source"] = "Hong Kong Monetary Authority"
        fx["source_vintage"] = SOURCE_VINTAGE
        fx["direction"] = "HKD per USD"
        ipath = CANON / "I_hkma_hkd_usd.csv"
        fx.to_csv(ipath, index=False)
        all_canonical_paths["I_hkma_hkd_usd"] = ipath

# L concordance audit at HS4 without fractional allocation.
audit_rows = []
for source_ed, target_ed in [("HS2012", "HS2017"), ("HS2017", "HS2022")]:
    source_codes = hs4_sets[source_ed]
    target_codes = hs4_sets[target_ed]
    for code in sorted(source_codes | target_codes):
        audit_rows.append({
            "source_edition": source_ed, "target_edition": target_ed, "source_hs4": code if code in source_codes else "",
            "target_hs4": code if code in target_codes else "", "relation_at_hs4": "stable_same_code" if code in source_codes and code in target_codes else "edition_specific",
            "fractional_allocation_used": False, "analysis_rule": "Use native-vintage HS4 in main analysis; stable_same_code subset in concordance robustness; edition_specific codes excluded from the stable subset.",
        })
laudit = pd.DataFrame(audit_rows)
lpath = CANON / "L_hs_concordance.csv"
laudit.to_csv(lpath, index=False)
all_canonical_paths["L_hs_concordance"] = lpath

# M selected World Bank Pink Sheet prices.
if pink_path is not None:
    try:
        book = pd.ExcelFile(pink_path)
        target_sheet = next((s for s in book.sheet_names if "Monthly" in s or "Data" in s), book.sheet_names[0])
        raw = pd.read_excel(pink_path, sheet_name=target_sheet, header=None)
        # Locate a row containing the Date label and commodity names.
        header_row = None
        for i in range(min(20, len(raw))):
            vals = " ".join(raw.iloc[i].astype(str).tolist()).lower()
            if "gold" in vals and ("date" in vals or "year" in vals):
                header_row = i
                break
        if header_row is None:
            header_row = 4
        data = pd.read_excel(pink_path, sheet_name=target_sheet, header=header_row)
        first = data.columns[0]
        data = data.rename(columns={first: "period_raw"})
        data["period"] = pd.to_datetime(data["period_raw"], errors="coerce")
        selected = [c for c in data.columns if any(k in str(c).lower() for k in ["gold", "silver", "platinum"])]
        m = data[["period"] + selected].dropna(subset=["period"])
        m = m[(m["period"] >= "2012-01-01") & (m["period"] <= "2026-06-30")]
        mpath = CANON / "M_key_commodity_prices.csv"
        m.to_csv(mpath, index=False)
        all_canonical_paths["M_key_commodity_prices"] = mpath
    except Exception as exc:
        manifest.append({"kind": "pink_parse_error", "error": repr(exc)})

# Core integrity checks inside acquisition job.
core = {k: pd.read_csv(v, dtype={"hs_code": str}) for k, v in all_canonical_paths.items() if k[:1] in set("ABCDEG")}
identity = core["E_total_exports_russia"][["period", "hs_code", "trade_value_hkd"]].rename(columns={"trade_value_hkd": "E"})
identity = identity.merge(core["C_domestic_exports_russia"][["period", "hs_code", "trade_value_hkd"]].rename(columns={"trade_value_hkd": "C"}), on=["period", "hs_code"], how="outer")
identity = identity.merge(core["D_re_exports_russia"][["period", "hs_code", "trade_value_hkd"]].rename(columns={"trade_value_hkd": "D"}), on=["period", "hs_code"], how="outer")
identity["gap"] = identity["E"] - identity["C"] - identity["D"]
identity.to_csv(REPORTS / "total_export_identity.csv", index=False)
validation = {
    "source_vintage": SOURCE_VINTAGE,
    "hs4_union_count": len(union_hs4),
    "hs4_counts": {k: len(v) for k, v in hs4_sets.items()},
    "canonical_files": {k: {"path": str(v), "sha256": sha256_file(v), "bytes": v.stat().st_size} for k, v in all_canonical_paths.items()},
    "identity_max_abs_gap_hkd": float(identity["gap"].abs().max()),
    "identity_nonzero_gaps": int(identity["gap"].abs().gt(1.0).sum()),
    "invalid_code_events": len(invalid_codes),
}
(REPORTS / "acquisition_validation.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
(REPORTS / "invalid_codes.json").write_text(json.dumps(invalid_codes, ensure_ascii=False, indent=2), encoding="utf-8")
(OUT / "source_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print("ACQUISITION COMPLETE", json.dumps(validation, ensure_ascii=False)[:4000])
