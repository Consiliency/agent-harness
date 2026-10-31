# claude-execute-phase — lane assignment and dispatch (Steps 3–5)

Reference for `claude-execute-phase` (linked from its `SKILL.md`). Read it before assigning models and dispatching lanes.

## Contents

- Step 3 — Assign model + thinking per lane
- Step 4 — TeamCreate
- Step 5 — Dispatch loop
- Lane state machine
- Parallelism contract
- Model selection quick-reference
- Model classes and governed mode

## Step 3 — Assign model + thinking per lane

Each lane gets a model and thinking level matched to its complexity. The assignment is encoded on the `Agent` call via `model:` and communicated as guidance in the brief.

Apply in order, first match wins:

1. Lane has `Execution hint: <tier>/<thinking>` inside its `### SL-N` section → use it verbatim.
2. Lane publishes any `IF-0-*` gate (contract-authoring) → `strong` / high. Downstream lanes depend on the symbols being correct.
3. Lane scope mentions migrations, schema, or SQL → `strong` / high. Bad migrations are expensive to unwind.
4. Lane scope mentions algorithmic/computed logic AND has tests as first task → `strong` / medium.
5. Lane owns >10 files AND publishes no interfaces (wiring / mechanical refactor) → `fast` / low.
6. Lane implements small components against already-frozen types → `fast` / low.
7. Default fallback → `strong` / medium.

Resolve tier → model from the Model tiers table in `SKILL.md` and pass the concrete model ID to `Agent(model: …)`.

