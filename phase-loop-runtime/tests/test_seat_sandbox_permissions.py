"""Falsifiers for the jailed-seat route (agent-harness#1132): J6-J9, J13, J15, D8.

What runs here without the maintainer's root prerequisite: the J7 order (each step's one
code), the D8 argv (holder map, launch order, drop), the J9 goldens, the EC-EXECFIND-2
gate, the jailed Claude argv, and the unmapped-holder mechanics with a single-uid map the
operator may write itself. Everything that needs a subordinate uid is skip-guarded with
the literal prerequisite; it neither fails nor passes on a host without it.
"""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from phase_loop_runtime import panel_invoker, sandbox_egress, seat_jail, seat_uid


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


def test_j7_gemini_stays_sealed_on_the_recorded_p4_stop():
    """P4 found scopes beyond inference; the "prove then enable" containment probe proved
    the access-token-only copy (a) and failed host-level egress (b). The recorded stop wins
    at step 1, and it is witnessed by the pinned evidence records."""
    evidence = Path(__file__).resolve().parents[2] / "plans" / "evidence" / "seat-jail-1132"
    assert seat_jail.GEMINI_RECORDED_STOP == "gemini_seat_egress_unconfined"
    scope = json.loads((evidence / "p4-agy-d7-credential.json").read_text())
    assert scope["gemini_route_code"] == "gemini_seat_token_scope_excess"
    record = json.loads((evidence / "p4-containment.json").read_text())
    assert record["a_holds"] is True and record["b_holds"] is False
    assert record["result"] == "stop" and record["gemini_route_code"] == seat_jail.GEMINI_RECORDED_STOP
    assert "gemini" not in seat_jail.JAILED_LEGS
    route = seat_jail.decide_seat_route("gemini", staged_tree_approved=True)
    assert route == seat_jail.SeatRoute(False, "gemini_seat_egress_unconfined")


def test_j7_without_a_stop_gemini_is_still_unqualified_until_l3():
    route = _decide("gemini", stop=None, qualified=True)
    assert route == seat_jail.SeatRoute(False, "gemini_seat_profile_unqualified")


@pytest.mark.parametrize("leg", ["claude", "gemini", "codex", "grok"])
def test_j7_the_jailed_route_is_claude_only(leg):
    """With every route fact forced true and no recorded stop, only Claude is jailed; a
    Gemini seat stays sealed with its typed notice (the tooled Gemini seat is
    agent-harness#1170)."""
    assert seat_jail.JAILED_LEGS == frozenset({"claude"})
    route = seat_jail.decide_seat_route(
        leg, staged_tree_approved=True, capable=lambda: None,
        claude_token_present=lambda: True, gemini_credential_present=lambda: True,
        gemini_qualified=lambda: True, gemini_recorded_stop=None)
    if leg == "claude":
        assert route == seat_jail.SeatRoute(True)
    elif leg == "gemini":
        assert route == seat_jail.SeatRoute(False, "gemini_seat_profile_unqualified")
    else:
        assert route is None


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
    assert route.jailed and notices == [] and refusal == "seat_sandbox_refused:jail_unqualified"


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


LAYOUT = "execfind-layout-test"
HOST = "a" * 64


def _write_pass(directory: Path, digest: str, *, host: str = HOST, layout: str = LAYOUT,
                evidence: dict | None = None) -> None:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    body = evidence if evidence is not None else {
        "profile_digest": digest, "result": "pass", "host_identity": host,
        "falsifier_layout": layout, "falsifiers": ["J1", "J14"]}
    raw = json.dumps(body).encode()
    (directory / f"{digest}.evidence.json").write_bytes(raw)
    (directory / f"{digest}.evidence.json").chmod(0o600)
    record = {"schema": seat_jail.PASS_RECORD_SCHEMA, "profile_digest": digest, "result": "pass",
              "host_identity": host, "falsifier_layout": layout,
              "evidence": f"{digest}.evidence.json",
              "evidence_sha256": __import__("hashlib").sha256(raw).hexdigest()}
    (directory / f"{digest}.json").write_text(json.dumps(record))
    (directory / f"{digest}.json").chmod(0o600)


