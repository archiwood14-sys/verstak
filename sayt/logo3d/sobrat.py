"""Собирает страницу 3D-логотипа: вставляет logo.svg в shablon.html → index.html."""
from pathlib import Path
from urllib.parse import quote
here = Path(__file__).parent
svg = (here / 'logo.svg').read_text()
html = (here / 'shablon.html').read_text()
html = html.replace('__SVG_URI__', quote(svg)).replace('__SVG__', svg.replace('`', ''))
(here / 'index.html').write_text(html)
print('index.html', len(html) // 1024, 'KB')
