# PStack → agent-harness: overlap matrix and adoption plan

**Inputs pinned.** PStack (`cursor/plugins`) @ `d0ef80d86795816da932a153458c5dbe192d294e`
(2026-10-06). agent-harness @ `1159a46b`. 17 sonnet subagents, one shared brief
(`/tmp/pstack-probe/work/BRIEF.md`) + a harness digest; every claim below was
re-checked by me against primary files before inclusion.

---

## 0. Findings about OUR repo, discovered incidentally

These came out of the comparison and are independent of whether we adopt anything.
I verified all four myself. All are filed: agent-harness#1300, #1301, #1302, #1303, plus
the audit finding as agent-harness#1304.

### 0.1 The self-improvement loop has stalled, for four locatable reasons

| Stage | State |
|---|---|
| Reflections written (post-2026-09-25) | **403** in `~/.codex/skills/*/reflections/**` |
| Improvement plans produced from them | **0** |
| Reflections archived as consumed | **0** (no `archive/` dir exists anywhere) |

Breakdown: 205 `execute-detailed`, 114 `plan-detailed`, 40 `execute-phase`, 29
`plan-phase`, 5 `roadmap-builder`, 9 `claude-*`, 1 `advisor-panel`; across 158
repo/branch pairs, with clusters of 35, 30 and 24 on single branches.

**The loop is not vaporware — it has run twice, by hand, and produced real edits:**
- `188125a1` + `af4c0a66` (2026-06-17) aggregated a 44-reflection corpus into 8 recurring
  themes + 4 singletons and applied them (`A1-A8, B3, B4`) to `execute-phase`,
  `plan-phase` and `roadmap-builder`.
- `be02e780` (2026-07-11) folded further learnings, and its body notes the
  `~/.codex/skills/*/reflections/` cache "is cleared at closeout (post-merge)".

So the 403 accumulated *after* that clear and nothing has consumed them since. Four
verified defects explain why:

1. **The planner's skill enumeration omits `execute-detailed`.**
   `skill-improvement-planner/SKILL.md:38-45` lists seven skills; `execute-detailed` is
   not among them — and it is **205 of 403 reflections (51%)**. `advisor-panel`,
   `phase-loop` and `run-train` are also absent.
2. **It ignores `What didn't`.** It parses only `What worked` and
   `Improvements to SKILL.md` (`SKILL.md:49-50`), and `aggregator_prompt.md:3` asserts
   each reflection "is a short markdown document with **two** sections". Real
   reflections have four, and the friction evidence lives in `What didn't`.
   That same prompt names `claude-*` skills while the corpus is `codex-*`.
3. **The editor's target paths do not exist.** Both skills direct edits to
   `<harness>-config/skills/...` and tell you to leave `vendor/phase-loop-skills/` stale
   "until the end-of-v36 cutover". I checked: `codex-config`, `claude-config` and
   `vendor/phase-loop-skills` are all **missing**. The canonical source is `skills-src/`.
4. **The runtime hook only counts.** `maintenance.py:44-62` globs only
   `codex-*/reflections` (so the 9 `claude-*` ones are invisible), returns a bare total,
   and has no threshold and no trigger; `maintain-skills` is operator-invoked only.

The corpus is usable: ~334/403 `Improvements` sections are free of repo/issue markers and
385/403 propose something. But it also shows capture with no quality filter — 42
reflections repeat one identical boilerplate line verbatim, 48 name org-qualified issues
the aggregator would reject, and much of `execute-detailed`'s body is closeout-ledger
text (e.g. `finalbaseline26/25`) that belongs in the handoff.

### 0.2 Two of three worktree scripts can destroy uncommitted work

> **Status: fixed in PR agent-harness#1309** (issue agent-harness#1300). Verified live on
> `dev0`: before the fix the sweep's own `--dry-run` selected three worktrees holding
> **60 uncommitted files** belonging to concurrent `codex/*` and `fix/*` sessions; after,
> all three are KEEP. Decision rule is now `PRUNE = MERGED and CLEAN`, matching the two
> siblings that were already correct. Adds the first tests either script has ever had,
> each with a positive control; 7 of 8 fail against the pre-fix scripts.

`phase-loop-skills/execute-phase/scripts/`:

| Script | Merge gate | Dirty gate | Removal |
|---|---|---|---|
| `prune_merged_worktrees.sh` | `is-ancestor` + `gh` PR state (:92) | yes, KEEP on dirty (:152) | `--force`, then `git branch -D` (:167) |
| `sweep_stale_worktrees.sh` | ancestor of *local* HEAD | **none** | `remove -f -f` (:42) |
| `cleanup_lane_worktrees.sh` | **none** | **none** | `remove --force` (:88) |

`execute-phase/SKILL.md` states a KEEP-on-dirty policy, and only one script
implements it. `SKILL.md` also tells the operator to run the sweep *at phase start*.
None of the three has a liveness/recency gate, so a peer agent's freshly-created
worktree on a branch at-or-behind `origin/main` classifies as prunable.

### 0.3 The plan-size rule is contradictory, mis-sourced, and routinely blown

Three separate defects, all verified:

**(a) The rule contradicts itself.**
- `plan-phase/SKILL.md:314` + `phase-roadmap-builder/SKILL.md:169` (and all three
  `_overrides`): "Plan size is governed by a **3000-word budget**."
- `AGENTS.md:46` + `docs/agent-phase-convergence.md:104`: "**No fixed word cap**;
  treat length as a signal to investigate."
- `plan-phase/_overrides/claude/SKILL.md` carries *both*, at :320 and :807.

**(b) The "no cap" side rests on a mis-sourced quote.**
`docs/agent-phase-convergence.md:102-104` says *"this repository's own planning skill
says 'Be as short as possible while citing every load-bearing file:line. No fixed word
cap.'"* That string exists in exactly one place:
`plan-phase/_overrides/claude/SKILL.md:320` — where it is the length guideline for a
**teammate's research-brief reply over `SendMessage`**, not for plans at all. Our
doctrine doc sets plan-length policy by citing a rule about subagent brief length.

**(c) The rule is unevenly observed — and the giants predate it.**
The budget landed **2026-08-15** (`c6757809`, GOVLEAN). The three largest plans were
created 2026-07-31, two weeks *before* the rule:

