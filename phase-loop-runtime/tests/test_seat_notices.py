"""Typed seat notices (agent-harness#1132): J13, F030, delivery surfaces, reap (F022).

Every notice code is an exact literal of the closed detail vocabulary (F030), each
failure yields exactly one code, and each code reaches the `advisor-board` payload and
text summary. The governed-path surface is lane L4b and waits on agent-harness#1071.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import time
import types
import unittest.mock
from pathlib import Path

import pytest

from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import seat_jail, seat_uid


GOVERNED_1071 = "L4b governed-path notice rendering waits on agent-harness#1071"


# --------------------------------------------------------------------------------------
# F030: exact literals in the closed vocabulary.
# --------------------------------------------------------------------------------------

def test_f030_every_notice_code_is_an_exact_detail_literal():
    missing = sorted(seat_jail.NOTICE_CODES - pi._HARNESS_DETAIL_CODES)
    assert missing == [], f"notice codes outside the closed detail vocabulary: {missing}"


@pytest.mark.parametrize("code", sorted(seat_jail.NOTICE_CODES))
def test_f030_leg_detail_equals_the_literal_after_finalize(code):
    leg = pi.PanelLegResult(leg="claude", status="DEGRADED", text="", detail=code,
                            seat_key="claude:a")
    assert leg.detail == code
    assert pi._finalize_leg_detail(code) == code


def test_f030_no_regex_template_admits_a_seat_code():
    """Each sub-code is its own literal: no template may widen the vocabulary."""
    for pattern in pi._HARNESS_DETAIL_CODE_TEMPLATES:
        assert not pattern.fullmatch("seat_sandbox_refused:anything_else")
    assert pi._finalize_leg_detail("seat_sandbox_refused:anything_else") == pi._UNKNOWN_DETAIL


def test_notice_table_rows_are_complete_literals():
    for code, (what, why, fix) in seat_jail.NOTICES.items():
        assert code and what and why and fix


def test_sealed_fallback_codes_are_notices():
    assert seat_jail.SEALED_FALLBACK_CODES <= seat_jail.NOTICE_CODES


# --------------------------------------------------------------------------------------
# J13: one code per failure; rendered only from literals.
# --------------------------------------------------------------------------------------

def test_a_leg_ending_notice_is_also_its_detail_and_appears_once():
    leg = pi.PanelLegResult(leg="claude", status="DEGRADED", text="",
                            detail="seat_sandbox_refused:stage_changed", seat_key="claude:a")
    pi.attach_seat_notices(leg, ["seat_sandbox_refused:stage_changed"])
    assert [n.code for n in leg.seat_notices] == ["seat_sandbox_refused:stage_changed"]


def test_cli_text_shaped_like_a_code_yields_no_notice():
    text = "seat_sandbox_refused:identity\nclaude_seat_token_in_output\nAGREE"
    leg = pi.PanelLegResult(leg="claude", status="OK", text=text, seat_key="claude:a")
    assert leg.seat_notices == ()

    class _Sly(str):
        pass

    pi.attach_seat_notices(leg, [_Sly("seat_sandbox_refused:identity"), "not_a_code"])
    # The attach layer alone (the renderer's own exact-type check is a second layer).
    assert getattr(leg, "_seat_notice_codes") == ()
    assert leg.seat_notices == ()


def test_rendered_fields_are_the_table_literals():
    notice = seat_jail.render_notice("seat_sandbox_unavailable_seat_uid", "claude:a")
    assert notice.as_json() == {
        "code": "seat_sandbox_unavailable_seat_uid", "seat_key": "claude:a",
        "what": "inline fallback", "why": "no subordinate seat uid on this host",
        "fix": seat_jail.NOTICES["seat_sandbox_unavailable_seat_uid"][2],
    }
    assert seat_jail.render_notice("seat_sandbox_refused:bogus", "x") is None


def test_refusal_exception_carries_exactly_one_known_code():
    with pytest.raises(ValueError):
        seat_jail.SeatSandboxRefused("seat_sandbox_refused:bogus")
    exc = seat_jail.SeatSandboxRefused("seat_sandbox_refused:namespace", "free text")
    assert pi._exception_failure(exc) == "seat_sandbox_refused:namespace"


# --------------------------------------------------------------------------------------
# Delivery through the production brokered branch of `_default_spawn`.
# --------------------------------------------------------------------------------------

class _FakeBroker:
    invoked = 0

    def __init__(self, *_a, **_k):
        self.evidence: dict[str, object] = {}

    def run_credentialless_client(self, adapter, *, deadline_s, cancel_event=None):
        type(self).invoked += 1
        status, text = adapter.invoke()
        return {"schema": "parent_unix_broker_v1", "status": status, "text": text}, {"fake": True}

    def close(self):
        return None


def _brokered(monkeypatch, tmp_path, leg: str, staged: str | None):
    assert not pi._has_injected_review_execution_seam(leg=leg)
    monkeypatch.setattr(pi, "ParentUnixBroker", _FakeBroker)
    monkeypatch.setattr(pi, "revalidate_review_isolation_authorization", lambda *a, **k: None)
    monkeypatch.setattr(pi._advisor_board_backing, "_revalidate_staged_tree", lambda *a, **k: None)
    monkeypatch.setattr(pi, "derive_review_leg_authorization",
                        lambda *a, **k: types.SimpleNamespace(expires_monotonic_ns=time.monotonic_ns() + 10**12))
    monkeypatch.setattr(pi, "harden_subscription_model", lambda leg, model, effort=None: model)
    monkeypatch.setattr(pi, "_canonical_review_repo_authority", lambda _p: tmp_path)
    monkeypatch.setattr(pi, "_claude_code_support_status", lambda *a: (False, "missing_claude_cli"))
    monkeypatch.setattr(pi, "_under_claude_code", lambda env=None: False)
    monkeypatch.setattr(_FakeBroker, "invoked", 0)
    return pi._default_spawn(
        leg, "ARTIFACT", mode="review", model="m",
        review_authorization=types.SimpleNamespace(staged_tree_sha256=staged),
        canonical_repo_authority=tmp_path,
    )


def test_sealed_claude_seat_carries_its_notice_through_the_spawn(monkeypatch, tmp_path):
    spawned = _brokered(monkeypatch, tmp_path, "claude", None)
    assert _FakeBroker.invoked == 1
    assert spawned.seat_notices == ("seat_sandbox_not_staged",)


def test_jailed_route_without_an_execfind_pass_is_refused_with_zero_launches(monkeypatch, tmp_path):
    monkeypatch.setattr(pi._seat_jail, "decide_seat_route",
                        lambda leg, **k: seat_jail.SeatRoute(True))
    spawned = _brokered(monkeypatch, tmp_path, "claude", "a" * 64)
    assert _FakeBroker.invoked == 0
    assert tuple(spawned)[0] == "DEGRADED"
    assert pi._finalize_leg_detail(tuple(spawned)[-1]) == "seat_sandbox_refused:jail_unqualified"
    assert spawned.seat_notices == ("seat_sandbox_refused:jail_unqualified",)
    notice = seat_jail.render_notice("seat_sandbox_refused:jail_unqualified", "claude:a")
    assert "per-host EC-EXECFIND-2 jail qualification" in notice.fix
    assert "seat-jail-passes" in notice.fix


def test_gemini_seat_stays_sealed_with_one_notice(monkeypatch, tmp_path):
    route, notices, refusal = pi._seat_route_for_spawn(
        "gemini", types.SimpleNamespace(staged_tree_sha256="a" * 64), eligible=True)
    assert not route.jailed and len(notices) == 1 and refusal is None
    assert notices[0] in seat_jail.SEALED_FALLBACK_CODES


# --------------------------------------------------------------------------------------
# The advisor-board payload and text summary.
# --------------------------------------------------------------------------------------

def _run_board(tmp_path, legs, *, json_out: bool):
    from phase_loop_runtime.advisor_board import composition as comp_mod
    from phase_loop_runtime.cli import main as cli_main

    real_compose = comp_mod.compose_review_board
    artifact = tmp_path / "bundle.md"
    artifact.write_text("review me\n")
    out, err = io.StringIO(), io.StringIO()
    with (
        unittest.mock.patch.object(
            comp_mod, "compose_review_board",
            side_effect=lambda *a, **k: real_compose(
                is_available=lambda v: v in {"codex", "gemini", "claude", "grok"}),
        ),
        unittest.mock.patch.object(pi, "invoke_board", return_value=pi.PanelResult(legs=legs)),
        contextlib.redirect_stdout(out), contextlib.redirect_stderr(err),
    ):
        cli_main(["advisor-board", *(["--json"] if json_out else []), str(artifact)])
    return out.getvalue(), err.getvalue()


def _legs():
    claude = pi.PanelLegResult(leg="claude", status="OK", text="AGREE", seat_key="claude:a")
    pi.attach_seat_notices(claude, ["seat_sandbox_unavailable_seat_uid"])
    codex = pi.PanelLegResult(leg="codex", status="OK", text="AGREE", seat_key="codex:a")
    pi.attach_seat_notices(codex, ["seat_filesystem_unconfined"])
    gemini = pi.PanelLegResult(leg="gemini", status="DEGRADED", text="",
                               detail="seat_sandbox_refused:output_unsafe", seat_key="gemini:a")
    grok = pi.PanelLegResult(leg="grok", status="OK", text="seat_tool_denied AGREE",
                             seat_key="grok:a")
    return (claude, codex, gemini, grok)


def test_payload_surface_carries_board_and_leg_notices(tmp_path):
    out, _err = _run_board(tmp_path, _legs(), json_out=True)
    payload = json.loads(out)
    codes = sorted(n["code"] for n in payload["notices"])
    assert codes == ["seat_filesystem_unconfined", "seat_sandbox_refused:output_unsafe",
                     "seat_sandbox_unavailable_seat_uid"]
    per_leg = {leg["seat_key"]: [n["code"] for n in leg["notices"]] for leg in payload["legs"]}
    assert per_leg == {"claude:a": ["seat_sandbox_unavailable_seat_uid"],
                       "codex:a": ["seat_filesystem_unconfined"],
                       "gemini:a": ["seat_sandbox_refused:output_unsafe"], "grok:a": []}


def test_text_summary_surface_names_each_notice_once(tmp_path):
    out, _err = _run_board(tmp_path, _legs(), json_out=False)
    for code in ("seat_sandbox_unavailable_seat_uid", "seat_filesystem_unconfined",
                 "seat_sandbox_refused:output_unsafe"):
        assert out.count(f"notice {code}:") == 1, out
    assert "notice seat_tool_denied" not in out


@pytest.mark.skip(reason=GOVERNED_1071)
def test_governed_surface_renders_every_notice():
    """L4b: `governed_review.py` renders `notices` after agent-harness#1071 lands."""


