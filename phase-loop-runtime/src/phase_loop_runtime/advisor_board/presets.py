"""Named board presets (ABDREG, Phase 2 — lane 4).

Nine built-in presets, each a named, purpose-tagged, open-ended seat list:

* ``default``     — IS ``fixtures.DEFAULT_BOARD`` (imported, not re-declared), so
                    the back-compat keystone holds by construction: the default
                    board defines the canonical four-vendor review seats (the claude seat
                    on Opus 5.5, ``claude-opus-5-5``).
* ``code-review`` — the 4-vendor cross-vendor board (grok / claude / codex /
                    gemini) at max thinking, distinct lenses, composed
                    availability-aware (``composition.compose_review_board``).
* ``brainstorm``  — multi-vendor divergent thinking, lens-differentiated.
* ``doc-edit``    — a lighter documentation-editing board.
* ``legal-review`` / ``legal-strategy-review`` / ``legal-brainstorm`` — the legal
                    boards (see below).

**Review-class boards run on frontier models, never the implementer.** Pre-merge
and legal review are mid-tier decisions where being wrong is expensive, so the
review-class boards (``default``, ``code-review``, ``legal-review``,
``legal-strategy-review``) seat Opus 5.5 (``claude-opus-5-5``) on the claude lane --
the maintainer's review default "for now" (2026-09-23; Fable ``claude-fable-5-1``
before that) -- not the implementer ``claude-sonnet-5``. The catch-all ``general`` and
``solo`` boards follow the same default. The divergent-thinking boards (``brainstorm``,
``doc-edit``, ``legal-brainstorm``) deliberately KEEP Sonnet — a diverse voice / a
low-stakes copyedit / an aggressive-but-cheap ideation seat — where it is the right
tool.

Every preset seat uses only REGISTERED, VALID ``(model, harness)`` pairs on the
built-3 + ``opencode`` lanes (no ``pi`` / ``cursor`` / unregistered-model seats),
so the presets pass their OWN config-time validation — ``config.load_boards()``
self-validates every preset (``tests/test_advisor_board_config.py``). Adding a
preset seat on an unregistered model or an incompatible lane would turn the suite
red, which is the intended guardrail. ``lens`` and ``purpose`` are free-form
strings (``schema.py``): the legal lenses/purposes below need no enum extension.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from .composition import compose_review_board
from .fixtures import DEFAULT_BOARD
from .schema import Board, Seat

# code-review: review-class = the 4-vendor cross-vendor board, each vendor at MAX
# thinking with a DISTINCT lens (grok=adversarial, claude=correctness,
# codex=red-team, gemini=alternative-approach). This is the IDEAL (all-vendors-up)
# shape; the live panel composes it AVAILABILITY-AWARE via
# ``composition.compose_review_board`` — down vendors are backfilled with distinct
# lenses onto available vendors so the reviewer count never drops below the floor.
# The static preset here is the all-available composition (so a snapshot / config
# validation sees the canonical 4-seat board); it supersedes the old three-seat
# adversarial board.
CODE_REVIEW_BOARD: Board = compose_review_board(
    is_available=lambda _vendor: True, auth_ok=lambda _vendor: True,
)

# brainstorm: divergent, multi-vendor, each seat a different thinking lens.
BRAINSTORM_BOARD: Board = Board(
    name="brainstorm",
    purpose="brainstorm",
    seats=(
        Seat(model="claude-sonnet-5", effort="high", harness="claude", lens="adversarial"),
        Seat(model="gpt-6-astra", effort="high", harness="codex", lens="supportive"),
        Seat(model="gemini-3.8-flash", effort="high", harness="gemini", lens="lateral"),
    ),
)

# doc-edit: a lighter documentation-editing board (structure + copyedit).
DOC_EDIT_BOARD: Board = Board(
    name="doc-edit",
    purpose="doc-edit",
    seats=(
        Seat(model="claude-sonnet-5", effort="medium", harness="claude", lens="copyedit"),
        Seat(model="gpt-6-astra", effort="medium", harness="codex", lens="structure"),
    ),
)

# --- legal boards ----------------------------------------------------------
#
# Each seat below encodes the PRIMARY review lens per vendor. The richer treatment
# — four lenses per seat, an apex-Opus seat, a verify-round, and retrieval-grounded
# citation-verification — is a documented deep-seat FOLLOW-ON (see CONTRACTS.md),
# intentionally NOT built here. Review-class legal boards seat Opus 5.5 on claude;
# legal-brainstorm keeps Sonnet as a cheap aggressive ideation voice.

# legal-review: document/contract review. Opposing-counsel adversary, risk/liability
# scan, and authority (citation/precedent) verification.
LEGAL_REVIEW_BOARD: Board = Board(
    name="legal-review",
    purpose="legal-review",
    seats=(
        Seat(model="gpt-6-astra", effort="max", harness="codex", lens="opposing-counsel"),
        Seat(model="gemini-3.8-flash", effort="high", harness="gemini", lens="risk-liability"),
        Seat(model="claude-opus-5-5", effort="max", harness="claude", lens="authority-verification"),
    ),
)

# legal-strategy-review: red-team a legal strategy — attack it, surface alternatives,
# and stress the downside / ethical exposure.
LEGAL_STRATEGY_REVIEW_BOARD: Board = Board(
    name="legal-strategy-review",
    purpose="legal-strategy-review",
    seats=(
        Seat(model="gpt-6-astra", effort="max", harness="codex", lens="red-team"),
        Seat(model="gemini-3.8-flash", effort="high", harness="gemini", lens="alternatives"),
        Seat(model="claude-opus-5-5", effort="max", harness="claude", lens="downside-ethics"),
    ),
)

# legal-brainstorm: divergent legal ideation. KEEPS Sonnet (aggressive, cheap voice)
# alongside a conservative and a creative seat.
LEGAL_BRAINSTORM_BOARD: Board = Board(
    name="legal-brainstorm",
    purpose="legal-brainstorm",
    seats=(
        Seat(model="claude-sonnet-5", effort="high", harness="claude", lens="aggressive"),
        Seat(model="gpt-6-astra", effort="high", harness="codex", lens="conservative"),
        Seat(model="gemini-3.8-flash", effort="high", harness="gemini", lens="creative"),
    ),
)

# --- general-purpose catch-alls -------------------------------------------
#
# For use cases we have NOT pre-modeled, so the board library is open-ended rather
# than limited to the named domains. Both default to TOP-END models: an unanticipated
# task cannot be assumed low-stakes, so the safe default is frontier — dial down
# explicitly (a cheaper board or max_concurrency aside) when a task is known-cheap.

# general: the domain-agnostic top-tier PANEL. Three frontier vendors with generic
# critical lenses (adversarial / alternative-angle / completeness) — hand it any
# task + brief and it convenes a cross-vendor frontier review.
GENERAL_BOARD: Board = Board(
    name="general",
    purpose="general",
    seats=(
        Seat(model="gpt-6-astra", effort="max", harness="codex", lens="adversarial"),
        Seat(model="gemini-3.8-flash", effort="high", harness="gemini", lens="alternative"),
        Seat(model="claude-opus-5-5", effort="max", harness="claude", lens="completeness"),
    ),
)

# solo: the general-purpose single MEMBER — one quick top-end opinion when a full
# panel is overkill. A one-seat board resolves + validates like any other.
SOLO_BOARD: Board = Board(
    name="solo",
    purpose="general",
    seats=(
        Seat(model="claude-opus-5-5", effort="max", harness="claude", lens="completeness"),
    ),
)

# The built-in presets, keyed by name. ``default`` IS the shared fixture board.
PRESETS: dict[str, Board] = {
    DEFAULT_BOARD.name: DEFAULT_BOARD,
    CODE_REVIEW_BOARD.name: CODE_REVIEW_BOARD,
    BRAINSTORM_BOARD.name: BRAINSTORM_BOARD,
    DOC_EDIT_BOARD.name: DOC_EDIT_BOARD,
    LEGAL_REVIEW_BOARD.name: LEGAL_REVIEW_BOARD,
    LEGAL_STRATEGY_REVIEW_BOARD.name: LEGAL_STRATEGY_REVIEW_BOARD,
    LEGAL_BRAINSTORM_BOARD.name: LEGAL_BRAINSTORM_BOARD,
    GENERAL_BOARD.name: GENERAL_BOARD,
    SOLO_BOARD.name: SOLO_BOARD,
}

PRESET_NAMES: tuple[str, ...] = tuple(PRESETS)

# The board a bare ``advisor-board`` invocation resolves to absent a user override.
DEFAULT_BOARD_NAME: str = DEFAULT_BOARD.name


def get_preset(name: str) -> Board:
    """Return a built-in preset by name, or raise ``KeyError`` naming the known
    presets."""
    try:
        return PRESETS[name]
    except KeyError as exc:
        known = ", ".join(PRESET_NAMES)
        raise KeyError(f"unknown board preset {name!r}; known presets: {known}") from exc


# --- PANEL lane tables (v10 Phase 18, agent-harness#1078; EC-PANEL-1/2) -----------
#
# Each built-in task declares its lanes: a lens with an ordered vendor preference. A
# lane's first vendor is the vendor that task seats today, so with every vendor up the
# built-in table composes exactly the preset's seats; every lane then lists every board
# vendor, so any one available vendor fills every lane (``composition.compose_panel_board``).

PANEL_VENDORS: tuple[str, ...] = ("grok", "claude", "codex", "gemini")


@dataclass(frozen=True)
class ResolvedLens:
    """A seat's lens: its name, its instruction text, and ``built-in`` or ``declared``."""

    name: str
    text: str
    kind: str