| Plan | Words | Added | vs rule |
|---|---|---|---|
| `phase-plan-v10-CONFORM.md` | 20,839 | 2026-07-31 | pre-rule |
| `phase-plan-v10-FABPUB.md` | 15,757 | 2026-07-31 | pre-rule |
| `phase-plan-v10-LEGIBLE.md` | 13,516 | 2026-07-31 | pre-rule |
| `phase-plan-v10-PANEL.md` | 15,241 | 2026-09-26 | **post-rule, 5x over** |
| `phase-plan-v10-EXECFIND.md` | 4,977 | 2026-09-21 | **post-rule, 1.7x over** |

So **2 of 10 post-rule plans exceed the budget**, neither carrying the "explicit
justification" the rule requires. That is a real but narrow violation, not systemic —
I initially overstated this as "blown 7x in practice" and the dates refute that.

Separately: CONFORM, the 20,839-word plan `agent-phase-convergence.md:102` cites as its
stalled-plan cautionary example, is still sitting in `plans/` at full size.

### 0.4 Malformed text on our highest-stakes conditional

`execute-phase/SKILL.md` line 167 is **2,317 characters** and line 21 is **1,564** —
each a single nested conditional governing the closeout audit, which decides
`complete` vs `dirty_worktree_conflict`. Both contain visibly broken grammar from
patch-on-patch editing:

- :167 — "so the audit blocks and **block only when** it exits 1"
- :21 — "so the audit blocks and **treat them as blocking** ONLY when it exits 1"

This is a behavior risk, not a style nit: an agent must parse exit-code precedence
(0 / 1 / 2 / failed-to-run) out of a 2.3KB paragraph to pick the right terminal status,
and we ship this text to four harnesses.

---

## 1. The architectural difference that governs everything else

**PStack is not a skill library. It is one router with 50 inert leaves.**

Verified: 50 of 51 PStack skills carry `disable-model-invocation: true`. Only
`setup-pstack` can auto-trigger. Nothing in PStack fires on its own; `poteto-mode`
(typed by the user) matches the request to one of 23 playbooks, copies that playbook's
steps verbatim into a todo list, and pulls in leaf skills as its steps fire.

Our model is the inverse: 11 skills, each with a `description` that the host matches
against the request, each auto-firing, each 100-316 lines carrying its full doctrine
inline.

| | PStack | agent-harness |
|---|---|---|
| Entry | one user-typed router | per-skill auto-trigger |
| Unit count | 1 router + 23 playbooks + 50 leaves | 11 skills |
| Leaf size | 16-34 lines (principles), ~25 (playbooks) | 94-316 lines |
| Doctrine delivery | short always-loaded index → lazy leaf read | fully inline, always |
| Adherence check | reply must name each principle *and the decision it changed* | none |
| State across runs | the chat, plus a Slack thread or PR | `.phase-loop/` ledger + typed handoffs |
| Enforcement | prose | validators, lane-IR refusal, closeout audit, typed blockers |
| Parallelism | redundant (`arena`) or sliced (`swarm`), isolation advisory | disjoint lanes, machine-verified, scheduler worktrees |
| Taxonomy | 23 task types (bug/perf/refactor/forensics/...) | none; all work is "a phase" or "a bounded change" |
| Review | N same-prompt models, author-adjacent lead adjudicates | 4 lens-distinct cross-vendor seats, unanimity, no adjudicator |

**Three consequences for adoption:**

1. **You cannot lift a PStack skill in isolation.** Each assumes the router loaded
   doctrine and that a step will call it. Lifted alone, it is inert prose.
2. **Their cheapness is a function of their architecture, not better writing.** A
   20-line principle works because an index routes to it on demand. Copying 24 files
   into a system where everything auto-loads would fragment doctrine and add read hops.
3. **Their trigger problem is solved by fiat, ours is not.** With everything
   `disable-model-invocation`, PStack never worries about two skills competing for a
   request. We have 11 auto-firing descriptions and no disambiguation aid.

**What is genuinely transferable from the packaging** (and it is not the file split):
the **short always-loaded index + lazy leaf read + mandatory "name the rule and the
decision it changed"** output requirement. `AGENTS.md` "Plan discipline" is already
half of an index. We have no adherence-citation requirement anywhere — and 403
reflections that never ask "which doctrine rule changed a decision".

---

## 2. The overlap matrix

Classification: **DUP** = we do it, equivalently or better · **COMP** = same area,
different angle · **GAP-H** = they have something we lack · **GAP-P** = we are
clearly stronger · **UNREL** = no meaningful overlap.
Portability: **P** portable · **P\*** portable with adaptation · **C** Cursor-bound.

### 2a. Lifecycle & orchestration

| PStack | Ours | Cls | What we'd gain | Port |
|---|---|---|---|---|
| `poteto-mode` router + 23-playbook taxonomy | *none* (`phase-loop` is a lifecycle driver, not a classifier) | **GAP-H** | A request→work-class map. Ours routes one axis only (bounded vs multi-phase, via two skill descriptions). No read-only or measure-first shape exists. | P\* |
| `multi-phase-plan` | `phase-roadmap-builder` + `plan-phase` | **COMP** | Their per-unit verification spec (unit/live/perf all checked). No interface freeze, no goal IDs, no DAG validation — we are far more rigorous. | P |
| `autopilot-stack` | `run-train --governed --review-only` | **DUP** | Nothing. Ours is cross-repo, crash-resumable, with bound approval. | — |
| `autopilot-full`, `shipping` | `run-train` | **COMP** | `git patch-id` verdict reuse: a pure rebase shouldn't void a review. Ours invalidates on any head change, forcing a fresh 4-vendor round. | P |
| `babysit` + `watch-pr/policy.ts` | *none* | **GAP-H** | PR shepherding: fixed triage order (conflicts→threads→CI), CI-failure classification before retry, "watching never authorizes merge", review text treated as untrusted. We open PRs in `execute-phase` and never follow through. | P\* |
| `autonomous-run`, `orchestrate` | `phase-loop` + blocker taxonomy | **GAP-P** | Little. Ours is typed and durable; theirs is prose. One idea: re-inject standing orders verbatim into every brief/resume. | P |
| `opening-a-pr` | `execute-phase` publication + typed closeout | **COMP** | A fixed PR-body template with a mandatory "what this deliberately leaves out" section. We say when to open a PR, never what goes in it. | P |
| benny (triage→reproduce→fix) | *none* | **UNREL** (as a shape) | Event-driven external intake is a different architecture, not something `phase-loop` can express. Two pieces do transfer — see 2d. | C mostly |