**Retry escalation** (after a lane's first failure):

- `fast` → `strong`
- `strong` → `frontier`
- `frontier` → stay at `frontier`
- Thinking level bumps up one tier (`low → medium → high`).

`Agent` does not expose a direct thinking-level parameter — convey it in the brief's framing (e.g., "Think carefully before editing shared type definitions" vs "These are mechanical edits; move quickly").

## Step 4 — TeamCreate

**Preflight (before any `Agent` or `TeamCreate` call).** Flush inherited team context from a predecessor skill run via `TeamList` (or a defensive `TeamDelete`). On the error signature `"already leading team X"`, `TeamDelete` the stale team and retry with a repo-scoped suffix — e.g., the short hash of `$(git rev-parse --show-toplevel)` — to prevent cross-project team-name collisions. Same-aliased phases from different repos collide on the global team namespace without a suffix. Error signature `"Team X does not exist"` on `TeamDelete` is a no-op; proceed.

Create one team for the phase:

- **Team name**: `phase-<PHASE_ALIAS>` (e.g., `phase-p1`), with repo-scoped suffix appended when collision is detected.
- **Teammates**: one per lane, `subagent_type: "general-purpose"`. Teammate names use the allocator — see Step 5.

TeamCreate registration enables `SendMessage` retry rounds without fresh Agent spawns.

## Step 5 — Dispatch loop

State per lane: `pending | running | verify-ok | merged | failed`. State per gate: `open | closed`.

Repeat until all lanes are `merged` or halt is triggered:

1. **Find ready lanes** — `pending` lanes whose upstream lanes are all `merged` AND all consumed `IF-0-*` gates are `closed`. Synthesized artifact writer lanes are ready only after every producer lane named in `Interfaces consumed` is merged. Cap the dispatch batch at `EXECUTE_MAX_PARALLEL_LANES` (default 4). Slice the eligible set to the first N (lower SL-ID first) and queue the rest.

2. **Allocate worktree names**. For each ready lane, run `scripts/allocate_worktree_name.sh <sl-id>`. Substitute the emitted name (e.g., `lane-sl-1-20260418T144536-nxz5`) into both `Agent(name=…)` and the briefed `EnterWorktree(name=…)`. Bare `lane-<sl-id>` names collide under rapid dispatch.

3. **Dispatch in parallel** — single message with one `Agent(team_name: "phase-<alias>", name: "<allocated-name>", subagent_type: "general-purpose", model: "<assigned>")` call per ready lane. Sequential dispatch within a wave is a bug. Do NOT pass `isolation: "worktree"` when `team_name` is set — the harness drops `isolation` in that combination. Use `team_name` for coordination + teammate-called `EnterWorktree` for filesystem isolation.

4. **Teammate brief** contains:
   - **Worktree isolation (mandatory, first tool call)**: Load `EnterWorktree` via `ToolSearch(query="select:EnterWorktree,ExitWorktree")` if not already in the tool registry. Call `ExitWorktree(action="keep")` FIRST (no-op if no session active; clears any stale session-state flag inherited from a prior teammate). Then call `EnterWorktree(name: "<allocated-name>")` as the very next tool call, BEFORE any file operation. Every subsequent edit/commit goes into that worktree. At the end, call `ExitWorktree(action: "keep")` so the worktree and branch remain available for the orchestrator to merge.
   - The full `### SL-N` section copied verbatim from the plan doc.
   - **Architecture context** (1–2 sentences): how this lane fits the phase; how this phase fits the roadmap.
   - **Related files** the lane reads but does not own: type defs, test fixtures, shared config. Distinct from `Owned files`.
   - Concrete upstream artifact paths (populated from now-merged upstream lanes) for every entry in `Interfaces consumed`.
   - The merge target branch and the orchestrator's current tip SHA, injected as `<TIP_SHA>` (used by the stale-base check below).
   - The lane's test → impl → verify task list. The lane's verify command must include regression files listed in the plan's `## Verification` section that reference this lane's owned files, not only the lane's new tests. Each lane must enumerate tests that mock or stub any existing public function the lane's scope adds a call to, and include those tests in verify.
   - Thinking-level guidance matching the lane's profile.
   - **Browser setup**, when the lane's tests need a browser: the obligations from [Browser verification](merge-and-verify.md#browser-verification), including adding a missing Playwright config in the lane rather than deferring the test.
   - **Stale-base discipline**: AFTER `EnterWorktree` returns and BEFORE any code change, run `git rebase main` (or `git merge main --no-ff -m "merge: incorporate prior-lane foundation"`). Verify with `git merge-base --is-ancestor <TIP_SHA> HEAD && echo OK || echo STALE`. Repeat the rebase immediately before your final commit. On conflicts, STOP and report — do not resolve silently. Never `git reset --hard` or `git checkout HEAD~N -- …` in a stale worktree; this destroys peer-lane work on `--no-ff` merge.
   - **Staging discipline**: Forbid `git add -A` and `git add .`. Stage with explicit pathspecs drawn from the lane's `Owned files`.
   - **No self-merge**: DO NOT run `git merge` or `git push` against the merge-target branch yourself; the orchestrator owns merges.
   - **Structured-reply instruction**: "When done, reply with JSON `{lane, verify_exit_code, failed_tasks, pre_existing_failures, tsc_error_delta, notes, commit_sha, branch, worktree_path}`. `failed_tasks` lists failures attributable to this lane; `pre_existing_failures` lists failures reproducible on the base SHA (capture the base-SHA reproduction command as evidence). When the lane's verify chain runs whole-repo type-checking, populate `tsc_error_delta` (errors-after minus errors-before); accept `tsc_error_delta <= 0` as a pass even if raw exit code is non-zero. `branch` and `worktree_path` come from `EnterWorktree`'s return value."

   Apply the `/claude-task-contextualizer` checklist to every brief.

5. **Await completions**. For each:
   - `verify_exit_code == 0` → run gate verification (Step 6). On green → auto-merge (Step 7). Mark lane `merged`, flip produced gates to `closed`, update the lane's `TaskCreate`'d task to `completed`.
   - Non-zero or gate failure → retry-once (Step 8).
   - **Idle without JSON reply** → handle per the decision table below. After one `SendMessage` retry with no response in a reasonable interval, escalate directly to SHA-discovery rather than continuing to ping.

     | Case | Condition | Action |
     |---|---|---|
     | (a) | Idle + no commits | `SendMessage` one nudge requesting commit + envelope. |
     | (b) | Idle + commit on identifiable lane branch | Treat the commit as the result; run Step 6.5 / Step 7 audits; proceed on `CLEAN`. |
     | (c) | Idle + multiple candidate commits | One more `SendMessage`; if no response, halt for user. |
     | (d) | Idle + commits landed on merge-target directly | Route to `PARENT_ON_MERGE_TARGET` verdict (Step 6.5). |

6. Persist lane + gate state to `.claude/claude-execute-phase-state.json` after every transition (enables `--resume`).


## Lane state machine

```
pending ──► running ──► verify-ok ──► merged
                 │                        ▲
                 └─fail─► failed ─retry─►─┘ (once)
                                 │
                                 └─fail2─► HALT
```

## Parallelism contract

- All lanes whose dependencies are satisfied at the same time MUST be dispatched in the same message (parallel `Agent` tool calls), up to `EXECUTE_MAX_PARALLEL_LANES`.
- Lanes must not share files. The plan's lane-validation checklist guarantees disjoint ownership; claude-execute-phase trusts the plan and does not re-verify file-glob intersections.
- Shared generated files (e.g., barrel index files, generated types) are called out in the plan's `## Execution Notes`; only the lane that lists them under `Owned files` may modify them.

## Model selection quick-reference

| Symptom in the plan doc | Assigned tier | Thinking |
|---|---|---|
| `Scope` mentions schema / migration / SQL | `strong` | high |
| `Interfaces provided` includes any `IF-0-*` gate | `strong` | high |
| `Scope` mentions algorithm / compute / worker logic | `strong` | medium |
| `Owned files` glob expands to >10 files, no interfaces provided | `fast` | low |
| `Scope` is "small components against frozen types" | `fast` | low |
| `Execution hint:` line is present in lane section | Use it verbatim | Use it verbatim |
| Retry | One tier up | One tier up |

Resolve tier names to model IDs via the Model tiers table in `SKILL.md`.

## Model classes and governed mode

The tiers in [Model tiers](../SKILL.md#model-tiers-edit-on-anthropic-releases) map to the runtime `model_class` axis: implementer = strong, worker = fast.
(The planner class routes to the heavy model `claude-opus-5` — the same model as
`frontier`. The reviewer class routes to the ULTRA model `claude-opus-5-5`, a
review-tier model above that execute table.) The shipped `model_policy` dispatches **implementation at the
implementer class**. The runtime's `model_class`-escalation bookkeeping is
runner-internal and is NOT applied to the launched model — see
`governed_premerge.next_escalation` / `runner.py` for its current status. This
skill's own retry-tier ladder is `fast → strong → frontier`.
The default `run_mode` is `autonomous` — no panel,
no `human_required`; every governed escalation terminal is a non-human
`review_gate_block` surfaced in the run-end summary, never a synchronous human
wait.

Governed mode is **live on the serial path** (`--governed` / `PHASE_LOOP_RUN_MODE=governed`,
model-routing-v2): a pre-merge panel gate (codex + gemini) reviews the
implementation diff *before* the closeout commit and runs a bounded
review→fix→re-review loop. The runtime re-runs the full panel every round and
stops at `max_rounds` (`governed_premerge.DEFAULT_MAX_REVIEW_ROUNDS`); it
performs no delta review and no descope itself. A `block` finding holds the
merge until fixed; if one still stands when the loop stops, the terminal is a
non-human `review_gate_block` with `mergeable=False` — the loop ending never
releases the merge. The agent applies the review-round rules from the
advisor-board skill to what that loop returns: let every seat finish before
fixing, fix once per round, and treat a finding as blocking only when it cites
what it breaks under that skill's rule 3 (the citation classes are defined
there, not here). At the cap, descope by removing the scope that carries the
blocker and leaving its goal unclaimed; a blocker that cannot be removed with
its scope halts the phase for the operator — never merge with a blocker
waived. Autonomous runs spawn no panel. Concurrent-wave dispatch is not
governed yet.