@dataclass(frozen=True)
class PanelLane:
    """One lane: a lens name and the ordered vendors that may seat it."""

    lens: str
    vendors: tuple[str, ...]


@dataclass(frozen=True)
class PanelTable:
    """A ``[panel.<task>]`` table: its lanes, its declared lenses (name -> text) and the
    optional ``min_distinct_vendors`` (``None`` when omitted; ``code-review`` only)."""

    task: str
    lanes: tuple[PanelLane, ...]
    lenses: Mapping[str, str] = field(default_factory=dict)
    min_distinct_vendors: int | None = None


# The instruction text of every built-in lens. A lens narrows what a reviewer looks at;
# the verdict protocol stays the same for every seat.
BUILTIN_LENS_TEXT: dict[str, str] = {
    "adversarial": "Look for the ways this change fails: inputs, states and orderings that break it.",
    "correctness": "Check that the change does what it claims, and that every claim is backed by the code.",
    "red-team": "Attack the change as an adversary would: bypasses, escalations and unsafe defaults.",
    "alternative-approach": "Ask whether a simpler or safer design reaches the same goal, and say which.",
    "opposing-counsel": "Argue the other side: the strongest case against every conclusion the artifact draws.",
    "conservative": "Prefer the least risky reading and flag anything that raises risk without need.",
    "supportive": "Find what works and how to build on it, without hiding real problems.",
    "lateral": "Look sideways: connections, analogies and options the artifact did not consider.",
    "copyedit": "Check wording, grammar, consistency and clarity, sentence by sentence.",
    "structure": "Check the document's organisation: order, headings, and what belongs where.",
    "risk-liability": "Find the risks and liabilities the artifact creates or leaves unaddressed.",
    "authority-verification": "Verify every cited authority, precedent and citation is real and says what is claimed.",
    "alternatives": "Lay out the alternative strategies and how each compares.",
    "downside-ethics": "Stress the downside cases and any ethical exposure.",
    "aggressive": "Push for the boldest defensible position and say what it would take.",
    "creative": "Offer unexpected approaches the artifact has not tried.",
    "alternative": "Look for a different angle on the problem and what it changes.",
    "completeness": "Check that nothing needed is missing: cases, steps, evidence and follow-through.",
}


