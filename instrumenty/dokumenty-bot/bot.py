"""Telegram-бот «АРХИВУД Документы»: поиск и выдача файлов из каталога.

Запуск на Mac:  /opt/homebrew/bin/python3 bot.py
Работает через long polling (getUpdates), только библиотекой requests.
Каталог (SQLite) заполняет katalog.py; здесь чтение через poisk.py.
Соединение с базой открывается на каждый запрос — так бот видит свежий каталог.

Каркас: в меню и поиске — только актуальные (крайние) версии документов, по разделам
karkas.TIPY; у проектов с «разрезом» (зоны, этажи, объекты) — выбор значения разреза.
Старые версии — кнопкой «История версий» или в поиске со словом «архив».

«📝 Составить документ»: короткий диалог → заявка в очередь (zayavki.jsonl) →
sostavitel.py запускает агента на Mac → бот раз в 30 секунд забирает ответы
(вопросы агента или готовый черновик) и присылает их тому, кто заказал.

«Одно рабочее окно»: с каждым новым запросом прежние ответы бота и само сообщение пользователя
удаляются — в чате только текущий экран и присланный файл (кроме черновиков: они живут до кнопки
«Готово — закрыть»). Что показано, записано в okna.json рядом с базой — переживает перезапуск.
Файлы уходят документами; file_id Telegram запоминается по sha1 файла (telegram_faily.json),
повторно файл отправляется по file_id без загрузки.

Ключ бота лежит в отдельном файле (nastroyki.json → klyuch_bota) и никогда
не попадает в журнал: формат журнала вырезает его из любых строк.
"""
import contextlib
import hashlib
import html
import json
import logging
import os
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from logging.handlers import RotatingFileHandler

import requests

import karkas
import poisk
import sostavitel

API = 'https://api.telegram.org'
NA_STRANICE = 8               # файлов в списке раздела
MAKS_NAJDENO = 7              # результатов поиска
MAKS_SVEZHIH = 10             # файлов в /svezhee
MAKS_OSNOV = 3                # документов-основ для черновика
MAKS_V_KARTOCHKE = 40         # кнопок приложений/записок на одном экране
MAKS_RAZMER = 49 * 1024 * 1024  # больше этого Telegram-боту не отправить
MAKS_GOLOS_SEK = 180          # голосовые длиннее — не распознаём
DLINA_KNOPKI = 40             # обрезка имени файла на кнопке
PROVERKA_OTVETOV_SEK = 30     # как часто смотреть ответы составителя
OPROS_SEK = 25                # long polling: не дольше, чтобы успевать проверять ответы

DOGOVORY = poisk.DOGOVORY
KNOPKA_SOSTAVIT = '📝 Составить документ'
DLYA = [('zak', 'Заказчику'), ('vn', 'Внутренний'), ('kon', 'Конструктору'), ('mon', 'Монтажникам')]
SROKI = [('seg', 'Сегодня'), ('zav', 'Завтра'), ('ns', 'Не срочно')]

log = logging.getLogger('dokumenty')

KLYUCH = None          # ключ бота, читается из файла при запуске
NAST = None            # настройки из nastroyki.json (перечитываются при изменении)
_NAST_VREMYA = None
_MODEL = None          # модель распознавания голоса, грузится один раз при первом голосовом
_UZHE_PROSILI = set()  # кто уже просил доступ с момента запуска (чтобы не засыпать админа)
_DIALOGI = {}          # telegram_id → состояние диалога «Составить документ» / ответа на вопросы агента
_POSLEDNIJ_ZAPROS = {}  # telegram_id → последний поиск, который ничего не нашёл

TEKST_POMOSHCH = (
    '<b>Как искать</b>\n'
    'Просто напишите, что нужно: «договор олимпийский», «чертёж прихожей», '
    '«смета двери». Я пришлю до 7 подходящих документов — нажмите на кнопку, '
    'и файл придёт сюда. Показываю только актуальные (крайние) версии.\n\n'
    '<b>Старые версии</b>\n'
    'У файла есть кнопка «История версий». Или добавьте к запросу «архив», '
    '«все версии» или «старые».\n\n'
    '<b>Кнопки</b>\n'
    '«Проекты» — документы по проектам и разделам, свежие сверху.\n'
    '«Свежее» — 10 последних документов.\n'
    '«📝 Составить документ» — опишите, что нужно, и агент подготовит черновик.\n\n'
    '<b>Голос</b>\n'
    'Можно надиктовать запрос голосовым сообщением — я распознаю и поищу.\n\n'
    '<b>Одно окно</b>\n'
    'Прежние ответы я убираю — в чате всегда только текущий экран и присланный файл. '
    'Черновик от «Составить документ» остаётся, пока не нажмёте «Готово — закрыть».\n\n'
    'Команды: /start — меню, /svezhee — свежие, /sostavit — составить документ, /pomosh — подсказка.'
)
TEKST_PUSTO = ('Ничего не нашёл. Попробуйте другие слова: например, '
               '«договор олимпийский» или «чертёж прихожей».\n'
               'Или я составлю такой документ — нажмите «📝 Составить документ».')
TEKST_OSHIBKA = 'Что-то пошло не так, попробуйте ещё раз.'
TEKST_USTARELA = 'Кнопка устарела. Нажмите «Проекты».'
TEKST_CHERNOVIK = 'Черновик — проверьте перед отправкой. Источники: '

KLAVIATURA = {'keyboard': [[{'text': 'Проекты'}, {'text': 'Свежее'}],
                           [{'text': KNOPKA_SOSTAVIT}, {'text': 'Помощь'}]],
              'resize_keyboard': True, 'is_persistent': True}
KNOPKI_KLAVIATURY = ('Проекты', 'Свежее', 'Помощь', KNOPKA_SOSTAVIT)


class NetKataloga(Exception):
    """Файла каталога ещё нет (katalog.py не запускался)."""


# ---------- журнал ----------

class _BezKlyucha(logging.Formatter):
    """Формат журнала, который вырезает ключ бота из любых строк (в т.ч. из адресов в ошибках)."""
    def format(self, zapis):
        s = super().format(zapis)
        return s.replace(KLYUCH, '***') if KLYUCH else s


def nastroit_zhurnal():
    put = os.path.expanduser(NAST['zhurnal'])
    os.makedirs(os.path.dirname(put), exist_ok=True)
    fmt = _BezKlyucha('%(asctime)s %(levelname)s %(message)s', '%Y-%m-%d %H:%M:%S')
    koren = logging.getLogger()  # на корень — чтобы и сообщения requests/urllib3 шли через формат без ключа
    koren.setLevel(logging.INFO)
    obrabotchiki = [RotatingFileHandler(put, maxBytes=2 * 1024 * 1024, backupCount=3, encoding='utf-8')]
    if sys.stderr.isatty():  # запуск руками — журнал и на экран; под launchd — только в файл
        obrabotchiki.append(logging.StreamHandler(sys.stderr))
    for h in obrabotchiki:
        h.setFormatter(fmt)
        koren.addHandler(h)
    logging.getLogger('urllib3').setLevel(logging.WARNING)


def obnovit_nastroyki():
    """Перечитать nastroyki.json, если файл изменился (например, добавили пользователя)."""
    global NAST, _NAST_VREMYA
    try:
        t = os.path.getmtime(os.environ.get('DOKUMENTY_NASTROYKI') or poisk.NASTROYKI)
    except OSError:
        return
    if t == _NAST_VREMYA:
        return
    try:
        NAST = poisk.nastroyki()
        if _NAST_VREMYA is not None:
            log.info('Настройки перечитаны')
        _NAST_VREMYA = t
    except Exception:
        if NAST is None:
            raise
        log.exception('nastroyki.json не читается, работаю со старыми настройками')


# ---------- Telegram ----------

def api(metod, files=None, zhdat=30, tiho=False, **par):
    """Вызов метода Telegram. Возвращает ответ целиком ({'ok': ..., 'result': ...}).
    tiho — неудачу не писать в журнал как предупреждение (удаление старых сообщений и т.п.)."""
    url = f'{API}/bot{KLYUCH}/{metod}'
    if files:
        data = {k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
                for k, v in par.items() if v is not None}
        r = requests.post(url, data=data, files=files, timeout=zhdat)
    else:
        r = requests.post(url, json={k: v for k, v in par.items() if v is not None}, timeout=zhdat)
    otvet = r.json()
    if not otvet.get('ok'):
        opis = otvet.get('description', '')
        if 'message is not modified' not in opis:
            (log.info if tiho else log.warning)('Telegram %s: %s %s', metod, otvet.get('error_code'), opis)
    return otvet


