"""Telegram-бот «АРХИВУД Документы»: поиск и выдача файлов из каталога.

Запуск на Mac:  /opt/homebrew/bin/python3 bot.py
Работает через long polling (getUpdates), только библиотекой requests.
Каталог (SQLite) заполняет katalog.py; здесь только чтение через poisk.py.
Соединение с базой открывается на каждый запрос — так бот видит свежий каталог.

Ключ бота лежит в отдельном файле (nastroyki.json → klyuch_bota) и никогда
не попадает в журнал: формат журнала вырезает его из любых строк.
"""
import html
import json
import logging
import os
import sys
import tempfile
import time
from logging.handlers import RotatingFileHandler

import requests

import poisk

API = 'https://api.telegram.org'
NA_STRANICE = 8               # файлов в списке раздела
MAKS_NAJDENO = 7              # результатов поиска
MAKS_SVEZHIH = 10             # файлов в /svezhee
MAKS_RAZMER = 49 * 1024 * 1024  # больше этого Telegram-боту не отправить
MAKS_GOLOS_SEK = 180          # голосовые длиннее — не распознаём
DLINA_KNOPKI = 40             # обрезка имени файла на кнопке

log = logging.getLogger('dokumenty')

KLYUCH = None          # ключ бота, читается из файла при запуске
NAST = None            # настройки из nastroyki.json (перечитываются при изменении)
_NAST_VREMYA = None
_MODEL = None          # модель распознавания голоса, грузится один раз при первом голосовом
_UZHE_PROSILI = set()  # кто уже просил доступ с момента запуска (чтобы не засыпать админа)

TEKST_POMOSHCH = (
    '<b>Как искать</b>\n'
    'Просто напишите, что нужно: «договор олимпийский», «чертёж прихожей», '
    '«смета двери». Я пришлю до 7 подходящих файлов — нажмите на кнопку, '
    'и файл придёт сюда.\n\n'
    '<b>Кнопки</b>\n'
    '«Проекты» — все документы по проектам и разделам, свежие сверху.\n'
    '«Свежее» — 10 последних файлов.\n\n'
    '<b>Голос</b>\n'
    'Можно надиктовать запрос голосовым сообщением — я распознаю и поищу.\n\n'
    'Команды: /start — меню, /svezhee — свежие файлы, /pomosh — эта подсказка.'
)
TEKST_PUSTO = ('Ничего не нашёл. Попробуйте другие слова: например, '
               '«договор олимпийский» или «чертёж прихожей».')
TEKST_OSHIBKA = 'Что-то пошло не так, попробуйте ещё раз.'
TEKST_USTARELA = 'Кнопка устарела. Нажмите «Проекты».'

KLAVIATURA = {'keyboard': [[{'text': 'Проекты'}, {'text': 'Свежее'}], [{'text': 'Помощь'}]],
              'resize_keyboard': True, 'is_persistent': True}


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
    for h in (RotatingFileHandler(put, maxBytes=2 * 1024 * 1024, backupCount=3, encoding='utf-8'),
              logging.StreamHandler(sys.stderr)):
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

def api(metod, files=None, zhdat=30, **par):
    """Вызов метода Telegram. Возвращает ответ целиком ({'ok': ..., 'result': ...})."""
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
            log.warning('Telegram %s: %s %s', metod, otvet.get('error_code'), opis)
    return otvet


def _razmetka(knopki=None, klaviatura=None):
    if knopki:
        return {'inline_keyboard': knopki}
    return klaviatura


def otpravit(chat, tekst, knopki=None, klaviatura=None):
    if len(tekst) > 4000:
        tekst = tekst[:4000] + '…'
    return api('sendMessage', chat_id=chat, text=tekst, parse_mode='HTML',
               disable_web_page_preview=True, reply_markup=_razmetka(knopki, klaviatura))


def izmenit(chat, mid, tekst, knopki=None):
    """Заменить текст и кнопки сообщения (листание меню). Не вышло — прислать новым сообщением."""
    if mid is None:
        return otpravit(chat, tekst, knopki)
    otvet = api('editMessageText', chat_id=chat, message_id=mid, text=tekst, parse_mode='HTML',
                disable_web_page_preview=True, reply_markup=_razmetka(knopki) or {'inline_keyboard': []})
    if not otvet.get('ok') and 'message is not modified' not in otvet.get('description', ''):
        return otpravit(chat, tekst, knopki)
    return otvet


