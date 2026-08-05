from pathlib import Path
import hashlib, json
import requests

out = Path('research_output/bauer_swanson')
out.mkdir(parents=True, exist_ok=True)
url = 'https://www.frbsf.org/wp-content/uploads/monetary-policy-surprises-data.xlsx'
r = requests.get(url, timeout=90, headers={'User-Agent':'AcademicResearchBot/1.0'})
r.raise_for_status()
path = out / 'monetary-policy-surprises-data.xlsx'
path.write_bytes(r.content)
meta = {'url': url, 'bytes': len(r.content), 'sha256': hashlib.sha256(r.content).hexdigest()}
(out / 'manifest.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
print(meta)
