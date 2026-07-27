from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from .capability_registry import (
    CLAUDE_HEAVY_MODEL,
    CLAUDE_LITE_MODEL,
    CLAUDE_REGULAR_MODEL,
    CLAUDE_ULTRA_MODEL,
    default_model_profile_for_executor,
    provider_policy_capabilities,
)
from .models import (
    ExecutionPolicyRule,
    MODEL_TIERS,
    ModelSelection,
    ResolvedExecutionPolicy,
    WorkUnitPolicy,
    require_literal,
)

if TYPE_CHECKING:
    from .governed_premerge import EscalationDecision


OPENAI_HEAVY_MODEL = "gpt-5.6-sol"
# codex regular (implementer) model — hoisted here so EXECUTOR_MODEL_OVERRIDES below
# can reference it. Equals CODEX_REGULAR_MODEL in the tier matrix (single source).
OPENAI_IMPLEMENTER_MODEL = "gpt-5.6-terra"
OPENCODE_OPENAI_HEAVY_MODEL = "openai/gpt-5.6-sol"
# opencode regular (implementer) model — hoisted here so EXECUTOR_MODEL_OVERRIDES below
# can reference it (same reason as OPENAI_IMPLEMENTER_MODEL). Provider-qualified prefix.
OPENCODE_OPENAI_IMPLEMENTER_MODEL = "openai/gpt-5.6-terra"
GEMINI_PRO_ROUTED_MODEL = "pro"
GEMINI_AUTO_ROUTED_MODEL = "auto"
# Gemini implementer (regular tier) — the CANONICAL agy model id from `agy models`
# (authoritative list), NOT a display label. CR round-5 finding B: the operator asked us
# to adopt the newest gemini light/medium models; `agy models` exposes gemini-3.6-flash-*
# (GA), so the regular tier retargets from the old 3.5 Flash to the newest 3.6 Flash.
# (agy's ids are `gemini-<ver>-<family>-<effort>`; the old "Gemini 3.5 Flash (High)" display
# label is NOT in `agy models` — hoisted here so EXECUTOR_MODEL_OVERRIDES can reference it.)
GEMINI_IMPLEMENTER_MODEL = "gemini-3.6-flash"
PI_AUTO_ROUTED_MODEL = "auto"
# xAI-family grok executor default (GROKEXEC). Single source for the grok live
# adapter model alias; the grok CLI takes it verbatim via `-m`.
GROK_DEFAULT_MODEL = "grok-4.5"  # model-id-source: SSOT constant definition (can't reference itself)

DEFAULT_PROFILES = {
    "roadmap": (OPENAI_HEAVY_MODEL, "high"),
    "plan": (OPENAI_HEAVY_MODEL, "high"),
    "execute": (OPENAI_HEAVY_MODEL, "medium"),
    "repair": (OPENAI_HEAVY_MODEL, "medium"),
    "review": (OPENAI_HEAVY_MODEL, "high"),
    "skill-maintenance": (OPENAI_HEAVY_MODEL, "high"),
}

ACTION_WORK_UNITS = {
    "roadmap": "roadmap_build",
    "plan": "phase_plan",
    "execute": "lane_execute",
    "repair": "repair",
    "review": "lane_review",
    "maintain-skills": "phase_verify",
}

EXECUTOR_MODEL_OVERRIDES = {
    "claude": {
        # Consiliency/agent-harness#310: authoring/supervision use heavy Opus,
        # review/advice/security use ultra Fable, and implementation stays regular.
        "roadmap": CLAUDE_HEAVY_MODEL,
        "plan": CLAUDE_HEAVY_MODEL,
        "execute": CLAUDE_REGULAR_MODEL,
        "repair": CLAUDE_REGULAR_MODEL,
        "review": CLAUDE_ULTRA_MODEL,
    },
    # codex is the fleet's DEFAULT execute executor. Give it an explicit executor-
    # default map mirroring claude's (CR round 3): planning/review → heavy (ultra-
    # else-heavy == gpt-5.6-sol), implementation → the regular model (gpt-5.6-terra).
    # These constants ARE the tier matrix's codex source (CODEX_HEAVY/REGULAR), so this
    # AGREES with resolve() — previously codex fell through to DEFAULT_PROFILES (heavy)
    # and the DELEGATED-CHILD / HARNESS-LANE seams launched implementation on sol.
    "codex": {
        "roadmap": OPENAI_HEAVY_MODEL,
        "plan": OPENAI_HEAVY_MODEL,
        "execute": OPENAI_IMPLEMENTER_MODEL,
        "repair": OPENAI_IMPLEMENTER_MODEL,
        "review": OPENAI_HEAVY_MODEL,
    },
    # opencode is launch-live (promotion_status="live", first-class --executor opencode,
    # harness-lane accepts it). Mirror the codex/claude fix (CR round 3): implementation
    # → the regular model (openai/gpt-5.6-terra), planning/review → heavy — so the
    # executor path AGREES with CLASS_MODEL_OVERRIDES["opencode"]["implementer"].
    # Previously all actions mapped to sol, so the harness-lane seam launched
    # implementation on HEAVY while the main seam resolved terra (intra-vendor split).
    "opencode": {
        "roadmap": OPENCODE_OPENAI_HEAVY_MODEL,
        "plan": OPENCODE_OPENAI_HEAVY_MODEL,
        "execute": OPENCODE_OPENAI_IMPLEMENTER_MODEL,
        "repair": OPENCODE_OPENAI_IMPLEMENTER_MODEL,
        "review": OPENCODE_OPENAI_HEAVY_MODEL,
    },
    # gemini is launch-live. CR round-4: implementation must NOT use the broad `auto`
    # alias — _gemini_cli_model('auto') collapses to the Pro (HEAVY) argv, so the
    # delegated-child / harness-lane seams were launching implementation on Pro while
    # the main seam launched Flash. execute/repair → the validated Flash implementer
    # name (== the class map), planning/review → `pro` (heavy, agrees with the class map).
    "gemini": {
        "roadmap": GEMINI_PRO_ROUTED_MODEL,
        "plan": GEMINI_PRO_ROUTED_MODEL,
        "execute": GEMINI_IMPLEMENTER_MODEL,
        "repair": GEMINI_IMPLEMENTER_MODEL,
        "review": GEMINI_PRO_ROUTED_MODEL,
    },
    "grok": {
        "roadmap": GROK_DEFAULT_MODEL,
        "plan": GROK_DEFAULT_MODEL,
        "execute": GROK_DEFAULT_MODEL,
        "repair": GROK_DEFAULT_MODEL,
        "review": GROK_DEFAULT_MODEL,
    },
    "pi": {
        "roadmap": PI_AUTO_ROUTED_MODEL,
        "plan": PI_AUTO_ROUTED_MODEL,
        "execute": PI_AUTO_ROUTED_MODEL,
        "repair": PI_AUTO_ROUTED_MODEL,
        "review": PI_AUTO_ROUTED_MODEL,
    },
}