def _razmetka(knopki=None, klaviatura=None):
    if knopki:
        return {'inline_keyboard': knopki}
    return klaviatura


def otpravit(chat, tekst, knopki=None, klaviatura=None):
    """Просто отправить сообщение (в окно не записывается: уведомления админу, чужим)."""
    if len(tekst) > 4000:
        tekst = tekst[:4000] + '…'
    return api('sendMessage', chat_id=chat, text=tekst, parse_mode='HTML',
               disable_web_page_preview=True, reply_markup=_razmetka(knopki, klaviatura))


def otvetit_knopke(cq, tekst=None):
    try:
        api('answerCallbackQuery', callback_query_id=cq['id'], text=tekst)
    except Exception:
        log.exception('answerCallbackQuery не прошёл')


# ---------- «одно рабочее окно» ----------
# В чате с ботом всегда только текущий ответ. Что бот показал в чате, записано в okna.json
# рядом с базой: {chat: [{"id": message_id, "vid": "ekran"|"dop"|"chernovik", "fail": true?, "gruppa": ...}]}.
#   ekran     — экран меню/списка (его правят кнопками навигации);
#   dop       — всё остальное: присланный файл, «Распознал…», сообщения об ошибках, вопросы агента;
#   chernovik — черновик от составителя: живёт, пока не нажмут «Готово — закрыть».
# Новый запрос (сообщение или кнопка, показавшая новый экран): всё прежнее, кроме черновиков, удаляется;
# входящее сообщение пользователя — тоже. Файл записан на диск, поэтому и после перезапуска бот
# удалит то, что показывал до него.

OKNA = 'okna.json'
FAJLY_TG = 'telegram_faily.json'   # {sha1 файла: file_id в Telegram} — повторно отправляем без загрузки


def put_ryadom(imya):
    """Служебный файл рядом с базой каталога."""
    return os.path.join(os.path.dirname(os.path.expanduser(NAST['baza'])) or '.', imya)


def chitat_slovar(put):
    try:
        with open(put, encoding='utf-8') as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def pisat_slovar(put, d):
    """Записать целиком: во временный файл и подменить — при сбое не останется половины."""
    os.makedirs(os.path.dirname(put) or '.', exist_ok=True)
    with open(put + '.novyj', 'w', encoding='utf-8') as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(put + '.novyj', put)


def okno(chat):
    return [e for e in chitat_slovar(put_ryadom(OKNA)).get(str(chat), []) if isinstance(e, dict) and e.get('id')]


def sohranit_okno(chat, zapisi):
    put = put_ryadom(OKNA)
    d = chitat_slovar(put)
    vidannye, chistye = set(), []
    for e in zapisi:                 # без повторов: одно сообщение — одна запись (последняя)
        if e['id'] in vidannye:
            chistye = [x for x in chistye if x['id'] != e['id']]
        vidannye.add(e['id'])
        chistye.append(e)
    if chistye:
        d[str(chat)] = chistye
    else:
        d.pop(str(chat), None)
    pisat_slovar(put, d)


def zapomnit(chat, mid, vid='dop', **dop):
    if mid:
        sohranit_okno(chat, okno(chat) + [dict(id=mid, vid=vid, **dop)])


def _mid(otvet):
    return (otvet.get('result') or {}).get('message_id') if otvet.get('ok') else None


def ubrat(chat, e):
    """Удалить сообщение. Не вышло (старше 48 ч, уже удалено) — хотя бы стереть текст и кнопки."""
    try:
        if api('deleteMessage', tiho=True, chat_id=chat, message_id=e['id']).get('ok'):
            return
        if e.get('fail'):
            api('editMessageCaption', tiho=True, chat_id=chat, message_id=e['id'], caption='—',
                reply_markup={'inline_keyboard': []})
        else:
            api('editMessageText', tiho=True, chat_id=chat, message_id=e['id'], text='—',
                reply_markup={'inline_keyboard': []})
    except (requests.RequestException, ValueError) as oshibka:
        log.info('Не удалось убрать сообщение %s: %s', e.get('id'), oshibka)


def posledni_ekran(chat):
    return next((e['id'] for e in reversed(okno(chat)) if e['vid'] == 'ekran'), None)


@contextlib.contextmanager
def zapros(chat, vhodyashchee=None):
    """Один запрос пользователя. Внутри окно содержит только черновики; всё, что запрос покажет,
    записывается туда. В конце прежние сообщения, которых нет в новом окне, удаляются.
    Кнопка, которая ничего нового не показала (устарела, всплывающая подсказка), окно не трогает."""
    staroe = okno(chat)
    sohranit_okno(chat, [e for e in staroe if e['vid'] == 'chernovik'])
    try:
        yield
    finally:
        novoe = okno(chat)
        if vhodyashchee is None and not any(e['vid'] != 'chernovik' for e in novoe):
            ostavshiesya = {e['id'] for e in novoe}
            sohranit_okno(chat, [e for e in staroe if e['vid'] != 'chernovik' or e['id'] in ostavshiesya]
                          + novoe)
        else:
            ostavit = {e['id'] for e in novoe}
            for e in staroe:
                if e['id'] not in ostavit:
                    ubrat(chat, e)
            if vhodyashchee:
                ubrat(chat, {'id': vhodyashchee})


def pokazat(chat, tekst, knopki=None, klaviatura=None, vid='dop', **dop):
    """Отправить сообщение и записать его в окно."""
    otvet = otpravit(chat, tekst, knopki, klaviatura)
    zapomnit(chat, _mid(otvet), vid, **dop)
    return otvet


def ekran(chat, tekst, knopki=None, mid=None, klaviatura=None):
    """Показать экран: править сообщение mid (навигация кнопками), а нет его — прислать новым."""
    if mid:
        otvet = api('editMessageText', chat_id=chat, message_id=mid, text=tekst[:4000], parse_mode='HTML',
                    disable_web_page_preview=True, reply_markup=_razmetka(knopki) or {'inline_keyboard': []})
        if otvet.get('ok') or 'message is not modified' in otvet.get('description', ''):
            zapomnit(chat, mid, 'ekran')
            return otvet
        ubrat(chat, {'id': mid})
    return pokazat(chat, tekst, knopki, klaviatura, vid='ekran')


def otpravit_dokument(chat, put, imya, caption, knopki=None, vid='dop', **dop):
    """Файл документом. Уже отправляли такой же (по sha1) — по file_id, без загрузки;
    Telegram не принял file_id — загружаем заново. Возвращает ответ Telegram."""
    h = hesh_faila(put)
    put_kesha = put_ryadom(FAJLY_TG)
    kesh = chitat_slovar(put_kesha)
    razmetka = {'inline_keyboard': knopki} if knopki else None
    otvet = None
    if kesh.get(h):
        otvet = api('sendDocument', tiho=True, chat_id=chat, document=kesh[h], caption=caption,
                    parse_mode='HTML', reply_markup=razmetka)
        if not otvet.get('ok'):
            log.info('file_id не принят — загружаю %s заново', imya)
            kesh.pop(h, None)
            pisat_slovar(put_kesha, kesh)
            otvet = None
    if otvet is None:
        api('sendChatAction', chat_id=chat, action='upload_document')
        with open(put, 'rb') as fh:
            otvet = api('sendDocument', files={'document': (imya, fh)}, zhdat=300, chat_id=chat,
                        caption=caption, parse_mode='HTML', reply_markup=razmetka)
        file_id = ((otvet.get('result') or {}).get('document') or {}).get('file_id') if otvet.get('ok') else None
        if file_id:
            kesh = chitat_slovar(put_kesha)
            kesh[h] = file_id
            pisat_slovar(put_kesha, kesh)
    zapomnit(chat, _mid(otvet), vid, fail=True, **dop)
    return otvet


def hesh_faila(put):
    h = hashlib.sha1()
    with open(put, 'rb') as fh:
        for kusok in iter(lambda: fh.read(1 << 20), b''):
            h.update(kusok)
    return h.hexdigest()


