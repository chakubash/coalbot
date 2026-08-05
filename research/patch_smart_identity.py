from pathlib import Path
p=Path('research/russia_hk_smart_extract.py')
s=p.read_text(encoding='utf-8')
old="codes={ed:set(e.loc[(e.international_hs_edition==ed)&(e.trade_value_hkd>0),'hs_code']) for ed in START_END};make_extract(spec['C'][1],spec['C'][0],*spec['C'][2:],active=act,restrict_codes=codes);make_extract(spec['D'][1],spec['D'][0],*spec['D'][2:],active=act,restrict_codes=codes)"
new="make_extract(spec['C'][1],spec['C'][0],*spec['C'][2:],active=act);make_extract(spec['D'][1],spec['D'][0],*spec['D'][2:],active=act)"
if old not in s: raise SystemExit('identity patch target not found')
p.write_text(s.replace(old,new),encoding='utf-8')
print('C/D grids aligned to E full HS4 universe')
