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
import zlib
from typing import Callable, Literal, NamedTuple

from . import __version__
from . import agy_provenance
from . import gemini_heartbeat as gh
from .file_lock import acquire_exclusive

# The files an installed wheel runs the qualified route from (agent-harness#1076 D2).
# ``runtime_identity`` reports their digests. Since RECBIND no CI gate pins them: catalog
# records bind to ``seat_qci()`` instead (AGYROLL §2.1, §3.3). The upstream watch
# (``agy_watch.py``) is deliberately outside it.
ROUTE_CORE = ("gemini_heartbeat.py", "agy_qualification.py", "agy_provenance.py")

SELF_QUALIFICATION_FAILED = "gemini_heartbeat_self_qualification_failed"
SELF_QUALIFICATION_UNAVAILABLE = "gemini_heartbeat_self_qualification_unavailable"
STORE_UNSAFE = "gemini_heartbeat_self_qualification_store_unsafe"
CANCELLED = "review_operation_cancelled"
class Operation(NamedTuple):
    operation_id: str
    argv_template: tuple[str, ...]
    env_names: tuple[str, ...]
    pass_predicate_id: str


_HEARTBEAT_ARGV = (
    "<executable>", "--model", "<model>", "--sandbox", "--mode", "plan",
    "--disable-slash-commands", "--input-format", "stream-json",
    "--output-format", "stream-json", "--print=", "--print-timeout", "0",
)
_HEARTBEAT_ENV_NAMES = (
    "HOME", "LANG", "LC_ALL", "LC_CTYPE", "NO_COLOR", "PATH", "TERM",
    "XDG_CONFIG_HOME",
)
OPERATIONS_CONTRACT: tuple[Operation, ...] = (
    Operation("completion", _HEARTBEAT_ARGV, _HEARTBEAT_ENV_NAMES, "terminal_agreement_v1"),
    Operation("cancel", _HEARTBEAT_ARGV, _HEARTBEAT_ENV_NAMES, "explicit_cancel_v1"),
    Operation("owner-loss", _HEARTBEAT_ARGV, _HEARTBEAT_ENV_NAMES, "owner_loss_cleanup_v1"),
)
OPERATIONS = tuple(operation.operation_id for operation in OPERATIONS_CONTRACT)
_PASS_PREDICATES = {
    "completion": "terminal_agreement_v1",
    "cancel": "explicit_cancel_v1",
    "owner-loss": "owner_loss_cleanup_v1",
}
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


def _operation(operation_id: str) -> Operation:
    try:
        return next(operation for operation in OPERATIONS_CONTRACT
                    if operation.operation_id == operation_id)
    except StopIteration as exc:
        raise ValueError("unknown Gemini qualification operation") from exc


def render_operation_argv(operation_id: str, model: str) -> list[str]:
    """Render the measured provider argv from the closed operations contract."""
    operation = _operation(operation_id)
    values = {"<executable>": gh.PRIVATE_HOME + "/agy", "<model>": model}
    return [values.get(part, part) for part in operation.argv_template]


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
        require(_operation(operation).pass_predicate_id == _PASS_PREDICATES[operation])
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
        require(argv == render_operation_argv(
            operation, _harden_subscription_model("gemini", argv[2], None)))
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


def write_failure(root, exc, stage, helpers, observed_processes, worker_terminal=None):
    value = {"schema": "gemini_heartbeat_qualification_failure.v1",
             "exception_type": type(exc).__name__, "stage": stage,
             "reason": str(exc) if isinstance(exc, QualificationFailure) else LOCAL_FAILURE,
             "helpers": helpers.records, "rejected_image": helpers.rejected_image,
             "observed_processes": list(observed_processes.values()),
             "qualification_passed": False, "same_candidate_retry_authorized": False}
    if worker_terminal is not None:
        value["worker_terminal"] = worker_terminal
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
    if sys.platform != "linux":
        raise QualificationFailure(SELF_QUALIFICATION_UNAVAILABLE)
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


# ------------------------------------------------------------------- review authority

# Each operation's board reviews a repository that the coordinator creates fresh for that
# operation and removes afterwards. The caller's cwd plays no part: the board needs a git
# toplevel owned by this uid with at least one tracked regular file, so the outcome used to
# depend on the directory the command ran in. The authority reaches the worker as
# ``--authority`` and the board as ``repo_dir`` only: ``canonical_repo_authority`` would make
# the request governed. It is not part of the preregistration or the record.
#
# Threat model. Processes running as this uid are OUT of scope: they own the qualification
# store and could falsify any record directly. Other uids are IN scope. The authority is
# created only under a directory whose every ancestor is owned by root or this uid and is
# not writable by group or others unless it is sticky, so no other uid can rename or
# replace any component of its path. The worker proves that again before the board runs.
#
# The repository is byte-for-byte constant: one blob, one tree and one commit with a fixed
# identity, date and message on a fixed branch, written as loose objects by git's own
# plumbing. Its object ids are pinned below. The verifier accepts exactly this layout,
# these refs and these objects, and nothing else: no other history, refs, tags, stash,
# packed-refs, packs, alternates, grafts or shallow state. ``.git/config`` is fixed too, so
# the repository is SHA-1 with no extensions on every git version.
_AUTHORITY_FILE = "QUALIFICATION"
_AUTHORITY_BYTES = b"agy self-qualification authority placeholder\n"
_AUTHORITY_BRANCH = "refs/heads/qualification"
_AUTHORITY_CONFIG = (b"[core]\n\trepositoryformatversion = 0\n\tfilemode = true\n"
                     b"\tbare = false\n\tlogallrefupdates = false\n")
_AUTHORITY_SIGNATURE = b"phase-loop <qualification@invalid> 946684800 +0000"
_AUTHORITY_BLOB = "7e10b71ae4bc3b01ea8100680c32f67ddca84186"
_AUTHORITY_TREE = "8475a3951f689f66f76ac9223faddb4d3b84dc58"
_AUTHORITY_COMMIT = "02338206e2a590f29d3611bc0d2c1bb7a66cda95"
_AUTHORITY_COMMIT_BODY = (b"tree " + _AUTHORITY_TREE.encode() + b"\nauthor " + _AUTHORITY_SIGNATURE
                          + b"\ncommitter " + _AUTHORITY_SIGNATURE + b"\n\nqualification authority\n")
# ``review_stage.review_tree_manifest_sha256`` of the authority's working tree: the digest
# the board authorizes and revalidates its stage against.
_AUTHORITY_MANIFEST_SHA256 = "52e879d934588abe71210022586afc20f887d7455846ecdfc885b426136bdf6a"
_AUTHORITY_SMALL_FILE = 4096
_AUTHORITY_MAX_ENTRIES = 64
_WORKER_DETAIL_CHARS = 1024


def _authority_objects():
    """``{object id: uncompressed loose-object bytes}`` for the authority's three objects."""
    def raw(kind, body):
        return b"%s %d\0%s" % (kind, len(body), body)

    return {
        _AUTHORITY_BLOB: raw(b"blob", _AUTHORITY_BYTES),
        _AUTHORITY_TREE: raw(b"tree", b"100644 " + _AUTHORITY_FILE.encode() + b"\0"
                             + bytes.fromhex(_AUTHORITY_BLOB)),
        _AUTHORITY_COMMIT: raw(b"commit", _AUTHORITY_COMMIT_BODY),
    }


def _authority_layout():
    """Every path in the authority, relative to it: ``"d"`` for a directory, ``"f"`` for a file."""
    layout = {".git": "d", ".git/HEAD": "f", ".git/config": "f", ".git/index": "f",
              ".git/objects": "d", ".git/objects/info": "d", ".git/objects/pack": "d",
              ".git/refs": "d", ".git/refs/heads": "d", ".git/refs/tags": "d",
              ".git/" + _AUTHORITY_BRANCH: "f", _AUTHORITY_FILE: "f"}
    for oid in _authority_objects():
        layout[f".git/objects/{oid[:2]}"] = "d"
        layout[f".git/objects/{oid[:2]}/{oid[2:]}"] = "f"
    return layout


def _private_ancestry(path, euid):
    """No other uid can rename or replace any directory on ``path``.

    Each directory, ``path`` included, is a real directory owned by root or ``euid``; one
    writable by group or others must be sticky, so only its owner (root or ``euid``) and
    the owner of an entry (root or ``euid``, checked one level down) can rename it."""
    for directory in (path, *path.parents):
        info = os.lstat(directory)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, euid):
            return False
        if info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX:
            return False
    return True


def _git_url_literal(path):
    """Does git read ``file://<path>`` as exactly ``path``?

    The board stages the authority by cloning ``file://<authority>``, and git decodes
    ``%XX`` escapes in a file URL, so a path such as ``/tmp/qual%20state/...`` would be
    verified literally but cloned from ``/tmp/qual state/...``. Any ``%`` is refused, and
    so is any ASCII control character, which git versions treat differently in URLs."""
    text = str(path)
    return "%" not in text and not any(ord(char) < 0x20 or ord(char) == 0x7F for char in text)


def _authority_bases():
    """Candidate parents for a review authority, most preferred first.

    A private directory in the qualification store, when the store root exists and passes
    the store's own safety check; then ``/tmp``. A candidate is used only when its whole
    ancestry is private (``_private_ancestry``) and git reads its path literally in a file
    URL (``_git_url_literal``); otherwise the next candidate is tried."""
    store = Store()
    bases = [store.root / "authority"] if store._dir_ok(store.root) is True else []
    return [*bases, Path("/tmp")]


