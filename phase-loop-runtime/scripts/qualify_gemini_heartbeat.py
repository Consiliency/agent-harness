#!/usr/bin/env python3
"""Observe the real brokered route and validate distinct qualification records."""
import argparse
from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import select
import shlex
import signal
import subprocess
import sys
import threading
import time

from phase_loop_runtime import gemini_heartbeat as gh
from phase_loop_runtime import panel_invoker as panel
from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD
from phase_loop_runtime.advisor_board.backing import harden_subscription_model


class QualificationFailure(ValueError):
    """A diagnostic raised with a fixed, content-free message by this driver."""


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_records(record, *, expected_source_sha256, expected_image_sha256,
                     expected_help_sha256, expected_profile_sha256, expected_helper_sha256=None):
    """Require external input pins and cross-record facts, not self-hashes alone."""
    def require(condition):
        if not condition:
            raise QualificationFailure("gemini qualification record rejected")

    def hash_value(value):
        require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None)

    try:
        require(record["schema"] == "gemini_heartbeat_qualification.v1")
        operation = record["operation"]
        require(operation in ("completion", "cancel", "owner-loss"))
        require(record["source_sha256"] == expected_source_sha256 and bool(expected_source_sha256))
        require(record["image_sha256"] == expected_image_sha256)
        require(record["help_sha256"] == expected_help_sha256)
        helper_pins = expected_helper_sha256 or {}
        require(record.get("helper_sha256", {}) == helper_pins)
        allowed_images = {expected_image_sha256, *helper_pins.values()}
        profile = record["profile"]
        require(profile["id"] == gh.PROFILE_ID and profile["home"] == gh.PRIVATE_HOME)
        require(profile["image_sha256"] == expected_image_sha256)
        hash_value(profile["settings_sha256"])
        require(record["profile_sha256"] == expected_profile_sha256 == digest(profile))
        invocation = record["invocation"]
        require(isinstance(invocation, str) and bool(invocation))
        monitor, broker, observer, result = (record[name] for name in ("monitoring", "broker", "observer", "result"))
        require(record["record_sha256"] == {name: digest(record[name]) for name in ("monitoring", "broker", "observer", "result")})
        require(monitor["schema"] == "review_monitoring.v1" and monitor["invocation"] == invocation)
        require(monitor["requested_policy"] == monitor["effective_policy"] == "heartbeat_only")
        require(monitor["model_deadline_s"] is None and monitor["silence_deadline_s"] is None)
        require(type(monitor["admission_expires_monotonic_ns"]) is int and monitor["admission_expires_monotonic_ns"] > 0)
        require(observer["invocation"] == invocation)
        require(observer["image_sha256"] == expected_image_sha256)
        require(observer["profile_sha256"] == expected_profile_sha256)
        require(observer["settings_sha256"] == profile["settings_sha256"])
        for key in ("image_readonly", "home_removed", "init_exited", "owned_fds_closed",
                    "sandbox_network_filtered", "network_rules_verified",
                    "credential_target_regular_before", "credential_target_regular_after"):
            require(observer[key] is True)
        require(observer["credential_home_source"] == "scrubbed_subscription_home")
        require(type(observer["network_rule_checks"]) is int and observer["network_rule_checks"] > 0)
        require(observer["live_namespace_members"] == [])
        require(observer["mount_namespace_users_after"] == [])
        require(type(observer["mount_namespace_inode"]) is int and observer["mount_namespace_inode"] > 0)
        require(type(observer["mount_namespace_device"]) is int)
        require(type(observer["mount_scan_unreadable_entries"]) is int and observer["mount_scan_unreadable_entries"] >= 0)
        fd_rows = observer["fd_cleanup_observations"]
        require(bool(fd_rows))
        for row in fd_rows:
            require(row["state"] in ("absent", "reused", "empty") and row["fd_count"] == 0)
        require({(row["pid"], row["start"]) for row in fd_rows} >= {
            (observer["init_pid"], observer["init_start"]),
            (observer["provider_pid"], observer["provider_start"]),
        })
        require(type(observer["init_pid"]) is int and observer["init_pid"] > 0)
        require(str(observer["init_start"]).isdigit())
        require(type(observer["pid_namespace_inode"]) is int and observer["pid_namespace_inode"] > 0)
        require(isinstance(observer["helpers"], list) and bool(observer["helpers"]))
        histories = {}
        for helper in observer["helpers"]:
            hash_value(helper["executable_sha256"])
            require(type(helper["pid"]) is int and helper["pid"] > 0 and str(helper["start"]).isdigit())
            require(helper["executable_sha256"] in allowed_images)
            key = (helper["pid"], helper["start"])
            if key == (observer["provider_pid"], observer["provider_start"]) and histories.get(key) == expected_image_sha256:
                require(helper["executable_sha256"] == expected_image_sha256)
            histories[key] = helper["executable_sha256"]
            if helper.get("is_agy"):
                require(helper["executable_sha256"] == expected_image_sha256)
        require(any(h["executable_sha256"] == expected_image_sha256 and h.get("is_agy") is True
                    and (h["pid"], h["start"]) == (observer["provider_pid"], observer["provider_start"])
                    for h in observer["helpers"]))
        argv = observer["argv"]
        require(isinstance(argv, list) and len(argv) == 14)
        require(argv == [gh.PRIVATE_HOME + "/agy", "--model", harden_subscription_model("gemini", argv[2], None),
                         "--sandbox", "--mode", "plan", "--disable-slash-commands", "--input-format", "stream-json",
                         "--output-format", "stream-json", "--print=", "--print-timeout", "0"])
        request = record["request"]
        for key in ("artifact_sha256", "instructions_sha256", "provider_input_sha256", "provider_transport_sha256"):
            hash_value(request[key])
        if operation == "owner-loss":
            require(broker is None and result is None and monitor["terminal_reason"] is None)
            kill = observer["kill_event"]
            require(kill["target"] == "invoker" and kill["signal"] == signal.SIGKILL)
            require(type(kill["pid"]) is int and kill["pid"] > 0 and str(kill["start"]).isdigit())
            return
        require(observer["kill_event"] is None)
        require(broker["schema"] == "parent_unix_broker_v1" and broker["operation_deadline_s"] is None)
        require(broker["stage_bundle_sha256"] == request["artifact_sha256"])
        require(broker["stage_instructions_sha256"] == request["instructions_sha256"])
        issued, expiry = broker["leg_authorization_issued_monotonic_ns"], broker["leg_authorization_expires_monotonic_ns"]
        require(type(issued) is int and type(expiry) is int and 0 <= issued < expiry)
        require(expiry - issued <= 10000000000)
        policy = broker["monitoring"]
        require(policy["schema"] == "review_monitoring.v1")
        require(policy["requested_policy"] == policy["effective_policy"] == "heartbeat_only")
        require(policy["operation_deadline_s"] is None and policy["authorization_expiry_scope"] == "admission_only")
        require(policy["admission_expires_monotonic_ns"] == expiry)
        require(monitor["admission_expires_monotonic_ns"] == expiry)
        require(broker["provider_namespace_identity"] == {
            "init_pid": observer["init_pid"], "init_start": observer["init_start"],
            "pid_namespace_device": observer["pid_namespace_device"],
            "pid_namespace_inode": observer["pid_namespace_inode"],
        })
        require(broker["provider_namespace_quiescence"]["init_exited"] is True)
        require(broker["provider_namespace_quiescence"]["live_members"] == [])
        shape = argv + ["<STDIN_SEALED_INLINE_PROMPT>"]
        require(broker["provider_argv_shape"] == shape)
        require(broker["provider_argv_sha256"] == sha256("\0".join(shape).encode()).hexdigest())
        require(broker["provider_isolation_profile"] == profile["id"])
        require(broker["provider_profile_sha256"] == expected_profile_sha256)
        require(broker["provider_agy_settings_sha256"] == profile["settings_sha256"])
        require(broker["provider_input_sha256"] == broker["provider_prompt_sha256"] == request["provider_input_sha256"])
        require(broker["provider_transport_sha256"] == request["provider_transport_sha256"])
        for key in ("provider_agy_home_cleanup_verified", "sandbox_network_filtered", "child_quiescent",
                    "broker_thread_quiescent", "provider_adapter_quiescent", "cleanup_root_removed", "host_secret_probe_removed"):
            require(broker[key] is True)
        if operation == "completion":
            require(monitor["terminal_reason"] == "completed")
            require(result["status"] == broker["provider_response_status"] == "OK")
            require(isinstance(result["text"], str) and bool(result["text"].strip()) and result["detail"] is None)
            require(panel.terminal_verdict(result["text"]) is not None)
            require(broker["provider_response_sha256"] == sha256(result["text"].encode()).hexdigest())
            require(broker["provider_stream_outcome"] == "accepted")
            require(broker["provider_stream_acknowledgements_verified"] is True and broker["provider_stream_final_no_truncation"] is True)
        else:
            require(monitor["terminal_reason"] == "user_cancel")
            require(result == {"status": "UNAVAILABLE", "text": "", "detail": "review_operation_cancelled"})
            require(broker["provider_cancel_requested"] is True)
            require("provider_response_status" not in broker and "provider_response_sha256" not in broker)
    except (KeyError, TypeError, IndexError, AttributeError, OverflowError) as exc:
        raise QualificationFailure("gemini qualification record incomplete") from exc


