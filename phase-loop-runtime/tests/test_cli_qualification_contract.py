"""The harness-agnostic CLI qualification contract, inert (agent-harness#1333 PR2).

One cell per PR2 acceptance item of
``.consiliency/plans/detailed-cli-qualification-parity-20261008-0615.md`` plus the r3 items
the plan defers to PR2 (a bounded lock wait; a second lookup after the lock is acquired).
Nothing here is wired into a seat: no adapter exists yet, and no ``seat_cli_*`` code is
emitted by any launch path. Each cell names the mutation that turns it red.

Nothing reaches the network or a model. Operations are counting fakes, machine-id is
injected, and every store lives under a per-test ``$XDG_STATE_HOME``.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import jsonschema
import pytest

from phase_loop_runtime import cli_qualification as cq
from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import seat_jail
from phase_loop_runtime import seat_preflight

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux per-user store contract")

MACHINE = "a" * 32
NOW = 1_800_000_000.0


@pytest.fixture(autouse=True)
def _private_state(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(cq, "read_machine_id", lambda path="/etc/machine-id": MACHINE)


def _key(harness="codex", *, payload="1" * 64, help_sha256="2" * 64, interpreter=None, version="9.9.9"):
    return cq.QualificationKey(
        harness=harness, platform="linux-x64", payload_sha256=payload, payload_kind="binary",
        help_sha256=help_sha256, runtime={"version": version, "route_core": {"cli_qualification.py": "3" * 64}},
        interpreter_sha256=interpreter)


def _ops(calls, *, fail=None, transient=None):
    def op(name):
        def run():
            calls.append((name, cq.candidate()))
            if name == fail:
                raise cq.OperationFailed("synthetic identity violation")
            if name == transient:
                raise cq.OperationTransient("synthetic provider outage")
        return run
    return {name: op(name) for name in cq.OPERATIONS}


def _qualify(key, *, now=NOW, **kwargs):
    calls = []
    result = cq.ensure_admitted(key, _ops(calls, **kwargs), now=now)
    return result, calls


def _user_config(tmp_path, text):
    path = tmp_path / "config" / "agent-harness" / "advisor-boards.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


# ------------------------------------------------------------------------- vocabulary

def test_the_six_codes_are_typed_notices_in_the_closed_detail_vocabulary():
    assert cq.CODES == ("seat_cli_unqualified", "seat_cli_qualification_failed",
                        "seat_cli_qualification_unavailable", "seat_cli_qualification_store_unsafe",
                        "seat_cli_adapter_missing", "seat_cli_platform_unsupported")
    for code in cq.CODES:
        assert code in pi._HARNESS_DETAIL_CODES
        notice = seat_jail.render_notice(code, "codex:a")
        assert notice is not None and notice.what and notice.why and notice.fix
        assert "phase-loop cli-qualification" in notice.fix or code == "seat_cli_adapter_missing"
        assert pi._finalize_leg_detail(code) == code


def test_no_cli_code_is_a_sealed_or_jail_fallback():
    """Never toolless: no ``seat_cli_*`` code can route a seat to ``sealed``.

    Mutation: adding any of the six codes to ``SEALED_FALLBACK_CODES``.
    """
    assert not set(cq.CODES) & seat_jail.SEALED_FALLBACK_CODES
    assert not set(cq.CODES) & seat_jail.JAIL_NOT_RUN_CODES
    assert not any(code.startswith("seat_cli_") for code in seat_jail.SEALED_FALLBACK_CODES)


def test_classes_and_operations_are_the_plans():
    assert cq.CLASSES == ("release_qualified", "locally_qualified", "qualification_candidate", "none")
    assert cq.OPERATIONS == ("identity", "completion", "cancel", "owner_loss")


@pytest.mark.parametrize("outcome, admission_class, code", [
    ("candidate", "qualification_candidate", None),
    ("locally_qualified", "locally_qualified", None),
    ("absent", "none", None),
    ("opted_out", "none", None),
    ("transient", "none", None),
    ("failed_transient", "none", None),
    ("failed_identity", None, "seat_cli_qualification_failed"),
    ("store_unsafe", None, "seat_cli_qualification_store_unsafe"),
])
def test_lookup_outcomes_encode_refuse_versus_record(outcome, admission_class, code):
    """Recording-only release: only an identity failure and an unsafe store refuse here."""
    result = cq.Lookup(outcome)
    assert (result.admission_class, result.code, result.refuses) == (admission_class, code, code is not None)


def test_an_unknown_outcome_is_rejected():
    with pytest.raises(ValueError):
        cq.Lookup("trusted_because_i_said_so")


@pytest.mark.parametrize("field, value", [
    ("harness", "not-a-harness"), ("platform", "darwin-arm64"), ("payload_sha256", "x"),
    ("payload_kind", "shim"), ("help_sha256", "2" * 63), ("interpreter_sha256", "z" * 64),
])
def test_a_malformed_key_is_rejected(field, value):
    fields = {"harness": "codex", "platform": "linux-x64", "payload_sha256": "1" * 64,
              "payload_kind": "binary", "help_sha256": "2" * 64,
              "runtime": {"version": "1", "route_core": {}}, "interpreter_sha256": None}
    fields[field] = value
    with pytest.raises(ValueError):
        cq.QualificationKey(**fields)


def test_platform_detection_maps_an_unsupported_host_to_its_code(monkeypatch):
    from phase_loop_runtime import agy_provenance

    def unsupported(**_kwargs):
        raise agy_provenance.ProvenanceError(agy_provenance.UNSUPPORTED)

    monkeypatch.setattr(agy_provenance, "detect_platform", unsupported)
    with pytest.raises(cq.QualificationError, match="seat_cli_platform_unsupported"):
        cq.detect_platform()


def test_runtime_identity_hashes_the_contract_module_and_the_adapter_module(tmp_path):
    adapter = tmp_path / "synthetic_adapter.py"
    adapter.write_text("X = 1\n")
    first = cq.runtime_identity(adapter)
    adapter.write_text("X = 2\n")
    second = cq.runtime_identity(adapter)
    from phase_loop_runtime import __version__
    assert first["version"] == __version__
    assert set(first["route_core"]) == {"cli_qualification.py", "synthetic_adapter.py"}
    assert first["route_core"]["cli_qualification.py"] == second["route_core"]["cli_qualification.py"]
    assert first["route_core"]["synthetic_adapter.py"] != second["route_core"]["synthetic_adapter.py"]


# ------------------------------------------------------------------------ store safety

def _seed_qualified(key):
    result, calls = _qualify(key)
    assert result.outcome == "locally_qualified" and len(calls) == len(cq.OPERATIONS)
    assert cq.lookup(key, now=NOW).outcome == "locally_qualified"
    return cq.Store(key.harness)


def test_the_store_layout_is_per_user_per_host_per_harness(tmp_path):
    store = cq.Store("codex")
    assert store.host_dir.parent.parent == tmp_path / "state" / "phase-loop" / "cli-qualification" / "hosts"
    assert store.host_dir.name == "codex"
    assert cq.Store("grok").host_dir.parent == store.host_dir.parent
    assert MACHINE not in str(store.host_dir)


@pytest.mark.parametrize("how", ["harness_dir_0755", "host_dir_0755", "root_0755", "key_0644",
                                 "symlinked_store", "symlinked_entry", "foreign_euid"])
def test_an_unsafe_store_refuses(how):
    """Mutation: dropping the euid/mode/``O_NOFOLLOW`` checks turns a cell green-admitting."""
    key = _key()
    store = _seed_qualified(key)
    if how == "harness_dir_0755":
        store.host_dir.chmod(0o755)
    elif how == "host_dir_0755":
        store.host_dir.parent.chmod(0o755)
    elif how == "root_0755":
        store.root.chmod(0o755)
    elif how == "key_0644":
        (store.host_dir / "key").chmod(0o644)
    elif how == "symlinked_store":
        real = store.root.with_name("real-store")
        store.root.rename(real)
        store.root.symlink_to(real)
    elif how == "symlinked_entry":
        for path in store.host_dir.glob("qualified-*.json"):
            moved = path.with_name("real-" + path.name)
            path.rename(moved)
            path.symlink_to(moved)
    if how == "foreign_euid":
        result = cq.lookup(key, store=cq.Store("codex", euid=os.geteuid() + 1), now=NOW)
        assert result.outcome == "store_unsafe" and result.refuses
    elif how == "symlinked_entry":
        assert cq.lookup(key, now=NOW).outcome != "locally_qualified"
    else:
        result = cq.lookup(key, now=NOW)
        assert result.outcome == "store_unsafe" and result.code == cq.STORE_UNSAFE


def test_first_use_never_qualifies_into_an_unsafe_store():
    key = _key()
    store = cq.Store("codex")
    store.create()
    store.host_dir.chmod(0o755)
    result, calls = _qualify(key)
    assert result.outcome == "store_unsafe" and calls == []


@pytest.mark.parametrize("how", ["flipped_byte", "swapped_payload", "copied_from_other_harness",
                                 "copied_from_other_host"])
def test_a_tampered_entry_never_admits(how, monkeypatch):
    """Mutation: removing the HMAC comparison admits the tampered entry."""
    key = _key()
    store = _seed_qualified(key)
    (entry,) = store.host_dir.glob("qualified-*.json")
    if how == "flipped_byte":
        raw = bytearray(entry.read_bytes())
        raw[-5] ^= 1
        entry.write_bytes(bytes(raw))
    elif how == "swapped_payload":
        record = json.loads(entry.read_text())
        record["payload"]["operations"]["identity"] = "passed-by-hand"
        entry.write_text(json.dumps(record))
    elif how == "copied_from_other_harness":
        other = _key("grok")
        other_store = cq.Store("grok")
        other_store.create()
        (other_store.host_dir / "key").write_bytes((store.host_dir / "key").read_bytes())
        target = other_store._path("qualified", other_store._name_context(other, with_help=True))
        target.write_bytes(entry.read_bytes())
        target.chmod(0o600)
        assert cq.lookup(other, now=NOW).outcome == "absent"
        return
    else:
        monkeypatch.setattr(cq, "read_machine_id", lambda path="/etc/machine-id": "b" * 32)
        other = cq.Store("codex")
        other.create()
        (other.host_dir / "key").write_bytes((store.host_dir / "key").read_bytes())
        target = other._path("qualified", other._name_context(key, with_help=True))
        target.write_bytes(entry.read_bytes())
        target.chmod(0o600)
    assert cq.lookup(key, now=NOW).outcome == "absent"


# ---------------------------------------------------------------------- failure rules

def test_an_identity_failure_is_sticky_until_clear():
    """Mutation: expiring identity failures like transient ones turns this green-admitting."""
    key = _key()
    result, calls = _qualify(key, fail="completion")
    assert result.outcome == "failed_identity" and result.code == cq.FAILED
    assert [name for name, _ in calls] == ["identity", "completion"]
    later = NOW + 30 * 86400
    assert cq.lookup(key, now=later).outcome == "failed_identity"
    assert cq.lookup(_key(help_sha256="4" * 64), now=later).outcome == "failed_identity"
    rerun, calls = _qualify(key, now=later)
    assert rerun.outcome == "failed_identity" and calls == []
    assert cq.Store("codex").remove(("failed", "transient")) == 1
    assert cq.lookup(key, now=later).outcome == "absent"


def _three_transients(key):
    outcomes = []
    for attempt in range(cq.MAX_TRANSIENT_ATTEMPTS):
        result, _calls = _qualify(key, transient="cancel", now=NOW + attempt)
        outcomes.append(result.outcome)
    return outcomes


def test_the_third_consecutive_transient_records_a_transient_derived_failure():
    key = _key()
    assert _three_transients(key) == ["transient", "transient", "failed_transient"]
    result = cq.lookup(key, now=NOW + 10)
    assert result.outcome == "failed_transient" and result.admission_class == "none" and not result.refuses


def test_a_transient_derived_failure_expires_after_24_hours():
    """Mutation: removing the expiry keeps it ``failed_transient`` forever."""
    key = _key()
    _three_transients(key)
    assert cq.lookup(key, now=NOW + cq.TRANSIENT_FAILURE_EXPIRY_S - 1).outcome == "failed_transient"
    assert cq.lookup(key, now=NOW + cq.TRANSIENT_FAILURE_EXPIRY_S + 2).outcome == "absent"


@pytest.mark.parametrize("change", ["help", "payload", "runtime", "interpreter"])
def test_a_transient_derived_failure_expires_on_any_key_change(change):
    key = _key()
    _three_transients(key)
    changed = {"help": _key(help_sha256="4" * 64), "payload": _key(payload="5" * 64),
               "runtime": _key(version="9.9.10"), "interpreter": _key(interpreter="6" * 64)}[change]
    assert cq.lookup(changed, now=NOW + 10).outcome == "absent"


def test_a_pass_resets_the_transient_count():
    key = _key()
    for attempt in range(cq.MAX_TRANSIENT_ATTEMPTS - 1):
        assert _qualify(key, transient="cancel", now=NOW + attempt)[0].outcome == "transient"
    assert _qualify(key, now=NOW + 5)[0].outcome == "locally_qualified"
    assert "transient" not in cq.Store("codex").entries()


def test_cancellation_writes_nothing():
    key = _key()
    cancel = threading.Event()
    calls = []
    ops = _ops(calls)
    ops["completion"] = lambda: cancel.set()
    with pytest.raises(cq.QualificationError, match=cq.CANCELLED):
        cq.ensure_admitted(key, ops, cancel_event=cancel, now=NOW)
    assert [entry for entry in cq.Store("codex").entries() if entry != "key"] == []
    assert cq.lookup(key, now=NOW).outcome == "absent"


def test_an_unexpected_operation_error_is_transient_never_a_pass():
    key = _key()
    ops = _ops([])
    ops["owner_loss"] = lambda: (_ for _ in ()).throw(RuntimeError("synthetic local crash"))
    assert cq.ensure_admitted(key, ops, now=NOW).outcome == "transient"
    assert cq.lookup(key, now=NOW).outcome == "absent"


def test_operations_must_cover_every_operation():
    ops = _ops([])
    del ops["owner_loss"]
    with pytest.raises(ValueError):
        cq.ensure_admitted(_key(), ops, now=NOW)


# ------------------------------------------------------------------------ tree digest

def _closure(tmp_path):
    package = tmp_path / "node_modules" / "@vendor" / "cli"
    (package / "lib").mkdir(parents=True)
    (package / "cli.js").write_text("require('./lib/core.js')\n")
    (package / "lib" / "core.js").write_text("module.exports = 1\n")
    native = tmp_path / "node_modules" / "@vendor" / "cli-linux-x64"
    (native / "bin").mkdir(parents=True)
    (native / "bin" / "cli").write_bytes(b"\x7fELF synthetic native payload")
    (native / "bin" / "cli").chmod(0o755)
    bindir = tmp_path / "node_modules" / ".bin"
    bindir.mkdir()
    (bindir / "cli").symlink_to("../@vendor/cli/cli.js")
    return {"package": package, "@vendor/cli-linux-x64": native}, bindir / "cli"


def test_a_byte_identical_shim_over_a_changed_payload_changes_the_key(tmp_path):
    """Mutation: hashing the entry file (the shim) instead of the closure."""
    closure, shim = _closure(tmp_path)
    before_shim = os.readlink(shim)
    before = cq.tree_digest(closure)
    (closure["@vendor/cli-linux-x64"] / "bin" / "cli").write_bytes(b"\x7fELF a different payload")
    assert os.readlink(shim) == before_shim
    assert cq.tree_digest(closure) != before


def test_a_changed_imported_module_changes_the_key(tmp_path):
    """codex F007: the entry file is unchanged, an imported module is not."""
    closure, _shim = _closure(tmp_path)
    entry = (closure["package"] / "cli.js").read_bytes()
    before = cq.tree_digest(closure)
    (closure["package"] / "lib" / "core.js").write_text("module.exports = 2\n")
    assert (closure["package"] / "cli.js").read_bytes() == entry
    assert cq.tree_digest(closure) != before


def test_a_mode_change_changes_the_key(tmp_path):
    closure, _shim = _closure(tmp_path)
    before = cq.tree_digest(closure)
    (closure["@vendor/cli-linux-x64"] / "bin" / "cli").chmod(0o644)
    assert cq.tree_digest(closure) != before


def test_a_symlink_in_the_tree_is_recorded_by_its_text_and_never_followed(tmp_path):
    closure, _shim = _closure(tmp_path)
    outside = tmp_path / "outside.js"
    outside.write_text("a\n")
    link = closure["package"] / "lib" / "linked.js"
    link.symlink_to(outside)
    before = cq.tree_digest(closure)
    outside.write_text("b\n")
    assert cq.tree_digest(closure) == before  # the target's bytes are not part of the tree
    link.unlink()
    link.symlink_to(tmp_path / "elsewhere.js")
    assert cq.tree_digest(closure) != before  # the link text is


def test_the_digest_is_independent_of_the_closure_location(tmp_path):
    first, _ = _closure(tmp_path / "a")
    second, _ = _closure(tmp_path / "b")
    assert cq.tree_digest(first) == cq.tree_digest(second)


def test_a_symlinked_closure_root_or_special_file_is_refused(tmp_path):
    closure, _shim = _closure(tmp_path)
    linked = tmp_path / "linked-root"
    linked.symlink_to(closure["package"])
    with pytest.raises(cq.QualificationError, match=cq.UNAVAILABLE):
        cq.tree_digest({"package": linked})
    os.mkfifo(closure["package"] / "pipe")
    with pytest.raises(cq.QualificationError, match=cq.UNAVAILABLE):
        cq.tree_digest(closure)


def test_a_single_binary_digest_does_not_follow_a_symlink(tmp_path):
    binary = tmp_path / "cli"
    binary.write_bytes(b"payload")
    assert cq.file_digest(binary) == sha256(b"payload").hexdigest()
    link = tmp_path / "link"
    link.symlink_to(binary)
    with pytest.raises(cq.QualificationError, match=cq.UNAVAILABLE):
        cq.file_digest(link)


# ------------------------------------------------------------------------ pinned probe

def _env_printer(tmp_path):
    script = tmp_path / "cli"
    script.write_text("#!/bin/sh\nenv | LC_ALL=C sort\necho usage: cli [--flag] >&2\n")
    script.chmod(0o755)
    return script


def test_the_same_binary_under_two_user_environments_measures_the_same_help(tmp_path, monkeypatch):
    """Mutation: inheriting ``os.environ`` (or a caller env) into the probe."""
    script = _env_printer(tmp_path)
    home = tmp_path / "probe-home"
    home.mkdir()
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    monkeypatch.setenv("COLUMNS", "37")
    monkeypatch.setenv("SYNTHETIC_USER_SECRET", "one")
    first = cq.measure_help([[str(script), "--help"]], home=home)
    monkeypatch.setenv("LANG", "ja_JP.UTF-8")
    monkeypatch.setenv("COLUMNS", "301")
    monkeypatch.setenv("SYNTHETIC_USER_SECRET", "two")
    monkeypatch.setenv("TERM", "xterm-256color")
    second = cq.measure_help([[str(script), "--help"]], home=home)
    assert first == second
    assert b"SYNTHETIC_USER_SECRET" not in first
    for line in (b"LC_ALL=C.UTF-8", b"COLUMNS=200", b"TERM=dumb", b"NO_COLOR=1",
                 b"PATH=/usr/bin:/bin", b"HOME=" + str(home).encode()):
        assert line in first.splitlines()
    assert b"usage: cli [--flag]" in first  # stderr is captured with stdout


def test_suppressors_are_added_but_never_override_the_pinned_environment(tmp_path):
    script = _env_printer(tmp_path)
    out = cq.measure_help([[str(script)]], home=tmp_path, suppressors={"VENDOR_NO_UPDATE": "1"})
    assert b"VENDOR_NO_UPDATE=1" in out.splitlines()
    with pytest.raises(ValueError):
        cq.probe_env(tmp_path, {"COLUMNS": "80"})


def test_every_probe_argv_is_measured_and_a_failing_probe_is_unavailable(tmp_path):
    script = tmp_path / "cli"
    script.write_text('#!/bin/sh\necho "probe $1"\n[ "$1" = bad ] && exit 3\nexit 0\n')
    script.chmod(0o755)
    one = cq.measure_help([[str(script), "a"]], home=tmp_path)
    two = cq.measure_help([[str(script), "a"], [str(script), "b"]], home=tmp_path)
    assert one != two and b"probe b" in two
    with pytest.raises(cq.QualificationError, match=cq.UNAVAILABLE):
        cq.measure_help([[str(script), "bad"]], home=tmp_path)


# ------------------------------------------------------------------------ re-entrancy

def test_qualification_launches_carry_the_candidate_token_bound_to_the_key():
    key = _key()
    result, calls = _qualify(key)
    assert result.outcome == "locally_qualified"
    assert [token.key for _name, token in calls] == [key] * len(cq.OPERATIONS)
    assert cq.candidate() is None  # reset after the runner


def test_a_nested_ensure_admitted_under_the_candidate_token_raises():
    """Mutation: removing the nesting guard lets an operation's launch run first use again."""
    key = _key()
    nested = []

    def identity():
        with pytest.raises(cq.QualificationReentered):
            cq.ensure_admitted(_key("grok"), _ops([]), now=NOW)
        nested.append(True)

    ops = _ops([])
    ops["identity"] = identity
    assert cq.ensure_admitted(key, ops, now=NOW).outcome == "locally_qualified"
    assert nested == [True]


