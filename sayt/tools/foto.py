"""Готовит фотографии для сайта: из исходников в папке foto/ делает легкие WebP
в нескольких размерах (для телефона и для большого экрана) в static/img/
и записывает их размеры в static/img/manifest.json.

    python3 sayt/tools/foto.py   # обрабатывает новые и измененные фото

Исходник может быть .jpg, .jpeg, .png или .webp. Если для одного места лежат
два файла (например, заглушка .jpg и ваше фото .jpeg), берется более новый.
"""
import json
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / 'foto'
OUT = ROOT / 'static' / 'img'
EXTS = ('.jpg', '.jpeg', '.png', '.webp')
WIDTHS = [800, 1600, 2400]
QUALITY = 78


def sources():
    """Ключ места (путь без расширения) -> самый новый исходник."""
    found = {}
    for p in SRC.rglob('*'):
        if p.suffix.lower() not in EXTS or not p.is_file():
            continue
        key = p.relative_to(SRC).with_suffix('').as_posix()
        if key not in found or p.stat().st_mtime > found[key].stat().st_mtime:
            found[key] = p
    return found


def main():
    widths = WIDTHS
    # Уже готовые фото остаются, даже если исходника нет (папка foto/ не хранится в git).
    mpath = OUT / 'manifest.json'
    manifest = json.loads(mpath.read_text('utf-8')) if mpath.exists() else {}
    done = 0
    found = sources()
    # Список заглушек: если на месте заглушки лежит другой файл — это уже настоящее фото.
    zpath = ROOT / 'tools' / 'zaglushki.json'
    zag = json.loads(zpath.read_text('utf-8')) if zpath.exists() else {}
    for key in list(zag):
        src = found.get(key)
        if src and (src != SRC / f'{key}.jpg' or abs(src.stat().st_mtime - zag[key]) > 1):
            del zag[key]
    zpath.write_text(json.dumps(zag, ensure_ascii=False, indent=1), 'utf-8')
    for key, src in sorted(found.items()):
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im).convert('RGB')
            w, h = im.size
            use = [x for x in widths if x < w] + [min(w, widths[-1])]
            use = sorted(set(use))
            for tw in use:
                out = OUT / f'{key}-{tw}.webp'
                if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
                    continue
                out.parent.mkdir(parents=True, exist_ok=True)
                th = round(h * tw / w)
                im.resize((tw, th), Image.LANCZOS).save(out, 'WEBP', quality=QUALITY, method=6)
                done += 1
        manifest[key] = {'w': w, 'h': h, 'widths': use}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1), 'utf-8')
    print(f'фото: {len(manifest)}, новых файлов: {done}')


if __name__ == '__main__':
    main()
