# 002 — keep all disk file effects inside the configured root

Status: owner authorized, 2026-09-16. Branch `codex/improve-long-tasks` from the default-profile source 0.13.0.

## Reproduction

The dojoP baseline `FILES-READ`, `FILES-WRITE`, `FILES-DELETE`, `FILES-SYMLINK` and `FILES-QUOTA` all fail. The disk resolver compares path strings by prefix, so a same-prefix sibling or symlink may escape; a failed write can still leave outside bytes. Total quota is not enforced before mutation. The in-root round trip and alternate-backend sanitizer controls pass. Existing plugin suite: 74 passed, one skipped, one version-footer failure.

## Change

- Resolve paths and require path-component ancestry under the configured root before every disk operation, including moves and parent creation. Reject symlink escapes and root-destructive operations.
- Enforce both single-file and total-byte limits before mutation. Stage writes atomically and clean up failed attempts; account for overwrite size and concurrent writes.
- Add sibling, symlink, overwrite, quota and valid-operation regressions. Keep manifest, runtime and package versions synchronized with a new patch release if code changes.

## Verification

Run dojoP's Files group, Files' full unit suite, and a live Luna + Files workflow in the frozen default profile. Preserve before/after receipts and note any existing unrelated test failures in `execution_summary.md`.
