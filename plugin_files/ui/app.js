// Luna file browser — standalone plugin UI (vanilla, no build step).
// Receives the auth token from the shell via postMessage.
//
// Design (extends plan 003):
//   1. State-driven, synchronous tree render. Directory listings are fetched
//      ONCE and cached; selecting a file or toggling a folder re-renders from
//      memory. Network is touched only on first load, expanding an *uncached*
//      folder, or a mutation.
//   2. Mount-relative API base derived from this script's own URL (keeps any
//      host mount prefix, e.g. luna-service /a/<slug>/...).
//   3. Auth-correct previews. JSON/text via fetch + Bearer; tag-loaded bytes
//      (<img>/<video>/<audio>/<iframe>/<a>) hit /read with ?token=.
//   4. Rich preview registry (plan 005): image, svg, pdf, video, audio, html,
//      markdown, code (highlighted), csv, json, notebook, font, + a nice
//      fallback. Loading indicators everywhere (caret spinner, skeleton,
//      upload progress). HTML/SVG/markdown are rendered sandboxed / sanitized.

const _SELF = (document.currentScript && document.currentScript.src)
  || new URL('app.js', document.baseURI).href;
const API = new URL('..', _SELF).href.replace(/\/+$/, '');
let TOKEN = '';
let currentPath = '/';
let selectedFile = null;
let viewMode = 'list';          // 'list' | 'grid'
let filterText = '';

// ---- state cache -----------------------------------------------------------
const cache = new Map();          // listKey -> entries[]
const expandedDirs = new Set(['/']);
const loadingDirs = new Set();    // dirs with an in-flight /list (caret spinner)
let visibleRows = [];             // flat, in render order — for keyboard nav
let _objectUrl = null;            // last created blob: URL (revoked on nav)

function listKey(path) { return path && path !== '/' ? path : '/'; }

function readUrl(path) {
  const q = TOKEN ? `?token=${encodeURIComponent(TOKEN)}` : '';
  return `${API}/read/${encodeURIComponent(path)}${q}`;
}

// Auth
window.addEventListener('message', (e) => {
  if (e.data && e.data.type === 'luna-auth') {
    TOKEN = e.data.token;
    init();
  }
});
setTimeout(() => {
  if (!TOKEN) {
    TOKEN = localStorage.getItem('luna.token') || '';
    if (TOKEN) init();
  }
}, 500);

async function api(method, path, body) {
  const opts = { method, headers: { 'Authorization': `Bearer ${TOKEN}` } };
  if (body instanceof FormData) {
    opts.body = body;
  } else if (body) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(`${API}${path}`, opts);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res;
}

async function authedText(path) {
  const res = await fetch(`${API}/read/${encodeURIComponent(path)}`, {
    headers: { 'Authorization': `Bearer ${TOKEN}` },
  });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.text();
}

async function authedBlobUrl(path) {
  if (_objectUrl) { URL.revokeObjectURL(_objectUrl); _objectUrl = null; }
  const res = await fetch(`${API}/read/${encodeURIComponent(path)}`, {
    headers: { 'Authorization': `Bearer ${TOKEN}` },
  });
  if (!res.ok) throw new Error(`${res.status}`);
  const blob = await res.blob();
  _objectUrl = URL.createObjectURL(blob);
  return _objectUrl;
}

// ---- file type detection ---------------------------------------------------
const KINDS = {
  image: ['png','jpg','jpeg','gif','webp','avif','bmp','ico'],
  svg: ['svg'],
  pdf: ['pdf'],
  video: ['mp4','webm','mov','mkv','m4v','ogv'],
  audio: ['mp3','wav','ogg','oga','m4a','flac','aac'],
  html: ['html','htm'],
  markdown: ['md','markdown','mdx'],
  csv: ['csv','tsv'],
  json: ['json'],
  notebook: ['ipynb'],
  font: ['ttf','otf','woff','woff2'],
  code: ['py','js','ts','tsx','jsx','sh','bash','zsh','rb','go','rs','c','cpp','cc','h','hpp',
    'java','kt','swift','sql','css','scss','less','php','pl','lua','r','yaml','yml','toml',
    'ini','cfg','conf','xml','env','dockerfile','makefile','gradle','vue','svelte'],
  text: ['txt','log','rst','text','csv'],
};

// coarse color group for the file glyph
const COLOR_GROUP = {
  code: 'code', text: 'doc', markdown: 'doc', pdf: 'pdf',
  image: 'image', svg: 'image', video: 'video', audio: 'audio',
  html: 'config', json: 'config', csv: 'config', notebook: 'config',
  font: 'other', other: 'other',
};

