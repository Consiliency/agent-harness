"""Configurable president ladder (built-in < user < repo) and the carried
agent-harness#998 follow-ups: brief-bound native resume (the #998 president's
BLOCKING F035), alias-aware resume rung, stale-ruling removal on deferral, and the
credential-less gemini HOME.

Not part of the PRESROUTE SL-0 frozen corpus.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from harden_tdd_guard import invoke_sanctioned_board_control
from phase_loop_runtime import panel_invoker, president_adapter
from phase_loop_runtime.advisor_board.config import (
    BoardConfigError,
    load_boards,
    load_president_ladder,
)
from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD, DEFAULT_SEATS
from phase_loop_runtime.advisor_board.schema import Board
from phase_loop_runtime.panel_invoker import (
    PRESIDENT_LADDER,
    PRESIDENT_LADDER_INVALID,
    PresidentPolicyError,
    ReviewLandingTier,
    validate_president_ladder,
)
from phase_loop_runtime.president_operation import (
    PRESIDENT_FILL_DIGEST_MISMATCH,
    run_president_operation,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
OUR_LADDER = ("fable", "sol", "grok", "gemini")


def _user_cfg(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "user" / "advisor-boards.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _repo(tmp_path: Path, body: str | None) -> Path:
    repo = tmp_path / "repo"
    (repo / ".agent-harness").mkdir(parents=True, exist_ok=True)
    if body is not None:
        (repo / ".agent-harness" / "advisor-boards.toml").write_text(body, encoding="utf-8")
    return repo


# --- validation ---------------------------------------------------------------------


def test_our_order_and_the_built_in_order_validate():
    assert validate_president_ladder(list(OUR_LADDER)) == OUR_LADDER
    assert validate_president_ladder(PRESIDENT_LADDER) == PRESIDENT_LADDER


@pytest.mark.parametrize(
    "ladder", [[], "fable", ["fable", "fable"], ["fable", "nobody"], ["fable", 3], None]
)
def test_a_malformed_ladder_is_refused(ladder):
    with pytest.raises(PresidentPolicyError) as excinfo:
        validate_president_ladder(ladder)
    assert excinfo.value.code == PRESIDENT_LADDER_INVALID


# --- layering -----------------------------------------------------------------------


def test_no_config_is_the_built_in_ladder(tmp_path):
    assert load_president_ladder(_repo(tmp_path, None), path=tmp_path / "absent.toml") == PRESIDENT_LADDER


def test_the_user_ladder_overrides_the_built_in(tmp_path):
    user = _user_cfg(tmp_path, '[president]\nladder = ["grok", "sol"]\n')
    assert load_president_ladder(_repo(tmp_path, None), path=user) == ("grok", "sol")


def test_the_repo_ladder_overrides_the_user(tmp_path):
    user = _user_cfg(tmp_path, '[president]\nladder = ["grok", "sol"]\n')
    repo = _repo(tmp_path, '[president]\nladder = ["gemini", "fable"]\n')
    assert load_president_ladder(repo, path=user) == ("gemini", "fable")


def test_a_layer_without_a_ladder_leaves_the_lower_one(tmp_path):
    user = _user_cfg(tmp_path, '[president]\nladder = ["grok", "sol"]\n')
    repo = _repo(tmp_path, "[president]\n")
    assert load_president_ladder(repo, path=user) == ("grok", "sol")


@pytest.mark.parametrize(
    "body",
    [
        '[president]\nladder = ["fable", "nobody"]\n',
        '[president]\nladder = []\n',
        '[president]\norder = ["fable"]\n',
        'president = "fable"\n',
        '[[boards]]\nname = "x"\n',  # repo-level boards are not a feature: refused, not ignored
        "not toml [",
    ],
)
def test_a_bad_repo_file_is_an_error_never_a_silent_fallback(tmp_path, body):
    with pytest.raises(BoardConfigError):
        load_president_ladder(_repo(tmp_path, body), path=tmp_path / "absent.toml")


def test_a_bad_user_president_table_fails_load_boards_too(tmp_path):
    user = _user_cfg(tmp_path, '[president]\nladder = ["fable", "fable"]\n')
    with pytest.raises(BoardConfigError):
        load_boards(user, validate=False, is_available=lambda _v: True, auth_ok=lambda _v: True)


def test_a_valid_user_president_table_loads_with_the_boards(tmp_path):
    user = _user_cfg(tmp_path, '[president]\nladder = ["fable", "sol"]\n')
    config = load_boards(user, validate=False, is_available=lambda _v: True, auth_ok=lambda _v: True)
    assert config.default_board


def test_this_repository_configures_our_order():
    assert load_president_ladder(REPO_ROOT, path=REPO_ROOT / "no-user-config.toml") == OUR_LADDER


# --- the seam walks the configured order ---------------------------------------------


class _RecordingSeam:
    def __init__(self, ladder, answers):
        self.ladder = ladder
        self.answers = answers
        self.asked: list[str] = []

    def __call__(self, rung, prompt):
        self.asked.append(rung)
        if rung in self.answers:
            return {"status": "ok", "text": "FINDING F001: DEFERRED — ok\nFORCING DECISION: LAND"}
        return {"status": "unavailable", "code": "president_unavailable", "detail": "down"}


def _authorization():
    from types import SimpleNamespace

    from phase_loop_runtime.president_operation import PRESIDENT_OPERATION

    return SimpleNamespace(operation=PRESIDENT_OPERATION)


def test_the_configured_ladder_is_walked_first_rung_first():
    seam = _RecordingSeam(OUR_LADDER, answers={"sol"})
    result = run_president_operation(
        brief="b", findings=("F001: [x] y",), authorization=_authorization(),
        invoke=seam, max_substantive_rounds=3,
    )
    assert seam.asked == ["fable", "sol"]
    assert result.ruling.model == "sol"
    assert result.rung_index == 1  # against the configured ladder, not the built-in


def test_a_seam_without_a_ladder_walks_the_built_in_order():
    seam = _RecordingSeam(None, answers={"fable"})
    run_president_operation(
        brief="b", findings=("F001: [x] y",), authorization=_authorization(),
        invoke=seam, max_substantive_rounds=3,
    )
    assert seam.asked == list(PRESIDENT_LADDER[: PRESIDENT_LADDER.index("fable") + 1])


def test_build_president_invoke_validates_and_carries_the_ladder():
    seam = president_adapter.build_president_invoke(DEFAULT_BOARD, ladder=list(OUR_LADDER))
    assert seam.ladder == OUR_LADDER
    with pytest.raises(PresidentPolicyError):
        president_adapter.build_president_invoke(DEFAULT_BOARD, ladder=["nobody"])


# --- native defer/resume follow-ups -------------------------------------------------


def _ok_spawn(leg: str, artifact: str) -> tuple[str, str]:
    return "OK", f"{leg} found: the {leg} concern\nAGREE"


def _fable_board() -> Board:
    return Board(
        name="fable-president", purpose="premerge-review",
        seats=tuple(seat for seat in DEFAULT_SEATS if seat.harness != "codex"),
    )


_POLICY = panel_invoker.ReviewLandingPolicy(
    required_seats=("fable", "gemini", "grok"), requires_president=True
)


def _dispatch(stream, **extra):
    return invoke_sanctioned_board_control(
        _fable_board(), "artifact", spawn=_ok_spawn,
        landing_tier=ReviewLandingTier.PRODUCTION_CODE, review_policy=_POLICY,
        base_env={"CLAUDECODE": "1"}, stream_dir=stream, **extra,
    )


def _fill_for(deferred):
    pending = deferred.needs_native_president
    text = "\n".join(
        f"FINDING {f.split(':', 1)[0]}: DEFERRED — ruled" for f in deferred.president_findings
    ) + "\nFORCING DECISION: LAND"
    return {"rung": pending["rung"], "brief_digest": pending["brief_digest"],
            "findings_digest": pending["findings_digest"], "text": text}


# The #998 president's BLOCKING F035: the seats' verdicts answer the review brief, so a
# resume under a different brief must not report brief-A verdicts under brief B.
def test_a_resume_under_a_different_review_brief_is_refused(tmp_path):
    brief_a = tmp_path / "brief-a.md"
    brief_b = tmp_path / "brief-b.md"
    brief_a.write_text("Review brief ONE.", encoding="utf-8")
    brief_b.write_text("Review brief TWO.", encoding="utf-8")
    stream = tmp_path / "stream"
    deferred = _dispatch(stream, brief_ref=str(brief_a))
    fill = _fill_for(deferred)
    pending_path = stream / panel_invoker.PRESIDENT_PENDING_FILENAME
    before = pending_path.read_bytes()
    with pytest.raises(PresidentPolicyError) as excinfo:
        _dispatch(stream, brief_ref=str(brief_b), native_president_fill=fill)
    assert excinfo.value.code == PRESIDENT_FILL_DIGEST_MISMATCH
    assert pending_path.read_bytes() == before  # the refusal modifies nothing
    assert not (stream / "president.ruling.json").exists()
    # ... and the ORIGINAL brief still resumes.
    assert _dispatch(stream, brief_ref=str(brief_a), native_president_fill=fill).president is not None


def test_a_new_deferral_removes_a_stale_ruling_from_the_stream(tmp_path):
    stream = tmp_path / "stream"
    stream.mkdir()
    (stream / "president.ruling.json").write_text('{"stale": true}', encoding="utf-8")
    deferred = _dispatch(stream)
    assert deferred.needs_native_president is not None
    assert not (stream / "president.ruling.json").exists()


def test_the_resume_rung_check_honours_review_seat_aliases(tmp_path):
    # A claude seat whose model the DEFAULT alias table does not know, answering to
    # "fable" only through ``review_seat_aliases``: the deferral finds the rung through
    # the aliases, so the resume must too.
    from dataclasses import replace

    model = "claude-sonnet-5"
    assert model not in panel_invoker.DEFAULT_REVIEW_SEAT_ALIASES
    board = Board(
        name="aliased", purpose="premerge-review",
        seats=tuple(
            replace(seat, model=model) if seat.harness == "claude" else seat
            for seat in DEFAULT_SEATS if seat.harness != "codex"
        ),
    )
    aliases = {model: "fable"}
    stream = tmp_path / "stream"

    def dispatch(**extra):
        return invoke_sanctioned_board_control(
            board, "artifact", spawn=_ok_spawn,
            landing_tier=ReviewLandingTier.PRODUCTION_CODE, review_policy=_POLICY,
            base_env={"CLAUDECODE": "1"}, stream_dir=stream,
            review_seat_aliases=aliases, **extra,
        )

    deferred = dispatch()
    assert deferred.needs_native_president["rung"] == "fable"
    assert dispatch(native_president_fill=_fill_for(deferred)).president is not None


# --- gemini rung follow-ups ---------------------------------------------------------


def test_the_credential_less_gemini_home_carries_the_deny_all_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "no-credential-home"))
    seen: list[dict[str, object]] = []

    def capture(argv, **kwargs):
        # Inspect the HOME WHILE the launch holds it (it is reclaimed afterwards).
        home = Path((kwargs.get("env") or {})["HOME"])
        settings = home / ".gemini" / "antigravity-cli" / "settings.json"
        seen.append({
            "home": home,
            "files": sorted(str(p.relative_to(home)) for p in home.rglob("*") if p.is_file()),
            "settings": settings.read_bytes() if settings.is_file() else None,
        })
        raise RuntimeError("no agy here")

    with patch.object(panel_invoker, "launch_provider", capture):
        seam = president_adapter.build_president_invoke(DEFAULT_BOARD, repo_dir=str(tmp_path), base_env={})
        seam("gemini", "F001: [gemini] x")
    assert len(seen) == 1
    assert seen[0]["home"] != tmp_path / "no-credential-home"
    assert seen[0]["files"] == [".gemini/antigravity-cli/settings.json"]  # no credential of any kind
    assert seen[0]["settings"] == panel_invoker._broker_agy_settings_bytes()
    assert not seen[0]["home"].exists()


def test_a_gemini_ruling_is_read_through_the_acknowledged_stream_decoder(tmp_path):
    prompt = panel_invoker._president_prompt(("F001: [gemini] x",))
    decoded: list[tuple[str, object]] = []

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="RAW-STREAM", stderr="")

    def fake_decode(stdout, protocol):
        decoded.append((stdout, protocol))
        return 0, "FINDING F001: DEFERRED — ok\nFORCING DECISION: LAND", None, {}

    with patch.object(panel_invoker, "_run_leg_with_liveness", fake_run), patch.object(
        panel_invoker, "_broker_gemini_stream_result", fake_decode
    ):
        seam = president_adapter.build_president_invoke(DEFAULT_BOARD, repo_dir=str(tmp_path), base_env={})
        response = seam("gemini", prompt)
    assert len(decoded) == 1
    stdout, protocol = decoded[0]
    assert stdout == "RAW-STREAM"
    expected = president_adapter._president_gemini_stream_protocol(prompt)
    assert protocol.final_event_sha256 == expected.final_event_sha256
    assert response["status"] == "ok" and "FORCING DECISION" in response["text"]


# --- the configured ladder reaches the live entry points ----------------------------


def _git_repo(tmp_path: Path, body: str) -> Path:
    repo = _repo(tmp_path, body)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    return repo


def _cli_env(monkeypatch, tmp_path):
    from phase_loop_runtime.advisor_board import backing, composition

    monkeypatch.setattr(backing, "prepare_review_isolation_authorization", lambda *a, **k: None)
    monkeypatch.setattr(composition, "compose_review_board", lambda *a, **k: DEFAULT_BOARD)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("CLAUDECODE", "1")
    artifact = tmp_path / "artifact.md"
    artifact.write_text("# artifact\n", encoding="utf-8")
    return artifact


def test_the_cli_binds_the_repositorys_configured_ladder(tmp_path, monkeypatch):
    from phase_loop_runtime import cli
    from phase_loop_runtime.panel_invoker import PanelResult

    artifact = _cli_env(monkeypatch, tmp_path)
    monkeypatch.chdir(_git_repo(tmp_path, '[president]\nladder = ["gemini", "fable"]\n'))
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        panel_invoker, "invoke_board", lambda board, art, **kw: seen.update(kw) or PanelResult(legs=())
    )
    cli.main(["advisor-board", str(artifact), "--landing-tier", "production_code",
              "--native-fill-dir", str(tmp_path), "--json"])
    assert seen["president_invoke"].ladder == ("gemini", "fable")


def test_the_cli_refuses_a_malformed_ladder_before_the_board_runs(tmp_path, monkeypatch, capsys):
    from phase_loop_runtime import cli

    artifact = _cli_env(monkeypatch, tmp_path)
    monkeypatch.chdir(_git_repo(tmp_path, '[president]\nladder = ["nobody"]\n'))
    called: list[object] = []
    monkeypatch.setattr(panel_invoker, "invoke_board", lambda *a, **k: called.append(k))
    rc = cli.main(["advisor-board", str(artifact), "--landing-tier", "production_code",
                   "--native-fill-dir", str(tmp_path), "--json"])
    assert rc == 2 and called == []
    assert "president ladder config" in capsys.readouterr().err


def test_the_auto_wired_seam_walks_the_repositorys_ladder(tmp_path):
    repo = _repo(tmp_path, '[president]\nladder = ["fable"]\n')
    stream = tmp_path / "stream"
    deferred = _dispatch(stream, repo_dir=str(repo))
    assert deferred.needs_native_president["rung"] == "fable"
    pending = json.loads((stream / panel_invoker.PRESIDENT_PENDING_FILENAME).read_text())
    assert pending["binding"]["ladder"] == ["fable"]


def test_the_auto_wired_seam_refuses_a_malformed_ladder_before_any_seat(tmp_path):
    repo = _repo(tmp_path, '[president]\nladder = ["fable", "fable"]\n')
    ran: list[str] = []

    def spawn(leg, artifact):
        ran.append(leg)
        return _ok_spawn(leg, artifact)

    with pytest.raises(PresidentPolicyError) as excinfo:
        invoke_sanctioned_board_control(
            _fable_board(), "artifact", spawn=spawn,
            landing_tier=ReviewLandingTier.PRODUCTION_CODE, review_policy=_POLICY,
            base_env={"CLAUDECODE": "1"}, stream_dir=tmp_path / "stream", repo_dir=str(repo),
        )
    assert excinfo.value.code == PRESIDENT_LADDER_INVALID
    assert ran == []


# --- agent-harness#1004 round-1 board findings ---------------------------------------


def test_the_runner_seam_carries_the_repositorys_ladder(tmp_path, monkeypatch):
    # native seat B1: the phase-loop runner built its seam without the configured ladder.
    from test_president_wiring import _ruling, _runner_fixture, _stub_board_result

    from phase_loop_runtime import runner

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    repo, run_dir, bundle = _runner_fixture(tmp_path)
    (repo / ".agent-harness").mkdir()
    (repo / ".agent-harness" / "advisor-boards.toml").write_text(
        '[president]\nladder = ["fable", "sol", "grok", "gemini"]\n', encoding="utf-8"
    )
    seen: dict[str, object] = {}

    def capture(*_a, **kw):
        seen.update(kw)
        return _stub_board_result(_ruling("FINDING F001: DEFERRED — ok\nFORCING DECISION: LAND"))

    monkeypatch.setattr(panel_invoker, "invoke_board", capture)
    runner._run_legible_panel(repo, run_dir, "1" * 40, bundle)
    assert seen["president_invoke"].ladder == OUR_LADDER


def test_a_passed_environment_never_reads_the_process_home(tmp_path, monkeypatch):
    # native seat B2: the user layer follows the PASSED env, never the process HOME.
    process_home = tmp_path / "process-home"
    cfg = process_home / ".config" / "agent-harness" / "advisor-boards.toml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text('[president]\nladder = ["fable", "fable"]\n', encoding="utf-8")  # malformed
    monkeypatch.setenv("HOME", str(process_home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert load_president_ladder(None, env={}) == PRESIDENT_LADDER
    other = tmp_path / "other-home"
    ocfg = other / ".config" / "agent-harness" / "advisor-boards.toml"
    ocfg.parent.mkdir(parents=True)
    ocfg.write_text('[president]\nladder = ["grok"]\n', encoding="utf-8")
    assert load_president_ladder(None, env={"HOME": str(other)}) == ("grok",)
    # and the auto-wired seam (base_env without HOME) is unaffected by the bad process file
    deferred = _dispatch(tmp_path / "stream")
    assert deferred.needs_native_president["rung"] == "fable"


def test_a_brief_edited_after_the_seats_read_it_cannot_rebind_their_verdicts(tmp_path):
    # codex B2: the brief digest is captured before any seat runs.
    brief = tmp_path / "brief.md"
    brief.write_text("Review brief ONE.", encoding="utf-8")
    stream = tmp_path / "stream"

    def editing_spawn(leg, artifact):
        brief.write_text("Review brief TWO.", encoding="utf-8")  # changed mid-run
        return _ok_spawn(leg, artifact)

    deferred = invoke_sanctioned_board_control(
        _fable_board(), "artifact", spawn=editing_spawn,
        landing_tier=ReviewLandingTier.PRODUCTION_CODE, review_policy=_POLICY,
        base_env={"CLAUDECODE": "1"}, stream_dir=stream, brief_ref=str(brief),
    )
    fill = _fill_for(deferred)
    with pytest.raises(PresidentPolicyError) as excinfo:  # brief now reads TWO
        _dispatch(stream, brief_ref=str(brief), native_president_fill=fill)
    assert excinfo.value.code == PRESIDENT_FILL_DIGEST_MISMATCH
    brief.write_text("Review brief ONE.", encoding="utf-8")
    assert _dispatch(stream, brief_ref=str(brief), native_president_fill=fill).president is not None


def test_a_brief_that_vanishes_before_resume_is_a_typed_refusal(tmp_path):
    brief = tmp_path / "brief.md"
    brief.write_text("Review brief ONE.", encoding="utf-8")
    stream = tmp_path / "stream"
    fill = _fill_for(_dispatch(stream, brief_ref=str(brief)))
    brief.unlink()
    with pytest.raises(PresidentPolicyError):
        _dispatch(stream, brief_ref=str(brief), native_president_fill=fill)


def test_an_aliased_ruling_is_recorded_with_the_aliased_seats_model(tmp_path):
    # codex B1: persistence resolves the rung through the same aliases as the resume.
    from dataclasses import replace

    model = "claude-sonnet-5"
    board = Board(
        name="aliased", purpose="premerge-review",
        seats=tuple(
            replace(seat, model=model) if seat.harness == "claude" else seat
            for seat in DEFAULT_SEATS if seat.harness != "codex"
        ),
    )
    stream = tmp_path / "stream"

    def dispatch(**extra):
        return invoke_sanctioned_board_control(
            board, "artifact", spawn=_ok_spawn,
            landing_tier=ReviewLandingTier.PRODUCTION_CODE, review_policy=_POLICY,
            base_env={"CLAUDECODE": "1"}, stream_dir=stream,
            review_seat_aliases={model: "fable"}, **extra,
        )

    dispatch(native_president_fill=_fill_for(dispatch()))
    record = json.loads((stream / "president.ruling.json").read_text())
    assert record["model_id"] == model


def test_a_model_id_and_its_alias_are_the_same_rung():
    claude_model = next(s.model for s in DEFAULT_SEATS if s.harness == "claude")
    with pytest.raises(PresidentPolicyError) as excinfo:
        validate_president_ladder([claude_model, "fable"])
    assert excinfo.value.code == PRESIDENT_LADDER_INVALID


def test_a_synthesised_ladder_attribute_is_not_a_configured_ladder():
    from unittest.mock import MagicMock

    assert panel_invoker.effective_president_ladder(MagicMock()) == PRESIDENT_LADDER


def test_a_ruling_consumes_any_pending_request_left_in_the_stream(tmp_path):
    # native seat F4: an older pending request must not later resume over a newer ruling.
    from phase_loop_runtime.panel_invoker import PresidentRuling

    stream = tmp_path / "stream"
    stream.mkdir()
    pending = stream / panel_invoker.PRESIDENT_PENDING_FILENAME
    pending.write_text("{}", encoding="utf-8")
    ruling = PresidentRuling(
        model="grok", text="FINDING F001: DEFERRED — ok\nFORCING DECISION: LAND",
        substantive_rounds=1, format_reasks=0,
    )
    panel_invoker._persist_president_ruling(stream, DEFAULT_BOARD, ruling, ("F001: [x] y",))
    assert (stream / "president.ruling.json").is_file() and not pending.exists()


@pytest.mark.parametrize("kind", ["directory", "binary"])
def test_an_unreadable_config_is_a_typed_error(tmp_path, kind):
    repo = _repo(tmp_path, None)
    target = repo / ".agent-harness" / "advisor-boards.toml"
    if kind == "directory":
        target.mkdir()
    else:
        target.write_bytes(b"\xff\xfe[president]\n")
    with pytest.raises(BoardConfigError):
        load_president_ladder(repo, path=tmp_path / "absent.toml")
