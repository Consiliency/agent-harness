"""ah#823: the brokered gemini guard compared an effort-fused id against a raw one.

``gemini_model`` is *defined* as ``render_seat_invocation(model, effort)`` whenever an
effort is set, and the guard then required ``gemini_model == model``. That could only
hold if the caller's model already carried the effort suffix -- which ``validate_seat``
rejects as an unknown model. The two requirements were mutually unsatisfiable, so every
brokered gemini seat carrying an effort raised BEFORE ``agy`` was exec'd and surfaced as
a bare ERROR with no detail.

``CODE_REVIEW_BOARD`` ships exactly such a seat (``gemini-3.8-flash`` + ``high``) and
``gemini`` is a REQUIRED landing seat, so a 4/4 round silently became unlandable. The
signature reads as flakiness, and was misdiagnosed as backend stalls for a whole
milestone (#309) -- which is why this is pinned by a test rather than left to review.
"""
from __future__ import annotations

import subprocess

import pytest

from phase_loop_runtime import panel_invoker
from phase_loop_runtime.advisor_board import CODE_REVIEW_BOARD

_ROUTE_REFUSAL = "brokered Gemini model is not the authorized HARDEN route"


def _shipped_gemini_seat():
    seats = [s for s in CODE_REVIEW_BOARD.seats if (s.harness or "") == "gemini"]
    assert seats, "CODE_REVIEW_BOARD no longer has a gemini seat"
    return seats[0]


def _run_leg(tmp_path, monkeypatch, *, model, effort):
    """Drive the real guard, stubbing the launch so no CLI is spawned.

    Returns the ValueError message if the guard refused, else None.
    """
    review_dir = tmp_path / "review"
    out_dir = tmp_path / "out"
    review_dir.mkdir()
    out_dir.mkdir()
    (review_dir / "review-bundle.md").write_text("bundle")
    (review_dir / "review-instructions.md").write_text("instructions")

    def _no_launch(*a, **k):  # the guard runs BEFORE this; reaching it means it passed
        raise _Launched

    monkeypatch.setattr(subprocess, "run", _no_launch, raising=False)
    monkeypatch.setattr(panel_invoker.subprocess, "run", _no_launch, raising=False)

    try:
        panel_invoker._exec_leg(
            "gemini",
            review_dir,
            out_dir,
            timeout_s=5,
            artifact="artifact",
            model=model,
            effort=effort,
            broker_prompt="prompt",
            deadline_s=5,
        )
    except _Launched:
        return None
    except ValueError as exc:
        return str(exc)
    except Exception:
        # Any other failure is downstream of the guard, i.e. the guard passed.
        return None
    return None


class _Launched(Exception):
    """Raised by the stub to mark that the guard let execution through."""


def test_shipped_board_gemini_seat_is_routable_when_brokered(tmp_path, monkeypatch):
    """The regression. Before the fix this refused, so the seat could never fill."""
    seat = _shipped_gemini_seat()
    err = _run_leg(tmp_path, monkeypatch, model=seat.model, effort=seat.effort)
    assert err is None or _ROUTE_REFUSAL not in err, (
        f"the shipped CODE_REVIEW_BOARD gemini seat "
        f"({seat.model!r} + {seat.effort!r}) cannot be routed on the brokered path: {err}"
    )


def test_defaulted_model_is_still_refused(tmp_path, monkeypatch):
    """The guard's anti-defaulting intent must survive the fix.

    A caller that supplies no model gets a DEFAULTED route, which the broker never
    bound. That must still refuse -- otherwise the fix would trade one hole for another.
    """
    err = _run_leg(tmp_path, monkeypatch, model=None, effort="high")
    assert err is not None and _ROUTE_REFUSAL in err, (
        "a defaulted gemini model must still be refused on the brokered path"
    )


@pytest.mark.parametrize("effort", ["low", "medium", "high", "max"])
def test_every_effort_level_routes(tmp_path, monkeypatch, effort):
    """The bug was not specific to 'high' -- any non-None effort fused the id."""
    err = _run_leg(tmp_path, monkeypatch, model="gemini-3.8-flash", effort=effort)
    if err is not None and "HARDEN review route is unsupported" in err:
        pytest.skip(f"effort {effort!r} is not a supported HARDEN route")
    assert err is None or _ROUTE_REFUSAL not in err, (
        f"gemini-3.8-flash + {effort!r} is not routable when brokered: {err}"
    )