function detectKind(entry) {
  const ext = (entry.name.split('.').pop() || '').toLowerCase();
  const bare = entry.name.toLowerCase();
  if (bare === 'dockerfile' || bare === 'makefile') return 'code';
  for (const [kind, exts] of Object.entries(KINDS)) {
    if (exts.includes(ext)) return kind;
  }
  const mt = entry.mime_type || '';
  if (mt.startsWith('image/')) return mt.includes('svg') ? 'svg' : 'image';
  if (mt.startsWith('video/')) return 'video';
  if (mt.startsWith('audio/')) return 'audio';
  if (mt === 'application/pdf') return 'pdf';
  if (mt.startsWith('text/')) return 'text';
  return 'other';
}

function fileColor(kind) {
  const g = COLOR_GROUP[kind] || 'other';
  const map = { code: 'var(--color-code)', doc: 'var(--color-doc)', pdf: 'var(--color-pdf)',
    image: 'var(--color-image)', config: 'var(--color-config)', video: 'var(--color-video)',
    audio: 'var(--color-audio)', other: 'var(--color-other)' };
  return map[g] || map.other;
}

function kindGlyph(kind) {
  // Minimal inline SVG paths per kind for the big fallback glyph / grid tiles.
  const paths = {
    image: '<circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/><rect x="3" y="3" width="18" height="18" rx="2"/>',
    video: '<polygon points="10 9 15 12 10 15 10 9"/><rect x="3" y="5" width="18" height="14" rx="2"/>',
    audio: '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
    pdf: '<path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/>',
    code: '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',
    font: '<polyline points="4 7 4 4 20 4 20 7"/><line x1="9" y1="20" x2="15" y2="20"/><line x1="12" y1="4" x2="12" y2="20"/>',
    other: '<path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/>',
  };
  const g = ({ image: 'image', svg: 'image', video: 'video', audio: 'audio', pdf: 'pdf',
    code: 'code', text: 'code', markdown: 'code', json: 'code', csv: 'code', html: 'code',
    notebook: 'code', font: 'font' })[kind] || 'other';
  return paths[g] || paths.other;
}

function fileIcon(entry) {
  if (entry.is_dir) return `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="var(--color-folder)" stroke-width="2"><path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z"/></svg>`;
  const kind = detectKind(entry);
  return `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="${fileColor(kind)}" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>`;
}

function formatSize(bytes) {
  if (bytes == null) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024*1024) return `${(bytes/1024).toFixed(1)} KB`;
  if (bytes < 1024*1024*1024) return `${(bytes/1024/1024).toFixed(1)} MB`;
  return `${(bytes/1024/1024/1024).toFixed(1)} GB`;
}

function escapeHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ---- toasts ----------------------------------------------------------------
function toast(msg, kind = 'info') {
  const host = document.getElementById('toast-host');
  if (!host) return;
  const el = document.createElement('div');
  el.className = `toast toast-${kind}`;
  el.textContent = msg;
  host.appendChild(el);
  requestAnimationFrame(() => el.classList.add('show'));
  setTimeout(() => {
    el.classList.remove('show');
    setTimeout(() => el.remove(), 250);
  }, kind === 'error' ? 5000 : 2500);
}

// ---- tree: cached fetch + synchronous render -------------------------------
async function ensureDir(path) {
  const key = listKey(path);
  if (cache.has(key)) return cache.get(key);
  const res = await api('GET', `/list?path=${encodeURIComponent(path)}`);
  const entries = (await res.json()).entries || [];
  cache.set(key, entries);
  return entries;
}

function filterActive() { return filterText.trim().length > 0; }

function nameMatches(entry) {
  return entry.name.toLowerCase().includes(filterText.trim().toLowerCase());
}

// A dir is shown under an active filter if it (or a cached descendant) matches.
function dirHasMatch(path) {
  const entries = cache.get(listKey(path)) || [];
  for (const e of entries) {
    if (e.is_dir) { if (dirHasMatch(e.path)) return true; }
    else if (nameMatches(e)) return true;
  }
  return false;
}

function renderTree() {
  const tree = document.getElementById('tree');
  tree.className = 'tree' + (viewMode === 'grid' ? ' grid' : '');
  tree.innerHTML = '';
  visibleRows = [];
  renderDir('/', 0, tree);
  if (!tree.children.length) {
    tree.innerHTML = `<div class="tree-empty">${filterActive() ? 'No matches' : 'This folder is empty — drop files to upload'}</div>`;
  }
  renderBreadcrumb();
}

