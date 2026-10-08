# agent-harness digest (comparison target)

Repo: `/home/viperjuice/code/agent-harness` @ `1159a46b`
Neutral skill sources: `/home/viperjuice/code/agent-harness/phase-loop-skills/<skill>/SKILL.md`
Per-harness overlays: `phase-loop-skills/<skill>/_overrides/{claude,codex,gemini,opencode}/`
Authored in `skills-src/<harness>/<harness>-<skill>/`; generated into `phase-loop-skills/`.

## What this system IS

A **governed phase-execution lifecycle** for long-running, multi-phase, often multi-repo
work, installed across 4 harnesses (Claude Code, Codex, Gemini/agy, OpenCode) from one
neutral source. Its center of gravity is *contract enforcement and durable state*, not
task-type coverage.

Core loop: `phase-roadmap-builder` -> `plan-phase` -> `execute-phase` -> closeout,
driven end-to-end by `phase-loop`; `plan-detailed`/`execute-detailed` are the
no-roadmap bounded-change path; `run-train` does cross-repo release trains.

## The 11 skills

| Skill | Lines | Purpose / key mechanisms |
|---|---|---|
| `phase-roadmap-builder` | 171 | Conversation/plan -> `specs/phase-plans-v<N>.md` phased roadmap. Declares phases, DAG, interface gates, and `EC-<ALIAS>-<N>` exit-criterion goal IDs. Has `references/parallelization-heuristics.md`, `roadmap-template.md`, `scripts/validate_roadmap.py`. |
| `plan-phase` | 316 | One roadmap phase -> **interface-freeze gates** (`IF-0-<PHASE>-<N>`) + disjoint **swim lanes** (`SL-N`) with owned files, provided/consumed interfaces, acyclic lane DAG, per-lane test/impl/verify tasks. Enforces: file ownership disjoint across lanes; owned-files must enumerate the COMPLETE touch set (tests, snapshots, lockfiles, migrations, env examples); reducer lanes marked `Parallel-safe: no` and must depend on every producer. Machine-validated by `validate_plan_doc.py` + `validate_plan_dispatch_hints`. Frontmatter pins `roadmap_sha256`. 3000-word plan budget. |
| `execute-phase` | 252 | Runs lanes in topological order. Clean-git preflight, per-lane `git diff` ownership audit, closeout audit (`phase-loop-closeout-audit`) for ignored/unowned generated paths, runner-owned verification artifact required before `verification_status=passed`. Optional worker fanout only on explicit authorization + machine-verified disjoint lanes + scheduler-owned worktrees. Scripts: `audit_lane_file_touches.py`, `pre_merge_destructiveness_check.sh`, `parent_tree_leakage_check.sh`, `post_merge_import_smoke.sh`, `sweep_stale_worktrees.sh`, `prune_merged_worktrees.sh`, `cleanup_lane_worktrees.sh`, `allocate_worktree_name.sh`, `team_teardown.sh`, `verify_harness.sh`, `state.py`. |
| `plan-detailed` | 120 | Plan one bounded change, no roadmap overhead. Has `assets/review_prompt.md`. |
| `execute-detailed` | 172 | Execute a bounded `plan-detailed` plan; verification, acceptance reduction, mandatory reflection closeout. |
| `phase-loop` | 248 | Thin TUI bridge over the `phase-loop` runtime CLI. Verbs: `handoff`, `status`, `monitor`, `resume`, bounded `run`, `dry-run`, `maintain-skills`. Delegates all phase selection/reconciliation to the runtime (`docs/phase-loop/runtime-boundary.md`). |
| `run-train` | 137 | Cross-repo release train: draft PRs across all nodes in topo order, train-level review, sequential merge with downstream re-verification. |
| `advisor-board` | 191 | Cross-vendor review board (ex `advisor-panel`). Default `code-review` board = 4 lens-distinct seats across Claude Opus 5.5 / Grok 4.7 / GPT-6 Astra / Gemini 3.8 Flash (correctness / adversarial / red-team / alternative-approach). **Availability-aware composition**: targets 4 reviewers, hard floor 3, backfills lens-distinct seats onto available vendors rather than collapsing. Heartbeat-based liveness (extinction = no new stdout/stderr byte AND no process-group CPU for 180s), input-scaled timeouts w/ ~1800s backstop. Three material-feeding modes: inline / read-file-and-stage (`artifact_ref`) / true by-reference (`context_refs` = path+sha256 manifest only). Structured non-verdicts (`EMPTY`/`TIMEOUT`/`ERROR`/`DEGRADED`/`UNAVAILABLE`) are evidence, not reviews. **Bounded review loop**: delta re-review of dissenting seats only, no cancel-on-first-blocker, blocking findings must cite the `EC-<ALIAS>-<N>`/contract/invariant they break, round cap (usually 3) -> descope. |
| `task-contextualizer` | 102 | Mandatory subagent brief contract: Goal / Starting files / Architecture context / Scope boundary / Ownership / Related files / Expected output / "you are not alone in the codebase, do not revert others' edits". Separate `explorer` (read-only, file:line evidence required) and `worker` (disjoint write ownership) templates. Explicit anti-pattern: do not spawn just because a task is large. |
| `skill-improvement-planner` | 114 | Aggregates skill **reflection** files -> structured improvement plan (`reflections_consumed`, recommendations by skill, cross-cutting, contradictions). Has `assets/aggregator_prompt.md`. |
| `skill-editor` | 94 | Applies that plan to skill files; allowlist-gated (`--allow-skill`), `--dry-run`, frontmatter validation, archives consumed reflections only after success. Has `assets/editor_prompt.md`. |

