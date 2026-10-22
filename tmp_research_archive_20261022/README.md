# /tmp Research Archive — 2026-10-22

Preserves the research artefacts that accumulated in `/tmp/` on
`AutoBotV1` before cleanup frees space on the near-full root volume.

See:

* `MANIFEST.md` — per-file manifest with archive-side SHA-256.
* `MANIFEST_SOURCE.md` — per-file SHA-256 of the `/tmp/` originals.
  Pair-check: all 113 pairs verified byte-identical before commit.
* `SAFE_DELETE.md` — groupings of what is safe to delete, what is
  reproducible, and what must NOT be touched (active worktrees + env
  files).

Scope: markdown reports, named `.txt` reports, dated research Python
scripts, and small JSON "results" files that back dated reports.
Explicitly out of scope: active worktree content, env/credential
files, pytest fixtures, raw datasets.

Branch: `archive/tmp-research-20261022`.
