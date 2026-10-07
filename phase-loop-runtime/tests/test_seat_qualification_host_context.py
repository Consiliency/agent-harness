"""Owned review legs hold their own filtered namespace outside a board (agent-harness#1222).

Trusted host helpers (host Git above all) are resolved and run in the trusted parent,
never inside the seat's egress namespace: inside it, host files map to the overflow owner
and a trusted-helper check correctly refuses them. Only the provider launch goes through
the namespace.

The agy qualification's ``--help`` measurement runs an owned review leg outside any board
leg. Before this it found no namespace and refused, so the qualification was run inside a
hand-built namespace around the WHOLE command, which put the qualification worker -- and
its host Git -- inside it too. The leg now holds a namespace for its own launch only.
"""

from __future__ import annotations

import contextlib

import pytest

from phase_loop_runtime import sandbox_egress
from phase_loop_runtime import panel_invoker as pi

_HOLDER = ("nsenter", "--net", "--mount", "-t", "1", "-U", "--preserve-credentials",
           "setpriv", "--bounding-set=-all", "--inh-caps=-all", "--")


def test_an_owned_leg_outside_a_board_holds_its_own_namespace(tmp_path, monkeypatch):
    """The agy ``--help`` measurement runs a leg outside any board leg's namespace. The
    leg opens one for its own launch, so the unwrapped CLI never needs a hand-built holder
    around the whole qualification (which would also put the worker's host Git inside it)."""
    held, seen = [], []

    @contextlib.contextmanager
    def _holder(*, timeout_s, required, **_):
        held.append(required)
        yield _HOLDER

    def _launch(argv, **kwargs):
        seen.append(pi._EGRESS_LAUNCH_PREFIX.get())
        raise OSError("stop at the launch")

    monkeypatch.setattr(sandbox_egress, "isolated_network", _holder)
    monkeypatch.setattr(pi, "launch_owned", _launch)
    with pytest.raises(OSError):
        pi._run_leg_with_liveness(["true"], cwd=tmp_path, env={}, deadline_s=5)
    assert held == [True] and seen == [_HOLDER]
    assert pi._EGRESS_LAUNCH_PREFIX.get() == ()


def test_an_owned_leg_inside_a_board_reuses_its_namespace(tmp_path, monkeypatch):
    def _never(**_):
        raise AssertionError("a second namespace was opened")

    seen = []

    def _launch(argv, **kwargs):
        seen.append(pi._EGRESS_LAUNCH_PREFIX.get())
        raise OSError("stop at the launch")

    monkeypatch.setattr(sandbox_egress, "isolated_network", _never)
    monkeypatch.setattr(pi, "launch_owned", _launch)
    token = pi._EGRESS_LAUNCH_PREFIX.set(_HOLDER)
    try:
        with pytest.raises(OSError):
            pi._run_leg_with_liveness(["true"], cwd=tmp_path, env={}, deadline_s=5)
    finally:
        pi._EGRESS_LAUNCH_PREFIX.reset(token)
    assert seen == [_HOLDER]