# ---------- оформление ----------

def esc(s):
    return html.escape(str(s or ''), quote=False)


def korotko(imya, n=DLINA_KNOPKI):
    """Обрезать длинное имя файла, сохранив расширение: «Очень длинный дог….pdf»."""
    imya = imya or ''
    if len(imya) <= n:
        return imya
    osn, rassh = os.path.splitext(imya)
    if len(rassh) > 6:
        rassh = ''
    return osn[:max(1, n - len(rassh) - 1)].rstrip() + '…' + rassh


def obrezat(s, n=DLINA_KNOPKI):
    """Обрезать название (без расширения)."""
    s = s or ''
    return s if len(s) <= n else s[:n - 1].rstrip() + '…'


def data_korotko(d):
    """'2026-10-28T13:01:57' → '28.10'."""
    d = d or ''
    return f'{d[8:10]}.{d[5:7]}' if len(d) >= 10 else ''


def data_polnaya(d):
    d = d or ''
    return f'{d[8:10]}.{d[5:7]}.{d[:4]}' if len(d) >= 10 else ''


def razmer_mb(b):
    return f'{b / 1024 / 1024:.1f}'.replace('.', ',') + ' МБ'


def nastroyki_proekta(pid):
    for p in NAST.get('proekty', []):
        if p.get('id') == pid:
            return p
    return {}


def imya_proekta(f):
    if f.get('proekt_imya'):
        return f['proekt_imya']
    return nastroyki_proekta(f.get('proekt')).get('imya') or f.get('proekt') or 'Без проекта'


def imya_razreza(pid):
    """Как называется разрез проекта: «Зона», «Этаж», «Объект» (nastroyki.json → proekty[].razrez.imya)."""
    return (nastroyki_proekta(pid).get('razrez') or {}).get('imya') or 'Зона'


def poryadok_razreza(pid):
    r = nastroyki_proekta(pid).get('razrez') or {}
    return [z['id'] for z in r.get('znacheniya', []) if z.get('id')] or None


def podpis_zony(pid, zona):
    """«Зона АГ», «Объект Озерки»; если значение уже называет разрез («2 этаж») — без повтора."""
    if not zona:
        return ''
    imya = imya_razreza(pid)
    return zona if imya.lower()[:4] in zona.lower() else f'{imya} {zona}'


def bez_zony(pid):
    return 'Без зоны' if imya_razreza(pid) == 'Зона' else 'Остальные'


def nazvanie(f):
    return f.get('nazvanie') or f.get('imya') or ''


def imya_knopki(f):
    """На кнопке: у приложения к договору — его роль («Приложение 2 — ТЗ на накладки»), иначе чистое название."""
    rol = f.get('rol') or ''
    if f.get('tip') == DOGOVORY and rol.startswith('Приложение'):
        return rol
    return nazvanie(f)


def gde(f):
    """«Олимпийский · Договоры · Зона АГ · Приложение 1 — Смета»."""
    rol = f.get('rol') if f.get('tip') == DOGOVORY else ''
    return ' · '.join(x for x in (imya_proekta(f), f.get('tip') or f.get('razdel'),
                                  podpis_zony(f.get('proekt'), f.get('zona')), rol) if x)


def otkuda(f):
    if f.get('otkuda'):
        return f['otkuda']
    return f"от: {f['otkogo']}" if f.get('otkogo') else ''


def formaty(f):
    return (f.get('formaty') or '').replace(',', '+')


def knopka_faila(f, nomer=None, metka=''):
    tekst = metka + obrezat(imya_knopki(f))
    dk = data_korotko(f.get('data'))
    if dk:
        tekst += f' · {dk}'
    if nomer:
        tekst = f'{nomer}. {tekst}'
    return {'text': tekst, 'callback_data': f"f:{f['id']}"}


def chistyj_otryvok(s, n=180):
    s = ' '.join((s or '').split())
    if len(s) > n:
        s = s[:n].rstrip() + '…'
    return s


# ---------- пользователи и база ----------

def polzovatel(uid):
    for p in NAST.get('polzovateli', []):
        if p.get('telegram_id') is not None and str(p['telegram_id']) == str(uid):
            return p
    return None


def dostup_polzovatelya(p):
    # нет поля «proekty» — значит ничего (безопаснее, чем «всё»)
    return {'proekty': p.get('proekty', []), 'bez_vnutrennego': bool(p.get('bez_vnutrennego'))}


def otkryt_bazu():
    put = os.path.expanduser(NAST['baza'])
    if not os.path.isfile(put):
        raise NetKataloga(put)
    return poisk.baza(put)


def chuzhoj(chat, kto):
    """Незнакомый пользователь: сказать его номер, записать в журнал, сообщить админу."""
    uid = kto.get('id')
    imya = ' '.join(x for x in (kto.get('first_name'), kto.get('last_name')) if x) or '(без имени)'
    un = kto.get('username')
    log.warning('Нет доступа: %s @%s, номер %s', imya, un or '-', uid)
    otpravit(chat, f'Нет доступа. Ваш номер Telegram: {uid}. '
                   f'Передайте его Мансуру, чтобы он добавил вас.')
    if uid in _UZHE_PROSILI:
        return
    _UZHE_PROSILI.add(uid)
    for a in NAST.get('polzovateli', []):
        if a.get('admin') and a.get('telegram_id'):
            try:
                otpravit(a['telegram_id'], f'Просит доступ: {esc(imya)} '
                                           f'{"@" + esc(un) if un else "(без username)"}, номер <code>{uid}</code>')
            except Exception:
                log.exception('Не удалось уведомить админа')


# ---------- экраны меню ----------
# Кнопки (callback_data, до 64 байт):
#   m                 — проекты
#   p:<проект>        — разделы каркаса проекта
#   t:<проект>:<i>    — вход в раздел karkas.TIPY[i] (выбор зоны/этажа или сразу список)
#   l:<проект>:<i>:<z>:<с> — список раздела; z — номер значения разреза, x — без значения, * — все
#   z:<проект>:<z>    — карточка договора по значению разреза (зона)
#   zp:<проект>:<z>   — записки к договорам
#   v:<id>            — история версий;  f:<id> — прислать файл
#   a:<id> / h:<id>   — сделать актуальной / убрать в историю
#   sd, sdq, sp:, sk:, ss:, sx, so: — «Составить документ» и ответы на вопросы агента

def nazad_k_proektu(proekt):
    return [{'text': 'Назад', 'callback_data': f'p:{proekt}'}]


def ekran_proektov(con, dostup):
    pr = [p for p in poisk.proekty(con, dostup) if p['proekt']]
    if not pr:
        return 'Пока нет доступных документов.', None
    return 'Выберите проект:', [
        [{'text': f"{imya_proekta(p)} ({p['n']})", 'callback_data': f"p:{p['proekt']}"}] for p in pr]


def ekran_tipov(con, proekt, dostup):
    tp = poisk.tipy(con, proekt, dostup)
    if not tp:
        return 'В этом проекте нет доступных документов.', [[{'text': 'Назад', 'callback_data': 'm'}]]
    imya = imya_proekta({'proekt': proekt})
    knopki = [[{'text': f"{t['tip']} ({t['n']})", 'callback_data': f"t:{proekt}:{karkas.TIPY.index(t['tip'])}"}]
              for t in tp]
    knopki.append([{'text': 'Назад', 'callback_data': 'm'}])
    return f'<b>{esc(imya)}</b>\nВыберите раздел:', knopki


def tip_po_nomeru(i):
    if 0 <= i < len(karkas.TIPY) and karkas.TIPY[i] not in poisk.SKRYTYE_TIPY:
        return karkas.TIPY[i]
    return None


def zony_razdela(con, proekt, tip, dostup):
    return poisk.zony(con, proekt, dostup, tip=tip, poryadok=poryadok_razreza(proekt))


def zona_po_klyuchu(zn, zk):
    """Ключ кнопки → значение разреза: '*' → None (все), 'x' → '' (без значения), номер → значение.
    Устаревший ключ → False."""
    if zk == '*':
        return None
    if zk == 'x':
        return ''
    if zk.isdigit() and int(zk) < len(zn) and zn[int(zk)]['zona']:
        return zn[int(zk)]['zona']
    return False


