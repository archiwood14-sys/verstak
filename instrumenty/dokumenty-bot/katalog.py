"""Каталог документов АРХИВУД: обходит папки проектов, почты и Telegram,
достаёт текст из документов и записывает всё в SQLite для поиска и бота.

Файлы никуда не переносятся — каталог только читает и запоминает, где что лежит.
Каждый файл размечается по каркасу (karkas.py): раздел, зона, роль в договоре,
семья версий; после обхода в каждой семье отмечается актуальная (крайняя) версия.

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

import karkas
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
  hash TEXT, dubl_of INTEGER,
  tip TEXT, zona TEXT, rol TEXT, semya TEXT, nazvanie TEXT, otkuda TEXT,
  arhiv INTEGER DEFAULT 0, aktualno INTEGER DEFAULT 1, versiy INTEGER DEFAULT 1, formaty TEXT
);
CREATE INDEX IF NOT EXISTS i_hash ON faily(hash);
CREATE VIRTUAL TABLE IF NOT EXISTS tekst USING fts5(
  imya, mesto, soderzhanie, tokenize = "unicode61 remove_diacritics 2"
);
'''
# столбцы каркаса: в старой базе их нет — добавляем (ALTER TABLE ADD COLUMN)
NOVYE_STOLBCY = [('tip', 'TEXT'), ('zona', 'TEXT'), ('rol', 'TEXT'), ('semya', 'TEXT'), ('nazvanie', 'TEXT'),
                 ('otkuda', 'TEXT'), ('arhiv', 'INTEGER DEFAULT 0'), ('aktualno', 'INTEGER DEFAULT 1'),
                 ('versiy', 'INTEGER DEFAULT 1'), ('formaty', 'TEXT')]


def migraciya(con):
    """Старая база (до каркаса): добавить недостающие столбцы и индексы, данные не трогаем."""
    est_uzhe = {r[1] for r in con.execute('PRAGMA table_info(faily)')}
    for imya, tip in NOVYE_STOLBCY:
        if imya not in est_uzhe:
            con.execute(f'ALTER TABLE faily ADD COLUMN {imya} {tip}')
    con.execute('CREATE INDEX IF NOT EXISTS i_tip ON faily(proekt, tip, aktualno, data)')
    con.execute('CREATE INDEX IF NOT EXISTS i_semya ON faily(semya)')


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
    iskhodnaya = ' '.join(chasti) + ' ' + imya
    stroka = nizhniy(iskhodnaya)
    luchshiy, ochki = 'obshchee', 0
    nachalo = nizhniy(tekst[:20000])
    for pid, (_, p) in PROEKTY.items():   # порядок в настройках решает ничью
        o = sum(5 for k in p.get('kody', []) if re.search(k, iskhodnaya))
        o += sum(3 for s in p['slova'] if s in stroka) + sum(1 for s in p['slova'] if s in nachalo)
        if o > ochki:
            luchshiy, ochki = pid, o
    return luchshiy


def eto_arhiv(chasti, imya):
    a = N.get('arhiv', {})
    # папка «9 АРХИВ (не для работы)» или «Архив», но не «Двери Архивуд»
    if any(re.match(r'^(\d+\s+)?архив(?![а-яa-z])', nizhniy(c)) for c in chasti):
        return True
    if est_slovo(nizhniy(imya), a.get('slova_v_imeni', [])):
        return True
    return bool(a.get('papki_s_podcherkivaniem')) and any(c.startswith('_') for c in chasti)


def opredelit_razdel(koren, chasti, imya):
    # имя верхней папки тоже учитываем: «3 … КОНСТРУКТОРУ», «4 … ВНУТРЕННЕЕ»
    papki = nizhniy(' / '.join([os.path.basename(raskryt(koren['put']))] + chasti))
    im = nizhniy(imya)
    ist = koren.get('istochnik', 'papka')
    rassh = im.rsplit('.', 1)[-1] if '.' in im else ''
    if eto_arhiv(chasti, imya):
        return len(RAZDELY), 'Архив'          # в поиске скрыт, пока не спросят «архив»
    # 1) тип документа по имени файла — договор остаётся договором, где бы ни лежал
    for i, r in RAZDELY:
        if r.get('istochnik'):
            continue
        if est_slovo(im, r.get('slova_v_imeni', [])):
            return i, r['imya']
    # 2) фото и видео — по расширению
    for i, r in RAZDELY:
        if rassh and rassh in r.get('rasshireniya', []):
            return i, r['imya']
    # 3) почта и Telegram — свои разделы
    for i, r in RAZDELY:
        if r.get('istochnik') == ist:
            return i, r['imya']
    # 4) по папке, в которой лежит; во внутренней папке — «Внутреннее»
    if koren.get('vnutrennee'):
        for i, r in RAZDELY:
            if r['imya'] == 'Внутреннее':
                return i, r['imya']
    for i, r in RAZDELY:
        if est_slovo(papki, r.get('papki', [])):
            return i, r['imya']
    return len(RAZDELY) - 1, RAZDELY[-1][1]['imya']


def propustit(imya):
    rassh = imya.rsplit('.', 1)[-1].lower() if '.' in imya else ''
    return (imya.startswith('.') or any(p in imya for p in N.get('propuskat', []))
            or rassh in N.get('propuskat_rasshireniya', []))


def razmetka(koren, chasti, imya, rassh, otkogo, pid):
    """Разметка каркаса для одного файла. Путь для karkas — папки от корня Диска:
    имя папки-корня («1 ОЛИМПИЙСКИЙ», «Почта», «Telegram») и папки внутри него.
    Семья версий — в пределах проекта: «olimp|Договоры|АГ|договор|».
    zona — значение «разреза» проекта (nastroyki.json → proekty[].razrez: зона, этаж, объект…)."""
    papki = [os.path.basename(raskryt(koren['put']).rstrip('/'))] + list(chasti)
    arhiv = 1 if eto_arhiv(chasti, imya) else 0
    z = {'imya': imya, 'put': ' / '.join(papki), 'rassh': rassh, 'istochnik': koren.get('istochnik', 'papka'),
         'otkogo': otkogo, 'arhiv': arhiv}
    razrez = PROEKTY.get(pid, PROEKTY['obshchee'])[1].get('razrez')
    r = karkas.razmetit(z, razrez=razrez)
    return {'tip': r['tip'], 'zona': r.get('zona') or '', 'rol': r.get('rol') or '',
            'semya': f"{pid}|{r['semya']}", 'nazvanie': r['nazvanie'], 'otkuda': r.get('otkuda') or '',
            'arhiv': arhiv, 'papki': z['put'], 'istochnik': z['istochnik']}


def poryadok_tipa(tip):
    return karkas.TIPY.index(tip) if tip in karkas.TIPY else len(karkas.TIPY)


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
            lishnie = {nizhniy(x) for x in N.get('propuskat_papki', [])}
            dirs[:] = [d for d in dirs if not d.startswith('.') and nizhniy(d) not in lishnie]
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
        migraciya(con)
        bylo = {r[0]: (r[1], r[2], r[3], r[4], r[5], r[6]) for r in con.execute(
            'SELECT put, razmer, izmenen, id, proekt, otkogo, nazvanie FROM faily')}
        ids = {r[0]: r[1] for r in con.execute('SELECT put, id FROM faily')}
        vidennye, novye, izmenennye, pererazmecheno = set(), 0, 0, 0
        razmetki = {}   # id → разметка каркаса (для склейки семей и выбора актуальных после обхода)
        t0 = time.time()
        for put, koren, chasti in obkhod():
            try:
                st = os.stat(put)
            except OSError:
                continue
            vidennye.add(put)
            imya = os.path.basename(put)
            rassh = imya.rsplit('.', 1)[-1].lower() if '.' in imya else ''
            if put in bylo and bylo[put][0] == st.st_size and abs(bylo[put][1] - st.st_mtime) < 1:
                # файл не менялся — текст не перечитываем, но разметку каркаса обновляем всегда:
                # правила karkas.py могли поменяться, а старая база могла быть без каркаса
                _, _, fid, pid, otkogo, staroe = bylo[put]
                rz = razmetka(koren, chasti, imya, rassh, otkogo or '', pid)
                razmetki[fid] = rz
                con.execute('UPDATE faily SET tip=?, zona=?, rol=?, semya=?, nazvanie=?, otkuda=?, arhiv=?, '
                            'razdel=?, poryadok_razdela=? WHERE id=?',
                            (rz['tip'], rz['zona'], rz['rol'], rz['semya'], rz['nazvanie'], rz['otkuda'],
                             rz['arhiv'], rz['tip'], poryadok_tipa(rz['tip']), fid))
                if staroe != rz['nazvanie']:
                    con.execute('UPDATE tekst SET imya=? WHERE rowid=?', (rz['nazvanie'] + ' ' + imya.replace('_', ' '), fid))
                    pererazmecheno += 1
                continue
            tekst = izvlech_tekst(put, rassh)[:MAX_TEKST]
            data_p, otkogo, tema = razbor_pisma(chasti)
            data = data_p or datetime.fromtimestamp(st.st_mtime).isoformat(timespec='seconds')
            pid = opredelit_proekt(koren, chasti, imya, tekst)
            p_por, p = PROEKTY.get(pid, PROEKTY['obshchee'])
            rz = razmetka(koren, chasti, imya, rassh, otkogo, pid)
            r_por, r_imya = poryadok_tipa(rz['tip']), rz['tip']   # razdel = tip каркаса
            vnutr = 1 if koren.get('vnutrennee') or est_slovo(nizhniy(' / '.join(chasti) + ' ' + imya),
                                                              N.get('vnutrennee_slova', ['внутренн'])) else 0
            try:
                h = hesh(put, st.st_size)
            except OSError:
                h = None
            mesto = ' / '.join([p['imya'], r_imya] + chasti + ([tema] if tema else []))
            zap = (imya, rassh, st.st_size, st.st_mtime, data, pid, p['imya'], p_por, r_imya, r_por,
                   koren.get('istochnik', 'papka'), otkogo, vnutr, h,
                   rz['tip'], rz['zona'], rz['rol'], rz['semya'], rz['nazvanie'], rz['otkuda'], rz['arhiv'])
            if put in ids:
                con.execute('''UPDATE faily SET imya=?, rasshirenie=?, razmer=?, izmenen=?, data=?, proekt=?,
                    proekt_imya=?, poryadok_proekta=?, razdel=?, poryadok_razdela=?, istochnik=?, otkogo=?,
                    vnutrennee=?, hash=?, tip=?, zona=?, rol=?, semya=?, nazvanie=?, otkuda=?, arhiv=?
                    WHERE put=?''', zap + (put,))
                fid = ids[put]
                con.execute('DELETE FROM tekst WHERE rowid=?', (fid,))
                izmenennye += 1
            else:
                cur = con.execute('''INSERT INTO faily (imya, rasshirenie, razmer, izmenen, data, proekt, proekt_imya,
                    poryadok_proekta, razdel, poryadok_razdela, istochnik, otkogo, vnutrennee, hash,
                    tip, zona, rol, semya, nazvanie, otkuda, arhiv, put)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', zap + (put,))
                fid = cur.lastrowid
                ids[put] = fid
                novye += 1
            razmetki[fid] = rz
            # в поиске по имени — и чистое название, и исходное имя файла
            con.execute('INSERT INTO tekst(rowid, imya, mesto, soderzhanie) VALUES (?,?,?,?)',
                        (fid, rz['nazvanie'] + ' ' + imya.replace('_', ' '), mesto, tekst))
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
        otmetit_aktualnye(con, razmetki, poisk.prochitat_resheniya(N))
        con.commit()
        vsego = con.execute('SELECT COUNT(*) FROM faily').fetchone()[0]
        dubli = con.execute('SELECT COUNT(*) FROM faily WHERE dubl_of IS NOT NULL').fetchone()[0]
        akt = con.execute('SELECT COUNT(*) FROM faily WHERE aktualno = 1').fetchone()[0]
        print(f'Готово за {time.time() - t0:.0f} с: всего {vsego}, новых {novye}, изменённых {izmenennye}, '
              f'удалено {len(ushli)}, дублей склеено {dubli}, актуальных документов {akt}'
              + (f', переименовано по каркасу {pererazmecheno}' if pererazmecheno else '') + '.')
    finally:
        os.remove(zamok)


def sklejka_dublej(con):
    """Один и тот же файл в нескольких местах показываем один раз.
    Главная копия — та, что в папке проекта (не почта/Telegram), потом самая ранняя."""
    con.execute('UPDATE faily SET dubl_of = NULL')
    # склеиваем только в пределах проекта и уровня доступа, чтобы никто не потерял свой файл
    gruppy = con.execute('SELECT hash, proekt, vnutrennee FROM faily WHERE hash IS NOT NULL AND razmer > 0 '
                         'GROUP BY hash, proekt, vnutrennee HAVING COUNT(*) > 1').fetchall()
    for h, pr, vn in gruppy:
        rows = con.execute('''SELECT id FROM faily WHERE hash = ? AND proekt = ? AND vnutrennee = ? ORDER BY
            CASE istochnik WHEN 'papka' THEN 0 ELSE 1 END, COALESCE(arhiv, 0), data''',
                           (h, pr, vn)).fetchall()
        glavnyy = rows[0][0]
        con.executemany('UPDATE faily SET dubl_of = ? WHERE id = ?', [(glavnyy, r[0]) for r in rows[1:]])


def otmetit_aktualnye(con, razmetki=None, resheniya=None):
    """В каждой семье версий — одна актуальная, как в demo/dannye_karkas.py:
    karkas.skleit_pokhozhie → karkas.vybrat_aktualnye → karkas.popravka_dogovorov,
    потом поверх автоматики — ручные решения из aktualnost.json (кнопки бота).
    Дубли (тот же файл в другом месте) в выборе не участвуют: они скрыты, актуальной быть не могут."""
    razmetki = razmetki or {}
    faily = []
    for r in con.execute('SELECT id, put, semya, data, arhiv, rasshirenie, proekt, tip, zona, rol, nazvanie, istochnik '
                         'FROM faily WHERE dubl_of IS NULL'):
        rz = razmetki.get(r[0], {})
        faily.append({'id': r[0], 'put_faila': r[1], 'semya': r[2] or f'id{r[0]}', 'data': r[3] or '',
                      'arhiv': r[4] or 0, 'rassh': r[5] or '', 'proekt': r[6], 'tip': r[7], 'zona': r[8] or '',
                      'rol': r[9] or '', 'nazvanie': r[10] or '', 'istochnik': r[11] or 'papka',
                      # karkas смотрит в «put» папки от корня Диска (для «данные заказчика», «как получено»)
                      'put': rz.get('papki') or r[1]})
    karkas.skleit_pokhozhie(faily, proekt_pole='proekt')
    karkas.vybrat_aktualnye(faily)
    karkas.popravka_dogovorov(faily, proekt_pole='proekt')
    poisk.primenit_resheniya(faily, resheniya or {}, pole_puti='put_faila')
    con.execute('UPDATE faily SET aktualno = 0, versiy = 1, formaty = NULL WHERE dubl_of IS NOT NULL')
    con.executemany('UPDATE faily SET semya = ?, aktualno = ?, versiy = ?, formaty = ? WHERE id = ?',
                    [(f['semya'], f['aktualno'], f['versiy'], '+'.join(f['formaty']) if f.get('formaty') else None,
                      f['id']) for f in faily])


# ---------------- Отчёт и проверка поиска ----------------

def otchet():
    con = poisk.baza()
    print('Проект / раздел каркаса — актуальных документов (всего файлов без дублей)')
    for r in con.execute('''SELECT proekt_imya, tip, SUM(aktualno = 1) a, COUNT(*) n FROM faily WHERE dubl_of IS NULL
                            GROUP BY proekt, tip ORDER BY MIN(poryadok_proekta), MIN(poryadok_razdela)'''):
        print(f'  {r[0]:<20} {r[1] or "?":<28} {r[2]:>6} ({r[3]})')
    bez = con.execute("SELECT COUNT(*) FROM faily WHERE aktualno = 1 AND tip='Прочее'").fetchone()[0]
    pust = con.execute("SELECT COUNT(*) FROM faily f JOIN tekst t ON t.rowid=f.id WHERE f.rasshirenie IN "
                       "('pdf','docx','doc','xlsx') AND length(t.soderzhanie) < 20").fetchone()[0]
    print(f'В «Прочее»: {bez}. Документов без текста (сканы?): {pust}.')


def proverka_poiska(slova):
    con = poisk.baza()
    for r in poisk.najti(con, ' '.join(slova), {'proekty': '*'}):
        print(f"  {r['data'][:10]}  {r['proekt_imya']} · {r['tip']}{' · ' + r['zona'] if r.get('zona') else ''}  "
              f"{r['nazvanie']}  [{r['put']}]{'' if r.get('aktualno') else '  (старая версия)'}\n"
              f"      {(r['otryvok'] or '')[:160]}")


if __name__ == '__main__':
    if '--otchet' in sys.argv:
        otchet()
    elif '--nayti' in sys.argv:
        proverka_poiska(sys.argv[sys.argv.index('--nayti') + 1:])
    else:
        obnovit(zanovo='--zanovo' in sys.argv)