def file_hash(path):
    value = sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


class HelperObserver:
    """Recheck executable identity on every sample, including same-PID execs."""
    def __init__(self, image_sha256, helper_sha256, provider_identity=None):
        self.image_sha256 = image_sha256
        self.provider_identity = provider_identity
        self.allowed = {image_sha256, *helper_sha256.values()}
        self.latest = {}
        self.hashes = {}
        self.records = []
        self.rejected_image = None

    def observe(self, pid, start):
        path = Path(f"/proc/{pid}/exe")
        info = path.stat()
        identity = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        value = self.hashes.get(identity)
        if value is None:
            value = file_hash(path)
            after = path.stat()
            if identity != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise QualificationFailure("qualification executable changed during measurement")
            self.hashes[identity] = value
        if gh._proc_stat(pid)[2] != start:
            raise QualificationFailure("qualification helper process identity changed")
        key = (pid, start)
        if value not in self.allowed or (key == self.provider_identity and value != self.image_sha256):
            self.rejected_image = {"pid": pid, "start": start, "executable_sha256": value,
                                   "executable_path": os.readlink(path)}
            raise QualificationFailure("qualification helper executable is outside the registered identity policy")
        if self.latest.get(key) != value:
            self.records.append({"pid": pid, "start": start, "executable_sha256": value,
                                 "is_agy": value == self.image_sha256})
            self.latest[key] = value