def test_lookup_under_the_token_returns_the_candidate_without_config_or_store(monkeypatch):
    key = _key()
    seen = []

    def completion():
        with monkeypatch.context() as patched:
            patched.setattr(cq, "Store", lambda *a, **k: pytest.fail("candidate lookup read the store"))
            patched.setattr(cq, "self_qualification_enabled", lambda harness: pytest.fail("config read"))
            seen.append(cq.lookup(key, now=NOW))
            seen.append(cq.lookup(_key(payload="7" * 64), now=NOW))

    ops = _ops([])
    ops["completion"] = completion
    assert cq.ensure_admitted(key, ops, now=NOW).outcome == "locally_qualified"
    assert seen[0].outcome == "candidate" and seen[0].admission_class == "qualification_candidate"
    assert seen[1].outcome == "candidate_mismatch" and seen[1].code == cq.UNQUALIFIED


def test_the_token_crosses_a_thread_pool_only_when_bound():
    """``ThreadPoolExecutor.submit`` does not copy the context; ``bind_candidate`` carries it.

    Mutation: making ``bind_candidate`` return ``fn`` unchanged loses the token.
    """
    key = _key()
    seen = {}

    def identity():
        with ThreadPoolExecutor(max_workers=1) as pool:
            seen["plain"] = pool.submit(cq.candidate).result()
            seen["bound"] = pool.submit(cq.bind_candidate(cq.candidate)).result()

    ops = _ops([])
    ops["identity"] = identity
    cq.ensure_admitted(key, ops, now=NOW)
    assert seen["plain"] is None
    assert seen["bound"] is not None and seen["bound"].key == key


