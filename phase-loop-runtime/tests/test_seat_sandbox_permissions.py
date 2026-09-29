"""Falsifiers for the jailed-seat route (agent-harness#1132): J6-J9, J13, J15, D8.

What runs here without the maintainer's root prerequisite: the J7 order (each step's one
code), the D8 argv (holder map, launch order, drop), the J9 goldens, the EC-EXECFIND-2
gate, the jailed Claude argv, and the unmapped-holder mechanics with a single-uid map the
operator may write itself. Everything that needs a subordinate uid is skip-guarded with
the literal prerequisite; it neither fails nor passes on a host without it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from phase_loop_runtime import panel_invoker, sandbox_egress, seat_jail, seat_uid

from ._seat_prereq import (
    EXECFIND_1071,
    require_seat_token,
    require_seat_uid,
)

GOLDEN = json.loads((Path(__file__).parent / "data" / "seat_jail_1132_sealed_golden.json")
                    .read_text(encoding="utf-8"))


# --------------------------------------------------------------------------------------
# J7: one code per step, in order.
# --------------------------------------------------------------------------------------

class _Counter:
    def __init__(self, value):
        self.value, self.calls = value, 0

    def __call__(self, *a, **k):
        self.calls += 1
        return self.value


def _decide(leg="claude", *, staged=True, capable=None, token=True, cred=True, qualified=False,
            stop=seat_jail.GEMINI_RECORDED_STOP):
    capable = capable if capable is not None else _Counter(None)
    return seat_jail.decide_seat_route(
        leg, staged_tree_approved=staged, capable=capable,
        claude_token_present=_Counter(token), gemini_credential_present=_Counter(cred),
        gemini_qualified=_Counter(qualified), gemini_recorded_stop=stop,
    )


def test_j7_step0_no_tree_wins_and_evaluates_nothing_else():
    capable = _Counter("seat_sandbox_unavailable_host")  # an INCAPABLE host
    token = _Counter(False)
    route = seat_jail.decide_seat_route("claude", staged_tree_approved=False, capable=capable,
                                        claude_token_present=token)
    assert route == seat_jail.SeatRoute(False, "seat_sandbox_not_staged")
    assert capable.calls == 0 and token.calls == 0


def test_j7_step1_recorded_gemini_stop_beats_qualification():
    route = _decide("gemini", qualified=False, stop="gemini_seat_stream_split_unavailable")
    assert route.code == "gemini_seat_stream_split_unavailable"


def test_j7_step1_gemini_stays_sealed_until_p4_and_p3_pass():
    """P4 has not run; the production default keeps Gemini sealed, never tooled."""
    route = seat_jail.decide_seat_route("gemini", staged_tree_approved=True)
    assert route == seat_jail.SeatRoute(False, "gemini_seat_credential_unusable")
    assert "gemini" not in seat_jail.JAILED_LEGS


@pytest.mark.parametrize("code", ["seat_sandbox_unavailable_host",
                                  "seat_sandbox_unavailable_tiocsti",
                                  "seat_sandbox_unavailable_seat_uid"])
def test_j7_step2_incapable_host_takes_the_inline_route(code):
    token = _Counter(True)
    route = seat_jail.decide_seat_route("claude", staged_tree_approved=True,
                                        capable=_Counter(code), claude_token_present=token)
    assert route == seat_jail.SeatRoute(False, code)
    assert token.calls == 0


def test_j7_step3_missing_token_is_the_credential_code():
    assert _decide(token=False).code == "claude_seat_token_missing"


def test_j7_step3_credential_before_qualification_for_gemini():
    route = _decide("gemini", stop=None, cred=False, qualified=False)
    assert route.code == "gemini_seat_credential_missing"


def test_j7_all_steps_pass_is_the_jailed_route():
    assert _decide() == seat_jail.SeatRoute(True)


def test_j7_codex_and_grok_are_not_jailed_by_this_plan():
    assert _decide("codex") is None and _decide("grok") is None


@pytest.mark.parametrize("tiocsti,expected", [("0\n", None), ("1\n", "seat_sandbox_unavailable_tiocsti"),
                                               (None, "seat_sandbox_unavailable_tiocsti")])
def test_j11_tiocsti_precondition(tmp_path, tiocsti, expected):
    sysctl = tmp_path / "legacy_tiocsti"
    if tiocsti is not None:
        sysctl.write_text(tiocsti)
    code = seat_jail.seat_sandbox_capable(host_capable=lambda: True,
                                          tiocsti=lambda: seat_jail.tiocsti_safe(sysctl),
                                          seat_uid_available=lambda: True)
    assert code == expected


def test_j7_step2_live_on_this_host_names_the_missing_prerequisite():
    code = seat_jail.seat_sandbox_capable()
    if seat_uid.seat_uid_available():
        assert code in (None, "seat_sandbox_unavailable_host", "seat_sandbox_unavailable_tiocsti")
    else:
        assert code in ("seat_sandbox_unavailable_host", "seat_sandbox_unavailable_tiocsti",
                        "seat_sandbox_unavailable_seat_uid")


# --------------------------------------------------------------------------------------
# EC-EXECFIND-2: an unrecorded jail digest is refused, never jailed, never sent sealed.
# --------------------------------------------------------------------------------------

def _auth(staged: bool):
    class _A:
        staged_tree_sha256 = "a" * 64 if staged else None
    return _A()


def test_execfind_gate_refuses_an_unrecorded_digest_before_any_effect():
    route, notices, refusal = panel_invoker._seat_route_for_spawn(
        "claude", _auth(True), eligible=True,
        decide=lambda leg, **k: seat_jail.SeatRoute(True), pass_recorded=lambda d: False,
    )
    assert route.jailed and notices == [] and refusal == "seat_sandbox_refused:identity"


def test_execfind_gate_mutation_carrying_an_unrecorded_digest_would_jail():
    route, _, refusal = panel_invoker._seat_route_for_spawn(
        "claude", _auth(True), eligible=True,
        decide=lambda leg, **k: seat_jail.SeatRoute(True), pass_recorded=lambda d: True,
    )
    assert route.jailed and refusal is None


def test_sealed_route_carries_exactly_its_one_notice():
    route, notices, refusal = panel_invoker._seat_route_for_spawn(
        "claude", _auth(False), eligible=True)
    assert notices == ["seat_sandbox_not_staged"] and refusal is None


def test_non_production_routes_decide_nothing():
    assert panel_invoker._seat_route_for_spawn("claude", _auth(True), eligible=False) == (None, [], None)


def test_execfind_pass_record_is_keyed_by_the_exact_digest(tmp_path):
    digest = seat_jail.jail_profile_digest("claude")
    assert seat_jail.execfind_pass_recorded(digest, root=tmp_path) is False
    (tmp_path / f"{digest}.json").write_text(json.dumps({"profile_digest": digest, "result": "pass"}))
    assert seat_jail.execfind_pass_recorded(digest, root=tmp_path) is True
    other = "0" * 64
    (tmp_path / f"{other}.json").write_text(json.dumps({"profile_digest": digest, "result": "pass"}))
    assert seat_jail.execfind_pass_recorded(other, root=tmp_path) is False


def test_no_digest_has_a_recorded_pass_in_this_runtime():
    """The jailed route is inert until agent-harness#1071's falsifier run is recorded."""
    assert seat_jail.execfind_pass_recorded(seat_jail.jail_profile_digest("claude")) is False