def klyuch_zony(zn, zona):
    if not zona:
        return 'x'
    return next((str(i) for i, z in enumerate(zn) if z['zona'] == zona), 'x')


def nuzhen_vybor_zony(tip, zn):
    """Сначала выбрать зону/этаж: у договоров — всегда, если у них есть значения разреза;
    в других разделах — если документов больше страницы."""
    if not any(z['zona'] for z in zn):
        return False
    return tip == DOGOVORY or sum(z['n'] for z in zn) > NA_STRANICE


def ekran_vhoda(con, proekt, i, dostup):
    tip = tip_po_nomeru(i)
    if not tip:
        return ekran_tipov(con, proekt, dostup)
    zn = zony_razdela(con, proekt, tip, dostup)
    if not zn:  # каталог поменялся — показываем разделы заново
        return ekran_tipov(con, proekt, dostup)
    if nuzhen_vybor_zony(tip, zn):
        return ekran_vybora_zony(con, proekt, i, tip, zn)
    if tip == DOGOVORY:
        return ekran_dogovora(con, proekt, 'x', dostup)
    return ekran_spiska(con, proekt, i, '*', 0, dostup)


def ekran_vybora_zony(con, proekt, i, tip, zn):
    imya = imya_proekta({'proekt': proekt})
    razrez = imya_razreza(proekt)
    knopki = []
    for k, z in enumerate(zn):
        cel = (f'z:{proekt}:' if tip == DOGOVORY else f'l:{proekt}:{i}:') + (str(k) if z['zona'] else 'x')
        if tip != DOGOVORY:
            cel += ':0'
        knopki.append([{'text': f"{z['zona'] or bez_zony(proekt)} ({z['n']})", 'callback_data': cel}])
    knopki.append([{'text': f"Все ({sum(z['n'] for z in zn)})", 'callback_data': f'l:{proekt}:{i}:*:0'}])
    knopki.append(nazad_k_proektu(proekt))
    return f'<b>{esc(imya)} · {esc(tip)}</b>\nВыберите: {esc(razrez.lower())}', knopki


def ekran_spiska(con, proekt, i, zk, smeshchenie, dostup):
    tip = tip_po_nomeru(i)
    if not tip:
        return ekran_tipov(con, proekt, dostup)
    zn = zony_razdela(con, proekt, tip, dostup)
    zona = zona_po_klyuchu(zn, zk)
    if zona is False:
        return ekran_vhoda(con, proekt, i, dostup)
    vsego = poisk.skolko(con, proekt, tip, dostup, zona)
    if not vsego:
        return ekran_tipov(con, proekt, dostup)
    smeshchenie = max(0, smeshchenie)
    faily = poisk.spisok(con, proekt, tip, dostup, smeshchenie, NA_STRANICE + 1, zona=zona)
    est_eshche = len(faily) > NA_STRANICE
    faily = faily[:NA_STRANICE]
    zag = f"<b>{esc(imya_proekta({'proekt': proekt}))} · {esc(tip)}"
    if zona:
        zag += f' · {esc(podpis_zony(proekt, zona))}'
    elif zona == '':
        zag += f' · {esc(bez_zony(proekt).lower())}'
    zag += '</b>\n'
    if faily:
        zag += (f"Документы {smeshchenie + 1}–{smeshchenie + len(faily)} из {vsego}, свежие сверху. "
                f"Нажмите, чтобы получить.")
    else:
        zag += 'Здесь больше ничего нет.'
    knopki = [[knopka_faila(f)] for f in faily]
    niz = []
    if smeshchenie > 0:
        niz.append({'text': 'Назад', 'callback_data': f'l:{proekt}:{i}:{zk}:{max(0, smeshchenie - NA_STRANICE)}'})
        niz.append({'text': 'К разделам', 'callback_data': f'p:{proekt}'})
    elif nuzhen_vybor_zony(tip, zn):
        niz.append({'text': 'Назад', 'callback_data': f't:{proekt}:{i}'})
    else:
        niz.append({'text': 'Назад', 'callback_data': f'p:{proekt}'})
    if est_eshche:
        niz.append({'text': 'Ещё', 'callback_data': f'l:{proekt}:{i}:{zk}:{smeshchenie + NA_STRANICE}'})
    knopki.append(niz)
    return zag, knopki


def ekran_dogovora(con, proekt, zk, dostup):
    """Карточка договора зоны: договор (актуальная версия) + приложения + кнопка записок."""
    zn = zony_razdela(con, proekt, DOGOVORY, dostup)
    zona = zona_po_klyuchu(zn, zk)
    if zona is None or zona is False:
        return ekran_vhoda(con, proekt, karkas.TIPY.index(DOGOVORY), dostup)
    d = poisk.dogovor_zony(con, proekt, zona, dostup)
    dog, pril = d['dogovor'], d['prilozheniya'][:MAKS_V_KARTOCHKE]
    if not dog and not pril:
        return ekran_vhoda(con, proekt, karkas.TIPY.index(DOGOVORY), dostup)
    s_zonami = any(z['zona'] for z in zn)
    zag = f"<b>{esc(imya_proekta({'proekt': proekt}))} · Договоры"
    if zona:
        zag += f' · {esc(podpis_zony(proekt, zona))}'
    elif s_zonami:
        zag += f' · {esc(bez_zony(proekt).lower())}'
    stroki = [zag + '</b>']
    knopki = []
    imya_dog = f'Договор {zona}' if zona else 'Договор'
    if dog:
        stroki.append(f'\n📄 <b>{esc(imya_dog)}</b> — {esc(nazvanie(dog))}')
        detali = [x for x in (data_polnaya(dog.get('data')), otkuda(dog)) if x]
        if (dog.get('versiy') or 1) > 1:
            detali.append(f"версий: {dog['versiy']}")
        if '+' in formaty(dog):
            detali.append(formaty(dog))
        if detali:
            stroki.append(esc(' · '.join(detali)))
        knopki.append([{'text': f"📄 {imya_dog} · {data_korotko(dog.get('data'))}".rstrip(' ·'),
                        'callback_data': f"f:{dog['id']}"}])
        if (dog.get('versiy') or 1) > 1:
            knopki.append([{'text': f"История версий ({dog['versiy']})", 'callback_data': f"v:{dog['id']}"}])
    else:
        stroki.append('\nСамого договора здесь нет — только приложения и другие документы.')
    if pril:
        stroki.append('\n<b>Приложения и другие документы:</b>')
        for f in pril:
            stroki.append(f"• {esc(imya_knopki(f))} · {data_korotko(f.get('data'))}")
            knopki.append([knopka_faila(f)])
    zap = poisk.zapiski(con, proekt, zona, dostup)
    if zap:
        knopki.append([{'text': f'📝 Записки к договорам ({len(zap)})', 'callback_data': f'zp:{proekt}:{zk}'}])
    knopki.append([{'text': 'Назад', 'callback_data': f't:{proekt}:{karkas.TIPY.index(DOGOVORY)}'}]
                  if s_zonami else nazad_k_proektu(proekt))
    return '\n'.join(stroki), knopki


def ekran_zapisok(con, proekt, zk, dostup):
    zn = zony_razdela(con, proekt, DOGOVORY, dostup)
    zona = zona_po_klyuchu(zn, zk)
    if zona is None or zona is False:
        zona = ''
    zap = poisk.zapiski(con, proekt, zona, dostup)
    zag = f"<b>{esc(imya_proekta({'proekt': proekt}))} · Записки к договорам</b>\n"
    if not zap:
        zag += 'Записок и разборов нет.'
    elif zona and any(f.get('zona') == zona for f in zap):
        zag += f'Пояснительные записки и разборы проекта; сначала — {esc(podpis_zony(proekt, zona))}.'
    else:
        zag += 'Пояснительные записки и разборы проекта, свежие сверху.'
    knopki = [[knopka_faila(f, metka='★ ' if zona and f.get('zona') == zona else '')]
              for f in zap[:MAKS_V_KARTOCHKE]]
    knopki.append([{'text': 'К договору', 'callback_data': f'z:{proekt}:{zk}'}])
    return zag, knopki


