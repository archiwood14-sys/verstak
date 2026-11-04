import json
css=open('css_old.txt').read()
extra=open('extra.css').read()
css=css.replace('/* ---------- адаптив ---------- */',extra+'\n/* ---------- адаптив ---------- */')
head='''<title>АРХИВУД Проекты</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Cormorant:wght@500;600;700&display=swap">
'''
data=open('data.json').read().replace('</','<\\/')
body=open('body.html').read().replace('__DATA__',data)
open('../index.html','w').write(head+css+body)
print(len(head+css+body))