# Executor-path effort overrides. Consiliency/agent-harness#310 binds Claude
# authoring/review to max and normal implementation/repair to high. Other
# providers receive the same action policy through SHIPPED_MODEL_POLICY and
# normalize or translate only at their documented provider/adapter boundary.
EXECUTOR_EFFORT_OVERRIDES = {
    "claude": {
        "roadmap": "max",
        "plan": "max",
        "execute": "high",
        "repair": "high",
        "review": "max",
    },
}

# --- model-routing-v1: vendor-agnostic model_class -> concrete model ----------
# Where a provider exposes no separate implementer/worker tier, all classes map
# to its single model (pi). Non-`phase-loop-` model strings pass through
# `_resolve_policy_model` unchanged for every executor (claude/codex have no
# model_aliases; gemini/pi pass through non-alias strings), so these resolve.
# CLAUDE_IMPLEMENTER_MODEL is an ALIAS of the regular tier constant (not a second
# literal) so the two can never drift (CR nit F) — kept as a named symbol only
# because panel_invoker imports it. The old CLAUDE_WORKER_MODEL (undated
# `claude-haiku-4-5`) is RETIRED — the worker class now derives to the lite tier's
# DATED pin (CLAUDE_LITE_MODEL); an undated id is the floating-alias shape the
# pin-only rule rejects (design-model-tier-taxonomy.md).
CLAUDE_IMPLEMENTER_MODEL = CLAUDE_REGULAR_MODEL
# OPENAI_IMPLEMENTER_MODEL is defined near OPENAI_HEAVY_MODEL at the top of this
# module (hoisted so EXECUTOR_MODEL_OVERRIDES can reference it).
OPENAI_WORKER_MODEL = "gpt-5.6-luna"
# OPENCODE_OPENAI_IMPLEMENTER_MODEL is hoisted near OPENCODE_OPENAI_HEAVY_MODEL (top).
OPENCODE_OPENAI_WORKER_MODEL = "openai/gpt-5.6-luna"
# Gemini authoring/review stays on the CLI `pro` alias. Implementation uses the
# base `gemini-3.6-flash` id on both class and executor paths; the adapter appends
# the policy-normalized effort. Worker (lite) uses the canonical
# agy 3.5 Flash id: `agy models` exposes NO flash-lite, so the matrix's gemini-3.5-flash-lite
# lite cell is ASPIRATIONAL (target, not live) — the live worker degrades to real 3.5 Flash,
# named in the deferral below (a real version/family gap, like grok-4.3, NOT representational).
GEMINI_WORKER_MODEL = "gemini-3.5-flash-high"

# CLASS_MODEL_OVERRIDES + resolve_model_class are defined BELOW the tier matrix
# (see "class↔tier bridge"), so the claude/codex class mappings can DERIVE from
# TIER_MODELS instead of duplicating literals (design-model-tier-taxonomy.md CR).


# ===========================================================================
# Model-tier taxonomy (design-model-tier-taxonomy.md)
#
# A first-class `role -> tier -> (vendor -> model_id)` resolution, ADDITIVE to
# (not replacing) the legacy MODEL_CLASSES / CLASS_MODEL_OVERRIDES machinery
# above — the two coexist during the migration. The four tiers are the vocabulary
# frozen in `models.MODEL_TIERS`; "tier" here is the model-capability band and is
# lexically distinct from the audit-evidence `--tier-N` budgets (see the
# MODEL_TIERS definition-site note in models.py).
#
# PIN where the vendor publishes immutable ids: claude (dateless per-gen snapshots)
# and codex (gpt-5.6-<name>) are pinned canonical literals — no floating aliases
# (`gpt-5.6`, `gemini-flash-latest`, `-latest`). Two exceptions are marked
# `volatile=True` in the matrix: gemini heavy (a PREVIEW id) and ALL grok cells (xAI
# ships no dated snapshot; bare ids float to latest stable — blocker 2). A version
# bump is a single-line edit to one of these constants.
#
# NON-CLAUDE ULTRA: only Claude ships a distinct ultra model. For codex/gemini/grok
# the "ultra" band IS the heavy model run at `effort=max` (OpenAI Sol-Pro, grok
# high-reasoning, etc. are reasoning MODES, not separate catalog ids). So the
# vendor matrices below omit an `"ultra"` entry and `resolve()` falls back to
# `(heavy_model, effort="max")` — the operator rule "ultra when available for that
# vendor, otherwise heavy".
# ===========================================================================