# --------------------------------------------------------------------------- the lock

def test_the_lock_wait_is_bounded():
    """r3 deferred item: a waiter gives up with the typed code instead of hanging."""
    store = cq.Store("codex")
    store.create()
    with store.lock():
        started = time.monotonic()
        with pytest.raises(cq.QualificationError, match=cq.UNAVAILABLE):
            with store.lock(timeout_s=0.3, poll_s=0.05):
                pytest.fail("acquired a held lock")
        assert time.monotonic() - started < 5


def test_the_lock_is_per_harness():
    codex, grok = cq.Store("codex"), cq.Store("grok")
    codex.create()
    grok.create()
    with codex.lock():
        with grok.lock(timeout_s=1):
            pass


def test_a_waiter_looks_up_again_after_acquiring_the_lock():
    """r3 deferred item: another holder qualified the key while we waited, so nothing runs.

    Mutation: skipping the second lookup runs every operation again.
    """
    key = _key()
    store = cq.Store("codex")
    store.create()
    calls = []
    acquired, release = threading.Event(), threading.Event()

    def holder():
        with store.lock():
            acquired.set()
            release.wait(10)
            store.put_qualified(key)

    thread = threading.Thread(target=holder)
    thread.start()
    assert acquired.wait(10)
    timer = threading.Timer(0.3, release.set)
    timer.start()
    try:
        result = cq.ensure_admitted(key, _ops(calls), now=NOW)
    finally:
        thread.join(10)
        timer.cancel()
    assert result.outcome == "locally_qualified" and calls == []


