# Design: Fleet-wide model-tier taxonomy (ultra / heavy / regular / lite)

Status: DELIVERED — merged as PR Consiliency/agent-harness#309 (squashed to main @c266410, 2026-07-26)
after 11 rounds of cross-vendor CR (final: 4/4 AGREE, 0 blockers). Every acceptance
criterion below was re-verified against live code on main before being ticked.
Owner: model-routing
Related: model-id-source guard (agent-harness#129 / gp#108), advisor-board registries, phase-loop profiles

## Context & goal

Today `phase-loop-runtime` has **no named model-tier taxonomy**. Models route by an
informal `MODEL_CLASSES = ("planner","reviewer","implementer","worker")` axis × effort × action,
resolved through `profiles.SHIPPED_MODEL_POLICY` → `CLASS_MODEL_OVERRIDES` →
per-vendor constants, with concrete model IDs scattered across 6+ guarded-registry
files. "tier" is a **reserved word** here — it already means audit-evidence budgets
(`--tier-2/--tier-3`, `models.py:28`), so the model bands below are implemented as a
**model-tier vocabulary kept lexically distinct from audit tiers** (documented at the
definition site).

Goal: a first-class **4-tier taxonomy** with an explicit **role → tier → (vendor →
model_id)** resolution, centralizing every model ID into one registry so a version
bump is a single-file edit (the real fix for "stop chasing versions" — see Alias
decision). Introduces Opus 5 as the Claude heavy model.

## The 4 tiers and their roles

| Tier | Role(s) it serves | Effort default |
|---|---|---|
| **ultra** | review, advising, security evaluation | `max` |
| **heavy** | roadmap/plan authoring and **supervising** long-running workflows | `xhigh` |
| **regular** | implementation (`execute`,`repair`) | `medium` |
| **lite** | cheap/high-volume subtasks (Haiku-like) | `low` |

> **Effort defaults are ADVISORY, not enforced** (CR round-4, item I decision (ii)).
> Only the per-tier **MODEL** mapping is operator-ratified and enforced (the wiring
> test asserts model agreement across seams). The per-tier efforts above are advisory
> defaults returned by `resolve().effort` (the field is `_TIER_ADVISORY_EFFORT`); where
> an executor declares an effort override it intentionally wins. The
> Consiliency/agent-harness#310 amendment binds authoring and review requests to
> `max`, normal execute/repair to `high`, and records requested,
> provider-normalized, and adapter-effective effort separately. Gemini clamps
> unsupported `max` during policy normalization; Codex and Grok translate only
> at argv emission.

**Graceful degradation (user rule):** *ultra when available for that vendor, otherwise
heavy.* Only Claude has a distinct ultra model (`claude-fable-5`). For codex/gemini/grok
there is no separate ultra model — their "ultra" is **the heavy model at `effort=max`**
(this is literally how OpenAI "Sol Pro" `reasoning.mode=pro` and grok `reasoning_effort=high`
work). So `resolve(role=ultra, vendor≠claude)` → `(heavy_model, effort=max)`.

## Verified per-vendor tier matrix (canonical API IDs, live-doc sourced 2026-07-25)

| Tier | claude | codex (OpenAI) | gemini (Google) | grok (xAI) |
|---|---|---|---|---|
| **ultra** | `claude-fable-5` | *(none)* → heavy@max | *(none)* → heavy@max | *(none)* → heavy@max |
| **heavy** | `claude-opus-5` | `gpt-5.6-sol` | `gemini-3.1-pro-preview` ⚠️PREVIEW | `grok-4.5` |
| **regular** | `claude-sonnet-5` | `gpt-5.6-terra` | `gemini-3.6-flash` ✓ | `grok-4.3` |
| **lite** | `claude-haiku-4-5-20251001` | `gpt-5.6-luna` | `gemini-3.5-flash-lite` ⚠️API-only (not live on agy) | `grok-build-0.1` |

Notes:
- **claude lite** pins the dated snapshot `claude-haiku-4-5-20251001` (Haiku still uses
  alias→dated form; pin the dated one to freeze the snapshot).
- **gemini heavy** `gemini-3.1-pro-preview` is a **preview** model (Google already
  retired `gemini-3-pro-preview`) → tag it `volatile=True` / `preview` in the registry.
- **gemini regular/lite** — GOOGLE-API-confirmed (live docs, changelog 2026-07-21): regular =
  `gemini-3.6-flash` (stable GA), lite = `gemini-3.5-flash-lite` (stable GA). Both are true
  stable Google-API ids. **FLEET-LIVENESS (CR round-6/7, `agy models` on host):** the agy CLI
  (the gemini executor) exposes `gemini-3.6-flash-{high,…}` — so REGULAR is LIVE and routes —
  but exposes NO flash-lite at all. So the **lite cell is ASPIRATIONAL for the fleet**: it is a
  real Google-API id but NOT reachable through agy, so the live worker band degrades to
  `gemini-3.5-flash-high` (real 3.5 Flash). Repin the lite cell to a canonical agy id when agy
  ships a flash-lite. (Note: agy's ids are canonical `gemini-<ver>-<family>-<effort>`, not the
  bare Google-API ids in this table.)
- **codex ultra** = `gpt-5.6-sol` at `effort=max` ("Sol Pro" is a reasoning mode, not a
  distinct catalog id).

## Alias decision: PIN, do not auto-track

Every vendor recommends pinning a specific version for production; Anthropic's 5-gen has
**no floating aliases at all** (dateless IDs `claude-opus-5` ARE per-generation pinned
snapshots). OpenAI/Google/xAI offer one floating alias each (`gpt-5.6`,
`gemini-flash-latest`, `grok-4.5-latest`) but hot-swap them (Google: 2-week email
notice). So aliasing does NOT safely end version-chasing for a governed pipeline.

Decision (operator-confirmed): **pin canonical IDs in the one tier registry.** A version
bump = a single-file edit. No floating aliases. (An opt-in "track-latest" resolve mode
that records the resolved snapshot in provenance may be added later for non-governed
convenience runs — out of scope here.)

## Role → tier mapping (retarget SHIPPED_MODEL_POLICY)

| action / role | today (class) | NEW (tier) | change |
|---|---|---|---|
| `roadmap`, `plan` | planner (opus) | **heavy** (opus) | authoring stays distinct from evaluation |
| `review`, `advise`, `security` | reviewer (fable) | **ultra** (fable) | dedicated evaluation class |
| *supervise* (coordinator/runner) | *(none — inherits session)* | **heavy** (opus-5) | advisory provenance only (no programmatic launch seam — see item 7) |
| `execute`, `repair` | implementer (sonnet) | **regular** (sonnet) | unchanged |
| worker / cheap subtasks | worker (haiku) | **lite** (haiku) | rename + cross-vendor formalization |

Panel/board reviewer defaults already sit at the correct tier per vendor
(`DEFAULT_LEG_MODELS` = claude fable-5 / codex sol / gemini 3.1 Pro / grok 4.5) → no
change needed there; they become the canonical "ultra-else-heavy" realization.

## Implementation surface (from the architecture map)

All under `phase-loop-runtime/src/phase_loop_runtime/`.

1. **`models.py`** — add `MODEL_TIERS = ("ultra","heavy","regular","lite")` with the
   audit-"tier" distinction documented. Keep `MODEL_CLASSES` as a back-compat alias
   mapping (`planner↔heavy`-ish) only if needed by external consumers; otherwise migrate.
2. **`capability_registry.py`** — replace the single `CLAUDE_HEAVY_MODEL = "claude-opus-4-8"`
   SSOT with the 4 Claude constants: `CLAUDE_ULTRA_MODEL="claude-fable-5"`,
   `CLAUDE_HEAVY_MODEL="claude-opus-5"`, `CLAUDE_REGULAR_MODEL="claude-sonnet-5"`,
   `CLAUDE_LITE_MODEL="claude-haiku-4-5-20251001"` (each `# model-id-source:` marked).
3. **`profiles.py`** — the resolution core. Define the per-vendor `TIER_MODELS[vendor][tier]
   → (model_id, effort, volatile?)` matrix (replacing `CLASS_MODEL_OVERRIDES`), the
   `resolve(role, vendor) → (model_id, effort)` with the ultra→heavy@max fallback, and
   retarget `SHIPPED_MODEL_POLICY` per the role→tier table. Add per-vendor constants for
   codex/gemini/grok tiers.
4. **`advisor_board/registries.py`** (`_MODEL_DEFS`) — add `claude-opus-5`; keep
   `effort_ceiling` column (unrelated to the new tier field). Add lite ids as needed.
5. **`advisor_board/{composition,presets,fixtures}.py`** — no tier change (already
   ultra/heavy correct); update any `claude-opus-4-8` literal only if it denotes heavy.
6. **`panel_invoker.py`** `DEFAULT_LEG_MODELS` — unchanged (already at ultra-else-heavy).
7. **Supervisor binding — ADVISORY PROVENANCE ONLY** (CR round-3
   correction). The `supervise → heavy` mapping exists (`SUPERVISOR_TIER = "heavy"` +
   `resolve("supervise", vendor)` via `profiles.supervise_selection`), BUT there is no
   programmatic coordinator launch that sets a model: the run-train coordinator and the
   phase-loop-runner orchestrator ARE the CLI/ambient session (per-node `run_loop`
   launches its own phase executors, each on its own tier model). So the binding does
   not drive a launch request — the coordinator RECORDS the supervise tier on its review
   artifact as provenance, and an operator running the supervisor session should be on
   the heavy model (Opus 5 — now the Claude Code default anyway). Wiring an actual
   programmatic supervisor-launch model is a future item if such a seam is introduced.
8. **`scripts/check_model_id_sources.py`** — keep the 6-file allowlist; ensure every new
   literal lives in an allowlisted registry or carries a `# model-id-source:` marker.
9. **Tests** — update `test_model_id_source_guard.py`, `test_advisor_board_registries.py`,
   `test_advisor_board_matrix.py`, and profiles tests; add a `resolve()` matrix test
   (every role×vendor → expected id+effort, incl. the ultra→heavy@max fallback and the
   gemini-preview marker).

## Acceptance criteria

- [x] `MODEL_TIERS` defined; audit-"tier" collision documented at the definition site.
- [x] `resolve(role, vendor)` returns the matrix's id+effort for all 4 tiers × 4 vendors,
      with non-claude ultra → heavy model @ `effort=max`.
- [x] Claude heavy = `claude-opus-5`; Claude roadmap/plan authoring = `claude-opus-5`;
      review/advice/security = `claude-fable-5`; implementation = `claude-sonnet-5`;
      lite = `claude-haiku-4-5-20251001`.
- [x] gemini heavy carries a `preview`/`volatile` marker.
- [x] Pinned where the vendor publishes immutable ids (claude dateless per-gen
      snapshots; codex `gpt-5.6-<name>`); no floating aliases (`gpt-5.6`,
      `gemini-flash-latest`, `-latest`). gemini heavy (preview) and ALL grok cells
      are marked `volatile=True` — xAI ships no dated snapshot, so bare grok ids
      float to latest stable; repin when dated ids exist.
- [x] `python3 scripts/check_model_id_sources.py` → exit 0.
- [x] Full `pytest` green; new `resolve()` matrix test passes.
- [x] Cross-vendor CR converged (public-repo gate) before merge.

## Non-goals

- Opt-in "track-latest" alias resolve mode (future).
- Changing audit `--tier-N` budgets.
- Vertex AI id variants (Gemini API ids only).
