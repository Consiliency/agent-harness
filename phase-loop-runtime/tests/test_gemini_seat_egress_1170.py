"""agent-harness#1170: the Gemini seat runs jailed with tools; its egress goes through an
allowlisting proxy (srt's TLS-terminating proxy, plan agent-harness#1244 rulings S3/S4).

The route, the jail profile, the proxy-only namespace rules, the pinned egress layer and the
tooled stream are held here. The live containment and P3 evidence is recorded by the probes
in plans/evidence/seat-jail-1132/; ``test_live_proxy_*`` re-run the containment rows on a
host where the egress layer is installed.
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import subprocess
import time
import types
from pathlib import Path

import pytest

from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import sandbox_egress, seat_egress_proxy, seat_jail

_REAL_DECIDE = getattr(seat_jail.decide_seat_route, "real", seat_jail.decide_seat_route)


def _decide(leg="gemini", *, egress=None, qualified=None, cred=True, capable=None):
    return _REAL_DECIDE(
        leg, staged_tree_approved=True, capable=capable or (lambda: None),
        claude_token_present=lambda: True, gemini_credential_present=lambda: cred,
        gemini_qualified=qualified, gemini_egress_unavailable=lambda: egress)


# --------------------------------------------------------------------------------------
# The route.
# --------------------------------------------------------------------------------------

def test_gemini_has_no_recorded_stop_and_is_a_jailed_leg():
    assert seat_jail.GEMINI_RECORDED_STOP is None
    assert seat_jail.JAILED_LEGS == frozenset({"claude", "gemini"})


def test_a_capable_host_with_its_egress_layer_jails_the_gemini_seat():
    assert _decide() == seat_jail.SeatRoute(True)


def test_without_its_egress_layer_the_gemini_seat_is_degraded_never_sealed():
    route = _decide(egress="srt is not installed")
    assert route == seat_jail.SeatRoute(False, "gemini_seat_egress_unavailable")
    assert route.code in seat_jail.JAIL_NOT_RUN_CODES
    assert route.code not in seat_jail.SEALED_FALLBACK_CODES
    what, why, fix = seat_jail.NOTICES[route.code]
    assert "phase-loop seat-egress install" in fix


def test_the_spawn_refuses_a_gemini_seat_without_its_egress_layer():
    route, notices, refusal = pi._seat_route_for_spawn(
        "gemini", types.SimpleNamespace(staged_tree_sha256="a" * 64), eligible=True,
        decide=lambda leg, **kw: _decide(leg, egress="node is not installed"))
    assert not route.jailed and notices == [] and refusal == "gemini_seat_egress_unavailable"


def test_the_egress_check_follows_the_credential_and_an_injected_qualification():
    assert _decide(cred=False, egress="x").code == "gemini_seat_credential_missing"
    assert _decide(qualified=lambda: False, egress="x").code == "gemini_seat_profile_unqualified"


def test_an_incapable_host_still_takes_the_sealed_route():
    route = _decide(capable=lambda: "seat_sandbox_unavailable_host", egress="x")
    assert route == seat_jail.SeatRoute(False, "seat_sandbox_unavailable_host")


def test_the_new_code_is_a_harness_detail_code():
    assert "gemini_seat_egress_unavailable" in pi._HARNESS_DETAIL_CODES


# --------------------------------------------------------------------------------------
# The jail profile.
# --------------------------------------------------------------------------------------

def _gemini_jail(tmp_path: Path, proxy="http://srt:session-token-1@127.0.0.1:3128"):
    review = tmp_path / "seat"
    tree = tmp_path / "review" / seat_jail.HOST_TREE_DIRNAME
    tree.mkdir(parents=True)
    review.mkdir()
    config = review / seat_jail.HOST_GEMINI_CONFIG_DIRNAME
    pi._write_gemini_config(config, b'{"token": {}}')
    ca = review / "egress-ca.pem"
    ca.write_text("certificate\n")
    return seat_jail.build_seat_jail(
        "gemini", review, Path("/usr/bin/true"), tree=tree,
        bundle_memfd=seat_jail.memfd_with("b", b"B"),
        instructions_memfd=seat_jail.memfd_with("i", b"I"), seat_ids=(3, 3),
        gemini_config=config, egress_ca=ca, egress_proxy=proxy)


def _binds(owner):
    return [(owner[i], owner[i + 1], owner[i + 2]) for i, item in enumerate(owner)
            if item in ("--bind", "--ro-bind")]


def test_the_gemini_jail_binds_its_config_read_only_and_only_the_measured_dirs_writable(tmp_path):
    jail = _gemini_jail(tmp_path)
    try:
        binds = _binds(list(jail.process_owner))
        config = seat_jail.SEAT_GEMINI_CONFIG
        # F006: the read-only bind is the ancestor `.gemini`, not `antigravity-cli` itself,
        # so the seat cannot rename the ancestor and recreate a writable config under it.
        assert ("--ro-bind", jail.gemini_config_dir, seat_jail.SEAT_GEMINI_DOTDIR) in binds
        assert not any(target == config for _k, _s, target in binds)  # config is never its own mount
        writable = sorted(target for kind, _src, target in binds
                          if kind == "--bind" and target.startswith(config + "/"))
        assert writable == [f"{config}/{name}" for name in ("bin", "cache", "log")]
        assert ("--ro-bind", jail.egress_ca, seat_jail.SEAT_EGRESS_CA) in binds
        env = jail.env
        assert env["HTTPS_PROXY"] == jail.egress_proxy
        assert env["SSL_CERT_FILE"] == seat_jail.SEAT_EGRESS_CA
        assert "--unshare-net" not in jail.process_owner
    finally:
        seat_jail.close_jail_fds(jail)


def test_only_the_ca_certificate_enters_the_jail_never_its_key(tmp_path):
    """S4: the CA key is never mounted -- no bind source is the CA directory or its key."""
    jail = _gemini_jail(tmp_path)
    try:
        key_dir = str(seat_egress_proxy.ca_dir())
        for _kind, source, _target in _binds(list(jail.process_owner)):
            assert not source.startswith(key_dir) and not source.endswith(".key")
    finally:
        seat_jail.close_jail_fds(jail)


def test_per_launch_egress_values_do_not_move_the_qualified_digest(tmp_path):
    one = _gemini_jail(tmp_path / "a", proxy="http://srt:aaaa@127.0.0.1:3128")
    two = _gemini_jail(tmp_path / "b", proxy="http://srt:bbbb@127.0.0.1:3128")
    try:
        canonical = seat_jail.jail_profile_digest("gemini")
        assert one.profile_digest == two.profile_digest == canonical
        pi._require_canonical_jail(one)
        assert "http://srt:aaaa@127.0.0.1:3128" not in one.redacted_owner()
        assert "<egress-proxy>" in one.redacted_owner()
    finally:
        seat_jail.close_jail_fds(one)
        seat_jail.close_jail_fds(two)


def test_an_extra_writable_config_dir_is_not_the_qualified_profile(tmp_path):
    jail = _gemini_jail(tmp_path)
    owner = list(jail.process_owner)
    at = owner.index("--remount-ro")
    owner[at:at] = ["--bind", str(tmp_path), f"{seat_jail.SEAT_GEMINI_CONFIG}/brain"]
    try:
        with pytest.raises(seat_jail.SeatSandboxRefused):
            pi._require_canonical_jail(dataclasses.replace(jail, process_owner=tuple(owner)))
    finally:
        seat_jail.close_jail_fds(jail)


def test_the_gemini_mount_set_is_declared(tmp_path):
    jail = _gemini_jail(tmp_path)
    try:
        points = seat_jail.expected_mount_points(jail)
        for point in (seat_jail.SEAT_GEMINI_DOTDIR, seat_jail.SEAT_EGRESS_CA,
                      *(f"{seat_jail.SEAT_GEMINI_CONFIG}/{n}" for n in ("bin", "cache", "log"))):
            assert point in points
        assert seat_jail.SEAT_GEMINI_CONFIG not in points  # inside the ro-bind, not its own mount
    finally:
        seat_jail.close_jail_fds(jail)


def test_a_gemini_jail_without_its_egress_is_not_built(tmp_path):
    review = tmp_path / "seat"
    (review / seat_jail.HOST_TREE_DIRNAME).mkdir(parents=True)
    with pytest.raises(seat_jail.SeatSandboxRefused):
        seat_jail.build_seat_jail(
            "gemini", review, Path("/usr/bin/true"),
            bundle_memfd=seat_jail.memfd_with("b", b"B"),
            instructions_memfd=seat_jail.memfd_with("i", b"I"), seat_ids=(3, 3))


def test_the_claude_jail_carries_none_of_the_gemini_egress(tmp_path):
    review = tmp_path / "review"
    (review / seat_jail.HOST_TREE_DIRNAME).mkdir(parents=True)
    jail = seat_jail.build_seat_jail(
        "claude", review, Path("/usr/bin/true"), bundle_memfd=seat_jail.memfd_with("b", b"B"),
        instructions_memfd=seat_jail.memfd_with("i", b"I"),
        token_fd=seat_jail.token_pipe(b"tok"), seat_ids=(3, 3))
    try:
        owner = " ".join(jail.process_owner)
        assert "HTTPS_PROXY" not in owner and seat_jail.SEAT_EGRESS_CA not in owner
        assert seat_jail.SEAT_GEMINI_CONFIG not in owner
    finally:
        seat_jail.close_jail_fds(jail)


# --------------------------------------------------------------------------------------
# The proxy-only namespace.
# --------------------------------------------------------------------------------------

def test_the_proxy_only_rules_admit_one_loopback_port_and_nothing_else():
    rules = sandbox_egress.proxy_only_rules(3128)
    accepts = [rule for rule in rules if rule.endswith("-j ACCEPT")]
    assert accepts == [
        "-A OUTPUT -o lo -s 127.0.0.1 -d 127.0.0.1 -p tcp --dport 3128 -j ACCEPT",
        "-A OUTPUT -o lo -s 127.0.0.1 -d 127.0.0.1 -p tcp --sport 3128 -j ACCEPT",
    ]
    assert rules[-2:] == ["-A OUTPUT -j REJECT", "-P OUTPUT DROP"]


def test_a_proxy_only_namespace_is_only_a_jailed_seat_namespace():
    with pytest.raises(ValueError):
        with sandbox_egress.isolated_network(proxy_socket="/tmp/x.sock"):
            pass


# --------------------------------------------------------------------------------------
# The pinned egress layer.
# --------------------------------------------------------------------------------------

def test_the_allowlist_is_the_measured_request_set():
    rules = seat_egress_proxy.allowlist()["allow"]
    assert rules == [
        {"host": "daily-cloudcode-pa.googleapis.com", "port": 443, "method": "POST",
         "path_prefix": "/v1internal:"},
        {"host": "www.googleapis.com", "port": 443, "method": "GET", "path": "/oauth2/v2/userinfo"},
        {"host": "lh3.googleusercontent.com", "port": 443, "method": "GET", "path_prefix": "/a/"},
    ]
    for rule in rules:
        assert "*" not in rule["host"]


def test_the_shipped_lockfile_pins_srt_by_version_and_integrity():
    lock = json.loads(seat_egress_proxy._data_path("package-lock.json").read_text())
    entry = lock["packages"]["node_modules/@anthropic-ai/sandbox-runtime"]
    assert entry["version"] == seat_egress_proxy.SRT_VERSION
    assert entry["integrity"] == seat_egress_proxy.SRT_INTEGRITY
    assert all(e.get("integrity", "").startswith("sha512-")
               for name, e in lock["packages"].items() if name)


def _fake_install(root: Path) -> Path:
    modules = root / "node_modules"
    package = modules / "@anthropic-ai" / "sandbox-runtime"
    (package / "dist").mkdir(parents=True)
    (package / "package.json").write_text(json.dumps({"version": seat_egress_proxy.SRT_VERSION}))
    (package / "dist" / "index.js").write_text("export const SandboxManager = {};\n")
    shipped = json.loads(seat_egress_proxy._data_path("package-lock.json").read_text())
    (modules / ".package-lock.json").write_text(json.dumps(shipped))
    return modules


def test_verify_install_accepts_the_pinned_tree_and_refuses_a_changed_file(tmp_path, monkeypatch):
    modules = _fake_install(tmp_path)
    monkeypatch.setattr(seat_egress_proxy, "SRT_TREE_SHA256", seat_egress_proxy.tree_sha256(modules))
    assert seat_egress_proxy.verify_install(tmp_path).name == "index.js"
    (modules / "@anthropic-ai" / "sandbox-runtime" / "dist" / "index.js").write_text("changed\n")
    with pytest.raises(seat_egress_proxy.EgressLayerUnavailable, match="changed after install"):
        seat_egress_proxy.verify_install(tmp_path)


def test_verify_install_rejects_a_symlink_shadow_outside_bin(tmp_path, monkeypatch):
    """F007: the digest skips symlinks and os.walk does not descend them, so a dependency
    link would change what Node loads while the digest stayed the same. verify_install
    rejects any symlink outside .bin before trusting the digest."""
    modules = _fake_install(tmp_path)
    monkeypatch.setattr(seat_egress_proxy, "SRT_TREE_SHA256", seat_egress_proxy.tree_sha256(modules))
    # A .bin link is the clean-tree shape and is accepted.
    (modules / ".bin").mkdir()
    (modules / ".bin" / "srt").symlink_to("../@anthropic-ai/sandbox-runtime/dist/cli.js")
    assert seat_egress_proxy.verify_install(tmp_path).name == "index.js"
    # A link anywhere else redirects resolution without changing the digest: refused.
    shadow = tmp_path / "evil"
    shadow.mkdir()
    (modules / "@anthropic-ai" / "sandbox-runtime" / "node_modules").symlink_to(shadow)
    with pytest.raises(seat_egress_proxy.EgressLayerUnavailable, match="unexpected symlink"):
        seat_egress_proxy.verify_install(tmp_path)


def test_verify_install_refuses_another_version_or_integrity(tmp_path, monkeypatch):
    modules = _fake_install(tmp_path)
    monkeypatch.setattr(seat_egress_proxy, "SRT_TREE_SHA256", seat_egress_proxy.tree_sha256(modules))
    recorded = json.loads((modules / ".package-lock.json").read_text())
    recorded["packages"]["node_modules/@anthropic-ai/sandbox-runtime"]["integrity"] = "sha512-other"
    (modules / ".package-lock.json").write_text(json.dumps(recorded))
    with pytest.raises(seat_egress_proxy.EgressLayerUnavailable, match="pinned"):
        seat_egress_proxy.verify_install(tmp_path)
    with pytest.raises(seat_egress_proxy.EgressLayerUnavailable, match="not installed"):
        seat_egress_proxy.verify_install(tmp_path / "absent")


@pytest.mark.parametrize("directory_mode,key_mode,problem", [
    (0o700, 0o600, None), (0o750, 0o600, "not 0700"), (0o700, 0o640, "not 0600")])
def test_the_ca_must_be_owner_only(tmp_path, monkeypatch, directory_mode, key_mode, problem):
    directory = tmp_path / "seat-egress-ca"
    directory.mkdir()
    (directory / "ca.crt").write_text("cert")
    (directory / "ca.key").write_text("key")
    (directory / "ca.crt").chmod(0o644)
    directory.chmod(directory_mode)
    (directory / "ca.key").chmod(key_mode)
    monkeypatch.setattr(seat_egress_proxy, "ca_dir", lambda: directory)
    if problem is None:
        assert seat_egress_proxy.ensure_ca(Path("/unused"), "/unused") == (
            directory / "ca.crt", directory / "ca.key")
    else:
        with pytest.raises(seat_egress_proxy.EgressLayerUnavailable, match=problem):
            seat_egress_proxy.ensure_ca(Path("/unused"), "/unused")


def test_the_proxy_environment_carries_nothing_of_the_operators(monkeypatch):
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/secret")
    monkeypatch.setenv("HTTPS_PROXY", "http://elsewhere")
    env = seat_egress_proxy._proxy_env("/usr/bin/node", Path("/w"))
    assert set(env) == {"PATH", "LANG", "HOME"}


def test_the_proxy_script_checks_the_inner_host_and_refuses_other_requests():
    script = seat_egress_proxy._data_path("proxy.mjs").read_text()
    assert "tlsTerminate" in script and "filterRequest" in script
    assert "the inner Host does not name the tunnel host" in script
    assert "the inner SNI is not on the seat allowlist" in script


def test_the_proxy_script_has_a_fail_closed_front():
    """grok-A: the front forwards to srt only a positively-inspected ClientHello whose SNI
    is allowed, so srt never takes its opaque-tunnel fallback for a non-TLS first flight."""
    script = seat_egress_proxy._data_path("proxy.mjs").read_text()
    assert "clientHelloSNI" in script and "fail_closed_front" in script
    # the refusal of anything not positively a ClientHello is a destroy, not a forward
    assert "no bytes upstream" in script.lower() or "no positively-inspected" in script.lower()


# --------------------------------------------------------------------------------------
# The tooled stream and the jailed argv.
# --------------------------------------------------------------------------------------

def test_the_jailed_argv_makes_no_workspace_of_the_tree():
    argv = pi._jailed_gemini_command("gemini-3.8-flash-medium")
    assert argv[:2] == ["/usr/bin/env", f"--chdir={seat_jail.SEAT_GEMINI_WORKSPACE}"]
    assert argv[2] == "/seat/bin/gemini"
    assert "--add-dir" not in argv and "--sandbox" not in argv and "--mode" not in argv
    assert "--dangerously-skip-permissions" in argv
    assert argv[argv.index("--print-timeout") + 1] == "0"


def _events(*steps, result="Review.\nAGREE"):
    lines = [{"event": "init", "conversation_id": "c"}]
    lines += [{"event": "step_update", "step_update": {"conversation_id": "c", **step}}
              for step in steps]
    lines.append({"event": "result", "result": {"conversation_id": "c", "status": "SUCCESS",
                                                 "response": result}})
    return "\n".join(json.dumps(line) for line in lines) + "\n"


def test_the_tooled_stream_accepts_tool_steps():
    protocol = pi._broker_gemini_stream_protocol("prompt", tooled=True)
    raw = _events({"step_type": "tool", "tool_name": "run_command", "tool_info": {}},
                  {"step_type": "agent_response", "text_delta": "x"})
    rc, text, detail, _ = pi._broker_gemini_stream_result(raw, protocol, tooled=True)
    assert (rc, text, detail) == (0, "Review.\nAGREE", "")


@pytest.mark.parametrize("step", [
    {"step_type": "subagent", "tool_name": "invoke_subagent", "subagent_info": {}},
    {"step_type": "agent_response", "subagent_info": {}},
    {"step_type": "browser"},
])
def test_a_subagent_or_unrecorded_step_ends_the_tooled_leg(step):
    protocol = pi._broker_gemini_stream_protocol("prompt", tooled=True)
    rc, text, detail, _ = pi._broker_gemini_stream_result(_events(step), protocol, tooled=True)
    assert (rc, text, detail) == (1, "", "gemini_seat_subagent_or_unknown_event")


def test_the_sealed_stream_still_rejects_every_tool_step():
    protocol = pi._broker_gemini_stream_protocol("prompt")
    raw = _events({"step_type": "tool", "tool_info": {}})
    rc, _text, detail, _ = pi._broker_gemini_stream_result(raw, protocol)
    assert rc == 1 and detail == "Gemini broker stream rejected: tool or subagent activity observed"


def test_the_tooled_final_turn_asks_for_tools_and_the_sealed_one_forbids_them():
    tooled = pi._broker_gemini_stream_protocol("prompt", tooled=True).transport
    sealed = pi._broker_gemini_stream_protocol("prompt").transport
    assert "Review with your tools" in tooled and "Do not use or request tools" not in tooled
    assert "Do not use or request tools" in sealed


def test_the_gemini_pointer_preamble_promises_no_internet_and_claudes_is_unchanged():
    gemini = pi._broker_review_jail_preamble(model_only_network=True)
    assert "no network beyond your own model" in gemini and "PUBLIC internet" not in gemini
    assert "PUBLIC internet" in pi._broker_review_jail_preamble()


# --------------------------------------------------------------------------------------
# The jailed leg: the token never leaves, typed outcomes.
# --------------------------------------------------------------------------------------

_PROXY_TOKEN = "b7c0f2e1a9d34e5f8c1b2a3d4e5f6071"


def _seat(tmp_path, token=b"ya29.secret-access-token-value"):
    jail = types.SimpleNamespace(
        env={"HTTPS_PROXY": f"http://srt:{_PROXY_TOKEN}@127.0.0.1:3128"},
        profile_digest="d", profile_id="p", filter_digest="f",
        redacted_owner=lambda: [], pass_fds=())
    return pi._JailedSeat(jail=jail, probe_jail=jail, holder_pid=1, token=token,
                          review_dir=tmp_path, seat_dir=tmp_path, expires_at=None)


def _run_with(monkeypatch, chunks, returncode=0):
    stopped = []

    def fake(cmd, **kw):
        out = b""
        for chunk in chunks:
            out += chunk
            if kw["stdout_guard"](chunk):
                stopped.append(len(out))   # the liveness loop ends the provider here
                break
        return types.SimpleNamespace(returncode=returncode, stdout=out.decode(), stderr="")
    monkeypatch.setattr(pi, "_run_leg_with_liveness", fake)
    monkeypatch.setattr(seat_jail, "close_jail_fds", lambda jail: None)
    monkeypatch.setattr(pi._seat_uid, "teardown_in_h", lambda pid, parent: [])
    return stopped


def test_a_token_split_across_chunks_is_caught_before_it_is_kept(monkeypatch, tmp_path):
    seat = _seat(tmp_path)
    leak = json.dumps({"event": "init", "x": seat.token.decode()}).encode()
    middle = leak.index(b"secret")
    stopped = _run_with(monkeypatch, [leak[:middle], leak[middle:], b"more output\n"])
    sink = []
    status, text = pi._exec_jailed_gemini_leg(seat, deadline_s=60, model="m", prompt="p",
                                              broker_evidence={}, failure_detail_sink=sink)
    assert (status, text) == ("DEGRADED", "") and sink[-1].template == "gemini_seat_token_in_output"
    # The guard stopped the provider at the chunk that completed the token.
    assert stopped == [len(leak)]


def test_a_tooled_review_is_returned(monkeypatch, tmp_path):
    seat = _seat(tmp_path)
    _run_with(monkeypatch, [_events({"step_type": "tool", "tool_info": {}}).encode()])
    evidence = {}
    status, text = pi._exec_jailed_gemini_leg(
        seat, deadline_s=60, model="m", prompt="p", broker_evidence=evidence,
        egress_evidence={"tls_inspection": True})
    assert status == "OK" and text.endswith("AGREE")
    assert evidence["egress"] == {"tls_inspection": True}
    assert evidence["sandbox_filesystem_confined"] is True
    assert evidence["provider_cwd_class"] == "seat_jail_empty_workspace"
    assert _PROXY_TOKEN not in json.dumps(evidence, default=str)


def test_the_proxy_session_token_in_the_output_ends_the_leg(monkeypatch, tmp_path):
    """F008: the proxy's session credential reaches the seat in HTTPS_PROXY; if it appears in
    the returned review it is a leak, scanned like the model bearer."""
    seat = _seat(tmp_path)
    leak = json.dumps({"event": "init", "note": f"proxy={_PROXY_TOKEN}"}).encode()
    stopped = _run_with(monkeypatch, [leak, b"more\n"])
    sink = []
    status, text = pi._exec_jailed_gemini_leg(seat, deadline_s=60, model="m", prompt="p",
                                              broker_evidence={}, failure_detail_sink=sink)
    assert (status, text) == ("DEGRADED", "") and sink[-1].template == "gemini_seat_token_in_output"
    assert stopped == [len(leak)]


def test_both_seat_secrets_are_scanned(tmp_path):
    seat = _seat(tmp_path)
    secrets = pi._jailed_gemini_secrets(seat)
    assert seat.token in secrets and _PROXY_TOKEN.encode() in secrets


def test_an_expired_copy_ends_the_leg_typed(monkeypatch, tmp_path):
    seat = dataclasses.replace(_seat(tmp_path), expires_at=1.0)
    _run_with(monkeypatch, [b'{"event":"result","result":{"status":"ERROR"}}\n'], returncode=1)
    sink = []
    pi._exec_jailed_gemini_leg(seat, deadline_s=60, model="m", prompt="p", broker_evidence={},
                               failure_detail_sink=sink)
    assert sink[-1].template == "gemini_seat_token_expired"


def test_the_egress_evidence_records_tls_inspection():
    proxy = seat_egress_proxy.SeatEgressProxy(
        socket="/s", proxy_url="http://srt:t@127.0.0.1:3128", ca_cert=Path("/c"),
        ca_sha256="ab", inner_sni_check=True, process=None)
    evidence = seat_egress_proxy.egress_evidence(proxy)
    assert evidence["tls_inspection"] is True and evidence["inner_host_check"] is True
    assert evidence["proxy"]["integrity"] == seat_egress_proxy.SRT_INTEGRITY
    assert "http://srt:t@" not in json.dumps(evidence)


# --------------------------------------------------------------------------------------
# Live: the containment rows, through the real proxy (a host with the layer installed).
# --------------------------------------------------------------------------------------

def _layer_or_skip():
    reason = seat_egress_proxy.unavailable_reason()
    if reason is not None or shutil.which("curl") is None or shutil.which("socat") is None:
        pytest.skip(f"the seat egress layer is not installed here ({reason})")


@pytest.mark.parametrize("url,extra,method,refused", [
    ("https://storage.googleapis.com/", (), None, True),
    ("https://iam.googleapis.com/", (), None, True),
    ("https://www.googleapis.com/storage/v1/b", (), None, True),
    ("https://www.googleapis.com/compute/v1/projects", (), None, True),
    ("https://daily-cloudcode-pa.googleapis.com/v1internal:loadCodeAssist",
     ("-H", "Host: storage.googleapis.com"), "POST", True),
    ("https://daily-cloudcode-pa.googleapis.com/v1internal:loadCodeAssist",
     ("--connect-to", "storage.googleapis.com:443:daily-cloudcode-pa.googleapis.com:443"), "POST",
     True),
    ("https://daily-cloudcode-pa.googleapis.com/v1internal:loadCodeAssist", (), "POST", False),
])
def test_live_proxy_containment_rows(url, extra, method, refused):
    """Through the real proxy, with real replies: only the allowed request reaches its host.
    The tunnelling rows (Host, or SNI with Host, naming storage inside a tunnel to the
    inference host) are REFUSED, not redirected."""
    _layer_or_skip()
    import socket

    if "--connect-to" in extra:
        url = url.replace("daily-cloudcode-pa.googleapis.com", "storage.googleapis.com")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with seat_egress_proxy.start_proxy() as proxy:
        bridge = subprocess.Popen(["socat", f"TCP4-LISTEN:{port},bind=127.0.0.1,fork,reuseaddr",
                                   f"UNIX-CONNECT:{proxy.socket}"])
        try:
            done = subprocess.run(
                ["curl", "-sS", "-o", "/dev/null", "--max-time", "20", "-w", "%{http_code}",
                 "--retry", "3", "--retry-connrefused", "--cacert", str(proxy.ca_cert),
                 "-x", proxy.proxy_url.replace(f":{seat_egress_proxy.SEAT_PROXY_PORT}", f":{port}"),
                 *(["-X", method] if method else []), *extra, url],
                capture_output=True, text=True, env={"PATH": os.environ["PATH"]})
        finally:
            bridge.terminate()
            bridge.wait(5)
    code = done.stdout.strip()
    if refused:
        assert code == "403" or "403" in done.stderr or (
            code == "000" and "SSL" in done.stderr), (code, done.stderr[-200:])
    else:
        assert code not in ("000", "403"), (code, done.stderr[-200:])


def _client_hello(sni: bytes, rec_ver_lo: int = 0x03) -> bytes:
    """A minimal TLS ClientHello record. ``rec_ver_lo`` sets the record-layer version low
    byte: 0x04 is the president's attack value (srt classifies it non-TLS and opaque-tunnels)."""
    ext = b"\x00\x00" + (len(sni) + 5).to_bytes(2, "big") + (len(sni) + 3).to_bytes(2, "big") \
        + b"\x00" + len(sni).to_bytes(2, "big") + sni
    body = b"\x03\x03" + b"\x00" * 32 + b"\x00" + b"\x00\x02\x13\x01" + b"\x01\x00" \
        + len(ext).to_bytes(2, "big") + ext
    hs = b"\x01" + len(body).to_bytes(3, "big") + body
    return b"\x16\x03" + bytes([rec_ver_lo]) + len(hs).to_bytes(2, "big") + hs


