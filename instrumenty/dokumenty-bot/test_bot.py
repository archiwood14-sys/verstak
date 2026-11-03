"""Проверки бота «АРХИВУД Документы», каталога и составителя без сети.

Telegram подменяется (unittest.mock): requests.post/get не выходят в интернет,
а записывают, что бот хотел отправить. Каталог — временная SQLite-база.
Агент составителя (claude -p) подменяется: subprocess.run не запускается.

    python3 -m unittest test_bot -v
"""
import importlib
import json
import logging
import os
import sqlite3
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bot  # noqa: E402
import karkas  # noqa: E402
import katalog  # noqa: E402
import poisk  # noqa: E402
import sostavitel  # noqa: E402

MANSUR, YULIYA, IGOR, OGRANICHENNYJ, CHUZHOJ = 101, 102, 103, 909, 555
KLYUCH = '123456:SEKRETNYJ-KLYUCH'
OLIMP_ZONY = {'imya': 'Зона', 'znacheniya': [{'id': z, 'rx': rx} for z, rx in karkas.ZONY]}


class FalshivyjTelegram:
    """Вместо requests.post: запоминает вызовы и отвечает «ok»."""
    def __init__(self):
        self.vyzovy = []
        self.nomer = 1000           # message_id новых сообщений: 1001, 1002, …
        self.ne_udalyat = set()     # эти сообщения deleteMessage не удаляет («старше 48 часов»)
        self.plohie_file_id = set()  # эти file_id Telegram «не принимает»

    def post(self, url, json=None, data=None, files=None, timeout=None):
        metod = url.rsplit('/', 1)[1]
        par = dict(json or data or {})
        if files:
            par['_fail'] = files['document'][0]
        self.vyzovy.append((metod, par))
        result = {}
        if metod in ('sendMessage', 'sendDocument'):
            if metod == 'sendDocument' and not files and par.get('document') in self.plohie_file_id:
                return mock.Mock(json=lambda: {'ok': False, 'error_code': 400,
                                               'description': 'Bad Request: wrong file identifier'})
            self.nomer += 1
            result = {'message_id': self.nomer}
            if metod == 'sendDocument':
                result['document'] = {'file_id': f'FID-{self.nomer}' if files else par['document']}
        elif metod == 'editMessageText':
            result = {'message_id': par['message_id']}
        elif metod == 'deleteMessage' and par['message_id'] in self.ne_udalyat:
            return mock.Mock(json=lambda: {'ok': False, 'error_code': 400,
                                           'description': "Bad Request: message can't be deleted"})
        elif metod == 'getFile':
            result = {'file_path': 'voice/file_1.oga'}
        return mock.Mock(json=lambda: {'ok': True, 'result': result})

    def udaleno(self, chat=None):
        return [p['message_id'] for m, p in self.vyzovy
                if m == 'deleteMessage' and (chat is None or p['chat_id'] == chat)]

    def get(self, url, timeout=None):
        self.vyzovy.append(('skachat', {}))
        return mock.Mock(content=b'OggS-fake', raise_for_status=lambda: None)

    def metody(self):
        return [m for m, _ in self.vyzovy]

    def soobshcheniya(self, chat=None):
        return [p['text'] for m, p in self.vyzovy
                if m in ('sendMessage', 'editMessageText') and (chat is None or p['chat_id'] == chat)]

    def dokumenty(self):
        return [p for m, p in self.vyzovy if m == 'sendDocument']

    @staticmethod
    def _razmetka(p):
        r = p.get('reply_markup') or {}
        return json.loads(r) if isinstance(r, str) else r   # sendDocument: разметка строкой (multipart)

    def poslednie_knopki(self):
        for m, p in reversed(self.vyzovy):
            if m in ('sendMessage', 'editMessageText') and self._razmetka(p).get('inline_keyboard'):
                return [k for ryad in self._razmetka(p)['inline_keyboard'] for k in ryad]
        return []

    def knopki_dokumenta(self):
        return [k for ryad in self._razmetka(self.dokumenty()[-1]).get('inline_keyboard', []) for k in ryad]


def chitat_json(put):
    with open(put, encoding='utf-8') as fh:
        return json.load(fh)


def para(knopki):
    return [(k['text'], k['callback_data']) for k in knopki]


