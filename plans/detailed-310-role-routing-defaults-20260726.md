# Detailed plan: reconcile role routing and effective effort defaults

## Task

Implement the core model-policy portion of Consiliency/agent-harness#310 without
collapsing the four-tier taxonomy:

- roadmap and detailed-plan authoring use Claude Opus 5 (`heavy`);
- plan review, code review, advice, and security review use Claude Fable 5
  (`ultra`);
- normal execution and repair stay on Claude Sonnet 5 (`regular`);
- supervision stays on Opus 5 (`heavy`);
- cheap worker routing remains explicit and opt-in.

This plan lands before the repair-escalation and advisor-board plans. It deliberately
does not change any adapter, panel launch, refusal behavior, or dotfiles setting.

## Current-state findings

- `models.MODEL_CLASSES` currently contains only `planner`, `implementer`, and
  `worker`; `ExecutionPolicyRule` rejects any other class.
- `profiles._CLASS_TIER_BRIDGE` maps `planner -> ultra`, so Claude planning and
  review both resolve to Fable. `SHIPPED_MODEL_POLICY.review` also uses `planner`.
- Every manually maintained provider class map must know a new class; otherwise a
  policy can validate but fail to resolve on Gemini, Grok, OpenCode, or PI.
- `ROLE_TIERS` already maps `supervise -> heavy` and `advise -> ultra`, but there is
  no distinct `security` role and roadmap/plan still map to `ultra`.
- Claude's `EXECUTOR_EFFORT_OVERRIDES` forces `high` for every action, so it
  currently defeats the max-effort policy described for authoring and review.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/models.py` (modify)

- Extend `MODEL_CLASSES` to `("planner", "reviewer", "implementer", "worker")`.
- Keep `MODEL_PROFILES`, product-action vocabulary, and work-unit vocabulary
  unchanged. `reviewer` is a model class, not a new phase-loop command.
- Update the adjacent taxonomy comment to distinguish authoring (`planner`) from
  evaluation (`reviewer`).

### `phase-loop-runtime/src/phase_loop_runtime/profiles.py` (modify)

- Change `ROLE_TIERS` so `roadmap` and `plan` resolve to `heavy`; keep `review` and
  `advise` on `ultra`; add `security -> ultra`; leave `supervise -> heavy`,
  `execute`/`repair -> regular`, and `worker -> lite`.
- Change `_CLASS_TIER_BRIDGE` to:
  - `planner -> heavy`
  - `reviewer -> ultra`
  - `implementer -> regular`
  - `worker -> lite`
- Regenerate the derived Claude and Codex class maps through the existing bridge,
  and add explicit `reviewer` entries to every manually maintained provider map
  (`opencode`, `gemini`, `grok`, and `pi`). Use each provider's current
  review-capable/top model; do not invent or silently alias unknown model IDs.
- Change `SHIPPED_MODEL_POLICY.review.model_class` from `planner` to `reviewer`.
  Keep roadmap/plan on `planner`, execute/repair on `implementer`.
- Make `EXECUTOR_MODEL_OVERRIDES` agree with the class/tier path for every live
  action: Claude roadmap/plan -> `claude-opus-5`, review -> `claude-fable-5`, and
  execute/repair -> `claude-sonnet-5`. Preserve the equivalent vendor-specific
  routing for Codex, Gemini, Grok, OpenCode, and PI.
- Make effective effort explicit at the existing action boundary:
  roadmap/plan/review request `max`; execute/repair request `high`. Gemini clamps
  unsupported max during policy normalization and records policy fallback.
  Grok and Codex keep max at the policy layer and translate only at the adapter
  boundary (Grok high, Codex xhigh), recording adapter-effective provenance with
  `fallback_applied=false`. Do not conflate those two clamp stages.
- Change Gemini action overrides to carry the base model
  `gemini-3.6-flash` plus the requested effort, rather than baking `high` into
  the stored default model. This lets a valid operator `--effort medium` render
  `gemini-3.6-flash-medium`; an operator who explicitly supplies an embedded
  `gemini-3.6-flash-high` model together with conflicting effort fails loudly.
- Do not add `advise` or `security` to `ACTION_WORK_UNITS` in this change. Those
  are role-resolution/advisor-board classifications, not executable product-loop
  actions today; adding commands would be unrelated surface growth.

### `phase-loop-runtime/src/phase_loop_runtime/models.py` and launcher metadata (modify: effort provenance)

- Extend `ResolvedExecutionPolicy` additively with `requested_effort` and
  `policy_effort` (defaulted for positional/back-compat callers). Keep the
  historical `effort` field equal to policy-normalized effort. Do not label it
  final/effective because Grok intentionally clamps `max -> high` only at argv.
- Populate both fields in `resolve_execution_policy`: requested is the winning
  operator/plan/roadmap/shipped value before provider normalization; policy is
  the normalized provider value. `fallback_applied` compares those two.
- Add launch/argv effort provenance with `requested_effort`, `policy_effort`, and
  `effective_effort`. Each adapter renderer returns or records its emitted token;
  Grok therefore truthfully records max/max/high and Codex records max/max/xhigh,
  while policy fallback remains separate from adapter clamp.

### `phase-loop-runtime/tests/test_model_tier_taxonomy.py` (modify)

- Update the role-to-tier expectations: roadmap/plan/supervise -> heavy;
  review/advise/security -> ultra; execute/repair -> regular; worker -> lite.
- Replace the old “planning resolves to Fable” assertion with separate author and
  reviewer assertions: Claude roadmap/plan -> Opus, Claude review -> Fable.
- Extend live class-path coverage with `reviewer -> ultra` for Claude and Codex.
- Keep the full tier-by-vendor matrix itself unchanged.

### `phase-loop-runtime/tests/test_model_class_policy.py` (modify)

- Assert `ExecutionPolicyRule(model_class="reviewer")` validates.
- Assert Claude class resolution returns Opus for `planner`, Fable for
  `reviewer`, Sonnet for `implementer`, and the dated Haiku pin for `worker`.
- Assert shipped review policy resolves `reviewer`/Fable while shipped plan policy
  resolves `planner`/Opus.
- Add precedence coverage proving an operator `--model` or `--effort` still wins
  and provider effort clamping remains explicit, including requested/effective
  values on max-to-high clamps.

### `phase-loop-runtime/tests/test_phase_loop_policy.py`,
`test_phase_loop_launcher.py`, and `test_execution_policy_tiering.py` (modify)

- Update only assertions that freeze the old Claude roadmap/plan model or the
  old all-actions-high effort override.
- Add argv-level assertions that Claude roadmap/plan/review emit max effort,
  execute/repair emit high, Codex max renders to xhigh, and Gemini/Grok preserve
  their documented clamp. Do not weaken unrelated launch or sandbox goldens.
- Update the existing runner assertion that freezes Claude roadmap planning on
  Fable; it must now expect Opus while the adjacent review assertion remains Fable.

### `plans/design-model-tier-taxonomy.md` (modify)

- Record the ratified author/reviewer split, the new `reviewer` class, and the
  exact role-to-tier table.
- State that regular remains the normal implementation tier and heavy is reached
  by authoring/supervision or recorded escalation, not by blanket implementation.
- Record Consiliency/agent-harness#310 as the amendment to the model-tier design.

### `CHANGELOG.md` (modify)

- Add an unreleased entry describing Opus authoring, Fable review/advice/security,
  Sonnet implementation, and effective per-action effort binding.

## Dependencies and order

1. Add `reviewer` to the frozen class vocabulary and every provider map.
2. Move shipped review policy to `reviewer`.
3. Retier `planner` and roadmap/plan to heavy.
4. Bind effective effort overrides.
5. Update tests and documentation.

Steps 1-3 are load-bearing: retiering `planner` before moving review to
`reviewer` would silently route review from Fable to Opus.

## Execution Policy

- execute: effort=high, reason=cross-provider frozen-vocabulary and routing change
- review: model_class=reviewer, effort=max

## Verification

```bash
cd phase-loop-runtime
PYTHONPATH=src:tests python -m pytest \
  tests/test_model_tier_taxonomy.py \
  tests/test_model_class_policy.py \
  tests/test_phase_loop_policy.py \
  tests/test_execution_policy_tiering.py \
  tests/test_phase_loop_launcher.py \
  tests/test_phase_loop_runner.py -q
