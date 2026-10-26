"""Переводит PNG-логотип в векторный SVG (для 3D и для сайта)."""
from PIL import Image, ImageFilter
import numpy as np, potrace, sys
SRC = sys.argv[1] if len(sys.argv) > 1 else '/home/user/verstak/ilinka/logo.png'
im = Image.open(SRC).convert('RGBA')
a = im.split()[3]
S = 6
big = a.resize((a.width * S, a.height * S), Image.LANCZOS).filter(ImageFilter.GaussianBlur(2.2))
arr = np.array(big)
bmp = potrace.Bitmap(arr <= 110)  # potracer считает рисунком значения False
path = bmp.trace(turdsize=30, alphamax=1.0, opticurve=True, opttolerance=0.3)
W, H = big.size
parts = []
for curve in path:
    s = curve.start_point
    d = [f"M{s.x:.1f},{s.y:.1f}"]
    for seg in curve.segments:
        if seg.is_corner:
            d.append(f"L{seg.c.x:.1f},{seg.c.y:.1f}L{seg.end_point.x:.1f},{seg.end_point.y:.1f}")
        else:
            d.append(f"C{seg.c1.x:.1f},{seg.c1.y:.1f} {seg.c2.x:.1f},{seg.c2.y:.1f} {seg.end_point.x:.1f},{seg.end_point.y:.1f}")
    d.append("Z")
    parts.append("".join(d))
d = " ".join(parts)
open('logo.svg', 'w').write(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W // S * 2}" height="{H // S * 2}"><path fill="#c18048" fill-rule="evenodd" d="{d}"/></svg>')
print(len(path), 'контуров')
