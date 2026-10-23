// Сборщик сайта Archiwood. Без зависимостей, нужен только Node.js 18+.
//
//   node sayt/build.mjs            → готовый сайт в sayt/dist (для хостинга)
//   node sayt/build.mjs --preview  → предпросмотр в sayt/preview (одна ширина фото, ссылки на index.html)
//
// Тексты и проекты — в content/site.mjs, фото — в foto/ (см. FOTO.md).

import { createHash } from 'node:crypto';
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { crafts, principles, process as steps, projects, reviews, site } from './content/site.mjs';

const ROOT = dirname(fileURLToPath(import.meta.url));
const PREVIEW = process.argv.includes('--preview');
const OUT = join(ROOT, PREVIEW ? 'preview' : 'dist');
const TODAY = new Date().toISOString().slice(0, 10);
const YEAR = TODAY.slice(0, 4);

const manifestPath = join(ROOT, 'static/img/manifest.json');
const manifest = existsSync(manifestPath) ? JSON.parse(readFileSync(manifestPath, 'utf8')) : {};
const usedImages = new Set();

/* ---------------- Текст ---------------- */

const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
// Неразрывный пробел после коротких предлогов и союзов, чтобы они не висели в конце строки.
const typo = (s) => esc(s).replace(/(^|[\s(«])(в|во|и|с|со|на|по|для|к|ко|о|об|а|от|до|из|не|за|у|без|под|при|т\. к\.)\s/gi, '$1$2 ');

/* ---------------- Адреса ---------------- */

// Каждая страница знает свою глубину, все ссылки относительные — сайт работает с любого адреса.
let depth = 0;
let absolute = false;
const prefix = () => (absolute ? '/' : '../'.repeat(depth));
const href = (path, extra = '') => (prefix() + path + (PREVIEW ? 'index.html' : '') || './') + extra;
const asset = (path) => prefix() + path;
const versions = {};
const inline = { css: '', js: '' };
const versioned = (path) => `${asset(path)}?v=${versions[path]}`;

/* ---------------- Фото ---------------- */

const has = (key) => Boolean(key && manifest[key]);
const widthsOf = (key) => {
  const w = manifest[key].widths;
  if (!PREVIEW) return w;
  const fit = w.filter((x) => x <= 1600);
  return [fit.length ? fit[fit.length - 1] : w[0]];
};
const fileOf = (key, w) => {
  usedImages.add(`${key}-${w}.webp`);
  return asset(`img/${key}-${w}.webp`);
};
const srcset = (key) => widthsOf(key).map((w) => `${fileOf(key, w)} ${w}w`).join(', ');
const biggest = (key) => { const w = widthsOf(key); return fileOf(key, w[w.length - 1]); };

// <img> с размерами (страница не прыгает при загрузке) и набором ширин.
function img(key, { alt = '', sizes = '100vw', priority = false } = {}) {
  if (!has(key)) return '';
  const m = manifest[key];
  const ws = widthsOf(key);
  const load = priority ? ' fetchpriority="high"' : ' loading="lazy"';
  return `<img src="${fileOf(key, ws[Math.min(1, ws.length - 1)])}" srcset="${srcset(key)}" sizes="${sizes}" width="${m.w}" height="${m.h}" alt="${esc(alt)}" decoding="async"${load}>`;
}
const photo = (key, opts = {}, cls = '') => `<figure class="photo${cls ? ' ' + cls : ''}">${img(key, opts)}</figure>`;

const galleryKeys = (id) => {
  const pre = `proekty/${id}/galereya/`;
  return Object.keys(manifest).filter((k) => k.startsWith(pre)).sort();
};
const hasPage = (p) => galleryKeys(p.id).length > 0;
const withPages = projects.filter(hasPage);
const coverOf = (p) => (has(p.cover) ? p.cover : galleryKeys(p.id)[0]);
const STATUS = { work: 'В производстве', done: 'Реализован', soon: 'В реализации' };

/* ---------------- Значки ---------------- */

const icon = {
  prev: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 19l-7-7 7-7"/></svg>',
  next: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 5l7 7-7 7"/></svg>',
  close: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  tg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.894 8.221l-1.97 9.28c-.145.658-.537.818-1.084.508l-3-2.21-1.446 1.394c-.14.18-.357.223-.548.223l.188-2.85 5.18-4.686c.223-.195-.054-.285-.346-.09l-6.4 4.024-2.76-.86c-.6-.185-.615-.595.125-.89l10.736-4.14c.498-.22 1.006.115.825.901z"/></svg>',
  wa: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12.01 2.002c-5.524 0-10.007 4.48-10.007 10.004 0 1.758.46 3.414 1.252 4.881L2 21.999l5.297-1.192c1.425.736 3.018 1.127 4.713 1.127 5.523 0 10.005-4.481 10.005-10.005C22.015 6.482 17.533 2.002 12.01 2.002zm4.359 14.394c-.19.54-.928 1.026-1.39 1.1-.409.062-1.025.109-2.923-.676-2.348-.925-3.882-3.376-4.004-3.535-.12-.158-.956-1.282-.956-2.443 0-1.161.605-1.734.825-1.97.221-.238.513-.3.676-.3.161 0 .324-.002.464-.002.164 0 .385-.062.605.467.226.541.745 1.83.81 1.961.066.133.111.286.035.438-.076.152-.115.247-.229.382-.113.132-.238.29-.336.381-.11.1-.225.213-.099.431.126.219.561.928 1.203 1.503.826.738 1.517.969 1.737 1.073.22.105.348.087.48-.063.131-.151.564-.658.718-.884.152-.226.305-.188.536-.1.23.087 1.455.688 1.705.812.25.125.415.188.476.29.062.103.062.595-.128 1.133z"/></svg>',
};
const logo = (cls = '', alt = 'Archiwood', light = false) =>
  `<img src="${asset(light ? 'logo-light.png' : 'logo.png')}" width="484" height="240" alt="${esc(alt)}"${cls ? ` class="${cls}"` : ''}>`;

/* ---------------- Общие части ---------------- */

const NAV = [
  ['', 'Главная', 'Дом'],
  ['proekty/', 'Проекты', `${withPages.length + projects.filter((p) => !hasPage(p)).length} объектов`],
  ['masterskaya/', 'Мастерская', 'О нас'],
];

function header() {
  return `<header class="hdr">
  <button class="hdr__menu" type="button" data-menu-open aria-controls="menu" aria-expanded="false"><i></i><span>Меню</span></button>
  <a class="hdr__logo" href="${href('')}" aria-label="Archiwood — на главную">${logo('', '')}</a>
  <div class="hdr__right"><a class="hide-sm" href="tel:${site.phoneHref}">${site.phone}</a><a href="#kontakty">Связаться</a></div>
</header>`;
}

function menu(current) {
  const links = NAV.map(([p, t, note]) => `<a href="${href(p)}"${p === current ? ' aria-current="page"' : ''}>${t}<small>${note}</small></a>`).join('\n      ');
  return `<div class="menu" id="menu" role="dialog" aria-modal="true" aria-label="Меню сайта" aria-hidden="true">
  <div class="menu__col">
    <div class="menu__top">${logo()}<button class="round" type="button" data-menu-close aria-label="Закрыть меню">${icon.close}</button></div>
    <nav class="menu__nav" aria-label="Разделы сайта">
      ${links}
      <a href="#kontakty" data-menu-close>Контакты<small>Шоурум</small></a>
    </nav>
    <div class="menu__foot">
      <a href="tel:${site.phoneHref}">${site.phone}</a>
      <a href="mailto:${site.email}">${site.email}</a>
      <span>${typo(site.address)}</span>
    </div>
  </div>
  ${photo(site.photos.menu, { sizes: '50vw' }, 'menu__photo')}
</div>`;
}

function contact() {
  return `<section class="contact" id="kontakty" aria-labelledby="kontakty-h">
  ${photo(site.photos.contact, { alt: 'Кабинет с панелями из ореха', sizes: '(max-width: 860px) 100vw, 50vw' })}
  <div class="contact__body">
    <p class="eyebrow rv">Связаться</p>
    <h2 id="kontakty-h" class="h2 rv d1">Обсудим ваш проект</h2>
    <p class="text rv d1">${typo('Пришлите дизайн-проект или чертежи — подготовим конструкторские решения, образцы отделок и расчет.')}</p>
    <div class="contact__list rv d2">
      <a href="tel:${site.phoneHref}">${site.phone}</a>
      <a href="mailto:${site.email}">${site.email}</a>
      <a href="${site.mapUrl}" target="_blank" rel="noopener">${typo(site.address)}</a>
    </div>
    <p class="contact__note rv d2">${typo(site.addressNote)}</p>
    <div class="contact__social rv d3">
      <a class="round" href="${site.telegram}" target="_blank" rel="noopener" aria-label="Написать в Telegram">${icon.tg}</a>
      <a class="round" href="${site.whatsapp}" target="_blank" rel="noopener" aria-label="Написать в WhatsApp">${icon.wa}</a>
    </div>
  </div>
</section>
<footer class="foot">
  ${logo('', 'Archiwood, Санкт-Петербург')}
  <nav aria-label="Разделы">${NAV.map(([p, t]) => `<a href="${href(p)}">${t}</a>`).join('')}<a href="#kontakty">Контакты</a></nav>
  <small>© ${YEAR} Archiwood · Столярное производство и конструкторское бюро · Санкт-Петербург</small>
</footer>`;
}

function metrika() {
  if (!site.metrika) return '';
  const id = String(site.metrika).replace(/\D/g, '');
  return `<script>(function(m,e,t,r,i,k,a){m[i]=m[i]||function(){(m[i].a=m[i].a||[]).push(arguments)};m[i].l=1*new Date();k=e.createElement(t),a=e.getElementsByTagName(t)[0],k.async=1,k.src=r,a.parentNode.insertBefore(k,a)})(window,document,"script","https://mc.yandex.ru/metrika/tag.js","ym");ym(${id},"init",{clickmap:true,trackLinks:true,accurateTrackBounce:true,webvisor:true});</script>
<noscript><div><img src="https://mc.yandex.ru/watch/${id}" style="position:absolute;left:-9999px" alt=""></div></noscript>`;
}

// Страница целиком. В предпросмотре главная пишется без <html>/<head> (их добавляет площадка).
function layout({ path, page, title, description, content, ogImage, jsonld, fragment = false }) {
  const canonical = site.url + '/' + path;
  const og = has(ogImage) ? `${site.url}/img/${ogImage}-${manifest[ogImage].widths.slice(-1)[0]}.webp` : '';
  const headInner = `<title>${esc(title)}</title>
<meta name="description" content="${esc(description)}">
<link rel="canonical" href="${canonical}">
<meta property="og:type" content="website">
<meta property="og:locale" content="ru_RU">
<meta property="og:site_name" content="Archiwood">
<meta property="og:title" content="${esc(title)}">
<meta property="og:description" content="${esc(description)}">
<meta property="og:url" content="${canonical}">
${og ? `<meta property="og:image" content="${og}">\n` : ''}<meta name="theme-color" content="#faf6f0">
<link rel="icon" href="${asset('favicon.png')}" type="image/png">
<link rel="apple-touch-icon" href="${asset('favicon.png')}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Jost:wght@400;500&family=Prata&display=swap">
${PREVIEW ? `<style>${inline.css}</style>` : `<link rel="stylesheet" href="${versioned('assets/style.css')}">`}
<script>document.documentElement.classList.add('js')</script>
${jsonld ? `<script type="application/ld+json">${JSON.stringify(jsonld)}</script>\n` : ''}${metrika()}`;

  const bodyInner = `<a class="sr-only" href="#main">К содержимому</a>
${header()}
${menu(path)}
<main id="main" data-page="${page}">
${content}
</main>
${contact()}
<div class="toast" role="status" aria-live="polite"></div>
${PREVIEW ? `<script>${inline.js}</script>` : `<script src="${versioned('assets/app.js')}" defer></script>`}`;

  if (fragment) return `${headInner}\n${bodyInner}\n`;
  return `<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
${headInner}
</head>
<body>
${bodyInner}
</body>
</html>
`;
}

/* ---------------- Блоки ---------------- */

function stepsBlock() {
  return `<section class="sec wrap" aria-labelledby="steps-h">
  <div class="sec-head"><div class="sec-head__title"><p class="eyebrow">Как мы работаем</p><h2 id="steps-h" class="h2">От идеи до монтажа</h2></div></div>
  <ol class="steps">
    ${steps.map((s, k) => `<li class="rv${k % 3 ? ' d' + (k % 3) : ''}"><span class="steps__n">${String(k + 1).padStart(2, '0')}</span><h3 class="h3">${typo(s.title)}</h3><p class="text">${typo(s.text)}</p></li>`).join('\n    ')}
  </ol>
</section>`;
}

function featureBlock(p, k) {
  const keys = galleryKeys(p.id);
  const second = keys.find((x) => x !== coverOf(p) && !Object.values(site.photos).flat().includes(x)) || keys[1];
  return `<a class="feature${k % 2 ? ' feature--rev' : ''}" href="${href(`proekty/${p.id}/`)}">
    <div class="feature__media rv">${photo(coverOf(p), { alt: p.title, sizes: '(max-width: 860px) 60vw, 34vw' })}${photo(second, { alt: '', sizes: '(max-width: 860px) 40vw, 24vw' })}</div>
    <div class="feature__body rv d1">
      <span class="tag">${STATUS[p.status]}</span>
      <h3 class="h2">${typo(p.title)}</h3>
      <p class="text">${typo(p.desc)}</p>
      <span class="link">Смотреть проект · ${keys.length} кадров</span>
    </div>
  </a>`;
}

function indexBlock() {
  const groups = [
    ['Реализованные', projects.filter((p) => p.status === 'done')],
    ['В реализации', projects.filter((p) => p.status === 'soon')],
  ];
  return groups.map(([name, list]) => `<div class="index__group">
    <div class="index__label"><h3 class="eyebrow">${name}</h3><span>${list.length}</span></div>
    ${list.map((p) => {
      const inner = `<span class="h3">${typo(p.title)}</span><span>${esc(p.kind)}</span><span>${esc(p.place || '')}</span><em>${hasPage(p) ? 'Смотреть' : p.status === 'done' ? 'Фото скоро' : 'В работе'}</em>`;
      return hasPage(p) ? `<a class="index__row" href="${href(`proekty/${p.id}/`)}">${inner}</a>` : `<div class="index__row">${inner}</div>`;
    }).join('\n    ')}
  </div>`).join('\n  ');
}

/* ---------------- Страницы ---------------- */

function pageHome() {
  const quotes = reviews.map((r) => `<blockquote class="quote"><p>«${typo(r.text[0])}»</p><cite>${typo(r.author)}</cite></blockquote>`).join('\n        ');
  const content = `<div class="hero-wrap">
  <div class="hero">
    ${site.photos.hero.map((k, n) => photo(k, { alt: n === 0 ? 'Библиотека и гостиная с панелями из ореха' : '', sizes: '(max-width: 860px) 84vw, 33vw', priority: n < 2 })).join('\n    ')}
  </div>
  <div class="hero__box">
    <p class="eyebrow">Мастерская в Санкт-Петербурге</p>
    <h1>${typo('Архитектурная мебель и интерьеры из дерева')}</h1>
    <a class="link" href="${href('proekty/')}">Проекты</a>
  </div>
</div>

<section class="statement" aria-labelledby="st-h">
  <p class="eyebrow rv">Archiwood</p>
  <h2 id="st-h" class="h2 rv d1">${typo(site.tagline)}</h2>
  <p class="lead rv d2">${typo('Мы объединяем возможности технологичного производства с вниманием мебельного ателье. Подключаемся на этапе идеи, разрабатываем конструкторские решения для сложных узлов и отвечаем за результат — от документации до монтажа.')}</p>
</section>

<section class="sec" aria-labelledby="craft-h" style="padding-top:0">
  <div class="wrap"><div class="sec-head">
    <div class="sec-head__title"><p class="eyebrow">Что мы делаем</p><h2 id="craft-h" class="h2">Ремесло в каждой комнате</h2></div>
    <div class="arrows"><button class="round" type="button" data-rail-prev="crafts" aria-label="Назад">${icon.prev}</button><button class="round" type="button" data-rail-next="crafts" aria-label="Вперед">${icon.next}</button></div>
  </div></div>
  <div class="rail" id="crafts" data-rail>
    ${crafts.map((c) => `<article class="craft">${photo(c.photo, { alt: c.title, sizes: '(max-width: 860px) 70vw, 26vw' })}<h3 class="h3">${typo(c.title)}</h3><p class="text">${typo(c.text)}</p></article>`).join('\n    ')}
  </div>
</section>

<section class="sec wrap" aria-labelledby="now-h" style="padding-top:0">
  <div class="sec-head">
    <div class="sec-head__title"><p class="eyebrow">Сейчас в производстве</p><h2 id="now-h" class="h2">Объекты этого сезона</h2></div>
    <a class="link" href="${href('proekty/')}">Все проекты</a>
  </div>
  ${projects.filter((p) => p.status === 'work' && hasPage(p)).map(featureBlock).join('\n  ')}
</section>

<section class="box" aria-labelledby="box-h">
  <div class="wrap box-split">
    <div><p class="eyebrow">Главное обещание</p><h2 id="box-h" class="h2 h2--sm">${typo(site.promise)}</h2></div>
    <div><p class="lead">${typo('Собственное производство и конструкторское бюро: прототипы, образцы отделок и контроль каждого узла до выезда на объект.')}</p><a class="btn btn--line" href="${href('masterskaya/')}">О мастерской</a></div>
  </div>
</section>

${stepsBlock()}

<section class="sec wrap" aria-labelledby="idx-h" style="padding-top:0">
  <div class="sec-head"><div class="sec-head__title"><p class="eyebrow">Портфолио</p><h2 id="idx-h" class="h2">Частные резиденции, квартиры и рестораны</h2></div><a class="link" href="${href('proekty/')}">Все проекты</a></div>
  ${indexBlock()}
</section>

<section class="box" data-slider aria-roledescription="карусель" aria-label="Отзывы">
  <div class="wrap quotes">
    <div class="quotes__aside">
      <p class="eyebrow">Отзывы архитекторов и заказчиков</p>
      <p class="quotes__count" data-count></p>
      <div class="arrows"><button class="round" type="button" data-prev aria-label="Предыдущий отзыв">${icon.prev}</button><button class="round" type="button" data-next aria-label="Следующий отзыв">${icon.next}</button></div>
    </div>
    <div class="track-fade" data-track aria-live="polite">
        ${quotes}
    </div>
  </div>
</section>`;

  return layout({
    path: '', page: 'glavnaya', fragment: PREVIEW,
    title: PREVIEW ? 'Сайт Archiwood' : 'Archiwood — архитектурная мебель и столярные интерьеры в Санкт-Петербурге',
    description: site.description,
    ogImage: site.photos.hero[0],
    jsonld: {
      '@context': 'https://schema.org',
      '@type': 'HomeAndConstructionBusiness',
      name: 'Archiwood',
      description: site.description,
      url: site.url + '/',
      logo: site.url + '/logo.png',
      telephone: site.phoneHref,
      email: site.email,
      address: { '@type': 'PostalAddress', streetAddress: '3-я линия В.О., д. 6', addressLocality: 'Санкт-Петербург', addressCountry: 'RU' },
      sameAs: [site.telegram],
    },
    content,
  });
}

function pageWorkshop() {
  const [a, b] = site.photos.about;
  const content = `<div class="wrap">
  <header class="page-intro">
    <p class="eyebrow">Мастерская</p>
    <h1 class="h1">${typo('Технологичное производство и внимание мебельного ателье')}</h1>
    <p class="lead">${typo('Не просто работаем по чертежам: подключаемся на этапе идеи, разрабатываем решения для сложных узлов и берем на себя ответственность за реализацию от документации до монтажа.')}</p>
  </header>
</div>
<div class="diptych">${photo(a, { alt: 'Гостиная с панелями из ореха', sizes: '50vw' })}${photo(b, { alt: 'Спальня с мебелью из ореха', sizes: '50vw' })}</div>

<section class="sec wrap" aria-labelledby="pr-h">
  <div class="sec-head"><div class="sec-head__title"><p class="eyebrow">Принципы</p><h2 id="pr-h" class="h2">Как мы думаем о мебели</h2></div></div>
  <ul class="principles">
    ${principles.map((p, k) => `<li class="rv${k % 2 ? ' d1' : ''}"><h3 class="h3">${typo(p.title)}</h3><p class="text">${typo(p.text)}</p></li>`).join('\n    ')}
  </ul>
</section>

<section class="box" aria-labelledby="box-h">
  <div class="wrap box-split">
    <div><p class="eyebrow">Главное обещание</p><h2 id="box-h" class="h2 h2--sm">${typo(site.promise)}</h2></div>
    <div><p class="lead">${typo('Мы производим кухни, гардеробные, мебель, паркет, двери и панели, добиваясь совпадения оттенков и фактур во всем интерьере.')}</p><a class="btn btn--line" href="${href('proekty/')}">Смотреть проекты</a></div>
  </div>
</section>

${stepsBlock()}`;
  return layout({
    path: 'masterskaya/', page: 'masterskaya',
    title: 'Мастерская Archiwood — производство и конструкторское бюро',
    description: 'Archiwood объединяет технологичное производство и внимание мебельного ателье: прототипы и тестирование узлов, своя конструкторская служба, работа с деревом от отбора шпона до монтажа.',
    ogImage: a,
    content,
  });
}

function pageProjects() {
  const content = `<div class="wrap">
  <header class="page-intro">
    <p class="eyebrow">Проекты</p>
    <h1 class="h1">${typo('Интерьеры, сделанные руками мастерской')}</h1>
    <p class="lead">${typo('Частные резиденции, квартиры, рестораны и жилые комплексы в Санкт-Петербурге, Москве и Дубае.')}</p>
  </header>
  <section class="sec" style="padding-top:0" aria-label="Объекты в производстве">
    ${projects.filter((p) => p.status === 'work' && hasPage(p)).map(featureBlock).join('\n    ')}
  </section>
  <section class="sec" style="padding-top:0" aria-labelledby="idx-h">
    <h2 id="idx-h" class="sr-only">Все объекты</h2>
    ${indexBlock()}
  </section>
</div>`;
  return layout({
    path: 'proekty/', page: 'proekty',
    title: 'Проекты Archiwood — мебель, панели и столярные интерьеры',
    description: 'Портфолио Archiwood: частные резиденции, квартиры, рестораны и жилые комплексы. Стеновые панели, корпусная мебель, двери и перегородки.',
    ogImage: withPages[0] && coverOf(withPages[0]),
    content,
  });
}

function pageProject(p, k) {
  const next = withPages[(k + 1) % withPages.length];
  const keys = galleryKeys(p.id);
  const gallery = keys.map((key, n) =>
    `<a class="photo" href="${biggest(key)}" data-lb>${img(key, { alt: `${p.title} — кадр ${n + 1}`, sizes: '(max-width: 860px) 50vw, 33vw' })}</a>`
  ).join('\n  ');
  const content = `<div class="wrap">
  <header class="proj-head">
    <div>
      <nav class="crumbs" aria-label="Вы здесь"><a href="${href('')}">Главная</a><span>/</span><a href="${href('proekty/')}">Проекты</a></nav>
      <h1 class="h1">${typo(p.title)}</h1>
      <p class="lead">${typo(p.desc)}</p>
    </div>
    <div>
      <dl class="facts">
        <div><dt>Объект</dt><dd>${esc(p.kind)}${p.place ? ', ' + esc(p.place) : ''}</dd></div>
        <div><dt>Статус</dt><dd>${STATUS[p.status]}</dd></div>
        <div><dt>Кадров</dt><dd>${keys.length}</dd></div>
      </dl>
      ${p.status === 'work' ? `<p class="note">${typo('Визуализации дизайн-проекта. Фотографии готового интерьера появятся после съемки.')}</p>` : ''}
    </div>
  </header>
</div>
<div class="gallery">
  ${gallery}
</div>
${next && next.id !== p.id ? `<a class="next" href="${href(`proekty/${next.id}/`)}"><span class="eyebrow">Следующий проект</span><span class="h2">${typo(next.title)}</span></a>` : ''}`;
  return layout({
    path: `proekty/${p.id}/`, page: 'proekt',
    title: `${p.title} — проект Archiwood`,
    description: p.desc,
    ogImage: coverOf(p),
    jsonld: {
      '@context': 'https://schema.org',
      '@type': 'BreadcrumbList',
      itemListElement: [
        { '@type': 'ListItem', position: 1, name: 'Главная', item: site.url + '/' },
        { '@type': 'ListItem', position: 2, name: 'Проекты', item: site.url + '/proekty/' },
        { '@type': 'ListItem', position: 3, name: p.title, item: `${site.url}/proekty/${p.id}/` },
      ],
    },
    content,
  });
}

function page404() {
  return layout({
    path: '404.html', page: '404',
    title: 'Страница не найдена — Archiwood',
    description: 'Такой страницы нет на сайте Archiwood.',
    content: `<div class="wrap"><header class="page-intro" style="min-height:50svh;align-content:center">
  <p class="eyebrow">Ошибка 404</p>
  <h1 class="h1">Такой страницы нет</h1>
  <p class="lead">Возможно, адрес изменился после переезда сайта.</p>
  <a class="btn btn--copper" href="${href('')}">На главную</a>
</header></div>`,
  });
}

/* ---------------- Список фото (FOTO.md) ---------------- */

function writeFotoList() {
  let md = `# Фотографии для сайта

Файл собирается автоматически (\`node sayt/build.mjs\`).

**Как добавить фото.** Положите файл в папку \`sayt/foto/\` по нужному пути (.jpg, .jpeg, .png или .webp), затем:

\`\`\`
python3 sayt/tools/foto.py && node sayt/build.mjs
\`\`\`

Фото уменьшится и сожмется в WebP в нескольких размерах. Присылайте исходники в максимальном качестве, длинная сторона от 2400 px.

**Галерея проекта** — папка \`sayt/foto/proekty/<проект>/galereya/\`. Сколько файлов положите, столько кадров будет на странице проекта, по порядку имен. Как только в папке появляется хотя бы одно фото, у проекта появляется своя страница.

## Проекты

| Проект | Папка | Кадров | Страница |
|---|---|---|---|
`;
  projects.forEach((p) => {
    const n = galleryKeys(p.id).length;
    md += `| ${p.title} | \`foto/proekty/${p.id}/galereya/\` | ${n} | ${n ? '✅ есть' : p.status === 'done' ? '🔴 нужны фото' : '⚪ после съемки'} |\n`;
  });
  md += `
## Общие места сайта

Кадры для первого экрана, меню, контактов и страницы «Мастерская» задаются в \`content/site.mjs\` → \`site.photos\`, для раздела «Что мы делаем» — в \`crafts\`. Сейчас там стоят визуализации Плющихи и Ильинки.
`;
  writeFileSync(join(ROOT, 'FOTO.md'), md);
}

/* ---------------- Сборка ---------------- */

function minifyCss(css) {
  return css.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\s+/g, ' ').replace(/\s*([{}:;,>])\s*/g, '$1').replace(/;}/g, '}').trim();
}

