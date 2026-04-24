---
description: Orchestrate the release PR workflow for chronoq-ranker, chronoq-celery, or both. Runs the full release gate and prepares for uv publish.
argument-hint: <ranker | celery | all>
---

Release target: `$ARGUMENTS` (one of `ranker`, `celery`, `all`). If missing, ask the user.

Before doing anything, read `docs/v2/internal/versioning.md` §1 to confirm the correct semver bump for this release. PjM is responsible for this classification — do not guess.

Run the following steps in order. Stop immediately on any failure and report it with the exact command output. Do not proceed to a later step if an earlier one fails.

**Step 1 — Full validate**
Invoke `/validate`: lint + format check + all pytest tests. Must be clean.

**Step 2 — Boundary check**
Invoke `/boundary-check`: chronoq-ranker must have zero server/framework imports.

**Step 3 — Docs sync**
Invoke `/sync-docs`: README + BENCHMARKS + CHANGELOG must be coherent with the
code and with each other.

**Step 4 — Bench artifacts**
Run `make bench` to regenerate all artifacts from a clean state (expect 10–15 min).
Commit any artifact updates (PNGs under `docs/assets/`, `bench/artifacts/`) if
they differ from HEAD. Do not commit if no diff.

**Step 5 — Build wheels**
```bash
uv build
```
Must produce `.whl` + `.tar.gz` for each target package with no errors.

**Step 6 — Dry-run publish**
```bash
uv publish --dry-run
```
Verifies PyPI credentials and package metadata without uploading. Must succeed.

---

## Subagent sequence

Run subagents in this order — each must complete before the next starts:

1. `product-manager` — confirms release scope matches PRD/BRD claims; drafts the
   release-note narrative; approves the CHANGELOG `[0.X.Y]` entry.
2. `project-manager` — cuts the CHANGELOG `[Unreleased]` → `[0.X.Y] — YYYY-MM-DD`
   section from merged PRs; opens the release PR using the standard body template.
3. `docs-writer` — final docs sync pass; verifies README install command matches
   the new version.
4. `qa-validator` — runs the full gate above; confirms INTEGRATION-CLEAN before
   authorising publish.

## Publish (user-gated — never run by a subagent)

`uv publish` requires explicit user approval. No subagent, hook, or automated
pipeline may invoke it. When all steps above are green:

1. User approves in chat.
2. Run `uv publish` — ranker first, then celery (celery declares a ranker dependency).
3. `git tag v0.X.Y && git push --tags`
4. Create GitHub Release from the tag; paste release notes from `CHANGELOG.md [0.X.Y]`.
5. Update the pinned install command in `README.md` if the version string changed.
