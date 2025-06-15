"""Offline orchestration and non-root EOF startup; never load policy or prove enforcement."""

from __future__ import annotations

import ctypes
import errno
import io
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

import codex_apparmor_canary as aa


NS = "phase_loop_codex_canary_" + "a" * 32
UID, GID = 1000, 1001


def dropped():
    return {"Uid": " ".join([str(UID)] * 4), "Gid": " ".join([str(GID)] * 4),
            "Groups": "", "NoNewPrivs": "1", **{k: "0000000000000000" for k in aa.CAPS}}


def gate():
    host = {k: k + ":[1]" for k in ("user", "mnt", "pid", "net", "ipc", "uts")}
    return {"pid": 45, "start": 123, "status": dropped(),
            "label": f":{NS}:bwrap//&unpriv_bwrap (enforce)",
            "namespaces": {k: k + ":[2]" for k in host}, "host_namespaces": host,
            "user_parent": host["user"], "user_owner": UID,
            "uid_map": [[UID, UID, 1]], "gid_map": [[GID, GID, 1]],
            "fds": {"0": "gate", "1": "status", "2": "status"},
            "mounts": [{"path": "/", "fs": "tmpfs", "options": ["rw"], "propagation": []},
                       {"path": "/fixture.txt", "fs": "ext4", "dev": "8:1", "root": "/fixture.txt",
                        "options": ["ro"], "propagation": []}]}


BINDS = {"/fixture.txt": ("8:1", "/fixture.txt")}


def arm(result=-errno.EPERM, audit=True):
    observation = gate()
    request = {"pid": 45, "start": 123, "syscall": "unshare", "flags": 0x10020000,
               "return": result, "monotonic_ns": 200, "realtime_ns": 1000000000, "exit_realtime_ns": 1001000000}
    denial = {"pid": 45, "start": 123, "capability": 21, "operation": "capable",
              "label": observation["label"], "monotonic_ns": 210, "realtime_ns": 1000500000, "boot_id": "boot"}
    return {"gate": observation, "trace": [request], "audit": [denial] if audit else [],
            "finish": {"monotonic_ns": 300}, "boot_id": "boot", "exit_codes": {45: 1}}


def policy_tree(tmp_path):
    tmp_path = tmp_path / "inputs"
    tmp_path.mkdir()
    source = Path(aa.__file__).resolve().parents[2] / "plans/evidence/codex-apparmor-canary"
    for name in aa.POLICY_HASHES:
        (tmp_path / name).write_bytes((source / name).read_bytes())
    (tmp_path / "parser.conf").write_bytes(b"")
    (tmp_path / "features.dump").write_bytes(b"features { yes }\n")
    (tmp_path / "fixture.txt").write_bytes(b"fixture\n")
    (tmp_path / "codex_apparmor_canary.py").write_bytes(b"helper\n")
    (tmp_path / "manifest.json").write_text("{}")
    return tmp_path


def experiment(tmp_path):
    root = policy_tree(tmp_path)
    experiment = aa.Experiment(root, tmp_path / "evidence", UID, GID)
    experiment.namespace.name = NS
    return experiment


def test_exact_reviewed_single_rule_and_closed_profiles(tmp_path):
    root = policy_tree(tmp_path)
    aa.policy_check(root)
    baseline = (root / "baseline.policy").read_bytes()
    candidate = (root / "candidate.policy").read_bytes()
    assert baseline.replace(b"audit deny capability,", b"allow capability sys_admin,") == candidate
    assert baseline.count(b"audit deny capability,") == 1
    assert candidate.count(b"allow capability sys_admin,") == 1


@pytest.mark.parametrize("directive", [b"include <x>\n", b"#include <x>\n", b"include if exists <x>\n",
                                        b"abi <abi/5.0>,\n", b"@{HOME}=/home\n"])
def test_reject_open_inputs_before_parser(tmp_path, directive):
    root = policy_tree(tmp_path)
    (root / "baseline.policy").write_bytes(directive)
    with pytest.raises(aa.Inconclusive, match="open policy input"):
        aa.policy_check(root)


@pytest.mark.parametrize("name", ["baseline.policy", "candidate.policy", "parser.conf"])
def test_policy_or_config_edits_are_not_silently_accepted(tmp_path, name):
    root = policy_tree(tmp_path)
    with (root / name).open("ab") as stream:
        stream.write(b"# changed\n")
    with pytest.raises(aa.Inconclusive):
        aa.policy_check(root)


@pytest.mark.parametrize("operation", ["load", "remove", "compile", "preprocess"])
def test_parser_commands_bind_closed_inputs_and_namespace(tmp_path, operation):
    argv = aa.parser_argv(tmp_path, "baseline.policy", operation, NS if operation in ("load", "remove") else None)
    assert "-K" in argv and "--write-cache" not in argv
    for option, target in (("--config-file", tmp_path / "parser.conf"), ("--base", tmp_path),
                           ("--Include", tmp_path), ("--policy-features", tmp_path / "features.dump")):
        assert argv[argv.index(option) + 1] == str(target)
    if operation in ("load", "remove"):
        assert argv[argv.index("--namespace") + 1] == NS
    else:
        assert "--namespace" not in argv


@pytest.mark.parametrize("namespace", [None, "", "root", "other", NS + "/other", ":" + NS])
@pytest.mark.parametrize("operation", ["load", "remove"])
def test_no_load_or_remove_can_target_root_or_foreign_namespace(tmp_path, namespace, operation):
    with pytest.raises(aa.Inconclusive, match="namespace"):
        aa.parser_argv(tmp_path, "baseline.policy", operation, namespace)


def fake_root_stat(monkeypatch):
    original = Path.lstat

    def observed(path):
        info = original(path)
        return SimpleNamespace(st_uid=0, st_mode=info.st_mode, st_nlink=info.st_nlink)

    monkeypatch.setattr(Path, "lstat", observed)


def test_protected_staging_refuses_links_and_writable_ancestors(tmp_path, monkeypatch):
    # Root identity is synthetic here; real filesystem links and modes remain observed.
    fake_root_stat(monkeypatch)
    file = tmp_path / "helper"
    file.write_text("helper")
    link = tmp_path / "symbolic"
    link.symlink_to(file)
    with pytest.raises(aa.Inconclusive, match="noncanonical"):
        aa.protected(link)
    hard = tmp_path / "hard"
    os.link(file, hard)
    with pytest.raises(aa.Inconclusive, match="single-link"):
        aa.protected(file)
    hard.unlink()
    tmp_path.chmod(0o777)
    with pytest.raises(aa.Inconclusive, match="ancestry"):
        aa.protected(file)


def test_unprivileged_staging_is_refused(tmp_path):
    if os.getuid() == 0:
        pytest.skip("negative non-root ownership control")
    file = tmp_path / "helper"
    file.write_text("helper")
    with pytest.raises(aa.Inconclusive, match="ancestry"):
        aa.protected(file)


def test_executable_setid_and_file_capabilities_refused(tmp_path, monkeypatch):
    target = tmp_path / "program"
    target.write_bytes(b"test")
    target.chmod(0o4755)
    with pytest.raises(aa.Inconclusive, match="privileged"):
        aa.executable(target)
    target.chmod(0o755)
    original = Path.stat
    monkeypatch.setattr(Path, "stat", lambda self, **kw: SimpleNamespace(
        st_uid=0, st_mode=original(self, **kw).st_mode))
    monkeypatch.setattr(aa.os, "getxattr", lambda *a: b"capability")
    with pytest.raises(aa.Inconclusive, match="file capabilities"):
        aa.executable(target)


def test_feature_and_closure_changes_abort_before_load(tmp_path, monkeypatch):
    root = policy_tree(tmp_path)
    inputs = aa.closure(root)
    help_text = b"Do not attempt to load or save cached profiles"
    manifest = {"inputs": inputs, "boot_id": aa.boot_id(), "kernel": aa.platform.release(),
                "tools": {}, "fixture": {}, "parser_help_sha256": aa.digest(help_text)}
    monkeypatch.setattr(aa, "protected", lambda *a, **k: None)
    monkeypatch.setattr(aa, "tools", lambda **kw: {})
    monkeypatch.setattr(aa, "fixture_inputs", lambda **kw: {})
    monkeypatch.setattr(aa, "bounded", lambda argv, **kw: help_text if argv[0] == aa.PARSER else b"new features")
    with pytest.raises(aa.Inconclusive, match="kernel features changed"):
        aa.validate_inputs(root, manifest)
    (root / "fixture.txt").write_text("mutated")
    with pytest.raises(aa.Inconclusive, match="closure changed"):
        aa.validate_inputs(root, manifest)
    (root / "extra").write_text("unexpected include")
    with pytest.raises(aa.Inconclusive, match="inventory changed"):
        aa.validate_inputs(root, manifest)


