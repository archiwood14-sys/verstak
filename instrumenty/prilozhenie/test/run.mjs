import pw from '/opt/node22/lib/node_modules/playwright/index.js';
import fs from 'fs';
const dir='/tmp/claude-0/-home-user-verstak/afac7431-1c44-5757-99db-0c717ff88dbb/scratchpad/prilozhenie';
const html=`<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><style>:root{color-scheme:light}body{margin:0;font:14px system-ui}img{max-width:100%}[hidden]{display:none!important}</style></head><body>`+fs.readFileSync(dir+'/index.html','utf8')+`</body></html>`;
fs.writeFileSync(dir+'/test/wrapped.html',html);
const shots=[['today','#today'],['portfolio','#portfolio'],['project','#project-raz_dveri'],['positions','#project-raz_dveri',"ptab:pos"],['docs','#project-olimp',"ptab:docs"],['money','#project-raz_dveri',"ptab:money"],['decisions','#decisions'],['inbox','#inbox'],['doc','#doc-0'],['search','#search',"search"],['compose','#compose',"compose"],['bot','#bot',"bot"]];
const b=await pw.chromium.launch();
const errs=[];
for(const [w,h,tag] of [[1440,900,'desktop'],[390,844,'mobile']]){
 const ctx=await b.newContext({viewport:{width:w,height:h},deviceScaleFactor:1});
 const pg=await ctx.newPage();
 await pg.route(/fonts\.(googleapis|gstatic)\.com/,r=>r.fulfill({status:200,body:'',contentType:'text/css'}));
 pg.on('console',m=>{if(m.type()==='error')errs.push(tag+': '+m.text());});
 pg.on('pageerror',e=>errs.push(tag+' pageerror: '+e.message));
 for(const [name,hash,act] of shots){
  await pg.goto('file://'+dir+'/test/wrapped.html'+hash);
  await pg.waitForTimeout(150);
  if(act==='ptab:pos'){await pg.click('[data-act=ptab][data-t=pos]');await pg.click('.pos-h >> nth=0');await pg.click('.pos-h >> nth=6');}
  if(act==='ptab:docs'){await pg.click('[data-act=ptab][data-t=docs]');await pg.click('[data-act=regsec][data-sec="Договоры"]');}
  if(act==='ptab:money'){await pg.click('[data-act=ptab][data-t=money]');}
  if(act==='search'){await pg.fill('#q','крайняя смета Раздоры');await pg.waitForTimeout(400);}
  if(act==='compose'){await pg.click('[data-act=cTpl][data-tpl=pay]');await pg.click('[data-act=cAns] >> nth=0');await pg.click('[data-act=cAns] >> nth=0');await pg.click('[data-act=cAns] >> nth=0');await pg.click('[data-act=cGen]');}
  if(act==='bot'){await pg.click('[data-act=botQ] >> nth=0');await pg.click('[data-act=botPhoto]');await pg.click('[data-act=botPick] >> nth=0');await pg.click('[data-act=botQ] >> nth=1');}
  await pg.waitForTimeout(150);
  const ov=await pg.evaluate(()=>({sw:document.documentElement.scrollWidth,cw:document.documentElement.clientWidth,wide:[...document.querySelectorAll('body *')].filter(e=>{const r=e.getBoundingClientRect();return r.right>document.documentElement.clientWidth+1&&r.width>0&&!e.closest('.tw,.board-w,.gw,.tg-quick,.tabs,.pal-l')}).slice(0,4).map(e=>e.tagName+'.'+e.className+' '+Math.round(e.getBoundingClientRect().right))}));
  if(ov.sw>ov.cw)errs.push(`${tag} ${name}: overflow ${ov.sw}>${ov.cw} ${ov.wide.join(' | ')}`);
  await pg.screenshot({path:`${dir}/shot-${tag}-${name}.png`,fullPage:tag==='desktop'?false:false});
 }
 // палитра
 await pg.goto('file://'+dir+'/test/wrapped.html#today');await pg.keyboard.press('Control+k');await pg.keyboard.type('договор АГ');await pg.waitForTimeout(200);
 await pg.screenshot({path:`${dir}/shot-${tag}-palette.png`});
 await pg.keyboard.press('Enter');await pg.waitForTimeout(200);
 // темная тема
 await pg.goto('file://'+dir+'/test/wrapped.html#portfolio');await pg.click('#side [data-act=theme], #mtop [data-act=theme] >> visible=true');await pg.waitForTimeout(100);
 await pg.screenshot({path:`${dir}/shot-${tag}-dark.png`});
 await pg.evaluate(()=>{try{localStorage.clear()}catch(e){}});
 await ctx.close();
}
await b.close();
console.log(errs.length?errs.join('\n'):'OK: no errors, no overflow');