def nomer_versii(f, vse):
    """«версия K из N»: K — место файла среди версий по дате (от старых к новым)."""
    po_date = sorted(vse, key=lambda v: (v.get('data') or '', v['id']))
    k = next((n for n, v in enumerate(po_date, 1) if v['id'] == f['id']), len(po_date))
    return k, len(po_date)


def ekran_versiy(con, fid, dostup):
    f = poisk.fail(con, fid, dostup)
    if not f:
        return 'Файл не найден или к нему нет доступа.', None
    vse = poisk.versii(con, f['semya'], dostup) if f.get('semya') else [f]
    stroki = [f'<b>История версий: {esc(nazvanie(f))}</b>', esc(gde(f)),
              f'Всего версий: {len(vse)}. ✓ — актуальная, её видно в меню и поиске.']
    knopki = []
    for v in vse:
        metka = '✓ ' if v.get('aktualno') else ('🗄 ' if v.get('arhiv') else '')
        tekst = f"{metka}{data_polnaya(v.get('data')) or '—'} · {korotko(v.get('imya'), 30)}"
        knopki.append([{'text': tekst, 'callback_data': f"f:{v['id']}"}])
    knopki.append(nazad_k_proektu(f['proekt']) if f.get('proekt') else [{'text': 'К проектам', 'callback_data': 'm'}])
    return '\n'.join(stroki), knopki


def spisok_faylov(zag, faily, s_otryvkom=False):
    """Текст со списком файлов и кнопки «получить» под ним (для поиска и /svezhee)."""
    stroki = [zag]
    for n, f in enumerate(faily, 1):
        s = f"\n{n}. <b>{esc(obrezat(nazvanie(f), 90))}</b>\n{esc(gde(f))}"
        if data_polnaya(f.get('data')):
            s += f" · {data_polnaya(f['data'])}"
        if otkuda(f):
            s += f"\n{esc(otkuda(f))}"
        if f.get('aktualno') == 0:
            s += '\n<i>старая версия</i>'
        otr = chistyj_otryvok(f.get('otryvok')) if s_otryvkom else ''
        if otr:
            s += f'\n<i>…{esc(otr)}…</i>'
        stroki.append(s)
    return '\n'.join(stroki), [[knopka_faila(f, n)] for n, f in enumerate(faily, 1)]


# ---------- действия ----------

def pokazat_proekty(chat, dostup):
    con = otkryt_bazu()
    try:
        tekst, knopki = ekran_proektov(con, dostup)
    finally:
        con.close()
    ekran(chat, tekst, knopki)


def svezhee(chat, dostup):
    con = otkryt_bazu()
    try:
        faily = poisk.svezhie(con, dostup, MAKS_SVEZHIH)
    finally:
        con.close()
    if not faily:
        ekran(chat, 'Пока нет доступных документов.')
        return
    ekran(chat, *spisok_faylov('<b>Свежие документы</b>', faily))


def iskat(chat, uid, tekst, dostup):
    con = otkryt_bazu()
    try:
        rez = poisk.najti(con, tekst, dostup, MAKS_NAJDENO)
    finally:
        con.close()
    if not rez:
        _POSLEDNIJ_ZAPROS[uid] = tekst
        ekran(chat, TEKST_PUSTO, [[{'text': KNOPKA_SOSTAVIT, 'callback_data': 'sdq'}]])
        return
    zag = f'Нашёл: {len(rez)}'
    if poisk.eto_zapros_arhiva(tekst):
        zag += ' (вместе со старыми версиями)'
    tekst_s, knopki = spisok_faylov(zag, rez, s_otryvkom=True)
    knopki.append([{'text': KNOPKA_SOSTAVIT, 'callback_data': 'sd'}])
    ekran(chat, tekst_s, knopki)


def podpis(f, vse=None):
    """Подпись к файлу: название, проект · раздел · зона, дата, откуда, версия K из N, форматы."""
    stroki = [f'<b>{esc(obrezat(nazvanie(f), 200))}</b>', esc(gde(f))]
    detali = [x for x in (data_polnaya(f.get('data')), otkuda(f)) if x]
    if detali:
        stroki.append(esc(korotko(' · '.join(detali), 150)))
    k, n = nomer_versii(f, vse or [f])
    versiya = f'версия {k} из {n}' + ('' if f.get('aktualno', 1) else ' (не актуальная)')
    fm = formaty(f) or f.get('rasshirenie') or ''
    stroki.append(versiya + (f' · {esc(fm.lstrip("."))}' if fm else ''))
    return '\n'.join(stroki)


def knopki_dokumenta(f, n_versiy):
    """Под файлом: история версий и ручное решение об актуальности."""
    knopki = []
    if n_versiy > 1:
        knopki.append([{'text': f'История версий ({n_versiy})', 'callback_data': f"v:{f['id']}"}])
    if f.get('aktualno', 1):
        knopki.append([{'text': '🗄 Убрать в историю', 'callback_data': f"h:{f['id']}"}])
    else:
        knopki.append([{'text': '✅ Сделать актуальной', 'callback_data': f"a:{f['id']}"}])
    return knopki


def otpravit_fail(chat, con, fid, dostup):
    f = poisk.fail(con, fid, dostup)  # права проверяются здесь же: чужой id → None
    if not f:
        pokazat(chat, 'Файл не найден или к нему нет доступа.')
        return
    vse = poisk.versii(con, f['semya'], dostup) if f.get('semya') else [f]
    put = f['put']
    if not os.path.isfile(put) and not dostup.get('bez_vnutrennego'):
        # основной файл пропал — может, жива копия с тем же содержимым
        put = next((k for k in poisk.kopii(con, fid) if os.path.isfile(k)), put)
    if not os.path.isfile(put):
        pokazat(chat, f"<b>{esc(nazvanie(f))}</b>\nФайл не найден на диске — возможно, его переместили "
                       f"или удалили. Где он был:\n<code>{esc(f['put'])}</code>", knopki_dokumenta(f, len(vse)))
        return
    razmer = os.path.getsize(put)
    if razmer > MAKS_RAZMER:
        pokazat(chat, f"<b>{esc(nazvanie(f))}</b>\nФайл большой ({razmer_mb(razmer)}) — в Telegram "
                       f"его не отправить. Он лежит на Mac:\n<code>{esc(put)}</code>", knopki_dokumenta(f, len(vse)))
        return
    otvet = otpravit_dokument(chat, put, f['imya'], podpis(f, vse), knopki_dokumenta(f, len(vse)))
    if otvet.get('ok'):
        log.info('Отправлен файл %s → %s', fid, chat)
    else:
        pokazat(chat, f"Не получилось отправить файл. Он лежит на Mac:\n<code>{esc(put)}</code>")


def reshit_aktualnost(chat, con, fid, reshenie, dostup, p, mid=None):
    f = poisk.otmetit_vruchnuyu(con, NAST, fid, reshenie, dostup)
    if not f:
        ekran(chat, 'Файл не найден или к нему нет доступа.', mid=mid)
        return
    log.info('%s: %s → %s (%s)', p.get('imya'), f['put'], reshenie, f.get('semya'))
    nazad = nazad_k_proektu(f['proekt']) if f.get('proekt') else [{'text': 'К проектам', 'callback_data': 'm'}]
    if reshenie == 'aktualno':
        ekran(chat, f'✅ «{esc(nazvanie(f))}» — теперь актуальная версия. '
                       'В меню и поиске показывается она, остальные — в истории.', [nazad], mid=mid)
    else:
        ekran(chat, f'🗄 «{esc(nazvanie(f))}» убран в историю: в меню и поиске его больше нет. '
                       'Найти можно поиском со словом «архив» или через «История версий».',
                 [[{'text': '✅ Вернуть', 'callback_data': f"a:{f['id']}"}], nazad], mid=mid)


# ---------- «Составить документ» ----------

def dostupnye_proekty(dostup):
    pr = dostup.get('proekty', '*')
    return [p for p in NAST.get('proekty', []) if pr == '*' or p.get('id') in pr]


def otmena():
    return [{'text': 'Отмена', 'callback_data': 'sx'}]


