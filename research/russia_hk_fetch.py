from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlencode, urljoin

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

OUT = Path('research/discovery_output')
OUT.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.headers.update({
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
})

manifest = []

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def save_response(name: str, response: requests.Response) -> None:
    suffix = '.bin'
    ct = response.headers.get('content-type', '')
    if 'json' in ct:
        suffix = '.json'
    elif 'html' in ct or response.text.lstrip().startswith('<'):
        suffix = '.html'
    elif 'pdf' in ct or response.content[:4] == b'%PDF':
        suffix = '.pdf'
    path = OUT / f'{name}{suffix}'
    path.write_bytes(response.content)
    (OUT / f'{name}.headers.json').write_text(json.dumps(dict(response.headers), indent=2), encoding='utf-8')
    manifest.append({
        'name': name,
        'url': response.url,
        'status': response.status_code,
        'content_type': ct,
        'bytes': len(response.content),
        'sha256': sha256(response.content),
        'file': str(path),
        'history': [h.status_code for h in response.history],
    })

def get(name: str, url: str, **kwargs) -> requests.Response | None:
    try:
        r = SESSION.get(url, timeout=90, allow_redirects=True, **kwargs)
        save_response(name, r)
        print(name, r.status_code, r.url, len(r.content), r.headers.get('content-type'))
        return r
    except Exception as exc:
        (OUT / f'{name}.error.txt').write_text(repr(exc), encoding='utf-8')
        manifest.append({'name': name, 'url': url, 'error': repr(exc)})
        print(name, 'ERROR', repr(exc))
        return None

# 1. Trade-IDDS bootstrap, documentation, page assets.
index = get('tradeidds_index', 'https://tradeidds.censtatd.gov.hk/Index/ceb455b8811d4b49acd147f01382540c', verify=False)
get('tradeidds_api_spec', 'https://tradeidds.censtatd.gov.hk/MetadataLink/ApiSpec/API_eng.pdf', verify=False)
get('tradeidds_common_total_exports', 'https://tradeidds.censtatd.gov.hk/CommonTable/ETR10_TX', verify=False)
get('tradeidds_common_imports', 'https://tradeidds.censtatd.gov.hk/CommonTable/ETR10_IM', verify=False)

if index is not None:
    soup = BeautifulSoup(index.text, 'html.parser')
    assets = []
    for tag, attr in [('script', 'src'), ('link', 'href')]:
        for el in soup.find_all(tag):
            value = el.get(attr)
            if value and not value.startswith('data:'):
                full = urljoin(index.url, value)
                if full.startswith('https://tradeidds.censtatd.gov.hk'):
                    assets.append(full)
    (OUT / 'tradeidds_assets.txt').write_text('\n'.join(dict.fromkeys(assets)), encoding='utf-8')
    for i, url in enumerate(dict.fromkeys(assets)):
        if i >= 80:
            break
        get(f'tradeidds_asset_{i:03d}', url, verify=False)

# 2. Trade-IDDS API tests. Base examples and plausible country filters.
base = 'https://tradeidds.censtatd.gov.hk/api/get'
queries = {
    'api_world_hs8542_tx': dict(lang='EN', sv='VCm', freq='M', period='202501,202502', ttype='4', codeclass='HKHS4', code='8542'),
    'api_world_total_tx': dict(lang='EN', sv='VCm', freq='M', period='202501,202502', ttype='4'),
    'api_ru_hs8542_tx_co': dict(lang='EN', sv='VCm', freq='M', period='202501,202502', ttype='4', codeclass='HKHS4', code='8542', co='RU'),
    'api_ru_hs8542_tx_country': dict(lang='EN', sv='VCm', freq='M', period='202501,202502', ttype='4', codeclass='HKHS4', code='8542', country='RU'),
    'api_ru_hs8542_tx_partner': dict(lang='EN', sv='VCm', freq='M', period='202501,202502', ttype='4', codeclass='HKHS4', code='8542', partner='RU'),
    'api_ru_total_tx_co': dict(lang='EN', sv='VCm', freq='M', period='202501,202502', ttype='4', co='RU'),
    'api_ru_total_import_co': dict(lang='EN', sv='VCm', freq='M', period='202501,202502', ttype='1', co='RU'),
    'api_ru_hs7108_import_co': dict(lang='EN', sv='VCm', freq='M', period='202501,202502', ttype='1', codeclass='HKHS4', code='7108', co='RU'),
}
for name, params in queries.items():
    get(name, base + '?' + urlencode(params), verify=False)

# Extract text from API PDF when available.
pdf_path = OUT / 'tradeidds_api_spec.pdf'
if pdf_path.exists():
    try:
        reader = PdfReader(str(pdf_path))
        text = '\n'.join(page.extract_text() or '' for page in reader.pages)
        (OUT / 'tradeidds_api_spec.txt').write_text(text, encoding='utf-8')
    except Exception as exc:
        (OUT / 'tradeidds_api_spec_parse.error.txt').write_text(repr(exc), encoding='utf-8')

# 3. HKMA official monthly average exchange rate.
hkma = 'https://api.hkma.gov.hk/public/market-data-and-statistics/monthly-statistical-bulletin/er-ir/er-eeri-periodaverage?pagesize=1000&offset=0'
get('hkma_periodaverage', hkma)

# 4. UN Comtrade preview tests for one month and different aggregation levels.
ct_base = 'https://comtradeapi.un.org/public/v1/preview/C/M/HS'
ct_queries = {
    'comtrade_hk_import_ru_total_202501': dict(reporterCode='344', period='202501', cmdCode='TOTAL', flowCode='M', partnerCode='643', maxRecords='500', includeDesc='true'),
    'comtrade_hk_export_ru_total_202501': dict(reporterCode='344', period='202501', cmdCode='TOTAL', flowCode='X', partnerCode='643', maxRecords='500', includeDesc='true'),
    'comtrade_ru_export_hk_total_202501': dict(reporterCode='643', period='202501', cmdCode='TOTAL', flowCode='X', partnerCode='344', maxRecords='500', includeDesc='true'),
    'comtrade_ru_import_hk_total_202501': dict(reporterCode='643', period='202501', cmdCode='TOTAL', flowCode='M', partnerCode='344', maxRecords='500', includeDesc='true'),
    'comtrade_hk_import_ru_hs71_202501': dict(reporterCode='344', period='202501', cmdCode='71', flowCode='M', partnerCode='643', maxRecords='500', includeDesc='true'),
    'comtrade_hk_import_ru_hs7108_202501': dict(reporterCode='344', period='202501', cmdCode='7108', flowCode='M', partnerCode='643', maxRecords='500', includeDesc='true'),
}
for name, params in ct_queries.items():
    get(name, ct_base + '?' + urlencode(params))

# 5. Official source landing pages / likely downloadable resources.
get('data_gov_tradeidds', 'https://data.gov.hk/en-data/dataset/hk-censtatd-trade-idds-trade')
get('hkma_docs', 'https://apidocs.hkma.gov.hk/documentation/market-data-and-statistics/monthly-statistical-bulletin/er-ir/er-eeri-periodaverage/')
get('un_comtrade_docs', 'https://uncomtrade.org/docs/un-comtrade-api/')
get('unsd_classifications', 'https://unstats.un.org/unsd/classifications/Econ')
get('worldbank_pinksheet_page', 'https://www.worldbank.org/en/research/commodity-markets')

(OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
print('saved', len(manifest), 'responses')
