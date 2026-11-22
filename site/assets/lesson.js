/* Lesson page: render docs/en.md + quiz.json for ?path=phases/<phase>/<lesson>. Needs common.js. */
(function () {
  'use strict';

  var A = window.AAFS, esc = A.esc, pad = A.pad;
  var RAW = 'https://raw.githubusercontent.com/' + A.SITE.repo + '/main/';
  var body = document.getElementById('lessonBody');
  var state = document.getElementById('lessonState');

  var path = new URLSearchParams(location.search).get('path') || '';
  var lesson = A.findLesson(path.replace(/\/+$/, ''));

  /* Only paths that exist in the curriculum are ever fetched. */
  if (!lesson) return fail('That lesson does not exist.', true);
  var phase = lesson.phase;
  renderAside();
  renderCrumbs();
  if (!lesson.published) return fail('This lesson is planned and not written yet.', false);

  /* local build copy first (site/content), then GitHub raw as a fallback */
  function fetchText(rel) {
    return fetch('content/' + rel).then(function (r) { if (!r.ok) throw r; return r.text(); })
      .catch(function () { return fetch(RAW + rel).then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); }); });
  }

  fetchText(lesson.path + '/docs/en.md').then(renderLesson).catch(function () {
    fail('Could not load this lesson. Read it on GitHub instead.', false);
  });

  /* ---------------------------------------------------------- aside + crumbs */

  function renderAside() {
    var a = document.getElementById('asidePhase');
    a.href = './?phase=' + phase.index + '#contents';
    a.innerHTML = '<span class="eyebrow">Phase ' + pad(phase.index) + '</span><span class="aside-phase-name">' + esc(phase.name) + '</span>';
    document.getElementById('asideLessons').innerHTML = phase.lessons.map(function (l) {
      var cls = (l === lesson ? 'is-current ' : '') + (l.published ? '' : 'is-planned ') + (A.isDone(l) ? 'is-done' : '');
      var label = '<span class="al-num">' + l.num.slice(3) + '</span><span class="al-name">' + esc(l.title) + '</span>';
      return '<li class="' + cls + '">' + (l.published
        ? '<a href="' + A.lessonHref(l) + '"' + (l === lesson ? ' aria-current="page"' : '') + '>' + label + '</a>'
        : '<span>' + label + '</span>') + '</li>';
    }).join('');
  }

  function renderCrumbs() {
    document.getElementById('crumbs').innerHTML =
      '<a href="./#contents">Curriculum</a><span>/</span><a href="./?phase=' + phase.index + '#contents">Phase ' + pad(phase.index) + ' · ' + esc(phase.name) + '</a>' +
      '<span>/</span><span>' + lesson.num + '</span>';
    document.title = lesson.title + ' | Agentic AI from Scratch';
  }

  function fail(msg, notFound) {
    state.className = 'lesson-empty';
    state.innerHTML = '<p class="eyebrow">' + (notFound ? '404 · not in the curriculum' : 'Lesson ' + lesson.num) + '</p>' +
      '<h1 class="lesson-title">' + esc(notFound ? 'Lesson not found' : lesson.title) + '</h1><p>' + esc(msg) + '</p>' +
      '<div class="lesson-actions"><a class="btn btn--primary" href="./#contents">Browse the curriculum</a>' +
      (notFound ? '' : '<a class="btn" href="' + A.REPO_URL + '/blob/main/CONTRIBUTING.md" target="_blank" rel="noopener">Write this lesson</a>') + '</div>';
  }

  /* ---------------------------------------------------------- lesson */

  function renderLesson(md) {
    /* pull out the header parts the template defines: # title, > motto, **Key:** value lines */
    var title = (md.match(/^#\s+(.+)$/m) || [, lesson.title])[1];
    md = md.replace(/^#\s+.+$/m, '');
    var motto = '';
    md = md.replace(/^\s*>\s?(.+)\n/, function (_, m) { motto = m; return ''; });
    var meta = [];
    md = md.replace(/^\*\*(Type|Languages|Prerequisites|Time):\*\*\s*(.+)$\n?/gm, function (_, k, v) { meta.push([k, v.trim()]); return ''; });

    marked.use({ gfm: true });
    var html = marked.parse(md);

    var done = A.isDone(lesson);
    state.remove();
    body.insertAdjacentHTML('beforeend',
      '<header class="lesson-head">' +
        '<p class="eyebrow">Lesson ' + lesson.num + (lesson.type ? ' · ' + esc(lesson.type) : '') + '</p>' +
        '<h1 class="lesson-title">' + esc(title) + '</h1>' +
        (motto ? '<p class="lesson-motto">' + marked.parseInline(motto) + '</p>' : '') +
        '<dl class="lesson-meta">' + meta.map(function (m) { return '<div><dt>' + m[0] + '</dt><dd>' + marked.parseInline(m[1]) + '</dd></div>'; }).join('') + '</dl>' +
        '<div class="lesson-actions">' +
          '<button class="btn' + (done ? ' btn--primary' : '') + '" type="button" id="doneBtn" aria-pressed="' + done + '">' + (done ? '✓ Completed' : 'Mark complete') + '</button>' +
          '<a class="btn" href="' + A.REPO_URL + '/tree/main/' + lesson.path + '/code" target="_blank" rel="noopener">Run the code ↗</a>' +
          '<a class="btn btn--quiet" href="' + A.REPO_URL + '/edit/main/' + lesson.path + '/docs/en.md" target="_blank" rel="noopener">Edit on GitHub</a>' +
        '</div>' +
      '</header>' +
      '<div class="prose" id="prose">' + html + '</div>' +
      (lesson.hasQuiz ? '<section class="quiz" id="quiz" aria-labelledby="quizTitle"><p class="eyebrow">Check your understanding</p><h2 id="quizTitle">Quiz</h2><div id="quizBody">Loading quiz…</div></section>' : '') +
      byline() + pager());

    enhanceProse();
    buildToc();
    renderFiles();
    if (lesson.hasQuiz) fetchText(lesson.path + '/quiz.json').then(function (t) { renderQuiz(JSON.parse(t)); })
      .catch(function () { document.getElementById('quizBody').textContent = 'Quiz unavailable.'; });

    document.getElementById('doneBtn').addEventListener('click', function () {
      var now = !A.isDone(lesson);
      A.setDone(lesson, now);
      this.classList.toggle('btn--primary', now);
      this.setAttribute('aria-pressed', now);
      this.textContent = now ? '✓ Completed' : 'Mark complete';
      renderAside();
    });
    if (location.hash) { var t = document.getElementById(location.hash.slice(1)); if (t) t.scrollIntoView(); }
  }

  function enhanceProse() {
    var prose = document.getElementById('prose');
    var base = A.REPO_URL + '/blob/main/' + lesson.path + '/docs/';
    prose.querySelectorAll('a[href]').forEach(function (a) {
      var h = a.getAttribute('href');
      if (/^(https?:|mailto:|#)/.test(h)) { if (/^https?:/.test(h)) { a.target = '_blank'; a.rel = 'noopener'; } return; }
      a.href = new URL(h, base).href; a.target = '_blank'; a.rel = 'noopener';
    });
    prose.querySelectorAll('pre > code').forEach(function (code, i) {
      var pre = code.parentNode;
      var lang = ((code.className.match(/language-(\w+)/) || [])[1] || 'text');
      code.id = code.id || 'code-' + i;
      if (window.hljs && lang !== 'text') { try { hljs.highlightElement(code); } catch (e) {} }
      var wrap = document.createElement('div');
      wrap.className = 'code-block';
      wrap.innerHTML = '<div class="code-bar"><span>' + esc(lang) + '</span><button class="copy-chip" type="button" data-copy-target="' + code.id + '">copy</button></div>';
      pre.parentNode.insertBefore(wrap, pre);
      wrap.appendChild(pre);
    });
    prose.querySelectorAll('table').forEach(function (t) {
      var w = document.createElement('div'); w.className = 'table-wrap'; t.parentNode.insertBefore(w, t); w.appendChild(t);
    });
  }

  function slug(s) { return s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''); }

  function buildToc() {
    var hs = document.querySelectorAll('#prose h2');
    if (!hs.length) return;
    var items = [];
    hs.forEach(function (h) {
      h.id = h.id || slug(h.textContent);
      items.push('<li><a href="#' + h.id + '">' + esc(h.textContent) + '</a></li>');
    });
    if (lesson.hasQuiz) items.push('<li><a href="#quiz">Quiz</a></li>');
    document.getElementById('asideToc').innerHTML = items.join('');
    document.getElementById('tocBlock').hidden = false;

    var links = document.querySelectorAll('#asideToc a');
    if (!('IntersectionObserver' in window)) return;
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        links.forEach(function (a) { a.classList.toggle('active', a.getAttribute('href') === '#' + en.target.id); });
      });
    }, { rootMargin: '-80px 0px -70% 0px' });
    hs.forEach(function (h) { io.observe(h); });
  }

  function renderFiles() {
    var base = A.REPO_URL + '/tree/main/' + lesson.path + '/';
    var blob = A.REPO_URL + '/blob/main/' + lesson.path + '/';
    var files = [['docs/en.md', blob + 'docs/en.md'], ['code/', base + 'code'], ['quiz.json', blob + 'quiz.json'], ['outputs/', base + 'outputs']];
    document.getElementById('asideFiles').innerHTML = files.map(function (f) {
      return '<li><a href="' + f[1] + '" target="_blank" rel="noopener">' + f[0] + ' ↗</a></li>';
    }).join('');
    document.getElementById('filesBlock').hidden = false;
  }

  /* ---------------------------------------------------------- quiz */

  function renderQuiz(quiz) {
    var qs = quiz.questions || [];
    var answered = 0, correct = 0;
    var el = document.getElementById('quizBody');
    el.innerHTML = '<p class="quiz-intro">' + qs.length + ' questions: answer the <b>pre</b> ones before reading, then the rest after. Nothing is saved.</p>' +
      qs.map(function (q, i) {
        return '<fieldset class="quiz-q" data-q="' + i + '"><legend><span class="quiz-stage">' + pad(i + 1) + ' · ' + esc(q.stage || 'check') + '</span>' +
          esc(q.question) + '</legend><div class="quiz-options">' +
          q.options.map(function (o, j) { return '<button type="button" class="quiz-opt" data-o="' + j + '"><span class="quiz-letter">' + 'ABCD'[j] + '</span>' + esc(o) + '</button>'; }).join('') +
          '</div><p class="quiz-explain" hidden></p></fieldset>';
      }).join('') + '<p class="quiz-score" id="quizScore" hidden></p>';

    el.addEventListener('click', function (e) {
      var btn = e.target.closest('.quiz-opt');
      if (!btn) return;
      var fs = btn.closest('.quiz-q');
      if (fs.classList.contains('answered')) return;
      var q = qs[+fs.getAttribute('data-q')], pick = +btn.getAttribute('data-o');
      fs.classList.add('answered');
      fs.querySelectorAll('.quiz-opt').forEach(function (b, j) {
        b.disabled = true;
        if (j === q.correct) b.classList.add('is-correct');
        else if (j === pick) b.classList.add('is-wrong');
      });
      var ok = pick === q.correct;
      var ex = fs.querySelector('.quiz-explain');
      ex.hidden = false;
      ex.innerHTML = '<b>' + (ok ? 'Correct.' : 'Not quite.') + '</b> ' + esc(q.explanation || '');
      answered++; if (ok) correct++;
      if (answered === qs.length) {
        var s = document.getElementById('quizScore');
        s.hidden = false;
        s.innerHTML = 'Score: <b>' + correct + ' / ' + qs.length + '</b>' + (correct === qs.length
          ? ' · clean sweep. <button class="link-btn" type="button" id="quizDone">Mark lesson complete</button>'
          : ' · re-read the sections behind the ones you missed, then try the exercises.');
        var d = document.getElementById('quizDone');
        if (d) d.addEventListener('click', function () { if (!A.isDone(lesson)) document.getElementById('doneBtn').click(); d.textContent = 'Marked ✓'; });
      }
    });
  }

  /* ---------------------------------------------------------- byline + pager */

  function byline() {
    var M = A.SITE.maintainer;
    return '<aside class="byline"><img src="' + M.avatar + '" alt="" width="56" height="56" loading="lazy">' +
      '<div><p class="eyebrow">Written by</p><p class="byline-name">' + esc(M.name) + '</p><p class="byline-role">' + esc(M.role) + '</p></div>' +
      '<div class="byline-socials">' + M.socials.map(function (s) {
        return '<a class="social-icon" href="' + s.url + '" target="_blank" rel="noopener me" aria-label="' + esc(s.label + ' ' + s.handle) + '" title="' + esc(s.label + ' ' + s.handle) + '">' + A.icon(s.id, 16) + '</a>';
      }).join('') + '</div></aside>';
  }

  function pager() {
    var i = A.ALL.indexOf(lesson);
    var prev = null, next = null, upcoming = A.ALL[i + 1];
    for (var a = i - 1; a >= 0; a--) if (A.ALL[a].published) { prev = A.ALL[a]; break; }
    for (var b = i + 1; b < A.ALL.length; b++) if (A.ALL[b].published) { next = A.ALL[b]; break; }
    function card(l, dir) {
      return '<a class="pager-card pager-' + dir + '" href="' + A.lessonHref(l) + '"><span class="eyebrow">' + (dir === 'prev' ? '← Previous' : 'Next →') + ' · ' + l.num + '</span>' +
        '<span class="pager-title">' + esc(l.title) + '</span></a>';
    }
    var note = upcoming && !upcoming.published
      ? '<p class="pager-note">Up next in the curriculum: <b>' + upcoming.num + ' ' + esc(upcoming.title) + '</b> (planned). ' +
        '<a href="' + A.REPO_URL + '/blob/main/CONTRIBUTING.md" target="_blank" rel="noopener">Help write it →</a></p>' : '';
    return '<nav class="pager" aria-label="Lesson pagination">' + (prev ? card(prev, 'prev') : '<span></span>') + (next ? card(next, 'next') : '<span></span>') + '</nav>' + note;
  }

  /* ---------------------------------------------------------- reading progress */

  var bar = document.getElementById('readProgress');
  window.addEventListener('scroll', function () {
    var h = document.documentElement.scrollHeight - innerHeight;
    bar.style.width = (h > 0 ? Math.min(100, scrollY / h * 100) : 0) + '%';
  }, { passive: true });
})();
