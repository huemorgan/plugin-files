# 002 — execution summary

Date: 2026-09-16. Source branch `codex/improve-long-tasks` from 0.13.0; changed package/manifest/runtime to 0.13.2. The Files UI version footer and cache keys also now match 0.13.2 (the footer mismatch was a pre-existing test failure).

The disk backend now uses path-component ancestry, rejects deletion or movement of the configured root, checks total quota before mutation, stages writes atomically, and removes failed temporary files. A per-instance lock plus an OS file lock serializes quota decisions across instances and workers. Same-prefix sibling and symlink escapes are rejected before effect. Other storage backends remain unchanged.

dojoP Files contracts changed from 2 PASS / 5 FAIL to 7 PASS / 0 FAIL (`dojoP/results/20260916-final-offline-contracts.json`). The full plugin suite now includes a forced cross-instance quota race, reserved-lock-path control and symlinked-lock refusal: 78 passed, one skipped. A live agent workflow could not run yet because the test-provider key returned HTTP 401; the independent disk contract and unit suite are valid.
