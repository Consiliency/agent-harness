"""Shared canonical fixtures (IF-0-ABDFREEZE-2 keystone).

ONE fixture set, importable from both ``src`` and ``tests``, that ABDREG
populates *from* and ABDRESOLVE / ABDHOME test *against* — so the parallel lanes
never diverge into a mock-vs-real integration cliff.

The values here are **golden expectations**, deliberately hard-coded (not derived
from ``panel_invoker``) so a change to model-first board defaults trips tests
instead of silently re-baselining. The legacy three-leg order remains a separate
fixture for explicit ``invoke_panel`` compatibility.
"""
from __future__ import annotations

from .schema import (
    AUTH_SUBSCRIPTION,
    BACKING_HOMEBREW,
    Board,
    Seat,
)

# The legacy built-3 panel legs, in ``panel_invoker.PANEL_LEGS`` order. This
# compatibility fixture remains frozen even though the model-first default board
# now has four vendors.
CANONICAL_LEG_ORDER: tuple[str, ...] = ("codex", "gemini", "claude")
DEFAULT_BOARD_VENDOR_ORDER: tuple[str, ...] = ("codex", "gemini", "claude", "grok")

# The default board's four seats — model-first, effort split out of the model
# name. These reconstruct ``DEFAULT_LEG_MODELS`` under
# ``harness_mapping.render_seat_invocation``:
#   codex  gpt-6-astra           + effort max  -> ``-c model_reasoning_effort=xhigh``
#   gemini gemini-3.8-flash   + effort high -> model ``gemini-3.8-flash-high``
#   claude claude-fable-5-1  + effort max  -> ``--effort max``
#   grok   grok-4.6           + effort max  -> ``--reasoning-effort high``
#
# The claude seat runs Fable (``claude-fable-5-1``): pre-merge review is a mid-tier
# decision where being wrong is expensive, so the default review board reviews on
# Fable, not on the implementer model ``claude-sonnet-5``. This is byte-pinned to
# ``panel_invoker.DEFAULT_LEG_MODELS["claude"]`` (also Fable) by the golden proof.
DEFAULT_SEATS: tuple[Seat, ...] = (
    Seat(model="gpt-6-astra", effort="max", harness="codex", lens="red-team",
         auth=AUTH_SUBSCRIPTION, backing=BACKING_HOMEBREW),
    Seat(model="gemini-3.8-flash", effort="high", harness="gemini", lens="alternative-approach",
         auth=AUTH_SUBSCRIPTION, backing=BACKING_HOMEBREW),
    Seat(model="claude-fable-5-1", effort="max", harness="claude", lens="correctness",
         auth=AUTH_SUBSCRIPTION, backing=BACKING_HOMEBREW),
    Seat(model="grok-4.6", effort="max", harness="grok", lens="adversarial",
         auth=AUTH_SUBSCRIPTION, backing=BACKING_HOMEBREW),
)

DEFAULT_BOARD: Board = Board(
    name="default",
    purpose="premerge-review",
    seats=DEFAULT_SEATS,
    allow_api_key_fallback=False,
)

# Golden literals the default seats must reproduce (cross-checked in the
# back-compat test against the live ``panel_invoker`` constants).
DEFAULT_SEAT_RENDERED_MODEL: dict[str, str] = {
    "codex": "gpt-6-astra",
    "gemini": "gemini-3.8-flash-high",
    "claude": "claude-fable-5-1",
    "grok": "grok-4.6",
}
DEFAULT_SEAT_EFFORT_ARGS: dict[str, tuple[str, ...]] = {
    "codex": ("-c", "model_reasoning_effort=xhigh"),
    "gemini": (),
    "claude": ("--effort", "max"),
    "grok": ("--reasoning-effort", "high"),
}

# Canonical (model x harness) pairs ABDREG's matrix + ABDRESOLVE's validation test
# against. Same-vendor-across-harness (gpt-5.6-sol on codex and opencode) is VALID and
# projects to one family; a cross-vendor mismatch (gpt-5.6-sol on claude) is INVALID.
CANONICAL_VALID_PAIRS: tuple[tuple[str, str], ...] = (
    ("gpt-5.6-sol", "codex"),
    ("gpt-5.6-sol", "opencode"),
    ("claude-sonnet-5", "claude"),
    ("Gemini 3.1 Pro", "gemini"),
    ("gemini-3.8-flash", "gemini"),
    ("gemini-3.7-flash", "gemini"),
    ("gemini-3.6-flash", "gemini"),
    ("grok-4.6", "grok"),
    ("grok-4.5", "grok"),  # xAI-family model on the grok lane (4-vendor board)
)
CANONICAL_INVALID_PAIRS: tuple[tuple[str, str], ...] = (
    ("gpt-5.6-sol", "claude"),        # openai-family model on the claude lane
    ("claude-sonnet-5", "codex"),  # anthropic model on the codex lane
    ("grok-4.6", "claude"),        # xAI-family model on the claude lane
    ("gpt-5.6-sol", "grok"),       # openai-family model on the grok lane
)

# A two-same-vendor-seat board: exercises result re-keying (leg -> seat) and the
# governed reviewer != author disjointness under model-first (both seats project
# to ``codex``). Used by ABDRESOLVE / ABDHOME.
TWO_SAME_VENDOR_BOARD: Board = Board(
    name="two-openai",
    purpose="brainstorm",
    seats=(
        Seat(model="gpt-6-astra", effort="high", harness="codex"),
        Seat(model="gpt-5.6-sol", effort="high", harness="opencode"),
    ),
)
