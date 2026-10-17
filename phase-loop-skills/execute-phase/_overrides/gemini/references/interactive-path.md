# Interactive path (gemini-execute-phase)

Read this only on the interactive path. Runner-managed and governed runs pass an explicit
plan and never publish from the skill; "Publication mode" (a) in `SKILL.md` covers them.

- [Plan handoff reuse](#plan-handoff-reuse)
- [Publication mode (b)](#publication-mode-b)
- [Interactive publication mode](#interactive-publication-mode-agent-harness1392)
- [Draft PR early](#draft-pr-early--push-on-first-commit-visibility)

## Plan handoff reuse

If no plan path is explicit, first check the current repo and branch handoff from `gemini-plan-phase` using `gemini-config/shared/runtime-state.md`: read the repo-local handoff resolver target `.dev-skills/handoffs/gemini-plan-phase/latest.md`, validate `from`, `repo`, `repo_root`, `branch`, `branch_slug`, `commit`, and `artifact`, then use the artifact only if it exists under the current repo root. Ignore missing or mismatched handoffs unless the user explicitly asks to reuse cross-branch state.

## Publication mode (b)

- (b) Interactive orchestrator on a clean, non-protected feature branch (a clear
  interactive signal, and the merge target passed the merge-target safety gate). After the
  Step-9 clean-tree state, run `phase-loop publication-mode --repo .` and do what its
  `PUBLICATION_ACTION:` line says (see "Interactive publication mode" below). With `ready`,
  push the merge-target branch and open a PR (`gh pr create`, `--draft` if dependencies
  remain or verification was partial/skipped, else ready) instead of leaving the lane merge
  only local. Before readiness, follow "PR descriptions on the interactive path" in [SKILL.md](../SKILL.md#pr-descriptions-on-the-interactive-path).
  With `draft-only`, push and open or keep a DRAFT PR; never flip it to ready.
  With `none`, do not push and do not open a PR: the work stays committed on the local
  feature branch, and the final report names that branch as unpublished.

This applies only to interactive (non-runner) completion; it never overrides
`awaiting_phase_closeout`, the runner's deliberate non-complete terminal. Allowed runner
hygiene (forced lane-worktree removal, `branch -D`, `sweep_stale_worktrees.sh`) is
unchanged — the destructive-op ban targets publication branches/worktrees holding
unmerged work.

## Interactive publication mode (agent-harness#1392)

On the interactive path, run `phase-loop publication-mode --repo .` immediately before each `git push`, `gh pr create`, `gh pr edit`, or `gh pr ready`, including the closeout publication in mode (b). Module form, only when the package is on the ACTIVE python's path: `python -m phase_loop_runtime.publication_mode --repo .`. It prints `publication_mode=<none|draft-only|ready>` and exactly one `PUBLICATION_ACTION:` line. Do what that line says. Never choose the mode yourself, and never read the config files by hand.

- `ready` (the default when nothing is configured): push on the first commit, open a draft PR, refresh its description at closeout, and flip it to ready once verification is green.
- `draft-only`: push and open or refresh an agent-owned draft PR. Never run `gh pr ready`, and never open a ready PR.
- `none`: no `git push`, no `gh pr create`, no `gh pr edit`, no `gh pr ready`. The phase still completes: lanes merge locally and closeout runs. The final report names the local branch and says publication was withheld by the publication mode.
- A non-zero exit, `publication_mode=error`, or a missing command: publish nothing and report the error. Finish the phase locally as under `none`; never fall back to `ready`.

The mode comes from the repo's committed `.phase-loop-publication.toml` and the user's `agent-harness/publication.toml`; the most restrictive wins. It governs only this interactive path. Runner-managed closeout (mode (a)) stays under `--closeout-mode`.

## Draft PR early — push on first commit (visibility)

Use "PR descriptions on the interactive path" in [SKILL.md](../SKILL.md#pr-descriptions-on-the-interactive-path)
for pending-work draft text and the final description refresh before readiness.

Do not let a phase branch accumulate commits only locally — that is how lanes drift 70–100 commits ahead of `origin` and in-flight work stays invisible. On the FIRST commit of a phase, unless the interactive publication mode below is `none`, push the branch to `origin` and open a DRAFT PR (`gh pr create --draft`); keep pushing as the phase progresses, and flip the PR to ready at closeout once verification is green. The early draft PR is the visibility contract, not a request to merge.

Respect the publication ownership above: in runner-managed / governed mode the RUNNER owns publication, so the runner performs the early push and draft-PR — do not independently publish or bypass the governed pre-merge review panel. In the interactive-orchestrator path you perform the early push + draft PR yourself on the first commit, as the interactive publication mode allows.