### 2b. Planning & review

| PStack | Ours | Cls | What we'd gain | Port |
|---|---|---|---|---|
| `architect` + `design-red-flags.md` | `plan-phase` interface-freeze gates | **COMP** / **GAP-H** on quality | **Caller-first**: write 1-2 real consumer call sites *before* the symbol text ("the caller's experience is the spec"). Stated 3× in their files, nowhere in ours. Plus a shape-smell screen: leakage of wire types, pass-through methods, shallow module, two-ways-to-do-one-task, split state ownership. Our gates test *specificity*, never whether the frozen shape is *good* — and a bad frozen shape propagates to every consuming lane. | P |
| `architect/rationale-template.md` | `## Context` heading | **GAP-H** (small) | One line per gate naming the rejected alternative. Weigh against the plan-size rule (§0.3). | P |
| `interrogate` + `rubric.md` + `code-quality-review.md` | `advisor-board` | **GAP-P** overall, **GAP-H** on two points | (1) **Reachability trace**: a blocking finding must show the call chain that triggers it, not just cite an EC. (2) A **code-quality lens** — all four of our lenses are correctness-flavored; maintainability is unreviewed. Their panel is weaker (N identical prompts, ~2 seats, silent same-family fallback) and has **no handling for a hung or empty reviewer at all** — `EMPTY` is indistinguishable from "clean". | P |
| `interrogate/lead-judgment.md` | *none* (we require unanimity) | **COMP** — do not adopt as a gate | Their adjudicator is the author's own session with full context. Faster convergence, bought by discarding independence. Useful only as non-binding pre-triage. | P |
| `arena` (N competing attempts, pick base + graft) | *none* — we refuse write overlap at the lane-IR validator | **GAP-H**, narrow | Genuine gap *for design/spec artifacts only*. Would fit `plan-phase` interface-freeze exploration. Do **not** port to code lanes: "hand-port the best parts of N divergent diffs" is precisely what our ownership model exists to prevent, and their merge step offers no mechanism. | P\* |
| `swarm` | `execute-phase` lanes + `task-contextualizer` | **COMP** | One good idea: **result-validity gate** — a worker result that fails to record the SHAs and method its brief named is dropped, respawned once, then recorded as a gap, and "a gap does not count as a pass". | P |

### 2c. Evidence & verification