class OsnovaTesta(unittest.TestCase):
    """Временная база с размеченными по каркасу документами и подменённый Telegram."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.put_bazy = os.path.join(d, 'katalog.db')
        con = sqlite3.connect(self.put_bazy)
        con.executescript(katalog.SHEMA)
        katalog.migraciya(con)
        self.id, self.put = {}, {}

        def dobavit(klyuch, imya, proekt, tip, data, soderzhanie='', na_diske=True, razmer=None, **pole):
            put = os.path.join(d, klyuch + '_' + imya)
            if na_diske:
                with open(put, 'wb') as fh:
                    if razmer:
                        fh.truncate(razmer)  # «разреженный» файл: большой по размеру, но место не занимает
                    else:
                        fh.write(b'test')
            pi = {'olimp': 'Олимпийский', 'raz_mebel': 'Раздоры. Мебель'}[proekt]
            z = {'put': put, 'imya': imya, 'rasshirenie': imya.rsplit('.', 1)[-1], 'razmer': razmer or 4,
                 'data': data, 'proekt': proekt, 'proekt_imya': pi, 'poryadok_proekta': 0 if proekt == 'olimp' else 2,
                 'razdel': tip, 'poryadok_razdela': karkas.TIPY.index(tip), 'istochnik': 'papka', 'otkogo': '',
                 'vnutrennee': 0, 'tip': tip, 'zona': '', 'rol': '', 'semya': f'{proekt}|{tip}|{klyuch}',
                 'nazvanie': karkas.chistoe_imya(imya), 'otkuda': '', 'arhiv': 0, 'aktualno': 1, 'versiy': 1}
            z.update(pole)
            cur = con.execute(f"INSERT INTO faily ({','.join(z)}) VALUES ({','.join('?' * len(z))})", list(z.values()))
            con.execute('INSERT INTO tekst (rowid, imya, mesto, soderzhanie) VALUES (?,?,?,?)',
                        [cur.lastrowid, z['nazvanie'] + ' ' + imya, f'{pi} {tip}', soderzhanie])
            self.id[klyuch], self.put[klyuch] = cur.lastrowid, put

        # Олимпийский, зона АГ: договор в трёх версиях, два приложения
        sem = 'olimp|Договоры|АГ|договор|'
        dobavit('dog_ag_v1', 'Договор АГ.docx', 'olimp', 'Договоры', '2026-09-01T10:00:00', 'договор подряда АГ',
                zona='АГ', rol='Договор', semya=sem, aktualno=0, versiy=3, nazvanie='Договор АГ')
        dobavit('dog_ag_v2', 'Договор АГ ред2.docx', 'olimp', 'Договоры', '2026-10-01T10:00:00', 'договор подряда АГ',
                zona='АГ', rol='Договор', semya=sem, aktualno=0, versiy=3, nazvanie='Договор АГ ред2')
        dobavit('dog_ag', 'Договор АГ ред3.docx', 'olimp', 'Договоры', '2026-10-20T10:00:00',
                'договор подряда монтаж накладок АГ Зверева', zona='АГ', rol='Договор', semya=sem, versiy=3,
                formaty='docx+pdf', otkuda='из почты: Зверева', istochnik='pochta', otkogo='Зверева',
                nazvanie='Договор АГ ред3')
        dobavit('pril2_ag', 'Приложение 2 - ТЗ на накладки АГ.docx', 'olimp', 'Договоры', '2026-10-19T10:00:00',
                'техническое задание накладки', zona='АГ', rol='Приложение 2 — ТЗ на накладки')
        dobavit('pril1_ag', 'Приложение 1 Смета АГ.xlsx', 'olimp', 'Договоры', '2026-10-18T10:00:00',
                'смета накладки', zona='АГ', rol='Приложение 1 — Смета')
        dobavit('dog_gs', 'Договор ГС-ДЯ.docx', 'olimp', 'Договоры', '2026-10-15T10:00:00', 'договор ГС-ДЯ',
                zona='ГС-ДЯ', rol='Договор')
        dobavit('dog_bez', 'Договор поставки клея.pdf', 'olimp', 'Договоры', '2026-08-01T10:00:00',
                'договор поставки клея', rol='Договор')
        # записки: по зоне АГ (старше) и общая (свежее) — под договором АГ первой идёт записка АГ
        dobavit('zap_ag', 'Пояснительная записка к договору АГ.docx', 'olimp', 'Записки и разборы',
                '2026-10-05T10:00:00', 'пояснительная записка', zona='АГ')
        dobavit('zap_obshch', 'Разбор замечаний заказчика.docx', 'olimp', 'Записки и разборы',
                '2026-10-25T10:00:00', 'разбор замечаний')
        # 10 чертежей: зоны АГ и ЗБ поровну — больше страницы, значит, сначала выбор зоны
        for i in range(10):
            dobavit(f'ch{i}', f'Чертёж накладки {i}.pdf', 'olimp', 'Чертежи конструктора',
                    f'2026-10-{10 + i:02d}T12:00:00', 'чертёж накладки', zona='АГ' if i % 2 else 'ЗБ')
        dobavit('chat', 'Чат с Натальей.md', 'olimp', 'Переписка', '2026-10-30T10:00:00',
                'Наталья прислала новые размеры')
        dobavit('bolshoj', 'Модель здания очень большая.dwg', 'olimp', 'Прочее', '2026-09-02T10:00:00',
                'модель', razmer=50 * 1024 * 1024)
        dobavit('net_na_diske', 'Пропавшая смета.xlsx', 'olimp', 'Сметы и расчёты', '2026-01-01T10:00:00',
                'пропавшая', na_diske=False)
        # Раздоры. Мебель: обычный чертёж и внутреннее с ценами
        dobavit('prihozhaya', 'Чертёж прихожей.pdf', 'raz_mebel', 'Чертежи конструктора', '2026-10-28T13:01:57',
                'чертёж прихожей шкаф', otkuda='из Telegram: Нелли', istochnik='telegram', otkogo='Нелли')
        dobavit('sebest', 'Себестоимость прихожей.xlsx', 'raz_mebel', 'Сметы и расчёты', '2026-10-29T09:00:00',
                'себестоимость прихожей цена', vnutrennee=1)
        con.commit()
        con.close()

        self.chernoviki = os.path.join(d, 'Черновики')
        bot.KLYUCH = KLYUCH
        bot.NAST = {
            'baza': self.put_bazy, 'model_golosa': 'tiny',
            'ochered_zayavok': os.path.join(d, 'zayavki.jsonl'),
            'aktualnost': os.path.join(d, 'aktualnost.json'),
            'sostavitel': {'chernoviki': self.chernoviki, 'papka': d},
            'proekty': [{'id': 'olimp', 'imya': 'Олимпийский', 'razrez': OLIMP_ZONY},
                        {'id': 'raz_mebel', 'imya': 'Раздоры. Мебель', 'razrez': {'imya': 'Этаж', 'znacheniya': []}}],
            'polzovateli': [
                {'imya': 'Мансур', 'telegram_id': MANSUR, 'proekty': '*', 'bez_vnutrennego': False, 'admin': True},
                {'imya': 'Юлия Евгеньевна', 'telegram_id': YULIYA, 'proekty': '*', 'bez_vnutrennego': False},
                {'imya': 'Игорь Михайлович', 'telegram_id': str(IGOR), 'proekty': '*', 'bez_vnutrennego': False},
                # проверка общей логики ограничений (в настоящих настройках таких нет)
                {'imya': 'Проверка ограничений', 'telegram_id': OGRANICHENNYJ, 'proekty': ['raz_mebel'],
                 'bez_vnutrennego': True},
                {'imya': 'Без номера', 'telegram_id': None, 'proekty': '*'},
            ]}
        bot._UZHE_PROSILI.clear()
        bot._DIALOGI.clear()
        bot._POSLEDNIJ_ZAPROS.clear()
        bot._MODEL = None
        self.tg = FalshivyjTelegram()
        zaplatki = [mock.patch.object(bot.requests, 'post', side_effect=self.tg.post),
                    mock.patch.object(bot.requests, 'get', side_effect=self.tg.get)]
        for z in zaplatki:
            z.start()
            self.addCleanup(z.stop)

    def tearDown(self):
        self.tmp.cleanup()

    # --- помощники ---
    def napisat(self, kto, tekst, imya='Тест', username='test'):
        bot.obrabotat({'update_id': 1, 'message': {
            'message_id': 10, 'chat': {'id': kto}, 'text': tekst,
            'from': {'id': kto, 'first_name': imya, 'username': username}}})

    def nazhat(self, kto, data, mid=77, dokument=False):
        msg = {'message_id': mid, 'chat': {'id': kto}}
        if dokument:
            msg['document'] = {'file_id': 'x'}
        bot.obrabotat({'update_id': 2, 'callback_query': {
            'id': 'cq1', 'data': data, 'from': {'id': kto, 'first_name': 'Тест'}, 'message': msg}})

    def f(self, *klyuchi):
        return [f'f:{self.id[k]}' for k in klyuchi]

    def aktualno(self, klyuch):
        con = sqlite3.connect(self.put_bazy)
        try:
            return con.execute('SELECT aktualno FROM faily WHERE id=?', [self.id[klyuch]]).fetchone()[0]
        finally:
            con.close()


class TestBot(OsnovaTesta):

    # --- доступ ---
    def test_chuzhoj_poluchaet_svoj_nomer(self):
        with self.assertLogs('dokumenty', 'WARNING') as zh:
            self.napisat(CHUZHOJ, 'договор', imya='Пётр', username='petr')
        tekst = self.tg.soobshcheniya(CHUZHOJ)
        self.assertEqual(tekst, ['Нет доступа. Ваш номер Telegram: 555. '
                                 'Передайте его Мансуру, чтобы он добавил вас.'])
        self.assertIn('Пётр @petr, номер 555', zh.output[0])
        admin = self.tg.soobshcheniya(MANSUR)
        self.assertEqual(len(admin), 1)
        self.assertIn('Просит доступ: Пётр @petr, номер', admin[0])
        self.assertNotIn('sendDocument', self.tg.metody())
        # повторное сообщение — админа второй раз не беспокоим
        with self.assertLogs('dokumenty', 'WARNING'):
            self.napisat(CHUZHOJ, 'ещё')
        self.assertEqual(len(self.tg.soobshcheniya(MANSUR)), 1)

    def test_chuzhoj_ne_mozhet_nazhat_knopku(self):
        for data in (f"f:{self.id['dog_ag']}", f"a:{self.id['dog_ag_v1']}", 'sd'):
            with self.assertLogs('dokumenty', 'WARNING'):
                self.nazhat(CHUZHOJ, data)
        self.assertNotIn('sendDocument', self.tg.metody())
        self.assertIn('Ваш номер Telegram: 555', self.tg.soobshcheniya(CHUZHOJ)[0])
        self.assertEqual(self.aktualno('dog_ag_v1'), 0)

    def test_polzovateli_v_nastroykah(self):
        """В настоящих настройках — только Мансур, Юлия Евгеньевна и Игорь Михайлович, все видят всё."""
        nast = chitat_json(poisk.NASTROYKI)
        p = nast['polzovateli']
        self.assertEqual([x['imya'] for x in p], ['Мансур', 'Юлия Евгеньевна', 'Игорь Михайлович'])
        self.assertTrue(all(x['proekty'] == '*' and not x.get('bez_vnutrennego') for x in p))
        self.assertNotIn('Ольг', json.dumps(p, ensure_ascii=False))

    def test_vse_troe_vidyat_vse(self):
        for kto in (MANSUR, YULIYA, IGOR):
            self.tg.vyzovy.clear()
            self.napisat(kto, 'Проекты')
            self.assertEqual([k['callback_data'] for k in self.tg.poslednie_knopki()], ['p:olimp', 'p:raz_mebel'])

    # --- меню по разделам каркаса ---
    def test_menyu_proektov(self):
        self.napisat(MANSUR, '/start')
        tekst = self.tg.soobshcheniya(MANSUR)
        self.assertIn('Здравствуйте, Мансур', tekst[0])
        # только актуальные и без «Переписки»: 5 договоров, 2 записки, 10 чертежей, смета, прочее
        self.assertEqual(para(self.tg.poslednie_knopki()),
                         [('Олимпийский (19)', 'p:olimp'), ('Раздоры. Мебель (2)', 'p:raz_mebel')])
        klav = [p for m, p in self.tg.vyzovy if m == 'sendMessage' and 'keyboard' in (p.get('reply_markup') or {})]
        self.assertIn('📝 Составить документ', json.dumps(klav[0]['reply_markup'], ensure_ascii=False))

    def test_razdely_karkasa(self):
        self.nazhat(MANSUR, 'p:olimp')
        self.assertEqual(self.tg.metody(), ['answerCallbackQuery', 'editMessageText'])
        self.assertEqual(para(self.tg.poslednie_knopki()),
                         [('Договоры (5)', 't:olimp:0'),
                          ('Сметы и расчёты (1)', 't:olimp:1'),
                          ('Чертежи конструктора (10)', 't:olimp:3'),
                          ('Записки и разборы (2)', 't:olimp:5'),
                          ('Прочее (1)', 't:olimp:11'),
                          ('Назад', 'm')])
        tekst = self.tg.soobshcheniya()[-1]
        for net in ('Переписка', 'Почта', 'Telegram'):
            self.assertNotIn(net, tekst + json.dumps(self.tg.poslednie_knopki(), ensure_ascii=False))

    def test_perepiska_ne_v_menyu(self):
        self.nazhat(MANSUR, f"t:olimp:{karkas.TIPY.index('Переписка')}")
        self.assertIn('Выберите раздел', self.tg.soobshcheniya()[-1])   # подделанная кнопка → разделы
        self.assertFalse([k for k in self.tg.poslednie_knopki() if k['callback_data'] == self.f('chat')[0]])

    def test_zony_dogovorov(self):
        self.nazhat(MANSUR, 't:olimp:0')
        self.assertIn('Олимпийский · Договоры', self.tg.soobshcheniya()[-1])
        self.assertEqual(para(self.tg.poslednie_knopki()),
                         [('АГ (3)', 'z:olimp:0'), ('ГС-ДЯ (1)', 'z:olimp:1'), ('Без зоны (1)', 'z:olimp:x'),
                          ('Все (5)', 'l:olimp:0:*:0'), ('Назад', 'p:olimp')])

    def test_kartochka_dogovora_s_prilozheniyami(self):
        self.nazhat(MANSUR, 'z:olimp:0')
        tekst = self.tg.soobshcheniya()[-1]
        self.assertIn('Олимпийский · Договоры · Зона АГ', tekst)
        self.assertIn('📄 <b>Договор АГ</b> — Договор АГ ред3', tekst)
        self.assertIn('20.10.2026 · из почты: Зверева · версий: 3 · docx+pdf', tekst)
        self.assertLess(tekst.index('Приложение 1 — Смета'), tekst.index('Приложение 2 — ТЗ на накладки'))
        self.assertEqual(para(self.tg.poslednie_knopki()), [
            ('📄 Договор АГ · 20.10', self.f('dog_ag')[0]),
            ('История версий (3)', f"v:{self.id['dog_ag']}"),
            ('Приложение 1 — Смета · 18.10', self.f('pril1_ag')[0]),
            ('Приложение 2 — ТЗ на накладки · 19.10', self.f('pril2_ag')[0]),
            ('📝 Записки к договорам (2)', 'zp:olimp:0'),
            ('Назад', 't:olimp:0')])
        # старые версии договора в карточке не видны
        self.assertNotIn(self.f('dog_ag_v1')[0], json.dumps(self.tg.vyzovy))

    def test_zapiski_k_dogovoram(self):
        self.nazhat(MANSUR, 'zp:olimp:0')
        knopki = self.tg.poslednie_knopki()
        # записка той же зоны — первой, хотя общий разбор свежее
        self.assertEqual([k['callback_data'] for k in knopki], self.f('zap_ag', 'zap_obshch') + ['z:olimp:0'])
        self.assertTrue(knopki[0]['text'].startswith('★ Пояснительная записка'))
        self.assertIn('сначала — Зона АГ', self.tg.soobshcheniya()[-1])

    def test_dogovor_bez_zony(self):
        self.nazhat(MANSUR, 'z:olimp:x')
        self.assertIn('Олимпийский · Договоры · без зоны', self.tg.soobshcheniya()[-1])
        self.assertEqual(self.tg.poslednie_knopki()[0]['callback_data'], self.f('dog_bez')[0])

    def test_istoriya_versiy(self):
        self.nazhat(MANSUR, f"v:{self.id['dog_ag']}")
        self.assertEqual(self.tg.metody(), ['answerCallbackQuery', 'editMessageText'])   # тот же экран
        self.assertIn('История версий: Договор АГ ред3', self.tg.soobshcheniya()[-1])
        self.assertEqual(para(self.tg.poslednie_knopki()), [
            ('✓ 20.10.2026 · Договор АГ ред3.docx', self.f('dog_ag')[0]),
            ('01.10.2026 · Договор АГ ред2.docx', self.f('dog_ag_v2')[0]),
            ('01.09.2026 · Договор АГ.docx', self.f('dog_ag_v1')[0]),
            ('Назад', 'p:olimp')])
        # старая версия приходит с пометкой и кнопкой «Сделать актуальной»
        self.tg.vyzovy.clear()
        self.nazhat(MANSUR, self.f('dog_ag_v1')[0])
        dok = self.tg.dokumenty()[0]
        self.assertIn('версия 1 из 3 (не актуальная)', dok['caption'])
        self.assertEqual(para(self.tg.knopki_dokumenta()), [
            ('История версий (3)', f"v:{self.id['dog_ag_v1']}"),
            ('✅ Сделать актуальной', f"a:{self.id['dog_ag_v1']}")])

    def test_razrez_v_bolshom_razdele(self):
        """Любой раздел больше страницы, у документов которого есть значения разреза: сначала выбор."""
        self.nazhat(MANSUR, 't:olimp:3')
        self.assertEqual(para(self.tg.poslednie_knopki()),
                         [('АГ (5)', 'l:olimp:3:0:0'), ('ЗБ (5)', 'l:olimp:3:1:0'),
                          ('Все (10)', 'l:olimp:3:*:0'), ('Назад', 'p:olimp')])
        self.tg.vyzovy.clear()
        self.nazhat(MANSUR, 'l:olimp:3:0:0')
        self.assertIn('Олимпийский · Чертежи конструктора · Зона АГ', self.tg.soobshcheniya()[-1])
        faily = [k['callback_data'] for k in self.tg.poslednie_knopki() if k['callback_data'].startswith('f:')]
        self.assertEqual(faily, self.f('ch9', 'ch7', 'ch5', 'ch3', 'ch1'))
        self.assertIn({'text': 'Назад', 'callback_data': 't:olimp:3'}, self.tg.poslednie_knopki())

    def test_spisok_s_listaniem(self):
        self.nazhat(MANSUR, 'l:olimp:3:*:0')
        knopki = self.tg.poslednie_knopki()
        faily = [k for k in knopki if k['callback_data'].startswith('f:')]
        self.assertEqual(len(faily), 8)
        self.assertEqual(faily[0]['callback_data'], self.f('ch9')[0])   # свежие сверху
        self.assertEqual(faily[0]['text'], 'Чертёж накладки 9 · 19.10')
        self.assertIn({'text': 'Ещё', 'callback_data': 'l:olimp:3:*:8'}, knopki)
        self.assertIn('Документы 1–8 из 10', self.tg.soobshcheniya()[-1])
        self.tg.vyzovy.clear()
        self.nazhat(MANSUR, 'l:olimp:3:*:8')
        knopki = self.tg.poslednie_knopki()
        self.assertEqual([k['callback_data'] for k in knopki if k['callback_data'].startswith('f:')],
                         self.f('ch1', 'ch0'))
        self.assertNotIn('Ещё', [k['text'] for k in knopki])
        self.assertIn({'text': 'Назад', 'callback_data': 'l:olimp:3:*:0'}, knopki)

    def test_malenkij_razdel_bez_vybora(self):
        self.nazhat(MANSUR, 't:olimp:5')   # 2 записки — сразу список
        self.assertEqual([k['callback_data'] for k in self.tg.poslednie_knopki()],
                         self.f('zap_obshch', 'zap_ag') + ['p:olimp'])

    def test_callback_data_korotkie(self):
        for data in ('m', 'p:olimp', 't:olimp:0', 'z:olimp:0', 'zp:olimp:0', 't:olimp:3', 'l:olimp:3:*:0',
                     'l:olimp:3:*:8', 'p:raz_mebel', f"v:{self.id['dog_ag']}", 'sd'):
            self.nazhat(MANSUR, data)
        self.napisat(MANSUR, 'договор')
        self.napisat(MANSUR, '/svezhee')
        self.nazhat(MANSUR, self.f('dog_ag')[0])
        for m, p in self.tg.vyzovy:
            for ryad in self.tg._razmetka(p).get('inline_keyboard', []):
                for k in ryad:
                    self.assertLessEqual(len(k['callback_data'].encode()), 64)

    def test_ustarevshaya_knopka(self):
        self.nazhat(MANSUR, 'x:chto-to')
        self.assertEqual(self.tg.vyzovy[0][1]['text'], bot.TEKST_USTARELA)
        self.nazhat(MANSUR, 't:olimp:99')  # раздела нет — показываем разделы
        self.assertIn('Выберите раздел', self.tg.soobshcheniya()[-1])
        self.nazhat(MANSUR, 'z:olimp:7')   # зоны с таким номером уже нет — выбор зоны
        self.assertIn('Выберите: зона', self.tg.soobshcheniya()[-1])

    # --- общая логика ограничений по проектам ---
    def test_ogranichennyj_vidit_tolko_svoj_proekt(self):
        self.napisat(OGRANICHENNYJ, '/start')
        knopki = self.tg.poslednie_knopki()
        self.assertEqual(para(knopki), [('Раздоры. Мебель (1)', 'p:raz_mebel')])   # внутреннее не считается
        self.tg.vyzovy.clear()
        self.nazhat(OGRANICHENNYJ, 'p:olimp')  # подделанная кнопка чужого проекта
        self.assertIn('нет доступных', self.tg.soobshcheniya()[-1])
        for data in ('z:olimp:0', 'l:olimp:3:*:0', f"v:{self.id['dog_ag']}"):
            self.tg.vyzovy.clear()
            self.nazhat(OGRANICHENNYJ, data)
            self.assertFalse([k for k in self.tg.poslednie_knopki() if k['callback_data'].startswith('f:')])
        for klyuch in ('dog_ag', 'sebest'):
            self.tg.vyzovy.clear()
            self.nazhat(OGRANICHENNYJ, self.f(klyuch)[0])
            self.assertNotIn('sendDocument', self.tg.metody())
        self.tg.vyzovy.clear()
        self.napisat(OGRANICHENNYJ, 'себестоимость прихожей')
        self.assertNotIn('Себестоимость', ' '.join(self.tg.soobshcheniya()))

    # --- поиск ---
    def test_poisk_tolko_aktualnye(self):
        self.napisat(MANSUR, 'договор АГ')
        tekst = self.tg.soobshcheniya()[-1]
        self.assertTrue(tekst.startswith('Нашёл: '))
        self.assertIn('Олимпийский · Договоры · Зона АГ · Договор', tekst)
        self.assertIn('из почты: Зверева', tekst)
        dannye = [k['callback_data'] for k in self.tg.poslednie_knopki()]
        self.assertIn(self.f('dog_ag')[0], dannye)
        for star in self.f('dog_ag_v1', 'dog_ag_v2'):
            self.assertNotIn(star, dannye)
        self.assertEqual(dannye[-1], 'sd')   # «📝 Составить документ» под результатами
        self.assertNotIn('старая версия', tekst)

    def test_poisk_arhiv_pokazyvaet_starye(self):
        for zapros in ('договор АГ архив', 'все версии договор АГ', 'старые договор АГ'):
            self.tg.vyzovy.clear()
            self.napisat(MANSUR, zapros)
            tekst = self.tg.soobshcheniya()[-1]
            self.assertIn('вместе со старыми версиями', tekst)
            self.assertIn('старая версия', tekst)
            dannye = [k['callback_data'] for k in self.tg.poslednie_knopki()]
            for k in self.f('dog_ag', 'dog_ag_v1', 'dog_ag_v2'):
                self.assertIn(k, dannye)

    def test_poisk_nahodit_perepisku(self):
        self.napisat(MANSUR, 'Наталья размеры')
        self.assertIn(self.f('chat')[0], [k['callback_data'] for k in self.tg.poslednie_knopki()])
        self.assertIn('Олимпийский · Переписка', self.tg.soobshcheniya()[-1])

    def test_poisk_s_otryvkom_i_otkuda(self):
        self.napisat(MANSUR, 'чертёж прихожей')
        tekst = self.tg.soobshcheniya()[-1]
        self.assertIn('<b>Чертёж прихожей</b>', tekst)
        self.assertIn('из Telegram: Нелли', tekst)
        self.assertIn('«', tekst)  # отрывок с подсветкой найденного

    def test_svezhee(self):
        self.napisat(OGRANICHENNYJ, '/svezhee')
        self.assertEqual([k['callback_data'] for k in self.tg.poslednie_knopki()], self.f('prihozhaya'))
        self.tg.vyzovy.clear()
        self.napisat(MANSUR, '/svezhee')
        dannye = [k['callback_data'] for k in self.tg.poslednie_knopki()]
        self.assertEqual(len(dannye), 10)
        self.assertEqual(dannye[0], self.f('sebest')[0])
        self.assertNotIn(self.f('chat')[0], dannye)   # переписка — только поиском

    def test_pomosh(self):
        self.napisat(MANSUR, '/pomosh')
        self.assertIn('Как искать', self.tg.soobshcheniya()[-1])
        self.assertIn('архив', self.tg.soobshcheniya()[-1])

    # --- отправка файлов ---
    def test_otpravka_faila_i_podpis(self):
        self.nazhat(MANSUR, self.f('prihozhaya')[0])
        dok = self.tg.dokumenty()
        self.assertEqual(len(dok), 1)
        self.assertEqual(dok[0]['_fail'], 'Чертёж прихожей.pdf')
        podpis = dok[0]['caption']
        self.assertIn('<b>Чертёж прихожей</b>', podpis)
        self.assertIn('Раздоры. Мебель · Чертежи конструктора', podpis)
        self.assertIn('28.10.2026 · из Telegram: Нелли', podpis)
        self.assertIn('версия 1 из 1', podpis)
        self.assertNotIn(self.tmp.name, podpis)   # путь на Mac в подписи не показываем
        self.assertEqual(para(self.tg.knopki_dokumenta()), [('🗄 Убрать в историю', f"h:{self.id['prihozhaya']}")])

    def test_podpis_dogovora(self):
        self.nazhat(MANSUR, self.f('dog_ag')[0])
        podpis = self.tg.dokumenty()[0]['caption']
        self.assertIn('<b>Договор АГ ред3</b>', podpis)
        self.assertIn('Олимпийский · Договоры · Зона АГ · Договор', podpis)
        self.assertIn('20.10.2026 · из почты: Зверева', podpis)
        self.assertIn('версия 3 из 3 · docx+pdf', podpis)
        self.assertIn(('История версий (3)', f"v:{self.id['dog_ag']}"), para(self.tg.knopki_dokumenta()))

    def test_bolshoj_fail_ne_otpravlyaetsya(self):
        self.nazhat(MANSUR, self.f('bolshoj')[0])
        self.assertNotIn('sendDocument', self.tg.metody())
        tekst = self.tg.soobshcheniya()[-1]
        self.assertIn('50,0 МБ', tekst)
        self.assertIn('<code>' + self.tmp.name, tekst)

    def test_fail_propal_s_diska(self):
        self.nazhat(MANSUR, self.f('net_na_diske')[0])
        self.assertNotIn('sendDocument', self.tg.metody())
        self.assertIn('не найден на диске', self.tg.soobshcheniya()[-1])

    # --- ручная актуальность ---
    def test_sdelat_aktualnoj_i_ubrat_v_istoriyu(self):
        self.nazhat(MANSUR, f"a:{self.id['dog_ag_v2']}")
        self.assertIn('теперь актуальная версия', self.tg.soobshcheniya()[-1])
        resheniya = chitat_json(bot.NAST['aktualnost'])
        self.assertEqual(resheniya, {self.put['dog_ag_v2']: 'aktualno'})
        self.assertEqual((self.aktualno('dog_ag_v2'), self.aktualno('dog_ag')), (1, 0))   # сразу в базе
        self.tg.vyzovy.clear()
        self.nazhat(MANSUR, 'z:olimp:0')
        self.assertEqual(self.tg.poslednie_knopki()[0]['callback_data'], self.f('dog_ag_v2')[0])
        # убрать в историю: договора АГ в меню больше нет, решение по ред2 заменено
        self.tg.vyzovy.clear()
        self.nazhat(MANSUR, f"h:{self.id['dog_ag_v2']}")
        self.assertIn('убран в историю', self.tg.soobshcheniya()[-1])
        resheniya = chitat_json(bot.NAST['aktualnost'])
        self.assertEqual(resheniya, {self.put['dog_ag_v2']: 'istoriya'})
        self.assertEqual(self.aktualno('dog_ag_v2'), 0)
        self.tg.vyzovy.clear()
        self.nazhat(MANSUR, 'z:olimp:0')
        self.assertIn('Самого договора здесь нет', self.tg.soobshcheniya()[-1])
        # вернуть другой версией
        self.nazhat(MANSUR, f"a:{self.id['dog_ag']}")
        resheniya = chitat_json(bot.NAST['aktualnost'])
        self.assertEqual(resheniya, {self.put['dog_ag']: 'aktualno'})
        self.assertEqual(self.aktualno('dog_ag'), 1)

    # --- голос ---
    def golosovoe(self, kto=MANSUR):
        bot.obrabotat({'update_id': 3, 'message': {
            'message_id': 11, 'chat': {'id': kto}, 'from': {'id': kto},
            'voice': {'file_id': 'abc', 'duration': 3, 'mime_type': 'audio/ogg'}}})

    def podmenit_golos(self, tekst):
        segment = types.SimpleNamespace(text=f' {tekst} ')
        model = mock.Mock()
        model.transcribe.side_effect = lambda *a, **k: (iter([segment]), None)
        fw = types.ModuleType('faster_whisper')
        fw.WhisperModel = mock.Mock(return_value=model)
        return fw, model

    def test_golos_bez_faster_whisper(self):
        with mock.patch.dict(sys.modules, {'faster_whisper': None}):
            self.golosovoe()
        self.assertIn('Голосовой поиск пока недоступен', self.tg.soobshcheniya()[-1])
        self.assertNotIn('getFile', self.tg.metody())

    def test_golos_raspoznan_i_poisk(self):
        fw, model = self.podmenit_golos('чертёж прихожей')
        with mock.patch.dict(sys.modules, {'faster_whisper': fw}):
            self.golosovoe()
            self.golosovoe()
        fw.WhisperModel.assert_called_once_with('tiny', device='cpu', compute_type='int8')  # грузится один раз
        put, = model.transcribe.call_args[0]
        self.assertTrue(put.endswith('.oga'))
        self.assertFalse(os.path.exists(put))  # временный файл убран
        self.assertEqual(model.transcribe.call_args[1]['language'], 'ru')
        tekst = self.tg.soobshcheniya()
        self.assertEqual(tekst[0], 'Распознал: «чертёж прихожей»')
        self.assertIn('Чертёж прихожей', tekst[1])

    # --- устойчивость и журнал ---
    def test_oshibka_ne_ronyaet_bota(self):
        with mock.patch.object(bot.poisk, 'najti', side_effect=RuntimeError('сломалось')), \
                self.assertLogs('dokumenty', 'ERROR'):
            self.napisat(MANSUR, 'договор')
        self.assertEqual(self.tg.soobshcheniya()[-1], 'Что-то пошло не так, попробуйте ещё раз.')

    def test_net_kataloga(self):
        bot.NAST['baza'] = os.path.join(self.tmp.name, 'net.db')
        with self.assertLogs('dokumenty', 'ERROR'):
            self.napisat(MANSUR, 'договор')
        self.assertIn('Каталог документов ещё не готов', self.tg.soobshcheniya()[-1])
        self.assertFalse(os.path.exists(bot.NAST['baza']))

    def test_klyuch_ne_popadaet_v_zhurnal(self):
        fmt = bot._BezKlyucha('%(message)s')
        zapis = logging.LogRecord('x', logging.WARNING, '', 0,
                                  'ошибка https://api.telegram.org/bot%s/getUpdates', (KLYUCH,), None)
        self.assertEqual(fmt.format(zapis), 'ошибка https://api.telegram.org/bot***/getUpdates')

    def test_opros_perezhivaet_obryv_svyazi(self):
        """getUpdates: обрыв сети → пауза и повтор; потом обновление обрабатывается, offset растёт."""
        otvety = [bot.requests.ConnectionError('нет сети'),
                  {'ok': True, 'result': [{'update_id': 40, 'message': {
                      'message_id': 1, 'chat': {'id': MANSUR}, 'from': {'id': MANSUR}, 'text': '/pomosh'}}]},
                  KeyboardInterrupt()]
        zaprosy = []

        def post(url, json=None, data=None, files=None, timeout=None):
            if url.endswith('/getUpdates'):
                zaprosy.append(dict(json))
                o = otvety.pop(0)
                if isinstance(o, BaseException):
                    raise o
                return mock.Mock(json=lambda: o)
            return self.tg.post(url, json=json, data=data, files=files, timeout=timeout)

        with mock.patch.object(bot.requests, 'post', side_effect=post), \
                mock.patch.object(bot, 'obnovit_nastroyki'), \
                mock.patch.object(bot, 'prochitat_klyuch', return_value=KLYUCH), \
                mock.patch.object(bot, 'nastroit_zhurnal'), \
                mock.patch.object(bot, 'proverit_otvety') as otv, \
                mock.patch.object(bot.time, 'sleep') as pauza, \
                self.assertLogs('dokumenty', 'INFO') as zh:
            bot.glavnaya()
        pauza.assert_called_once_with(5)
        self.assertEqual([z.get('offset') for z in zaprosy], [None, None, 41])
        self.assertEqual(zaprosy[0]['timeout'], 25)   # короткий опрос — чтобы раз в 30 с смотреть ответы агента
        self.assertGreaterEqual(otv.call_count, 1)
        self.assertIn('Как искать', self.tg.soobshcheniya(MANSUR)[-1])
        self.assertTrue(any('Нет связи с Telegram' in s for s in zh.output))

    def test_multipart_s_russkim_imenem(self):
        """Запрос sendDocument собирается requests'ом (без отправки) — с русским именем файла."""
        with open(os.path.join(self.tmp.name, 'x.pdf'), 'wb') as fh:
            fh.write(b'%PDF')
        with open(os.path.join(self.tmp.name, 'x.pdf'), 'rb') as fh:
            z = bot.requests.Request('POST', 'https://example.invalid/sendDocument',
                                     data={'chat_id': '1', 'caption': '<b>Чертёж</b>'},
                                     files={'document': ('Чертёж прихожей.pdf', fh)}).prepare()
        self.assertIn('Чертёж прихожей.pdf'.encode(), z.body)

    def test_net_faila_klyucha(self):
        bot.NAST['klyuch_bota'] = os.path.join(self.tmp.name, 'net_klyucha')
        with mock.patch('sys.stderr') as err, self.assertRaises(SystemExit):
            bot.prochitat_klyuch()
        self.assertIn('Нет файла с ключом бота', ''.join(c.args[0] for c in err.write.call_args_list))


