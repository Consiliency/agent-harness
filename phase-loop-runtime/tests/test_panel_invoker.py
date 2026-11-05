"""model-routing-v1 P2 — panel-invoker (IF-0-P2-2). No live CLI calls."""
import unittest
from dataclasses import fields
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import pytest

from harden_tdd_guard import invoke_sanctioned_review_transport
from president_fakes import deferring_president
from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD
from phase_loop_runtime.panel_invoker import (
    LEG_STATUSES,
    PANEL_LEGS,
    PanelLegResult,
    PanelRequest,
    available_panel_legs,
    invoke_panel,
    invoke_panel_request,
    panel_leg_timeout_seconds,
)


@pytest.mark.parametrize("vendor", ["claude", "gemini", "codex", "grok"])
def test_seats_firstseat_exec_record_prelaunch(tmp_path, monkeypatch, vendor):
    from phase_loop_runtime import panel_invoker as pi
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(pi, "_leg_auth_ok", lambda *a: (False, "unavailable"))
    monkeypatch.setattr(pi, "_parent_auth_state", lambda *a: "healthy")
    result = pi._exec_leg(vendor, tmp_path, tmp_path, artifact="planted auth text")
    assert result[0] != 0
    records = list((tmp_path / "state").rglob("leg-*.json"))
    assert len(records) == 1
    record = json.loads(records[0].read_text())
    assert record["vendor"] == vendor
    assert record["exit_code"] is None
    assert record["outcome"] != "leg_auth_signed_out"
    assert "planted" not in records[0].read_text()
    assert records[0].stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("assurance", [None, (), (b"fixture-token-123456789",)])
def test_seats_firstseat_exec_record_closed_fields(tmp_path, assurance):
    from phase_loop_runtime import panel_invoker as pi
    from phase_loop_runtime import seat_jail
    secret = b"fixture-token-123456789"
    for form in seat_jail.secret_encodings(secret):
        record = pi.leg_exec_record("grok", 1,
            ["grok", "-p", form.decode(), "--cwd", "/some/private/path"],
            auth_state="healthy", model_turn=False, verdict=False, scan_secrets=assurance)
        encoded = json.dumps(record).encode()
        assert not seat_jail.contains_secret(encoded, secret)
        assert len(encoded) <= 4096
        assert b"/some/private/path" not in encoded
        assert record["outcome"] == "leg_execution_failed"


@pytest.mark.parametrize("turn,verdict,state,expected", [
    (False, False, "signed_out", "leg_auth_signed_out"),
    (None, False, "signed_out", "leg_execution_failed"),
    (False, False, "unavailable", "leg_auth_unavailable"),
    (True, True, "unavailable", "leg_execution_failed"),
    (None, None, "healthy", "leg_execution_failed"),
    (False, False, "healthy", "leg_execution_failed"),
    (True, False, "signed_out", "leg_execution_failed"),
    (False, True, "signed_out", "leg_execution_failed"),
])
def test_seats_firstseat_exec_record_auth_observations(turn, verdict, state, expected):
    from phase_loop_runtime import panel_invoker as pi
    assert pi.leg_exec_record("grok", 1, [], auth_state=state,
        model_turn=turn, verdict=verdict)["outcome"] == expected


def test_seats_firstseat_exec_record_nested_launch(tmp_path, monkeypatch):
    from phase_loop_runtime import panel_invoker as pi
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(pi, "_parent_auth_state", lambda *a: "healthy")
    @pi._retained_leg_exec
    def inner(leg):
        observation = pi._EXEC_OBSERVATION.get()
        observation.update(argv=["fixture", "--model", "private-value"],
                           model_turn=True, verdict=True)
        return 0, "AGREE", ""
    @pi._retained_leg_exec
    def outer(leg):
        return inner(leg)
    assert outer("codex") == (0, "AGREE", "")
    records = list((tmp_path / "state").rglob("leg-*.json"))
    assert len(records) == 1
    assert json.loads(records[0].read_text())["model_turn"] is True