PYTHONPATH=src:tests python -m pytest tests/test_launchspec_golden.py tests/test_model_id_source_guard.py -q
```

`automation.suite_command`: `cd phase-loop-runtime && PYTHONPATH=src:tests python -m pytest tests/test_model_tier_taxonomy.py tests/test_model_class_policy.py tests/test_phase_loop_policy.py tests/test_execution_policy_tiering.py tests/test_phase_loop_launcher.py tests/test_phase_loop_runner.py tests/test_launchspec_golden.py tests/test_model_id_source_guard.py -q`

## Acceptance criteria

- [x] `MODEL_CLASSES` includes `reviewer`, and every supported provider resolves it explicitly.
- [x] `resolve("plan", "claude")` and `resolve("roadmap", "claude")` select `claude-opus-5`.
- [x] `resolve("review", "claude")` selects `claude-fable-5` before and after planner retiering.
- [x] `resolve("execute", "claude")` and `resolve("repair", "claude")` select `claude-sonnet-5`.
- [x] `resolve("supervise", "claude")` remains `claude-opus-5`; `advise` and `security` resolve to the ultra/Fable tier.
- [x] Claude authoring/review requests max effort and execution/repair requests high; provider clamps remain recorded rather than overclaimed.
- [x] Resolved policy carries requested and policy effort; launch metadata carries final adapter-effective effort.
- [x] Grok max-to-high and Codex max-to-xhigh argv clamps are recorded without falsely setting policy fallback.
- [x] Gemini stores a base Flash model for default routing, so an effort-only operator override renders a matching canonical agy ID.
- [x] Operator model/effort overrides retain precedence.
- [x] The tier matrix and lite/economy pins remain unchanged.