def helper_pins(extra_images=()):
    paths = [Path("/usr/bin/bwrap"), Path("/usr/bin/setpriv"), *map(Path, extra_images)]
    return {str(path.resolve()): file_hash(path) for path in paths}


def validate_directory(root, **expected):
    registered = sorted(root.rglob("preregistration.json"))
    receipts = sorted(root.rglob("qualification.json"))
    if not registered or list(root.rglob("failure.json")):
        raise QualificationFailure("qualification has no registered attempts or retains a failed attempt")
    if {path.parent for path in registered} != {path.parent for path in receipts}:
        raise QualificationFailure("qualification registered attempt set is incomplete")
    operations = []
    for path in registered:
        preregistration = json.loads(path.read_text())
        record = json.loads(path.with_name("qualification.json").read_text())
        if preregistration.get("attempt_limit") != 1:
            raise QualificationFailure("qualification attempt limit differs from one")
        for key in ("operation", "source_sha256", "image_sha256", "help_sha256", "profile", "profile_sha256", "request", "helper_sha256"):
            if preregistration.get(key) != record.get(key):
                raise QualificationFailure("qualification receipt differs from its preregistration")
        artifact = path.with_name("artifact.md").read_text()
        brief = path.with_name("brief.md").read_text()
        prompt = panel._render_broker_inline_prompt(artifact, brief, "review")
        request = {"artifact_sha256": sha256(artifact.encode()).hexdigest(),
                   "instructions_sha256": sha256(brief.encode()).hexdigest(),
                   "provider_input_sha256": sha256(prompt.encode()).hexdigest(),
                   "provider_transport_sha256": sha256(panel._broker_gemini_stream_protocol(prompt).transport.encode()).hexdigest()}
        if record["request"] != request or file_hash(path.with_name("agy-help.txt")) != expected["expected_help_sha256"]:
            raise QualificationFailure("qualification retained input bytes do not bind the receipt")
        admission = json.loads(path.with_name("admission-observation.json").read_text())
        for key in ("invocation", "argv", "image_sha256", "profile_sha256", "settings_sha256",
                    "init_pid", "init_start", "provider_pid", "provider_start", "pid_namespace_device", "pid_namespace_inode",
                    "mount_namespace_device", "mount_namespace_inode"):
            if admission[key] != record["observer"][key]:
                raise QualificationFailure("qualification admission observation differs from the receipt")
        if admission["monitoring"]["invocation"] != record["invocation"] or admission["monitoring"]["terminal_reason"] is not None:
            raise QualificationFailure("qualification admission monitor is not the live operation")
        for key in ("schema", "requested_policy", "effective_policy", "model_deadline_s",
                    "silence_deadline_s", "admission_expires_monotonic_ns"):
            if admission["monitoring"][key] != record["monitoring"][key]:
                raise QualificationFailure("qualification admission policy differs from the receipt")
        terminal_path = path.with_name("terminal.json")
        if record["operation"] == "owner-loss":
            if terminal_path.exists():
                raise QualificationFailure("qualification owner-loss retains a fabricated terminal record")
        elif json.loads(terminal_path.read_text()) != {key: record[key] for key in ("monitoring", "broker", "result")}:
            raise QualificationFailure("qualification terminal records differ from the receipt")
        validate_records(record, **expected)
        operations.append(record["operation"])
    if len(set(operations)) != len(operations):
        raise QualificationFailure("qualification repeats a registered operation")
    return {"validated": len(receipts), "operations": operations,
            "route_qualified": sorted(operations) == ["cancel", "completion", "owner-loss"]}


