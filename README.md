# plugin-files

A file store for [Luna](https://github.com/huemorgan/luna): agent file tools, a
standalone **Files** sidebar item with an iframe file-browser UI (list, upload,
preview, rename, delete), and the sanctioned `StorageProvider` (registry key
`storage`) every other plugin persists bytes through.

This is a **Luna plugin** built against the Luna Plugin SDK (`luna_sdk`) v0. It
imports nothing from `luna.*` — only the stable SDK surface (including
`get_current_user` for route auth, and `declarative_base`/`ctx.engine` for the
`db` backend's own table) — so it installs from the Luna marketplace and runs
without being part of Luna core.

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
| `file_storage_status` | Report the active backend, durability, location, usage. |

Plus auth-gated REST routes under `/api/p/plugin-files/*` (including `/status`)
and the file-browser UI served from the plugin's own `ui/` dir.

## Storage backends (002)

One plugin, four backends behind a single seam (`StorageBackend`). The plugin
**reports its own durability** so "is my data safe here?" is answerable at a
glance (`file_storage_status` / `GET /status`). Durability is **declared** by the
deployment — never guessed.

| Backend | Bytes live in | IO | Durable | In-place edit | Use |
|---|---|---|---|---|---|
| `local` | local disk (`LUNA_FILES_ROOT`) | fast | only if the disk is | yes | local dev |
| `fly` | local disk on a mounted **Fly volume** | fast (NVMe) | yes (host-pinned) | yes | hosted code/dev machines |
| `object` | S3-compatible — **Tigris** (Fly) or **Cloudflare R2** | network | yes (machine-independent) | **no** | durable artifacts/attachments/archives |
| `db` | per-agent Postgres (`plugin_files_blobs`) | medium, small files | yes | yes | zero-infra durability |

Pick with `LUNA_FILES_BACKEND` (`auto` default). `auto` order: durable disk
(`LUNA_FILES_ROOT` + `LUNA_FILES_DURABLE=1`) → `object` (S3 creds) → `db`
(`ctx.engine`) → ephemeral `local` (+ warning, never loses function).

## Config (env)

| Var | Default | For |
|---|---|---|
| `LUNA_FILES_BACKEND` | `auto` | `auto`\|`local`\|`fly`\|`object`\|`db` |
| `LUNA_FILES_ROOT` | `~/.luna/files` | `local`/`fly` |
| `LUNA_FILES_DURABLE` | (unset) | declare the disk durable → `state.durable=true` |
| `LUNA_FILES_MAX_SIZE_GB` | `5` (`1` for db) | all |
| `LUNA_FILES_MAX_FILE_MB` | `50` (`20` for db, `200` object) | all |
| `LUNA_FILES_S3_ENDPOINT` | (unset) | `object` — Tigris/R2 endpoint |
| `LUNA_FILES_S3_ACCESS_KEY_ID` / `_SECRET_ACCESS_KEY` | (unset) | `object` |
| `LUNA_FILES_S3_BUCKET` / `_PREFIX` / `_REGION` | (unset) | `object` |

## Add a backend

1. Subclass `StorageBackend` (in `storage.py`); implement `list/read/write/mkdir/
   delete/move/stat/exists/usage` + `state()`.
2. Set the capability flags (`supports_dirs`, `supports_move`, and in `state()`
   `supports_inplace_edit`) honestly so tools degrade instead of crashing.
3. Register it in `backends/__init__.py:make_storage_from_env`.
4. Tools, the `StorageProvider`, routes and UI are untouched — they only see the
   seam.

## Layout

```
plugin_files/
  __init__.py        # the plugin (luna_sdk only) — tools + sidebar + status
  routes.py          # REST routes (SDK auth) + UI serving + /status
  provider.py        # FilesStorageProvider (the "storage" capability) over the seam
  storage.py         # StorageBackend seam + StorageState + DiskFileStorage
  backends/          # disk (local/fly) · object (Tigris/R2) · db (Postgres) + factory
  models.py          # plugin_files_blobs table (db backend, E4 isolated metadata)
  ui/                # standalone file-browser (index.html, app.js, style.css)
  luna-plugin.toml   # the data manifest the marketplace reads
```

## License

MIT — see [LICENSE](./LICENSE).