def test_an_admitted_key_runs_nothing():
    key = _key()
    _seed_qualified(key)
    result, calls = _qualify(key)
    assert result.outcome == "locally_qualified" and calls == []


# --------------------------------------------------------------------------- opt-out

def test_opt_out_is_user_config_only_and_records_class_none(tmp_path):
    key = _key()
    _user_config(tmp_path, "[qualification.codex]\nself_qualification = false\n")
    result, calls = _qualify(key)
    assert result.outcome == "opted_out" and result.admission_class == "none" and calls == []
    assert cq.self_qualification_enabled("grok") is True


def test_the_agy_opt_out_still_opts_gemini_out(tmp_path):
    _user_config(tmp_path, "[agy]\nself_qualification = false\n")
    assert cq.self_qualification_enabled("gemini") is False
    assert cq.self_qualification_enabled("codex") is True


def test_a_malformed_opt_out_fails_closed_to_opted_out(tmp_path):
    _user_config(tmp_path, "[qualification.codex]\nself_qualification = \"no\"\n")
    assert cq.self_qualification_enabled("codex") is False
    _user_config(tmp_path, "[qualification.not-a-harness]\nself_qualification = false\n")
    assert cq.self_qualification_enabled("codex") is False


def test_the_new_table_keeps_the_agy_opt_out_loading(tmp_path):
    from phase_loop_runtime.advisor_board import config

    path = _user_config(tmp_path, "[qualification.codex]\nself_qualification = false\n"
                                  "[agy]\nself_qualification = true\n")
    assert config.load_agy_self_qualification(path=path) is True


