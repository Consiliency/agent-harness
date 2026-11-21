"""``phase-loop seat-window status --vendor grok`` (GROKROLL §3, §5.1; lane SL-0).

Contract: ``plans/artifacts/grokroll-v1-contract.md``. The query answers whether a grok
build is measured and whether to move onto an update, and it never turns absent or corrupt
evidence into ``advance``. These tests drive it through ``cli.main`` and the production
resolver, pin its ``grok_seat_status.v1`` field table against a golden file, enumerate the
decision table, and show that a run opens no socket, launches nothing and writes nothing.
No test runs grok or contacts the vendor.
"""

from __future__ import annotations

import base64
import builtins
import contextlib
import io
import itertools
import json
import os
import re
import signal
import socket
import subprocess
import sys
from hashlib import sha256, sha512
from pathlib import Path

import pytest

from phase_loop_runtime import cli
from phase_loop_runtime import grok_tool_surface as gts
from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime.grok_roll import catalog as rc
from phase_loop_runtime.grok_roll import evidence as ev
from phase_loop_runtime.grok_roll import status as st
from test_grok_evidence import (  # noqa: F401 - ``seat`` is a fixture
    ROUTES, catalog, ensure_root, listing_receipt, publish, put, seat, serve, surface,
    write_receipt)

GOLDEN = json.loads((Path(__file__).resolve().parent / "fixtures" / "grok_roll" / "status"
                     / "grok_seat_status.v1.golden.json").read_text())
KEYID = next(iter(rc.REGISTRY_KEYS))
_HEX64 = re.compile(r"[0-9a-f]{64}")
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z")


# ---------------------------------------------------------------------------- helpers

