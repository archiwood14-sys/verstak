"""Поиск по каталогу документов АРХИВУД (общий модуль для бота и проверок).

Каталог — SQLite-файл, его заполняет katalog.py. Здесь чтение и ручные решения
об актуальности (aktualnost.json: кнопки бота «Сделать актуальной» / «Убрать в историю»).

Права доступа (dostup) — словарь из nastroyki.json → polzovateli[...]:
    {"proekty": "*" или ["raz_mebel", ...], "bez_vnutrennego": true/false}

Каркас: в меню и в поиске — только актуальные (крайние) версии документов (aktualno = 1).
Старые версии — через versii() («История версий») или в поиске со словами
«архив», «все версии», «старые». Раздел «Переписка» в меню не показывается, только в поиске.
"""
import json
import os
import re
import sqlite3
from pathlib import Path

import karkas

PAPKA = Path(__file__).resolve().parent
NASTROYKI = PAPKA / 'nastroyki.json'

DOGOVORY = 'Договоры'
ZAPISKI = 'Записки и разборы'
SKRYTYE_TIPY = ('Переписка',)       # в меню не показываем, только поиском
# старая база без каркаса (aktualno ещё NULL) — считаем всё актуальным, пока katalog.py не пересчитает
AKTUALNO = 'COALESCE(f.aktualno, 1) = 1'
RESHENIYA_PO_UMOLCHANIYU = '~/archiwood_proekty/dokumenty/aktualnost.json'
RE_ARHIV = re.compile(r'архив\w*|все\s+верси\w*|(?:стар(?:ые|ая|ую|ый|ых|ое)|предыдущ\w*)(?:\s+верси\w*)?(?!\w)')


def nastroyki():
    # для проверок можно подставить другой файл: DOKUMENTY_NASTROYKI=/путь/к/test.json
    put = Path(os.environ.get('DOKUMENTY_NASTROYKI') or NASTROYKI)
    return json.loads(put.read_text('utf-8'))


def baza(put=None):
    put = put or os.path.expanduser(nastroyki()['baza'])
    con = sqlite3.connect(put)
    con.row_factory = sqlite3.Row
    return con


def _uslovie_dostupa(dostup, alias='f'):
    """SQL-условие и параметры, которые прячут чужие проекты и внутреннее."""
    us, par = [f'{alias}.dubl_of IS NULL'], []
    pr = dostup.get('proekty', '*')
    if pr != '*':
        us.append(f'{alias}.proekt IN ({",".join("?" * len(pr))})')
        par += list(pr)
    if dostup.get('bez_vnutrennego'):
        us.append(f'{alias}.vnutrennee = 0')
    return ' AND '.join(us), par


def eto_zapros_arhiva(tekst):
    """Просят старые версии: «архив», «все версии», «старые»."""
    return bool(RE_ARHIV.search((tekst or '').lower().replace('ё', 'е')))


def _fts_zapros(tekst):
    """Слова запроса → запрос FTS5: каждое слово как префикс, все обязательны."""
    tekst = RE_ARHIV.sub(' ', (tekst or '').lower().replace('ё', 'е'))   # «архив» — режим, а не слово поиска
    slova = re.findall(r'[\w\d]+', tekst)
    slova = [s for s in slova if len(s) > 1][:12]
    if not slova:
        return None
    # окончания русских слов отрезаем, чтобы «договора» нашло «договор»
    def osnova(s):
        return s[:max(4, len(s) - 2)] if len(s) > 5 and not s.isdigit() else s
    return ' '.join(f'"{osnova(s)}"*' for s in slova)


def najti(con, tekst, dostup, limit=7, proekt=None):
    """Поиск: сначала все слова, если пусто — любое из слов. Свежие и точные выше.
    Только актуальные версии, если в запросе нет «архив»/«все версии»/«старые»."""
    q = _fts_zapros(tekst)
    if not q:
        return []
    us, par = _uslovie_dostupa(dostup)
    if not eto_zapros_arhiva(tekst):
        us += ' AND ' + AKTUALNO
    if proekt:
        us += ' AND f.proekt = ?'
        par = par + [proekt]
    sql = f'''SELECT f.*, bm25(tekst, 8.0, 3.0, 1.0) AS ves,
                     snippet(tekst, 2, '«', '»', '…', 12) AS otryvok
              FROM tekst JOIN faily f ON f.id = tekst.rowid
              WHERE tekst MATCH ? AND {us}
              ORDER BY ves + (julianday('now') - julianday(f.data)) / 120.0
              LIMIT ?'''
    rows = con.execute(sql, [q] + par + [limit]).fetchall()
    if not rows and ' ' in q:
        rows = con.execute(sql, [q.replace('" "', '" OR "')] + par + [limit]).fetchall()
    return [dict(r) for r in rows]


def _menyu(dostup):
    """Условие для меню: доступно, актуально, не «Переписка»."""
    us, par = _uslovie_dostupa(dostup)
    us += f' AND {AKTUALNO} AND COALESCE(f.tip, \'\') NOT IN ({",".join("?" * len(SKRYTYE_TIPY))})'
    return us, par + list(SKRYTYE_TIPY)


