"""Проверки бота «АРХИВУД Документы» без сети.

Telegram подменяется (unittest.mock): requests.post/get не выходят в интернет,
а записывают, что бот хотел отправить. Каталог — временная SQLite-база.

    python3 -m unittest test_bot -v
"""
import logging
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bot  # noqa: E402

MANSUR, OLGA, CHUZHOJ = 101, 202, 555
KLYUCH = '123456:SEKRETNYJ-KLYUCH'

SHEMA = '''
CREATE TABLE faily (
  id INTEGER PRIMARY KEY, put TEXT UNIQUE NOT NULL,
  imya TEXT, rasshirenie TEXT, razmer INTEGER, izmenen REAL, data TEXT,
  proekt TEXT, proekt_imya TEXT, poryadok_proekta INTEGER,
  razdel TEXT, poryadok_razdela INTEGER,
  istochnik TEXT, otkogo TEXT, vnutrennee INTEGER DEFAULT 0,
  hash TEXT, dubl_of INTEGER
);
CREATE VIRTUAL TABLE tekst USING fts5(imya, mesto, soderzhanie, tokenize = "unicode61 remove_diacritics 2");
'''


class FalshivyjTelegram:
    """Вместо requests.post: запоминает вызовы и отвечает «ok»."""
    def __init__(self):
        self.vyzovy = []

    def post(self, url, json=None, data=None, files=None, timeout=None):
        metod = url.rsplit('/', 1)[1]
        par = dict(json or data or {})
        if files:
            par['_fail'] = files['document'][0]
        self.vyzovy.append((metod, par))
        result = {'message_id': 1}
        if metod == 'getFile':
            result = {'file_path': 'voice/file_1.oga'}
        return mock.Mock(json=lambda: {'ok': True, 'result': result})

    def get(self, url, timeout=None):
        self.vyzovy.append(('skachat', {}))
        return mock.Mock(content=b'OggS-fake', raise_for_status=lambda: None)

    def metody(self):
        return [m for m, _ in self.vyzovy]

    def soobshcheniya(self, chat=None):
        return [p['text'] for m, p in self.vyzovy
                if m in ('sendMessage', 'editMessageText') and (chat is None or p['chat_id'] == chat)]

    def poslednie_knopki(self):
        for m, p in reversed(self.vyzovy):
            if m in ('sendMessage', 'editMessageText') and p.get('reply_markup', {}).get('inline_keyboard'):
                return [k for ryad in p['reply_markup']['inline_keyboard'] for k in ryad]
        return []