def source_pins():
    source = Path(panel.__file__).parent
    files = sorted(source.rglob("*.py"))
    files.append(Path(__file__).resolve())
    return {str(path.relative_to(source)) if path.is_relative_to(source) else path.name: file_hash(path) for path in files}


def profile_description():
    return {"id": gh.PROFILE_ID, "image_sha256": gh.QUALIFIED_IMAGE_SHA256,
            "settings_sha256": sha256(panel._broker_agy_settings_bytes()).hexdigest(), "home": gh.PRIVATE_HOME}


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def write_failure(root, exc, stage, helpers, observed_processes):
    value = {"schema": "gemini_heartbeat_qualification_failure.v1",
             "exception_type": type(exc).__name__, "stage": stage,
             "reason": str(exc) if isinstance(exc, QualificationFailure) else "qualification local failure",
             "helpers": helpers.records, "rejected_image": helpers.rejected_image,
             "observed_processes": list(observed_processes.values()),
             "qualification_passed": False, "same_candidate_retry_authorized": False}
    path = root / "failure.json"
    if stage == "observer_cleanup" and path.exists():
        original = json.loads(path.read_text())
        original["cleanup_failure"] = value
        value = original
    write_json(path, value)


def process_table():
    table = {}
    for path in Path("/proc").iterdir():
        if not path.name.isdigit():
            continue
        try:
            state, parent, start = gh._proc_stat(int(path.name))
            table[int(path.name)] = {"state": state, "parent": parent, "start": start}
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    return table


def cleanup_observations(observer, held):
    fd_rows = []
    for pid, start in held:
        try:
            current_start = gh._proc_stat(pid)[2]
            if current_start != start:
                state, count = "reused", 0
            else:
                count = len(list(Path(f"/proc/{pid}/fd").iterdir()))
                state = "empty" if count == 0 else "open"
        except (FileNotFoundError, ProcessLookupError):
            state, count = "absent", 0
        fd_rows.append({"pid": pid, "start": start, "state": state, "fd_count": count})
    mounted, unreadable = [], 0
    for pid, row in process_table().items():
        try:
            ns = os.stat(f"/proc/{pid}/ns/mnt")
            if (ns.st_dev, ns.st_ino) != (observer["mount_namespace_device"], observer["mount_namespace_inode"]):
                continue
            mounts = Path(f"/proc/{pid}/mountinfo").read_text().splitlines()
            if any(line.split()[4] == gh.PRIVATE_HOME or line.split()[4].startswith(gh.PRIVATE_HOME + "/") for line in mounts):
                mounted.append({"pid": pid, "start": row["start"]})
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError:
            unreadable += 1
    return {"fd_cleanup_observations": fd_rows, "mount_namespace_users_after": mounted,
            "mount_scan_unreadable_entries": unreadable,
            "owned_fds_closed": all(row["fd_count"] == 0 for row in fd_rows), "home_removed": not mounted}