def test_a_repository_config_cannot_opt_out(tmp_path):
    from phase_loop_runtime.advisor_board import config

    repo = tmp_path / "repo"
    (repo / ".agent-harness").mkdir(parents=True)
    (repo / ".agent-harness" / "advisor-boards.toml").write_text(
        "[qualification.codex]\nself_qualification = false\n")
    with pytest.raises(config.BoardConfigError, match="unknown config key"):
        config.load_president_ladder(repo_dir=repo, env={})


# ------------------------------------------------------------------- candidate schema

def _candidate(**overrides):
    record = {
        "harness": "codex", "platform": "linux-x64", "version_label": "codex-cli 0.99.0",
        "payload_sha256": "1" * 64, "payload_kind": "binary", "help_sha256": "2" * 64,
        "runtime_identity": {"version": "0.7.26", "route_core": {"cli_qualification.py": "3" * 64}},
        "agent_harness_version": "0.7.26",
        "ops": {op: "passed" for op in cq.OPERATIONS},
        "utc": "2026-10-08T12:00:00Z",
    }
    record.update(overrides)
    return record


def test_a_well_formed_candidate_validates():
    cq.validate_candidate(_candidate())


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(hostname="claw"),
    lambda r: r.update(machine_id="a" * 32),
    lambda r: r.update(interpreter_sha256="4" * 64),
    lambda r: r.update(path="/home/someone/.local/bin/codex"),
    lambda r: r.update(version_label="/home/someone/.local/bin/codex"),
    lambda r: r.update(version_label="codex\nrm -rf"),
    lambda r: r["runtime_identity"].update(host="claw"),
    lambda r: r["runtime_identity"]["route_core"].update({"/etc/passwd": "3" * 64}),
    lambda r: r["ops"].update(identity="skipped"),
    lambda r: r["ops"].pop("cancel"),
    lambda r: r.update(platform="darwin-arm64"),
    lambda r: r.update(payload_kind="shim"),
    lambda r: r.update(utc="2026-10-08 12:00:00"),
    lambda r: r.pop("help_sha256"),
], ids=["hostname", "machine_id", "interpreter", "path_field", "path_label", "control_label",
        "nested_host", "route_core_path", "op_not_passed", "op_missing", "platform", "kind",
        "utc", "missing_help"])
