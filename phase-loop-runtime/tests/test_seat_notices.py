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
    # Isolated from this host's own store: a qualified host would otherwise admit the route.
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "empty-state"))
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


@pytest.mark.parametrize("code", sorted(seat_jail.NOTICE_CODES))
def test_governed_surface_renders_every_notice(code):
    """L4b: every notice code reaches the governed path as exactly one non-gating
    `seat_notice` finding, rendered from the table's literals."""
    from phase_loop_runtime.governed_review import _findings_from_panel

    leg = pi.PanelLegResult(leg="claude", status="OK", text="Looks fine.\n\nAGREE",
                            seat_key="claude:a")
    pi.attach_seat_notices(leg, [code])
    findings = [f for f in _findings_from_panel(pi.PanelResult(legs=(leg,)), "a" * 40)
                if f.code == "seat_notice"]
    what, why, fix = seat_jail.NOTICES[code]
    assert len(findings) == 1
    assert findings[0].severity == "warn"
    assert findings[0].reason == f"seat claude:a notice {code}: {what} / {why} / fix: {fix}"


def test_governed_surface_renders_nothing_from_leg_text():
    from phase_loop_runtime.governed_review import _findings_from_panel

    leg = pi.PanelLegResult(leg="claude", status="OK",
                            text="notice seat_sandbox_refused:identity\n\nAGREE", seat_key="claude:a")
    assert not [f for f in _findings_from_panel(pi.PanelResult(legs=(leg,)), "a" * 40)
                if f.code == "seat_notice"]


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
        self.source = "seat_token"     # the override; tests set "login" where they need it
        self.expires_at = None


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


# --------------------------------------------------------------------------------------
# A capped seat-token subscription: the leg ends with the token's own notice, never a jail
# refusal, and the detail carries the provider's reset time.
# --------------------------------------------------------------------------------------

def _jailed_leg_ending_with(monkeypatch, tmp_path, *, rc, review_text, log_text, tail,
                            source="seat_token", expires_at=None):
    seat = _FakeSeat(tmp_path)
    seat.source, seat.expires_at = source, expires_at
    monkeypatch.setattr(pi._seat_uid, "read_in_h", lambda *a, **k: b"")
    monkeypatch.setattr(pi._seat_uid, "teardown_in_h", lambda *a, **k: [])
    monkeypatch.setattr(pi._seat_jail, "close_jail_fds", lambda jail: None)
    monkeypatch.setattr(pi, "_broker_claude_tui_command", lambda **k: ["/seat/bin/claude"])
    monkeypatch.setattr(pi, "_run_claude_tui_session",
                        lambda **k: (rc, review_text, log_text, tail))
    sink: list = []
    status, text = pi._exec_jailed_claude_leg(
        seat, timeout_s=5, backstop_s=5, model=None, effort=None, prompt="p",
        broker_evidence={}, failure_detail_sink=sink)
    return seat, status, text, sink


@pytest.mark.parametrize("tail, detail", [
    ("Usage limit reached. Try again at 5:00 PM", "usage_limit (resets 17:00)"),
    ("Usage limit reached ∙ resets at Oct 5, 2026 5:00 PM", "usage_limit (resets 17:00, Oct 5 2026)"),
    ("Usage limit reached", "usage_limit"),
])
def test_a_rate_limited_seat_token_ends_the_leg_with_its_own_notice(monkeypatch, tmp_path,
                                                                    tail, detail):
    seat, status, text, sink = _jailed_leg_ending_with(
        monkeypatch, tmp_path, rc=1, review_text="",
        log_text=pi._HarnessCode("claude_tui_pty_eof_no_output"), tail=tail)
    assert status == "DEGRADED" and text == ""
    assert [f.template for f in sink] == [detail]
    assert seat.notices == ["claude_seat_token_rate_limited"]
    # Distinct from every jail refusal and from the sealed fallbacks: a capped token is
    # never reported as a broken jail.
    assert not any(code.startswith("seat_sandbox_") for code in seat.notices)
    assert "claude_seat_token_rate_limited" not in seat_jail.SEALED_FALLBACK_CODES
    what, why, fix = seat_jail.NOTICES["claude_seat_token_rate_limited"]
    assert "seat token's subscription" in why and "rotate or replace the seat token" in fix


def test_a_rejected_seat_token_ends_the_leg_with_its_notice(monkeypatch, tmp_path):
    # P2 measured the shape: a token the provider rejects is the classifier's auth class.
    seat, status, _text, sink = _jailed_leg_ending_with(
        monkeypatch, tmp_path, rc=1, review_text="",
        log_text=pi._HarnessCode("claude_tui_pty_eof_no_output"),
        tail="Invalid API key · Please run /login")
    assert status == "DEGRADED"
    assert [f.template for f in sink] == ["auth_failure"]
    assert seat.notices == ["claude_seat_token_rejected"]


