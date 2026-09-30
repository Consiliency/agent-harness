"""PRESROUTE (agent-harness#952) CLI seams on ``advisor-board``: --landing-tier / --native-president.

Not part of the SL-0 frozen corpus. These pin the CLI wiring only: the flags reach
``invoke_board`` with the president seam bound to the DRIVING process's environment,
a deferral prints the pending request, and a resume without a tier is refused.
"""
from __future__ import annotations

import json
from pathlib import Path

from phase_loop_runtime import cli, panel_invoker, president_adapter
from phase_loop_runtime.advisor_board import backing
from phase_loop_runtime.panel_invoker import PanelResult


def _artifact(tmp_path: Path) -> Path:
    artifact = tmp_path / "artifact.md"
    artifact.write_text("# artifact\nreview me\n", encoding="utf-8")
    return artifact


def _stub_mint(monkeypatch, tmp_path=None) -> None:
    """Hermetic: no review mint, no vendor availability/auth probe, no user config."""
    from phase_loop_runtime.advisor_board import composition
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD

    monkeypatch.setattr(
        backing, "prepare_review_isolation_authorization", lambda *a, **k: None
    )
    monkeypatch.setattr(composition, "compose_review_board", lambda *a, **k: DEFAULT_BOARD)
    if tmp_path is not None:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))


def _landing_target(tmp_path: Path, monkeypatch) -> None:
    """PANEL SL-1 (agent-harness#1078, plan amendment #3, granted): a landing-tier run
    fetches its target at gate time and composes the code-review lanes through
    ``build_panel_context``. The run happens in a fixture repository whose ``origin`` has
    a commit, and the forced composer is ``compose_panel_board``, seating the node's own
    full board (all four vendors available)."""
    import subprocess

    from phase_loop_runtime.advisor_board import composition

    real = composition.compose_panel_board
    monkeypatch.setattr(composition, "compose_panel_board", lambda table, **_k: real(
        table, is_available=lambda v: True, auth_ok=lambda v: True, preflight=lambda v: True))
    repo = tmp_path / "repo"
    origin = tmp_path / "origin.git"
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "base"], check=True)
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run([*git, "remote", "add", "origin", str(origin)], check=True)
    subprocess.run([*git, "push", "-q", "origin", "HEAD:refs/heads/main"], check=True, capture_output=True)
    monkeypatch.chdir(repo)


def test_native_president_without_a_landing_tier_is_refused(tmp_path, monkeypatch, capsys):
    _stub_mint(monkeypatch, tmp_path)
    called: list[object] = []
    monkeypatch.setattr(panel_invoker, "invoke_board", lambda *a, **k: called.append(k))
    fill = tmp_path / "fill.json"
    fill.write_text("{}", encoding="utf-8")
    rc = cli.main(["advisor-board", str(_artifact(tmp_path)), "--native-president", str(fill)])
    assert rc == 2
    assert called == []
    assert "--native-president requires --landing-tier" in capsys.readouterr().err


def test_production_tier_binds_a_president_seam_to_the_driving_env(tmp_path, monkeypatch, capsys):
    _stub_mint(monkeypatch, tmp_path)
    _landing_target(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAUDECODE", "1")
    seen: dict[str, object] = {}

    def fake_invoke_board(board, artifact, **kwargs):
        seen.update(kwargs)
        result = PanelResult(legs=())
        object.__setattr__(
            result,
            "_needs_native_president",
            {"rung": "fable", "brief_digest": "b" * 64, "findings_digest": "f" * 64, "prompt": "P"},
        )
        return result

    monkeypatch.setattr(panel_invoker, "invoke_board", fake_invoke_board)
    artifact = _artifact(tmp_path)
    rc = cli.main([
        "advisor-board", str(artifact), "--landing-tier", "production_code",
        "--native-fill-dir", str(tmp_path), "--json",
    ])
    assert rc == 0
    assert seen["landing_tier"] == "production_code"
    seam = seen["president_invoke"]
    assert isinstance(seam, president_adapter.PresidentInvoke)
    # decided from THIS process's environment: under Claude Code the Fable rung defers.
    assert seam.base_env is not None and seam.base_env.get("CLAUDECODE") == "1"
    assert seen["stream_dir"] == tmp_path / "native-fill" / "president"
    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == "native_president_requested"
    assert printed["rung"] == "fable"
    assert printed["prompt"] == "P"


def test_native_president_fill_is_passed_through_for_resume(tmp_path, monkeypatch):
    _stub_mint(monkeypatch, tmp_path)
    _landing_target(tmp_path, monkeypatch)
    seen: dict[str, object] = {}

    def fake_invoke_board(board, artifact, **kwargs):
        seen.update(kwargs)
        return PanelResult(legs=())

    monkeypatch.setattr(panel_invoker, "invoke_board", fake_invoke_board)
    fill = {"rung": "fable", "brief_digest": "b", "findings_digest": "f", "text": "T"}
    fill_path = tmp_path / "fill.json"
    fill_path.write_text(json.dumps(fill), encoding="utf-8")
    cli.main([
        "advisor-board", str(_artifact(tmp_path)), "--landing-tier", "plan",
        "--native-president", str(fill_path), "--native-fill-dir", str(tmp_path),
    ])
    assert seen["native_president_fill"] == fill
    assert seen["landing_tier"] == "plan"
