"""Готовит логотип Archiwood для 3D как барельеф (как на медали).

Из PNG-логотипа делает:
  kolesnica-*.png — колесница с конями: карта высот (каждая часть рисунка
                    выпуклая и скругленная), нормали, маска патины в бороздках
                    и силуэт;
  kolesnica.svg   — внешний силуэт колесницы (основание барельефа);
  liniya.svg, nadpis.svg, gorod.svg — линия земли, ARCHIWOOD, St.PETERSBURG
                    (буквы выдавливаются отдельно, с гранёной фаской);
  relief.json     — размеры и положение частей.

    python3 sayt/logo3d/relief.py
"""
import json
from pathlib import Path

import numpy as np
import potrace
from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).parent
SRC = Path('/home/user/verstak/ilinka/logo.png')
S = 8            # увеличение исходника перед обработкой
R = 26           # радиус скругления выпуклостей, px увеличенного рисунка
MAX_W = 2048     # ширина текстур колесницы


def mask_from_png():
    a = Image.open(SRC).convert('RGBA').split()[3]
    big = a.resize((a.width * S, a.height * S), Image.LANCZOS).filter(ImageFilter.GaussianBlur(S * 0.35))
    return np.array(big) > 110


def bands(m):
    """Границы по высоте: колесница, линия земли, ARCHIWOOD, St.PETERSBURG."""
    def longest(row):
        best = cur = 0
        for v in row:
            cur = cur + 1 if v else 0
            best = max(best, cur)
        return best
    W = m.shape[1]
    # линия земли — строки со сплошным отрезком длиннее 40% ширины
    ys = [y for y in range(m.shape[0]) if m[y].any() and longest(m[y]) > 0.4 * W]
    line = (ys[0], ys[-1] + 1)

    def runs(y0, y1):
        on = m[y0:y1].any(1)
        out, y = [], 0
        while y < len(on):
            if on[y]:
                a = y
                while y < len(on) and on[y]:
                    y += 1
                out.append((y0 + a, y0 + y))
            y += 1
        return out
    above = runs(0, line[0])
    # отсекаем тонкие полоски сглаживания у линии земли
    below = [r for r in runs(line[1], m.shape[0]) if r[1] - r[0] > 0.02 * m.shape[0]]
    nad = max(below, key=lambda r: r[1] - r[0])
    return (above[0][0], above[-1][1]), line, nad, below[-1]


def trace(mask, name, offset):
    """Векторизация маски в SVG-путь (координаты всего логотипа)."""
    path = potrace.Bitmap(~mask).trace(turdsize=40, alphamax=1.0, opticurve=True, opttolerance=0.25)
    ox, oy = offset
    parts = []
    for c in path:
        d = [f'M{c.start_point.x + ox:.1f},{c.start_point.y + oy:.1f}']
        for s in c.segments:
            if s.is_corner:
                d.append(f'L{s.c.x + ox:.1f},{s.c.y + oy:.1f}L{s.end_point.x + ox:.1f},{s.end_point.y + oy:.1f}')
            else:
                d.append(f'C{s.c1.x + ox:.1f},{s.c1.y + oy:.1f} {s.c2.x + ox:.1f},{s.c2.y + oy:.1f} {s.end_point.x + ox:.1f},{s.end_point.y + oy:.1f}')
        d.append('Z')
        parts.append(''.join(d))
    (HERE / f'{name}.svg').write_text(f'<svg xmlns="http://www.w3.org/2000/svg"><path d="{" ".join(parts)}"/></svg>')
    return len(path)


def fill_holes(m):
    """Заливает внутренние просветы: снаружи заливка от края, всё остальное — тело."""
    pad = np.pad(~m, 2, constant_values=True)
    img = Image.fromarray((pad * 255).astype(np.uint8)).copy()  # copy: иначе floodfill не меняет картинку
    ImageDraw.floodfill(img, (0, 0), 128)
    outside = np.array(img)[2:-2, 2:-2] == 128
    return ~outside


