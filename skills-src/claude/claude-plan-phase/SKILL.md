---
name: claude-plan-phase
description: "Claude Code phase planner for a versioned roadmap phase. Produces an interface-freeze + swim-lane document for parallel execution. Use in plan mode. Supports --consensus for multi-agent architectural consensus across named Plan teammates."
---

# claude-plan-phase

## Runtime State

For reflections, handoffs, and latest handoff pointers, follow `claude-config/shared/runtime-state.md`. This repo/branch/run-isolated contract supersedes any older flat closeout examples retained for historical context in this skill.

`shared/phase-loop/protocol.md` is the canonical shared contract for
execution-ready plan metadata, including `phase_loop_plan_version: 1`,
`roadmap_sha256`, optional `Dispatch Hints`, and downstream roadmap-amendment
rules.

When this skill runs through the live phase-loop adapter, the child launch is a
non-interactive `claude -p` session and the final response must still include a
shared `automation:` closeout with `verification_status`. The repo-injected
workflow bundle remains authoritative whether the adapter delivers it inline or
through the run-local context-file fallback.
That repo-owned bundle includes the full Claude workflow pack
(`claude-phase-roadmap-builder`, `claude-plan-phase`,
`claude-execute-phase`, and `claude-phase-loop`) and does not depend on
installed bridge skills under `resolve_skill_bundle_root("claude")/`.

## Phase-Loop Adapter Mode

When the prompt or run-local context file starts with a concrete
`claude-plan-phase <roadmap> <phase>` command from `.codex/phase-loop/runs/`,
this adapter mode overrides the delegation-first interactive workflow below.

- Do not read installed handoffs under `resolve_skill_bundle_root("claude")/**`; the run-local
  phase-loop context is the only predecessor context.
- Do not call `ToolSearch`, `TaskCreate`, `TeamCreate`, `TeamDelete`, `Agent`,
  `SendMessage`, `ExitPlanMode`, `advisor()`, or `AskUserQuestion`.
- Resolve the roadmap and phase from the first command line, read only the
  repo-local roadmap and relevant files, and write the repo-local
  `plans/phase-plan-<VERSION>-<PHASE_ALIAS>.md` artifact directly.
- The plan artifact frontmatter is part of the trust contract. `roadmap:` MUST
  be the exact repo-relative path from repo root to the roadmap file, not a
  shortened basename or suffix, and `roadmap_sha256:` MUST be the SHA-256 of
  that exact roadmap file.
- Do not read or write `~/.claude/**` reflection or handoff files, and do not
  edit `.codex/phase-loop/` runner artifacts. Adapter-mode closeout happens
  only through stdout plus repo-local artifacts.
- If ambiguity, access, dirty-state, or missing-input handling would normally
  ask a user, stop and emit a shared `automation:` closeout with
  `status: blocked`, `human_required` set accurately, the frozen
  `blocker_class`, concrete `blocker_summary`, and `verification_status:
  blocked`.
- End stdout with one shared `automation:` closeout. Do not wait for
  interactive approval after the artifact is written.

## Dispatch Hints

When non-default executor policy is needed, add an optional `## Dispatch Hints`
section using the frozen vocabulary from `shared/phase-loop/protocol.md`
instead of inventing Claude-only plan metadata.

When model, effort, work-unit defaults, lane-specific policy, fallback, policy
source, or override reason must also be frozen, add optional `## Execution
Policy` using the protocol syntax. Precedence is CLI/operator override,
phase-plan policy, roadmap policy, `Dispatch Hints`, then registry defaults;
silent downgrade is forbidden unless explicit fallback or default inheritance
is recorded.

## Model & Effort Tiering (right-size per lane, don't default to the ceiling)

The runtime resolves one planning model per executor, so reasoning effort is the primary cost dial (`minimal` < `low` < `medium` < `high` < `xhigh` < `max`). Default each lane to the cheapest effort you believe will succeed, escalate only with a stated reason, and record the choice in an `## Execution Policy` section. Two parser rules fail the whole section when broken: lane selectors are numeric lane ids (`SL-3`, or `lane <name>:` for other names), and a `reason=` value contains no commas. The registry defaults, an example section, `model_class` and run mode are in [references/model-effort-tiering.md](references/model-effort-tiering.md).

## Planner Literal Validation

