"""Каркас документов АРХИВУД: из отдельных файлов — карточки документов.

Один документ живёт во многих файлах (версии, docx+pdf, копии из почты).
Здесь каждый файл получает:
  tip     — раздел каркаса (Договоры, Сметы и расчёты, Исходные данные, …);
  zona    — зона проекта (у Олимпийского: АГ, ГС-ДЯ, ЗБ, НЯ);
  rol     — роль внутри договора: «Договор», «Приложение 2 — ТЗ на накладки»;
  semya   — ключ семьи версий: все файлы одного документа;
  nazvanie — человеческое название без мусора;
  istochnik_tekst — откуда пришёл: «из почты: Зверева», «из Telegram: Наталья».
Потом в каждой семье выбирается актуальная (крайняя) версия; остальные — история.

Модуль чистый (без базы и файлов), его используют katalog.py, бот и демо.
"""
import re

TIPY = [
    'Договоры',
    'Сметы и расчёты',
    'Исходные данные заказчика',
    'Чертежи конструктора',
    'Производство и монтаж',
    'Записки и разборы',
    'Встречи и решения',
    'Материалы и каталоги',
    'Счета и оплаты',
    'Фото',
    'Переписка',      # чаты и тексты писем: в меню не показываем, ищутся поиском
    'Прочее',
]

ZONY = [('АГ', r'(?<![А-ЯA-Z])АГ(?![А-ЯA-Z])'), ('ГС-ДЯ', r'ГС[ _-]?ДЯ'), ('ЗБ', r'(?<![А-ЯA-Z])ЗБ(?![А-ЯA-Z])'),
        ('НЯ', r'(?<![А-ЯA-Z])НЯ(?![А-ЯA-Z])')]

FOTO = {'jpg', 'jpeg', 'png', 'heic', 'webp', 'mov', 'mp4', 'm4v', 'gif'}
AUDIO = {'m4a', 'mp3', 'wav', 'ogg', 'oga', 'aac'}


def nizh(s):
    return (s or '').lower().replace('ё', 'е')


def est(tekst, *slova):
    """Слово с начала слова: «смет» найдётся в «смета», но «счет» не найдётся в «расчет»."""
    return any(re.search(r'(?<![а-яa-z0-9])' + re.escape(s), tekst) for s in slova)


def zona(imya, put):
    """Зона: сначала папка зоны («/ 2 ГС-ДЯ /»), потом имя файла, потом остальной путь.
    Слова «по форме АГ» зону не задают — это ссылка на образец."""
    def ubrat(t):
        return re.sub(r'по\s+форме\s+\S+', ' ', t or '', flags=re.I)
    papki = [ubrat(x) for x in (put or '').split(' / ')]
    for c in reversed(papki):
        for z, rx in ZONY:
            if re.fullmatch(r'\s*\d*\s*' + rx + r'\s*', c):
                return z
    for t in [ubrat(imya)] + list(reversed(papki)):
        naydeno = sorted((m.start(), z) for z, rx in ZONY for m in [re.search(rx, t)] if m)
        if len(naydeno) == 1 or (naydeno and len({z for _, z in naydeno}) == 1):
            return naydeno[0][1]
    return ''


def nomer_prilozheniya(n):
    m = re.search(r'(?<![а-яa-z])(?:прил\.?|приложение)\s*№?\s*(\d+)', n)
    return int(m.group(1)) if m else None