# --------------------------------------------------------------------------------------
# F022/F020: reap accepts only a recorded, contained, subuid-owned directory.
# --------------------------------------------------------------------------------------

def _record(records: Path, path: Path) -> None:
    records.mkdir(exist_ok=True, mode=0o700)
    (records / f"r-{abs(hash(str(path)))}.json").write_text(json.dumps({"path": str(path)}))


def test_reap_refuses_an_unrecorded_path(tmp_path):
    with pytest.raises(seat_uid.ReapRefused, match="not recorded"):
        seat_uid.validate_reap_target(str(tmp_path / "x"), records=tmp_path / "records",
                                      root=tmp_path)


def test_reap_refuses_a_path_outside_the_stage_root(tmp_path):
    records = tmp_path / "records"
    elsewhere = Path("/etc")
    _record(records, elsewhere)
    with pytest.raises(seat_uid.ReapRefused, match="stage root"):
        seat_uid.validate_reap_target(str(elsewhere), records=records, root=tmp_path / "stage")


def test_reap_refuses_a_symlinked_component(tmp_path):
    stage = tmp_path / "stage"
    (stage / "real" / "seat-home").mkdir(parents=True)
    (stage / "alias").symlink_to(stage / "real")
    records = tmp_path / "records"
    target = stage / "alias" / "seat-home"
    _record(records, target)
    with pytest.raises(seat_uid.ReapRefused, match="without following a link"):
        seat_uid.validate_reap_target(str(target), records=records, root=stage)