def test_the_jail_digest_covers_mounts_flags_and_filter():
    base = seat_jail.jail_profile("claude", "x86_64")
    assert base["filter_sha256"] == seat_jail.production_filter_digest("x86_64")
    assert seat_jail.jail_profile_digest("claude", "x86_64") != seat_jail.jail_profile_digest(
        "gemini", "x86_64")


@pytest.mark.skip(reason=EXECFIND_1071)
def test_execfind2_jail_falsifiers_recorded_against_the_shipped_digest():
    """Acceptance: EC-EXECFIND-2's jail falsifiers pass against this digest (L4b era)."""


# --------------------------------------------------------------------------------------
# J8/J9: the sealed surfaces are byte-identical to the input base; the jailed argv.
# --------------------------------------------------------------------------------------

def test_j9_sealed_claude_argv_is_golden():
    assert panel_invoker._broker_claude_tui_command(
        model=None, effort=None, session_id="SESSION") == GOLDEN["claude"]
    assert panel_invoker._broker_claude_tui_command(
        model="claude-opus-5-5", effort="max", session_id="S2") == GOLDEN["claude_max"]


def test_j9_sealed_gemini_argv_settings_and_prompt_are_golden():
    import hashlib

    assert panel_invoker._brokered_gemini_command(
        model="gemini-3.8-flash", deadline_s=900.0, monitoring_policy="heartbeat_only") == GOLDEN["gemini_hb"]
    assert panel_invoker._brokered_gemini_command(
        model="gemini-3.8-flash", deadline_s=900.0) == GOLDEN["gemini_bounded"]
    assert hashlib.sha256(panel_invoker._render_broker_inline_prompt(
        "BUNDLE", "INSTR", "review").encode()).hexdigest() == GOLDEN["prompt_sha"]
    assert hashlib.sha256(panel_invoker._broker_agy_settings_bytes()).hexdigest() == GOLDEN["agy_settings_sha"]


