"""Поиск по каталогу документов АРХИВУД (общий модуль для бота и проверок).

Каталог — SQLite-файл, его заполняет katalog.py. Здесь только чтение.

Права доступа (dostup) — словарь из nastroyki.json → polzovateli[...]:
    {"proekty": "*" или ["raz_mebel", ...], "bez_vnutrennego": true/false}
"""
import json
import os
import re
import sqlite3
from pathlib import Path

PAPKA = Path(__file__).resolve().parent
NASTROYKI = PAPKA / 'nastroyki.json'


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


def _fts_zapros(tekst):
    """Слова запроса → запрос FTS5: каждое слово как префикс, все обязательны."""
    slova = re.findall(r'[\w\d]+', tekst.lower())
    slova = [s for s in slova if len(s) > 1][:12]
    if not slova:
        return None
    # окончания русских слов отрезаем, чтобы «договора» нашло «договор»
    def osnova(s):
        return s[:max(4, len(s) - 2)] if len(s) > 5 and not s.isdigit() else s
    return ' '.join(f'"{osnova(s)}"*' for s in slova)


def najti(con, tekst, dostup, limit=7):
    """Поиск: сначала все слова, если пусто — любое из слов. Свежие и точные выше."""
    q = _fts_zapros(tekst)
    if not q:
        return []
    us, par = _uslovie_dostupa(dostup)
    if 'архив' not in tekst.lower():   # старые и заменённые версии — только по просьбе
        us += " AND f.razdel != 'Архив'"
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


def proekty(con, dostup):
    us, par = _uslovie_dostupa(dostup)
    return [dict(r) for r in con.execute(
        f'SELECT proekt, proekt_imya, COUNT(*) n, MAX(data) svezhee FROM faily f WHERE {us} '
        f'GROUP BY proekt ORDER BY MIN(poryadok_proekta), proekt_imya', par)]


def razdely(con, proekt, dostup):
    us, par = _uslovie_dostupa(dostup)
    return [dict(r) for r in con.execute(
        f'SELECT razdel, COUNT(*) n FROM faily f WHERE {us} AND f.proekt = ? '
        f'GROUP BY razdel ORDER BY MIN(poryadok_razdela)', par + [proekt])]


def spisok(con, proekt, razdel, dostup, smeshchenie=0, limit=8):
    us, par = _uslovie_dostupa(dostup)
    return [dict(r) for r in con.execute(
        f'SELECT * FROM faily f WHERE {us} AND f.proekt = ? AND f.razdel = ? '
        f'ORDER BY f.data DESC LIMIT ? OFFSET ?', par + [proekt, razdel, limit, smeshchenie])]


def svezhie(con, dostup, limit=10):
    """Самые свежие файлы из всех доступных проектов."""
    us, par = _uslovie_dostupa(dostup)
    return [dict(r) for r in con.execute(
        f'SELECT * FROM faily f WHERE {us} ORDER BY f.data DESC LIMIT ?', par + [limit])]


def fail(con, fid, dostup):
    us, par = _uslovie_dostupa(dostup)
    r = con.execute(f'SELECT * FROM faily f WHERE {us} AND f.id = ?', par + [fid]).fetchone()
    return dict(r) if r else None


def kopii(con, fid):
    """Где ещё лежит тот же файл (дубли с тем же содержимым)."""
    return [r['put'] for r in con.execute('SELECT put FROM faily WHERE dubl_of = ?', [fid])]