def finish_observer(proc, held, namespace_fd):
    error = None
    try:
        if proc is not None and proc.poll() is None:
            # Observer failure requests explicit cancellation; no thinking timer.
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
    finally:
        for fd in held.values():
            try:
                if not select.select([fd], [], [], 0)[0]:
                    try:
                        signal.pidfd_send_signal(fd, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    if not select.select([fd], [], [], 5)[0]:
                        raise QualificationFailure("qualification cleanup could not reap an observed process")
            except Exception as exc:
                error = error or exc
            finally:
                os.close(fd)
        if namespace_fd is not None:
            os.close(namespace_fd)
        if error is not None:
            raise error


def descendants(table, owner):
    result = {owner}
    while True:
        children = {pid for pid, row in table.items() if row["parent"] in result}
        if children <= result:
            return result - {owner}
        result.update(children)


def observe_owned_helpers(table, init_pid, helpers):
    # Nested PID namespaces still belong to the pinned init's descendant tree.
    for pid in {init_pid, *descendants(table, init_pid)}:
        try:
            if pid in table and table[pid]["state"] != "Z":
                helpers.observe(pid, table[pid]["start"])
        except (FileNotFoundError, ProcessLookupError):
            continue


_NS_GET_USERNS = 0xB701  # linux/nsfs.h: _IO(0xb7, 0x1)


def _network_owner_pid(pid):
    """The nearest ancestor-or-self of ``pid`` living in the user namespace that OWNS its
    network namespace. Since agent-harness#1052 an ordinary owned provider runs in a nested
    user namespace with no capabilities, so entering the PROVIDER's user namespace cannot
    read the holder's egress rules; the owner's user namespace can."""
    import fcntl
    net_fd = os.open(f"/proc/{pid}/ns/net", os.O_RDONLY | os.O_CLOEXEC)
    try:
        owner_fd = fcntl.ioctl(net_fd, _NS_GET_USERNS)
    finally:
        os.close(net_fd)
    try:
        owner = os.fstat(owner_fd)
    finally:
        os.close(owner_fd)
    current = pid
    while current >= 1:  # pid 1 is checked too; its parent is 0
        user = os.stat(f"/proc/{current}/ns/user")
        if (user.st_dev, user.st_ino) == (owner.st_dev, owner.st_ino):
            return current
        current = int(Path(f"/proc/{current}/stat").read_text().rsplit(")", 1)[1].split()[1])
    raise QualificationFailure("qualification network namespace owner was not observed")


def inspect_network(pid):
    from phase_loop_runtime import sandbox_egress
    owner = _network_owner_pid(pid)
    # The PROVIDER's network namespace, entered with the credentials of the user namespace
    # that owns it (the holder's; the provider's own may be a capability-less child).
    admin = ["nsenter", f"--net=/proc/{pid}/ns/net"]
    own, target = os.stat("/proc/self/ns/user"), os.stat(f"/proc/{owner}/ns/user")
    if (own.st_dev, own.st_ino) != (target.st_dev, target.st_ino):  # setns to one's own is EINVAL
        admin += [f"--user=/proc/{owner}/ns/user", "--preserve-credentials"]
    rules = sandbox_egress.egress_rules()
    if not rules:
        raise QualificationFailure("qualification network rule set is empty")
    for rule in rules:
        check = shlex.split(rule.replace("-I OUTPUT 1", "-C OUTPUT", 1).replace("-A OUTPUT", "-C OUTPUT", 1))
        outcome = panel.run_provider([*admin, "iptables", *check], capture_output=True, timeout=10)
        if outcome.returncode != 0:
            raise QualificationFailure("qualification network rule observation failed")
    measured = panel.run_provider([*admin, "iptables", "-S", "OUTPUT"], capture_output=True, timeout=10)
    if measured.returncode != 0:
        raise QualificationFailure("qualification network policy observation failed")
    return {"network_rules_verified": True, "sandbox_network_filtered": True,
            "network_rules_sha256": sha256(measured.stdout).hexdigest(), "network_rule_checks": len(rules)}


def worker(root):
    cancel = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: cancel.set())
    signal.signal(signal.SIGINT, lambda *_: cancel.set())
    board = replace(DEFAULT_BOARD, name="gemini-heartbeat-qualification",
                    seats=tuple(s for s in DEFAULT_BOARD.seats if s.harness == "gemini"))
    result = panel.invoke_board(
        board, (root / "artifact.md").read_text(), brief_ref=str(root / "brief.md"),
        repo_dir=Path.cwd(), mode="review", monitoring_policy="heartbeat_only",
        stream_dir=root / "stream", cancel_event=cancel,
        review_policy=panel.ReviewLandingPolicy(("gemini",), False),
    )
    leg, = result.legs
    write_json(root / "terminal.json", {
        "monitoring": leg.review_monitoring, "broker": leg.harden_isolation_evidence,
        "result": {"status": leg.status, "text": leg.text, "detail": leg.detail},
    })