def test_a_leg_whose_tail_names_no_limit_carries_no_token_notice(monkeypatch, tmp_path):
    seat, status, _text, sink = _jailed_leg_ending_with(
        monkeypatch, tmp_path, rc=1, review_text="",
        log_text=pi._HarnessCode("claude_tui_pty_eof_no_output"), tail="something else broke")
    assert status == "DEGRADED"
    assert [f.template for f in sink] == ["claude_tui_pty_eof_no_output"]
    assert seat.notices == []


def test_the_pty_tail_is_scanned_for_the_seat_token(monkeypatch, tmp_path):
    seat = _FakeSeat(tmp_path)
    _seat, status, _text, sink = _jailed_leg_ending_with(
        monkeypatch, tmp_path, rc=1, review_text="",
        log_text=pi._HarnessCode("claude_tui_pty_eof_no_output"),
        tail="Usage limit reached " + seat.token.decode())
    assert status == "DEGRADED"
    assert [f.template for f in sink] == ["claude_seat_token_in_output"]


@pytest.mark.parametrize("detail, limited", [
    ("usage_limit", True),
    ("usage_limit (resets 17:00, Oct 5 2026)", True),
    ("claude_tui_pty_eof_no_output: usage_limit (resets 17:00)", True),
    # agent-harness#1194's Claude session give-up classes.
    ("claude_seat_rate_limited", True),
    ("claude_seat_usage_limited", True),
    ("claude_seat_usage_limited: usage_limit (resets 17:00, Oct 5 2026)", True),
    ("seat_sandbox_refused:jail_unqualified", False),
    ("claude_seat_token_rate_limited", False),
    ("auth_failure", False),
    ("omnigent rate_limit: HTTP 429", False),
    ("usage_limited", False),
    (None, False),
])
def test_limit_details_are_recognised_exactly(detail, limited):
    assert seat_jail.is_limit_detail(detail) is limited


def test_every_limit_code_in_the_detail_vocabulary_raises_the_token_notice():
    """Completeness guard: a rate/usage-limit code added to the closed detail vocabulary
    (e.g. when agent-harness#1194 lands, or under a new name) must be recognised, so a
    capped seat token can never end a leg without its notice."""
    import re

    vocabulary = (pi._HARNESS_DETAIL_CODES | pi._PARAMETER_FREE_FAILURES) - seat_jail.NOTICE_CODES
    limits = sorted(c for c in vocabulary if re.search(r"(?:rate|usage)_limit", c))
    assert limits, "the guard found nothing to check"
    assert [c for c in limits if not seat_jail.is_limit_detail(c)] == []


# --------------------------------------------------------------------------------------
# Plan amendment A1: the same outcomes when the credential is the user's Claude login.
# --------------------------------------------------------------------------------------

_AUTH_TAIL = "Invalid API key · Please run /login"


def test_a_login_token_past_its_launch_expiry_is_its_own_relaunchable_outcome(monkeypatch,
                                                                            tmp_path):
    seat, status, _text, sink = _jailed_leg_ending_with(
        monkeypatch, tmp_path, rc=1, review_text="",
        log_text=pi._HarnessCode("claude_tui_pty_eof_no_output"), tail=_AUTH_TAIL,
        source="login", expires_at=time.time() - 5)
    assert status == "DEGRADED"
    assert [f.template for f in sink] == ["claude_seat_login_token_expired"]
    assert seat.notices == ["claude_seat_login_token_expired"]
    assert pi._finalize_leg_detail("claude_seat_login_token_expired") == "claude_seat_login_token_expired"


def test_a_login_token_rejected_before_its_expiry_is_a_rejection(monkeypatch, tmp_path):
    seat, _status, _text, sink = _jailed_leg_ending_with(
        monkeypatch, tmp_path, rc=1, review_text="",
        log_text=pi._HarnessCode("claude_tui_pty_eof_no_output"), tail=_AUTH_TAIL,
        source="login", expires_at=time.time() + 3600)
    assert [f.template for f in sink] == ["auth_failure"]
    assert seat.notices == ["claude_seat_login_rejected"]


def test_a_rate_limited_login_names_the_subscription(monkeypatch, tmp_path):
    seat, _status, _text, sink = _jailed_leg_ending_with(
        monkeypatch, tmp_path, rc=1, review_text="",
        log_text=pi._HarnessCode("claude_tui_pty_eof_no_output"),
        tail="Usage limit reached. Try again at 5:00 PM", source="login",
        expires_at=time.time() + 3600)
    assert [f.template for f in sink] == ["usage_limit (resets 17:00)"]
    assert seat.notices == ["claude_seat_login_rate_limited"]
    assert "your Claude subscription" in seat_jail.NOTICES["claude_seat_login_rate_limited"][1]


