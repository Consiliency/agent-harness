# Shared context for all handoffs in this directory

Read this once, then your issue's handoff. Written 2026-10-07; `main` at `37114d36`.

## Where this came from

A comparison of the `pstack` Cursor plugin against our phase-loop skills
(`../REPORT.md`, 489 lines). The comparison incidentally surfaced four defects in our
own repo. One is fixed (agent-harness#1300, PR agent-harness#1309, merged). The rest are
handed off here, plus the PStack adoption programme itself.

| Handoff | Issue | Kind |
|---|---|---|
| `01-reflection-consumption-1301.md` | agent-harness#1301 | bug — do this first |
| `02-plan-size-contradiction-1302.md` | agent-harness#1302 | bug |
| `03-closeout-rule-text-1303.md` | agent-harness#1303 | bug |
| `04-under-enumeration-validator-1304.md` | agent-harness#1304 | enhancement |
| `05-pstack-alignment.md` | none yet | programme |

## House rules that bit me — read before editing anything

**1. `skills-src/` is canonical. `phase-loop-skills/` is generated.**
Per `docs/phase-loop/skills-canonical-source.md` (IF-0-CANON-1). Editing
`phase-loop-skills/` directly will fail the parity gate. The pipeline is:

```
skills-src/<harness>/<harness>-<skill>/
  → python3 phase-loop-runtime/scripts/regenerate_skills_bundle.py   # → phase-loop-skills/
  → python3 phase-loop-runtime/scripts/sync_skills_bundle.py         # → src/phase_loop_runtime/skills_bundle/
```

One edit fans out to ~12 files. That is expected bundle output, not hand editing — say so
in the PR body or a reviewer will flag it.

Note: for `execute-phase`, only `skills-src/claude/claude-execute-phase/scripts/` carries
the `scripts/` dir; the other harness trees have none. The neutral base is built from
codex + per-harness `_overrides`, so check which tree actually holds your target.

**2. Run the gates.** No `.venv` and no system `pytest`; use `uv`:

```sh
uv run --quiet --with pytest --with-editable ./phase-loop-runtime python -m pytest <tests> -q
```

Always include `phase-loop-runtime/tests/test_skills_canon_parity.py` and
`test_skills_bundle_drift.py` after touching skills. A `ContractFloorUnverified` warning
on every run is pre-existing and unrelated.

**3. Commit before you test a revert.** I reverted `skills-src` to run a negative control
with nothing committed yet and lost the edit (recovered from the generated copies).
Commit first, then experiment.

**4. Qualify every issue/PR reference** — `agent-harness#1301`, never a bare `#1301`
(`AGENTS.md`, "Referencing issues & PRs").

## Concurrency: this is a shared team host

Host `dev0`, `/etc/consiliency/team-host` exists. Create worktrees at
`$WORKTREE_ROOT/<project>-<branch>` (= `/home/viperjuice/workspace/worktrees`, a symlink
to `/mnt/workspace/worktrees/viperjuice`). **Never** work directly on `main`.

Live at time of writing — check again, these move:

| Branch | ahead | dirty |
|---|---|---|
| `claude/panel-structured-reply-plan` | 6 | 0 |
| `claude/release-0.7.25` | 5 | 0 |
| `claude/sealed-head-recovery-1296` | 5 | 3 |
| `codex/owner-decision-875` | 1 | 0 |
| `codex/jevdrill-host` | 0 | **14** |
| `fix/runtime-imports-20260911` | 0 | **11** |
| `codex/jevdrill-windows-port` | 0 | **35** |

Before editing, re-run the collision check:

```sh
git diff --name-only main...<branch> | grep -E '<your target files>'
```

None of these touched my targets when I checked, but `codex/owner-decision-875` is the one
to watch for `AGENTS.md` (see handoff 02).

**Do not reclaim the three dirty worktrees.** They hold 60 uncommitted files belonging to
other sessions. agent-harness#1309 made the sweep refuse them, but a **liveness gap
remains**: a freshly-created worktree on a branch at-or-behind `origin/main` is
merged-and-clean and therefore still prunable.

## Our own doctrine, which these handoffs try to honour

- `AGENTS.md` "Plan discipline": pin inputs, never your own outputs. Watch the
  amendment-to-implementation ratio.
- `docs/agent-phase-convergence.md` §6: define the proof **and show it can fail**. Every
  fix below should ship a negative control, i.e. evidence the new test fails against the
  old code. agent-harness#1309 did this (7 of 8 cases) and it is cheap.
- §5: *"if a rule matters, something must be able to refuse when it is broken."* Three of
  these four bugs exist because a rule lived only in prose. Prefer an enforcer over more text.
