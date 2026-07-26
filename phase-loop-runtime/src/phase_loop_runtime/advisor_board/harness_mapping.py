"""Per-harness model/effort -> invocation mapping (IF-0-ABDFREEZE-1).

Effort reaches each subscription CLI differently. The model-first
``{model, effort}`` split therefore needs one per-harness mapping that turns a
canonical pair into the exact invocation token shared by launcher and board paths:

    claude  -> effort flag        ``--effort max``
    codex   -> config override    ``-c model_reasoning_effort=xhigh``
    gemini  -> model-name embed   ``gemini-3.6-flash-high``
    grok    -> effort flag        ``--reasoning-effort high``

Legacy Gemini Pro display names remain supported for explicit boards.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .schema import EFFORT_LEVELS


class EffortMappingError(NotImplementedError):
    """Raised when a harness's effort mapping is not frozen here (breadth lanes
    land in ABDREG/ABDHOME/ABDOMNI)."""


# Effort mechanism: HOW the effort reaches the CLI for a harness.
MECH_FLAG = "flag"          # a dedicated flag, e.g. claude ``--effort <level>``
MECH_CONFIG = "config"      # a ``-c key=value`` override, e.g. codex reasoning
MECH_MODEL_NAME = "model_name"  # baked into the model string, e.g. agy/gemini


@dataclass(frozen=True)
class SeatInvocation:
    """The frozen, harness-specific shape ``(model, effort)`` renders to.

    ``model``        the model string to pass to the CLI (effort-embedded for the
                     ``model_name`` mechanism; otherwise the model verbatim).
    ``effort_args``  extra CLI args carrying effort (empty for ``model_name``).
    ``mechanism``    one of ``MECH_FLAG`` / ``MECH_CONFIG`` / ``MECH_MODEL_NAME``.
    ``harness``      the execution lane this rendering targets.
    """

    harness: str
    model: str
    effort_args: tuple[str, ...]
    mechanism: str


# canonical effort -> codex ``model_reasoning_effort`` token. codex's max reasoning
# is ``xhigh`` (panel_invoker.py:992), so canonical ``max`` -> ``xhigh``.
_CODEX_EFFORT: dict[str, str] = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "max": "xhigh",
}

# canonical effort -> grok ``--reasoning-effort`` token. The grok CLI accepts ONLY
# ``high | medium | low`` (verified via an out-of-range probe: ``--reasoning-effort max``
# -> ``unknown effort level 'max'; use one of: high, medium, low``). So canonical ``max``
# CLAMPS to grok's own ``high`` ceiling — the panel's grok seat runs at grok-4.5's maximum
# reasoning. (ah#222: a prior literal ``max`` made the grok leg ERROR on every default panel
# run.) The grokexec/launcher grok effort path is separate (capability_registry) — not fixed here.
#
# ah#231: kept as an OVERRIDES map (only the entries that don't pass through unchanged) plus a
# ``.get``-with-clamp lookup below, matching ``launcher._GROK_CLI_EFFORT_OVERRIDES`` /
# ``_grok_cli_effort`` VERBATIM (same keys, same values) for parity: the panel and the launcher
# must clamp the same canonical effort to the same grok CLI token. Direct ``_GROK_EFFORT[effort]``
# indexing (the prior form) would ``KeyError`` on any effort outside its literal 4-key set (e.g.
# if the panel effort vocabulary ever grows past today's ``EFFORT_LEVELS`` to include
# ``minimal``/``xhigh``, which ``NORMALIZED_EFFORT_LEVELS`` already knows about); the ``.get`` form
# instead clamps a recognized-but-unsupported token to a valid one (and passes a genuinely unknown
# token through unchanged) so the grok leg never KeyErrors and never emits an invalid CLI token.
_GROK_EFFORT_OVERRIDES: dict[str, str] = {
    "minimal": "low",   # matches launcher._GROK_CLI_EFFORT_OVERRIDES verbatim
    "xhigh": "high",
    "max": "high",  # grok has no 'max'/'xhigh'; its ceiling is 'high'
}


def _grok_panel_effort(effort: str) -> str:
    """Map a canonical panel effort to a grok-CLI-supported token (ah#231, robust lookup).

    Low/medium/high pass through unchanged. minimal/xhigh/max clamp to a valid grok CLI
    token via ``_GROK_EFFORT_OVERRIDES`` (identical to ``launcher._grok_cli_effort``'s
    map, for panel/launcher parity). Any other, genuinely unrecognized effort passes
    through unchanged via the ``.get`` default, so this can never ``KeyError`` — unlike
    the direct-index form it replaces.
    """
    return _GROK_EFFORT_OVERRIDES.get(effort, effort)


# canonical effort -> the ``(Word)`` token used by agy's legacy display names.
_GEMINI_EFFORT_WORD: dict[str, str] = {
    "low": "Low",
    "medium": "Medium",
    "high": "High",
    "max": "Max",
}

# strip a trailing ``" (Effort)"`` embed so re-rendering is idempotent when a caller
# passes an already-baked model string (e.g. ``"Gemini 3.1 Pro (High)"``). Matches
# ONLY the four canonical effort words (the Title-case tokens ``render_gemini_model``
# emits) — a model whose name genuinely ends in a parenthetical (e.g.
# ``"Gemini 3.1 Pro (Preview)"``) is a DIFFERENT model and must be left untouched,
# never silently rewritten to a lower effort.
_GEMINI_EMBED_RE = re.compile(r"\s*\((?:Low|Medium|High|Max)\)\s*$")

# Canonical agy model ids embed effort as a suffix. Keep the phase-loop matrix
# aliases here too: launcher and advisor-board seats must share one renderer so a
# given (model, effort) pair cannot select different Gemini models by entrypoint.
_AGY_CANONICAL_GEMINI = re.compile(
    r"^(gemini-\d+\.\d+-(?:flash|pro))-(high|medium|low|thinking)$"
)
_AGY_BASE_GEMINI = re.compile(r"^gemini-\d+\.\d+-(?:flash|pro)$")
_GEMINI_MODEL_ID_ALIASES: dict[str, str] = {
    "gemini-3.1-pro-preview": "Gemini 3.1 Pro (High)",  # model-id-source: shared agy compatibility alias
    "gemini-3.5-flash-lite": "gemini-3.5-flash-high",  # model-id-source: shared agy capability fallback
}


def gemini_base_model(model: str) -> str:
    """Return the gemini model with any trailing ``(Effort)`` embed removed."""
    return _GEMINI_EMBED_RE.sub("", model or "").strip()


def render_agy_model(model: str, effort: str | None = None) -> str:
    """Render a Gemini model for agy's effort-in-model-name convention.

    Canonical ids such as ``gemini-3.6-flash`` become
    ``gemini-3.6-flash-high``. Legacy display names retain their parenthesized
    effort spelling, and the established routing aliases remain compatible.
    Unknown ``gemini-*`` ids fail loud instead of silently selecting Pro.
    """
    candidate = (model or "").strip()
    if _AGY_BASE_GEMINI.match(candidate):
        rendered_effort = effort or "high"
        if rendered_effort not in {"high", "medium", "low", "thinking"}:
            raise ValueError(
                f"gemini base model {candidate!r} requires a supported agy effort; got {effort!r}"
            )
        return f"{candidate}-{rendered_effort}"
    if candidate in {"", "auto", "pro"}:
        return "Gemini 3.1 Pro (High)"
    if candidate in _GEMINI_MODEL_ID_ALIASES:
        return _GEMINI_MODEL_ID_ALIASES[candidate]
    canonical = _AGY_CANONICAL_GEMINI.match(candidate)
    if canonical:
        embedded_effort = canonical.group(2)
        if effort is not None and effort != embedded_effort:
            raise ValueError(
                f"gemini model {candidate!r} embeds effort {embedded_effort!r}, "
                f"which conflicts with requested effort {effort!r}"
            )
        return candidate
    if candidate.startswith("gemini-"):
        raise ValueError(
            f"unmapped gemini model id {candidate!r}: add it to "
            "_GEMINI_MODEL_ID_ALIASES (never silently coerce a gemini-* id to Pro)"
        )
    if effort is None:
        return candidate
    _require_effort(effort)
    return f"{gemini_base_model(candidate)} ({_GEMINI_EFFORT_WORD[effort]})"


def agy_model_effort(model: str) -> str | None:
    """Return the effort embedded in a rendered agy model, when present."""
    canonical = _AGY_CANONICAL_GEMINI.match(model)
    if canonical:
        return canonical.group(2)
    display = re.search(r"\((High|Medium|Low|Thinking|Max)\)$", model)
    return display.group(1).lower() if display else None


def render_gemini_model(model: str, effort: str) -> str:
    """Compatibility name for the shared agy renderer."""
    return render_agy_model(model, effort)


def _require_effort(effort: str) -> None:
    if effort not in EFFORT_LEVELS:
        raise ValueError(f"effort {effort!r} not in {EFFORT_LEVELS}")


def render_seat_invocation(harness: str, model: str, effort: str) -> SeatInvocation:
    """Freeze: turn a canonical ``(harness, model, effort)`` into its CLI invocation.

    Only the homebrew lanes (claude / codex / gemini / grok) are frozen here —
    claude / codex / gemini are what the ``default`` board's back-compat proof
    rides on; grok joins them for the 4-vendor ``code-review`` board. Breadth
    lanes (opencode / pi / cursor / amp) raise ``EffortMappingError`` until
    ABDREG/ABDHOME/ABDOMNI populate them; a board with an unmapped lane degrades
    skip-with-warning, never silently drops effort.
    """
    _require_effort(effort)
    lane = (harness or "").lower()
    if lane == "claude":
        # panel_invoker.py:322-325 -> ``--model <model> --effort <level>``
        return SeatInvocation(lane, model, ("--effort", effort), MECH_FLAG)
    if lane == "codex":
        # panel_invoker.py:991-992 -> ``--model <model> -c model_reasoning_effort=<tok>``
        token = _CODEX_EFFORT[effort]
        return SeatInvocation(lane, model, ("-c", f"model_reasoning_effort={token}"), MECH_CONFIG)
    if lane == "gemini":
        # panel_invoker.py:1016 -> effort baked into ``--model "<base> (Word)"``
        return SeatInvocation(lane, render_gemini_model(model, effort), (), MECH_MODEL_NAME)
    if lane == "grok":
        # grok headless -> ``--reasoning-effort <token>`` (alias ``--effort``); the
        # model is passed verbatim via ``-m``. Same flag mechanism as claude.
        token = _grok_panel_effort(effort)
        return SeatInvocation(lane, model, ("--reasoning-effort", token), MECH_FLAG)
    raise EffortMappingError(
        f"effort mapping for harness {harness!r} is populated in ABDREG/ABDHOME/ABDOMNI"
    )