# Per-tier advisory defaults remain part of resolve(). Action launches use the
# explicit shipped action policy below: roadmap/plan/review request max and
# execute/repair request high, with provider and adapter normalization recorded.
_TIER_ADVISORY_EFFORT: dict[str, str] = {
    "ultra": "max",
    "heavy": "xhigh",
    "regular": "medium",
    "lite": "low",
}

# codex/OpenAI per-tier ids (reuse the existing single-source constants).
CODEX_HEAVY_MODEL = OPENAI_HEAVY_MODEL
CODEX_REGULAR_MODEL = OPENAI_IMPLEMENTER_MODEL
CODEX_LITE_MODEL = OPENAI_WORKER_MODEL

# gemini/Google per-tier ids — API-style canonical ids (NOT the CLI routing
# aliases `pro`/`auto` or the display label used by the legacy class overrides).
# heavy is a PREVIEW model (Google already retired gemini-3-pro-preview) → marked
# volatile in the matrix; regular/lite are stable GA ids.
GEMINI_HEAVY_MODEL = "gemini-3.1-pro-preview"
GEMINI_REGULAR_MODEL = "gemini-3.6-flash"
GEMINI_LITE_MODEL = "gemini-3.5-flash-lite"

# grok/xAI per-tier ids. heavy reuses the existing GROK_DEFAULT_MODEL SSOT.
# VOLATILE: xAI publishes NO dated snapshot for these — a bare `grok-4.5`/`grok-4.3`
# id tracks the latest stable build per xAI docs, so these are NOT immutable pins.
# All grok tier cells are marked volatile below; repin to dated ids when xAI ships
# them (design-model-tier-taxonomy.md CR, blocker 2).
GROK_HEAVY_MODEL = GROK_DEFAULT_MODEL
GROK_REGULAR_MODEL = "grok-4.3"
GROK_LITE_MODEL = "grok-build-0.1"


@dataclass(frozen=True)
class TierModel:
    """One (model_id, effort, volatile) cell of the per-vendor tier matrix."""

    model_id: str
    effort: str
    volatile: bool = False


@dataclass(frozen=True)
class TierResolution:
    """Result of `resolve(role, vendor)`: the resolved tier plus its model id,
    ADVISORY effort (see _TIER_ADVISORY_EFFORT), and volatility marker. `.model_id`/`.effort` are the
    primary outputs; `.volatile` flags a preview/hot-swappable id (gemini heavy)."""

    tier: str
    model_id: str
    effort: str
    volatile: bool = False


# The per-vendor tier matrix. `ultra` is present ONLY for claude; every other
# vendor's ultra resolves to its heavy model @ max via resolve()'s fallback.
TIER_MODELS: dict[str, dict[str, TierModel]] = {
    "claude": {
        "ultra": TierModel(CLAUDE_ULTRA_MODEL, _TIER_ADVISORY_EFFORT["ultra"]),
        "heavy": TierModel(CLAUDE_HEAVY_MODEL, _TIER_ADVISORY_EFFORT["heavy"]),
        "regular": TierModel(CLAUDE_REGULAR_MODEL, _TIER_ADVISORY_EFFORT["regular"]),
        "lite": TierModel(CLAUDE_LITE_MODEL, _TIER_ADVISORY_EFFORT["lite"]),
    },
    "codex": {
        "heavy": TierModel(CODEX_HEAVY_MODEL, _TIER_ADVISORY_EFFORT["heavy"]),
        "regular": TierModel(CODEX_REGULAR_MODEL, _TIER_ADVISORY_EFFORT["regular"]),
        "lite": TierModel(CODEX_LITE_MODEL, _TIER_ADVISORY_EFFORT["lite"]),
    },
    "gemini": {
        "heavy": TierModel(GEMINI_HEAVY_MODEL, _TIER_ADVISORY_EFFORT["heavy"], volatile=True),
        "regular": TierModel(GEMINI_REGULAR_MODEL, _TIER_ADVISORY_EFFORT["regular"]),
        "lite": TierModel(GEMINI_LITE_MODEL, _TIER_ADVISORY_EFFORT["lite"]),
    },
    # grok: ALL cells volatile — xAI publishes no dated snapshot, bare ids float to
    # latest stable (blocker 2). NOTE: grok's LIVE class/executor routing stays
    # single-model (GROK_DEFAULT_MODEL = grok-4.5) by grok's documented design; these
    # per-tier ids are the taxonomy target, consulted via resolve(), not yet the live
    # grok class path (deferred — see CLASS_MODEL_OVERRIDES: claude+codex derived).
    "grok": {
        "heavy": TierModel(GROK_HEAVY_MODEL, _TIER_ADVISORY_EFFORT["heavy"], volatile=True),
        "regular": TierModel(GROK_REGULAR_MODEL, _TIER_ADVISORY_EFFORT["regular"], volatile=True),
        "lite": TierModel(GROK_LITE_MODEL, _TIER_ADVISORY_EFFORT["lite"], volatile=True),
    },
}

TIER_VENDORS: tuple[str, ...] = tuple(TIER_MODELS.keys())

# The supervise role (run-train coordinator + phase-loop runner orchestrator) maps to
# the heavy tier. ADVISORY PROVENANCE ONLY (design item 7, CR round-3 correction): there
# is no programmatic coordinator launch that sets a model — the coordinator IS the
# ambient CLI session (per-node run_loop launches its own phase executors). This tier is
# recorded on the coordinator's review artifact via supervise_selection(); an operator
# running the supervisor session should be on the heavy model (Opus 5).
SUPERVISOR_TIER = "heavy"

