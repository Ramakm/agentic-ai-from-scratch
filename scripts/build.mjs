#!/usr/bin/env node
/**
 * Build everything that is derived from curriculum.json and the phases/ folder.
 *
 *   node scripts/build.mjs           write generated files
 *   node scripts/build.mjs --check   exit 1 if any committed generated file is stale (CI)
 *
 * A lesson counts as published when phases/<phase>/<lesson>/docs/en.md exists.
 * Phase status is derived: all published -> complete, some -> in-progress, none -> planned.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const CHECK = process.argv.includes('--check');
const read = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8');
const exists = (p) => fs.existsSync(path.join(ROOT, p));
const pad = (n) => String(n).padStart(2, '0');

const cur = JSON.parse(read('curriculum.json'));
const repoUrl = `https://github.com/${cur.repo}`;
const stale = [];

function write(rel, content) {
  const abs = path.join(ROOT, rel);
  const prev = fs.existsSync(abs) ? fs.readFileSync(abs, 'utf8') : null;
  if (prev === content) return;
  if (CHECK) { stale.push(rel); return; }
  fs.mkdirSync(path.dirname(abs), { recursive: true });
  fs.writeFileSync(abs, content);
  console.log('wrote', rel);
}

/* ------------------------------------------------------------ model */

const phases = cur.phases.map((p, i) => {
  const lessons = p.lessons.map((l, j) => {
    const dir = `phases/${p.id}/${l.id}`;
    const published = exists(`${dir}/docs/en.md`);
    const doc = published ? read(`${dir}/docs/en.md`) : '';
    const type = (doc.match(/^\*\*Type:\*\*\s*(.+)$/m) || [])[1]?.trim() || '';
    return {
      id: l.id, title: l.title, minutes: l.minutes, path: dir, published, type,
      num: `${pad(i)}.${pad(j + 1)}`, hasQuiz: published && exists(`${dir}/quiz.json`),
    };
  });
  const pub = lessons.filter((l) => l.published).length;
  const status = pub === lessons.length ? 'complete' : pub ? 'in-progress' : 'planned';
  return { index: i, id: p.id, name: p.name, desc: p.desc, status, published: pub, lessons };
});
const lessonUrl = (l) => `${cur.site}${l.path.replace(/^phases\//, 'lessons/')}/`;
const all = phases.flatMap((p) => p.lessons.map((l) => ({ p, l })));
const totals = {
  phases: phases.length, lessons: all.length,
  published: all.filter((x) => x.l.published).length,
  hours: Math.round(all.reduce((s, x) => s + x.l.minutes, 0) / 60),
};

/* ------------------------------------------------------------ interview questions */
/* interviews/cards.json lists the topics; interviews/<card>/<NN-slug>.md is one question.
   The header shape is fixed (see interviews/README.md) and checked below. */