@pytest.mark.parametrize("label,sni,rec_ver_lo", [
    ("opaque-tunnel attack: 0x04 record version, SNI storage", b"storage.googleapis.com", 0x04),
    ("standard ClientHello, SNI storage (disallowed)", b"storage.googleapis.com", 0x03),
    # Shape (b): the SNI is ALLOWED, so only the front's record-version check keeps this first
    # flight off srt's opaque path (srt would tunnel a 0x04 record to the upstream uninspected).
    ("opaque-tunnel attack: 0x04 record version, ALLOWED SNI", b"daily-cloudcode-pa.googleapis.com",
     0x04),
], ids=["0x04-record-sni-storage", "standard-hello-sni-storage", "0x04-record-allowed-sni"])
def test_live_fail_closed_front_lets_no_bytes_reach_a_non_allowlisted_service(label, sni, rec_ver_lo):
    """grok-A: a CONNECT to the allowed host followed by a first flight that is either not a
    standard ClientHello (0x04 record version) or names a non-allowlisted SNI reaches NO
    service: the fail-closed front forwards nothing to srt, so srt never opaque-tunnels it."""
    _layer_or_skip()
    import base64
    import socket

    allowed = b"daily-cloudcode-pa.googleapis.com"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with seat_egress_proxy.start_proxy() as proxy:
        token = proxy.proxy_url.split("srt:")[1].split("@")[0]
        auth = base64.b64encode(f"srt:{token}".encode()).decode()
        bridge = subprocess.Popen(["socat", f"TCP4-LISTEN:{port},bind=127.0.0.1,fork,reuseaddr",
                                   f"UNIX-CONNECT:{proxy.socket}"])
        try:
            time.sleep(0.5)
            s = socket.create_connection(("127.0.0.1", port), 5)
            s.settimeout(8)
            s.sendall(b"CONNECT " + allowed + b":443 HTTP/1.1\r\nHost: " + allowed
                      + b":443\r\nProxy-Authorization: Basic " + auth.encode() + b"\r\n\r\n")
            assert b"200" in s.recv(128)
            s.sendall(_client_hello(sni, rec_ver_lo))
            try:
                reply = s.recv(4096)
            except (TimeoutError, ConnectionResetError, OSError):
                reply = b""
            s.close()
        finally:
            bridge.terminate()
            bridge.wait(5)
    # No ServerHello, no application bytes: nothing reached an upstream service.
    assert reply == b"", (label, reply[:64])


