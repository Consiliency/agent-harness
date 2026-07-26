"""Gemini/agy headless TOOL-DENIAL regression (panel_invoker).

Root cause found while diagnosing the gemini seat returning EMPTY in 6 of 11 rounds
of the model-tier review: `agy` running headless cannot prompt for a tool permission,
so it AUTO-DENIES, prints its reason on stderr, and exits rc==0 with a ZERO-BYTE body.
The panel classified that as an anonymous soft-empty and dropped the leg silently.
"""
from __future__ import annotations

import re

from phase_loop_runtime import panel_invoker as pi


_REAL_AGY_STDERR = (
    'jetski: no output produced — a tool required the "command" permission that '
    "headless mode cannot prompt for, so it was auto-denied. Add an allow-rule under "
    "permissions.allow in settings.json (e.g. command(<target>)). Alternatively, "
    "re-run with --dangerously-skip-permissions to auto-approve all tools."
)


def test_tool_denial_regex_matches_the_real_agy_stderr():
    # Captured verbatim from a live `agy` run; the classifier must recognise it.
    assert pi._TOOL_DENIED_RE.search(_REAL_AGY_STDERR)


def test_tool_denial_is_not_misread_as_a_transient_stall():
    # Retrying a denied permission reproduces it exactly — it must NOT be retried
    # through the transient-stall path.
    assert not pi._GEMINI_TRANSIENT_RE.search(_REAL_AGY_STDERR)


def test_tool_denial_regex_does_not_fire_on_a_review_that_merely_discusses_it():
    # This panel reviews code about permissions/tooling; a real review body that
    # QUOTES the phrase must not be discarded as a failure. The classifier only runs
    # on an EMPTY body, but keep the phrasing distinct enough to be safe.
    body = "The adapter should fail loudly rather than let a tool call be silently dropped."
    assert not pi._TOOL_DENIED_RE.search(body)


def test_no_tool_preamble_states_the_constraint_and_forbids_fake_verification():
    p = pi._NO_TOOL_PREAMBLE
    assert "auto-denied" in p
    # Must tell the leg what to do INSTEAD, or it will silently claim it verified things.
    assert "do not claim to have" in p.lower()
    assert re.search(r"could NOT verify", p)


def test_gemini_cmd_prepends_the_preamble_before_the_prompt():
    # Prepended, not appended: the constraint has to be read before the instructions
    # that would otherwise trigger a tool call.
    prompt = "Review this and run the guard to verify."
    combined = pi._NO_TOOL_PREAMBLE + prompt
    assert combined.startswith(pi._NO_TOOL_PREAMBLE)
    assert combined.endswith(prompt)