def test_close_fds_actually_closes_inherited_nonstdio(tmp_path):
    # The subprocess runs only close_fds; no policy, identity or namespace operation.
    with (tmp_path / "root-file-substitute").open("w") as stream:
        fd = stream.fileno()
        code = ("import sys; sys.path.insert(0," + repr(str(Path(aa.__file__).parent)) + "); "
                "import codex_apparmor_canary as aa; aa.close_fds(); "
                "import os; os.fstat(" + str(fd) + ")")
        result = subprocess.run([sys.executable, "-c", code], pass_fds=(fd,), capture_output=True, timeout=5)
    assert result.returncode != 0 and b"Bad file descriptor" in result.stderr


def test_drop_orders_restriction_bounding_groups_ids_zeroing_and_nnp(monkeypatch):
    calls = []
    class Libc:
        def capset(self, header, data):
            calls.append(("capset", list(data)))
            return 0

        def prctl(self, *args):
            calls.append(("prctl", args))
            return 0

    monkeypatch.setattr(aa, "LIBC", Libc())
    monkeypatch.setattr(aa, "close_fds", lambda: calls.append(("close",)))
    monkeypatch.setattr(aa, "prctl", lambda *args: calls.append(("prctl", args)))
    monkeypatch.setattr(aa.os, "setgroups", lambda x: calls.append(("groups", x)))
    monkeypatch.setattr(aa.os, "setresgid", lambda *x: calls.append(("gid", x)))
    monkeypatch.setattr(aa.os, "setresuid", lambda *x: calls.append(("uid", x)))
    monkeypatch.setattr(aa, "status", lambda _: dropped())
    aa.drop_identity(UID, GID)
    assert calls[0] == ("close",) and calls[-1] == ("close",)
    assert calls[1] == ("capset", [0x1c0, 0x1c0, 0, 0, 0, 0])
    assert ("groups", []) in calls and ("uid", (UID,) * 3) in calls
    group_index = calls.index(("groups", []))
    assert sum(c[0] == "prctl" and c[1][0] == 24 for c in calls[:group_index]) == int(Path("/proc/sys/kernel/cap_last_cap").read_text()) + 1
    assert calls.index(("capset", [0] * 6)) > calls.index(("uid", (UID,) * 3))
    assert ("prctl", (38, 1)) in calls


@pytest.mark.parametrize("uid,gid", [(0, GID), (UID, 0), (-1, GID)])
def test_root_operator_rejected_before_drop(monkeypatch, uid, gid):
    monkeypatch.setattr(aa, "close_fds", lambda: pytest.fail("drop started"))
    with pytest.raises(aa.Inconclusive, match="root identity"):
        aa.drop_identity(uid, gid)


GATE_MUTATIONS = [
    ("status", "CapEff", "1"), ("status", "CapPrm", "1"), ("status", "CapBnd", "1"),
    ("status", "CapInh", "1"), ("status", "CapAmb", "1"), ("status", "NoNewPrivs", "0"),
    ("status", "Uid", "0 0 0 0"), ("status", "Gid", "0 0 0 0"), ("status", "Groups", "4"),
    (None, "label", "bwrap//&unpriv_bwrap (enforce)"),
    (None, "label", f":{NS}:bwrap//&unpriv_bwrap//&extra (enforce)"),
    (None, "label", f":{NS}:bwrap//&unpriv_bwrap (complain)"),
    (None, "user_parent", "user:[foreign]"), (None, "user_owner", 0),
    (None, "uid_map", [[UID, 0, 1]]), (None, "gid_map", [[GID, 0, 1]]),
    ("fds", "3", "root-file"), ("fds", "0", "other-pipe"),
    ("namespaces", "user", "user:[1]"), ("namespaces", "mnt", "mnt:[1]"),
    ("namespaces", "pid", "pid:[1]"), ("namespaces", "net", "net:[1]"),
]


@pytest.mark.parametrize("mutation", GATE_MUTATIONS + ["mount_rw", "shared", "host_etc", "apparmorfs", "missing_bind"])
@pytest.mark.parametrize("name", ["baseline", "candidate"])
def test_each_arm_holds_go_until_all_independent_host_gates_pass(tmp_path, monkeypatch, mutation, name):
    ex = experiment(tmp_path)
    observation = gate()
    if mutation == "mount_rw":
        observation["mounts"][1]["options"] = ["rw"]
    elif mutation == "shared":
        observation["mounts"][0]["propagation"] = ["shared:1"]
    elif mutation in ("host_etc", "apparmorfs"):
        observation["mounts"].append({"path": "/etc" if mutation == "host_etc" else "/sys/kernel/security",
                                      "fs": "ext4", "options": ["ro"], "propagation": []})
    elif mutation == "missing_bind":
        observation["mounts"].pop()
    else:
        section, key, value = mutation
        (observation[section] if section else observation)[key] = value
    events = []
    class FakeObserver:
        exits = {}
        def __init__(self, *args, **kwargs):
            events.append("attached")
        def run(self, go):
            events.append("observer-run")
            go()
            return []
    monkeypatch.setattr(aa, "Observer", FakeObserver)
    monkeypatch.setattr(aa, "observe_gate", lambda *a: observation)
    pipe = io.BytesIO()
    ex.child = SimpleNamespace(stdin=pipe)
    record = {"go_sent": False}
    ex.result["arms"][name] = record
    with pytest.raises(aa.Inconclusive):
        ex.primary(SimpleNamespace(alive=lambda: True), BINDS, record)
    assert events == ["attached"] and pipe.getvalue() == b"" and not record["go_sent"]


def test_successful_gate_attaches_before_go_and_records_trace(tmp_path, monkeypatch):
    ex = experiment(tmp_path)
    events = []
    class FakeObserver:
        exits = {45: 1}
        def __init__(self, *a, **kw):
            events.append("attached")
        def run(self, go):
            events.append("observing")
            go()
            return arm()["trace"]
    monkeypatch.setattr(aa, "Observer", FakeObserver)
    monkeypatch.setattr(aa, "observe_gate", lambda *a: gate())
    ex.child = SimpleNamespace(stdin=io.BytesIO())
    record = {"go_sent": False}
    ex.primary(SimpleNamespace(alive=lambda: True), BINDS, record)
    assert record["trace"] == arm()["trace"] and record["go_sent"]
    assert ex.child.stdin.getvalue() == b"G" and events == ["attached", "observing"]


def test_positive_syscall_evidence_and_all_three_outcomes():
    assert aa.outcome(arm(), arm(result=0, audit=False)) == "hypothesis_supported"
    # A later command failure is independent of the successful namespace request.
    assert arm(result=0)["exit_codes"][45] == 1
    assert aa.outcome(arm(), arm()) == "hypothesis_refuted"
    assert aa.outcome(arm(), arm(audit=False)) == "inconclusive"
    silent = arm(audit=False)
    silent["trace"] = []
    assert aa.outcome(arm(), silent) == "inconclusive"
    assert aa.outcome(arm(audit=False), arm(result=0)) == "inconclusive"


@pytest.mark.parametrize("key,value", [("pid", 99), ("start", 999), ("capability", 7),
                                       ("label", "foreign"), ("monotonic_ns", 199),
                                       ("boot_id", "other-boot"), ("operation", "other")])
def test_denial_must_match_exact_task_label_boot_capability_and_interval(key, value):
    baseline = arm()
    baseline["audit"][0][key] = value
    assert not aa.attributed(baseline)
    assert aa.outcome(baseline, arm(result=0)) == "inconclusive"


@pytest.mark.parametrize("key,value", [("pid", 99), ("start", 999), ("flags", 0x10000000)])
def test_successful_other_task_or_other_syscall_does_not_support_hypothesis(key, value):
    candidate = arm(result=0, audit=False)
    candidate["trace"][0][key] = value
    assert aa.outcome(arm(), candidate) == "inconclusive"


def test_duplicate_primary_requests_are_inconclusive():
    candidate = arm(result=0)
    candidate["trace"] *= 2
    assert aa.outcome(arm(), candidate) == "inconclusive"


def test_pid_reuse_never_authorizes_signal(monkeypatch):
    identity = aa.Process.__new__(aa.Process)
    identity.pid, identity.start, identity.fd = 45, 123, 7
    monkeypatch.setattr(aa, "start_time", lambda _: 124)
    monkeypatch.setattr(aa.signal, "pidfd_send_signal", lambda *a: pytest.fail("signalled reused PID"))
    identity.send(signal.SIGKILL)
    assert not identity.alive()