def run_operation(operation, root, help_evidence, extra_helpers=()):
    """External observer survives owner loss; no provider adapter is replaced."""
    subscription_env = panel._broker_subscription_env()
    image_path = gh.require_capability(subscription_env)
    if not subscription_env.get("HOME"):
        raise QualificationFailure("qualification credential HOME is unavailable")
    credential = Path(subscription_env["HOME"]) / ".gemini/antigravity-cli/antigravity-oauth-token"
    credential_regular_before = credential.is_file()
    if not credential_regular_before:
        raise QualificationFailure("qualification credential target is unavailable")
    if file_hash(help_evidence) != gh.QUALIFIED_HELP_SHA256:
        raise QualificationFailure("qualification help input differs from the measured candidate")
    root.mkdir(mode=0o700, parents=False, exist_ok=False)
    artifact = (
        "This is a compatibility qualification, not a governance vote.\n"
        "Review these proposed requirements for internal consistency: a review operation has one "
        "selected subscription provider; no deadline limits model thinking or silence; local "
        "admission and cleanup have finite bounds; cancellation is explicit; no retry silently "
        "substitutes another session; local process cleanup does not prove remote billing settlement.\n"
        "Explain each distinction, then give one terminal verdict. Do not use tools.\n"
    )
    brief = "Review only the supplied text. No tools, commands, files, network, browser, agents or further sessions. End with exactly AGREE, PARTIALLY AGREE or DISAGREE.\n"
    (root / "artifact.md").write_text(artifact)
    (root / "brief.md").write_text(brief)
    (root / "agy-help.txt").write_bytes(Path(help_evidence).read_bytes())
    sources, profile, registered_helpers = source_pins(), profile_description(), helper_pins(extra_helpers)
    prompt = panel._render_broker_inline_prompt(artifact, brief, "review")
    transport = panel._broker_gemini_stream_protocol(prompt).transport
    request = {"artifact_sha256": sha256(artifact.encode()).hexdigest(),
               "instructions_sha256": sha256(brief.encode()).hexdigest(),
               "provider_input_sha256": sha256(prompt.encode()).hexdigest(),
               "provider_transport_sha256": sha256(transport.encode()).hexdigest()}
    preregistration = {"operation": operation, "attempt_limit": 1, "source_sha256": sources,
                       "helper_sha256": registered_helpers,
                       "image_sha256": file_hash(image_path), "help_sha256": gh.QUALIFIED_HELP_SHA256,
                       "profile": profile, "profile_sha256": digest(profile), "request": request,
                       "trigger": "observed provider progress after admission" if operation == "cancel" else "observed qualified provider admission after independent local measurements",
                       "model_deadline_s": None, "silence_deadline_s": None}
    write_json(root / "preregistration.json", preregistration)
    held, observed_processes = {}, {}
    helpers = HelperObserver(gh.QUALIFIED_IMAGE_SHA256, registered_helpers)
    namespace_fd = None
    observer = None
    monitor = None
    proc = None
    completed = False
    stage = "launch"
    try:
        with (root / "worker.log").open("wb") as log:
            proc = panel.launch_provider([sys.executable, str(Path(__file__).resolve()), "--worker", str(root)],
                                         stdout=log, stderr=log, start_new_session=True)
        owner_start = gh._proc_stat(proc.pid)[2]
        triggered = False
        while proc.poll() is None:
            stage = "admission_observation" if observer is None else "helper_observation"
            table = process_table()
            children = descendants(table, proc.pid)
            for pid in children:
                row = table[pid]
                key = (pid, row["start"])
                if key in held or row["state"] == "Z":
                    continue
                try:
                    fd = os.pidfd_open(pid)
                    if gh._proc_stat(pid)[2] != row["start"]:
                        os.close(fd)
                        raise QualificationFailure("qualification process identity changed")
                    held[key] = fd
                    observed_processes[key] = {"pid": pid, "start": row["start"],
                                               "executable_sha256": file_hash(f"/proc/{pid}/exe")}
                except (FileNotFoundError, ProcessLookupError):
                    continue
            if observer is None:
                for pid in sorted(children):
                    try:
                        argv = Path(f"/proc/{pid}/cmdline").read_bytes().rstrip(b"\0").decode(errors="replace").split("\0")
                        if not argv or argv[0] != gh.PRIVATE_HOME + "/agy":
                            continue
                        image_hash = file_hash(f"/proc/{pid}/exe")
                        if image_hash != gh.QUALIFIED_IMAGE_SHA256:
                            raise QualificationFailure("qualification observed an unqualified provider image")
                        ns = os.stat(f"/proc/{pid}/ns/pid")
                        init = None
                        for candidate in children:
                            cns = os.stat(f"/proc/{candidate}/ns/pid")
                            status = Path(f"/proc/{candidate}/status").read_text()
                            ids = next(line for line in status.splitlines() if line.startswith("NSpid:")).split()[1:]
                            if cns.st_ino == ns.st_ino and ids[-1] == "1":
                                init = candidate
                                break
                        if init is None:
                            raise QualificationFailure("qualification namespace init was not observed")
                        namespace_fd = os.open(f"/proc/{init}/ns/pid", os.O_RDONLY | os.O_CLOEXEC)
                        held_namespace = os.fstat(namespace_fd)
                        if (held_namespace.st_dev, held_namespace.st_ino) != (ns.st_dev, ns.st_ino):
                            raise QualificationFailure("qualification namespace identity changed")
                        provider_root = Path(f"/proc/{pid}/root")
                        settings = provider_root / (gh.PRIVATE_HOME.lstrip("/") + "/.gemini/antigravity-cli/settings.json")
                        if file_hash(settings) != profile["settings_sha256"]:
                            raise QualificationFailure("qualification settings identity mismatch")
                        mountinfo = Path(f"/proc/{pid}/mountinfo").read_text().splitlines()
                        image_mount = [line.split() for line in mountinfo if line.split()[4] == gh.PRIVATE_HOME + "/agy"]
                        if len(image_mount) != 1 or "ro" not in image_mount[0][5].split(","):
                            raise QualificationFailure("qualification executable mount is not read-only")
                        review_dir = Path(os.readlink(f"/proc/{pid}/cwd")).parent / "review"
                        if file_hash(review_dir / "review-bundle.md") != request["artifact_sha256"] or file_hash(review_dir / "review-instructions.md") != request["instructions_sha256"]:
                            raise QualificationFailure("qualification observed another staged request")
                        network = inspect_network(pid)
                        if gh._proc_stat(pid)[2] != table[pid]["start"] or gh._proc_stat(init)[2] != table[init]["start"]:
                            raise QualificationFailure("qualification provider identity changed")
                        mount_ns = os.stat(f"/proc/{pid}/ns/mnt")
                        observer = {"argv": argv, "image_sha256": image_hash, "image_readonly": True,
                                    "profile_sha256": digest(profile), "settings_sha256": profile["settings_sha256"],
                                    "init_pid": init, "init_start": table[init]["start"],
                                    "provider_pid": pid, "provider_start": table[pid]["start"],
                                    "pid_namespace_inode": ns.st_ino, "pid_namespace_device": ns.st_dev,
                                    "mount_namespace_inode": mount_ns.st_ino, "mount_namespace_device": mount_ns.st_dev,
                                    "kill_event": None, **network}
                        helpers.provider_identity = (pid, table[pid]["start"])
                        break
                    except (FileNotFoundError, ProcessLookupError):
                        if namespace_fd is not None:
                            os.close(namespace_fd)
                            namespace_fd = None
                        continue
            if observer is not None:
                observe_owned_helpers(table, observer["init_pid"], helpers)
                paths = list((root / "stream").glob("*/seat-0.json"))
                if len(paths) == 1:
                    monitor = json.loads(paths[0].read_text())
                if not triggered and monitor is not None and (
                    operation != "cancel" or monitor["observation_state"] == "progress_observed"
                ):
                    observer["invocation"] = monitor["invocation"]
                    write_json(root / "admission-observation.json", {**observer, "helpers": helpers.records, "monitoring": monitor})
                    if operation == "owner-loss":
                        if gh._proc_stat(proc.pid)[2] != owner_start:
                            raise QualificationFailure("qualification owner identity changed")
                        observer["kill_event"] = {"target": "invoker", "pid": proc.pid, "start": owner_start, "signal": signal.SIGKILL}
                        proc.kill()
                    elif operation == "cancel":
                        proc.send_signal(signal.SIGTERM)
                    triggered = True
            time.sleep(.02)
        proc.wait()
        stage = "terminal_observation"
        if observer is None or monitor is None or not triggered:
            raise QualificationFailure("qualification ended before complete admission observation")
        if operation == "owner-loss":
            if proc.returncode != -signal.SIGKILL:
                raise QualificationFailure("qualification owner-loss exit differs from requested signal")
            broker, result = None, None
        else:
            terminal = json.loads((root / "terminal.json").read_text())
            monitor, broker, result = (terminal[name] for name in ("monitoring", "broker", "result"))
        stage = "cleanup_observation"
        deadline = time.monotonic() + 5  # finite local cleanup, after provider/owner terminal event
        while any(not select.select([fd], [], [], 0)[0] for fd in held.values()):
            if time.monotonic() >= deadline:
                raise QualificationFailure("qualification observed a surviving owned process")
            time.sleep(.02)
        live = []
        for pid, row in process_table().items():
            if row["state"] == "Z":
                continue
            try:
                ns = os.stat(f"/proc/{pid}/ns/pid")
                if (ns.st_dev, ns.st_ino) == (observer["pid_namespace_device"], observer["pid_namespace_inode"]):
                    live.append({"pid": pid, "start": row["start"]})
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue
        observer.update(helpers=helpers.records, owned_processes=list(observed_processes.values()),
                        credential_home_source="scrubbed_subscription_home",
                        credential_target_regular_before=credential_regular_before,
                        credential_target_regular_after=credential.is_file(),
                        init_exited=bool(select.select([held[(observer["init_pid"], observer["init_start"])]], [], [], 0)[0]),
                        live_namespace_members=live, **cleanup_observations(observer, held))
        record = {**preregistration, "schema": "gemini_heartbeat_qualification.v1", "invocation": monitor["invocation"],
                  "monitoring": monitor, "broker": broker, "observer": observer, "result": result}
        record["record_sha256"] = {name: digest(record[name]) for name in ("monitoring", "broker", "observer", "result")}
        stage = "validation"
        if source_pins() != sources:
            raise QualificationFailure("qualification runtime changed during observation")
        validate_records(record, expected_source_sha256=sources, expected_image_sha256=gh.QUALIFIED_IMAGE_SHA256,
                         expected_help_sha256=gh.QUALIFIED_HELP_SHA256, expected_profile_sha256=digest(profile),
                         expected_helper_sha256=registered_helpers)
        completed = True
    except BaseException as exc:
        write_failure(root, exc, stage, helpers, observed_processes)
        raise
    finally:
        try:
            finish_observer(proc, held, namespace_fd)
        except BaseException as exc:
            write_failure(root, exc, "observer_cleanup", helpers, observed_processes)
            raise
    write_json(root / "qualification.json", record)
    return completed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--validate", type=Path)
    group.add_argument("--operation", choices=("completion", "cancel", "owner-loss"))
    group.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--help-evidence", type=Path)
    parser.add_argument("--helper-image", type=Path, action="append", default=[],
                        help="Pre-register an additional expected helper executable by its actual bytes")
    args = parser.parse_args()
    if args.worker is not None:
        worker(args.worker.resolve())
    elif args.validate is not None:
        result = validate_directory(args.validate, expected_source_sha256=source_pins(),
                         expected_image_sha256=gh.QUALIFIED_IMAGE_SHA256, expected_help_sha256=gh.QUALIFIED_HELP_SHA256,
                         expected_profile_sha256=digest(profile_description()), expected_helper_sha256=helper_pins(args.helper_image))
        print(json.dumps(result))
        return 0 if result["route_qualified"] else 2
    else:
        if args.output is None or args.help_evidence is None:
            parser.error("--operation requires --output and measured --help-evidence")
        run_operation(args.operation, args.output.resolve(), args.help_evidence, args.helper_image)


if __name__ == "__main__":
    raise SystemExit(main())