# Role -> tier. Roles are the product-loop actions plus `supervise` and the
# cheap/worker high-volume band. resolve() ALSO accepts a bare tier name (any
# member of MODEL_TIERS) as `role`, so callers can address a tier directly.
ROLE_TIERS: dict[str, str] = {
    "roadmap": "heavy",
    "plan": "heavy",
    "review": "ultra",
    "advise": "ultra",
    "security": "ultra",
    "supervise": SUPERVISOR_TIER,
    "execute": "regular",
    "repair": "regular",
    "worker": "lite",
    "cheap": "lite",
}


def tier_for_role(role: str) -> str:
    """The model tier a role maps to. A bare tier name passes through."""
    if role in MODEL_TIERS:
        return role
    tier = ROLE_TIERS.get(role)
    if tier is None:
        raise ValueError(f"unknown model-tier role: {role}")
    return tier


def resolve(role: str, vendor: str) -> TierResolution:
    """Resolve `(role, vendor)` to `(model_id, effort)` (+ tier + volatile marker).

    `role` is either a product role (roadmap/plan/review/execute/repair/supervise/
    worker/…) or a bare tier name (ultra/heavy/regular/lite). `vendor` is one of
    claude/codex/gemini/grok.

    ULTRA FALLBACK: for a non-claude vendor the ultra tier resolves to that
    vendor's heavy model at `effort=max` (there is no separate ultra catalog id).
    """
    if vendor not in TIER_MODELS:
        raise ValueError(f"unknown model-tier vendor: {vendor}")
    tier = tier_for_role(role)
    vendor_matrix = TIER_MODELS[vendor]
    if tier == "ultra" and "ultra" not in vendor_matrix:
        # ultra-else-heavy@max for codex/gemini/grok.
        heavy = vendor_matrix["heavy"]
        return TierResolution(
            tier="ultra",
            model_id=heavy.model_id,
            effort=_TIER_ADVISORY_EFFORT["ultra"],
            volatile=heavy.volatile,
        )
    cell = vendor_matrix[tier]
    return TierResolution(
        tier=tier,
        model_id=cell.model_id,
        effort=cell.effort,
        volatile=cell.volatile,
    )


def supervise_selection(vendor: str = "claude") -> TierResolution:
    """The supervise-tier binding for a coordinator/orchestrator on `vendor`.

    ADVISORY PROVENANCE ONLY (design item 7, CR round-3 correction): there is no
    programmatic coordinator launch that sets a model — `run_train` launches per-NODE
    `run_loop` phase executors (each with its own tier model), and the coordinator /
    phase-loop-runner orchestrator is CLI/ambient-invoked with an OPERATOR-selected
    model. So this does not BIND a launch; the run-train coordinator records the
    supervise tier on its review artifact as provenance (the operator running the
    supervisor session should be on the heavy model, Opus 5)."""
    return resolve(SUPERVISOR_TIER, vendor)