class TestSostavit(OsnovaTesta):
    """Диалог «📝 Составить документ», очередь заявок и ответы составителя."""

    def zayavki(self):
        return sostavitel.prochitat(bot.NAST['ochered_zayavok'])

    def sostavit(self, kto=MANSUR, chto='письмо Зверевой о переносе монтажа АГ'):
        self.napisat(kto, '📝 Составить документ')
        self.napisat(kto, chto)
        self.nazhat(kto, 'sp:olimp')
        self.nazhat(kto, 'sk:zak')
        self.nazhat(kto, 'ss:zav')
        return self.zayavki()[-1]

    def otvet_sostavitelya(self, o):
        sostavitel.dopisat_otvet(sostavitel.put_otvetov(bot.NAST['ochered_zayavok']), o)

    def test_dialog_pishet_zayavku(self):
        self.napisat(MANSUR, '📝 Составить документ')
        self.assertIn('Что за документ нужен?', self.tg.soobshcheniya()[-1])
        self.napisat(MANSUR, 'письмо Зверевой о переносе монтажа АГ')
        self.assertIn('По какому проекту?', self.tg.soobshcheniya()[-1])
        self.assertEqual(para(self.tg.poslednie_knopki()),
                         [('Олимпийский', 'sp:olimp'), ('Раздоры. Мебель', 'sp:raz_mebel'), ('Отмена', 'sx')])
        self.nazhat(MANSUR, 'sp:olimp')
        self.assertEqual([k['text'] for k in self.tg.poslednie_knopki()],
                         ['Заказчику', 'Внутренний', 'Конструктору', 'Монтажникам', 'Отмена'])
        self.nazhat(MANSUR, 'sk:zak')
        self.assertEqual([k['text'] for k in self.tg.poslednie_knopki()], ['Сегодня', 'Завтра', 'Не срочно', 'Отмена'])
        with self.assertLogs('dokumenty', 'INFO'):
            self.nazhat(MANSUR, 'ss:zav')
        tekst = self.tg.soobshcheniya()[-1]
        self.assertIn('Нашёл похожие документы-основы:', tekst)
        self.assertIn('Отправляю задание агенту — пришлю черновик сюда.', tekst)

        with open(bot.NAST['ochered_zayavok'], encoding='utf-8') as fh:
            stroki = fh.read().splitlines()
        self.assertEqual(len(stroki), 1)
        z = json.loads(stroki[0])
        self.assertEqual(set(z) >= {'id', 'kto', 'chto', 'proekt', 'dlya', 'srok', 'osnovy', 'sozdano', 'status'}, True)
        self.assertEqual(z['kto'], {'telegram_id': MANSUR, 'imya': 'Мансур', 'chat': MANSUR})
        self.assertEqual((z['chto'], z['proekt'], z['proekt_imya'], z['dlya'], z['srok'], z['status']),
                         ('письмо Зверевой о переносе монтажа АГ', 'olimp', 'Олимпийский', 'Заказчику', 'Завтра',
                          'novaya'))
        self.assertTrue(1 <= len(z['osnovy']) <= 3)
        self.assertEqual(z['osnovy'][0]['id'], self.id['dog_ag'])   # актуальный договор АГ (Зверева)
        self.assertEqual(z['osnovy'][0]['put'], self.put['dog_ag'])
        akt = {self.id[k] for k in self.id} - {self.id['dog_ag_v1'], self.id['dog_ag_v2']}
        self.assertTrue(all(o['id'] in akt for o in z['osnovy']))   # только актуальные
        self.assertEqual([k['callback_data'] for k in self.tg.poslednie_knopki()],
                         [f"f:{o['id']}" for o in z['osnovy']])
        self.assertNotIn(MANSUR, bot._DIALOGI)

    def test_sostavit_kogda_nichego_ne_nashlos(self):
        self.napisat(YULIYA, 'акт скрытых работ лестница')
        self.assertEqual(self.tg.soobshcheniya()[-1], bot.TEKST_PUSTO)
        self.assertEqual(para(self.tg.poslednie_knopki()), [('📝 Составить документ', 'sdq')])
        self.nazhat(YULIYA, 'sdq')
        self.assertIn('Составлю: «акт скрытых работ лестница»', self.tg.soobshcheniya()[-1])
        self.nazhat(YULIYA, 'sp:raz_mebel')
        self.nazhat(YULIYA, 'sk:mon')
        with self.assertLogs('dokumenty', 'INFO'):
            self.nazhat(YULIYA, 'ss:ns')
        z = self.zayavki()[-1]
        self.assertEqual((z['chto'], z['proekt'], z['dlya'], z['srok'], z['kto']['imya']),
                         ('акт скрытых работ лестница', 'raz_mebel', 'Монтажникам', 'Не срочно', 'Юлия Евгеньевна'))
        self.assertEqual(z['osnovy'], [])
        self.assertIn('Похожих документов-основ не нашёл', self.tg.soobshcheniya()[-1])

    def test_otmena_i_knopki_preryvayut_dialog(self):
        self.napisat(MANSUR, '/sostavit')
        self.nazhat(MANSUR, 'sx')
        self.napisat(MANSUR, 'чертёж прихожей')     # после отмены — обычный поиск
        self.assertIn('Нашёл', self.tg.soobshcheniya()[-1])
        self.napisat(MANSUR, '📝 Составить документ')
        self.napisat(MANSUR, 'Проекты')
        self.assertNotIn(MANSUR, bot._DIALOGI)
        self.nazhat(MANSUR, 'ss:zav')               # кнопка не по порядку — заявки нет
        self.assertEqual(self.zayavki(), [])

    def test_golosom_chto_za_dokument(self):
        fw, _ = self.podmenit_golos('смета на накладки для зоны АГ')
        self.napisat(MANSUR, '📝 Составить документ')
        with mock.patch.dict(sys.modules, {'faster_whisper': fw}):
            TestBot.golosovoe(self)
        self.assertIn('Составлю: «смета на накладки для зоны АГ»', self.tg.soobshcheniya()[-1])

    podmenit_golos = TestBot.podmenit_golos

    def test_voprosy_dohodyat_i_otvet_v_zayavku(self):
        with self.assertLogs('dokumenty', 'INFO'):
            z = self.sostavit()
        sostavitel.izmenit(bot.NAST['ochered_zayavok'], z['id'],
                           {'status': 'voprosy', 'voprosy': ['На какую дату перенести?', 'Кто подписывает?']})
        self.otvet_sostavitelya({'id': z['id'], 'status': 'voprosy',
                                 'voprosy': ['На какую дату перенести?', 'Кто подписывает?']})
        self.tg.vyzovy.clear()
        self.assertEqual(bot.proverit_otvety(), 1)
        tekst = self.tg.soobshcheniya(MANSUR)[-1]
        self.assertIn('агенту не хватает данных', tekst)
        self.assertIn('1. На какую дату перенести?\n2. Кто подписывает?', tekst)
        # повторная проверка не шлёт то же самое
        self.assertEqual(bot.proverit_otvety(), 0)
        with self.assertLogs('dokumenty', 'INFO'):
            self.napisat(MANSUR, 'на 15 ноября, подписывает Игорь Михайлович')
        self.assertIn('Передал ответ агенту', self.tg.soobshcheniya()[-1])
        z = sostavitel.najti_zayavku(bot.NAST['ochered_zayavok'], z['id'])
        self.assertEqual(z['status'], 'novaya')
        self.assertEqual(z['utochneniya'][0]['otvet'], 'на 15 ноября, подписывает Игорь Михайлович')
        self.assertEqual(z['utochneniya'][0]['voprosy'], ['На какую дату перенести?', 'Кто подписывает?'])

    def test_otvet_kn_knopke_posle_perezapuska(self):
        with self.assertLogs('dokumenty', 'INFO'):
            z = self.sostavit()
        bot._DIALOGI.clear()     # бот перезапускался — состояние потеряно, кнопка «Ответить» работает
        self.nazhat(MANSUR, f"so:{z['id']}")
        with self.assertLogs('dokumenty', 'INFO'):
            self.napisat(MANSUR, 'ответ')
        self.assertEqual(sostavitel.najti_zayavku(bot.NAST['ochered_zayavok'], z['id'])['utochneniya'][0]['otvet'],
                         'ответ')
        # чужую заявку ответом не изменить
        self.nazhat(YULIYA, f"so:{z['id']}")
        self.napisat(YULIYA, 'чужой ответ')
        self.assertEqual(len(sostavitel.najti_zayavku(bot.NAST['ochered_zayavok'], z['id'])['utochneniya']), 1)

    def test_gotovyj_chernovik_prihodit_failom(self):
        with self.assertLogs('dokumenty', 'INFO'):
            z = self.sostavit()
        put = os.path.join(self.chernoviki, 'Олимпийский', '2026-11-03 Письмо Зверевой.docx')
        os.makedirs(os.path.dirname(put))
        with open(put, 'wb') as fh:
            fh.write(b'PK')
        self.otvet_sostavitelya({'id': z['id'], 'status': 'gotovo', 'fail': put,
                                 'istochniki': [self.put['dog_ag'], self.put['pril1_ag']],
                                 'chto_izmeneno': 'Новая дата монтажа', 'proverki': 'Сверить дату с графиком'})
        self.tg.vyzovy.clear()
        with self.assertLogs('dokumenty', 'INFO'):
            bot.proverit_otvety()
        dok = self.tg.dokumenty()
        self.assertEqual(len(dok), 1)
        self.assertEqual(str(dok[0]['chat_id']), str(MANSUR))
        self.assertEqual(dok[0]['_fail'], '2026-11-03 Письмо Зверевой.docx')
        self.assertTrue(dok[0]['caption'].startswith('Черновик — проверьте перед отправкой. Источники: '))
        self.assertIn('dog_ag_Договор АГ ред3.docx', dok[0]['caption'])
        self.assertIn('Сверить дату с графиком', self.tg.soobshcheniya(MANSUR)[-1])

    def test_chernovik_ne_iz_papki_chernovikov_ne_otpravlyaetsya(self):
        with self.assertLogs('dokumenty', 'INFO'):
            z = self.sostavit()
        self.otvet_sostavitelya({'id': z['id'], 'status': 'gotovo', 'fail': self.put['sebest']})
        self.tg.vyzovy.clear()
        bot.proverit_otvety()
        self.assertEqual(self.tg.dokumenty(), [])
        self.assertIn('не нашёлся в папке черновиков', self.tg.soobshcheniya(MANSUR)[-1])

    def test_oshibka_sostavitelya(self):
        with self.assertLogs('dokumenty', 'INFO'):
            z = self.sostavit()
        self.otvet_sostavitelya({'id': z['id'], 'status': 'oshibka', 'oshibka': 'агент не уложился в 30 мин'})
        self.tg.vyzovy.clear()
        bot.proverit_otvety()
        self.assertIn('Не получилось составить черновик', self.tg.soobshcheniya(MANSUR)[-1])

    def test_obryv_svyazi_ne_teryaet_otvet(self):
        with self.assertLogs('dokumenty', 'INFO'):
            z = self.sostavit()
        self.otvet_sostavitelya({'id': z['id'], 'status': 'voprosy', 'voprosy': ['?']})
        with mock.patch.object(bot.requests, 'post', side_effect=bot.requests.ConnectionError('нет сети')):
            with self.assertRaises(bot.requests.ConnectionError):
                bot.proverit_otvety()
        self.tg.vyzovy.clear()
        self.assertEqual(bot.proverit_otvety(), 1)   # доставлен со второго раза


