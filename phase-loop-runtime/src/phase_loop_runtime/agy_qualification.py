"""First-use self-qualification of genuine upstream agy releases (agent-harness#1076).

This module is the packaged qualification driver (formerly only
``scripts/qualify_gemini_heartbeat.py``, which is now a shim over it), the per-user
qualification store, and the lookup / first-use admission for a Gemini heartbeat image
whose digest is not release-qualified.

Import discipline: ``panel_invoker`` imports ``gemini_heartbeat`` at module level and
this module is imported lazily from ``gemini_heartbeat``; every ``panel_invoker`` and
``advisor_board`` import here is therefore lazy, and ``ROUTE_CORE`` stays importable
with the standard library alone (``scripts/verify_qualified_agy_image.py`` imports it).
"""
import argparse
import contextlib
import ctypes
from dataclasses import replace
import fcntl
from hashlib import sha256
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import select
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time

from . import __version__
from . import agy_provenance
from . import gemini_heartbeat as gh

# The files an installed wheel runs the qualified route from (agent-harness#1076 D2).
# The local record key and the CI ``--route-core`` gate hash exactly these files;
# ``verify_qualified_agy_image.py`` imports this tuple. The upstream watch
# (``agy_watch.py``) is deliberately outside it.
ROUTE_CORE = ("gemini_heartbeat.py", "agy_qualification.py", "agy_provenance.py")

SELF_QUALIFICATION_FAILED = "gemini_heartbeat_self_qualification_failed"
SELF_QUALIFICATION_UNAVAILABLE = "gemini_heartbeat_self_qualification_unavailable"
STORE_UNSAFE = "gemini_heartbeat_self_qualification_store_unsafe"
CANCELLED = "review_operation_cancelled"
OPERATIONS = ("completion", "cancel", "owner-loss")
_SHIM = Path(__file__).resolve().parents[2] / "scripts" / "qualify_gemini_heartbeat.py"
_SRC = Path(__file__).resolve().parents[1]


def _panel():
    from . import panel_invoker
    return panel_invoker


def __getattr__(name):
    # ``module.panel`` keeps working for callers (and tests) that patch panel_invoker.
    if name == "panel":
        return _panel()
    raise AttributeError(name)


def _harden_subscription_model(*args):
    from .advisor_board.backing import harden_subscription_model
    return harden_subscription_model(*args)


# --------------------------------------------------------------------- runtime identity

def runtime_identity(package_dir=None):
    """``__version__`` plus the digests of the INSTALLED route-core files (D2).

    Always this running package's own files, never a reviewed tree's: a board admits
    with the installed base runtime (agent-harness#1076 "Counting").
    """
    package_dir = Path(package_dir or Path(__file__).resolve().parent)
    return {"version": __version__,
            "route_core": {name: file_hash(package_dir / name) for name in ROUTE_CORE}}