# --- class↔tier bridge: derive the legacy class overrides from the matrix -----
# The MODEL_CLASSES axis maps authoring, evaluation, implementation, and worker
# roles onto model tiers so the
# class path and the tier path can never DIVERGE on the same decision (the CR's
# blocker). CONVERGED VENDORS — claude + codex: their class models are API-id-shaped,
# so CLASS_MODEL_OVERRIDES DERIVES from TIER_MODELS via this bridge AND their
# EXECUTOR_MODEL_OVERRIDES entries use the same tier-matrix constants — so BOTH the
# class path and the executor-default path agree with resolve() for every action
# (enforced by tests/test_model_tier_taxonomy.py::TierLiveWiringTest).
# DEFERRED vendor×path pairs — LIVE routing NOT sourced from the matrix (accurate
# enumeration; each is intentional, with the reason it can't be a one-line derive):
#   • gemini — the MODEL-PATH split is FIXED (CR round-4) and the REGULAR VERSION is now
#     ALIGNED (CR round-5 finding B): implementation on BOTH the class and executor paths
#     stores the base `gemini-3.6-flash` id; the adapter appends the normalized
#     effort to emit agy's canonical id. Two things remain: (a) the PRO/
#     planning path still routes via the `pro` CLI alias / "Gemini 3.1 Pro (High)" DISPLAY
#     label rather than a canonical agy id — REPRESENTATIONAL only (same Pro model), and out
#     of this fix's scope; (b) LITE is ASPIRATIONAL — `agy models` exposes NO flash-lite, so
#     the matrix's gemini-3.5-flash-lite lite cell is a TARGET, not live; the live worker
#     degrades to the real agy 3.5 Flash (gemini-3.5-flash-high). This is a genuine
#     version/family divergence (like grok-4.3), NOT representational — repin the lite cell
#     when agy ships a flash-lite id.
#   • grok class path AND grok executor path — GROK_DEFAULT_MODEL (grok-4.5) for every
#     class/action by grok's documented SINGLE-MODEL design; the per-tier matrix ids
#     (grok-4.3/grok-build-0.1, all volatile) are the taxonomy target, not yet live.
#   • opencode — NO LONGER a bypass: its class AND executor paths now AGREE (both use
#     the provider-qualified `openai/gpt-5.6-{sol,terra,luna}` at heavy/regular/lite;
#     execute/repair → terra, planning/review → sol; CR round-4 fix). It is not DERIVED
#     from TIER_MODELS only because opencode is not a tier-matrix vendor (its ids carry
#     the `openai/` transport prefix); the mapping is hand-maintained but tier-consistent.
#   • pi class path AND pi executor path — both the `auto` router alias (pi has no
#     separate per-tier model; both paths use the single alias, so no intra-vendor split).
#   • `command` executor — LAUNCH-CAPABLE (its `{model}` is a renderable command-template
#     placeholder via _render_command_template, so the model CAN reach a live argv when an
#     operator template uses `{model}`), but has NO defined tier value (not a tier vendor),
#     so it stays on the DEFAULT_PROFILES heavy default — SEAM-CONSISTENT (same value on
#     every seam, no intra-vendor split). Named here as an accepted no-tier case. Weaker
#     channel-class residue (N3): `{model}` is OPTIONAL in a command template (only
#     `{context_file}` is required), so an operator template that OMITS it records
#     selected_model while binding nothing, with no unbound stamp — operator-authored, not a
#     production default; stamping it is tracked as agent-harness#307.
#   • MAINTENANCE seam (CR round-5 finding 1) — `maintain-skills` runs via
#     maintenance.py:run_maintenance, which calls resolve_profile("skill-maintenance")
#     → DEFAULT_PROFILES = (gpt-5.6-sol, high) → build_codex_command, bypassing BOTH the
#     class path and the executor path (no resolve_profile_for_executor, no policy layer).
#     It hardwires codex on the HEAVY model. ACCEPTED: maintain-skills is not execute/repair,
#     ROLE_TIERS defines no tier for it, and it is seam-consistent (fixed codex). Latent
#     note: resolve_profile_for_executor("maintain-skills", executor≠codex) would return
#     gpt-5.6-sol via DEFAULT_PROFILES — unreachable today (maintain-skills is codex-fixed)
#     but live code.
#   • claude CHANNEL route (CR round-5 finding 3) — the PRODUCTION-DEFAULT interactive route
#     (`claude-channel send`) binds NO `--model` (the print/agent_view routes DO). A send into
#     an EXISTING claude session cannot rebind that session's model, so implementation on the
#     channel route runs on the operator's ambient session model, NOT the resolved tier model.
#     TRANSPORT-INHERENT carve-out (same logic as the supervise carve-out). The channel
#     LaunchSpec stamps a `session_model_unbound` provenance warning so selected_model is not
#     read as a bound guarantee (see launcher._CHANNEL_SESSION_MODEL_UNBOUND_WARNING).
#   • ESCALATION-CEILING divergence (CR round-8/9 finding A-ii) — NAMED, not aligned, because the
#     two ladders are DIFFERENT with different CEILINGS: (1) the class-escalation ladder
#     (governed_premerge.next_escalation / _NEXT_CLASS: worker→implementer→planner) is applied
#     by the repair-loop policy boundary after repeated governed failures, unless an explicit
#     operator model wins; its ceiling is the PLANNER class = the HEAVY model
#     (claude-opus-5). (2) the
#     claude-execute-phase skill's in-lane retry-tier ladder (fast→strong→frontier) has a
#     ceiling of `frontier` = the HEAVY model (claude-opus-5). This comment states the two
#     CEILINGS only — it makes NO claim about when/whether the retry-tier ladder takes effect
#     (that is skill/runner behavior it does not own; see the skill for its retry semantics).
# MODEL-PATH BYPASS CLASS — CLOSED or NAMED across the FOUR phase-executor RESOLUTION seams
# (main-loop, delegated-child runner.py:4894, harness-lane runner.py:5554, maintenance). These
# are the only four seams that RESOLVE a model; worker_pool.py executes LaunchSpecs the main
# seam already resolved (a parallel TRANSPORT, no resolution of its own), and the runner
# resolve_profile calls at runner.py:1358/1458 feed BLOCKED-path snapshots only (no launch).
# No phase executor SILENTLY launches implementation on a heavier model than its regular tier:
# for the tier vendors the class + executor paths agree; the remaining listed cases are either
# REPRESENTATIONAL (aliases / display labels / provider-prefixes that are tier-consistent but
# not literally the matrix ids), or the named no-tier seams (command, maintenance) and the
# transport carve-out (channel). EXCEPT grok: grok's intentional SINGLE-MODEL routing runs
# implementation on grok-4.5 (its HEAVY cell) — NAMED above; the taxonomy's grok-4.3 regular
# target is not yet live. There are TWO named model disagreements (grok single-model; gemini
# LITE aspirational — agy exposes no flash-lite), not one. Panel/advisor legs
# (panel_invoker.DEFAULT_LEG_MODELS = fable-5 / sol / 3.1-Pro / grok-4.5) are a SEPARATE
# model-bearing surface (review-only), NOT a phase-executor resolution seam — their defaults
# are the ultra-else-heavy reviewer set, tier-correct and not a routing bypass.
# Effort is bound by shipped action policy and recorded at requested, policy,
# and adapter-effective layers. Migrating the representational cases wholesale
# is out of scope.
_CLASS_TIER_BRIDGE: dict[str, str] = {
    "planner": "heavy",
    "reviewer": "ultra",    # ultra-else-heavy@max via resolve()
    "implementer": "regular",
    "worker": "lite",
}


def _class_model_from_tier(vendor: str, model_class: str) -> str:
    """The concrete model for `(vendor, model_class)`, sourced from TIER_MODELS."""
    return resolve(_CLASS_TIER_BRIDGE[model_class], vendor).model_id


def _derived_class_overrides(vendor: str) -> dict[str, str]:
    return {mc: _class_model_from_tier(vendor, mc) for mc in _CLASS_TIER_BRIDGE}


