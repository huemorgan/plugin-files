// Reader window — a real browser window (window.open), not an in-iframe modal,
// so a document can be read on top of everything at full screen height.
//
// Same origin as the pane, so the auth token comes from localStorage; the
// opener also pushes it via postMessage as the reliable path when the shell
// handed the pane a token that never reached localStorage.

const _SELF = (document.currentScript && document.currentScript.src)
  || new URL('reader.js', document.baseURI).href;
const API = new URL('..', _SELF).href.replace(/\/+$/, '');

const params = new URLSearchParams(location.search);
const PATH = params.get('path') || '';
let TOKEN = localStorage.getItem('luna.token') || '';

const docEl = document.getElementById('rd-doc');
const titleEl = document.getElementById('rd-title');

function readUrl(path) {
  const q = TOKEN ? `?token=${encodeURIComponent(TOKEN)}` : '';
  return `${API}/read/${encodeURIComponent(path)}${q}`;
}

function parentDir(path) {
  const i = path.lastIndexOf('/');
  return i <= 0 ? '' : path.slice(0, i);
}

async function load() {
  titleEl.textContent = PATH.split('/').pop() || 'Document';
  document.title = `${titleEl.textContent} — Luna Files`;
  try {
    const res = await fetch(`${API}/read/${encodeURIComponent(PATH)}`, {
      headers: { Authorization: `Bearer ${TOKEN}` },
    });
    if (!res.ok) throw new Error(`${res.status}`);
    const text = await res.text();
    window.LunaMd.renderMarkdown(text, docEl, {
      dir: parentDir(PATH),
      readUrl,
    });
  } catch (err) {
    docEl.innerHTML = `<p class="rd-error">Could not open this document (${String(err.message || err)}).</p>`;
  }
}

// The opener may hand us a fresher token than localStorage holds.
window.addEventListener('message', (e) => {
  if (e.origin !== location.origin) return;
  if (e.data && e.data.type === 'luna-auth' && e.data.token) {
    const changed = e.data.token !== TOKEN;
    TOKEN = e.data.token;
    if (changed) load();
  }
});
if (window.opener) {
  try { window.opener.postMessage({ type: 'luna-reader-ready' }, location.origin); } catch (e) { /* closed */ }
}

// ---- text size (persisted) ---------------------------------------------------
const SIZES = [15, 16, 17, 18, 20, 22];
let sizeIdx = Number(localStorage.getItem('luna.files.readerSize') || 2);

function applySize() {
  sizeIdx = Math.max(0, Math.min(SIZES.length - 1, sizeIdx));
  docEl.style.fontSize = `${SIZES[sizeIdx]}px`;
  localStorage.setItem('luna.files.readerSize', String(sizeIdx));
}
document.getElementById('rd-bigger').addEventListener('click', () => { sizeIdx++; applySize(); });
document.getElementById('rd-smaller').addEventListener('click', () => { sizeIdx--; applySize(); });
document.getElementById('rd-print').addEventListener('click', () => window.print());
document.getElementById('rd-close').addEventListener('click', () => window.close());
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') window.close();
  if ((e.metaKey || e.ctrlKey) && (e.key === '=' || e.key === '+')) { e.preventDefault(); sizeIdx++; applySize(); }
  if ((e.metaKey || e.ctrlKey) && e.key === '-') { e.preventDefault(); sizeIdx--; applySize(); }
});

applySize();
load();