def proekty(con, dostup):
    us, par = _menyu(dostup)
    return [dict(r) for r in con.execute(
        f'SELECT proekt, proekt_imya, COUNT(*) n, MAX(data) svezhee FROM faily f WHERE {us} '
        f'GROUP BY proekt ORDER BY MIN(poryadok_proekta), proekt_imya', par)]


def tipy(con, proekt, dostup):
    """Разделы каркаса проекта с числом актуальных документов, в порядке karkas.TIPY, без «Переписки»."""
    us, par = _menyu(dostup)
    n = {r['tip']: r['n'] for r in con.execute(
        f'SELECT f.tip, COUNT(*) n FROM faily f WHERE {us} AND f.proekt = ? GROUP BY f.tip', par + [proekt])}
    return [{'tip': t, 'n': n[t]} for t in karkas.TIPY if n.get(t)]


def spisok(con, proekt, tip, dostup, smeshchenie=0, limit=8, zona=None):
    """Актуальные документы раздела каркаса, свежие сверху. zona: None — все, '' — без значения разреза."""
    us, par = _menyu(dostup)
    if zona is not None:
        us += " AND COALESCE(f.zona, '') = ?"
        par = par + [zona]
    return [dict(r) for r in con.execute(
        f'SELECT * FROM faily f WHERE {us} AND f.proekt = ? AND f.tip = ? '
        f'ORDER BY f.data DESC LIMIT ? OFFSET ?', par + [proekt, tip, limit, smeshchenie])]


def skolko(con, proekt, tip, dostup, zona=None):
    us, par = _menyu(dostup)
    if zona is not None:
        us += " AND COALESCE(f.zona, '') = ?"
        par = par + [zona]
    return con.execute(f'SELECT COUNT(*) FROM faily f WHERE {us} AND f.proekt = ? AND f.tip = ?',
                       par + [proekt, tip]).fetchone()[0]


def _poryadok_zony(z, poryadok=None):
    """Порядок значений разреза: как в настройках проекта (razrez.znacheniya), иначе зоны karkas.ZONY,
    дальше остальные по алфавиту; «без значения» — в конце."""
    imena = list(poryadok) if poryadok else [x for x, _ in karkas.ZONY]
    if not z:
        return (2, 0, '')
    return (0, imena.index(z), '') if z in imena else (1, 0, z)


def zony(con, proekt, dostup, tip=DOGOVORY, poryadok=None):
    """Значения разреза (зоны, этажи, объекты) у актуальных документов раздела:
    [{'zona': 'АГ', 'n': 4}, …, {'zona': '', 'n': 2}] («» — без значения, в конце).
    Пустой список — документов нет; один элемент с zona='' — разреза у документов нет."""
    us, par = _menyu(dostup)
    rows = [dict(r) for r in con.execute(
        f"SELECT COALESCE(f.zona, '') zona, COUNT(*) n FROM faily f WHERE {us} AND f.proekt = ? AND f.tip = ? "
        f"GROUP BY COALESCE(f.zona, '')", par + [proekt, tip])]
    return sorted(rows, key=lambda r: _poryadok_zony(r['zona'], poryadok))


def nomer_rol(rol):
    m = re.search(r'(\d+)', rol or '')
    return int(m.group(1)) if m else 999


def dogovor_zony(con, proekt, zona, dostup):
    """Карточка договора зоны: {'dogovor': актуальный договор или None, 'prilozheniya': [...]}.
    Приложения — по номеру («Приложение 1 — Смета», «Приложение 2 — ТЗ …»); другие договоры зоны
    (допсоглашения, договор на другой предмет) — после приложений."""
    us, par = _menyu(dostup)
    rows = [dict(r) for r in con.execute(
        f"SELECT * FROM faily f WHERE {us} AND f.proekt = ? AND f.tip = ? AND COALESCE(f.zona, '') = ? "
        f"ORDER BY f.data DESC", par + [proekt, DOGOVORY, zona or ''])]
    dogovory = [r for r in rows if (r.get('rol') or 'Договор') == 'Договор']
    dogovor = dogovory[0] if dogovory else None
    prochie = [r for r in rows if r is not dogovor]
    prochie.sort(key=lambda r: (0 if (r.get('rol') or '').startswith('Приложение') else 1,
                                nomer_rol(r.get('rol')), r.get('rol') or '', -_den(r)))
    return {'dogovor': dogovor, 'prilozheniya': prochie}


def _den(r):
    d = re.sub(r'\D', '', (r.get('data') or '')[:19])
    return int(d) if d else 0


def zapiski(con, proekt, zona, dostup, limit=50):
    """Записки и разборы проекта (актуальные): сначала той же зоны, потом остальные; свежие сверху."""
    us, par = _menyu(dostup)
    return [dict(r) for r in con.execute(
        f"SELECT * FROM faily f WHERE {us} AND f.proekt = ? AND f.tip = ? "
        f"ORDER BY (COALESCE(f.zona, '') = ? AND ? != '') DESC, f.data DESC LIMIT ?",
        par + [proekt, ZAPISKI, zona or '', zona or '', limit])]