def test_pid_reuse_during_acquisition_closes_pidfd(monkeypatch):
    starts = iter([123, 124])
    closed = []
    monkeypatch.setattr(aa, "start_time", lambda _: next(starts))
    monkeypatch.setattr(aa.os, "pidfd_open", lambda _: 9)
    monkeypatch.setattr(aa.os, "close", closed.append)
    with pytest.raises(aa.Inconclusive, match="PID reused"):
        aa.Process(45)
    assert closed == [9]


def test_namespace_collision_and_exact_owned_cleanup_preserve_neighbors(tmp_path, monkeypatch):
    monkeypatch.setattr(aa, "AA", tmp_path)
    (tmp_path / "policy/namespaces").mkdir(parents=True)
    ns = aa.Namespace()
    ns.path.mkdir()
    unrelated = ns.path / "foreign"
    unrelated.write_text("preserve")
    with pytest.raises(FileExistsError):
        ns.create()
    assert not ns.created and unrelated.read_text() == "preserve"
    owned = aa.Namespace()
    owned.create()
    owned.remove()
    assert not owned.path.exists() and unrelated.exists()


def test_namespace_identity_replacement_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(aa, "AA", tmp_path)
    (tmp_path / "policy/namespaces").mkdir(parents=True)
    ns = aa.Namespace()
    ns.create()
    original = ns.path.with_name("original")
    ns.path.rename(original)
    ns.path.mkdir()
    try:
        with pytest.raises(aa.Inconclusive, match="identity changed"):
            ns.remove()
        assert ns.path.exists() and original.exists()
    finally:
        os.close(ns.fd)


def test_bounded_output_and_deadline_controls():
    with pytest.raises(aa.Inconclusive, match="overflow"):
        aa.bounded([sys.executable, "-c", "print('x'*100000)"], limit=1000)
    with pytest.raises(aa.Inconclusive, match="deadline"):
        aa.bounded([sys.executable, "-c", "import time; time.sleep(2)"], timeout=0.2)


def fake_run_environment(tmp_path, monkeypatch):
    ex = experiment(tmp_path)
    events = []
    ex.namespace.path = tmp_path / NS
    monkeypatch.setattr(aa, "protected", lambda *a, **k: None)
    monkeypatch.setattr(aa.os, "getuid", lambda: 0)
    monkeypatch.setattr(aa.os, "geteuid", lambda: 0)
    original_text = Path.read_text
    monkeypatch.setattr(Path, "read_text", lambda path, *a, **k:
                        "unconfined" if str(path) == "/proc/self/attr/current" else original_text(path, *a, **k))
    monkeypatch.setattr(aa.os, "readlink", lambda _: "user:[1]")
    monkeypatch.setattr(aa, "validate_inputs", lambda *a, **kw: None)
    monkeypatch.setattr(aa, "journal_cursor", lambda: "cursor")
    monkeypatch.setattr(aa, "prctl", lambda *a: None)
    monkeypatch.setattr(aa, "root_policy", lambda **kw: {"disk": "stable", "loaded": "stable"})
    monkeypatch.setattr(ex, "reap", lambda: events.append("reap"))
    def parse(name, operation):
        events.append((name, operation))
        if operation == "load":
            ex.loaded = True
    monkeypatch.setattr(ex, "parse", parse)
    return ex, events


@pytest.mark.parametrize("baseline", [arm(audit=False), {**arm(), "trace": []}])
def test_orchestrator_does_not_run_candidate_without_attributed_baseline(tmp_path, monkeypatch, baseline):
    ex, events = fake_run_environment(tmp_path, monkeypatch)
    def run_arm(name):
        events.append(name)
        ex.loaded = True
        return baseline
    monkeypatch.setattr(ex, "arm", run_arm)
    result = ex.run()
    assert "baseline" in events and "candidate" not in events
    assert result["outcome"] == "inconclusive" and result["cleanup"]["status"] == "passed"
    assert events.index("reap") < events.index(("baseline.policy", "remove"))
    assert not ex.namespace.path.exists()


@pytest.mark.parametrize("failure", [KeyboardInterrupt, aa.Inconclusive])
def test_partial_load_and_cancellation_cleanup_only_owned_namespace(tmp_path, monkeypatch, failure):
    ex, events = fake_run_environment(tmp_path, monkeypatch)
    unrelated = tmp_path / "unrelated"
    unrelated.write_text("preserve")
    def run_arm(name):
        ex.loaded = True
        raise failure("partial arm")
    monkeypatch.setattr(ex, "arm", run_arm)
    result = ex.run()
    assert result["outcome"] == "inconclusive" and result["cleanup"]["status"] == "passed"
    assert ("baseline.policy", "remove") in events
    assert unrelated.read_text() == "preserve" and not ex.namespace.path.exists()
    assert (ex.evidence / "result.json").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("failure", ["namespace_removal", "root_policy_change", "reap"])
def test_cleanup_failure_overrides_supported_hypothesis(tmp_path, monkeypatch, failure):
    ex, events = fake_run_environment(tmp_path, monkeypatch)
    monkeypatch.setattr(ex, "arm", lambda name: arm() if name == "baseline" else arm(result=0))
    if failure == "namespace_removal":
        monkeypatch.setattr(ex.namespace, "remove", lambda: aa.require(False, "removal failed"))
    elif failure == "root_policy_change":
        snapshots = iter([{"loaded": "before"}, {"loaded": "after"}])
        monkeypatch.setattr(aa, "root_policy", lambda **kw: next(snapshots))
    else:
        monkeypatch.setattr(ex, "reap", lambda: aa.require(False, "reap failed"))
    try:
        result = ex.run()
        assert result["outcome"] == "inconclusive" and result["cleanup"]["status"] == "failed"
        assert result["cleanup"]["owned_target"] == str(ex.namespace.path)
    finally:
        if ex.namespace.fd is not None:
            os.close(ex.namespace.fd)


def test_existing_evidence_is_not_used_or_overwritten(tmp_path, monkeypatch):
    ex, events = fake_run_environment(tmp_path, monkeypatch)
    ex.evidence.mkdir()
    foreign = ex.evidence / "keep"
    foreign.write_text("preserve")
    result = ex.run()
    assert result["outcome"] == "inconclusive" and foreign.read_text() == "preserve"
    assert not (ex.evidence / "result.json").exists()


def test_trampoline_consumes_onexec_before_drop_and_fixed_bwrap_exec(tmp_path, monkeypatch):
    ex = experiment(tmp_path)
    events = []
    monkeypatch.setattr(aa.os, "getuid", lambda: 0)
    monkeypatch.setattr(aa.os, "geteuid", lambda: 0)
    original = Path.read_text
    monkeypatch.setattr(Path, "read_text", lambda p: f":{NS}:unconfined" if str(p) == "/proc/self/attr/current" else original(p))
    deadline = aa.time.monotonic() + 10
    monkeypatch.setattr(aa, "validate_inputs", lambda *a, **kw: events.append(("validated", kw["deadline"])))
    monkeypatch.setattr(aa, "bwrap_argv", lambda *a: ["/usr/bin/bwrap", "fixed"])
    monkeypatch.setattr(aa, "drop_identity", lambda u, g: events.append(("drop", u, g)))
    monkeypatch.setattr(aa.os, "execve", lambda *a: events.append(("exec", *a)))
    aa.trampoline(ex.root, UID, GID, NS, deadline)
    assert events[:2] == [("validated", deadline), ("drop", UID, GID)]
    assert events[2] == ("exec", "/usr/bin/bwrap", ["/usr/bin/bwrap", "fixed"], aa.ENV)


def test_bwrap_fixture_exposes_no_host_directory_or_arbitrary_command(tmp_path):
    manifest = {"fixture": {"files": {aa.PYTHON: {"path": "/usr/bin/python3.14"}},
                             "encodings": "/usr/lib/python3.14/encodings",
                             "dynload": "/usr/lib/python3.14/lib-dynload"}}
    argv = aa.bwrap_argv(tmp_path, manifest, UID, GID)
    assert argv[-1] == aa.WORKER and aa.PRIMARY == ["/usr/bin/unshare", "--user", "--map-root-user", "--mount", "/usr/bin/true"]
    assert "--cap-drop" in argv and "--unshare-user" in argv and "--die-with-parent" in argv
    assert not ({"/etc", "/sys", "/run", "/home/viperjuice", str(aa.AA)} & set(argv))
    assert "--clearenv" in argv and "--dev-bind" in argv