def test_sandbox_usable_by_is_unchanged_unless_jailed():
    assert panel_invoker.sandbox_usable_by("claude", brokered=True) is False
    assert panel_invoker.sandbox_usable_by("gemini", brokered=True) is False
    assert panel_invoker.sandbox_usable_by("claude", brokered=True, jailed=True) is True


def _fake_jail(tmp_path: Path, **kw) -> seat_jail.SeatJail:
    review = tmp_path / "review"
    (review / seat_jail.HOST_TREE_DIRNAME).mkdir(parents=True)
    return seat_jail.build_seat_jail(
        "claude", review, Path("/usr/bin/true"),
        bundle_memfd=seat_jail.memfd_with("b", b"B"),
        instructions_memfd=seat_jail.memfd_with("i", b"I"),
        token_fd=seat_jail.token_pipe(b"tok"), seat_ids=(3, 3), **kw)


def test_jailed_claude_argv_has_full_tools_and_a_closed_config_surface(tmp_path):
    jail = _fake_jail(tmp_path)
    try:
        argv = panel_invoker._broker_claude_tui_command(model=None, effort=None,
                                                        session_id="S", sandboxed=jail)
    finally:
        seat_jail.close_jail_fds(jail)
    assert argv[0] == "/seat/bin/claude"
    assert argv[argv.index("--tools") + 1] == "default"
    assert argv[argv.index("--permission-mode") + 1] == "bypassPermissions"
    assert argv[argv.index("--setting-sources") + 1] == ""
    for flag in ("--safe-mode", "--strict-mcp-config", "--disable-slash-commands", "--no-chrome"):
        assert flag in argv
    assert "--disallowedTools" not in argv and "--bare" not in argv and "--restricted" not in argv


def test_pointer_brief_names_paths_and_digests_never_the_bundle():
    bundle = "UNTRUSTED BUNDLE " * 50_000  # far over the 512 KiB sealed cap
    prompt = panel_invoker._render_broker_pointer_prompt(
        bundle, "INSTRUCTIONS", source_commit="a" * 40, staged_tree_sha256="b" * 64)
    assert "UNTRUSTED BUNDLE" not in prompt
    assert "/seat/review/review-bundle.md" in prompt and "/seat/tree" in prompt
    assert f"bytes={len(bundle.encode())}" in prompt and "INSTRUCTIONS" in prompt
    with pytest.raises(ValueError):
        panel_invoker._render_broker_pointer_prompt("b", "i", source_commit="x",
                                                    staged_tree_sha256="b" * 64)


# --------------------------------------------------------------------------------------
# D8: the launch order and the drop.
# --------------------------------------------------------------------------------------

def test_d8_prefix_order_replaces_the_1109_switch(tmp_path):
    jail = _fake_jail(tmp_path)
    egress = ("nsenter", "--net", "--mount", "-t", "4242", "-U", "--preserve-credentials",
              "setpriv", "--bounding-set=-all", "--inh-caps=-all", "--")
    token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(egress)
    try:
        prefix = panel_invoker._compose_launch_prefix(None, process_owner=jail)
    finally:
        panel_invoker._EGRESS_LAUNCH_PREFIX.reset(token)
        seat_jail.close_jail_fds(jail)
    keyring = prefix.index("phase_loop_runtime.seat_keyring_exec")
    nsenter = prefix.index("nsenter")
    handoff = prefix.index("phase_loop_runtime.seat_uid")
    bwrap = prefix.index("/usr/bin/bwrap")
    drop = prefix.index("/usr/bin/setpriv")
    assert keyring < nsenter < handoff < bwrap < drop
    assert "--unshare-user" not in prefix and "--unshare-net" not in prefix
    assert "--map-user" not in " ".join(prefix) and "env" not in prefix[:bwrap]
    # An independent literal, never derived from the module under test.
    assert prefix[drop:] == ["/usr/bin/setpriv", "--reuid", "3", "--regid", "3", "--clear-groups",
                             "--inh-caps=-all", "--ambient-caps=-all", "--bounding-set=-all",
                             "--no-new-privs", "--"]
    caps = [prefix[i + 1] for i, item in enumerate(prefix) if item == "--cap-add"]
    assert caps == ["CAP_SETUID", "CAP_SETGID", "CAP_SETPCAP"]


