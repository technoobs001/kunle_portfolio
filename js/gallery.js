/* =========================================================================
   Gallery page behaviour
   - starts the curtain once the hero art has decoded
   - reads gallery/manifest.json and builds the scrapbook (no per-photo edits)
   - responsive <picture> markup (AVIF/WebP, srcset + sizes), lazy loading
   - lays frames out with the layout values saved in the manifest, so the
     arrangement is stable: adding photos never moves the existing ones
   ========================================================================= */
(function () {
  'use strict';

  var MANIFEST_URL = 'gallery/manifest.json';
  var stage = document.querySelector('[data-scrapbook]');
  var note = document.querySelector('[data-gallery-note]');
  var hero = document.querySelector('.hero');

  /* ---------- hero: wait for the art, then let the curtain go ------------ */
  function startCurtain() { hero.classList.add('is-ready'); }
  (function () {
    var imgs = hero.querySelectorAll('.hero__painting, .hero__curtain');
    var done = false;
    function go() { if (!done) { done = true; startCurtain(); } }
    var jobs = [].map.call(imgs, function (img) {
      return img.decode ? img.decode().catch(function () {}) : Promise.resolve();
    });
    Promise.all(jobs).then(go);
    setTimeout(go, 2500);                         // never wait forever
  })();

  if (!stage) return;

  /* ---------- manifest -------------------------------------------------- */
  function loadManifest() {
    return fetch(MANIFEST_URL, { cache: 'no-cache' })       // revalidates; images themselves are immutable
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .catch(function () {
        // opened straight from disk (file://): fall back to the script copy
        return new Promise(function (resolve, reject) {
          var s = document.createElement('script');
          s.src = 'gallery/manifest.js';
          s.onload = function () { window.__GALLERY_MANIFEST__ ? resolve(window.__GALLERY_MANIFEST__) : reject(); };
          s.onerror = reject;
          document.head.appendChild(s);
        });
      });
  }

  /* ---------- layout ---------------------------------------------------- */
  // Logical stage widths: sizes are expressed in "units" of the stage, and the
  // stage scales with the viewport, so proportions are identical everywhere.
  var CONFIG = {
    // sub = number of fine columns frames can snap to (so different widths nest together)
    wide:   { W: 1440, margin: 44, sub: 6, gutter: 14, bottom: 30,
              range: { portrait: [310, 500], square: [340, 470], landscape: [470, 690] } },
    // phones and tablets: the same collage as desktop, scaled with the screen, with slightly
    // larger frames so that two across is the norm (as in the mobile reference)
    narrow: { W: 1440, margin: 40, sub: 6, gutter: 12, bottom: 30, fixed: true,
              range: { portrait: [372, 600], square: [410, 565], landscape: [565, 830] } }
  };
  var mq = window.matchMedia('(min-width: 1000px)');
  var items = [];

  function lerp(a, b, t) { return a + (b - a) * t; }

  // small deterministic hash -> 0..1 (so every photo keeps the same personality)
  function hash01(seed, n) {
    var x = Math.sin((seed % 100003) * 12.9898 + n * 78.233) * 43758.5453;
    return x - Math.floor(x);
  }

  // Keep the manifest order, but never let three of one shape (or two of the same frame) sit
  // together: pull a different photo forward from the next few. Stable: only the tail changes
  // when photos are added.
  function mixOrder(list) {
    var rest = list.slice(), out = [];
    while (rest.length) {
      var pick = 0, a = out[out.length - 1], b = out[out.length - 2];
      var runOfThree = a && b && a.orientation === b.orientation && rest[0].orientation === a.orientation;
      var sameFrame = a && rest[0].frame && rest[0].frame === a.frame;
      if (runOfThree || sameFrame) {
        for (var j = 1; j < Math.min(rest.length, 6); j++) {
          var ok = (!runOfThree || rest[j].orientation !== a.orientation) && (!a || !rest[j].frame || rest[j].frame !== a.frame);
          if (ok) { pick = j; break; }
        }
      }
      out.push(rest.splice(pick, 1)[0]);
    }
    return out;
  }

  function computeLayout(list, cfg) {
    var sub = (!cfg.fixed && list.length < 3) ? Math.max(2, list.length * 2) : cfg.sub;   // very few photos: fewer, larger columns
    var subW = (cfg.W - 2 * cfg.margin - (sub - 1) * cfg.gutter) / sub;
    var colY = [];
    for (var i = 0; i < sub; i++) colY.push(0);
    var out = [];

    list.forEach(function (it) {
      var L = it.layout || {};
      var rng = range(cfg, it.orientation);
      var aspect = it.width / it.height;
      var w = lerp(rng[0], rng[1], clamp01(L.size == null ? 0.5 : L.size));
      var span = Math.min(sub, Math.max(1, Math.ceil((w - 1) / (subW + cfg.gutter))));
      var spanW = span * subW + (span - 1) * cfg.gutter;
      w = Math.min(w, spanW);
      var h = w / aspect;

      // choose where it nests best: low, flush against the edge or a neighbour (so free space
      // stays in one piece), with little wasted space underneath
      var best = -1, bestScore = Infinity, bestY = 0, bestSide = 'l';
      for (var pass = 0; pass < 2 && best < 0; pass++) {
        for (var c = 0; c + span <= sub; c++) {
          var y = 0, waste = 0, k;
          for (k = c; k < c + span; k++) y = Math.max(y, colY[k]);
          for (k = c; k < c + span; k++) waste += y - colY[k];
          var flushL = c === 0 || (colY[c - 1] > 0 && colY[c - 1] >= y - 1);
          var flushR = c + span === sub || (colY[c + span] > 0 && colY[c + span] >= y - 1);
          if (pass === 0 && !(flushL || flushR)) continue;          // pass 1: any spot at all
          var noise = hash01(L.seed || 1, c) * 70;                   // gentle variety, identical every visit
          var score = y + (waste / span) * 0.55 + noise;
          if (score < bestScore) { bestScore = score; best = c; bestY = y; bestSide = flushL && (!flushR || hash01(L.seed || 1, 99) < 0.5) ? 'l' : 'r'; }
        }
      }
      var slack = spanW - w;
      var jx = L.jitter_x == null ? 0 : L.jitter_x;                  // -1..1
      var t = (jx + 1) / 2;                                          // 0..1
      var x = cfg.margin + best * (subW + cfg.gutter) + slack * (bestSide === 'l' ? t * 0.35 : 1 - t * 0.35);
      var gap = bestY === 0 ? 0 : 14 + 46 * (L.jitter_y == null ? 0.5 : L.jitter_y);
      var yTop = bestY + gap;
      for (var m = best; m < best + span; m++) colY[m] = yTop + h + 4;
      out.push({ x: x, y: yTop, w: w, h: h, rot: L.rotation || 0 });
    });
    return { boxes: out, height: Math.max.apply(null, colY) + cfg.bottom };
  }
  function range(cfg, orientation) { return cfg.range[orientation] || cfg.range.portrait; }
  function clamp01(v) { return Math.max(0, Math.min(1, v)); }

  /* ---------- rendering ------------------------------------------------- */
  var io = ('IntersectionObserver' in window) ? new IntersectionObserver(function (entries) {
    entries.forEach(function (en) {
      if (en.isIntersecting) { en.target.classList.add('is-in'); io.unobserve(en.target); }
    });
  }, { rootMargin: '0px 0px -8% 0px' }) : null;

  function srcset(list, base) {
    return list.map(function (v) { return base + v.src + ' ' + v.w + 'w'; }).join(', ');
  }

  var base = '';
  function build() {
    var cfg = mq.matches ? CONFIG.wide : CONFIG.narrow;
    var lay = computeLayout(items, cfg);
    stage.style.aspectRatio = cfg.W + ' / ' + Math.round(lay.height);
    var existing = stage.children;
    var rebuild = existing.length !== items.length;
    if (rebuild) stage.textContent = '';

    items.forEach(function (it, i) {
      var b = lay.boxes[i];
      var fig = rebuild ? document.createElement('figure') : existing[i];
      if (rebuild) {
        fig.className = 'frame';
        fig.tabIndex = 0;
        fig.setAttribute('role', 'button');
        fig.setAttribute('aria-label', 'View larger: ' + (it.alt || 'painting'));
        fig.dataset.index = i;
        var pic = document.createElement('picture');
        ['avif', 'webp'].forEach(function (fmt) {
          if (it.sources && it.sources[fmt] && it.sources[fmt].length) {
            var s = document.createElement('source');
            s.type = 'image/' + fmt;
            s.srcset = srcset(it.sources[fmt], base);
            pic.appendChild(s);
          }
        });
        var img = document.createElement('img');
        var webp = (it.sources && it.sources.webp) || [];
        var fallback = webp[Math.floor((webp.length - 1) / 2)] || webp[0];
        img.src = base + fallback.src;
        img.width = it.width;
        img.height = it.height;
        img.alt = it.alt || '';
        if (it.title) img.title = it.title;
        img.loading = 'lazy';                                   // below the fold: load on demand
        img.decoding = 'async';
        pic.appendChild(img);
        fig.appendChild(pic);
        stage.appendChild(fig);
        if (io) io.observe(fig); else fig.classList.add('is-in');
      }
      fig.style.left = (b.x / cfg.W * 100).toFixed(3) + '%';
      fig.style.top = (b.y / cfg.W * 100).toFixed(3) + 'cqw';
      fig.style.width = (b.w / cfg.W * 100).toFixed(3) + '%';
      fig.style.setProperty('--rot', b.rot + 'deg');
      var sizes = (b.w / cfg.W * 100).toFixed(1) + 'vw';          // tells the browser which file to fetch
      [].forEach.call(fig.querySelectorAll('source'), function (s) { s.sizes = sizes; });
      fig.querySelector('img').sizes = sizes;
    });
  }
    var lb = document.getElementById('lightbox');
  var viewer = null;

  function setupLightbox() {
    if (viewer || !lb || typeof lb.showModal !== 'function') return;
    var picture = lb.querySelector('.lightbox__picture');
    var srcAvif = picture.querySelector('source[type="image/avif"]');
    var srcWebp = picture.querySelector('source[type="image/webp"]');
    var img = lb.querySelector('.lightbox__img');
    var count = lb.querySelector('.lightbox__count');
    var prevBtn = lb.querySelector('.lightbox__nav--prev');
    var nextBtn = lb.querySelector('.lightbox__nav--next');
    var closeBtn = lb.querySelector('.lightbox__close');
    var current = -1, closing = false, token = 0, opener = null;
    var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    // hidden picture used to warm the cache for the neighbouring paintings
    var warm = document.createElement('div');
    warm.setAttribute('aria-hidden', 'true');
    warm.style.cssText = 'position:absolute;width:0;height:0;overflow:hidden;opacity:0;pointer-events:none';
    document.body.appendChild(warm);

    function fill(it, dest) {                         // dest = {avif, webp, img}
      var S = it.sources || {};
      var sizes = '(max-width: 700px) 96vw, 80vw';
      if (S.avif && S.avif.length) { dest.avif.srcset = srcset(S.avif, base); dest.avif.sizes = sizes; } else dest.avif.removeAttribute('srcset');
      dest.webp.srcset = srcset(S.webp, base); dest.webp.sizes = sizes;
      var big = S.webp[S.webp.length - 1];
      dest.img.src = base + big.src;                   // largest version as the fallback
      dest.img.sizes = sizes;
    }

    function prefetch(i) {
      var it = items[(i + items.length) % items.length];
      var pic = document.createElement('picture');
      var a = document.createElement('source'), w = document.createElement('source'), im = document.createElement('img');
      a.type = 'image/avif'; w.type = 'image/webp';
      pic.appendChild(a); pic.appendChild(w); pic.appendChild(im);
      fill(it, { avif: a, webp: w, img: im });
      warm.textContent = '';
      warm.appendChild(pic);
    }

    function wrap(i) { return (i + items.length) % items.length; }

    function show(i, how) {                            // how: open | next | prev
      var my = ++token;
      current = wrap(i);
      var it = items[current];
      lb.classList.add('is-loading');
      img.classList.remove('anim-open', 'anim-next', 'anim-prev');
      fill(it, { avif: srcAvif, webp: srcWebp, img: img });
      img.alt = it.alt || '';
      count.textContent = (current + 1) + ' / ' + items.length;
      var ready = img.decode ? img.decode().catch(function () {}) : new Promise(function (r) { img.onload = r; });
      ready.then(function () {
        if (my !== token) return;                      // a newer request superseded this one
        lb.classList.remove('is-loading');
        if (!reduce) { void img.offsetWidth; img.classList.add('anim-' + how); }
        prefetch(current + 1);
        setTimeout(function () { if (my === token) prefetch(current - 1); }, 700);
      });
    }

    function open(i, from) {
      if (lb.open) return;
      opener = from || null;
      closing = false;
      lb.classList.toggle('is-single', items.length < 2);
      lb.showModal();
      show(i, 'open');
      requestAnimationFrame(function () { requestAnimationFrame(function () { lb.classList.add('is-open'); }); });
      closeBtn.focus({ preventScroll: true });
    }

    function close() {
      if (!lb.open || closing) return;
      closing = true;
      lb.classList.remove('is-open');
      var done = function () {
        if (lb.open) lb.close();
        closing = false;
        if (opener && opener.focus) opener.focus({ preventScroll: true });
      };
      if (reduce) done(); else setTimeout(done, 480);
    }

    function step(d) { if (items.length > 1 && lb.open && !closing) show(current + d, d > 0 ? 'next' : 'prev'); }

    prevBtn.addEventListener('click', function () { step(-1); });
    nextBtn.addEventListener('click', function () { step(1); });
    closeBtn.addEventListener('click', close);
    lb.addEventListener('cancel', function (e) { e.preventDefault(); close(); });          // Esc
    lb.addEventListener('click', function (e) {                                            // click on the veil
      if (e.target === lb || e.target.classList.contains('lightbox__figure')) close();
    });
    lb.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowRight') { e.preventDefault(); step(1); }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); step(-1); }
    });
    // keep the page behind from scrolling while the viewer is open
    ['wheel', 'touchmove'].forEach(function (ev) {
      lb.addEventListener(ev, function (e) { e.preventDefault(); }, { passive: false });
    });
    // swipe left / right
    var sx = null, sy = 0;
    lb.addEventListener('pointerdown', function (e) { if (e.pointerType !== 'mouse') { sx = e.clientX; sy = e.clientY; } });
    lb.addEventListener('pointerup', function (e) {
      if (sx === null) return;
      var dx = e.clientX - sx, dy = e.clientY - sy; sx = null;
      if (Math.abs(dx) > 48 && Math.abs(dx) > Math.abs(dy) * 1.4) step(dx < 0 ? 1 : -1);
    });
    lb.addEventListener('pointercancel', function () { sx = null; });

    // open from the gallery (click, Enter or Space)
    function figureOf(t) { return t.closest ? t.closest('.frame') : null; }
stage.addEventListener('click', function (e) {
  var f = figureOf(e.target);
  if (f) open(+f.dataset.index, f);
});
    stage.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      var f = figureOf(e.target); if (f) { e.preventDefault(); open(+f.dataset.index, f); }
    });
    viewer = { open: open, close: close };
  }


  function showNote(text) { note.textContent = text; note.hidden = false; }

  loadManifest().then(function (m) {
    base = 'gallery/';
    items = (m.items || []).filter(function (it) {
      return it && it.sources && it.sources.webp && it.sources.webp.length && it.width && it.height;
    });
    if (!items.length) {
      showNote('The archive is being prepared. Add photographs to gallery/images and run process_images.py.');
      return;
    }
    items = mixOrder(items);
    build();
        setupLightbox();

    var t;
    (mq.addEventListener ? mq.addEventListener.bind(mq, 'change') : mq.addListener.bind(mq))(function () {
      clearTimeout(t); t = setTimeout(build, 60);
    });
  }).catch(function () {
    showNote('The gallery could not be loaded. If you opened this page from disk, start serve.py and visit the address it prints.');
  });
})();