@pytest.mark.parametrize("component", [True, False])
def test_audit_capture_filters_exact_identity_and_detects_loss(monkeypatch, component):
    observation = gate()
    subject = f'namespace="{NS}" profile="unpriv_bwrap"' if component else f'label="{observation["label"].removesuffix(" (enforce)")}"'
    message = (f'audit(1.500:77): apparmor="DENIED" operation="capable" {subject} '
               'pid=45 capability=21 capname="sys_admin"')
    row = {"MESSAGE": message, "_BOOT_ID": "boot", "__REALTIME_TIMESTAMP": "2000000", "__MONOTONIC_TIMESTAMP": "2000000"}
    monkeypatch.setattr(aa, "boot_id", lambda: "boot")
    monkeypatch.setattr(aa, "bounded", lambda *a, **k: json.dumps(row).encode())
    result = aa.audit_capture("cursor", observation, {"realtime_ns": 1000000000, "monotonic_ns": 1000000000},
                              {"realtime_ns": 3000000000, "monotonic_ns": 3000000000})
    assert len(result) == 1 and result[0]["serial"] == "77" and "MESSAGE" not in result[0]
    row["MESSAGE"] = "audit: 12 callbacks suppressed"
    with pytest.raises(aa.Inconclusive, match="capture loss"):
        aa.audit_capture("cursor", observation, {}, {})


@pytest.mark.parametrize("ops", [[1, 2], [1], [2]])
def test_observer_requires_positive_verified_unshare_entry_and_exit(monkeypatch, ops):
    worker = SimpleNamespace(pid=45, start=123, alive=lambda: True)
    observer = aa.Observer.__new__(aa.Observer)
    observer.worker, observer.active, observer.pending = worker, {45: worker}, {}
    observer.deadline = None
    observer.records, observer.exits = [], {}
    observer.expected_label = gate()["label"]
    original_read = Path.read_text
    original_resolve = Path.resolve
    monkeypatch.setattr(Path, "read_text", lambda p: gate()["label"] if str(p) == "/proc/45/attr/current" else original_read(p))
    monkeypatch.setattr(Path, "resolve", lambda p, **k: Path("/usr/bin/unshare").absolute() if str(p) in ("/proc/45/exe", "/usr/bin/unshare") else original_resolve(p, **k))
    states = iter([(45, ((signal.SIGTRAP | 0x80) << 8) | 0x7f)] * len(ops) + [(45, 0)])
    monkeypatch.setattr(aa.os, "waitpid", lambda *a: next(states))
    monkeypatch.setattr(aa.platform, "machine", lambda: "x86_64")
    op = iter(ops)
    def ptrace(request, pid, addr=0, data=0):
        if request == 0x420e:
            entry = next(op)
            buf = bytearray(88)
            buf[0] = entry
            buf[4:8] = (0xc000003e).to_bytes(4, sys.byteorder)
            buf[24:32] = (272 if entry == 1 else 0).to_bytes(8, sys.byteorder)
            if entry == 1:
                buf[32:40] = (0x10020000).to_bytes(8, sys.byteorder)
            ctypes.memmove(data, bytes(buf), 88)
            return 80 if entry == 1 else 33
        return 0
    monkeypatch.setattr(aa, "ptrace", ptrace)
    events = []
    records = observer.run(lambda: events.append("GO"))
    assert events == ["GO"] and worker.reaped
    if ops == [1, 2]:
        assert len(records) == 1 and records[0]["return"] == 0
        assert records[0]["flags"] == 0x10020000 and records[0]["start"] == 123
    else:
        assert not records