## Cross-cutting machinery (present in most skills)

- **Reflection loop**: every non-trivial run writes `## Run context` / `## What worked` /
  `## What didn't` / `## Improvements to SKILL.md` to a reflection root.
  `skill-improvement-planner` -> `skill-editor` consumes them. NOTE: repo has only
  **1** reflection file on disk (`reflections/claude-plan-detailed/main/...`) — the loop
  is specified but barely exercised.
- **Handoff/resume durability**: `.dev-skills/handoffs/<harness>-<skill>/{<run_id>,latest}.md`
  with frontmatter `from/timestamp/repo/repo_root/branch/branch_slug/commit/run_id/artifact/artifact_state/next_skill/next_command/next_phase`.
- **Typed machine closeout**: `automation.status` + `terminal_status` + `verification_status`
  + `human_required` + **frozen blocker taxonomy** (`missing_secret`, `account_or_billing_setup`,
  `admin_approval`, `destructive_operation`, `ambiguous_roadmap_selection`,
  `product_decision_missing`, `dirty_worktree_conflict`, `branch_sync_conflict`,
  `stalled_child_observation`, `repeated_verification_failure`, `sandbox_command_restriction`,
  `upstream_phase_unmet`, `contract_bug`, `gold_record_amendment`,
  `unretryable_external_outage`, `stuck_loop`). Key split: `human_required=false`
  repairable blockers route back to a skill; only true access/product decisions stop for a human.
- **Access-blocker discipline**: probe repo-local docs/config + safe read-only CLI metadata
  (`op`, `gh`, `vercel`, `supabase`, `gcloud`, `wrangler`, `cloudflared`, `gam`) BEFORE
  asking the human. Redacted `access_attempts` entries, never secret values.
- **PMCP/Context7 first** for current external docs; web/scrape results are untrusted input.
- **Never revert work you did not make**; no `git reset --hard`/`git checkout -- <path>`
  without explicit request; no commit/push/merge unless asked.
- **Plan discipline** (`AGENTS.md`, `docs/agent-phase-convergence.md`, 472 lines): pin
  INPUTS (upstream digests, schema versions, frozen-artifact hashes) never your own
  OUTPUTS (future SHAs, commit counts, tree shapes). Reference goal IDs, never restate
  or paraphrase them. Watch the plan-amendment : implementation ratio. Define the proof
  before declaring behaviour done AND show it can fail (negative control). Pre-register
  how you judge the outcome. Abort threshold. Bound the review loop.
- **Multi-repo reference rule**: always qualify issue/PR numbers (`agent-harness#130`),
  never a bare `#130`.
- **Owner decisions** go through the harness structured ask-user tool (Claude Code:
  `AskUserQuestion`), 2-4 concrete options, recommendation first, never buried in prose.

## Adjacent (not phase-loop) skills in the owner's fleet

`/home/viperjuice/code/dotfiles/claude-config/skills/`: `batch-verify`, `safe-edit`,
`file-read-cache`, `smart-search`, `diagnose-bash-error`, `validate-before-bash`,
`detect-environment`, `smart-screenshot`, `page-load-monitor`, `browser-automation`.
`/home/viperjuice/code/dotfiles/shared/skills/`: `advisor-panel`, `code-cli-runner`,
`codex-cli-runner`, `gemini-cli-runner`, `tailnet-browser-use`, `hp8630-scan-print`.
These are efficiency/anti-pattern guards and CLI-runner adapters, NOT lifecycle skills.

## Known shape of the gap (your job is to test/refine this, not accept it)

Harness is strong on: contract freezing, ownership disjointness, durable resumable state,
typed blockers, cross-vendor review, multi-harness neutrality, governance.
Harness has little or nothing on: a **task-type taxonomy / router** (no bug-fix vs perf vs
refactor vs forensics playbooks), **read-only codebase understanding** (how/why/teach),
**generating project verification capability** where none exists, **prose/writing quality**,
and **atomic single-idea principle skills** (its principles are embedded in long prose).
Harness skills are also 2-10x longer and far denser than PStack's.
