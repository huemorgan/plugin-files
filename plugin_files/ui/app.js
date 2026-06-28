// Luna file browser — standalone plugin UI.
// Receives auth token from the shell via postMessage.
//
// Design rules:
//   1. State-driven, synchronous render. Directory listings are fetched ONCE
//      and cached; selecting a file or toggling a folder re-renders from memory
//      with no network call and no flicker. The network is only touched on first
//      load, expanding an *uncached* folder, or a mutation.
//   2. Mount-relative API base. The base is derived from this script's own URL,
//      never hardcoded, so it keeps any host mount prefix (luna-service serves
//      tenants under /a/<slug>/...). A leading-slash path would 404 there.
//   3. Auth-correct previews. JSON/text calls send `Authorization: Bearer` via
//      fetch. Tag-loaded bytes (<img>/<iframe>/<a> for image/PDF/download) can't
//      set headers, so they hit the /read route with a ?token= query param
//      (core's auth dependency accepts either). Everything stays prefixed.

// API base is derived from THIS script's own URL, NOT hardcoded — so it keeps
// any host mount prefix. luna-service serves each tenant under /a/<slug>/..., so
// a leading-slash '/api/p/plugin-files' would resolve to the host root and 404.
// app.js lives at <mount>/api/p/plugin-files/ui/app.js → the API root is one
// level up from ui/. document.currentScript is valid during this classic-script
// initial evaluation; document.baseURI is the fallback.
const _SELF = (document.currentScript && document.currentScript.src)
  || new URL('app.js', document.baseURI).href;
const API = new URL('..', _SELF).href.replace(/\/+$/, '');
let TOKEN = '';
let currentPath = '/';
let selectedFile = null;

// ---- state cache (the seamless fix) ----------------------------------------
const cache = new Map();          // listKey -> entries[]   (a folder's children)
const expandedDirs = new Set(['/']);

function listKey(path) { return path && path !== '/' ? path : '/'; }

// Tag-loaded endpoints (<img>/<iframe>/<a>) can't set an Authorization header,
// so the bytes route also accepts the JWT as a ?token= query param (core's auth
// dependency reads either). Build a fully-prefixed, tokened URL for those tags.
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
// Fallback: try localStorage directly (same origin)
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

// ---- file type detection ---------------------------------------------------
const EXT_COLORS = {
  code: ['py','js','ts','tsx','jsx','sh','bash','rb','go','rs','c','cpp','h','java','kt','swift'],
  doc: ['md','txt','csv','log','rst'],
  pdf: ['pdf'],
  image: ['png','jpg','jpeg','gif','svg','webp','ico','bmp','avif'],
  config: ['yaml','yml','toml','json','env','ini','cfg','conf','xml'],
};

function fileType(name) {
  const ext = (name.split('.').pop() || '').toLowerCase();
  for (const [type, exts] of Object.entries(EXT_COLORS)) {
    if (exts.includes(ext)) return type;
  }
  return 'other';
}

function fileColor(type) {
  const map = { code: 'var(--color-code)', doc: 'var(--color-doc)', pdf: 'var(--color-pdf)',
    image: 'var(--color-image)', config: 'var(--color-config)', other: 'var(--color-other)' };
  return map[type] || map.other;
}

function fileIcon(entry) {
  if (entry.is_dir) return `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="var(--color-folder)" stroke-width="2"><path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z"/></svg>`;
  const color = fileColor(fileType(entry.name));
  return `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>`;
}

function formatSize(bytes) {
  if (bytes == null) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024*1024) return `${(bytes/1024).toFixed(1)} KB`;
  if (bytes < 1024*1024*1024) return `${(bytes/1024/1024).toFixed(1)} MB`;
  return `${(bytes/1024/1024/1024).toFixed(1)} GB`;
}

// ---- tree: cached fetch + SYNCHRONOUS render -------------------------------
async function ensureDir(path) {
  const key = listKey(path);
  if (cache.has(key)) return cache.get(key);
  const res = await api('GET', `/list?path=${encodeURIComponent(path)}`);
  const entries = (await res.json()).entries || [];
  cache.set(key, entries);
  return entries;
}

