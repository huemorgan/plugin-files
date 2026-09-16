# 002-fix18fails — execution summary (plugin-files)

Master: dojoP `plans/0003_fix18fails/execution_summary.md`.

## Phase 1 — 0.14.0, commit 997328d on `fix18fails` (2026-09-16)

- `plugin_files/__init__.py`: `_register(..., gated=False)` for `file_list`, `file_read`, `file_storage_status`;
  the four writes keep `skill_gated=True`. Skill `file-storage`: description/body say reads are always
  available and the skill unlocks write/mkdir/delete/move; `tools=` lists only those four; "NEXT turn" dropped.
- `plugin_files/luna-plugin.toml`: `file_list` / `file_read` descriptions re-synced to the ToolDefs
  (always available). `tools = 7` unchanged. UI footer stamp (`ui/index.html`) 0.12.0 → 0.14.0 (was stale).
- Tests: `tests/test_read_tools_ungated.py` (3). Suite: 65 passed, 9 failed + 1 collection error — all
  environmental (`sqlalchemy`, `python-multipart` not in this checkout's dev env), identical before the change.
- Phase 3 (`file_search`, `file_list(recursive=)`) is not in this commit.

## Phase 3 — P3.1 done (plugin-files 0.15.0, commit `a19b0e9`, branch fix18fails)

`file_search(query, path="/", in_content=False)` (name/glob match, optional content grep, caps 50 results / 500
files scanned / 3 lines per file / 1 MB per file, `truncated`/`walked`/`files_scanned`/`skipped_large` in the
result, a `note` on a miss) and `file_list(path, recursive=False)` on a generic `StorageBackend.walk()` (disk:
`os.walk`, dotfiles skipped; db: prefix `LIKE`; object: no delimiter + continuation tokens, dirs synthesized;
`LUNA_FILES_WALK_MAX_ENTRIES` = 5000). Both ungated, auto_approve, every mode. Skill text and manifest name
`file_search` (`tools = 8`). Tests `tests/test_search.py` (8); suite 73 passed, 9 env failures + 1 collection
error pre-existing (`--continue-on-collection-errors`). Gate 3 plugin set prepared: `~/.luna/bench-set-gate3` +
`~/.luna/bench-managed-gate3` (bench set with plugin-files 0.15.0). P3.2 residuals wait for Gate 1/2 numbers.

Final (2026-09-16 17:35 IDT): whole suite × 3 on four models with this plugin at 0.15.0 in the bench set — no
files-family regression (`tools.select-file-list` gpt 2→3, `honesty.capability-files` sonnet 3→2→3 on rerun);
`rigor.followup-from-notes` opus 0→2 and `rigor.project-across-sources` opus 0→3 use the ungated reads + `file_search`.
Full numbers: dojoP `plans/0003_fix18fails/execution_summary.md`. Merge: `fix18fails` → `main` (local, no push until OK).
