# Handoff — agent-harness#1301: the reflection loop is write-only

Read `00-SHARED-CONTEXT.md` first. **Do this one first of the four.**

## The problem in one paragraph

Every phase-loop skill writes a reflection file at closeout. There are **403** of them.
Nothing has ever read them: **0** improvement plans exist, **0** reflections are archived.
We pay the per-run capture cost and get none of the benefit. This is not a design that was
never built — it ran twice by hand and produced real skill edits. It is a pipeline with
four specific breaks in it.

## Verified evidence (do not re-derive)

```sh
find ~/.codex/skills ~/.claude/skills -path '*/reflections/*' -name '*.md' | wc -l   # 403
find ~/.codex/skills ~/.claude/skills -path '*skill-improvement-planner/plans*' | wc -l  # 0
find ~/.codex/skills ~/.claude/skills -path '*reflections*' -path '*archive*' | wc -l    # 0 real
```

Corpus: 205 `execute-detailed`, 114 `plan-detailed`, 40 `execute-phase`, 29 `plan-phase`,
5 `phase-roadmap-builder`, 9 `claude-*`, 1 `advisor-panel`. 158 repo/branch pairs. All
dated 2026-09-25 → 2026-10-07.

It worked before:
- `188125a1` + `af4c0a66` (2026-06-17) — aggregated a 44-reflection corpus into 8 recurring
  themes + 4 singletons and applied `A1-A8, B3, B4` to execute-phase, plan-phase,
  roadmap-builder.
- `be02e780` (2026-07-11) — folded further learnings; its body notes the reflections cache
  "is cleared at closeout (post-merge)". The current 403 accumulated after that clear.

## The four breaks, each with its location

1. **The planner's enumeration omits the biggest producer.**
   `phase-loop-skills/skill-improvement-planner/SKILL.md:38-45` lists seven skills.
   `execute-detailed` is **not** among them — and it is **205 of 403 (51%)**.
   `advisor-panel`, `phase-loop` and `run-train` are also absent.

2. **`What didn't` is never parsed.** `SKILL.md:49-50` reads only `What worked` and
   `Improvements to SKILL.md`. Worse, `assets/aggregator_prompt.md:3` asserts each
   reflection "is a short markdown document with **two** sections". Real reflections have
   four (`Run context`, `What worked`, `What didn't`, `Improvements`), and the friction
   evidence is in `What didn't`. That same prompt also names `claude-*` skills while the
   corpus is overwhelmingly `codex-*`.

3. **The editor targets paths that do not exist.**
   `skill-improvement-planner/SKILL.md:14-15` and `skill-editor/SKILL.md:14-15` direct edits
   to `<harness>-config/skills/...` and say to leave `vendor/phase-loop-skills/` stale
   "until the end-of-v36 cutover". Verified absent: `codex-config/`, `claude-config/`,
   `vendor/`. Canonical is `skills-src/` (IF-0-CANON-1).

4. **The runtime hook only counts.**
   `phase-loop-runtime/src/phase_loop_runtime/maintenance.py:44-62` globs only
   `codex-*/reflections` (so the 9 `claude-*` reflections are invisible), returns a bare
   total, and has no threshold and no trigger. `maintain-skills` is operator-invoked only.

## Suggested approach

Phase 1 — repair the pipeline (four small edits, all in `skills-src/`):
- add the four missing skills to the enumeration
- parse `What didn't`; fix the "two sections" claim and the `claude-*` naming in
  `aggregator_prompt.md`
- repoint both skills at `skills-src/`
- give `maintenance.py` a threshold and a trigger, and widen its glob beyond `codex-*`

Phase 2 — add a quality filter **before** the first big run, or it will drown:
- 42 reflections repeat one identical boilerplate line verbatim
- 48 name org-qualified issue refs the aggregator rejects by its own repo-agnostic rule
- one branch carries 35 reflections; `recur-freeze-counts` alone has 4
- much of `execute-detailed`'s body is closeout-ledger text (e.g. `finalbaseline26/25`)
  that belongs in the handoff, not a reflection
Suggest: dedup, a per-run-per-skill cap, and requiring `Improvements` to be either
repo-agnostic or an explicit "none".

Phase 3 — run it on the backlog, with `--dry-run` first.

## Worth considering: four admission gates from PStack

PStack's `/reflect` synthesizer has 8 gates; we have recurrence only. Four are directly
applicable and cost nothing (`../REPORT.md` §2e, Tier 1.14):

- **skill-was-used** — is this a skill gap, or did the agent just not follow the skill?
  Needs a new "skills read this run" field in `Run context`.
- **already-covered** — read the target skill before accepting an edit. Note the nuance:
  *"If the existing guidance is buried, weak, or easy to skip past, accept the row but
  reframe the proposal as a wording / placement improvement to make it fire (not a
  duplicate addition)."* That is exactly agent-harness#1303's problem.
- **decision-changing** — "a future agent does something different because of the edit,
  not just reads more text."
- **structural-mechanism** — "route to Backlog when a lint rule, script, metadata flag, or
  runtime check already enforces the rule or could enforce it cheaply. Skill prose is for
  things mechanisms cannot enforce." Route these to
  `docs/registers/deferred-findings.md`.

Source: `/tmp/pstack-probe/repo/pstack/skills/reflect/references/synthesizer.md:15-23`
(re-clone if gone; pinned at `d0ef80d8`).

## Why first

The corpus is **403 reflections of our own friction data that nobody has read.** Running
the aggregator may well tell us which of our skills actually hurt in practice — which
could reorder or shrink the PStack adoption list in handoff 05. Adopting someone else's
answers while sitting on an unread record of our own problems is the wrong order.

## Acceptance

- planner emits a plan artifact from the real backlog
- the four missing skills appear in its scope
- a `What didn't` item demonstrably reaches a recommendation
- editor resolves a real target path under `skills-src/`
- consumed reflections get archived
- **negative control**: show the pipeline produced nothing before your change and something
  after, on the same corpus

## What I did not check

- `skill_improvement_planner` runtime code beyond `maintenance.py:44-62`
- whether reflection *writing* is templated (the 42 identical lines suggest it, but I did
  not find the writer)
- whether any of the ~400 reflections contain genuine decision content; I read ~12 and
  grepped the rest. My "usable corpus" claim (~334/403 repo-agnostic) is a regex heuristic.

## Collision risk

Low. No active branch touched `skill-improvement-planner`, `skill-editor` or
`maintenance.py` when I checked. Re-check per `00-SHARED-CONTEXT.md`.