const IV_LEVELS = { 1: 'Fundamentals', 2: 'Practitioner', 3: 'Senior', 4: 'Staff' };
const IV_TYPES = ['Concept', 'Debug', 'Design', 'Trade-off', 'Estimate', 'Code'];
const IV_SECTIONS = ['Short answer', 'Full answer', 'Follow-ups', 'Wrong answers'];
const ivProblems = [];
const lessonByKey = new Map(all.map((x) => [`${x.p.id}/${x.l.id}`, x]));
const ivCards = exists('interviews/cards.json') ? JSON.parse(read('interviews/cards.json')) : [];
const interviews = [];
for (const card of ivCards) {
  const dir = `interviews/${card.id}`;
  if (!exists(dir)) { ivProblems.push(`${dir}: card has no folder`); continue; }
  for (const f of fs.readdirSync(path.join(ROOT, dir)).filter((f) => f.endsWith('.md')).sort()) {
    const rel = `${dir}/${f}`, doc = read(rel);
    const field = (k) => (doc.match(new RegExp(`^\\*\\*${k}:\\*\\*\\s*(.+)$`, 'm')) || [])[1]?.trim() || '';
    const sections = {};
    for (const part of doc.split(/^## /m).slice(1)) {
      const nl = part.indexOf('\n');
      sections[part.slice(0, nl).trim()] = part.slice(nl + 1).trim();
    }
    const q = {
      card: card.id, slug: f.replace(/^\d+-/, '').replace(/\.md$/, ''), file: rel,
      title: (doc.match(/^# (.+)$/m) || [])[1]?.trim() || '',
      prompt: doc.split('\n').filter((x) => /^>\s?/.test(x)).map((x) => x.replace(/^>\s?/, '')).join('\n').trim(),
      level: Number(field('Level')), type: field('Type'), minutes: Number((field('Time').match(/\d+/) || [])[0] || 0),
      lessons: field('Taught in').split(',').map((s) => s.trim()).filter(Boolean), sections,
    };
    if (!q.title) ivProblems.push(`${rel}: missing "# title"`);
    if (!q.prompt) ivProblems.push(`${rel}: missing "> scenario" line`);
    if (!IV_LEVELS[q.level]) ivProblems.push(`${rel}: **Level:** must be 1-4`);
    if (!IV_TYPES.includes(q.type)) ivProblems.push(`${rel}: **Type:** must be one of ${IV_TYPES.join(', ')}`);
    if (!q.minutes) ivProblems.push(`${rel}: **Time:** must be "~N minutes"`);
    for (const s of IV_SECTIONS) if (!sections[s]) ivProblems.push(`${rel}: missing "## ${s}"`);
    if (!q.lessons.length) ivProblems.push(`${rel}: **Taught in:** needs at least one lesson`);
    for (const k of q.lessons) {
      const x = lessonByKey.get(k);
      if (!x) ivProblems.push(`${rel}: unknown lesson ${k}`);
      else if (!x.l.published) ivProblems.push(`${rel}: lesson ${k} is not live yet`);
    }
    interviews.push(q);
  }
}
interviews.forEach((q, i) => { q.num = i + 1; q.url = `${cur.site}interviews/${q.card}/${q.slug}/`; q.href = `/interviews/${q.card}/${q.slug}/`; });
{
  const seen = new Set();
  for (const q of interviews) { if (seen.has(q.href)) ivProblems.push(`duplicate interview slug ${q.href}`); seen.add(q.href); }
}

/* ------------------------------------------------------------ site data */

write('site/assets/data.js',
  '/* Generated by scripts/build.mjs from curriculum.json. Do not edit by hand. */\n' +
  `window.SITE = ${JSON.stringify({ title: cur.title, repo: cur.repo, site: cur.site, maintainer: cur.maintainer, totals }, null, 2)};\n` +
  `window.PHASES = ${JSON.stringify(phases.map(({ index, ...p }) => ({
    ...p, lessons: p.lessons.map(({ published, hasQuiz, ...l }) => ({ ...l, ...(published && { published }), ...(hasQuiz && { hasQuiz }) })),
  })), null, 1)};\n`);

/* ------------------------------------------------------------ markdown helpers */

const statusMark = { complete: '■', 'in-progress': '◩', planned: '□' };
const lessonRow = (l) => `| ${l.num} | ${l.published ? `[${l.title}](${l.id}/docs/en.md)` : l.title} | ${l.published ? (l.type || 'Build') : 'planned'} | ${l.minutes} min |`;

function contentsMarkdown(linkBase = '') {
  return phases.map((p) => {
    const rows = p.lessons.map((l) => `| ${l.num} | ${l.published ? `[${l.title}](${linkBase}${l.path}/docs/en.md)` : l.title} | ${l.published ? '■ live' : '□ planned'} | ${l.minutes} min |`);
    return `<details${p.published ? ' open' : ''}>\n<summary><b>Phase ${pad(p.index)} · ${p.name}</b> · ${p.lessons.length} lessons · ${p.published} live</summary>\n\n` +
      `${p.desc}\n\n| # | Lesson | Status | Time |\n|---|--------|--------|------|\n${rows.join('\n')}\n\n` +
      `[Phase overview →](${linkBase}phases/${p.id}/README.md)\n\n</details>`;
  }).join('\n\n');
}

/* ------------------------------------------------------------ phase READMEs */

for (const p of phases) {
  const prev = phases[p.index - 1], next = phases[p.index + 1];
  write(`phases/${p.id}/README.md`,
    `<!-- Generated by scripts/build.mjs from curriculum.json. Do not edit by hand. -->\n` +
    `# Phase ${pad(p.index)} · ${p.name}\n\n> ${p.desc}\n\n` +
    `**Status:** ${statusMark[p.status]} ${p.status.replace('-', ' ')} · **Lessons:** ${p.published} of ${p.lessons.length} live · ` +
    `**Time:** ~${Math.round(p.lessons.reduce((s, l) => s + l.minutes, 0) / 60)} hours\n\n` +
    `| # | Lesson | Type | Time |\n|---|--------|------|------|\n${p.lessons.map(lessonRow).join('\n')}\n\n` +
    `Every live lesson folder has \`docs/en.md\`, runnable \`code/\` with tests, a \`quiz.json\`, and an artifact in \`outputs/\`.\n` +
    `Want to write a planned lesson? See [CONTRIBUTING.md](../../CONTRIBUTING.md) and [LESSON_TEMPLATE.md](../../LESSON_TEMPLATE.md).\n\n` +
    `${prev ? `← [Phase ${pad(prev.index)} · ${prev.name}](../${prev.id}/README.md)` : ''}` +
    `${prev && next ? ' · ' : ''}${next ? `[Phase ${pad(next.index)} · ${next.name}](../${next.id}/README.md) →` : ''}\n`);
}

/* ------------------------------------------------------------ README contents block */

const START = '<!-- CONTENTS:START -->', END = '<!-- CONTENTS:END -->';
if (exists('README.md')) {
  const readme = read('README.md');
  const a = readme.indexOf(START), b = readme.indexOf(END);
  if (a !== -1 && b > a) {
    const block = `${START}\n<!-- Generated by scripts/build.mjs. Edit curriculum.json instead. -->\n\n` +
      `**${totals.phases} phases · ${totals.lessons} lessons · ${totals.published} live · ~${totals.hours} hours**\n\n${contentsMarkdown()}\n\n${END}`;
    write('README.md', readme.slice(0, a) + block + readme.slice(b + END.length));
  }
}

/* ------------------------------------------------------------ ROADMAP */

write('ROADMAP.md',
  `<!-- Generated by scripts/build.mjs from curriculum.json. Do not edit by hand. -->\n# Roadmap\n\n` +
  `${totals.published} of ${totals.lessons} lessons are live. A lesson goes live when its docs, tested code, quiz and output artifact are merged.\n\n` +
  `| Phase | Name | Live | Total | Status |\n|-------|------|------|-------|--------|\n` +
  phases.map((p) => `| ${pad(p.index)} | [${p.name}](phases/${p.id}/README.md) | ${p.published} | ${p.lessons.length} | ${statusMark[p.status]} ${p.status.replace('-', ' ')} |`).join('\n') +
  `\n\n## Up next\n\nThe next lessons to write, in curriculum order:\n\n` +
  all.filter((x) => !x.l.published).slice(0, 10).map((x) => `- **${x.l.num}** ${x.l.title} (Phase ${pad(x.p.index)} · ${x.p.name})`).join('\n') +
  `\n\nPick one, open an issue saying you're on it, and follow [CONTRIBUTING.md](CONTRIBUTING.md).\n`);

/* ------------------------------------------------------------ llms.txt */

write('site/llms.txt',
  `# ${cur.title}\n\n> ${cur.tagline} ${totals.phases} phases, ${totals.lessons} lessons (${totals.published} live), Python and TypeScript, free and open source (MIT).\n\n` +
  `Source: ${repoUrl}\nSite: ${cur.site}\nMaintainer: ${cur.maintainer.name} (${cur.maintainer.socials.map((s) => s.url).join(', ')})\n\n` +
  `Install the tutor skills into a coding agent: npx skills add ${cur.repo}\n\n` +
  phases.map((p) => `## Phase ${pad(p.index)}: ${p.name}\n\n${p.desc}\n\n` + p.lessons.map((l) =>
    `- ${l.num} ${l.title} (${l.minutes} min)${l.published ? `: ${lessonUrl(l)} | raw: https://raw.githubusercontent.com/${cur.repo}/main/${l.path}/docs/en.md` : ' [planned]'}`).join('\n')).join('\n\n') +
  (interviews.length ? `\n\n## Interview questions\n\n${interviews.length} practice questions with short and full answers, follow-ups and common wrong answers: ${cur.site}interviews/\n\n` +
    interviews.map((q) => `- ${q.title} (level ${q.level} ${IV_LEVELS[q.level]}, ${q.type}): ${q.url}`).join('\n') : '') + '\n');

/* ------------------------------------------------------------ lesson content for the site (not committed) */

if (!CHECK) {
  const out = path.join(ROOT, 'site/content');
  fs.rmSync(out, { recursive: true, force: true });
  for (const { l } of all.filter((x) => x.l.published)) {
    for (const f of ['docs/en.md', 'quiz.json']) {
      if (!exists(`${l.path}/${f}`)) continue;
      const dest = path.join(out, l.path, f);
      fs.mkdirSync(path.dirname(dest), { recursive: true });
      fs.copyFileSync(path.join(ROOT, l.path, f), dest);
    }
    /* diagrams referenced from docs/en.md as ![alt](assets/name.svg) */
    const assets = path.join(ROOT, l.path, 'docs/assets');
    if (fs.existsSync(assets)) fs.cpSync(assets, path.join(out, l.path, 'docs/assets'), { recursive: true });
  }
  console.log(`copied ${totals.published} lesson(s) into site/content/`);
}

/* ------------------------------------------------------------ SEO: homepage meta, sitemap, robots */

const htmlEsc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const plain = (md) => md.replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/[*_`]/g, '').replace(/\s+/g, ' ').trim();
const clip = (s, n) => (s.length <= n ? s : s.slice(0, n - 1).replace(/\s+\S*$/, '') + '…');
const jsonLd = (o) => `<script type="application/ld+json">${JSON.stringify(o).replace(/</g, '\\u003c')}</script>`;
const OG_IMAGE = `${cur.site}assets/og.png`;
const person = { '@type': 'Person', name: cur.maintainer.name, url: `https://github.com/${cur.maintainer.github}` };
const course = {
  '@type': 'Course', '@id': `${cur.site}#course`, name: cur.title, url: cur.site,
  description: `A free, open-source agentic AI course: ${totals.lessons} lessons that teach you to build AI agents from scratch, from a raw while-loop and an HTTP call to tool use, memory, RAG, planning, MCP, multi-agent systems, evals and safety.`,
  provider: person, author: person, isAccessibleForFree: true, inLanguage: 'en', license: `${repoUrl}/blob/main/LICENSE`,
  educationalLevel: 'Intermediate', teaches: phases.map((p) => p.name),
  offers: { '@type': 'Offer', category: 'Free', price: 0, priceCurrency: 'USD' },
  hasCourseInstance: { '@type': 'CourseInstance', courseMode: 'Online', courseWorkload: `PT${totals.hours}H` },
  syllabusSections: phases.map((p) => ({ '@type': 'Syllabus', name: `Phase ${pad(p.index)}: ${p.name}`, description: p.desc,
    timeRequired: `PT${p.lessons.reduce((m, l) => m + l.minutes, 0)}M` })),
};

function metaTags({ title, description, url, type = 'website' }) {
  return [
    `<title>${htmlEsc(title)}</title>`,
    `<meta name="description" content="${htmlEsc(description)}">`,
    `<link rel="canonical" href="${url}">`,
    `<meta name="robots" content="index, follow, max-image-preview:large">`,
    `<meta property="og:type" content="${type}">`,
    `<meta property="og:site_name" content="${htmlEsc(cur.title)}">`,
    `<meta property="og:title" content="${htmlEsc(title)}">`,
    `<meta property="og:description" content="${htmlEsc(description)}">`,
    `<meta property="og:url" content="${url}">`,
    `<meta property="og:image" content="${OG_IMAGE}">`,
    `<meta property="og:image:width" content="1200">`,
    `<meta property="og:image:height" content="630">`,
    `<meta name="twitter:card" content="summary_large_image">`,
    `<meta name="twitter:creator" content="@${cur.maintainer.handle}">`,
    `<meta name="twitter:title" content="${htmlEsc(title)}">`,
    `<meta name="twitter:description" content="${htmlEsc(description)}">`,
    `<meta name="twitter:image" content="${OG_IMAGE}">`,
  ].map((t) => '  ' + t).join('\n');
}

const SEO_START = '<!-- SEO:START -->', SEO_END = '<!-- SEO:END -->';
{
  const home = read('site/index.html');
  const a = home.indexOf(SEO_START), b = home.indexOf(SEO_END);
  if (a === -1 || b < a) { console.error('site/index.html is missing the SEO:START/SEO:END markers'); process.exit(1); }
  const block = `${SEO_START}\n  <!-- Generated by scripts/build.mjs from curriculum.json. -->\n` + metaTags({
    title: 'Agentic AI Course (Free): Build AI Agents from Scratch',
    description: `Free, open-source agentic AI course: ${totals.lessons} lessons on building AI agents from scratch. Tool use, memory, RAG, planning, MCP, multi-agent systems and evals.`,
    url: cur.site,
  }) + '\n  ' + jsonLd({ '@context': 'https://schema.org', '@graph': [
    { '@type': 'WebSite', '@id': `${cur.site}#website`, name: cur.title, alternateName: 'Free Agentic AI Course', url: cur.site, inLanguage: 'en' },
    course,
  ] }) + `\n  ${SEO_END}`;
  write('site/index.html', home.slice(0, a) + block + home.slice(b + SEO_END.length));
}

write('site/robots.txt', `User-agent: *\nAllow: /\n\nSitemap: ${cur.site}sitemap.xml\n`);
write('site/sitemap.xml',
  `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n` +
  [`  <url><loc>${cur.site}</loc><priority>1.0</priority></url>`,
    ...all.filter((x) => x.l.published).map((x) => `  <url><loc>${lessonUrl(x.l)}</loc><priority>0.8</priority></url>`),
    ...(interviews.length ? [`  <url><loc>${cur.site}interviews/</loc><priority>0.9</priority></url>`] : []),
    ...interviews.map((q) => `  <url><loc>${q.url}</loc><priority>0.6</priority></url>`)].join('\n') +
  `\n</urlset>\n`);

/* ------------------------------------------------------------ static lesson pages (not committed) */
/* One crawlable page per live lesson at /lessons/<phase>/<lesson>/: its own title, description,
   canonical URL, structured data and a server-rendered summary. lesson.js then renders the full lesson. */

if (!CHECK) {
  const template = read('site/lesson.html');
  const out = path.join(ROOT, 'site/lessons');
  fs.rmSync(out, { recursive: true, force: true });
  const live = all.filter((x) => x.l.published);
  live.forEach(({ p, l }, k) => {
    const doc = read(`${l.path}/docs/en.md`);
    const motto = plain((doc.match(/^>\s?(.+)$/m) || [, ''])[1]);
    const section = (h) => (doc.split(new RegExp(`^## ${h}\\s*$`, 'm'))[1] || '').split(/^## /m)[0];
    const objectives = section('Learning Objectives').split('\n').filter((x) => /^\s*[-*]\s/.test(x)).map((x) => plain(x.replace(/^\s*[-*]\s+/, '')));
    const problem = plain((section('The Problem').trim().split(/\n\s*\n/)[0] || ''));
    const url = lessonUrl(l);
    const title = `${l.title} · Agentic AI Course (Free) · Lesson ${l.num}`;
    const description = clip(`${motto} Lesson ${l.num} of a free agentic AI course: ${p.name}.`, 158);
    const prev = live[k - 1], next = live[k + 1];
    const ld = { '@context': 'https://schema.org', '@graph': [
      { '@type': 'LearningResource', name: l.title, description, url, learningResourceType: 'Lesson', inLanguage: 'en',
        isAccessibleForFree: true, timeRequired: `PT${l.minutes}M`, educationalLevel: 'Intermediate', author: person,
        isPartOf: { '@type': 'Course', '@id': `${cur.site}#course`, name: cur.title, url: cur.site } },
      { '@type': 'BreadcrumbList', itemListElement: [
        { '@type': 'ListItem', position: 1, name: cur.title, item: cur.site },
        { '@type': 'ListItem', position: 2, name: `Phase ${pad(p.index)}: ${p.name}`, item: `${cur.site}?phase=${p.index}#contents` },
        { '@type': 'ListItem', position: 3, name: l.title, item: url }] },
    ] };
    const summary =
      `<article class="lesson-prerender">\n` +
      `        <p class="eyebrow">Lesson ${l.num} · Phase ${pad(p.index)} · ${htmlEsc(p.name)}</p>\n` +
      `        <h1 class="lesson-title">${htmlEsc(l.title)}</h1>\n` +
      (motto ? `        <p class="lesson-motto">${htmlEsc(motto)}</p>\n` : '') +
      (objectives.length ? `        <h2>Learning objectives</h2>\n        <ul>${objectives.map((o) => `<li>${htmlEsc(o)}</li>`).join('')}</ul>\n` : '') +
      (problem ? `        <p>${htmlEsc(problem)}</p>\n` : '') +
      `        <nav class="lesson-pager-static">${prev ? `<a href="${lessonUrl(prev.l).replace(cur.site, '/')}">← ${htmlEsc(prev.l.title)}</a>` : ''} ${next ? `<a href="${lessonUrl(next.l).replace(cur.site, '/')}">${htmlEsc(next.l.title)} →</a>` : ''}</nav>\n` +
      `        <p>Loading the full lesson…</p>\n      </article>`;
    let page = template
      .replace('  <meta name="robots" content="noindex, follow">\n', '')
      .replace(/<title>[\s\S]*?<\/title>\n\s*<meta name="description"[^>]*>/, metaTags({ title, description, url, type: 'article' }).trimStart() + '\n  ' + jsonLd(ld) +
        `\n  <script>window.AAFS_LESSON_PATH = ${JSON.stringify(l.path)};</script>`)
      .replace('<div class="lesson-loading" id="lessonState">Loading lesson…</div>', `<div class="lesson-loading" id="lessonState">${summary}</div>`);
    if (!page.includes('AAFS_LESSON_PATH') || !page.includes('lesson-prerender')) { console.error('site/lesson.html changed shape; update the lesson page generator'); process.exit(1); }
    const dest = path.join(out, l.path.replace(/^phases\//, ''), 'index.html');
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.writeFileSync(dest, page);
  });
  console.log(`wrote ${live.length} static lesson page(s) into site/lessons/`);
}

/* ------------------------------------------------------------ interview pages (not committed) */
/* /interviews/ is a filterable index; /interviews/<card>/<slug>/ is one question, rendered at build
   time so every answer is in the HTML. interviews.js adds search, filters, reveal and progress. */

function mdInline(s) {
  const codes = [];
  s = htmlEsc(s).replace(/`([^`]+)`/g, (_, c) => `\u0000${codes.push(c) - 1}\u0000`);
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, t, u) => `<a href="${u}"${/^https?:/.test(u) ? ' target="_blank" rel="noopener"' : ''}>${t}</a>`)
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/(^|[^*\w])\*([^*\n]+)\*(?!\w)/g, '$1<em>$2</em>');
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${codes[i]}</code>`);
}

function mdToHtml(md) {
  /* The subset interview answers use: paragraphs, ### headings, lists, tables, code fences, quotes. */
  const out = [], lines = md.split('\n');
  for (let i = 0; i < lines.length;) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    if (line.startsWith('```')) {
      const lang = line.slice(3).trim(), body = [];
      for (i++; i < lines.length && !lines[i].startsWith('```'); i++) body.push(lines[i]);
      i++;
      out.push(`<pre><code${lang ? ` class="language-${lang}"` : ''}>${htmlEsc(body.join('\n'))}</code></pre>`);
    } else if (/^#{3,4} /.test(line)) {
      const n = line.match(/^#+/)[0].length;
      out.push(`<h${n}>${mdInline(line.slice(n + 1))}</h${n}>`); i++;
    } else if (/^\|/.test(line)) {
      const rows = [];
      for (; i < lines.length && /^\|/.test(lines[i]); i++) rows.push(lines[i]);
      const cells = (r) => r.replace(/^\||\|$/g, '').split(/(?<!\\)\|/).map((c) => mdInline(c.trim().replace(/\\\|/g, '|')));
      const body = rows.slice(2).map((r) => `<tr>${cells(r).map((c) => `<td>${c}</td>`).join('')}</tr>`).join('');
      out.push(`<div class="table-wrap"><table><thead><tr>${cells(rows[0]).map((c) => `<th>${c}</th>`).join('')}</tr></thead><tbody>${body}</tbody></table></div>`);
    } else if (/^\s*([-*]|\d+\.) /.test(line)) {
      const ordered = /^\s*\d+\./.test(line), items = [];
      for (; i < lines.length && (/^\s*([-*]|\d+\.) /.test(lines[i]) || (/^\s{2,}\S/.test(lines[i]) && items.length)); i++) {
        if (/^\s*([-*]|\d+\.) /.test(lines[i])) items.push(lines[i].replace(/^\s*([-*]|\d+\.) /, ''));
        else items[items.length - 1] += ' ' + lines[i].trim();
      }
      out.push(`<${ordered ? 'ol' : 'ul'}>${items.map((t) => `<li>${mdInline(t)}</li>`).join('')}</${ordered ? 'ol' : 'ul'}>`);
    } else if (line.startsWith('>')) {
      const body = [];
      for (; i < lines.length && lines[i].startsWith('>'); i++) body.push(lines[i].replace(/^>\s?/, ''));
      out.push(`<blockquote>${mdToHtml(body.join('\n'))}</blockquote>`);
    } else {
      const body = [];
      for (; i < lines.length && lines[i].trim() && !/^(```|#{3,4} |\||\s*([-*]|\d+\.) |>)/.test(lines[i]); i++) body.push(lines[i].trim());
      out.push(`<p>${mdInline(body.join(' '))}</p>`);
    }
  }
  return out.join('\n');
}

const ivLevelChip = (n) => `<span class="iv-level iv-level--${n}">L${n} · ${IV_LEVELS[n]}</span>`;

if (!CHECK && interviews.length) {
  const shell = read('scripts/interview-shell.html');
  if (!shell.includes('<!-- IV:HEAD -->') || !shell.includes('<!-- IV:BODY -->')) { console.error('scripts/interview-shell.html is missing the IV:HEAD / IV:BODY markers'); process.exit(1); }
  const out = path.join(ROOT, 'site/interviews');
  fs.rmSync(out, { recursive: true, force: true });
  const page = (head, body) => shell.replace('<!-- IV:HEAD -->', head).replace('<!-- IV:BODY -->', body);
  const cardName = Object.fromEntries(ivCards.map((c) => [c.id, c.name]));
  const save = (rel, html) => { const dest = path.join(out, rel, 'index.html'); fs.mkdirSync(path.dirname(dest), { recursive: true }); fs.writeFileSync(dest, html); };

  /* index */
  const levelCounts = (qs) => [1, 2, 3, 4].map((n) => qs.filter((q) => q.level === n).length);
  const indexTitle = 'Agentic AI Interview Questions (Free): AI Agent Engineer Interview Prep';
  const indexDesc = clip(`${interviews.length} AI agent interview questions with short answers, full answers, follow-ups and the wrong answers interviewers hear most. Free, from the Agentic AI from Scratch course.`, 158);
  const indexLd = { '@context': 'https://schema.org', '@graph': [
    { '@type': 'CollectionPage', name: indexTitle, description: indexDesc, url: `${cur.site}interviews/`, isPartOf: { '@id': `${cur.site}#website` } },
    { '@type': 'ItemList', itemListElement: interviews.map((q) => ({ '@type': 'ListItem', position: q.num, url: q.url, name: q.title })) },
  ] };
  const cardsHtml = ivCards.map((c) => {
    const qs = interviews.filter((q) => q.card === c.id), lc = levelCounts(qs);
    return `<button type="button" class="iv-card" data-card-filter="${c.id}">` +
      `<span class="iv-card-count">${qs.length} questions</span><span class="iv-card-name">${htmlEsc(c.name)}</span>` +
      `<span class="iv-card-desc">${htmlEsc(c.desc)}</span>` +
      `<span class="iv-card-levels">${lc.map((n, k) => `<span title="${IV_LEVELS[k + 1]}">L${k + 1} ${n}</span>`).join('')}</span></button>`;
  }).join('\n');
  const rowsHtml = interviews.map((q) =>
    `<li class="iv-row" data-id="${q.card}/${q.slug}" data-card="${q.card}" data-level="${q.level}" data-type="${q.type}" ` +
    `data-text="${htmlEsc((q.title + ' ' + plain(q.prompt) + ' ' + cardName[q.card] + ' ' + q.type).toLowerCase())}">` +
    `<span class="iv-row-num">${pad(q.num)}</span><a class="iv-row-title" href="${q.href}">${htmlEsc(q.title)}</a>` +
    `<span class="iv-row-meta">${ivLevelChip(q.level)}<span class="iv-type">${q.type}</span><span class="iv-card-tag">${htmlEsc(cardName[q.card])}</span><span class="iv-min">~${q.minutes} min</span></span>` +
    `<span class="iv-row-done" aria-label="practiced" hidden>✓</span></li>`).join('\n');
  const opts = (pairs) => pairs.map(([v, t]) => `<option value="${v}">${htmlEsc(t)}</option>`).join('');
  save('', page(
    metaTags({ title: indexTitle, description: indexDesc, url: `${cur.site}interviews/` }) + '\n  ' + jsonLd(indexLd),
    `<section class="iv-hero">
      <p class="eyebrow">Interview prep · free</p>
      <h1 class="lesson-title">Interviews</h1>
      <p class="iv-intro">Questions you'll meet when interviewing for AI agent and LLM engineering roles. Each one has a scenario, a short answer, a full answer, follow-ups an interviewer might ask next, and the wrong answers they hear most. Try the question first, then open the answer. Every answer links to the lesson that teaches it.</p>
      <dl class="iv-stats"><div><dt>Questions</dt><dd>${interviews.length}</dd></div><div><dt>Topics</dt><dd>${ivCards.length}</dd></div><div><dt>Levels</dt><dd>4</dd></div><div><dt>Practiced</dt><dd id="ivDoneCount">0</dd></div></dl>
    </section>
    <section class="iv-cards" aria-label="Topics">${cardsHtml}</section>
    <section class="iv-bank" aria-label="Question bank">
      <div class="iv-controls">
        <label class="iv-search"><span class="sr-only">Search questions</span><input type="search" id="ivSearch" placeholder="Search the questions…" autocomplete="off"></label>
        <label><span class="sr-only">Level</span><select id="ivLevel"><option value="">All levels</option>${opts(Object.entries(IV_LEVELS).map(([n, t]) => [n, `L${n} · ${t}`]))}</select></label>
        <label><span class="sr-only">Type</span><select id="ivType"><option value="">All types</option>${opts(IV_TYPES.map((t) => [t, t]))}</select></label>
        <label><span class="sr-only">Topic</span><select id="ivCard"><option value="">All topics</option>${opts(ivCards.map((c) => [c.id, c.name]))}</select></label>
        <label class="iv-check"><input type="checkbox" id="ivHideDone"> Hide practiced</label>
        <button type="button" class="btn" id="ivRandom">Random question</button>
      </div>
      <p class="iv-count" id="ivCount">${interviews.length} questions</p>
      <ol class="iv-list" id="ivList">${rowsHtml}</ol>
      <p class="iv-empty" id="ivEmpty" hidden>No question matches these filters.</p>
    </section>`));

  /* one page per question */
  interviews.forEach((q, k) => {
    const prev = interviews[k - 1], next = interviews[k + 1];
    const title = `${q.title} · AI Agent Interview Question`;
    const description = clip(plain(q.prompt), 158);
    const ld = { '@context': 'https://schema.org', '@graph': [
      { '@type': 'QAPage', mainEntity: { '@type': 'Question', name: q.title, text: plain(q.prompt), answerCount: 1,
        acceptedAnswer: { '@type': 'Answer', text: plain(q.sections['Short answer']), url: q.url } } },
      { '@type': 'BreadcrumbList', itemListElement: [
        { '@type': 'ListItem', position: 1, name: cur.title, item: cur.site },
        { '@type': 'ListItem', position: 2, name: 'Interviews', item: `${cur.site}interviews/` },
        { '@type': 'ListItem', position: 3, name: q.title, item: q.url }] },
    ] };
    const followUps = q.sections['Follow-ups'].split('\n').filter((x) => /^\s*-\s/.test(x)).map((x) => x.replace(/^\s*-\s+/, ''));
    const followHtml = followUps.map((f) => {
      const [ask, expected] = f.split(/\s*\*Expected:\*\s*/);
      return `<li><p>${mdInline(ask)}</p>${expected ? `<details class="iv-expected"><summary>Expected answer</summary><p>${mdInline(expected)}</p></details>` : ''}</li>`;
    }).join('');
    const taught = q.lessons.map((key) => {
      const { p, l } = lessonByKey.get(key);
      return `<li><a href="${lessonUrl(l).replace(cur.site, '/')}">Lesson ${l.num} · ${htmlEsc(l.title)}</a> <span class="iv-min">Phase ${pad(p.index)} · ${htmlEsc(p.name)}</span></li>`;
    }).join('');
    save(`${q.card}/${q.slug}`, page(
      metaTags({ title, description, url: q.url, type: 'article' }) + '\n  ' + jsonLd(ld),
      `<article class="iv-question" data-id="${q.card}/${q.slug}">
      <nav class="lesson-crumbs" aria-label="Breadcrumb"><a href="/interviews/">Interviews</a> / <a href="/interviews/?card=${q.card}">${htmlEsc(cardName[q.card])}</a> / Q${pad(q.num)}</nav>
      <h1 class="lesson-title">${htmlEsc(q.title)}</h1>
      <p class="iv-meta">${ivLevelChip(q.level)}<span class="iv-type">${q.type}</span><span class="iv-min">~${q.minutes} min</span><span class="iv-card-tag">${htmlEsc(cardName[q.card])}</span></p>
      <div class="iv-prompt prose">${mdToHtml(q.prompt)}</div>
      <p class="iv-hint">Answer it out loud or on paper first. Then open the short answer.</p>
      <details class="iv-reveal"><summary>Short answer</summary><div class="prose">${mdToHtml(q.sections['Short answer'])}</div></details>
      <details class="iv-reveal"><summary>Full answer</summary><div class="prose">${mdToHtml(q.sections['Full answer'])}</div></details>
      <section class="iv-section"><h2>Follow-ups</h2><ol class="iv-follow">${followHtml}</ol></section>
      <details class="iv-reveal"><summary>Wrong answers interviewers hear</summary><div class="prose">${mdToHtml(q.sections['Wrong answers'])}</div></details>
      <section class="iv-section"><h2>Taught in</h2><ul class="iv-taught">${taught}</ul></section>
      <div class="iv-actions"><button type="button" class="btn btn--primary" id="ivMark">Mark as practiced</button><button type="button" class="btn" id="ivRandom">Random question</button>
        <a class="btn" href="https://github.com/${cur.repo}/blob/main/${q.file}" target="_blank" rel="noopener">Improve this answer</a></div>
      <nav class="lesson-pager-static iv-pager">${prev ? `<a href="${prev.href}">← ${htmlEsc(prev.title)}</a>` : '<span></span>'}${next ? `<a href="${next.href}">${htmlEsc(next.title)} →</a>` : ''}</nav>
      <script type="application/json" id="ivAll">${JSON.stringify(interviews.map((x) => x.href))}</script>
    </article>`));
  });
  console.log(`wrote ${interviews.length} interview page(s) into site/interviews/`);
}

/* ------------------------------------------------------------ lesson structure */

const problems = [...ivProblems];
for (const { l } of all.filter((x) => x.l.published)) {
  const need = ['code/main.py', 'quiz.json'];
  for (const f of need) if (!exists(`${l.path}/${f}`)) problems.push(`${l.path}: missing ${f}`);
  if (!fs.readdirSync(path.join(ROOT, l.path, 'code')).some((f) => /^test_.*\.py$/.test(f))) problems.push(`${l.path}: no code/test_*.py`);
  const outDir = path.join(ROOT, l.path, 'outputs');
  if (!fs.existsSync(outDir) || !fs.readdirSync(outDir).length) problems.push(`${l.path}: outputs/ is empty`);
  const doc = read(`${l.path}/docs/en.md`);
  for (const h of ['## The Problem', '## The Concept', '## Build It', '## Use It', '## Ship It', '## Exercises'])
    if (!doc.includes(h)) problems.push(`${l.path}: docs/en.md missing "${h}"`);
  for (const [, src] of doc.matchAll(/!\[[^\]]*\]\(([^)\s]+)\)/g))
    if (!/^https?:/.test(src) && !exists(`${l.path}/docs/${src}`)) problems.push(`${l.path}: docs/en.md links a missing image ${src}`);
  if (exists(`${l.path}/quiz.json`)) {
    try {
      const qs = JSON.parse(read(`${l.path}/quiz.json`)).questions || [];
      if (qs.length < 4) problems.push(`${l.path}: quiz.json needs at least 4 questions`);
      qs.forEach((q, k) => {
        if (!['pre', 'check', 'post'].includes(q.stage)) problems.push(`${l.path}: quiz q${k + 1} bad stage`);
        if (!Array.isArray(q.options) || !(q.correct >= 0 && q.correct < q.options.length)) problems.push(`${l.path}: quiz q${k + 1} bad options/correct`);
        if (!q.explanation) problems.push(`${l.path}: quiz q${k + 1} missing explanation`);
      });
    } catch (e) { problems.push(`${l.path}: quiz.json is not valid JSON (${e.message})`); }
  }
}
const ids = new Set();
for (const p of cur.phases) for (const l of p.lessons) {
  const key = `${p.id}/${l.id}`;
  if (ids.has(key)) problems.push(`duplicate lesson id ${key}`);
  ids.add(key);
  if (!/^\d{2}-[a-z0-9-]+$/.test(l.id)) problems.push(`bad lesson id ${key}`);
}
if (problems.length) {
  console.error(`Lesson structure problems:\n  ${problems.join('\n  ')}`);
  process.exit(1);
}

/* ------------------------------------------------------------ done */

if (CHECK && stale.length) {
  console.error(`Generated files are out of date:\n  ${stale.join('\n  ')}\nRun: node scripts/build.mjs`);
  process.exit(1);
}
console.log(`${totals.phases} phases · ${totals.lessons} lessons · ${totals.published} live · ~${totals.hours}h · ${interviews.length} interview questions${CHECK ? ' · generated files up to date' : ''}`);