function renderDir(path, depth, container) {
  const entries = cache.get(listKey(path)) || [];
  for (const entry of entries) {
    if (filterActive()) {
      if (entry.is_dir) { if (!dirHasMatch(entry.path)) continue; }
      else if (!nameMatches(entry)) continue;
    }
    const item = document.createElement('div');
    item.className = 'tree-item' + (selectedFile === entry.path ? ' active' : '');
    item.style.setProperty('--depth', depth);
    item.dataset.path = entry.path;

    let caret;
    if (entry.is_dir) {
      if (loadingDirs.has(entry.path)) caret = `<span class="caret loading"><span class="mini-spin"></span></span>`;
      else caret = `<span class="caret ${expandedDirs.has(entry.path) ? 'open' : ''}">▸</span>`;
    } else {
      caret = `<span class="caret-spacer"></span>`;
    }
    item.innerHTML = `
      ${caret}
      ${fileIcon(entry)}
      <span class="name">${escapeHtml(entry.name)}</span>
      ${entry.is_dir ? '' : `<span class="size">${formatSize(entry.size_bytes)}</span>`}
      <button class="menu-btn" title="Options">&#x22EF;</button>
    `;
    const idx = visibleRows.length;
    visibleRows.push(entry);
    item.addEventListener('click', (e) => {
      if (e.target.closest('.menu-btn')) return;
      onRowActivate(entry);
    });
    item.querySelector('.menu-btn').addEventListener('click', (e) => {
      e.stopPropagation();
      showContextMenu(e, entry);
    });
    container.appendChild(item);

    if (entry.is_dir && (expandedDirs.has(entry.path) || (filterActive() && dirHasMatch(entry.path)))) {
      renderDir(entry.path, depth + 1, container);
    }
  }
}

async function onRowActivate(entry) {
  if (entry.is_dir) {
    if (expandedDirs.has(entry.path)) {
      expandedDirs.delete(entry.path);
      renderTree();
    } else {
      expandedDirs.add(entry.path);
      if (!cache.has(listKey(entry.path))) {
        loadingDirs.add(entry.path);
        renderTree();                       // show caret spinner immediately
        try { await ensureDir(entry.path); }
        catch (err) { toast(`Couldn't open ${entry.name}`, 'error'); }
        finally { loadingDirs.delete(entry.path); }
      }
      renderTree();
    }
  } else {
    selectedFile = entry.path;
    currentPath = parentDir(entry.path) === '/' ? '/' : '/' + parentDir(entry.path);
    renderTree();
    showFile(entry);
  }
}

// ---- breadcrumb ------------------------------------------------------------
function renderBreadcrumb() {
  const bc = document.getElementById('breadcrumb');
  if (!bc) return;
  const rel = (selectedFile ? parentDir(selectedFile) : '') || '';
  const parts = rel ? rel.split('/') : [];
  let acc = '';
  const crumbs = [`<a href="#" data-path="/" class="crumb">/</a>`];
  for (const p of parts) {
    acc = acc ? `${acc}/${p}` : p;
    crumbs.push(`<span class="crumb-sep">/</span><a href="#" data-path="${escapeHtml(acc)}" class="crumb">${escapeHtml(p)}</a>`);
  }
  bc.innerHTML = crumbs.join('');
  bc.querySelectorAll('.crumb').forEach((a) => {
    a.addEventListener('click', async (e) => {
      e.preventDefault();
      const p = a.dataset.path;
      if (p !== '/') {
        // expand the chain to this dir
        const segs = p.split('/');
        let cur = '';
        for (const s of segs) { cur = cur ? `${cur}/${s}` : s; expandedDirs.add(cur); try { await ensureDir(cur); } catch {} }
      }
      renderTree();
    });
  });
}

// ---- content viewer: preview registry --------------------------------------
function skeleton() {
  return `<div class="skeleton"><div class="sk-bar"></div><div class="sk-block"></div></div>`;
}

function toolbar(entry, extra = '') {
  return `
    <div class="pv-toolbar">
      <span class="pv-name">${escapeHtml(entry.name)}</span>
      <span class="pv-size">${formatSize(entry.size_bytes)}</span>
      <span class="pv-spacer"></span>
      ${extra}
      <button class="btn pv-download">Download</button>
    </div>`;
}

function wireDownload(viewer, entry) {
  const b = viewer.querySelector('.pv-download');
  if (b) b.addEventListener('click', () => downloadFile(entry));
}