def nachat_sostavlenie(chat, uid, chto=None, mid=None):
    """(а) что за документ → (б) проект → (в) для кого → (г) срок → заявка в очередь."""
    if not chto:
        _DIALOGI[uid] = {'shag': 'chto'}
        tekst = ('📝 <b>Составить документ</b>\nЧто за документ нужен? Напишите или надиктуйте одним '
                 'сообщением, например: «письмо Зверевой о переносе монтажа АГ на неделю».')
        return ekran(chat, tekst, [otmena()], mid)
    _DIALOGI[uid] = {'shag': 'proekt', 'chto': chto[:1000]}
    knopki = [[{'text': p['imya'], 'callback_data': f"sp:{p['id']}"}] for p in dostupnye_proekty(
        _dostup_po_uid(uid))]
    knopki.append(otmena())
    tekst = f'📝 Составлю: «{esc(chto)}»\nПо какому проекту?'
    return ekran(chat, tekst, knopki, mid)


def _dostup_po_uid(uid):
    p = polzovatel(uid)
    return dostup_polzovatelya(p) if p else {'proekty': []}


def shag_proekt(chat, uid, mid, pid):
    d = _DIALOGI.get(uid)
    if not d or d.get('shag') != 'proekt' or pid not in [p['id'] for p in dostupnye_proekty(_dostup_po_uid(uid))]:
        return False
    d.update(shag='dlya', proekt=pid)
    knopki = [[{'text': t, 'callback_data': f'sk:{k}'} for k, t in DLYA[:2]],
              [{'text': t, 'callback_data': f'sk:{k}'} for k, t in DLYA[2:]], otmena()]
    ekran(chat, f"📝 «{esc(d['chto'])}» · {esc(imya_proekta({'proekt': pid}))}\nДля кого или куда?", knopki, mid)
    return True


def shag_dlya(chat, uid, mid, kod):
    d = _DIALOGI.get(uid)
    if not d or d.get('shag') != 'dlya' or kod not in dict(DLYA):
        return False
    d.update(shag='srok', dlya=dict(DLYA)[kod])
    knopki = [[{'text': t, 'callback_data': f'ss:{k}'} for k, t in SROKI], otmena()]
    ekran(chat, f"📝 «{esc(d['chto'])}» · {esc(imya_proekta({'proekt': d['proekt']}))} · "
                f"{esc(d['dlya'].lower())}\nК какому сроку?", knopki, mid)
    return True


def srok_data(kod):
    if kod == 'seg':
        return date.today().isoformat()
    if kod == 'zav':
        return (date.today() + timedelta(days=1)).isoformat()
    return None


def put_ocheredi():
    return sostavitel.put_ocheredi(NAST)


def shag_srok(chat, uid, mid, kod, p, dostup):
    d = _DIALOGI.get(uid)
    if not d or d.get('shag') != 'srok' or kod not in dict(SROKI):
        return False
    _DIALOGI.pop(uid, None)
    proekt_imya = imya_proekta({'proekt': d['proekt']})
    # документы-основы: похожие актуальные в этом проекте, если нет — где угодно
    osnovy = []
    try:
        con = otkryt_bazu()
        try:
            osnovy = (poisk.najti(con, d['chto'], dostup, MAKS_OSNOV, proekt=d['proekt'])
                      or poisk.najti(con, d['chto'], dostup, MAKS_OSNOV))
        finally:
            con.close()
    except NetKataloga:
        log.warning('Нет каталога — заявка без документов-основ')
    z = {'id': sostavitel.novyj_id(),
         'kto': {'telegram_id': uid, 'imya': p.get('imya', ''), 'chat': chat},
         'chto': d['chto'], 'proekt': d['proekt'], 'proekt_imya': proekt_imya,
         'dlya': d['dlya'], 'srok': dict(SROKI)[kod], 'srok_data': srok_data(kod),
         'osnovy': [{'id': f['id'], 'put': f['put'], 'nazvanie': nazvanie(f)} for f in osnovy],
         'sozdano': datetime.now().isoformat(timespec='seconds'), 'status': 'novaya'}
    sostavitel.dobavit(put_ocheredi(), z)
    log.info('Заявка %s (%s): %s', z['id'], p.get('imya'), z['chto'][:200])
    stroki = [f"📝 <b>Заявка принята</b>: «{esc(z['chto'])}»",
              f"{esc(proekt_imya)} · {esc(z['dlya'].lower())} · срок: {esc(z['srok'].lower())}"]
    if osnovy:
        stroki.append('\nНашёл похожие документы-основы:')
        for n, f in enumerate(osnovy, 1):
            stroki.append(f"{n}. <b>{esc(obrezat(nazvanie(f), 90))}</b> — {esc(gde(f))}"
                          + (f" · {data_polnaya(f['data'])}" if data_polnaya(f.get('data')) else ''))
    else:
        stroki.append('\nПохожих документов-основ не нашёл — агент поищет в каталоге сам.')
    stroki.append('\nОтправляю задание агенту — пришлю черновик сюда.')
    ekran(chat, '\n'.join(stroki), [[knopka_faila(f, n)] for n, f in enumerate(osnovy, 1)] or None, mid)
    return True


def otvet_na_voprosy(chat, uid, zid, tekst):
    """Ответ пользователя на вопросы агента: дописать в заявку и вернуть её в очередь."""
    def dopisat(z):
        z.setdefault('utochneniya', []).append({'voprosy': z.get('voprosy') or [], 'otvet': tekst[:3000],
                                               'vremya': datetime.now().isoformat(timespec='seconds')})
        z['status'] = 'novaya'
    z = sostavitel.najti_zayavku(put_ocheredi(), zid)
    if not z or str((z.get('kto') or {}).get('telegram_id')) != str(uid):
        ekran(chat, 'Заявка не найдена.')
        return
    sostavitel.izmenit(put_ocheredi(), zid, dopisat)
    log.info('Ответ на вопросы по заявке %s', zid)
    ekran(chat, 'Передал ответ агенту — пришлю черновик сюда.')


# ---------- ответы составителя ----------

def put_otvetov():
    return sostavitel.put_otvetov(put_ocheredi())


def proverit_otvety():
    """Новые строки zayavki_otvety.jsonl (с прошлого раза) → сообщения тем, кто заказал.
    Где остановились — в файле .poz рядом, чтобы после перезапуска не слать повторно."""
    put = put_otvetov()
    if not os.path.isfile(put):
        return 0
    put_poz = put + '.poz'
    try:
        with open(put_poz) as fh:
            poz = int(fh.read().strip() or 0)
    except (OSError, ValueError):
        poz = 0
    if os.path.getsize(put) < poz:   # файл начали заново
        poz = 0
    with open(put, 'rb') as fh:
        fh.seek(poz)
        kusok = fh.read()
    konec = kusok.rfind(b'\n')
    if konec < 0:
        return 0
    n = 0
    try:
        for stroka in kusok[:konec + 1].splitlines(keepends=True):
            if stroka.strip():
                try:
                    dostavit_otvet(json.loads(stroka.decode('utf-8')))
                    n += 1
                except requests.RequestException:
                    raise            # нет связи — эту строку доставим в следующий раз
                except Exception:
                    log.exception('Ответ составителя не доставлен: %s', stroka[:200])
            poz += len(stroka)
    finally:
        with open(put_poz, 'w') as fh:
            fh.write(str(poz))
    return n


def dostavit_otvet(o):
    z = sostavitel.najti_zayavku(put_ocheredi(), o.get('id')) or {}
    kto = z.get('kto') or o.get('kto') or {}
    chat, uid = kto.get('chat') or kto.get('telegram_id'), kto.get('telegram_id')
    if not chat:
        log.warning('Ответ по заявке %s: неизвестно, кому отправить', o.get('id'))
        return
    chto = esc(obrezat(z.get('chto') or o.get('chto') or '', 120))
    status = o.get('status')
    if status == 'voprosy':
        voprosy = '\n'.join(f'{n}. {esc(v)}' for n, v in enumerate(o.get('voprosy') or [], 1))
        if uid:
            _DIALOGI[uid] = {'shag': 'otvet', 'zayavka': o['id']}
        pokazat(chat, f'❓ По заявке «{chto}» агенту не хватает данных:\n{voprosy}\n\n'
                       'Ответьте одним сообщением (текстом или голосом) — передам ответ, и агент продолжит.',
                 [[{'text': 'Ответить', 'callback_data': f"so:{o['id']}"}]])
    elif status == 'gotovo':
        otpravit_chernovik(chat, o, chto)
    elif status == 'oshibka':
        pokazat(chat, f"Не получилось составить черновик по заявке «{chto}»: {esc(o.get('oshibka') or 'ошибка')}. "
                       'Попробуйте ещё раз или напишите Мансуру.')