def _authority_parent():
    euid = os.geteuid()
    for base in _authority_bases():
        try:
            if not _git_url_literal(base):
                continue
            if not os.path.lexists(base):
                with contextlib.suppress(FileExistsError):
                    base.mkdir(mode=0o700)
            resolved = Path(base).resolve(strict=True)
            if _git_url_literal(resolved) and _private_ancestry(resolved, euid):
                return resolved
        except (OSError, RuntimeError, ValueError):
            continue
    raise QualificationFailure(LOCAL_FAILURE)


def _read_small(path):
    """A regular file's bytes, read without following a symlink and bounded."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("not a regular file")
        data = os.read(fd, _AUTHORITY_SMALL_FILE + 1)
    finally:
        os.close(fd)
    if len(data) > _AUTHORITY_SMALL_FILE:
        raise ValueError("file too large")
    return data


def _inflates_to(data, expected):
    inflater = zlib.decompressobj()
    try:
        inflated = inflater.decompress(data, _AUTHORITY_SMALL_FILE)
    except zlib.error:
        return False
    return inflater.eof and not inflater.unconsumed_tail and not inflater.unused_data and inflated == expected


def _tree_layout(root):
    """``{relative path: "d" | "f" | "?"}`` without following symlinks; ``None`` past the bound."""
    found, pending = {}, [root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                relative = os.path.relpath(entry.path, root)
                if entry.is_dir(follow_symlinks=False):
                    found[relative] = "d"
                    pending.append(entry.path)
                else:
                    found[relative] = "f" if entry.is_file(follow_symlinks=False) else "?"
                if len(found) > _AUTHORITY_MAX_ENTRIES:
                    return None
    return found


def _authority_proven(authority):
    """Is ``authority`` (absolute, canonical) exactly the constant repository, privately placed?

    Raises ``OSError``, ``ValueError`` or ``SubprocessError`` when a check cannot run."""
    from .review_stage import host_git

    if not _git_url_literal(authority):
        return False
    euid = os.geteuid()
    info = os.lstat(authority)
    if not (stat.S_ISDIR(info.st_mode) and info.st_uid == euid and stat.S_IMODE(info.st_mode) == 0o700):
        return False
    if not _private_ancestry(authority.parent, euid) or _tree_layout(authority) != _authority_layout():
        return False
    contents = {".git/HEAD": b"ref: " + _AUTHORITY_BRANCH.encode() + b"\n",
                ".git/" + _AUTHORITY_BRANCH: _AUTHORITY_COMMIT.encode() + b"\n",
                ".git/config": _AUTHORITY_CONFIG, _AUTHORITY_FILE: _AUTHORITY_BYTES}
    if any(_read_small(authority / relative) != data for relative, data in contents.items()):
        return False
    if os.lstat(authority / _AUTHORITY_FILE).st_mode & 0o111:
        return False
    for oid, raw in _authority_objects().items():
        if not _inflates_to(_read_small(authority / ".git/objects" / oid[:2] / oid[2:]), raw):
            return False
    if _panel()._canonical_review_repo_authority(authority) != authority:
        return False

    def git(*args):
        return host_git(authority, *args, check=True, capture_output=True, timeout=3, offline=True).stdout

    return (git("ls-files", "-s", "-z") == b"100644 %s 0\t%s\0" % (_AUTHORITY_BLOB.encode(), _AUTHORITY_FILE.encode())
            and git("rev-parse", "--verify", "HEAD^{commit}") == _AUTHORITY_COMMIT.encode() + b"\n")


def _remove_review_authority(authority):
    """Best effort: a leftover authority is inert, private and constant."""
    shutil.rmtree(authority, ignore_errors=True)


def _create_review_authority():
    """Create one operation's authority: a fresh 0700 directory holding the constant repository.

    Runs the hardened offline host git (no system or global config, no hooks, no templates),
    checks every object id it reports against the pinned ones, and proves the result with
    the worker's own verifier. Any error is a local failure and leaves nothing behind."""
    from .review_stage import host_git

    authority = None
    try:
        authority = Path(tempfile.mkdtemp(prefix="agy-authority-", dir=_authority_parent()))

        def git(*args, data=None):
            return host_git(authority, *args, check=True, capture_output=True, timeout=30,
                            offline=True, input=data).stdout

        git("init", "-q", "--template=")
        (authority / ".git/config").write_bytes(_AUTHORITY_CONFIG)
        written = (
            git("hash-object", "-w", "--stdin", "--no-filters", data=_AUTHORITY_BYTES),
            git("mktree", data=b"100644 blob %s\t%s\n" % (_AUTHORITY_BLOB.encode(), _AUTHORITY_FILE.encode())),
            git("hash-object", "-t", "commit", "-w", "--stdin", data=_AUTHORITY_COMMIT_BODY),
        )
        if written != tuple(oid.encode() + b"\n" for oid in (_AUTHORITY_BLOB, _AUTHORITY_TREE, _AUTHORITY_COMMIT)):
            raise ValueError("authority object ids differ from the pinned ones")
        git("symbolic-ref", "HEAD", _AUTHORITY_BRANCH)
        git("update-ref", _AUTHORITY_BRANCH, _AUTHORITY_COMMIT, "")
        git("read-tree", _AUTHORITY_COMMIT)
        fd = os.open(authority / _AUTHORITY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            os.write(fd, _AUTHORITY_BYTES)
        finally:
            os.close(fd)
        if not _authority_proven(authority):
            raise ValueError("authority differs from the constant repository")
    except Exception as exc:
        if authority is not None:
            _remove_review_authority(authority)
        raise QualificationFailure(LOCAL_FAILURE) from exc
    return authority


def _verified_review_authority(authority):
    """The operation's coordinator-created authority, proven before the board may use it.

    Fails closed unless the path is absolute and canonical and ``_authority_proven`` holds:
    a 0700 directory owned by this euid under a private ancestry, holding exactly the
    constant repository (pinned objects, one ref, no other history or state) and the
    placeholder, as its own git toplevel."""
    try:
        path = Path(authority)
        proven = path.is_absolute() and path.resolve(strict=True) == path and _authority_proven(path)
    except (OSError, ValueError, TypeError, RuntimeError, subprocess.SubprocessError) as exc:
        raise QualificationFailure("qualification review authority is not private") from exc
    if not proven:
        raise QualificationFailure("qualification review authority is not private")
    return path


def _staged_authority_matches(leg):
    """Bind what the board staged to what the worker verified.

    The leg's placement evidence carries the staged-tree manifest the board authorized and
    revalidated its stage against; it must be the authority's constant manifest. A leg that
    answered without a staged tree does not match; one refused before staging has none."""
    placement = getattr(leg, "sandbox_placement_evidence", None) or {}
    staged = placement.get("sandbox_snapshot_sha256")
    if staged is None:
        return leg.status != "OK"
    return staged == _AUTHORITY_MANIFEST_SHA256


def _worker_terminal(root):
    """The worker's terminal ``{status, detail}`` for ``failure.json``, never its ``text``.

    When the provider was never observed, this is the board's refusal code, which is
    otherwise only in the worker's ``terminal.json``. ``None`` if the worker wrote none."""
    try:
        result = json.loads((root / "terminal.json").read_text())["result"]
        status, detail = result["status"], result["detail"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not all(value is None or isinstance(value, str) for value in (status, detail)):
        return None
    return {"status": status, "detail": detail if detail is None else detail[:_WORKER_DETAIL_CHARS]}


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
    authority = None
    stage = "authority"
    try:
        # A fresh authority per operation, outside ``root``; the worker re-proves it.
        authority = _create_review_authority()
        stage = "launch"
        image_fd = image.reopen()
        try:
            with (root / "worker.log").open("wb") as log:
                proc = _panel().launch_provider(
                    [sys.executable, "-I", "-c", _WORKER_BOOT, str(_SRC), "--worker", str(root),
                     "--authority", str(authority),
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
        write_failure(root, exc, stage, helpers, observed_processes,
                      worker_terminal=_worker_terminal(root) if stage == "terminal_observation" and observer is None else None)
        raise
    finally:
        try:
            finish_observer(proc, held, namespace_fd)
        except BaseException as exc:
            write_failure(root, exc, "observer_cleanup", helpers, observed_processes)
            raise
        finally:
            if authority is not None:
                _remove_review_authority(authority)
    write_json(root / "qualification.json", record)
    return completed


# ------------------------------------------------------------------------------- store

_ENTRY_SCHEMA = "agy_qualification_entry.v1"
_ENTRY_TYPES = ("provenance", "qualified", "failed", "member_cache", "transient", "watch_push",
                "fetch_ledger")
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


def agy_profile_digest() -> str:
    """Digest only the owned profile and qualification operations that affect admission."""
    document = {
        "profile_id": gh.PROFILE_ID,
        "profile": profile_description("<image>"),
        "operations": [operation._asdict() for operation in OPERATIONS_CONTRACT],
    }
    return sha256(_canonical(document)).hexdigest()


# What "passed" means (AGYROLL §2.1). Bump it whenever a verdict of the validator entry points
# (``validate_records``, ``validate_directory``, ``_classify_failure``) or anything they reach,
# transitively -- ``panel_invoker.terminal_verdict`` and its prompt and stream helpers
# included -- can change. tests/test_agy_qci.py pins the verdict vector per value.
QUALIFICATION_VALIDATOR = "agy_validator_v1"


def seat_qci() -> str:
    """The seat qualification contract identity. Equal to ``agy_profile_digest()`` at
    ``agy_validator_v1``, so binding records to it changes no store key (TEAMHOST §5)."""
    if QUALIFICATION_VALIDATOR == "agy_validator_v1":
        return agy_profile_digest()
    return sha256(_canonical({"agy_profile_digest": agy_profile_digest(),
                              "validator": QUALIFICATION_VALIDATOR})).hexdigest()


def qualification_key(image_sha256: str, help_sha256: str, host: str) -> dict[str, str]:
    return {
        "image_sha256": image_sha256,
        "platform": host,
        "profile_id": gh.PROFILE_ID,
        "help_sha256": help_sha256,
        "agy_profile_digest": agy_profile_digest(),
    }


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
        return self._entry(entry_type, name_context, context)[1]

    def _entry(self, entry_type, name_context, context):
        """``("valid", payload)``, ``("absent", None)`` or ``("invalid", None)``.

        ``get`` reads both failures as None. The fetch ledger must not: an entry that exists
        but does not verify is a tampered ledger, never an empty one."""
        if self.status() != "ok":
            return "invalid", None
        try:
            data = self._read(self._path(entry_type, name_context))
        except FileNotFoundError:
            return "absent", None
        except (OSError, ValueError):
            return "invalid", None
        try:
            raw = json.loads(data)
            if raw.get("schema") != _ENTRY_SCHEMA or raw.get("type") != entry_type:
                return "invalid", None
            payload, mac = raw["payload"], raw["mac"]
            if not isinstance(payload, dict) or not isinstance(mac, str):
                return "invalid", None
            if not hmac.compare_digest(mac, self._mac(self._key(), entry_type, context, payload)):
                return "invalid", None
            return "valid", payload
        except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError):
            # RecursionError: a deeply nested document is not an entry (json recurses per level).
            return "invalid", None

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
    def lock(self, cancel_event=None, heartbeat=None, *, poll_s=0.1, dir_fd=None):
        """Once per key per user per host (I3): a flock on a CLOEXEC fd; waiters stay
        cancellable and emit heartbeats. ``dir_fd`` is an already verified descriptor of
        ``host_dir`` (the HOLD cache's anchor): the lock is then opened relative to it."""
        if sys.platform != "linux":
            raise ValueError(SELF_QUALIFICATION_UNAVAILABLE)
        fd = os.open("lock" if dir_fd is not None else self.host_dir / "lock",
                     os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=dir_fd)
        try:
            info = self._fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != self.euid or stat.S_IMODE(info.st_mode) != 0o600:
                raise ValueError(STORE_UNSAFE)
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise ValueError(CANCELLED)
                try:
                    acquire_exclusive(fd, blocking=False)
                    break
                except BlockingIOError:
                    if heartbeat is not None:
                        heartbeat("agy_qualification_lock_wait")
                    time.sleep(poll_s)
            yield
        finally:
            os.close(fd)

    @contextlib.contextmanager
    def try_lock(self, *, dir_fd=None):
        """The same lock without waiting (AGYFRESH §2.5, the HOLD cache's ``retain``): yields
        ``True`` while held, ``False`` at once when another holder has it. ``dir_fd`` as for
        ``lock``."""
        fd = os.open("lock" if dir_fd is not None else self.host_dir / "lock",
                     os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=dir_fd)
        try:
            info = self._fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != self.euid or stat.S_IMODE(info.st_mode) != 0o600:
                raise ValueError(STORE_UNSAFE)
            try:
                acquire_exclusive(fd, blocking=False)
            except BlockingIOError:
                yield False
                return
            yield True
        finally:
            os.close(fd)

    # -- typed entries (agent-harness#1076; claude 5.1/5.3 on agent-harness#1118) --------
    @staticmethod
    def _base(image_sha256, platform, profile_digest):
        return {"image_sha256": image_sha256, "platform": platform,
                "agy_profile_digest": profile_digest}

    @staticmethod
    def _reported(payload):
        return {**payload, "written_under": __version__}

    def put_provenance(self, prov, profile_digest):
        # The two recorded statuses ride in the payload (AGYROLL §1.3); the MAC context is
        # unchanged, so entries written before them still verify.
        context = {**self._base(prov.image_sha256, prov.platform, profile_digest),
                   "asset": prov.asset.name}
        self.put("provenance", context, context,
                 self._reported({"release_version": prov.asset.version,
                                 "asset_sha256": prov.asset.digest,
                                 "attestation": getattr(prov, "attestation", "not_checked"),
                                 "second_channel": getattr(prov, "second_channel", "not_checked")}))

    def get_provenance(self, image_sha256, host, profile_digest):
        context = {**self._base(image_sha256, host.name, profile_digest), "asset": host.asset}
        return self.get("provenance", context, context)

    def _qualified_contexts(self, image_sha256, help_sha256, host, profile_digest):
        context = qualification_key(image_sha256, help_sha256, host.name)
        if profile_digest != context["agy_profile_digest"]:
            context["agy_profile_digest"] = profile_digest
        return context, context

    def put_qualified(self, image_sha256, help_sha256, host, profile_digest, release_version):
        name, context = self._qualified_contexts(image_sha256, help_sha256, host, profile_digest)
        self.put("qualified", name, context, self._reported({
            "operations": {op: "passed" for op in OPERATIONS},
            "release_version": release_version,
        }))

    def get_qualified(self, image_sha256, help_sha256, host, profile_digest):
        name, context = self._qualified_contexts(image_sha256, help_sha256, host, profile_digest)
        payload = self.get("qualified", name, context)
        if payload is None or payload.get("operations") != {op: "passed" for op in OPERATIONS}:
            return None
        return payload

    def _failed_context(self, image_sha256, host, profile_digest):
        # Keyed WITHOUT the help digest (it rides as MAC-bound payload), so a refusal on a
        # failed image needs no execution at all.
        return {**self._base(image_sha256, host.name, profile_digest), "profile_id": gh.PROFILE_ID}

    def put_failed(self, image_sha256, help_sha256, host, profile_digest, operation, reason):
        context = self._failed_context(image_sha256, host, profile_digest)
        self.put("failed", context, context, self._reported({
            "help_sha256": help_sha256, "operation": operation,
            "reason": reason, "status": "failed",
        }))

    def get_failed(self, image_sha256, host, profile_digest):
        context = self._failed_context(image_sha256, host, profile_digest)
        return self.get("failed", context, context)

    def note_transient(self, image_sha256, host, profile_digest, *, now=None):
        """Count one consecutive transient attempt for this key; return the new count."""
        context = self._failed_context(image_sha256, host, profile_digest)
        payload = self.get("transient", context, context) or {}
        count = payload.get("count") if isinstance(payload.get("count"), int) else 0
        self.put("transient", context, context, self._reported({
            "count": count + 1, "at": time.time() if now is None else now,
        }))
        return count + 1

    def last_transient_at(self, image_sha256, host, profile_digest):
        context = self._failed_context(image_sha256, host, profile_digest)
        payload = self.get("transient", context, context) or {}
        value = payload.get("at")
        return float(value) if isinstance(value, (int, float)) else None

    def reset_transients(self, image_sha256, host, profile_digest):
        self._path("transient", self._failed_context(image_sha256, host, profile_digest)).unlink(missing_ok=True)

    def _member_context(self, asset, host, profile_digest):
        return {"asset": asset.name, "asset_sha256": asset.digest, "platform": host.name,
                "agy_profile_digest": profile_digest}

    def put_member(self, asset, member_sha256, host, profile_digest):
        context = self._member_context(asset, host, profile_digest)
        self.put("member_cache", context, context, self._reported({
            "member_sha256": member_sha256, "release_version": asset.version,
        }))

    def get_member(self, asset, host, profile_digest):
        payload = self.get("member_cache", self._member_context(asset, host, profile_digest),
                           self._member_context(asset, host, profile_digest))
        value = payload.get("member_sha256") if payload else None
        return value if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) else None

    # -- the fetch ledger (AGYROLL §1.2 total bound; PROVFWD-detail §1.3) -------------------
    # One MAC-bound entry per (store, image, platform): no profile, help or runtime digest in
    # its key, so every profile and runtime using this store shares one allowance per image.
    # First use calls these under the store's one lock, so the cap is read, compared and
    # charged before a fetch starts with no release in between. A pass (``reset_transients``)
    # and ``agy-qualification clear`` leave it; ``clear --all`` removes it.
    @staticmethod
    def _ledger_context(image_sha256, host):
        return {"image_sha256": image_sha256, "platform": host.name}

    @staticmethod
    def _ledger_shape(payload):
        times = payload.get("fetches")
        rejected = payload.get("rejected")
        quarantined_at = payload.get("quarantined_at")
        number = (int, float)
        if (not isinstance(times, list) or not all(type(t) in number for t in times)
                or not isinstance(rejected, dict)
                or not all(isinstance(d, str) and re.fullmatch(r"[0-9a-f]{64}", d) and isinstance(v, list)
                           and all(type(t) in number for t in v) for d, v in rejected.items())
                or (quarantined_at is not None and type(quarantined_at) not in number)):
            return None
        return {"fetches": list(times), "rejected": {d: list(v) for d, v in rejected.items()},
                "quarantined_at": quarantined_at}

    def _ledger_read(self, image_sha256, host, now):
        """``(ledger, quarantined_now)``. A ledger that exists but does not verify (a bad MAC,
        unreadable, undecodable or the wrong shape) is replaced, when first seen, by an
        authenticated quarantine of ``TOTAL_DOWNLOAD_CAP`` fetch times at that moment: it
        counts as a reached cap for the next 24 h, then expires like any fetch, and a new
        ``Store`` reads the same quarantine. It is never read as empty."""
        context = self._ledger_context(image_sha256, host)
        state, payload = self._entry("fetch_ledger", context, context)
        if state == "absent":
            return {"fetches": [], "rejected": {}, "quarantined_at": None}, False
        ledger = self._ledger_shape(payload) if state == "valid" else None
        if ledger is not None:
            return ledger, False
        quarantine = {"fetches": [now] * agy_provenance.TOTAL_DOWNLOAD_CAP, "rejected": {}, "quarantined_at": now}
        self._put_ledger(image_sha256, host, quarantine, now)
        return quarantine, True

    def _ledger(self, image_sha256, host, now):
        return self._ledger_read(image_sha256, host, now)[0]

    def _put_ledger(self, image_sha256, host, ledger, now):
        """Write the ledger, dropping what is older than 24 h: at most ``TOTAL_DOWNLOAD_CAP``
        fetch times and ``MAX_LISTED`` rejected digests are kept. A quarantine marker is kept
        for as long as the quarantine lasts."""
        cutoff = now - agy_provenance.TOTAL_DOWNLOAD_WINDOW_S
        fetches = sorted(t for t in ledger["fetches"] if t > cutoff)[-agy_provenance.TOTAL_DOWNLOAD_CAP:]
        rejected = {digest: sorted(t for t in times if t > cutoff) for digest, times in ledger["rejected"].items()}
        rejected = {digest: times for digest, times in rejected.items() if times}
        if len(rejected) > agy_provenance.MAX_LISTED:
            kept = sorted(rejected, key=lambda digest: rejected[digest][-1])[-agy_provenance.MAX_LISTED:]
            rejected = {digest: rejected[digest] for digest in kept}
        payload = {"fetches": fetches, "rejected": rejected}
        quarantined_at = ledger.get("quarantined_at")
        if quarantined_at is not None and quarantined_at > cutoff:
            payload["quarantined_at"] = quarantined_at
        context = self._ledger_context(image_sha256, host)
        self.put("fetch_ledger", context, context, self._reported(payload))

    def fetch_times(self, image_sha256, host):
        """The recorded fetch times for this image; a tampered ledger reads as a full one."""
        return tuple(self._ledger(image_sha256, host, _ledger_clock())["fetches"])

    def note_fetch(self, image_sha256, host, at):
        """Charge one fetch, or refuse it. The charge reads the ledger again; if that read finds
        it invalid (now quarantined) or already full, nothing is written and the fetch is
        refused with the retryable ``download_cap_reached``, so the fetch never starts and a
        quarantine is never overwritten."""
        ledger, quarantined = self._ledger_read(image_sha256, host, at)
        cutoff = at - agy_provenance.TOTAL_DOWNLOAD_WINDOW_S
        if quarantined or sum(1 for t in ledger["fetches"] if t > cutoff) >= agy_provenance.TOTAL_DOWNLOAD_CAP:
            raise agy_provenance.ProvenanceError(agy_provenance.UNVERIFIED, agy_provenance.DOWNLOAD_CAP_REACHED)
        self._put_ledger(image_sha256, host, {**ledger, "fetches": [*ledger["fetches"], at]}, at)

    def rejected_assets(self, image_sha256, host, *, now):
        """Asset digest -> how often its archive refused ``unverified`` in the last 24 h."""
        cutoff = now - agy_provenance.TOTAL_DOWNLOAD_WINDOW_S
        counts = {digest: sum(1 for t in times if t > cutoff)
                  for digest, times in self._ledger(image_sha256, host, now)["rejected"].items()}
        return {digest: count for digest, count in counts.items() if count}

    def note_rejected(self, image_sha256, host, asset_sha256, at):
        ledger = self._ledger(image_sha256, host, at)
        rejected = {**ledger["rejected"], asset_sha256: [*ledger["rejected"].get(asset_sha256, ()), at]}
        self._put_ledger(image_sha256, host, {**ledger, "rejected": rejected}, at)


def _ledger_clock():
    """The fetch ledger's clock (tests replace it)."""
    return time.time()


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


class AgyVerdict(NamedTuple):
    status: Literal["admits", "refuses", "unknown"]
    code: str | None
    reason: Literal["launch_measurement", "provider_absent"] | None


LkgProvider = Callable[[], gh.VerifiedImage | None]
_LAST_KNOWN_GOOD_PROVIDER: LkgProvider | None = None
_REQUALIFIED: set[tuple[str, str, str]] = set()
_REQUALIFIED_LOCK = threading.Lock()


def register_last_known_good(provider: LkgProvider) -> None:
    """Register the process's sole source of a previously admitted agy image."""
    global _LAST_KNOWN_GOOD_PROVIDER
    if _LAST_KNOWN_GOOD_PROVIDER is not None:
        raise RuntimeError("Gemini last-known-good provider is already registered")
    if not callable(provider):
        raise TypeError("Gemini last-known-good provider must be callable")
    _LAST_KNOWN_GOOD_PROVIDER = provider


def last_known_good() -> gh.VerifiedImage | None:
    return None if _LAST_KNOWN_GOOD_PROVIDER is None else _LAST_KNOWN_GOOD_PROVIDER()


def has_record(image_sha256: str, *, store: Store | None = None) -> bool:
    """Whether the image has any live-key admission state, without executing it."""
    store = store or Store()
    if store.status() != "ok":
        return False
    try:
        host = _host()
    except ValueError:
        return False
    profile_digest = agy_profile_digest()
    return (store.get_failed(image_sha256, host, profile_digest) is not None
            or store.get_provenance(image_sha256, host, profile_digest) is not None)


def _admit_last_known_good(env, *, store=None):
    image = last_known_good()
    if image is None:
        return None
    admitted = False
    try:
        if not isinstance(image, gh.VerifiedImage) or image.fd is None:
            return None
        descriptor = image.reopen()
        try:
            if gh._fd_digest(descriptor) != image.sha256:
                return None
        finally:
            os.close(descriptor)
        store = store or Store()
        if store.status() != "ok":
            return None
        host = _host()
        profile_digest = agy_profile_digest()
        if store.get_failed(image.sha256, host, profile_digest) is not None:
            return None
        if store.get_provenance(image.sha256, host, profile_digest) is None:
            return None
        help_sha256 = sha256(measure_help(image, env, profile_digest)).hexdigest()
        if store.get_qualified(image.sha256, help_sha256, host, profile_digest) is None:
            return None
        admitted = True
        return gh.Admission(image, help_sha256, "locally_qualified", image.path, source="lkg")
    except (OSError, ValueError):
        return None
    finally:
        if not admitted:
            image.close()


def admission_verdict(env, subject_path: Path | None, *, execute: bool) -> AgyVerdict:
    """Report the admission decision while keeping doctor-mode checks spawn-free."""
    path = subject_path or shutil.which("agy", path=env.get("PATH", os.defpath))
    if path is None:
        return AgyVerdict("unknown", None, "provider_absent")
    if execute:
        from . import agy_integrity

        try:
            image = agy_integrity.admit_for_seat(Path(path), env)
        except agy_integrity.AgyImageUnqualified:
            return AgyVerdict("refuses", "agy_image_unqualified", None)
        except (OSError, ValueError, RuntimeError) as exc:
            code = getattr(exc, "code", None) or str(exc)
            return AgyVerdict("refuses", code, None)
        else:
            image.close()
            return AgyVerdict("admits", None, None)
    try:
        data = gh._read_image(path)
        gh.VerifiedImage.from_bytes(data, path).close()
    except (OSError, ValueError, gh.AgyCanaryEvidenceError):
        return AgyVerdict("refuses", "agy_image_unqualified", None)
    image_sha256 = sha256(data).hexdigest()
    if image_sha256 in gh.QUALIFIED_IMAGES:
        return AgyVerdict("admits", None, None)
    if not self_qualification_enabled():
        return AgyVerdict("refuses", "agy_image_unqualified", None)
    store = Store()
    if store.status() != "ok":
        return AgyVerdict("refuses", "agy_image_unqualified", None)
    try:
        host = _host()
    except ValueError:
        return AgyVerdict("refuses", "agy_image_unqualified", None)
    profile_digest = agy_profile_digest()
    if store.get_failed(image_sha256, host, profile_digest) is not None:
        return AgyVerdict("refuses", "agy_image_unqualified", None)
    if store.get_provenance(image_sha256, host, profile_digest) is not None:
        return AgyVerdict("unknown", None, "launch_measurement")
    if _last_known_good_recorded(store, host, profile_digest):
        return AgyVerdict("unknown", None, "launch_measurement")
    return AgyVerdict("refuses", "agy_image_unqualified", None)


def _last_known_good_recorded(store, host, profile_digest):
    """Whether the last-known-good image passes everything but the help measurement."""
    image = last_known_good()
    if image is None:
        return False
    try:
        return (isinstance(image, gh.VerifiedImage) and image.fd is not None
                and store.get_failed(image.sha256, host, profile_digest) is None
                and store.get_provenance(image.sha256, host, profile_digest) is not None)
    finally:
        image.close()


def requalify_once(env, *, cancel_event=None, heartbeat=None, subject_path=None):
    """Run the first-use qualifier once before board composition is fixed."""
    from .executable_dependency_startup import refuse_unwired_dependency_route
    refuse_unwired_dependency_route("Gemini heartbeat image admission")
    store = Store()
    path = (os.fspath(subject_path) if subject_path is not None
            else shutil.which("agy", path=env.get("PATH", os.defpath)))
    image_sha256 = "<provider-absent>"
    if path is not None:
        try:
            image_sha256 = sha256(gh._read_image(path)).hexdigest()
        except (OSError, ValueError):
            image_sha256 = "<provider-unreadable>"
    key = (str(store.host_dir), agy_profile_digest(), image_sha256)
    with _REQUALIFIED_LOCK:
        first = key not in _REQUALIFIED
        _REQUALIFIED.add(key)
    if not first:
        # A repeat preflight is lookup only, with gh.admit's refusal mapping; it can still
        # reach the hold, which observes the caller's cancellation (AGYFRESH §2.2).
        return gh.admit(env, subject_path=subject_path, cancel_event=cancel_event)

    def release(_reason=None):
        # The key is released so the next preflight runs first use again: after a
        # cancellation, and after a retryable provenance refusal (``budget_exhausted``,
        # ``download_cap_reached``; AGYROLL §1.2), even when a hold admitted another image,
        # so a host far behind continues its forward walk.
        with _REQUALIFIED_LOCK:
            _REQUALIFIED.discard(key)

    try:
        return ensure_admitted(
            env, cancel_event, heartbeat, store=store, subject_path=subject_path, on_retryable=release)
    except ValueError as exc:
        if str(exc) == CANCELLED:  # a cancelled preflight used no attempt
            release()
        raise


# Help measured from a VerifiedImage memfd, per (image digest, runtime identity), so a
# board's per-leg lookups do not execute ``--help`` again.
_HELP_MEMO = {}
_HELP_LOCK = threading.Lock()


def _run_help(image, env, *, cancel_event=None):
    """Execute ``--help`` from the sealed memfd inside the owned profile; return the bytes.

    ``cancel_event`` is the caller's cancellation (the hold passes its own). The run's monitor
    carries it, so the existing liveness path stops the run when it is set, and a run
    stopped that way is ``CANCELLED``, never a failed measurement."""
    panel = _panel()
    admission = gh.Admission(gh.VerifiedImage(image.reopen(), image.sha256), None, "qualification_candidate")
    cancel = cancel_event if cancel_event is not None else threading.Event()
    try:
        with tempfile.TemporaryDirectory(prefix="agy-help-") as scratch:
            monitor = panel._ReviewMonitor(Path(scratch) / "monitor.json", "agy-help", 0, cancel)
            home = env.get("HOME") or str(Path.home())
            with gh.owned_profile(env, settings_bytes=panel._broker_agy_settings_bytes(),
                                  credential_path=Path(home) / ".gemini/antigravity-cli/antigravity-oauth-token",
                                  admission=admission) as profile:
                with panel._uncapped_nonseat_probe():
                    try:
                        proc = panel._run_leg_with_liveness(
                            [profile.executable, "--help"], cwd=scratch, env=profile.env,
                            deadline_s=panel._MAX_LEG_TIMEOUT_S, input_text=None,
                            review_monitor=monitor, gemini_profile=profile,
                        )
                    except panel._ReviewOperationCancelled as exc:
                        if cancel.is_set():
                            raise ValueError(CANCELLED) from exc
                        raise
        if cancel.is_set():
            raise ValueError(CANCELLED)
        # agy prints its usage on stderr; the measured help is both streams, in that
        # order (``agy --help > help.txt 2>&1`` for a tool that writes only one).
        text = proc.stdout + proc.stderr
        if proc.returncode != 0 or not text:
            raise ValueError(SELF_QUALIFICATION_UNAVAILABLE)
        return text.encode()
    finally:
        admission.close()


def measure_help(image, env, profile_digest, *, cancel_event=None):
    """The memoized help of ``image``; a cancelled run is not memoized. ``cancel_event`` (the
    hold's) reaches the run's liveness path."""
    key = (image.sha256, profile_digest)
    with _HELP_LOCK:
        if key not in _HELP_MEMO:
            _HELP_MEMO[key] = (_run_help(image, env) if cancel_event is None
                               else _run_help(image, env, cancel_event=cancel_event))
        return _HELP_MEMO[key]


def _host():
    try:
        return agy_provenance.detect_platform()
    except agy_provenance.ProvenanceError as exc:
        raise ValueError(str(exc)) from exc


def lookup(env, data, path, *, store=None):
    """Admission steps 2-5 for a non-release image; lookup only (no network, no qualification).

    Called by ``gemini_heartbeat.admit`` and ``agy_integrity.check`` with the sealed image of
    their single read (a ``gh.VerifiedImage``, whose ownership passes to this call), or with
    bytes, which are sealed here. Opt-out is
    checked first and reads nothing else (D3). A failed entry refuses with no execution.
    Help is measured -- from the sealed memfd -- only after a provenance entry verifies
    against the live key (5.1 option (b)); the qualified entry is then verified against the
    full live key, including the measured help. A miss raises ``AdmissionMiss``.
    """
    if sys.platform != "linux":
        raise ValueError(SELF_QUALIFICATION_UNAVAILABLE)
    image = data if isinstance(data, gh.VerifiedImage) else None
    handed_off = False  # the memfd leaves only inside an Admission or an AdmissionMiss
    try:
        if not self_qualification_enabled():
            raise ValueError(gh._CAPABILITY)
        if image is None:
            image = gh.VerifiedImage.from_bytes(data, path)
        store = store or Store()
        try:
            host = _host()
        except ValueError:
            handed_off = True
            raise gh.AdmissionMiss(image, path) from None
        profile_digest = agy_profile_digest()
        if store.status() == "ok":
            if store.get_failed(image.sha256, host, profile_digest) is not None:
                raise ValueError(SELF_QUALIFICATION_FAILED)
            if store.get_provenance(image.sha256, host, profile_digest) is not None:
                help_sha256 = sha256(measure_help(image, env, profile_digest)).hexdigest()
                if store.get_qualified(image.sha256, help_sha256, host, profile_digest) is not None:
                    handed_off = True
                    return gh.Admission(image, help_sha256, "locally_qualified", Path(path),
                                        source="subject")
            if not has_record(image.sha256, store=store):
                fallback = _admit_last_known_good(env, store=store)
                if fallback is not None:
                    return fallback
        handed_off = True
        raise gh.AdmissionMiss(image, path)
    finally:
        if not handed_off and image is not None:
            image.close()


def ensure_admitted(env, cancel_event=None, heartbeat=None, *, store=None, transport=None,
                    qualify=None, subject_path=None, on_retryable=None):
    """The seat admission boundary with first use (AGYFRESH §2.2): ``admit_seat(first_use=True)``.

    Called only by the whole-board preflight and by ``agy-qualification run``. The
    qualification worker's candidate token is admitted through ``gh.admit``, as before.
    ``on_retryable`` is passed to ``admit_seat``.
    """
    if gh._CANDIDATE is not None:
        return gh.admit(env, subject_path=subject_path)
    return admit_seat(env, subject_path, first_use=True, cancel_event=cancel_event,
                      heartbeat=heartbeat, store=store, transport=transport, qualify=qualify,
                      on_retryable=on_retryable)


# ------------------------------------------------- the seat admission boundary (AGYFRESH §2.2)

#: The subject-side reasons a hold may follow (AGYFRESH §2.2). Evidence values only: a hold
#: is an admission, and with no qualifying candidate the original refusal is raised.
HOLD_REASONS = (
    "subject_unreadable", "subject_not_regular", "subject_over_bound",
    "self_qualification_disabled",
    "subject_failed", "subject_unqualified", "store_unsafe",
    "provenance_unverified", "provenance_unavailable", "first_use_failed", "first_use_unavailable",
)
#: The two retryable provenance reasons (AGYROLL §1.2): the per-call budget and the daily cap.
RETRYABLE_PROVENANCE_REASONS = frozenset({agy_provenance.BUDGET_EXHAUSTED, agy_provenance.DOWNLOAD_CAP_REACHED})


def provenance_refusal(exc: agy_provenance.ProvenanceError) -> ValueError:
    """First use's provenance refusal: a plain ``ValueError`` whose ``str()`` is the code, as
    before, with ``reason`` kept as an attribute. Its type stays exactly ``ValueError``, because
    with nothing held the hold handler re-raises the original refusal unchanged (AGYFRESH §2.2)."""
    refusal = ValueError(str(exc))
    refusal.reason = exc.reason
    return refusal


# First use's refusals by their code. Any other code (a cancellation, an unsupported
# platform) is not the subject's and propagates unchanged.
_FIRST_USE_REASONS = {
    SELF_QUALIFICATION_FAILED: "first_use_failed",
    SELF_QUALIFICATION_UNAVAILABLE: "first_use_unavailable",
    STORE_UNSAFE: "store_unsafe",
    agy_provenance.UNVERIFIED: "provenance_unverified",
    agy_provenance.UNAVAILABLE: "provenance_unavailable",
}


class _SubjectNotAdmitted(Exception):
    """The subject was not admitted for a reason in ``HOLD_REASONS``, raised at one explicit
    stage of ``admit_seat``. The hold handler catches only this type; ``refusal`` is the
    exception today's code raises, re-raised unchanged when nothing is held."""

    def __init__(self, reason, refusal, subject_sha256):
        super().__init__(reason)
        self.reason, self.refusal, self.subject_sha256 = reason, refusal, subject_sha256


class _SubjectImageUnsealed(gh.AgyCanaryEvidenceError, ValueError):
    """H2: the subject's image memfd was not sealed: the seal ABI was unavailable when it was
    created, or its seals did not hold. Never hold-eligible. Classified here, before
    ``agy_integrity.check`` maps it to the same ``agy_image_unqualified`` an unqualified
    subject raises. It is still the seal error (``AgyCanaryEvidenceError``), and a
    ``ValueError`` whose ``str()`` is today's ``gemini_heartbeat_capability_unavailable``, so
    every caller's mapping is unchanged."""


def _refusal(code, cause):
    refusal = ValueError(code)
    refusal.__cause__ = cause
    return refusal


def _read_subject(path, resolved):
    """Stage 2: the subject's single read into one sealed memfd (AGYFRESH §1.2).

    ``resolved`` is the subject's resolved name, captured once by ``admit_seat`` and also used
    for the managed-release classification, so the bytes read and the classification name the
    same file; ``path`` stays the image's path metadata. The subject's digest is unknown for
    all three subject-side reasons, so they carry ``None``."""
    try:
        fd = os.open(resolved, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK | os.O_NOFOLLOW)
    except OSError as exc:
        raise _SubjectNotAdmitted("subject_unreadable", _refusal(gh._CAPABILITY, exc), None) from None
    try:
        try:
            info = os.fstat(fd)
        except OSError as exc:
            raise _SubjectNotAdmitted("subject_unreadable", _refusal(gh._CAPABILITY, exc), None) from None
        if not stat.S_ISREG(info.st_mode):
            raise _SubjectNotAdmitted("subject_not_regular", ValueError(gh._CAPABILITY), None)
        if info.st_size > agy_provenance.MAX_MEMBER_BYTES:
            raise _SubjectNotAdmitted("subject_over_bound", ValueError(gh._CAPABILITY), None)
        try:
            return gh.VerifiedImage.from_fd(fd, path=path)
        except gh.AgyCanaryEvidenceError as exc:
            raise _SubjectImageUnsealed(gh._CAPABILITY) from exc
        except OSError as exc:
            raise _SubjectNotAdmitted("subject_unreadable", _refusal(gh._CAPABILITY, exc), None) from None
        except gh.ImageOverBound as exc:
            # The streaming cap, as the reader raised it: the file grew past the bound while it
            # was read, whatever its size is now. A digest mismatch is not the subject's and
            # propagates unchanged.
            raise _SubjectNotAdmitted("subject_over_bound", _refusal(gh._CAPABILITY, exc), None) from None
    finally:
        os.close(fd)


def admit_seat(env, subject_path, *, first_use=False, cancel_event=None, heartbeat=None,
               store=None, transport=None, qualify=None, on_retryable=None) -> gh.Admission:
    """The only place a seat image is admitted (AGYFRESH §2.2).

    Stages, in order: the never-eligible conditions at their own sites (local
    capabilities, no provider, an unsealable image); the subject's single read; a release
    member, before any config or store read; the opt-out; the store lookup (which owns the
    image, and whose agent-harness#1602 seam admission is returned unchanged); with
    ``first_use=True`` only, first use. A subject-side failure at any of them is a
    ``_SubjectNotAdmitted``, and only that reaches the hold: ``admit_held`` for a standalone
    subject with the hold enabled, else the original refusal, unchanged. What a stage raises
    with its own type (a cancellation, a typed seat, quiescence or jail refusal) propagates.

    ``gh.admit`` and ``agy_integrity.check`` (with an env) call this with
    ``first_use=False`` and map its refusals as they always have; ``ensure_admitted`` calls
    it with ``first_use=True``.

    ``on_retryable(reason)`` is called when the subject's provenance stage refuses with
    ``budget_exhausted`` or ``download_cap_reached`` (AGYROLL §1.2), before the hold, so it
    is called whether the caller then raises or a hold admits another image. Such a refusal
    stays hold-eligible as ``provenance_unverified`` and counts no transient.
    """
    if sys.platform != "linux":
        raise ValueError(SELF_QUALIFICATION_UNAVAILABLE)
    try:
        gh._local_capabilities()
    except (OSError, gh.AgyCanaryEvidenceError, ValueError) as exc:
        raise ValueError(gh._CAPABILITY) from exc
    path = (os.fspath(subject_path) if subject_path is not None
            else shutil.which("agy", path=env.get("PATH", os.defpath)))
    if path is None:
        raise ValueError(gh._CAPABILITY)  # no provider installed: no seat, and no hold
    # Resolved before anything is read, so a subject removed later is still classified.
    resolved = Path(os.path.realpath(path))
    try:
        admission = _admit_subject(env, path, resolved, first_use=first_use, cancel_event=cancel_event,
                                   heartbeat=heartbeat, store=store, transport=transport, qualify=qualify,
                                   on_retryable=on_retryable)
    except _SubjectNotAdmitted as refused:
        not_admitted = refused
    else:
        if first_use and admission.source == "subject":
            # AGYFRESH §2.8: after a subject admission, and after the first-use lock is
            # released (_admit_subject has returned), keep the image for a later hold.
            _retain_admitted(env, admission, path, resolved, store)
        return admission
    return _hold_or_refuse(env, not_admitted, resolved, store=store, cancel_event=cancel_event,
                           path=path)


def _retain_admitted(env, admission, path, resolved, store):
    """``agy_hold.retain`` for a subject admission, gated as AGYFRESH §2.8 says (B7): only with
    the hold enabled and for a standalone subject; never a denied digest. Best effort: it
    never raises and never changes the admission."""
    from . import agy_hold

    try:
        if _names_managed_release(path, resolved) or not agy_hold.hold_enabled():
            return
        deny = agy_hold.hold_deny()
        if deny is None or admission.image.sha256 in deny:
            return
        store = store or Store()
        built = []

        def cache_version(digest, member_version):
            # Built on first use: only pruning needs versions, and an image already
            # retained (the common case) returns before any pruning.
            if not built:
                predicates = _hold_predicates(env, subject_sha256=None, store=store, measure=False)
                built.append(None if predicates is None else predicates[1])
            return None if built[0] is None else built[0](digest, member_version)

        agy_hold.retain(admission.image, store, cache_version=cache_version)
    except Exception:  # noqa: BLE001 - retention never fails an admission
        return


def _admit_subject(env, path, resolved, *, first_use, cancel_event, heartbeat, store, transport,
                   qualify, on_retryable=None):
    """Stages 2 to 6 of ``admit_seat`` for the subject only. Every subject image is closed or
    handed on exactly once (H1)."""
    image = _read_subject(path, resolved)
    digest = image.sha256
    if digest in gh.QUALIFIED_IMAGES:
        try:
            return gh.Admission(image, gh.QUALIFIED_IMAGES[digest], "release_qualified", Path(path),
                                source="subject")
        except BaseException:
            image.close()
            raise
    try:
        enabled = self_qualification_enabled()
    except BaseException:
        image.close()
        raise
    if not enabled:
        image.close()
        raise _SubjectNotAdmitted("self_qualification_disabled", ValueError(gh._CAPABILITY), digest)
    try:
        # lookup takes ownership of the image: it is closed there unless it is handed on.
        return lookup(env, image, path)
    except gh.AdmissionMiss as miss:
        missed = miss.image
    except ValueError as exc:
        if str(exc) == SELF_QUALIFICATION_FAILED:
            raise _SubjectNotAdmitted("subject_failed", exc, digest) from None
        if str(exc) == gh._CAPABILITY:  # the opt-out, read again inside lookup
            raise _SubjectNotAdmitted("self_qualification_disabled", exc, digest) from None
        raise
    except (OSError, gh.AgyCanaryEvidenceError) as exc:
        # AGYFRESH §2.2: the help measurement's typed outcomes propagate unchanged, so the typed
        # process-group quiescence outcome keeps its type here, as it always did when first
        # use's own phase 2 measured the help; only an OSError or the seal error itself keep
        # first use's capability refusal. (Which stage measures first depends on the help memo.)
        if first_use and not _is_typed_quiescence(exc):
            raise ValueError(gh._CAPABILITY) from exc
        raise
    if not first_use:
        missed.close()
        unsafe = (store or Store()).status() == "unsafe"
        raise _SubjectNotAdmitted("store_unsafe" if unsafe else "subject_unqualified",
                                  ValueError(gh._CAPABILITY), digest)
    try:
        return _first_use_subject(env, missed, path, cancel_event=cancel_event, heartbeat=heartbeat,
                                  store=store, transport=transport, qualify=qualify)
    except ValueError as exc:
        reason = _FIRST_USE_REASONS.get(str(exc))
        if reason is None:
            raise
        if on_retryable is not None and getattr(exc, "reason", None) in RETRYABLE_PROVENANCE_REASONS:
            on_retryable(exc.reason)
        raise _SubjectNotAdmitted(reason, exc, digest) from None


def _is_typed_quiescence(exc):
    from .panel_invoker import ProviderProcessGroupQuiescenceError
    return isinstance(exc, ProviderProcessGroupQuiescenceError)


def _cancelled(cancel_event):
    return cancel_event is not None and cancel_event.is_set()


def _names_managed_release(*names) -> bool:
    """Whether any of ``names`` lies below the managed releases root or one of its aliases,
    BY NAME: the root is resolved, the names never are.

    The subject's name is resolved once, by ``admit_seat``, and that captured name is both
    read and classified here. Resolving it again (``seat_subject._names_managed_root``
    does) would follow whatever replaced the entry during the read. ``MANAGED_RELEASES_ROOT``
    is read at call time."""
    from . import seat_subject

    root = seat_subject.MANAGED_RELEASES_ROOT
    roots = [root.absolute()]
    try:
        roots.append(root.resolve(strict=True))
    except OSError:
        pass
    return any(Path(os.path.abspath(name)).is_relative_to(item) for name in names for item in roots)


def _hold_or_refuse(env, refused, resolved, *, store, cancel_event, path=None):
    """The hold handler (AGYFRESH §2.2). The subject's image is already closed here."""
    from . import agy_hold

    refusal = refused.refusal
    # A managed-release subject is never held, on any route (§2.9, R-F0-1, R-F0-2): nothing
    # is searched or opened. Nor with the hold off, nor on an unsupported platform. The
    # classification is of the captured names (as given, and as resolved once), not of
    # whatever the entry names now.
    names = (resolved,) if path is None else (path, resolved)
    if _names_managed_release(*names) or not agy_hold.hold_enabled():
        raise refusal from refusal.__cause__
    try:
        _host()
    except ValueError:
        raise refusal from refusal.__cause__
    admission = admit_held(env, reason=refused.reason, subject_sha256=refused.subject_sha256,
                           store=store, cancel_event=cancel_event)
    if admission is None:
        raise refusal from refusal.__cause__
    return admission


def _held_help(image, env, profile_digest, cancel_event=None):
    """A candidate's measured help digest, or ``None`` on a candidate-local failure. A
    cancellation and the help measurement's typed outcomes propagate (AGYFRESH §2.2): the
    caller's ``cancel_event`` reaches the run's liveness path, is checked before and after
    the run, and a run it stopped is ``CANCELLED``, never a rejected candidate."""
    from .executable_dependency import ExecutableDependencyError
    from .panel_invoker import ProviderProcessGroupQuiescenceError
    from .sandbox_egress import EgressUnavailable
    from .seat_jail import SeatSandboxRefused

    if _cancelled(cancel_event):
        raise ValueError(CANCELLED)
    try:
        measured = measure_help(image, env, profile_digest, cancel_event=cancel_event)
    except (EgressUnavailable, gh.GeminiQuiescenceError, ProviderProcessGroupQuiescenceError,
            SeatSandboxRefused, ExecutableDependencyError):
        raise
    except ValueError as exc:
        if str(exc) == CANCELLED:
            raise
        if _cancelled(cancel_event):
            raise ValueError(CANCELLED) from exc
        return None
    except (OSError, RuntimeError) as exc:
        if _cancelled(cancel_event):
            raise ValueError(CANCELLED) from exc
        return None
    if _cancelled(cancel_event):
        raise ValueError(CANCELLED)
    return sha256(measured).hexdigest()


def _hold_predicates(env, *, subject_sha256, store, measure, cancel_event=None):
    """The §2.3 predicate over one sealed candidate, and the cache's version lookup (§2.4).

    ``measure=False`` (status) stops before executing anything: a candidate that passed the
    store half of step 3 is reported with ``help_sha256 None``. Returns ``None`` when the
    hold cannot run (the deny list is unreadable)."""
    from . import agy_hold

    deny = agy_hold.hold_deny()
    if deny is None:
        return None
    excluded = frozenset(deny | ({subject_sha256} if subject_sha256 else set()))
    store_ok = store.status() == "ok"
    try:
        host = _host()
    except ValueError:
        host = None
    local = store_ok and host is not None and self_qualification_enabled()
    profile_digest = agy_profile_digest()

    def cache_version(digest, member_version):
        if digest in excluded:
            return None
        if store_ok and host is not None and store.get_failed(digest, host, profile_digest) is not None:
            return None
        if member_version is not None:
            return member_version
        if not store_ok or host is None:
            return None
        payload = store.get_provenance(digest, host, profile_digest)
        return agy_hold.parse_version(payload.get("release_version")) if payload else None

    def predicate(image, candidate):
        digest = image.sha256
        if digest in excluded:
            return None
        if digest in gh.QUALIFIED_IMAGES:
            return gh.QUALIFIED_IMAGES[digest], "release_qualified"
        if not local:
            return None
        if store.get_failed(digest, host, profile_digest) is not None:
            return None
        if store.get_provenance(digest, host, profile_digest) is None:
            return None  # never executed, not even for --help, before this (F5)
        if not measure:
            return None, "locally_qualified"
        help_sha256 = _held_help(image, env, profile_digest, cancel_event)
        if help_sha256 is None or store.get_qualified(digest, help_sha256, host, profile_digest) is None:
            return None
        return help_sha256, "locally_qualified"

    return excluded, cache_version, predicate, (store.host_dir if store_ok else None)


def admit_held(env, *, reason, subject_sha256, store=None, cancel_event=None) -> gh.Admission | None:
    """The hold (AGYFRESH §2.3, §2.4): the first candidate of the bounded, ordered search that
    passes an existing qualification predicate, admitted with ``source="lkg"`` and no path,
    or ``None``. Every route executes a held admission's sealed image; none executes a path
    derived from it."""
    from . import agy_hold

    store = store or Store()
    predicates = _hold_predicates(env, subject_sha256=subject_sha256, store=store, measure=True,
                                  cancel_event=cancel_event)
    if predicates is None:
        # No hold (the deny list could not be read): a miss, unless the caller cancelled
        # meanwhile, which is a cancellation and never the subject's refusal.
        if _cancelled(cancel_event):
            raise ValueError(CANCELLED)
        return None
    excluded, cache_version, predicate, store_dir = predicates
    held = agy_hold.search(
        members=gh.catalog_members(), store_dir=store_dir, cache_version=cache_version,
        predicate=predicate, excluded=excluded, cancelled=lambda: _cancelled(cancel_event))
    if held is None:
        if _cancelled(cancel_event):
            raise ValueError(CANCELLED)
        return None
    if _cancelled(cancel_event):  # never hand a winner off after the caller cancelled
        held.image.close()
        raise ValueError(CANCELLED)
    try:
        return gh.Admission(held.image, held.help_sha256, held.admission_class, None, source="lkg",
                            hold_reason=reason, subject_sha256=subject_sha256)
    except BaseException:
        held.image.close()
        raise


def hold_status(env, subject_path) -> dict:
    """The ``hold`` object of ``agy-qualification status`` (AGYFRESH §2.6; EC-HOLD-12, -15).

    A lookup: it measures no help and executes nothing, and it never says an image is in
    use. Use is reported only by a launch's evidence (``provider_admission_source``). For a
    managed-release subject, with the hold off or with no provider, every route is
    ``not_covered``, ``candidate`` is ``None`` and nothing is searched."""
    from . import agy_hold

    enabled = agy_hold.hold_enabled()
    path = (os.fspath(subject_path) if subject_path is not None
            else shutil.which("agy", path=env.get("PATH", os.defpath)))
    resolved = None if path is None else Path(os.path.realpath(path))
    managed = resolved is not None and _names_managed_release(path, resolved)
    status = {"enabled": enabled, "subject": "managed_release" if managed else "standalone",
              "routes": {route: "not_covered" for route in agy_hold.ROUTE_COVERAGE},
              "candidate": None}
    if managed or not enabled or path is None:
        return status
    try:
        _host()
    except ValueError:
        return status
    status["routes"] = {route: "covered" if covered else "not_covered"
                        for route, covered in agy_hold.ROUTE_COVERAGE.items()}
    try:
        subject = _read_subject(path, resolved)
    except (_SubjectNotAdmitted, OSError, ValueError):
        subject_sha256 = None
    else:
        subject_sha256 = subject.sha256
        subject.close()
    try:
        predicates = _hold_predicates(env, subject_sha256=subject_sha256, store=Store(), measure=False)
        if predicates is None:
            return status
        excluded, cache_version, predicate, store_dir = predicates
        held = agy_hold.search(members=gh.catalog_members(), store_dir=store_dir,
                               cache_version=cache_version, predicate=predicate, excluded=excluded)
    except (OSError, ValueError, RuntimeError):
        return status
    if held is not None:
        held.image.close()
        status["candidate"] = {
            "origin": held.candidate.origin,
            "version": ".".join(str(part) for part in held.candidate.version),
            "image_sha256": held.image.sha256,
            "admission_class": held.admission_class,
            "state": "ready" if held.admission_class == "release_qualified" else "pending_help_measurement",
        }
    return status


def _first_use_subject(env, image, path, *, cancel_event=None, heartbeat=None, store=None,
                       transport=None, qualify=None):
    """Stage 6, first use for the subject's image after a lookup miss (agent-harness#1076).

    Phase 1 (provenance, nothing executes) writes a provenance entry; phase 2 measures help
    and runs the three live operations from the same sealed memfd, then writes the qualified
    entry. Operation failures write a typed failed entry; transients, cancellation and fetch
    failures write no verdict entry. Every archive fetch is charged to the fetch ledger before
    it starts. Owns ``image``: it is closed unless handed on in the admission.
    """
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
            profile_digest = agy_profile_digest()
            if store.get_failed(image.sha256, host, profile_digest) is not None:
                raise ValueError(SELF_QUALIFICATION_FAILED)
            last = store.last_transient_at(image.sha256, host, profile_digest)
            if last is not None and last >= wait_started:
                # Another holder hit a transient while we waited: refuse, run nothing, count nothing.
                raise ValueError(SELF_QUALIFICATION_UNAVAILABLE)
            if store.get_provenance(image.sha256, host, profile_digest) is None:
                if heartbeat is not None:
                    heartbeat("agy_qualification_provenance")
                try:
                    # The hint orders the walk; the ledger (keyed on this store, image and
                    # platform, shared by every profile) bounds it to TOTAL_DOWNLOAD_CAP
                    # fetches a day, checked and charged here under the store lock.
                    prov = agy_provenance.find_provenance(
                        image.sha256, host=host, transport=transport,
                        cached_member=lambda asset: store.get_member(asset, host, profile_digest),
                        remember_member=lambda asset, member: store.put_member(
                            asset, member, host, profile_digest),
                        hint=agy_provenance.version_hint(path),
                        fetch_times=lambda: store.fetch_times(image.sha256, host),
                        note_fetch=lambda at: store.note_fetch(image.sha256, host, at),
                        rejected=lambda: store.rejected_assets(image.sha256, host, now=_ledger_clock()),
                        note_rejected=lambda digest, at: store.note_rejected(image.sha256, host, digest, at),
                        now=lambda: _ledger_clock(),
                    )
                except agy_provenance.ProvenanceError as exc:
                    raise provenance_refusal(exc) from exc
                store.put_provenance(prov, profile_digest)
            provenance = store.get_provenance(image.sha256, host, profile_digest)
            if provenance is None:
                raise ValueError(STORE_UNSAFE)
            # Phase 2: only now does anything execute, and only the verified memfd.
            if heartbeat is not None:
                heartbeat("agy_qualification_help")
            help_bytes = measure_help(image, env, profile_digest)
            help_sha256 = sha256(help_bytes).hexdigest()
            if store.get_qualified(image.sha256, help_sha256, host, profile_digest) is None:
                if cancel_event is not None and cancel_event.is_set():
                    raise ValueError(CANCELLED)
                outcome = (qualify or qualify_image)(image, help_bytes, cancel_event=cancel_event,
                                                     heartbeat=heartbeat, store=store)
                if outcome["status"] == "passed":
                    store.put_qualified(image.sha256, help_sha256, host, profile_digest,
                                        provenance["release_version"])
                    store.reset_transients(image.sha256, host, profile_digest)
                elif outcome["status"] == "failed":
                    store.put_failed(image.sha256, help_sha256, host, profile_digest,
                                     outcome.get("operation"), outcome.get("reason", "qualification_failed"))
                    raise ValueError(SELF_QUALIFICATION_FAILED)
                elif outcome["status"] == "cancelled":
                    raise ValueError(CANCELLED)
                else:
                    if store.note_transient(image.sha256, host, profile_digest) >= MAX_TRANSIENT_ATTEMPTS:
                        store.put_failed(image.sha256, help_sha256, host, profile_digest,
                                         outcome.get("operation"), "repeated_transient")
                        raise ValueError(SELF_QUALIFICATION_FAILED)
                    raise ValueError(SELF_QUALIFICATION_UNAVAILABLE)
            if store.get_qualified(image.sha256, help_sha256, host, profile_digest) is None:
                raise ValueError(STORE_UNSAFE)
            return gh.Admission(image, help_sha256, "locally_qualified", Path(path),
                                source="subject")
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
    if sys.platform != "linux":
        raise QualificationFailure(SELF_QUALIFICATION_UNAVAILABLE)
    import fcntl
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
    return store.get_provenance(image_sha256, host, agy_profile_digest()) is not None


def _set_parent_death_signal():
    if sys.platform != "linux":
        raise QualificationFailure(SELF_QUALIFICATION_UNAVAILABLE)
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(_PR_SET_PDEATHSIG, signal.SIGKILL, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "prctl")
    except (OSError, AttributeError) as exc:
        raise QualificationFailure("qualification worker cannot bind to its owner") from exc


def worker(root, image_fd=None, parent_pid=None, authority=None):
    # Dies with the qualification coordinator: a SIGKILLed lock holder leaves no worker.
    _set_parent_death_signal()
    if parent_pid is not None and os.getppid() != parent_pid:
        raise SystemExit(3)
    if image_fd is None:
        raise QualificationFailure("qualification worker requires an image fd")
    image = verified_fd_image(image_fd)
    if not provenance_gate(image.sha256):
        raise QualificationFailure("qualification image fd has no provenance")
    authority = _verified_review_authority(authority)
    gh._CANDIDATE = image
    from .advisor_board.fixtures import DEFAULT_BOARD
    panel = _panel()
    cancel = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: cancel.set())
    signal.signal(signal.SIGINT, lambda *_: cancel.set())
    board = replace(DEFAULT_BOARD, name="gemini-heartbeat-qualification",
                    seats=tuple(s for s in DEFAULT_BOARD.seats if s.harness == "gemini"))
    root = Path(root).absolute()
    # The board reviews the coordinator's authority, never the inherited cwd; the chdir
    # gives any remaining cwd reader the same directory. Not ``canonical_repo_authority``:
    # that would make the request governed and demand a pre-minted authorization. The
    # previous directory is restored afterwards, so an in-process call leaves no trace.
    previous_cwd = _hold_cwd()
    try:
        os.chdir(authority)
        result = panel.invoke_board(
            board, (root / "artifact.md").read_text(), brief_ref=str(root / "brief.md"),
            repo_dir=authority, mode="review", monitoring_policy="heartbeat_only",
            stream_dir=root / "stream", cancel_event=cancel,
            review_policy=panel.ReviewLandingPolicy(("gemini",), False),
        )
        leg, = result.legs
        if not _staged_authority_matches(leg):
            # No terminal record: the coordinator then fails this operation as a local failure.
            raise QualificationFailure("qualification staged review tree differs from its authority")
        write_json(root / "terminal.json", {
            "monitoring": leg.review_monitoring, "broker": leg.harden_isolation_evidence,
            "result": {"status": leg.status, "text": leg.text, "detail": leg.detail},
        })
    finally:
        _restore_cwd(previous_cwd)


def _hold_cwd():
    """An fd on the current directory, to return to it later; ``None`` when it cannot be held.

    ``O_PATH`` needs no read permission on the directory. The qualification never depends
    on this: a dedicated worker process exits right after the board."""
    try:
        return os.open(".", getattr(os, "O_PATH", os.O_RDONLY) | os.O_DIRECTORY | os.O_CLOEXEC)
    except OSError:
        return None


def _restore_cwd(fd):
    if fd is None:
        return
    try:
        with contextlib.suppress(OSError):
            os.fchdir(fd)
    finally:
        os.close(fd)


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
    parser.add_argument("--authority", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker is not None:
        worker(args.worker.resolve(), args.image_fd, args.parent_pid, args.authority)
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
        env = _panel()._broker_subscription_env()
        from .executable_dependency import ExecutableDependencyError
        from .seat_subject import resolve_seat_subject

        subject_path = None  # unresolved: the hold status looks the PATH agy up itself
        try:
            subject = resolve_seat_subject("gemini", env)
        except FileNotFoundError:
            verdict = AgyVerdict("unknown", None, "provider_absent")
        except ExecutableDependencyError as exc:
            verdict = AgyVerdict("refuses", exc.code, None)
        else:
            subject_path = subject.subject_path
            verdict = admission_verdict(env, subject_path, execute=True)
        print(json.dumps({"store": str(store.host_dir), "store_status": store.status(),
                          "entries": store.entries(), "self_qualification": self_qualification_enabled(),
                          "key": agy_profile_digest(), "written_under": __version__,
                          "verdict": verdict._asdict(), "hold": hold_status(env, subject_path)},
                         sort_keys=True))
        return 0
    if args.action == "clear":
        if not args.all:
            removed = store.remove(("failed", "transient"))
            _HELP_MEMO.clear()
            print(json.dumps({"removed": removed}))
            return 0
        from . import agy_hold
        # --all also removes the HOLD cache (AGYFRESH §2.6, §2.8); a plain clear leaves it.
        # The cache step is isolated: an entry's removal error cannot skip it or hide its
        # result, and is then raised as clear has always raised it. What could not be removed
        # from the cache is reported, and the command fails: no silent leftovers.
        entry_error = None
        try:
            removed = store.remove(_ENTRY_TYPES)
        except Exception as exc:  # noqa: BLE001 - re-raised below, after the cache step
            entry_error, removed = exc, None
        _HELP_MEMO.clear()
        cleared = agy_hold.clear_held(store)
        output = {"removed": removed, "held_removed": cleared.removed}
        if cleared.not_removed:
            output["held_not_removed"] = list(cleared.not_removed)
        print(json.dumps(output))
        if cleared.not_removed:
            print("phase-loop agy-qualification clear --all: the HOLD cache was not removed "
                  "completely; see held_not_removed", file=sys.stderr)
        if entry_error is not None:
            raise entry_error
        return 1 if cleared.not_removed else 0
    env = _panel()._broker_subscription_env()
    from .executable_dependency import ExecutableDependencyError
    from .seat_subject import resolve_seat_subject

    try:
        try:
            subject = resolve_seat_subject("gemini", env)
        except FileNotFoundError as exc:
            raise ValueError("seat_provider_unavailable") from exc
        admission = requalify_once(
            env,
            heartbeat=lambda phase: print(f"agy-qualification: {phase}", file=sys.stderr),
            subject_path=subject.subject_path,
        )
    except (ValueError, ExecutableDependencyError) as exc:
        print(f"phase-loop agy-qualification run: {exc}", file=sys.stderr)
        return 1
    try:
        output = {"admission_class": admission.admission_class, "image_sha256": admission.image.sha256,
                  "help_sha256": admission.help_sha256, "source": admission.source}
        if admission.source == "lkg":
            # A held image is not the subject qualifying: say so (AGYFRESH §2.6).
            output.update(hold_reason=admission.hold_reason,
                          subject_image_sha256=admission.subject_sha256)
        print(json.dumps(output, sort_keys=True))
    finally:
        admission.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