async function showFile(entry) {
  const placeholder = document.getElementById('content-placeholder');
  const viewer = document.getElementById('content-viewer');
  placeholder.classList.add('hidden');
  viewer.classList.remove('hidden');
  viewer.innerHTML = skeleton();

  const kind = detectKind(entry);
  setStatus(`${entry.path} · ${formatSize(entry.size_bytes)} · ${entry.mime_type || 'unknown type'}`);

  const fn = PREVIEWERS[kind] || PREVIEWERS.other;
  try {
    await fn(entry, viewer, kind);
  } catch (err) {
    viewer.innerHTML = toolbar(entry) + `<div class="pv-error">Failed to load preview (${escapeHtml(String(err.message || err))}).</div>`;
    wireDownload(viewer, entry);
  }
}

const PREVIEWERS = {
  image: async (entry, viewer) => {
    viewer.innerHTML = toolbar(entry, `<span class="pv-dim" id="pv-dim"></span>`) +
      `<div class="image-view" id="image-view" title="Click to toggle actual size"><img id="preview-img" alt="${escapeHtml(entry.name)}"></div>`;
    wireDownload(viewer, entry);
    const img = viewer.querySelector('#preview-img');
    img.addEventListener('load', () => {
      const d = viewer.querySelector('#pv-dim');
      if (d && img.naturalWidth) d.textContent = `${img.naturalWidth}×${img.naturalHeight}`;
    });
    img.addEventListener('error', () => { viewer.querySelector('#image-view').innerHTML = '<div class="pv-error">Failed to load image</div>'; });
    img.src = readUrl(entry.path);
    viewer.querySelector('#image-view').addEventListener('click', (e) => e.currentTarget.classList.toggle('actual-size'));
  },

  svg: async (entry, viewer) => {
    let showingSource = false;
    const text = await authedText(entry.path);
    const render = () => {
      viewer.innerHTML = toolbar(entry, `<button class="btn pv-toggle">${showingSource ? 'Preview' : 'Source'}</button>`);
      const body = document.createElement('div');
      if (showingSource) {
        body.className = 'code-view';
        body.innerHTML = `<pre><code class="language-xml">${escapeHtml(text)}</code></pre>`;
      } else {
        body.className = 'image-view';
        body.innerHTML = `<img src="${readUrl(entry.path)}" alt="${escapeHtml(entry.name)}">`;
      }
      viewer.appendChild(body);
      if (showingSource && window.hljs) body.querySelectorAll('code').forEach((c) => hljs.highlightElement(c));
      wireDownload(viewer, entry);
      viewer.querySelector('.pv-toggle').addEventListener('click', () => { showingSource = !showingSource; render(); });
    };
    render();
  },

  pdf: async (entry, viewer) => {
    viewer.innerHTML = toolbar(entry) + `<iframe class="pv-frame" src="${readUrl(entry.path)}"></iframe>`;
    wireDownload(viewer, entry);
  },

  video: async (entry, viewer) => {
    viewer.innerHTML = toolbar(entry) +
      `<div class="media-view"><video controls preload="metadata" src="${readUrl(entry.path)}"></video></div>`;
    wireDownload(viewer, entry);
  },

  audio: async (entry, viewer) => {
    viewer.innerHTML = toolbar(entry) +
      `<div class="media-view audio"><div class="audio-glyph"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">${kindGlyph('audio')}</svg></div>
       <audio controls src="${readUrl(entry.path)}"></audio></div>`;
    wireDownload(viewer, entry);
  },

  html: async (entry, viewer) => {
    let showingSource = false;
    const text = await authedText(entry.path);
    const render = () => {
      viewer.innerHTML = toolbar(entry, `<button class="btn pv-toggle">${showingSource ? 'Preview' : 'Source'}</button>`);
      if (showingSource) {
        const body = document.createElement('div');
        body.className = 'code-view';
        body.innerHTML = `<pre><code class="language-html">${escapeHtml(text)}</code></pre>`;
        viewer.appendChild(body);
        if (window.hljs) body.querySelectorAll('code').forEach((c) => hljs.highlightElement(c));
      } else {
        // Sandboxed, script-free render of untrusted HTML.
        const frame = document.createElement('iframe');
        frame.className = 'pv-frame';
        frame.setAttribute('sandbox', '');
        frame.srcdoc = text;
        viewer.appendChild(frame);
      }
      wireDownload(viewer, entry);
      viewer.querySelector('.pv-toggle').addEventListener('click', () => { showingSource = !showingSource; render(); });
    };
    render();
  },

  markdown: async (entry, viewer) => {
    let showingSource = false;
    const text = await authedText(entry.path);
    const render = () => {
      viewer.innerHTML = toolbar(entry, `<button class="btn pv-toggle">${showingSource ? 'Rendered' : 'Source'}</button>`);
      const body = document.createElement('div');
      if (showingSource) {
        body.className = 'code-view';
        body.innerHTML = `<pre><code class="language-markdown">${escapeHtml(text)}</code></pre>`;
        viewer.appendChild(body);
        if (window.hljs) body.querySelectorAll('code').forEach((c) => hljs.highlightElement(c));
      } else {
        body.className = 'markdown-view';
        const raw = window.marked ? marked.parse(text) : escapeHtml(text);
        body.innerHTML = window.DOMPurify ? DOMPurify.sanitize(raw) : raw;
        viewer.appendChild(body);
        if (window.hljs) body.querySelectorAll('pre code').forEach((c) => hljs.highlightElement(c));
      }
      wireDownload(viewer, entry);
      viewer.querySelector('.pv-toggle').addEventListener('click', () => { showingSource = !showingSource; render(); });
    };
    render();
  },

  code: async (entry, viewer) => codeOrText(entry, viewer, true),
  text: async (entry, viewer) => codeOrText(entry, viewer, false),

  csv: async (entry, viewer) => {
    const text = await authedText(entry.path);
    const delim = entry.name.toLowerCase().endsWith('.tsv') ? '\t' : '';
    const parsed = window.Papa ? Papa.parse(text.trim(), { delimiter: delim, skipEmptyLines: true }) : { data: text.split('\n').map((r) => r.split(',')) };
    const rows = parsed.data || [];
    const head = rows[0] || [];
    const bodyRows = rows.slice(1, 2001); // cap for the DOM
    let html = toolbar(entry, `<span class="pv-size">${rows.length} rows</span>`) + `<div class="table-view"><table><thead><tr>`;
    html += head.map((h) => `<th>${escapeHtml(h)}</th>`).join('');
    html += `</tr></thead><tbody>`;
    for (const r of bodyRows) html += `<tr>${r.map((c) => `<td>${escapeHtml(c)}</td>`).join('')}</tr>`;
    html += `</tbody></table>`;
    if (rows.length > 2001) html += `<div class="pv-note">Showing first 2000 rows of ${rows.length - 1}.</div>`;
    html += `</div>`;
    viewer.innerHTML = html;
    wireDownload(viewer, entry);
  },

  json: async (entry, viewer) => {
    const text = await authedText(entry.path);
    let pretty, valid = true;
    try { pretty = JSON.stringify(JSON.parse(text), null, 2); } catch { pretty = text; valid = false; }
    viewer.innerHTML = toolbar(entry, valid ? '' : `<span class="pv-badge warn">invalid JSON</span>`) +
      `<div class="code-view"><pre><code class="language-json">${escapeHtml(pretty)}</code></pre></div>`;
    wireDownload(viewer, entry);
    if (window.hljs) viewer.querySelectorAll('code').forEach((c) => hljs.highlightElement(c));
  },

  notebook: async (entry, viewer) => {
    const text = await authedText(entry.path);
    let nb;
    try { nb = JSON.parse(text); } catch { return PREVIEWERS.json(entry, viewer); }
    let html = toolbar(entry) + `<div class="markdown-view nb-view">`;
    for (const cell of (nb.cells || [])) {
      const src = Array.isArray(cell.source) ? cell.source.join('') : (cell.source || '');
      if (cell.cell_type === 'markdown') {
        const raw = window.marked ? marked.parse(src) : escapeHtml(src);
        html += `<div class="nb-md">${window.DOMPurify ? DOMPurify.sanitize(raw) : raw}</div>`;
      } else if (cell.cell_type === 'code') {
        html += `<pre class="nb-code"><code class="language-python">${escapeHtml(src)}</code></pre>`;
        for (const out of (cell.outputs || [])) {
          const t = out.text || (out.data && out.data['text/plain']) || '';
          const txt = Array.isArray(t) ? t.join('') : t;
          if (txt) html += `<pre class="nb-out">${escapeHtml(txt)}</pre>`;
          const img = out.data && out.data['image/png'];
          if (img) html += `<img class="nb-img" src="data:image/png;base64,${img}">`;
        }
      }
    }
    html += `</div>`;
    viewer.innerHTML = html;
    wireDownload(viewer, entry);
    if (window.hljs) viewer.querySelectorAll('pre code').forEach((c) => hljs.highlightElement(c));
  },

  font: async (entry, viewer) => {
    const url = await authedBlobUrl(entry.path);
    const fam = `pv-font-${Date.now()}`;
    const style = document.createElement('style');
    style.textContent = `@font-face{font-family:'${fam}';src:url('${url}');}`;
    document.head.appendChild(style);
    const sizes = [12, 18, 24, 36, 48, 64];
    let html = toolbar(entry) + `<div class="font-view" style="font-family:'${fam}'">`;
    html += `<div class="font-pangram" style="font-size:40px">The quick brown fox jumps over the lazy dog</div>`;
    html += `<div class="font-glyphs">ABCDEFGHIJKLMNOPQRSTUVWXYZ<br>abcdefghijklmnopqrstuvwxyz<br>0123456789 &amp; ! ? @ # $ %</div>`;
    for (const s of sizes) html += `<div class="font-line" style="font-size:${s}px">${s}px — Sphinx of black quartz, judge my vow</div>`;
    html += `</div>`;
    viewer.innerHTML = html;
    wireDownload(viewer, entry);
  },

  other: async (entry, viewer) => {
    const kind = detectKind(entry);
    viewer.innerHTML = toolbar(entry) + `
      <div class="fallback-view">
        <div class="fallback-glyph"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2">${kindGlyph(kind)}</svg></div>
        <div class="fallback-title">${escapeHtml(entry.name)}</div>
        <div class="fallback-sub">No inline preview for this file type.</div>
        <dl class="meta">
          <dt>Path</dt><dd>${escapeHtml(entry.path)}</dd>
          <dt>Size</dt><dd>${formatSize(entry.size_bytes)}</dd>
          <dt>Type</dt><dd>${escapeHtml(entry.mime_type || 'unknown')}</dd>
        </dl>
        <button class="btn btn-primary fallback-dl">Download</button>
      </div>`;
    wireDownload(viewer, entry);
    viewer.querySelector('.fallback-dl').addEventListener('click', () => downloadFile(entry));
  },
};

