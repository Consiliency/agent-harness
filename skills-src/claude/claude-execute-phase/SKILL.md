---
name: claude-execute-phase
description: "Claude Code executor for a claude-plan-phase lane plan. Uses TeamCreate, worktree-isolated teammates, lane DAG ordering, verification gates, and retry-once failure handling."
---

# claude-execute-phase

## Runtime State

For reflections, handoffs, and latest handoff pointers, follow `claude-config/shared/runtime-state.md`. This repo/branch/run-isolated contract supersedes any older flat closeout examples retained for historical context in this skill.

`shared/phase-loop/protocol.md` is the canonical shared contract for the
`automation:` object, `verification_status`, frozen blocker taxonomy,
manual event import, and downstream roadmap-amendment handling.

When launched by the live phase-loop adapter, this skill runs through
non-interactive `claude -p`; its final reply must still emit the shared
`automation:` closeout or the parent runner will reduce the turn to
`repeated_verification_failure` rather than silent success. The repo-injected
workflow bundle remains authoritative whether the adapter delivers it inline or
through the run-local context-file fallback.
That repo-owned bundle includes the full Claude workflow pack
(`claude-phase-roadmap-builder`, `claude-plan-phase`,
`claude-execute-phase`, and `claude-phase-loop`) and does not depend on
installed bridge skills under `resolve_skill_bundle_root("claude")/`.

Claude closeout and blocker reporting must use the shared literals directly,
including `dirty_worktree_conflict`, and must treat older downstream plans as
stale after a roadmap amendment.

## Runner-Owned Lane Work Units

Injected HARNESSLANE runs may include a `HarnessLaneAssignment` from
`shared/phase-loop/protocol.md`. Treat that assignment as the work-unit
contract: execute only the selected `lane_id`, write only the listed
`owned_files`, treat `consumed_interfaces` as read-only, and emit one shared
`automation:` closeout for that work unit. Installed-skill drift is
warning-only when the repo-injected context is present.

Native Claude subagent and `agent_team` activity stays internal unless it emits
a typed `DelegationRequest` and the runner approves it. Review, reducer,
verify, and closeout prompts are distinct from implementation prompts. If the
selected policy is unsupported by the active harness, stop with a typed
non-human blocker instead of silently downgrading.

## Phase-Loop Adapter Mode

When the prompt or run-local context file starts with a concrete
`claude-execute-phase <plan>` command from `.codex/phase-loop/runs/`, this
adapter mode overrides the orchestrator-only interactive workflow below.

- Do not read installed handoffs under `resolve_skill_bundle_root("claude")/**`; the run-local
  context and the plan artifact are the only predecessor context.
- Do not call `ToolSearch`, `TaskCreate`, `TaskUpdate`, `TaskList`,
  `TeamCreate`, `TeamDelete`, `Agent`, `SendMessage`, `EnterWorktree`,
  `ExitWorktree`, or `AskUserQuestion`.
- Do not create `.claude/worktrees/` or lane branches. Execute the plan
  directly in the provided workspace, respecting the plan's owned-file
  boundaries and running the narrowest applicable verification commands.
- Treat ignored, private, raw-data, credential, and evidence-source files as
  read-protected unless the run-local context, phase plan, or source bundle
  explicitly allowlists the exact path or glob for read access. Do not infer
  permission from nearby owned output paths, old memory, or prior phases.
- Do not read or write `~/.claude/**` reflection or handoff files, and do not
  edit `.codex/phase-loop/` runner artifacts. Adapter-mode closeout happens
  only through stdout plus repo-local artifacts.
- If a missing script or unavailable helper is nonessential, replace it with a
  direct repo-local check and record the substitution in the closeout. If the
  missing input is essential, stop with a shared blocked `automation:`
  closeout.
- If ambiguity, access, dirty-state, or merge safety handling would normally
  ask a user, stop and emit a shared `automation:` closeout with
  `status: blocked`, `human_required` set accurately, the frozen
  `blocker_class`, concrete `blocker_summary`, and `verification_status:
  blocked`.
- End stdout with one shared `automation:` closeout. Do not wait for
  interactive approval after verification is complete.
- Do not emit a `/clear` recommendation or any human-only context-reset
  instruction. Continuity to the next phase is the run-local handoff plus the
  runner re-invoking the next phase in a fresh executor process — that fresh
  process is the context reset. There is no human in this loop to reset it.
