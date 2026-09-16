Status: approved
Approval: Roy, 2026-09-16, in session (see master). Covers changes and merge to main; publishing waits for Roy's OK.

# 002 — fix18fails (plugin-files part)

Master plan: dojoP `plans/0003_fix18fails/PLAN.md` (thesis `idea_fix.md`, test changes `research/agent-rigor-and-scope/results.md` §0003). This mirror lists only what changes in THIS repo; evidence, diagnosis, date validation and gates are in the master.

Branch `fix18fails` from main `3de2445` (0.13.0). Versions: 0.14.0 (phase 1), 0.15.0 (phase 3). Stamps that must agree: `pyproject.toml:3`, `plugin_files/luna-plugin.toml:3`, `plugin_files/__init__.py:43`; `luna-plugin.toml [requires] tools` and the `[[tools]]` blocks.

## Phase 1 (0.14.0)
- `plugin_files/__init__.py:221-233`: register `file_list`, `file_read`, `file_storage_status` WITHOUT `skill_gated`; keep the gate on write/mkdir/delete/move.
- `__init__.py:301-332` SkillDef: description/body say reads are always available and the skill is loaded before writing; drop "unlock on your NEXT turn"; `tools` lists only the gated four.
- `luna-plugin.toml` `[[tools]]` descriptions re-synced with the ToolDefs (file_read/file_write drift).

## Phase 3 (0.15.0)
- `file_search(query, path="/", in_content=false, limit)`: recursive walk (disk: `os.walk` as in `storage.py:289`; db: drop the `NOT LIKE 'base%/%'` predicate in `backends/db.py:69-87`; object: drop `Delimiter="/"` in `backends/object.py:114-142`), name match, optional content grep, capped.
- `file_list` gains `recursive: bool = false`.
- Manifest `tools = 8`, new `[[tools]]` block.

## Tests
Reads registered ungated / writes gated; `file_search` and recursive `file_list` on the disk and db backends.
