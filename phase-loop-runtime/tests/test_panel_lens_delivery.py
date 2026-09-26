"""PANEL SL-0 frozen corpus: EC-PANEL-6 -- every seat's lens reaches its reviewer's instructions.

Frozen byte-equal from SL-0's landing until the phase merges (``content_tdd_receipt.v1``;
see ``panel_content_tdd_adapter.py``). Every node keys on
``advisor_board.lens_frame.render_lens_section`` (slice 2): it skips in an ordinary run
while that symbol is absent and FAILS under ``PHASE_LOOP_TDD_EXPECT_PANEL=1``.

Routes (observed exactly as ``test_panel_lanes.route_instructions`` documents):
* brokered -- the non-Claude seats; TUI -- the Claude seat outside Claude Code. The
  observation is the exact prompt production hands to each seat's transport, through the
  IF-0-PANEL-1 seam ``panel_invoker.deliver_seat_prompt`` and bound to its seat by the
  ``seat_key`` production passes (one delivery per seat, on its lane's route), with both
  frames' bound digests checked; each seat's OWN lens must sit INSIDE its own
  AUTHORITATIVE-INSTRUCTIONS frame and NOT in the UNTRUSTED-REVIEW-BUNDLE frame;
* native fill -- the Claude seat under Claude Code: bound by the request's own
  ``seat_key``; the seat's own lens (``seat_lenses[seat_key]``, never the request's
  ``lens`` field) must be in the request's ``instructions`` (the instruction channel).

President follow-ups encoded here:
* F018 -- "verdict protocol text" is a seat's instructions MINUS its lens section; it
  must be identical for every seat, on every route.
* F021 -- the expected lens-delivery label is DERIVED from the actual instructions
  (``prompt`` iff the rendered section is in them), never assumed.
"""
from __future__ import annotations

import re
import types

import pytest

from panel_content_tdd_adapter import SLICE2, require_ready
from test_panel_lanes import (
    BOARD_VENDORS,
    ROUTES,
    _context,
    assert_own_lens,
    route_labels,
    _names,
    _panel_toml,
    route_instructions,
)

HEADING = "Review lens (subordinate to the verdict protocol)"
DECLARED = "supply-chain"
DECLARED_TEXT = "Check every new dependency's provenance and pinning.\nName each unpinned one."
LENSES_BY_VENDOR = {"grok": "adversarial", "claude": "correctness", "codex": "red-team", "gemini": "alternative-approach"}


def slice2() -> types.SimpleNamespace:
    lens_frame = require_ready(SLICE2)
    names = _names()
    names.render = lens_frame.render_lens_section
    return names


def _table(declared_on: str) -> str:
    """One lane per vendor, each vendor first in its own lane (so every vendor seats exactly
    one seat); the lane led by ``declared_on`` carries the declared lens."""
    lanes = []
    for i, vendor in enumerate(BOARD_VENDORS):
        order = BOARD_VENDORS[i:] + BOARD_VENDORS[:i]
        lanes.append((DECLARED if vendor == declared_on else LENSES_BY_VENDOR[vendor], order))
    return _panel_toml("code-review", lanes, lenses={DECLARED: DECLARED_TEXT}, minimum=1)


def _assert_section_shape(section: str, lens) -> None:
    assert HEADING in section, "the lens is not under the fixed subordinate heading"
    heading_at = section.index(HEADING)
    name_at = section.index(lens.name, heading_at + len(HEADING))
    text_at = section.index(lens.text, name_at + len(lens.name))
    _assert_precedence_direction(section[text_at + len(lens.text):])


def _assert_precedence_direction(tail: str) -> None:
    """The text after the lens must state that the VERDICT PROTOCOL takes precedence (the
    roadmap's order: "the verdict protocol takes precedence"), and must not state the reverse.

    Pinned at the roadmap's own granularity, not its exact prose: some sentence names the
    verdict protocol BEFORE "precedence" (the protocol is what takes precedence), and no
    sentence names "precedence" BEFORE the verdict protocol (e.g. "The lens takes
    precedence over the verdict protocol." -- the reversal -- is refused)."""
    sentences = [s.strip().lower() for s in re.split(r"[.!?\n]+", tail) if s.strip()]
    stated = [s for s in sentences if "verdict protocol" in s and "precedence" in s]
    assert stated, "the lens text is not followed by the statement that the verdict protocol takes precedence"
    assert any(s.index("verdict protocol") < s.index("precedence") for s in stated), (
        "no sentence makes the verdict protocol the thing that takes precedence")
    reversed_ = [s for s in stated if s.index("precedence") < s.index("verdict protocol")]
    assert not reversed_, f"the section gives something precedence OVER the verdict protocol: {reversed_}"


