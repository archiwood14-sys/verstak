"""Каталог документов АРХИВУД: обходит папки проектов, почты и Telegram,
достаёт текст из документов и записывает всё в SQLite для поиска и бота.

Файлы никуда не переносятся — каталог только читает и запоминает, где что лежит.

    python3 katalog.py            # обновить каталог (только новое и изменённое)
    python3 katalog.py --zanovo   # пересобрать с нуля
    python3 katalog.py --otchet   # сколько файлов по проектам и разделам
    python3 katalog.py --nayti договор олимпийский   # проверить поиск
"""
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sqlite3
import sys
import time
import zipfile
from datetime import datetime
from html import unescape
from pathlib import Path

import poisk

N = poisk.nastroyki()
MAX_TEKST = 200_000          # символов текста с одного файла
MAX_HASH = 300 * 1024 ** 2   # файлы больше хешируем по краям

SHEMA = '''
CREATE TABLE IF NOT EXISTS faily (
  id INTEGER PRIMARY KEY,
  put TEXT UNIQUE NOT NULL,
  imya TEXT, rasshirenie TEXT, razmer INTEGER, izmenen REAL, data TEXT,
  proekt TEXT, proekt_imya TEXT, poryadok_proekta INTEGER,
  razdel TEXT, poryadok_razdela INTEGER,
  istochnik TEXT, otkogo TEXT, vnutrennee INTEGER DEFAULT 0,
  hash TEXT, dubl_of INTEGER
);
CREATE INDEX IF NOT EXISTS i_proekt ON faily(proekt, razdel, data);
CREATE INDEX IF NOT EXISTS i_hash ON faily(hash);
CREATE VIRTUAL TABLE IF NOT EXISTS tekst USING fts5(
  imya, mesto, soderzhanie, tokenize = "unicode61 remove_diacritics 2"
);
'''


def raskryt(p):
    return os.path.expanduser(p)


def nizhniy(s):
    return s.lower().replace('ё', 'е')


# ---------------- Текст из документов ----------------

def _xml_tekst(xml):
    xml = re.sub(r'</w:p>|</a:p>|<w:tab/>|<w:br/>|</row>|</si>', '\n', xml)
    return unescape(re.sub(r'<[^>]+>', ' ', xml))


def tekst_iz_zip(put, chasti):
    out = []
    with zipfile.ZipFile(put) as z:
        for n in z.namelist():
            if any(fnmatch.fnmatch(n, c) for c in chasti):
                out.append(_xml_tekst(z.read(n).decode('utf-8', 'ignore')))
    return '\n'.join(out)


def tekst_pdf(put):
    try:
        import fitz  # PyMuPDF, на Mac есть
        with fitz.open(put) as d:
            return '\n'.join(stranica.get_text() for stranica in d)
    except ImportError:
        r = subprocess.run(['pdftotext', '-q', put, '-'], capture_output=True, timeout=60)
        return r.stdout.decode('utf-8', 'ignore')


def tekst_textutil(put):
    """doc, rtf, odt, html — встроенный в macOS textutil."""
    r = subprocess.run(['textutil', '-convert', 'txt', '-stdout', put], capture_output=True, timeout=60)
    return r.stdout.decode('utf-8', 'ignore')


