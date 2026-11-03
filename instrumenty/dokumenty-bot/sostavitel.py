"""Составитель черновиков «АРХИВУД Документы»: заявки из бота → черновик от Claude Code.

Бот записывает заявку («📝 Составить документ») строкой JSON в очередь zayavki.jsonl
(nastroyki.json → ochered_zayavok). Этот скрипт (launchd, раз в минуту) берёт новые
заявки и для каждой запускает на Mac Claude Code в неинтерактивном режиме:

    claude -p "<промпт>" --output-format json      (в папке ~/archiwood_proekty)

Команда, флаги и папки — в nastroyki.json → sostavitel. Агент либо задаёт вопросы
({"voprosy": [...]}), либо сохраняет черновик в Черновики/<проект>/ и возвращает
{"fail": ..., "istochniki": [...], "chto_izmeneno": ..., "proverki": ...}.
Наружу агент ничего не отправляет — только читает файлы и пишет черновик.

Статусы заявки: novaya → v_rabote → voprosy / gotovo / oshibka.
Результат дописывается в zayavki_otvety.jsonl — его раз в 30 секунд читает бот
и пересылает вопросы или готовый черновик тому, кто заказал.

    python3 sostavitel.py           # обработать новые заявки
    python3 sostavitel.py --spisok  # показать очередь
"""
import fcntl
import json
import os
import subprocess
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime

import poisk

OCHERED_PO_UMOLCHANIYU = '~/archiwood_proekty/dokumenty/zayavki.jsonl'
PO_UMOLCHANIYU = {
    'komanda': ['claude', '-p'],
    # без --allowedTools в режиме -p агенту запрещено всё, что требует разрешения;
    # разрешаем только чтение, запись черновика и поиск по каталогу — отправлять наружу нечем
    'flagi': ['--output-format', 'json', '--permission-mode', 'acceptEdits',
              '--allowedTools', 'Read,Write,Edit,Glob,Grep,Bash(python3:*)'],
    'papka': '~/archiwood_proekty',
    'chernoviki': '~/archiwood_proekty/dokumenty/Черновики',
    'katalog': '~/archiwood_proekty/dokumenty/katalog.py',
    'tajmaut_sek': 1800,
    'popytok': 3,          # сколько раз перезапускать заявку, застрявшую в v_rabote
    'za_raz': 10,          # заявок за один запуск
}
STATUSY = ('novaya', 'v_rabote', 'voprosy', 'gotovo', 'oshibka')


class OshibkaAgenta(Exception):
    """Агент не отработал или вернул непонятный ответ."""


# ---------- настройки и пути ----------

def nastroyki_sostavitelya(nast):
    s = dict(PO_UMOLCHANIYU)
    s.update(nast.get('sostavitel') or {})
    return s


def put_ocheredi(nast):
    return os.path.expanduser(nast.get('ochered_zayavok') or OCHERED_PO_UMOLCHANIYU)


def put_otvetov(put):
    """zayavki.jsonl → zayavki_otvety.jsonl рядом."""
    osn, rassh = os.path.splitext(put)
    return f'{osn}_otvety{rassh or ".jsonl"}'


def seychas():
    return datetime.now().isoformat(timespec='seconds')


def novyj_id():
    """«20261103-142530-ab12»: время + случайный хвост (короткий — влезает в кнопку Telegram)."""
    return datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:4]


# ---------- очередь (общая с ботом) ----------

@contextmanager
def zamok(put):
    """Замок на файл очереди: бот дописывает, составитель переписывает — не одновременно."""
    os.makedirs(os.path.dirname(put) or '.', exist_ok=True)
    with open(put + '.zamok', 'a') as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _chitat(put):
    if not os.path.isfile(put):
        return []
    out = []
    with open(put, encoding='utf-8') as fh:
        for n, stroka in enumerate(fh, 1):
            if not stroka.strip():
                continue
            try:
                out.append(json.loads(stroka))
            except ValueError:
                print(f'  ! {put}: строка {n} не читается, пропускаю', file=sys.stderr)
    return out


def _zapisat(put, zayavki):
    """Переписать очередь целиком: сначала во временный файл, потом подменить (не теряем при сбое)."""
    vremennyj = put + '.novyj'
    with open(vremennyj, 'w', encoding='utf-8') as fh:
        for z in zayavki:
            fh.write(json.dumps(z, ensure_ascii=False) + '\n')
    os.replace(vremennyj, put)


def prochitat(put):
    if not os.path.isfile(put):   # очереди ещё нет — и замок не нужен (папку не создаём)
        return []
    with zamok(put):
        return _chitat(put)


def najti_zayavku(put, zid):
    return next((z for z in prochitat(put) if z.get('id') == zid), None)


def dobavit(put, z):
    with zamok(put):
        with open(put, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(z, ensure_ascii=False) + '\n')


def izmenit(put, zid, izmenenie):
    """Изменить заявку по id: izmenenie — словарь полей или функция(z). Возвращает новую заявку или None."""
    with zamok(put):
        zayavki = _chitat(put)
        for z in zayavki:
            if z.get('id') == zid:
                if callable(izmenenie):
                    izmenenie(z)
                else:
                    z.update(izmenenie)
                z['izmeneno'] = seychas()
                _zapisat(put, zayavki)
                return z
    return None


