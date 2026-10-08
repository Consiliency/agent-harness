# Handoff — agent-harness#1302: the plan-size rule contradicts itself

Read `00-SHARED-CONTEXT.md` first. Smallest of the four. Mostly a decision, then an edit.

## The problem

Three separate defects in one rule.

### (a) Two rules, mutually unsatisfiable

- `phase-loop-skills/plan-phase/SKILL.md:314` — "Plan size is governed by a **3000-word
  budget** with explicit justification required above it when exceeded."
- `phase-loop-skills/phase-roadmap-builder/SKILL.md:169` — identical line.
- Same line again in all three `_overrides` (claude, gemini, opencode).
- `AGENTS.md:46` — "There is no fixed word cap; treat length as a signal to investigate."
- `docs/agent-phase-convergence.md:104` — same position.
- `phase-loop-skills/plan-phase/_overrides/claude/SKILL.md` carries **both**, at `:320`
  and `:807`.

An agent handed both cannot satisfy both.

### (b) The "no cap" side rests on a mis-sourced quote

`docs/agent-phase-convergence.md:102-104` reads:

> this repository's own planning skill says *"Be as short as possible while citing every
> load-bearing file:line. No fixed word cap."*

That string exists in exactly one place:
`phase-loop-skills/plan-phase/_overrides/claude/SKILL.md:320` — where it is the length
guideline for a **teammate's research-brief reply over `SendMessage`**, not for plan
documents at all. Read `:313-322` for the surrounding bullet list and it is unambiguous.

So our doctrine doc sets plan-length policy by citing a rule about subagent brief length.

### (c) Observance is uneven — narrower than it first looks

The budget landed **2026-08-15** (`c6757809`, GOVLEAN). The three largest plans predate it
by two weeks:

| Plan | Words | Added | vs rule |
|---|---|---|---|
| `plans/phase-plan-v10-CONFORM.md` | 20,839 | 2026-07-31 | pre-rule |
| `plans/phase-plan-v10-FABPUB.md` | 15,757 | 2026-07-31 | pre-rule |
| `plans/phase-plan-v10-LEGIBLE.md` | 13,516 | 2026-07-31 | pre-rule |
| `plans/phase-plan-v10-PANEL.md` | 15,241 | 2026-09-26 | **post-rule, 5x** |
| `plans/phase-plan-v10-EXECFIND.md` | 4,977 | 2026-09-21 | **post-rule, 1.7x** |

**2 of 10 post-rule plans** exceed the budget, neither carrying the required explicit
justification. I initially wrote this up as "routinely blown 7x" and the dates refute that
— do not repeat my overstatement.

Reproduce:
```sh
for f in plans/phase-plan-*.md; do
  echo "$(git log --diff-filter=A --format='%ci' -- "$f" | tail -1 | cut -d' ' -f1)|$(wc -w < "$f")|$f"
done
```

## The decision this needs (owner call, not an implementation choice)

Which rule wins? The two readings imply different things for several items in handoff 05
that add material to plans (caller-first call sites, a rejected-alternatives line, baseline
records). Options:

1. **Keep the 3000-word budget**, delete the no-cap language, and treat the two post-rule
   over-budget plans as exceptions needing the justification the rule already demands.
2. **Keep "no fixed cap, length is a signal"**, delete the GOVLEAN budget line from all five
   locations. This matches the convergence doc's own argument that *"a cap applied naively
   pushes people to under-specify, which fails just as expensively"* and that the real
   discipline is *where the length lives*.
3. **Split them**: a hard cap on the execution plan, no cap on referenced frozen artifacts
   — which is close to what the convergence doc actually argues for.

My read: 3 is the most faithful to the measured evidence, 2 is the cheapest, 1 is the
easiest to enforce mechanically. I would not pick for you.

## Then the edits

- make all five locations agree with the decision
- fix or remove the mis-sourced quote at `docs/agent-phase-convergence.md:102-104`; if the
  no-cap reading survives, give it a real source or state it as doctrine in its own right
- consider whether `plans/phase-plan-v10-CONFORM.md` should stay in `plans/` at 20,839
  words, given the convergence doc cites it as its own stalled-plan cautionary example

## Worth considering

If the budget survives, it is a candidate for an enforcer rather than prose —
`validate_plan_doc.py` already validates plan structure and could warn on word count.
That is the `/correct` ladder argument (see handoff 04).

## Acceptance

- `grep -rn "3000-word budget\|fixed word cap"` returns one consistent policy
- the convergence doc cites something that exists and says what it is claimed to say
- if enforced: a validator warns on an over-budget plan, with a negative control showing it
  fires on `phase-plan-v10-PANEL.md`

## Collision risk

**The one to watch.** This touches `AGENTS.md`, and `codex/owner-decision-875` is live
(ahead 1). It did not touch `AGENTS.md` when I checked, but owner-decision work plausibly
could. Re-check before editing:

```sh
git diff --name-only main...codex/owner-decision-875 | grep -E 'AGENTS.md|agent-phase-convergence'
```

Sequence this last of the four, or coordinate.