def run(*arguments: str) -> tuple[int, dict | None]:
    """``cli.main`` on ``seat-window status --vendor grok`` plus ``arguments``."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        try:
            code = cli.main(["seat-window", "status", "--vendor", "grok", *arguments])
        except SystemExit as exc:  # argparse usage errors
            code = exc.code
    text = out.getvalue().strip()
    return code, (json.loads(text) if text else None)


def member(version: str, digest: str, **overrides) -> dict:
    value = {"version": version, "package": rc.PACKAGE,
             "tarball_integrity": "sha512-" + base64.b64encode(
                 sha512(version.encode()).digest()).decode(),
             "registry_keyid": KEYID, "registry_signature": "MEQCIA==", "member": rc.MEMBER,
             "binary_sha256": digest, "binary_bytes": 208487936, "pinned": False}
    value.update(overrides)
    return value


ATTESTED_GATE = {"schema": "grok_catalog_gate.v1", "attested": True,
                 "ruleset_scope": "organization", "ruleset_id": 4242,
                 "workflow_ref": "refs/heads/main", "attested_at": "2026-11-21T12:00:00Z"}


def releases(monkeypatch, entries=(), raw: bytes | None = None, *,
             gate: dict | bytes | None = ATTESTED_GATE) -> None:
    """The release catalog the query loads, and the gate beside it: attested by default,
    since only an attested gate establishes membership (GROKROLL E1). ``gate=None`` keeps
    the shipped, unattested gate."""
    data = raw if raw is not None else json.dumps(
        {"schema": rc.RELEASE_CATALOG_SCHEMA, "platform": rc.PLATFORM,
         "releases": list(entries)}).encode()
    serve(monkeypatch, rc.RELEASES_NAME, data)
    if gate is not None:
        serve(monkeypatch, rc.GATE_NAME, gate if isinstance(gate, bytes) else json.dumps(gate).encode())


def digest_of(label: str) -> str:
    return sha256(label.encode()).hexdigest()


def check(value, spec: dict, path: str = "$") -> None:
    """``value`` against one golden field spec: type, nullability, enumeration, shape."""
    if value is None:
        assert spec.get("nullable") is True, f"{path} is null"
        return
    kind = spec["type"]
    if kind == "string":
        assert type(value) is str, path
    elif kind == "hex64":
        assert type(value) is str and _HEX64.fullmatch(value), path
    elif kind == "utc":
        assert type(value) is str and _UTC.fullmatch(value), path
    elif kind == "boolean":
        assert type(value) is bool, path
    elif kind == "array":
        assert type(value) is list, path
        if "length" in spec:
            assert len(value) == spec["length"], path
        for index, item in enumerate(value):
            check(item, spec["items"], f"{path}[{index}]")
    elif kind == "object":
        assert type(value) is dict, path
        check_shape(value, GOLDEN["shapes"][spec["shape"]], path)
    else:  # pragma: no cover - a golden typo
        raise AssertionError(kind)
    if "enum" in spec:
        assert value in spec["enum"], (path, value)


def check_shape(value: dict, shape: dict, path: str = "$") -> None:
    assert type(value) is dict and set(value) == set(shape), (path, sorted(value), sorted(shape))
    for key, spec in shape.items():
        check(value[key], spec, f"{path}.{key}")


def check_answer(document: dict) -> None:
    check_shape(document, GOLDEN["answer"])


# ------------------------------------------------------------------- the golden table

def test_ec_grokroll_2_the_golden_table_matches_the_code():
    shapes = GOLDEN["shapes"]
    assert shapes["build"]["state"]["enum"] == list(ev.STATES)
    assert shapes["route"]["evidence"]["enum"] == list(ev.EVIDENCE)
    assert shapes["route"]["basis"]["enum"] == list(ev.BASES)
    assert shapes["route"]["source"]["enum"] == list(ev.SOURCES)
    assert shapes["decision"]["reason"]["enum"] == list(st.REASONS)
    assert shapes["decision"]["action"]["enum"] == list(st.ACTIONS)
    assert GOLDEN["error"]["detail"]["enum"] == [*st.DETAILS, st.CONTEXT_UNAVAILABLE]
    assert GOLDEN["answer"]["schema"]["enum"] == [st.SCHEMA]
    assert shapes["route"]["route"]["enum"] == list(gts.MEASURED_ROUTES)


def _a_full_answer(seat, monkeypatch) -> dict:
    """An answer with every nullable object filled: a measured subject, a measured
    candidate and both targets."""
    old, new = digest_of("old"), digest_of("new")
    releases(monkeypatch, [member("1.0.88", old), member("1.0.89", seat.digest),
                           member("1.0.90", new)])
    for digest in (old, seat.digest, new):
        publish(seat, surface(digest))
    code, document = run("--candidate-digest", new)
    assert code == 0
    return document


def test_ec_grokroll_2_every_key_type_and_enumeration_is_pinned(seat, monkeypatch):
    document = _a_full_answer(seat, monkeypatch)
    check_answer(document)
    assert all(document[key] is not None for key in document)
    assert document["decision"] == {"action": "advance", "reason": "candidate_measured"}
    assert document["advance_to"]["version"] == "1.0.90"
    assert document["rollback_to"]["version"] == "1.0.88"
    assert document["subject"]["release"] == "member" and document["subject"]["version"] == "1.0.89"


def test_ec_grokroll_2_the_null_answer_is_golden_too(seat):
    code, document = run()
    assert code == 0
    check_answer(document)
    assert document["candidate"] is None and document["decision"] is None
    assert document["advance_to"] is None and document["rollback_to"] is None
    assert document["inputs"] == {"surface_catalog": "ok", "release_catalog": "ok",
                                  "host_records": "absent", "catalog_gate": "unattested"}


def _mutations(document: dict):
    yield "drop a top-level key", lambda doc: doc.pop("rollback_to")
    yield "add a top-level key", lambda doc: doc.update(extra=1)
    yield "retype measured", lambda doc: doc["subject"].update(measured="false")
    yield "retype a route list", lambda doc: doc["subject"].update(routes={})
    yield "drop a route key", lambda doc: doc["subject"]["routes"][0].pop("basis")
    yield "rename a decision key", lambda doc: doc.update(decision={"verdict": "advance",
                                                                   "reason": "candidate_measured"})
    yield "null a non-nullable key", lambda doc: doc.update(vendor=None)
    yield "an unknown state", lambda doc: doc["candidate"].update(state="mostly_measured")
    yield "an unknown evidence", lambda doc: doc["subject"]["routes"][1].update(evidence="none")
    yield "a short digest", lambda doc: doc["advance_to"].update(binary_sha256="ab")
    yield "a dropped input", lambda doc: doc["inputs"].pop("host_records")


def test_ec_grokroll_2_a_retyped_or_deleted_key_fails_the_golden_check(seat, monkeypatch):
    document = _a_full_answer(seat, monkeypatch)
    for name, change in _mutations(document):
        mutated = json.loads(json.dumps(document))
        change(mutated)
        with pytest.raises(AssertionError):
            check_answer(mutated)
        assert name


def test_ec_grokroll_2_the_error_object_and_exit_statuses(seat, tmp_path):
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    code, document = run("--binary", str(fifo))
    assert code == GOLDEN["exit"]["unavailable"] == 3
    check_shape(document, GOLDEN["error"])
    assert document == {"schema": "grok_seat_status.v1", "error": "status_unavailable",
                        "detail": "subject_not_regular"}
    assert run()[0] == GOLDEN["exit"]["answer"] == 0
    assert run("--exit-code")[0] == GOLDEN["exit"]["not_measured_or_hold_with_exit_code"] == 1
    for usage in (("--binary-digest", "A" * 64), ("--release-version", "1.0"),
                  ("--binary", str(fifo), "--binary-digest", "a" * 64),
                  ("--candidate-digest", "a" * 64, "--candidate-version", "1.0.1"),
                  ("--schema", "v2"), ("--require-route", "execute")):
        assert run(*usage) == (GOLDEN["exit"]["usage"], None), usage


def test_ec_grokroll_2_exit_code_is_zero_only_for_a_measured_subject_and_no_hold(seat, monkeypatch):
    publish(seat, surface(seat.digest))
    assert run("--exit-code")[0] == 0
    releases(monkeypatch, [member("1.0.90", digest_of("new"))])
    code, document = run("--exit-code", "--candidate-version", "1.0.90")
    assert document["decision"]["action"] == "hold" and code == 1


def test_ec_grokroll_2_schema_v1_and_required_routes_are_echoed(seat):
    publish(seat, surface(seat.digest, ("review",)))
    code, document = run("--schema", "v1")
    assert document["required_routes"] == ["review"] and document["subject"]["state"] == "measured"
    code, document = run("--require-route", "staged", "--require-route", "review")
    assert document["required_routes"] == ["review", "staged"]
    assert document["subject"]["state"] == "partial"
    assert [route["route"] for route in document["subject"]["routes"]] == list(ROUTES)


# --------------------------------------------------------------------- path selectors

@contextlib.contextmanager
def _never_blocks(seconds: int = 10):
    def expired(*_args):
        raise AssertionError("the query blocked")
    previous = signal.signal(signal.SIGALRM, expired)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


@pytest.mark.parametrize("role,flag", [("subject", "--binary"), ("candidate", "--candidate")])
@pytest.mark.parametrize("case,failure", [
    ("a FIFO", "not_regular"), ("a directory", "not_regular"), ("a link", "not_regular"),
    ("oversize", "too_large"), ("rewritten during the read", "changed"),
    ("missing", "unreadable"), ("not native", "not_native"),
])
def test_ec_grokroll_1_path_selectors_fail_with_their_detail_and_never_block(
        seat, monkeypatch, tmp_path, role, flag, case, failure):
    target = tmp_path / "selected"
    if case == "a FIFO":
        os.mkfifo(target)
    elif case == "a directory":
        target.mkdir()
    elif case == "a link":
        target.symlink_to(seat.binary)
    elif case == "oversize":
        with open(target, "wb") as handle:  # sparse: nothing is read before the size check
            handle.truncate(rc.MAX_BINARY_BYTES + 1)
    elif case == "rewritten during the read":
        target.write_bytes(seat.binary.read_bytes())
        real_read = os.read
        rewritten = []

        def read(descriptor, size):
            chunk = real_read(descriptor, size)
            if chunk and not rewritten and os.fstat(descriptor).st_ino == target.stat().st_ino:
                rewritten.append(True)
                with open(target, "r+b") as handle:  # same size, new content and mtime
                    handle.write(b"\x7fELF rewritten")
                    os.utime(handle.fileno(), ns=(1, 1))
            return chunk
        monkeypatch.setattr(st.os, "read", read)
    elif case == "not native":
        target.write_bytes(b"#!/bin/sh\nexec grok\n")
    with _never_blocks():
        code, document = run(flag, str(target))
    assert (code, document["detail"]) == (3, f"{role}_{failure}")


def test_a_path_selector_hashes_the_file_it_names(seat):
    code, document = run("--binary", str(seat.binary), "--candidate", str(seat.binary))
    assert code == 0 and document["subject"]["binary_sha256"] == seat.digest
    assert document["decision"] == {"action": "hold", "reason": "same_build"}


# --------------------------------------------- A1 and the no-effect guard, unmocked resolver

@pytest.fixture
def _fixed_umask():
    previous = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(previous)


def _exe(path: Path, data: bytes | str, mode: int = 0o755) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode())
    path.chmod(mode)
    return path


NATIVE = b"\x7fELF grok native stand-in, never executed\n"


def _shape(case: str, tmp_path: Path, monkeypatch) -> tuple[Path, Path | None]:
    """``(bin_dir, native)`` for one wrapper shape; ``native`` is ``None`` when the
    resolver must not follow it, and the bin dir holds nothing when no grok is installed."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    native = tmp_path / "opt" / "grok-1.0.89" / "grok"
    if case == "no grok installed":
        return bin_dir, None
    _exe(native, NATIVE)
    if case == "native binary":
        _exe(bin_dir / "grok", NATIVE)
        return bin_dir, bin_dir / "grok"
    if case == "a link to the native binary":
        (bin_dir / "grok").symlink_to(native)
        return bin_dir, native
    if case == "exec wrapper":
        _exe(bin_dir / "grok", f'#!/bin/sh\nexport NO_COLOR=1\nexec {native} "$@"\n')
        return bin_dir, native
    if case == "exec wrapper with config pairs":
        _exe(bin_dir / "grok", f'#!/bin/sh\nexec {native} -c telemetry=off -c x.y=1 "$@"\n')
        return bin_dir, native
    if case == "exec wrapper with exports":
        _exe(bin_dir / "grok", f'#!/bin/sh\nexport PATH="$PATH"\nexport LANG=C.UTF-8\n'
                               f'exec {native} "$@"\n')
        return bin_dir, native
    if case == "guarded frontdoor":
        root = tmp_path / "releases"
        root.mkdir()
        monkeypatch.setattr(pi, "_FRONTDOOR_RELEASES", root)
        monkeypatch.setattr(pi, "_FRONTDOOR_OWNERS", frozenset({0, os.getuid()}))
        release = root / "2026.11.21-grok.1-0123456789ab"
        _exe(release / "source/lib/user_agent_tools.py", "# launcher\n", 0o644)
        (release / "node/bin").mkdir(parents=True)
        shared = _exe(release / "native/grok", NATIVE)
        for path in [release, *release.rglob("*")]:
            if path.is_dir():
                path.chmod(0o755)
        _exe(bin_dir / "grok",
             "#!/bin/sh\n"
             f'export PATH={release}/node/bin:"$PATH"\n'
             f"exec /usr/bin/python3 -I {release}/source/lib/user_agent_tools.py launch"
             f" --provider grok --shared {shared} --node-bin {release}/node/bin -- \"$@\"\n")
        return bin_dir, shared
    if case == "an unrecognised wrapper":
        _exe(bin_dir / "grok", f'#!/bin/sh\nexec /usr/bin/env node {native}.js "$@"\n')
        return bin_dir, None
    raise AssertionError(case)