@pytest.mark.parametrize("kind", ["wide", "symlink", "foreign", "checkout"])
def test_seats_firstseat_exec_record_storage(tmp_path, monkeypatch, kind):
    import os
    from phase_loop_runtime import president_adapter as pa
    root = tmp_path / "records"
    root.mkdir(mode=0o700)
    if kind == "wide":
        root.chmod(0o755)
    elif kind == "symlink":
        link = tmp_path / "link"
        link.symlink_to(root, target_is_directory=True)
        root = link
    elif kind == "foreign":
        real = os.fstat
        def fstat(fd):
            info = real(fd)
            return type("Info", (), {"st_uid": -1, "st_mode": info.st_mode})()
        monkeypatch.setattr(os, "fstat", fstat)
    else:
        (tmp_path / ".git").mkdir()
    with pytest.raises((ValueError, OSError)):
        pa.write_private_record("record.json", {"event": "start"}, root=root)


def test_seats_firstseat_exec_record_detector_error(monkeypatch):
    from phase_loop_runtime import panel_invoker as pi
    from detect_secrets.core import scan
    monkeypatch.setattr(scan, "scan_line", lambda *a: (_ for _ in ()).throw(RuntimeError()))
    assert pi._scan_exec_field(["--model"], ()) is None
    assert pi._scan_exec_field(["--model"], None) is None


def test_seats_firstseat_exec_record_exception_preserved(tmp_path, monkeypatch):
    from phase_loop_runtime import panel_invoker as pi
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    @pi._retained_leg_exec
    def transport(leg):
        raise RuntimeError("fixture")
    with pytest.raises(RuntimeError, match="fixture"):
        transport("grok")
    assert len(list((tmp_path / "state").rglob("leg-*.json"))) == 1


def test_seats_firstseat_exec_record_broker_context(tmp_path, monkeypatch):
    import threading
    from phase_loop_runtime import panel_invoker as pi
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(pi, "_parent_auth_state", lambda *a: "healthy")
    @pi._retained_leg_exec
    def transport(leg):
        def observe():
            pi._EXEC_OBSERVATION.get().update(argv=["fixture", "--model"], scan_secrets=())
            pi._note_exec_signals(model_turn=True, verdict=True)
        worker = threading.Thread(target=pi._exec_in_context(observe))
        worker.start()
        worker.join()
        return "OK", "AGREE"
    result = transport("gemini")
    record = json.loads(next((tmp_path / "state").rglob("leg-*.json")).read_text())
    assert record["model_turn"] is True and record["verdict"] is True
    assert record["argv_flags"] == ["--model"]
    assert len(result.leg_exec_metadata["record_digest"]) == 64


def test_seats_firstseat_exec_record_scan_before_bound():
    from phase_loop_runtime import panel_invoker as pi, seat_jail
    secret = b"fixture-token-123456789"
    for form in seat_jail.secret_encodings(secret):
        value = "x" * 4090 + form.decode() + "x" * 8000
        assert pi._scan_exec_field(value, (secret,)) is None


def test_seats_firstseat_exec_record_typed_return(tmp_path, monkeypatch):
    from phase_loop_runtime import panel_invoker as pi
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    @pi._retained_leg_exec
    def transport(leg):
        pi._EXEC_OBSERVATION.get().update(auth_state="healthy", model_turn=False, verdict=False)
        return pi._BrokeredSpawnResult("DEGRADED", "", pi._LegFailure(template="auth_failure"))
    result = transport("grok")
    assert result[2] == "leg_execution_failed"
    assert "unknown failure" not in pi._finalize_leg_detail(result[2])


