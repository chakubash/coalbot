from pathlib import Path
p=Path('research/russia_hk_smart_extract.py')
s=p.read_text(encoding='utf-8')
repls={
"a=make_extract(*spec['A'][1:],extra=spec['A'][0],active=a_act)":"a=make_extract(spec['A'][1],spec['A'][0],*spec['A'][2:],active=a_act)",
"make_extract(*spec['B'][1:],extra=spec['B'][0],active=act)":"make_extract(spec['B'][1],spec['B'][0],*spec['B'][2:],active=act)",
"e=make_extract(*spec['E'][1:],extra=spec['E'][0],active=act)":"e=make_extract(spec['E'][1],spec['E'][0],*spec['E'][2:],active=act)",
"make_extract(*spec['C'][1:],extra=spec['C'][0],active=act,restrict_codes=codes)":"make_extract(spec['C'][1],spec['C'][0],*spec['C'][2:],active=act,restrict_codes=codes)",
"make_extract(*spec['D'][1:],extra=spec['D'][0],active=act,restrict_codes=codes)":"make_extract(spec['D'][1],spec['D'][0],*spec['D'][2:],active=act,restrict_codes=codes)",
}
for old,new in repls.items():
    if old not in s: raise SystemExit('missing patch target: '+old)
    s=s.replace(old,new)
p.write_text(s,encoding='utf-8')
print('smart call signatures patched')
