# 001 — the reading plan: markdown reader, media tools, a pane you can clear

## Why

Roy: markdown files don't show properly, the preview lives in an iframe that
"doesn't even cover the whole vertical space", images have no tools, and the
file list can't get out of the way. A file browser whose job is *looking at
files* currently makes looking at them the worst part.

Three concrete gaps behind that:

1. **Markdown is a second-class preview.** It renders through `marked` with a
   `Rendered / Source` toggle and no way to edit, no way to share, and reading
   width is the full pane (60+ em lines are unreadable).
2. **No room.** The pane is a fixed 280px tree + whatever is left. A long
   document reads inside that remainder; there is no way to hide the tree and
   no way to escape the iframe.
3. **Images and HTML are static.** Image preview is a click-to-toggle
   `actual-size` div — no zoom, no pan, no 1:1 readout. HTML renders in a
   sandboxed frame that inherits the same cramped box.

## Doctrine

- **The reader is the product.** Every file kind gets one honest answer to
  "let me actually look at this": markdown gets a typeset column, images get a
  zoomable canvas, HTML gets a real preview. Everything else is chrome.
- **Escape the iframe by owning a window, not by fighting the shell.** The
  plugin is embedded in an iframe the shell owns (`PluginIframe` in
  `luna-service`, which we do not modify). Rather than ask for fullscreen we
  cannot be granted, the Reader opens a **real browser window** via
  `window.open` — same origin, so it shares the token, and it genuinely sits
  on top of everything. Fullscreen-within-the-iframe is attempted first and
  used when the host allows it; the window is the guaranteed path.
- **Per-kind toolbars, one grammar.** Every preview keeps the same toolbar
  skeleton (name · size · spacer · kind actions · Download). Markdown adds
  `Preview | Edit` + `Share` + `Reader`; images add zoom controls; HTML adds
  `Preview | Source` + `Open`. A user learns the bar once.
- **Sharing is publishing, so it asks first.** `Share` uploads the document's
  bytes to a public URL on md.page. That is an outward-facing action: it gets
  a confirm dialog that says so in words, states the 24-hour expiry, and only
  then publishes. Never silent, never one-click-from-a-hover.
- **Honest about expiry.** md.page anonymous pages die after 24 hours
  (verified against the live API). The UI says "expires in 24 hours" next to
  the link rather than implying permanence.

## Shape

### Markdown (`PREVIEWERS.markdown`)

- Toolbar: segmented **Preview | Edit**, then **Share**, **Reader**,
  **Download**. Source view folds into Edit (an editor *is* the source), so
  the old `Rendered/Source` toggle disappears — one control, not two.
- Render: `marked` with GFM (tables, task lists, strikethrough, autolinks),
  `DOMPurify` sanitize (unchanged), `highlight.js` on fenced blocks, heading
  anchors, and a **measured column** centred in the pane. Relative image `src`
  and links to other files in the store resolve against the file's own
  directory and are rewritten to authed `/read` URLs — a doc that references
  `./diagram.png` shows the diagram instead of a broken glyph.
- Edit: full-height textarea seeded with the raw text, `Cmd/Ctrl+S` and a
  **Save** button → existing `POST /write/{path}`; dirty marker in the bar;
  switching to Preview keeps unsaved text in memory and renders it (preview
  of what you typed, not of what is on disk).

### Share → md.page (new route)

- `POST /api/p/plugin-files/share` `{path}` → reads the file through the
  storage seam, refuses non-text and anything over 1 MB, POSTs
  `{"markdown": <text>}` to `https://md.page/api/publish`, returns
  `{url, expires_at}`. Server-side (not browser-side) so the call is one code
  path for every backend and no host CSP can block it; `httpx` is already in
  Luna's runtime, no new dependency.
- UI: confirm dialog → publish → the link replaces the dialog with a **Copy
  link** button, an **Open** button, and the expiry line. Failures toast.

### Reader window (new `ui/reader.html` + `ui/reader.js`)

- `window.open('ui/reader.html?path=…', …)` — same origin, so it reads
  `luna.token` from `localStorage` and asks its opener for the token as a
  fallback. Renders the same markdown pipeline (shared `mdRender()` module) at
  a comfortable measure, dark, with a minimal top bar: title · Copy · Print ·
  Close. This is the "on top of the whole browser" path.
- Images and HTML get the same button (`Open` / `Reader`) pointed at the same
  window shell so the affordance is uniform.
- **Blocked popups are not a dead end.** A browser (or a locked-down host) can
  refuse `window.open`; it returns `null` and the click would otherwise do
  nothing. When that happens the Reader falls back to a fixed-position overlay
  inside the pane — smaller than a real window, but it still fills the plugin
  viewport and carries the same bar. A toast says which one the user got.

### Image tools (`PREVIEWERS.image`)

- Toolbar: `−` · **percentage** · `+` · **Fit** · **1:1** · **Rotate** ·
  **Open** · **Download**, plus the existing natural-dimensions readout.
- Canvas: wheel-zoom around the cursor, drag-to-pan when zoomed past fit,
  double-click toggles Fit ↔ 1:1, `+`/`−`/`0`/`1` keys. Zoom is a CSS
  transform on the `<img>` — no library, no re-decode.

### HTML

- `Preview | Source` segmented control (same grammar as markdown), sandboxed
  `srcdoc` frame unchanged for safety, plus **Open** which opens the file in
  its own browser tab through the authed `/read` URL.

### The pane itself

- **Hide list** toggle in the header (and `Cmd/Ctrl+B`): collapses the tree to
  zero width, gives the whole pane to the preview, and persists in
  `localStorage`. A slim rail button brings it back so the control is never
  lost.
- The viewer becomes the vertical owner: `#main` and the content pane already
  flex, but `.viewer` gains explicit `min-height: 0` discipline through the
  markdown/image containers so long documents scroll *inside* the pane
  instead of being clipped by it.

### Version

- 0.9.0 → **0.10.0** in all three stamps (`pyproject.toml`,
  `plugin_files/luna-plugin.toml`, `PluginManifest` in `__init__.py`), plus
  the stale `v0.7.0` label in `index.html` — which is exactly the drift the
  three-stamp rule exists to catch. Static assets get `?v=0.10.0`.

## Verify

- Unit: share route (text guard, size guard, md.page payload shape via a
  stubbed transport), version-stamp coherence across the three files.
- Browser (the real check, per the dev process Roy asked for): local Luna on
  :8767 against `luna_p05`, driven through CDP with screenshots at each step —
  markdown render, edit+save, share dialog, reader window, image zoom, HTML
  preview, list collapsed. Screenshots reviewed before ship, not after.
- Ship: push `plugin-files`, package, publish to marketplaces.com.ai official.

## Out of scope

- Restyling the whole plugin to the violet token set (`/vision/ux_guidelines.md`
  reference implementation) — this plan keeps the existing file-browser
  language and applies only the calm-surface rules to what it touches.
- Permanent share links (needs a md.page account) and any share of non-text
  file kinds.