def izvlech_tekst(put, rassh):
    try:
        if rassh == 'pdf':
            return tekst_pdf(put)
        if rassh in ('docx', 'docm', 'dotx'):
            return tekst_iz_zip(put, ['word/document.xml', 'word/comments.xml', 'word/footnotes.xml'])
        if rassh in ('xlsx', 'xlsm'):
            return tekst_iz_zip(put, ['xl/sharedStrings.xml', 'xl/worksheets/sheet*.xml'])
        if rassh == 'pptx':
            return tekst_iz_zip(put, ['ppt/slides/slide*.xml'])
        if rassh in ('doc', 'rtf', 'odt', 'html', 'htm') and sys.platform == 'darwin':
            return tekst_textutil(put)
        if rassh in ('txt', 'md', 'csv', 'json', 'eml'):
            with open(put, 'rb') as f:
                return f.read(MAX_TEKST * 2).decode('utf-8', 'ignore')
        if rassh == 'xls':
            try:
                import xlrd  # необязательно
                kn = xlrd.open_workbook(put)
                return '\n'.join(' '.join(str(c) for c in sh.row_values(i)) for sh in kn.sheets() for i in range(sh.nrows))
            except Exception:
                return ''
    except Exception as e:
        print(f'  ! текст не прочитан: {put}: {e}', file=sys.stderr)
    return ''


# ---------------- Хеш для поиска дублей ----------------

def hesh(put, razmer):
    h = hashlib.sha1(str(razmer).encode())
    with open(put, 'rb') as f:
        if razmer <= MAX_HASH:
            for kusok in iter(lambda: f.read(1 << 20), b''):
                h.update(kusok)
        else:
            h.update(f.read(1 << 20))
            f.seek(-(1 << 20), 2)
            h.update(f.read())
    return h.hexdigest()


# ---------------- Проект, раздел, дата, от кого ----------------

PROEKTY = {p['id']: (i, p) for i, p in enumerate(N['proekty'])}
RAZDELY = [(i, r) for i, r in enumerate(N['razdely'])]

# Папки почты: «2026-10-23 1815 — мы → ARCHIWOOD — Self  Тема» (исходящие)
# и «2026-11-02 1559 — Степаненко Юлия Сергеевна — Тема» (входящие, без стрелки)
RE_PISMO = re.compile(r'^(\d{4}-\d{2}-\d{2}) (\d{2})(\d{2}) — (.+?)(?: → (.+?))? — (.+)$')


def razbor_pisma(chasti):
    """Дата, от кого и тема из имени папки письма/сообщения."""
    for ch in reversed(chasti):
        m = RE_PISMO.match(ch)
        if m:
            d, hh, mm, ot, komu, tema = m.groups()
            return f'{d}T{hh}:{mm}:00', ot.strip(), tema.strip()
    return None, '', ''


def est_slovo(tekst, slova):
    """Есть ли одно из слов, начиная с начала слова («счет» не находится в «расчет»)."""
    return any(re.search(r'(?<![а-яa-z0-9])' + re.escape(nizhniy(s).strip()), tekst) for s in slova if s.strip())


def opredelit_proekt(koren, chasti, imya, tekst):
    if koren.get('proekt'):
        return koren['proekt']
    # почта и Telegram: по словам в названии чата/письма, потом в тексте
    stroka = nizhniy(' '.join(chasti) + ' ' + imya)
    luchshiy, ochki = 'obshchee', 0
    nachalo = nizhniy(tekst[:20000])
    for pid, (_, p) in PROEKTY.items():
        o = sum(3 for s in p['slova'] if s in stroka) + sum(1 for s in p['slova'] if s in nachalo)
        if o > ochki:
            luchshiy, ochki = pid, o
    return luchshiy


def opredelit_razdel(koren, chasti, imya):
    papki = nizhniy(' / '.join(chasti))
    im = nizhniy(imya)
    ist = koren.get('istochnik', 'papka')
    # 1) тип документа по имени файла — договор остаётся договором, где бы ни лежал
    for i, r in RAZDELY:
        if r.get('istochnik'):
            continue
        if est_slovo(im, r.get('slova_v_imeni', [])):
            return i, r['imya']
    # 2) почта и Telegram — свои разделы
    for i, r in RAZDELY:
        if r.get('istochnik') == ist:
            return i, r['imya']
    # 3) по папке, в которой лежит
    for i, r in RAZDELY:
        if est_slovo(papki, r.get('papki', [])):
            return i, r['imya']
    return len(RAZDELY) - 1, RAZDELY[-1][1]['imya']