def otvetit_knopke(cq, tekst=None):
    try:
        api('answerCallbackQuery', callback_query_id=cq['id'], text=tekst)
    except Exception:
        log.exception('answerCallbackQuery не прошёл')


# ---------- оформление ----------

def esc(s):
    return html.escape(str(s or ''), quote=False)


def korotko(imya, n=DLINA_KNOPKI):
    """Обрезать длинное имя, сохранив расширение: «Очень длинный дог….pdf»."""
    imya = imya or ''
    if len(imya) <= n:
        return imya
    osn, rassh = os.path.splitext(imya)
    if len(rassh) > 6:
        rassh = ''
    return osn[:max(1, n - len(rassh) - 1)].rstrip() + '…' + rassh


def data_korotko(d):
    """'2026-10-28T13:01:57' → '28.10'."""
    d = d or ''
    return f'{d[8:10]}.{d[5:7]}' if len(d) >= 10 else ''


def data_polnaya(d):
    d = d or ''
    return f'{d[8:10]}.{d[5:7]}.{d[:4]}' if len(d) >= 10 else ''


def razmer_mb(b):
    return f'{b / 1024 / 1024:.1f}'.replace('.', ',') + ' МБ'


def imya_proekta(f):
    if f.get('proekt_imya'):
        return f['proekt_imya']
    for p in NAST.get('proekty', []):
        if p.get('id') == f.get('proekt'):
            return p['imya']
    return f.get('proekt') or 'Без проекта'


def gde(f):
    """«Олимпийский · Договоры и сметы»."""
    return ' · '.join(x for x in (imya_proekta(f), f.get('razdel')) if x)


def knopka_faila(f, nomer=None):
    tekst = korotko(f['imya'])
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

def razdely_proekta(con, proekt, dostup):
    return [r for r in poisk.razdely(con, proekt, dostup) if r['razdel']]


def ekran_proektov(con, dostup):
    pr = [p for p in poisk.proekty(con, dostup) if p['proekt']]
    if not pr:
        return 'Пока нет доступных документов.', None
    return 'Выберите проект:', [
        [{'text': f"{imya_proekta(p)} ({p['n']})", 'callback_data': f"p:{p['proekt']}"}] for p in pr]


def ekran_razdelov(con, proekt, dostup):
    rz = razdely_proekta(con, proekt, dostup)
    if not rz:
        return 'В этом проекте нет доступных документов.', [[{'text': 'Назад', 'callback_data': 'm'}]]
    imya = imya_proekta({'proekt': proekt})
    knopki = [[{'text': f"{r['razdel']} ({r['n']})", 'callback_data': f'r:{proekt}:{i}:0'}]
              for i, r in enumerate(rz)]
    knopki.append([{'text': 'Назад', 'callback_data': 'm'}])
    return f'<b>{esc(imya)}</b>\nВыберите раздел:', knopki


def ekran_spiska(con, proekt, i, smeshchenie, dostup):
    rz = razdely_proekta(con, proekt, dostup)
    if not 0 <= i < len(rz):  # каталог поменялся — показываем разделы заново
        return ekran_razdelov(con, proekt, dostup)
    r = rz[i]
    smeshchenie = max(0, smeshchenie)
    faily = poisk.spisok(con, proekt, r['razdel'], dostup, smeshchenie, NA_STRANICE + 1)
    est_eshche = len(faily) > NA_STRANICE
    faily = faily[:NA_STRANICE]
    zag = f"<b>{esc(imya_proekta({'proekt': proekt}))} · {esc(r['razdel'])}</b>\n"
    if faily:
        zag += f"Файлы {smeshchenie + 1}–{smeshchenie + len(faily)} из {r['n']}, свежие сверху. Нажмите, чтобы получить."
    else:
        zag += 'Здесь больше ничего нет.'
    knopki = [[knopka_faila(f)] for f in faily]
    niz = []
    if smeshchenie > 0:
        niz.append({'text': 'Назад', 'callback_data': f'r:{proekt}:{i}:{max(0, smeshchenie - NA_STRANICE)}'})
        niz.append({'text': 'К разделам', 'callback_data': f'p:{proekt}'})
    else:
        niz.append({'text': 'Назад', 'callback_data': f'p:{proekt}'})
    if est_eshche:
        niz.append({'text': 'Ещё', 'callback_data': f'r:{proekt}:{i}:{smeshchenie + NA_STRANICE}'})
    knopki.append(niz)
    return zag, knopki