def test_d8_prefix_refuses_without_the_seat_uid_holder(tmp_path):
    jail = _fake_jail(tmp_path)
    try:
        with pytest.raises(seat_jail.SeatSandboxRefused) as refused:
            panel_invoker._compose_launch_prefix(None, process_owner=jail)
    finally:
        seat_jail.close_jail_fds(jail)
    assert refused.value.code == "seat_sandbox_refused:namespace"


def test_j6_test_only_filter_variant_is_refused_before_any_probe(tmp_path, monkeypatch):
    variant = seat_jail.build_seccomp_filter(key_rules=False)
    jail = _fake_jail(tmp_path, seccomp_program=variant)
    spawned: list[object] = []
    monkeypatch.setattr(panel_invoker.subprocess, "run", lambda *a, **k: spawned.append(a))
    try:
        with pytest.raises(seat_jail.SeatSandboxRefused) as refused:
            panel_invoker._require_jailed_seat_identity(["true"], jail)
    finally:
        seat_jail.close_jail_fds(jail)
    assert refused.value.code == "seat_sandbox_refused:identity" and spawned == []


def test_j6_expected_identity_is_seat_ids_zero_caps_nnp_seccomp(tmp_path):
    jail = _fake_jail(tmp_path)
    try:
        lines = seat_jail.expected_probe_lines(jail)
    finally:
        seat_jail.close_jail_fds(jail)
    assert lines[:2] == ["3", "3"]
    assert lines[2:7] == [f"{c}:\t{0:016x}" for c in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")]
    assert lines[7:9] == ["NoNewPrivs:\t1", "Seccomp:\t2"]
    assert lines[-1] == "host-marker-hidden"


def test_jailed_launch_without_its_probe_jail_is_refused(tmp_path):
    jail = _fake_jail(tmp_path)
    try:
        with pytest.raises(seat_jail.SeatSandboxRefused):
            panel_invoker.launch_provider(["true"], process_owner=jail)
    finally:
        seat_jail.close_jail_fds(jail)


def test_seat_uid_map_argv_maps_operator_to_zero_and_the_range_above():
    argv = seat_uid.uid_map_argv("/usr/bin/newuidmap", 99, 1000,
                                 seat_uid.SubordinateRange(100000, 65536), 256)
    assert argv == ["/usr/bin/newuidmap", "99", "0", "1000", "1", "1", "100000", "256"]


def test_subordinate_range_parsing(tmp_path):
    subuid = tmp_path / "subuid"
    subuid.write_text(f"someone:1:2\n{os.getuid()}:200000:65536\nbad line\n")
    assert seat_uid.subordinate_range(subuid) == seat_uid.SubordinateRange(200000, 65536)
    subuid.write_text(f"{os.getuid()}:200000:1\n")  # no room for a seat id
    assert seat_uid.subordinate_range(subuid) is None


def test_seat_uid_unavailable_without_helpers_range_or_as_root(tmp_path):
    subuid = tmp_path / "subuid"
    subuid.write_text(f"{os.getuid()}:200000:65536\n")
    missing = str(tmp_path / "no-newuidmap")
    assert not seat_uid.seat_uid_available(subuid=subuid, subgid=subuid,
                                           newuidmap=missing, newgidmap=missing)
    assert not seat_uid.seat_uid_available(uid=0, subuid=subuid, subgid=subuid)


def test_seat_id_leases_are_exclusive(tmp_path):
    with seat_uid.lease_seat_id(2, directory=tmp_path) as first:
        with seat_uid.lease_seat_id(2, directory=tmp_path) as second:
            assert {first, second} == {1, 2}
            with pytest.raises(seat_uid.SeatIdsExhausted):
                with seat_uid.lease_seat_id(2, directory=tmp_path):
                    pass


def test_handoff_refuses_a_hard_linked_stage_before_any_chown(tmp_path, monkeypatch):
    seat_dir = tmp_path / "seat"
    tree = tmp_path / "tree"
    for directory in (seat_dir / "seat-home", seat_dir / "seat-out", tree):
        directory.mkdir(parents=True)
    outside = tmp_path / "operator-file"
    outside.write_text("secret")
    outside.chmod(0o600)
    os.link(outside, tree / "planted")
    chowned: list[object] = []
    monkeypatch.setattr(seat_uid, "chown_tree_at", lambda *a: chowned.append(a))
    with pytest.raises(seat_jail.SeatSandboxRefused) as refused:
        seat_uid.handoff(str(seat_dir), 5, tree=str(tree))
    assert refused.value.code == "seat_sandbox_refused:stage_not_private"
    assert chowned == []
    assert outside.stat().st_uid == os.getuid() and outside.stat().st_mode & 0o777 == 0o600


def test_handoff_mutation_skipping_nlink_rechowns_the_outside_inode(tmp_path):
    """The red half of the hand-off falsifier needs H-root and a seat uid."""
    require_seat_uid()
    pytest.skip("run on a prerequisite host by L5; see plans/evidence/seat-jail-1132")


# --------------------------------------------------------------------------------------
# The unmapped holder (sandbox_egress, D8): gate mechanics with a single-uid map.
# --------------------------------------------------------------------------------------

def _self_map(pid: int, **_: object) -> int:
    """Write "0 <uid> 1" -- the one mapping an unprivileged parent may write itself."""
    Path(f"/proc/{pid}/uid_map").write_text(f"0 {os.getuid()} 1\n")
    Path(f"/proc/{pid}/setgroups").write_text("deny\n")
    Path(f"/proc/{pid}/gid_map").write_text(f"0 {os.getgid()} 1\n")
    return 1


@pytest.mark.skipif(not sandbox_egress.egress_isolation_available(),
                    reason="needs unshare + slirp4netns + iptables")
@pytest.mark.parametrize("timeout_s", [None, 120.0])
def test_unmapped_holder_waits_for_its_map_then_yields_a_working_prefix(monkeypatch, timeout_s):
    monkeypatch.setattr(seat_uid, "map_holder", _self_map)
    with sandbox_egress.isolated_network(timeout_s=timeout_s, required=True,
                                         seat_uid_map=True) as prefix:
        assert prefix and prefix[0] == "nsenter"
        done = subprocess.run([*prefix, "id", "-u"], capture_output=True, text=True, timeout=30)
        assert done.stdout.strip() == "0"  # the operator is H-root
        assert seat_uid.holder_pid_from_prefix(prefix) > 0


@pytest.mark.skipif(not sandbox_egress.egress_isolation_available(),
                    reason="needs unshare + slirp4netns + iptables")
def test_unmapped_holder_that_cannot_be_mapped_refuses(monkeypatch):
    def _fail(pid, **_):
        raise OSError("newuidmap failed")

    monkeypatch.setattr(seat_uid, "map_holder", _fail)
    with pytest.raises(sandbox_egress.EgressUnavailable):
        with sandbox_egress.isolated_network(timeout_s=60.0, required=True, seat_uid_map=True):
            pass


# --------------------------------------------------------------------------------------
# Live D8 (P5-shaped): skip-guarded on the maintainer's prerequisite.
# --------------------------------------------------------------------------------------

def test_j6_j15_live_seat_runs_as_its_subordinate_uid_with_nothing_left():
    require_seat_uid()
    pytest.skip("P5/L5 live replay on a prerequisite host; see plans/evidence/seat-jail-1132")


def test_j4_live_concurrent_seats_cannot_reach_each_other():
    require_seat_uid()
    pytest.skip("L5 live check on a prerequisite host; see plans/evidence/seat-jail-1132")


def test_live_jailed_claude_runs_a_tool_and_quotes_it():
    require_seat_uid()
    require_seat_token()
    pytest.skip("L5 live board on a prerequisite host with a seat token")


# --------------------------------------------------------------------------------------
# J8: the evidence verifier reports EC-HARDEN-5 UNMET on every tooled or pointer record.
# --------------------------------------------------------------------------------------

def _verifier():
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / "verify_harden_evidence.py"
    spec = importlib.util.spec_from_file_location("verify_harden_evidence_1132", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("record", [
    {"provider_input_mode": "pointer"},
    {"provider_input_inline": False},
    {"sandbox_filesystem_confined": True},
    {"seat_jail_profile_digest": "a" * 64},
])
def test_j8_verifier_reports_harden5_unmet_on_tooled_records(record):
    verifier = _verifier()
    with pytest.raises(verifier.EvidenceError, match="EC-HARDEN-5 UNMET.*agent-harness#361"):
        verifier.verify_broker(record, "claude", "m", "m", "0" * 64, "0" * 64, "p", "r")


def test_j8_a_sealed_record_is_not_reported_unmet():
    verifier = _verifier()
    assert verifier.harden5_unmet({"provider_input_inline": True,
                                   "provider_live_tree_cwd": False}) is False
