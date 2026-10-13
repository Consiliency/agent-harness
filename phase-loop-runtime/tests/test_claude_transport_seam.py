"""Stage 2: the Claude transport seam (`tui | print | sdk`), agent-harness#1391.

`_resolve_claude_transport` is the one place a Claude panel seat and the president's Claude
rung learn their transport. `print` is the default and `tui` the fallback; `sdk` is a named
member of the seam that EC-REVIEWTRUTH-18 does not admit, so it is refused with its own code
(`panel_claude_transport_not_admitted`), never read as a typo and never a silent fallback.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import phase_loop_runtime.panel_invoker as pi
from phase_loop_runtime import president_adapter
from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD

_ROUTE_ENV = "PHASE_LOOP_PANEL_CLAUDE_ROUTE"
_FINDING = "F001: [fable] the dispatch lock is never released"


def _stage(tmp_path: Path) -> tuple[Path, Path]:
    review_dir = tmp_path / "review"
    review_dir.mkdir()
    (review_dir / "review-bundle.md").write_text("bundle", encoding="utf-8")
    (review_dir / "review-instructions.md").write_text("instructions", encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    return review_dir, out_dir


@pytest.fixture
def ready_host(monkeypatch):
    """A supported, subscription-authed host outside Claude Code (the gates pass)."""
    monkeypatch.delenv(_ROUTE_ENV, raising=False)
    monkeypatch.setattr(pi, "_under_claude_code", lambda env=None: False)
    monkeypatch.setattr(pi, "_claude_code_support_status", lambda *a, **k: (True, "supported"))
    monkeypatch.setattr(pi, "_claude_subscription_auth_ok", lambda env: (True, ""))


def _forbid_launches(monkeypatch) -> list:
    launched: list = []
    for name in ("_run_claude_print_session", "_run_claude_tui_session", "_run_leg_with_liveness"):
        monkeypatch.setattr(pi, name, lambda *a, _n=name, **k: launched.append(_n))
    return launched


@pytest.mark.parametrize("raw,tui_only,expected", [
    (None, False, ("print", None)),
    ("", False, ("print", None)),
    ("  ", False, ("print", None)),
    ("print", False, ("print", None)),
    (" TUI ", False, ("tui", None)),
    ("sdk", False, (None, "panel_claude_transport_not_admitted")),
    ("SDK", False, (None, "panel_claude_transport_not_admitted")),
    ("Print-ish", False, (None, "panel_claude_route_invalid")),
    ("channel", False, (None, "panel_claude_route_invalid")),
    # A seat only the TUI carries takes the TUI for an admitted selection ...
    (None, True, ("tui", None)),
    ("print", True, ("tui", None)),
    ("tui", True, ("tui", None)),
    # ... but a refused selection stays refused, whatever kind of seat read it.
    ("sdk", True, (None, "panel_claude_transport_not_admitted")),
    ("bogus", True, (None, "panel_claude_route_invalid")),
])
def test_the_seam_resolves_every_selection(monkeypatch, raw, tui_only, expected):
    if raw is None:
        monkeypatch.delenv(_ROUTE_ENV, raising=False)
    else:
        monkeypatch.setenv(_ROUTE_ENV, raw)
    assert pi._resolve_claude_transport(tui_only=tui_only) == expected


def test_the_seam_names_three_transports_and_admits_two():
    assert pi._PANEL_CLAUDE_TRANSPORTS == ("print", "tui", "sdk")
    assert pi._PANEL_CLAUDE_ADMITTED_TRANSPORTS == frozenset({"print", "tui"})


@pytest.mark.parametrize("raw", ["sdk", "bogus"])
def test_the_compat_route_is_the_admitted_subset(monkeypatch, raw):
    monkeypatch.setenv(_ROUTE_ENV, raw)
    assert pi._panel_claude_route() is None
    monkeypatch.setenv(_ROUTE_ENV, "tui")
    assert pi._panel_claude_route() == "tui"


def test_an_sdk_panel_seat_is_refused_without_launching(tmp_path, monkeypatch, ready_host):
    review_dir, out_dir = _stage(tmp_path)
    launched = _forbid_launches(monkeypatch)
    monkeypatch.setenv(_ROUTE_ENV, "sdk")
    assert pi._exec_claude_tui_leg(review_dir, out_dir, 60, "bundle") == (
        "UNAVAILABLE", "panel_claude_transport_not_admitted",
    )
    assert launched == []


def test_an_sdk_president_rung_is_refused_without_launching(tmp_path, monkeypatch, ready_host):
    monkeypatch.setenv(_ROUTE_ENV, "sdk")
    launched = _forbid_launches(monkeypatch)
    seam = president_adapter.build_president_invoke(
        DEFAULT_BOARD, repo_dir=str(tmp_path), base_env={}
    )
    response = seam("fable", _FINDING)
    assert response["status"] == "failed"
    assert "panel_claude_transport_not_admitted" in response["detail"]
    assert launched == []


@pytest.mark.parametrize("transport,expected", [("tui", "tui"), ("print", "print")])
def test_the_panel_leg_follows_the_seam(tmp_path, monkeypatch, ready_host, transport, expected):
    """The leg launches whatever the seam resolves, looked up late through the module, so
    the seam is the single switch (the environment says print throughout)."""
    review_dir, out_dir = _stage(tmp_path)
    launched: list = []
    monkeypatch.setattr(
        pi, "_run_claude_print_session",
        lambda *a, **k: launched.append("print") or (0, "AGREE", "claude_print_result", ""),
    )
    monkeypatch.setattr(
        pi, "_run_claude_tui_session",
        lambda **k: launched.append("tui") or (0, "AGREE", "claude_tui_file_output", ""),
    )
    monkeypatch.setattr(pi, "_resolve_claude_transport", lambda **k: (transport, None))
    pi._exec_claude_tui_leg(review_dir, out_dir, 60, "bundle")
    assert launched == [expected]


def test_the_panel_leg_reports_the_seam_refusal_verbatim(tmp_path, monkeypatch, ready_host):
    review_dir, out_dir = _stage(tmp_path)
    launched = _forbid_launches(monkeypatch)
    monkeypatch.setattr(pi, "_resolve_claude_transport", lambda **k: (None, "seam_refusal_probe"))
    assert pi._exec_claude_tui_leg(review_dir, out_dir, 60, "bundle") == (
        "UNAVAILABLE", "seam_refusal_probe",
    )
    assert launched == []


def test_the_president_follows_the_seam(tmp_path, monkeypatch, ready_host):
    launched = _forbid_launches(monkeypatch)
    monkeypatch.setattr(pi, "_resolve_claude_transport", lambda **k: (None, "seam_refusal_probe"))
    seam = president_adapter.build_president_invoke(
        DEFAULT_BOARD, repo_dir=str(tmp_path), base_env={}
    )
    response = seam("fable", _FINDING)
    assert response["status"] == "failed"
    assert "seam_refusal_probe" in response["detail"]
    assert launched == []
