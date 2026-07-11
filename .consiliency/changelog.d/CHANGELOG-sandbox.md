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

- **Known deferred gap (out of scope, intentionally left as-is) — filed as
  ViperJuice/agent-harness#177:** the codex product-loop `review` leg is launched
  with `--sandbox danger-full-access` (write-capable). Codex *honors* `--sandbox
  read-only`, so this is trivially closable later by threading the `review` action
  into `build_codex_command`; it is left untouched here per phase scope (the phase
  targets the two vendors — agy + grok — where `--sandbox` is insufficient) and to
  avoid churning the codex launchspec golden.

- **Advisor-board `claude` leg exposes a machine-branchable deferral + structured
  native-agent request (#125).** The runtime never spawns a Claude TUI it cannot
  drive, so on a host with no controlling terminal the `claude` leg degrades to
  `UNAVAILABLE` (empty text — never an AGREE, recorded as a non-gating
  `panel_leg_degraded` warn). #92 blended two host cases into one reason string;
  `panel_invoker._claude_leg_deferred_reason(env)` now returns a distinct code —
  `under_claude_code` (inside a Claude Code session → the driving session runs its
  own `Task` Agent) vs `native_adapter_required` (a headless / no-tty host such as
  the Codex Desktop tool shell → the host fulfills the leg through its native
  sub-agent adapter). New additive `panel_invoker.native_agent_leg_request(...)`
  returns a `NativeAgentLegRequest` descriptor (leg, model, mode, reason, review
  brief `instructions`, and the terminal-verdict contract; `.to_dict()` for a tool
  boundary) so a Codex-hosted driver can spawn the third leg natively instead of a
  human noticing `UNAVAILABLE` and improvising. The descriptor is a pure function of
  its inputs and is NEVER threaded through the governed `(status, text)` spawn
  boundary, so `invoke_panel`'s byte-pinned governed path and the advisor-board
  golden stay byte-identical. The codex advisor-board skill documents the Codex
  Desktop native-adapter flow. Closes #125.
