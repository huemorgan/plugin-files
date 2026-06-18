// Luna file browser — standalone plugin UI
// Receives auth token from shell via postMessage

const API = '/api/p/plugin-files';
let TOKEN = '';
let currentPath = '/';
let selectedFile = null;
let expandedDirs = new Set(['/']);

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
  const opts = {
    method,
    headers: { 'Authorization': `Bearer ${TOKEN}` },
  };
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

// File type detection
const EXT_COLORS = {
  code: ['py','js','ts','tsx','jsx','sh','bash','rb','go','rs','c','cpp','h','java','kt','swift'],
  doc: ['md','txt','csv','log','rst'],
  pdf: ['pdf'],
  image: ['png','jpg','jpeg','gif','svg','webp','ico','bmp'],
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

// Tree rendering
async function loadTree(path = '/') {
  const res = await api('GET', `/list?path=${encodeURIComponent(path)}`);
  return (await res.json()).entries || [];
}

async function renderTree() {
  const tree = document.getElementById('tree');
  tree.innerHTML = '';
  await renderDir('/', 0, tree);
}

async function renderDir(path, depth, container) {
  const entries = await loadTree(path);
  for (const entry of entries) {
    const item = document.createElement('div');
    item.className = 'tree-item' + (selectedFile === entry.path ? ' active' : '');
    item.style.setProperty('--depth', depth);
    item.innerHTML = `
      ${fileIcon(entry)}
      <span class="name">${entry.name}</span>
      ${entry.is_dir ? '' : `<span class="size">${formatSize(entry.size_bytes)}</span>`}
      <button class="menu-btn" title="Options">&#x22EF;</button>
    `;
    item.addEventListener('click', (e) => {
      if (e.target.closest('.menu-btn')) return;
      if (entry.is_dir) {
        if (expandedDirs.has(entry.path)) expandedDirs.delete(entry.path);
        else expandedDirs.add(entry.path);
        renderTree();
      } else {
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
      await renderDir(entry.path, depth + 1, container);
    }
  }
}

// Content viewer
async function showFile(entry) {
  const placeholder = document.getElementById('content-placeholder');
  const viewer = document.getElementById('content-viewer');
  placeholder.classList.add('hidden');
  viewer.classList.remove('hidden');
  viewer.innerHTML = '<div class="placeholder">Loading...</div>';

  const type = fileType(entry.name);
  const status = document.getElementById('status-text');
  status.textContent = `${entry.path} · ${formatSize(entry.size_bytes)} · ${entry.mime_type || 'unknown type'}`;

  if (type === 'image') {
    viewer.innerHTML = `<img src="${API}/read/${encodeURIComponent(entry.path)}" alt="${entry.name}" />`;
    return;
  }

  if (type === 'pdf') {
    viewer.innerHTML = `<iframe src="${API}/read/${encodeURIComponent(entry.path)}"></iframe>`;
    return;
  }

  // Text/code files — editable
  if (['code', 'doc', 'config'].includes(type) || (entry.size_bytes && entry.size_bytes < 500000)) {
    try {
      const res = await fetch(`${API}/read/${encodeURIComponent(entry.path)}`, {
        headers: { 'Authorization': `Bearer ${TOKEN}` },
      });
      const text = await res.text();
      viewer.innerHTML = `
        <div class="save-bar">
          <span style="font-size:12px;color:var(--text-dim)">${entry.name}</span>
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
        setTimeout(() => { const el = document.getElementById('save-status'); if (el) el.textContent = ''; }, 2000);
      });
    } catch {
      viewer.innerHTML = '<div class="placeholder">Failed to load file</div>';
    }
    return;
  }

  // Binary / other
  viewer.innerHTML = `
    <dl class="meta">
      <dt>Name</dt><dd>${entry.name}</dd>
      <dt>Path</dt><dd>${entry.path}</dd>
      <dt>Size</dt><dd>${formatSize(entry.size_bytes)}</dd>
      <dt>Type</dt><dd>${entry.mime_type || 'unknown'}</dd>
    </dl>
    <a href="${API}/read/${encodeURIComponent(entry.path)}" download="${entry.name}" class="btn download-btn">Download</a>
  `;
}

// Context menu
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
    await api('POST', '/move', { src: entry.path, dst: `${parentPath}/${newName}` });
    renderTree();
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
    renderTree();
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

// Upload
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
  renderTree();
});

// Drag and drop
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
  renderTree();
});

// New folder
document.getElementById('btn-mkdir').addEventListener('click', async () => {
  const name = prompt('Folder name:');
  if (!name) return;
  await api('POST', `/mkdir/${encodeURIComponent(currentPath.replace(/\/$/, '') + '/' + name)}`);
  expandedDirs.add(currentPath.replace(/\/$/, '') + '/' + name);
  renderTree();
});

// Usage bar
async function loadUsage() {
  const res = await api('GET', '/usage');
  const data = await res.json();
  const pct = data.max_bytes > 0 ? Math.round(data.used_bytes / data.max_bytes * 100) : 0;
  const color = pct < 60 ? 'var(--green)' : pct < 80 ? 'var(--yellow)' : 'var(--red)';
  document.getElementById('usage').innerHTML = `
    ${formatSize(data.used_bytes)} / ${formatSize(data.max_bytes)}
    <div class="bar"><div class="bar-fill" style="width:${pct}%;background:${color}"></div></div>
  `;
}

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

async function init() {
  await renderTree();
  await loadUsage();
}