class _Effects:
    """Every way the query could reach the network, launch a process or write, patched to
    record and fail."""

    def __init__(self, monkeypatch) -> None:
        self.seen: list[str] = []
        real_open = os.open
        writes = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND

        def refuse(name):
            def call(*args, **kwargs):
                self.seen.append(name)
                raise AssertionError(f"{name} called")
            return call

        def guarded_open(path, flags, *args, **kwargs):
            if flags & writes:
                self.seen.append(f"os.open({path!r}, write)")
                raise AssertionError("write-mode open")
            return real_open(path, flags, *args, **kwargs)

        monkeypatch.setattr(socket, "socket", refuse("socket.socket"))
        monkeypatch.setattr(subprocess, "Popen", refuse("subprocess.Popen"))
        monkeypatch.setattr(os, "execve", refuse("os.execve"))
        monkeypatch.setattr(os, "posix_spawn", refuse("os.posix_spawn"))
        monkeypatch.setattr(os, "mkdir", refuse("os.mkdir"))
        monkeypatch.setattr(os, "open", guarded_open)


SHAPES = ["native binary", "a link to the native binary", "exec wrapper",
          "exec wrapper with config pairs", "exec wrapper with exports", "guarded frontdoor"]


@pytest.mark.parametrize("case", [*SHAPES, "an unrecognised wrapper", "no grok installed"])
def test_ec_grokroll_1_a1_and_the_no_effect_guard_through_the_production_resolver(
        _fixed_umask, tmp_path, monkeypatch, case):
    bin_dir, native = _shape(case, tmp_path, monkeypatch)
    monkeypatch.setattr(pi, "_PROVIDER_SEARCH_PATH", None)
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))  # the record root is absent
    monkeypatch.setattr(gts, "egress_allowlist_digest", lambda: "a" * 64)
    effects = _Effects(monkeypatch)
    code, document = run()
    assert effects.seen == []
    assert not (tmp_path / "state").exists()
    if case == "an unrecognised wrapper":
        assert (code, document["detail"]) == (3, "subject_not_native")
    elif case == "no grok installed":
        assert code == 0 and document["subject"] is None
    else:
        assert code == 0
        assert document["subject"]["binary_sha256"] == sha256(NATIVE).hexdigest(), case
        assert document["inputs"]["host_records"] == "absent"
        assert document["subject"]["state"] == "unmeasured"


