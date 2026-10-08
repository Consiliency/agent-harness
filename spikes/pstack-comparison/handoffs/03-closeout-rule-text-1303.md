# Handoff — agent-harness#1303: malformed text in the rule that sets terminal status

Read `00-SHARED-CONTEXT.md` first.

## The problem

Two Core Rules in `phase-loop-skills/execute-phase/SKILL.md` are single lines of **2,317**
and **1,564** characters (lines `167` and `21`; `183` is 1,295). Each is a nested
conditional governing the closeout audit — the rule that decides whether a phase reports
`complete` or `dirty_worktree_conflict`. Both contain grammar broken by patch-on-patch
editing:

- **`:167`** — "so the audit blocks and **block only when** it exits 1 (unknown ignored outputs)"
- **`:21`** — "so the audit blocks and **treat them as blocking** ONLY when it exits 1"

Reproduce:
```sh
awk '{print NR": "length}' phase-loop-skills/execute-phase/SKILL.md | sort -t: -k2 -rn | head -3
sed -n '167p' phase-loop-skills/execute-phase/SKILL.md | grep -o "so the audit blocks and[^.]*"
```

## Why this is a behaviour risk, not a style nit

An agent must extract exit-code precedence — 0 / 1 / 2 / could-not-run — from a 2.3KB
paragraph to pick the right terminal status. The semantics are spread across three nested
sentences: exit 0 and 1 in one, exit 2 and "ANY failure to run" in the next, joined by
"and so does". Line `:167` also states its precedence exception *ahead of* the instruction
it overrides. And we generate this text into four harness overlays, so any
mis-parse is multiplied.

The corpus also uses four names for overlapping things — "closeout audit", "whole-tree
`git status --short` closeout audit", `phase-loop-closeout-audit`, and "the audit" — so an
agent cannot tell whether `:21`'s audit is `:167`'s.

## Suggested approach

Edit in `skills-src/` (see `00-SHARED-CONTEXT.md` for the regenerate pipeline).

1. Fix the two broken sentences.
2. Replace the prose with an **exit-code case table**, condition before instruction:

   | audit exit | meaning | action |
   |---|---|---|
   | 0 | producer accounted for | not a blocker; continue |
   | 1 | unknown ignored outputs | stop, `dirty_worktree_conflict` |
   | 2 | probe failed | stop, `dirty_worktree_conflict` |
   | cannot run at all | inability to measure | stop — never evidence of a clean tree |

   Confirm those mappings against the current text before trusting my table; I derived it
   from `:21` and `:167`, which are the very lines in question.
3. Use one name for the audit throughout.
4. Keep the `--phase <ALIAS>` substitution warning — it is load-bearing and correct.

## The better fix, if you have appetite

The exit-code semantics belong in the **audit tool's own output**, not in skill prose. The
rule already tells the agent not to judge by hand ("For IGNORED paths do not judge by hand:
run `phase-loop-closeout-audit` ..."), so having the agent re-derive the exit-code meaning
from a paragraph is the inconsistency. Having the tool print its own verdict and the
required action would delete most of both lines.

That is `/correct` ladder level 2 instead of level 4, and it is the same argument as
handoff 04. If you take this route, note it on agent-harness#1304 too — they are the same
class of fix.

## Scope discipline

This is the most tempting file in the repo to "clean up". Don't. `execute-phase/SKILL.md`
is 252 lines / 4,563 words of load-bearing contract text, and a broad rewrite is both a
large diff across 12 generated files and a real regression risk. Fix the two named lines
and the naming inconsistency. Nothing else.

I considered and rejected adopting a prose-quality skill for this (`../REPORT.md` §2f,
Tier 4): the behaviour-bearing writing rules are worth applying to our own corpus, a
`technical-writing` skill is not worth installing.

## Acceptance

- both sentences parse
- exit-code mapping is readable without re-reading
- one name for the audit
- parity + drift gates green; `pytest` green
- **negative control is hard here** — this is a text fix with no obvious failing test.
  Honest options: (a) accept that and rely on review, (b) if you move the semantics into
  the tool, test the tool's verdict output instead, which *is* testable. (b) is better and
  is another argument for the tool route.

## What I did not check

Whether any runtime code parses these lines (I assume not — they are agent-facing prose).
Confirm before restructuring, in case a test asserts on the wording.

## Collision risk

Low but non-zero: `execute-phase/SKILL.md` is high-traffic. No active branch touched it
when I checked. Re-check per `00-SHARED-CONTEXT.md` — and note my own
agent-harness#1309 just touched the same skill's `scripts/`, so `main` has moved.