def test_reap_refuses_an_operator_owned_directory(tmp_path):
    stage = tmp_path / "stage"
    target = stage / "pl-panel-x" / "seat" / "seat-home"
    target.mkdir(parents=True)
    records = tmp_path / "records"
    _record(records, target)
    subuid = tmp_path / "subuid"
    subuid.write_text(f"{os.getuid()}:200000:65536\n")
    with pytest.raises(seat_uid.ReapRefused, match="subordinate"):
        seat_uid.validate_reap_target(str(target), records=records, root=stage, subuid=subuid)


def test_reap_mutation_accepting_any_owner_would_pass_the_operator_dir(tmp_path, monkeypatch):
    stage = tmp_path / "stage"
    target = stage / "seat-home"
    target.mkdir(parents=True)
    records = tmp_path / "records"
    _record(records, target)
    monkeypatch.setattr(seat_uid, "owned_by_subordinate", lambda *a, **k: True)
    fd = seat_uid.validate_reap_target(str(target), records=records, root=stage)
    os.close(fd)


def test_retention_record_sits_under_an_operator_owned_0700_parent(tmp_path):
    """F020: the leg's mkdtemp scratch dir is the retained directory's 0700 parent."""
    import tempfile

    scratch = Path(tempfile.mkdtemp(prefix="pl-panel-", dir=tmp_path))
    info = scratch.stat()
    assert info.st_uid == os.getuid() and info.st_mode & 0o777 == 0o700
    record = seat_uid.record_retention(scratch / "seat" / "seat-home", directory=tmp_path / "r")
    assert json.loads(record.read_text())["path"] == str(scratch / "seat" / "seat-home")