def test_seats_firstseat_exec_record_parent_probes(tmp_path, monkeypatch):
    import subprocess
    from phase_loop_runtime import panel_invoker as pi
    calls = []
    def runner(command, **kw):
        calls.append((command, kw))
        if command[0] == "claude":
            return subprocess.CompletedProcess(command, 1, '{"loggedIn":false}', "")
        return subprocess.CompletedProcess(command, 1, "", "Not logged in")
    monkeypatch.setattr(pi, "run_provider", runner)
    assert pi._parent_auth_state("claude") == "signed_out"
    assert pi._parent_auth_state("codex") == "signed_out"
    assert pi._parent_auth_state("gemini") == "unavailable"
    assert pi._parent_auth_state("grok") == "unavailable"
    assert all(Path(kw["cwd"]) != tmp_path and kw["stdin"] == subprocess.DEVNULL
               and kw["executor"] is True for _, kw in calls)


@pytest.mark.parametrize("route,exit_code", [("print", 41), ("tui", 42)])
def test_seats_firstseat_exec_record_claude_adapters(tmp_path, monkeypatch, route, exit_code):
    from phase_loop_runtime import panel_invoker as pi
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("PHASE_LOOP_PANEL_CLAUDE_ROUTE", route)
    monkeypatch.setattr(pi, "_under_claude_code", lambda *a: False)
    monkeypatch.setattr(pi, "_claude_code_support_status", lambda **k: (True, "supported"))
    monkeypatch.setattr(pi, "_claude_subscription_auth_ok", lambda *a: (True, ""))
    monkeypatch.setattr(pi, "_run_claude_print_session", lambda *a, **k: (exit_code, "", "", ""))
    monkeypatch.setattr(pi, "_run_claude_tui_session", lambda **k: (exit_code, "", "claude_tui_pty_eof_no_output", ""))
    review, out = tmp_path / "review", tmp_path / "out"
    review.mkdir()
    out.mkdir()
    (review / "review-bundle.md").write_text("fixture")
    (review / "review-instructions.md").write_text("fixture")
    @pi._retained_leg_exec
    def run(leg):
        return pi._exec_claude_tui_leg(review, out, 60, "fixture", env={})
    assert run("claude")[0] != "OK"
    record = json.loads(next((tmp_path / "state").rglob("leg-*.json")).read_text())
    assert record["exit_code"] == exit_code
    assert record["auth_state"] == "unavailable"


@pytest.mark.parametrize("vendor,exit_code", [("gemini", 43), ("claude", 44)])
def test_seats_firstseat_exec_record_jailed_adapters(tmp_path, monkeypatch, vendor, exit_code):
    from types import SimpleNamespace
    from phase_loop_runtime import panel_invoker as pi
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(pi, "_cleanup_jailed_seat", lambda *a, **k: None)
    monkeypatch.setattr(pi._seat_uid, "read_in_h", lambda *a, **k: b"")
    monkeypatch.setattr(pi, "_parent_auth_state", lambda *a: "healthy")
    jail = SimpleNamespace(env={}, leg=vendor, provider_argv0="/seat/bin/" + vendor,
        profile_digest="d", profile_id="p", filter_digest="f",
        redacted_owner=lambda: [], pass_fds=())
    seat = pi._JailedSeat(jail=jail, probe_jail=jail, holder_pid=1, token=b"fixture-token",
        review_dir=tmp_path, seat_dir=tmp_path, expires_at=None)
    monkeypatch.setattr(pi, "_run_leg_with_liveness", lambda *a, **k:
        SimpleNamespace(returncode=exit_code, stdout="", stderr=""))
    monkeypatch.setattr(pi, "_run_claude_tui_session", lambda **k:
        (exit_code, "not logged in; please run claude login", "", ""))
    @pi._retained_leg_exec
    def run(leg):
        if leg == "gemini":
            return pi._exec_jailed_gemini_leg(seat, deadline_s=60, model="m", prompt="fixture", broker_evidence=None)
        return pi._exec_jailed_claude_leg(seat, timeout_s=60, backstop_s=60,
            model=None, effort=None, prompt="fixture", broker_evidence=None, failure_detail_sink=[])
    assert run(vendor)[0] != "OK"
    assert not seat.notices
    record = json.loads(next((tmp_path / "state").rglob("leg-*.json")).read_text())
    assert record["exit_code"] == exit_code
    assert record["outcome"] == "leg_execution_failed"