def propustit(imya):
    return imya.startswith('.') or any(p in imya for p in N.get('propuskat', []))


# ---------------- Обход ----------------

def obkhod():
    """Все файлы из корней: (полный путь, корень, части пути внутри корня)."""
    vidennye = set()
    for koren in N['korni']:
        top = raskryt(koren['put'])
        if not os.path.isdir(top):
            print(f'  ! нет папки, пропускаю: {top}', file=sys.stderr)
            continue
        krome = set(koren.get('krome', []))
        for papka, dirs, files in os.walk(top):
            otn = os.path.relpath(papka, top)
            chasti = [] if otn == '.' else otn.split(os.sep)
            if not chasti:
                dirs[:] = [d for d in dirs if d not in krome]
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for f in files:
                if propustit(f):
                    continue
                put = os.path.join(papka, f)
                if put in vidennye:
                    continue
                vidennye.add(put)
                yield put, koren, chasti


def obnovit(zanovo=False):
    put_bazy = raskryt(N['baza'])
    os.makedirs(os.path.dirname(put_bazy), exist_ok=True)
    zamok = put_bazy + '.zamok'
    if os.path.exists(zamok) and time.time() - os.path.getmtime(zamok) < 3 * 3600:
        print('Каталог уже обновляется (есть замок), выхожу.')
        return
    open(zamok, 'w').close()
    try:
        con = sqlite3.connect(put_bazy)
        if zanovo:
            con.executescript('DROP TABLE IF EXISTS faily; DROP TABLE IF EXISTS tekst;')
        con.executescript(SHEMA)
        bylo = {r[0]: (r[1], r[2], r[3]) for r in con.execute('SELECT put, razmer, izmenen, id FROM faily')}
        ids = {r[0]: r[1] for r in con.execute('SELECT put, id FROM faily')}
        vidennye, novye, izmenennye = set(), 0, 0
        t0 = time.time()
        for put, koren, chasti in obkhod():
            try:
                st = os.stat(put)
            except OSError:
                continue
            vidennye.add(put)
            if put in bylo and bylo[put][0] == st.st_size and abs(bylo[put][1] - st.st_mtime) < 1:
                continue
            imya = os.path.basename(put)
            rassh = imya.rsplit('.', 1)[-1].lower() if '.' in imya else ''
            tekst = izvlech_tekst(put, rassh)[:MAX_TEKST]
            data_p, otkogo, tema = razbor_pisma(chasti)
            data = data_p or datetime.fromtimestamp(st.st_mtime).isoformat(timespec='seconds')
            pid = opredelit_proekt(koren, chasti, imya, tekst)
            p_por, p = PROEKTY.get(pid, PROEKTY['obshchee'])
            r_por, r_imya = opredelit_razdel(koren, chasti, imya)
            vnutr = 1 if koren.get('vnutrennee') or any('внутренн' in nizhniy(c) for c in chasti) else 0
            try:
                h = hesh(put, st.st_size)
            except OSError:
                h = None
            mesto = ' / '.join([p['imya'], r_imya] + chasti + ([tema] if tema else []))
            zap = (imya, rassh, st.st_size, st.st_mtime, data, pid, p['imya'], p_por, r_imya, r_por,
                   koren.get('istochnik', 'papka'), otkogo, vnutr, h)
            if put in ids:
                con.execute('''UPDATE faily SET imya=?, rasshirenie=?, razmer=?, izmenen=?, data=?, proekt=?,
                    proekt_imya=?, poryadok_proekta=?, razdel=?, poryadok_razdela=?, istochnik=?, otkogo=?,
                    vnutrennee=?, hash=? WHERE put=?''', zap + (put,))
                fid = ids[put]
                con.execute('DELETE FROM tekst WHERE rowid=?', (fid,))
                izmenennye += 1
            else:
                cur = con.execute('''INSERT INTO faily (imya, rasshirenie, razmer, izmenen, data, proekt, proekt_imya,
                    poryadok_proekta, razdel, poryadok_razdela, istochnik, otkogo, vnutrennee, hash, put)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', zap + (put,))
                fid = cur.lastrowid
                ids[put] = fid
                novye += 1
            con.execute('INSERT INTO tekst(rowid, imya, mesto, soderzhanie) VALUES (?,?,?,?)',
                        (fid, imya.replace('_', ' '), mesto, tekst))
            if (novye + izmenennye) % 200 == 0:
                con.commit()
                print(f'  … {novye + izmenennye} файлов, {time.time() - t0:.0f} с')
        # удалённые с диска
        ushli = [put for put in bylo if put not in vidennye]
        for put in ushli:
            fid = ids[put]
            con.execute('DELETE FROM tekst WHERE rowid=?', (fid,))
            con.execute('DELETE FROM faily WHERE id=?', (fid,))
        sklejka_dublej(con)
        con.commit()
        vsego = con.execute('SELECT COUNT(*) FROM faily').fetchone()[0]
        dubli = con.execute('SELECT COUNT(*) FROM faily WHERE dubl_of IS NOT NULL').fetchone()[0]
        print(f'Готово за {time.time() - t0:.0f} с: всего {vsego}, новых {novye}, изменённых {izmenennye}, '
              f'удалено {len(ushli)}, дублей склеено {dubli}.')
    finally:
        os.remove(zamok)


def sklejka_dublej(con):
    """Один и тот же файл в нескольких местах показываем один раз.
    Главная копия — та, что в папке проекта (не почта/Telegram), потом самая ранняя."""
    con.execute('UPDATE faily SET dubl_of = NULL')
    gruppy = con.execute('SELECT hash FROM faily WHERE hash IS NOT NULL AND razmer > 0 '
                         'GROUP BY hash HAVING COUNT(*) > 1').fetchall()
    for (h,) in gruppy:
        rows = con.execute('''SELECT id FROM faily WHERE hash = ? ORDER BY
            CASE istochnik WHEN 'papka' THEN 0 ELSE 1 END, vnutrennee, data''', (h,)).fetchall()
        glavnyy = rows[0][0]
        con.executemany('UPDATE faily SET dubl_of = ? WHERE id = ?', [(glavnyy, r[0]) for r in rows[1:]])


# ---------------- Отчёт и проверка поиска ----------------

def otchet():
    con = poisk.baza()
    print('Проект / раздел — файлов (без дублей)')
    for r in con.execute('''SELECT proekt_imya, razdel, COUNT(*) n FROM faily WHERE dubl_of IS NULL
                            GROUP BY proekt, razdel ORDER BY poryadok_proekta, poryadok_razdela'''):
        print(f'  {r[0]:<20} {r[1]:<24} {r[2]:>6}')
    bez = con.execute("SELECT COUNT(*) FROM faily WHERE dubl_of IS NULL AND razdel='Прочее'").fetchone()[0]
    pust = con.execute("SELECT COUNT(*) FROM faily f JOIN tekst t ON t.rowid=f.id WHERE f.rasshirenie IN "
                       "('pdf','docx','doc','xlsx') AND length(t.soderzhanie) < 20").fetchone()[0]
    print(f'В «Прочее»: {bez}. Документов без текста (сканы?): {pust}.')


def proverka_poiska(slova):
    con = poisk.baza()
    for r in poisk.najti(con, ' '.join(slova), {'proekty': '*'}):
        print(f"  {r['data'][:10]}  {r['proekt_imya']} · {r['razdel']}  {r['imya']}\n      {r['otryvok'][:160]}")


if __name__ == '__main__':
    if '--otchet' in sys.argv:
        otchet()
    elif '--nayti' in sys.argv:
        proverka_poiska(sys.argv[sys.argv.index('--nayti') + 1:])
    else:
        obnovit(zanovo='--zanovo' in sys.argv)
