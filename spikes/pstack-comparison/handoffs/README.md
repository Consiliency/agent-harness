# Handoffs from the PStack comparison

Written 2026-10-07 against `main` @ `37114d36`. Each handoff is self-contained enough to
start cold, but **read `00-SHARED-CONTEXT.md` first** — it carries the house rules that
cost me time (canonical `skills-src/` vs generated `phase-loop-skills/`, the `uv` test
invocation, the live-branch collision table) and the doctrine these fixes try to honour.

| # | Handoff | Issue | Kind | Notes |
|---|---|---|---|---|
| 00 | `00-SHARED-CONTEXT.md` | — | context | read first |
| 01 | `01-reflection-consumption-1301.md` | agent-harness#1301 | bug | **start here** — may reorder 05 |
| 02 | `02-plan-size-contradiction-1302.md` | agent-harness#1302 | bug | needs an owner decision; touches `AGENTS.md` — sequence last |
| 03 | `03-closeout-rule-text-1303.md` | agent-harness#1303 | bug | resist scope creep |
| 04 | `04-under-enumeration-validator-1304.md` | agent-harness#1304 | enhancement | scope already halved by an audit |
| 05 | `05-pstack-alignment.md` | none filed | programme | gated on 01 + an `eval` capability |

Already closed: agent-harness#1300 (worktree dirty gate), fixed in PR
agent-harness#1309, merged.

## Reading order if you are picking up the whole thing

`00` → `01` → `04` → `03` → `02` → `05`.

That is bugs-before-adoption, cheapest-first within the bugs, and `02` last because it is
the only one that touches a file an active branch may contend for. `05` is last because
`01` may change what it recommends.

## The two things I would not want lost

1. **50 of 51 PStack skills cannot auto-trigger.** It is a router with inert leaves, not a
   skill library. "Adopt a PStack skill" is mostly a category error — see `05`.
2. **Check the failure before building the capability.** I nearly built a tree-sitter
   touch-set proposer for agent-harness#1304; auditing the actual failure showed it would
   address 1 of 5 categories. See `04`.