def dopisat_otvet(put_otv, otvet):
    with zamok(put_otv):
        with open(put_otv, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(otvet, ensure_ascii=False) + '\n')


# ---------- промпт и запуск агента ----------

def papka_proekta(z):
    """Имя папки черновиков: имя проекта без «/» и прочего, что мешает в пути."""
    imya = z.get('proekt_imya') or z.get('proekt') or 'Без проекта'
    return ''.join('-' if c in '/\\:' else c for c in imya).strip() or 'Без проекта'


def prompt(z, s):
    chernoviki = os.path.join(os.path.expanduser(s['chernoviki']), papka_proekta(z))
    osnovy = '\n'.join(f"- {o.get('nazvanie') or os.path.basename(o.get('put', ''))}: {o.get('put')}"
                       for o in z.get('osnovy') or []) or '- (похожих не нашлось — поищи сам)'
    utochneniya = ''
    for u in z.get('utochneniya') or []:
        voprosy = '; '.join(u.get('voprosy') or [])
        utochneniya += f"- Вопросы: {voprosy}\n  Ответ заказчика заявки: {u.get('otvet')}\n"
    kto = (z.get('kto') or {}).get('imya') or ''
    return f'''Ты помогаешь сотрудникам АРХИВУД (столярное производство: двери, мебель, отделка).
Составь ЧЕРНОВИК документа по заявке из Telegram-бота «АРХИВУД Документы».

Заявка {z.get('id')}:
- Что нужно: {z.get('chto')}
- Проект: {z.get('proekt_imya') or z.get('proekt') or 'не указан'}
- Для кого / куда: {z.get('dlya') or 'не указано'}
- Срок: {z.get('srok') or 'не указан'}
- Заказал: {kto}

Документы-основы (актуальные версии из каталога):
{osnovy}
{('Уточнения по прошлым вопросам:' + chr(10) + utochneniya) if utochneniya else ''}
Как работать:
1. Прочитай документы-основы. Остальное ищи в каталоге документов:
   python3 {s['katalog']} --nayti <слова>
   (печатает дату, проект, раздел, название и путь; старые версии — только со словом «архив»).
   Опирайся на актуальные версии, старые — только для сравнения.
2. Если для документа не хватает данных (суммы, сроки, реквизиты, размеры, кто подписывает)
   и их нельзя взять из документов — НЕ выдумывай и не составляй документ, а верни только JSON:
   {{"voprosy": ["короткий вопрос 1", "вопрос 2"]}}  (не больше 5 вопросов).
3. Иначе сохрани черновик в папку {chernoviki}/ (создай, если нет):
   имя файла начинается с даты ({datetime.now():%Y-%m-%d}), формат — как у основы (docx, xlsx) или md.
   Ничего не меняй и не удаляй в других папках, основы не перезаписывай.
4. НИКОГДА ничего не отправляй наружу: ни почту, ни Telegram, ни сообщения, ни загрузки в облако.
   Только чтение файлов и запись черновика.
5. В конце ответь ТОЛЬКО JSON, без пояснений вокруг:
   {{"fail": "<полный путь к черновику>", "istochniki": ["<пути использованных файлов>"],
     "chto_izmeneno": "<что взято из основы и что изменено>",
     "proverki": "<что проверено и что человеку проверить перед отправкой>"}}
'''


def _json_iz_teksta(tekst):
    """Последний JSON-объект с voprosy или fail в тексте ответа агента (может быть в ```json …```)."""
    tekst = (tekst or '').strip()
    try:
        d = json.loads(tekst)
        if isinstance(d, dict):
            return d
    except ValueError:
        pass
    dek = json.JSONDecoder()
    for i in reversed([i for i, c in enumerate(tekst) if c == '{']):
        try:
            d, _ = dek.raw_decode(tekst, i)
        except ValueError:
            continue
        if isinstance(d, dict) and ('voprosy' in d or 'fail' in d):
            return d
    raise OshibkaAgenta('в ответе агента нет JSON с «fail» или «voprosy»: ' + tekst[-300:])


def razobrat_vyvod(stdout):
    """Вывод `claude -p --output-format json`: {"type": "result", "is_error": …, "result": "<текст>"}."""
    try:
        vnesh = json.loads(stdout)
    except ValueError:
        return _json_iz_teksta(stdout)
    if isinstance(vnesh, dict) and ('voprosy' in vnesh or 'fail' in vnesh):
        return vnesh
    if not isinstance(vnesh, dict) or 'result' not in vnesh:
        raise OshibkaAgenta('непонятный вывод агента: ' + stdout[-300:])
    if vnesh.get('is_error'):
        raise OshibkaAgenta(f"агент закончил с ошибкой ({vnesh.get('subtype')}): {str(vnesh.get('result'))[-300:]}")
    return _json_iz_teksta(vnesh.get('result'))