class TestBot(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.put_bazy = os.path.join(d, 'katalog.db')
        con = sqlite3.connect(self.put_bazy)
        con.executescript(SHEMA)
        self.id = {}

        def dobavit(klyuch, imya, proekt, razdel, data, soderzhanie='', vnutrennee=0,
                    otkogo='', na_diske=True, razmer=None):
            put = os.path.join(d, klyuch + '_' + imya)
            if na_diske:
                with open(put, 'wb') as fh:
                    if razmer:
                        fh.truncate(razmer)  # «разреженный» файл: большой по размеру, но место не занимает
                    else:
                        fh.write(b'test')
            pi = {'olimp': 'Олимпийский', 'raz_mebel': 'Раздоры. Мебель'}[proekt]
            cur = con.execute(
                'INSERT INTO faily (put, imya, rasshirenie, razmer, data, proekt, proekt_imya, '
                'poryadok_proekta, razdel, poryadok_razdela, istochnik, otkogo, vnutrennee) '
                'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                [put, imya, os.path.splitext(imya)[1], razmer or 4, data, proekt, pi,
                 0 if proekt == 'olimp' else 2, razdel, {'Договоры и сметы': 0, 'Чертежи и схемы': 1,
                                                         'Внутреннее': 4}[razdel],
                 'papka', otkogo, vnutrennee])
            con.execute('INSERT INTO tekst (rowid, imya, mesto, soderzhanie) VALUES (?,?,?,?)',
                        [cur.lastrowid, imya, f'{pi} {razdel}', soderzhanie])
            self.id[klyuch] = cur.lastrowid

        # Олимпийский: 10 договоров (для листания по 8) и чертёж
        for i in range(10):
            dobavit(f'dog{i}', f'Договор олимпийский поставка №{i}.pdf', 'olimp', 'Договоры и сметы',
                    f'2026-10-{10 + i:02d}T12:00:00', 'договор поставки дверей Олимпийский')
        dobavit('olimp_chertezh', 'Схема дверей корпус 2.pdf', 'olimp', 'Чертежи и схемы',
                '2026-09-01T10:00:00', 'схема дверей')
        dobavit('bolshoj', 'Модель здания очень большая.dwg', 'olimp', 'Чертежи и схемы',
                '2026-09-02T10:00:00', 'модель', razmer=50 * 1024 * 1024)
        dobavit('net_na_diske', 'Пропавший договор.docx', 'olimp', 'Договоры и сметы',
                '2026-01-01T10:00:00', 'пропавший', na_diske=False)
        # Раздоры. Мебель: обычный чертёж и внутреннее с ценами
        dobavit('prihozhaya', 'Чертёж прихожей.pdf', 'raz_mebel', 'Чертежи и схемы',
                '2026-10-28T13:01:57', 'чертёж прихожей шкаф', otkogo='Нелли')
        dobavit('sebest', 'Себестоимость прихожей.xlsx', 'raz_mebel', 'Внутреннее',
                '2026-10-29T09:00:00', 'себестоимость прихожей цена', vnutrennee=1)
        con.commit()
        con.close()

        bot.KLYUCH = KLYUCH
        bot.NAST = {
            'baza': self.put_bazy, 'model_golosa': 'tiny',
            'proekty': [{'id': 'olimp', 'imya': 'Олимпийский'}, {'id': 'raz_mebel', 'imya': 'Раздоры. Мебель'}],
            'polzovateli': [
                {'imya': 'Мансур', 'telegram_id': MANSUR, 'proekty': '*', 'bez_vnutrennego': False, 'admin': True},
                {'imya': 'Ольга (конструктор)', 'telegram_id': str(OLGA), 'proekty': ['raz_mebel'],
                 'bez_vnutrennego': True},
                {'imya': 'Без номера', 'telegram_id': None, 'proekty': '*'},
            ]}
        bot._UZHE_PROSILI.clear()
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

    def nazhat(self, kto, data):
        bot.obrabotat({'update_id': 2, 'callback_query': {
            'id': 'cq1', 'data': data, 'from': {'id': kto, 'first_name': 'Тест'},
            'message': {'message_id': 77, 'chat': {'id': kto}}}})

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
        with self.assertLogs('dokumenty', 'WARNING'):
            self.nazhat(CHUZHOJ, f"f:{self.id['dog0']}")
        self.assertNotIn('sendDocument', self.tg.metody())
        self.assertIn('Ваш номер Telegram: 555', self.tg.soobshcheniya(CHUZHOJ)[0])

    # --- меню ---
    def test_menyu_proektov(self):
        self.napisat(MANSUR, '/start')
        tekst = self.tg.soobshcheniya(MANSUR)
        self.assertIn('Здравствуйте, Мансур', tekst[0])
        knopki = self.tg.poslednie_knopki()
        self.assertEqual([(k['text'], k['callback_data']) for k in knopki],
                         [('Олимпийский (13)', 'p:olimp'), ('Раздоры. Мебель (2)', 'p:raz_mebel')])
        # кнопка «Проекты» на клавиатуре — то же меню
        self.tg.vyzovy.clear()
        self.napisat(MANSUR, 'Проекты')
        self.assertEqual(len(self.tg.poslednie_knopki()), 2)

    def test_razdely(self):
        self.nazhat(MANSUR, 'p:olimp')
        self.assertEqual(self.tg.metody(), ['answerCallbackQuery', 'editMessageText'])
        knopki = self.tg.poslednie_knopki()
        self.assertEqual([(k['text'], k['callback_data']) for k in knopki],
                         [('Договоры и сметы (11)', 'r:olimp:0:0'),
                          ('Чертежи и схемы (2)', 'r:olimp:1:0'),
                          ('Назад', 'm')])

    def test_spisok_s_listaniem(self):
        self.nazhat(MANSUR, 'r:olimp:0:0')
        knopki = self.tg.poslednie_knopki()
        faily = [k for k in knopki if k['callback_data'].startswith('f:')]
        self.assertEqual(len(faily), 8)
        # свежие сверху: №9 от 19.10 — первый
        self.assertEqual(faily[0]['callback_data'], f"f:{self.id['dog9']}")
        self.assertTrue(faily[0]['text'].endswith(' · 19.10'))
        self.assertLessEqual(len(faily[0]['text'].split(' · ')[0]), 40)
        self.assertIn({'text': 'Ещё', 'callback_data': 'r:olimp:0:8'}, knopki)
        self.assertIn({'text': 'Назад', 'callback_data': 'p:olimp'}, knopki)
        self.assertIn('Файлы 1–8 из 11', self.tg.soobshcheniya()[-1])

        self.tg.vyzovy.clear()
        self.nazhat(MANSUR, 'r:olimp:0:8')
        knopki = self.tg.poslednie_knopki()
        faily = [k['callback_data'] for k in knopki if k['callback_data'].startswith('f:')]
        self.assertEqual(faily, [f"f:{self.id['dog1']}", f"f:{self.id['dog0']}",
                                 f"f:{self.id['net_na_diske']}"])
        self.assertNotIn('Ещё', [k['text'] for k in knopki])
        self.assertIn({'text': 'Назад', 'callback_data': 'r:olimp:0:0'}, knopki)
        self.assertIn('Файлы 9–11 из 11', self.tg.soobshcheniya()[-1])

    def test_callback_data_korotkie(self):
        for data in ('m', 'p:olimp', 'r:olimp:0:0', 'r:olimp:0:8', 'p:raz_mebel', 'r:raz_mebel:0:0'):
            self.nazhat(MANSUR, data)
        self.napisat(MANSUR, 'договор')
        self.napisat(MANSUR, '/svezhee')
        for m, p in self.tg.vyzovy:
            for ryad in (p.get('reply_markup') or {}).get('inline_keyboard', []):
                for k in ryad:
                    self.assertLessEqual(len(k['callback_data'].encode()), 64)

    def test_ustarevshaya_knopka(self):
        self.nazhat(MANSUR, 'x:chto-to')
        self.assertEqual(self.tg.vyzovy[0][1]['text'], bot.TEKST_USTARELA)
        self.nazhat(MANSUR, 'r:olimp:99:0')  # раздела уже нет — показываем разделы
        self.assertIn('Выберите раздел', self.tg.soobshcheniya()[-1])

    # --- права Ольги ---
    def test_olga_vidit_tolko_svoj_proekt(self):
        self.napisat(OLGA, '/start')
        knopki = self.tg.poslednie_knopki()
        self.assertEqual([k['callback_data'] for k in knopki], ['p:raz_mebel'])
        self.assertEqual(knopki[0]['text'], 'Раздоры. Мебель (1)')  # внутреннее не считается

        self.tg.vyzovy.clear()
        self.nazhat(OLGA, 'p:raz_mebel')
        self.assertEqual([k['text'] for k in self.tg.poslednie_knopki()], ['Чертежи и схемы (1)', 'Назад'])

        self.tg.vyzovy.clear()
        self.nazhat(OLGA, 'p:olimp')  # подделанная кнопка чужого проекта
        self.assertIn('нет доступных', self.tg.soobshcheniya()[-1])
        self.assertFalse([k for k in self.tg.poslednie_knopki() if k['callback_data'].startswith('r:')])

        self.tg.vyzovy.clear()
        self.nazhat(OLGA, 'r:olimp:0:0')
        self.assertFalse([k for k in self.tg.poslednie_knopki() if k['callback_data'].startswith('f:')])

    def test_olga_ne_poluchit_chuzhoj_fail_po_poddelke(self):
        for klyuch in ('dog0', 'sebest'):
            self.tg.vyzovy.clear()
            self.nazhat(OLGA, f'f:{self.id[klyuch]}')
            self.assertNotIn('sendDocument', self.tg.metody())
            self.assertEqual(self.tg.soobshcheniya(OLGA), ['Файл не найден или к нему нет доступа.'])
        # а свой файл — получает
        self.tg.vyzovy.clear()
        self.nazhat(OLGA, f"f:{self.id['prihozhaya']}")
        self.assertIn('sendDocument', self.tg.metody())

    def test_olga_ne_nahodit_vnutrennee_i_chuzhoe(self):
        self.napisat(OLGA, 'себестоимость прихожей')
        self.assertNotIn('Себестоимость', ' '.join(self.tg.soobshcheniya()))
        self.tg.vyzovy.clear()
        self.napisat(OLGA, 'договор олимпийский')
        self.assertEqual(self.tg.soobshcheniya(), [bot.TEKST_PUSTO])

    # --- поиск ---
    def test_poisk_nahodit(self):
        self.napisat(MANSUR, 'договор олимпийский')
        tekst = self.tg.soobshcheniya()[-1]
        self.assertTrue(tekst.startswith('Нашёл: 7'))
        self.assertIn('Олимпийский · Договоры и сметы', tekst)
        knopki = self.tg.poslednie_knopki()
        self.assertEqual(len(knopki), 7)
        self.assertTrue(all(k['callback_data'].startswith('f:') for k in knopki))
        self.assertTrue(knopki[0]['text'].startswith('1. '))

    def test_poisk_s_otryvkom_i_otkogo(self):
        self.napisat(MANSUR, 'чертёж прихожей')
        tekst = self.tg.soobshcheniya()[-1]
        self.assertIn('Чертёж прихожей.pdf', tekst)
        self.assertIn('От: Нелли', tekst)
        self.assertIn('«', tekst)  # отрывок с подсветкой найденного

    def test_poisk_pusto(self):
        self.napisat(MANSUR, 'абракадабра несуществующее')
        self.assertEqual(self.tg.soobshcheniya(), [
            'Ничего не нашёл. Попробуйте другие слова: например, '
            '«договор олимпийский» или «чертёж прихожей».'])

    def test_svezhee(self):
        self.napisat(OLGA, '/svezhee')
        self.assertEqual([k['callback_data'] for k in self.tg.poslednie_knopki()],
                         [f"f:{self.id['prihozhaya']}"])
        self.tg.vyzovy.clear()
        self.napisat(MANSUR, '/svezhee')
        knopki = self.tg.poslednie_knopki()
        self.assertEqual(len(knopki), 10)
        self.assertEqual(knopki[0]['callback_data'], f"f:{self.id['sebest']}")

    def test_pomosh(self):
        self.napisat(MANSUR, '/pomosh')
        self.assertIn('Как искать', self.tg.soobshcheniya()[-1])

    # --- отправка файлов ---
    def test_otpravka_faila(self):
        self.nazhat(MANSUR, f"f:{self.id['prihozhaya']}")
        dok = [p for m, p in self.tg.vyzovy if m == 'sendDocument']
        self.assertEqual(len(dok), 1)
        self.assertEqual(dok[0]['_fail'], 'Чертёж прихожей.pdf')
        podpis = dok[0]['caption']
        self.assertIn('<b>Чертёж прихожей.pdf</b>', podpis)
        self.assertIn('Раздоры. Мебель · Чертежи и схемы', podpis)
        self.assertIn('28.10.2026', podpis)
        self.assertIn('От: Нелли', podpis)
        self.assertIn('<code>' + self.tmp.name, podpis)

    def test_bolshoj_fail_ne_otpravlyaetsya(self):
        self.nazhat(MANSUR, f"f:{self.id['bolshoj']}")
        self.assertNotIn('sendDocument', self.tg.metody())
        tekst = self.tg.soobshcheniya()[-1]
        self.assertIn('50,0 МБ', tekst)
        self.assertIn('<code>' + self.tmp.name, tekst)

    def test_fail_propal_s_diska(self):
        self.nazhat(MANSUR, f"f:{self.id['net_na_diske']}")
        self.assertNotIn('sendDocument', self.tg.metody())
        self.assertIn('не найден на диске', self.tg.soobshcheniya()[-1])

    # --- голос ---
    def golosovoe(self, kto=MANSUR):
        bot.obrabotat({'update_id': 3, 'message': {
            'message_id': 11, 'chat': {'id': kto}, 'from': {'id': kto},
            'voice': {'file_id': 'abc', 'duration': 3, 'mime_type': 'audio/ogg'}}})

    def test_golos_bez_faster_whisper(self):
        with mock.patch.dict(sys.modules, {'faster_whisper': None}):
            self.golosovoe()
        self.assertIn('Голосовой поиск пока недоступен', self.tg.soobshcheniya()[-1])
        self.assertNotIn('getFile', self.tg.metody())

    def test_golos_raspoznan_i_poisk(self):
        segment = types.SimpleNamespace(text=' чертёж прихожей ')
        model = mock.Mock()
        model.transcribe.return_value = (iter([segment]), None)
        fw = types.ModuleType('faster_whisper')
        fw.WhisperModel = mock.Mock(return_value=model)
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
        self.assertIn('Чертёж прихожей.pdf', tekst[1])

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
                mock.patch.object(bot.time, 'sleep') as pauza, \
                self.assertLogs('dokumenty', 'INFO') as zh:
            bot.glavnaya()
        pauza.assert_called_once_with(5)
        self.assertEqual([z.get('offset') for z in zaprosy], [None, None, 41])
        self.assertEqual(zaprosy[0]['timeout'], 50)
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


if __name__ == '__main__':
    unittest.main()