async function codeOrText(entry, viewer, highlight) {
  const text = await authedText(entry.path);
  let editing = false;
  const langClass = highlight ? `language-${(entry.name.split('.').pop() || '').toLowerCase()}` : '';
  const render = () => {
    viewer.innerHTML = toolbar(entry, editing
      ? `<button class="btn btn-primary pv-save">Save</button><span class="pv-saved"></span>`
      : `<button class="btn pv-edit">Edit</button>`);
    if (editing) {
      const ta = document.createElement('textarea');
      ta.id = 'editor';
      ta.value = text;
      viewer.appendChild(ta);
      viewer.querySelector('.pv-save').addEventListener('click', async () => {
        const content = viewer.querySelector('#editor').value;
        const form = new FormData();
        form.append('content', new Blob([content], { type: 'text/plain' }));
        try {
          await api('POST', `/write/${encodeURIComponent(entry.path)}`, form);
          viewer.querySelector('.pv-saved').textContent = 'Saved';
          invalidateParent(entry.path);
          toast('Saved', 'success');
        } catch { toast('Save failed', 'error'); }
      });
    } else {
      const body = document.createElement('div');
      body.className = 'code-view';
      body.innerHTML = `<pre><code class="${langClass}">${escapeHtml(text)}</code></pre>`;
      viewer.appendChild(body);
      if (highlight && window.hljs) body.querySelectorAll('code').forEach((c) => { try { hljs.highlightElement(c); } catch {} });
      viewer.querySelector('.pv-edit').addEventListener('click', () => { editing = true; render(); });
    }
    wireDownload(viewer, entry);
  };
  render();
}

