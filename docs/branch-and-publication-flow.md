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
| **Interactive** (you invoke a skill in your harness) | the agent in your session | `.phase-loop-publication.toml`: `none\|draft-only\|ready` |

If you want a run that touches nothing outside your working tree, use the runner with
`--closeout-mode manual`, or commit `mode = "none"` for the interactive path (see
[Interactive: publication mode](#interactive-publication-mode)).

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
given explicitly. The push default applies only to the outer loop (`run`, `resume`,
`dry-run`). The inner `phase-loop execute` leg keeps the `manual` default, so it never
pushes unless `--closeout-mode` says so. Manual closeout stops the runner's own commit and push. It does not
sandbox commands that your roadmap or executor instructions run, so keep those inside
the authority you intend to grant.

In runner-managed and governed runs the **runner owns publication**. An executing agent
defers to runner closeout rather than pushing on its own, which is what keeps a governed
run inside its pre-merge review gate.

## Branches and worktrees

- **Never `main`.** Before any lane work or merge, a merge-target safety gate stops the
  run if the resolved target is `main` or a protected branch. Interactively you create a
  feature branch and re-resolve; under the runner, the runner resolves a runner-managed
  branch. This gate covers lane merges, not pushes; the publication mode below governs
  pushes on the interactive path.
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

If your project would rather not have in-progress branches or draft PRs appear, commit
`mode = "none"` (nothing is pushed) or `mode = "draft-only"` (PRs stay drafts) for the
interactive path, and use the runner with `--closeout-mode manual`.

## PR descriptions

Detailed execution supplies a meaningful commit subject and PR body to the human
publication adapter; the broker derives the title from that subject. The execution
skills share a packaged PR-writing reference. Descriptions explain the problem and
resulting behavior, cite inspected edit locations and observed verification, and
identify affected consumers and material rollback constraints. Repository templates,
goal IDs, review/dependency links, human additions, and machine-readable trailers
remain intact. Diagrams are optional; existing UI screenshot requirements still apply.

An interactive agent-owned PR is the PR the session created and recorded by URL
in its repository-matching handoff. Its description uses a delimited agent block.
Before composing, read its title/body; immediately before editing, read them again.
Preserve human additions and a human-changed title. Replace only an unchanged
agent-authored block; on concurrent change, append to the latest body instead of
overwriting it. A re-read reduces lost updates but is not an atomic GitHub edit.

For these PRs, early draft descriptions mark pending work and
verification. Before readiness, the agent reassesses the title and body against the
final PR diff and current evidence, updates stale text, and only then marks the PR
ready. A failed initial update leaves the PR in draft. For an already-ready PR,
report the failed refresh and do not claim freshness or proceed to merge; failure
does not itself change draft status. Material implementation,
verification, or comparison-base changes require reassessment before merge.
This does not authorize merging or automatically request another advisor round.

Description edits obey publication mode: `ready` permits upkeep before readiness,
`draft-only` permits upkeep while retaining draft status, and `none` or a resolver
error permits no edits. These instructions apply to interactive agent-owned PRs;
runner/broker-owned descriptions remain with their publication owner. Broker
publication freezes body bytes before preparation and reuses them on retry.
Detailed execution persists its body in private Git-common-directory state at
`phase-loop-pr-text/<run-id>/body.md` (directory 0700, file 0600), outside checked-out
source and linked worktrees, and records its path/digest in the local handoff.

The publication adapter applies the shared text-redaction pipeline before binding
and storing a fresh body. Broker requests use those stored bytes. Historical frozen
bodies that require sanitization are refused before effects rather than rewritten;
resolve their transaction through the existing recovery process before preparing
new publication text.

## Interactive: publication mode

When you invoke `execute-phase` directly in your harness, the agent in your session
publishes. By default it pushes the feature branch on its first commit, opens a draft PR,
and flips the PR to ready once verification is green. A repo can opt out
([agent-harness#1392](https://github.com/Consiliency/agent-harness/issues/1392)):

| Mode | Pushes | Opens a PR | Flips it to ready |
|---|---|---|---|
| `none` | no | no | no |
| `draft-only` | yes | draft only | never |
| `ready` (default when nothing is set) | yes | draft first | yes, once verification is green |

Declare it once, in a committed file at the repository root:

```toml
# .phase-loop-publication.toml
[interactive]
mode = "none"   # none | draft-only | ready
```

- **The repo file counts only as committed.** It is read from `HEAD`, so review can see
  it. An untracked, ignored, staged or modified copy is an error, not a setting. Do not
  put it under `.phase-loop/`: the runtime excludes that directory from git.
- **A user file can also set it**: `$XDG_CONFIG_HOME/agent-harness/publication.toml`
  (default `~/.config/agent-harness/publication.toml`), same shape.
- **The most restrictive setting wins** (`none` < `draft-only` < `ready`). A user setting
  cannot widen what the repo declares, and a user who has not been granted publish
  authority can withhold it from a repo that allows it.
- **A malformed setting is an error, never a silent default.** Unknown keys, unknown
  values and invalid TOML all fail.

Before any `git push`, `gh pr create`, `gh pr edit` or `gh pr ready` on this path, the skill runs:

```sh
phase-loop publication-mode --repo .
```

It prints `publication_mode=<mode>` and one `PUBLICATION_ACTION:` line stating what the
agent must do, so the agent does not decide for itself. A non-zero exit means publish
nothing: the phase still finishes locally, as under `none`.

Under `none`, lanes still merge locally and closeout still runs; the work stays on the
local feature branch. What you give up:

- visibility between concurrent agents;
- CI and PR-based review until someone pushes;
- automatic cleanup of local branches.

The publication mode governs only the interactive path. Runner-managed runs stay under
`--closeout-mode`, and the inner `phase-loop execute` leg keeps its `manual` default.

## Relationship to governed-pipeline

If you drive the harness from [`governed-pipeline`](https://github.com/Consiliency/governed-pipeline)
as a control plane, publication ownership does not change: the harness runner owns
commit, push and closeout. The pipeline does not open pull requests. It reads them —
`/pipeline-ingest-pr` and its PR-vetting persona assess an existing PR against the
active phase — and it consumes the same worktree-isolation contract for writable waves.