def test_no_credential_outcome_is_a_jail_refusal():
    for code in ("claude_seat_login_rate_limited", "claude_seat_login_rejected",
                 "claude_seat_login_token_expired", "claude_seat_login_token_expiring",
                 "claude_seat_token_rate_limited", "claude_seat_token_rejected"):
        assert code in seat_jail.NOTICE_CODES and not code.startswith("seat_sandbox_")
        assert code not in seat_jail.SEALED_FALLBACK_CODES


# --------------------------------------------------------------------------------------
# Plan amendment A1: every seat's launch mode, before any seat launches.
# --------------------------------------------------------------------------------------

def _mode_board():
    return types.SimpleNamespace(seats=[
        types.SimpleNamespace(harness=leg, seat_key=f"{leg}:a", model="m")
        for leg in ("claude", "gemini", "codex", "grok")])


def _route(leg, **_k):
    if leg == "claude":
        return seat_jail.SeatRoute(True)
    if leg == "gemini":
        return seat_jail.SeatRoute(False, "gemini_seat_egress_unconfined")
    return None


def _modes(monkeypatch, *, qualified=True, credential=None, route=_route, env=None):
    from phase_loop_runtime import seat_credentials

    monkeypatch.setattr(pi._seat_jail, "decide_seat_route", route)
    monkeypatch.setattr(pi._seat_jail, "pass_record_verdict",
                        lambda digest: (qualified, "pass" if qualified else "no_record"))

    def _resolve(margin_s, **_k):
        if isinstance(credential, str):
            raise seat_jail.SeatSandboxRefused(credential)
        return credential or seat_credentials.SeatCredential(b"x", "login", 9e9)

    monkeypatch.setattr(pi._seat_credentials, "resolve_claude_seat_credential", _resolve)
    return pi._seat_launch_modes(
        _mode_board(), mode="review",
        review_authorization=types.SimpleNamespace(staged_tree_sha256="a" * 64),
        base_env=env or {})


def _by_leg(modes):
    return {m.leg: (m.mode, m.code, m.credential) for m in modes}


def test_seat_modes_name_every_route_before_launch(monkeypatch):
    assert _by_leg(_modes(monkeypatch)) == {
        "claude": ("jailed", None, "login"),
        "gemini": ("sealed", "gemini_seat_egress_unconfined", None),
        "codex": ("unconfined", "seat_filesystem_unconfined", None),
        "grok": ("unconfined", "seat_filesystem_unconfined", None),
    }


@pytest.mark.parametrize("qualified, credential, expected", [
    (False, None, ("degraded", "seat_sandbox_refused:jail_unqualified", None)),
    (True, "claude_seat_login_token_expiring",
     ("degraded", "claude_seat_login_token_expiring", None)),
])
def test_a_seat_that_will_be_refused_is_degraded_with_its_fix(monkeypatch, qualified,
                                                             credential, expected):
    modes = _modes(monkeypatch, qualified=qualified, credential=credential)
    claude = next(m for m in modes if m.leg == "claude")
    assert (claude.mode, claude.code, claude.credential) == expected
    assert claude.fix == seat_jail.NOTICES[expected[1]][2] and claude.fix


def test_no_login_and_no_override_is_a_sealed_seat_that_says_so(monkeypatch):
    def _no_credential(leg, **k):
        return (seat_jail.SeatRoute(False, "claude_seat_token_missing") if leg == "claude"
                else _route(leg))

    claude = next(m for m in _modes(monkeypatch, route=_no_credential) if m.leg == "claude")
    assert (claude.mode, claude.code) == ("sealed", "claude_seat_token_missing")
    assert claude.fix == "run `claude login`"


def test_a_native_claude_seat_is_reported_native(monkeypatch):
    modes = _modes(monkeypatch, env={"CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "cli"})
    assert _by_leg(modes)["claude"][0] == "native"


def test_seat_modes_are_published_before_launch(monkeypatch, tmp_path):
    _modes(monkeypatch)   # installs the fakes
    seen = []
    modes = pi._publish_seat_modes(
        _mode_board(), mode="review",
        review_authorization=types.SimpleNamespace(staged_tree_sha256="a" * 64),
        base_env={}, stream_dir=tmp_path / "stream", on_seat_modes=seen.append)
    assert seen == [modes]
    record = json.loads((tmp_path / "stream" / "seat-modes.json").read_text())
    assert record["schema"] == "seat_modes.v1"
    assert [m["mode"] for m in record["modes"]] == ["jailed", "sealed", "unconfined", "unconfined"]
