"""Собирает демо-страницу бота: данные каркаса (dannye_karkas.py) → shablon2.html.

    python3 demo/sobrat_demo.py <karkas.json> <выход.html>
"""
import json
import sys
from pathlib import Path

POLYA = ['imya', 'put', 'rassh', 'arhiv', 'tip', 'zona', 'rol', 'semya', 'nazvanie', 'otkuda', 'p', 'd', 's', 'u',
         'tema', 'aktualno', 'versiy', 'formaty', 'zamenen_paketom']
d = json.load(open(sys.argv[1]))
d['faily'] = [{k: f[k] for k in POLYA if f.get(k) not in (None, '', [])} for f in d['faily']]
for f in d['faily']:
    f.setdefault('aktualno', 0); f.setdefault('zona', ''); f.setdefault('d', '')
html = (Path(__file__).parent / 'shablon2.html').read_text()
dat = json.dumps(d, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
Path(sys.argv[2]).write_text(html.replace('__DATA__', dat))
print(len(html) // 1024 + len(dat) // 1024, 'KB')