def test_observer_seizes_with_syscall_stop_tagging_before_waiting(monkeypatch):
    worker = SimpleNamespace(pid=45, start=123)
    events = []
    monkeypatch.setattr(aa.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(aa, "ptrace", lambda *a: events.append(a))
    monkeypatch.setattr(aa.Observer, "wait_stop", lambda *a: events.append("stopped"))
    aa.Observer(worker, {45: worker})
    assert events == [(0x4206, 45, 0, 1 | 2 | 4 | 8), (0x4207, 45), "stopped"]


def test_real_unprivileged_child_cleanup_preserves_bystander(tmp_path):
    ex = experiment(tmp_path)
    command = [sys.executable, "-c", "import time; time.sleep(30)"]
    bystander = subprocess.Popen(command, start_new_session=True)
    child = subprocess.Popen(command, start_new_session=True, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        ex.child = child
        handle = aa.Process(child.pid)
        ex.children[handle.pid] = handle
        ex.reap()
        assert not ex.children and child.poll() is not None and bystander.poll() is None
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        bystander.terminate()
        bystander.wait(timeout=5)


@pytest.mark.parametrize("registered", [False, True])
def test_direct_child_teardown_survives_acquisition_or_discovery_failure(tmp_path, monkeypatch, registered):
    ex = experiment(tmp_path)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                             start_new_session=True, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    ex.child = child
    if registered:
        ex.children[child.pid] = aa.Process(child.pid)
        monkeypatch.setattr(aa, "descendants", lambda *a, **kw: aa.require(False, "discovery failed"))
    try:
        try:
            ex.reap()
        except aa.Inconclusive:
            pass
        assert child.poll() is not None
        assert all(s.closed for s in (child.stdin, child.stdout, child.stderr))
        if registered:
            with pytest.raises(aa.Inconclusive, match="discovery failed"):
                ex.reap()
        else:
            assert ex.child is None
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)
        for stream in (child.stdin, child.stdout, child.stderr):
            stream.close()
        for handle in ex.children.values():
            handle.close()


def test_dead_owned_children_all_have_wait_status_consumed(tmp_path):
    ex = experiment(tmp_path)
    children = [subprocess.Popen([sys.executable, "-c", "pass"], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True) for _ in range(2)]
    try:
        ex.child = children[0]
        for child in children:
            handle = aa.Process(child.pid)
            ex.children[child.pid] = handle
            assert aa.select.select([handle.fd], [], [], 5)[0]
        ex.reap()
        for child in children:
            with pytest.raises(ChildProcessError):
                os.waitpid(child.pid, os.WNOHANG)
        assert not ex.children and ex.child is None
    finally:
        for child in children:
            child.wait(timeout=5)
            for stream in (child.stdin, child.stdout, child.stderr):
                stream.close()
        for handle in ex.children.values():
            handle.close()


def test_failed_descendant_revalidation_closes_unregistered_handle(monkeypatch):
    closed = []
    owner = SimpleNamespace(pid=45, alive=lambda: True)
    handle = SimpleNamespace(pid=46, start=123, close=lambda: closed.append(46))
    monkeypatch.setattr(Path, "read_text", lambda *a: "46")
    monkeypatch.setattr(aa, "Process", lambda pid: handle)
    monkeypatch.setattr(aa, "status", lambda pid: {"PPid": "99"})
    found = {}
    with pytest.raises(aa.Inconclusive, match="ownership changed"):
        aa.descendants(owner, found)
    assert closed == [46] and not found


def scratch_fixture(tmp_path, monkeypatch):
    stdlib = tmp_path / "python3.99"
    encodings = stdlib / "encodings"
    encodings.mkdir(parents=True)
    (encodings / "__init__.py").write_text("pass")
    monkeypatch.setattr(aa, "Path", lambda p: tmp_path if p == "/usr/lib" else Path(p))
    monkeypatch.setattr(aa, "bounded", lambda argv, **kw: b"3.99" if argv[0] == aa.PYTHON else b"")
    monkeypatch.setattr(aa, "executable", lambda p, *a: {"path": str(Path(p).resolve()), "sha256": "hash"})
    monkeypatch.setattr(aa, "protected", lambda p, **kw: aa.require(
        str(p) == str(Path(p).resolve()), "noncanonical staging"))
    return encodings


@pytest.mark.parametrize("entry", ["fifo", "symlink", "directory_symlink"])
def test_encoding_inventory_rejects_unapproved_objects(tmp_path, monkeypatch, entry):
    encodings = scratch_fixture(tmp_path, monkeypatch)
    aa.fixture_inputs()
    if entry == "fifo":
        os.mkfifo(encodings / "extra")
    elif entry == "symlink":
        (encodings / "extra").symlink_to(encodings / "__init__.py")
    else:
        encodings.rename(encodings.with_name("elsewhere"))
        encodings.symlink_to(encodings.with_name("elsewhere"), target_is_directory=True)
    with pytest.raises(aa.Inconclusive, match="noncanonical|unsupported encoding"):
        aa.fixture_inputs()


def test_encoding_directory_membership_is_bound(tmp_path, monkeypatch):
    encodings = scratch_fixture(tmp_path, monkeypatch)
    before = aa.fixture_inputs()
    (encodings / "new_directory").mkdir()
    assert before != aa.fixture_inputs()


def test_parser_only_library_change_changes_tool_closure(tmp_path, monkeypatch):
    library_hash = ["before"]
    monkeypatch.setattr(aa, "executable", lambda p, *a: {
        "path": str(Path(p).resolve()),
        "sha256": library_hash[0] if str(p) == "/fake/parser-only.so" else "unchanged"})
    def command(argv, **kw):
        if argv[0] == aa.PYTHON:
            return b'["/usr/lib/python3.14/os.py"]'
        return b"libparser => /fake/parser-only.so (0x1)\n" if aa.PARSER in argv else b""
    monkeypatch.setattr(aa, "bounded", command)
    before = aa.tools()
    root = policy_tree(tmp_path)
    manifest = {"inputs": aa.closure(root), "boot_id": aa.boot_id(),
                "kernel": aa.platform.release(), "tools": before, "fixture": {}}
    monkeypatch.setattr(aa, "protected", lambda *a, **kw: None)
    monkeypatch.setattr(aa, "fixture_inputs", lambda **kw: {})
    library_hash[0] = "after"
    assert before != aa.tools()
    with pytest.raises(aa.Inconclusive, match="executable closure changed"):
        aa.validate_inputs(root, manifest)


def fake_outer_arm(tmp_path, monkeypatch):
    ex = experiment(tmp_path)
    ex.namespace.path = tmp_path / "namespace"
    for name in ("bwrap", "unpriv_bwrap"):
        profile = ex.namespace.path / "profiles" / name
        profile.mkdir(parents=True)
        (profile / "name").write_text(name)
        (profile / "mode").write_text("enforce")
    monkeypatch.setattr(ex, "parse", lambda *a: None)
    monkeypatch.setattr(ex.namespace, "check", lambda: None)
    monkeypatch.setattr(aa, "journal_cursor", lambda: "cursor")
    monkeypatch.setattr(aa, "loss_counters", lambda **kw: {})
    monkeypatch.setattr(aa, "expected_binds", lambda *a: {})
    monkeypatch.setattr(aa, "audit_capture", lambda *a: [])
    monkeypatch.setattr(aa, "descendants", lambda *a, **kw: None)
    monkeypatch.setattr(ex, "reap", lambda: None)
    monkeypatch.setattr(ex, "primary", lambda worker, binds, record: record.update(gate=gate()))
    owner = SimpleNamespace(pid=45, start=123, alive=lambda: True)
    monkeypatch.setattr(aa, "Process", lambda pid: owner)
    original = Path.resolve
    monkeypatch.setattr(Path, "resolve", lambda p, **kw:
                        original(Path(aa.PYTHON)) if str(p) == "/proc/45/exe" else original(p, **kw))
    return ex


def test_exited_outer_diagnostics_are_drained_and_aggregate_limited(tmp_path, monkeypatch):
    ex = fake_outer_arm(tmp_path, monkeypatch)
    class Pipe(io.BytesIO):
        def fileno(self):
            return 501
    child = SimpleNamespace(pid=45, stdin=Pipe(), stdout=Pipe(), stderr=Pipe(), poll=lambda: 0)
    monkeypatch.setattr(aa.subprocess, "Popen", lambda *a, **kw: child)
    monkeypatch.setattr(aa.select, "select", lambda *a: ([child.stdout], [], []))
    chunks = iter([b"READY\n", *([b"x" * 8192] * 8), b"", b""])
    monkeypatch.setattr(aa.os, "read", lambda *a: next(chunks))
    monkeypatch.setattr(aa.os, "set_blocking", lambda *a: None)
    # 64 KiB after READY exceeds the single aggregate limit even though poll()==0.
    with pytest.raises(aa.Inconclusive, match="diagnostic overflow"):
        ex.arm("baseline")


@pytest.mark.parametrize("failure", [aa.Inconclusive, OSError, KeyboardInterrupt])
def test_spawn_acquisition_failure_retains_direct_ownership_and_signal_mask(tmp_path, monkeypatch, failure):
    ex = fake_outer_arm(tmp_path, monkeypatch)
    masks, spawned = [], []
    child = SimpleNamespace(pid=45)
    monkeypatch.setattr(aa.signal, "pthread_sigmask", lambda *a: masks.append(a) or set())
    def spawn(argv, **kwargs):
        spawned.append(kwargs)
        return child
    monkeypatch.setattr(aa.subprocess, "Popen", spawn)
    monkeypatch.setattr(aa, "Process", lambda pid: (_ for _ in ()).throw(failure("acquisition")))
    with pytest.raises(failure):
        ex.arm("baseline")
    assert ex.child is child and ex.session_pid == child.pid and not ex.children
    assert masks[0][0] == signal.SIG_BLOCK and masks[-1] == (signal.SIG_SETMASK, set())
    spawned[0]["preexec_fn"]()
    assert masks[-1] == (signal.SIG_SETMASK, set())


@pytest.mark.parametrize("operation_time,expected", [(5, "passed"), (10, "deadline")])
def test_outer_drain_shares_primary_budget_instead_of_startup_clock(tmp_path, monkeypatch, operation_time, expected):
    ex = fake_outer_arm(tmp_path, monkeypatch)
    clock = [0.0]
    monkeypatch.setattr(aa.time, "monotonic", lambda: clock[0])
    class Pipe(io.BytesIO):
        def fileno(self):
            return 501
    child = SimpleNamespace(pid=45, stdin=Pipe(), stdout=Pipe(), stderr=Pipe(), poll=lambda: 0)
    monkeypatch.setattr(aa.subprocess, "Popen", lambda *a, **kw: child)
    selected = [False]
    def ready(streams, *a):
        if not selected[0]:
            selected[0] = True
            return [child.stdout], [], []
        return list(streams), [], []
    monkeypatch.setattr(aa.select, "select", ready)
    chunks = iter([b"READY\n", b"", b""])
    monkeypatch.setattr(aa.os, "read", lambda *a: next(chunks))
    monkeypatch.setattr(aa.os, "set_blocking", lambda *a: None)
    def counters(**kw):
        if "deadline" in kw:
            assert kw["deadline"] == 10
            clock[0] = 9
        return {}
    monkeypatch.setattr(aa, "loss_counters", counters)
    def primary(worker, binds, record):
        assert ex.operation_end == 19
        record["gate"] = gate()
        clock[0] += operation_time
    monkeypatch.setattr(ex, "primary", primary)
    if expected == "passed":
        assert ex.arm("baseline")["diagnostic_bytes"] == len(b"READY\n")
        assert clock[0] > 10  # Startup's end is no longer reused after primary.
    else:
        with pytest.raises(aa.Inconclusive, match="deadline"):
            ex.arm("baseline")
        assert clock[0] == 19  # No new drain budget after the operation expires.


def test_trampoline_validation_expiry_prevents_drop_or_exec(tmp_path, monkeypatch):
    ex = experiment(tmp_path)
    clock = [0.0]
    monkeypatch.setattr(aa.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(aa.os, "getuid", lambda: 0)
    monkeypatch.setattr(aa.os, "geteuid", lambda: 0)
    original = Path.read_text
    monkeypatch.setattr(Path, "read_text", lambda p: f":{NS}:unconfined" if str(p) == "/proc/self/attr/current" else original(p))
    def validate(root, manifest, *, deadline):
        assert deadline == 10
        clock[0] = 10
    monkeypatch.setattr(aa, "validate_inputs", validate)
    monkeypatch.setattr(aa, "bwrap_argv", lambda *a: ["bwrap"])
    monkeypatch.setattr(aa, "drop_identity", lambda *a: pytest.fail("drop after startup expiry"))
    monkeypatch.setattr(aa.os, "execve", lambda *a: pytest.fail("exec after startup expiry"))
    with pytest.raises(aa.Inconclusive, match="deadline"):
        aa.trampoline(ex.root, UID, GID, NS, 10)


def test_partial_teardown_closes_resolved_handles_and_keeps_unresolved(tmp_path, monkeypatch):
    ex = experiment(tmp_path)
    closed, signals = [], []
    good = SimpleNamespace(pid=45, start=123, send=lambda sig: signals.append((45, sig)),
                           collect=lambda: True, close=lambda: closed.append(45))
    def unresolved():
        raise aa.Inconclusive("wait identity unresolved")
    bad = SimpleNamespace(pid=46, start=124, send=lambda sig: signals.append((46, sig)),
                          collect=unresolved, close=lambda: pytest.fail("unresolved pidfd discarded"))
    ex.children = {45: good, 46: bad}
    clock = [0.0]
    monkeypatch.setattr(aa.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(aa.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(aa, "descendants", lambda *a, **kw: None)
    ex.cleanup_end = 0.01
    with pytest.raises(aa.Inconclusive, match="not proved reaped"):
        ex.reap()
    assert closed == [45] and ex.children == {46: bad}
    assert (46, signal.SIGKILL) in signals and "wait identity unresolved" in ex.teardown_errors


def test_discovery_failure_blocks_policy_cleanup_after_known_teardown(tmp_path, monkeypatch):
    ex, events = fake_run_environment(tmp_path, monkeypatch)
    monkeypatch.setattr(ex, "reap", aa.Experiment.reap.__get__(ex))
    closed, signals = [], []
    handle = SimpleNamespace(pid=45, start=123, send=signals.append,
                             collect=lambda: True, close=lambda: closed.append(45))
    def run_arm(name):
        ex.children[45] = handle
        ex.loaded = True
        raise aa.Inconclusive("startup failure")
    monkeypatch.setattr(ex, "arm", run_arm)
    monkeypatch.setattr(aa, "descendants", lambda *a, **kw: aa.require(False, "discovery failed"))
    result = ex.run()
    try:
        assert signals and closed == [45] and not ex.children
        assert result["cleanup"]["status"] == "failed"
        assert "discovery failed" in result["cleanup"]["reason"]
        assert result["teardown_errors"] == ["discovery failed"]
        assert ex.namespace.path.exists() and ("baseline.policy", "remove") not in events
    finally:
        if ex.namespace.fd is not None:
            os.close(ex.namespace.fd)


def test_failed_arm_teardown_keeps_same_budget_for_final_cleanup(tmp_path, monkeypatch):
    ex, events = fake_run_environment(tmp_path, monkeypatch)
    monkeypatch.setattr(ex, "reap", aa.Experiment.reap.__get__(ex))
    clock = [0.0]
    monkeypatch.setattr(aa.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(aa.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    handle = SimpleNamespace(pid=45, start=123, send=lambda sig: None,
                             collect=lambda: False, close=lambda: pytest.fail("unresolved handle closed"))
    monkeypatch.setattr(aa, "descendants", lambda *a, **kw: None)
    def run_arm(name):
        ex.loaded = True
        ex.children[45] = handle
        ex.reap()
    monkeypatch.setattr(ex, "arm", run_arm)
    try:
        result = ex.run()
        assert ex.cleanup_end == 30 and clock[0] == 30
        assert result["cleanup"]["status"] == "failed" and ex.children == {45: handle}
        assert ex.namespace.path.exists() and ("baseline.policy", "remove") not in events
        assert result["processes"] == [{"pid": 45, "start": 123}]
    finally:
        if ex.namespace.fd is not None:
            os.close(ex.namespace.fd)


def test_real_subreaper_consumes_already_exited_adopted_child(tmp_path):
    root = policy_tree(tmp_path)
    code = '''
import json, os, select, subprocess, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import codex_apparmor_canary as aa
aa.prctl(36, 1)
ex = aa.Experiment(Path(sys.argv[2]), Path(sys.argv[2])/'unused', os.getuid(), os.getgid())
command = "import os,time; pid=os.fork(); (time.sleep(.1),os._exit(0)) if pid==0 else print(pid,flush=True)"
child = subprocess.Popen([sys.executable,'-c',command],start_new_session=True,
                         stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
ex.child = child
grandpid = int(child.stdout.readline())
try:
    for pid in (child.pid, grandpid):
        h = aa.Process(pid)
        ex.children[pid] = h
    for h in ex.children.values():
        assert select.select([h.fd],[],[],5)[0]
    assert int(aa.status(grandpid)['PPid']) == os.getpid()
    ex.reap()
    assert not ex.children and ex.child is None
    try: os.waitpid(grandpid,os.WNOHANG)
    except ChildProcessError: pass
    else: raise AssertionError('adopted wait status was not consumed')
    print('adopted dead descendant reaped')
finally:
    for h in ex.children.values():
        h.send(9)
        try: os.waitpid(h.pid,0)
        except ChildProcessError: pass
        h.close()
    child.wait(timeout=5)
'''
    result = subprocess.run([sys.executable, "-c", code, str(Path(aa.__file__).parent), str(root)],
                            capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout == b"adopted dead descendant reaped\n"


def test_observed_partial_parser_load_is_removed_before_namespace(tmp_path, monkeypatch):
    ex, events = fake_run_environment(tmp_path, monkeypatch)
    ex.manifest = {"inputs": {}}
    marker = ex.namespace.path / "partial-profile"
    monkeypatch.setattr(ex, "parse", aa.Experiment.parse.__get__(ex))
    def parser(argv, **kwargs):
        events.append(tuple(argv))
        if "-r" in argv:
            marker.write_text("partially loaded")
            raise aa.Inconclusive("fake partial load")
        if "-R" in argv:
            assert marker.exists()
            marker.unlink()
        return b""
    monkeypatch.setattr(aa, "bounded", parser)
    monkeypatch.setattr(ex, "arm", lambda name: ex.parse(name + ".policy", "load"))
    result = ex.run()
    assert ex.loaded and result["outcome"] == "inconclusive"
    assert result["cleanup"]["status"] == "passed" and not marker.exists() and not ex.namespace.path.exists()
    loads = [e for e in events if isinstance(e, tuple) and "-r" in e]
    removes = [e for e in events if isinstance(e, tuple) and "-R" in e]
    assert len(loads) == len(removes) == 1
    assert loads[0][loads[0].index("--namespace") + 1] == NS
    assert removes[0][removes[0].index("--namespace") + 1] == NS


def test_root_policy_proof_needs_loaded_bytes_and_detects_changes(tmp_path):
    disk = tmp_path / "disk"
    disk.mkdir()
    (disk / "host.policy").write_text("unchanged")
    kernel = tmp_path / "kernel"
    kernel.mkdir()
    with pytest.raises(aa.Inconclusive, match="loaded root-policy"):
        aa.root_policy(disk, kernel)
    profile = kernel / "policy/profiles/host.1"
    profile.mkdir(parents=True)
    for name, text in (("name", "host"), ("mode", "enforce"), ("raw_data", "compiled")):
        (profile / name).write_text(text)
    (kernel / "profiles").write_text("host (enforce)\n")
    before = aa.root_policy(disk, kernel)
    (profile / "raw_data").write_text("different loaded bytes")
    after = aa.root_policy(disk, kernel)
    assert before["disk"] == after["disk"] and before["loaded"] != after["loaded"]
    assert (disk / "host.policy").read_text() == "unchanged"


def test_signal_cancellation_enters_cleanup_and_restores_handlers(tmp_path, monkeypatch):
    previous = signal.getsignal(signal.SIGTERM)
    monkeypatch.setattr(aa.os, "getuid", lambda: 0)
    monkeypatch.setattr(aa.os, "geteuid", lambda: 0)
    monkeypatch.setattr(aa.sys, "flags", SimpleNamespace(isolated=True, no_site=True))
    events = []
    class FakeExperiment:
        def __init__(self, *a):
            pass
        def run(self):
            try:
                signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
            except aa.Inconclusive:
                events.append("cleanup")
                return {"outcome": "inconclusive", "cleanup": {"status": "passed"}}
    monkeypatch.setattr(aa, "Experiment", FakeExperiment)
    assert aa.main(["run", "--operator-uid", str(UID), "--operator-gid", str(GID),
                    "--evidence", str(tmp_path / "result")]) == 1
    assert events == ["cleanup"] and signal.getsignal(signal.SIGTERM) == previous


def test_pid_change_at_go_leaves_gate_closed(tmp_path, monkeypatch):
    ex = experiment(tmp_path)
    class FakeObserver:
        def __init__(self, *a, **kw):
            pass
        def run(self, go):
            go()
    monkeypatch.setattr(aa, "Observer", FakeObserver)
    monkeypatch.setattr(aa, "observe_gate", lambda *a: gate())
    ex.child = SimpleNamespace(stdin=io.BytesIO())
    record = {"go_sent": False}
    with pytest.raises(aa.Inconclusive, match="identity changed"):
        ex.primary(SimpleNamespace(alive=lambda: False), BINDS, record)
    assert not record["go_sent"] and ex.child.stdin.getvalue() == b""


@pytest.mark.parametrize("key,value", [("namespace", "foreign"), ("profile", "bwrap"),
                                       ("capability", "7"), ("pid", "46"), ("capname", "setuid")])
def test_audit_component_must_belong_to_exact_namespace_and_denied_capability(monkeypatch, key, value):
    fields = {"namespace": NS, "profile": "unpriv_bwrap", "capability": "21", "pid": "45", "capname": "sys_admin"}
    fields[key] = value
    message = 'audit(1.500:77): apparmor="DENIED" operation="capable" ' + " ".join(f'{k}="{v}"' for k, v in fields.items())
    row = {"MESSAGE": message, "_BOOT_ID": "boot", "__REALTIME_TIMESTAMP": "2000000", "__MONOTONIC_TIMESTAMP": "2000000"}
    monkeypatch.setattr(aa, "boot_id", lambda: "boot")
    monkeypatch.setattr(aa, "bounded", lambda *a, **k: json.dumps(row).encode())
    bounds = {"realtime_ns": 1000000000, "monotonic_ns": 1000000000}
    finish = {"realtime_ns": 3000000000, "monotonic_ns": 3000000000}
    assert aa.audit_capture("cursor", gate(), bounds, finish) == []


def test_nonroot_fixture_startup_reaches_ready_and_refuses_eof(tmp_path):
    if os.getuid() == 0 or os.getgid() == 0:
        pytest.skip("startup-only regression requires a non-root operator")
    if sys.platform != "linux" or not shutil.which("bwrap") or not Path(aa.PYTHON).exists():
        pytest.skip("Linux, system Python and bubblewrap are required for actual fixture startup")
    manifest = {"fixture": aa.fixture_inputs()}
    (tmp_path / "fixture.txt").write_bytes(b"synthetic fixture\n")
    argv = aa.bwrap_argv(tmp_path, manifest, os.getuid(), os.getgid())
    # EOF is permanent: this process can never receive GO or execute PRIMARY.
    result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True,
                            env=aa.ENV, close_fds=True, timeout=10)
    if result.returncode != 125 and any(message in result.stderr for message in (
            b"No permissions to create new namespace", b"Creating new namespace failed",
            b"setting up uid map: Permission denied", b"unshare user namespace: Operation not permitted")):
        pytest.skip("host denies unprivileged bubblewrap startup: " + result.stderr.decode(errors="replace")[:500])
    assert result.returncode == 125, result.stderr.decode(errors="replace")
    assert result.stdout == b"READY\n" and result.stderr == b""
    stdlib = Path(manifest["fixture"]["encodings"]).parent
    assert {str(stdlib / "os.py"), str(stdlib / "linecache.py")} <= set(manifest["fixture"]["files"])
    assert str(stdlib) not in argv and str(stdlib / "lib-dynload") not in manifest["fixture"]["files"]
    # Reading host mount metadata is unprivileged and does not open the gate.
    assert str(stdlib / "lib-dynload") not in aa.expected_binds(tmp_path, manifest)


@pytest.mark.parametrize("after_validation", [10, 11])
def test_cleanup_revalidation_cannot_launch_parser_at_or_after_deadline(tmp_path, monkeypatch, after_validation):
    ex = experiment(tmp_path)
    clock = [0.0]
    ex.cleanup_end = 10
    monkeypatch.setattr(aa.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(ex.namespace, "check", lambda: None)
    def validate(root, manifest, *, deadline):
        assert deadline == 10
        clock[0] = after_validation
    monkeypatch.setattr(aa, "validate_inputs", validate)
    monkeypatch.setattr(aa, "bounded", lambda *a, **kw: pytest.fail("parser launched after expiry"))
    with pytest.raises(aa.Inconclusive, match="deadline"):
        ex.parse("baseline.policy", "remove")
    assert not ex.result["parser"]


def test_revalidation_subcommands_share_the_cleanup_deadline(tmp_path, monkeypatch):
    ex = experiment(tmp_path)
    clock = [0.0]
    ex.cleanup_end = 10
    help_text = b"Do not attempt to load or save cached profiles"
    ex.manifest = {"inputs": aa.closure(ex.root), "boot_id": aa.boot_id(),
                   "kernel": aa.platform.release(), "tools": {}, "fixture": {},
                   "parser_help_sha256": aa.digest(help_text)}
    monkeypatch.setattr(aa.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(ex.namespace, "check", lambda: None)
    monkeypatch.setattr(aa, "protected", lambda *a, **kw: None)
    deadlines = []
    def tools(*, deadline):
        deadlines.append(deadline)
        clock[0] = 3
        return {}
    def fixture(*, deadline):
        deadlines.append(deadline)
        clock[0] = 6
        return {}
    calls = []
    def command(argv, *, deadline, **kw):
        deadlines.append(deadline)
        assert aa.remaining(deadline) <= 4
        calls.append(argv)
        clock[0] += 2
        return help_text if "--help" in argv else (ex.root / "features.dump").read_bytes()
    monkeypatch.setattr(aa, "tools", tools)
    monkeypatch.setattr(aa, "fixture_inputs", fixture)
    monkeypatch.setattr(aa, "bounded", command)
    with pytest.raises(aa.Inconclusive, match="deadline"):
        ex.parse("baseline.policy", "remove")
    assert len(calls) == 2 and "--help" in calls[0] and calls[1][0] == aa.FEATURES
    assert deadlines == [10] * 4 and not ex.result["parser"]


def test_fixture_dependency_probes_receive_one_deadline(monkeypatch):
    clock = [0.0]
    calls = []
    monkeypatch.setattr(aa.time, "monotonic", lambda: clock[0])
    def command(argv, *, deadline, **kw):
        aa.remaining(deadline)
        calls.append((argv[0], deadline))
        clock[0] += 4
        aa.remaining(deadline)
        return b""
    monkeypatch.setattr(aa, "bounded", command)
    with pytest.raises(aa.Inconclusive, match="deadline"):
        aa.fixture_inputs(deadline=10)
    assert calls == [("/usr/bin/ldd", 10)] * 3


def test_bounded_refuses_expired_budget_before_spawn(monkeypatch):
    monkeypatch.setattr(aa.time, "monotonic", lambda: 10)
    monkeypatch.setattr(aa.subprocess, "Popen", lambda *a, **kw: pytest.fail("expired spawn"))
    with pytest.raises(aa.Inconclusive, match="deadline"):
        aa.bounded(["parser"], deadline=10)


@pytest.mark.parametrize("failure", ["selector", "identity", "signal", "selector_close", "teardown_signal"])
def test_controller_spawn_setup_failure_is_reaped_before_namespace_removal(tmp_path, monkeypatch, failure):
    ex, events = fake_run_environment(tmp_path, monkeypatch)
    spawned = []
    popen, identity = subprocess.Popen, aa.start_time
    def spawn(*args, **kwargs):
        child = popen(*args, **kwargs)
        spawned.append(child)
        if failure == "identity":
            monkeypatch.setattr(aa, "start_time", lambda pid: aa.require(False, "identity failure"))
        if failure == "signal":
            os.kill(os.getpid(), signal.SIGHUP)
        return child
    def cancelled(signum, frame):
        raise aa.Inconclusive("scratch cancellation")
    previous = signal.signal(signal.SIGHUP, cancelled)
    monkeypatch.setattr(aa.subprocess, "Popen", spawn)
    def run_arm(name):
        ex.loaded = True
        if failure == "selector":
            monkeypatch.setattr(aa.selectors, "DefaultSelector", lambda: aa.require(False, "selector failure"))
        elif failure == "selector_close":
            selector = aa.selectors.DefaultSelector
            class BrokenClose(selector):
                def close(self):
                    super().close()
                    raise aa.Inconclusive("selector close failure")
            monkeypatch.setattr(aa.selectors, "DefaultSelector", BrokenClose)
        elif failure == "teardown_signal":
            sending = popen.send_signal
            def send(child, sig):
                sending(child, sig)
                os.kill(os.getpid(), signal.SIGHUP)
            monkeypatch.setattr(popen, "send_signal", send)
        aa.bounded([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.5)
    monkeypatch.setattr(ex, "arm", run_arm)
    try:
        result = ex.run()
        assert spawned and all(child.returncode is not None for child in spawned)
        assert result["outcome"] == "inconclusive"
        assert not ex.namespace.path.exists() or result["cleanup"]["status"] == "failed"
    finally:
        signal.signal(signal.SIGHUP, previous)
        monkeypatch.setattr(aa, "start_time", identity)
        for child in spawned:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=2)
            for stream in (child.stdout, child.stderr):
                stream.close()
        if ex.namespace.fd is not None:
            os.close(ex.namespace.fd)


@pytest.mark.parametrize("failure", ["injected_cancellation", "signal", "lstat", "open", "fstat"])
def test_namespace_acquisition_interruption_keeps_honest_recovery(tmp_path, monkeypatch, failure):
    ex, events = fake_run_environment(tmp_path, monkeypatch)
    mkdir, lstat, opening = Path.mkdir, Path.lstat, os.open
    def cancelled(signum, frame):
        raise aa.Inconclusive("scratch cancellation")
    previous = signal.signal(signal.SIGHUP, cancelled)
    def create(path, *a, **kw):
        result = mkdir(path, *a, **kw)
        if path == ex.namespace.path:
            if failure == "injected_cancellation":
                raise aa.Inconclusive("scratch cancellation")
            if failure == "signal":
                os.kill(os.getpid(), signal.SIGHUP)
        return result
    monkeypatch.setattr(Path, "mkdir", create)
    def inspect(path, *a, **kw):
        if path == ex.namespace.path and failure == "lstat":
            raise OSError("scratch lstat failure")
        return lstat(path, *a, **kw)
    monkeypatch.setattr(Path, "lstat", inspect)
    def acquire(path, *a, **kw):
        if path == ex.namespace.path and failure == "open":
            raise OSError("scratch open failure")
        return opening(path, *a, **kw)
    monkeypatch.setattr(aa.os, "open", acquire)
    if failure == "fstat":
        fstat = os.fstat
        monkeypatch.setattr(aa.os, "fstat", lambda fd: aa.require(False, "scratch fstat failure")
                            if fd == ex.namespace.fd else fstat(fd))
    monkeypatch.setattr(ex, "arm", lambda name: pytest.fail("arm after interrupted namespace acquisition"))
    try:
        result = ex.run()
        assert result["outcome"] == "inconclusive"
        assert result["cleanup"]["owned_target"] == str(ex.namespace.path)
        if failure == "signal":
            assert result["cleanup"]["status"] == "passed" and not ex.namespace.path.exists()
        else:
            assert result["cleanup"]["status"] == "failed" and ex.namespace.path.exists()
    finally:
        signal.signal(signal.SIGHUP, previous)
        if ex.namespace.fd is not None:
            os.close(ex.namespace.fd)


@pytest.mark.parametrize("escaped,controller", [(False, True), (True, True), (False, False)])
def test_controller_command_adopted_fork_is_reaped_or_refused(tmp_path, escaped, controller):
    code = '''
import os, subprocess, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import codex_apparmor_canary as aa
registry = []
token = aa.COMMAND_OWNERS.set(registry if sys.argv[3] == 'True' else None)
session = os.getsid(0)
before = aa.ctypes.c_int()
aa.prctl(37, aa.ctypes.byref(before))
command = """import os,signal,time
pid=os.fork()
if pid:
    assert os.getsid(0) EXPECTED_SESSION
    print(pid,flush=True)
    os._exit(0)
if ESCAPED: os.setsid()
os.close(1)
os.close(2)
signal.signal(signal.SIGTERM, signal.SIG_IGN)
time.sleep(30)
""".replace('ESCAPED', sys.argv[2]).replace('EXPECTED_SESSION',
    ('!= ' if sys.argv[3] == 'True' else '== ') + str(session))
try:
    try:
        output = aa.bounded([sys.executable, '-c', command], timeout=5)
    except aa.Inconclusive as error:
        assert sys.argv[2] == 'True' and 'escaped owned session' in str(error), str(error)
    else:
        assert sys.argv[2] == 'False' and int(output) > 0
    assert all(not owner.children and owner.child is None for owner in registry)
    if sys.argv[2] == 'False':
        after = aa.ctypes.c_int()
        aa.prctl(37, aa.ctypes.byref(after))
        assert after.value == before.value
    try: os.waitpid(-1, os.WNOHANG)
    except ChildProcessError: pass
    else: raise AssertionError('command descendant wait status was not consumed')
    print('controller descendants reaped')
finally:
    aa.COMMAND_OWNERS.reset(token)
'''
    result = subprocess.run([sys.executable, "-c", code, str(Path(aa.__file__).parent), str(escaped), str(controller)],
                            capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout == b"controller descendants reaped\n"


@pytest.mark.parametrize("stage", ["load", "remove", "revalidation"])
def test_subprocess_teardown_cannot_obtain_a_new_budget(tmp_path, monkeypatch, stage):
    ex, events = fake_run_environment(tmp_path, monkeypatch)
    clock = [0.0]
    waits, killed = [], []
    monkeypatch.setattr(aa.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(aa, "start_time", lambda pid: 456)
    monkeypatch.setattr(aa.os, "getsid", lambda pid: pid)
    monkeypatch.setattr(aa.time, "sleep", lambda duration: clock.__setitem__(0, clock[0] + duration))
    monkeypatch.setattr(aa, "descendants", lambda *a, **kw: None)
    monkeypatch.setattr(aa, "Process", lambda pid: SimpleNamespace(
        pid=pid, start=456, send=lambda sig: None, close=lambda: None, collect=lambda: False))
    class Selector:
        def register(self, *a):
            pass
        def get_map(self):
            return {}
        def close(self):
            pass
    class Child:
        pid = 123
        stdin = None
        stdout, stderr = io.BytesIO(), io.BytesIO()
        def poll(self):
            return None
        def send_signal(self, sig):
            killed.append((sig, clock[0]))
        def wait(self, *, timeout):
            waits.append((clock[0], timeout))
            clock[0] += timeout
            raise subprocess.TimeoutExpired("parser", timeout)
        def __exit__(self, *a):
            pytest.fail("unbounded Popen context-manager wait")
    monkeypatch.setattr(aa.selectors, "DefaultSelector", Selector)
    monkeypatch.setattr(aa.subprocess, "Popen", lambda *a, **kw: Child())
    def command():
        aa.bounded(["parser"], deadline=10)
    def run_arm(name):
        ex.loaded = True
        if stage == "load":
            command()
        return arm() if name == "baseline" else arm(result=0)
    monkeypatch.setattr(ex, "arm", run_arm)
    original_parse = ex.parse
    def parse(name, operation):
        if operation == "remove" and stage == "revalidation":
            monkeypatch.setattr(aa, "validate_inputs", lambda *a, **kw: command())
            return aa.Experiment.parse(ex, name, operation)
        if operation == "remove" and stage == "remove":
            command()
        original_parse(name, operation)
    monkeypatch.setattr(ex, "parse", parse)
    result = ex.run()
    assert waits == [(0, 9)] and clock[0] == 10
    assert (signal.SIGTERM, 9) in killed and (signal.SIGKILL, 9) in killed
    assert Child.stdout.closed and Child.stderr.closed
    assert result["cleanup"]["status"] == "failed" and result["outcome"] == "inconclusive"
    assert ex.namespace.path.exists() and ex.commands
    assert result["controller_commands"][0]["processes"] == [{"pid": 123, "start": 456}]
    assert ex.commands[0].cleanup_end == 10
    if stage == "load":
        assert ("baseline.policy", "remove") not in events
    os.close(ex.namespace.fd)


def test_expired_cleanup_still_removes_exact_namespace_and_reports_failed_proof(tmp_path, monkeypatch):
    ex, events = fake_run_environment(tmp_path, monkeypatch)
    clock = [0.0]
    monkeypatch.setattr(aa.time, "monotonic", lambda: clock[0])
    def run_arm(name):
        ex.loaded = True
        return arm() if name == "baseline" else arm(result=0)
    monkeypatch.setattr(ex, "arm", run_arm)
    original_parse = ex.parse
    def parse(name, operation):
        if operation == "remove":
            clock[0] = ex.cleanup_end + 1
            raise aa.Inconclusive("cleanup deadline")
        original_parse(name, operation)
    monkeypatch.setattr(ex, "parse", parse)
    result = ex.run()
    assert result["cleanup"]["status"] == "failed" and result["outcome"] == "inconclusive"
    assert not ex.namespace.path.exists() and "root_after" not in result
    assert result["cleanup"]["owned_target"] == str(ex.namespace.path)


def test_host_mount_escapes_decode_without_relaxing_fixture_mount_gate():
    text = r"11 1 8:1 /root\040space /mnt\134path rw - ext4 /dev/sda rw"
    row = aa.mount_rows(text, host=True)[0]
    assert row["root"] == "/root space" and row["path"] == "/mnt\\path"
    with pytest.raises(aa.Inconclusive, match="escaped mount path"):
        aa.mount_rows(text)
    with pytest.raises(aa.Inconclusive, match="unknown host mount escape"):
        aa.mount_rows(text.replace(r"\040", r"\999"), host=True)