CLASS_MODEL_OVERRIDES = {
    # claude + codex: DERIVED from the tier matrix (planner←heavy,
    # reviewer←ultra, implementer←regular, worker←lite).
    "claude": _derived_class_overrides("claude"),
    "codex": _derived_class_overrides("codex"),
    "opencode": {
        "planner": OPENCODE_OPENAI_HEAVY_MODEL,
        "reviewer": OPENCODE_OPENAI_HEAVY_MODEL,
        "implementer": OPENCODE_OPENAI_IMPLEMENTER_MODEL,
        "worker": OPENCODE_OPENAI_WORKER_MODEL,
    },
    "gemini": {
        "planner": GEMINI_PRO_ROUTED_MODEL,
        "reviewer": GEMINI_PRO_ROUTED_MODEL,
        "implementer": GEMINI_IMPLEMENTER_MODEL,
        "worker": GEMINI_WORKER_MODEL,
    },
    # grok exposes no separate implementer/worker tier — every class maps to its
    # single model (like pi), passed through the CLI's `-m` verbatim. Its per-tier
    # matrix ids (grok-4.3/grok-build-0.1) are the taxonomy target, not yet live.
    "grok": {
        "planner": GROK_DEFAULT_MODEL,
        "reviewer": GROK_DEFAULT_MODEL,
        "implementer": GROK_DEFAULT_MODEL,
        "worker": GROK_DEFAULT_MODEL,
    },
    "pi": {
        "planner": PI_AUTO_ROUTED_MODEL,
        "reviewer": PI_AUTO_ROUTED_MODEL,
        "implementer": PI_AUTO_ROUTED_MODEL,
        "worker": PI_AUTO_ROUTED_MODEL,
    },
}


def resolve_model_class(executor: str, model_class: str) -> str | None:
    """Map (model_class, executor) -> concrete model, or None if unmapped."""
    return CLASS_MODEL_OVERRIDES.get(executor, {}).get(model_class)


@dataclass(frozen=True)
class ModelClassEscalationApplication:
    policy: ResolvedExecutionPolicy
    applied: bool
    action: str
    from_model_class: str | None
    model_class: str
    from_model: str
    effective_model: str
    reason: str
    not_applied_reason: str | None = None


def apply_model_class_escalation(
    policy: ResolvedExecutionPolicy,
    *,
    executor: str,
    decision: "EscalationDecision",
    from_model_class: str | None,
    operator_model_present: bool,
) -> ModelClassEscalationApplication:
    """Apply one typed model-class escalation without weakening operator precedence."""
    if decision.action != "escalate_class":
        return ModelClassEscalationApplication(
            policy=policy,
            applied=False,
            action=decision.action,
            from_model_class=from_model_class,
            model_class=decision.model_class,
            from_model=policy.model,
            effective_model=policy.model,
            reason=decision.reason,
            not_applied_reason="action_not_escalate_class",
        )
    if operator_model_present:
        return ModelClassEscalationApplication(
            policy=policy,
            applied=False,
            action=decision.action,
            from_model_class=from_model_class,
            model_class=decision.model_class,
            from_model=policy.model,
            effective_model=policy.model,
            reason=decision.reason,
            not_applied_reason="explicit_operator_model",
        )
    escalated_model = resolve_model_class(executor, decision.model_class)
    if escalated_model is None:
        raise ValueError(
            f"executor {executor!r} has no model mapping for escalated class "
            f"{decision.model_class!r}"
        )
    escalated = replace(
        policy,
        model=escalated_model,
        model_class=decision.model_class,
        model_source="runtime model-class escalation",
        execution_policy_override_reason=decision.reason,
    )
    return ModelClassEscalationApplication(
        policy=escalated,
        applied=True,
        action=decision.action,
        from_model_class=from_model_class,
        model_class=decision.model_class,
        from_model=policy.model,
        effective_model=escalated_model,
        reason=decision.reason,
    )


# Actions that author a final patch. The `worker` class (bounded, high-volume
# subtasks) must never own these — enforced as a routing invariant (P5).
PATCH_AUTHORING_ACTIONS: tuple[str, ...] = ("execute", "repair")


def max_effort_planner_eligible(executor: str) -> bool:
    """True iff `executor` may be represented as the max-effort PLANNER OF RECORD.

    The "planner of record" for a max-effort planning action must deliver max
    reasoning. Gemini and pi both ceiling at `high` (their `effort_map`s clamp
    `max -> high`) and express that by declaring a narrow `supported_efforts`
    (no `"max"`), so neither is eligible — each serves as a panel member instead,
    never the authoritative planner.

    ah#231 decouples this eligibility signal from run-level effort translation via
    the dedicated `planner_max_class` capability field. When a provider leaves it
    unset (`None`), eligibility DERIVES from `supported_efforts` exactly as before
    (`"max" in supported_efforts`), so gemini/pi/codex/claude/... are unchanged.
    A provider sets it explicitly to break the coupling: grok keeps a broad
    `supported_efforts` — so an explicit `max` request stays VALID and is clamped
    to grok's real `high` ceiling only at the CLI-emit boundary
    (`launcher._grok_cli_effort`, ah#224), never at the policy layer — yet declares
    `planner_max_class=False` so it is not represented as a max-effort planner.

    None of this reduces any provider's effort where it actually runs: grok (like
    gemini/pi) still runs fully at its own real ceiling as a panel/CR reviewer leg
    and as a planner for non-max efforts. This is a representational guard, not a
    selection gate — grok is never AUTOSEL-selected as the planner of record anyway
    (`resolve_dispatch_decision` does not consult eligibility); the only live reader
    is the effort max->high fallback in `resolve_execution_policy`.
    """
    capability = provider_policy_capabilities().get(executor)
    if capability is None:
        return False
    if capability.planner_max_class is not None:
        return capability.planner_max_class
    return "max" in capability.supported_efforts


# The repo's SHIPPED model_policy. THIS repo's default: planning at max,
# implementation at the implementer model. `clamp=True` resolves a sub-max
# provider's `max` request to its ceiling via the provider effort_map fallback
# (otherwise normalize_provider_effort RAISES). A downstream repo that ships no
# policy keeps the registry defaults — that empty-policy path is the back-compat
# contract (callers pass model_policy_rule=None to get it).
SHIPPED_MODEL_POLICY = {
    "roadmap": {"model_class": "planner", "effort": "max", "clamp": True},
    "plan": {"model_class": "planner", "effort": "max", "clamp": True},
    "execute": {"model_class": "implementer", "effort": "high"},
    "repair": {"model_class": "implementer", "effort": "high"},
    # design-model-tier-taxonomy.md: review is an ULTRA-tier role → max effort (was
    # high). clamp=True still resolves a sub-max provider's `max` to its ceiling.
    "review": {"model_class": "reviewer", "effort": "max", "clamp": True},
}