def opredelit_tip(imya, put, rassh):
    n, p = nizh(imya.replace('_', ' ')), nizh(put)
    if rassh == 'md' and 'telegram' in p:
        return 'Переписка'
    # расшифровки голосовых и видео: «Telegram audio.ogg.txt»
    if rassh == 'txt' and re.search(r'\.(ogg|oga|m4a|mp3|wav|mp4|mov)$', n.rsplit('.', 1)[0]):
        return 'Встречи и решения'
    if rassh in AUDIO or est(n, 'расшифровк', 'встреча', 'итоги встречи', 'протокол встречи', 'журнал', 'запись юлии',
                              'разговор', 'состояние проекта', 'решения', 'задачи'):
        return 'Встречи и решения'
    if rassh in FOTO:
        if est(n + ' ' + p, 'визуализ', 'дизайн-проект', 'дизайн проект', 'рендер'):
            return 'Исходные данные заказчика'
        return 'Фото'
    if nomer_prilozheniya(n) is not None and not est(n, 'пояснен', 'записк'):
        return 'Договоры'
    if est(n, 'пояснительн', 'пояснения', 'записка', 'разбор', 'проверка пакета', 'замечания', 'анализ', 'для юлии',
           'для мансура', 'для игоря', 'расхождения', 'уточнения', 'инф.письмо', 'информационное письмо', 'письма-условия'):
        return 'Записки и разборы'
    if est(n, 'акт приема', 'акт приемки', 'акт передачи'):
        return 'Договоры'
    if est(n, 'договор', 'допсоглаш', 'доп соглаш', 'доп. соглаш', 'дополнительное соглаш', 'протокол разноглас', 'спецификац'):
        return 'Договоры'
    if est(n, 'счет на оплату', 'счет №', 'счет ', 'упд', 'upd', 'акт сверки', 'платеж', 'payment', 'оплат', 'выписк', 'чек',
           'заказ покупателя', 'требование', 'фнс', 'налог'):
        return 'Счета и оплаты'
    if est(n, 'смет', 'структура стоимост', 'себестоим', 'расчет', 'кп', 'коммерческое предлож', 'цены', 'с ценами',
           'свод', 'снижение', 'маржа', 'стоимост', 'прайс', 'подсчет'):
        return 'Сметы и расчёты'
    if est(n, 'монтаж', 'коробк', 'в производство', 'очеред', 'очеред', 'лист монтажник', 'ведомост', 'фиксация',
           'согласование дверей', 'согласованные', 'двери 1 эт', 'двери цоколь', 'этаж двери', 'парадные двери', 'первоочеред'):
        return 'Производство и монтаж'
    if est(n, 'каталог', 'catalog', 'сертификат', 'отказное письмо', 'наличие', 'price', 'паспорт', 'акрил', 'лак ', 'краск', 'фурнитур', 'образц', 'техлист', 'tds'):
        return 'Материалы и каталоги'
    if est(n + ' ' + p, 'тз', 'техническое задание', 'визуализ', 'дизайн-проект', 'дизайн проект', 'график', 'лист замер',
           'замер', 'данные заказчика', 'от заказчика', 'заявка'):
        return 'Исходные данные заказчика'
    if (rassh in ('dwg', 'dxf') or re.match(r'^(ип|ир|им|из|ио|ии)[ -]?\d', n)
            or est(n + ' ' + p, 'чертеж', 'узел', 'узлы', 'раскладк', 'развертк', 'маркировк', 'пилот', 'ир-', 'конструктор',
                   'схема', 'деталировк', 'сборка', 'профил', 'детали')):
        return 'Чертежи конструктора'
    return 'Прочее'


# слова-признаки предмета договора, чтобы разные договоры не слились в одну семью
PREDMET = ['монтаж', 'накладк', 'форма', 'паркет рус', 'закупк', 'поставк', 'обшивк', 'лестниц', 'мебел', 'панел']


def chistoe_imya(imya):
    """Название без расширения, номеров-приставок, дат и служебных слов."""
    s = re.sub(r'\.[A-Za-z0-9]{2,5}$', '', imya)
    s = re.sub(r'^\d{3,}_+', '', s)                     # 50891__Схема…
    s = re.sub(r'^[А-ЯЁA-Z][а-яёa-z]+_[А-ЯЁ]_[А-ЯЁ]_', '', s)   # Зиновьев_И_М_…
    s = s.replace('_', ' ')
    s = re.sub(r'\b\d{1,2}\.\d{1,2}\.\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b', '', s)
    s = re.sub(r'\(\d+\)|\bкопия\b|\bcopy\b', '', s, flags=re.I)
    s = re.sub(r'\s*[—–-]\s*$', '', re.sub(r'\s+', ' ', s)).strip(' .,—–-')
    return s[:1].upper() + s[1:] if s else imya