// Rebuild the whole tree DOM from the in-memory cache. No awaits → instant, no
// flicker. Expanded-but-uncached dirs are guaranteed cached by the click handler
// before this runs.
function renderTree() {
  const tree = document.getElementById('tree');
  tree.innerHTML = '';
  renderDir('/', 0, tree);
}

function renderDir(path, depth, container) {
  const entries = cache.get(listKey(path)) || [];
  for (const entry of entries) {
    const item = document.createElement('div');
    item.className = 'tree-item' + (selectedFile === entry.path ? ' active' : '');
    item.style.setProperty('--depth', depth);
    const caret = entry.is_dir
      ? `<span class="caret ${expandedDirs.has(entry.path) ? 'open' : ''}">▸</span>`
      : `<span class="caret-spacer"></span>`;
    item.innerHTML = `
      ${caret}
      ${fileIcon(entry)}
      <span class="name">${entry.name}</span>
      ${entry.is_dir ? '' : `<span class="size">${formatSize(entry.size_bytes)}</span>`}
      <button class="menu-btn" title="Options">&#x22EF;</button>
    `;
    item.addEventListener('click', async (e) => {
      if (e.target.closest('.menu-btn')) return;
      if (entry.is_dir) {
        if (expandedDirs.has(entry.path)) {
          expandedDirs.delete(entry.path);
          renderTree();
        } else {
          expandedDirs.add(entry.path);
          await ensureDir(entry.path);   // fetch ONCE; cached thereafter
          renderTree();
        }
      } else {
        // Selection is instant: update highlight + preview, NO tree refetch.
        selectedFile = entry.path;
        renderTree();
        showFile(entry);
      }
    });
    item.querySelector('.menu-btn').addEventListener('click', (e) => {
      e.stopPropagation();
      showContextMenu(e, entry);
    });
    container.appendChild(item);

    if (entry.is_dir && expandedDirs.has(entry.path)) {
      renderDir(entry.path, depth + 1, container);
    }
  }
}

// ---- content viewer --------------------------------------------------------
async function showFile(entry) {
  const placeholder = document.getElementById('content-placeholder');
  const viewer = document.getElementById('content-viewer');
  placeholder.classList.add('hidden');
  viewer.classList.remove('hidden');
  viewer.innerHTML = '<div class="placeholder">Loading…</div>';

  const type = fileType(entry.name);
  const status = document.getElementById('status-text');
  status.textContent = `${entry.path} · ${formatSize(entry.size_bytes)} · ${entry.mime_type || 'unknown type'}`;

  // Images — load the tag directly from the tokened, mount-prefixed bytes URL.
  if (type === 'image') {
    const url = readUrl(entry.path);
    viewer.innerHTML = `
      <div class="img-toolbar">
        <span class="img-name">${escapeHtml(entry.name)}</span>
        <span class="img-dim" id="img-dim"></span>
        <span class="img-spacer"></span>
        <button class="btn" id="img-download">Download</button>
      </div>
      <div class="image-view" id="image-view" title="Click to toggle actual size">
        <img id="preview-img" alt="${escapeHtml(entry.name)}" />
      </div>`;
    const img = document.getElementById('preview-img');
    img.addEventListener('load', () => {
      const dim = document.getElementById('img-dim');
      if (dim && img.naturalWidth) dim.textContent = `${img.naturalWidth}×${img.naturalHeight}`;
    });
    img.addEventListener('error', () => {
      viewer.innerHTML = '<div class="placeholder">Failed to load image</div>';
    });
    img.src = url;
    document.getElementById('image-view').addEventListener('click', () => {
      document.getElementById('image-view').classList.toggle('actual-size');
    });
    document.getElementById('img-download').addEventListener('click', () => downloadFile(entry));
    return;
  }

  // PDF — same tokened URL straight into the iframe.
  if (type === 'pdf') {
    viewer.innerHTML = `<iframe src="${readUrl(entry.path)}"></iframe>`;
    return;
  }

  // Text/code/config — editable.
  if (['code', 'doc', 'config'].includes(type) || (entry.size_bytes && entry.size_bytes < 500000)) {
    try {
      const res = await fetch(`${API}/read/${encodeURIComponent(entry.path)}`, {
        headers: { 'Authorization': `Bearer ${TOKEN}` },
      });
      const text = await res.text();
      viewer.innerHTML = `
        <div class="save-bar">
          <span style="font-size:12px;color:var(--text-dim)">${escapeHtml(entry.name)}</span>
          <button class="btn btn-primary" id="save-btn">Save</button>
          <span id="save-status" style="font-size:12px;color:var(--green)"></span>
        </div>
        <textarea id="editor">${escapeHtml(text)}</textarea>
      `;
      document.getElementById('save-btn').addEventListener('click', async () => {
        const content = document.getElementById('editor').value;
        const form = new FormData();
        form.append('content', new Blob([content], { type: 'text/plain' }));
        await api('POST', `/write/${encodeURIComponent(entry.path)}`, form);
        document.getElementById('save-status').textContent = 'Saved';
        // The file's bytes changed → drop its parent listing cache so size refreshes.
        invalidateParent(entry.path);
        setTimeout(() => { const el = document.getElementById('save-status'); if (el) el.textContent = ''; }, 2000);
      });
    } catch {
      viewer.innerHTML = '<div class="placeholder">Failed to load file</div>';
    }
    return;
  }

  // Binary / other — metadata + a WORKING (authed) download.
  viewer.innerHTML = `
    <dl class="meta">
      <dt>Name</dt><dd>${escapeHtml(entry.name)}</dd>
      <dt>Path</dt><dd>${escapeHtml(entry.path)}</dd>
      <dt>Size</dt><dd>${formatSize(entry.size_bytes)}</dd>
      <dt>Type</dt><dd>${escapeHtml(entry.mime_type || 'unknown')}</dd>
    </dl>
    <button class="btn download-btn" id="dl-btn">Download</button>
  `;
  document.getElementById('dl-btn').addEventListener('click', () => downloadFile(entry));
}

