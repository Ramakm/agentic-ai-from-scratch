/* Home page: phase cards, lesson drawer, books, marquee, reveal. Needs common.js. */
(function () {
  'use strict';

  var A = window.AAFS, PHASES = A.PHASES, esc = A.esc, pad = A.pad;

  /* ---------- phase cards ---------- */
  var grid = document.getElementById('phaseGrid');
  var cardsRendered = false;

  function nextPhaseIndex() {
    for (var i = 0; i < PHASES.length; i++) {
      var live = PHASES[i].lessons.filter(function (l) { return l.published; });
      if (live.length && live.some(function (l) { return !A.isDone(l); })) return i;
    }
    return -1;
  }

  function renderCards() {
    var next = nextPhaseIndex();
    grid.innerHTML = PHASES.map(function (p, i) {
      var n = p.lessons.length, done = A.doneCount(p), pct = Math.round(done / n * 100);
      var mins = p.lessons.reduce(function (s, l) { return s + l.minutes; }, 0);
      var cls = 'phase-card' + (i === next ? ' is-next' : '') + (done ? ' is-started' : '') + (cardsRendered ? '' : ' reveal');
      var action = done === n ? 'Complete ✓' : done ? 'Continue →' : i === next ? 'Start →' : p.published ? 'Open →' : 'Planned';
      return '<button class="' + cls + '" type="button" data-open-phase="' + i + '" style="--d:' + (i % 4) * 40 + 'ms">' +
        '<span class="phase-card-top"><span class="phase-card-num"><i class="status ' + p.status + '"></i>Phase ' + pad(i) + '</span>' +
        '<span>' + n + ' lessons · ' + Math.round(mins / 60) + 'h</span></span>' +
        '<span class="phase-card-name">' + esc(p.name) + '</span>' +
        '<span class="phase-card-desc">' + esc(p.desc) + '</span>' +
        '<span class="phase-card-bar"><span style="width:' + pct + '%"></span></span>' +
        '<span class="phase-card-foot"><span>' + done + '/' + n + ' done' + (p.published ? ' · ' + p.published + ' live' : '') + '</span>' +
        '<span class="phase-card-action">' + action + '</span></span></button>';
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
  var booksGrid = document.getElementById('booksGrid');
  if (booksGrid) booksGrid.innerHTML = BOOKS.map(function (b, i) {
    var count = PHASES.slice(b.range[0], b.range[1] + 1).reduce(function (s, p) { return s + p.lessons.length; }, 0);
    return '<article class="book reveal" style="--d:' + i * 50 + 'ms">' +
      '<div class="book-cover"><span class="book-vol">Vol. ' + b.vol + ' · Phases ' + pad(b.range[0]) + '–' + pad(b.range[1]) + '</span>' +
      '<span class="book-name">' + b.name + '</span><span class="book-glyph" aria-hidden="true">' + b.vol + '</span></div>' +
      '<div class="book-meta"><p>' + b.blurb + ' ' + count + ' chapters.</p><span class="book-status">In the works · ships with v1.0</span></div></article>';
  }).join('');

  /* ---------- phase drawer ---------- */
  var overlay = document.getElementById('phaseOverlay');
  var lessonsEl = document.getElementById('modalLessons');
  var searchEl = document.getElementById('modalSearch');
  var current = null;

  function openPhase(i, lessonIdx) {
    current = PHASES[i];
    document.getElementById('modalNum').innerHTML = '<i class="status ' + current.status + '"></i>Phase ' + pad(i) + ' · ' +
      current.published + ' of ' + current.lessons.length + ' live';
    document.getElementById('modalTitle').textContent = current.name;
    document.getElementById('modalDesc').textContent = current.desc;
    document.getElementById('modalRepo').href = A.REPO_URL + '/tree/main/phases/' + current.id;
    searchEl.value = '';
    renderLessons();
    A.openOverlay(overlay, searchEl);
    lessonsEl.scrollTop = 0;
    if (lessonIdx != null) {
      var row = lessonsEl.querySelector('[data-idx="' + lessonIdx + '"]');
      if (row) setTimeout(function () {
        row.scrollIntoView({ block: 'center' });
        row.classList.add('flash');
        setTimeout(function () { row.classList.remove('flash'); }, 1400);
      }, 120);
    }
  }
  A.openPhase = openPhase;

  function renderLessons() {
    var q = searchEl.value.trim().toLowerCase();
    var rows = current.lessons.map(function (l, j) {
      if (q && l.title.toLowerCase().indexOf(q) === -1) return '';
      var done = A.isDone(l);
      var name = l.published
        ? '<a href="' + A.lessonHref(l) + '">' + esc(l.title) + '</a>'
        : esc(l.title) + ' <span class="lesson-tag">planned</span>';
      return '<li class="lesson-row' + (done ? ' is-done' : '') + (l.published ? '' : ' is-planned') + '" data-idx="' + j + '">' +
        '<input type="checkbox" class="lesson-check" data-idx="' + j + '"' + (done ? ' checked' : '') + (l.published ? '' : ' disabled') +
        ' aria-label="Mark ' + esc(l.title) + ' done">' +
        '<span class="lesson-num">' + l.num + '</span><span class="lesson-name">' + name + '</span>' +
        '<span class="lesson-time">' + l.minutes + ' min</span></li>';
    }).join('');
    lessonsEl.innerHTML = rows || '<li class="palette-empty">No lessons match "' + esc(q) + '".</li>';
    var done = A.doneCount(current), n = current.lessons.length, pct = Math.round(done / n * 100);
    document.getElementById('modalCount').textContent = done + ' of ' + n + ' lessons done';
    document.getElementById('modalPct').textContent = pct + '%';
    document.getElementById('modalBar').style.width = pct + '%';
  }

  lessonsEl.addEventListener('change', function (e) {
    if (!e.target.classList.contains('lesson-check')) return;
    A.setDone(current.lessons[+e.target.getAttribute('data-idx')], e.target.checked);
    renderLessons(); renderCards();
  });
  searchEl.addEventListener('input', renderLessons);
  document.getElementById('modalReset').addEventListener('click', function () {
    current.lessons.forEach(function (l) { A.setDone(l, false); });
    renderLessons(); renderCards();
  });
  document.getElementById('modalClose').addEventListener('click', function () { A.closeOverlay(overlay); });
  overlay.addEventListener('click', function (e) { if (e.target === overlay) A.closeOverlay(overlay); });

  /* buttons with data-open-phase open the drawer; data-open-lesson goes straight to a live lesson */
  document.addEventListener('click', function (e) {
    var t = e.target.closest('[data-open-phase]');
    if (!t) return;
    e.preventDefault();
    var i = parseInt(t.getAttribute('data-open-phase'), 10);
    var j = t.getAttribute('data-lesson');
    var lesson = j == null ? null : PHASES[i].lessons[+j];
    if (lesson && lesson.published && t.hasAttribute('data-go')) { location.href = A.lessonHref(lesson); return; }
    openPhase(i, j == null ? null : +j);
  });

  /* turn entry-point buttons into real links when their lesson is live (keeps middle-click working) */
  document.querySelectorAll('[data-go][data-lesson]').forEach(function (el) {
    var l = PHASES[+el.getAttribute('data-open-phase')].lessons[+el.getAttribute('data-lesson')];
    if (l && l.published && el.tagName === 'A') el.href = A.lessonHref(l);
  });

  /* ---------- marquee (duplicate for a seamless loop) ---------- */
  var track = document.getElementById('marqueeTrack');
  if (track) {
    var half = track.querySelector('.marquee-half').cloneNode(true);
    half.setAttribute('aria-hidden', 'true');
    track.appendChild(half);
  }

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

  /* ---------- deep link: ?phase=3&lesson=0 opens the drawer ---------- */
  var qs = new URLSearchParams(location.search);
  if (qs.has('phase') && PHASES[+qs.get('phase')]) openPhase(+qs.get('phase'), qs.has('lesson') ? +qs.get('lesson') : null);
})();
