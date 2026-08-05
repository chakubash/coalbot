from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

OUT = Path("research_output/hk_monetary_supplemental")
OUT.mkdir(parents=True, exist_ok=True)

FILES = {
    "hkma_hkab_compiled_master.csv": "https://raw.githubusercontent.com/RianMehta21/hkd-peg-analysis/15e35810f4394c52492a2d8c0f9fc2e9b15b116d/data/master.csv",
    "hkma_hibor_3m_monthly.csv": "https://raw.githubusercontent.com/coolwg-dev/Funding-Stress-and-Housing-Market-model-replication/a5376295c365b4a5d657e8c7f82376e6d1d8e27b/data/raw/hkma_hibor.csv",
    "hk_housing_index_replication.csv": "https://raw.githubusercontent.com/coolwg-dev/Funding-Stress-and-Housing-Market-model-replication/a5376295c365b4a5d657e8c7f82376e6d1d8e27b/data/raw/hk_housing_index.csv",
    "hkma_res_mortgage_survey_replication.csv": "https://raw.githubusercontent.com/coolwg-dev/Funding-Stress-and-Housing-Market-model-replication/a5376295c365b4a5d657e8c7f82376e6d1d8e27b/data/raw/hkma_res_mortgage_survey.csv",
    "hk_transactions_domestic_replication.csv": "https://raw.githubusercontent.com/coolwg-dev/Funding-Stress-and-Housing-Market-model-replication/a5376295c365b4a5d657e8c7f82376e6d1d8e27b/data/raw/hk_transactions_domestic.csv",
}

s = requests.Session()
s.headers.update({"User-Agent": "AcademicResearchBot/1.0"})
manifest = []
for filename, url in FILES.items():
    rec = {"file": filename, "url": url, "retrieved_utc": datetime.now(timezone.utc).isoformat()}
    try:
        r = s.get(url, timeout=60)
        r.raise_for_status()
        data = r.content
        if len(data) < 20:
            raise ValueError("response too small")
        (OUT / filename).write_bytes(data)
        rec.update({"status": "ok", "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    except Exception as exc:
        rec.update({"status": "failed", "error": repr(exc)})
    print(json.dumps(rec, ensure_ascii=False), flush=True)
    manifest.append(rec)

(OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