// Download: same tokened, mount-prefixed URL via a temp <a>. Same-origin, so the
// `download` attribute names the saved file.
function downloadFile(entry) {
  const a = document.createElement('a');
  a.href = readUrl(entry.path);
  a.download = entry.name;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

// ---- cache invalidation (only on mutations) --------------------------------
function parentDir(path) {
  const i = path.lastIndexOf('/');
  return i <= 0 ? '/' : path.slice(0, i);
}
function invalidateParent(path) { cache.delete(listKey(parentDir(path))); }

// Re-fetch the root + every still-expanded dir, then render. Used after
// mutations only (upload/mkdir/rename/delete) — never on a plain click.
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
    await api('POST', '/move', { src: entry.path, dst: parentPath ? `${parentPath}/${newName}` : newName });
    refresh();
  });

  const del = document.createElement('button');
  del.className = 'danger';
  del.textContent = 'Delete';
  del.addEventListener('click', async () => {
    closeContextMenu();
    if (!confirm(`Delete "${entry.name}"?`)) return;
    await api('DELETE', `/delete/${encodeURIComponent(entry.path)}`);
    if (selectedFile === entry.path) {
      selectedFile = null;
      document.getElementById('content-viewer').classList.add('hidden');
      document.getElementById('content-placeholder').classList.remove('hidden');
    }
    refresh();
  });

  menu.appendChild(rename);
  menu.appendChild(del);
  document.body.appendChild(menu);

  const close = () => closeContextMenu();
  setTimeout(() => document.addEventListener('click', close, { once: true }), 10);
}

function closeContextMenu() {
  document.querySelectorAll('.ctx-menu').forEach((m) => m.remove());
}

// ---- upload ----------------------------------------------------------------
document.getElementById('btn-upload').addEventListener('click', () => {
  document.getElementById('file-input').click();
});
document.getElementById('file-input').addEventListener('change', async (e) => {
  for (const file of e.target.files) {
    const form = new FormData();
    form.append('file', file);
    form.append('path', currentPath);
    await fetch(`${API}/upload?path=${encodeURIComponent(currentPath)}`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${TOKEN}` },
      body: form,
    });
  }
  e.target.value = '';
  refresh();
});

// ---- drag and drop ---------------------------------------------------------
const dropZone = document.getElementById('drop-zone');
const treePaneEl = document.getElementById('tree-pane');
treePaneEl.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('active'); });
treePaneEl.addEventListener('dragleave', () => dropZone.classList.remove('active'));
treePaneEl.addEventListener('drop', async (e) => {
  e.preventDefault();
  dropZone.classList.remove('active');
  for (const file of e.dataTransfer.files) {
    const form = new FormData();
    form.append('file', file);
    await fetch(`${API}/upload?path=${encodeURIComponent(currentPath)}`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${TOKEN}` },
      body: form,
    });
  }
  refresh();
});

