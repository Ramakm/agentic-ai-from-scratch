(function () {
  'use strict';

  var SITE = window.SITE, PHASES = window.PHASES;
  var REPO_URL = 'https://github.com/' + SITE.repo;
  var STORE_KEY = 'aafs-progress';

  /* ---------- data ---------- */
  PHASES.forEach(function (p, i) {
    p.index = i;
    var n = p.lessons.length;
    var published = p.status === 'complete' ? n : p.status === 'in-progress' ? Math.ceil(n * 0.6) : 0;
    p.items = p.lessons.map(function (raw, j) {
      var parts = raw.split('|');
      var title = parts[0];
      return {
        id: p.slug + '/' + j,
        title: title,
        mins: parseInt(parts[1], 10) || 0,
        num: String(i).padStart(2, '0') + '.' + String(j + 1).padStart(2, '0'),
        published: j < published,
        href: REPO_URL + '/tree/main/phases/' + p.slug + '/' + String(j + 1).padStart(2, '0') + '-' + slugify(title),
      };
    });
  });
  var ALL = [];
  PHASES.forEach(function (p) { p.items.forEach(function (it) { ALL.push({ phase: p, item: it }); }); });
  var totalLessons = ALL.length;
  var totalHours = Math.round(ALL.reduce(function (s, x) { return s + x.item.mins; }, 0) / 60);

  function slugify(s) { return s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''); }
  function esc(s) { return s.replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function pad(i) { return String(i).padStart(2, '0'); }

  /* ---------- progress (browser-only, guarded) ---------- */
  var progress = {};
  try { progress = JSON.parse(localStorage.getItem(STORE_KEY) || '{}') || {}; } catch (e) { progress = {}; }
  function saveProgress() { try { localStorage.setItem(STORE_KEY, JSON.stringify(progress)); } catch (e) {} }
  function doneCount(p) { return p.items.filter(function (it) { return progress[it.id]; }).length; }

  /* ---------- fill counts + repo links ---------- */
  document.querySelectorAll('[data-lesson-count]').forEach(function (el) { el.textContent = totalLessons + ' lessons'; });
  document.querySelectorAll('[data-phase-count]').forEach(function (el) { el.textContent = PHASES.length + ' phases'; });
  document.querySelectorAll('[data-lesson-num]').forEach(function (el) { el.textContent = totalLessons; });
  document.querySelectorAll('[data-phase-num]').forEach(function (el) { el.textContent = PHASES.length; });
  document.querySelectorAll('[data-hours-num]').forEach(function (el) { el.textContent = totalHours; });
  document.querySelectorAll('[data-maintainer]').forEach(function (el) { el.textContent = SITE.maintainer; });
  document.querySelectorAll('[data-repo-link]').forEach(function (el) { el.href = REPO_URL + (el.getAttribute('data-repo-link') || ''); });
  document.querySelectorAll('[data-install-cmd]').forEach(function (el) { el.textContent = 'npx skills add ' + SITE.repo; });
  document.getElementById('installCmdText').textContent = 'npx skills add ' + SITE.repo;
  document.getElementById('cloneCmdText').textContent = 'git clone ' + REPO_URL + '.git';
  document.getElementById('paletteInput').placeholder = 'Search ' + totalLessons + ' lessons…';

  /* ---------- phase cards ---------- */
  var grid = document.getElementById('phaseGrid');
  var cardsRendered = false;
  function nextPhaseIndex() {
    for (var i = 0; i < PHASES.length; i++) {
      var p = PHASES[i], pub = p.items.filter(function (x) { return x.published; }).length;
      if (pub && doneCount(p) < pub) return i;
    }
    return -1;
  }
  function renderCards() {
    var next = nextPhaseIndex();
    grid.innerHTML = PHASES.map(function (p, i) {
      var done = doneCount(p), n = p.items.length, pct = Math.round(done / n * 100);
      var mins = p.items.reduce(function (s, x) { return s + x.mins; }, 0);
      var cls = 'phase-card' + (i === next ? ' is-next' : '') + (done ? ' is-started' : '');
      var action = done === n ? 'Complete ✓' : done ? 'Continue →' : i === next ? 'Start here →' : p.status === 'planned' ? 'Planned' : 'Open →';
      return '<button class="' + cls + (cardsRendered ? '' : ' reveal') + '" type="button" data-open-phase="' + i + '" style="--d:' + (i % 4) * 40 + 'ms">' +
        '<span class="phase-card-top"><span class="phase-card-num"><i class="status ' + p.status + '"></i>Phase ' + pad(i) + '</span>' +
        '<span>' + n + ' lessons · ' + Math.round(mins / 60) + 'h</span></span>' +
        '<span class="phase-card-name">' + esc(p.name) + '</span>' +
        '<span class="phase-card-desc">' + esc(p.desc) + '</span>' +
        '<span class="phase-card-bar"><span style="width:' + pct + '%"></span></span>' +
        '<span class="phase-card-foot"><span>' + done + ' / ' + n + ' done</span><span class="phase-card-action">' + action + '</span></span>' +
        '</button>';
    }).join('');
    if (!cardsRendered) observeReveals(grid);
    cardsRendered = true;
  }

  /* ---------- books ---------- */
  var BOOKS = [
    { vol: 'I', name: 'The Loop', range: [0, 3], blurb: 'Setup, model foundations, tool use, and the agent loop.' },
    { vol: 'II', name: 'Memory & Mind', range: [4, 6], blurb: 'Context engineering, agentic retrieval, planning, and reflection.' },
    { vol: 'III', name: 'Many Agents', range: [7, 10], blurb: 'MCP, multi-agent systems, frameworks, and coding agents.' },
    { vol: 'IV', name: 'Shipping Agents', range: [11, 15], blurb: 'Evals, security, production, UX, and the capstone harness.' },
  ];
  document.getElementById('booksGrid').innerHTML = BOOKS.map(function (b, i) {
    var count = PHASES.slice(b.range[0], b.range[1] + 1).reduce(function (s, p) { return s + p.items.length; }, 0);
    var rel = REPO_URL + '/releases/latest';
    return '<article class="book reveal" style="--d:' + i * 50 + 'ms">' +
      '<div class="book-cover"><span class="book-vol">Vol. ' + b.vol + ' · Phases ' + pad(b.range[0]) + '–' + pad(b.range[1]) + '</span>' +
      '<span class="book-name">' + b.name + '</span><span class="book-glyph" aria-hidden="true">' + b.vol + '</span></div>' +
      '<div class="book-meta"><p>' + b.blurb + ' ' + count + ' chapters.</p>' +
      '<div class="book-links"><a class="copy-chip" href="' + rel + '" target="_blank" rel="noopener">EPUB</a>' +
      '<a class="copy-chip" href="' + rel + '" target="_blank" rel="noopener">PDF</a></div></div></article>';
  }).join('');

  /* ---------- overlays ---------- */
  var lastFocus = null;
  function openOverlay(el, focusEl) {
    lastFocus = document.activeElement;
    el.classList.add('open'); el.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
    setTimeout(function () { (focusEl || el).focus(); }, 30);
  }
  function closeOverlay(el) {
    el.classList.remove('open'); el.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
    if (lastFocus) lastFocus.focus();
  }

  /* ---------- phase drawer ---------- */
  var phaseOverlay = document.getElementById('phaseOverlay');
  var lessonsEl = document.getElementById('modalLessons');
  var searchEl = document.getElementById('modalSearch');
  var current = null;

  function openPhase(i, lessonIdx) {
    current = PHASES[i];
    document.getElementById('modalNum').innerHTML = '<i class="status ' + current.status + '"></i>Phase ' + pad(i) + ' · ' + current.status.replace('-', ' ');
    document.getElementById('modalTitle').textContent = current.name;
    document.getElementById('modalDesc').textContent = current.desc;
    searchEl.value = '';
    renderLessons();
    openOverlay(phaseOverlay, searchEl);
    lessonsEl.scrollTop = 0;
    if (lessonIdx != null) {
      var row = lessonsEl.querySelector('[data-idx="' + lessonIdx + '"]');
      if (row) {
        setTimeout(function () {
          row.scrollIntoView({ block: 'center' });
          row.classList.add('flash');
          setTimeout(function () { row.classList.remove('flash'); }, 1400);
        }, 120);
      }
    }
  }
  function renderLessons() {
    var q = searchEl.value.trim().toLowerCase();
    var rows = current.items.map(function (it, j) {
      if (q && it.title.toLowerCase().indexOf(q) === -1) return '';
      var done = !!progress[it.id];
      var name = it.published
        ? '<a href="' + it.href + '" target="_blank" rel="noopener">' + esc(it.title) + '</a>'
        : esc(it.title) + ' <span class="lesson-time">· planned</span>';
      return '<li class="lesson-row' + (done ? ' is-done' : '') + (it.published ? '' : ' is-planned') + '" data-idx="' + j + '">' +
        '<input type="checkbox" class="lesson-check" data-id="' + it.id + '"' + (done ? ' checked' : '') + (it.published ? '' : ' disabled') + ' aria-label="Mark ' + esc(it.title) + ' done">' +
        '<span class="lesson-num">' + it.num + '</span><span class="lesson-name">' + name + '</span>' +
        '<span class="lesson-time">' + it.mins + ' min</span></li>';
    }).join('');
    lessonsEl.innerHTML = rows || '<li class="palette-empty">No lessons match "' + esc(q) + '".</li>';
    var done = doneCount(current), n = current.items.length, pct = Math.round(done / n * 100);
    document.getElementById('modalCount').textContent = done + ' of ' + n + ' lessons done';
    document.getElementById('modalPct').textContent = pct + '%';
    document.getElementById('modalBar').style.width = pct + '%';
  }
  lessonsEl.addEventListener('change', function (e) {
    var t = e.target;
    if (!t.classList.contains('lesson-check')) return;
    if (t.checked) progress[t.dataset.id] = 1; else delete progress[t.dataset.id];
    saveProgress(); renderLessons(); renderCards();
  });
  searchEl.addEventListener('input', renderLessons);
  document.getElementById('modalReset').addEventListener('click', function () {
    current.items.forEach(function (it) { delete progress[it.id]; });
    saveProgress(); renderLessons(); renderCards();
  });
  document.getElementById('modalClose').addEventListener('click', function () { closeOverlay(phaseOverlay); });
  phaseOverlay.addEventListener('click', function (e) { if (e.target === phaseOverlay) closeOverlay(phaseOverlay); });

  document.addEventListener('click', function (e) {
    var t = e.target.closest('[data-open-phase]');
    if (!t) return;
    e.preventDefault();
    var l = t.getAttribute('data-lesson');
    openPhase(parseInt(t.getAttribute('data-open-phase'), 10), l == null ? null : parseInt(l, 10));
  });

  /* ---------- command palette ---------- */
  var palOverlay = document.getElementById('paletteOverlay');
  var palInput = document.getElementById('paletteInput');
  var palList = document.getElementById('paletteList');
  var palResults = [], palSel = 0;

  function renderPalette() {
    var q = palInput.value.trim().toLowerCase();
    palResults = ALL.filter(function (x) {
      return !q || x.item.title.toLowerCase().indexOf(q) > -1 || x.phase.name.toLowerCase().indexOf(q) > -1;
    }).slice(0, 40);
    palSel = Math.min(palSel, Math.max(palResults.length - 1, 0));
    palList.innerHTML = palResults.length ? palResults.map(function (x, i) {
      return '<li class="palette-item" role="option" data-i="' + i + '" aria-selected="' + (i === palSel) + '">' +
        '<span class="pi-phase">' + x.item.num + '</span><span class="pi-name">' + esc(x.item.title) + '</span>' +
        '<span class="pi-time">' + x.item.mins + ' min</span></li>';
    }).join('') : '<li class="palette-empty">Nothing matches. Try "memory", "MCP" or "eval".</li>';
  }
  function choose(i) {
    var r = palResults[i]; if (!r) return;
    closeOverlay(palOverlay);
    openPhase(r.phase.index, r.phase.items.indexOf(r.item));
  }
  function openPalette() { palInput.value = ''; palSel = 0; renderPalette(); openOverlay(palOverlay, palInput); }
  palInput.addEventListener('input', function () { palSel = 0; renderPalette(); });
  palInput.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowDown') { palSel = Math.min(palSel + 1, palResults.length - 1); renderPalette(); scrollSel(); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { palSel = Math.max(palSel - 1, 0); renderPalette(); scrollSel(); e.preventDefault(); }
    else if (e.key === 'Enter') { choose(palSel); }
  });
  function scrollSel() { var el = palList.querySelector('[aria-selected="true"]'); if (el) el.scrollIntoView({ block: 'nearest' }); }
  palList.addEventListener('click', function (e) { var li = e.target.closest('.palette-item'); if (li) choose(+li.dataset.i); });
  palOverlay.addEventListener('click', function (e) { if (e.target === palOverlay) closeOverlay(palOverlay); });
  document.getElementById('searchToggle').addEventListener('click', openPalette);

  document.addEventListener('keydown', function (e) {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); palOverlay.classList.contains('open') ? closeOverlay(palOverlay) : openPalette(); }
    else if (e.key === '/' && !/input|textarea/i.test(document.activeElement.tagName) && !document.querySelector('.overlay.open')) { e.preventDefault(); openPalette(); }
    else if (e.key === 'Escape') {
      if (palOverlay.classList.contains('open')) closeOverlay(palOverlay);
      else if (phaseOverlay.classList.contains('open')) closeOverlay(phaseOverlay);
    }
  });

  /* ---------- theme ---------- */
  var root = document.documentElement, themeIcon = document.getElementById('themeIcon');
  function syncThemeIcon() { themeIcon.textContent = root.getAttribute('data-theme') === 'dark' ? 'D' : 'N'; }
  syncThemeIcon();
  document.getElementById('themeToggle').addEventListener('click', function () {
    var t = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', t);
    try { localStorage.setItem('aafs-theme', t); } catch (e) {}
    syncThemeIcon();
  });

  /* ---------- mobile menu ---------- */
  var nav = document.getElementById('headerNav'), menuBtn = document.getElementById('menuToggle');
  menuBtn.addEventListener('click', function () {
    var open = nav.classList.toggle('open');
    menuBtn.setAttribute('aria-expanded', open);
  });
  nav.addEventListener('click', function (e) { if (e.target.closest('a')) { nav.classList.remove('open'); menuBtn.setAttribute('aria-expanded', 'false'); } });

  /* ---------- copy chips ---------- */
  document.querySelectorAll('[data-copy-target]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var text = document.getElementById(btn.dataset.copyTarget).textContent;
      var done = function () {
        btn.classList.add('copied'); btn.textContent = 'copied';
        setTimeout(function () { btn.classList.remove('copied'); btn.textContent = 'copy'; }, 1400);
      };
      if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, done); else done();
    });
  });

  /* ---------- marquee (duplicate for seamless loop) ---------- */
  var track = document.getElementById('marqueeTrack');
  var half = track.querySelector('.marquee-half').cloneNode(true);
  half.setAttribute('aria-hidden', 'true');
  track.appendChild(half);

  /* ---------- reveal on scroll ---------- */
  var io = null;
  if ('IntersectionObserver' in window && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
    document.body.classList.add('js-anim');
    io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) { if (en.isIntersecting) { en.target.classList.add('in-view'); io.unobserve(en.target); } });
    }, { rootMargin: '0px 0px -40px 0px' });
  }
  function observeReveals(scope) {
    if (!io) return;
    scope.querySelectorAll('.reveal:not(.in-view)').forEach(function (el) { io.observe(el); });
  }

  renderCards();
  observeReveals(document);
})();