Before writing a plan document to the project path, validate the complete draft
with `phase_loop_runtime.planner_validation.validate_plan_dispatch_hints`. In
Plan Mode, run this after the scratch draft is fully emitted and before
`ExitPlanMode`; in adapter/default flows, run it before writing
`plans/phase-plan-<VERSION>-<PHASE_ALIAS>.md`. If findings are returned, do not
write the plan artifact. Stop with a validation_failed closeout:
`terminal_status=blocked`, `verification_status=blocked`,
`blocker_class=contract_bug`, `human_required=false`, and a non-secret
`blocker_summary` listing each finding's `field_path`, `literal`,
`allowed_values`, and `suggested_fix`.

The validator imports its defaults from `phase_loop_runtime.models`:
`DISPATCH_CAPABILITIES`, `EXECUTORS`, and `PRODUCT_LOOP_ACTIONS`. Keep these
allowed values inline in the planner prompt so invented literals are visibly
out of contract:

- `dispatch_hints.required_capabilities`: `live_launch`, `dry_run`, `skill_bundle_injection`, `inline_instructions`, `context_file_instructions`, `manual_handoff`, `subagents`, `explicit_approval_controls`, `structured_output`, `browser_automation`
- `dispatch_hints.executors[]`: `codex`, `claude`, `gemini`, `opencode`, `pi`, `command`, `manual`
- `## Execution Policy` selectors: `work-unit defaults`, `roadmap`, `plan`, `execute`, `repair`, `review`, `maintain-skills`, and lane selectors such as `SL-2`
- `terminal_status`: `unplanned`, `planned`, `executing`, `executed`, `awaiting_phase_closeout`, `complete`, `blocked`, `unknown`
- `verification_status`: `not_run`, `passed`, `failed`, `blocked`
- `blocker_class`: `missing_secret`, `account_or_billing_setup`, `admin_approval`, `destructive_operation`, `ambiguous_roadmap_selection`, `product_decision_missing`, `dirty_worktree_conflict`, `branch_sync_conflict`, `stalled_child_observation`, `repeated_verification_failure`, `sandbox_command_restriction`, `upstream_phase_unmet`, `contract_bug`, `gold_record_amendment`, `unretryable_external_outage`, `stuck_loop`

Architecture-first planner for a single phase of a multi-phase specification. Produces a plan document containing interface freezes, swim lanes with disjoint file ownership, a lane DAG, per-lane task lists (test → impl → verify), and testable acceptance criteria. Designed to be run in **plan mode** and handed off to `claude-execute-phase` for parallel execution.

## When to use

- The input is a multi-phase spec (e.g., `specs/phase-plans-v1.md`) and the user wants to plan a specific phase.
- The work touches more than one area of the codebase and would benefit from parallel lane execution.
- You need interface contracts frozen before lanes diverge.

## When NOT to use

- Single-file, single-concern change → use `/claude-plan-detailed` instead.
- Pure research / "how does X work" → use `Agent(subagent_type: "Explore")` directly, no plan doc needed.
- No phase structure in the spec → use `/claude-plan-detailed` or ad-hoc planning.

## Inputs

| Arg | Required | Meaning |
|---|---|---|
| `<spec-path>` | no | Path to the spec file (relative to repo root). Default: auto-detected `specs/phase-plans-v*.md` at the highest version. |
| `<phase-name-or-id>` | yes | A phase heading, short alias (`P1`–`P7`), or any fuzzy match. Ambiguous → stop and ask via `AskUserQuestion`. |
| `--output <path>` | no | Override the default output path. Default: `plans/phase-plan-<VERSION>-<PHASE_ALIAS>.md`. `<PHASE_ALIAS>` MUST be uppercase exactly as declared in the roadmap (e.g., `FOUND`, `DESIGNFOUND`); lowercase or alternate filename variants force an extra plan-iteration roundtrip because the runner uses the uppercase alias to locate the plan artifact. |
| `--consensus` | no | Enable multi-agent architectural consensus (2–3 Plan teammates with different framings). |
| `--review-external` | no | After writing the plan doc, run Gemini + Codex CLIs in parallel to review it. Requires `gemini` and `codex` installed and authenticated. Produces a `_reviews.md` sibling file. |

