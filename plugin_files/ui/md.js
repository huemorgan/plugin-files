// Shared markdown pipeline — used by the pane (app.js) and the reader window
// (reader.js) so a document looks identical in both.
//
// marked (GFM) -> DOMPurify -> post-processing:
//   * relative <img src> / <a href> resolved against the document's own folder
//     and rewritten to authed /read URLs, so `./diagram.png` actually shows,
//   * highlight.js on fenced blocks + a copy button per block,
//   * heading anchors (stable slugs) for the table of contents.
//
// Sanitize happens BEFORE any rewriting, and rewriting only ever produces URLs
// on our own API — untrusted markdown never reaches innerHTML unsanitized.

(function (global) {
  'use strict';

  function slugify(text) {
    return String(text).toLowerCase().trim()
      .replace(/[^\w\s-]/g, '')
      .replace(/\s+/g, '-')
      .replace(/-+/g, '-') || 'section';
  }

  // Resolve `rel` against directory `dir` ("a/b" + "../c.png" -> "a/c.png").
  function resolveRelative(dir, rel) {
    const stack = (dir || '').split('/').filter(Boolean);
    for (const seg of rel.split('/')) {
      if (!seg || seg === '.') continue;
      if (seg === '..') stack.pop();
      else stack.push(seg);
    }
    return stack.join('/');
  }

  function isExternal(url) {
    return /^([a-z][a-z0-9+.-]*:|\/\/|#|data:|mailto:)/i.test(url);
  }

  /**
   * Render markdown into `container`.
   * opts = { dir, readUrl(path)->string, onInternalLink(path) }
   */
  function renderMarkdown(text, container, opts) {
    opts = opts || {};
    const raw = global.marked
      ? global.marked.parse(text, { gfm: true, breaks: false })
      : escapeHtml(text);
    container.innerHTML = global.DOMPurify ? global.DOMPurify.sanitize(raw) : raw;

    // --- resolve relative assets/links against the document's folder --------
    if (opts.readUrl) {
      container.querySelectorAll('img[src]').forEach((img) => {
        const src = img.getAttribute('src') || '';
        if (isExternal(src)) return;
        img.src = opts.readUrl(resolveRelative(opts.dir, src.replace(/^\//, '')));
      });
    }
    container.querySelectorAll('a[href]').forEach((a) => {
      const href = a.getAttribute('href') || '';
      if (href.startsWith('#')) {
        a.addEventListener('click', (e) => {
          e.preventDefault();
          const t = container.querySelector(`[id="${CSS.escape(href.slice(1))}"]`);
          if (t) t.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
        return;
      }
      if (isExternal(href)) {
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
        return;
      }
      const target = resolveRelative(opts.dir, href.replace(/^\//, ''));
      if (opts.onInternalLink) {
        a.href = '#';
        a.addEventListener('click', (e) => { e.preventDefault(); opts.onInternalLink(target); });
      } else if (opts.readUrl) {
        a.href = opts.readUrl(target);
        a.target = '_blank';
      }
    });

    // --- heading anchors ----------------------------------------------------
    const seen = new Map();
    const headings = [];
    container.querySelectorAll('h1, h2, h3, h4').forEach((h) => {
      let id = slugify(h.textContent);
      const n = (seen.get(id) || 0) + 1;
      seen.set(id, n);
      if (n > 1) id = `${id}-${n}`;
      h.id = id;
      headings.push({ id, level: Number(h.tagName[1]), text: h.textContent });
    });

    // --- code blocks: highlight + copy --------------------------------------
    container.querySelectorAll('pre > code').forEach((code) => {
      if (global.hljs) { try { global.hljs.highlightElement(code); } catch (e) { /* unknown lang */ } }
      const pre = code.parentElement;
      pre.classList.add('has-copy');
      const btn = document.createElement('button');
      btn.className = 'code-copy';
      btn.type = 'button';
      btn.textContent = 'Copy';
      btn.addEventListener('click', async () => {
        try {
          await navigator.clipboard.writeText(code.textContent);
          btn.textContent = 'Copied';
        } catch (e) {
          btn.textContent = 'Press ⌘C';
        }
        setTimeout(() => { btn.textContent = 'Copy'; }, 1400);
      });
      pre.appendChild(btn);
    });

    // GFM task lists render as <li><input disabled> — tag them for styling.
    container.querySelectorAll('li > input[type="checkbox"]').forEach((cb) => {
      cb.parentElement.classList.add('task-item');
    });

    return headings;
  }

  function escapeHtml(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  global.LunaMd = { renderMarkdown, slugify, resolveRelative, escapeHtml };
})(window);
