# plugin-files

A disk-backed file store for [Luna](https://github.com/huemorgan/luna): agent
file tools plus a standalone **Files** sidebar item with an iframe file-browser
UI (list, upload, preview, rename, delete).

This is a **Luna plugin** built against the Luna Plugin SDK (`luna_sdk`) v0. It
imports nothing from `luna.*` — only the stable SDK surface (including
`get_current_user` for route auth) — so it installs from the Luna marketplace
and runs without being part of Luna core.

## Install

In Luna: **Marketplace → Luna Official → plugin-files → Install**. A "Files"
item appears in the sidebar.

## What it does

| Tool | Purpose |
|---|---|
| `file_list` | List files/folders in a directory. |
| `file_read` | Read a text file's content. |
| `file_write` | Write text to a file (owner-approved). |
| `file_mkdir` | Create a directory. |
| `file_delete` | Delete a file/dir (owner-approved, high risk). |
| `file_move` | Move/rename a file or directory. |

Plus auth-gated REST routes under `/api/p/plugin-files/*` and the file-browser
UI served from the plugin's own `ui/` dir.

## Config (env)

| Var | Default |
|---|---|
| `LUNA_FILES_ROOT` | `~/.luna/files` |
| `LUNA_FILES_MAX_SIZE_GB` | `5` |
| `LUNA_FILES_MAX_FILE_MB` | `50` |

## Layout

```
plugin_files/
  __init__.py        # the plugin (luna_sdk only) — tools + sidebar
  routes.py          # REST routes (SDK auth) + UI serving
  storage.py         # DiskFileStorage + make_storage_from_env (pure stdlib)
  ui/                # standalone file-browser (index.html, app.js, style.css)
  luna-plugin.toml   # the data manifest the marketplace reads
```

## License

MIT — see [LICENSE](./LICENSE).
