"""CODEX SL-3.7: registration, OD-4 inputs and doctor/launch agreement."""
from dataclasses import replace
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from phase_loop_runtime import panel_invoker as pi, seat_admission, seat_codex_credential as cred
from phase_loop_runtime import seat_egress_proxy, seat_jail, seat_profiles, seat_route, seat_subject
from phase_loop_runtime.seat_route_contract import NamedException
from test_seat_route import Capacity, Native, Remote, policy, request
from test_seat_codex_credential import NOW, _claims, _login
from test_seat_codex_cli_shape import EXEC_HELP_0_167_0, FEATURES_0_167_0


def test_registration_includes_executable_and_admission_gate():
    from phase_loop_runtime.seat_profile_codex import codex_admission_gate
    profile = seat_profiles.profile_for("codex")
    assert profile is not None and profile.vendor == "codex"
    assert seat_subject._PROVIDER_EXECUTABLES["codex"] == "codex"
    assert codex_admission_gate in seat_admission._GATES["codex"]


def test_registered_evidence_resolves_to_committed_records():
    root = Path(__file__).resolve().parents[2]
    if not (root / "plans/phase-plan-v1-seats-CODEX.md").is_file():
        pytest.skip("repository-only decision and evidence; absent from installed wheel")
    profile = seat_profiles.profile_for("codex")
    records = {}
    for name in ("credential-scope", "refresh-detection", "allowlist-probes"):
        relative = f"plans/evidence/seat-codex/{name}.json"
        raw = subprocess.check_output(["git", "-C", str(root), "show", f"HEAD:{relative}"])
        assert raw == (root / relative).read_bytes()
        record = json.loads(raw)
        records[record["evidence_id"]] = record
    assert profile.credential.scope_evidence in records
    for value in vars(profile.containment).values():
        assert value is None or value in records
    assert profile.containment.deferred_to is None
    assert seat_egress_proxy.allowlist_ref("codex").request_set
    decision = (root / "plans/decision-seats-codex-boundary.md").read_text()
    assert "OD-4 accepted" in decision and "2026-11-08" in decision
    for name, digest in (
        ("provider-free", "2d3ec21ed625e2a766547d59c0471ee8b727be67484e0fdc83cb440b6e07c83e"),
        ("refresh-detection", "b59d933d12445c2a97a048b4714c43bb1d5349e2d306301022131fb84218dfa6"),
    ):
        assert hashlib.sha256((root / f"plans/evidence/seat-codex/{name}.json").read_bytes()).hexdigest() == digest
        assert digest in decision


@pytest.fixture
def ready_codex(tmp_path, monkeypatch):
    from phase_loop_runtime import sandbox_egress, seat_jail_autoqualify
    from phase_loop_runtime import seat_profile_codex
    home = tmp_path / "operator"
    auth = home / ".codex/auth.json"
    auth.parent.mkdir(parents=True)
    auth.write_text(json.dumps(_login()))
    auth.chmod(0o600)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setattr(cred, "auth_path", lambda env=None: auth)
    monkeypatch.setattr(seat_profile_codex.time, "time", lambda: NOW)
    profile = replace(seat_profiles.profile_for("codex"), preconditions=seat_profile_codex.CODEX_PROFILE.preconditions)
    monkeypatch.setitem(seat_profiles._REGISTRY, "codex", profile)
    monkeypatch.setattr(seat_jail, "seat_sandbox_capable", lambda: None)
    monkeypatch.setattr(sandbox_egress, "egress_required", lambda: True)
    monkeypatch.setattr(seat_egress_proxy, "unavailable_code", lambda: None)
    monkeypatch.setattr(seat_route, "_projection_for_launch", lambda *_: None)
    monkeypatch.setattr(seat_jail_autoqualify, "ensure_qualified", lambda *a, **k:
                        seat_jail_autoqualify.Outcome(seat_jail_autoqualify.QUALIFIED))
    subject = seat_subject.SeatSubject("codex", "standalone", Path("/synthetic/codex"), None, None)
    monkeypatch.setattr(seat_subject, "resolve_seat_subject", lambda *_: subject)
    monkeypatch.setattr(pi, "_resolved_jail_subject", lambda *_: (subject, None))
    monkeypatch.setattr(pi, "run_provider", lambda cmd, **k: SimpleNamespace(
        returncode=0, stdout=EXEC_HELP_0_167_0 if "--help" in cmd else FEATURES_0_167_0))
    return auth