# --------------------------------------------------------------------------------------
# The agy self-qualification measures the SEALED heartbeat route: its own seat is never jailed.
# --------------------------------------------------------------------------------------

def _capable_spawn_route(monkeypatch, leg):
    monkeypatch.setattr(seat_jail, "decide_seat_route", _REAL_DECIDE)
    monkeypatch.setattr(seat_jail, "seat_sandbox_capable", lambda **kw: None)
    monkeypatch.setattr(seat_jail, "_gemini_egress_unavailable", lambda: None)
    monkeypatch.setattr(seat_jail, "gemini_operator_credential_present", lambda path=None: True)
    return pi._seat_route_for_spawn(
        leg, types.SimpleNamespace(staged_tree_sha256="a" * 64), eligible=True,
        decide=lambda leg, **kw: _REAL_DECIDE(
            leg, capable=lambda: None, gemini_egress_unavailable=lambda: None,
            gemini_credential_present=lambda: True, claude_token_present=lambda: True, **kw),
        qualify_on_first_use=lambda leg: types.SimpleNamespace(qualified=True, reason=None))


def test_outside_a_qualification_a_capable_host_jails_the_gemini_seat(monkeypatch):
    from phase_loop_runtime import gemini_heartbeat

    monkeypatch.setattr(gemini_heartbeat, "_CANDIDATE", None)
    route, _notices, refusal = _capable_spawn_route(monkeypatch, "gemini")
    assert route == seat_jail.SeatRoute(True) and refusal is None


def test_the_agy_qualification_worker_keeps_its_gemini_seat_on_the_heartbeat_route(monkeypatch):
    """The qualification worker sets ``gemini_heartbeat._CANDIDATE`` and runs a one-seat
    Gemini board to measure the heartbeat route's admission and quiescence. That seat must
    take the heartbeat route it is qualifying, never the jail (a jailed seat has no heartbeat
    admission to observe, so the qualification could never pass)."""
    from phase_loop_runtime import gemini_heartbeat

    monkeypatch.setattr(gemini_heartbeat, "_CANDIDATE", object())
    # On a host that could jail it, the worker's leg keeps the heartbeat route with its own
    # code (the one candidate seam shared with agent-harness#1244): never jailed, never refused.
    code = "gemini_seat_qualification_candidate"
    assert _capable_spawn_route(monkeypatch, "gemini") == (
        seat_jail.SeatRoute(False, code), [code], None)
    # A Claude seat in the same process is unaffected.
    route, _notices, refusal = _capable_spawn_route(monkeypatch, "claude")
    assert route == seat_jail.SeatRoute(True) and refusal is None