| PStack | Ours | Cls | What we'd gain | Port |
|---|---|---|---|---|
| `benchmark-checklist` | *none* | **GAP-H** (cleanest in the study) | 7 checks before trusting a number: name the limiter ("why not double?"), both sides tuned, arithmetic vs hard limits, count errors, ≥5 alternating runs with median+range, end-to-end relevance, confirm the work ran inside the timed region. Verdict is **inconclusive** if the limiter is unnamed or a side ran untuned. We verify that a command ran; nothing checks that a measured number means anything. | P\* |
| `blast-radius` | `pre_merge_destructiveness_check.sh`, `parent_tree_leakage_check.sh`, `audit_lane_file_touches.py` | **GAP-H**, different axis | All our gates police the *declared write set*. None asks what *outside* it behaves differently. Their evidence ladder (said-so → pointed at the line → showed the bad case can't happen → **ran it** → reproduced live) with a mandatory `unproven` label is the transferable shape. Weaker than us on proof: no negative control. | P |
| `create-verification-skill` + feature map | `plan-phase` *requires* `automation.suite_command`; absence is a blocker | **GAP-H** | We have **no answer to "the project has no scripted verification"**. They generate one. But their artifact is agent-interpreted prose with embedded commands — no pass/fail exit code — so it could not satisfy our contract as-is. | P\* |
| `maintain-verification-skill` | *none* | **GAP-H** | Drift between declared verification and actual behavior. Three-way triage (doc drift / harness gap / **product regression — report it, keep it out of this PR**), bounded to one PR. Nothing of ours notices a green suite that stopped testing the thing. | P\* |
| benny `control-adapter.md` | *none* | **GAP-H** | A capability contract for driving a real app: bring-up with app-identity confirmation, real UI drive ("do not inject the symptom"), read-only inspect, screenshot, recording, cleanup that "must not delete user work", reset between attempts, same inputs for baseline and patched. | P\* |
| benny existing-fix guard | `execute-phase` preflight | **GAP-H** (cheap, high value) | Before planning/executing, search for an existing fix artifact. "A claim without a commit or pull request is not a fix artifact." Our preflight checks the tree and the plan, never whether the work already landed. | P |
| `tdd` | `execute-phase` "tests first when practical" | **COMP** | A sharper applicability test: skip when the test needs broad harness setup, brittle mocks, slow e2e, production-only state, vague repro, or large fixture churn. Plus a "bad test" definition. Replaces our undefined "when practical". | P |
| `principle-test-behavior-not-implementation` | `falsified by <negative control>` | **COMP** | The five vacuous-test shapes, and a one-line check: *would it still pass if every imported function returned undefined?* Our rule demands a negative control but never says what makes an assertion hollow. | P\* |
| `principle-prove-it-works` | falsifier doctrine | **GAP-P** | We are sharper (pre-declared, goal-bound, must be shown to fail). One borrow: "when verification fails, suspect the observation method before the system". | P |

### 2d. Task-type disciplines (from the playbooks)

Ranked by value to us. These attach as short conditional blocks in
`plan-detailed`/`execute-detailed`, **not** as a 10-way skill taxonomy.

| PStack playbook | Transferable discipline | Cls | Port |
|---|---|---|---|
| `hillclimb` | A loop we lack entirely: frozen sensitivity-checked harness before any change; stop predicate with an **attempts floor** so a lucky early win can't end the run; `decision.tsv` ledger recording **reverted** attempts too, read before each attempt; accept only past noise with the gate green, else full revert; one commit per accepted win. Ours is convergent-on-agreement; this is convergent-on-a-number. Theirs lacks our hard cap — combine. | **GAP-H** | P\* |
| `perf-issue` | Baseline first, numeric before/after on a named repeatable command, and the ordered mantras (don't do it → don't do it again → do it less → later → when they're not looking → concurrently → cheaper; stop when one meets the target) as hypothesis ordering. | **GAP-H** | P\* |
| `refactoring` | **Pin behavior before structure moves**, and "type check and lint are not a pin". Our Quality Bar ("every changed behavior has a verification path") is *vacuously satisfied* by behavior-preserving work. Plus: a bug discovered mid-refactor is split out, not folded in. | **GAP-H** | P |
| `bug-fix` | Confirm the **mechanism** with runtime evidence *before* planning the fix; every shipped line traces to evidence; speculative hardening gets reverted, not left to ride. Our bound is file-scoped, not evidence-scoped. | **GAP-H** | P\* |
| `prototype` | A spike to settle an empirical fork *before* an interface freezes — entry-gated ("no decision means no prototype"), observe-don't-assert, never ships. Fills a real hole: `plan-phase` demands exact symbols with no branch for "this depends on a fact we don't have", and our own doctrine admits strict ordering "invites freezing a guessed interface". | **GAP-H**, narrow | P\* |
| `trace-forensics` | "Reach the queryable shape before you read" (dump the artifact into sqlite, then query) and calibrated confidence: no paired capture means hypothesis, not confirmed cause. | **COMP** | P\* |
| `investigation` | A read-only outcome (cited answer / diagnosis, no diff). Minor coverage gap; competent agents already do this. | **COMP** | P |
| `feature`, `visual-parity`, `runtime-forensics` | Little. `feature` is orchestration `plan-phase` does better; `visual-parity`'s one principle (don't alter the oracle) we already enforce; `runtime-forensics` is CDP-specific. | **DUP**/**UNREL** | — |

### 2e. Session state & self-improvement

| PStack | Ours | Cls | What we'd gain | Port |
|---|---|---|---|---|
| `eval` (blinded skill A/B) | *none* | **GAP-H** | Our skill edits are accepted if the YAML parses. Their blinding checklist is good (forbidden-word list, organic-looking prompt, sanitized dirs, judge sees labels not model names, **grade chain-following from files actually opened, never self-report**). Their experimental design is *not* rigorous: no control arm, variant confounded with model, no replication, no pre-registered bar. Our convergence doc §6-§7 supplies exactly those. | P\* |
| `correct` (mistake-class mining + rule→enforcer table) | *none* | **GAP-H** — the standout | Two things. (1) An **escalation ladder**: eliminate with architecture → enforce with types/lint/CI whose error names the fix → test the behavior → docs last, "only for judgment calls. Nothing fails when an agent skips them." Plus "prove each new check fails on a real past mistake" and a ratchet ("if the pattern is already common, fail only when a change adds more"). (2) A **rule→enforcer table** where a correction on a rule that exists but has no enforcer counts as a *repeat* and forces escalation in the same change, and a rule is dropped once its mistake can't happen. Their tooling for this is aspirational prose; the discipline is real and needs none. |
| `reflect` (3 lenses + synthesizer) | `skill-improvement-planner` → `skill-editor` | **COMP** | Don't adopt wholesale — it's Cursor transcript-mining at 4 model calls per session, and its 3 lenses (judgment/tooling/divergent) add recall diversity, not actionability. The value is in the **synthesizer's admission gates**, which we lack: *skill-was-used* (is this a skill gap or did the agent just not follow it?), *already-covered* (read the target skill before accepting an edit), *decision-changing* ("a future agent does something different, not just reads more text"), and *structural-mechanism* ("route to Backlog when a lint rule, script or runtime check could enforce it cheaply. Skill prose is for things mechanisms cannot enforce."). Also their tooling lens flags "every moment the user manually supplied context the agent could have fetched itself". Ours is stronger on cross-session recurrence (`--min-reflections`), contradiction surfacing, allowlist gating and archive-after-success. |
| `session-pickup` | `phase-loop resume` + typed handoffs | **COMP** | A no-durable-state fallback: reconstruct from `git log`/diff vs base, PR and plan artifacts. Ours is far more robust *when state exists* and silent when it doesn't. Keep our stricter "don't reconcile against a rejected closeout" rule. | P\* |
| `pause-safely` | `.phase-loop/stop` (between phases only) | **GAP-H** | A cooperative **mid-run** checkpoint note (intent, what's verified, next steps, key files, gotchas). Today a repair turn reverse-engineers intent from a dirty tree. Do not copy the auto `wip:` commit — it violates our no-commit-unless-asked rule. | P\* |
| `worktree-cleanup` + `worktree-audit.sh` | our 3 scripts | **COMP** | A **liveness/recency gate** before deleting a merged-and-clean sibling (theirs uses chat recency; ours would use process cwd or worktree mtime). Their script fails open on Linux (BSD `stat -f`). See §0.2 — our own scripts are the bigger problem. | P\* |
| `recall` | `phase-loop status/resume` | **COMP** | A capped brief shape (≤5 bullets, closed status tags, reverted fixes named). Low priority. | P\* |
| `show-me-your-work` (append-only decision TSV) | reflections + typed closeouts | **GAP-H** | We record outcomes, blockers and a fixed set of typed closeout decisions — but **no decision trail with alternatives**. Columns: `ts phase decision why evidence result`, where "evidence is a pointer, not prose". | P |
| `automate-me` | `skill-editor` | **COMP** | Nothing worth taking. Personal conventions belong in the owner's `CLAUDE.md`. Our planner's `--min-reflections 2` already encodes its one safeguard. | C |
| `figure-it-out` | *none* | **GAP-H**, small | A fallback when no shape fits. Lands as an escalation section in `plan-detailed`, not a skill. Our §6 falsifiability doctrine is stricter than theirs. | P |

### 2f. Understanding, prose, principles

| PStack | Ours | Cls | What we'd gain | Port |
|---|---|---|---|---|
| `why/references/epistemics.md` | *none* | **GAP-H** (best single file in PStack) | Evidence tiers — Direct / Supported / Inferred / Speculative / Unknown — with phrasing gated per tier; causal words ("because", "was designed to", "fixes") require an adjacent citation; **"never cite code as evidence for its own intent"**; an `Unknown` must list the queries run; anti-sycophancy (the user's hypothesis is one candidate). We rank *verification* evidence rigorously and *testimonial* evidence not at all — yet handoffs, reflections and reviews make rationale claims constantly. | P |
| `why` (7-category parallel MCP sweep) | PMCP/Context7 for library docs only | **GAP-H**, expensive | The **coverage map**: every evidence category reports searched / null / gap / skipped-with-reason. "Document the null, don't skip the search." Their discovery (list a dir, guess by name) is *worse* than `gateway_catalog_search`/`describe`. Note: they feed Slack/Notion text to subagents with full MCP access and have **no untrusted-input rule**. | P\* |
| `how` | `task-contextualizer` explorer template | **COMP** | An "open questions / couldn't trace" return section and an explicit licence to say "I could not determine X". Ours demands `file:line` but never says what to do at a dead end. | P |
| `teach`, `bro`, `typescript-best-practices`, `make-bot-ui` | — | **UNREL** | Nothing. `make-bot-ui` is a Grok-Bot webhook dashboard with Tailscale handoff. | — |
| `setup-pstack`, `poteto-help` | `## Execution Policy` + executor registry; skill `description`s | **GAP-P** / **GAP-H** (small) | `setup-pstack` is far weaker than ours (one always-on Cursor rule file vs our per-lane validated policy with a frozen vocabulary and no-silent-downgrade). `poteto-help` is a "which skill?" aid — worth at most a short "close calls" paragraph in `docs/TEAM-ONBOARDING.md` for our genuinely overlapping pairs, not a 12th skill competing for triggers. | P |
| `technical-writing`, `unslop` | *none* | **GAP-H** as a standard, low value as a skill | Don't adopt a prose skill. Do take the behavior-bearing rules and apply them to **our own** corpus: condition before instruction, no dropped verbs, one name per thing, no noun-string bullets, no pronoun pointing at a clause. See §0.4. | P |
| `no-comments` / Comment Sicko | validators | **UNREL** (skill) / **DUP** (principle) | The instinct — a claimed invariant becomes a type, test or lint — is how our validators got built. No evidence comment bloat is a problem here. | C |
| 24 `principle-*` skills | doctrine in `AGENTS.md` + 472-line convergence doc | mixed | Honest tally: 2 DUP, 2 UNREL, 1 low-value, 1 wrong-for-us (`migrate-callers-then-delete-legacy-apis` — its precondition "no external users depend on backward compatibility" fails for a published harness), leaving ~4 sentence-level borrows. `separate-before-serializing-shared-state` is **refuted as a gap** — our disjoint lane ownership is stricter and machine-enforced. The packaging lesson (§1) is worth more than any leaf. | P |
| `principle-never-block-on-the-human` | ask-user rule + continuation rules + `human_required=false` | **COMP**; ours sharper | Their principle has one axis (reversible vs not) and an unexamined premise. **But** `poteto-mode:20` has the real gem: *"If the answer is a fact you could observe by running something … it is not the human's to answer."* We probe before asking about **access** blockers; we have no such test for "which approach?" questions. | P\* |
| `principle-encode-lessons-in-structure` | convergence doc §5 ("if a rule matters, something must be able to refuse") | **DUP**, ours stronger | One borrow: a routing step in `skill-editor` — before appending prose, ask "can this be a validator, lint, or runtime check?"; if yes, file a mechanism task instead. Plus "a weaker guard becomes the next template". Directly aimed at §0.4. | P |
| `principle-fix-root-causes` | `execute-phase` "diagnose once" | **GAP-H** | Our bound says when to *stop*, never what a diagnosis must *contain* — so a symptom guard satisfies it. | P |
| `principle-guard-the-context-window` | dotfiles `file-read-cache`, `smart-search` | **COMP** | A return budget on subagent briefs ("summary + file:line, not raw dumps") and a counterweight to atomic splitting: inline what is read every invocation. | P |
| `principle-minimize-reader-load` | "Watch plan size" | **COMP** | "Name the invariant at the boundary, not in every consumer." Our access-blocker rule appears verbatim in 4 places across `plan-phase` and `execute-phase`; the CLI-exception wording in 2. That is duplication *and* drift risk across generated harness overlays. | P\* |

---

## 3. Our tooling changes several answers

PStack does impact analysis, touch-set enumeration and interface checking with LLM
judgment and grep, because that is all a Cursor plugin has. `/blast-radius` literally
instructs the agent to "look where grep stops". We have tooling that can make some of
this mechanical — but only some, and the honest line matters.

### What is usable today

| Capability | State | Evidence |
|---|---|---|
| **Boundary IR** — per-definition nodes with `qualified_name`, `signature`, span; edges `imports`/`dependencies`/`calls`, each tagged `resolved`/`ambiguous`/`unresolved` with strict-mode provenance | **Working, installed fleet-wide** | `treesitter-chunker` v5.2.0, Production/Stable, 1,291 commits, 267 test files, installed at `/opt/consiliency/tooling/current/bin/`. I ran `boundary` on one of our own scripts and got resolved `calls` edges with `resolution_mode: "strict"` and a `candidates` list. |
| **Definition-level retrieval** — fetch one symbol's span instead of a whole file | Working | `chunk_file`/`chunk --json`; `Code-Index-MCP` `symbol_lookup` returns `defined_in`, `line`, `span`, `signature` |
| **Greenfield boundary/seam/lane contracts** — `seam_lint` verdicts `out_of_scope_write`, `read_only_neighbor_modification`, `generated_output_authority_violation`; `parallel_lane_ownership` write-conflict reduction | Working (v0.2.2, 230 test files, commit 2026-10-07) | built directly on chunker Boundary IR via `greenfield/interface_boundary.py` |
| **Structural spec conformance** — 5-dimension parity certificate (completeness, soundness, closure, prohibition, revision-alignment), canon-digested, LLM never in the grading path | Working core; proven on graphbase (10/10 divergences caught, n=1) | `spec-engine/parity.py`, `spec-parity/SEMANTICS.md` |

### What is not ready, and why it bounds everything

- **Call resolution is name-based.** An edge resolves only when exactly one symbol in
  the repo has that name; otherwise `ambiguous`/`unresolved`. No type or binding
  resolution. `docs/agent-interface-readiness.md` says so itself. Common names (`run`,
  `get`, `main`) degrade.
- **Language coverage is narrower than the headline.** 370/371 grammars load, but only
  28 are extraction-verified, and **call extraction exists for just 6 languages**
  (C, Go, JS, Python, Rust, TS). **Shell has no call edges** — and our repo is
  Python + shell.
- **IDs are rename-unstable** ("Tier-2" fingerprints), so a rename reads as
  delete-plus-add.
- **Reverse-dependency BFS exists but is not agent-callable.** `find_dependents` lives
  in `Code-Index-MCP/mcp_server/graph/graph_analyzer.py:84` and is exposed only on the
  admin FastAPI gateway after an admin-only `POST /graph/initialize`. The MCP tool list
  (`symbol_lookup`, `search_code`, `get_status`, `reindex`, …) has **no graph tool**.
- **Code-Index-MCP indexes the default branch only.** Sibling worktrees return
  `index_unavailable` with `safe_fallback: native_search`. That is a direct problem for
  a worktree-per-lane pipeline.
- **`codegraph-de` is a prototype and explicitly demoted** — 31.9% of calls still
  `AMBIGUOUS_CALL`, `cycle_score` hardcoded to 0.0, clustering says Leiden but runs BFS,
  identity is `path+qualname+span`. Fleet decision D1 makes it an enrichment overlay
  behind greenfield, not a source of truth. Do not build on it.
- **`consiliency-pipeline` is a stale clone** of `governed-pipeline` (same origin, HEAD
  is 27 commits behind). Not a distinct capability.
- **Pin skew:** `greenfield` pins `treesitter-chunker==5.0.1`; `spec` targets 5.2.0.

### The under-enumeration audit — and why it refutes my own first instinct

Our worst documented failure is under-enumeration of a lane's owned files
(`plan-phase/SKILL.md:27`: "hit ~70% of phases in that drive"). My first instinct was to
derive the complete touch set from Boundary IR. **The audit refutes that.**

Commit `47c772b4` (2026-05-25) records what was actually missed:

> plan-phase agents under-declared owned files, omitting **test files, snapshots,
> generated migrations, env examples, lockfiles**.

| Missed category | Derivable from Boundary IR? |
|---|---|
| test files | **yes** (reverse edges + test glob) |
| snapshots | no — data, not parsed code |
| generated migrations | no — timestamped SQL |
| env examples | no — `.env.example` is not code |
| lockfiles | no — JSON/YAML are `empty` in the coverage table |

So a code-graph proposer would address **1 of 5** categories. All five are plain
**file-convention rules** — and `plan-phase/SKILL.md:27` already states them in prose.
Prose is what failed. The right fix is a check in `validate_plan_doc.py` that warns when
a conventional sibling is absent from the ownership set. That is `/correct` ladder level 2
("a check whose error names the file to use instead") instead of level 4 (more text).

Filed as agent-harness#1304. Secondary finding: the cited authority,
`docs/runtime/2026-05-25-end-to-end-drive-runner-failures.md`, **does not exist** in the
tree or anywhere in history — the same provenance problem as §0.3(b).

This is the clearest lesson of the whole exercise: our tooling is real, but the failure it
looked applicable to turned out to be a conventions problem. Check the failure before
building the capability.

### Second-highest: the acceptance-criterion gap

`spec` already has `acceptance_criterion` as a first-class node kind with
`given`/`when`/`then` (`spec-graph/schema/spec-graph.schema.json:34,173-175`) and
`verified_by` edges. And the parity checker already specifies the hook:

> `"acceptance_criterion": "Observed via evidence refs to test/conformance artifacts; if
> E(C) carries no such evidence -> unknown."` — `spec-parity/kind-alignment.json:264`

So the *declaration* side exists and the *evidence channel* is specified but
unimplemented. Closing that one gap would give us, in one move, strictly better versions
of **two** PStack skills: `create-verification-skill` (compile criteria into checks
instead of hand-writing a prose feature map) and `maintain-verification-skill` (detect a
green suite that no longer tests its criterion). PStack cannot do this at all — they have
no spec layer.

Caveats, stated plainly: the spec governance pilot is deferred, bootstrapped specs are
"vacuous by construction until a human grounds intent", the value step is validated on
n=1, and `governed-pipeline`'s spec-certificate gate is **descoped** with exactly one
delivered certificate fleet-wide. This is a build, not a switch to flip.

### Where our tooling does *not* help

`EC-*` IDs are not spec-derived — `goal_coverage.py` parses them from roadmap markdown
and consults no spec data; it also documents that it guarantees completeness but "does
NOT verify ADEQUACY". `IF-0` gates are not bound to spec `interface`/`operation` nodes.
Nothing compares a frozen signature against the current tree (greenfield's
`stale_boundary_ir` is a digest freshness check, not per-signature drift). And there is
no structured rejected-alternatives record anywhere — `spec`'s `rationale` field is an
unhashed, non-authoritative envelope. So `architect`'s caller-first and
alternatives practices remain prose practices for us, not mechanizable ones.

**Integration reality check:** of all this, `agent-harness` consumes exactly one
artifact — `phase-source-bundle.v1`, read by `phase_loop_runtime/discovery.py`. The
"Greenfield authority files" and `portal_contracts` rules in our skills are
**path-name refusal heuristics in `redaction.py`**, not integrations. Nothing in the
harness calls the chunker, greenfield, spec, or any index. The skills describe an
integration that does not exist yet.

---

## 4. Adoption plan

Ordered by our own doctrine: cheap and portable first, watch the amendment-to-
implementation ratio, and don't let governance become the work. Everything in Tiers 1-2
is prose landing in existing skills; nothing needs a new skill until Tier 3.

### Tier 0 — Fix our own defects first (no PStack dependency)

These are not adoptions. They are bugs the comparison surfaced, and three of the four
would undercut any adoption built on top of them.

| # | Action | Why first |
|---|---|---|
| 0.1 (agent-harness#1301) | **Repair the consumption path** (4 one-line fixes, all verified): add `execute-detailed` (+`advisor-panel`, `phase-loop`, `run-train`) to the planner enumeration; parse `What didn't`; repoint the editor at `skills-src/` instead of the missing `<harness>-config/` and `vendor/`; give `maintenance.py` a threshold/trigger instead of a bare count. Then run it on the 403 backlog. | We pay the per-run capture cost and get nothing. It worked by hand on 44 reflections in June; 51% of the current corpus is invisible to the planner. Any "capture more" recommendation is worthless until this works. |
| 0.1b (agent-harness#1301) | **Add a quality filter to capture**: dedup, a per-run-per-skill cap, require either a repo-agnostic `Improvements` line or an explicit "none", and move closeout-ledger text to the handoff where it already lives. | 42 reflections repeat one identical line; 48 name org-qualified issues the aggregator rejects by rule; one branch has 35. |
| 0.2 (agent-harness#1300 → PR #1309) | ~~Add the dirty-tree gate to `sweep_stale_worktrees.sh` and `cleanup_lane_worktrees.sh`~~ — **DONE** | They `remove -f -f` / `--force` with no dirty check, against a stated KEEP-on-dirty policy, and `SKILL.md` tells operators to run the sweep at phase start. Uncommitted work can be destroyed. |
| 0.3 (agent-harness#1302) | **Resolve the plan-size contradiction**; fix the misattributed quote at `agent-phase-convergence.md:102-104`. | An agent handed both rules cannot satisfy both. The "no cap" side cites a subagent-brief guideline as authority on plan length. |
| 0.4 (agent-harness#1303) | **Repair `execute-phase/SKILL.md:21` and `:167`** — fix the broken grammar, lead with the exit-code case table, use one name for the audit. | 2,317 chars of nested conditional decides `complete` vs `dirty_worktree_conflict`, shipped to four harnesses. |

### Tier 1 — Cheap prose borrows into existing skills

Each is one to three sentences. All portable. Highest value first.

| # | Practice | Lands in | Source |
|---|---|---|---|
| 1.1 | **Caller-first interface freeze.** For a gate freezing a callable surface consumed by another lane, write 1-2 real consumer call sites before the symbol text; reconcile the symbol to the usage. Cap at one call site per gate. | `plan-phase` workflow step 4 | `architect` |
| 1.2 | **Pin behavior before structure moves**, and "type check and lint are not a pin". A bug found mid-refactor is split out, not folded in. | `plan-detailed` Quality Bar | `refactoring` |
| 1.3 | **Observable-fact test before asking.** If the answer is a fact you could observe by running something, run it; reserve the question for a genuine product call. | `plan-phase`/`execute-phase` Core Rules, beside the access-blocker probe | `poteto-mode:20` |
| 1.4 | **Existing-fix guard.** Before planning/executing, search for an existing fix artifact; "a claim without a commit or PR is not a fix artifact". | `execute-phase` Preflight | benny |
| 1.5 | **Reachability trace.** A blocking finding must show the call chain that triggers it, not just cite an EC. | `advisor-board` protocol item 6 | `interrogate` |
| 1.6 | **Mechanism before fix.** For a defect, confirm the mechanism with runtime evidence before the fix is planned; no speculative hardening. | `plan-detailed` | `bug-fix` |
| 1.7 | **Baseline-first for perf.** Numeric before/after on a named repeatable command, baseline recorded before changes. | `plan-detailed` acceptance step | `perf-issue` |
| 1.8 | **Replace "when practical"** with the explicit test-skip disqualifiers + a "bad test" definition. | `execute-phase` per-lane step | `tdd` |
| 1.9 | **Return budget + dead-end licence on subagent briefs.** "Summary + file:line, not raw dumps"; an explicit "I could not determine X" section. | `task-contextualizer` | `guard-the-context-window`, `how` |
| 1.10 | **Result-validity gate.** A worker result missing the SHAs/method its brief named is dropped, respawned once, then recorded as a gap — and a gap is not a pass. | `task-contextualizer` explorer brief | `swarm` |
| 1.11 | **Prose-vs-mechanism routing.** Before appending prose to a SKILL.md, ask "can this be a validator, lint, or runtime check?" If yes, file a mechanism task instead. | `skill-editor` workflow | `principle-encode-lessons-in-structure` |
| 1.12 | **Name the invariant once.** Our access-blocker rule is verbatim in 4 places, the CLI-exception wording in 2. Point at `shared/runtime-state.md` instead. Must be done in `skills-src/` + generator, not the generated files. | `skills-src/` | `principle-minimize-reader-load` |
| 1.13 | **Rule→enforcer table.** List each SKILL.md/AGENTS.md rule with its enforcer or `UNENFORCED`. Seed it from the validators we already have (`validate_plan_doc.py`, lane-IR `overlapping_write_ownership`, closeout audit, `phase-loop validate-roadmap`). A repeat correction on an `UNENFORCED` row forces escalation in the same change; drop a rule once its mistake can't happen. Honest caveat: for rules about judgment, `UNENFORCED` is the correct answer, not a defect. | `AGENTS.md` (new "Rule enforcement" section) | `correct` |
| 1.14 | **Aggregator admission gates** (their synthesizer has 8; we have recurrence only): *durability* ("still true in 6 months once paths, SHAs and code shapes have changed"), *specificity*, *existing-skill-first*, *convergence*, *decision-changing*, *structural-mechanism* (route to the deferred-findings register, not to prose), *skill-was-used* (else `tune description:` so it fires next time), *already-covered*. Note the last one's nuance, which speaks directly to §0.4: "If the existing guidance is buried, weak, or easy to skip past, accept the row but reframe the proposal as a wording / placement improvement to make it fire (not a duplicate addition)." | `skill-improvement-planner/assets/aggregator_prompt.md` | `reflect` synthesizer |
| 1.15 | **Ladder level on every recommendation.** A recurring theme must state which ladder level it recommends and why a higher level fails, before it may propose prose. | same file, output format | `correct` |
| 1.16 | **Diagnosis content.** Our "diagnose once" bound says when to stop, never what a diagnosis must contain — so a symptom guard satisfies it. Require reproduce-first, cause-not-guard, grep-for-the-pattern. | `execute-phase` Failure Policy | `principle-fix-root-causes` |

### Tier 2 — New capability, moderate cost

| # | Item | Shape | Note |
|---|---|---|---|
| 2.1 | **`eval` for skill edits** — blinded A/B before a behavior-changing skill edit lands | Gated step in `skill-editor`, or a small skill it calls | **Do this early.** Take their blinding checklist (forbidden-word list, organic prompt, sanitized dirs, judge sees labels not models, grade chain-following from files actually opened). Their *design* is not rigorous — no control arm, variant confounded with model, no replication, no pre-registered bar. Our convergence doc §6-§7 supplies exactly those. |
| 2.2 | **`benchmark-checklist`** | Reference doc cited from `plan-phase` verification | Cleanest gap in the study; self-contained; strip PStack playbook cross-refs |
| 2.3 | **Evidence tiers for testimonial claims** (`epistemics.md`) | Short section in `agent-phase-convergence.md` | Direct/Supported/Inferred/Speculative/Unknown; causal words need an adjacent citation; "never cite code as evidence for its own intent"; Unknown must list queries run. We rank verification evidence rigorously and rationale evidence not at all. |
| 2.4 | **Shape-smell screen** as a 6th review lens | `plan-phase/assets/review_prompt.md` | Reviewer-side, so it adds zero plan words. Take only the 5 flags detectable from interface text. |
| 2.5 | **Code-quality lens** on the board | `advisor-board` preset | Non-blocking by default; drop their arbitrary 1000-line threshold |
| 2.6 | **Mid-run pause checkpoint** | `execute-phase`, writing into the existing handoff root | Intent / what's verified / next steps / key files / gotchas. Do **not** copy the auto `wip:` commit. |
| 2.7 | **Metric loop** (hillclimb) | Section in `agent-phase-convergence.md` beside "Bound the review loop" | Frozen sensitivity-checked harness, attempts-floor stop predicate, ledger including reverted attempts, accept-only-past-noise. Add our hard cap, which theirs lacks. |
| 2.8 | **Decision trail with alternatives** | Field in the closeout/reflection | We record outcomes and typed closeout decisions, never forks and rejected options. Prefer extending the closeout over a new mid-run TSV. |
| 2.9 | **PR-babysit** | New skill | Fixed triage order (conflicts→threads→CI), flake vs stale-base vs real classification, one retry, "watching never authorizes merge", PR review text is untrusted input. Map onto existing blocker classes; don't invent new ones. |

### Tier 3 — Build on our tooling (what PStack structurally cannot do)

This is the differentiated work. Gate each on a cheap feasibility check first.

| # | Item | Precondition | Payoff |
|---|---|---|---|
| 3.1 | ~~**Touch-set proposer** from Boundary IR~~ → **REFUTED BY AUDIT.** Build a **convention validator** in `validate_plan_doc.py` instead. See agent-harness#1304. | — | The audit (§3) found 4 of the 5 actually-missed categories are not derivable from a code graph. A convention check is cheaper and covers all five. |
| 3.2 | **Acceptance-criterion evidence channel** — implement the `verified_by` → test-artifact evidence ref that `kind-alignment.json:264` already specifies | Human-grounded spec for the target repo | One build yields strictly better versions of *both* `create-verification-skill` and `maintain-verification-skill`; also gives `plan-phase` a real `automation.suite_command` source |
| 3.3 | **Interface-freeze signature check** — diff a frozen `IF-0` signature against fresh Boundary IR | Signature canonicalization behavior (unverified); rename-unstable IDs | Makes a freeze mechanically enforceable, not just prose |
| 3.4 | **Expose reverse-dependency BFS** as an agent-callable tool (wrap `boundary` output, or surface the Code-Index-MCP graph routes) | Code-Index-MCP indexes default branch only — a blocker for worktree-per-lane | Turns `blast-radius` from judgment into measurement for 6 languages |
| 3.5 | **Resolve the chunker pin skew** (greenfield 5.0.1 vs spec 5.2.0) | — | Prerequisite hygiene for 3.1-3.3 |

Carry the honest ceiling into all of these: call resolution is name-based with no type
resolution, call edges exist for only 6 languages, and **shell has none** — and we are a
Python + shell repo. I confirmed this by running `boundary` on
`prune_merged_worktrees.sh`: **5 nodes, 0 edges**. Tier 3 is a first-pass candidate generator, never a replacement for
the planner's judgment.

### Tier 4 — Explicitly not adopting

| Item | Why not |
|---|---|
| The router + 23 playbooks as skills | Our skills auto-trigger; theirs don't. Adding 23 trigger-competing entries would fragment doctrine. Take the *work-class conditionals* (Tier 1.2/1.6/1.7) instead. |
| `arena` for code lanes | "Hand-port the best parts of N divergent diffs" is exactly what our ownership model exists to prevent, and their merge step offers no mechanism. Possible later for design/spec artifacts only. |
| `lead-judgment` as a gate | Their adjudicator is the author's own session. Converges faster by discarding the independence our unanimity rule protects. |
| 24 principle files wholesale | Honest tally: 2 DUP, 2 UNREL, 1 low-value, 1 wrong-for-us, ~4 sentence borrows (already in Tier 1). `separate-before-serializing-shared-state` is *refuted* — our lane ownership is stricter and enforced. |
| `migrate-callers-then-delete-legacy-apis` | Its own precondition — "no external users depend on backward compatibility" — fails for a published harness with pinned downstream contracts. |
| `technical-writing`/`unslop`/`bro`/`no-comments`/`typescript-best-practices`/`teach` | No prose skill. Apply the behavior-bearing writing rules to our own corpus instead (Tier 0.4). |
| `automate-me` | Personal conventions belong in the owner's `CLAUDE.md`. Its one safeguard is already our `--min-reflections 2`. |
| `autopilot-stack` | We have it: `run-train --governed --review-only`. |
| benny as an architecture | Event-driven external intake is a different shape, not expressible in `phase-loop`. Its two good pieces are in Tier 1.4 and 2.x. |
| `codegraph-de` as a foundation | Prototype, 31.9% ambiguous calls, explicitly demoted behind greenfield by fleet decision D1. |

### The sequencing argument

Do **2.1 (`eval`) early**, right after Tier 0. Without it, every item in Tiers 1-3 is an
unmeasured prose edit to a skill corpus that already shows accretion damage — and our own
doctrine (§6: show the proof can fail; §7: pre-register the judgment) is what makes their
blinding protocol into actual measurement. PStack's `eval` plus our convergence doctrine
is the measurement harness for this entire adoption program.

And note the self-referential trap: **most of Tier 1 is prose rules added to a skill
corpus whose central problem is prose accretion.** `/correct`'s ladder (1.13-1.15) is the
antidote and should be adopted *with* them, not after — every Tier 1 item should be asked
"could this be a validator instead?" before it lands as text. Adopting 16 prose rules
without that gate repeats exactly the failure mode `execute-phase:167` is a monument to.