def test_codex_r1_reap_namespace_is_mapped_only_after_it_exists(monkeypatch):
    """Board round 1 (codex): `mapped_namespace` wrote the map straight after `Popen`. With a
    self-map that fails unless the holder is already in its namespace, it must now pass."""
    import subprocess as sp

    def _self_map(pid, **_):
        Path(f"/proc/{pid}/uid_map").write_text(f"0 {os.getuid()} 1\n")
        Path(f"/proc/{pid}/setgroups").write_text("deny\n")
        Path(f"/proc/{pid}/gid_map").write_text(f"0 {os.getgid()} 1\n")
        return 1

    if sp.run(["unshare", "--user", "true"], capture_output=True).returncode:
        pytest.skip("unprivileged user namespaces unavailable")
    monkeypatch.setattr(seat_uid, "map_holder", _self_map)
    for _ in range(10):
        with seat_uid.mapped_namespace() as pid:
            assert Path(f"/proc/{pid}/uid_map").read_text().split()[:3] == ["0", str(os.getuid()), "1"]


# --------------------------------------------------------------------------------------
# Board round 1 (codex) regressions.
# --------------------------------------------------------------------------------------

def _tui_session_with_launch_refusal(monkeypatch, tmp_path):
    def _refuse(*a, **k):
        raise seat_jail.SeatSandboxRefused("seat_sandbox_refused:identity", "probe mismatch")

    monkeypatch.setattr(pi, "launch_provider", _refuse)
    fake_jail = types.SimpleNamespace(leg="claude")
    return pi._run_claude_tui_session(
        command=["/seat/bin/claude"], cwd=tmp_path, prompt="p", output_file=tmp_path / "o",
        timeout_s=5, env={}, seat_jail=fake_jail, probe_jail=fake_jail)