class TestOkno(OsnovaTesta):
    """«Одно рабочее окно»: в чате только текущий ответ; файлы — из кэша file_id."""

    def okno(self, kto=MANSUR):
        return [(e['id'], e['vid']) for e in bot.okno(kto)]

    def test_novyj_zapros_udalyaet_proshlye(self):
        self.napisat(MANSUR, '/start')                 # 1001 — приветствие, 1002 — проекты
        self.assertEqual(self.okno(), [(1001, 'dop'), (1002, 'ekran')])
        self.tg.vyzovy.clear()
        self.napisat(MANSUR, 'договор АГ')
        self.assertEqual(sorted(self.tg.udaleno(MANSUR)), [10, 1001, 1002])
        # сначала новый ответ, потом уборка — чат не мигает пустым
        self.assertEqual(self.tg.metody()[0], 'sendMessage')
        self.assertEqual(self.okno(), [(1003, 'ekran')])

    def test_vhodyashchee_soobshchenie_udalyaetsya(self):
        self.napisat(MANSUR, 'Проекты')
        self.assertEqual(self.tg.udaleno(MANSUR), [10])
        fw, _ = TestBot.podmenit_golos(self, 'чертёж прихожей')
        self.tg.vyzovy.clear()
        with mock.patch.dict(sys.modules, {'faster_whisper': fw}):
            TestBot.golosovoe(self)                     # голосовое тоже убирается
        self.assertEqual(sorted(self.tg.udaleno(MANSUR)), [11, 1001])
        self.assertEqual(self.okno(), [(1002, 'dop'), (1003, 'ekran')])   # «Распознал…» и результаты

    def test_navigaciya_pravit_ekran_a_fail_ubiraet(self):
        self.napisat(MANSUR, 'Проекты')                 # экран 1001
        self.tg.vyzovy.clear()
        self.nazhat(MANSUR, 'p:olimp', mid=1001)
        self.assertEqual(self.tg.metody(), ['answerCallbackQuery', 'editMessageText'])
        self.nazhat(MANSUR, 'z:olimp:0', mid=1001)
        self.tg.vyzovy.clear()
        self.nazhat(MANSUR, self.f('dog_ag')[0], mid=1001)    # файл 1002 под экраном
        self.assertEqual(self.tg.udaleno(), [])
        self.assertEqual(self.okno(), [(1001, 'ekran'), (1002, 'dop')])
        self.nazhat(MANSUR, self.f('pril1_ag')[0], mid=1001)  # другой файл — прежний убирается
        self.assertEqual(self.tg.udaleno(), [1002])
        self.assertEqual(self.okno(), [(1001, 'ekran'), (1003, 'dop')])
        self.tg.vyzovy.clear()
        self.nazhat(MANSUR, 't:olimp:0', mid=1001)            # «Назад» — файл убран, экран тот же
        self.assertEqual(self.tg.udaleno(), [1003])
        self.assertIn(('editMessageText', 1001), [(m, p.get('message_id')) for m, p in self.tg.vyzovy])
        self.assertEqual(self.okno(), [(1001, 'ekran')])

    def test_knopka_pod_failom_pravit_ekran_okna(self):
        self.napisat(MANSUR, 'договор АГ')              # экран 1001
        self.nazhat(MANSUR, self.f('dog_ag')[0], mid=1001)     # файл 1002
        self.tg.vyzovy.clear()
        self.nazhat(MANSUR, f"v:{self.id['dog_ag']}", mid=1002, dokument=True)   # «История версий» под файлом
        pravki = [p['message_id'] for m, p in self.tg.vyzovy if m == 'editMessageText']
        self.assertEqual(pravki, [1001])                 # документ не правится — правится экран
        self.assertEqual(self.tg.udaleno(), [1002])
        self.assertEqual(self.okno(), [(1001, 'ekran')])

    def test_ustarevshaya_knopka_okno_ne_trogaet(self):
        self.napisat(MANSUR, 'Проекты')
        self.tg.vyzovy.clear()
        self.nazhat(MANSUR, 'x:chto-to', mid=1001)
        self.assertEqual(self.tg.udaleno(), [])
        self.assertEqual(self.okno(), [(1001, 'ekran')])

    def test_okno_posle_perezapuska(self):
        """Окно лежит в okna.json рядом с базой: после перезапуска бот убирает прежние сообщения.
        Не удаляется (старше 48 ч) — стирает текст, у файла — подпись."""
        put = os.path.join(self.tmp.name, 'okna.json')
        with open(put, 'w', encoding='utf-8') as fh:
            json.dump({str(MANSUR): [{'id': 500, 'vid': 'ekran'}, {'id': 501, 'vid': 'dop', 'fail': True},
                                     {'id': 502, 'vid': 'dop'}]}, fh)
        self.tg.ne_udalyat = {501, 502}
        nast = bot.NAST
        importlib.reload(bot)                            # «перезапуск»: в памяти бота ничего нет
        bot.KLYUCH, bot.NAST = KLYUCH, nast
        self.napisat(MANSUR, 'Свежее')
        self.assertEqual(sorted(self.tg.udaleno(MANSUR)), [10, 500, 501, 502])
        self.assertIn(('editMessageCaption', 501), [(m, p.get('message_id')) for m, p in self.tg.vyzovy])
        stert = [p for m, p in self.tg.vyzovy if m == 'editMessageText' and p['message_id'] == 502]
        self.assertEqual(stert[0]['reply_markup'], {'inline_keyboard': []})
        self.assertEqual(chitat_json(put), {str(MANSUR): [{'id': 1001, 'vid': 'ekran'}]})
        self.assertFalse(os.path.exists(put + '.novyj'))   # запись атомарная, временный файл подменён

    def test_kesh_file_id(self):
        self.nazhat(MANSUR, self.f('prihozhaya')[0])
        dok = self.tg.dokumenty()
        self.assertEqual(dok[0]['_fail'], 'Чертёж прихожей.pdf')     # первый раз — загрузка
        kesh = chitat_json(os.path.join(self.tmp.name, 'telegram_faily.json'))
        self.assertEqual(kesh, {bot.hesh_faila(self.put['prihozhaya']): 'FID-1001'})
        self.tg.vyzovy.clear()
        self.nazhat(YULIYA, self.f('prihozhaya')[0])                 # второй раз (и другому) — по file_id
        dok = self.tg.dokumenty()
        self.assertEqual(len(dok), 1)
        self.assertNotIn('_fail', dok[0])
        self.assertEqual(dok[0]['document'], 'FID-1001')
        self.assertIn('версия 1 из 1', dok[0]['caption'])
        self.assertNotIn('sendChatAction', self.tg.metody())
        # файл на диске изменился — другой хэш, загружаем заново
        with open(self.put['prihozhaya'], 'wb') as fh:
            fh.write(b'new')
        self.tg.vyzovy.clear()
        self.nazhat(YULIYA, self.f('prihozhaya')[0])
        self.assertEqual(self.tg.dokumenty()[0]['_fail'], 'Чертёж прихожей.pdf')

    def test_kesh_file_id_otkat_pri_oshibke(self):
        put_kesha = os.path.join(self.tmp.name, 'telegram_faily.json')
        h = bot.hesh_faila(self.put['prihozhaya'])
        with open(put_kesha, 'w', encoding='utf-8') as fh:
            json.dump({h: 'STARYJ'}, fh)
        self.tg.plohie_file_id = {'STARYJ'}
        self.nazhat(MANSUR, self.f('prihozhaya')[0])
        dok = self.tg.dokumenty()
        self.assertEqual([d.get('document') for d in dok], ['STARYJ', None])   # сначала file_id, потом загрузка
        self.assertEqual(dok[1]['_fail'], 'Чертёж прихожей.pdf')
        self.assertEqual(chitat_json(put_kesha), {h: 'FID-1001'})
        self.assertEqual(self.okno(), [(77, 'ekran'), (1001, 'dop')])
        self.assertNotIn('Не получилось', ' '.join(self.tg.soobshcheniya()))

    def test_uvedomlenie_adminu_ne_v_okne(self):
        self.napisat(MANSUR, 'Проекты')                  # экран 1001
        with self.assertLogs('dokumenty', 'WARNING'):
            self.napisat(CHUZHOJ, 'привет')               # 1002 — чужому, 1003 — уведомление админу
        self.assertEqual(self.okno(), [(1001, 'ekran')])
        self.tg.vyzovy.clear()
        self.napisat(MANSUR, 'Свежее')
        self.assertNotIn(1003, self.tg.udaleno())


