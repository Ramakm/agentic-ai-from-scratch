/* Interview pages: search and filters on /interviews/, reveal, "practiced" progress (localStorage),
   and a random-question button. The content itself is static HTML written by scripts/build.mjs. */
(function () {
  'use strict';
  var KEY = 'aafs-interviews-done';
  function load() { try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch (e) { return {}; } }
  function save(d) { try { localStorage.setItem(KEY, JSON.stringify(d)); } catch (e) {} }
  var done = load();

  /* ---------- index ---------- */
  var list = document.getElementById('ivList');
  if (list) {
    var rows = Array.prototype.slice.call(list.querySelectorAll('.iv-row'));
    var $ = function (id) { return document.getElementById(id); };
    var search = $('ivSearch'), level = $('ivLevel'), type = $('ivType'), card = $('ivCard'), hide = $('ivHideDone');
    var params = new URLSearchParams(location.search);
    if (params.get('card')) card.value = params.get('card');
    if (params.get('level')) level.value = params.get('level');
    if (params.get('q')) search.value = params.get('q');

    var marks = function () {
      rows.forEach(function (r) { r.querySelector('.iv-row-done').hidden = !done[r.dataset.id]; r.classList.toggle('is-done', !!done[r.dataset.id]); });
      $('ivDoneCount').textContent = Object.keys(done).filter(function (k) { return done[k]; }).length;
    };
    var apply = function () {
      var words = search.value.toLowerCase().split(/\s+/).filter(Boolean), shown = 0;
      rows.forEach(function (r) {
        var ok = (!level.value || r.dataset.level === level.value) && (!type.value || r.dataset.type === type.value) &&
          (!card.value || r.dataset.card === card.value) && (!hide.checked || !done[r.dataset.id]) &&
          words.every(function (w) { return r.dataset.text.indexOf(w) !== -1; });
        r.hidden = !ok;
        if (ok) shown++;
      });
      $('ivCount').textContent = shown + (shown === 1 ? ' question' : ' questions');
      $('ivEmpty').hidden = shown > 0;
      document.querySelectorAll('[data-card-filter]').forEach(function (b) { b.classList.toggle('is-active', b.dataset.cardFilter === card.value); });
      var q = new URLSearchParams();
      if (card.value) q.set('card', card.value);
      if (level.value) q.set('level', level.value);
      if (search.value) q.set('q', search.value);
      history.replaceState(null, '', location.pathname + (q.toString() ? '?' + q : ''));
    };
    [search, level, type, card, hide].forEach(function (el) { el.addEventListener('input', apply); el.addEventListener('change', apply); });
    document.querySelectorAll('[data-card-filter]').forEach(function (b) {
      b.addEventListener('click', function () {
        card.value = card.value === b.dataset.cardFilter ? '' : b.dataset.cardFilter;
        apply();
        list.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    });
    $('ivRandom').addEventListener('click', function () {
      var pool = rows.filter(function (r) { return !r.hidden && !done[r.dataset.id]; });
      if (!pool.length) pool = rows.filter(function (r) { return !r.hidden; });
      if (pool.length) location.href = pool[Math.floor(Math.random() * pool.length)].querySelector('a').href;
    });
    marks();
    apply();
  }

  /* ---------- question page ---------- */
  var q = document.querySelector('.iv-question');
  if (q) {
    var id = q.dataset.id, mark = document.getElementById('ivMark');
    var paint = function () {
      mark.textContent = done[id] ? 'Practiced ✓' : 'Mark as practiced';
      mark.classList.toggle('btn--primary', !done[id]);
    };
    mark.addEventListener('click', function () { done[id] = !done[id]; if (!done[id]) delete done[id]; save(done); paint(); });
    paint();
    var all = JSON.parse(document.getElementById('ivAll').textContent);
    document.getElementById('ivRandom').addEventListener('click', function () {
      var pool = all.filter(function (h) { return !done[h.replace(/^\/interviews\/|\/$/g, '')] && h !== location.pathname; });
      if (!pool.length) pool = all;
      location.href = pool[Math.floor(Math.random() * pool.length)];
    });
    /* Opening the full answer also opens the short one, so the page reads top to bottom. */
    var reveals = q.querySelectorAll('.iv-reveal');
    if (reveals[1]) reveals[1].addEventListener('toggle', function () { if (reveals[1].open) reveals[0].open = true; });
    if (window.hljs) q.querySelectorAll('pre code').forEach(function (b) { window.hljs.highlightElement(b); });
  }
})();
