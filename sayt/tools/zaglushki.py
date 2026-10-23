"""Рисует фото-заглушки (выдуманные интерьеры из дерева) для всех мест на сайте.

Каждая заглушка подписана: какое это место и какого размера нужно настоящее фото.
Список мест берется из tools/sloty.json, его пишет сборка (node sayt/build.mjs).

    python3 sayt/tools/zaglushki.py          # рисует только недостающие
    python3 sayt/tools/zaglushki.py --vse    # перерисовывает все заглушки
"""
import json
import sys
import zlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FOTO = ROOT / 'foto'
FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'

WOODS = [
    (188, 140, 96),   # дуб
    (112, 76, 52),    # орех
    (214, 188, 152),  # ясень
    (160, 104, 66),   # вишня
    (140, 112, 84),   # дымчатый дуб
]
WALLS = [(236, 226, 212), (222, 214, 204), (60, 56, 52), (196, 186, 172)]


def smooth_noise(rng, h, w, cells):
    small = rng.random((max(2, h // cells), max(2, w // cells))).astype(np.float32)
    img = Image.fromarray((small * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)
    return np.asarray(img, dtype=np.float32) / 255.0


def grain(rng, h, w, freq, vertical=True):
    """Текстура древесных волокон: 0..1."""
    warp = smooth_noise(rng, h, w, 60) * 40 + smooth_noise(rng, h, w, 12) * 6
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    axis = xx if vertical else yy
    g = np.sin((axis + warp) * freq) * 0.5 + 0.5
    g = g ** 3 * 0.6 + smooth_noise(rng, h, w, 4) * 0.4
    return g


def tint(base, g, depth=0.35):
    b = np.array(base, dtype=np.float32)
    return b[None, None, :] * (1 - depth * g[..., None])


def scene(rng, w, h, kind):
    wood = WOODS[rng.integers(len(WOODS))]
    wall = WALLS[rng.integers(len(WALLS))]
    img = np.zeros((h, w, 3), dtype=np.float32)
    img[:] = wall
    floor_y = int(h * rng.uniform(0.72, 0.84))

    if kind == 'panels':
        n = int(rng.integers(5, 11))
        g = grain(rng, h, w, rng.uniform(0.05, 0.12))
        img[:floor_y] = tint(wood, g[:floor_y])
        pw = w / n
        for i in range(1, n):
            x = int(i * pw)
            img[:floor_y, max(0, x - 2):x + 1] *= 0.55
    elif kind == 'coffer':
        top = int(h * 0.38)
        g = grain(rng, h, w, 0.08, vertical=False)
        img[:top] = tint(wood, g[:top])
        cols, rows = int(rng.integers(6, 12)), 3
        for c in range(cols + 1):
            x = int(c * w / cols)
            img[:top, max(0, x - 6):x + 6] *= 0.72
        for r in range(rows + 1):
            y = int(r * top / rows)
            img[max(0, y - 5):y + 5, :] *= 0.74
        img[top:top + 8] *= 0.6
    elif kind == 'cabinet':
        g = grain(rng, h, w, rng.uniform(0.04, 0.09))
        x0, x1 = int(w * 0.08), int(w * 0.92)
        y0 = int(h * 0.12)
        img[y0:floor_y, x0:x1] = tint(wood, g[y0:floor_y, x0:x1])
        cols = int(rng.integers(3, 7))
        for c in range(cols + 1):
            x = int(x0 + c * (x1 - x0) / cols)
            img[y0:floor_y, max(0, x - 2):x + 2] *= 0.5
        mid = int(y0 + (floor_y - y0) * 0.62)
        img[mid - 2:mid + 2, x0:x1] *= 0.5
        img[y0:floor_y, x0:x0 + 10] *= 0.8
    else:  # slab — столешница крупным планом
        g = grain(rng, h, w, rng.uniform(0.03, 0.06), vertical=False)
        floor_y = int(h * 0.45)
        img[floor_y:] = tint(wood, g[floor_y:], 0.45)
        img[floor_y:floor_y + 6] *= 0.6

    if kind != 'slab':
        fg = grain(rng, h, w, 0.02, vertical=False)
        floor = tint((150, 110, 78), fg[floor_y:], 0.3)
        planks = int(rng.integers(6, 14))
        img[floor_y:] = floor
        for i in range(planks + 1):
            x = int(i * w / planks)
            img[floor_y:, max(0, x - 1):x + 1] *= 0.7

    # Свет из окна и виньетка
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    lx = rng.uniform(0.1, 0.9) * w
    light = np.exp(-(((xx - lx) / (w * 0.55)) ** 2) - ((yy / (h * 1.1)) ** 2))
    img *= (0.72 + 0.42 * light)[..., None]
    img += np.array([18, 10, 0], dtype=np.float32) * light[..., None]
    vign = 1 - 0.35 * (((xx / w - 0.5) ** 2 + (yy / h - 0.5) ** 2) * 2.2)
    img *= np.clip(vign, 0.5, 1)[..., None]
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.8))


def label(im, key, size):
    d = ImageDraw.Draw(im, 'RGBA')
    fs = max(18, min(im.width, im.height) // 34)
    font = ImageFont.truetype(FONT, fs)
    small = ImageFont.truetype(FONT, int(fs * 0.8))
    lines = [(f'ЗАГЛУШКА · {key}', font), (f'нужно фото {size}', small)]
    pad = fs // 2
    tw = max(d.textlength(t, font=f) for t, f in lines)
    th = fs + int(fs * 0.8) + pad
    x, y = int(im.width * 0.07), int(im.height * 0.12)
    d.rounded_rectangle([x - pad, y - pad, x + tw + pad, y + th + pad // 2], radius=pad // 2, fill=(20, 18, 16, 150))
    d.text((x, y), lines[0][0], font=font, fill=(250, 240, 230, 235))
    d.text((x, y + fs + pad // 2), lines[1][0], font=small, fill=(213, 170, 128, 235))


def main():
    sloty = json.loads((ROOT / 'tools' / 'sloty.json').read_text('utf-8'))
    redo = '--vse' in sys.argv
    zpath = ROOT / 'tools' / 'zaglushki.json'
    zag = json.loads(zpath.read_text('utf-8')) if zpath.exists() else {}
    made = 0
    for s in sloty:
        if s.get('optional'):
            continue
        out = FOTO / f"{s['key']}.jpg"
        exists = any((FOTO / f"{s['key']}{ext}").exists() for ext in ('.jpg', '.jpeg', '.png', '.webp'))
        if exists and not redo:
            continue
        w, h = s['w'], s['h']
        seed = zlib.crc32(s['key'].encode())
        rng = np.random.default_rng(seed)
        kinds = ['panels', 'coffer', 'cabinet', 'slab']
        im = scene(rng, w, h, kinds[seed % len(kinds)])
        label(im, s['key'], f'{w}×{h}')
        out.parent.mkdir(parents=True, exist_ok=True)
        im.save(out, quality=88)
        zag[s['key']] = out.stat().st_mtime
        made += 1
    zpath.write_text(json.dumps(zag, ensure_ascii=False, indent=1), 'utf-8')
    print(f'заглушек нарисовано: {made}')


if __name__ == '__main__':
    main()
