# Vendored libraries

Pinned, single-file, permissively-licensed dependencies committed verbatim so the
Files UI works **offline inside the iframe** (no build step, no runtime CDN). The
marketplace zips `ui/` as-is, so these ship with the plugin.

| File | Library | Version | License | Source |
|---|---|---|---|---|
| `marked.min.js` | marked (Markdown → HTML) | 12.0.2 | MIT | https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js |
| `purify.min.js` | DOMPurify (HTML sanitizer) | 3.1.6 | Apache-2.0 / MPL-2.0 | https://cdn.jsdelivr.net/npm/dompurify@3.1.6/dist/purify.min.js |
| `papaparse.min.js` | PapaParse (CSV/TSV parser) | 5.4.1 | MIT | https://cdn.jsdelivr.net/npm/papaparse@5.4.1/papaparse.min.js |
| `highlight.min.js` | highlight.js (syntax highlight, common langs) | 11.9.0 | BSD-3-Clause | https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js |
| `highlight-theme.min.css` | highlight.js `github-dark` theme | 11.9.0 | BSD-3-Clause | https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css |

To update: re-download the exact pinned URL, bump the version here, and re-test.
Markdown/HTML render output is always passed through DOMPurify before insertion.
