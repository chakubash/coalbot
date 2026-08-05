from pathlib import Path

path = Path('research/russia_hk_parallel_extract.py')
text = path.read_text(encoding='utf-8')
old = "   if r.status_code==200 and (not st or st.get('name')=='Success'):\n"
new = """   msg = st.get('message', '') if isinstance(st, dict) else ''
   msg_text = ' '.join(map(str, msg)) if isinstance(msg, list) else str(msg)
   if r.status_code==200 and st.get('name')=='Fail' and 'No record found' in msg_text:
    j = {'header': {'status': {'name': 'Success'}, 'count': {'noOfRecords': 0}, 'title': j.get('header', {}).get('title')}, 'dataSet': []}
    st = j['header']['status']
   if r.status_code==200 and (not st or st.get('name')=='Success'):
"""
if old not in text:
    raise SystemExit('patch target not found')
path.write_text(text.replace(old, new, 1), encoding='utf-8')
print('empty-batch patch applied')