function downloadFile(entry) {
  const a = document.createElement('a');
  a.href = readUrl(entry.path);
  a.download = entry.name;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

// ---- cache invalidation ----------------------------------------------------
function parentDir(path) {
  const i = path.lastIndexOf('/');
  return i <= 0 ? '/' : path.slice(0, i);
}
function invalidateParent(path) { cache.delete(listKey(parentDir(path))); }

async function refresh() {
  cache.clear();
  await ensureDir('/');
  for (const d of expandedDirs) {
    if (d !== '/') { try { await ensureDir(d); } catch { expandedDirs.delete(d); } }
  }
  renderTree();
  loadUsage();
}

// ---- context menu ----------------------------------------------------------
function showContextMenu(e, entry) {
  closeContextMenu();
  const menu = document.createElement('div');
  menu.className = 'ctx-menu';
  menu.style.left = e.clientX + 'px';
  menu.style.top = e.clientY + 'px';

  const rename = document.createElement('button');
  rename.textContent = 'Rename';
  rename.addEventListener('click', async () => {
    closeContextMenu();
    const newName = prompt('New name:', entry.name);
    if (!newName || newName === entry.name) return;
    const parentPath = entry.path.split('/').slice(0, -1).join('/');
    try {
      await api('POST', '/move', { src: entry.path, dst: parentPath ? `${parentPath}/${newName}` : newName });
      refresh();
    } catch { toast('Rename failed', 'error'); }
  });

  const del = document.createElement('button');
  del.className = 'danger';
  del.textContent = 'Delete';
  del.addEventListener('click', async () => {
    closeContextMenu();
    if (!confirm(`Delete "${entry.name}"?`)) return;
    try {
      await api('DELETE', `/delete/${encodeURIComponent(entry.path)}`);
      if (selectedFile === entry.path) {
        selectedFile = null;
        document.getElementById('content-viewer').classList.add('hidden');
        document.getElementById('content-placeholder').classList.remove('hidden');
      }
      refresh();
    } catch { toast('Delete failed', 'error'); }
  });

  menu.appendChild(rename);
  menu.appendChild(del);
  document.body.appendChild(menu);
  setTimeout(() => document.addEventListener('click', closeContextMenu, { once: true }), 10);
}
function closeContextMenu() {
  document.querySelectorAll('.ctx-menu').forEach((m) => m.remove());
}

// ---- upload (with progress) ------------------------------------------------
function uploadOne(file) {
  return new Promise((resolve, reject) => {
    const host = document.getElementById('upload-progress');
    host.classList.remove('hidden');
    const row = document.createElement('div');
    row.className = 'up-row';
    row.innerHTML = `<span class="up-name">${escapeHtml(file.name)}</span><div class="up-bar"><div class="up-fill"></div></div>`;
    host.appendChild(row);
    const fill = row.querySelector('.up-fill');

    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${API}/upload?path=${encodeURIComponent(currentPath)}`);
    xhr.setRequestHeader('Authorization', `Bearer ${TOKEN}`);
    xhr.upload.addEventListener('progress', (e) => {
      if (e.lengthComputable) fill.style.width = `${Math.round(e.loaded / e.total * 100)}%`;
    });
    xhr.addEventListener('load', () => {
      fill.style.width = '100%';
      setTimeout(() => { row.remove(); if (!host.children.length) host.classList.add('hidden'); }, 600);
      if (xhr.status >= 200 && xhr.status < 300) resolve();
      else { toast(`Upload failed: ${file.name}`, 'error'); reject(new Error(xhr.statusText)); }
    });
    xhr.addEventListener('error', () => { row.remove(); toast(`Upload failed: ${file.name}`, 'error'); reject(new Error('network')); });
    const form = new FormData();
    form.append('file', file);
    xhr.send(form);
  });
}

async function uploadFiles(fileList) {
  for (const file of fileList) {
    try { await uploadOne(file); } catch {}
  }
  refresh();
}

document.getElementById('btn-upload').addEventListener('click', () => document.getElementById('file-input').click());
document.getElementById('file-input').addEventListener('change', (e) => {
  const files = [...e.target.files];
  e.target.value = '';
  uploadFiles(files);
});

// ---- drag and drop ---------------------------------------------------------
const dropZone = document.getElementById('drop-zone');
const treePaneEl = document.getElementById('tree-pane');
treePaneEl.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('active'); });
treePaneEl.addEventListener('dragleave', () => dropZone.classList.remove('active'));
treePaneEl.addEventListener('drop', (e) => {
  e.preventDefault();
  dropZone.classList.remove('active');
  uploadFiles([...e.dataTransfer.files]);
});

// ---- new folder ------------------------------------------------------------
document.getElementById('btn-mkdir').addEventListener('click', async () => {
  const name = prompt('Folder name:');
  if (!name) return;
  const newDir = currentPath.replace(/\/$/, '') + '/' + name;
  try {
    await api('POST', `/mkdir/${encodeURIComponent(newDir)}`);
    expandedDirs.add(newDir.replace(/^\//, ''));
    refresh();
  } catch { toast('Could not create folder', 'error'); }
});

// ---- filter ----------------------------------------------------------------
document.getElementById('filter').addEventListener('input', (e) => {
  filterText = e.target.value;
  renderTree();
});

// ---- list / grid toggle ----------------------------------------------------
document.getElementById('btn-view').addEventListener('click', () => {
  viewMode = viewMode === 'list' ? 'grid' : 'list';
  renderTree();
});

// ---- keyboard navigation ---------------------------------------------------
document.addEventListener('keydown', (e) => {
  if (['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) return;
  if (!visibleRows.length) return;
  let idx = visibleRows.findIndex((r) => r.path === selectedFile);
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    idx = Math.min(visibleRows.length - 1, idx + 1);
    focusRow(idx);
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    idx = Math.max(0, idx - 1);
    focusRow(idx);
  } else if (e.key === 'Enter' && idx >= 0) {
    onRowActivate(visibleRows[idx]);
  } else if ((e.key === 'ArrowRight' || e.key === 'ArrowLeft') && idx >= 0) {
    const entry = visibleRows[idx];
    if (entry.is_dir) {
      const open = expandedDirs.has(entry.path);
      if (e.key === 'ArrowRight' && !open) onRowActivate(entry);
      if (e.key === 'ArrowLeft' && open) onRowActivate(entry);
    }
  }
});
function focusRow(idx) {
  const entry = visibleRows[idx];
  if (!entry) return;
  selectedFile = entry.path;
  renderTree();
  const el = document.querySelector(`.tree-item[data-path="${CSS.escape(entry.path)}"]`);
  if (el) el.scrollIntoView({ block: 'nearest' });
  if (!entry.is_dir) showFile(entry);
}

// ---- usage bar -------------------------------------------------------------
async function loadUsage() {
  try {
    const res = await api('GET', '/usage');
    const data = await res.json();
    const pct = data.max_bytes > 0 ? Math.round(data.used_bytes / data.max_bytes * 100) : 0;
    const color = pct < 60 ? 'var(--green)' : pct < 80 ? 'var(--yellow)' : 'var(--red)';
    document.getElementById('usage').innerHTML = `
      ${formatSize(data.used_bytes)} / ${formatSize(data.max_bytes)}
      <div class="bar"><div class="bar-fill" style="width:${pct}%;background:${color}"></div></div>`;
  } catch { /* best-effort */ }
}

function setStatus(text) {
  const el = document.getElementById('status-text');
  if (el) el.textContent = text;
}

// ---- storage type indicator ------------------------------------------------
const STORAGE_KINDS = {
  local: { label: 'This machine', desc: 'Files live on this machine\u2019s own disk \u2014 fast, but if this is a hosted/temporary container they are wiped when it restarts or redeploys. Best for local development.' },
  fly: { label: 'Persistent disk', desc: 'Files live on a persistent disk (a mounted volume) attached to this machine \u2014 local-disk speed, and they survive restarts and redeploys. Best for working with code and large files.' },
  db: { label: 'Database', desc: 'Files are stored as blobs inside the database \u2014 durable with no extra infrastructure and they survive restarts. Best for smaller files.' },
  object: { label: 'Cloud storage (R2)', desc: 'Files live in S3-compatible object storage (Cloudflare R2 / Tigris) \u2014 durable and independent of any single machine. Best for artifacts, attachments and archives (not a code workspace: no in-place edits).' },
};

async function loadStorageStatus() {
  const wrap = document.getElementById('storage-indicator');
  if (!wrap) return;
  try {
    const res = await api('GET', '/status');
    const s = await res.json();
    const kind = STORAGE_KINDS[s.backend] || { label: s.backend || 'Storage', desc: 'File storage backend.' };
    document.getElementById('storage-dot').className = 'storage-dot ' + (s.durable ? 'durable' : 'ephemeral');
    document.getElementById('storage-label').textContent = kind.label;
    const reason = s.durability_reason ? escapeHtml(s.durability_reason) : (s.durable ? 'durable' : 'not durable');
    const loc = s.location ? escapeHtml(s.location) : '';
    document.getElementById('storage-tooltip').innerHTML = `
      <strong>${escapeHtml(kind.label)}</strong> \u2014 ${s.durable ? 'durable' : 'not durable'}<br>
      ${escapeHtml(kind.desc)}
      <span class="tip-meta">${reason}${loc ? ` \u00b7 ${loc}` : ''}</span>`;
    wrap.classList.remove('hidden');
  } catch {
    wrap.classList.add('hidden');
  }
}

async function init() {
  const tree = document.getElementById('tree');
  tree.innerHTML = `<div class="tree-empty"><span class="mini-spin"></span> Loading…</div>`;
  try { await ensureDir('/'); } catch { toast('Could not load files', 'error'); }
  renderTree();
  loadUsage();
  loadStorageStatus();
}
