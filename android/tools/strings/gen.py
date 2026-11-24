"""Generates app/src/main/res/values{,-hi}/strings.xml from the string tables.
Usage: python3 gen.py <res dir> <file listing used keys>"""
import sys, os, re
sys.path.insert(0, os.path.dirname(__file__))
from strings1 import S
from strings2 import S2, GUIDE_EN, GUIDE_HI, PRIV_EN, PRIV_HI
from strings3 import S3
from strings4 import S4
from strings5 import S5
from strings6 import S6
from strings7 import S7
from strings8 import S8
from strings9 import S9
from strings10 import S10
from strings11 import S11
from strings12 import S12
from strings13 import S13
allS = S + S2 + S3 + S4 + S5 + S6 + S7 + S8 + S9 + S10 + S11 + S12 + S13
keys = [k for k,_,_ in allS]
dups = {k for k in keys if keys.count(k) > 1}
assert not dups, dups
def esc(v):
    v = v.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
    v = v.replace("'", "\\'").replace('"','\\"')
    if v.startswith('@') or v.startswith('?'): v = '\\' + v
    return v
res = sys.argv[1]
used = set(open(sys.argv[2]).read().split())
missing = used - set(keys); extra = set(keys) - used
print("missing:", sorted(missing)); print("unused:", sorted(extra))
for lang, idx, guide, priv in (("values",1,GUIDE_EN,PRIV_EN),("values-hi",2,GUIDE_HI,PRIV_HI)):
    os.makedirs(os.path.join(res, lang), exist_ok=True)
    out = ['<?xml version="1.0" encoding="utf-8"?>', '<!-- Generated from one table so English and Hindi stay in sync. -->', '<resources>']
    for t in sorted(allS):
        k = t[0]; v = t[idx]
        attr = ' translatable="false"' if (k == 'app_name' and lang == 'values-hi' and False) else ''
        if len(re.findall(r'%[ds]', v)) > 1: raise SystemExit("non-positional multi format: " + k)
        out.append(f'    <string name="{k}">{esc(v)}</string>')
    for name, arr in (("guide", guide), ("privacy", priv)):
        out.append(f'    <string-array name="{name}">')
        for line in arr: out.append(f'        <item>{esc(line)}</item>')
        out.append('    </string-array>')
    out.append('</resources>')
    open(os.path.join(res, lang, 'strings.xml'), 'w').write('\n'.join(out) + '\n')
print("written", len(allS))
