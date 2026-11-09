"""JOURNAL SL-0: durable writer, admission index and verifying reader (IF-0-JOURNAL-1).

Everything enters through production entries. Vectors are materialized to disk
and read back through ``read_index``/``read_attempt``. Each mutation control
replaces exactly one asserted-present source fragment in an isolated module
copy; its witness passes on production and fails on the mutant.
"""
from __future__ import annotations

from collections import Counter
import errno
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import threading
from types import ModuleType

import pytest
import rfc8785

import _run_status_vectors as vectors
from phase_loop_runtime import __version__
from phase_loop_runtime import run_status as production

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the journal writer is Linux-only")

A = sha256(b"assignment-a").hexdigest()
B = sha256(b"assignment-b").hexdigest()
ENVELOPE = sha256(b"envelope").hexdigest()
SNAPSHOT = sha256(b"snapshot").hexdigest()
LAUNCH = sha256(b"launch").hexdigest()
CALLER = sha256(b'{"caller":"context"}').hexdigest()
SRC = str(Path(production.__file__).resolve().parents[1])


@pytest.fixture(autouse=True)
def umask077():
    previous = os.umask(0o077)
    yield
    os.umask(previous)


# --------------------------------------------------------------------------
# Helpers (every helper takes the module under test)
# --------------------------------------------------------------------------

def ident(m, attempt="attempt-1", run="run-1", assignment=A, envelope=ENVELOPE):
    return m.AttemptIdentity(assignment, envelope, run, attempt)


def units(m):
    return m.Units(("unit:target",), ("unit:neighbor",), SNAPSHOT)


def make_root(m, tmp_path, name="journal"):
    root = m.open_journal_root(tmp_path / name, create=True)
    assert isinstance(root, m.JournalRoot), root
    return root


def reopen(m, root):
    reopened = m.open_journal_root(root.path, create=False)
    assert isinstance(reopened, m.JournalRoot), reopened
    return reopened


def reserve(m, root, attempt="attempt-1", run="run-1", assignment=A):
    return m.reserve_attempt(root, ident(m, attempt, run, assignment), units=units(m), launch_digest=LAUNCH,
                             caller_context_sha256=CALLER)


def writer(m, root, attempt="attempt-1", limits=None, run="run-1", assignment=A):
    reservation = reserve(m, root, attempt, run, assignment)
    assert isinstance(reservation, m.Reservation), reservation
    opened = m.open_writer(root, reservation) if limits is None else m.open_writer(root, reservation, limits=limits)
    assert isinstance(opened, m.AttemptWriter), opened
    return reservation, opened


def evidence_digest(attempt):
    return sha256(b"evidence:" + attempt.encode()).hexdigest()


def binding(m, reservation):
    identity = reservation.identity
    return m.ResultBinding(identity.envelope_digest, identity.run_id, identity.attempt_id, None,
                           evidence_digest(identity.attempt_id))


def finish(m, attempt_writer, reservation, *, events=1):
    assert isinstance(attempt_writer.state("queued", worker_invocations=0), m.ChainHead)
    assert isinstance(attempt_writer.state("running", worker_invocations=1), m.ChainHead)
    for _ in range(events):
        assert isinstance(attempt_writer.event("output streams digested",
                                               refs=(m.make_ref("stdout", b"out", None),)), m.ChainHead)
    head = attempt_writer.terminal("finished", worker_invocations=1,
                                   termination=m.Termination("completed", None, "worker"), refusal=None,
                                   result_binding=binding(m, reservation))
    assert isinstance(head, m.ChainHead), head
    return head


def finished_attempt(tmp_path, attempt="attempt-1", events=1, limits=None):
    root = make_root(production, tmp_path)
    reservation, attempt_writer = writer(production, root, attempt, limits)
    head = finish(production, attempt_writer, reservation, events=events)
    attempt_writer.close()
    return root, reservation, head


def snapshot(path):
    state = {}
    for directory, names, files in os.walk(path):
        for name in names + files:
            full = Path(directory) / name
            st = os.lstat(full)
            data = full.read_bytes() if stat.S_ISREG(st.st_mode) else None
            state[str(full.relative_to(path))] = (st.st_mode, st.st_mtime_ns, st.st_nlink, data)
    st = os.lstat(path)
    state["."] = (st.st_mode, st.st_mtime_ns, st.st_nlink, None)
    return state


def segment_files(root, attempt="attempt-1"):
    return sorted((root.path / "attempts" / attempt).glob("*.jsonl"))


def journal_lines(root, attempt="attempt-1"):
    return [json.loads(raw) for path in segment_files(root, attempt) for raw in path.read_bytes().splitlines()]


def rewrite(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_TRUNC)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def read_vector(m, tmp_path, journal):
    path = vectors.materialize(journal, tmp_path / "vector")
    root = m.open_journal_root(path, create=False)
    assert isinstance(root, m.JournalRoot), root
    diagnostics, displays = set(), []
    for digest in dict.fromkeys(a["segments"][0]["lines"][0]["attempt"]["assignment_digest"]
                                for a in journal["attempts"]):
        diagnostics |= set(m.read_index(root, digest).diagnostics)
    for attempt_id in vectors.attempt_ids(journal):
        read = m.read_attempt(root, attempt_id)
        diagnostics |= set(read.diagnostics)
        displays.append(read.display)
    return diagnostics, displays


def vector_witness(m, tmp_path, case_id):
    item = vectors.case(case_id)
    diagnostics, displays = read_vector(m, tmp_path, vectors.expand(case_id)["journal"])
    assert diagnostics == set(item["expected"]), (case_id, diagnostics)
    if item.get("expected_effect"):
        assert displays == item["expected_effect"]["display"]


def refused(m, code):
    return m.JournalRefused(code)


CHILD = ("import sys; sys.path.insert(0, sys.argv[1])\n"
         "import json, os, time\nfrom pathlib import Path\nfrom phase_loop_runtime import run_status as rs\n")