def test_ec_grokroll_2_the_query_answers_with_both_extras_import_blocked(seat, monkeypatch):
    blocked = ("brotli", "cryptography")
    real_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in blocked:
            raise ImportError(f"{name} is blocked")
        return real_import(name, *args, **kwargs)

    for name in [name for name in sys.modules if name.split(".")[0] in blocked]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(builtins, "__import__", guarded)
    publish(seat, surface(seat.digest))
    code, document = run()
    assert code == 0 and document["subject"]["state"] == "measured"
    assert not any(name.split(".")[0] in blocked for name in sys.modules)


# ------------------------------------------------------- records on disk, through cli.main

@pytest.mark.parametrize("register,state", [("current", "measured"), ("superseded", "partial"),
                                            ("missing", "partial"), ("invalid", "invalid")])
@pytest.mark.parametrize("role", ["subject", "candidate", "target"])
def test_ec_grokroll_1_the_register_decides_as_subject_candidate_and_target(
        seat, monkeypatch, register, state, role):
    other = digest_of("other")
    releases(monkeypatch, [member("1.0.89", seat.digest), member("1.0.90", other)])
    if role == "subject":
        publish(seat, surface(seat.digest), register=register)
        code, document = run()
        assert document["subject"]["state"] == state
        assert document["subject"]["measured"] is (state == "measured")
    elif role == "candidate":
        publish(seat, surface(other), register=register)
        code, document = run("--candidate-digest", other)
        assert document["candidate"]["state"] == state
        expected = {"measured": ("advance", "candidate_measured"),
                    "partial": ("hold", "candidate_partial"),
                    "invalid": ("hold", "candidate_evidence_invalid")}[state]
        assert (document["decision"]["action"], document["decision"]["reason"]) == expected
    else:
        publish(seat, surface(other), register=register)
        code, document = run()
        assert (document["advance_to"] is not None) is (state == "measured")
        if document["advance_to"] is not None:
            assert document["advance_to"]["version"] == "1.0.90"
    assert code == 0
    check_answer(document)


