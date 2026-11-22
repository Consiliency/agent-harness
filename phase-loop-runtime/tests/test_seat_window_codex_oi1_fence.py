"""K-1 OI-1: the refuse-all fence on the Codex expired leg (owner decision 2026-11-22,
"Block all its traffic"; plan ``detailed-k1-oi1-refuse-all-fence-20261122-0736.md``).

Branch B (president ruling on agent-harness#2080): the fence is one declaration in Codex's
own supplier, ``seat_window_supply_codex.EXPIRED_LEG_PROXY``, which both the kit's proxy
start (``panel_invoker._open_window_launch``) and Codex's own reducer read.
``seat_jail_qualification.py`` is never edited.

Every test is provider-free: launches are stubbed at the spawn boundary, and the one real
proxy runs against a loopback fixture upstream.
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
from pathlib import Path

import pytest

from test_seat_window_supply_codex import (  # noqa: F401 - the shared K-1 harness
    CREDENTIAL_KINDS, HOLD_CODE, K1_CONTRACT_SHA256, NONE_KINDS, TOKEN_HOST, _ACCOUNT_CHECK,
    _COMPLETED, _FIELDS, _FAILED, _MODEL, _NAMED_DENIAL, _OTHER_DENY, _allowlist_digests,
    _binding, _context, _control_world, _observation, _reasons, _stream, codex_supplier,
)
from test_seat_window_vendor_neutral import (  # noqa: F401
    _codex_open_stubs, _codex_spec, _row_world, _watch_stub, fixture_vendor,
)
from test_seat_egress_allowlist_codex import (  # noqa: F401 - the real-proxy fixture
    _exchange, _http, codex_front,
)

FENCE = "refuse_all"
REPO = Path(__file__).resolve().parents[2]
FROZEN_REDUCER = "phase-loop-runtime/src/phase_loop_runtime/seat_jail_qualification.py"


def _with_expired(context, digest):
    return dataclasses.replace(context, expired_copy=dataclasses.replace(
        context.expired_copy, binding=_binding("expired_copy", allowlist=digest)))


# --------------------------------------------------------------------------------------
# T1(a): the hold is released by the declaration, and re-armed without it.
# --------------------------------------------------------------------------------------

def test_t1a_codex_declares_the_refuse_all_fence(codex_supplier):
    assert codex_supplier.EXPIRED_LEG_PROXY == FENCE
    assert codex_supplier.ROW_WINDOW_HOLD is None


def _guard_real_launch(monkeypatch):
    from phase_loop_runtime import panel_invoker as panel

    def never(*args, **kwargs):
        pytest.fail("a stubbed row window reached a real jail, proxy or provider")
    for target, name in ((panel, "_prepare_jailed_codex"), (panel, "_run_leg_with_liveness"),
                         (panel._seat_egress_proxy, "start_proxy"),
                         (panel._sandbox_egress, "isolated_network")):
        monkeypatch.setattr(target, name, never)


def test_t1a_a_fenced_codex_row_qualify_passes_the_hold_and_launches_only_stubs(
        codex_supplier, tmp_path, monkeypatch, capsys):
    from phase_loop_runtime import cli, seat_window as w
    assert w._row_ready_codes("codex")[0] is None
    _row_world(tmp_path, monkeypatch, "codex")
    stubbed = codex_supplier.reduce_containment

    def reduce_containment(inputs):  # the shared harness binds its fixture contract
        reduction = stubbed(inputs)
        return dataclasses.replace(reduction, binding={
            **reduction.binding, "contract_sha256": K1_CONTRACT_SHA256})
    monkeypatch.setattr(codex_supplier, "reduce_containment", reduce_containment)
    _guard_real_launch(monkeypatch)
    capsys.readouterr()
    code = cli.main(["--repo", str(tmp_path), "seat-window", "qualify", "--window", "row",
                     "--vendor", "codex", "--attended"])
    out = json.loads(capsys.readouterr().out)
    assert out["code"] != HOLD_CODE
    assert code == 0 and out["code"] == "window_review_required", out


@pytest.mark.parametrize("value", ["drop", None])
def test_t1a_m4_without_the_declaration_the_hold_re_arms_and_launches_nothing(
        codex_supplier, tmp_path, monkeypatch, value):
    from phase_loop_runtime import panel_invoker as panel, seat_window as w
    if value == "drop":
        monkeypatch.delattr(codex_supplier, "EXPIRED_LEG_PROXY", raising=False)
    else:
        monkeypatch.setattr(codex_supplier, "EXPIRED_LEG_PROXY", value, raising=False)

    def never(*args, **kwargs):
        pytest.fail("the hold let a Codex row window start")
    for target, name in ((w, "claim_window_attempt"), (w, "preflight"),
                         (w, "run_native_window"), (panel, "_open_window_launch"),
                         (panel._seat_egress_proxy, "start_proxy")):
        monkeypatch.setattr(target, name, never)
    assert codex_supplier.ROW_WINDOW_HOLD == HOLD_CODE
    assert w.qualify(window="row", monitoring_policy="bounded", repo=tmp_path,
                     attended=True, vendor="codex") == {"status": "candidate",
                                                         "code": HOLD_CODE}


def test_t1a_an_unknown_declaration_keeps_the_hold(codex_supplier, monkeypatch):
    monkeypatch.setattr(codex_supplier, "EXPIRED_LEG_PROXY", "allow_all")
    assert codex_supplier.ROW_WINDOW_HOLD == HOLD_CODE


# --------------------------------------------------------------------------------------
# T1(b): the kit's proxy start selects refuse-all for the expired leg only.
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("kind,refuse_all", [
    ("tree_control", True), ("runtime_control", True),
    ("credentialed_tree_control", False), ("credentialed_runtime_control", False),
    ("measured", False), ("expired_copy", True)])
def test_t1b_the_expired_leg_alone_of_the_credentialed_kinds_runs_refuse_all(
        codex_supplier, tmp_path, monkeypatch, kind, refuse_all):
    from phase_loop_runtime import panel_invoker as panel
    seen = _control_world(monkeypatch, tmp_path, codex_supplier, stdout=_FAILED)
    panel.window_control_launch(_codex_spec(kind, tmp_path))
    # The production allowlist id and named set are unchanged; only the mode differs.
    assert seen["proxies"] == [("codex", refuse_all)]
    named = panel._window_named_refusals("codex")
    assert seen["named"] == [named] and ("CONNECT", TOKEN_HOST, None) in named


# --------------------------------------------------------------------------------------
# T1(c): the real proxy in refuse-all mode with the production named set.
# --------------------------------------------------------------------------------------

def test_t1c_the_real_refuse_all_proxy_names_the_refresh_denial_and_dials_nothing(
        codex_supplier, codex_front):
    from phase_loop_runtime import panel_invoker as panel, seat_egress_proxy
    upstream = codex_front()
    named = panel._window_named_refusals("codex")
    with seat_egress_proxy.start_proxy(allowlist_id="codex", refuse_all=True,
                                       named=named) as proxy:
        assert proxy.allowlist_sha256 == seat_egress_proxy._digest([])
        assert proxy.allowlist_sha256 == _allowlist_digests()["refuse_all"]
        start = seat_egress_proxy.fence(proxy, "start", "leg")
        statuses = [_exchange(proxy, host, _http("POST", host, path))[0]
                    for host, path in ((TOKEN_HOST, "/oauth/token"),
                                       ("chatgpt.com", "/backend-api/codex/responses"))]
        end = seat_egress_proxy.fence(proxy, "end", "leg")
    stream = seat_egress_proxy.proxy_stream(proxy)
    assert start.acknowledged and end.acknowledged
    assert all(status.startswith(b"HTTP/1.1 403") for status in statuses), statuses
    assert upstream.connections == 0 and upstream.requests == []
    assert stream.final and not stream.protocol_error and not stream.outside_events
    (leg,) = [window for window in stream.windows if window.label == "leg"]
    observed = [(e.method, e.host, e.path, e.decision) for e in leg.events]
    assert observed == [("CONNECT", TOKEN_HOST, None, "deny"),
                        ("CONNECT", "<other>", None, "deny")]
    # The landed terminal reads this real fenced stream as refused_intended (r5.2 / E2).
    for changes in ({"status": "FAILURE"}, {"status": "NONE", "timed_out": True,
                                            "error": "launch_failed"}):
        observation = _observation(stream=stream, **changes)
        assert codex_supplier.terminal(observation) == "refused_intended"


# --------------------------------------------------------------------------------------
# T1(d), T2: Codex's own reducer accepts sha256([]) for the fenced expired leg only.
# --------------------------------------------------------------------------------------

def test_t1d_m3_the_fenced_reducer_accepts_refuse_all_and_rejects_production(codex_supplier):
    digests = _allowlist_digests()
    assert digests["refuse_all"] != digests["production"]
    reduction = codex_supplier.reduce_containment(
        _with_expired(_context(codex_supplier), digests["refuse_all"]))
    assert reduction.admitted is True and all(reduction.checks.values()), \
        reduction.owner_summary.unavailable_reasons
    assert dict(reduction.containment)["refresh_detection"] == "pass"
    # The expired leg is out of the production set; the bound digests are unchanged.
    assert reduction.binding["production_allowlist_sha256"] == digests["production"]
    assert reduction.binding["refuse_all_allowlist_sha256"] == digests["refuse_all"]
    rejected = codex_supplier.reduce_containment(
        _with_expired(_context(codex_supplier), digests["production"]))
    assert not any(rejected.checks.values())
    assert all("binding_mismatch" in _reasons(rejected, name) for name in _FIELDS)


@pytest.mark.parametrize("value", ["drop", None])
def test_t2_without_the_declaration_the_reducer_requires_production(
        codex_supplier, monkeypatch, value):
    if value == "drop":
        monkeypatch.delattr(codex_supplier, "EXPIRED_LEG_PROXY", raising=False)
    else:
        monkeypatch.setattr(codex_supplier, "EXPIRED_LEG_PROXY", value, raising=False)
    digests = _allowlist_digests()
    fenced = codex_supplier.reduce_containment(
        _with_expired(_context(codex_supplier), digests["refuse_all"]))
    assert not any(fenced.checks.values())
    assert all("binding_mismatch" in _reasons(fenced, name) for name in _FIELDS)
    unfenced = codex_supplier.reduce_containment(
        _with_expired(_context(codex_supplier), digests["production"]))
    assert unfenced.admitted is True and all(unfenced.checks.values())


@pytest.mark.parametrize("kind", ["measured", "credentialed_tree_control",
                                  "credentialed_runtime_control"])
def test_t2_m2_with_the_declaration_refuse_all_elsewhere_is_still_a_mismatch(
        codex_supplier, kind):
    digest = _allowlist_digests()["refuse_all"]
    context = _context(codex_supplier)
    if kind == "measured":
        context = dataclasses.replace(context, measured=dataclasses.replace(
            context.measured, binding=_binding(kind, allowlist=digest)))
    else:
        context = dataclasses.replace(context, controls=tuple(
            dataclasses.replace(item, binding=_binding(kind, allowlist=digest))
            if item.kind == kind else item for item in context.controls))
    reduction = codex_supplier.reduce_containment(context)
    assert not any(reduction.checks.values())
    assert all("binding_mismatch" in _reasons(reduction, name) for name in _FIELDS)


def test_t2_the_fence_moves_only_the_expired_role(codex_supplier):
    assert codex_supplier._allowlist_role("expired_copy") == FENCE
    roles = {kind: codex_supplier._allowlist_role(kind)
             for kind in CREDENTIAL_KINDS | NONE_KINDS}
    assert roles == {**dict.fromkeys(NONE_KINDS, FENCE),
                     **dict.fromkeys(CREDENTIAL_KINDS - {"expired_copy"}, "production"),
                     "expired_copy": FENCE}


def test_t2_an_unknown_declaration_is_a_contract_bug_in_the_reducer(codex_supplier,
                                                                    monkeypatch):
    monkeypatch.setattr(codex_supplier, "EXPIRED_LEG_PROXY", "allow_all")
    with pytest.raises(ValueError, match="contract_bug"):
        codex_supplier.reduce_containment(_context(codex_supplier))


def test_t2_m5_a_fixture_vendor_without_the_declaration_keeps_production_rules(
        tmp_path, monkeypatch, fixture_vendor):
    from phase_loop_runtime import panel_invoker as panel
    assert not hasattr(fixture_vendor.module, "EXPIRED_LEG_PROXY")
    seen = _codex_open_stubs(monkeypatch, tmp_path)
    _watch_stub(fixture_vendor, monkeypatch)
    monkeypatch.setattr(panel, "_run_leg_with_liveness", lambda command, **k: (
        seen["spawned"].append(list(command)) or type("Done", (), {
            "returncode": 0, "stdout": "completed"})()))
    panel.window_control_launch(_codex_spec("expired_copy", tmp_path))
    assert seen["proxies"] == [("codex", False)]


def test_t2_an_unknown_declaration_is_a_contract_bug_at_the_proxy_start(
        tmp_path, monkeypatch, fixture_vendor):
    from phase_loop_runtime import panel_invoker as panel
    monkeypatch.setattr(fixture_vendor.module, "EXPIRED_LEG_PROXY", "allow_all",
                        raising=False)
    seen = _codex_open_stubs(monkeypatch, tmp_path)
    _watch_stub(fixture_vendor, monkeypatch)
    monkeypatch.setattr(panel, "_run_leg_with_liveness", lambda command, **k: pytest.fail(
        "an unknown fence declaration launched"))
    with pytest.raises(ValueError, match="contract_bug"):
        with panel._open_window_launch(_codex_spec("expired_copy", tmp_path)):
            pass
    assert seen["proxies"] == []


# --------------------------------------------------------------------------------------
# T3: the landed terminal reads a fenced expired stream by r5.2's stream rule (E2).
# --------------------------------------------------------------------------------------

_FENCED = (_NAMED_DENIAL, _OTHER_DENY, _OTHER_DENY)


@pytest.mark.parametrize("changes", [
    {"status": "FAILURE"},
    {"status": "NONE", "timed_out": True},
    {"status": "NONE", "timed_out": True, "error": "launch_failed"},
], ids=["failure", "own-deadline", "own-deadline-kit"])
def test_t3_a_fenced_expired_stream_is_refused_intended_whatever_the_exit(
        codex_supplier, changes):
    observation = _observation(stream=_stream(*_FENCED), **changes)
    assert codex_supplier.terminal(observation) == "refused_intended"


@pytest.mark.parametrize("changes", [
    {"stream": "incomplete"}, {"stream": "unacked"},
    {"status": "NONE", "exit_code": 137},                     # an outer timeout 900 / kill
    {"status": "NONE", "exit_code": -9},
    {"stream": "allowed"}, {"stream": "allowed_model"},
    {"error": "proxy_unavailable"}, {"error": "fence_unacknowledged"},
    {"error": "jail_unavailable"}, {"error": "watch_unavailable"},
    {"refresh": "codex_seat_token_refreshed_in_jail"},
], ids=lambda value: "-".join(f"{k}={v}" for k, v in value.items()))
def test_t3_a_fenced_expired_leg_is_never_refused_intended_on_a_hard_failure(
        codex_supplier, changes):
    changes = dict(changes)
    stream = changes.pop("stream", None)
    streams = {
        None: _stream(*_FENCED),
        "incomplete": _stream(*_FENCED, final=False),
        "unacked": _stream(*_FENCED, end_acked=False),
        "allowed": _stream(*_FENCED, _ACCOUNT_CHECK),
        "allowed_model": _stream(*_FENCED, _MODEL),
    }
    exit_code = changes.pop("exit_code", None)
    changes.setdefault("status", "FAILURE")
    observation = _observation(stream=streams[stream], **changes)
    if exit_code is not None:
        observation.exit_code = exit_code
    assert codex_supplier.terminal(observation) != "refused_intended"


# --------------------------------------------------------------------------------------
# T4: the frozen Gemini reducer file is unedited.
# --------------------------------------------------------------------------------------

def _base() -> str | None:
    for ref in ("origin/main", "main"):
        done = subprocess.run(["git", "-C", str(REPO), "merge-base", "HEAD", ref],
                              capture_output=True, text=True, check=False)
        if done.returncode == 0 and done.stdout.strip():
            return done.stdout.strip()
    return None


def test_t4_seat_jail_qualification_is_unedited():
    if not (REPO / ".git").exists():
        pytest.skip("not a source checkout")
    base = _base()
    if base is None:
        pytest.skip("no base ref to diff against")
    done = subprocess.run(["git", "-C", str(REPO), "diff", "--exit-code", base, "--",
                           FROZEN_REDUCER], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stdout