// ---- new folder ------------------------------------------------------------
document.getElementById('btn-mkdir').addEventListener('click', async () => {
  const name = prompt('Folder name:');
  if (!name) return;
  const newDir = currentPath.replace(/\/$/, '') + '/' + name;
  await api('POST', `/mkdir/${encodeURIComponent(newDir)}`);
  expandedDirs.add(newDir.replace(/^\//, ''));
  refresh();
});

// ---- usage bar -------------------------------------------------------------
async function loadUsage() {
  try {
    const res = await api('GET', '/usage');
    const data = await res.json();
    const pct = data.max_bytes > 0 ? Math.round(data.used_bytes / data.max_bytes * 100) : 0;
    const color = pct < 60 ? 'var(--green)' : pct < 80 ? 'var(--yellow)' : 'var(--red)';
    document.getElementById('usage').innerHTML = `
      ${formatSize(data.used_bytes)} / ${formatSize(data.max_bytes)}
      <div class="bar"><div class="bar-fill" style="width:${pct}%;background:${color}"></div></div>
    `;
  } catch { /* usage is best-effort */ }
}

function setStatus(text) {
  const el = document.getElementById('status-text');
  if (el) el.textContent = text;
}

// ---- storage type indicator ------------------------------------------------
// Friendly name + plain-English explanation per backend kind. The live state
// (durable?, location, reason) comes from /status and is appended to the tip.
const STORAGE_KINDS = {
  local: {
    label: 'This machine',
    desc: 'Files live on this machine\u2019s own disk \u2014 fast, but if this is a hosted/temporary container they are wiped when it restarts or redeploys. Best for local development.',
  },
  fly: {
    label: 'Persistent disk',
    desc: 'Files live on a persistent disk (a mounted volume) attached to this machine \u2014 local-disk speed, and they survive restarts and redeploys. Best for working with code and large files.',
  },
  db: {
    label: 'Database',
    desc: 'Files are stored as blobs inside the database \u2014 durable with no extra infrastructure and they survive restarts. Best for smaller files.',
  },
  object: {
    label: 'Cloud storage (R2)',
    desc: 'Files live in S3-compatible object storage (Cloudflare R2 / Tigris) \u2014 durable and independent of any single machine. Best for artifacts, attachments and archives (not a code workspace: no in-place edits).',
  },
};

async function loadStorageStatus() {
  const wrap = document.getElementById('storage-indicator');
  if (!wrap) return;
  try {
    const res = await api('GET', '/status');
    const s = await res.json();
    const kind = STORAGE_KINDS[s.backend] || {
      label: s.backend || 'Storage', desc: 'File storage backend.',
    };
    const dot = document.getElementById('storage-dot');
    dot.className = 'storage-dot ' + (s.durable ? 'durable' : 'ephemeral');
    document.getElementById('storage-label').textContent = kind.label;

    const reason = s.durability_reason ? escapeHtml(s.durability_reason) : (s.durable ? 'durable' : 'not durable');
    const loc = s.location ? escapeHtml(s.location) : '';
    document.getElementById('storage-tooltip').innerHTML = `
      <strong>${escapeHtml(kind.label)}</strong> \u2014 ${s.durable ? 'durable' : 'not durable'}<br>
      ${escapeHtml(kind.desc)}
      <span class="tip-meta">${reason}${loc ? ` \u00b7 ${loc}` : ''}</span>
    `;
    wrap.classList.remove('hidden');
  } catch {
    wrap.classList.add('hidden');   // older core / no status route \u2192 just hide it
  }
}

function escapeHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

async function init() {
  await ensureDir('/');
  renderTree();
  loadUsage();
  loadStorageStatus();
}