@pytest.mark.parametrize("case,expected", [
    ("corrupt record", "invalid"), ("corrupt receipt", "invalid"), ("another host", "invalid"),
    ("withdrawn", "partial"), ("stale context", "stale_context"), ("revoked", "revoked"),
    ("no evidence", "unmeasured"), ("help-text listing claim", "unmeasured"),
])
def test_ec_grokroll_1_records_on_disk_through_the_cli(seat, monkeypatch, case, expected):
    if case == "corrupt record":
        put(seat, gts.host_record_name(seat.digest), b"{")
    elif case == "corrupt receipt":
        write_receipt(seat, seat.digest, "review", b"[")
    elif case == "another host":
        publish(seat, surface(seat.digest), host="f" * 64)
    elif case == "withdrawn":
        publish(seat, surface(seat.digest), register="superseded")
    elif case == "stale context":
        publish(seat, surface(seat.digest, context_digest="d" * 64))
    elif case == "revoked":
        catalog(monkeypatch, revoked=[seat.digest])
        write_receipt(seat, seat.digest, "review", listing_receipt(seat.digest, "review"))
    elif case == "no evidence":
        ensure_root(seat)
    elif case == "help-text listing claim":
        seat.binary.write_bytes(b"\x7fELF --list-tools  List the tools this build offers\n")
        ensure_root(seat)
    code, document = run()
    assert code == 0
    assert document["subject"]["state"] == expected
    assert document["subject"]["measured"] is False


# ---------------------------------------------------------------- the decision table

SUBJECT_STATES = (None, *ev.STATES)
CANDIDATE_STATES = ev.STATES


def _expected(inputs_invalid: bool, subject: str | None, candidate: str, same: bool) -> tuple:
    """GROKROLL §5.1, written out row by row."""
    rows = [
        (inputs_invalid, "hold", "inputs_invalid"),
        (candidate == "unresolved", "hold", "candidate_unresolved"),
        (candidate == "invalid", "hold", "candidate_evidence_invalid"),
        (candidate == "revoked", "hold", "candidate_revoked"),
        (subject == "invalid", "hold", "subject_evidence_invalid"),
        (subject is not None and same, "hold", "same_build"),
        (candidate == "measured", "advance", "candidate_measured"),
        (candidate == "partial", "hold", "candidate_partial"),
        (subject == "revoked", "hold", "subject_revoked"),
        (subject in ("measured", "partial"), "hold", "candidate_unmeasured"),
        (subject is None, "hold", "first_install_unmeasured"),
        (subject in ("unmeasured", "stale_context", "unresolved")
         and candidate in ("unmeasured", "stale_context"), "hold", "no_measured_build"),
    ]
    for number, (condition, action, reason) in enumerate(rows, start=1):
        if condition:
            return number, action, reason
    raise AssertionError(("no row", inputs_invalid, subject, candidate, same))


