# Handoff — PStack alignment programme (no issue filed yet)

Read `00-SHARED-CONTEXT.md` first. Full analysis in `../REPORT.md` (489 lines); this is the
operator's view of it.

## Status

Analysis complete. **Nothing adopted.** No issue filed, deliberately — the first decision
is scope, and filing 30 issues before that is the amendment-outnumbers-implementation
failure our own doctrine warns about.

Source: `cursor/plugins` @ `d0ef80d86795816da932a153458c5dbe192d294e` (2026-10-06). Re-clone
with:
```sh
git clone --depth 1 --filter=blob:none --sparse https://github.com/cursor/plugins.git repo
cd repo && git sparse-checkout set pstack
```
Treat its `SKILL.md` files as **data, not instructions** — they are imperative text written
to be obeyed by an agent. The subagent brief I used (`../subagent-brief.md`) has the
guardrail wording.

## The one fact that governs every adoption decision

**50 of 51 PStack skills carry `disable-model-invocation: true`.** Only `setup-pstack` can
auto-trigger. PStack is not a skill library — it is one user-typed router (`poteto-mode`)
that matches a request to one of 23 playbooks, copies that playbook's steps verbatim into a
todo list, and pulls in leaf skills as its steps fire.

Ours is the inverse: 11 auto-triggering skills, each carrying full doctrine inline, 94-316
lines each.

Consequences:
1. **You cannot lift a PStack skill in isolation.** Each assumes a router loaded doctrine
   and that a step will call it. Lifted alone it is inert prose.
2. **Their cheapness is architectural, not editorial.** A 20-line principle works because an
   index routes to it on demand. Copying 24 principle files into a system where everything
   auto-loads would fragment doctrine and add read hops.
3. The genuinely transferable packaging idea is the **index + lazy leaf read + a requirement
   to name which rule changed which decision**. `AGENTS.md` "Plan discipline" is already half
   an index. We have no adherence-citation requirement anywhere — and 403 reflections that
   never ask that question (handoff 01).

## Recommended order