Repos may supply a phase alias table (JSON file) via `$PLAN_PHASE_ALIASES` or fall back to the built-in `P1`–`P7` table. If the alias isn't recognized and no custom table is set, stop and ask via `AskUserQuestion` with the actual spec headings.

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `PLAN_SPEC` | Auto-detected highest `specs/phase-plans-v*.md` | Path to the spec file. |
| `PLAN_VERSION` | Extracted `v\d+` from spec filename | Version string embedded in output filename. |
| `PLAN_PHASE_ALIASES` | Built-in alias table | Path to a JSON file mapping alias → phase heading. |

Example `.env`:

```sh
PLAN_SPEC=specs/phase-plans-v1.md
```

Invocation examples:

```
/claude-plan-phase P1
/claude-plan-phase P3 --consensus
/claude-plan-phase P3 --review-external
/claude-plan-phase specs/roadmap.md "Phase 3: Billing" --consensus --review-external
```

## Expected helpers

The skill references these `_shared/` helpers. Each degrades gracefully if absent:

- `_shared/next_reflection_path.py` — legacy helper only; current closeout writes reflections to `resolve_skill_bundle_root("codex")/claude-plan-phase/reflections/<repo_hash>/<branch_slug>/<run_id>.md`.
- `_shared/review_with_cli.py` — required only for `--review-external`. No fallback; if absent, surface an `AskUserQuestion` with `[skip review this run, abort]`.
- `_shared/scaffold_docs_catalog.py` — used by `SL-docs.1`. If absent, the docs lane records "docs-catalog rescan helper unavailable; manual catalog audit" in its commit message and proceeds.

## Deferred tool preloading

Load tools used later in a single query so mid-workflow calls don't pay a round-trip:

```
ToolSearch(query: "select:TaskCreate,AskUserQuestion,ExitPlanMode")
```

## Workflow (delegation-first)

The main thread is an orchestrator only: brief specialists, synthesize output, enforce consensus, write the final doc, emit tasks. See `## Teamwork & delegation posture` for the posture rules.

### Step 0 — Read predecessor handoff (if present)

The predecessor is `claude-phase-roadmap-builder` (first phase planned against a new roadmap) or `claude-execute-phase` (the next phase after one finished executing). Resolve both repo-keyed `latest.md` handoff paths (`phase_loop_runtime.skill_paths.resolve_handoff_root`, falling back to `resolve_handoff_path` in `shared/phase-loop/handoff_path.py`), use the one with the newer `timestamp:`, or proceed standalone if neither exists. Before trusting it, check that `from:` matches the predecessor, the timestamp is under 7 days old and every `artifact:` path resolves under `$(git rev-parse --show-toplevel)`; on any failure ask via `AskUserQuestion` with `[use anyway, ignore, abort]`. Fold its "Open items" and "Repo-specific gotchas" into the Step 2 briefs. The path-resolution script is in [references/interactive-workflow.md](references/interactive-workflow.md).

### Step 1 — Resolve spec path, phase, and PHASE_ID

**Spec path resolution (in order):**
1. `$PLAN_SPEC` env var → use verbatim.
2. `<spec-path>` arg → use verbatim.
3. Glob `specs/phase-plans-v*.md`; pick the highest version.
4. Else any `specs/*.md` if exactly one exists → use it and note the assumption.
5. Else stop and ask via `AskUserQuestion`.

**Version string** (for output filename): `$PLAN_VERSION` → pattern `v\d+` in filename → `v1` default.

**Phase alias table**: `$PLAN_PHASE_ALIASES` (JSON file) → built-in table.

**Phase name**: short alias → fuzzy match → 0 matches: stop + ask → multiple matches: stop + disambiguate.

**PHASE_ALIAS**: the resolved short alias in lowercase (e.g., `p1`). If none exists, use `phase-<N>`.

**Output path**: `--output` override, else `plans/phase-plan-<VERSION>-<PHASE_ALIAS>.md`.

### Step 2 — Parallel reconnaissance via Explore teammates

**Skip this reconnaissance when the context is already in session.** If the files this phase touches have already been read, the architecture was just discussed, or the caller supplied the file map, do not spawn Explore teammates to re-gather what you already have — plan directly from it. Keep reconnaissance proportional: launch one focused Explore per genuinely-unknown area, not a full three-way fan-out for a one- or two-file change.

Otherwise `TeamDelete` defensively (treat `Team X does not exist` and `already leading team X` as benign), `TeamCreate` a fresh team, then launch up to 3 named `Agent(subagent_type: "Explore")` teammates (`explore-<area>`) in a single message, one per major area the phase touches. Each brief carries the phase Objective and Exit criteria verbatim, a scoped mapping question, architecture context, related files, a `SendMessage` preload and an explicit `SendMessage` deliverable; apply the `/claude-task-contextualizer` checklist. The full brief template is in [references/interactive-workflow.md](references/interactive-workflow.md).