def test_ec_grokroll_3_the_decision_table_by_exhaustive_enumeration():
    seen_rows = set()
    for inputs_invalid, subject, candidate, same in itertools.product(
            (False, True), SUBJECT_STATES, CANDIDATE_STATES, (False, True)):
        if same and (subject is None or candidate == "unresolved" or subject == "unresolved"):
            continue  # a digest can be shared only by two resolved builds
        digest = "c" * 64 if candidate != "unresolved" else None
        subject_object = None if subject is None else {
            "state": subject, "binary_sha256": digest if same else (
                None if subject == "unresolved" else "d" * 64)}
        decision = st.decide(inputs_invalid=inputs_invalid, subject=subject_object,
                             candidate={"state": candidate, "binary_sha256": digest})
        row, action, reason = _expected(inputs_invalid, subject, candidate, same)
        seen_rows.add(row)
        assert decision == {"action": action, "reason": reason}, (inputs_invalid, subject,
                                                                  candidate, same)
        assert (decision["action"] == "advance") is (row == 7)
        if decision["action"] == "advance":
            assert not inputs_invalid and candidate == "measured" and subject != "invalid"
    assert seen_rows == set(range(1, 13))


@pytest.mark.parametrize("candidate_state", ["unresolved", "invalid", "revoked", "partial",
                                             "stale_context", "unmeasured"])
def test_ec_grokroll_3_each_falsifier_holds(candidate_state):
    for subject in SUBJECT_STATES:
        decision = st.decide(inputs_invalid=False,
                             subject=None if subject is None else {"state": subject,
                                                                    "binary_sha256": "d" * 64},
                             candidate={"state": candidate_state, "binary_sha256": "c" * 64})
        assert decision["action"] == "hold"
    for inputs_invalid, subject in ((True, None), (False, "invalid")):
        decision = st.decide(inputs_invalid=inputs_invalid,
                             subject=None if subject is None else {"state": subject,
                                                                    "binary_sha256": "d" * 64},
                             candidate={"state": "measured", "binary_sha256": "c" * 64})
        assert decision["action"] == "hold"


@pytest.mark.parametrize("inputs", ["surface catalog", "release catalog", "host records"])
def test_ec_grokroll_3_an_invalid_input_holds_and_nulls_both_targets(seat, monkeypatch, inputs):
    new = digest_of("new")
    releases(monkeypatch, [member("1.0.89", seat.digest), member("1.0.90", new)])
    publish(seat, surface(seat.digest))
    publish(seat, surface(new))
    if inputs == "surface catalog":
        catalog(monkeypatch, raw=b"{")
    elif inputs == "release catalog":
        releases(monkeypatch, raw=b"{")
    else:
        seat.root.chmod(0o755)
    code, document = run("--candidate-digest", new)
    assert code == 0
    assert document["decision"] == {"action": "hold", "reason": "inputs_invalid"}
    assert document["advance_to"] is None and document["rollback_to"] is None


def test_ec_grokroll_3_through_the_cli_with_a_candidate_selector(seat, monkeypatch, tmp_path):
    staged = _exe(tmp_path / "staged" / "grok", b"\x7fELF staged 1.0.90\n")
    staged_digest = sha256(staged.read_bytes()).hexdigest()
    releases(monkeypatch, [member("1.0.89", seat.digest), member("1.0.90", staged_digest)])
    publish(seat, surface(seat.digest))
    code, document = run("--candidate", str(staged))
    assert document["decision"] == {"action": "hold", "reason": "candidate_unmeasured"}
    assert document["candidate"]["version"] == "1.0.90"
    publish(seat, surface(staged_digest))
    code, document = run("--candidate", str(staged))
    assert document["decision"] == {"action": "advance", "reason": "candidate_measured"}
    code, document = run("--candidate-version", "1.0.91")
    assert document["candidate"]["state"] == "unresolved"
    assert document["decision"] == {"action": "hold", "reason": "candidate_unresolved"}


def test_ec_grokroll_3_no_subject_and_nothing_measured_hold_with_their_own_reasons(
        tmp_path, monkeypatch, seat):
    candidate = digest_of("new")
    code, document = run("--candidate-digest", candidate)
    assert document["decision"] == {"action": "hold", "reason": "no_measured_build"}
    seat.binary.unlink()
    code, document = run("--candidate-digest", candidate)
    assert document["subject"] is None
    assert document["decision"] == {"action": "hold", "reason": "first_install_unmeasured"}


# ------------------------------------------------------------------------- the targets