@pytest.mark.parametrize("statement,accepted", [
    ("The verdict protocol takes precedence over this lens.", True),
    ("If they conflict, the verdict protocol takes precedence.", True),
    ("The lens takes precedence over the verdict protocol.", False),
    ("The verdict protocol applies. This lens takes precedence over the verdict protocol.", False),
    ("Precedence is not stated here.", False),
], ids=["protocol-over-lens", "protocol-on-conflict", "REVERSED", "both-with-reversal", "absent"])
def test_ec6_the_precedence_direction_check_refuses_the_reversal(statement, accepted):
    """A falsifier for the falsifier: the shape check refuses a section that gives the lens
    precedence over the verdict protocol (codex's counterexample)."""
    s = slice2()
    lens = s.ResolvedLens(name="correctness", text="Check the logic.", kind="built-in")
    section = f"{HEADING}\n{lens.name}\n{lens.text}\n{statement}\n"
    if accepted:
        _assert_section_shape(section, lens)
    else:
        with pytest.raises(AssertionError):
            _assert_section_shape(section, lens)


@pytest.mark.parametrize("kind", ["built-in", "declared"])
def test_ec6_section_has_the_fixed_heading_the_lens_verbatim_and_the_precedence_statement(kind):
    s = slice2()
    if kind == "built-in":
        lens = s.ResolvedLens(name="correctness", text=s.lens_text["correctness"], kind="built-in")
    else:
        lens = s.ResolvedLens(name=DECLARED, text=DECLARED_TEXT, kind="declared")
    section = s.render(lens)
    assert section.strip()
    _assert_section_shape(section, lens)


@pytest.mark.parametrize("declared_on", ["grok", "claude"])
@pytest.mark.parametrize("route", ROUTES)
def test_ec6_every_seat_lens_is_inside_its_routes_authoritative_instructions(tmp_path, monkeypatch, route, declared_on):
    s = slice2()
    c = _context(s, tmp_path, monkeypatch, user=_table(declared_on))
    result, seen, payloads = route_instructions(c.ctx, route, tmp_path, monkeypatch)
    assert seen
    assert_own_lens(c.ctx, seen, s.render)
    kinds = set()
    for key, instructions in seen.items():
        lens = c.ctx.composed.seat_lenses[key]
        kinds.add(lens.kind)
        section = s.render(lens)
        assert section in instructions, f"seat {key}: its lens section is not in the instructions its route sends"
        _assert_section_shape(instructions[instructions.index(section):], lens)
        # On brokered/TUI ``instructions`` IS the digest-bound frame body and ``payloads``
        # the bundle frame body of the actual outgoing prompt.
        assert lens.name in instructions and lens.text in instructions
        if route != "native_fill":  # on native fill the "payload" is the artifact file: trivially true
            assert lens.text not in payloads[key], f"seat {key}: the lens leaked into the reviewed payload"
    if (route == "brokered") == (declared_on == "grok"):
        assert "declared" in kinds, "the declared lens never reached this route"


@pytest.mark.parametrize("route", ROUTES)
def test_ec6_verdict_protocol_text_is_identical_across_seats(tmp_path, monkeypatch, route):
    s = slice2()
    c = _context(s, tmp_path, monkeypatch, user=_table("grok"))
    protocols = {}
    for observed in dict.fromkeys(("brokered", "tui", route)):
        (tmp_path / observed).mkdir()
        _result, seen, _payloads = route_instructions(c.ctx, observed, tmp_path / observed, monkeypatch)
        assert_own_lens(c.ctx, seen, s.render)
        for key, instructions in seen.items():
            section = s.render(c.ctx.composed.seat_lenses[key])
            assert instructions.count(section) == 1
            protocols[(observed, key)] = instructions.replace(section, "", 1)
    assert len(protocols) >= len(BOARD_VENDORS)
    assert len(set(protocols.values())) == 1, "the verdict protocol text differs between seats"


@pytest.mark.parametrize("route", ROUTES)
def test_ec6_the_prompt_label_is_derived_from_the_actual_instructions(tmp_path, monkeypatch, route):
    s = slice2()
    c = _context(s, tmp_path, monkeypatch, user=_table("claude"))
    result, seen, _payloads = route_instructions(c.ctx, route, tmp_path, monkeypatch)
    labels = route_labels(result)
    for key, instructions in seen.items():
        derived = "prompt" if s.render(c.ctx.composed.seat_lenses[key]) in instructions else "metadata-only"
        assert labels[key]["lens_delivery"] == derived
        assert derived == "prompt", f"seat {key}: slice 2 did not deliver its lens"
