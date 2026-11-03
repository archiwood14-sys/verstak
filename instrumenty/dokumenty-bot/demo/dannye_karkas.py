"""Данные для демо по новому каркасу: метаданные Диска → проект (katalog.py) →
раздел, зона, семья версий, актуальность (karkas.py).

    python3 demo/dannye_karkas.py <all.json> <выход.json>
"""
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import karkas  # noqa: E402
import katalog as K  # noqa: E402

FOLD = 'application/vnd.google-apps.folder'
ROOT = '1OBmIJRrokxVVmA8fWk7dBx9gd1mjiYl3'

db = json.load(open(sys.argv[1]))
deti = defaultdict(list)
for x in db.values():
    deti[x['parentId']].append(x)


def obkhod(fid, put):
    for c in deti[fid]:
        p = put + [c['title']]
        if c['mimeType'] == FOLD:
            yield from obkhod(c['id'], p)
        else:
            yield c, p


korni = sorted(((k['put'].split('Проекты на Google Диске/', 1)[-1].split('/'), k) for k in K.N['korni']),
               key=lambda t: -len(t[0]))
lishnie = {K.nizhniy(x) for x in K.N.get('propuskat_papki', [])}
faily = []
for f, put in obkhod(ROOT, []):
    papki, imya = put[:-1], put[-1]
    koren = None
    for otn, k in korni:
        if papki[:len(otn)] == otn and not (set(k.get('krome', [])) & set(papki[len(otn):len(otn) + 1])):
            koren, chasti = k, papki[len(otn):]
            break
    if (not koren or K.propustit(imya) or any(K.nizhniy(p) in lishnie for p in papki)
            or f['mimeType'].startswith('application/vnd.google-apps') or imya.endswith('.md') and 'Почта' in papki):
        continue   # письма-.md — это тексты писем, их показываем через вложения
    data_p, otkogo, tema = K.razbor_pisma(chasti)
    pid = K.opredelit_proekt(koren, chasti, imya, '')
    rassh = imya.rsplit('.', 1)[-1].lower() if '.' in imya else ''
    z = {'imya': imya, 'put': ' / '.join(papki), 'rassh': rassh, 'istochnik': koren.get('istochnik', 'papka'),
         'otkogo': otkogo, 'arhiv': 1 if K.eto_arhiv(chasti, imya) else 0}
    z.update(karkas.razmetit(z, K.PROEKTY.get(pid, K.PROEKTY['obshchee'])[1].get('razrez')))
    z.update({'p': pid, 'd': (data_p or f.get('modifiedTime', ''))[:16], 's': int(f.get('fileSize') or 0),
              'u': f.get('viewUrl', ''), 'tema': tema,
              'v': 1 if koren.get('vnutrennee') or K.est_slovo(K.nizhniy(' / '.join(papki) + ' ' + imya), K.N.get('vnutrennee_slova', [])) else 0})
    z['data'] = z['d']
    z['semya'] = pid + '|' + z['semya']
    faily.append(z)

karkas.skleit_pokhozhie(faily)
karkas.vybrat_aktualnye(faily)
karkas.popravka_dogovorov(faily)
proekty = [{'id': p['id'], 'imya': p['imya'], 'razrez': p.get('razrez', {}).get('imya', ''),
           'znacheniya': [v['id'] for v in p.get('razrez', {}).get('znacheniya', [])]} for p in K.N['proekty']]
json.dump({'faily': faily, 'proekty': proekty, 'tipy': karkas.TIPY}, open(sys.argv[2], 'w'), ensure_ascii=False)
akt = sum(f['aktualno'] for f in faily)
print(f'{len(faily)} файлов → {akt} актуальных документов')