def _qualified(directory: Path, digest: str, **kw) -> bool:
    return seat_jail.execfind_pass_recorded(digest, root=directory, layout=kw.get("layout", LAYOUT),
                                            host=kw.get("host", HOST))


def test_a_complete_bound_record_qualifies_exactly_its_digest(tmp_path):
    digest = seat_jail.jail_profile_digest("claude")
    _write_pass(tmp_path, digest)
    assert _qualified(tmp_path, digest) is True
    assert _qualified(tmp_path, "0" * 64) is False


def test_a_record_from_another_falsifier_layout_is_no_pass(tmp_path):
    """The default layout is the live EXECFIND identity: a record bound to any other layout
    (an older runner, or none) does not qualify."""
    digest = seat_jail.jail_profile_digest("claude")
    _write_pass(tmp_path, digest)  # bound to the test layout, not the live one
    assert seat_jail.execfind_pass_recorded(digest, root=tmp_path, host=HOST) is False
    _write_pass(tmp_path, digest, layout=seat_jail.falsifier_layout_identity())
    assert seat_jail.execfind_pass_recorded(digest, root=tmp_path, host=HOST) is True


def test_codex_r4_a_hand_written_pass_without_evidence_is_no_pass(tmp_path):
    """Round 4 (codex): an owner-written 0600 record with the digest and `result: pass`
    admitted the route. Without the evidence it names, re-hashed, it does not."""
    digest = seat_jail.jail_profile_digest("claude")
    tmp_path.chmod(0o700)
    (tmp_path / f"{digest}.json").write_text(json.dumps({
        "schema": seat_jail.PASS_RECORD_SCHEMA, "profile_digest": digest, "result": "pass",
        "host_identity": HOST, "falsifier_layout": LAYOUT}))
    (tmp_path / f"{digest}.json").chmod(0o600)
    assert _qualified(tmp_path, digest) is False


def test_codex_r4_another_hosts_record_is_no_pass(tmp_path):
    digest = seat_jail.jail_profile_digest("claude")
    _write_pass(tmp_path, digest, host="b" * 64)          # recorded on another host
    assert _qualified(tmp_path, digest) is False


def test_codex_r4_a_stale_record_is_no_pass(tmp_path):
    digest = seat_jail.jail_profile_digest("claude")
    _write_pass(tmp_path, digest)
    evidence = tmp_path / f"{digest}.evidence.json"
    evidence.chmod(0o600)
    evidence.write_text(evidence.read_text().replace('"J14"', '"J14", "edited"'))
    assert _qualified(tmp_path, digest) is False            # evidence no longer hashes
    _write_pass(tmp_path, digest, layout="older-layout")
    assert _qualified(tmp_path, digest) is False            # recorded by another layout


def test_codex_r4_accidental_reuse_of_a_copied_record_is_no_pass(tmp_path):
    digest = seat_jail.jail_profile_digest("claude")
    _write_pass(tmp_path / "a", digest)
    fresh = tmp_path / "fresh"
    fresh.mkdir(mode=0o700)
    (fresh / f"{digest}.json").write_bytes((tmp_path / "a" / f"{digest}.json").read_bytes())
    (fresh / f"{digest}.json").chmod(0o600)
    assert _qualified(fresh, digest) is False               # the evidence did not come with it


def test_codex_r4_a_seat_owned_record_is_no_pass(tmp_path, monkeypatch):
    """The seat uid is not the operator: a record it owned would be refused by owner."""
    digest = seat_jail.jail_profile_digest("claude")
    _write_pass(tmp_path, digest)
    real = seat_jail.os.geteuid
    monkeypatch.setattr(seat_jail.os, "geteuid", lambda: real() + 200000)
    assert _qualified(tmp_path, digest) is False


