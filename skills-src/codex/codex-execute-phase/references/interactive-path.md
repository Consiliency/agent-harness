# Codex execute-phase interactive procedures

Read the relevant section only when its trigger in `SKILL.md` applies. The entrypoint's runner ownership, governance, PR-description and closeout rules still govern these procedures.

## Reuse a planning handoff

If no plan path is explicit, first check the current repo and branch handoff from `codex-plan-phase` using `codex-config/shared/runtime-state.md`: read the repo-local handoff resolver target `.dev-skills/handoffs/codex-plan-phase/latest.md`, validate `from`, `repo`, `repo_root`, `branch`, `branch_slug`, `commit`, and `artifact`, then use the artifact only if it exists under the current repo root. Ignore missing or mismatched handoffs unless the user explicitly asks to reuse cross-branch state.

## Interactive publication

- (b) Interactive orchestrator on a clean, non-protected feature branch (a clear
  interactive signal, and the merge target passed the merge-target safety gate). After the
  Step-9 clean-tree state, run `phase-loop publication-mode --repo .` and do what its
  `PUBLICATION_ACTION:` line says (see "Interactive publication mode" below). With `ready`,
  push the merge-target branch and open a PR (`gh pr create`, `--draft` if dependencies
  remain or verification was partial/skipped, else ready) instead of leaving the lane merge
  only local. Before readiness, follow [PR descriptions on the interactive path](../SKILL.md#pr-descriptions-on-the-interactive-path).
  With `draft-only`, push and open or keep a DRAFT PR; never flip it to ready.
  With `none`, do not push and do not open a PR: the work stays committed on the local
  feature branch, and the final report names that branch as unpublished.
- (c) Merge target is `main` or a protected branch. Already STOPPED at the merge-target
  safety gate before any lane merge — never merge lanes onto `main`/protected. Re-target a
  feature branch or take explicit instruction.

## Draft PR early — push on first commit (visibility)

Use [PR descriptions on the interactive path](../SKILL.md#pr-descriptions-on-the-interactive-path)
for pending-work draft text and the final description refresh before readiness.

Do not let a phase branch accumulate commits only locally — that is how lanes drift 70–100 commits ahead of `origin` and in-flight work stays invisible. On the FIRST commit of a phase, unless the interactive publication mode below is `none`, push the branch to `origin` and open a DRAFT PR (`gh pr create --draft`); keep pushing as the phase progresses, and flip the PR to ready at closeout once verification is green. The early draft PR is the visibility contract, not a request to merge.

Respect the publication ownership above: in runner-managed / governed mode the RUNNER owns publication, so the runner performs the early push and draft-PR — do not independently publish or bypass the governed pre-merge review panel. In the interactive-orchestrator path you perform the early push + draft PR yourself on the first commit, as the interactive publication mode allows.

## Interactive publication mode (agent-harness#1392)

On the interactive path, run `phase-loop publication-mode --repo .` immediately before each `git push`, `gh pr create`, `gh pr edit`, or `gh pr ready`, including the closeout publication in mode (b). Module form, only when the package is on the ACTIVE python's path: `python -m phase_loop_runtime.publication_mode --repo .`. It prints `publication_mode=<none|draft-only|ready>` and exactly one `PUBLICATION_ACTION:` line. Do what that line says. Never choose the mode yourself, and never read the config files by hand.

- `ready` (the default when nothing is configured): push on the first commit, open a draft PR, refresh its description at closeout, and flip it to ready once verification is green.
- `draft-only`: push and open or refresh an agent-owned draft PR. Never run `gh pr ready`, and never open a ready PR.
- `none`: no `git push`, no `gh pr create`, no `gh pr edit`, no `gh pr ready`. The phase still completes: lanes merge locally and closeout runs. The final report names the local branch and says publication was withheld by the publication mode.
- A non-zero exit, `publication_mode=error`, or a missing command: publish nothing and report the error. Finish the phase locally as under `none`; never fall back to `ready`.

The mode comes from the repo's committed `.phase-loop-publication.toml` and the user's `agent-harness/publication.toml`; the most restrictive wins. It governs only this interactive path. Runner-managed closeout (mode (a)) stays under `--closeout-mode`.

## Worktree lifecycle — prune after merge (standing rule)

**Prune a worktree — and delete its now-dead branch — as soon as its PR merges. Never leave merged or abandoned worktrees behind.** Forced removal of the run's own lane worktrees at merge time is already allowed runner hygiene; this rule additionally covers the **sibling worktrees under the shared workspace volume** (`/mnt/workspace/worktrees/<project>-<branch>`, or the repo-sibling `../<project>-<branch>` fallback on hosts without it) that outlive a single run. Left unpruned they accumulate without bound — the shared volume has reached thousands of stale merged worktrees because nothing swept them.

This is a **sweep**, not "delete the tree you are standing in." At closeout the current run's own branch/worktree is still unmerged, so it is KEPT by the criterion below — which is exactly right. Run the sweep at closeout (and, cheaply, at phase start).

For each sibling worktree from `git worktree list` (excluding the primary checkout and this run's own worktree), classify:

- **SAFE to prune** — the branch is MERGED **and** the tree is CLEAN. MERGED means either `git merge-base --is-ancestor <branch> origin/main` (fetch first) OR `gh pr view <branch> --json state -q .state` reports `MERGED` (catches squash/rebase merges that are not ancestors). CLEAN means `git -C <path> status --porcelain` is empty. Then `git worktree remove --force <path>` and `git branch -D <branch>` — the ref is dead once its PR merged to `origin`, so deleting it is correct regardless of the branch's naming.
- **KEEP** — unmerged (work not on `origin/main` and no merged PR) OR dirty (`--porcelain` non-empty). Leave it and log one line. This preserves the current run's own worktree and any in-flight peer work.

**Permission-locked fallback (gotcha).** A worktree whose `node_modules` (or other build output) was installed under a **different uid** — e.g. CI-offload / rootless-docker runs — is permission-locked. `git worktree remove --force` and a plain `rm -rf` will FAIL with `Permission denied`. When removal fails on permissions, fall back to `sudo rm -rf <path>` (or re-run the cleanup as the installing uid), then `git worktree prune` to drop the dangling administrative entry, then `git branch -D <branch>`. A permission-denied removal is still SAFE — do not reclassify it as KEEP.