def test_mode_line_and_launch_use_jailed_even_with_unconfined_exception(ready_codex, monkeypatch):
    exception = NamedException("codex", "unconfined", dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1), "fixture")
    monkeypatch.setattr(seat_route, "load_route_policy", lambda: policy(exceptions={"codex": exception}))
    capacity = Capacity()
    monkeypatch.setattr(pi._seat_uid, "SeatIdCapacity", lambda: capacity)
    pi._JAILCORE_ROUTE_CACHE.clear()
    auth = SimpleNamespace(staged_tree_sha256="a" * 64)
    board = SimpleNamespace(seats=[SimpleNamespace(harness="codex", seat_key="codex:a", model="m")])
    (mode,) = pi._seat_launch_modes(board, mode="review", review_authorization=auth, base_env={})
    route, notices, refusal = pi._seat_route_for_spawn("codex", auth, eligible=True, seat_key="codex:a", env={})
    try:
        assert (mode.mode, mode.code) == ("jailed", None)
        assert route.jailed and route.decision.exception is None
        assert notices == [] and refusal is None and capacity.calls == 1
    finally:
        pi._release_seat_route(route)
        pi._JAILCORE_ROUTE_CACHE.clear()


@pytest.mark.parametrize("code", ["seat_sandbox_unavailable_host", "seat_sandbox_unavailable_tiocsti", "seat_sandbox_unavailable_seat_uid"])
def test_l3_failure_walks_remote_native_degraded_without_unconfined(ready_codex, monkeypatch, code):
    monkeypatch.setattr(seat_jail, "seat_sandbox_capable", lambda: code)
    exception = NamedException("codex", "unconfined", dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1), "fixture")
    remote, native, capacity = Remote(), Native(), Capacity()
    decision = seat_route.resolve(request("codex"), policy=policy(exceptions={"codex": exception}),
                                  remote=remote, native=native, capacity=capacity)
    assert decision.mode == "degraded" and decision.code == code
    assert [s.rung for s in decision.steps] == ["local", "remote", "native_fill", "degraded"]
    assert len(remote.calls) == len(native.calls) == 1 and capacity.calls == 0
    assert decision.exception is None


AGREEMENT_ROWS = (
    ("missing", "codex_seat_credential_missing", "L5"),
    ("api_key", "codex_seat_api_key_refused", "L6"),
    ("expiring", "codex_seat_token_expiring", "L6"),
    ("scope", "codex_seat_token_scope_excess", "L6"),
    ("unsafe", "seat_sandbox_refused:token_file_unsafe", "L6"),
    ("shape", "codex_seat_cli_shape", "gate"),
)


@pytest.mark.parametrize("state,code,step", AGREEMENT_ROWS)
def test_doctor_and_launch_agree_on_each_codex_prelaunch_refusal(ready_codex, monkeypatch, state, code, step):
    if state == "missing":
        ready_codex.unlink()
    elif state == "unsafe":
        ready_codex.chmod(0o644)
    elif state != "shape":
        doc = _login()
        if state == "api_key":
            doc["OPENAI_API_KEY"] = "synthetic-api-key"
        elif state == "expiring":
            doc = _login(claims=_claims(exp=int(NOW) + 1))
        else:
            doc = _login(claims=_claims(scp=["unrecorded-fixture-scope"]))
        ready_codex.write_text(json.dumps(doc))
    else:
        monkeypatch.setattr(pi, "run_provider", lambda *a, **k: SimpleNamespace(returncode=0, stdout=""))
    doctor = seat_admission.verdict("codex", {}, execute=True)
    assert doctor.status == "refuses" and doctor.code == code
    # Enter actual preparation: the gate must refuse before creating the seat home.
    monkeypatch.setattr(pi, "_approved_stage_or_refuse", lambda *a: ready_codex.parent)
    monkeypatch.setattr(pi, "_validate_jail_dependency", lambda *a: None)
    from phase_loop_runtime import seat_codex_runtime
    monkeypatch.setattr(seat_codex_runtime, "subject_runtime", lambda *a: object())
    seat_dir = ready_codex.parents[1] / "refused-seat"
    with pytest.raises(seat_jail.SeatSandboxRefused) as refused:
        pi._prepare_jailed_codex(ready_codex.parent, seat_dir, object(), 1, 1,
                                ("bundle", "instructions"), object(), env={})
    assert refused.value.code == code and not seat_dir.exists()
    if step != "gate":
        decision = seat_route.resolve(request("codex"), policy=policy(), remote=Remote(), native=Native(), capacity=Capacity())
        assert decision.code == code and decision.steps[-1].step == step


def test_no_retained_capability_can_be_requested():
    from phase_loop_runtime import sandbox_egress
    assert sandbox_egress.SEAT_RETAINABLE_CAPS == frozenset()
    assert not hasattr(pi, "_BROKER_CODEX_SANDBOX_RETAINED_CAPS")
    with pytest.raises(ValueError, match="not retainable"):
        pi._seat_identity_switch(("setfcap",))


@pytest.mark.parametrize("module", ["seat_profiles", "seat_jail", "seat_profile_codex", "seat_codex_credential", "seat_codex_runtime"])
def test_registration_has_no_import_order_dependency(module):
    subprocess.run([sys.executable, "-c", f"import phase_loop_runtime.{module}; from phase_loop_runtime.seat_profiles import profile_for; assert profile_for('codex') is not None"],
                   check=True, timeout=15, capture_output=True)