@pytest.mark.parametrize("parent", ["symlink", "group-writable"])
def test_codex_r4_an_unsafe_parent_directory_is_no_pass(tmp_path, monkeypatch, parent):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    # A shared group: the operator's primary group also lists another member. (Hermetic:
    # the real account database would decide differently on different hosts.)
    _fake_accounts(monkeypatch, os.stat(tmp_path).st_gid, members=("op", "someone-else"))
    digest = seat_jail.jail_profile_digest("claude")
    (tmp_path / "state").mkdir(mode=0o700)
    real = tmp_path / "elsewhere"
    _write_pass(real, digest)
    if parent == "symlink":
        (tmp_path / "state" / "phase-loop").mkdir(mode=0o700)
        (tmp_path / "state" / "phase-loop" / "seat-jail-passes").symlink_to(real)
    else:
        _write_pass(seat_jail.jail_pass_dir(), digest)
        (tmp_path / "state" / "phase-loop").chmod(0o770)
    assert seat_jail.execfind_pass_recorded(digest, layout=LAYOUT, host=HOST) is False


def test_the_default_store_is_per_user_state(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    (tmp_path / "state").mkdir(mode=0o700)
    digest = seat_jail.jail_profile_digest("claude")
    assert seat_jail.jail_pass_dir() == tmp_path / "state" / "phase-loop" / "seat-jail-passes"
    (tmp_path / "state" / "phase-loop").mkdir(mode=0o700)
    _write_pass(seat_jail.jail_pass_dir(), digest)
    assert seat_jail.execfind_pass_recorded(digest, layout=LAYOUT, host=HOST) is True
    assert not (Path(seat_jail.__file__).parent / "seat_jail_passes").exists()


@pytest.mark.parametrize("shape", ["fifo", "nested-json-bomb", "oversized", "directory"])
def test_codex_r4_unsafe_records_give_a_typed_refusal_in_bounded_time(tmp_path, shape):
    import time

    digest = seat_jail.jail_profile_digest("claude")
    tmp_path.chmod(0o700)
    target = tmp_path / f"{digest}.json"
    if shape == "fifo":
        os.mkfifo(target, 0o600)
    elif shape == "nested-json-bomb":
        target.write_text("[" * 3000 + "]" * 3000)
        target.chmod(0o600)
    elif shape == "oversized":
        target.write_bytes(b" " * (seat_jail._PASS_RECORD_CAP + 1))
        target.chmod(0o600)
    else:
        target.mkdir(mode=0o700)
    started = time.monotonic()
    route, _, refusal = panel_invoker._seat_route_for_spawn(
        "claude", _auth(True), eligible=True, decide=lambda leg, **k: seat_jail.SeatRoute(True),
        pass_recorded=lambda d: _qualified(tmp_path, d))
    assert refusal == "seat_sandbox_refused:jail_unqualified"
    assert time.monotonic() - started < 5


def test_codex_r4_a_digest_change_between_gate_and_launch_is_refused(tmp_path, monkeypatch):
    """Round 4 (codex): the gate admitted digest A, then the host layout changed and the jail
    was built with digest B. The launch re-checks qualification against the BUILT jail."""
    admitted = seat_jail.jail_profile_digest("claude")
    monkeypatch.setattr(seat_jail, "ETC_READONLY_SUBSET", seat_jail.ETC_READONLY_SUBSET + ("pl-new",))
    real_lexists = os.path.lexists
    monkeypatch.setattr(seat_jail.os.path, "lexists",
                        lambda p: True if str(p) == "/etc/pl-new" else real_lexists(p))
    jail = _fake_jail(tmp_path)
    try:
        assert jail.profile_digest != admitted
        with pytest.raises(seat_jail.SeatSandboxRefused) as refused:
            panel_invoker._require_qualified_jail(jail, pass_recorded=lambda d: d == admitted)
    finally:
        seat_jail.close_jail_fds(jail)
    assert refused.value.code == "seat_sandbox_refused:jail_unqualified"


def test_the_built_jail_reproduces_the_canonical_digest(tmp_path):
    jail = _fake_jail(tmp_path)
    try:
        assert jail.profile_digest == seat_jail.jail_profile_digest("claude")
        panel_invoker._require_canonical_jail(jail)
    finally:
        seat_jail.close_jail_fds(jail)
    assert seat_jail.jail_profile_digest("claude") != seat_jail.jail_profile_digest("gemini")


def test_codex_r1_an_extra_bind_invalidates_the_qualified_digest(tmp_path):
    """Board round 1 (codex): an added host bind kept the digest and passed the probe. The
    digest now binds the ACTUAL argv, so the launch is refused."""
    jail = _fake_jail(tmp_path)
    owner = list(jail.process_owner)
    at = owner.index("--remount-ro")
    owner[at:at] = ["--ro-bind", str(Path.home()), "/seat/leak"]
    mutated = dataclasses.replace(jail, process_owner=tuple(owner))
    try:
        with pytest.raises(seat_jail.SeatSandboxRefused) as refused:
            panel_invoker._require_canonical_jail(mutated)
    finally:
        seat_jail.close_jail_fds(jail)
    assert refused.value.code == "seat_sandbox_refused:identity"


def test_codex_r1_dropping_seccomp_invalidates_the_qualified_digest(tmp_path):
    jail = _fake_jail(tmp_path)
    owner = list(jail.process_owner)
    at = owner.index("--seccomp")
    del owner[at:at + 2]
    mutated = dataclasses.replace(jail, process_owner=tuple(owner))
    try:
        with pytest.raises(seat_jail.SeatSandboxRefused):
            panel_invoker._require_canonical_jail(mutated)
    finally:
        seat_jail.close_jail_fds(jail)


def test_codex_r1_the_installed_filter_bytes_are_checked_not_metadata(tmp_path):
    """The memfd holds the test-only variant while the stored digest claims production."""
    jail = _fake_jail(tmp_path, seccomp_program=seat_jail.build_seccomp_filter(key_rules=False))
    lying = dataclasses.replace(jail, filter_digest=seat_jail.production_filter_digest())
    try:
        with pytest.raises(seat_jail.SeatSandboxRefused):
            panel_invoker._require_canonical_jail(lying)
    finally:
        seat_jail.close_jail_fds(jail)


def test_expected_mounts_do_not_follow_an_extra_bind(tmp_path):
    jail = _fake_jail(tmp_path)
    owner = list(jail.process_owner)
    owner[owner.index("--remount-ro"):owner.index("--remount-ro")] = ["--bind", "/srv", "/seat/leak"]
    mutated = dataclasses.replace(jail, process_owner=tuple(owner))
    try:
        assert "/seat/leak" not in seat_jail.expected_mount_points(mutated)
    finally:
        seat_jail.close_jail_fds(jail)


def test_the_falsifier_layout_identity_follows_execfind_staging(monkeypatch):
    """EC-EXECFIND-2: any change to EXECFIND's staging invalidates recorded passes."""
    from phase_loop_runtime import review_stage

    before = seat_jail.falsifier_layout_identity()
    monkeypatch.setattr(review_stage, "_FALSIFIER_SYSTEM_ROOTS",
                        (*review_stage._FALSIFIER_SYSTEM_ROOTS, Path("/opt")))
    assert seat_jail.falsifier_layout_identity() != before


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
                             "--no-new-privs", "--", "/usr/bin/env", "--chdir=/seat/tree", "--",
                             *seat_jail.seat_fd_closer(str(jail.token_fd))]
    # P5: bwrap as H-root keeps every capability unless emptied first.
    assert prefix.index("--cap-drop") < prefix.index("--cap-add")
    assert prefix[prefix.index("--cap-drop") + 1] == "ALL" and "--chdir" not in prefix
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


