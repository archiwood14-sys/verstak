"""Данные для демо-страницы бота: метаданные файлов Google Диска (выгрузка
инвентаризации) прогоняются через те же правила, что и katalog.py.
Содержимое файлов не читается — только имена, папки, даты, размеры.

    python3 demo/dannye_iz_diska.py <all.json> <выход.json>
"""
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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


# корни из настроек сопоставляем по имени папки
korni = []
for k in K.N['korni']:
    otn = k['put'].split('Проекты на Google Диске/', 1)[-1].split('/')
    korni.append((otn, k))
korni.sort(key=lambda t: -len(t[0]))   # самый длинный путь — первым

zapisi, vidim = [], set()
for f, put in obkhod(ROOT, []):
    papki, imya = put[:-1], put[-1]
    koren = None
    for otn, k in korni:
        if papki[:len(otn)] == otn and not (set(k.get('krome', [])) & set(papki[len(otn):len(otn) + 1])):
            koren, chasti = k, papki[len(otn):]
            break
    if not koren or K.propustit(imya) or any(K.nizhniy(p) in {K.nizhniy(x) for x in K.N.get('propuskat_papki', [])} for p in papki):
        continue
    if f['mimeType'].startswith('application/vnd.google-apps'):
        continue
    data_p, otkogo, tema = K.razbor_pisma(chasti)
    pid = K.opredelit_proekt(koren, chasti, imya, '')
    p_por, p = K.PROEKTY.get(pid, K.PROEKTY['obshchee'])
    r_por, razdel = K.opredelit_razdel(koren, chasti, imya)
    vnutr = 1 if koren.get('vnutrennee') or K.est_slovo(K.nizhniy(' / '.join([os.path.basename(koren['put'])] + chasti) + ' ' + imya),
                                                         K.N.get('vnutrennee_slova', [])) else 0
    razmer = int(f.get('fileSize') or 0)
    klyuch = (pid, vnutr, imya, razmer)
    dubl = klyuch in vidim
    vidim.add(klyuch)
    zapisi.append({
        'i': imya, 'p': pid, 'r': razdel, 'v': vnutr, 'd': (data_p or f.get('modifiedTime', ''))[:16],
        'o': otkogo, 's': razmer, 'm': ' / '.join(papki), 'u': f.get('viewUrl', ''), 'x': 1 if dubl else 0,
        't': tema,
    })

proekty = [{'id': p['id'], 'imya': p['imya']} for p in K.N['proekty']]
razdely = [r['imya'] for r in K.N['razdely']] + ['Архив']
json.dump({'faily': zapisi, 'proekty': proekty, 'razdely': razdely}, open(sys.argv[2], 'w'), ensure_ascii=False)
print(len(zapisi), 'файлов,', sum(z['x'] for z in zapisi), 'дублей')
