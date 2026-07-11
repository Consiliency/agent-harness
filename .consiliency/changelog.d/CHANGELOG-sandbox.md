# SANDBOX — per-vendor review-leg sandbox + claude native adapter (POST070FIX phase 4)

- **agy review legs run on a STAGED COPY, never the live tree (D3, IF-0-SANDBOX-1).**
  The product-loop `review` action pointed the gemini/`agy` leg at `--add-dir
  <repo>` — the live worktree — and `agy` honors no read-only lever (`--sandbox`
  still permits writes, no per-tool restriction), so a review leg could mutate the
  reviewed tree. `build_gemini_command` now emits the repo path behind a review-stage
  placeholder for the `review` action; `launch_with_spec` materializes a
  gitignore-aware working-tree copy at launch (tracked + untracked-non-ignored
  files, minus ignored build artifacts and `.git`, so uncommitted changes are still
  reviewed) and points `--add-dir` at the copy, cleaning it in the `finally`. A
  write by the leg can only ever hit the throwaway copy. Dry-run resolves to the
  live path with no copy materialized. No change to the non-`review` (execute /
  repair / roadmap / plan) paths.

- **IF-0-SANDBOX-1 frozen — the per-vendor read-only mechanism, per vendor.** The
  lever differs because the CLIs differ: **codex** honors `--sandbox read-only`
  (as-is); **claude** runs plan/Read-only (as-is); **grok** — whose headless `-p`
  auto-approves writes — is constrained by the `GROK_REVIEW_READONLY_TOOLS`
  read/search `--tools` allow-list (landed #149); **gemini/agy** — no honored lever
  — is constrained by the staged copy above. A regression test
  (`tests/test_review_leg_sandbox.py`) proves a review leg cannot write the reviewed
  tree on both surfaces: the launcher product-loop `review` leg (staged copy) and
  the panel/advisor-board cross-vendor CR (legs confined to a bundle-only review
  dir that never contains the repo).

- **Known deferred gap (out of scope, intentionally left as-is):** the codex
  product-loop `review` leg is launched with `--sandbox danger-full-access`
  (write-capable). Codex *honors* `--sandbox read-only`, so this is trivially
  closable later by threading the `review` action into `build_codex_command`; it is
  left untouched here per phase scope (the phase targets the two vendors —
  agy + grok — where `--sandbox` is insufficient) and to avoid churning the codex
  launchspec golden.

<!-- #125 chunk appended below when the claude native-adapter lane lands. -->