def test_hang_investigation_sealed_claude_tui_session_is_golden_to_main(monkeypatch, tmp_path):
    """Board round 1 hang investigation (agent-harness#1166): on the sealed route this
    runtime hands the Claude TUI session EXACTLY what main's runtime does -- argv, cwd shape,
    env keys, prompt and every liveness/monitoring kwarg. The golden was captured from
    main's runtime (origin/main b6a482fa) with the same inputs."""
    import uuid as _uuid

    golden = json.loads((Path(__file__).parent / "data"
                         / "seat_jail_1132_sealed_tui_session_golden.json").read_text())
    captured: dict[str, object] = {}

    def fake(**kw):
        captured.update({k: (list(v) if k == "command" else sorted(v) if k == "env"
                             else str(v) if isinstance(v, (str, int, float, bool, type(None), Path))
                             else type(v).__name__) for k, v in kw.items()})
        return 0, "ok\n\nAGREE", "claude_tui_file_output", ""

    monkeypatch.setattr(panel_invoker, "_run_claude_tui_session", fake)
    monkeypatch.setattr(panel_invoker, "_claude_code_support_status", lambda *a: (True, "supported"))
    monkeypatch.setattr(panel_invoker, "_claude_subscription_auth_ok", lambda env: (True, ""))
    monkeypatch.setattr(panel_invoker, "_under_claude_code", lambda env=None: False)
    monkeypatch.setattr(panel_invoker, "_cleanup_broker_claude_transcript", lambda p, e: True)
    monkeypatch.setattr(panel_invoker.uuid, "uuid4",
                        lambda: _uuid.UUID("00000000-0000-4000-8000-000000000000"))
    (tmp_path / "r").mkdir()
    (tmp_path / "o").mkdir()
    panel_invoker._exec_claude_tui_leg(
        tmp_path / "r", tmp_path / "o", 30, "BUNDLE", model="claude-opus-5-5", effort="max",
        env={"HOME": "/h", "PATH": "/usr/bin", "TERM": "xterm"}, broker_prompt="PROMPT",
        broker_evidence={})
    for key in ("cwd", "output_file"):
        captured[key] = str(captured[key]).replace(str(tmp_path), "<d>")
    captured["broker_transcript_path"] = "<redacted path>"
    assert captured == golden