def klyuch_semi(tip, zona_, imya):
    """Какие файлы — версии одного документа."""
    n = nizh(chistoe_imya(imya))
    if tip == 'Договоры':
        nom = nomer_prilozheniya(n)
        predmet = ' '.join(p for p in PREDMET if p in n and nom is None)
        rol = f'прил{nom}' if nom is not None else 'прил' if est(n, 'приложение') else 'договор'
        return f'{tip}|{zona_}|{rol}|{predmet}'
    # прочие: смысловые слова названия без служебных
    n = re.sub(r'\b(ред|редакция|версия|итоговая|итог|финал|final|исправлен\w*|кратко|новая|новый|v\d+|вариант \d+|'
               r'примечания подрядчика|наша редакция|как получено|для юлии|для мансура|внутренний|открытая)\b', ' ', n)
    n = re.sub(r'[^а-яa-z0-9 ]', ' ', n)
    slova = [w for w in n.split() if len(w) > 1 and not w.isdigit()][:8]
    return f'{tip}|{zona_}|{" ".join(slova)}'


def rol_v_dogovore(imya):
    n = nizh(imya)
    nom = nomer_prilozheniya(n)
    if nom is None:
        return 'Приложение (без номера)' if est(n, 'приложение') else 'Договор'
    ost = re.sub(r'.*?(?:прил\.?|приложение)\s*№?\s*\d+\s*[—–.-]*\s*', '', chistoe_imya(imya), count=1, flags=re.I)
    ost = re.sub(r'\s*\b(АГ|ГС[ -]?ДЯ|ЗБ|НЯ)\b\s*$', '', ost).strip(' —-')
    return f'Приложение {nom}' + (f' — {ost}' if ost else '')


def istochnik_tekst(istochnik, otkogo, put):
    if istochnik == 'pochta':
        return 'из почты' + (f': {otkogo}' if otkogo and otkogo != 'мы' else ': наше письмо' if otkogo == 'мы' else '')
    if istochnik == 'telegram':
        m = re.search(r'Вложения / ([^/]+)', put or '')
        return 'из Telegram' + (f': {m.group(1).strip()}' if m else '')
    return ''


def razmetit(f):
    """f — словарь с полями imya, put (папки), rassh, istochnik, otkogo, arhiv. Возвращает разметку каркаса."""
    tip = opredelit_tip(f['imya'], f['put'], f['rassh'])
    z = zona(f['imya'], f['put'])
    out = {'tip': tip, 'zona': z, 'semya': klyuch_semi(tip, z, f['imya']),
           'nazvanie': chistoe_imya(f['imya']), 'otkuda': istochnik_tekst(f.get('istochnik'), f.get('otkogo'), f['put'])}
    if tip == 'Договоры':
        out['rol'] = rol_v_dogovore(f['imya'])
    return out


def vybrat_aktualnye(faily):
    """faily — список словарей с полями semya, data, arhiv, rassh. Ставит aktualno=1 крайней версии в семье.
    docx и pdf одной даты — один документ в двух форматах (форматы складываются в главный)."""
    semi = {}
    for f in faily:
        semi.setdefault(f['semya'], []).append(f)
    for sem in semi.values():
        zhivye = [f for f in sem if not f.get('arhiv')] or []
        for f in sem:
            f['aktualno'] = 0
            f['versiy'] = len(sem)
        if not zhivye:
            continue
        zhivye.sort(key=lambda f: (f['data'], {'docx': 3, 'doc': 2, 'xlsx': 3, 'pdf': 1}.get(f['rassh'], 0)), reverse=True)
        glavnyy = zhivye[0]
        glavnyy['aktualno'] = 1
        # тот же день — другие форматы того же документа
        glavnyy['formaty'] = sorted({f['rassh'] for f in zhivye if f['data'][:10] == glavnyy['data'][:10]})
    return semi


