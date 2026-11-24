/* Shared by every page: theme, menu, search palette, socials, GitHub stars, copy chips, progress. */
(function () {
  'use strict';

  var SITE = window.SITE, PHASES = window.PHASES;
  var REPO_URL = 'https://github.com/' + SITE.repo;
  var STORE_KEY = 'aafs-progress';

  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function pad(i) { return String(i).padStart(2, '0'); }
  function storage(fn, fallback) { try { return fn(); } catch (e) { return fallback; } }

  PHASES.forEach(function (p, i) { p.index = i; p.lessons.forEach(function (l, j) { l.phase = p; l.index = j; }); });
  var ALL = [];
  PHASES.forEach(function (p) { p.lessons.forEach(function (l) { ALL.push(l); }); });

  function lessonHref(l) { return 'lesson.html?path=' + encodeURIComponent(l.path); }
  function findLesson(path) { for (var i = 0; i < ALL.length; i++) if (ALL[i].path === path) return ALL[i]; return null; }

  /* ---------- progress (browser only) ---------- */
  var progress = storage(function () { return JSON.parse(localStorage.getItem(STORE_KEY) || '{}') || {}; }, {});
  function saveProgress() { storage(function () { localStorage.setItem(STORE_KEY, JSON.stringify(progress)); }); }
  function isDone(l) { return !!progress[l.path]; }
  function setDone(l, done) { if (done) progress[l.path] = 1; else delete progress[l.path]; saveProgress(); }
  function doneCount(p) { return p.lessons.filter(isDone).length; }

  /* ---------- icons ---------- */
  var ICONS = {
    linkedin: '<path fill="currentColor" d="M20.45 20.45h-3.55v-5.57c0-1.33-.03-3.04-1.85-3.04-1.85 0-2.14 1.45-2.14 2.94v5.67H9.35V9h3.41v1.56h.05c.48-.9 1.64-1.85 3.37-1.85 3.6 0 4.27 2.37 4.27 5.46v6.28zM5.34 7.43a2.06 2.06 0 1 1 0-4.13 2.06 2.06 0 0 1 0 4.13zM7.12 20.45H3.56V9h3.56v11.45zM22.22 0H1.77C.79 0 0 .77 0 1.73v20.54C0 23.23.79 24 1.77 24h20.45c.98 0 1.78-.77 1.78-1.73V1.73C24 .77 23.2 0 22.22 0z"/>',
    x: '<path fill="currentColor" d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/>',
    github: '<path fill="currentColor" d="M12 .3a12 12 0 0 0-3.8 23.38c.6.12.82-.26.82-.58v-2.03c-3.34.73-4.04-1.6-4.04-1.6-.55-1.4-1.34-1.77-1.34-1.77-1.08-.74.09-.73.09-.73 1.2.09 1.84 1.24 1.84 1.24 1.07 1.83 2.8 1.3 3.49 1 .1-.78.42-1.3.76-1.6-2.67-.3-5.47-1.33-5.47-5.93 0-1.31.47-2.38 1.24-3.22-.14-.3-.54-1.52.1-3.18 0 0 1.01-.32 3.3 1.23a11.5 11.5 0 0 1 6 0c2.28-1.55 3.29-1.23 3.29-1.23.64 1.66.24 2.88.12 3.18a4.65 4.65 0 0 1 1.23 3.22c0 4.61-2.8 5.62-5.48 5.92.43.37.82 1.1.82 2.22v3.29c0 .32.21.7.82.58A12 12 0 0 0 12 .3"/>',
    instagram: '<rect x="3" y="3" width="18" height="18" rx="5" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="12" cy="12" r="4" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="17.5" cy="6.5" r="1.3" fill="currentColor"/>',
    threads: '<path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M19.2 8.3C18 4.9 15.4 3 12 3 6.9 3 4 6.6 4 12s2.9 9 8 9c3.5 0 6.1-1.7 7-4.4M16.4 11.6c-.4-2.6-2-4-4.4-4-2.5 0-4.2 1.8-4.2 4.5"/><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M16.4 11.6c.1 3-1.6 4.6-4.1 4.6-1.6 0-2.7-.9-2.7-2.1 0-1.4 1.3-2.2 3.2-2.2 1.3 0 2.6.2 3.6.7"/>',
    medium: '<circle cx="7" cy="12" r="5.5" fill="currentColor"/><ellipse cx="16" cy="12" rx="2.7" ry="5.2" fill="currentColor"/><ellipse cx="21.4" cy="12" rx="1.1" ry="4.7" fill="currentColor"/>',
    web: '<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="1.8"/><ellipse cx="12" cy="12" rx="4" ry="9" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M3 12h18" stroke="currentColor" stroke-width="1.8"/>',
  };
  function icon(id, size) { return '<svg class="ico" width="' + (size || 16) + '" height="' + (size || 16) + '" viewBox="0 0 24 24" aria-hidden="true">' + (ICONS[id] || ICONS.web) + '</svg>'; }

  /* ---------- static fills ---------- */
  var T = SITE.totals, M = SITE.maintainer;
  function fill(sel, fn) { document.querySelectorAll(sel).forEach(fn); }
  fill('[data-lesson-count]', function (el) { el.textContent = T.lessons + ' lessons'; });
  fill('[data-phase-count]', function (el) { el.textContent = T.phases + ' phases'; });
  fill('[data-live-count]', function (el) { el.textContent = T.published; });
  fill('[data-lesson-num]', function (el) { el.textContent = T.lessons; });
  fill('[data-phase-num]', function (el) { el.textContent = T.phases; });
  fill('[data-hours-num]', function (el) { el.textContent = T.hours; });
  fill('[data-maintainer]', function (el) { el.textContent = M.name; });
  fill('[data-maintainer-role]', function (el) { el.textContent = M.role; });
  fill('[data-maintainer-avatar]', function (el) { el.src = M.avatar; el.alt = M.name; });
  fill('[data-handle]', function (el) { el.textContent = M.handle; });
  fill('[data-social-link]', function (el) {
    var s = M.socials.filter(function (x) { return x.id === el.getAttribute('data-social-link'); })[0];
    if (s) el.href = s.url;
  });
  fill('[data-repo-link]', function (el) { el.href = REPO_URL + (el.getAttribute('data-repo-link') || ''); });
  fill('[data-install-cmd]', function (el) { el.textContent = 'npx skills add ' + SITE.repo; });
  fill('[data-clone-cmd]', function (el) { el.textContent = 'git clone ' + REPO_URL + '.git'; });
  fill('[data-icon]', function (el) { el.insertAdjacentHTML('afterbegin', icon(el.getAttribute('data-icon'), el.getAttribute('data-icon-size'))); });

  /* socials: always icon + username, linked. data-socials="list" (boxed rows) or "inline" (footer/byline row) */
  function socialLinks(cls) {
    return M.socials.map(function (s) {
      return '<a class="' + cls + '" href="' + s.url + '" target="_blank" rel="noopener me" aria-label="' + esc(s.label + ': ' + s.handle) + '" title="' + esc(s.label) + '">' +
        icon(s.id, 16) + '<span class="social-handle">' + esc(s.handle) + '</span></a>';
    }).join('');
  }
  fill('[data-socials]', function (el) {
    el.innerHTML = socialLinks(el.getAttribute('data-socials') === 'list' ? 'social-row' : 'social-link');
  });

  /* ---------- GitHub stars (cached for an hour) ---------- */
  var starEls = document.querySelectorAll('[data-stars]');
  if (starEls.length) {
    var cached = storage(function () { return JSON.parse(sessionStorage.getItem('aafs-stars') || 'null'); }, null);
    var show = function (n) {
      if (!n) return;   /* a brand-new repo shows nothing rather than "★ 0" */
      var txt = n >= 1000 ? (n / 1000).toFixed(1).replace(/\.0$/, '') + 'k' : String(n);
      starEls.forEach(function (el) { el.textContent = txt; el.hidden = false; });
    };
    if (cached && Date.now() - cached.t < 3600e3) show(cached.n);
    else if (window.fetch) {
      fetch('https://api.github.com/repos/' + SITE.repo).then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
        if (!d || typeof d.stargazers_count !== 'number') return;
        show(d.stargazers_count);
        storage(function () { sessionStorage.setItem('aafs-stars', JSON.stringify({ n: d.stargazers_count, t: Date.now() })); });
      }).catch(function () {});
    }
  }

  /* ---------- theme ---------- */
  var root = document.documentElement, themeBtn = document.getElementById('themeToggle');
  function syncTheme() { var i = document.getElementById('themeIcon'); if (i) i.textContent = root.getAttribute('data-theme') === 'dark' ? 'D' : 'N'; }
  syncTheme();
  if (themeBtn) themeBtn.addEventListener('click', function () {
    var t = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', t);
    storage(function () { sessionStorage.setItem('aafs-theme', t); });   /* this visit only: new visits open in day mode */
    syncTheme();
  });

  /* ---------- site menu (hamburger, every page and width) ---------- */
  /* [label, href, external]. Only things that exist: no placeholder pages. */
  var MENU = [
    ['How to learn', './#tutor'],
    ['How lessons work', './#how'],
    ['Skills', REPO_URL + '/tree/main/skills', 1],
    ['Contents', './#contents'],
    ['Learning paths', './#paths'],
    ['Roadmap', REPO_URL + '/blob/main/ROADMAP.md', 1],
    ['Machines', './#machines'],
    ['Books', './#books'],
    ['Capstone', './#capstone'],
    ['Curriculum index', 'llms.txt'],
    ["What's new", REPO_URL + '/commits/main', 1],
    ['Contribute', REPO_URL + '/blob/main/CONTRIBUTING.md', 1],
    ['Report an issue', REPO_URL + '/issues/new/choose', 1],
    ['GitHub', REPO_URL, 1],
    ['About', './#maintainer']
  ];
  var menuBtn = document.getElementById('menuToggle');
  if (menuBtn) {
    var menu = document.createElement('nav');
    menu.className = 'site-menu'; menu.id = 'siteMenu'; menu.hidden = true;
    menu.setAttribute('aria-label', 'Site menu');
    var live = ALL.filter(function (l) { return l.published; }), done = live.filter(isDone).length;
    menu.innerHTML = MENU.map(function (m) {
      return '<a href="' + esc(m[1]) + '"' + (m[2] ? ' target="_blank" rel="noopener"' : '') + '>' + esc(m[0]) +
        (m[2] ? '<span class="site-menu-ext" aria-hidden="true">↗</span>' : '') + '</a>';
    }).join('') +
      '<p class="site-menu-progress">My progress · ' + done + ' of ' + live.length + ' live lessons done</p>';
    menuBtn.setAttribute('aria-controls', 'siteMenu');
    menuBtn.parentNode.appendChild(menu);
    var setMenu = function (open) {
      menu.hidden = !open;
      menuBtn.setAttribute('aria-expanded', String(open));
      menuBtn.classList.toggle('is-open', open);
    };
    menuBtn.addEventListener('click', function (e) { e.stopPropagation(); setMenu(menu.hidden); });
    menu.addEventListener('click', function (e) { if (e.target.closest('a')) setMenu(false); });
    document.addEventListener('click', function (e) { if (!menu.hidden && !menu.contains(e.target)) setMenu(false); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !menu.hidden) { setMenu(false); menuBtn.focus(); } });
  }

  /* ---------- copy chips ---------- */
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-copy-target]');
    if (!btn) return;
    var text = document.getElementById(btn.getAttribute('data-copy-target')).textContent;
    var done = function () {
      btn.classList.add('copied'); btn.textContent = 'copied';
      setTimeout(function () { btn.classList.remove('copied'); btn.textContent = 'copy'; }, 1400);
    };
    if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, done); else done();
  });

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
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }

  /* ---------- search palette (⌘K or /) ---------- */
  document.body.insertAdjacentHTML('beforeend',
    '<div class="overlay palette-overlay" id="paletteOverlay" aria-hidden="true"><div class="palette" role="dialog" aria-modal="true" aria-label="Search lessons">' +
    '<input class="palette-input" id="paletteInput" type="text" placeholder="Search ' + T.lessons + ' lessons…" autocomplete="off" spellcheck="false" aria-controls="paletteList">' +
    '<ul class="palette-list" id="paletteList" role="listbox"></ul>' +
    '<div class="palette-foot"><span><kbd>↑</kbd> <kbd>↓</kbd> move</span><span><kbd>↵</kbd> open</span><span><kbd>esc</kbd> close</span><span>■ live · □ planned</span></div></div></div>');
  var palOverlay = document.getElementById('paletteOverlay'), palInput = document.getElementById('paletteInput'), palList = document.getElementById('paletteList');
  var palResults = [], palSel = 0;

  function renderPalette() {
    var q = palInput.value.trim().toLowerCase();
    palResults = ALL.filter(function (l) { return !q || l.title.toLowerCase().indexOf(q) > -1 || l.phase.name.toLowerCase().indexOf(q) > -1; })
      .sort(function (a, b) { return q ? (b.published ? 1 : 0) - (a.published ? 1 : 0) : 0; }).slice(0, 40);
    palSel = Math.min(palSel, Math.max(palResults.length - 1, 0));
    palList.innerHTML = palResults.length ? palResults.map(function (l, i) {
      return '<li class="palette-item' + (l.published ? '' : ' is-planned') + '" role="option" data-i="' + i + '" aria-selected="' + (i === palSel) + '">' +
        '<span class="pi-phase">' + (l.published ? '■ ' : '□ ') + l.num + '</span><span class="pi-name">' + esc(l.title) + '</span>' +
        '<span class="pi-time">' + l.minutes + ' min</span></li>';
    }).join('') : '<li class="palette-empty">Nothing matches. Try "memory", "MCP" or "eval".</li>';
  }
  function choose(i) {
    var l = palResults[i];
    if (!l) return;
    closeOverlay(palOverlay);
    if (l.published) location.href = lessonHref(l);
    else if (window.AAFS.openPhase) window.AAFS.openPhase(l.phase.index, l.index);
    else location.href = './?phase=' + l.phase.index + '&lesson=' + l.index + '#contents';
  }
  function openPalette() { palInput.value = ''; palSel = 0; renderPalette(); openOverlay(palOverlay, palInput); }
  function scrollSel() { var el = palList.querySelector('[aria-selected="true"]'); if (el) el.scrollIntoView({ block: 'nearest' }); }
  palInput.addEventListener('input', function () { palSel = 0; renderPalette(); });
  palInput.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowDown') { palSel = Math.min(palSel + 1, palResults.length - 1); renderPalette(); scrollSel(); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { palSel = Math.max(palSel - 1, 0); renderPalette(); scrollSel(); e.preventDefault(); }
    else if (e.key === 'Enter') choose(palSel);
  });
  palList.addEventListener('click', function (e) { var li = e.target.closest('.palette-item'); if (li) choose(+li.getAttribute('data-i')); });
  palOverlay.addEventListener('click', function (e) { if (e.target === palOverlay) closeOverlay(palOverlay); });
  var searchBtn = document.getElementById('searchToggle');
  if (searchBtn) searchBtn.addEventListener('click', openPalette);

  document.addEventListener('keydown', function (e) {
    var typing = /input|textarea|select/i.test(document.activeElement.tagName);
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); palOverlay.classList.contains('open') ? closeOverlay(palOverlay) : openPalette(); }
    else if (e.key === '/' && !typing && !document.querySelector('.overlay.open')) { e.preventDefault(); openPalette(); }
    else if (e.key === 'Escape') {
      var open = document.querySelectorAll('.overlay.open');
      if (open.length) closeOverlay(open[open.length - 1]);
    }
  });

  window.AAFS = {
    SITE: SITE, PHASES: PHASES, ALL: ALL, REPO_URL: REPO_URL,
    esc: esc, pad: pad, icon: icon, socialLinks: socialLinks, lessonHref: lessonHref, findLesson: findLesson,
    isDone: isDone, setDone: setDone, doneCount: doneCount,
    openOverlay: openOverlay, closeOverlay: closeOverlay, openPhase: null,
  };
})();