# --------------------------------------------------------------------------------------
# Board round 5 (codex): the WHOLE record evaluation is one fail-closed boundary. Hostile
# record shapes must yield the typed refusal through the real route gate, never an error.
# --------------------------------------------------------------------------------------

# The typed reason for each shape: an exception is caught by the boundary and named by class.
R5_REASONS = {"nul-in-evidence-name": "error:ValueError",
              "unpaired-surrogate": "error:UnicodeEncodeError",
              "non-string-evidence": "evidence_mismatch", "huge-integer": "evidence_mismatch"}


@pytest.mark.parametrize("shape", ["nul-in-evidence-name", "unpaired-surrogate",
                                   "non-string-evidence", "huge-integer"])
def test_codex_r5_hostile_records_refuse_typed_through_the_gate(tmp_path, monkeypatch, shape):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    for directory in (tmp_path / "state", tmp_path / "state" / "phase-loop"):
        directory.mkdir(mode=0o700)
    digest = seat_jail.jail_profile_digest("claude")
    store = seat_jail.jail_pass_dir()
    _write_pass(store, digest, host=seat_jail.host_identity(),
                layout=seat_jail.falsifier_layout_identity())
    assert seat_jail.execfind_pass_recorded(digest) is True  # control: the bound record passes
    record_path = store / f"{digest}.json"
    record = json.loads(record_path.read_text())
    raw = None
    if shape == "nul-in-evidence-name":
        record["evidence"] = "bad\u0000name"
    elif shape == "unpaired-surrogate":
        raw = json.dumps(record).replace(json.dumps(record["evidence"]), '"bad\\ud800name"')
    elif shape == "non-string-evidence":
        record["evidence"] = {"not": "a name"}
    else:
        raw = json.dumps(record).replace(json.dumps(record["evidence_sha256"]), "9" * 4000)
    record_path.write_text(raw if raw is not None else json.dumps(record))
    record_path.chmod(0o600)
    assert seat_jail.pass_record_verdict(digest) == (False, R5_REASONS[shape])
    route, notices, refusal = panel_invoker._seat_route_for_spawn(
        "claude", _auth(True), eligible=True, decide=lambda leg, **k: seat_jail.SeatRoute(True))
    assert refusal == "seat_sandbox_refused:jail_unqualified" and notices == []