- Before that closeout, run `git status --short` and classify dirty paths
  against the active plan's owned files and control artifacts. If a generated
  path is unowned or derived from unauthorized raw/private inputs, stop with
  `dirty_worktree_conflict` instead of reporting completion. For IGNORED paths do
  not judge by hand: run the closeout audit, `phase-loop-closeout-audit --repo . --record-outputs --phase "<ALIAS>"` (module form `python -m phase_loop_runtime.closeout_classifier --repo . --record-outputs --phase "<ALIAS>"` only when the package is on the ACTIVE python's path); replace `<ALIAS>` with the alias of the phase you are executing, exactly as your plan and runner prompt name it.
  Pasted unchanged it is still valid shell; `--phase` matters only in a repo that commits `.phase-loop-generated-outputs.json`, and there an unsubstituted `<ALIAS>` records and accepts nothing, so the closeout audit blocks.
  The closeout audit's last output line (`action: exit N ... -> ...`) states the required action; follow it. A runtime that predates that line gets the same mapping from its exit code:
    - exit 0 (every ignored path was produced by the runner or its own toolchain -- `.phase-loop/**`, pytest/Ruff caches, `__pycache__`, egg-info, `.venv` -- is a harness handoff, or was written by a producer the committed `.phase-loop-generated-outputs.json` declares, re-run and recorded by `--record-outputs`, agent-harness#1139): ignored paths are not a blocker and must never block a verified owned diff (agent-harness#670); the rest of closeout still decides the terminal status.
    - exit 1 (unknown ignored outputs): stop with `dirty_worktree_conflict`.
    - exit 2 (probe failed): stop with `dirty_worktree_conflict`.
    - any failure to run the audit at all (command not found on a pinned runtime that predates it, non-zero for any other reason): stop with `dirty_worktree_conflict` -- inability to measure is never evidence of a clean tree.

  Precedence: when required verification passed and the ONLY uncommitted paths
  are phase-owned outputs this run was not authorized to commit, report
  `awaiting_phase_closeout` and let the runner's graduated closeout gate commit
  them — reserve `dirty_worktree_conflict` for unowned paths, ignored paths the
  closeout audit typed as unknown, or overlapping-unrelated paths.

Follow-on executor for `/claude-plan-phase`. Consumes the plan doc + TaskCreate'd lane tasks and drives them to completion: root lanes first, parallel lanes in parallel, auto-merge on green, retry-once on failure, halt-all on second failure.

## When to use

- `/claude-plan-phase` has produced `plans/phase-plan-<VERSION>-<PHASE_ALIAS>.md` and a `TaskCreate`'d task per lane.
- You want the phase executed **full-auto** end-to-end, with lanes merging to the current branch as their gates go green.
- The working tree is clean and you're on the branch lanes should merge into.

## When NOT to use

- Plan doc has never been produced → run `/claude-plan-phase` first.
- You want human checkpoints between lanes → execute lanes manually (`Agent(isolation: "worktree", name: "<SL-ID>")` with the lane's section pasted in).
- The plan doc's DAG has cycles or a lane's owned files overlap another lane's → fix the plan first.

## Model tiers (edit on Anthropic releases)

Model IDs appear only in this table. All model-routing logic in the workflow references the tier name.

| Tier      | Model              | Use for                                                       |
|-----------|--------------------|---------------------------------------------------------------|
| frontier  | claude-opus-5      | retry escalation ceiling, highest-stakes lanes                |
| strong    | claude-sonnet-5    | contract-authoring (IF-freeze), schema/migration, algorithmic |
| fast      | claude-haiku-4-5-20251001 | mechanical wiring, small components against frozen types |

This skill's retry-tier ladder is `fast → strong → frontier`. The default `run_mode` is `autonomous`: no panel and
no `human_required`. Tier-to-model-class mapping and the governed (`--governed` / `PHASE_LOOP_RUN_MODE=governed`) pre-merge
panel loop: [references/lane-dispatch.md](references/lane-dispatch.md#model-classes-and-governed-mode);
governed runs read it before each panel round. Never merge with a blocker waived.

## Inputs

| Arg | Required | Meaning |
|---|---|---|
| `<plan-path>` | no | Path to plan doc. Default: auto-detected via env vars + filename convention. |
| `--dry-run` | no | Parse + validate, print the dispatch schedule with per-lane model assignments, do not spawn teammates. |
| `--resume` | no | Continue a partially executed plan: skip lanes already merged (their merge commit is on the target branch and their produced gates are closed). |

Both modes: if a test needs a browser (Playwright, `claude-in-chrome`), read [browser setup](references/merge-and-verify.md#browser-verification) at plan intake, before implementation or lane dispatch; brief affected lanes on it.

## Workflow (orchestrator-only main thread)

The main thread reads exactly two things: the plan doc and the TaskList. It does not Grep/Read repo source — lane teammates own their files. If the main thread is reaching for Grep or Read on source files, the teammate brief was incomplete; re-brief via `SendMessage`.

### Interactive steps

Read each step's reference at that step; none is preloaded.

- Setup (environment variables, expected helpers, deferred tool preloading), teamwork posture (hard rules), Step 0 predecessor handoff, Step 1 resolve and parse the plan, Step 2 preflight (`scripts/verify_harness.sh`), Step 2.5 baseline capture, Step 2a worktree hygiene: [references/interactive-steps.md](references/interactive-steps.md).
- Step 3 model and thinking per lane, Step 4 TeamCreate, Step 5 dispatch loop and teammate brief, plus the lane state machine, parallelism contract, model selection quick-reference: [references/lane-dispatch.md](references/lane-dispatch.md).
- Steps 6–9 (gates, leakage check, auto-merge, retry-once, final verification), pruning, output contract, layout: [merge-and-verify](references/merge-and-verify.md).
- Interactive only, before the first commit: early draft PR and the publication-mode check before each push or PR command, [references/interactive-path.md](references/interactive-path.md); PR text, [PR descriptions on the interactive path](#pr-descriptions-on-the-interactive-path).
- Step 9.5 close-out (artifact staging, next-step routing, path resolution, reflection and handoff templates): [references/closeout-reflection-handoff.md](references/closeout-reflection-handoff.md).

### Step 2 — Merge-target safety gate

Before any lane dispatch or merge: if the resolved merge
target is `main` or a protected branch, STOP — do not dispatch lanes or run any
`git merge` onto it. Interactive: check out / create a dedicated feature branch first and
re-resolve the merge target; runner/adapter: the runner resolves a runner-managed branch.
This gate precedes Step 7's auto-merge, which would otherwise mutate `main` directly.

### Step 9.5 — After the reflection and handoff are written

Write the reflection and handoff per [references/closeout-reflection-handoff.md](references/closeout-reflection-handoff.md).
After both files are written, **in the interactive TUI path only** (a human is
driving), print to the user:

> Phase `<alias>` complete. `<N>` lanes merged; final verification `<pass|fail>`.
> Reflection saved to `<REFLECTION_PATH>`.
> Handoff written to `<REPO_LOCAL_HANDOFF>`.
> Artifact state: `<staged|tracked|modified|unstaged|blocked>`.
>
> Next phase: `<next alias - status|none - reason>`.
> Next command: `<exact command or none - reason>`.
> Recommended next step (interactive only): either run `/clear` to reset your
> context window and then invoke the next command above, **or** dispatch a fresh
> subagent (Task/Agent) to carry the next phase in clean context when this loop
> is skill/tool-driven. The next skill reads the handoff automatically.

`/clear` is a human-operated reset and applies only to the interactive TUI path
above. **Do not emit it in Phase-Loop Adapter (autonomous) mode** — an
autonomous loop has no human to run it and cannot clear its own context. Continuity there is
the written handoff (see "Phase-Loop Adapter Mode" above).

Use `phase_loop_runtime.skill_paths` resolver helpers for harness skill roots, handoff roots, helper roots, and reflection roots.


## Runner Verification Evidence

Before reporting a successful closeout, require the runner-owned verification artifact. The closeout must name `verification_artifact_path`, quote the artifact summary line, and must not report `verification_status=passed` unless that artifact exists and supports the executed work. Treat dependency-manifest install refresh and the full suite before closeout as runner-enforced expectations, not optional narrative checks. A blocked gate may be re-verdicted only by rerunning the originally specified runner check; proxy evidence requires a roadmap or plan amendment before the verdict changes. A prior run's terminal-summary is authoritative for reconcile-or-skip only when that closeout was accepted; a rejected or blocked prior closeout — regardless of any self-reported `complete`/`passed` — must not be reconciled against. On a re-run, re-do and re-verify the phase work from scratch rather than skipping on a stale summary.


## Spec Delta Closeout

Before final closeout, choose exactly one `spec_delta_closeout.v1` decision: `no_spec_delta`, `roadmap_amendment`, `canonical_spec_update`, `governed_pipeline_refresh`, `mirror_cutover_required`, `dotfiles_skill_source_update`, or `human_source_judgment_required`. Cite metadata-only evidence paths such as the active plan, lane closeouts, targeted pytest output, and `git diff --check` output. Preserve the phase plan's target surfaces and `redaction_posture=metadata_only`; do not include raw specification bodies, raw patch bodies, credentials, provider-supplied payloads, local environment values, or evidence-source contents. Missing or malformed spec-closeout evidence is a repairable automation blocker with `blocker_class=contract_bug` unless the decision is `human_source_judgment_required`.

## Closeout

In the closeout, handoff, and final response — and in any PR/issue body or commit message this run writes — reference issues and PRs as `repo#N` (or `owner/repo#N`), never a bare `#N`; the fleet is multi-repo, so a lone number is ambiguous.

### Manifest lifecycle

After plan validation and before lane execution, perform a best-effort `plan-manifest append` lifecycle update through `phase_loop_runtime.plan_manifest.update_lifecycle` to mark the matching `type=phase` entry `executing` with run metadata. During closeout, update the same entry to `completed` or `failed` with verification metadata, reflection metadata, produced-gate metadata, `if_gates_produced`, and dirty-worktree summary fields as available.
A `completed` phase update must also include explicit `issue_inventory` and matching `issue_dispositions` arrays, including explicit empty arrays when no issues were enrolled.
`if_gates_produced` must list only the IF gates the active phase produces per its own plan; never carry a prior phase's gate forward into this phase's closeout.
Manifest lifecycle failures are non-fatal during the dual-mode window: emit a ledger warning, mention the warning in the mandatory reflection, and preserve the existing phase closeout JSON, verification, and dirty-worktree behavior.

Closeout payload shape is defined by `EmitPhaseCloseout` in `phase_loop_runtime/baml_src/emit_phase_closeout.baml` (if that path is absent in the checkout, use the operator/prompt-supplied field contract or the installed `phase_loop_runtime` package — the missing vendored BAML source is not a blocker); keep skill text focused on value selection and handoff routing, not duplicated field ceremony.

Before final response, write a reflection for every non-trivial run. Write it to `resolve_skill_bundle_root("codex")/claude-execute-phase/reflections/<repo_hash>/<branch_slug>/<run_id>.md`. The reflection must include `## Run context` with skill name, ISO timestamp, repo, branch, commit, and artifact path if any, followed by `## What worked`, `## What didn't`, and `## Improvements to SKILL.md`. skip only when no artifact was produced AND no decision was made AND the run was pure inspection.


## Publication mode

After verified phase work, select exactly one of three modes. **Default to (a) unless a
clear interactive signal is present** — a run missing BOTH the adapter prompt prefix AND
`PHASE_LOOP_RUN_MODE` is AMBIGUOUS and MUST be treated as (a) (fail safe toward the runner).

- (a) Runner-managed closeout (incl. governed mode), OR ambiguous mode. If this is the
  phase-loop adapter (the prompt begins with `<harness>-execute-phase <plan>` from a
  pipeline run dir), or `PHASE_LOOP_RUN_MODE` is set (autonomous/governed), OR neither
  interactive signal is clearly present, the RUNNER owns closeout and commit. Do NOT
  independently publish — defer entirely to runner closeout (`awaiting_phase_closeout` /
  runner commit). Publishing here would bypass the governed pre-merge review panel.
- (b) Interactive orchestrator on a clean, non-protected feature branch (a clear
  interactive signal, and the merge target passed the merge-target safety gate): publish as
  [references/interactive-path.md](references/interactive-path.md) says, and follow [PR descriptions on the interactive path](#pr-descriptions-on-the-interactive-path).
- (c) Merge target is `main` or a protected branch. Already STOPPED at the merge-target
  safety gate before any lane merge — never merge lanes onto `main`/protected. Re-target a
  feature branch or take explicit instruction.

## PR descriptions on the interactive path

Before creating or refreshing an agent-owned PR, read `references/pr-writing.md`
from the installed `claude-execute-detailed` directory, located with
`resolve_skill_bundle_root("claude")`. Draft text identifies pending work and verification.
Create with an explicit title and `--body-file`; before readiness, reassess the title
and body against the final PR diff and current verification artifact, then update
with `gh pr edit <pr> --body-file <file>`. Ownership is this session's created PR,
recorded by URL in its repository-matching handoff. Read `gh pr view <pr> --json title,body`
before composing and again immediately before editing. Preserve human additions and
machine-readable trailers; replace only the unchanged delimited agent block. On
concurrent change, append to the latest body. Add `--title` only if the title still
equals this session's last authored title; preserve a human-changed title.
A failed pre-readiness update leaves the initial PR in draft. For an already-ready
PR, report `description refresh failed`, identify it, and do not claim freshness
or proceed to merge; a failed edit does not change its draft status.

Repeat the reassessment after material implementation, verification, or comparison-base
changes before merge; refresh stale agent-owned text through the same mode check.
This is description upkeep, not a new advisor round or merge authorization. Runner
and broker-owned descriptions remain with their publication owner.