def _seat_vendor(seat: Seat) -> str:
    return seat.vendor_family


def _builtin_table(board: Board) -> PanelTable:
    lanes = []
    for seat in board.seats:
        first = _seat_vendor(seat)
        lanes.append(PanelLane(
            lens=str(seat.lens),
            vendors=(first, *(v for v in PANEL_VENDORS if v != first)),
        ))
    return PanelTable(task=board.name, lanes=tuple(lanes))


# Every built-in preset task has a built-in table (EC-PANEL-1).
BUILTIN_PANEL_TABLES: dict[str, PanelTable] = {name: _builtin_table(board) for name, board in PRESETS.items()}


def panel_task_board(task: str) -> Board:
    """The preset board whose name, purpose and per-vendor seat specs a task composes with."""
    return PRESETS[task]


__all__ = [
    "PRESETS",
    "PRESET_NAMES",
    "DEFAULT_BOARD_NAME",
    "CODE_REVIEW_BOARD",
    "BRAINSTORM_BOARD",
    "DOC_EDIT_BOARD",
    "LEGAL_REVIEW_BOARD",
    "LEGAL_STRATEGY_REVIEW_BOARD",
    "LEGAL_BRAINSTORM_BOARD",
    "GENERAL_BOARD",
    "SOLO_BOARD",
    "get_preset",
    "PANEL_VENDORS",
    "BUILTIN_LENS_TEXT",
    "BUILTIN_PANEL_TABLES",
    "ResolvedLens",
    "PanelLane",
    "PanelTable",
    "panel_task_board",
]
