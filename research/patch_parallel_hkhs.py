from pathlib import Path

path = Path('research/russia_hk_parallel_extract.py')
text = path.read_text(encoding='utf-8')

old_empty = "   if r.status_code==200 and (not st or st.get('name')=='Success'):\n"
new_empty = """   msg = st.get('message', '') if isinstance(st, dict) else ''
   msg_text = ' '.join(map(str, msg)) if isinstance(msg, list) else str(msg)
   if r.status_code==200 and st.get('name')=='Fail' and 'No record found' in msg_text:
    j = {'header': {'status': {'name': 'Success'}, 'count': {'noOfRecords': 0}, 'title': j.get('header', {}).get('title')}, 'dataSet': []}
    st = j['header']['status']
   if r.status_code==200 and (not st or st.get('name')=='Success'):
"""
if old_empty in text:
    text = text.replace(old_empty, new_empty, 1)

old_codes = " codes_by_ed[ed]=sorted(set(codes))\n"
new_codes = " codes_by_ed[ed]=sorted(c for c in set(codes) if c != '9999')\n"
if old_codes not in text:
    raise SystemExit('code-list patch target not found')
text = text.replace(old_codes, new_codes, 1)

path.write_text(text, encoding='utf-8')
print('empty-batch and HKHS service-code patches applied')