def test_codex_r5_the_exception_class_reaches_the_launch_refusal_and_the_log(
        tmp_path, monkeypatch, caplog):
    """The route detail stays a closed code (F030); the class is in the launch refusal's
    message and in the log, as the verdict's typed reason."""
    def boom(*args, **kwargs):
        raise LookupError("unexpected")

    monkeypatch.setattr(seat_jail, "_evaluate_pass_record", boom)
    digest = seat_jail.jail_profile_digest("claude")
    assert seat_jail.pass_record_verdict(digest) == (False, "error:LookupError")
    with caplog.at_level("WARNING"):
        refusal = panel_invoker._pass_refusal(digest)
    assert refusal == ("seat_sandbox_refused:jail_unqualified", "error:LookupError")
    assert "LookupError" in caplog.text


# --------------------------------------------------------------------------------------
# The pass store under a umask-002 host (user-private groups): a group-writable directory
# is accepted ONLY when its group is the operator's user-private group.
# --------------------------------------------------------------------------------------

def _fake_accounts(monkeypatch, gid, *, primary=None, group_name="op", members=(),
                   other_primary=False, database=True):
    """Inject the account database: the operator ``op`` (this euid) and the group ``gid``."""
    from types import SimpleNamespace

    me = SimpleNamespace(pw_name="op", pw_uid=os.geteuid(),
                         pw_gid=gid if primary is None else primary)
    group = SimpleNamespace(gr_name=group_name, gr_mem=list(members))

    def getgrgid(wanted):
        if wanted != gid:
            raise KeyError(wanted)
        return group

    accounts = [me]
    if other_primary:
        accounts.append(SimpleNamespace(pw_name="other", pw_uid=os.geteuid() + 1, pw_gid=gid))
    monkeypatch.setattr(seat_jail, "_account_db",
                        (lambda: (me, getgrgid, lambda: accounts)) if database else (lambda: None))


