# 001 — execution summary

Shipped as **plugin-files 0.10.0**. Everything in the plan landed; the two
deviations are recorded below.

## What changed

| Area | File | Result |
| --- | --- | --- |
| Shared markdown pipeline | `ui/md.js` (new) | `window.LunaMd.renderMarkdown()` — marked GFM → DOMPurify → relative-image resolution against the file's own directory, in-store link interception, heading anchors, hljs + hover copy buttons, custom task-list checkboxes. One renderer, used by both the pane and the reader page. |
| Markdown toolbar | `ui/app.js` | Segmented **Preview \| Edit**, an in-place `Unsaved` badge, **Save** (`POST /write/{path}`), **Share**, **Reader**, **Download**. The old `Rendered/Source` toggle is gone — the editor *is* the source. |
| Share | `plugin_files/routes.py` | `POST /share {path}` → guards (dir, >1 MB, non-UTF-8) → `POST https://md.page/api/publish` → `{url, expires_at}`. Confirm dialog names the file and the 24-hour expiry before publishing; the result dialog gives Copy / Open and the exact expiry timestamp. |
| Reader | `ui/reader.html`, `ui/reader.js` (new) | Standalone same-origin page opened with `window.open` — a real browser window on top of everything, outside the shell's iframe. Token from `localStorage` with a `postMessage` handshake fallback. A−/A+ (persisted), Print, Close, Escape, ⌘±. |
| Image tools | `ui/app.js`, `ui/style.css` | CSS-transform zoom: cursor-anchored wheel zoom, drag-pan when past fit, double-click Fit↔1:1, `+ − 0 1` keys, live percentage readout, Rotate, Open, Download. `ResizeObserver` re-fits while in Fit mode. |
| HTML | `ui/app.js` | **Preview \| Source** in the same grammar, sandboxed `srcdoc` frame unchanged, plus **Open** in a real tab. |
| Pane | `ui/index.html`, `ui/style.css`, `ui/app.js` | Hide-list toggle + `⌘/Ctrl+B`, persisted; a slim rail button restores it so the control is never lost. |
| Version | four stamps | 0.9.0 → 0.10.0, including the stale `v0.7.0` in the footer. Assets carry `?v=0.10.0`. |

## Deviations from the plan

1. **Popup-blocked fallback.** `window.open` can return `null` (headless
   Chrome always does; a locked-down host may). A blocked click must not be a
   dead end, so the Reader falls back to a full-viewport overlay in the pane
   and toasts which one you got. The plan was amended to match.
2. **Fullscreen-within-the-iframe was dropped, not attempted.** The shell's
   `PluginIframe` carries no `allowfullscreen`, and `luna-service` is
   read-only here, so the API is unavailable by construction — trying it would
   only produce a rejected promise. The window (and the overlay) are the path.

## Verification

- **Unit:** 72 passed, 1 skipped. New `tests/test_share.py` covers the five
  guards (the size guard asserted to short-circuit *before* reading bytes), the
  exact md.page request body, expiry passthrough, and upstream-500 → 502. Plus
  cross-stamp version coherence, including the UI footer.
- **Browser:** local Luna on :8767 driven through CDP in headless Chrome at
  1440×900@2x. Ten screenshots reviewed, each one driving a fix — markdown
  render, long-document scroll, editor, image fit, image at 197%, HTML preview,
  reader overlay, reader page, share confirm, share result.
- **Share end-to-end against the live API**, not a stub: published
  `demo.md` → `https://md.page/Cnz5EJ` (HTTP 200), expiry rendered as
  "Stops working on 8/6/2026, 1:25:01 PM".

## 0.11.0 follow-up — the toolbar reads as a toolbar

Roy, on 0.10.0: *"make the toolbar more clear — like a different background or
something and also with nice flat icons"* and *"also have the left pane of the
files resizable"*.

- **The toolbar is a surface, not a caption.** It was a row of text with a hair
  line under it, sitting on the same background as the document. Now it is a
  raised strip — `--bg-panel`, a border, 10px radius, an inset highlight and a
  soft drop shadow — and the buttons on it get their own darker fill so they
  read as pressable rather than as labels.
- **Flat line icons on every action.** One `ICON_PATHS` map in `app.js` with a
  single 24-grid and one stroke weight, wrapped by `ico(name)`; glyphs inherit
  `currentColor`, so a hover or an active segment carries its icon with it.
  Covered: Preview, Edit, Source, Save, Share, Reader, Download, Open, zoom
  ±, Fit, 1:1, Rotate, Print, Close. The file's own kind glyph now leads the
  bar in its type colour, and a long name truncates instead of pushing the
  controls off the edge.
- **The file list is resizable.** A 5px handle between the tree and the
  content: drag to resize, double-click or Home to reset to 280px, arrow keys
  when focused (Shift for a bigger step). Width lives in one CSS variable
  (`--tree-w`) so a drag is one style write per frame, is clamped to
  180px…min(720, viewport − 320) so the preview can never be squeezed out of
  existence, re-clamps when the window narrows, and persists in
  `localStorage`. Hidden while the list is collapsed.

**A real bug this surfaced:** the global `* { padding: 0 }` reset had stripped
list padding in the markdown view, so bullets, ordered-list numbers and task
checkboxes were rendered *outside* the scroll container and clipped — a task
checkbox showed as a purple sliver, which is what made it look like a styling
mistake. Lists now own a 24px gutter and a task item outdents into exactly
that gutter. Verified by measuring the checkbox rect against the container's:
`left` was 6px outside before, flush after.

Verified in the browser across eight fresh screenshots: markdown, image, HTML
and edit-mode toolbars; the drag (280 → 460, persisted); the collapsed state
with the handle hidden and the rail shown; the reader overlay bar.

## Bugs found and fixed during the browser pass

- The dirty-marker refresh re-rendered the toolbar, destroying the textarea
  under the cursor on the *first* keystroke. The badge is now always in the DOM
  and only its class is toggled.
- GFM task checkboxes rendered as disabled native controls; replaced with
  `appearance: none` custom ticks and dimmed done text.
- `test_provider.py` pinned a literal version and broke on the bump — replaced
  with a shape check, with equality asserted once in `test_share.py`.