def test_ec_grokroll_3_targets_name_only_measured_members(seat, monkeypatch):
    """Members newest first: revoked, stale, partial, withdrawn, invalid, then measured,
    then the subject, then a measured older one. Only measured members are targets."""
    names = ["revoked", "stale", "partial", "withdrawn", "invalid", "measured_new"]
    digests = {name: digest_of(name) for name in names + ["measured_old"]}
    entries = [member("1.0.80", digests["measured_old"]), member("1.0.89", seat.digest)]
    entries += [member(f"1.0.{91 + index}", digests[name])
                for index, name in enumerate(reversed(names))]
    releases(monkeypatch, entries)
    catalog(monkeypatch, revoked=[digests["revoked"]])
    publish(seat, surface(digests["revoked"]))
    publish(seat, surface(digests["stale"], context_digest="d" * 64))
    publish(seat, surface(digests["partial"], refused=("review",)))
    publish(seat, surface(digests["withdrawn"]), register="superseded")
    put(seat, gts.host_record_name(digests["invalid"]), b"{")
    publish(seat, surface(digests["measured_new"]))
    publish(seat, surface(digests["measured_old"]))
    publish(seat, surface(seat.digest))
    code, document = run()
    assert document["advance_to"]["binary_sha256"] == digests["measured_new"]
    assert document["rollback_to"]["binary_sha256"] == digests["measured_old"]
    assert document["advance_to"]["tarball_integrity"].startswith("sha512-")
    # The same members, each named as a candidate, are held by their own state.
    for name, reason in (("revoked", "candidate_revoked"), ("stale", "candidate_unmeasured"),
                         ("partial", "candidate_partial"), ("withdrawn", "candidate_partial"),
                         ("invalid", "candidate_evidence_invalid")):
        code, document = run("--candidate-digest", digests[name])
        assert document["decision"] == {"action": "hold", "reason": reason}, name


def test_ec_grokroll_3_rollback_is_null_when_the_subject_version_is_unknown(seat, monkeypatch):
    old = digest_of("old")
    releases(monkeypatch, [member("1.0.80", old)])
    publish(seat, surface(old))
    code, document = run()
    assert document["subject"]["release"] == "unknown" and document["subject"]["version"] is None
    assert document["advance_to"]["version"] == "1.0.80"
    assert document["rollback_to"] is None


def test_selectors_by_digest_and_by_version(seat, monkeypatch):
    releases(monkeypatch, [member("1.0.89", seat.digest)])
    publish(seat, surface(seat.digest))
    by_version = run("--release-version", "1.0.89")[1]["subject"]
    by_digest = run("--binary-digest", seat.digest)[1]["subject"]
    assert by_version == by_digest and by_version["state"] == "measured"
    unknown = run("--release-version", "1.0.70")[1]["subject"]
    assert unknown["state"] == "unresolved" and unknown["binary_sha256"] is None


# ---------------------------------------------------------------- the shipped data

def test_the_shipped_data_answers_inert(seat):
    """The shipped release catalog is empty and the surface catalog has no surfaces, so
    every build is ``release: unknown`` and no target exists."""
    assert gts.load_catalog().surfaces == {}
    assert rc.check_tree().passed
    code, document = run()
    assert code == 0 and document["subject"]["release"] == "unknown"
    assert document["advance_to"] is None


# ------------------------------------------- catalog membership needs the gate (E1, R1)

def _bad_signature_member(digest: str) -> dict:
    """A structurally valid entry whose stored signature does not verify."""
    return member("1.0.90", digest, registry_signature="MEQCIAAAAAAAAAAAAAAAAAAAAA==")


@pytest.mark.parametrize("gate,state", [
    (None, "unattested"), (b"", "invalid"), (b'{"schema": "grok_catalog_gate.v1"}', "invalid"),
    (dict(ATTESTED_GATE, attested_at="2026-02-31T25:61:61Z"), "invalid"),
], ids=["shipped unattested", "empty", "malformed", "impossible attestation time"])
def test_ec_grokroll_3_without_an_attested_gate_no_membership_is_established(
        seat, monkeypatch, gate, state):
    new = digest_of("new")
    entry = _bad_signature_member(new)
    assert rc.verify_entry_signature(entry) is False
    releases(monkeypatch, [entry], gate=gate)
    publish(seat, surface(new))
    code, document = run("--candidate-version", "1.0.90")
    assert code == 0 and document["inputs"]["catalog_gate"] == state
    assert document["inputs"]["release_catalog"] == "ok"
    assert document["candidate"]["state"] == "unresolved"
    assert document["decision"] == {"action": "hold", "reason": "candidate_unresolved"}
    assert document["advance_to"] is None and document["rollback_to"] is None
    code, document = run("--candidate-digest", new)
    assert document["candidate"]["release"] == "unknown"
    assert document["candidate"]["version"] is None
    assert document["advance_to"] is None


def test_ec_grokroll_3_a_missing_gate_withholds_membership(seat, monkeypatch, tmp_path):
    package = tmp_path / "pkg"
    (package / "data").mkdir(parents=True)
    shipped = Path(rc.__file__).resolve().parents[1] / "data"
    for name in (rc.RELEASES_NAME, rc.SURFACES_NAME):
        (package / "data" / name).write_bytes((shipped / name).read_bytes())
    (package / "data" / rc.RELEASES_NAME).write_text(json.dumps(
        {"schema": rc.RELEASE_CATALOG_SCHEMA, "platform": rc.PLATFORM,
         "releases": [member("1.0.89", seat.digest)]}))
    monkeypatch.setattr(rc.resources, "files", lambda _package: package)
    publish(seat, surface(seat.digest))
    code, document = run("--release-version", "1.0.89")
    assert document["inputs"]["catalog_gate"] == "invalid"
    assert document["subject"]["state"] == "unresolved" and document["advance_to"] is None