class TestChernovikVOkne(OsnovaTesta):
    """Черновик в окне: не удаляется новыми запросами, пока не нажмут «Готово — закрыть»."""
    zayavki, sostavit, otvet_sostavitelya = TestSostavit.zayavki, TestSostavit.sostavit, TestSostavit.otvet_sostavitelya

    def chernovik(self, s_poyasneniem=True):
        with self.assertLogs('dokumenty', 'INFO'):
            z = self.sostavit()
        put = os.path.join(self.chernoviki, 'Олимпийский', 'Письмо.docx')
        os.makedirs(os.path.dirname(put), exist_ok=True)
        with open(put, 'wb') as fh:
            fh.write(b'PK')
        o = {'id': z['id'], 'status': 'gotovo', 'fail': put}
        if s_poyasneniem:
            o['proverki'] = 'Сверить дату'
        self.otvet_sostavitelya(o)
        self.tg.vyzovy.clear()
        with self.assertLogs('dokumenty', 'INFO'):
            bot.proverit_otvety()
        return z

    def test_knopka_zakryt_i_chernovik_ne_udalyaetsya(self):
        z = self.chernovik()
        dok_id, poyasn_id = self.tg.nomer - 1, self.tg.nomer
        self.assertEqual(para(self.tg.poslednie_knopki()), [('✅ Готово — закрыть', f"cz:{z['id']}")])
        okno = {e['id']: e['vid'] for e in bot.okno(MANSUR)}
        self.assertEqual((okno[dok_id], okno[poyasn_id]), ('chernovik', 'chernovik'))
        # новые запросы и навигация черновик не трогают
        self.napisat(MANSUR, 'Проекты')
        self.nazhat(MANSUR, 'p:olimp', mid=self.tg.nomer)
        self.napisat(MANSUR, 'договор АГ')
        self.assertFalse({dok_id, poyasn_id} & set(self.tg.udaleno()))
        # «Готово — закрыть» убирает и файл, и пояснение
        self.tg.vyzovy.clear()
        self.nazhat(MANSUR, f"cz:{z['id']}", mid=poyasn_id)
        self.assertEqual(sorted(self.tg.udaleno()), [dok_id, poyasn_id])
        self.assertEqual([e['vid'] for e in bot.okno(MANSUR)], ['ekran'])   # экран поиска остался

    def test_knopka_zakryt_pod_failom_bez_poyasneniya(self):
        z = self.chernovik(s_poyasneniem=False)
        self.assertEqual(para(self.tg.knopki_dokumenta()), [('✅ Готово — закрыть', f"cz:{z['id']}")])
        self.assertLessEqual(len(f"cz:{z['id']}".encode()), 64)