def zapustit_agenta(z, s):
    komanda = list(s['komanda']) + [prompt(z, s)] + list(s.get('flagi') or [])
    r = subprocess.run(komanda, cwd=os.path.expanduser(s['papka']), capture_output=True, text=True,
                       timeout=s['tajmaut_sek'], stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise OshibkaAgenta(f'код {r.returncode}: {(r.stderr or r.stdout or "")[-300:]}')
    return razobrat_vyvod(r.stdout)


def v_papke(put, papka):
    put, papka = os.path.realpath(put), os.path.realpath(papka)
    return os.path.commonpath([put, papka]) == papka


# ---------- обработка ----------

def obrabotat_zayavku(z, put, s):
    """Одна заявка: v_rabote → агент → voprosy / gotovo / oshibka. Возвращает строку ответа."""
    izmenit(put, z['id'], lambda x: x.update(status='v_rabote', nachato=seychas(), popytki=x.get('popytki', 0) + 1))
    otvet = {'id': z['id'], 'kto': z.get('kto'), 'chto': z.get('chto'), 'vremya': None}
    try:
        rez = zapustit_agenta(z, s)
        voprosy = [str(v) for v in rez.get('voprosy') or [] if str(v).strip()]
        if voprosy:
            otvet.update(status='voprosy', voprosy=voprosy[:5])
        elif rez.get('fail'):
            fail = os.path.expanduser(str(rez['fail']))
            if not os.path.isabs(fail):
                fail = os.path.join(os.path.expanduser(s['papka']), fail)
            if not os.path.isfile(fail):
                raise OshibkaAgenta(f'агент назвал файл, но его нет: {fail}')
            if not v_papke(fail, os.path.expanduser(s['chernoviki'])):
                raise OshibkaAgenta(f'черновик сохранён не в папку черновиков: {fail}')
            otvet.update(status='gotovo', fail=fail, istochniki=[str(x) for x in rez.get('istochniki') or []],
                         chto_izmeneno=str(rez.get('chto_izmeneno') or ''), proverki=str(rez.get('proverki') or ''))
        else:
            raise OshibkaAgenta('агент не вернул ни черновика, ни вопросов')
    except subprocess.TimeoutExpired:
        otvet.update(status='oshibka', oshibka=f"агент не уложился в {s['tajmaut_sek'] // 60} мин")
    except FileNotFoundError as e:
        otvet.update(status='oshibka', oshibka=f'не найдена команда агента ({e.filename}) — проверьте sostavitel.komanda')
    except (OshibkaAgenta, OSError) as e:
        otvet.update(status='oshibka', oshibka=str(e))
    otvet['vremya'] = seychas()
    polya = {k: otvet[k] for k in ('status', 'voprosy', 'fail', 'istochniki', 'chto_izmeneno', 'proverki', 'oshibka')
             if k in otvet}
    polya['zakoncheno'] = otvet['vremya']
    izmenit(put, z['id'], polya)
    dopisat_otvet(put_otvetov(put), otvet)
    return otvet


def zastryavshie(put, s):
    """Заявки в v_rabote при запуске — значит, прошлый запуск упал (мы держим замок составителя).
    Возвращаем их в очередь, но не бесконечно."""
    for z in prochitat(put):
        if z.get('status') != 'v_rabote':
            continue
        if z.get('popytki', 0) < s['popytok']:
            izmenit(put, z['id'], {'status': 'novaya'})
        else:
            otvet = {'id': z['id'], 'kto': z.get('kto'), 'chto': z.get('chto'), 'status': 'oshibka',
                     'oshibka': f"агент {z.get('popytki')} раза не довёл заявку до конца", 'vremya': seychas()}
            izmenit(put, z['id'], {'status': 'oshibka', 'oshibka': otvet['oshibka']})
            dopisat_otvet(put_otvetov(put), otvet)


def obrabotat_ochered(nast=None):
    """Обработать новые заявки по одной (новые и вернувшиеся с ответами подхватываются по ходу)."""
    nast = nast or poisk.nastroyki()
    s = nastroyki_sostavitelya(nast)
    put = put_ocheredi(nast)
    zastryavshie(put, s)
    gotovo = []
    for _ in range(s['za_raz']):
        z = next((z for z in prochitat(put) if z.get('status') == 'novaya'), None)
        if not z:
            break
        print(f"{seychas()} заявка {z['id']}: {z.get('chto', '')[:80]}")
        o = obrabotat_zayavku(z, put, s)
        print(f"  → {o['status']}" + (f": {o.get('oshibka')}" if o.get('oshibka') else ''))
        gotovo.append(o)
    return gotovo


def glavnaya():
    nast = poisk.nastroyki()
    put = put_ocheredi(nast)
    if '--spisok' in sys.argv:
        for z in prochitat(put):
            print(f"{z.get('id')}  {z.get('status'):<9} {z.get('proekt_imya') or ''}  {z.get('chto', '')[:70]}")
        return
    # один составитель за раз: launchd запускает раз в минуту, а агент может работать дольше
    os.makedirs(os.path.dirname(put), exist_ok=True)
    with open(os.path.join(os.path.dirname(put), 'sostavitel.zamok'), 'a') as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        obrabotat_ochered(nast)


if __name__ == '__main__':
    glavnaya()