def versii(con, semya, dostup):
    """Все версии документа (семья), включая архивные: актуальная первой, дальше от новых к старым."""
    us, par = _uslovie_dostupa(dostup)
    return [dict(r) for r in con.execute(
        f'SELECT * FROM faily f WHERE {us} AND f.semya = ? ORDER BY COALESCE(f.aktualno, 0) DESC, f.data DESC',
        par + [semya])]


def svezhie(con, dostup, limit=10):
    """Самые свежие актуальные документы из всех доступных проектов."""
    us, par = _menyu(dostup)
    return [dict(r) for r in con.execute(
        f'SELECT * FROM faily f WHERE {us} ORDER BY f.data DESC LIMIT ?', par + [limit])]


def fail(con, fid, dostup):
    """Один файл по id — любой версии (старые нужны для «Истории версий»); права проверяются."""
    us, par = _uslovie_dostupa(dostup)
    r = con.execute(f'SELECT * FROM faily f WHERE {us} AND f.id = ?', par + [fid]).fetchone()
    return dict(r) if r else None


def kopii(con, fid):
    """Где ещё лежит тот же файл (дубли с тем же содержимым)."""
    return [r['put'] for r in con.execute('SELECT put FROM faily WHERE dubl_of = ?', [fid])]


# ---------- ручные решения об актуальности ----------

def put_resheniy(nast=None):
    nast = nast if nast is not None else nastroyki()
    return os.path.expanduser(nast.get('aktualnost') or RESHENIYA_PO_UMOLCHANIYU)


def prochitat_resheniya(nast=None):
    """{semya или полный путь файла: "aktualno" | "istoriya"}. Нет файла или битый — решений нет."""
    put = put_resheniy(nast)
    try:
        with open(put, encoding='utf-8') as fh:
            d = json.load(fh)
        return {k: v for k, v in d.items() if v in ('aktualno', 'istoriya')} if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def zapisat_reshenie(nast, klyuch, reshenie, ubrat=()):
    """Записать решение (и убрать устаревшие решения по другим файлам той же семьи).
    Пишем во временный файл и подменяем — katalog.py никогда не прочитает половину."""
    put = put_resheniy(nast)
    d = prochitat_resheniya(nast)
    for k in ubrat:
        d.pop(k, None)
    d[klyuch] = reshenie
    os.makedirs(os.path.dirname(put) or '.', exist_ok=True)
    with open(put + '.novyj', 'w', encoding='utf-8') as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(put + '.novyj', put)
    return d


def primenit_resheniya(faily, resheniya, pole_puti='put'):
    """Ручные решения поверх автоматики (karkas.vybrat_aktualnye). faily — словари с semya, data, arhiv,
    aktualno и путём файла в поле pole_puti. Решение по файлу сильнее решения по семье:
      семья → "istoriya": весь документ в историю; "aktualno": документ виден (крайняя версия);
      файл  → "aktualno": этот файл — актуальная версия, остальные в семье — история;
              "istoriya": этот файл не актуален (другая версия сама не поднимается)."""
    if not resheniya:
        return
    semi = {}
    for f in faily:
        semi.setdefault(f['semya'], []).append(f)
    for semya, sem in semi.items():
        r = resheniya.get(semya)
        if r == 'istoriya':
            for f in sem:
                f['aktualno'] = 0
        elif r == 'aktualno' and not any(f.get('aktualno') for f in sem):
            max(sem, key=lambda f: (not f.get('arhiv'), f.get('data') or ''))['aktualno'] = 1
        for f in sem:
            if resheniya.get(f.get(pole_puti)) == 'istoriya':
                f['aktualno'] = 0
        vybrannye = [f for f in sem if resheniya.get(f.get(pole_puti)) == 'aktualno']
        if vybrannye:
            glavnyy = max(vybrannye, key=lambda f: f.get('data') or '')
            for f in sem:
                f['aktualno'] = 1 if f is glavnyy else 0


def otmetit_vruchnuyu(con, nast, fid, reshenie, dostup):
    """Кнопка бота: файл fid → "aktualno" / "istoriya". Пишет решение в aktualnost.json
    (katalog.py применит его при каждой сборке) и сразу меняет aktualno в базе. Возвращает файл или None."""
    f = fail(con, fid, dostup)
    if not f or reshenie not in ('aktualno', 'istoriya'):
        return None
    sem = versii(con, f['semya'], dostup) if f.get('semya') else [f]
    drugie = [v['put'] for v in sem if v['id'] != fid]
    # «сделать актуальной» отменяет прежние ручные выборы в семье; «в историю» — решение «aktualno» по семье
    zapisat_reshenie(nast, f['put'], reshenie, ubrat=drugie + ([f['semya']] if f.get('semya') else []))
    if reshenie == 'aktualno':
        if f.get('semya'):
            con.execute('UPDATE faily SET aktualno = 0 WHERE semya = ?', [f['semya']])
        con.execute('UPDATE faily SET aktualno = 1 WHERE id = ?', [fid])
    else:
        con.execute('UPDATE faily SET aktualno = 0 WHERE id = ?', [fid])
    con.commit()
    return fail(con, fid, dostup)