def shipped_model_policy_rule(action: str) -> ExecutionPolicyRule | None:
    """The shipped model_policy rule for an action, or None if unmapped."""
    spec = SHIPPED_MODEL_POLICY.get(action)
    if spec is None:
        return None
    clamp = bool(spec.get("clamp", False))
    return ExecutionPolicyRule(
        selector=action,
        action=action,
        model_class=spec.get("model_class"),
        effort=spec.get("effort"),
        unsupported_policy_behavior="fallback" if clamp else "block",
        fallback="high" if clamp else None,
        source="model_policy",
        override_reason="shipped model_policy (model-routing-v1)",
    )


def normalize_provider_effort(
    *,
    provider_key: str,
    work_unit_policy: WorkUnitPolicy,
    default_effort: str | None = None,
) -> str:
    capabilities = provider_policy_capabilities()
    if provider_key not in capabilities:
        raise ValueError(f"unknown provider policy capability: {provider_key}")

    capability = capabilities[provider_key]
    require_literal(work_unit_policy.work_unit_kind, capability.supported_work_units, "provider work-unit kind")
    requested_effort = work_unit_policy.effort or default_effort or capability.default_effort
    if requested_effort is None:
        if work_unit_policy.unsupported_policy_behavior == "inherit_default" and work_unit_policy.inherit_default:
            requested_effort = capability.default_effort
        if requested_effort is None:
            raise ValueError(f"no default effort for provider policy capability: {provider_key}")

    if requested_effort in capability.supported_efforts:
        return requested_effort

    if work_unit_policy.unsupported_policy_behavior == "inherit_default" and capability.default_effort:
        return capability.default_effort
    if work_unit_policy.unsupported_policy_behavior == "fallback" and work_unit_policy.fallback:
        fallback_effort = capability.effort_map.get(work_unit_policy.fallback, work_unit_policy.fallback)
        if fallback_effort in capability.supported_efforts:
            return fallback_effort
    raise ValueError(f"unsupported effort `{requested_effort}` for provider `{provider_key}`")


def resolve_profile(profile: str, model: str | None = None, effort: str | None = None) -> ModelSelection:
    default_model, default_effort = DEFAULT_PROFILES[profile]
    selected_model = model or default_model
    selected_effort = effort or default_effort
    if model or effort:
        return ModelSelection(
            profile=profile,
            model=selected_model,
            effort=selected_effort,
            source="user_override",
            override_reason="user supplied --model or --effort",
        )
    return ModelSelection(profile=profile, model=selected_model, effort=selected_effort)


def resolve_profile_for_executor(
    *,
    action: str,
    executor: str,
    profile: str | None = None,
    model: str | None = None,
    effort: str | None = None,
) -> ModelSelection:
    selected_profile = profile or default_model_profile_for_executor(action, executor)
    selection = resolve_profile(selected_profile, model=model, effort=effort)
    if model is not None:
        return selection
    executor_default = EXECUTOR_MODEL_OVERRIDES.get(executor, {}).get(action)
    effort_default = EXECUTOR_EFFORT_OVERRIDES.get(executor, {}).get(action)
    if not executor_default and not effort_default:
        return selection
    return ModelSelection(
        profile=selection.profile,
        model=executor_default or selection.model,
        effort=effort or effort_default or selection.effort,
        source=f"{executor}_default",
        override_reason=f"{executor} live adapter default model alias",
    )


