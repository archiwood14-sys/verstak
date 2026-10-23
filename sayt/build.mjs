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
import { featured, principles, projects, reviews, site } from './content/site.mjs';

const ROOT = dirname(fileURLToPath(import.meta.url));
const PREVIEW = process.argv.includes('--preview');
const OUT = join(ROOT, PREVIEW ? 'preview' : 'dist');
const TODAY = new Date().toISOString().slice(0, 10);
const YEAR = TODAY.slice(0, 4);

const manifestPath = join(ROOT, 'static/img/manifest.json');
const manifest = existsSync(manifestPath) ? JSON.parse(readFileSync(manifestPath, 'utf8')) : {};
const usedImages = new Set();
const done = projects.filter((p) => p.status === 'done');
const byId = Object.fromEntries(projects.map((p) => [p.id, p]));

/* ---------------- Текст ---------------- */

const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
// Неразрывный пробел после коротких предлогов и союзов, чтобы они не висели в конце строки.
const typo = (s) => esc(s).replace(/(^|[\s(«])(в|во|и|с|со|на|по|для|к|ко|о|об|а|от|до|из|не|за|у|без|под|при|т\. к\.)\s/gi, '$1$2 ');

/* ---------------- Адреса ---------------- */

// Каждая страница знает свою глубину, все ссылки относительные — сайт работает с любого адреса.
let depth = 0;
let absolute = false;
const prefix = () => (absolute ? '/' : '../'.repeat(depth));
const href = (path, extra = '') => {
  const p = path + (PREVIEW ? 'index.html' : '');
  const full = prefix() + p;
  return (full || './') + extra;
};
const asset = (path) => prefix() + path;
const versions = {};
const inline = { css: '', js: '' };
const versioned = (path) => `${asset(path)}?v=${versions[path]}`;

/* ---------------- Фото ---------------- */

const has = (key) => Boolean(manifest[key]);
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

// <img> с размерами (чтобы страница не прыгала при загрузке) и набором ширин.
// lazy: 'native' — loading=lazy; 'slide' — без src до показа слайда (подставляет app.js).
function img(key, { alt = '', sizes = '100vw', lazy = 'native', cls = '', priority = false } = {}) {
  if (!has(key)) return '';
  const m = manifest[key];
  const ws = widthsOf(key);
  const mid = fileOf(key, ws[Math.min(1, ws.length - 1)]);
  const set = srcset(key);
  const common = `width="${m.w}" height="${m.h}" alt="${esc(alt)}" sizes="${sizes}"${cls ? ` class="${cls}"` : ''} decoding="async"`;
  if (lazy === 'slide') return `<img data-src="${mid}" data-srcset="${set}" ${common}>`;
  const load = priority ? ' fetchpriority="high"' : lazy === 'native' ? ' loading="lazy"' : '';
  return `<img src="${mid}" srcset="${set}" ${common}${load}>`;
}

// Отдельное фото для вертикального телефона, если оно есть (ключ-mobile).
function picture(key, mobileKey, opts = {}) {
  const base = img(key, opts);
  if (!base) return '';
  if (!mobileKey || !has(mobileKey) || opts.lazy === 'slide') {
    if (opts.lazy === 'slide' && mobileKey && has(mobileKey)) {
      const mob = `<source media="(max-width: 980px) and (orientation: portrait)" data-srcset="${srcset(mobileKey)}" sizes="100vw">`;
      return `<picture>${mob}${base}</picture>`;
    }
    return base;
  }
  return `<picture><source media="(max-width: 980px) and (orientation: portrait)" srcset="${srcset(mobileKey)}" sizes="100vw">${base}</picture>`;
}

const photoOrMist = (html) => html || '<div class="mist" aria-hidden="true"></div>';

/* ---------------- Значки ---------------- */

const icon = {
  prev: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 19l-7-7 7-7"/></svg>',
  next: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 5l7 7-7 7"/></svg>',
  phone: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6.62 10.79a15.05 15.05 0 0 0 6.59 6.59l2.2-2.2c.27-.27.67-.36 1.02-.24 1.12.37 2.33.57 3.57.57.55 0 1 .45 1 1V20c0 .55-.45 1-1 1-9.39 0-17-7.61-17-17 0-.55.45-1 1-1h3.5c.55 0 1 .45 1 1 0 1.25.2 2.45.57 3.57.11.35.03.74-.25 1.02l-2.2 2.2z"/></svg>',
  mail: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4l-8 5-8-5V6l8 5 8-5v2z"/></svg>',
  pin: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z"/></svg>',
  tg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.894 8.221l-1.97 9.28c-.145.658-.537.818-1.084.508l-3-2.21-1.446 1.394c-.14.18-.357.223-.548.223l.188-2.85 5.18-4.686c.223-.195-.054-.285-.346-.09l-6.4 4.024-2.76-.86c-.6-.185-.615-.595.125-.89l10.736-4.14c.498-.22 1.006.115.825.901z"/></svg>',
  wa: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12.01 2.002c-5.524 0-10.007 4.48-10.007 10.004 0 1.758.46 3.414 1.252 4.881L2 21.999l5.297-1.192c1.425.736 3.018 1.127 4.713 1.127 5.523 0 10.005-4.481 10.005-10.005C22.015 6.482 17.533 2.002 12.01 2.002zm4.359 14.394c-.19.54-.928 1.026-1.39 1.1-.409.062-1.025.109-2.923-.676-2.348-.925-3.882-3.376-4.004-3.535-.12-.158-.956-1.282-.956-2.443 0-1.161.605-1.734.825-1.97.221-.238.513-.3.676-.3.161 0 .324-.002.464-.002.164 0 .385-.062.605.467.226.541.745 1.83.81 1.961.066.133.111.286.035.438-.076.152-.115.247-.229.382-.113.132-.238.29-.336.381-.11.1-.225.213-.099.431.126.219.561.928 1.203 1.503.826.738 1.517.969 1.737 1.073.22.105.348.087.48-.063.131-.151.564-.658.718-.884.152-.226.305-.188.536-.1.23.087 1.455.688 1.705.812.25.125.415.188.476.29.062.103.062.595-.128 1.133z"/></svg>',
};
const arrows = (cls = '') =>
  `<div class="arrows ${cls}"><button class="round" type="button" data-prev aria-label="Назад">${icon.prev}</button><button class="round" type="button" data-next aria-label="Вперед">${icon.next}</button></div>`;
const logoImg = (cls, alt = 'Archiwood') => `<img src="${asset('logo.svg')}" width="600" height="120" alt="${esc(alt)}" class="${cls}">`;

/* ---------------- Общие части ---------------- */

const NAV = [
  ['', 'Главная'],
  ['proekty/', 'Проекты'],
  ['o-kompanii/', 'О компании'],
];

function header(solid) {
  return `<header class="hdr${solid ? ' is-solid' : ''}">
  <a class="hdr__logo" href="${href('')}" aria-label="Archiwood — на главную">${logoImg('', '')}</a>
  <button class="burger" type="button" data-menu-open aria-controls="menu" aria-expanded="false" aria-label="Открыть меню"><span></span><span></span><span></span></button>
</header>`;
}

function menu(current) {
  const links = NAV.map(([p, t]) => `<a href="${href(p)}"${p === current ? ' aria-current="page"' : ''}>${t}</a>`).join('\n      ');
  return `<div class="menu" id="menu" role="dialog" aria-modal="true" aria-label="Меню сайта" aria-hidden="true">
  <div class="menu__col">
    ${logoImg('menu__logo')}
    <nav class="menu__nav" aria-label="Разделы сайта">
      ${links}
      <a href="#kontakty" data-menu-close>Контакты</a>
    </nav>
    <p class="menu__meta">${typo(site.tagline)}</p>
  </div>
  <div class="menu__img photo">${img('menu', { alt: '', sizes: '(max-width: 980px) 100vw, 50vw' })}</div>
  <button class="menu__close" type="button" data-menu-close aria-label="Закрыть меню"><span></span><span></span></button>
</div>`;
}

function contacts() {
  return `<section class="contacts" id="kontakty" aria-labelledby="kontakty-h">
  <div class="contacts__info">
    <h2 id="kontakty-h" class="sr-only">Контакты</h2>
    ${logoImg('contacts__logo rv')}
    <p class="contacts__text rv rv-2">${typo(site.promise)}</p>
    <div class="contacts__list rv rv-3">
      <a class="contacts__link" href="tel:${site.phoneHref}">${icon.phone}<span>${site.phone}</span></a>
      <a class="contacts__link" href="mailto:${site.email}">${icon.mail}<span>${site.email}</span></a>
      <a class="contacts__link contacts__addr" href="${site.mapUrl}" target="_blank" rel="noopener">${icon.pin}<span>${typo(site.address)}</span></a>
      <p class="contacts__note">${typo(site.addressNote)}</p>
    </div>
    <div class="socials rv rv-4">
      <a href="${site.telegram}" target="_blank" rel="noopener" aria-label="Написать в Telegram">${icon.tg}</a>
      <a href="${site.whatsapp}" target="_blank" rel="noopener" aria-label="Написать в WhatsApp">${icon.wa}</a>
    </div>
  </div>
  <div class="contacts__photo photo">${img('kontakty', { alt: 'Шоурум Archiwood на Васильевском острове', sizes: '(max-width: 980px) 100vw, 50vw' })}</div>
</section>
<footer class="foot">
  <span>© ${YEAR} Archiwood · Столярное производство, Санкт-Петербург</span>
  <a href="tel:${site.phoneHref}">${site.phone}</a>
</footer>`;
}

function metrika() {
  if (!site.metrika) return '';
  const id = String(site.metrika).replace(/\D/g, '');
  return `<script>(function(m,e,t,r,i,k,a){m[i]=m[i]||function(){(m[i].a=m[i].a||[]).push(arguments)};m[i].l=1*new Date();k=e.createElement(t),a=e.getElementsByTagName(t)[0],k.async=1,k.src=r,a.parentNode.insertBefore(k,a)})(window,document,"script","https://mc.yandex.ru/metrika/tag.js","ym");ym(${id},"init",{clickmap:true,trackLinks:true,accurateTrackBounce:true,webvisor:true});</script>
<noscript><div><img src="https://mc.yandex.ru/watch/${id}" style="position:absolute;left:-9999px" alt=""></div></noscript>`;
}

// Страница целиком. В предпросмотре главная пишется без <html>/<head> (их добавляет площадка).
function layout({ path, page, title, description, content, solid = false, intro = false, ogImage, jsonld, fragment = false }) {
  const canonical = site.url + '/' + path;
  const og = ogImage && has(ogImage) ? site.url + '/img/' + ogImage + '-' + manifest[ogImage].widths.slice(-1)[0] + '.webp' : '';
  const headInner = `<title>${esc(title)}</title>
<meta name="description" content="${esc(description)}">
<link rel="canonical" href="${canonical}">
<meta property="og:type" content="website">
<meta property="og:locale" content="ru_RU">
<meta property="og:site_name" content="Archiwood">
<meta property="og:title" content="${esc(title)}">
<meta property="og:description" content="${esc(description)}">
<meta property="og:url" content="${canonical}">
${og ? `<meta property="og:image" content="${og}">\n` : ''}<meta name="theme-color" content="#faf0e6">
<link rel="icon" href="${asset('favicon.svg')}" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Cormorant:ital,wght@0,400;0,500;1,400&display=swap">
${PREVIEW ? `<style>${inline.css}</style>` : `<link rel="stylesheet" href="${versioned('assets/style.css')}">`}
<script>document.documentElement.classList.add('js');try{if(sessionStorage.getItem('aw'))document.documentElement.classList.add('seen');sessionStorage.setItem('aw','1')}catch(e){}</script>
${jsonld ? `<script type="application/ld+json">${JSON.stringify(jsonld)}</script>\n` : ''}${metrika()}`;

  const bodyInner = `${intro ? `<div class="intro" aria-hidden="true">${logoImg('intro__logo', '')}</div>\n` : ''}<a class="sr-only" href="#main">К содержимому</a>
${header(solid)}
${menu(path)}
<main id="main" data-page="${page}">
${content}
</main>
${contacts()}
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

/* ---------------- Страницы ---------------- */

function pageHome() {
  const slides = featured.map((id) => byId[id]).filter(Boolean);
  const texts = slides.map((p) => {
    const link = p.status === 'done' ? href(`proekty/${p.id}/`) : href('proekty/', '#v-realizacii');
    return `<div data-id="${p.id}" data-group="${p.status === 'done' ? 'Галерея проектов' : 'В реализации'}" data-href="${link}" data-link-text="${p.status === 'done' ? 'К проекту' : 'Объекты в работе'}">
          <h3 class="split__title">${typo(p.title)}</h3>
          <p class="split__desc">${typo(p.desc)}</p>
        </div>`;
  }).join('\n        ');
  const images = slides.map((p, k) =>
    `<div>${photoOrMist(img(`proekty/${p.id}/oblozhka-v`, { alt: p.title, sizes: '(max-width: 980px) 100vw, 46vw', lazy: k === 0 ? 'native' : 'slide' }))}</div>`
  ).join('\n        ');

  const revTexts = reviews.map((r) => `<div>
          <h3 class="split__title split__title--sm">${typo(r.author)}</h3>
          <div class="split__desc">${r.text.map((t) => `<p>${typo(t)}</p>`).join('')}</div>
        </div>`).join('\n        ');
  const revImages = reviews.map((r, k) =>
    `<div>${photoOrMist(img(`otzyvy/${k + 1}`, { alt: '', sizes: '(max-width: 980px) 100vw, 46vw', lazy: k === 0 ? 'native' : 'slide' }))}</div>`
  ).join('\n        ');

  const content = `<section class="hero" data-hero>
  <div class="hero__bg">${picture('glavnaya/hero', 'glavnaya/hero-mobile', { alt: 'Интерьер с мебелью и стеновыми панелями Archiwood', priority: true, lazy: 'none' })}</div>
  <div class="hero__content">
    <h1>${logoImg('hero__logo', 'Archiwood — столярное производство мебели и интерьеров в Санкт-Петербурге')}</h1>
  </div>
  <span class="hero__scroll" aria-hidden="true"></span>
</section>

<section class="who" aria-labelledby="who-h">
  <div class="who__inner">
    <p class="label rv">Кто мы</p>
    <h2 id="who-h" class="display rv rv-2">${typo(site.tagline)}</h2>
    <p class="lead rv rv-3">${typo('Мы объединяем возможности технологичного производства с вниманием мебельного ателье. Не просто работаем по чертежам, а подключаемся на этапе идеи: разрабатываем конструкторские решения для сложных узлов и берем на себя ответственность за реализацию — от документации до монтажа.')}</p>
  </div>
</section>

<section class="split" id="galereya" data-slider aria-roledescription="карусель" aria-label="Галерея проектов">
  <div class="split__content">
    <p class="label rv" data-label>Галерея проектов</p>
    <div class="split__texts track-fade rv rv-2" data-track aria-live="polite">
        ${texts}
    </div>
    <div class="split__panel rv rv-3">
      <div class="controls">${arrows('hide-mob')}<div class="progress" data-progress><span class="progress__fill"></span></div></div>
      <div class="split__buttons">
        <a class="btn" href="#" data-link>К проекту</a>
        <a class="btn" href="${href('proekty/')}">Все проекты</a>
      </div>
    </div>
  </div>
  <div class="split__visual rv">
    <div class="track-img" data-track data-swipe>
        ${images}
    </div>
    ${arrows('hide-desk')}
  </div>
</section>

<section class="split split--rev" data-slider aria-roledescription="карусель" aria-label="Отзывы">
  <div class="split__content">
    <p class="label rv">Отзывы</p>
    <div class="controls controls--center rv rv-2" style="width:100%;max-width:600px">${arrows()}<div class="progress" data-progress><span class="progress__fill"></span></div></div>
    <div class="split__texts track-fade rv rv-3" data-track aria-live="polite">
        ${revTexts}
    </div>
  </div>
  <div class="split__visual rv">
    <div class="track-img" data-track data-swipe>
        ${revImages}
    </div>
  </div>
</section>`;

  return layout({
    path: '', page: 'glavnaya', intro: true, fragment: PREVIEW,
    title: PREVIEW ? 'Сайт Archiwood' : 'Archiwood — мебель и столярные интерьеры на заказ в Санкт-Петербурге',
    description: site.description,
    ogImage: 'glavnaya/hero',
    jsonld: {
      '@context': 'https://schema.org',
      '@type': 'HomeAndConstructionBusiness',
      name: 'Archiwood',
      description: site.description,
      url: site.url + '/',
      telephone: site.phoneHref,
      email: site.email,
      address: { '@type': 'PostalAddress', streetAddress: '3-я линия В.О., д. 6', addressLocality: 'Санкт-Петербург', addressCountry: 'RU' },
      sameAs: [site.telegram],
    },
    content,
  });
}

function pageAbout() {
  const texts = principles.map((p) => `<div>
          <h3 class="split__title">${typo(p.title)}</h3>
          <p class="split__desc lead">${typo(p.text)}</p>
        </div>`).join('\n        ');
  const images = principles.map((p, k) =>
    `<div>${photoOrMist(picture(`o-kompanii/printsip-${k + 1}`, `o-kompanii/printsip-${k + 1}-mobile`, { alt: p.title, lazy: k === 0 ? 'native' : 'slide' }))}</div>`
  ).join('\n        ');

  const content = `<section class="hero hero--dim" data-hero>
  <div class="hero__bg">${picture('o-kompanii/hero', 'o-kompanii/hero-mobile', { alt: 'Производство Archiwood', priority: true, lazy: 'none' })}</div>
  <div class="hero__content">
    <span data-typing-logo>${logoImg('hero__logo hero__logo--plain')}</span>
    <h1 class="hero__text" data-typing>${typo('Создаем архитектурную мебель премиум-класса. Инженерная точность и бескомпромиссное качество в каждой детали.')}</h1>
  </div>
  <span class="hero__scroll" aria-hidden="true"></span>
</section>

<section class="about" aria-labelledby="about-h">
  <div class="about__text">
    <p class="label label--left rv">О нас</p>
    <h2 id="about-h" class="display rv rv-2">${typo('Мы объединяем возможности технологичного производства с вниманием мебельного ателье.')}</h2>
    <p class="lead rv rv-3">${typo('Не просто работаем по чертежам, а подключаемся на этапе идеи: разрабатываем конструкторские решения для сложных узлов и берем на себя ответственность за реализацию от документации до монтажа.')}</p>
    <a class="btn rv rv-4" href="#kontakty">Связаться с нами</a>
  </div>
  <div class="about__photo photo rv rv-2">${picture('o-kompanii/o-nas', 'o-kompanii/o-nas-mobile', { alt: 'Мастерская Archiwood', sizes: '(max-width: 980px) 100vw, 50vw' })}</div>
</section>

<section class="principles" data-slider aria-roledescription="карусель" aria-label="Принципы работы">
  <div class="principles__top">
    <p class="label rv">Принципы работы</p>
    <div class="split__texts track-fade rv rv-2" data-track aria-live="polite">
        ${texts}
    </div>
    <div class="controls controls--center rv rv-3">${arrows()}</div>
  </div>
  <div class="principles__visual rv">
    <div class="track-img" data-track data-swipe>
        ${images}
    </div>
  </div>
</section>

<section class="promise" aria-labelledby="promise-h">
  <div class="promise__bg">${img('o-kompanii/obeshchanie', { alt: '' })}</div>
  <div class="promise__content">
    <p class="promise__label rv">Главное обещание</p>
    <h2 id="promise-h" class="promise__text rv rv-2">${typo(site.promise)}</h2>
  </div>
</section>`;

  return layout({
    path: 'o-kompanii/', page: 'o-kompanii',
    title: 'О компании Archiwood — производство и конструкторское бюро',
    description: 'Archiwood объединяет технологичное производство и внимание мебельного ателье: прототипы и тестирование узлов, своя конструкторская служба, работа с деревом от отбора шпона до монтажа.',
    ogImage: 'o-kompanii/hero',
    content,
  });
}

function card(p) {
  const v = `proekty/${p.id}/oblozhka-v`;
  const h = `proekty/${p.id}/oblozhka-h`;
  const photo = p.layout === 'h'
    ? (has(h) ? picture(h, has(v) ? v : null, { alt: p.title, sizes: '100vw' }) : img(v, { alt: p.title, sizes: '100vw' }))
    : img(v, { alt: p.title, sizes: '(max-width: 680px) 100vw, 50vw' });
  const inner = `<div class="photo">${photoOrMist(photo)}</div>
      <div class="card__body"><h3 class="card__title">${typo(p.short)}</h3><span class="card__more">${p.status === 'done' ? 'Смотреть проект' : 'В реализации'}</span></div>`;
  const cls = `card card--${p.layout} rv`;
  return p.status === 'done'
    ? `<a class="${cls}" href="${href(`proekty/${p.id}/`)}" data-project="${p.id}">
      ${inner}
    </a>`
    : `<div class="${cls} card--soon">
      ${inner}
    </div>`;
}

function pageProjects() {
  const soon = projects.filter((p) => p.status === 'soon');
  const content = `<header class="page-head">
  <p class="label">Портфолио</p>
  <h1 class="display">Проекты</h1>
  <p class="lead">${typo('Реализованные объекты и проекты, над которыми мы работаем сейчас.')}</p>
</header>
<div class="portfolio">
  <div class="grid">
    <div class="sec-head" id="realizovannye"><h2>Реализованные</h2><span></span></div>
    ${done.map(card).join('\n    ')}
    <div class="sec-head" id="v-realizacii"><h2>В реализации</h2><span></span></div>
    ${soon.map(card).join('\n    ')}
  </div>
</div>`;
  return layout({
    path: 'proekty/', page: 'proekty', solid: true,
    title: 'Проекты Archiwood — мебель, панели и столярные интерьеры',
    description: 'Портфолио Archiwood: частные резиденции, квартиры, рестораны и жилые комплексы в Санкт-Петербурге, Москве и Дубае. Стеновые панели, корпусная мебель, двери и перегородки.',
    ogImage: done[0] && `proekty/${done[0].id}/oblozhka-h`,
    content,
  });
}

function galleryKeys(id) {
  const pre = `proekty/${id}/galereya/`;
  return Object.keys(manifest).filter((k) => k.startsWith(pre)).sort();
}

function pageProject(p, k) {
  const next = done[(k + 1) % done.length];
  const keys = galleryKeys(p.id);
  const gallery = keys.map((key, n) =>
    `<a href="${biggest(key)}" data-lb>${img(key, { alt: `${p.title} — фото ${n + 1}`, sizes: '(max-width: 680px) 50vw, (max-width: 1200px) 50vw, 33vw' })}</a>`
  ).join('\n  ');
  const cover = has(`proekty/${p.id}/oblozhka-h`) ? `proekty/${p.id}/oblozhka-h` : `proekty/${p.id}/oblozhka-v`;
  const content = `<section class="proj-hero" data-hero>
  <div class="photo">${picture(cover, `proekty/${p.id}/oblozhka-v`, { alt: p.title, priority: true, lazy: 'none' })}</div>
  <div class="proj-hero__body">
    <nav class="crumbs" aria-label="Вы здесь"><a href="${href('')}">Главная</a><span>/</span><a href="${href('proekty/')}">Проекты</a></nav>
    <h1>${typo(p.title)}</h1>
  </div>
</section>
<section class="proj-about">
  <p class="lead">${typo(p.desc)}</p>
  <div class="split__buttons">
    <a class="btn" href="${href('proekty/')}">Все проекты</a>
    <a class="btn" href="${href('', `?return=${p.id}#galereya`)}">На главную</a>
  </div>
</section>
${keys.length ? `<div class="gallery">\n  ${gallery}\n</div>` : ''}
<a class="proj-next" href="${href(`proekty/${next.id}/`)}">
  <span class="label">Следующий проект</span>
  <span class="display">${typo(next.title)}</span>
</a>`;
  return layout({
    path: `proekty/${p.id}/`, page: 'proekt',
    title: `${p.title} — проект Archiwood`,
    description: p.desc,
    ogImage: cover,
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
    path: '404.html', page: '404', solid: true,
    title: 'Страница не найдена — Archiwood',
    description: 'Такой страницы нет на сайте Archiwood.',
    content: `<header class="page-head" style="min-height:60svh;align-content:center">
  <p class="label">Ошибка 404</p>
  <h1 class="display">Такой страницы нет</h1>
  <p class="lead">Возможно, адрес изменился после переезда сайта.</p>
  <a class="btn" href="${href('')}">На главную</a>
</header>`,
  });
}

/* ---------------- Список фото (FOTO.md и tools/sloty.json) ---------------- */

function slots() {
  const s = [];
  const add = (key, w, h, where, optional = false) => s.push({ key, w, h, where, optional });
  add('glavnaya/hero', 2400, 1350, 'Главная, первый экран — компьютер');
  add('glavnaya/hero-mobile', 1080, 1920, 'Главная, первый экран — телефон');
  add('menu', 1200, 1600, 'Меню, фото справа');
  add('kontakty', 1200, 1600, 'Блок контактов внизу каждой страницы (шоурум)');
  add('o-kompanii/hero', 2400, 1350, 'О компании, первый экран — компьютер');
  add('o-kompanii/hero-mobile', 1080, 1920, 'О компании, первый экран — телефон');
  add('o-kompanii/o-nas', 1200, 1600, 'О компании, блок «О нас» — компьютер');
  add('o-kompanii/o-nas-mobile', 1080, 1920, 'О компании, блок «О нас» — телефон');
  principles.forEach((p, k) => {
    add(`o-kompanii/printsip-${k + 1}`, 2400, 1200, `Принцип «${p.title}» — компьютер`);
    add(`o-kompanii/printsip-${k + 1}-mobile`, 1080, 1350, `Принцип «${p.title}» — телефон`);
  });
  add('o-kompanii/obeshchanie', 2400, 1350, 'О компании, блок «Главное обещание»');
  reviews.forEach((r, k) => add(`otzyvy/${k + 1}`, 1200, 1600, `Фото к отзыву: ${r.author}`));
  projects.forEach((p) => {
    const mystery = p.status === 'soon' && !['ozerki', 'repino2'].includes(p.id);
    add(`proekty/${p.id}/oblozhka-v`, 1200, 1600, `${p.title} — обложка вертикальная (слайдер на главной${p.layout === 'v' ? ', карточка' : ''})`, mystery);
    if (p.layout === 'h') add(`proekty/${p.id}/oblozhka-h`, 2400, 1350, `${p.title} — обложка широкая (карточка во всю ширину)`, mystery);
    if (p.status === 'done') {
      [[2400, 1600], [1600, 2400], [2400, 1600], [1600, 2000]].forEach(([w, h], n) =>
        add(`proekty/${p.id}/galereya/0${n + 1}`, w, h, `${p.title} — галерея`, false));
    }
  });
  return s;
}

function writeFotoList(list) {
  writeFileSync(join(ROOT, 'tools/sloty.json'), JSON.stringify(list, null, 1));
  const zPath = join(ROOT, 'tools/zaglushki.json');
  const z = existsSync(zPath) ? JSON.parse(readFileSync(zPath, 'utf8')) : {};
  const status = (key, optional) => (has(key) ? (z[key] ? '🟡 заглушка' : '✅ готово') : optional ? '⚪ можно без фото' : '🔴 нет');
  const rows = list.filter((x) => !x.key.includes('/galereya/'));
  const groups = {};
  rows.forEach((x) => { const g = x.key.split('/')[0]; (groups[g] ||= []).push(x); });
  const names = { glavnaya: 'Главная', menu: 'Меню', kontakty: 'Контакты', 'o-kompanii': 'О компании', otzyvy: 'Отзывы', proekty: 'Проекты (обложки)' };
  let md = `# Фотографии для сайта

Этот файл собирается автоматически (\`node sayt/build.mjs\`). Сейчас на местах стоят выдуманные фото-заглушки.

**Как заменить фото.** Положите файл в папку \`sayt/foto/\` по пути из колонки «Файл» (расширение .jpg, .jpeg, .png или .webp — любое), затем:

\`\`\`
python3 sayt/tools/foto.py && node sayt/build.mjs
\`\`\`

Фото автоматически уменьшится и сожмется в WebP в трех размерах. Присылайте исходники в максимальном качестве и не меньше указанного размера; соотношение сторон важнее точных пикселей.

**Галерея проекта** — это папка \`sayt/foto/proekty/<проект>/galereya/\`: сколько файлов положите, столько фото будет на странице проекта, в порядке имен (01, 02, 03…). Длинная сторона — от 2400 px, ориентация любая.

`;
  for (const [g, items] of Object.entries(groups)) {
    md += `## ${names[g] || g}\n\n| Статус | Файл | Размер | Где на сайте |\n|---|---|---|---|\n`;
    items.forEach((x) => { md += `| ${status(x.key, x.optional)} | \`foto/${x.key}.jpg\` | ${x.w}×${x.h} | ${x.where} |\n`; });
    md += '\n';
  }
  md += `## Галереи проектов\n\n| Проект | Папка | Сейчас фото |\n|---|---|---|\n`;
  done.forEach((p) => { md += `| ${p.title} | \`foto/proekty/${p.id}/galereya/\` | ${galleryKeys(p.id).length} |\n`; });
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
  writeFotoList(slots());
  rmSync(OUT, { recursive: true, force: true });
  mkdirSync(join(OUT, 'assets'), { recursive: true });

  const css = minifyCss(readFileSync(join(ROOT, 'src/style.css'), 'utf8'));
  const js = readFileSync(join(ROOT, 'src/app.js'), 'utf8');
  writeFileSync(join(OUT, 'assets/style.css'), css);
  writeFileSync(join(OUT, 'assets/app.js'), js);
  // В предпросмотре площадка разрешает только встроенные стили и скрипты
  inline.css = css;
  inline.js = js.replace(/<\/script/g, '<\\/script');
  versions['assets/style.css'] = createHash('sha1').update(css).digest('hex').slice(0, 8);
  versions['assets/app.js'] = createHash('sha1').update(js).digest('hex').slice(0, 8);
  for (const f of ['logo.svg', 'favicon.svg']) cpSync(join(ROOT, 'static', f), join(OUT, f));

  const pages = [];
  depth = 0; write('index.html', pageHome()); pages.push('');
  depth = 1; write('o-kompanii/index.html', pageAbout()); pages.push('o-kompanii/');
  depth = 1; write('proekty/index.html', pageProjects()); pages.push('proekty/');
  done.forEach((p, k) => { depth = 2; write(`proekty/${p.id}/index.html`, pageProject(p, k)); pages.push(`proekty/${p.id}/`); });
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
    write('_redirects', `/2 /o-kompanii/ 301\n/3 /proekty/ 301\n/2/ /o-kompanii/ 301\n/3/ /proekty/ 301\n`);
    write('_headers', `/assets/*\n  Cache-Control: public, max-age=31536000, immutable\n/img/*\n  Cache-Control: public, max-age=2592000\n/*\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: strict-origin-when-cross-origin\n`);
  }

  const missing = slots().filter((x) => !x.optional && !has(x.key)).length;
  console.log(`Готово: ${OUT} — страниц ${pages.length}, фото ${usedImages.size}${missing ? `, без фото мест: ${missing} (см. FOTO.md)` : ''}`);
}

build();