def spisok_faylov(zag, faily, s_otryvkom=False):
    """Текст со списком файлов и кнопки «получить» под ним (для поиска и /svezhee)."""
    stroki = [zag]
    for n, f in enumerate(faily, 1):
        s = f"\n{n}. <b>{esc(korotko(f['imya'], 90))}</b>\n{esc(gde(f))}"
        if data_polnaya(f.get('data')):
            s += f" · {data_polnaya(f['data'])}"
        if f.get('otkogo'):
            s += f"\nОт: {esc(f['otkogo'])}"
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
    otpravit(chat, tekst, knopki)


def svezhee(chat, dostup):
    con = otkryt_bazu()
    try:
        faily = poisk.svezhie(con, dostup, MAKS_SVEZHIH)
    finally:
        con.close()
    if not faily:
        otpravit(chat, 'Пока нет доступных документов.')
        return
    otpravit(chat, *spisok_faylov('<b>Свежие файлы</b>', faily))


def iskat(chat, tekst, dostup):
    con = otkryt_bazu()
    try:
        rez = poisk.najti(con, tekst, dostup, MAKS_NAJDENO)
    finally:
        con.close()
    if not rez:
        otpravit(chat, TEKST_PUSTO)
        return
    otpravit(chat, *spisok_faylov(f'Нашёл: {len(rez)}', rez, s_otryvkom=True))


def podpis(f, put):
    """Подпись к файлу: имя, проект · раздел, дата, от кого, путь на Mac."""
    imya = korotko(f['imya'], 200)
    if len(put) > 500:
        put = '…' + put[-500:]
    stroki = [f'<b>{esc(imya)}</b>', esc(gde(f))]
    if data_polnaya(f.get('data')):
        stroki.append(data_polnaya(f['data']))
    if f.get('otkogo'):
        stroki.append(f"От: {esc(korotko(f['otkogo'], 100))}")
    stroki.append(f'<code>{esc(put)}</code>')
    return '\n'.join(stroki)


def otpravit_fail(chat, con, fid, dostup):
    f = poisk.fail(con, fid, dostup)  # права проверяются здесь же: чужой id → None
    if not f:
        otpravit(chat, 'Файл не найден или к нему нет доступа.')
        return
    put = f['put']
    if not os.path.isfile(put) and not dostup.get('bez_vnutrennego'):
        # основной файл пропал — может, жива копия с тем же содержимым
        put = next((k for k in poisk.kopii(con, fid) if os.path.isfile(k)), put)
    if not os.path.isfile(put):
        otpravit(chat, f"<b>{esc(f['imya'])}</b>\nФайл не найден на диске — возможно, его переместили "
                       f"или удалили. Где он был:\n<code>{esc(f['put'])}</code>")
        return
    razmer = os.path.getsize(put)
    if razmer > MAKS_RAZMER:
        otpravit(chat, f"<b>{esc(f['imya'])}</b>\nФайл большой ({razmer_mb(razmer)}) — в Telegram "
                       f"его не отправить. Он лежит на Mac:\n<code>{esc(put)}</code>")
        return
    api('sendChatAction', chat_id=chat, action='upload_document')
    with open(put, 'rb') as fh:
        otvet = api('sendDocument', files={'document': (f['imya'], fh)}, zhdat=300,
                    chat_id=chat, caption=podpis(f, put), parse_mode='HTML')
    if otvet.get('ok'):
        log.info('Отправлен файл %s → %s', fid, chat)
    else:
        otpravit(chat, f"Не получилось отправить файл. Он лежит на Mac:\n<code>{esc(put)}</code>")


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