def otpravit_chernovik(chat, o, chto):
    put = os.path.expanduser(o.get('fail') or '')
    chernoviki = os.path.expanduser(sostavitel.nastroyki_sostavitelya(NAST)['chernoviki'])
    istochniki = ', '.join(os.path.basename(str(x).rstrip('/')) for x in o.get('istochniki') or []) or 'не указаны'
    if not (put and os.path.isfile(put) and sostavitel.v_papke(put, chernoviki)):
        pokazat(chat, f'Черновик по заявке «{chto}» готов, но файл не нашёлся в папке черновиков:\n'
                       f'<code>{esc(put)}</code>')
        return
    if os.path.getsize(put) > MAKS_RAZMER:
        pokazat(chat, f'Черновик по заявке «{chto}» большой — лежит на Mac:\n<code>{esc(put)}</code>')
        return
    podp = korotko(TEKST_CHERNOVIK + istochniki, 900)
    gruppa = str(o.get('id') or '')[:40]
    zakryt = [[{'text': '✅ Готово — закрыть', 'callback_data': f'cz:{gruppa}'}]]
    dop = [f'<b>Что изменено:</b> {esc(o["chto_izmeneno"])}' if o.get('chto_izmeneno') else '',
           f'<b>Проверки:</b> {esc(o["proverki"])}' if o.get('proverki') else '']
    dop = '\n'.join(x for x in dop if x)
    # черновик не удаляется новыми запросами, пока не нажмут «Готово — закрыть» (кнопка под последним)
    otvet = otpravit_dokument(chat, put, os.path.basename(put), esc(podp), None if dop else zakryt,
                              vid='chernovik', gruppa=gruppa)
    if not otvet.get('ok'):
        pokazat(chat, f'Черновик готов, но не отправился. Он лежит на Mac:\n<code>{esc(put)}</code>')
        return
    log.info('Черновик %s → %s', put, chat)
    if dop:
        pokazat(chat, dop, zakryt, vid='chernovik', gruppa=gruppa)


def zakryt_chernovik(chat, gruppa, mid):
    """«Готово — закрыть»: убрать черновик и пояснение к нему из окна и из чата."""
    zapisi = okno(chat)
    ubrat_ih = [e for e in zapisi if e['vid'] == 'chernovik' and (e.get('gruppa') == gruppa or e['id'] == mid)]
    if mid and mid not in {e['id'] for e in ubrat_ih}:
        ubrat_ih.append({'id': mid})
    sohranit_okno(chat, [e for e in zapisi if e not in ubrat_ih])
    for e in ubrat_ih:
        ubrat(chat, e)


# ---------- голос ----------

def model_golosa():
    """Модель faster_whisper — загружается один раз, при первом голосовом.
    ImportError наружу: значит, голос недоступен."""
    global _MODEL
    if _MODEL is None:
        from faster_whisper import WhisperModel
        log.info('Загружаю модель голоса %s…', NAST.get('model_golosa', 'medium'))
        _MODEL = WhisperModel(NAST.get('model_golosa', 'medium'), device='cpu', compute_type='int8')
    return _MODEL


def raspoznat(put):
    # faster_whisper сам читает ogg/opus через PyAV (av) — ffmpeg не нужен
    segmenty, _ = model_golosa().transcribe(put, language='ru', beam_size=5)
    return ' '.join(s.text.strip() for s in segmenty).strip()


def golos(chat, msg, p, dostup):
    v = msg.get('voice') or msg.get('audio')
    if (v.get('duration') or 0) > MAKS_GOLOS_SEK:
        ekran(chat, 'Слишком длинное сообщение. Скажите запрос коротко — до трёх минут.')
        return
    try:
        model_golosa()
    except ImportError:
        ekran(chat, 'Голосовой поиск пока недоступен. Напишите, пожалуйста, словами.')
        return
    api('sendChatAction', chat_id=chat, action='typing')
    info = api('getFile', file_id=v['file_id'])
    if not info.get('ok') or not info['result'].get('file_path'):
        ekran(chat, 'Не получилось скачать голосовое. Попробуйте ещё раз или напишите словами.')
        return
    put_tg = info['result']['file_path']
    r = requests.get(f'{API}/file/bot{KLYUCH}/{put_tg}', timeout=120)
    r.raise_for_status()
    rassh = os.path.splitext(put_tg)[1] or '.ogg'
    with tempfile.NamedTemporaryFile(suffix=rassh, delete=False) as t:
        t.write(r.content)
    try:
        tekst = raspoznat(t.name)
    finally:
        os.unlink(t.name)
    if not tekst:
        ekran(chat, 'Не разобрал слов. Попробуйте ещё раз или напишите словами.')
        return
    log.info('Голос распознан: %s', tekst)
    pokazat(chat, f'Распознал: «{esc(tekst)}»')
    obychnyj_tekst(chat, (msg.get('from') or {}).get('id'), p, tekst, dostup)


# ---------- обработка обновлений ----------

def obychnyj_tekst(chat, uid, p, tekst, dostup):
    """Текст (или распознанный голос), не команда и не кнопка клавиатуры:
    ответ в диалоге «Составить документ» / на вопросы агента, иначе — поиск."""
    d = _DIALOGI.get(uid)
    if d and d.get('shag') == 'chto':
        nachat_sostavlenie(chat, uid, tekst)
        return
    if d and d.get('shag') == 'otvet':
        _DIALOGI.pop(uid, None)
        otvet_na_voprosy(chat, uid, d['zayavka'], tekst)
        return
    _DIALOGI.pop(uid, None)   # на шаге с кнопками написали текст — значит, передумали; ищем
    log.info('Поиск (%s): %s', p.get('imya'), tekst[:200])
    iskat(chat, uid, tekst, dostup)


def soobshchenie(msg):
    chat = msg['chat']['id']
    kto = msg.get('from') or {}
    p = polzovatel(kto.get('id'))
    if not p:
        chuzhoj(chat, kto)
        return
    with zapros(chat, msg.get('message_id')):   # прежние ответы и само сообщение уберутся
        _soobshchenie(chat, msg, kto, p)


def _soobshchenie(chat, msg, kto, p):
    uid = kto.get('id')
    dostup = dostup_polzovatelya(p)
    tekst = (msg.get('text') or '').strip()

    if msg.get('voice') or msg.get('audio'):
        golos(chat, msg, p, dostup)
        return
    if not tekst:
        ekran(chat, 'Я понимаю текст и голосовые. Напишите, что найти, или нажмите «Проекты».')
        return
    if tekst.startswith('/') or tekst in KNOPKI_KLAVIATURY:
        _DIALOGI.pop(uid, None)   # команда или кнопка клавиатуры прерывает диалог
    if tekst.startswith('/'):
        komanda = tekst.split()[0].split('@')[0].lower()
        if komanda == '/start':
            imya = p.get('imya', '').split(' (')[0]
            pokazat(chat, f'Здравствуйте, {esc(imya)}! Это «АРХИВУД Документы».\n'
                          'Напишите, что найти, или выберите проект. Подсказка — /pomosh.',
                    klaviatura=KLAVIATURA)
            pokazat_proekty(chat, dostup)
        elif komanda in ('/pomosh', '/help'):
            ekran(chat, TEKST_POMOSHCH, klaviatura=KLAVIATURA)
        elif komanda == '/svezhee':
            svezhee(chat, dostup)
        elif komanda == '/sostavit':
            nachat_sostavlenie(chat, uid)
        else:
            ekran(chat, 'Не знаю такой команды. Есть /start, /svezhee, /sostavit и /pomosh.')
        return
    if tekst == 'Проекты':
        pokazat_proekty(chat, dostup)
    elif tekst == 'Свежее':
        svezhee(chat, dostup)
    elif tekst == 'Помощь':
        ekran(chat, TEKST_POMOSHCH)
    elif tekst == KNOPKA_SOSTAVIT:
        nachat_sostavlenie(chat, uid)
    else:
        obychnyj_tekst(chat, uid, p, tekst, dostup)