def test_the_closed_candidate_schema_refuses(mutate):
    """Mutation: dropping ``additionalProperties: false`` at any level, or loosening a pattern."""
    record = _candidate()
    mutate(record)
    with pytest.raises(jsonschema.ValidationError):
        cq.validate_candidate(record)


def test_the_schema_is_closed_at_every_object_level():
    def objects(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                yield node
            for value in node.values():
                yield from objects(value)

    found = list(objects(cq.CANDIDATE_SCHEMA))
    assert len(found) >= 4
    assert all(node.get("additionalProperties") is False for node in found)


# --------------------------------------------------------------------------- SeatMode

def test_seat_mode_carries_an_additive_cli_admission_class():
    mode = seat_preflight.SeatMode(seat_key="codex:a", leg="codex", mode="unconfined",
                                   code=None, why="", fix="")
    assert mode.cli_admission_class is None and mode.as_json()["cli_admission_class"] is None
    assert mode.qualified_now is False
    for value in cq.CLASSES:
        classed = seat_preflight.SeatMode(seat_key="codex:a", leg="codex", mode="unconfined",
                                          code=None, why="", fix="", cli_admission_class=value)
        assert classed.as_json()["cli_admission_class"] == value
    with pytest.raises(ValueError):
        seat_preflight.SeatMode(seat_key="codex:a", leg="codex", mode="unconfined", code=None,
                                why="", fix="", cli_admission_class="trusted")
    assert seat_preflight.MODES_SCHEMA == "seat_modes.v1"


# -------------------------------------------------------------------------------- CLI

def _cli(*argv):
    from phase_loop_runtime import cli

    return cli.main(["cli-qualification", *argv])


def test_status_reports_the_store_without_a_secret(capsys):
    key = _key()
    _seed_qualified(key)
    assert _cli("status", "--harness", "codex") == 0
    report = json.loads(capsys.readouterr().out)
    assert report["harness"] == "codex" and report["store_status"] == "ok"
    assert report["entries"] == ["qualified"] and report["self_qualification"] is True
    assert report["adapter"] == "none"
    key_bytes = (cq.Store("codex").host_dir / "key").read_bytes()
    assert key_bytes.hex() not in json.dumps(report)


def test_clear_removes_failures_and_keeps_passes(capsys):
    _seed_qualified(_key())
    _qualify(_key(payload="8" * 64), fail="identity")
    assert sorted(cq.Store("codex").entries()) == ["failed", "qualified"]
    assert _cli("clear", "--harness", "codex") == 0
    assert json.loads(capsys.readouterr().out) == {"harness": "codex", "removed": 1}
    assert cq.Store("codex").entries() == ["qualified"]
    assert _cli("clear", "--harness", "codex", "--all") == 0
    assert cq.Store("codex").entries() == []


def test_the_cli_refuses_an_unknown_harness_and_has_no_run_yet():
    with pytest.raises(SystemExit):
        _cli("status", "--harness", "not-a-harness")
    with pytest.raises(SystemExit):
        _cli("run", "--harness", "codex")


def test_no_adapter_exists_and_the_contract_is_inert():
    """PR2 is inert: no adapter, no seat call site. PR3 adds the first adapters."""
    assert cq.ADAPTERS == {}
    assert cq.PENDING_ADAPTERS == frozenset({"claude", "gemini"})
    source = Path(pi.__file__).read_text()
    assert "cli_qualification" not in source
