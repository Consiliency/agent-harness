"""Synthetic adapters test orchestration; these tests never load policy or prove enforcement."""

from __future__ import annotations

import ctypes
import errno
import io
import json
import os
from pathlib import Path
import signal
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
    monkeypatch.setattr(aa, "tools", lambda: {})
    monkeypatch.setattr(aa, "fixture_inputs", lambda: {})
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
        def __init__(self, *args):
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
        def __init__(self, *a):
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
        aa.bounded([sys.executable, "-c", "import time; time.sleep(2)"], timeout=0.02)


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
    monkeypatch.setattr(aa, "validate_inputs", lambda *a: None)
    monkeypatch.setattr(aa, "journal_cursor", lambda: "cursor")
    monkeypatch.setattr(aa, "prctl", lambda *a: None)
    monkeypatch.setattr(aa, "root_policy", lambda: {"disk": "stable", "loaded": "stable"})
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
        monkeypatch.setattr(aa, "root_policy", lambda: next(snapshots))
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
    monkeypatch.setattr(aa, "validate_inputs", lambda *a: events.append("validated"))
    monkeypatch.setattr(aa, "bwrap_argv", lambda *a: ["/usr/bin/bwrap", "fixed"])
    monkeypatch.setattr(aa, "drop_identity", lambda u, g: events.append(("drop", u, g)))
    monkeypatch.setattr(aa.os, "execve", lambda *a: events.append(("exec", *a)))
    aa.trampoline(ex.root, UID, GID, NS)
    assert events[:2] == ["validated", ("drop", UID, GID)]
    assert events[2] == ("exec", "/usr/bin/bwrap", ["/usr/bin/bwrap", "fixed"], aa.ENV)


def test_bwrap_fixture_exposes_no_host_directory_or_arbitrary_command(tmp_path):
    manifest = {"fixture": {"files": {aa.PYTHON: {"path": "/usr/bin/python3.14"}},
                             "encodings": "/usr/lib/python3.14/encodings"}}
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


def test_observer_requires_positive_verified_unshare_entry_and_exit(monkeypatch):
    worker = SimpleNamespace(pid=45, start=123, alive=lambda: True)
    observer = aa.Observer.__new__(aa.Observer)
    observer.worker, observer.active, observer.pending = worker, {45: worker}, {}
    observer.records, observer.exits = [], {}
    observer.expected_label = gate()["label"]
    original_read = Path.read_text
    original_resolve = Path.resolve
    monkeypatch.setattr(Path, "read_text", lambda p: gate()["label"] if str(p) == "/proc/45/attr/current" else original_read(p))
    monkeypatch.setattr(Path, "resolve", lambda p, **k: Path("/usr/bin/unshare").absolute() if str(p) in ("/proc/45/exe", "/usr/bin/unshare") else original_resolve(p, **k))
    states = iter([(45, ((signal.SIGTRAP | 0x80) << 8) | 0x7f),
                   (45, ((signal.SIGTRAP | 0x80) << 8) | 0x7f), (45, 0)])
    monkeypatch.setattr(aa.os, "waitpid", lambda *a: next(states))
    monkeypatch.setattr(aa.platform, "machine", lambda: "x86_64")
    op = iter([1, 2])
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
    assert events == ["GO"] and len(records) == 1 and records[0]["return"] == 0
    assert records[0]["flags"] == 0x10020000 and records[0]["start"] == 123


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
        def __init__(self, *a):
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