def test_codex_r1_a_jailed_launch_refusal_keeps_its_code(monkeypatch, tmp_path):
    rc, text, log, _tail = _tui_session_with_launch_refusal(monkeypatch, tmp_path)
    assert rc != 0 and text == ""
    assert pi._finalize_leg_detail(log) == "seat_sandbox_refused:identity"


class _FakeSeat:
    def __init__(self, tmp_path):
        self.jail = types.SimpleNamespace(
            leg="claude", provider_argv0="/seat/bin/claude", env={"HOME": "/seat/home"},
            profile_id="seat_jail_v1", profile_digest="d" * 64, filter_digest="f" * 64,
            pass_fds=(), redacted_owner=lambda: ["bwrap"])
        self.probe_jail = self.jail
        self.holder_pid = 1
        self.token = b"SEAT-JAIL-SENTINEL-r1-transcript-token"
        self.review_dir = tmp_path / "review"
        self.seat_dir = tmp_path / "seat"
        self.notices = []


def test_codex_r1_no_parent_snapshot_ever_holds_the_token(monkeypatch, tmp_path):
    seat = _FakeSeat(tmp_path)
    leaked = b'{"type":"assistant","message":{"role":"assistant","content":"' + seat.token + b'"}}\n'
    monkeypatch.setattr(pi._seat_uid, "read_in_h", lambda *a, **k: leaked)
    monkeypatch.setattr(pi._seat_uid, "teardown_in_h", lambda *a, **k: [])
    monkeypatch.setattr(pi._seat_jail, "close_jail_fds", lambda jail: None)
    monkeypatch.setattr(pi, "_broker_claude_tui_command", lambda **k: ["/seat/bin/claude"])
    seen: dict[str, object] = {}

    def _session(**kwargs):
        kwargs["transcript_refresh"]()
        snapshot = kwargs["broker_transcript_path"]
        seen["snapshot"] = snapshot.read_bytes()
        seen["mode"] = snapshot.stat().st_mode & 0o777
        seen["review_monitor"] = kwargs.get("review_monitor")
        return 0, "a review", "claude_tui_file_output", ""

    monkeypatch.setattr(pi, "_run_claude_tui_session", _session)
    import threading

    monitor = types.SimpleNamespace(cancel=threading.Event())
    sink: list = []
    status, _text = pi._exec_jailed_claude_leg(
        seat, timeout_s=5, backstop_s=5, model=None, effort=None, prompt="p",
        broker_evidence={}, failure_detail_sink=sink, review_monitor=monitor)
    assert seat.token not in seen["snapshot"], "the token reached a parent-owned snapshot"
    assert seen["mode"] == 0o600
    assert status == "DEGRADED" and sink[-1].template == "claude_seat_token_in_output"
    # ...and the heartbeat monitor reaches the jailed session (codex r1, finding 6).
    assert seen["review_monitor"] is monitor


def test_codex_r1_panel_invoker_imports_without_posix_open_flags():
    import subprocess as sp

    code = (
        "import os\n"
        "for name in ('O_NOFOLLOW', 'O_DIRECTORY', 'O_NONBLOCK', 'O_CLOEXEC', 'O_PATH'):\n"
        "    if hasattr(os, name): delattr(os, name)\n"
        "import phase_loop_runtime.panel_invoker\n"
        "print('imported')\n"
    )
    env = {**os.environ, "PYTHONPATH": str(Path(pi.__file__).resolve().parent.parent)}
    done = sp.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert done.stdout.strip() == "imported", done.stderr[-800:]