def _umask002_store(tmp_path, monkeypatch, *, mode=0o775) -> str:
    """The layout a umask-002 host creates: every directory in the chain is ``mode``."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    digest = seat_jail.jail_profile_digest("claude")
    _write_pass(seat_jail.jail_pass_dir(), digest)
    for directory in (tmp_path / "state", tmp_path / "state" / "phase-loop",
                      seat_jail.jail_pass_dir()):
        directory.chmod(mode)
    return digest


def test_upg_a_group_writable_chain_in_the_operators_private_group_qualifies(
        tmp_path, monkeypatch):
    digest = _umask002_store(tmp_path, monkeypatch)
    _fake_accounts(monkeypatch, os.stat(tmp_path / "state").st_gid, members=("op",))
    assert seat_jail.pass_record_verdict(digest, layout=LAYOUT, host=HOST) == (True, "pass")


@pytest.mark.parametrize("shape", ["not-the-primary-gid", "group-named-otherwise",
                                   "group-has-another-member", "another-accounts-primary",
                                   "no-account-database", "other-writable"])
def test_upg_every_other_group_writable_chain_refuses_with_the_chmod_notice(
        tmp_path, monkeypatch, shape):
    digest = _umask002_store(tmp_path, monkeypatch,
                             mode=0o777 if shape == "other-writable" else 0o775)
    gid = os.stat(tmp_path / "state").st_gid
    _fake_accounts(monkeypatch, gid,
                   primary=gid + 1 if shape == "not-the-primary-gid" else None,
                   group_name="staff" if shape == "group-named-otherwise" else "op",
                   members=("op", "someone-else") if shape == "group-has-another-member" else (),
                   other_primary=shape == "another-accounts-primary",
                   database=shape != "no-account-database")
    passed, reason = seat_jail.pass_record_verdict(digest, layout=LAYOUT, host=HOST)
    problem = "other_writable" if shape == "other-writable" else "group_writable"
    assert not passed and reason == f"store_unsafe:{problem}:{tmp_path / 'state'}"
    route, notices, refusal = panel_invoker._seat_route_for_spawn(
        "claude", _auth(True), eligible=True, decide=lambda leg, **k: seat_jail.SeatRoute(True),
        pass_recorded=None)
    assert refusal == "seat_sandbox_refused:pass_store_unsafe" and notices == []
    fix = seat_jail.NOTICES["seat_sandbox_refused:pass_store_unsafe"][2]
    assert "chmod go-w" in fix and "user-private group" in fix


def test_upg_the_recorder_accepts_the_private_group_and_refuses_a_shared_one(
        tmp_path, monkeypatch):
    from phase_loop_runtime import seat_jail_qualification as q

    state = tmp_path / "state"
    state.mkdir(mode=0o775)
    state.chmod(0o775)
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    gid = os.stat(state).st_gid
    evidence = {"profile_digest": "0" * 64, "host_identity": "h", "falsifier_layout": "l",
                "result": "pass"}
    _fake_accounts(monkeypatch, gid, members=("op", "someone-else"))
    with pytest.raises(q.QualificationError, match="user-private group"):
        q._record_pass(evidence)
    _fake_accounts(monkeypatch, gid)
    q._record_pass(evidence)
    assert state.stat().st_mode & 0o777 == 0o775                 # never re-permissioned
    assert (seat_jail.jail_pass_dir() / f"{'0' * 64}.json").is_file()


# --------------------------------------------------------------------------------------
# Seat-token rotation: the operator may swap the token file between legs (atomic rename in
# the same 0700 directory). Each launch reads it afresh; a running leg keeps its own.
# --------------------------------------------------------------------------------------

def _store_token(path: Path, token: bytes) -> None:
    staged = path.with_name(path.name + ".new")
    fd = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(token + b"\n")
    os.replace(staged, path)


def test_the_seat_token_is_read_afresh_after_an_atomic_replace(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    path = seat_jail.claude_seat_token_path()
    path.parent.mkdir(parents=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    _store_token(path, b"TOKEN-SUBSCRIPTION-A")
    assert seat_jail.read_claude_seat_token() == b"TOKEN-SUBSCRIPTION-A"
    _store_token(path, b"TOKEN-SUBSCRIPTION-B")
    assert seat_jail.read_claude_seat_token() == b"TOKEN-SUBSCRIPTION-B"


def test_each_jailed_leg_launches_with_the_token_current_at_its_launch(monkeypatch, tmp_path):
    import types

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    path = seat_jail.claude_seat_token_path()
    path.parent.mkdir(parents=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    delivered: list[bytes] = []

    def _build(leg, seat_dir, executable, *, token_fd, **_kw):
        token = os.read(token_fd, 4096)
        os.close(token_fd)
        if token != b"probe":
            delivered.append(token)   # what the seat's CLI would drain from its pipe
        return types.SimpleNamespace(leg=leg)

    monkeypatch.setattr(panel_invoker._seat_jail, "build_seat_jail", _build)
    monkeypatch.setattr(panel_invoker._seat_jail, "tree_manifest_sha256_at", lambda fd: "a" * 64)
    monkeypatch.setattr(panel_invoker._seat_jail, "CLAUDE_PRESEED", {})
    monkeypatch.setattr(panel_invoker, "_resolve_claude_executable", lambda: Path("/usr/bin/true"))
    auth = types.SimpleNamespace(staged_tree_sha256="a" * 64)

    def _launch(name: str):
        review = tmp_path / name / "review"
        (review / seat_jail.HOST_TREE_DIRNAME).mkdir(parents=True)
        return panel_invoker._prepare_jailed_claude(review, tmp_path / name / "seat", auth, 1, 1,
                                         ("bundle", "instructions"))

    _store_token(path, b"TOKEN-SUBSCRIPTION-A")
    first = _launch("leg-1")
    _store_token(path, b"TOKEN-SUBSCRIPTION-B")    # rotation between two legs
    second = _launch("leg-2")
    assert delivered == [b"TOKEN-SUBSCRIPTION-A", b"TOKEN-SUBSCRIPTION-B"]
    # The running leg keeps its own token (its output scan uses it), whatever the file holds now.
    assert first.token == b"TOKEN-SUBSCRIPTION-A" and second.token == b"TOKEN-SUBSCRIPTION-B"