Block until all return. Their findings populate `## Context`.

### Step 2.5 — Explore teammate recovery

If a teammate idles without a substantive reply, send one targeted `SendMessage` nudge naming the missing deliverable. On a second non-response, proceed with main-thread read-only reconnaissance rather than respawning the teammate.

### Step 3 — Architectural decisions

**With `--consensus`**: launch 2–3 named `Agent(subagent_type: "Plan")` teammates in a single message, one per framing (`arch-minimal`, `arch-clean`, `arch-parallel`). Each returns proposed interface freezes, a lane decomposition with file ownership, its rationale and known risks. Synthesize by the consensus rule (unanimous, then majority with dissent recorded, then one more `SendMessage` round, then the main thread picks, biased toward `arch-parallel`). The framings, brief contents and full synthesis rule are in [references/interactive-workflow.md](references/interactive-workflow.md).

**Without `--consensus`**: Launch 1 `Agent(subagent_type: "Plan", name: "arch-baseline")` for baseline architecture decisions.

### Step 4 — Lane decomposition (main thread)

Synthesize Explore + Plan output into swim lanes. For each lane, determine:

- **Scope** — one sentence.
- **Owned files** — glob list, disjoint from every other lane's globs. Before emitting the plan, scan each lane's owned files for overlap with every other lane in the same wave. On overlap, either move the shared file into a preamble lane (`SL-0`, see [references/lane-templates.md](references/lane-templates.md)) that all dependents consume, or collapse the overlapping lanes into one. Overlap that survives into the final plan triggers the `overlapping_write_ownership` lane-IR diagnostic at runtime and refuses execution (Pattern B from the 2026-05-25 runner failure analysis).
  - Owned files MUST enumerate the COMPLETE set the executor will touch, not just headline sources; under-enumeration fails the closeout's `phase_owned_dirty` check (Pattern A, commit `47c772b4`).
  - `validate_plan_doc.py` check (R) names each tracked companion (test, snapshot, lockfile, `.env.example`, migration test or glob) that no lane owns; own it or state why it stays untouched. (R) does not check generated artifacts: own those too.
- **Interfaces provided** — symbols, types, endpoints, migrations this lane publishes.
- **Interfaces consumed** — symbols this lane depends on from other lanes.
- **Parallel-safe** — `yes` / `no` / `mixed` (with explanation if not `yes`).

Run the Lane validation checklist before proceeding. If it fails, return to Step 3 with the failure noted.

### Step 5 — Task authoring (main thread)

For each lane, author an ordered task list:

- One **test** task (write failing tests for the lane's contracts).
- One or more **impl** tasks (each depends on the preceding test task).
- One **verify** task (runs the full test suite for the lane, plus any integration checks).

Tasks are identified `<SL-ID>.<N>`.

**Every phase must include a terminal `SL-docs` lane** after the impl/verify lanes. Copy it from the docs-sweep template in [references/lane-templates.md](references/lane-templates.md). No opt-out — force a conscious doc decision every phase, even if the lane ends up recording "no cross-cutting changes needed."

### Step 6 — Emit per-lane tasks via TaskCreate

Plan-mode note: `TaskCreate` writes outside the scratch file and is blocked in plan mode. Author the task bodies in-thread during Step 5 so they are ready, but defer the actual `TaskCreate` invocations until AFTER `ExitPlanMode` approval (Step 8).

For each lane, emit one `TaskCreate`:

- **Title**: `<SL-ID> — <lane name>`
- **Body**: `Depends on: <upstream SL-IDs>`, `Blocks: <downstream SL-IDs>`, `Parallel-safe: <flag>`, and the ordered child task list (`test / impl / verify`).

This makes the lane DAG visible in the user's task pane and becomes the hand-off surface for `claude-execute-phase`.

### Step 7 — Write plan doc

Draft the plan in the plan-mode scratch file only. The scratch-file path is given in the plan-mode system reminder — do not guess it. Do NOT write to `plans/phase-plan-<VERSION>-<PHASE_ALIAS>.md` yet; plan mode forbids writes outside the scratch file. The project-path copy + staging happens in the Close-out "Stage artifact" section after `ExitPlanMode` approval.

Then validate the scratch draft with
`validate_plan_dispatch_hints`. If it returns findings, stop without writing
the project-path artifact and emit the validation_failed closeout described in
`## Planner Literal Validation`. If `scripts/validate_plan_doc.py` exists
(shell test `[ -f scripts/validate_plan_doc.py ]`), run it against the scratch
file and fix any errors before `ExitPlanMode`:

```
python scripts/validate_plan_doc.py <scratch-file-path>
```

Otherwise walk the Lane validation checklist by hand and note manual verification in the post-approval closeout or Execution Notes. The validator checks required headings, disjoint file ownership, DAG acyclicity, grep-assertion-paired-with-tests, and eager-reexport risks.

### Step 7.75 — Advisor review

After the plan doc is drafted in the scratch file and before `ExitPlanMode`, call `advisor()`. Expect 1–4 contract-tightening suggestions per run, typically covering: under-specified freezes, asserted-but-unverified file paths, test-outline mechanism gaps, and spec-vs-contract conflicts. Apply the findings to the scratch draft before calling `ExitPlanMode`.

### Step 7.5 — External CLI review (only if `--review-external`)

Run `_shared/review_with_cli.py` against the plan with this skill's `assets/review_prompt.md`, writing `plans/phase-plan-<VERSION>-<PHASE_ALIAS>_reviews.md`. The command, the empty-cache path and the message to the user are in [references/interactive-workflow.md](references/interactive-workflow.md).

### Step 8 — ExitPlanMode

Call `ExitPlanMode`. The plan doc is the approval surface. After approval, execute the deferred actions in this order: Close-out "Stage artifact" (writes the project-path `plans/phase-plan-<VERSION>-<PHASE_ALIAS>.md` and stages it unless forbidden), then Step 6 `TaskCreate` invocations, then Close-out "Reflection + Handoff".

## Plan document template
Copy the template in [references/plan-document-template.md](references/plan-document-template.md): its frontmatter, headings, lane task tables, ID conventions and task-type rules. The phase-loop runner trusts the frontmatter before the body, so it is exactly:

```markdown
---
phase_loop_plan_version: 1
phase: <PHASE_ALIAS>
roadmap: <repo-relative roadmap path, e.g. specs/phase-plans-v1.md>
roadmap_sha256: <sha256 of that roadmap file>
---
```

Then `# <PHASE_ID>: <Phase Name>` and these headings in order: `## Context`, `## Interface Freeze Gates`, `## Cross-Repo Gates` (omit if single-repo), `## Lane Index & Dependencies`, `## Lanes`, `## Execution Notes`, `## Acceptance Criteria`, `## Verification`.

- Each lane's `Owned files` is a single-line inline bullet of comma-separated backticked globs, never nested sub-bullets.
- Each `## Acceptance Criteria` item is `- [ ] EC-<ALIAS>-<N> — proven by <command / test>, falsified by <assertion / negative control>`, and the falsifier must target a production construction site with path-entered control.
- The docs-sweep `SL-docs` lane comes from [references/lane-templates.md](references/lane-templates.md); non-numeric lane aliases still appear as `SL-<N>` in the Lane Index.

## Lane validation checklist

Walk the full checklist in [references/lane-validation-checklist.md](references/lane-validation-checklist.md) before writing the plan doc, and again by hand when `validate_plan_doc.py` is absent. The checks the validator and runtime enforce stay here:

- [ ] **Disjoint file ownership** — no two lanes' `Owned files` globs intersect. For generated files, call out shared-generated status in Execution Notes.
- [ ] **DAG has no cycles** — a topological sort of `Depends on:` succeeds.
- [ ] **Synthesis lanes are explicit reducers** — any lane that writes a docs summary, truth table, readiness matrix, release summary, or other synthesized artifact lists every producer lane under `Depends on` and every consumed finding under `Interfaces consumed`. Mark these lanes `Parallel-safe: no`.

The reference adds inline concrete `Owned files`, a `test` before every `impl`, testable acceptance items that reference their roadmap `EC-<ALIAS>-<N>` ID as plain text and name their proving command, grep-only checks paired with a test, a browser step for UI changes, stale-base `Interfaces consumed`, and the terminal `SL-docs` lane.

## Teamwork & delegation posture

- **Main thread = orchestrator only.** Brief, synthesize, write, emit. Do not `Grep`/`Read` the codebase directly during Steps 2–5. If you find yourself doing so, the teammate's brief was incomplete — re-brief via `SendMessage`.
- **Parallel-by-default.** Step 2 (Explore) and Step 3a (consensus Plan) MUST be issued as a single message with multiple `Agent` tool calls.
- **Name every teammate.** Set `name:` on every `Agent` call so you can re-address via `SendMessage` without losing context or paying to restart.
- **Task list as source of truth for the lane DAG.** Step 6's per-lane `TaskCreate` is how the plan becomes actionable; each lane task is addressable by ID for `claude-execute-phase`.
- **Hand-off to `claude-execute-phase`.** After `ExitPlanMode` approval, invoke `/claude-execute-phase <plan-doc-path>`. See that skill for the full execution contract (team creation, worktree isolation, merge policy). Do NOT pass `isolation: "worktree"` alongside `team_name` — the harness drops `isolation` in that combination.
- **Manual hand-off (when `claude-execute-phase` is unavailable).** Validate the plan with `python scripts/validate_plan_doc.py <plan-doc-path>`, then run each lane standalone or teamed as described in [references/interactive-workflow.md](references/interactive-workflow.md).

## Output contract

After `ExitPlanMode` approval, three artifacts exist:

1. `plans/phase-plan-<VERSION>-<PHASE_ALIAS>.md` — committable, valid markdown, all headings present.
2. The plan-mode scratch file — identical contents.
3. One `TaskCreate`'d top-level task per lane, each with `test / impl / verify` children, containing `Depends on:` / `Blocks:` / `Parallel-safe:` metadata in the body.

Those three are the full hand-off surface — everything downstream (manual lane execution or `claude-execute-phase`) reads from them.

## Close-out — Stage artifact (preservation guarantee)

After `ExitPlanMode` is approved, before exiting:

1. Verify frontmatter before staging:
   - `phase_loop_plan_version: 1`
   - `phase: <PHASE_ALIAS>`
   - `roadmap: <repo-relative roadmap path from repo root>`
   - `roadmap_sha256: <sha256 of that roadmap file>`
2. Run `validate_plan_dispatch_hints` before copying or staging the project-path
   artifact; stop with the validation_failed closeout if it returns findings.
3. Run `python scripts/validate_plan_doc.py plans/phase-plan-<VERSION>-<PHASE_ALIAS>.md` when the script is present; fix any frontmatter/path/hash failures before continuing.
4. Run `git status --short -- plans/phase-plan-<VERSION>-<PHASE_ALIAS>.md` and include the `_reviews.md` sibling if `--review-external` produced one.
5. If the plan or review artifact is untracked or modified and the user did not explicitly forbid staging, run `git add plans/phase-plan-<VERSION>-<PHASE_ALIAS>.md` plus the review sibling if present.
6. Rerun `git status --short -- plans/phase-plan-<VERSION>-<PHASE_ALIAS>.md` and report `Artifact state: staged|tracked|modified|unstaged|blocked`.
7. Do not commit unless the user explicitly asked for a commit.

When the generated plan is ready to execute, set `Next phase: <PHASE_ALIAS> - execution ready` and `Next command: /claude-execute-phase <PHASE_ALIAS>`. If execution should not start yet, set `Next phase: <PHASE_ALIAS> - blocked: <reason>` and `Next command: none - <reason>`.

## Close-out — Reflection + Handoff

After artifacts are staged or confirmed tracked (staging comes first unless the user explicitly forbade it), the orchestrator writes two files with the Write tool:

- FILE 1, a repo-agnostic reflection to `resolve_skill_bundle_root("codex")/claude-plan-phase/reflections/<repo_hash>/<branch_slug>/<run_id>.md`. It is about how the skill's instructions performed, and must not name this project, codebase, filenames or domain.
- FILE 2, the repo-specific handoff at the per-repo `latest.md` slot for `claude-plan-phase`, which overwrites any prior handoff from this skill in the same repo. Its frontmatter carries `from`, `timestamp`, `artifact`, `artifact_state`, `next_skill`, `next_command` and `next_phase`.

Path resolution, both templates, the optional fresh-context close-out agent and the final message to the user are in [references/closeout-reflection-handoff.md](references/closeout-reflection-handoff.md).


Use `phase_loop_runtime.skill_paths` resolver helpers for harness skill roots, handoff roots, helper roots, and reflection roots.



## Spec Closeout Plan

Generated phase plans must include a machine-readable section:

```markdown
## Spec Closeout Plan
- schema: `spec_delta_closeout.v1`
- decision: `<one of no_spec_delta, roadmap_amendment, canonical_spec_update, governed_pipeline_refresh, mirror_cutover_required, dotfiles_skill_source_update, human_source_judgment_required>`
- target surfaces: `<repo-relative paths or globs>`
- evidence paths: `<repo-relative metadata-only artifacts>`
- redaction posture: `metadata_only`
- downstream handling: `<none, roadmap amendment, Governed Pipeline refresh, mirror cutover, or human source judgment>`
```

Validate that the decision literal is in vocabulary, `target surfaces` and `evidence paths` are present, and `redaction posture` is `metadata_only`. Missing, malformed, or out-of-vocabulary spec-closeout sections are repairable `contract_bug` blockers unless the plan explicitly requires `human_source_judgment_required`. This section must preserve the allowed `## Execution Policy` selector vocabulary and must not invent new Dispatch Hints selectors. Reducer and verification lanes keep the existing `work-unit=phase_reducer` and `work-unit=phase_verify` policy literals.

## Verification Contract

Generated plans must contain machine-checkable verification commands and an effective `automation.suite_command`; phase plans must validate those commands through IF-0-VC-2 before they are handoff-ready. If an acceptance item depends on operational evidence that cannot be machine-checked directly, the plan must name the operational evidence artifact and the runner-stamped amendment mechanism that records it. proxy evidence requires a roadmap amendment before downstream plans rely on it.

## Closeout

### Manifest write

After the plan artifact and repo-local handoff path are known, perform a best-effort `plan-manifest append` through `phase_loop_runtime.plan_manifest.append_entry`. Append a `type=phase` entry with `status=committed`, `slug`, `file`, `created_at`, `owner_skill=claude-plan-phase`, `handoff_ref`, `roadmap_ref`, `phase_alias`, `if_gates_produced`, and `lanes`. Resolve paths with `phase_loop_runtime.skill_paths` helpers and keep the manifest write best-effort during the dual-mode window: failures are non-fatal, emit a ledger warning, and are mentioned in the mandatory reflection without changing the existing plan closeout result.

A legacy `plans/manifest.json` using the `schema`/`entries` layout raises `unsupported manifest schema_version: 0`; treat that exact error as the expected non-fatal case (warn, do not block or migrate in place). `phase_loop_runtime` may resolve from the installed dotfiles runtime on `PYTHONPATH` even when the target repo neither vendors nor installs it — use the importable package; a missing repo-local checkout is not a blocker.

Closeout payload shape is defined by `EmitPhaseCloseout` in `phase_loop_runtime/baml_src/emit_phase_closeout.baml` (if that path is absent in the checkout, use the operator/prompt-supplied field contract or the installed `phase_loop_runtime` package — the missing vendored BAML source is not a blocker); keep skill text focused on value selection and handoff routing, not duplicated field ceremony.

Before final response, write a reflection for every non-trivial run. Write it to `resolve_skill_bundle_root("codex")/claude-plan-phase/reflections/<repo_hash>/<branch_slug>/<run_id>.md`. The reflection must include `## Run context` with skill name, ISO timestamp, repo, branch, commit, and artifact path if any, followed by `## What worked`, `## What didn't`, and `## Improvements to SKILL.md`. skip only when no artifact was produced AND no decision was made AND the run was pure inspection.

## GOVLEAN Policy

- **Content & Behavior Falsifiers**: Runtime evidence primitives evaluate content and behavior bound properties; never commit topology or future-history pins to plan specifications.
- **External-Only Pins**: Pinned inputs are restricted strictly to declared external inputs in a dedicated section.
- **Plan Budget**: The execution plan document has a word budget that scales with lane count: 2000 words plus 500 per lane by default, configurable per repo or per phase in `.phase-loop-planning.toml` (keys: `docs/phase-loop/plan-budget.md`). `validate_plan_doc.py` check (S) warns above it. Frozen artifacts the plan references (contracts, schemas, freeze-gate payloads) have no cap: move long detail there and point at it rather than inlining it.
- **Review Policy**: Ratified review requires cross-vendor ablation evidence for all Sol-authored plans.
- **Proof-Cost Findings**: Flag proof-cost findings when evaluation is constrained to a single node over roughly five minutes or when a test run is unable to report multiple failures.
