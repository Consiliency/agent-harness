# Handoff — agent-harness#1304: owned-files under-enumeration needs an enforcer

Read `00-SHARED-CONTEXT.md` first. Enhancement, not a bug. The highest-leverage of the
four, and the one whose scope I already cut in half by auditing it.

## The problem

`plan-phase/SKILL.md:27` records our most expensive documented failure: planners
under-declare a lane's owned files, so the executor's actual dirty paths exceed the
declared ownership set and the closeout's `phase_owned_dirty` check fails closed.
It "hit ~70% of phases in that drive".

The rule's response was to state the requirement in prose, at length. That is level 4 of
the ladder. The failure rate suggests prose was the wrong level.

## What was actually missed — the audit result

`plan-phase/SKILL.md:27` does not say which files were omitted. Commit `47c772b4`
(2026-05-25) does:

> Pattern A (closeout refuses missing_phase_owned_dirty_paths, ~70% of phases): plan-phase
> agents under-declared owned files, omitting **test files, snapshots, generated
> migrations, env examples, lockfiles**.

Read that commit message in full (`git show 47c772b4 --no-patch`) — it also documents
Pattern B and Pattern C and is the best record of that drive.

## Why this killed the tooling idea I started with

I was going to derive the complete touch set from `treesitter-chunker` Boundary IR. Of the
five categories actually missed, **only one** is derivable from a code graph:

| Missed category | From Boundary IR? |
|---|---|
| test files | **yes** — reverse edges + test glob |
| snapshots | no — data, not parsed code |
| generated migrations | no — timestamped SQL |
| env examples | no — `.env.example` is not code |
| lockfiles | no — JSON/YAML are `empty` in the chunker coverage table |

Confirmed empirically, since it is the stated ceiling:
```sh
/opt/consiliency/tooling/current/bin/treesitter-chunker boundary \
  phase-loop-skills/execute-phase/scripts/prune_merged_worktrees.sh --pretty
# 5 nodes, 0 edges — shell has no call edges, and this repo is Python + shell
```

Call extraction exists for only 6 languages (C, Go, JS, Python, Rust, TS); 28 of 371
grammars are extraction-verified; call resolution is name-based with no type resolution
(an edge resolves only when exactly one symbol repo-wide has that name).

So: a code-graph proposer would address 1 of 5 categories at significant build cost. Don't
build it. This is the clearest lesson of the whole exercise — **check the failure before
building the capability.**

## Suggested approach: a convention check in the existing validator

All five categories are plain file-convention rules. Add them to
`phase-loop-skills/plan-phase/scripts/validate_plan_doc.py` (note: canonical copy under
`skills-src/claude/claude-execute-phase/`… verify the actual path — `validate_plan_doc.py`
exists under both `plan-phase/scripts/` and `execute-phase/scripts/`).

For every declared owned file, warn when a conventional sibling is missing from the
ownership set:

- `<dir>/x.py` → `test_x.py` / `tests/**` counterpart
- a touched component → its `__snapshots__/` or `.snap` sibling
- a dependency manifest in the set → the matching lockfile
- env shape changed → `.env.example` / `.env.local.example`
- `supabase/migrations/<ts>_*.sql` → matching `__tests__/*.test.sql`

Start with **warn**, not refuse. The existing rule already demands these in prose, so a
hard failure on day one would block legitimate plans that omit an irrelevant category.
Promote to refuse once you have data on the false-positive rate.

This is ladder level 2 — "a check whose error names the file to use instead" — from
pstack's `/correct` skill. See handoff 05 for the ladder in full; it is the single best idea
in PStack and it applies directly here.

## Secondary finding: the cited authority does not exist

`plan-phase/SKILL.md:27` sources Pattern A to
`docs/runtime/2026-05-25-end-to-end-drive-runner-failures.md`. That file is **not in the
tree and has no commit in history**:

```sh
ls docs/runtime/2026-05-25-end-to-end-drive-runner-failures.md   # No such file
git log --all -- docs/runtime/2026-05-25-end-to-end-drive-runner-failures.md   # empty
```

Same provenance problem as agent-harness#1302(b): a load-bearing rule citing a document we
never committed. Either reconstruct it from `47c772b4`'s message (which has the substance)
or change the citation to the commit.

## Acceptance

- validator warns on a plan omitting a conventional sibling
- **negative control**: it fires on a reconstructed plan from the Pattern A cohort, and is
  silent on a correctly-enumerated plan
- existing plan-validation tests stay green
- `plan-phase/SKILL.md:27` can then get *shorter*, not longer — the prose defers to the check

## What I did not check

- which specific plans in the ~70% cohort failed, or their diffs. I have the *categories*
  from `47c772b4`, not per-plan evidence. If you want the false-positive rate before
  choosing warn-vs-refuse, that is the data to get.
- whether `validate_plan_doc.py` already has a partial version of this.
- `greenfield`'s `source_provenance.py` / `generated_artifact_truth.py`, which model
  source→generated provenance and might cover the snapshots/generated categories. Worth 20
  minutes before hand-rolling conventions.

## Collision risk

Low. No active branch touched `plan-phase`. Re-check per `00-SHARED-CONTEXT.md`.
