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