def test_seats_firstseat_exec_record_dependency_probe(monkeypatch):
    from phase_loop_runtime import panel_invoker as pi
    from phase_loop_runtime.executable_dependency_startup import ExecutableDependencyError
    def unavailable(*a, **kw):
        raise ExecutableDependencyError("dependency_route_unwired")
    monkeypatch.setattr(pi, "run_provider", unavailable)
    assert pi._parent_auth_state("claude") == "unavailable"
    assert pi._parent_auth_state("codex") == "unavailable"


@pytest.mark.parametrize("missing", [None, "claude", "gemini", "grok", "codex", "all"])
def test_seats_firstseat_exec_record_composed_board(tmp_path, missing):
    from phase_loop_runtime import panel_invoker as pi
    from phase_loop_runtime.advisor_board.composition import compose_review_board_report
    composition = compose_review_board_report(is_available=lambda v: missing != "all" and v != missing,
                                               auth_ok=lambda v: True)
    outcome = composition.policy_outcome("plan")
    launched = []
    def spawn(leg, artifact, **kw):
        launched.append(leg)
        return "OK", "AGREE"
    if missing is not None:
        assert outcome.status == "policy_refused" and outcome.fix
        with pytest.raises(pi.PresidentPolicyError):
            invoke_sanctioned_review_transport(composition.board, "fixture", spawn=spawn,
                landing_tier="plan", president_invoke=deferring_president)
        assert not launched
    else:
        assert outcome.status == "admitted"
        result = invoke_sanctioned_review_transport(composition.board, "fixture", spawn=spawn,
            landing_tier="plan", president_invoke=deferring_president, max_concurrency=1)
        assert set(launched) == {"claude", "gemini", "codex", "grok"}
        assert result.legs


@pytest.mark.parametrize("failure", [False, True])
def test_seats_firstseat_exec_record_board_returns(tmp_path, monkeypatch, failure):
    from phase_loop_runtime.advisor_board import composition
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    composed = composition.compose_review_board_report(is_available=lambda v: True, auth_ok=lambda v: True)
    def spawn(leg, artifact, **kw):
        if failure:
            raise ValueError("fixture text omitted from records")
        return "OK", "AGREE"
    result = invoke_sanctioned_review_transport(composed.board, "fixture", spawn=spawn,
        landing_tier="plan", president_invoke=deferring_president, max_concurrency=1)
    records = list((tmp_path / "state").rglob("leg-*.json"))
    assert len(records) == len(result.legs) == 4
    assert all(leg.status == ("DEGRADED" if failure else "OK") for leg in result.legs)
    for leg in result.legs:
        assert getattr(leg, "_leg_exec_metadata", {}).get("record_digest")
    assert all("fixture" not in path.read_text() for path in records)


def test_seats_firstseat_exec_record_provider_metadata(tmp_path, monkeypatch):
    from phase_loop_runtime import panel_invoker as pi
    spawned = pi._BrokeredSpawnResult("OK", "AGREE")
    spawned.leg_exec_metadata = {"record_digest": "a" * 64, "outcome": "leg_execution_completed"}
    monkeypatch.setattr(pi, "_default_spawn", lambda *a, **kw: spawned)
    result = pi._default_spawn_via_provider("gemini", "fixture", repo_dir=tmp_path)
    assert result.leg_exec_metadata == spawned.leg_exec_metadata
    leg = pi.PanelLegResult("gemini", "OK", "AGREE")
    object.__setattr__(leg, "_leg_exec_metadata", result.leg_exec_metadata)
    assert pi._retain_panel_leg(leg) is leg


