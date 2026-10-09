# Branch and publication flow (what the harness does in your repo)

Who pushes, who opens pull requests, and what you can turn off. This describes
harness behaviour **in your project**. It is not a policy for you to adopt, and it
does not replace your own branch-protection or review rules.

For the authority decisions to settle before a first run, see
[Team onboarding](./TEAM-ONBOARDING.md). For what a completed phase writes, see
[closeout generated outputs](./phase-loop/closeout-generated-outputs.md).

## The short version

Git work happens on a feature branch, never directly on `main`. Which actor pushes
and publishes depends on how the phase was started:

| How the phase runs | Who commits/pushes | Your control |
|---|---|---|
| **Runner-managed** (`phase-loop run`, governed or autonomous) | the runner, at closeout | `--closeout-mode manual\|commit\|push` |
| **Interactive** (you invoke a skill in your harness) | the agent in your session | **no setting today — see [agent-harness#1392](https://github.com/Consiliency/agent-harness/issues/1392)** |

If you want a run that touches nothing outside your working tree, use the runner with
`--closeout-mode manual`, and read [Known gap](#known-gap-interactive-publication)
before using the interactive path in a repo where that matters.

## Runner-managed: closeout modes

`phase-loop run` drives phases unattended and **pushes completed work by default**.
Three modes:

| Mode | Commits | Pushes |
|---|---|---|
| `manual` | no | no |
| `commit` | yes | no |
| `push` (default when no mode is given) | yes | yes |

```sh
# nothing leaves the working tree
phase-loop run --repo . --roadmap specs/phase-plans-v1.md --phase P1 \
  --executor codex --max-phases 1 --closeout-mode manual
```

`--no-push` falls back to a manual closeout, and is ignored when `--closeout-mode` is
given explicitly. Manual closeout stops the runner's own commit and push. It does not
sandbox commands that your roadmap or executor instructions run, so keep those inside
the authority you intend to grant.

In runner-managed and governed runs the **runner owns publication**. An executing agent
defers to runner closeout rather than pushing on its own, which is what keeps a governed
run inside its pre-merge review gate.

## Branches and worktrees

- **Never `main`.** Before any lane work or merge, a merge-target safety gate stops the
  run if the resolved target is `main` or a protected branch. Interactively you create a
  feature branch and re-resolve; under the runner, the runner resolves a runner-managed
  branch. This gate covers lane merges, not pushes — see the known gap below.
- **One worktree per lane.** Parallel lanes get isolated git worktrees with disjoint file
  ownership, so two lanes never write the same path. Under the runner the **scheduler**
  assigns them; you do not create them yourself.
- **Cleanup keeps your work.** Worktree reclamation removes a worktree only when it is
  both merged **and** clean. A worktree with uncommitted work is kept, untracked files
  included (agent-harness#1300).

## Draft pull requests

Where the harness opens a PR, it may open it as a **draft**. A draft means "this exists
and is in progress", not "please review this". It is a visibility signal: on a repo with
several agents working at once, a branch that is never pushed is invisible, and
in-flight work silently collides. The PR is flipped to ready once verification is green.

Draft status is read, not just displayed: the runner inspects it when reconciling PR
state, and `governed-pipeline` records it when ingesting open PRs.

If your project would rather not have in-progress branches or draft PRs appear, say so
before a first run, and prefer the runner with `--closeout-mode manual`. There is no
drafts-only setting today.

## Known gap: interactive publication

**The interactive path can push a branch and open a PR without being granted that
authority, and there is no setting to prevent it.** Tracked as
[agent-harness#1392](https://github.com/Consiliency/agent-harness/issues/1392).

The three closeout modes govern the **runner**. When you invoke a skill directly in your
harness, the skill's interactive publication path pushes the feature branch and opens a
PR on its first commit. Its gates are an interactive signal, a clean non-protected
feature branch, and the merge-target safety gate — none of which asks whether push or
publish was authorized.

Scope: it pushes a feature branch and opens a draft PR. It does not merge, and
`main`/protected branches are separately gated. Until the gap closes, use the runner
with `--closeout-mode manual` when nothing should reach your remote.

## Relationship to governed-pipeline

If you drive the harness from [`governed-pipeline`](https://github.com/Consiliency/governed-pipeline)
as a control plane, publication ownership does not change: the harness runner owns
commit, push and closeout. The pipeline does not open pull requests. It reads them —
`/pipeline-ingest-pr` and its PR-vetting persona assess an existing PR against the
active phase — and it consumes the same worktree-isolation contract for writable waves.