def popravka_dogovorov(faily, proekt_pole='p'):
    """Договоры: крайний пакет — тот, что лежит в папке проекта. Всё по той же зоне,
    что пришло раньше из почты и Telegram, — история (а не отдельные «актуальные» приложения).
    Вызывать после vybrat_aktualnye()."""
    paket = {}
    for f in faily:
        if (f.get('tip') == 'Договоры' and f.get('istochnik') == 'papka' and f.get('rol') == 'Договор' and not f.get('arhiv')
                and not est(nizh(f.get('put', '')), 'данные заказчика', 'как получено')):
            k = (f[proekt_pole], f.get('zona', ''))
            paket[k] = max(paket.get(k, ''), f['data'])
    # пакет проекта целиком (самый свежий по любой зоне) — для черновиков без зоны
    po_proektu = {}
    for (pr, z), d in paket.items():
        po_proektu[pr] = max(po_proektu.get(pr, ''), d)
    for f in faily:
        k = (f[proekt_pole], f.get('zona', ''))
        if not f.get('zona') and f[proekt_pole] in po_proektu and f.get('semya', '').endswith('|'):
            k = (f[proekt_pole], '*')
            paket[k] = po_proektu[f[proekt_pole]]
        prislano = f.get('istochnik') != 'papka' or est(nizh(f.get('put', '')), 'данные заказчика', 'как получено')
        if (f.get('tip') == 'Договоры' and prislano and k in paket
                and f['data'][:10] < paket[k][:10] and f.get('aktualno')):
            f['aktualno'] = 0
            f['zamenen_paketom'] = paket[k][:10]


# слова, которые есть почти в каждом названии проекта и ничего не различают
OBSHCHIE = {'раздоры', 'раздор', 'мебель', 'панели', 'олимпийский', 'олимпийск', 'двери', 'двер', 'архивуд', 'archiwood',
            'лигнум', 'проект', 'для', 'по', 'на', 'и', 'в', 'с', 'к', 'от', 'pdf', 'docx', 'xlsx', 'doc'}


def _slova(nazvanie):
    n = re.sub(r'[^а-яa-z0-9 ]', ' ', nizh(nazvanie))
    return {w[:6] for w in n.split() if len(w) > 2 and not w.isdigit() and w not in OBSHCHIE}


def skleit_pokhozhie(faily, proekt_pole='p', porog=0.5):
    """Версии одного документа часто называются чуть по-разному («цены», «с ценами»,
    «цены без коэффициента»). Внутри проекта, раздела и зоны склеиваем семьи
    с похожими названиями (доля общих слов ≥ porog). Договоры не трогаем — у них свои правила.
    Вызывать до vybrat_aktualnye()."""
    gruppy = {}
    for f in faily:
        if f.get('tip') in ('Договоры', 'Фото', 'Переписка'):
            continue
        gruppy.setdefault((f[proekt_pole], f['tip'], f.get('zona', '')), []).append(f)
    for spisok in gruppy.values():
        semi = {}
        for f in spisok:
            semi.setdefault(f['semya'], _slova(f['nazvanie']))
        klyuchi = list(semi)
        roditel = {k: k for k in klyuchi}

        def koren(k):
            while roditel[k] != k:
                roditel[k] = roditel[roditel[k]]
                k = roditel[k]
            return k
        for i, a in enumerate(klyuchi):
            for b in klyuchi[i + 1:]:
                sa, sb = semi[a], semi[b]
                if sa and sb and len(sa & sb) / len(sa | sb) >= porog:
                    roditel[koren(b)] = koren(a)
        for f in spisok:
            f['semya'] = koren(f['semya'])