function write(rel, html) {
  const file = join(OUT, rel);
  mkdirSync(dirname(file), { recursive: true });
  writeFileSync(file, html);
}

function build() {
  writeFotoList();
  rmSync(OUT, { recursive: true, force: true });
  mkdirSync(join(OUT, 'assets'), { recursive: true });

  const css = minifyCss(readFileSync(join(ROOT, 'src/style.css'), 'utf8'));
  const js = readFileSync(join(ROOT, 'src/app.js'), 'utf8');
  versions['assets/style.css'] = createHash('sha1').update(css).digest('hex').slice(0, 8);
  versions['assets/app.js'] = createHash('sha1').update(js).digest('hex').slice(0, 8);
  // В предпросмотре площадка разрешает только встроенные стили и скрипты
  inline.css = css;
  inline.js = js.replace(/<\/script/g, '<\\/script');
  if (!PREVIEW) {
    writeFileSync(join(OUT, 'assets/style.css'), css);
    writeFileSync(join(OUT, 'assets/app.js'), js);
  }
  for (const f of ['logo.png', 'logo-light.png', 'favicon.png']) cpSync(join(ROOT, 'static', f), join(OUT, f));

  const pages = [];
  depth = 0; write('index.html', pageHome()); pages.push('');
  depth = 1; write('masterskaya/index.html', pageWorkshop()); pages.push('masterskaya/');
  depth = 1; write('proekty/index.html', pageProjects()); pages.push('proekty/');
  withPages.forEach((p, k) => { depth = 2; write(`proekty/${p.id}/index.html`, pageProject(p, k)); pages.push(`proekty/${p.id}/`); });
  if (!PREVIEW) { depth = 0; absolute = true; write('404.html', page404()); absolute = false; }

  for (const f of usedImages) {
    mkdirSync(dirname(join(OUT, 'img', f)), { recursive: true });
    cpSync(join(ROOT, 'static/img', f), join(OUT, 'img', f));
  }

  if (!PREVIEW) {
    write('sitemap.xml', `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${pages.map((p) => `  <url><loc>${site.url}/${p}</loc><lastmod>${TODAY}</lastmod></url>`).join('\n')}
</urlset>
`);
    write('robots.txt', `User-agent: *\nAllow: /\n\nSitemap: ${site.url}/sitemap.xml\n`);
    // Старые адреса Тильды → новые (Cloudflare Pages)
    write('_redirects', `/2 /masterskaya/ 301\n/2/ /masterskaya/ 301\n/3 /proekty/ 301\n/3/ /proekty/ 301\n/o-kompanii/ /masterskaya/ 301\n`);
    write('_headers', `/assets/*\n  Cache-Control: public, max-age=31536000, immutable\n/img/*\n  Cache-Control: public, max-age=2592000\n/*\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: strict-origin-when-cross-origin\n`);
  }

  console.log(`Готово: ${OUT} — страниц ${pages.length}, фото ${usedImages.size}`);
}

build();