def test_ec_grokroll_3_an_attested_gate_establishes_membership(seat, monkeypatch):
    new = digest_of("new")
    releases(monkeypatch, [member("1.0.89", seat.digest), member("1.0.90", new)])
    publish(seat, surface(seat.digest))
    publish(seat, surface(new))
    code, document = run("--candidate-version", "1.0.90")
    assert document["inputs"]["catalog_gate"] == "attested"
    assert document["candidate"]["release"] == "member"
    assert document["decision"] == {"action": "advance", "reason": "candidate_measured"}
    assert document["advance_to"]["version"] == "1.0.90"


# --------------------------------------------------------- receipt shape at the CLI (E2)

@pytest.mark.parametrize("case", ["unknown key", "repeated key", "malformed failed receipt"])
def test_ec_grokroll_3_an_ill_shaped_receipt_holds_the_candidate(seat, monkeypatch, case):
    from test_grok_evidence import failed_receipt

    new = digest_of("new")
    if case == "unknown key":
        write_receipt(seat, new, "review", listing_receipt(new, "review", note="x"))
    elif case == "repeated key":
        text = json.dumps(listing_receipt(new, "review"))
        write_receipt(seat, new, "review", (text[:-1] + ', "passed": true}').encode())
    else:
        write_receipt(seat, new, "review", failed_receipt(new, "review", tools=["read_file"]))
    code, document = run("--candidate-digest", new)
    assert document["candidate"]["state"] == "invalid"
    assert document["decision"] == {"action": "hold", "reason": "candidate_evidence_invalid"}


# --------------------------------------------- audit-based no-effect proof (real context)

_AUDIT: dict = {"active": False, "seen": []}
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
_EFFECT_EVENTS = ("socket.__new__", "socket.connect", "socket.getaddrinfo", "subprocess.Popen",
                  "os.exec", "os.posix_spawn", "os.fork", "os.forkpty", "os.system",
                  "os.mkdir", "os.rename", "os.replace", "os.remove", "os.rmdir", "os.symlink",
                  "os.link", "os.chmod", "os.chown", "os.truncate", "os.utime", "shutil.copyfile",
                  "shutil.rmtree")


def _audit(event, args):
    if not _AUDIT["active"]:
        return
    if event == "open":
        _path, mode, flags = (tuple(args) + (None, None, None))[:3]
        writes = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
            isinstance(flags, int) and flags & _WRITE_FLAGS)
        if writes:
            _AUDIT["seen"].append((event, str(args[0])))
    elif event in _EFFECT_EVENTS:
        _AUDIT["seen"].append((event, repr(args)[:200]))


_HOOK: list = []


def test_ec_grokroll_1_an_audited_run_over_real_context_and_populated_records_has_no_effect(
        tmp_path, monkeypatch):
    """The real packaged ``grok-review`` allow-list (no stub), a populated record root (a
    current host record and register, a listing receipt, a corrupt receipt) and a release
    catalog: the run raises no write, process, socket or filesystem-mutation audit event.
    Bytecode writing is off for the run, so "nothing written" covers a fresh source tree
    or a ``--no-compile`` install too."""
    from types import SimpleNamespace

    if not _HOOK:
        sys.addaudithook(_audit)
        _HOOK.append(True)
    bin_dir = tmp_path / "bin"
    native = _exe(bin_dir / "grok", NATIVE)
    digest = sha256(native.read_bytes()).hexdigest()
    monkeypatch.setattr(pi, "_PROVIDER_SEARCH_PATH", None)
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    from phase_loop_runtime import president_adapter as pa
    fake = SimpleNamespace(root=pa.private_record_root())
    publish(fake, surface(digest))
    other = digest_of("other")
    write_receipt(fake, other, "review", listing_receipt(other, "review"))
    write_receipt(fake, digest_of("third"), "review", b"{")
    releases(monkeypatch, [member("1.0.89", digest), member("1.0.90", other)])
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    before = sorted(str(path) for path in tmp_path.rglob("*"))
    _AUDIT["seen"] = []
    _AUDIT["active"] = True
    try:
        code, document = run("--candidate-version", "1.0.90", "--require-route", "review")
    finally:
        _AUDIT["active"] = False
    assert _AUDIT["seen"] == []
    assert sorted(str(path) for path in tmp_path.rglob("*")) == before
    assert code == 0 and document["subject"]["state"] == "measured"
    assert document["context_digest"] == gts.context_digest()  # the real allow-list
    assert document["decision"] == {"action": "advance", "reason": "candidate_measured"}
