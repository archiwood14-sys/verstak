/* Archiwood — общий скрипт сайта. Без внешних библиотек. */
(function () {
  'use strict';

  var doc = document;
  var root = doc.documentElement;
  var body = doc.body;
  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var $ = function (sel, el) { return (el || doc).querySelector(sel); };
  var $$ = function (sel, el) { return Array.prototype.slice.call((el || doc).querySelectorAll(sel)); };

  var params = new URLSearchParams(location.search);

  /* ---------- Старые ссылки с Тильды: /3?open=repino1 ---------- */
  var main = $('main');
  if (main && main.getAttribute('data-page') === 'proekty' && params.get('open')) {
    var target = $('[data-project="' + params.get('open') + '"]');
    if (target && target.tagName === 'A') { location.replace(target.href); return; }
  }

  /* ---------- Заставка ---------- */
  var intro = $('.intro');
  if (intro) {
    var hideIntro = function () {
      intro.classList.add('is-done');
      setTimeout(function () { intro.remove(); }, 800);
    };
    var fontsReady = doc.fonts && doc.fonts.ready ? doc.fonts.ready : Promise.resolve();
    Promise.race([fontsReady, new Promise(function (r) { setTimeout(r, 1200); })]).then(function () {
      setTimeout(hideIntro, 350);
    });
  }

  /* ---------- Плашка о потере сети ---------- */
  var toast = $('.toast');
  var toastTimer;
  function showToast(text, ok) {
    if (!toast) return;
    clearTimeout(toastTimer);
    toast.textContent = text;
    toast.classList.toggle('is-ok', !!ok);
    toast.classList.add('is-on');
    if (ok) toastTimer = setTimeout(function () { toast.classList.remove('is-on'); }, 3000);
  }
  window.addEventListener('offline', function () { showToast('Нет соединения. Проверьте подключение к интернету.'); });
  window.addEventListener('online', function () { showToast('Соединение восстановлено.', true); });

  /* ---------- Шапка, параллакс, исчезание текста первого экрана ---------- */
  var hdr = $('.hdr');
  var hero = $('[data-hero]');
  var heroBg = $('.hero__bg');
  var heroContent = $('.hero__content');
  var ticking = false;

  function onScroll() {
    var y = window.scrollY;
    if (hdr && hero) {
      hdr.classList.toggle('is-solid', y > hero.offsetHeight - hdr.offsetHeight - 10);
    }
    if (hero && y < hero.offsetHeight * 1.2) {
      if (heroBg && !reduceMotion) heroBg.style.transform = 'translate3d(0,' + (y * 0.3) + 'px,0)';
      if (heroContent) heroContent.classList.toggle('is-out', y > window.innerHeight * 0.4);
    }
    ticking = false;
  }
  window.addEventListener('scroll', function () {
    if (!ticking) { ticking = true; requestAnimationFrame(onScroll); }
  }, { passive: true });
  onScroll();

  /* ---------- Меню ---------- */
  var menu = $('.menu');
  var lastFocus = null;
  function setMenu(open) {
    if (!menu) return;
    menu.classList.toggle('is-open', open);
    menu.setAttribute('aria-hidden', open ? 'false' : 'true');
    if ('inert' in menu) menu.inert = !open;
    body.classList.toggle('is-locked', open);
    $$('[data-menu-open]').forEach(function (b) { b.setAttribute('aria-expanded', open ? 'true' : 'false'); });
    if (open) {
      lastFocus = doc.activeElement;
      var first = $('.menu__nav a', menu);
      if (first) setTimeout(function () { first.focus({ preventScroll: true }); }, 50);
    } else if (lastFocus) {
      lastFocus.focus({ preventScroll: true });
    }
  }
  if (menu && 'inert' in menu) menu.inert = true;
  doc.addEventListener('click', function (e) {
    if (e.target.closest('[data-menu-open]')) { e.preventDefault(); setMenu(true); }
    else if (e.target.closest('[data-menu-close]')) setMenu(false);
  });

  /* ---------- Появление при прокрутке ---------- */
  var revealItems = $$('.rv, .promise');
  if ('IntersectionObserver' in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { en.target.classList.add('is-in'); io.unobserve(en.target); }
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -5% 0px' });
    revealItems.forEach(function (el) { io.observe(el); });
  } else {
    revealItems.forEach(function (el) { el.classList.add('is-in'); });
  }

  /* ---------- Печать текста на первом экране (страница «О компании») ---------- */
  var typing = $('[data-typing]');
  if (typing && !reduceMotion) {
    var text = typing.textContent.trim();
    typing.setAttribute('aria-label', text);
    typing.textContent = '';
    var chars = [];
    text.split('').forEach(function (c) {
      if (c === ' ') { typing.appendChild(doc.createTextNode(' ')); return; }
      var s = doc.createElement('span');
      s.className = 'ch';
      s.setAttribute('aria-hidden', 'true');
      s.textContent = c;
      typing.appendChild(s);
      chars.push(s);
    });
    var logo = $('[data-typing-logo]');
    if (logo) { logo.style.opacity = '0'; logo.style.transition = 'opacity 1.2s, transform 1.2s'; logo.style.transform = 'translateY(16px)'; }
    chars.forEach(function (s, i) { setTimeout(function () { s.classList.add('is-on'); }, 300 + i * 16); });
    if (logo) setTimeout(function () { logo.style.opacity = '1'; logo.style.transform = 'none'; }, 300 + chars.length * 16 + 300);
  }

  /* ---------- Слайдеры ---------- */
  // Разметка: [data-slider] > [data-track] (дорожки с одинаковым числом слайдов),
  // кнопки [data-prev]/[data-next], полоса [data-progress], надпись [data-label],
  // ссылка [data-link] (берет адрес из data-href активного слайда).
  function hydrate(slide) {
    if (!slide) return;
    $$('source[data-srcset]', slide).forEach(function (el) {
      el.srcset = el.getAttribute('data-srcset');
      el.removeAttribute('data-srcset');
    });
    $$('img[data-src]', slide).forEach(function (el) {
      if (el.getAttribute('data-srcset')) el.srcset = el.getAttribute('data-srcset');
      el.src = el.getAttribute('data-src');
      el.removeAttribute('data-src');
      el.removeAttribute('data-srcset');
    });
  }

  $$('[data-slider]').forEach(function (slider) {
    var tracks = $$('[data-track]', slider);
    if (!tracks.length) return;
    var n = tracks[0].children.length;
    var i = 0;
    var fill = $('[data-progress] .progress__fill', slider);
    var label = $('[data-label]', slider);
    var link = $('[data-link]', slider);
    var counter = $('[data-count]', slider);
    var lead = tracks[0];

    if (fill) fill.style.width = (100 / n) + '%';

    function go(next) {
      i = (next + n) % n;
      tracks.forEach(function (t) {
        Array.prototype.forEach.call(t.children, function (s, k) {
          var on = k === i;
          s.classList.toggle('is-active', on);
          s.setAttribute('aria-hidden', on ? 'false' : 'true');
        });
        hydrate(t.children[i]);
        hydrate(t.children[(i + 1) % n]);
        hydrate(t.children[(i - 1 + n) % n]);
      });
      if (fill) fill.style.transform = 'translateX(' + (i * 100) + '%)';
      if (counter) counter.textContent = String(i + 1).padStart(2, '0') + ' / ' + String(n).padStart(2, '0');
      var active = lead.children[i];
      if (label && active.getAttribute('data-group')) label.textContent = active.getAttribute('data-group');
      if (link) {
        var href = active.getAttribute('data-href');
        link.setAttribute('aria-disabled', href ? 'false' : 'true');
        link.href = href || '#';
        var txt = active.getAttribute('data-link-text');
        if (txt) link.textContent = txt;
      }
    }

    $$('[data-prev]', slider).forEach(function (b) { b.addEventListener('click', function () { go(i - 1); }); });
    $$('[data-next]', slider).forEach(function (b) { b.addEventListener('click', function () { go(i + 1); }); });

    slider.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowLeft') go(i - 1);
      if (e.key === 'ArrowRight') go(i + 1);
    });

    // Свайп пальцем или мышью по фото
    $$('[data-swipe]', slider).forEach(function (area) {
      var x0 = null, y0 = 0;
      area.addEventListener('pointerdown', function (e) { x0 = e.clientX; y0 = e.clientY; });
      area.addEventListener('pointerup', function (e) {
        if (x0 === null) return;
        var dx = e.clientX - x0, dy = e.clientY - y0;
        x0 = null;
        if (Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(dy)) go(dx < 0 ? i + 1 : i - 1);
      });
      area.addEventListener('pointercancel', function () { x0 = null; });
    });

    // Возврат со страницы проекта: /?return=repino1 — открываем тот же слайд
    var ret = params.get('return');
    var start = 0;
    if (ret) {
      Array.prototype.forEach.call(lead.children, function (s, k) { if (s.getAttribute('data-id') === ret) start = k; });
    }
    go(start);
  });

  /* ---------- Горизонтальная лента со стрелками ---------- */
  $$('[data-rail]').forEach(function (rail) {
    var id = rail.id;
    var step = function (dir) {
      var item = rail.firstElementChild;
      var w = item ? item.getBoundingClientRect().width + 28 : rail.clientWidth * 0.8;
      rail.scrollBy({ left: dir * w, behavior: reduceMotion ? 'auto' : 'smooth' });
    };
    $$('[data-rail-prev="' + id + '"]').forEach(function (b) { b.addEventListener('click', function () { step(-1); }); });
    $$('[data-rail-next="' + id + '"]').forEach(function (b) { b.addEventListener('click', function () { step(1); }); });
  });

  /* ---------- Просмотр фотографий проекта ---------- */
  var links = $$('[data-lb]');
  if (links.length) {
    var lb = doc.createElement('div');
    lb.className = 'lb';
    lb.setAttribute('role', 'dialog');
    lb.setAttribute('aria-modal', 'true');
    lb.setAttribute('aria-label', 'Просмотр фотографий');
    lb.innerHTML =
      '<span class="lb__count"></span><img alt="">' +
      '<button class="round lb__close" type="button" aria-label="Закрыть"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button>' +
      '<button class="round lb__prev" type="button" aria-label="Предыдущее фото"><svg viewBox="0 0 24 24"><path d="M15 19l-7-7 7-7"/></svg></button>' +
      '<button class="round lb__next" type="button" aria-label="Следующее фото"><svg viewBox="0 0 24 24"><path d="M9 5l7 7-7 7"/></svg></button>';
    body.appendChild(lb);
    var img = $('img', lb);
    var count = $('.lb__count', lb);
    var cur = 0;
    var opener = null;

    var show = function (k) {
      cur = (k + links.length) % links.length;
      img.src = links[cur].href;
      img.alt = ($('img', links[cur]) || {}).alt || '';
      count.textContent = (cur + 1) + ' / ' + links.length;
      [cur + 1, cur - 1].forEach(function (j) { new Image().src = links[(j + links.length) % links.length].href; });
    };
    var open = function (k) {
      opener = doc.activeElement;
      show(k);
      lb.classList.add('is-open');
      body.classList.add('is-locked');
      $('.lb__close', lb).focus({ preventScroll: true });
    };
    var close = function () {
      lb.classList.remove('is-open');
      body.classList.remove('is-locked');
      if (opener) opener.focus({ preventScroll: true });
    };

    links.forEach(function (a, k) {
      a.addEventListener('click', function (e) { e.preventDefault(); open(k); });
    });
    $('.lb__close', lb).addEventListener('click', close);
    $('.lb__prev', lb).addEventListener('click', function () { show(cur - 1); });
    $('.lb__next', lb).addEventListener('click', function () { show(cur + 1); });
    lb.addEventListener('click', function (e) { if (e.target === lb) close(); });

    var sx = null;
    img.addEventListener('pointerdown', function (e) { sx = e.clientX; });
    img.addEventListener('pointerup', function (e) {
      if (sx === null) return;
      var dx = e.clientX - sx; sx = null;
      if (Math.abs(dx) > 40) show(dx < 0 ? cur + 1 : cur - 1);
    });

    doc.addEventListener('keydown', function (e) {
      if (!lb.classList.contains('is-open')) return;
      if (e.key === 'ArrowLeft') show(cur - 1);
      if (e.key === 'ArrowRight') show(cur + 1);
    });
  }

  /* ---------- Escape закрывает всё ---------- */
  doc.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    var lbOpen = $('.lb.is-open');
    if (lbOpen) { lbOpen.classList.remove('is-open'); body.classList.remove('is-locked'); return; }
    if (menu && menu.classList.contains('is-open')) setMenu(false);
  });
})();