def test_seats_firstseat_exec_record_board_storage(monkeypatch):
    from phase_loop_runtime import panel_invoker as pi, president_adapter as pa
    def fail(*args):
        raise OSError("fixture")
    monkeypatch.setattr(pa, "write_private_record", fail)
    result = pi._retain_panel_leg(pi.PanelLegResult("gemini", "OK", "AGREE"))
    assert result.status == "DEGRADED" and not result.text
    assert result.detail == "leg_exec_record_unavailable"




class PanelInvokerTest(unittest.TestCase):
    def test_available_legs_uses_injected_probe(self):
        # only codex + claude "installed"
        present = {"codex", "claude"}
        legs = available_panel_legs(probe=lambda cli: cli in present)
        self.assertEqual(set(legs), {"codex", "claude"})

    def test_available_panel_legs_includes_grok_when_present(self):
        # ah#171: grok is exposed (ordered last) when its CLI is installed, so a caller
        # whose gemini/agy leg is down reaches a 4th independent vendor without a
        # hand-rolled grok CLI.
        legs = available_panel_legs(probe=lambda cli: True)
        self.assertEqual(legs, ("codex", "gemini", "claude", "grok"))

    def test_available_panel_legs_grok_is_availability_aware(self):
        # grok absent -> not returned (a host without the grok CLI still gets the frozen
        # 3-tuple), and the byte-frozen PANEL_LEGS keystone is never mutated.
        legs = available_panel_legs(probe=lambda cli: cli != "grok")
        self.assertNotIn("grok", legs)
        self.assertEqual(legs, ("codex", "gemini", "claude"))
        self.assertEqual(PANEL_LEGS, ("codex", "gemini", "claude"))

    def test_invoke_flags_per_leg_status(self):
        def spawn(leg, artifact):
            if leg == "codex":
                return ("ok", "AGREE. looks fine")
            if leg == "gemini":
                return ("timeout", "")
            raise RuntimeError("claude leg crashed")

        result = invoke_panel("ARTIFACT", ["codex", "gemini", "claude"], spawn=spawn)
        by_leg = {leg.leg: leg for leg in result.legs}
        self.assertEqual(by_leg["codex"].status, "OK")
        self.assertTrue(by_leg["codex"].usable)
        self.assertEqual(by_leg["gemini"].status, "TIMEOUT")
        self.assertFalse(by_leg["gemini"].usable)
        # a crashing leg is fail-closed to degraded, never raised
        self.assertEqual(by_leg["claude"].status, "DEGRADED")
        # agent-harness#1102 r7: an exception's own text is not our vocabulary; the leg's
        # detail names an unknown failure (its message goes only to the private log).
        self.assertTrue((by_leg["claude"].detail or "").startswith("unknown failure"))
        self.assertEqual(result.usable_legs, (by_leg["codex"],))

    def test_ok_with_empty_text_becomes_empty(self):
        result = invoke_panel("A", ["codex"], spawn=lambda leg, art: ("ok", "   "))
        self.assertEqual(result.legs[0].status, "EMPTY")
        self.assertFalse(result.legs[0].usable)

    def test_unknown_status_degrades(self):
        result = invoke_panel("A", ["codex"], spawn=lambda leg, art: ("weird", "x"))
        self.assertEqual(result.legs[0].status, "DEGRADED")

    def test_leg_status_validation(self):
        with self.assertRaises(ValueError):
            PanelLegResult(leg="codex", status="not_a_status")

    def test_leg_statuses_are_canonical_uppercase(self):
        self.assertEqual(LEG_STATUSES, ("OK", "EMPTY", "TIMEOUT", "ERROR", "DEGRADED", "UNAVAILABLE"))
        self.assertEqual(PanelLegResult(leg="codex", status="ok", text="AGREE").status, "OK")
        self.assertEqual(PanelLegResult(leg="codex", status="Ok", text="AGREE").status, "OK")

    def test_panel_request_uses_metadata_only_redaction_and_scaled_timeouts(self):
        request = PanelRequest(artifact="x" * 400_000)
        self.assertEqual(request.redaction_posture, "metadata_only")
        self.assertGreater(request.timeout_seconds_for_leg("codex"), panel_leg_timeout_seconds("codex", "small"))
        self.assertLessEqual(request.timeout_seconds_for_leg("codex"), 1800)
        with self.assertRaises(ValueError):
            PanelRequest(artifact="bundle", redaction_posture="raw_payload")

    def test_panel_legs_are_three_vendors(self):
        self.assertEqual(PANEL_LEGS, ("codex", "gemini", "claude"))

    def test_artifact_ref_wins_over_inline_artifact_for_panel(self):
        seen = {}

        def spawn(leg, artifact):
            seen[leg] = artifact
            return ("ok", "AGREE")

        with TemporaryDirectory() as td:
            p = Path(td) / "bundle.md"
            p.write_text("FROM_ARTIFACT_REF", encoding="utf-8")
            invoke_panel("INLINE_SHOULD_NOT_APPEAR", ["codex"], artifact_ref=str(p), spawn=spawn)
        self.assertEqual(seen["codex"], "FROM_ARTIFACT_REF")

    def test_board_threads_artifact_ref_and_context_refs(self):
        seen = {}

        def spawn(leg, artifact):
            seen[leg] = artifact
            return ("ok", "AGREE")

        with TemporaryDirectory() as td:
            bundle = Path(td) / "bundle.md"
            bundle.write_text("FROM_BOARD_REF", encoding="utf-8")
            ref = Path(td) / "private.txt"
            ref.write_text("PRIVATE_BODY_ABSENT", encoding="utf-8")
            invoke_sanctioned_review_transport(
                DEFAULT_BOARD,
                "INLINE",
                artifact_ref=str(bundle),
                context_refs=[str(ref)],
                spawn=spawn,
                landing_tier="production_code",
                president_invoke=deferring_president,
            )
        self.assertIn("FROM_BOARD_REF", seen["codex"])
        self.assertNotIn("PRIVATE_BODY_ABSENT", seen["codex"])
        self.assertIn(str(ref.resolve()), seen["codex"])

    def test_board_threads_timeout_overrides_to_real_spawn_boundary(self):
        seen_timeouts = {}

        def spawn(leg, artifact, **kwargs):
            seen_timeouts[leg] = kwargs.get("timeout_s")
            return ("OK", "AGREE")

        with patch("phase_loop_runtime.panel_invoker._default_spawn_via_provider", side_effect=spawn):
            invoke_sanctioned_review_transport(
                DEFAULT_BOARD,
                "ARTIFACT",
                timeouts_by_leg={"gemini": 137},
                max_concurrency=1,
                landing_tier="production_code",
                president_invoke=deferring_president,
            )

        self.assertEqual(seen_timeouts["gemini"], 137)
        self.assertIsNone(seen_timeouts["codex"])
        self.assertIsNone(seen_timeouts["claude"])

    def test_panel_request_threads_artifact_ref_and_timeout_field_names(self):
        seen = {}

        def spawn(leg, artifact):
            seen[leg] = artifact
            return ("ok", "AGREE")

        with TemporaryDirectory() as td:
            p = Path(td) / "bundle.md"
            p.write_text("FROM_REQUEST_REF", encoding="utf-8")
            req = PanelRequest(
                artifact="INLINE",
                artifact_ref=str(p),
                legs=("codex",),
                timeout_seconds_by_leg={"codex": 123},
            )
            invoke_panel_request(req, spawn=spawn)
        self.assertEqual(seen["codex"], "FROM_REQUEST_REF")
        self.assertIn("timeout_seconds_by_leg", {field.name for field in fields(PanelRequest)})
        self.assertNotIn("timeouts_by_leg", {field.name for field in fields(PanelRequest)})

    def test_panel_request_deliberately_excludes_brief_ref(self):
        request_fields = {field.name for field in fields(PanelRequest)}
        self.assertNotIn("brief_ref", request_fields)


if __name__ == "__main__":
    unittest.main()