def resolve_execution_policy(
    *,
    action: str,
    executor: str,
    model_selection: ModelSelection,
    operator_model: str | None = None,
    operator_effort: str | None = None,
    plan_policy: ExecutionPolicyRule | None = None,
    roadmap_policy: ExecutionPolicyRule | None = None,
    model_policy_rule: ExecutionPolicyRule | None = None,
    lane: str | None = None,
) -> ResolvedExecutionPolicy:
    require_literal(action, tuple(ACTION_WORK_UNITS.keys()), "execution policy action")
    policy, source = _merge_policies(plan_policy, roadmap_policy, model_policy_rule)
    if _claude_model_needs_claude_executor(executor, model_selection.model, policy):
        executor = "claude"
    work_unit_kind = (
        (policy.work_unit_kind if policy else None)
        or ACTION_WORK_UNITS[action]
    )
    policy_executor = executor
    executor_source = "dispatch decision"
    policy_model = model_selection.model
    model_source = model_selection.source
    policy_effort = model_selection.effort
    effort_source = model_selection.source
    fallback = policy.fallback if policy else None
    fallback_source = source or "registry defaults"
    unsupported_behavior = policy.unsupported_policy_behavior if policy else "block"
    override_reason = policy.override_reason if policy else model_selection.override_reason

    if policy is not None:
        if policy.executor is not None:
            policy_executor = policy.executor
            executor_source = source or policy.source
        if policy.model is not None:
            policy_model = policy.model
            model_source = source or policy.source
        elif policy.model_class is not None:
            # model_class -> concrete model for the resolved executor. An
            # explicit `model` always wins; a class only fills in when no model
            # is given (model-routing-v1).
            class_model = resolve_model_class(policy_executor, policy.model_class)
            if class_model is not None:
                policy_model = class_model
                model_source = source or policy.source
        if policy.effort is not None:
            policy_effort = policy.effort
            effort_source = source or policy.source

    if operator_model is not None:
        policy_model = operator_model
        model_source = "CLI/operator override"
        override_reason = "operator supplied --model"
    if operator_effort is not None:
        policy_effort = operator_effort
        effort_source = "CLI/operator override"
        override_reason = "operator supplied --effort"

    # model-routing-v1 guard (wired, not just asserted): an executor whose
    # planner-class model cannot actually run at `max` (gemini/pi) must never be
    # the max-effort planner of record. Force the clamp so its `max` request
    # resolves to the provider ceiling instead of raising, regardless of whether
    # the policy opted into a fallback. This makes the effort clamp + this guard
    # jointly enforce the invariant at the dispatch-resolution boundary.
    policy_model_class = policy.model_class if policy else None
    if (
        policy_model_class == "planner"
        and policy_effort == "max"
        and not max_effort_planner_eligible(policy_executor)
    ):
        unsupported_behavior = "fallback"
        if not fallback:
            fallback = "high"

    work_unit_policy = WorkUnitPolicy(
        work_unit_kind=work_unit_kind,
        effort=policy_effort,
        unsupported_policy_behavior=unsupported_behavior,
        fallback=fallback,
        inherit_default=bool(policy.inherit_default) if policy else False,
    )
    normalized_effort = normalize_provider_effort(
        provider_key=policy_executor,
        work_unit_policy=work_unit_policy,
        default_effort=model_selection.effort,
    )
    fallback_applied = normalized_effort != policy_effort
    resolved_model = _resolve_policy_model(policy_executor, work_unit_kind, policy_model, fallback, unsupported_behavior)
    return ResolvedExecutionPolicy(
        action=action,
        lane=lane,
        executor=policy_executor,
        model=resolved_model,
        effort=normalized_effort,
        work_unit_kind=work_unit_kind,
        fallback=fallback,
        unsupported_policy_behavior=unsupported_behavior,
        execution_policy_source=source or "registry defaults",
        execution_policy_override_reason=override_reason,
        executor_source=executor_source,
        model_source=model_source,
        effort_source=effort_source,
        fallback_source=fallback_source,
        fallback_applied=fallback_applied,
        model_class=policy.model_class if policy else None,
        requested_effort=policy_effort,
        policy_effort=normalized_effort,
    )


def _claude_model_needs_claude_executor(
    executor: str,
    model: str,
    policy: ExecutionPolicyRule | None,
) -> bool:
    if executor != "pi":
        return False
    if policy is not None and policy.executor == "pi" and policy.override_reason:
        return False
    return model.lower().startswith(("claude", "anthropic/claude"))


def resolve_model_selection_from_policy(
    *,
    profile: str,
    resolved_policy: ResolvedExecutionPolicy,
) -> ModelSelection:
    return ModelSelection(
        profile=profile,
        model=resolved_policy.model,
        effort=resolved_policy.effort,
        source=resolved_policy.execution_policy_source,
        override_reason=resolved_policy.execution_policy_override_reason,
        model_class=resolved_policy.model_class,
        requested_effort=resolved_policy.requested_effort or resolved_policy.effort,
        policy_effort=resolved_policy.policy_effort or resolved_policy.effort,
    )


def _merge_policies(
    plan_policy: ExecutionPolicyRule | None,
    roadmap_policy: ExecutionPolicyRule | None,
    model_policy_rule: ExecutionPolicyRule | None = None,
) -> tuple[ExecutionPolicyRule | None, str | None]:
    # Precedence: plan > roadmap > model_policy > registry defaults — but LAYERED,
    # not winner-take-all. A higher-precedence policy overrides only the fields it
    # specifies; the rest fall through to the lower layer. This is the fix for the
    # tiering-bypass bug: a plan policy that pins only `executor=`/`effort=` (no
    # model/model_class) still inherits the shipped model_policy's `model_class`
    # and its clamp, instead of silently reverting to the registry heavy model.
    layers = [
        (model_policy_rule, "model_policy"),
        (roadmap_policy, "roadmap policy"),
        (plan_policy, "phase-plan policy"),
    ]
    present = [(rule, src) for rule, src in layers if rule is not None]
    if not present:
        return None, None
    top_rule, top_source = present[-1]
    merged: dict[str, object] = {
        "selector": top_rule.selector,
        "action": top_rule.action,
        "lane": top_rule.lane,
        "executor": None,
        "model": None,
        "model_class": None,
        "effort": None,
        "work_unit_kind": None,
        "unsupported_policy_behavior": "block",
        "fallback": None,
        "inherit_default": False,
        "source": top_source,
        "override_reason": None,
    }
    for rule, _src in present:  # low → high overlay
        for field_name in ("executor", "model", "model_class", "effort",
                           "work_unit_kind", "fallback", "override_reason", "action", "lane"):
            value = getattr(rule, field_name)
            if value is not None:
                merged[field_name] = value
        if rule.unsupported_policy_behavior and rule.unsupported_policy_behavior != "block":
            merged["unsupported_policy_behavior"] = rule.unsupported_policy_behavior
        if rule.inherit_default:
            merged["inherit_default"] = True
    return ExecutionPolicyRule(**merged), top_source


def _resolve_policy_model(
    executor: str,
    work_unit_kind: str,
    model: str,
    fallback: str | None,
    unsupported_behavior: str,
) -> str:
    capability = provider_policy_capabilities()[executor]
    if not capability.model_aliases:
        return model
    allowed = set(capability.model_aliases.values())
    default_alias = capability.model_aliases.get(work_unit_kind)
    if model in allowed:
        return model
    if unsupported_behavior == "inherit_default" and default_alias:
        return default_alias
    if unsupported_behavior == "fallback" and fallback in allowed:
        return fallback
    if model.startswith("phase-loop-"):
        raise ValueError(f"unsupported model `{model}` for provider `{executor}`")
    return model