def knopka_sostavleniya(cq, chat, mid, uid, p, dostup, chasti):
    """Кнопки диалога «Составить документ». True — кнопка обработана."""
    k = chasti[0]
    if k == 'sd':
        otvetit_knopke(cq)
        nachat_sostavlenie(chat, uid, mid=mid)
        return True
    if k == 'sdq':
        otvetit_knopke(cq)
        nachat_sostavlenie(chat, uid, _POSLEDNIJ_ZAPROS.pop(uid, None), mid)
        return True
    if k == 'sx':
        _DIALOGI.pop(uid, None)
        otvetit_knopke(cq, 'Отменено')
        ekran(chat, 'Хорошо, не составляю. Напишите, что найти, или нажмите «Проекты».', mid=mid)
        return True
    if k == 'so' and len(chasti) == 2:
        otvetit_knopke(cq, 'Напишите ответ одним сообщением (или голосом).')
        _DIALOGI[uid] = {'shag': 'otvet', 'zayavka': chasti[1]}
        return True
    if len(chasti) == 2 and k in ('sp', 'sk', 'ss'):
        if k == 'sp':
            ok = shag_proekt(chat, uid, mid, chasti[1])
        elif k == 'sk':
            ok = shag_dlya(chat, uid, mid, chasti[1])
        else:
            ok = shag_srok(chat, uid, mid, chasti[1], p, dostup)
        otvetit_knopke(cq, None if ok else 'Начните заново: «📝 Составить документ»')
        return True
    return False


def chislo(s):
    return s.isdigit()


def knopka(cq):
    kto = cq.get('from') or {}
    msg = cq.get('message') or {}
    chat = (msg.get('chat') or {}).get('id', kto.get('id'))
    mid = msg.get('message_id')
    p = polzovatel(kto.get('id'))
    if not p:
        otvetit_knopke(cq, 'Нет доступа')
        chuzhoj(chat, kto)
        return
    chasti = (cq.get('data') or '').split(':')
    if chasti[0] == 'cz' and len(chasti) == 2:   # «Готово — закрыть» под черновиком
        otvetit_knopke(cq, 'Закрыто')
        zakryt_chernovik(chat, chasti[1], mid)
        return
    # экран, который правим: нажатое текстовое сообщение; под файлом (документом) — экран окна
    mid_ekrana = mid if 'document' not in msg else posledni_ekran(chat)
    with zapros(chat):
        _knopka(cq, chat, mid_ekrana, kto, p, chasti)


def _knopka(cq, chat, mid, kto, p, chasti):
    uid = kto.get('id')
    dostup = dostup_polzovatelya(p)
    if knopka_sostavleniya(cq, chat, mid, uid, p, dostup, chasti):
        return
    k, n = chasti[0], len(chasti)
    con = otkryt_bazu()
    try:
        if chasti == ['m']:
            tekst, knopki = ekran_proektov(con, dostup)
        elif k == 'p' and n == 2:
            tekst, knopki = ekran_tipov(con, chasti[1], dostup)
        elif k == 't' and n == 3 and chislo(chasti[2]):
            tekst, knopki = ekran_vhoda(con, chasti[1], int(chasti[2]), dostup)
        elif k == 'l' and n == 5 and chislo(chasti[2]) and chislo(chasti[4]):
            tekst, knopki = ekran_spiska(con, chasti[1], int(chasti[2]), chasti[3], int(chasti[4]), dostup)
        elif k == 'z' and n == 3:
            tekst, knopki = ekran_dogovora(con, chasti[1], chasti[2], dostup)
        elif k == 'zp' and n == 3:
            tekst, knopki = ekran_zapisok(con, chasti[1], chasti[2], dostup)
        elif k == 'v' and n == 2 and chislo(chasti[1]):
            tekst, knopki = ekran_versiy(con, int(chasti[1]), dostup)
        elif k == 'f' and n == 2 and chislo(chasti[1]):
            otvetit_knopke(cq, 'Отправляю…')
            zapomnit(chat, mid, 'ekran')   # экран остаётся, прежний файл под ним заменится новым
            otpravit_fail(chat, con, int(chasti[1]), dostup)
            return
        elif k in ('a', 'h') and n == 2 and chislo(chasti[1]):
            otvetit_knopke(cq)
            reshit_aktualnost(chat, con, int(chasti[1]), 'aktualno' if k == 'a' else 'istoriya', dostup, p, mid)
            return
        else:
            otvetit_knopke(cq, TEKST_USTARELA)
            return
    finally:
        con.close()
    otvetit_knopke(cq)
    ekran(chat, tekst, knopki, mid)


def _chat_obnovleniya(upd):
    if 'message' in upd:
        return upd['message']['chat']['id']
    cq = upd.get('callback_query') or {}
    return ((cq.get('message') or {}).get('chat') or {}).get('id') or (cq.get('from') or {}).get('id')


def obrabotat(upd):
    """Одно обновление от Telegram. Любая ошибка — в журнал, человеку — короткое извинение."""
    try:
        if 'callback_query' in upd:
            knopka(upd['callback_query'])
        elif 'message' in upd:
            soobshchenie(upd['message'])
    except Exception as e:
        if isinstance(e, NetKataloga):
            log.error('Нет файла каталога: %s', e)
            tekst = 'Каталог документов ещё не готов. Попробуйте позже.'
        else:
            log.exception('Ошибка при обработке обновления %s', upd.get('update_id'))
            tekst = TEKST_OSHIBKA
        try:
            if 'callback_query' in upd:
                otvetit_knopke(upd['callback_query'])
            chat = _chat_obnovleniya(upd)
            if chat:
                pokazat(chat, tekst)
        except Exception:
            log.exception('Не удалось сообщить об ошибке')


# ---------- запуск ----------

def prochitat_klyuch():
    put = os.path.expanduser(NAST['klyuch_bota'])
    if not os.path.isfile(put):
        print(f'Нет файла с ключом бота: {put}\n'
              f'Создайте его и положите туда ключ от @BotFather одной строкой.', file=sys.stderr)
        sys.exit(1)
    with open(put, encoding='utf-8') as fh:
        klyuch = fh.read().strip()
    if not klyuch:
        print(f'Файл с ключом бота пустой: {put}', file=sys.stderr)
        sys.exit(1)
    return klyuch


def glavnaya():
    global KLYUCH
    obnovit_nastroyki()
    KLYUCH = prochitat_klyuch()
    nastroit_zhurnal()

    try:
        me = api('getMe')
        if me.get('error_code') == 401:
            log.critical('Telegram не принял ключ бота (401). Проверьте файл %s', NAST['klyuch_bota'])
            sys.exit(1)
        log.info('Бот запущен: @%s', (me.get('result') or {}).get('username'))
        api('setMyCommands', commands=[
            {'command': 'start', 'description': 'Меню проектов'},
            {'command': 'svezhee', 'description': 'Свежие документы'},
            {'command': 'sostavit', 'description': 'Составить документ'},
            {'command': 'pomosh', 'description': 'Как пользоваться'}])
    except requests.RequestException as e:
        log.warning('Нет связи с Telegram при запуске: %s', e)

    offset, pauza, proverka = None, 5, 0.0
    while True:
        try:
            obnovit_nastroyki()
            if time.time() - proverka >= PROVERKA_OTVETOV_SEK:
                proverka = time.time()
                try:
                    proverit_otvety()
                except requests.RequestException:
                    raise
                except Exception:
                    log.exception('Не удалось проверить ответы составителя')
            otvet = api('getUpdates', zhdat=OPROS_SEK + 15, timeout=OPROS_SEK, offset=offset,
                        allowed_updates=['message', 'callback_query'])
            if not otvet.get('ok'):
                if otvet.get('error_code') == 401:
                    log.critical('Telegram не принял ключ бота (401), останавливаюсь')
                    sys.exit(1)
                time.sleep(pauza)
                pauza = min(pauza * 2, 120)
                continue
            pauza = 5
            for upd in otvet['result']:
                offset = upd['update_id'] + 1
                obrabotat(upd)
        except KeyboardInterrupt:
            log.info('Остановлен вручную')
            break
        except (requests.RequestException, ValueError) as e:
            log.warning('Нет связи с Telegram: %s. Повтор через %s с', e, pauza)
            time.sleep(pauza)
            pauza = min(pauza * 2, 120)


if __name__ == '__main__':
    glavnaya()