# Driver reasons the failure classifier treats as transients (claude N2 on agent-harness#1130
# r2): named once here and used both where they are raised and by _classify_failure.
ENDED_BEFORE_ADMISSION = "qualification ended before complete admission observation"
LOCAL_FAILURE = "qualification local failure"


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
        require(argv == [gh.PRIVATE_HOME + "/agy", "--model", _harden_subscription_model("gemini", argv[2], None),
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
            require(_panel().terminal_verdict(result["text"]) is not None)
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
        prompt = _panel()._render_broker_inline_prompt(artifact, brief, "review")
        request = {"artifact_sha256": sha256(artifact.encode()).hexdigest(),
                   "instructions_sha256": sha256(brief.encode()).hexdigest(),
                   "provider_input_sha256": sha256(prompt.encode()).hexdigest(),
                   "provider_transport_sha256": sha256(_panel()._broker_gemini_stream_protocol(prompt).transport.encode()).hexdigest()}
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


def series_image(root, allowed=None):
    """The one qualified image a series measured, read from its preregistrations, never asserted."""
    allowed = gh.QUALIFIED_IMAGES if allowed is None else allowed
    images = {json.loads(path.read_text()).get("image_sha256") for path in root.rglob("preregistration.json")}
    if len(images) != 1 or next(iter(images)) not in allowed:
        raise QualificationFailure("qualification series does not measure exactly one qualified image")
    return next(iter(images))


def source_pins():
    """Every package source, plus the release-route shim when this is a source tree."""
    source = Path(__file__).resolve().parent
    pins = {str(path.relative_to(source)): file_hash(path) for path in sorted(source.rglob("*.py"))}
    if _SHIM.is_file():
        pins[_SHIM.name] = file_hash(_SHIM)
    return pins


def profile_description(image_sha256):
    return {"id": gh.PROFILE_ID, "image_sha256": image_sha256,
            "settings_sha256": sha256(_panel()._broker_agy_settings_bytes()).hexdigest(), "home": gh.PRIVATE_HOME}


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def write_failure(root, exc, stage, helpers, observed_processes):
    value = {"schema": "gemini_heartbeat_qualification_failure.v1",
             "exception_type": type(exc).__name__, "stage": stage,
             "reason": str(exc) if isinstance(exc, QualificationFailure) else LOCAL_FAILURE,
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
        outcome = _panel().run_provider([*admin, "iptables", *check], capture_output=True, timeout=10)
        if outcome.returncode != 0:
            raise QualificationFailure("qualification network rule observation failed")
    measured = _panel().run_provider([*admin, "iptables", "-S", "OUTPUT"], capture_output=True, timeout=10)
    if measured.returncode != 0:
        raise QualificationFailure("qualification network policy observation failed")
    return {"network_rules_verified": True, "sandbox_network_filtered": True,
            "network_rules_sha256": sha256(measured.stdout).hexdigest(), "network_rule_checks": len(rules)}


def run_operation(operation, root, help_evidence, extra_helpers=(), *, image, expected_help_sha256,
                  cancel_event=None):
    """External observer survives owner loss; no provider adapter is replaced.

    ``image`` is a VerifiedImage: the worker receives an independent read of its sealed
    memfd as an inherited fd and re-proves the seals itself; no path is opened.
    """
    subscription_env = _panel()._broker_subscription_env()
    try:
        gh._local_capabilities()
    except (OSError, ValueError) as exc:
        raise QualificationFailure("qualification local capabilities are unavailable") from exc
    if not subscription_env.get("HOME"):
        raise QualificationFailure("qualification credential HOME is unavailable")
    credential = Path(subscription_env["HOME"]) / ".gemini/antigravity-cli/antigravity-oauth-token"
    credential_regular_before = credential.is_file()
    if not credential_regular_before:
        raise QualificationFailure("qualification credential target is unavailable")
    image_sha256 = image.sha256
    help_sha256 = expected_help_sha256
    if file_hash(help_evidence) != help_sha256:
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
    sources, profile, registered_helpers = source_pins(), profile_description(image_sha256), helper_pins(extra_helpers)
    prompt = _panel()._render_broker_inline_prompt(artifact, brief, "review")
    transport = _panel()._broker_gemini_stream_protocol(prompt).transport
    request = {"artifact_sha256": sha256(artifact.encode()).hexdigest(),
               "instructions_sha256": sha256(brief.encode()).hexdigest(),
               "provider_input_sha256": sha256(prompt.encode()).hexdigest(),
               "provider_transport_sha256": sha256(transport.encode()).hexdigest()}
    preregistration = {"operation": operation, "attempt_limit": 1, "source_sha256": sources,
                       "helper_sha256": registered_helpers,
                       "image_sha256": image_sha256, "help_sha256": help_sha256,
                       "profile": profile, "profile_sha256": digest(profile), "request": request,
                       "trigger": "observed provider progress after admission" if operation == "cancel" else "observed qualified provider admission after independent local measurements",
                       "model_deadline_s": None, "silence_deadline_s": None}
    write_json(root / "preregistration.json", preregistration)
    held, observed_processes = {}, {}
    helpers = HelperObserver(image_sha256, registered_helpers)
    namespace_fd = None
    observer = None
    monitor = None
    proc = None
    completed = False
    stage = "launch"
    try:
        image_fd = image.reopen()
        try:
            with (root / "worker.log").open("wb") as log:
                proc = _panel().launch_provider(
                    [sys.executable, "-I", "-c", _WORKER_BOOT, str(_SRC), "--worker", str(root),
                     "--image-fd", str(image_fd), "--parent-pid", str(os.getpid())],
                    stdout=log, stderr=log, start_new_session=True, pass_fds=(image_fd,))
        finally:
            os.close(image_fd)
        owner_start = gh._proc_stat(proc.pid)[2]
        triggered = False
        while proc.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                raise QualificationFailure(CANCELLED)
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
                        if image_hash != image_sha256:
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
            raise QualificationFailure(ENDED_BEFORE_ADMISSION)
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
        validate_records(record, expected_source_sha256=sources, expected_image_sha256=image_sha256,
                         expected_help_sha256=help_sha256, expected_profile_sha256=digest(profile),
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


# ------------------------------------------------------------------------------- store

_ENTRY_SCHEMA = "agy_qualification_entry.v1"
_ENTRY_TYPES = ("provenance", "qualified", "failed", "member_cache", "transient")
# After this many CONSECUTIVE transient attempts for one key, the image is refused with a
# failed entry (claude N2 on agent-harness#1130 r1): a deterministic incompatibility must not
# re-run help and a real completion on every board forever. The count resets when the key
# qualifies and is removed by ``agy-qualification clear``. Cancellation is not counted. A
# lock waiter that finds a transient recorded while it waited refuses without running
# anything and without counting, so N queued boards cost one attempt, not N (claude N1 on
# agent-harness#1130 r2).
MAX_TRANSIENT_ATTEMPTS = 3
_MAX_ENTRY_BYTES = 256 * 1024


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def read_machine_id(path="/etc/machine-id"):
    try:
        value = Path(path).read_text().strip()
    except OSError:
        return None
    return value if re.fullmatch(r"[0-9a-f]{32}", value) else None


def default_store_root(environ=None):
    environ = os.environ if environ is None else environ
    base = environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "phase-loop" / "agy-qualification"


class Store:
    """The per-user qualification store (agent-harness#1076 "Store and record").

    ``<root>/hosts/<machine>/`` holds one host's entries (namespaced so a shared
    ``$XDG_STATE_HOME`` never mixes hosts), its HMAC key and its lock. Every directory is
    0700 and every file 0600, owned by the euid and opened ``O_NOFOLLOW``; anything else
    makes the whole store absent (lookups) and refuses first use.

    Every entry is typed. Its MAC is computed over a context recomputed from the LIVE key
    (never the entry's own fields or filename) plus the euid and machine-id, and the entry
    type is part of that context, so one type can never stand in for another.
    """

    def __init__(self, root=None, *, euid=None, machine_id=None, lstat=os.lstat, fstat=os.fstat):
        self.root = Path(root) if root is not None else default_store_root()
        self.euid = os.geteuid() if euid is None else euid
        self.machine_id = read_machine_id() if machine_id is None else machine_id
        self._lstat, self._fstat = lstat, fstat

    @property
    def host_dir(self):
        return self.root / "hosts" / sha256(f"agy-store-host\0{self.machine_id}".encode()).hexdigest()[:32]

    # -- safety ------------------------------------------------------------------
    def _dir_ok(self, path):
        try:
            info = self._lstat(path)
        except FileNotFoundError:
            return None
        except OSError:
            return False
        return (stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode)
                and info.st_uid == self.euid and stat.S_IMODE(info.st_mode) == 0o700)

    def status(self):
        """``absent`` | ``ok`` | ``unsafe`` for this host's namespace."""
        if self.machine_id is None:
            return "unsafe"
        for path in (self.root, self.root / "hosts", self.host_dir):
            state = self._dir_ok(path)
            if state is None:
                return "absent"
            if not state:
                return "unsafe"
        try:
            self._key()
        except FileNotFoundError:
            return "absent"
        except (OSError, ValueError):
            return "unsafe"
        return "ok"

    def create(self):
        if self.machine_id is None:
            raise ValueError(SELF_QUALIFICATION_UNAVAILABLE)
        # Race-safe: two first uses may create the store at once (I3).
        for path in (self.root, self.root / "hosts", self.host_dir):
            if self._dir_ok(path) is None:
                try:
                    path.mkdir(mode=0o700, parents=path == self.root)
                except FileExistsError:
                    continue
                os.chmod(path, 0o700)
        if self.status() == "absent":
            try:
                self._write(self.host_dir / "key", secrets.token_bytes(32), exclusive=True)
            except FileExistsError:
                pass
        if self.status() != "ok":
            raise ValueError(STORE_UNSAFE)

    def _read(self, path):
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        try:
            info = self._fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != self.euid
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > _MAX_ENTRY_BYTES):
                raise ValueError(STORE_UNSAFE)
            return os.read(fd, _MAX_ENTRY_BYTES + 1)
        finally:
            os.close(fd)

    def _write(self, path, data, *, exclusive=False):
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            os.fchmod(fd, 0o600)
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        if exclusive:
            try:
                os.link(temporary, path)
            finally:
                os.unlink(temporary)
        else:
            os.replace(temporary, path)

    def _key(self):
        key = self._read(self.host_dir / "key")
        if len(key) != 32:
            raise ValueError(STORE_UNSAFE)
        return key

    # -- entries -----------------------------------------------------------------
    def _context(self, entry_type, context):
        if entry_type not in _ENTRY_TYPES:
            raise ValueError(STORE_UNSAFE)
        return {**context, "type": entry_type, "euid": self.euid, "machine_id": self.machine_id}

    def _path(self, entry_type, name_context):
        name = sha256(_canonical(self._context(entry_type, name_context))).hexdigest()
        return self.host_dir / f"{entry_type}-{name}.json"

    def _mac(self, key, entry_type, context, payload):
        return hmac.new(key, _canonical({"context": self._context(entry_type, context), "payload": payload}),
                        "sha256").hexdigest()

    def put(self, entry_type, name_context, context, payload):
        if self.status() != "ok":
            raise ValueError(STORE_UNSAFE)
        mac = self._mac(self._key(), entry_type, context, payload)
        self._write(self._path(entry_type, name_context),
                    _canonical({"schema": _ENTRY_SCHEMA, "type": entry_type, "payload": payload, "mac": mac}))

    def get(self, entry_type, name_context, context):
        """The entry's payload iff its MAC verifies against the LIVE context; else None."""
        if self.status() != "ok":
            return None
        try:
            raw = json.loads(self._read(self._path(entry_type, name_context)))
            if raw.get("schema") != _ENTRY_SCHEMA or raw.get("type") != entry_type:
                return None
            payload, mac = raw["payload"], raw["mac"]
            if not isinstance(payload, dict) or not isinstance(mac, str):
                return None
            if not hmac.compare_digest(mac, self._mac(self._key(), entry_type, context, payload)):
                return None
            return payload
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return None

    def remove(self, entry_types):
        removed = 0
        if self.status() != "ok":
            return removed
        for path in self.host_dir.iterdir():
            if path.name.split("-", 1)[0] in entry_types and path.suffix == ".json":
                path.unlink()
                removed += 1
        return removed

    def entries(self):
        if self.status() != "ok":
            return []
        return sorted(path.name.split("-", 1)[0] for path in self.host_dir.iterdir()
                      if path.suffix == ".json" and not path.name.startswith("."))

    @contextlib.contextmanager
    def lock(self, cancel_event=None, heartbeat=None, *, poll_s=0.1):
        """Once per key per user per host (I3): a flock on a CLOEXEC fd; waiters stay
        cancellable and emit heartbeats."""
        fd = os.open(self.host_dir / "lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            info = self._fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != self.euid or stat.S_IMODE(info.st_mode) != 0o600:
                raise ValueError(STORE_UNSAFE)
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise ValueError(CANCELLED)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if heartbeat is not None:
                        heartbeat("agy_qualification_lock_wait")
                    time.sleep(poll_s)
            yield
        finally:
            os.close(fd)

    # -- typed entries (agent-harness#1076; claude 5.1/5.3 on agent-harness#1118) --------
    @staticmethod
    def _base(image_sha256, platform, runtime):
        return {"image_sha256": image_sha256, "platform": platform, "runtime": runtime}

    def put_provenance(self, prov, runtime):
        context = {**self._base(prov.image_sha256, prov.platform, runtime), "asset": prov.asset.name}
        self.put("provenance", context, context,
                 {"release_version": prov.asset.version, "asset_sha256": prov.asset.digest})

    def get_provenance(self, image_sha256, host, runtime):
        context = {**self._base(image_sha256, host.name, runtime), "asset": host.asset}
        return self.get("provenance", context, context)

    def _qualified_contexts(self, image_sha256, help_sha256, host, runtime):
        name = {**self._base(image_sha256, host.name, runtime), "profile_id": gh.PROFILE_ID}
        return name, {**name, "help_sha256": help_sha256}

    def put_qualified(self, image_sha256, help_sha256, host, runtime, release_version):
        name, context = self._qualified_contexts(image_sha256, help_sha256, host, runtime)
        self.put("qualified", name, context, {"operations": {op: "passed" for op in OPERATIONS},
                                              "release_version": release_version})

    def get_qualified(self, image_sha256, help_sha256, host, runtime):
        name, context = self._qualified_contexts(image_sha256, help_sha256, host, runtime)
        payload = self.get("qualified", name, context)
        if payload is None or payload.get("operations") != {op: "passed" for op in OPERATIONS}:
            return None
        return payload

    def _failed_context(self, image_sha256, host, runtime):
        # Keyed WITHOUT the help digest (it rides as MAC-bound payload), so a refusal on a
        # failed image needs no execution at all.
        return {**self._base(image_sha256, host.name, runtime), "profile_id": gh.PROFILE_ID}

    def put_failed(self, image_sha256, help_sha256, host, runtime, operation, reason):
        context = self._failed_context(image_sha256, host, runtime)
        self.put("failed", context, context, {"help_sha256": help_sha256, "operation": operation,
                                              "reason": reason, "status": "failed"})

    def get_failed(self, image_sha256, host, runtime):
        context = self._failed_context(image_sha256, host, runtime)
        return self.get("failed", context, context)

    def note_transient(self, image_sha256, host, runtime, *, now=None):
        """Count one consecutive transient attempt for this key; return the new count."""
        context = self._failed_context(image_sha256, host, runtime)
        payload = self.get("transient", context, context) or {}
        count = payload.get("count") if isinstance(payload.get("count"), int) else 0
        self.put("transient", context, context, {"count": count + 1, "at": time.time() if now is None else now})
        return count + 1

    def last_transient_at(self, image_sha256, host, runtime):
        context = self._failed_context(image_sha256, host, runtime)
        payload = self.get("transient", context, context) or {}
        value = payload.get("at")
        return float(value) if isinstance(value, (int, float)) else None

    def reset_transients(self, image_sha256, host, runtime):
        self._path("transient", self._failed_context(image_sha256, host, runtime)).unlink(missing_ok=True)

    def _member_context(self, asset, host, runtime):
        return {"asset": asset.name, "asset_sha256": asset.digest, "platform": host.name, "runtime": runtime}

    def put_member(self, asset, member_sha256, host, runtime):
        context = self._member_context(asset, host, runtime)
        self.put("member_cache", context, context, {"member_sha256": member_sha256, "release_version": asset.version})

    def get_member(self, asset, host, runtime):
        payload = self.get("member_cache", self._member_context(asset, host, runtime),
                           self._member_context(asset, host, runtime))
        value = payload.get("member_sha256") if payload else None
        return value if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) else None


# ---------------------------------------------------------------------------- admission

def self_qualification_enabled():
    """D3: ``[agy] self_qualification`` in the USER board config; on by default.

    Any unreadable, malformed or non-boolean value fails closed to ``False`` -- today's
    hard refusal. A repository config can never carry the table (config.py rejects it).
    """
    from .advisor_board.config import load_agy_self_qualification
    try:
        return load_agy_self_qualification()
    except Exception:  # noqa: BLE001 - any config failure restores today's refusal
        return False


# Help measured from a VerifiedImage memfd, per (image digest, runtime identity), so a
# board's per-leg lookups do not execute ``--help`` again.
_HELP_MEMO = {}
_HELP_LOCK = threading.Lock()


def _run_help(image, env):
    """Execute ``--help`` from the sealed memfd inside the owned profile; return the bytes."""
    panel = _panel()
    admission = gh.Admission(gh.VerifiedImage(image.reopen(), image.sha256), None, "qualification_candidate")
    try:
        with tempfile.TemporaryDirectory(prefix="agy-help-") as scratch:
            cancel = threading.Event()
            monitor = panel._ReviewMonitor(Path(scratch) / "monitor.json", "agy-help", 0, cancel)
            home = env.get("HOME") or str(Path.home())
            with gh.owned_profile(env, settings_bytes=panel._broker_agy_settings_bytes(),
                                  credential_path=Path(home) / ".gemini/antigravity-cli/antigravity-oauth-token",
                                  admission=admission) as profile:
                proc = panel._run_leg_with_liveness(
                    [profile.executable, "--help"], cwd=scratch, env=profile.env,
                    deadline_s=panel._MAX_LEG_TIMEOUT_S, input_text=None,
                    review_monitor=monitor, gemini_profile=profile,
                )
        # agy prints its usage on stderr; the measured help is both streams, in that
        # order (``agy --help > help.txt 2>&1`` for a tool that writes only one).
        text = proc.stdout + proc.stderr
        if proc.returncode != 0 or not text:
            raise ValueError(SELF_QUALIFICATION_UNAVAILABLE)
        return text.encode()
    finally:
        admission.close()


def measure_help(image, env, runtime):
    key = (image.sha256, sha256(_canonical(runtime)).hexdigest())
    with _HELP_LOCK:
        if key not in _HELP_MEMO:
            _HELP_MEMO[key] = _run_help(image, env)
        return _HELP_MEMO[key]


def _host():
    try:
        return agy_provenance.detect_platform()
    except agy_provenance.ProvenanceError as exc:
        raise ValueError(str(exc)) from exc


def lookup(env, data, path, *, store=None):
    """Admission steps 2-5 for a non-release image; lookup only (no network, no qualification).

    Called by ``gemini_heartbeat.admit`` with the bytes of its single read. Opt-out is
    checked first and reads nothing else (D3). A failed entry refuses with no execution.
    Help is measured -- from the sealed memfd -- only after a provenance entry verifies
    against the live key (5.1 option (b)); the qualified entry is then verified against the
    full live key, including the measured help. A miss raises ``AdmissionMiss``.
    """
    if not self_qualification_enabled():
        raise ValueError(gh._CAPABILITY)
    image = gh.VerifiedImage.from_bytes(data, path)
    handed_off = False  # the memfd leaves only inside an Admission or an AdmissionMiss
    try:
        store = store or Store()
        try:
            host = _host()
        except ValueError:
            handed_off = True
            raise gh.AdmissionMiss(image, path) from None
        runtime = runtime_identity()
        if store.status() == "ok":
            if store.get_failed(image.sha256, host, runtime) is not None:
                raise ValueError(SELF_QUALIFICATION_FAILED)
            if store.get_provenance(image.sha256, host, runtime) is not None:
                help_sha256 = sha256(measure_help(image, env, runtime)).hexdigest()
                if store.get_qualified(image.sha256, help_sha256, host, runtime) is not None:
                    handed_off = True
                    return gh.Admission(image, help_sha256, "locally_qualified", Path(path))
        handed_off = True
        raise gh.AdmissionMiss(image, path)
    finally:
        if not handed_off:
            image.close()


def ensure_admitted(env, cancel_event=None, heartbeat=None, *, store=None, transport=None,
                    qualify=None):
    """``admit``, and on a miss the first-use path (agent-harness#1076).

    Called only by the whole-board preflight and by ``agy-qualification run``. Phase 1
    (provenance, nothing executes) writes a provenance entry; phase 2 measures help and
    runs the three live operations from the same sealed memfd, then writes the qualified
    entry. Operation failures write a typed failed entry; transients, cancellation and
    fetch failures write nothing.
    """
    try:
        return gh.admit(env, keep_miss=True)
    except gh.AdmissionMiss as miss:
        image, path = miss.image, miss.path
    try:
        store = store or Store()
        if store.machine_id is None:
            raise ValueError(SELF_QUALIFICATION_UNAVAILABLE)
        state = store.status()
        if state == "unsafe":
            # 5.4: never qualify into a store lookups would ignore.
            raise ValueError(STORE_UNSAFE)
        host = _host()
        if state == "absent":
            store.create()
        wait_started = time.time()
        with store.lock(cancel_event, heartbeat):
            runtime = runtime_identity()
            if store.get_failed(image.sha256, host, runtime) is not None:
                raise ValueError(SELF_QUALIFICATION_FAILED)
            last = store.last_transient_at(image.sha256, host, runtime)
            if last is not None and last >= wait_started:
                # Another holder hit a transient while we waited: refuse, run nothing, count nothing.
                raise ValueError(SELF_QUALIFICATION_UNAVAILABLE)
            if store.get_provenance(image.sha256, host, runtime) is None:
                if heartbeat is not None:
                    heartbeat("agy_qualification_provenance")
                try:
                    prov = agy_provenance.find_provenance(
                        image.sha256, host=host, transport=transport,
                        cached_member=lambda asset: store.get_member(asset, host, runtime),
                        remember_member=lambda asset, member: store.put_member(asset, member, host, runtime),
                    )
                except agy_provenance.ProvenanceError as exc:
                    raise ValueError(str(exc)) from exc
                store.put_provenance(prov, runtime)
            provenance = store.get_provenance(image.sha256, host, runtime)
            if provenance is None:
                raise ValueError(STORE_UNSAFE)
            # Phase 2: only now does anything execute, and only the verified memfd.
            if heartbeat is not None:
                heartbeat("agy_qualification_help")
            help_bytes = measure_help(image, env, runtime)
            help_sha256 = sha256(help_bytes).hexdigest()
            if store.get_qualified(image.sha256, help_sha256, host, runtime) is None:
                if cancel_event is not None and cancel_event.is_set():
                    raise ValueError(CANCELLED)
                outcome = (qualify or qualify_image)(image, help_bytes, cancel_event=cancel_event,
                                                     heartbeat=heartbeat, store=store)
                if outcome["status"] == "passed":
                    store.put_qualified(image.sha256, help_sha256, host, runtime, provenance["release_version"])
                    store.reset_transients(image.sha256, host, runtime)
                elif outcome["status"] == "failed":
                    store.put_failed(image.sha256, help_sha256, host, runtime,
                                     outcome.get("operation"), outcome.get("reason", "qualification_failed"))
                    raise ValueError(SELF_QUALIFICATION_FAILED)
                elif outcome["status"] == "cancelled":
                    raise ValueError(CANCELLED)
                else:
                    if store.note_transient(image.sha256, host, runtime) >= MAX_TRANSIENT_ATTEMPTS:
                        store.put_failed(image.sha256, help_sha256, host, runtime,
                                         outcome.get("operation"), "repeated_transient")
                        raise ValueError(SELF_QUALIFICATION_FAILED)
                    raise ValueError(SELF_QUALIFICATION_UNAVAILABLE)
            if store.get_qualified(image.sha256, help_sha256, host, runtime) is None:
                raise ValueError(STORE_UNSAFE)
            return gh.Admission(image, help_sha256, "locally_qualified", Path(path))
    except OSError as exc:
        image.close()
        raise ValueError(SELF_QUALIFICATION_UNAVAILABLE) from exc
    except BaseException:
        image.close()
        raise


# Failures that say nothing about the image: the provider was never observed running, or
# the provider did not answer the completion (HTTP 5xx, quota, auth), or our own local
# failure. Everything else the observer or validator raises is an observed violation.
_TRANSIENT_REASONS = frozenset({ENDED_BEFORE_ADMISSION, LOCAL_FAILURE, CANCELLED})


def _classify_failure(root, operation):
    """``failed`` (terminal, written as a negative record) unless the failure is one of the
    few provider-availability or local transients (codex B1 on agent-harness#1130 r1).

    An observed isolation or identity violation -- an executable outside the registered
    helper policy, an unqualified provider image, a writable image mount, a settings or
    request mismatch, an unverified network policy, a surviving process -- is terminal,
    at whatever stage it was observed."""
    try:
        failure = json.loads((root / "failure.json").read_text())
    except (OSError, ValueError):
        return "transient"  # the operation never started observing
    if failure.get("rejected_image"):
        return "failed"
    if failure.get("reason") in _TRANSIENT_REASONS:
        return "transient"
    if failure.get("stage") == "validation" and operation == "completion":
        try:
            terminal = json.loads((root / "terminal.json").read_text())
            if terminal["result"]["status"] != "OK":
                return "transient"  # the provider did not answer
        except (OSError, ValueError, KeyError, TypeError):
            return "transient"
    return "failed"


def qualify_image(image, help_bytes, *, cancel_event=None, heartbeat=None, store=None):
    """Run the three live operations for ``image`` (already provenance-verified) and
    validate them with the release path's own validator (I2)."""
    store = store or Store()
    runs = store.host_dir / "runs"
    runs.mkdir(mode=0o700, exist_ok=True)
    series = Path(tempfile.mkdtemp(prefix=time.strftime("%Y%m%dT%H%M%S-"), dir=runs))
    help_path = series / "agy-help.txt"
    help_path.write_bytes(help_bytes)
    help_sha256 = sha256(help_bytes).hexdigest()
    for operation in OPERATIONS:
        if cancel_event is not None and cancel_event.is_set():
            return {"status": "cancelled"}
        if heartbeat is not None:
            heartbeat(f"agy_qualification_{operation}")
        try:
            run_operation(operation, series / operation, help_path, image=image,
                          expected_help_sha256=help_sha256, cancel_event=cancel_event)
        except Exception as exc:  # noqa: BLE001 - classified below; never escapes the preflight
            if str(exc) == CANCELLED or (cancel_event is not None and cancel_event.is_set()):
                return {"status": "cancelled"}
            if _classify_failure(series / operation, operation) == "failed":
                return {"status": "failed", "operation": operation, "reason": "operation_validation_failed"}
            return {"status": "transient", "operation": operation}
    try:
        result = validate_directory(series, expected_source_sha256=source_pins(), expected_image_sha256=image.sha256,
                                    expected_help_sha256=help_sha256,
                                    expected_profile_sha256=digest(profile_description(image.sha256)),
                                    expected_helper_sha256=helper_pins())
    except (QualificationFailure, OSError, ValueError, KeyError):
        return {"status": "failed", "operation": None, "reason": "series_validation_failed"}
    return {"status": "passed"} if result["route_qualified"] else {"status": "failed", "operation": None,
                                                                   "reason": "series_incomplete"}


# ----------------------------------------------------------------- landing (D1)

# agent-harness#1076 D1: a brokered heartbeat Gemini leg is a vote only when the
# coordinator's own Admission (recorded on the leg by the owned profile, never by the
# provider) says ``release_qualified`` or ``locally_qualified``. A
# ``qualification_candidate`` leg, or a leg with no class -- including a leg from a board
# that ran before the class existed; the remedy is a board re-run -- does not count.
# ``governed_review`` calls these two helpers and holds no D1 logic of its own.
COUNTED_ADMISSION_CLASSES = frozenset({"release_qualified", "locally_qualified"})


def _gemini_heartbeat_leg(leg):
    """A heartbeat leg that ran an agy image: by name, or by the coordinator's own profile
    evidence (claude N6), so a differently named agy leg is never counted unclassified."""
    monitoring = getattr(leg, "review_monitoring", None) or {}
    evidence = getattr(leg, "harden_isolation_evidence", None) or {}
    if evidence.get("provider_isolation_profile") == gh.PROFILE_ID:
        return True  # the owned heartbeat agy profile ran it, whatever the monitoring record says
    return leg.leg == "gemini" and monitoring.get("effective_policy") == "heartbeat_only"


def leg_admission_class(leg):
    evidence = getattr(leg, "harden_isolation_evidence", None) or {}
    value = evidence.get("provider_admission_class")
    return value if isinstance(value, str) else None


def counts_toward_landing(leg):
    """A usable leg that is also a vote under the D1 counting rule, at every tier."""
    if not leg.usable:
        return False
    if _gemini_heartbeat_leg(leg):
        return leg_admission_class(leg) in COUNTED_ADMISSION_CLASSES
    return True


def president_input_items(leg):
    """The president's input for an UNCOUNTED usable heartbeat Gemini leg (plan D1: the
    president's input legs follow the same eligibility rule). ``None`` for every other
    leg -- the builder's own rule applies, and a blocking objection (``DISAGREE``) from an
    uncounted leg is kept as its findings. An uncounted non-blocking leg contributes one
    synthetic item instead of its review, so it can never stand as a seat's review."""
    if not leg.usable or counts_toward_landing(leg) or not _gemini_heartbeat_leg(leg):
        return None
    if _panel().terminal_verdict(leg.text) == "DISAGREE":
        return None
    return [f"not counted (admission {leg_admission_class(leg) or 'missing'})"]


def board_heartbeat(stream_dir=None, *, every_s=5.0, clock=time.monotonic):
    """The board's qualification heartbeat (codex B4): a content-free progress record in the
    board's stream directory when it has one, and a line on stderr, at most once per
    ``every_s`` per phase so a lock waiter's 0.1 s poll does not flood."""
    last = {}

    def beat(phase):
        now = clock()
        if phase in last and now - last[phase] < every_s:
            return
        last[phase] = now
        print(f"agy-qualification: {phase}", file=sys.stderr, flush=True)
        if stream_dir is not None:
            try:
                target = Path(stream_dir) / "agy-qualification.json"
                # Never create the board's stream directory with a default mode; an
                # existing one keeps whatever mode the board gave it (claude N7).
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                temporary = target.with_suffix(".tmp")
                temporary.write_text(json.dumps({"schema": "agy_qualification_progress.v1", "phase": phase,
                                                 "monotonic_s": now}, sort_keys=True) + "\n")
                os.replace(temporary, target)
            except OSError:
                pass
    return beat


def landing_findings(legs, *, artifact=None, reviewed_sha=None):
    """Non-gating findings: an uncounted usable Gemini leg (never a vote; its blocking
    verdict still blocks through the ordinary path), and a Gemini leg whose admitted image
    digest the reviewed artifact names -- a seat voting on its own pin."""
    from .governed_review import ReviewFinding
    findings = []
    for leg in legs:
        if not _gemini_heartbeat_leg(leg):
            continue
        klass = leg_admission_class(leg)
        if leg.usable and klass not in COUNTED_ADMISSION_CLASSES:
            findings.append(ReviewFinding(
                code="panel_leg_admission_not_counted",
                reason=f"panel leg {leg.leg} admission class {klass or 'missing'} is not a vote; re-run the board",
                severity="warn", reviewed_sha=reviewed_sha,
            ))
        evidence = getattr(leg, "harden_isolation_evidence", None) or {}
        digest = evidence.get("provider_image_sha256")
        if artifact is not None and isinstance(digest, str) and len(digest) == 64 and digest in artifact:
            findings.append(ReviewFinding(
                code="gemini_seat_reviews_its_own_pin",
                reason=(f"panel leg {leg.leg} runs agy image {digest} ({klass or 'unclassified'}), "
                        "which the reviewed artifact pins"),
                severity="warn", reviewed_sha=reviewed_sha,
            ))
    return tuple(findings)


# ------------------------------------------------------------------ worker and fd gate

_PR_SET_PDEATHSIG = 1
_F_GET_SEALS = 1034
_REQUIRED_SEALS = 0x8 | 0x4 | 0x2 | 0x1  # F_SEAL_WRITE | F_SEAL_GROW | F_SEAL_SHRINK | F_SEAL_SEAL
# The worker imports THIS source tree, never whatever ``sys.path`` would resolve.
_WORKER_BOOT = ("import sys; sys.path.insert(0, sys.argv.pop(1)); "
                "from phase_loop_runtime.agy_qualification import main; sys.exit(main())")


def verified_fd_image(fd):
    """Prove an inherited fd is immutable BEFORE hashing it (agent-harness#1076 worker).

    A regular-file memfd carrying all four of F_SEAL_WRITE, F_SEAL_GROW, F_SEAL_SHRINK and
    F_SEAL_SEAL. F_SEAL_FUTURE_WRITE alone is refused: a live shared writable mapping
    made before it was added can still change the bytes. Any cross-process hand-off of
    an image memfd must go through this check (claude §2 on agent-harness#1118).
    """
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise QualificationFailure("qualification image fd is not a sealed memfd")
        if not os.readlink(f"/proc/self/fd/{fd}").startswith("/memfd:"):
            raise QualificationFailure("qualification image fd is not a sealed memfd")
        if fcntl.fcntl(fd, _F_GET_SEALS) & _REQUIRED_SEALS != _REQUIRED_SEALS:
            raise QualificationFailure("qualification image fd is not a sealed memfd")
    except OSError as exc:
        raise QualificationFailure("qualification image fd is not a sealed memfd") from exc
    return gh.VerifiedImage(fd, gh._fd_digest(fd))


def provenance_gate(image_sha256, *, store=None):
    """The worker's admission gate: a release-constant digest (the manual shim and the
    watch's prepared tree), or a provenance entry verified against the CURRENT runtime
    identity and host platform. Nothing else is ever admitted as a candidate."""
    if image_sha256 in gh.QUALIFIED_IMAGES:
        return True
    try:
        host = agy_provenance.detect_platform()
    except agy_provenance.ProvenanceError:
        return False
    store = store or Store()
    return store.get_provenance(image_sha256, host, runtime_identity()) is not None


def _set_parent_death_signal():
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(_PR_SET_PDEATHSIG, signal.SIGKILL, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "prctl")
    except (OSError, AttributeError) as exc:
        raise QualificationFailure("qualification worker cannot bind to its owner") from exc


def worker(root, image_fd=None, parent_pid=None):
    # Dies with the qualification coordinator: a SIGKILLed lock holder leaves no worker.
    _set_parent_death_signal()
    if parent_pid is not None and os.getppid() != parent_pid:
        raise SystemExit(3)
    if image_fd is None:
        raise QualificationFailure("qualification worker requires an image fd")
    image = verified_fd_image(image_fd)
    if not provenance_gate(image.sha256):
        raise QualificationFailure("qualification image fd has no provenance")
    gh._CANDIDATE = image
    from .advisor_board.fixtures import DEFAULT_BOARD
    panel = _panel()
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


def release_image_from_path(env):
    """The manual (release-route) qualification image: one read of PATH's agy, whose
    digest must already be a release-qualified set member."""
    path = shutil.which("agy", path=env.get("PATH", os.defpath))
    if path is None:
        raise QualificationFailure("qualification candidate image is unavailable")
    image = gh.VerifiedImage.from_bytes(gh._read_image(path), path)
    if image.sha256 not in gh.QUALIFIED_IMAGES:
        image.close()
        raise QualificationFailure("qualification candidate image is not a qualified set member")
    return image


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--validate", type=Path)
    group.add_argument("--operation", choices=OPERATIONS)
    group.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    group.add_argument("--measure-help", action="store_true",
                       help="Write the --image-fd image's owned-profile --help output to --output")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--help-evidence", type=Path)
    parser.add_argument("--helper-image", type=Path, action="append", default=[],
                        help="Pre-register an additional expected helper executable by its actual bytes")
    parser.add_argument("--image-fd", type=int,
                        help="Qualify the image held by this inherited, fully sealed memfd (the upstream watch)")
    parser.add_argument("--parent-pid", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker is not None:
        worker(args.worker.resolve(), args.image_fd, args.parent_pid)
    elif args.measure_help:
        # The upstream watch measures help with the PREPARED tree's owned profile.
        if args.image_fd is None or args.output is None:
            parser.error("--measure-help requires --image-fd and --output")
        image = verified_fd_image(args.image_fd)
        if not provenance_gate(image.sha256):
            raise QualificationFailure("qualification image fd has no provenance")
        args.output.write_bytes(_run_help(image, _panel()._broker_subscription_env()))
    elif args.validate is not None:
        image_sha256 = series_image(args.validate)
        result = validate_directory(args.validate, expected_source_sha256=source_pins(),
                         expected_image_sha256=image_sha256, expected_help_sha256=gh.QUALIFIED_IMAGES[image_sha256],
                         expected_profile_sha256=digest(profile_description(image_sha256)), expected_helper_sha256=helper_pins(args.helper_image))
        print(json.dumps(result))
        return 0 if result["route_qualified"] else 2
    else:
        if args.output is None or args.help_evidence is None:
            parser.error("--operation requires --output and measured --help-evidence")
        if args.image_fd is not None:
            image = verified_fd_image(args.image_fd)
            if image.sha256 not in gh.QUALIFIED_IMAGES:
                raise QualificationFailure("qualification candidate image is not a qualified set member")
        else:
            image = release_image_from_path(_panel()._broker_subscription_env())
        run_operation(args.operation, args.output.resolve(), args.help_evidence, args.helper_image,
                      image=image, expected_help_sha256=gh.QUALIFIED_IMAGES[image.sha256])
    return 0


def cli_main(args):
    """``phase-loop agy-qualification {status,run,clear,watch}``."""
    if args.action == "watch":
        from . import agy_watch
        # A top-level ``phase-loop --dry-run`` also makes the watch a dry run (claude N7).
        dry_run = bool(getattr(args, "watch_dry_run", False) or getattr(args, "dry_run", False))
        return agy_watch.main(repo=args.repo, dry_run=dry_run, version=getattr(args, "version", None),
                              base_ref=getattr(args, "base_ref", "origin/main"))
    store = Store()
    if args.action == "status":
        print(json.dumps({"store": str(store.host_dir), "store_status": store.status(),
                          "entries": store.entries(), "self_qualification": self_qualification_enabled(),
                          "runtime": runtime_identity()}, sort_keys=True))
        return 0
    if args.action == "clear":
        removed = store.remove(_ENTRY_TYPES if args.all else ("failed", "transient"))
        _HELP_MEMO.clear()
        print(json.dumps({"removed": removed}))
        return 0
    env = _panel()._broker_subscription_env()
    try:
        admission = ensure_admitted(env, heartbeat=lambda phase: print(f"agy-qualification: {phase}", file=sys.stderr))
    except ValueError as exc:
        print(f"phase-loop agy-qualification run: {exc}", file=sys.stderr)
        return 1
    try:
        print(json.dumps({"admission_class": admission.admission_class, "image_sha256": admission.image.sha256,
                          "help_sha256": admission.help_sha256}, sort_keys=True))
    finally:
        admission.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