class TestSostavitel(unittest.TestCase):
    """sostavitel.py: заявка → claude -p (подменён) → статус и строка ответа."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.chernoviki = os.path.join(d, 'Черновики')
        self.nast = {'ochered_zayavok': os.path.join(d, 'zayavki.jsonl'),
                     'sostavitel': {'komanda': ['claude', '-p'], 'flagi': ['--output-format', 'json'],
                                    'papka': d, 'chernoviki': self.chernoviki}}
        self.put = self.nast['ochered_zayavok']
        self.osnova = os.path.join(d, 'Договор АГ.docx')
        sostavitel.dobavit(self.put, {
            'id': 'z1', 'kto': {'telegram_id': MANSUR, 'imya': 'Мансур', 'chat': MANSUR},
            'chto': 'письмо о переносе монтажа', 'proekt': 'olimp', 'proekt_imya': 'Олимпийский',
            'dlya': 'Заказчику', 'srok': 'Завтра', 'osnovy': [{'id': 1, 'put': self.osnova, 'nazvanie': 'Договор АГ'}],
            'sozdano': '2026-11-03T10:00:00', 'status': 'novaya'})

    def tearDown(self):
        self.tmp.cleanup()

    def zapusk(self, rezultat=None, kod=0, sozdat=None, stdout=None):
        def run(komanda, **kw):
            if sozdat:
                os.makedirs(os.path.dirname(sozdat), exist_ok=True)
                open(sozdat, 'wb').close()
            vyvod = stdout if stdout is not None else json.dumps(
                {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': rezultat}, ensure_ascii=False)
            return subprocess.CompletedProcess(komanda, kod, vyvod, 'ошибка агента' if kod else '')
        with mock.patch.object(sostavitel.subprocess, 'run', side_effect=run) as m, \
                mock.patch('builtins.print'):
            otvety = sostavitel.obrabotat_ochered(self.nast)
        return m, otvety

    def otvety_v_fajle(self):
        return sostavitel._chitat(sostavitel.put_otvetov(self.put))

    def test_gotovo(self):
        fail = os.path.join(self.chernoviki, 'Олимпийский', '2026-11-03 Письмо.docx')
        rez = ('Готово.\n```json\n' + json.dumps({'fail': fail, 'istochniki': [self.osnova],
                                                 'chto_izmeneno': 'дата', 'proverki': 'сверить'}) + '\n```')
        m, otvety = self.zapusk(rez, sozdat=fail)
        komanda = m.call_args[0][0]
        self.assertEqual(komanda[:2], ['claude', '-p'])
        self.assertEqual(komanda[-2:], ['--output-format', 'json'])
        promt = komanda[2]
        for chast in ('письмо о переносе монтажа', 'Олимпийский', 'Заказчику', self.osnova, '--nayti',
                      '"voprosy"', '"fail"', 'НИКОГДА ничего не отправляй наружу',
                      os.path.join(self.chernoviki, 'Олимпийский')):
            self.assertIn(chast, promt)
        self.assertEqual(m.call_args[1]['cwd'], self.tmp.name)
        z = sostavitel.najti_zayavku(self.put, 'z1')
        self.assertEqual((z['status'], z['fail'], z['popytki']), ('gotovo', fail, 1))
        o, = self.otvety_v_fajle()
        self.assertEqual((o['id'], o['status'], o['fail'], o['istochniki'], o['kto']['chat']),
                         ('z1', 'gotovo', fail, [self.osnova], MANSUR))

    def test_voprosy(self):
        self.zapusk('{"voprosy": ["На какую дату?"]}')
        self.assertEqual(sostavitel.najti_zayavku(self.put, 'z1')['status'], 'voprosy')
        self.assertEqual(self.otvety_v_fajle()[0]['voprosy'], ['На какую дату?'])
        # пустой проход: новых заявок нет — агент не запускается
        m, otvety = self.zapusk('{}')
        m.assert_not_called()
        # заявка с ответом снова в очереди — промпт содержит уточнения
        sostavitel.izmenit(self.put, 'z1', {'status': 'novaya', 'utochneniya': [
            {'voprosy': ['На какую дату?'], 'otvet': 'на 15 ноября'}]})
        m, _ = self.zapusk('{"voprosy": ["Ещё вопрос"]}')
        self.assertIn('на 15 ноября', m.call_args[0][0][2])

    def test_oshibki(self):
        self.zapusk(kod=1)
        z = sostavitel.najti_zayavku(self.put, 'z1')
        self.assertEqual(z['status'], 'oshibka')
        self.assertIn('код 1', z['oshibka'])
        for rez, sozdat, ozhidaem in (('просто текст без JSON', None, 'нет JSON'),
                                      ('{"fail": "/tmp/net-takogo.docx"}', None, 'его нет'),
                                      (None, None, 'непонятный вывод')):
            sostavitel.izmenit(self.put, 'z1', {'status': 'novaya'})
            self.zapusk(rez, stdout='[]' if rez is None else None)
            self.assertIn(ozhidaem, sostavitel.najti_zayavku(self.put, 'z1')['oshibka'])
        # файл вне папки черновиков не принимаем
        chuzhoj = os.path.join(self.tmp.name, 'чужой.docx')
        sostavitel.izmenit(self.put, 'z1', {'status': 'novaya'})
        self.zapusk(json.dumps({'fail': chuzhoj}), sozdat=chuzhoj)
        self.assertIn('не в папку черновиков', sostavitel.najti_zayavku(self.put, 'z1')['oshibka'])

    def test_tajmaut_i_net_komandy(self):
        with mock.patch.object(sostavitel.subprocess, 'run', side_effect=subprocess.TimeoutExpired('claude', 1800)), \
                mock.patch('builtins.print'):
            sostavitel.obrabotat_ochered(self.nast)
        self.assertIn('не уложился', sostavitel.najti_zayavku(self.put, 'z1')['oshibka'])
        sostavitel.izmenit(self.put, 'z1', {'status': 'novaya'})
        with mock.patch.object(sostavitel.subprocess, 'run', side_effect=FileNotFoundError(2, 'нет', 'claude')), \
                mock.patch('builtins.print'):
            sostavitel.obrabotat_ochered(self.nast)
        self.assertIn('не найдена команда агента', sostavitel.najti_zayavku(self.put, 'z1')['oshibka'])

    def test_zastryavshaya_zayavka(self):
        sostavitel.izmenit(self.put, 'z1', {'status': 'v_rabote', 'popytki': 1})
        m, _ = self.zapusk('{"voprosy": ["?"]}')
        m.assert_called_once()   # вернулась в очередь и обработана
        sostavitel.izmenit(self.put, 'z1', {'status': 'v_rabote', 'popytki': 3})
        m, _ = self.zapusk('{"voprosy": ["?"]}')
        m.assert_not_called()
        self.assertEqual(sostavitel.najti_zayavku(self.put, 'z1')['status'], 'oshibka')
        self.assertEqual(self.otvety_v_fajle()[-1]['status'], 'oshibka')

    def test_nastroyki_po_umolchaniyu(self):
        nast = chitat_json(poisk.NASTROYKI)
        s = sostavitel.nastroyki_sostavitelya(nast)
        self.assertEqual(s['komanda'], ['claude', '-p'])
        self.assertEqual(s['flagi'][:2], ['--output-format', 'json'])
        self.assertEqual(s['papka'], '~/archiwood_proekty')
        self.assertEqual(s['chernoviki'], '~/archiwood_proekty/dokumenty/Черновики')
        self.assertTrue(sostavitel.put_ocheredi(nast).endswith('archiwood_proekty/dokumenty/zayavki.jsonl'))
        self.assertTrue(sostavitel.put_otvetov('/x/zayavki.jsonl') == '/x/zayavki_otvety.jsonl')


class TestKatalog(unittest.TestCase):
    """katalog.py на временной папке: разметка каркаса, актуальные версии, миграция, ручные решения."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.olimp = os.path.join(d, '1 ОЛИМПИЙСКИЙ')
        fajly = {
            'Договоры/1 АГ/Договор АГ.docx': '2026-09-01',
            'Договоры/1 АГ/Договор АГ ред2.docx': '2026-10-01',
            'Договоры/1 АГ/Договор АГ ред2.pdf': '2026-10-01',
            'Договоры/1 АГ/Приложение 1 Смета АГ.xlsx': '2026-10-02',
            'Договоры/2 ГС-ДЯ/Договор ГС-ДЯ.docx': '2026-10-03',
            'Пояснительная записка к договору АГ.docx': '2026-10-04',
            '9 АРХИВ/Договор ГС-ДЯ ред5.docx': '2026-10-20',
        }
        from datetime import datetime as dt
        for otn, den in fajly.items():
            put = os.path.join(self.olimp, otn)
            os.makedirs(os.path.dirname(put), exist_ok=True)
            with open(put, 'wb') as fh:
                fh.write(otn.encode())
            t = dt.fromisoformat(den + 'T12:00:00').timestamp()
            os.utime(put, (t, t))
        nast = chitat_json(poisk.NASTROYKI)
        nast.update(baza=os.path.join(d, 'katalog.db'), aktualnost=os.path.join(d, 'aktualnost.json'),
                    korni=[{'put': self.olimp, 'proekt': 'olimp'}])
        self.put_nast = os.path.join(d, 'nastroyki.json')
        with open(self.put_nast, 'w', encoding='utf-8') as fh:
            json.dump(nast, fh, ensure_ascii=False)
        self.nast = nast
        self.env = mock.patch.dict(os.environ, {'DOKUMENTY_NASTROYKI': self.put_nast})
        self.env.start()
        self.K = importlib.reload(katalog)

    def tearDown(self):
        self.env.stop()
        importlib.reload(katalog)
        self.tmp.cleanup()

    def sobrat(self, zanovo=False):
        with mock.patch('builtins.print'):
            self.K.obnovit(zanovo=zanovo)
        con = poisk.baza(self.nast['baza'])
        rows = {r['imya']: dict(r) for r in con.execute('SELECT * FROM faily')}
        return con, rows

    def test_razmetka_i_aktualnye(self):
        con, r = self.sobrat()
        d = r['Договор АГ ред2.docx']
        self.assertEqual((d['tip'], d['razdel'], d['zona'], d['rol'], d['aktualno'], d['versiy'], d['formaty']),
                         ('Договоры', 'Договоры', 'АГ', 'Договор', 1, 3, 'docx+pdf'))
        self.assertTrue(d['semya'].startswith('olimp|Договоры|АГ|договор'))
        self.assertEqual(r['Договор АГ.docx']['aktualno'], 0)
        self.assertEqual(r['Договор АГ ред2.pdf']['aktualno'], 0)
        self.assertEqual(r['Приложение 1 Смета АГ.xlsx']['rol'], 'Приложение 1 — Смета')
        self.assertEqual(r['Пояснительная записка к договору АГ.docx']['tip'], 'Записки и разборы')
        # архивная ред5 — новее, но не актуальна; актуальной остаётся живая версия
        self.assertEqual((r['Договор ГС-ДЯ ред5.docx']['arhiv'], r['Договор ГС-ДЯ ред5.docx']['aktualno']), (1, 0))
        self.assertEqual(r['Договор ГС-ДЯ.docx']['aktualno'], 1)
        # FTS: и чистое название, и имя файла
        imya = con.execute('SELECT imya FROM tekst WHERE rowid=?', [d['id']]).fetchone()[0]
        self.assertIn('Договор АГ ред2', imya)
        self.assertIn('Договор АГ ред2.docx', imya)
        # поиск по каталогу — только актуальные; «архив» — все
        dostup = {'proekty': '*'}
        najdeno = {x['imya'] for x in poisk.najti(con, 'договор АГ', dostup, 20)}
        self.assertIn('Договор АГ ред2.docx', najdeno)
        self.assertNotIn('Договор АГ.docx', najdeno)
        self.assertIn('Договор АГ.docx', {x['imya'] for x in poisk.najti(con, 'договор АГ архив', dostup, 20)})
        d = poisk.dogovor_zony(con, 'olimp', 'АГ', dostup)
        self.assertEqual(d['dogovor']['imya'], 'Договор АГ ред2.docx')
        self.assertEqual([x['rol'] for x in d['prilozheniya']], ['Приложение 1 — Смета'])
        self.assertEqual([z['zona'] for z in poisk.zony(con, 'olimp', dostup)], ['АГ', 'ГС-ДЯ'])
        self.assertEqual(len(poisk.versii(con, r['Договор АГ.docx']['semya'], dostup)), 3)
        con.close()

    def test_ruchnye_resheniya(self):
        con, r = self.sobrat()
        con.close()
        star = os.path.join(self.olimp, 'Договоры/1 АГ/Договор АГ.docx')
        with open(self.nast['aktualnost'], 'w', encoding='utf-8') as fh:
            json.dump({star: 'aktualno', r['Договор ГС-ДЯ.docx']['semya']: 'istoriya'}, fh, ensure_ascii=False)
        con, r = self.sobrat()
        self.assertEqual((r['Договор АГ.docx']['aktualno'], r['Договор АГ ред2.docx']['aktualno']), (1, 0))
        self.assertEqual(r['Договор ГС-ДЯ.docx']['aktualno'], 0)
        con.close()

    def test_migraciya_staroj_bazy(self):
        con = sqlite3.connect(self.nast['baza'])
        con.executescript('''CREATE TABLE faily (id INTEGER PRIMARY KEY, put TEXT UNIQUE NOT NULL,
            imya TEXT, rasshirenie TEXT, razmer INTEGER, izmenen REAL, data TEXT, proekt TEXT, proekt_imya TEXT,
            poryadok_proekta INTEGER, razdel TEXT, poryadok_razdela INTEGER, istochnik TEXT, otkogo TEXT,
            vnutrennee INTEGER DEFAULT 0, hash TEXT, dubl_of INTEGER);
            CREATE VIRTUAL TABLE tekst USING fts5(imya, mesto, soderzhanie, tokenize = "unicode61 remove_diacritics 2");''')
        con.close()
        con, _ = self.sobrat()    # первая сборка в старую базу
        # как в базе до каркаса: строки есть, разметки нет
        con.execute('UPDATE faily SET tip=NULL, zona=NULL, rol=NULL, semya=NULL, nazvanie=NULL, aktualno=NULL')
        con.commit()
        con.close()
        with mock.patch.object(self.K, 'izvlech_tekst', side_effect=AssertionError('текст не перечитываем')):
            con, r = self.sobrat()   # вторая: файлы не менялись, разметка пересчитана без чтения текста
        stolbcy = {x[1] for x in con.execute('PRAGMA table_info(faily)')}
        self.assertTrue({'tip', 'zona', 'rol', 'semya', 'nazvanie', 'otkuda', 'aktualno', 'versiy', 'formaty'}
                        <= stolbcy)
        self.assertEqual(r['Договор АГ ред2.docx']['aktualno'], 1)
        self.assertEqual((r['Договор АГ ред2.docx']['tip'], r['Договор АГ ред2.docx']['zona']), ('Договоры', 'АГ'))
        self.assertEqual(r['Договор АГ.docx']['aktualno'], 0)
        imya = con.execute('SELECT imya FROM tekst WHERE rowid=?', [r['Договор АГ ред2.docx']['id']]).fetchone()[0]
        self.assertTrue(imya.startswith('Договор АГ ред2 '))   # FTS дополнен чистым названием
        con.close()


if __name__ == '__main__':
    unittest.main()
