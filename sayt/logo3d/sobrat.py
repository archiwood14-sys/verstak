"""Собирает страницу 3D-логотипа: вставляет данные барельефа (relief.py) в shablon.html → index.html."""
import json
from pathlib import Path
here = Path(__file__).parent
info = (here / 'relief.json').read_text()
svgs = {n: (here / f'{n}.svg').read_text() for n in ('kolesnica', 'liniya', 'nadpis', 'gorod')}
html = (here / 'shablon.html').read_text()
html = html.replace('__INFO__', info).replace('__SVGS__', json.dumps(svgs))
(here / 'index.html').write_text(html)
print('index.html', len(html) // 1024, 'KB')