def child(code, *args):
    return subprocess.Popen([sys.executable, "-I", "-c", CHILD + code, SRC, *map(str, args)],
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


# --------------------------------------------------------------------------
# Pinned vectors through production readers
# --------------------------------------------------------------------------

def test_vector_ownership_counts():
    assert Counter(c["kind"] for c in vectors.cases()) == {
        "journal": 19, "projection": 4, "liveness": 3, "reader_view": 5, "page": 4}


@pytest.mark.parametrize("case_id", vectors.ids("journal"))
def test_journal_vector_through_production_readers(tmp_path, case_id):
    vector_witness(production, tmp_path, case_id)
    if vectors.case(case_id)["role"] == "control":
        # Controls carry foreign-format writer strings and non-section-9
        # messages; readers must still accept them without a diagnostic.
        journal = vectors.expand(case_id)["journal"]
        writers = {a["segments"][0]["lines"][0]["writer"]["writer_instance_id"] for a in journal["attempts"]}
        assert writers == {"writer-1"}


def test_vector_harness_asserts_every_edit(tmp_path):
    expanded = vectors.expand("N15-foreign-writer")
    line = expanded["journal"]["attempts"][0]["segments"][0]["lines"][3]
    assert line["writer"]["writer_instance_id"] == "writer-2"
    assert vectors.expand("V-running") == vectors.case("V-running")["input"]


# --------------------------------------------------------------------------
# Structural checker cross-check against the pinned schema
# --------------------------------------------------------------------------

def resolved(schema, node):
    if isinstance(node, dict):
        if "$ref" in node:
            assert set(node) == {"$ref"}
            target = schema
            for token in node["$ref"].removeprefix("#/").split("/"):
                target = target[token]
            return resolved(schema, target)
        return {key: resolved(schema, value) for key, value in node.items() if key not in ("description", "title")}
    if isinstance(node, list):
        return [resolved(schema, item) for item in node]
    return node


def test_structure_tables_equal_pinned_schema():
    schema = vectors.schema()
    assert set(production.STRUCTURE) == set(vectors.DEFINITIONS)
    for name in vectors.DEFINITIONS:
        assert production.STRUCTURE[name] == resolved(schema, schema["$defs"][name]), name
    rules = schema["x-journal-rules"]
    assert set(schema["x-semantic-rules"]) == production.PUBLIC_CODES
    assert production.PUBLIC_CODES.isdisjoint(production.LOCAL_CODES)
    assert rules["bounds"]["per_attempt_event_cap"] == production.DEFAULT_LIMITS.per_attempt_line_cap
    assert rules["bounds"]["event_message_max_chars"] == production.DEFAULT_LIMITS.event_message_max_chars
    assert {k: list(v) for k, v in production._NEXT.items() if k is not None} == rules["lifecycle"]


def vector_records():
    for item in vectors.cases():
        value = vectors.expand(item["id"])
        for attempt in value.get("journal", {}).get("attempts", ()):
            for segment in attempt["segments"]:
                for line in segment["lines"]:
                    if isinstance(line, dict):
                        yield "journal_line", line
        if item["kind"] == "projection":
            yield "projection", value["projection"]
        if item["kind"] == "reader_view":
            yield "reader_view", value
        if item["kind"] == "page":
            yield "page_request", value["request"]
            yield "page", value["page"]
            for line in value["page"]["events"]:
                yield "journal_line", line


def variants(definition, record):
    """Structurally invalid neighbours: both validators must reject them too."""
    yield dict(record, extra=1)
    first = next(iter(record))
    yield {k: v for k, v in record.items() if k != first}
    if definition == "journal_line":
        yield dict(record, seq=-1)
        yield dict(record, line_kind="bogus")
        yield dict(record, redaction_posture="raw")
        yield dict(record, attempt=dict(record["attempt"], run_id="r" * 129))
        yield dict(record, attempt=dict(record["attempt"], assignment_digest="A" * 64))
        yield dict(record, units=dict(record["units"], target_unit_ids=[]))
        yield dict(record, writer=dict(record["writer"], owner_pid=0))
        yield dict(record, writer=dict(record["writer"], owner_pid=True))
        yield dict(record, body=dict(record["body"], body_kind="other"))


def test_structural_checker_agrees_with_pinned_validator():
    total = rejected = 0
    for definition, record in vector_records():
        assert production.check_structure(definition, record) is True
        assert vectors.validate_record(definition, record) is True
        for variant in variants(definition, record):
            verdict = production.check_structure(definition, variant)
            assert verdict == vectors.validate_record(definition, variant), (definition, variant)
            rejected += not verdict
        total += 1
    assert total > 150 and rejected > 1000


def test_structural_checker_agrees_on_produced_records(tmp_path):
    root, reservation, _ = finished_attempt(tmp_path, events=3, limits=production.JournalLimits(segment_max_lines=3))
    lines = journal_lines(root)
    assert len(lines) >= 8
    for line in lines:
        assert production.check_structure("journal_line", line)
        assert vectors.validate_record("journal_line", line)


# --------------------------------------------------------------------------
# Storage trust
# --------------------------------------------------------------------------

def test_default_root_ignores_hostile_environment(monkeypatch):
    import pwd
    expected = Path(pwd.getpwuid(os.geteuid()).pw_dir) / ".local/state/agent-harness/supervised-worker/journal"
    monkeypatch.setenv("HOME", "/tmp/hostile-home")
    monkeypatch.setenv("XDG_STATE_HOME", "/tmp/hostile-state")
    assert production.default_journal_root() == expected


def test_root_creation_modes_and_layout(tmp_path):
    os.umask(0o000)
    root = make_root(production, tmp_path, "a/b/journal")
    for path in (tmp_path / "a", tmp_path / "a/b", root.path, root.path / "attempts",
                 root.path / "assignments", root.path / "runs"):
        st = os.lstat(path)
        assert stat.S_IMODE(st.st_mode) == 0o700 and st.st_uid == os.geteuid()
    assert sorted(os.listdir(root.path)) == ["assignments", "attempts", "runs"]


@pytest.mark.parametrize("path", ["relative/journal", "/x/../journal", "/x/\x00journal"])
def test_root_path_refusals(path):
    assert production.open_journal_root(path, create=True) == refused(production, "journal_root_unsafe")


def test_root_missing_without_create(tmp_path):
    assert production.open_journal_root(tmp_path / "absent", create=False) == refused(production, "journal_missing")


@pytest.mark.parametrize("mode", [0o750, 0o770, 0o707, 0o705, 0o1700])
def test_root_mode_refused(tmp_path, mode):
    root = make_root(production, tmp_path)
    os.chmod(root.path, mode)
    assert production.open_journal_root(root.path, create=False) == refused(production, "journal_root_unsafe")
    assert reserve(production, root) == refused(production, "journal_path_unsafe")
    assert production.read_attempt(root, "attempt-1").diagnostics == ("journal_path_unsafe",)


def test_wrong_owner_refused(tmp_path, monkeypatch):
    root = make_root(production, tmp_path)
    real = os.geteuid()
    with monkeypatch.context() as patch:
        patch.setattr(os, "geteuid", lambda: real + 1)
        assert production.open_journal_root(root.path, create=False) == refused(production, "journal_root_unsafe")
        assert production.read_index(root, A).diagnostics == ("journal_path_unsafe",)


def test_symlinked_components_refused(tmp_path):
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    (tmp_path / "link").symlink_to(real)
    assert production.open_journal_root(tmp_path / "link" / "journal", create=True) == refused(
        production, "journal_root_unsafe")
    assert not (real / "journal").exists()
    root = make_root(production, real)
    (real / "attempts-real").mkdir(mode=0o700)
    os.rmdir(root.path / "attempts")
    (root.path / "attempts").symlink_to(real / "attempts-real")
    assert production.open_journal_root(root.path, create=False) == refused(production, "journal_root_unsafe")
    assert production.read_attempt(root, "attempt-1").diagnostics == ("journal_path_unsafe",)


@pytest.mark.parametrize("relation", ["equal", "inside", "containing"])
def test_root_and_excluded_roots_disjoint(tmp_path, relation):
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    path = {"equal": workspace, "inside": workspace / "state/journal", "containing": tmp_path}[relation]
    if relation == "containing":
        os.chmod(tmp_path, 0o700)
    assert production.open_journal_root(path, create=True, excluded=(workspace,)) == refused(
        production, "journal_root_unsafe")
    assert production.open_journal_root(tmp_path / "elsewhere", create=True, excluded=("relative",)) == refused(
        production, "journal_root_unsafe")
    assert isinstance(production.open_journal_root(tmp_path / "elsewhere", create=True, excluded=(workspace,)),
                      production.JournalRoot)


def test_excluded_root_by_inode_through_alias(tmp_path):
    os.chmod(tmp_path, 0o700)
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(workspace)
    assert production.open_journal_root(workspace / "journal", create=True, excluded=(alias,)) == refused(
        production, "journal_root_unsafe")


def test_hardlinked_segment_and_nonregular_entries(tmp_path):
    root, _, _ = finished_attempt(tmp_path)
    segment = segment_files(root)[0]
    os.link(segment, tmp_path / "copy")
    assert production.read_attempt(root, "attempt-1").diagnostics == ("journal_path_unsafe",)
    os.unlink(tmp_path / "copy")
    assert production.read_attempt(root, "attempt-1").diagnostics == ()
    os.mkfifo(segment.parent / "0001.jsonl", 0o600)
    assert production.read_attempt(root, "attempt-1").diagnostics == ("journal_path_unsafe",)
    os.unlink(segment.parent / "0001.jsonl")
    (segment.parent / "0001.jsonl").mkdir(mode=0o700)
    assert production.read_attempt(root, "attempt-1").diagnostics == ("journal_path_unsafe",)


def test_unexpected_entry_and_unsafe_modes(tmp_path):
    root, _, _ = finished_attempt(tmp_path)
    directory = root.path / "attempts/attempt-1"
    (directory / "notes").write_bytes(b"x")
    assert production.read_attempt(root, "attempt-1").diagnostics == ("journal_unexpected_entry",)
    os.unlink(directory / "notes")
    for path, mode in ((segment_files(root)[0], 0o640), (segment_files(root)[0], 0o604), (directory, 0o750),
                       (directory / "lock", 0o660)):
        original = stat.S_IMODE(os.lstat(path).st_mode)
        os.chmod(path, mode)
        assert production.read_attempt(root, "attempt-1").diagnostics == ("journal_path_unsafe",), path
        os.chmod(path, original)
    index = root.path / "assignments" / A / "index.jsonl"
    os.chmod(index, 0o660)
    assert production.read_index(root, A).diagnostics == ("journal_path_unsafe",)
    assert reserve(production, root, "attempt-2") == refused(production, "journal_path_unsafe")


@pytest.mark.parametrize("bad", ["", ".", "..", "a/b", "-lead", "x" * 129, "x\n", "ä", "a b", None, 7])
def test_identifiers_refused_before_any_effect(tmp_path, bad):
    root = make_root(production, tmp_path)
    before = snapshot(root.path)
    for identity in (ident(production, attempt=bad), ident(production, run=bad)):
        assert production.reserve_attempt(root, identity, units=units(production), launch_digest=LAUNCH,
                                          caller_context_sha256=CALLER) == refused(production, "identifier_invalid")
    assert production.read_attempt(root, bad).diagnostics == ("identifier_invalid",)
    assert production.resolve_run(root, bad) == refused(production, "identifier_invalid")
    assert snapshot(root.path) == before


def test_digest_and_unit_refusals(tmp_path):
    root = make_root(production, tmp_path)
    before = snapshot(root.path)
    cases = [dict(launch_digest="F" * 64), dict(caller_context_sha256="0" * 63),
             dict(units=production.Units((), (), SNAPSHOT)), dict(units=production.Units(("u" * 201,), (), SNAPSHOT)),
             dict(units=production.Units(("u",), (), "z" * 64))]
    for override in cases:
        kwargs = {"units": units(production), "launch_digest": LAUNCH, "caller_context_sha256": CALLER, **override}
        assert production.reserve_attempt(root, ident(production), **kwargs) == refused(
            production, "identifier_invalid")
    assert production.reserve_attempt(root, ident(production, assignment="A" * 64), units=units(production),
                                      launch_digest=LAUNCH, caller_context_sha256=CALLER) == refused(
        production, "identifier_invalid")
    assert snapshot(root.path) == before


def test_longest_identifier_accepted(tmp_path):
    root = make_root(production, tmp_path)
    longest = "a" * 128
    reservation = reserve(production, root, attempt=longest, run=longest)
    assert isinstance(reservation, production.Reservation)
    assert production.resolve_run(root, longest) == (longest,)


# --------------------------------------------------------------------------
# Reader integrity
# --------------------------------------------------------------------------

def test_missing_journal_and_reserved_without_writer(tmp_path):
    root = make_root(production, tmp_path)
    missing = production.read_attempt(root, "attempt-1")
    assert missing.diagnostics == ("journal_missing",) and missing.display == "unknown"
    reservation = reserve(production, root)
    read = production.read_attempt(root, "attempt-1")
    assert read.diagnostics == ("journal_missing",) and read.display == "unknown"
    assert read.identity == reservation.identity and read.writer == reservation.writer


def test_missing_interior_segment_is_overwritten(tmp_path):
    root, _, _ = finished_attempt(tmp_path, events=4, limits=production.JournalLimits(segment_max_lines=3))
    files = segment_files(root)
    assert len(files) >= 3
    os.unlink(files[1])
    read = production.read_attempt(root, "attempt-1")
    assert read.diagnostics == ("attempt_overwritten",) and read.display == "unknown"


def test_unindexed_attempt_reads_unknown(tmp_path):
    root, _, _ = finished_attempt(tmp_path)
    index = root.path / "assignments" / A / "index.jsonl"
    rewrite(index, b"")
    read = production.read_attempt(root, "attempt-1")
    assert read.diagnostics == ("attempt_unindexed",) and read.display == "unknown"
    os.mkdir(root.path / "attempts/attempt-9", 0o700)
    assert set(production.read_attempt(root, "attempt-9").diagnostics) == {"journal_missing", "attempt_unindexed"}


def test_identity_versus_directory_and_index(tmp_path):
    root, reservation, _ = finished_attempt(tmp_path)
    os.rename(root.path / "attempts/attempt-1", root.path / "attempts/attempt-x")
    assert set(production.read_attempt(root, "attempt-x").diagnostics) == {
        "attempt_provenance_mismatch", "attempt_unindexed"}
    os.rename(root.path / "attempts/attempt-x", root.path / "attempts/attempt-1")
    index = root.path / "assignments" / A / "index.jsonl"
    original = index.read_bytes()
    entry = json.loads(original)
    for field, value in (("envelope_digest", B), ("run_id", "run-9")):
        rewrite(index, vectors.index_bytes([dict(entry, **{field: value})]))
        assert production.read_attempt(root, "attempt-1").diagnostics == ("attempt_provenance_mismatch",), field
    rewrite(index, vectors.index_bytes([dict(entry, units=dict(entry["units"], snapshot_ref=B))]))
    assert production.read_attempt(root, "attempt-1").diagnostics == ("attempt_provenance_mismatch",)
    rewrite(index, vectors.index_bytes([dict(entry, writer=dict(entry["writer"], writer_instance_id="0" * 32))]))
    assert production.read_attempt(root, "attempt-1").diagnostics == ("journal_foreign_writer",)
    rewrite(index, original)
    assert production.read_attempt(root, "attempt-1").diagnostics == ()


def test_index_defects_are_unverifiable(tmp_path):
    root, _, _ = finished_attempt(tmp_path)
    index = root.path / "assignments" / A / "index.jsonl"
    original = index.read_bytes()
    entry = json.loads(original)
    defects = [original + b'{"schema":', original.rstrip(b"\n"), original + original,
               vectors.index_bytes([dict(entry, assignment_digest=B)]),
               vectors.index_bytes([dict(entry, schema="other")]),
               json.dumps(entry).encode() + b"\n",
               rfc8785.dumps(dict(entry, index_seq=1)) + b"\n"]
    for data in defects:
        rewrite(index, data)
        assert production.read_index(root, A).diagnostics == ("index_unverifiable",)
        assert production.read_attempt(root, "attempt-1").diagnostics == ("index_unverifiable",)
        assert production.resolve_run(root, "run-1") == refused(production, "index_unverifiable")
    rewrite(index, original)
    assert production.read_index(root, A).diagnostics == ()


def test_reader_leaves_bytes_modes_and_mtimes(tmp_path):
    root, _, _ = finished_attempt(tmp_path)
    reserve(production, root, "attempt-2")
    os.mkdir(root.path / "attempts/attempt-9", 0o700)
    torn = segment_files(root)[0]
    with open(torn, "ab") as handle:
        handle.write(b'{"torn":')
    before = snapshot(root.path)
    for attempt in ("attempt-1", "attempt-2", "attempt-9", "absent-1"):
        production.read_attempt(root, attempt)
    production.read_index(root, A)
    production.read_index(root, B)
    production.resolve_run(root, "run-1")
    production.resolve_run(root, "run-absent")
    assert production.read_attempt(root, "attempt-1").diagnostics == ("journal_torn_line",)
    assert snapshot(root.path) == before


# --------------------------------------------------------------------------
# Writer rules
# --------------------------------------------------------------------------

def test_lifecycle_violations_write_nothing(tmp_path):
    root = make_root(production, tmp_path)
    reservation, attempt_writer = writer(production, root)
    segment = segment_files(root)[0]
    term = production.Termination("completed", None, "worker")
    refusal = production.TerminalRefusal("constraint_unsupported", "network_denial", None)
    bound = binding(production, reservation)

    def unchanged(call, code="lifecycle_invalid"):
        before = segment.read_bytes()
        assert call() == refused(production, code)
        assert segment.read_bytes() == before

    unchanged(lambda: attempt_writer.state("running", worker_invocations=1))
    unchanged(lambda: attempt_writer.state("paused", worker_invocations=0))
    unchanged(lambda: attempt_writer.state("queued", worker_invocations=-1))
    unchanged(lambda: attempt_writer.state("queued", worker_invocations=True))
    unchanged(lambda: attempt_writer.terminal("finished", worker_invocations=0, termination=term, refusal=None,
                                              result_binding=None))
    assert isinstance(attempt_writer.state("queued", worker_invocations=0), production.ChainHead)
    unchanged(lambda: attempt_writer.state("queued", worker_invocations=0))
    unchanged(lambda: attempt_writer.terminal("refused", worker_invocations=1, termination=None, refusal=refusal,
                                              result_binding=None))
    unchanged(lambda: attempt_writer.terminal("refused", worker_invocations=0, termination=None, refusal=None,
                                              result_binding=None))
    unchanged(lambda: attempt_writer.terminal("refused", worker_invocations=0, termination=term, refusal=refusal,
                                              result_binding=None))
    unchanged(lambda: attempt_writer.terminal("refused", worker_invocations=0, termination=None, refusal=refusal,
                                              result_binding=bound))
    assert isinstance(attempt_writer.state("running", worker_invocations=2), production.ChainHead)
    unchanged(lambda: attempt_writer.state("cancelling", worker_invocations=1))
    unchanged(lambda: attempt_writer.terminal("refused", worker_invocations=0, termination=None, refusal=refusal,
                                              result_binding=None))
    unchanged(lambda: attempt_writer.terminal("finished", worker_invocations=2, termination=None, refusal=None,
                                              result_binding=bound))
    unchanged(lambda: attempt_writer.terminal("finished", worker_invocations=2, termination=term, refusal=refusal,
                                              result_binding=bound))
    unchanged(lambda: attempt_writer.terminal("finished", worker_invocations=2,
                                              termination=production.Termination("exploded", None, "worker"),
                                              refusal=None, result_binding=bound))
    foreign = production.ResultBinding(ENVELOPE, "run-9", "attempt-1", None, evidence_digest("attempt-1"))
    unchanged(lambda: attempt_writer.terminal("finished", worker_invocations=2, termination=term, refusal=None,
                                              result_binding=foreign), "attempt_provenance_mismatch")
    assert isinstance(attempt_writer.terminal("finished", worker_invocations=2, termination=term, refusal=None,
                                              result_binding=bound), production.ChainHead)
    unchanged(lambda: attempt_writer.state("running", worker_invocations=2))
    unchanged(lambda: attempt_writer.event("attempt queued"))
    unchanged(lambda: attempt_writer.terminal("finished", worker_invocations=2, termination=term, refusal=None,
                                              result_binding=bound))
    attempt_writer.close()
    unchanged(lambda: attempt_writer.event("attempt queued"), "writer_closed")
    read = production.read_attempt(root, "attempt-1")
    assert read.diagnostics == () and read.display == "finished"
    assert read.terminal.termination == term and read.terminal.result_binding == bound


def test_refused_before_launch_round_trip(tmp_path):
    root = make_root(production, tmp_path)
    _, attempt_writer = writer(production, root)
    attempt_writer.state("queued", worker_invocations=0)
    refusal = production.TerminalRefusal("constraint_unsupported", "network_denial", "provider_readonly")
    assert isinstance(attempt_writer.terminal("refused", worker_invocations=0, termination=None, refusal=refusal,
                                              result_binding=None), production.ChainHead)
    attempt_writer.close()
    read = production.read_attempt(root, "attempt-1")
    assert read.display == "refused" and read.terminal.refusal == refusal and read.diagnostics == ()


@pytest.mark.parametrize("phrase", ["worker returned a proposal", "attempt queued\n", "", None, ["attempt queued"]])
def test_event_phrase_set_is_closed(tmp_path, phrase):
    root = make_root(production, tmp_path)
    _, attempt_writer = writer(production, root)
    before = segment_files(root)[0].read_bytes()
    assert attempt_writer.event(phrase) == refused(production, "phrase_invalid")
    assert segment_files(root)[0].read_bytes() == before
    for allowed in sorted(production.EVENT_PHRASES):
        assert isinstance(attempt_writer.event(allowed), production.ChainHead)
    attempt_writer.close()


def test_event_refs_built_only_by_make_ref(tmp_path):
    root = make_root(production, tmp_path)
    _, attempt_writer = writer(production, root)
    good = production.make_ref("stdout", b"x", "logs/out.txt")
    for bad in ((production.Ref("stdout", "raw text", None),), ({"kind": "stdout"},),
                (production.Ref("stdout", good.sha256, "/abs"),), (good,) * 17, 7):
        assert attempt_writer.event("output streams digested", refs=bad) == refused(production, "ref_invalid")
    assert isinstance(attempt_writer.event("output streams digested", refs=(good,)), production.ChainHead)
    for kind, locator in (("other", None), ("stdout", "../x"), ("stdout", "/x"), ("stdout", "a\\b"),
                          ("stdout", ""), ("stdout", "x" * 513)):
        with pytest.raises(ValueError):
            production.make_ref(kind, b"x", locator)
    with pytest.raises(ValueError):
        production.make_ref("stdout", "text", None)
    attempt_writer.close()


def line_cap_witness(m, tmp_path):
    root = make_root(m, tmp_path)
    reservation, attempt_writer = writer(m, root, limits=m.JournalLimits(per_attempt_line_cap=8, segment_max_lines=3))
    attempt_writer.state("queued", worker_invocations=0)
    attempt_writer.state("running", worker_invocations=1)
    heads = [attempt_writer.event("output streams digested") for _ in range(4)]
    assert [type(head).__name__ for head in heads] == ["ChainHead", "ChainHead", "JournalRefused", "JournalRefused"]
    assert heads[2] == m.JournalRefused("event_cap_reached")
    head = attempt_writer.terminal("finished", worker_invocations=1, termination=m.Termination("completed", None, "worker"),
                                   refusal=None, result_binding=binding(m, reservation))
    assert isinstance(head, m.ChainHead) and head.segment_index == 2 and head.last_seq == 7
    attempt_writer.close()
    assert sum(len(path.read_bytes().splitlines()) for path in segment_files(root)) == 8
    read = production.read_attempt(production.open_journal_root(root.path, create=False), "attempt-1")
    assert read.diagnostics == () and read.display == "finished"


def test_line_cap_reserves_terminal_headroom_across_rotation(tmp_path):
    line_cap_witness(production, tmp_path)


def segment_chain_witness(m, tmp_path):
    root = make_root(m, tmp_path)
    reservation, attempt_writer = writer(m, root, limits=m.JournalLimits(segment_max_lines=3))
    head = finish(m, attempt_writer, reservation, events=4)
    attempt_writer.close()
    files = segment_files(root)
    assert len(files) >= 3
    for previous, current in zip(files, files[1:]):
        header = json.loads(current.read_bytes().splitlines()[0])
        assert header["body"]["previous_segment_sha256"] == sha256(previous.read_bytes()).hexdigest()
        assert header["body"]["previous_last_seq"] == json.loads(previous.read_bytes().splitlines()[-1])["seq"]
    assert head.segment_sha256 == sha256(files[-1].read_bytes()).hexdigest()
    assert head.segment_index == len(files) - 1
    read = production.read_attempt(production.open_journal_root(root.path, create=False), "attempt-1")
    assert read.diagnostics == () and read.chain_head == production.ChainHead(*vars_of(head))


def vars_of(head):
    return head.segment_index, head.segment_sha256, head.last_seq


def test_rotation_chains_segments(tmp_path):
    segment_chain_witness(production, tmp_path)


def test_limits_validated(tmp_path):
    root = make_root(production, tmp_path)
    reservation = reserve(production, root)
    for limits in (production.JournalLimits(per_attempt_line_cap=3), production.JournalLimits(segment_max_lines=1),
                   production.JournalLimits(segment_max_bytes=1000),
                   production.JournalLimits(read_segment_max_bytes=1024),
                   production.JournalLimits(event_message_max_chars=201), "big"):
        assert production.open_writer(root, reservation, limits=limits) == refused(production, "limits_invalid")
    assert isinstance(production.open_writer(root, reservation), production.AttemptWriter)


# --------------------------------------------------------------------------
# Writer poisoning
# --------------------------------------------------------------------------

def poison_witness(m, tmp_path, monkeypatch, primitive="write"):
    root = make_root(m, tmp_path)
    reservation, attempt_writer = writer(m, root)
    attempt_writer.state("queued", worker_invocations=0)

    def boom(*args):
        raise OSError(errno.EIO, "injected")

    with monkeypatch.context() as patch:
        if primitive == "short":
            patch.setattr(os, "write", lambda fd, data: 0)
        else:
            patch.setattr(os, primitive, boom)
        assert attempt_writer.event("attempt queued") == m.JournalRefused("journal_write_failed")
    segment = segment_files(root)[0]
    before = segment.read_bytes()
    assert attempt_writer.event("attempt queued") == m.JournalRefused("writer_poisoned")
    assert attempt_writer.state("running", worker_invocations=1) == m.JournalRefused("writer_poisoned")
    assert attempt_writer.terminal("finished", worker_invocations=1, termination=m.Termination("completed", None, "worker"),
                                   refusal=None, result_binding=binding(m, reservation)) == m.JournalRefused(
        "writer_poisoned")
    assert segment.read_bytes() == before
    attempt_writer.close()
    fd = os.open(root.path / "attempts/attempt-1/lock", os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(fd)


@pytest.mark.parametrize("primitive", ["write", "fsync", "short"])
def test_writer_poisoned_after_failed_write_or_fsync(tmp_path, monkeypatch, primitive):
    poison_witness(production, tmp_path, monkeypatch, primitive)


def test_partial_line_reads_torn_after_poison(tmp_path, monkeypatch):
    root = make_root(production, tmp_path)
    _, attempt_writer = writer(production, root)
    real = os.write

    def partial(fd, data):
        if len(data) > 10:
            return real(fd, bytes(data[:10]))
        raise OSError(errno.ENOSPC, "full")

    with monkeypatch.context() as patch:
        patch.setattr(os, "write", partial)
        assert attempt_writer.state("queued", worker_invocations=0) == refused(production, "journal_write_failed")
    attempt_writer.close()
    assert production.read_attempt(root, "attempt-1").diagnostics == ("journal_torn_line",)


# --------------------------------------------------------------------------
# Writer identity and ownership
# --------------------------------------------------------------------------

def writer_identity_witness(m, tmp_path):
    root = make_root(m, tmp_path)
    reservation, attempt_writer = writer(m, root)
    finish(m, attempt_writer, reservation)
    attempt_writer.close()
    entry = m.read_index(root, A).entries[0]
    assert entry.writer == reservation.writer
    expected = {"harness_id": "phase-loop-runtime", "harness_version": __version__,
                "writer_instance_id": reservation.writer.writer_instance_id, "owner_pid": os.getpid(),
                "process_start_time": production.process_start_identity(os.getpid())}
    assert {name: getattr(reservation.writer, name) for name in expected} == expected
    assert re.fullmatch(r"[0-9a-f]{32}", reservation.writer.writer_instance_id)
    assert reservation.writer.process_start_time.startswith("linux-proc:")
    assert [line["writer"] for line in journal_lines(root)] == [expected] * len(journal_lines(root))
    assert production.read_attempt(production.open_journal_root(root.path, create=False), "attempt-1").diagnostics == ()


def test_writer_identity_minted_once(tmp_path):
    writer_identity_witness(production, tmp_path)


def test_writer_ownership(tmp_path):
    root = make_root(production, tmp_path)
    reservation, first = writer(production, root)
    assert production.open_writer(root, reservation) == refused(production, "journal_writer_busy")
    first.close()
    assert production.open_writer(root, reservation) == refused(production, "journal_exists")
    other = reserve(production, root, "attempt-2")
    forged = production.Reservation(other.identity, other.units, other.index_seq, other.entry_sha256,
                                    production.WriterIdentity(other.writer.harness_id, other.writer.harness_version,
                                                              "0" * 32, os.getpid(), other.writer.process_start_time))
    assert production.open_writer(root, forged) == refused(production, "attempt_unindexed")
    moved = production.Reservation(other.identity, other.units, other.index_seq, other.entry_sha256,
                                   production.WriterIdentity(other.writer.harness_id, other.writer.harness_version,
                                                             other.writer.writer_instance_id, os.getpid() + 1,
                                                             other.writer.process_start_time))
    assert production.open_writer(root, moved) == refused(production, "writer_identity_mismatch")
    payload = json.dumps({"path": str(root.path), "identity": vars_dict(other.identity),
                          "units": [list(other.units.target_unit_ids), list(other.units.readonly_neighbor_unit_ids),
                                    other.units.snapshot_ref],
                          "index_seq": other.index_seq, "entry": other.entry_sha256, "writer": vars_dict(other.writer)})
    process = child(
        "p = json.loads(sys.argv[2]); root = rs.open_journal_root(Path(p['path']), create=False)\n"
        "r = rs.Reservation(rs.AttemptIdentity(**p['identity']), rs.Units(tuple(p['units'][0]), tuple(p['units'][1]),"
        " p['units'][2]), p['index_seq'], p['entry'], rs.WriterIdentity(**p['writer']))\n"
        "print(getattr(rs.open_writer(root, r), 'code', 'opened'))\n", payload)
    out, err = process.communicate(timeout=60)
    assert process.returncode == 0, err
    assert out.strip() == "writer_identity_mismatch"
    assert not segment_files(root, "attempt-2")


def vars_dict(record):
    return {name: getattr(record, name) for name in record.__dataclass_fields__}


# --------------------------------------------------------------------------
# Reservation and admission index
# --------------------------------------------------------------------------

def test_reservation_refusals(tmp_path):
    root, reservation, _ = finished_attempt(tmp_path)
    assert reserve(production, root) == refused(production, "attempt_reserved")
    assert reserve(production, root, run="run-2") == refused(production, "attempt_reserved")
    assert reserve(production, root, assignment=B, run="run-b") == refused(production, "attempt_reserved")
    os.mkdir(root.path / "attempts/attempt-crashed", 0o700)
    assert reserve(production, root, "attempt-crashed") == refused(production, "attempt_reserved")
    assert reserve(production, root, "attempt-2", run="run-1", assignment=B) == refused(
        production, "run_assignment_mismatch")
    for data in (b"", b"abc", A.encode(), (A + "\nmore").encode()):
        record = root.path / "runs/run-bad"
        if record.exists():
            os.unlink(record)
        fd = os.open(record, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.write(fd, data)
        os.close(fd)
        assert reserve(production, root, "attempt-3", run="run-bad") == refused(production, "run_record_unreadable")
        assert production.resolve_run(root, "run-bad") == refused(production, "run_record_unreadable")
    assert production.resolve_run(root, "run-absent") == ()
    second = reserve(production, root, "attempt-2")
    assert second.index_seq == 1 and production.resolve_run(root, "run-1") == ("attempt-1", "attempt-2")
    entries = production.read_index(root, A).entries
    assert [e.index_seq for e in entries] == [0, 1] and entries[1].previous_entry_sha256 == entries[0].entry_sha256
    assert entries[1].entry_sha256 == second.entry_sha256 and entries[0].caller_context_sha256 == CALLER


def index_witness(m, tmp_path, defect):
    root = make_root(m, tmp_path)
    assert isinstance(reserve(m, root, "attempt-1"), m.Reservation)
    assert isinstance(reserve(m, root, "attempt-2"), m.Reservation)
    index = root.path / "assignments" / A / "index.jsonl"
    lines = index.read_bytes().splitlines()
    if defect == "chain":
        entry = json.loads(lines[1])
        entry["previous_entry_sha256"] = "0" * 64
        rewrite(index, lines[0] + b"\n" + rfc8785.dumps(entry) + b"\n")
    else:
        with open(index, "ab") as handle:
            handle.write(b'{"schema":')
    before = index.read_bytes()
    assert m.read_index(root, A).diagnostics == ("index_unverifiable",)
    assert reserve(m, root, "attempt-3") == m.JournalRefused("index_unverifiable")
    assert index.read_bytes() == before


@pytest.mark.parametrize("defect", ["chain", "torn"])
def test_reservation_refuses_broken_index(tmp_path, defect):
    index_witness(production, tmp_path, defect)


RACE = (
    "root = rs.open_journal_root(Path(sys.argv[2]), create=False); go = Path(sys.argv[3])\n"
    "print('ready', flush=True)\n"
    "while not go.exists(): time.sleep(0.001)\n"
    "identity = rs.AttemptIdentity(sys.argv[4], sys.argv[5], sys.argv[6], sys.argv[7])\n"
    "result = rs.reserve_attempt(root, identity, units=rs.Units(('unit:target',), (), sys.argv[8]),"
    " launch_digest=sys.argv[8], caller_context_sha256=sys.argv[8])\n"
    "print(json.dumps([getattr(result, 'code', None), getattr(result, 'index_seq', None)]), flush=True)\n")


def race(tmp_path, root, specs):
    go = tmp_path / "go"
    processes = [child(RACE, root.path, go, assignment, ENVELOPE, run, attempt, SNAPSHOT)
                 for assignment, run, attempt in specs]
    try:
        for process in processes:
            assert process.stdout.readline().strip() == "ready"
        go.write_text("go")
        results = []
        for process in processes:
            out, err = process.communicate(timeout=60)
            assert process.returncode == 0, err
            results.append(json.loads(out))
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait()
    return results


def test_reservation_race_same_attempt_has_one_winner(tmp_path):
    root = make_root(production, tmp_path)
    results = race(tmp_path, root, [(A, f"run-{n}", "attempt-1") for n in range(6)])
    assert Counter(code for code, _ in results) == {None: 1, "attempt_reserved": 5}
    assert len(production.read_index(root, A).entries) == 1


def test_reservation_race_across_assignments_has_one_winner(tmp_path):
    root = make_root(production, tmp_path)
    digests = [sha256(f"assignment-{n}".encode()).hexdigest() for n in range(6)]
    results = race(tmp_path, root, [(digest, f"run-{n}", "attempt-1") for n, digest in enumerate(digests)])
    assert Counter(code for code, _ in results) == {None: 1, "attempt_reserved": 5}
    assert sum(len(production.read_index(root, digest).entries) for digest in digests) == 1


def test_reservation_race_distinct_attempts_stay_gapless(tmp_path):
    root = make_root(production, tmp_path)
    results = race(tmp_path, root, [(A, "run-1", f"attempt-{n}") for n in range(6)])
    assert all(code is None for code, _ in results)
    assert sorted(seq for _, seq in results) == list(range(6))
    index = production.read_index(root, A)
    assert index.diagnostics == () and [e.index_seq for e in index.entries] == list(range(6))


CRASH = (
    "real = os.fsync\n"
    "def spy(fd):\n"
    "    real(fd)\n"
    "    if os.readlink(f'/proc/self/fd/{fd}').endswith('/attempts'):\n"
    "        print('claimed', flush=True); time.sleep(600)\n"
    "os.fsync = spy\n"
    "root = rs.open_journal_root(Path(sys.argv[2]), create=False)\n"
    "rs.reserve_attempt(root, rs.AttemptIdentity(sys.argv[3], sys.argv[4], 'run-1', 'attempt-1'),"
    " units=rs.Units(('unit:target',), (), sys.argv[4]), launch_digest=sys.argv[4], caller_context_sha256=sys.argv[4])\n"
    "print('returned', flush=True)\n")


def test_crash_after_directory_claim_never_reuses_the_id(tmp_path):
    root = make_root(production, tmp_path)
    process = child(CRASH, root.path, A, ENVELOPE)
    try:
        assert process.stdout.readline().strip() == "claimed"
        os.kill(process.pid, signal.SIGKILL)
    finally:
        process.wait(timeout=60)
        process.stdout.close()
        process.stderr.close()
    assert process.returncode == -signal.SIGKILL
    assert (root.path / "attempts/attempt-1").is_dir()
    assert production.read_index(root, A).entries == ()
    assert set(production.read_attempt(root, "attempt-1").diagnostics) == {"journal_missing", "attempt_unindexed"}
    assert production.read_attempt(root, "attempt-1").display == "unknown"
    assert production.resolve_run(root, "run-1") == ()
    assert reserve(production, root) == refused(production, "attempt_reserved")
    assert reserve(production, root, run="run-2") == refused(production, "attempt_reserved")


def fsync_calls(monkeypatch, call):
    calls, real = [], os.fsync

    def spy(fd):
        calls.append(os.readlink(f"/proc/self/fd/{fd}"))
        return real(fd)

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", spy)
        result = call()
    return result, calls


def fsync_witness(m, tmp_path, monkeypatch):
    root = make_root(m, tmp_path)
    base = os.path.realpath(root.path)
    result, calls = fsync_calls(monkeypatch, lambda: reserve(m, root))
    assert isinstance(result, m.Reservation)
    assert calls == [f"{base}/assignments", f"{base}/assignments/{A}", f"{base}/runs/run-1", f"{base}/runs",
                     f"{base}/attempts", f"{base}/assignments/{A}/index.jsonl", f"{base}/assignments/{A}"]
    result, calls = fsync_calls(monkeypatch, lambda: reserve(m, root, "attempt-2"))
    assert isinstance(result, m.Reservation)
    assert calls == [f"{base}/attempts", f"{base}/assignments/{A}/index.jsonl"]


def test_reservation_fsync_order(tmp_path, monkeypatch):
    fsync_witness(production, tmp_path, monkeypatch)


def test_writer_fsync_order(tmp_path, monkeypatch):
    root = make_root(production, tmp_path)
    reservation = reserve(production, root)
    base = os.path.realpath(root.path) + "/attempts/attempt-1"
    opened, calls = fsync_calls(monkeypatch, lambda: production.open_writer(
        root, reservation, limits=production.JournalLimits(segment_max_lines=2)))
    assert calls == [base, f"{base}/0000.jsonl", base]
    head, calls = fsync_calls(monkeypatch, lambda: opened.state("queued", worker_invocations=0))
    assert calls == [f"{base}/0000.jsonl"] and head.segment_index == 0
    head, calls = fsync_calls(monkeypatch, lambda: opened.state("running", worker_invocations=1))
    assert calls == [f"{base}/0001.jsonl", base, f"{base}/0001.jsonl"] and head.segment_index == 1
    opened.close()


# --------------------------------------------------------------------------
# Secrecy
# --------------------------------------------------------------------------

SENTINELS = {"prompt": b"PROMPT-SENTINEL-7f3a", "source": b"SOURCE-SENTINEL-91bc", "secret": b"SECRET-SENTINEL-c0de",
             "argv": b"ARGV-SENTINEL-5e11"}


def secrecy_witness(m, tmp_path):
    root = make_root(m, tmp_path)
    reservation, attempt_writer = writer(m, root)
    attempt_writer.state("queued", worker_invocations=0)
    attempt_writer.state("running", worker_invocations=1)
    payloads = {"stdout": SENTINELS["prompt"] + b" " + SENTINELS["argv"], "stderr": SENTINELS["secret"],
                "proposal_bytes": SENTINELS["source"], "evidence_envelope": b'{"evidence":"' + SENTINELS["secret"] + b'"}'}
    for kind, data in payloads.items():
        ref = m.make_ref(kind, data, None)
        assert ref.sha256 == sha256(data).hexdigest() and ref.locator is None
        assert isinstance(attempt_writer.event("output streams digested", refs=(ref,)), m.ChainHead)
    finish_head = attempt_writer.terminal("finished", worker_invocations=1,
                                          termination=m.Termination("completed", None, "worker"), refusal=None,
                                          result_binding=binding(m, reservation))
    assert isinstance(finish_head, m.ChainHead)
    attempt_writer.close()
    blob = b""
    for directory, names, files in os.walk(root.path):
        blob += "\0".join(names + files).encode()
        for name in files:
            blob += (Path(directory) / name).read_bytes()
    for sentinel in SENTINELS.values():
        assert sentinel not in blob
    for data in payloads.values():
        assert sha256(data).hexdigest().encode() in blob
    assert CALLER.encode() in blob
    read = production.read_attempt(production.open_journal_root(root.path, create=False), "attempt-1")
    assert read.diagnostics == () and not any(s in line for s in SENTINELS.values() for line in read.lines)


def test_sentinels_never_reach_journal_bytes(tmp_path):
    secrecy_witness(production, tmp_path)


def test_identity_and_records_are_immutable(tmp_path):
    root, reservation, head = finished_attempt(tmp_path)
    read = production.read_attempt(root, "attempt-1")
    for record in (reservation, reservation.writer, head, read, read.terminal, root):
        with pytest.raises((AttributeError, TypeError)):
            record.__setattr__("x", 1)
    assert isinstance(read.lines, tuple) and all(type(line) is bytes for line in read.lines)


# --------------------------------------------------------------------------
# Named mutation controls (artifact section 13, SL-0)
# --------------------------------------------------------------------------

CONTROLS = {
    "index_lock": ("fcntl.flock(lock_fd, fcntl.LOCK_EX)\n", "None\n"),
    "index_fsync": ("os.fsync(index_fd)", "None"),
    "assignment_dir_fsync": ("os.fsync(assignments_fd)", "None"),
    "run_claim_fsync": ("os.fsync(runs_fd)", "None"),
    "attempt_excl": ('raise _Fail("attempt_reserved") from None', "pass"),
    "run_claim": ('raise _Fail("run_assignment_mismatch")', "return"),
    "index_chain": ('if obj["previous_entry_sha256"] != previous:', "if False:"),
    "index_torn_refusal": ('if data and not data.endswith(b"\\n"):', "if False:"),
    "component_nofollow": ("_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC",
                           "_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC"),
    "owner_check": ("if st.st_uid != os.geteuid():", "if False:"),
    "mode_check": ("if stat.S_IMODE(st.st_mode) != (0o700 if directory else 0o600):", "if False:"),
    "nlink_check": (" and st.st_nlink == 1", ""),
    "torn_line": ('replay.diagnostics.add("journal_torn_line" if final else "journal_malformed_line")', "pass"),
    "unknown_version": ('if obj["schema"] != JOURNAL_FAMILY or obj["version"] != "1":', "if False:"),
    "foreign_writer": ('if obj["writer"] != self.reference["writer"]:', "if False:"),
    "writer_instance_reuse": ("    writer = reservation.writer\n", "    writer = _mint_writer()\n"),
    "seq_gap": ("if seq != self.expected_seq and not self.broken:", "if False:"),
    "segment_chain": ("previous = self._hash.hexdigest()", 'previous = "0" * 64'),
    "missing_segment": ("if 0 not in segments:", "if False:"),
    "identity_key": ('if obj["attempt"]["attempt_id"] != self.attempt_id:', "if False:"),
    "lifecycle_order": ("return not self._terminal and new in _NEXT[self._state]", "return not self._terminal"),
    "refused_after_launch": ('if kind == "terminal" and new == "refused" and (self.ran or body["worker_invocations"] > 0):',
                             "if False:"),
    "phrase_set": ("if not isinstance(phrase, str) or phrase not in EVENT_PHRASES:", "if not isinstance(phrase, str):"),
    "writer_poison": ("self._poisoned = True", "pass"),
    "ref_digest_only": ("return Ref(kind, hashlib.sha256(data).hexdigest(), locator)",
                        'return Ref(kind, bytes(data).decode("latin-1"), locator)'),
    "locator_rule": (' and ".." not in locator.split("/"))', ")"),
    "line_cap": ("if self._total_lines + needed > cap:", "if False:"),
    "terminal_headroom": ("cap = limits.per_attempt_line_cap if terminal else limits.per_attempt_line_cap - 2",
                          "cap = limits.per_attempt_line_cap"),
    "reader_readonly": ("_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW",
                        "_READ_FLAGS = os.O_RDWR | os.O_TRUNC | os.O_NOFOLLOW"),
    "structural_check": ('if schema.get("additionalProperties") is False and not set(value) <= set(properties):',
                         "if False:"),
}


def mutant(monkeypatch, control):
    source = Path(production.__file__).read_text()
    fragment, replacement = CONTROLS[control]
    assert source.count(fragment) == 1, control
    name = "phase_loop_runtime._mutation_run_status_" + control
    module = ModuleType(name)
    module.__file__ = production.__file__
    module.__package__ = "phase_loop_runtime"
    monkeypatch.setitem(sys.modules, name, module)
    exec(compile(source.replace(fragment, replacement), production.__file__, "exec"), module.__dict__)
    return module


def lock_witness(m, tmp_path):
    root = make_root(m, tmp_path)
    assert isinstance(reserve(m, root, "attempt-1"), m.Reservation)
    fd = os.open(root.path / "assignments" / A / "lock", os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)
    result = {}
    thread = threading.Thread(target=lambda: result.setdefault("value", reserve(m, root, "attempt-2")))
    thread.start()
    try:
        thread.join(0.5)
        blocked = thread.is_alive()
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
        thread.join(30)
    assert blocked
    assert isinstance(result["value"], m.Reservation) and result["value"].index_seq == 1


def excl_witness(m, tmp_path):
    root = make_root(m, tmp_path)
    os.mkdir(root.path / "attempts/attempt-1", 0o700)
    assert reserve(m, root) == m.JournalRefused("attempt_reserved")
    assert not (root.path / "assignments" / A / "index.jsonl").exists()


def run_claim_witness(m, tmp_path):
    root = make_root(m, tmp_path)
    fd = os.open(root.path / "runs/run-1", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.write(fd, (B + "\n").encode())
    os.close(fd)
    assert reserve(m, root) == m.JournalRefused("run_assignment_mismatch")
    assert not (root.path / "attempts/attempt-1").exists()


def nofollow_witness(m, tmp_path):
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    (tmp_path / "link").symlink_to(real)
    assert isinstance(m.open_journal_root(real / "journal", create=True), m.JournalRoot)
    assert m.open_journal_root(tmp_path / "link" / "journal", create=False) == m.JournalRefused("journal_root_unsafe")


def owner_witness(m, tmp_path, monkeypatch):
    root = make_root(m, tmp_path)
    real = os.geteuid()
    with monkeypatch.context() as patch:
        patch.setattr(os, "geteuid", lambda: real + 1)
        assert m.open_journal_root(root.path, create=False) == m.JournalRefused("journal_root_unsafe")
        assert reserve(m, root) == m.JournalRefused("journal_path_unsafe")


def mode_witness(m, tmp_path):
    root = make_root(m, tmp_path)
    os.chmod(root.path, 0o750)
    assert m.open_journal_root(root.path, create=False) == m.JournalRefused("journal_root_unsafe")
    assert reserve(m, root) == m.JournalRefused("journal_path_unsafe")


def reader_setup(tmp_path, events=1, limits=None):
    root, _, _ = finished_attempt(tmp_path, events=events, limits=limits)
    return root


def nlink_witness(m, tmp_path):
    root = reader_setup(tmp_path)
    os.link(segment_files(root)[0], tmp_path / "copy")
    assert m.read_attempt(reopen(m, root), "attempt-1").diagnostics == ("journal_path_unsafe",)


def missing_segment_witness(m, tmp_path):
    root = reader_setup(tmp_path, events=2, limits=production.JournalLimits(segment_max_lines=3))
    os.unlink(segment_files(root)[0])
    read = m.read_attempt(reopen(m, root), "attempt-1")
    assert read.diagnostics == ("journal_missing",) and read.display == "unknown"


def identity_key_witness(m, tmp_path):
    root = reader_setup(tmp_path)
    os.rename(root.path / "attempts/attempt-1", root.path / "attempts/attempt-x")
    assert set(m.read_attempt(reopen(m, root), "attempt-x").diagnostics) == {
        "attempt_provenance_mismatch", "attempt_unindexed"}


def readonly_witness(m, tmp_path):
    root = reader_setup(tmp_path)
    reserve(production, root, "attempt-2")
    before = snapshot(root.path)
    mroot = reopen(m, root)
    for attempt in ("attempt-1", "attempt-2", "absent-1"):
        m.read_attempt(mroot, attempt)
    m.read_index(mroot, A)
    m.resolve_run(mroot, "run-1")
    assert snapshot(root.path) == before
    assert m.read_attempt(mroot, "attempt-1").diagnostics == ()


def lifecycle_witness(m, tmp_path):
    root = make_root(m, tmp_path)
    reservation, attempt_writer = writer(m, root)
    before = segment_files(root)[0].read_bytes()
    assert attempt_writer.state("running", worker_invocations=1) == m.JournalRefused("lifecycle_invalid")
    assert isinstance(attempt_writer.state("queued", worker_invocations=0), m.ChainHead)
    assert attempt_writer.terminal("finished", worker_invocations=0, termination=m.Termination("completed", None, "worker"),
                                   refusal=None, result_binding=binding(m, reservation)) == m.JournalRefused(
        "lifecycle_invalid")
    attempt_writer.close()
    assert segment_files(root)[0].read_bytes().startswith(before)


def phrase_witness(m, tmp_path):
    root = make_root(m, tmp_path)
    _, attempt_writer = writer(m, root)
    before = segment_files(root)[0].read_bytes()
    assert attempt_writer.event("worker returned a proposal") == m.JournalRefused("phrase_invalid")
    attempt_writer.close()
    assert segment_files(root)[0].read_bytes() == before


def locator_witness(m, tmp_path):
    try:
        m.make_ref("stdout", b"x", "../x")
        raised = False
    except ValueError:
        raised = True
    assert raised
    vector_witness(m, tmp_path, "N20-parent-locator")


def structural_witness(m, tmp_path):
    journal = vectors.expand("V-running")["journal"]
    journal["attempts"][0]["segments"][0]["lines"][1]["extra"] = 1
    diagnostics, displays = read_vector(m, tmp_path, journal)
    assert diagnostics == {"journal_malformed_line"} and displays == ["unknown"]
    assert m.check_structure("journal_line", journal["attempts"][0]["segments"][0]["lines"][1]) is False


def witness(m, control, tmp_path, monkeypatch):
    if control == "index_lock":
        lock_witness(m, tmp_path)
    elif control in ("index_fsync", "assignment_dir_fsync", "run_claim_fsync"):
        fsync_witness(m, tmp_path, monkeypatch)
    elif control == "attempt_excl":
        excl_witness(m, tmp_path)
    elif control == "run_claim":
        run_claim_witness(m, tmp_path)
    elif control in ("index_chain", "index_torn_refusal"):
        index_witness(m, tmp_path, "chain" if control == "index_chain" else "torn")
    elif control == "component_nofollow":
        nofollow_witness(m, tmp_path)
    elif control == "owner_check":
        owner_witness(m, tmp_path, monkeypatch)
    elif control == "mode_check":
        mode_witness(m, tmp_path)
    elif control == "nlink_check":
        nlink_witness(m, tmp_path)
    elif control in ("torn_line", "unknown_version", "foreign_writer", "seq_gap", "refused_after_launch"):
        vector_witness(m, tmp_path, {"torn_line": "N15-no-final-newline", "unknown_version": "N15-unknown-version",
                                     "foreign_writer": "N15-foreign-writer", "seq_gap": "N04a-seq-skip",
                                     "refused_after_launch": "N19-refused-after-start"}[control])
    elif control == "writer_instance_reuse":
        writer_identity_witness(m, tmp_path)
    elif control == "segment_chain":
        segment_chain_witness(m, tmp_path)
    elif control == "missing_segment":
        missing_segment_witness(m, tmp_path)
    elif control == "identity_key":
        identity_key_witness(m, tmp_path)
    elif control == "lifecycle_order":
        lifecycle_witness(m, tmp_path)
    elif control == "phrase_set":
        phrase_witness(m, tmp_path)
    elif control == "writer_poison":
        poison_witness(m, tmp_path, monkeypatch)
    elif control == "ref_digest_only":
        secrecy_witness(m, tmp_path)
    elif control == "locator_rule":
        locator_witness(m, tmp_path)
    elif control in ("line_cap", "terminal_headroom"):
        line_cap_witness(m, tmp_path)
    elif control == "reader_readonly":
        readonly_witness(m, tmp_path)
    elif control == "structural_check":
        structural_witness(m, tmp_path)
    else:  # pragma: no cover - every named control has a witness
        raise AssertionError(control)


def test_control_inventory_matches_artifact():
    assert list(CONTROLS) == [
        "index_lock", "index_fsync", "assignment_dir_fsync", "run_claim_fsync", "attempt_excl", "run_claim",
        "index_chain", "index_torn_refusal", "component_nofollow", "owner_check", "mode_check", "nlink_check",
        "torn_line", "unknown_version", "foreign_writer", "writer_instance_reuse", "seq_gap", "segment_chain",
        "missing_segment", "identity_key", "lifecycle_order", "refused_after_launch", "phrase_set", "writer_poison",
        "ref_digest_only", "locator_rule", "line_cap", "terminal_headroom", "reader_readonly", "structural_check"]


@pytest.mark.parametrize("control", list(CONTROLS))
def test_production_control_witness(tmp_path, monkeypatch, control):
    witness(production, control, tmp_path, monkeypatch)


@pytest.mark.parametrize("control", list(CONTROLS))
def test_run_status_mutation_killed(tmp_path, monkeypatch, control):
    module = mutant(monkeypatch, control)
    with pytest.raises(AssertionError):
        witness(module, control, tmp_path, monkeypatch)