def golos(chat, msg, dostup):
    v = msg.get('voice') or msg.get('audio')
    if (v.get('duration') or 0) > MAKS_GOLOS_SEK:
        otpravit(chat, 'Слишком длинное сообщение. Скажите запрос коротко — до трёх минут.')
        return
    try:
        model_golosa()
    except ImportError:
        otpravit(chat, 'Голосовой поиск пока недоступен. Напишите, пожалуйста, словами.')
        return
    api('sendChatAction', chat_id=chat, action='typing')
    info = api('getFile', file_id=v['file_id'])
    if not info.get('ok') or not info['result'].get('file_path'):
        otpravit(chat, 'Не получилось скачать голосовое. Попробуйте ещё раз или напишите словами.')
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
        otpravit(chat, 'Не разобрал слов. Попробуйте ещё раз или напишите словами.')
        return
    log.info('Голос распознан: %s', tekst)
    otpravit(chat, f'Распознал: «{esc(tekst)}»')
    iskat(chat, tekst, dostup)


# ---------- обработка обновлений ----------

def soobshchenie(msg):
    chat = msg['chat']['id']
    kto = msg.get('from') or {}
    p = polzovatel(kto.get('id'))
    if not p:
        chuzhoj(chat, kto)
        return
    dostup = dostup_polzovatelya(p)
    tekst = (msg.get('text') or '').strip()

    if msg.get('voice') or msg.get('audio'):
        golos(chat, msg, dostup)
        return
    if not tekst:
        otpravit(chat, 'Я понимаю текст и голосовые. Напишите, что найти, или нажмите «Проекты».')
        return
    if tekst.startswith('/'):
        komanda = tekst.split()[0].split('@')[0].lower()
        if komanda == '/start':
            imya = p.get('imya', '').split(' (')[0]
            otpravit(chat, f'Здравствуйте, {esc(imya)}! Это «АРХИВУД Документы».\n'
                           'Напишите, что найти, или выберите проект. Подсказка — /pomosh.',
                     klaviatura=KLAVIATURA)
            pokazat_proekty(chat, dostup)
        elif komanda in ('/pomosh', '/help'):
            otpravit(chat, TEKST_POMOSHCH, klaviatura=KLAVIATURA)
        elif komanda == '/svezhee':
            svezhee(chat, dostup)
        else:
            otpravit(chat, 'Не знаю такой команды. Есть /start, /svezhee и /pomosh.')
        return
    if tekst == 'Проекты':
        pokazat_proekty(chat, dostup)
    elif tekst == 'Свежее':
        svezhee(chat, dostup)
    elif tekst == 'Помощь':
        otpravit(chat, TEKST_POMOSHCH)
    else:
        log.info('Поиск (%s): %s', p.get('imya'), tekst[:200])
        iskat(chat, tekst, dostup)


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
    dostup = dostup_polzovatelya(p)
    chasti = (cq.get('data') or '').split(':')
    con = otkryt_bazu()
    try:
        if chasti == ['m']:
            tekst, knopki = ekran_proektov(con, dostup)
        elif chasti[0] == 'p' and len(chasti) == 2:
            tekst, knopki = ekran_razdelov(con, chasti[1], dostup)
        elif chasti[0] == 'r' and len(chasti) == 4 and chasti[2].isdigit() and chasti[3].isdigit():
            tekst, knopki = ekran_spiska(con, chasti[1], int(chasti[2]), int(chasti[3]), dostup)
        elif chasti[0] == 'f' and len(chasti) == 2 and chasti[1].isdigit():
            otvetit_knopke(cq, 'Отправляю…')
            otpravit_fail(chat, con, int(chasti[1]), dostup)
            return
        else:
            otvetit_knopke(cq, TEKST_USTARELA)
            return
    finally:
        con.close()
    otvetit_knopke(cq)
    izmenit(chat, mid, tekst, knopki)


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
                otpravit(chat, tekst)
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
            {'command': 'svezhee', 'description': 'Свежие файлы'},
            {'command': 'pomosh', 'description': 'Как пользоваться'}])
    except requests.RequestException as e:
        log.warning('Нет связи с Telegram при запуске: %s', e)

    offset, pauza = None, 5
    while True:
        try:
            obnovit_nastroyki()
            otvet = api('getUpdates', zhdat=65, timeout=50, offset=offset,
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
