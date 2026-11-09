"""Test-only run-status vector harness (JOURNAL artifact section 12).

It loads the pinned corpus through the contract-intake bundle, applies the RFC
6902 patches with RFC 6901 pointers, materializes ``journal`` inputs to disk and
exposes the pinned validator for the differential cross-check. It carries no
semantic logic: its output only enters production readers and checkers.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from hashlib import sha256
import json
import os
from pathlib import Path

import rfc8785

from phase_loop_runtime.supervised_contracts import ContractError, load_contract_bundle, validate_record as _validate

FAMILY = "supervised_run_status.v1"
VECTORS = "conformance/run-status.vectors.json"
SCHEMA = "run-status.schema.json"
INDEX_SCHEMA = "phase_loop.supervised_admission_index.v1"
#: Fixed admission digests for materialized index entries; vectors carry none.
LAUNCH_DIGEST = sha256(b"run-status vector launch").hexdigest()
CALLER_CONTEXT_SHA256 = sha256(b"run-status vector caller context").hexdigest()
DEFINITIONS = ("journal_line", "projection", "page_request", "page", "reader_view")


@lru_cache(maxsize=1)
def bundle():
    return load_contract_bundle()


@lru_cache(maxsize=1)
def _corpus():
    return json.loads(bundle().resource_bytes(VECTORS))["cases"]


def schema():
    return json.loads(bundle().resource_bytes(SCHEMA))


def cases(kind=None):
    return [deepcopy(c) for c in _corpus() if kind is None or c["kind"] == kind]


def case(case_id):
    matches = [c for c in _corpus() if c["id"] == case_id]
    assert len(matches) == 1, case_id
    return deepcopy(matches[0])


def ids(kind):
    return [c["id"] for c in _corpus() if c["kind"] == kind]


def _token(text):
    return text.replace("~1", "/").replace("~0", "~")


def pointer(value, path):
    for token in path.removeprefix("/").split("/") if path else []:
        value = value[int(token)] if isinstance(value, list) else value[_token(token)]
    return value


def expand(case_id):
    """The patched input of ``case_id``; every edit is asserted to take effect."""
    item = case(case_id)
    if item["role"] == "control":
        return item["input"]
    value = case(item["control"])["input"]
    assert item.get("rehash") in (None, False), case_id
    for operation in item["patch"]:
        parent_path, _, leaf = operation["path"].rpartition("/")
        parent = pointer(value, parent_path)
        key = _token(leaf)
        if isinstance(parent, list):
            key = len(parent) if key == "-" else int(key)
        before = deepcopy(parent)
        if operation["op"] == "remove":
            del parent[key]
            assert len(parent) == len(before) - 1
        elif operation["op"] == "add" and isinstance(parent, list):
            parent.insert(key, deepcopy(operation["value"]))
            assert parent[:key] + parent[key + 1:] == before
        else:
            assert operation["op"] in ("add", "replace"), operation["op"]
            if operation["op"] == "replace":
                assert key in parent if isinstance(parent, dict) else 0 <= key < len(parent)
            parent[key] = deepcopy(operation["value"])
        assert parent != before, (case_id, operation["path"])
    return value


def line_bytes(line):
    return line.encode("utf-8") if isinstance(line, str) else rfc8785.dumps(line)


def segment_bytes(segment):
    data = b"\n".join(line_bytes(line) for line in segment["lines"])
    return data + b"\n" if segment.get("final_newline", True) else data


def validate_record(definition, value):
    """The pinned validator's verdict for one record (object or exact bytes)."""
    data = value if isinstance(value, bytes) else rfc8785.dumps(value)
    try:
        _validate(bundle(), FAMILY, data, definition=definition)
    except ContractError:
        return False
    return True


def _directory(path):
    path.mkdir(mode=0o700)
    os.chmod(path, 0o700)


def _file(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, data)
    finally:
        os.close(fd)


def index_entry(line, index_seq, previous):
    """An admission-index entry for an attempt whose first line is ``line``."""
    identity = line["attempt"]
    return {"schema": INDEX_SCHEMA, "version": "1", "index_seq": index_seq,
            "previous_entry_sha256": previous, "assignment_digest": identity["assignment_digest"],
            "envelope_digest": identity["envelope_digest"], "run_id": identity["run_id"],
            "attempt_id": identity["attempt_id"], "launch_digest": LAUNCH_DIGEST,
            "caller_context_sha256": CALLER_CONTEXT_SHA256, "units": line["units"], "writer": line["writer"]}


def index_bytes(entries):
    """JCS index bytes chaining ``entries`` (dicts without chain fields set)."""
    out, previous = [], None
    for position, entry in enumerate(entries):
        entry = dict(entry, index_seq=position, previous_entry_sha256=previous)
        raw = rfc8785.dumps(entry)
        previous = sha256(raw).hexdigest()
        out.append(raw + b"\n")
    return b"".join(out)


def materialize(journal, root):
    """Write ``journal`` under ``root``: index entries in listed order, then segments.

    Directories are 0700 and files 0600 under umask 077. Each attempt's index
    entry is taken from its first listed line; run records name its assignment.
    """
    previous_umask = os.umask(0o077)
    try:
        root = Path(root)
        _directory(root)
        for name in ("attempts", "assignments", "runs"):
            _directory(root / name)
        indexes = {}
        for attempt in journal["attempts"]:
            first = attempt["segments"][0]["lines"][0]
            assert isinstance(first, dict)
            identity = first["attempt"]
            digest = identity["assignment_digest"]
            indexes.setdefault(digest, []).append(index_entry(first, 0, None))
            run = root / "runs" / identity["run_id"]
            if not run.exists():
                _file(run, (digest + "\n").encode())
            directory = root / "attempts" / identity["attempt_id"]
            _directory(directory)
            for position, segment in enumerate(attempt["segments"]):
                _file(directory / f"{position:04d}.jsonl", segment_bytes(segment))
        for digest, entries in indexes.items():
            _directory(root / "assignments" / digest)
            _file(root / "assignments" / digest / "index.jsonl", index_bytes(entries))
    finally:
        os.umask(previous_umask)
    return root


def attempt_ids(journal):
    return [a["segments"][0]["lines"][0]["attempt"]["attempt_id"] for a in journal["attempts"]]
