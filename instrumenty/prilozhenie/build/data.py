import json,re,sys
K=json.load(open(sys.argv[1]))
F=K['faily']
TIPY=K['tipy']
# map drugie zones to sub projects
SUB={'Плющиха':'plu','Озерки':'oze','Ильинка':'ili','Медное Озеро':'med'}
def pid(x):
    return x['p']
srcs=[];si={}
def S(s):
    s=re.sub(r',?\s*\+7[\d\s\-()]{9,}','',s or '')
    s=re.sub(r'\s*\(\s*\)','',s).strip()
    if s not in si: si[s]=len(srcs);srcs.append(s)
    return si[s]
fams={}
for x in F: fams.setdefault(x['semya'],[]).append(x)
docs=[]
def clean(n):
    n=re.sub(r'\(\s*\)','',n)
    n=re.sub(r',\s*\)',')',n)
    n=re.sub(r'\s+от\s+\(','(',n)
    n=re.sub(r'\s+на\s+\.\s*',' ',n)
    n=re.sub(r'\s+\.\s+\.',' .',n)
    n=re.sub(r'\s+\.\s+',' . ',n)
    n=re.sub(r'\s+(от|от года)\s*$','',n)
    n=re.sub(r'\s+—\s*$','',n)
    n=re.sub(r'\s{2,}',' ',n).strip()
    n=n.replace(' . ВНУТРЕННИЙ','. ВНУТРЕННИЙ').replace(' . ','. ')
    return n
def status(name,tip,rol):
    n=name.lower()
    if re.search(r'заменен|заменён|устарел|не нужна|не отправлял|не отправлять|\(отменен',n): return 'old'
    if 'пилот' in n: return 'review'
    if 'подписано' in n or 'фиксация согласованных' in n: return 'ok'
    if 'примечания подрядчика' in n or 'рецензируем' in n: return 'review'
    if 'коммерческое предложение' in n or n.startswith('кп '): return 'review'
    if 'внутренний' in n or 'наша редакция' in n or 'состояние на' in n: return 'draft'
    if tip in ('Производство и монтаж',) or 'задани' in n: return 'prod'
    if tip=='Чертежи конструктора': return 'review' if 'эскиз' in n else 'ok'
    if tip in ('Исходные данные заказчика','Фото','Материалы и каталоги','Встречи и решения','Счета и оплаты','Переписка'): return 'ok'
    if tip=='Договоры': return 'review' if not rol or rol=='Договор' else 'ok'
    return 'ok'
for sem,items in fams.items():
    items=sorted(items,key=lambda x:(x['d'],x['aktualno']))
    act=[x for x in items if x['aktualno']]
    a=act[-1] if act else items[-1]
    # group versions by minute
    vers=[];byd={}
    for x in items:
        key=x['d']
        if key in byd:
            v=byd[key]
            if x['rassh'] and x['rassh'] not in v[2].split(','): v[2]+=','+x['rassh']
            v[3]+=x.get('s',0) or 0
            if x['aktualno']: v[5]=1
            continue
        v=[x['d'][2:].replace('T',' '), x['imya'], x['rassh'] or '', x.get('s',0) or 0, S(x['otkuda']), 1 if x['aktualno'] else 0, x.get('tema','') or '']
        byd[key]=v;vers.append(v)
    # ensure actual last
    ai=[i for i,v in enumerate(vers) if v[5]]
    if ai:
        v=vers.pop(ai[-1]);vers.append(v)
        for w in vers[:-1]: w[5]=0
    else:
        vers[-1][5]=1
    name=clean(a['nazvanie'] or a['imya'])
    st=status(name,a['tip'],a.get('rol',''))
    docs.append({'p':pid(a),'t':TIPY.index(a['tip']),'z':a['zona'], 'r':a.get('rol','') or '', 'n':name,'st':st,'ar':1 if a.get('arhiv') else 0,'v':vers})
# sort by date desc
docs.sort(key=lambda d:d['v'][-1][0],reverse=True)
out={'nfiles':len(F),'tipy':TIPY,'src':srcs,'docs':docs,'razrez':{p['id']:{'r':p['razrez'],'z':p['znacheniya']} for p in K['proekty']}}
s=json.dumps(out,ensure_ascii=False,separators=(',',':'))
open(sys.argv[2],'w').write(s)
print(len(docs),len(s),sum(len(d['v']) for d in docs))
from collections import Counter
print(Counter(d['p'] for d in docs)); print(Counter(d['st'] for d in docs))