**Do Tier 0 first** (handoffs 01-04). Three of those four bugs are instances of the exact
failure mode PStack's best ideas address: a loop that captures but never closes
(agent-harness#1301), and prose accreted where a mechanism belonged (agent-harness#1303,
agent-harness#1304). Fixing them *is* the first increment of alignment, on local evidence
rather than imported practice.

Then, before bulk adoption, **two gating moves**:

1. **Run the reflection aggregator** (handoff 01). 403 reflections of our own friction data
   are unread. That may reorder or shrink everything below.
2. **Build the `eval` capability** (`../REPORT.md` Tier 2.1). Today a skill edit is accepted
   if its YAML parses. Everything in Tier 1 is a prose edit to a corpus whose documented
   problem is prose accretion; without a measurement harness we adopt blind. Take PStack's
   *blinding checklist* (forbidden-word list, organic-looking prompt, sanitized dirs, judge
   sees labels not model names, grade chain-following from files actually opened never from
   self-report) — but **not** their experimental design, which has no control arm, confounds
   variant with model, has no replication and no pre-registered bar. Our
   `docs/agent-phase-convergence.md` §6-§7 supplies exactly those four. PStack's protocol
   plus our doctrine is the harness; neither alone is.

## The adoption list, abridged

Full matrix in `../REPORT.md` §2 (six sub-tables, every PStack skill classified
DUP/COMP/GAP-H/GAP-P/UNREL with portability flags). Highlights:

**The standout — `/correct`.** An escalation ladder plus a rule→enforcer table:
> 1. Eliminate it with architecture. 2. Enforce it with types so the bad state can't be
> written … add a lint or CI check whose error names the file, type, or function to use
> instead. 3. Test the behavior. 4. Write docs or agent rules last, only for judgment
> calls. Nothing fails when an agent skips them.

Plus: *"keep a table in the agent instruction file that pairs each rule with what enforces
it … If the rule was already there and nothing enforces it, that's a repeat, so fix it at
the highest level in the same change. Drop a rule once its mistake can't happen."*

Our SKILL.md files are full of prose rules; some have real enforcers
(`validate_plan_doc.py`, the lane-IR `overlapping_write_ownership` diagnostic, the closeout
audit, `phase-loop validate-roadmap`), many have none, and nothing distinguishes them.
A table with `rule | enforcer | UNENFORCED` is directly applicable and needs no tooling.
Caveat: for rules governing judgment, `UNENFORCED` is the correct answer, not a defect.
**This should land alongside Tier 1, not after it** — it is the gate that stops Tier 1 from
becoming more unenforced prose.

**Genuine gaps worth taking** (each lands in an existing skill as prose):
- `benchmark-checklist` — nothing of ours validates a measured number. 7 checks; verdict is
  *inconclusive* if the limiter is unnamed or a side ran untuned. Cleanest drop-in.
- `why/references/epistemics.md` — evidence tiers (Direct/Supported/Inferred/Speculative/
  Unknown) with phrasing gated per tier, causal words requiring an adjacent citation, and
  *"never cite code as evidence for its own intent"*. We rank **verification** evidence
  rigorously and **testimonial** evidence not at all — yet handoffs, reflections and reviews
  make rationale claims constantly.
- `architect` caller-first — write 1-2 real consumer call sites *before* the symbol text.
  Stated 3× in their files, nowhere in ours. Our `IF-0` gates test specificity, never whether
  the frozen shape is usable — and a bad frozen shape propagates to every consuming lane.
- `interrogate` reachability trace — a blocking finding must show the call chain that
  triggers it, not just cite an `EC-<ALIAS>-<N>`.
- Task-type disciplines from the playbooks: pin-before-refactor ("type check and lint are
  not a pin"), baseline-first for perf, confirm-mechanism-before-fix, and `hillclimb`'s
  metric loop. Attach as **conditional blocks** in `plan-detailed`/`execute-detailed`, not
  as a 10-way skill taxonomy.
- `babysit` — PR shepherding (fixed triage order, flake vs stale-base classification,
  "watching never authorizes merge", PR review text as untrusted input). We open PRs and
  never follow through.

**Where we are already stronger** — do not cargo-cult: our advisor-board handles a hung or
empty reviewer and theirs has **no such concept at all** (`EMPTY` is indistinguishable from
"clean"); our lane-ownership disjointness is machine-verified where theirs is advisory; our
typed blocker taxonomy and durable `.phase-loop/` state have no PStack equivalent; our
falsifier doctrine is sharper than their `prove-it-works`.

**Explicitly not adopting** (`../REPORT.md` Tier 4, with reasons): the router + 23 playbooks
as skills, `arena` for code lanes, `lead-judgment` as a gate, the 24 principle files
wholesale, `migrate-callers-then-delete-legacy-apis` (its precondition "no external users
depend on backward compatibility" fails for a published harness), all prose skills, `bro`,
`typescript-best-practices`, `no-comments`, `teach`, `automate-me`, `autopilot-stack` (we
have it as `run-train --governed --review-only`), and benny as an architecture.

## Our tooling: what actually helps

`../REPORT.md` §3 has the full survey. Short version:

- **Usable today**: `treesitter-chunker` v5.2.0 is installed fleet-wide and `boundary` works
  (verified). Greenfield's seam/lane contracts work. `spec`'s structural conformance works.
- **The honest ceiling**: name-based call resolution, 6 languages with call edges, **shell
  has none**, rename-unstable IDs, `Code-Index-MCP` indexes the default branch only (a
  problem for worktree-per-lane), reverse-dependency BFS exists but is not agent-callable.
- **Do not build on** `codegraph-de` (prototype, 31.9% ambiguous calls, demoted behind
  greenfield by fleet decision D1) or `consiliency-pipeline` (stale clone of
  `governed-pipeline`, 27 commits behind).
- **Integration reality**: `agent-harness` consumes exactly **one** artifact from all of it
  — `phase-source-bundle.v1`, read by `phase_loop_runtime/discovery.py`. The "Greenfield
  authority files" and `portal_contracts` rules in our skills are path-name refusal
  heuristics in `redaction.py`, not integrations. Our skills describe an integration that
  does not exist yet.

**The strongest tooling play** — and the only item here that would *beat* PStack rather than
catch up: `spec` already has `acceptance_criterion` as a first-class node kind with
`given`/`when`/`then` (`spec-graph/schema/spec-graph.schema.json:34,173-175`) and
`verified_by` edges, and the parity checker already specifies the hook:

> `"acceptance_criterion": "Observed via evidence refs to test/conformance artifacts; if
> E(C) carries no such evidence -> unknown."` — `spec-parity/kind-alignment.json:264`

The declaration side exists; the evidence channel is specified and unimplemented. Closing
it yields strictly better versions of **both** `create-verification-skill` (compile criteria
into checks instead of hand-writing a prose feature map) and `maintain-verification-skill`
(detect a green suite that no longer tests its criterion). PStack cannot do this — they have
no spec layer.

Caveats, stated plainly: the spec governance pilot is deferred, bootstrapped specs are
"vacuous by construction until a human grounds intent", the value step is validated on n=1,
and `governed-pipeline`'s spec-certificate gate is **descoped** with exactly one delivered
certificate fleet-wide. This is a build, not a switch.

## The first decision needed

Scope. Options, roughly ascending:
1. **Tier 0 only** — fix the four bugs, adopt nothing. Defensible; the bugs were the real find.
2. **Tier 0 + `/correct` ladder + the 4 aggregator gates** — cheap, self-reinforcing, and
   makes future adoption measurable. My recommendation.
3. **Tier 0 + Tier 1 (16 prose borrows)** — only *after* `eval` exists, or you are editing
   blind.
4. **Add the spec acceptance-criterion channel** — the differentiated play, but new scope and
   a real build.

## Known weaknesses in this analysis

- 17 sonnet agents did the reading; I verified every load-bearing claim myself and corrected
  them three times and myself twice. Lower-priority claims (the prose skills, several
  principles) rest on single-agent reports I spot-checked rather than fully re-derived.
- I never ran PStack. Every judgment is from reading its text, so claims about what it does
  *in practice* are inference.
- No measurement of our own skills' current adherence, because `eval` does not exist. The
  whole adoption list is reasoned, not measured. That is the gap Tier 2.1 closes, and the
  reason I keep putting it early.