def chamfer_distance(m, cap):
    """Расстояние до ближайшего «пустого» пикселя (просвета или края), не дальше cap."""
    d = np.where(m, float(cap), 0.0)
    steps = [(0, 1, 1), (0, -1, 1), (1, 0, 1), (-1, 0, 1), (1, 1, 1.414), (1, -1, 1.414), (-1, 1, 1.414), (-1, -1, 1.414)]
    for _ in range(int(cap * 1.5) + 2):
        prev = d
        for dy, dx, w in steps:
            sh = np.full_like(d, float(cap))
            ys = slice(max(dy, 0), d.shape[0] + min(dy, 0))
            yd = slice(max(-dy, 0), d.shape[0] + min(-dy, 0))
            xs = slice(max(dx, 0), d.shape[1] + min(dx, 0))
            xd = slice(max(-dx, 0), d.shape[1] + min(-dx, 0))
            sh[ys, xs] = d[yd, xd] + w
            d = np.minimum(d, sh)
        if np.array_equal(d, prev):
            break
    return np.minimum(d, cap)


def save_gray(arr, name, size):
    Image.fromarray(np.clip(arr * 255, 0, 255).astype(np.uint8)).resize(size, Image.LANCZOS).save(HERE / name, optimize=True)


def main():
    m = mask_from_png()
    H, W = m.shape
    (c0, c1), line, txt, city = bands(m)

    # ---- колесница: барельеф ----
    pad = 6
    cm = m[max(0, c0 - pad):c1 + pad]
    cols = np.where(cm.any(0))[0]
    x0, x1 = max(0, cols[0] - pad), min(W, cols[-1] + pad)
    cm = cm[:, x0:x1]
    oy = max(0, c0 - pad)
    filled = fill_holes(cm)
    # Широкие просветы (между спицами колеса, под рукой) оставляем сквозными,
    # заливаем только тонкие линии рисунка — они станут бороздками.
    hole = filled & ~cm
    core = chamfer_distance(hole, 14) >= 11
    near_core = chamfer_distance(~core, 14) <= 12
    filled = filled & ~(hole & (core | near_core))

    d = chamfer_distance(cm, R) / R                       # 0 у края и в бороздках, 1 в глубине
    h = np.sqrt(np.clip(1 - (1 - d) ** 2, 0, 1))           # скругленный профиль, как подушка
    h = np.where(filled & ~cm, 0.06, h)                    # дно бороздки
    hb = np.array(Image.fromarray((h * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.2)), dtype=np.float32) / 255

    gy, gx = np.gradient(hb * 9.0)                         # нормали из высот
    n = np.dstack([-gx, gy, np.ones_like(hb)])
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    normal = ((n * 0.5 + 0.5) * 255).astype(np.uint8)

    cavity = 0.28 + 0.72 * np.clip(hb / 0.55, 0, 1) ** 0.8  # патина: бороздки темнее
    cavity = np.where(filled, cavity, 1.0)

    th = round((cm.shape[0]) * MAX_W / cm.shape[1])
    size = (MAX_W, th)
    save_gray(hb, 'kolesnica-vysota.png', size)
    save_gray(cavity, 'kolesnica-patina.png', size)
    save_gray(filled.astype(np.float32), 'kolesnica-silhuet.png', size)
    Image.fromarray(normal).resize(size, Image.LANCZOS).save(HERE / 'kolesnica-normali.png', optimize=True)
    n_ch = trace(filled, 'kolesnica', (x0, oy))

    # ---- линия и надписи: обычные контуры ----
    out = {}
    for name, (a, b) in (('liniya', line), ('nadpis', txt), ('gorod', city)):
        sub = np.zeros_like(m)
        sub[a:b] = m[a:b]
        out[name] = trace(sub[max(0, a - 4):b + 4], name, (0, max(0, a - 4)))

    info = {
        'width': W, 'height': H,
        'kolesnica': {'x': int(x0), 'y': int(oy), 'w': int(cm.shape[1]), 'h': int(cm.shape[0]), 'tex': list(size), 'contours': n_ch},
        'contours': out,
    }
    (HERE / 'relief.json').write_text(json.dumps(info, ensure_ascii=False, indent=1))
    print(json.dumps(info, ensure_ascii=False))


if __name__ == '__main__':
    main()
