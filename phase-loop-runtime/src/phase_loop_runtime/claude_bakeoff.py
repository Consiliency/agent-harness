"""The W0 bake-off record, its validator and the W0 kit (SEATS CLAUDE, IF-0-CLAUDE-2,
EC-CLAUDE-5).

One canonical JSON record per run, ``claude-bakeoff-record.v1``, at
``plans/evidence/seat-qualification/claude-w0/<run_id>.json``. The schema is closed: every
field below is required, no other field is allowed, and every string is a vocabulary value or
matches a strict pattern, so no diagnostic passes through. The records are public: meter
readings and raw captures live only in per-operator private storage (mode 0600), and a record
carries a salted digest of its block's readings and a digest of its block's templated request
set. :func:`evidence_digest` is what an OD-3b section cites.

``python -m phase_loop_runtime.claude_bakeoff``:

* ``validate DIR`` -- V7, the shape check of every record in ``DIR`` and across them;
* ``digest DIR`` -- the order-independent evidence digest;
* ``run --plan PLAN --session 1|2`` -- the W0 kit (an owner action, LA-3), one of the two
  sessions OQ-4 fixes: session 1 is blocks 1-2 (print, control), session 2 blocks 3-6 and only
  once ``sdk`` is admitted and session 1's records are present. It refuses a run plan that
  differs from the phase plan's Execution Notes, a board whose president or a co-seat would use
  the W0 Claude account, and a bundle head that is not on ``main``. Each session opens with a
  meter reading and each block closes with one; it runs the block's arm, and once per native
  block the capture twin. A security-class outcome stops the arm, in that session and the
  next, and its records carry only ``withheld_private``;
* ``control-brief`` -- print the T3 Code SDK-route control block's brief.
  Its response is parsed through the Python ``ingest_control`` API; there is
  no ``ingest-control`` CLI subcommand.

Importing this module runs no provider. The owner-run kit invokes the board
and transport helpers for its measurement blocks.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import ipaddress
import json
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Iterable, Iterator, Mapping, Sequence

from . import claude_seat_transport as _transport
from . import seat_uid as _seat_uid

EVIDENCE_DIR = "plans/evidence/seat-qualification/claude-w0"
RECORD_FORMAT = "claude-bakeoff-record.v1"

ARMS = ("print", "sdk", "t3-sdk-control")
NATIVE_ARMS = ("print", "sdk")
CONTROL = "t3-sdk-control"
CANONICAL_OUTPUTS = ("admitted", "absent", "refused", "timed_out")
PREDICATE_VALUES = ("pass", "fail", "not_applicable", "self_reported")
BILLING = ("subscription", "extra_usage", "api", "unknown")
SECURITY_OUTCOMES = ("none", "withheld_private")
KEY_SOURCES = ("none", "present", "unknown")
COMPLETENESS = ("complete", "partial")
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")
CO_SEAT_VENDORS = ("codex", "cursor", "gemini", "grok", "opencode", "pi")

#: The admission predicates (§4a item 5) and the item 7 qualification checks.
ADMISSION_PREDICATES = (
    "jail", "staged_clone", "token_pipe", "login_proof", "init_api_key_source_none",
    "session_matches", "single_result", "result_success", "exit_zero", "verdict_conforming",
)
ITEM7_PREDICATES = (
    "seat_diagnostics", "exact_model_match", "staged_path_digest", "read_completed",
    "session", "subscription", "result", "exit", "verdict",
)
#: The only predicates the control arm may mark ``not_applicable``.
CONTROL_NOT_APPLICABLE = frozenset({"jail", "staged_clone", "token_pipe", "seat_diagnostics"})

FIELDS = (
    "run_id", "arm", "block", "w0_head", "cli_version", "canonical_output", "code",
    "admission", "item7", "billing", "meter_ref", "meter_digest", "claude_code_entrypoint",
    "claude_api_key_source", "request_set", "jail_profile_digest",
    "dependency_projection_digest", "activation_section_sha256", "co_seats_unconfined",
    "security_outcome",
)

_HEX40 = re.compile(r"[0-9a-f]{40}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_RUN_ID = re.compile(r"w0-b(?P<block>[1-9][0-9]?)-r(?P<n>[1-9][0-9]?)")
_METER_REF = re.compile(r"w0-block-(?P<block>[1-9][0-9]?)")
_CLI_VERSION = re.compile(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,4}|unknown")
_SLUG = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_PATH_LITERAL = re.compile(r"[a-z][a-z0-9._-]{0,63}|v[0-9]{1,3}")
_PRIVATE_SUFFIXES = (".local", ".internal", ".lan", ".ts.net", ".localhost", ".home.arpa")

#: Shapes no public record may carry anywhere (defence in depth over the patterns above).
_REFUSED_SHAPES: Mapping[str, re.Pattern[str]] = {
    # A key prefix, a JWT, a bearer header, or a long mixed-case-and-digit run (a token
    # shape; the snake_case codes and the lowercase hex digests are not one).
    "credential": re.compile(
        r"sk-ant-|\bsk-[A-Za-z0-9_-]{16,}|\bey[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{8,}|"
        r"(?i:bearer)\s|(?=[A-Za-z0-9+/_-]*[A-Z])(?=[A-Za-z0-9+/_-]*[a-z])"
        r"(?=[A-Za-z0-9+/_-]*[0-9])\b[A-Za-z0-9+/_-]{32,}"),
    "uuid": re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"),
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "home_path": re.compile(r"/home/|/Users/|/root/|~/|\\\\Users\\\\"),
    "ipv4": re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b"),
}
#: A path segment that carries an identifier and must be ``{id}``: an id-like run, or any
#: dotted segment (a name, an address or a file name).
_IDENTIFIER_SEGMENT = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}|[0-9]{4,}|[0-9a-f]{12,}|[A-Za-z0-9_-]{24,}"
    r"|.*[0-9].*[0-9].*[0-9].*|.*\..*")
#: Collections whose next segment names one member: it is always ``{id}``, however word-like.
ID_PARENTS = frozenset({"organizations", "orgs", "users", "accounts", "projects", "workspaces",
                        "members", "sessions", "conversations", "teams", "customers", "keys",
                        "api_keys", "files", "threads"})


# --------------------------------------------------------------------------------------
# The record.
# --------------------------------------------------------------------------------------

def canonical_bytes(record: Mapping[str, object]) -> bytes:
    return (json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            + "\n").encode("ascii")


def host_problem(host: object) -> str | None:
    if not isinstance(host, str) or not host or len(host) > 253 or host != host.lower():
        return "host"
    try:
        ipaddress.ip_address(host.strip("[]"))
        return "IP literal"
    except ValueError:
        pass
    labels = host.split(".")
    if len(labels) < 2:
        return "single-label host"
    if any(not _HOST_LABEL.fullmatch(label) for label in labels):
        return "host"
    if not re.fullmatch(r"[a-z][a-z0-9-]*", labels[-1]) or any(
            re.fullmatch(r"0x[0-9a-f]+", label) for label in labels):
        return "IP literal"  # a numeric or hex last label is an address spelling (127.1)
    if any(("." + host).endswith(suffix) for suffix in _PRIVATE_SUFFIXES):
        return "private-namespace host"
    return None


def path_problem(path: object) -> str | None:
    if not isinstance(path, str) or not path.startswith("/") or len(path) > 512:
        return "path"
    if any(c in path for c in "?#%@:;= \\"):
        return "path"
    previous = ""
    for segment in path.split("/")[1:]:
        if previous in ID_PARENTS and segment not in ("", "{id}"):
            return "untemplated identifier in a path"
        previous = segment
        if segment in ("", "{id}"):
            continue
        if _IDENTIFIER_SEGMENT.fullmatch(segment):
            return "untemplated identifier in a path"
        if not _PATH_LITERAL.fullmatch(segment):
            return "path"
    return None


def _strings(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _predicates(name: str, value: object, names: Sequence[str], arm: object) -> list[str]:
    if not isinstance(value, dict) or set(value) != set(names):
        return [f"{name}: must map exactly {', '.join(names)}"]
    problems = []
    for predicate, outcome in value.items():
        if outcome not in PREDICATE_VALUES:
            problems.append(f"{name}.{predicate}: not a predicate value")
        elif arm != CONTROL and outcome in ("not_applicable", "self_reported"):
            problems.append(f"{name}.{predicate}: a native record observes every predicate")
        elif (arm == CONTROL and outcome == "not_applicable"
              and predicate not in CONTROL_NOT_APPLICABLE):
            problems.append(f"{name}.{predicate}: the control may not mark this not_applicable")
    return problems


def _code_problem(code: object) -> str | None:
    from . import seat_jail

    if code == "none":
        return None
    known = (set(_transport.CODES) | set(_transport.REFUSAL_CODES)
             | set(seat_jail.NOTICE_CODES) | {"claude_print_auth_drift"})
    if not isinstance(code, str) or code not in known:
        return "code: not a typed code"
    if _transport.od10_class(code) == _transport.SECURITY:
        return "code: a security-class code is withheld, never published"
    return None


def validate_record(obj: object) -> list[str]:
    """Every problem with one record (empty when it is valid). Diagnostics name fields and
    rules, never the offending value."""
    if not isinstance(obj, dict):
        return ["record: not an object"]
    problems: list[str] = []
    missing, unknown = set(FIELDS) - set(obj), set(obj) - set(FIELDS)
    if missing:
        problems.append("missing: " + ", ".join(sorted(missing)))
    if unknown:
        problems.append("unknown field(s)")
    if problems:
        return problems
    arm = obj["arm"]
    if arm not in ARMS:
        problems.append("arm: not an arm")
    block = obj["block"]
    if type(block) is not int or not 1 <= block <= len(EXECUTION_NOTES.blocks):
        problems.append("block: not a block number")
    match = _RUN_ID.fullmatch(obj["run_id"]) if isinstance(obj["run_id"], str) else None
    if (match is None or int(match["block"]) != block
            or int(match["n"]) > EXECUTION_NOTES.runs_per_block):
        problems.append("run_id: not the generated w0-b<block>-r<n>")
    if not (isinstance(obj["w0_head"], str) and _HEX40.fullmatch(obj["w0_head"])):
        problems.append("w0_head: not a 40-hex commit")
    if not (isinstance(obj["cli_version"], str) and _CLI_VERSION.fullmatch(obj["cli_version"])):
        problems.append("cli_version: not a version")
    if obj["canonical_output"] not in CANONICAL_OUTPUTS:
        problems.append("canonical_output: not a value")
    code_problem = _code_problem(obj["code"])
    if code_problem:
        problems.append(code_problem)
    problems += _predicates("admission", obj["admission"], ADMISSION_PREDICATES, arm)
    problems += _predicates("item7", obj["item7"], ITEM7_PREDICATES, arm)
    if obj["billing"] not in BILLING:
        problems.append("billing: not a value")
    meter = _METER_REF.fullmatch(obj["meter_ref"]) if isinstance(obj["meter_ref"], str) else None
    if meter is None or int(meter["block"]) != block:
        problems.append("meter_ref: not this block's w0-block-<n>")
    for name in ("meter_digest",):
        if not (isinstance(obj[name], str) and _HEX64.fullmatch(obj[name])):
            problems.append(f"{name}: not a sha256")
    if not (isinstance(obj["claude_code_entrypoint"], str)
            and _SLUG.fullmatch(obj["claude_code_entrypoint"])):
        problems.append("claude_code_entrypoint: not a short slug")
    if obj["claude_api_key_source"] not in KEY_SOURCES:
        problems.append("claude_api_key_source: not a value")
    problems += _request_set_problems(obj["request_set"])
    for name, applicable in (("jail_profile_digest", arm in NATIVE_ARMS),
                             ("dependency_projection_digest", arm == "sdk"),
                             ("activation_section_sha256", arm in NATIVE_ARMS)):
        value = obj[name]
        if applicable:
            if not (isinstance(value, str) and _HEX64.fullmatch(value)):
                problems.append(f"{name}: not a sha256")
        elif value != "not_applicable":
            problems.append(f"{name}: must be not_applicable on this arm")
    seats = obj["co_seats_unconfined"]
    if (not isinstance(seats, list) or any(s not in CO_SEAT_VENDORS for s in seats)
            or seats != sorted(set(seats))):
        problems.append("co_seats_unconfined: not a sorted list of vendor slugs")
    if obj["security_outcome"] not in SECURITY_OUTCOMES:
        problems.append("security_outcome: not a value")
    elif obj["security_outcome"] == "withheld_private" and (
            obj["code"] != "none" or obj["canonical_output"] != "refused"
            or obj["claude_api_key_source"] != "unknown"
            or obj["claude_code_entrypoint"] != "unset"
            or any(value != "fail" for value in (*_values(obj["admission"]),
                                                 *_values(obj["item7"])))):
        problems.append("security_outcome: a withheld outcome publishes no code, output or "
                        "diagnostic")
    for text in _strings(obj):
        if _HEX64.fullmatch(text) or _HEX40.fullmatch(text):
            continue
        for shape, pattern in _REFUSED_SHAPES.items():
            if pattern.search(text):
                problems.append(f"a string carries a refused shape ({shape})")
    return list(dict.fromkeys(problems))


def _values(value: object) -> list[object]:
    return list(value.values()) if isinstance(value, dict) else [None]


def _request_set_problems(value: object) -> list[str]:
    if not isinstance(value, dict) or set(value) != {"completeness", "capture_digest", "entries"}:
        return ["request_set: must hold exactly completeness, capture_digest, entries"]
    problems = []
    if value["completeness"] not in COMPLETENESS:
        problems.append("request_set.completeness: not a value")
    if not (isinstance(value["capture_digest"], str) and _HEX64.fullmatch(value["capture_digest"])):
        problems.append("request_set.capture_digest: not a sha256")
    entries = value["entries"]
    if not isinstance(entries, list) or len(entries) > 512:
        return problems + ["request_set.entries: not a bounded list"]
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"method", "host", "path_template"}:
            problems.append("request_set.entries: an entry is not {method, host, path_template}")
            continue
        if entry["method"] not in METHODS:
            problems.append("request_set.entries: not a method")
        host = host_problem(entry["host"])
        if host:
            problems.append(f"request_set.entries: {host}")
        path = path_problem(entry["path_template"])
        if path:
            problems.append(f"request_set.entries: {path}")
    return problems


def evidence_digest(directory: Path | str, *, sessions: Sequence[int] | None = None) -> str:
    """sha256 over the sorted bytes of every record in ``directory``: independent of file
    order and names. An OD-3b section cites this value over the sessions it names
    (``sessions``; default every file), so later sessions' records can land beside it."""
    paths = []
    for path in Path(directory).glob("*.json"):
        if sessions is not None:
            found = _RUN_ID.fullmatch(path.name[:-5])
            if found is None or _session_or_none(int(found["block"])) not in sessions:
                continue
        paths.append(path)
    blobs = sorted(path.read_bytes() for path in paths)
    digest = hashlib.sha256()
    for blob in blobs:
        digest.update(len(blob).to_bytes(8, "big"))
        digest.update(blob)
    return digest.hexdigest()


# --------------------------------------------------------------------------------------
# The directory (V7).
# --------------------------------------------------------------------------------------

def _git_show(repo: Path, rev: str, path: str) -> bytes | None:
    try:
        done = subprocess.run(["git", "-C", str(repo), "show", f"{rev}:{path}"],
                              capture_output=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


_OD3B_DIGEST = re.compile(r"\*\*W0 evidence digest:\*\* `(?P<digest>[0-9a-f]{64})`")
#: The sessions an OD-3b section's evidence holds (OQ-4): ``1`` or ``1 and 2``.
_OD3B_SESSIONS = re.compile(r"^\*\*W0 sessions:\*\* (?P<sessions>1|1 and 2)[ \t]*$", re.M)
_OD3B_HEADING = re.compile(r"## 4[c-z]\. .*\bOD-3b\b")


#: The architectures a W0 host may run; a W0 head's TUI digest is one per architecture.
ARCHES = ("x86_64", "aarch64")


#: The runtime sources the TUI jail profile digest is computed from (the package's
#: ``__init__`` is loaded too, but declares nothing the digest reads).
JAIL_PROFILE_SOURCES = (
    "seat_jail.py",
    "seat_profiles.py",
    "seat_resource_caps.py",
    "seat_route_contract.py",
    # seat_profiles registers Codex at import; pin its complete import closure too.
    "seat_profile_codex.py",
    "seat_codex_cli_shape.py",
    # ...and Grok (GROK SL-2), whose profile module imports nothing else at import time.
    "seat_profile_grok.py",
    "seat_admission.py",
    "seat_subject.py",
    "executable_dependency.py",
    "executable_dependency_startup.py",
)
_RUNTIME_DIR = "phase-loop-runtime/src/phase_loop_runtime"


def tui_digests_at(repo: Path, head: str) -> frozenset[str]:
    """The TUI jail profile digests of ``head`` (one per architecture), with no code of
    ``head`` executed: this runtime computes them with its own copy of
    :data:`JAIL_PROFILE_SOURCES`, and only when ``head``'s copy of each is byte-identical to
    this one's and has no other importable form. Empty when they cannot be derived that
    way; the operator then validates from a checkout at ``head`` or passes ``--tui-digest``."""
    own = Path(__file__).resolve().parent
    try:
        entries = _transport._tree_entries(repo, head, f"{_RUNTIME_DIR}/", recursive=False)
    except _transport.AuditError:
        return frozenset()
    for name in JAIL_PROFILE_SOURCES:
        stem = name[:-3]
        forms = [(mode, path.rsplit("/", 1)[-1]) for mode, _obj, path in entries
                 if path.rsplit("/", 1)[-1] == stem
                 or path.rsplit("/", 1)[-1].startswith(stem + ".")]
        if forms != [("100644", name)]:
            return frozenset()
        theirs = _git_show(repo, head, f"{_RUNTIME_DIR}/{name}")
        try:
            mine = (own / name).read_bytes()
        except OSError:
            return frozenset()
        if theirs is None or theirs != mine:
            return frozenset()
    from . import seat_jail

    try:
        digests = [seat_jail.jail_profile_digest("claude", arch) for arch in ARCHES]
    except Exception:  # an underivable digest fails V7, never passes it
        return frozenset()
    if not all(isinstance(d, str) and _HEX64.fullmatch(d) for d in digests):
        return frozenset()
    return frozenset(digests)


def _directory_entries(directory: Path) -> tuple[list[Path], list[str]]:
    """The record files of ``directory``, and every entry that may not be there: only
    ``README.md`` and regular files named for a run id, no subdirectory and no link."""
    records, problems = [], []
    if not directory.is_dir():
        return records, [f"{directory.name}: not a directory"]
    for path in sorted(directory.iterdir()):
        info = os.lstat(path)
        regular = stat.S_ISREG(info.st_mode)
        if path.name == "README.md" and regular:
            continue
        stem = path.name[:-5] if path.name.endswith(".json") else None
        if regular and stem is not None and _RUN_ID.fullmatch(stem):
            records.append(path)
            continue
        problems.append(f"{path.name}: only README.md and <run_id>.json records may be here")
    return records, problems


def heads_on(records: Sequence[Mapping[str, object]]) -> list[str]:
    return sorted({str(obj["w0_head"]) for obj in records})


def validate_directory(directory: Path | str, *, repo: Path | str = ".",
                       record_text: bytes | None = None,
                       tui_digest: str | None = None,
                       tui_digests: Callable[[Path, str], frozenset[str]] | None = None
                       ) -> list[str]:
    """V7: every record's shape, then the rules across records. ``record_text`` is the
    decision record as of now (default: the working tree's) for the OD-3b citation rule.
    Every record's W0 head must be on ``main`` (an ancestor of ``origin/main`` in ``repo``).
    Every native record must carry its W0 head's TUI jail profile digest: ``tui_digest``
    when given, else the digests :func:`tui_digests_at` derives without running that head's
    code; a head whose digest cannot be derived fails."""
    directory, repo = Path(directory), Path(repo)
    records, problems = load_records(directory)
    gaps = coverage_gaps(records)
    for session in sorted(gaps):
        if session > 1 and gaps.get(session - 1, ["absent"]):
            problems.append(f"session {session} records without session {session - 1}'s "
                            "complete records")
    arms_by_block: dict[int, set[str]] = {}
    heads_by_block: dict[int, set[str]] = {}
    for obj in records:
        arms_by_block.setdefault(obj["block"], set()).add(obj["arm"])
        heads_by_block.setdefault(obj["block"], set()).add(obj["w0_head"])
    for block, arms in sorted(arms_by_block.items()):
        if len(arms) > 1:
            problems.append(f"block {block}: mixes arms")
    for obj in records:
        if obj["arm"] != EXECUTION_NOTES.blocks[obj["block"] - 1]:
            problems.append(f"{obj['run_id']}: not the arm the run plan sets for its block")
    for block, heads in sorted(heads_by_block.items()):
        if len(heads) > 1:
            problems.append(f"block {block}: more than one W0 head")
    if len({obj["run_id"] for obj in records}) != len(records):
        problems.append("a run_id repeats")
    native: dict[str, set[str]] = {}
    for obj in records:
        if obj["arm"] in NATIVE_ARMS:
            native.setdefault(obj["w0_head"], set()).add(obj["jail_profile_digest"])
    off_main = {head for head in heads_on(records) if not head_on_main(repo, head)}
    if off_main:
        problems.append("a record's W0 head is not on main")
    derive = tui_digests or tui_digests_at
    for head, digests in sorted(native.items()):
        if head in off_main:
            continue
        expected = frozenset({tui_digest}) if tui_digest is not None else derive(repo, head)
        if not expected:
            problems.append("the TUI jail profile digest at a W0 head cannot be derived")
        elif len(digests) > 1 or not digests <= expected:
            problems.append("a native record's jail_profile_digest is not the TUI's at its W0 head")
    for obj in records:
        if obj["arm"] not in NATIVE_ARMS or obj["w0_head"] in off_main:
            continue
        section = "4b" if obj["arm"] == "sdk" else "4a"
        at_head = _git_show(repo, obj["w0_head"], _transport.DECISION_RECORD)
        found = _transport.record_sections(at_head).get(section) if at_head else None
        if found is None or found[1] != obj["activation_section_sha256"] or (
                section == "4b" and not found[0].startswith("## 4b. OD-3a")):
            problems.append(f"{obj['run_id']}: its W0 head lacks the section its activation names")
    if record_text is None:
        current = repo / _transport.DECISION_RECORD
        record_text = current.read_bytes() if current.exists() else b""
    problems += od3b_problems(record_text, directory, records)
    return list(dict.fromkeys(problems))


def load_records(directory: Path) -> tuple[list[dict], list[str]]:
    """The valid records of ``directory`` and the problem of every entry that is not one."""
    paths, problems = _directory_entries(directory)
    records: list[dict] = []
    for path in paths:
        raw = path.read_bytes()
        try:
            obj = json.loads(raw)
        except ValueError:
            problems.append(f"{path.name}: not JSON")
            continue
        found = validate_record(obj)
        if found:
            problems += [f"{path.name}: {problem}" for problem in found]
            continue
        if raw != canonical_bytes(obj):
            problems.append(f"{path.name}: not canonical JSON")
        if path.name != f"{obj['run_id']}.json":
            problems.append(f"{path.name}: the file is not named for its run_id")
        records.append(obj)
    return records, problems


def _marked(body: str, marker: str) -> list[str]:
    return [line for line in body.splitlines() if line.startswith(marker)]


def od3b_problems(record_text: bytes, directory: Path,
                  records: Sequence[Mapping[str, object]]) -> list[str]:
    """OQ-4: only the latest OD-3b section, by letter, answers for this directory; earlier ones
    are history. It carries exactly one default, one digest and one sessions line. The sessions
    it names (``1`` or ``1 and 2``) are complete here, and the digest is over their records
    alone, so a later session's records can land beside it before the next section does. It
    picks ``print``, ``sdk`` or "none admitted"; a section over session 1 alone picks only
    ``print`` or "none admitted", and a transport it picks has records in its sessions."""
    headings = [line.decode("utf-8", "replace") for line in record_text.splitlines()
                if line.startswith(b"## ")]
    ids = [found.group(1) for line in headings
           if (found := re.match(r"## (\d+[a-z]?)\. ", line)) is not None]
    od3b_ids = {found.group(1) for line in headings if _OD3B_HEADING.match(line)
                and (found := re.match(r"## (\d+[a-z]?)\. ", line)) is not None}
    ambiguous = sorted(sid for sid in od3b_ids if ids.count(sid) > 1)
    if ambiguous:  # the section parser keeps one heading per id; never let it pick
        return [f"OD-3b section {sid} has more than one heading with its id" for sid in ambiguous]
    od3b = sorted(sid for sid, (heading, _d) in _transport.record_sections(record_text).items()
                  if _OD3B_HEADING.match(heading))
    if not od3b:
        return []
    sid = od3b[-1]
    body = (_transport.section_bytes(record_text, sid) or b"").decode("utf-8", "replace")
    problems = []
    defaults = _marked(body, "**Jailed Claude default:**")
    picked = _transport.DEFAULT_LINE.match(defaults[0]) if len(defaults) == 1 else None
    if picked is None:
        problems.append(f"OD-3b section {sid} needs exactly one well-formed default line")
    elif picked.group("value") == "tui":
        problems.append(f"OD-3b section {sid} may pick only print, sdk or none admitted")
    lines = _marked(body, "**W0 sessions:**")
    found = _OD3B_SESSIONS.fullmatch(lines[0]) if len(lines) == 1 else None
    if found is None:
        problems.append(f"OD-3b section {sid} needs exactly one `**W0 sessions:**` line")
        return problems
    named = SESSIONS[:2] if found["sessions"] == "1 and 2" else SESSIONS[:1]
    gaps = coverage_gaps(records)
    if any(gaps.get(session, ["absent"]) for session in named):
        problems.append(f"OD-3b section {sid} names a W0 session that is not complete here")
    digests = _marked(body, "**W0 evidence digest:**")
    cited = _OD3B_DIGEST.fullmatch(digests[0].rstrip()) if len(digests) == 1 else None
    if cited is None or cited["digest"] != evidence_digest(directory, sessions=named):
        problems.append(f"OD-3b section {sid} does not cite exactly the evidence digest of "
                        "the sessions it names")
    value = picked.group("value") if picked is not None else None
    if named == SESSIONS[:1] and value == "sdk":
        problems.append(f"OD-3b section {sid} is interim (session 1) and may pick only print "
                        "or none admitted")
    elif value in NATIVE_ARMS and not any(
            obj["arm"] == value and session_of(int(obj["block"])) in named  # type: ignore[call-overload]
            for obj in records):
        problems.append(f"OD-3b section {sid} names `{value}`, which has no record in its sessions")
    return problems


# --------------------------------------------------------------------------------------
# The run plan (Execution Notes, owner answers OQ-1 to OQ-5).
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class RunPlan:
    blocks: tuple[str, ...] = ("print", CONTROL, "sdk", "sdk", CONTROL, "print")
    runs_per_block: int = 3
    #: One reading opens each session and one closes each block (OQ-2, OQ-4).
    meter_readings: int = 8
    settle_s: int = 300
    timeout_s: int = 1800
    twins_per_native_block: int = 1
    sessions: int = 2
    #: OQ-4's early session: the blocks of each session, in order.
    session_blocks: tuple[tuple[int, ...], ...] = ((1, 2), (3, 4, 5, 6))


#: The phase plan's Execution Notes, fixed before the window.
EXECUTION_NOTES = RunPlan()
SESSIONS = tuple(range(1, EXECUTION_NOTES.sessions + 1))


def session_of(block: int) -> int:
    for session, blocks in enumerate(EXECUTION_NOTES.session_blocks, start=1):
        if block in blocks:
            return session
    raise ValueError(f"block {block} is in no session")


def sessions_held(records: Iterable[Mapping[str, object]]) -> tuple[int, ...]:
    return tuple(sorted({s for obj in records  # type: ignore[call-overload]
                         if (s := _session_or_none(int(obj["block"]))) is not None}))


def sessions_label(held: Sequence[int]) -> str:
    """How an OD-3b section names the sessions its evidence holds."""
    return " and ".join(str(session) for session in held)


def _session_or_none(block: int) -> int | None:
    try:
        return session_of(block)
    except ValueError:
        return None


def coverage_gaps(records: Iterable[Mapping[str, object]]) -> dict[int, list[str]]:
    """Each session that has any record, with what keeps it from being complete (``[]`` when
    complete). A block is complete with runs ``r1`` to ``r3`` of its planned arm; a security
    stop may end it early, but only on its last run; and a block whose arm stopped earlier
    has no record at all. Records of an unplanned block make their session incomplete."""
    by_block: dict[int, list[Mapping[str, object]]] = {}
    for obj in records:
        by_block.setdefault(int(obj["block"]), []).append(obj)  # type: ignore[call-overload]
    gaps: dict[int, list[str]] = {}
    stopped: set[str] = set()
    for session, blocks in enumerate(EXECUTION_NOTES.session_blocks, start=1):
        found: list[str] = []
        for block in blocks:
            arm = EXECUTION_NOTES.blocks[block - 1]
            runs = sorted(by_block.get(block, []),
                          key=lambda obj: int(str(obj["run_id"]).rsplit("-r", 1)[1]))
            numbers = [int(str(obj["run_id"]).rsplit("-r", 1)[1]) for obj in runs]
            withheld = [obj["security_outcome"] == "withheld_private" for obj in runs]
            if any(obj["arm"] != arm for obj in runs):
                found.append(f"block {block}: not the planned arm")
            if arm in stopped:
                if runs:
                    found.append(f"block {block}: records after its arm stopped")
                continue
            if numbers != list(range(1, len(numbers) + 1)):
                found.append(f"block {block}: runs are not r1 to r{len(numbers)}")
            elif any(withheld[:-1]) or not (
                    len(numbers) == EXECUTION_NOTES.runs_per_block
                    or (numbers and withheld[-1] and len(numbers) < EXECUTION_NOTES.runs_per_block)):
                found.append(f"block {block}: {len(numbers)} of "
                             f"{EXECUTION_NOTES.runs_per_block} runs")
            if any(withheld):
                stopped.add(arm)
        if any(block in by_block for block in blocks):
            gaps[session] = found
    extra = sorted(block for block in by_block if _session_or_none(block) is None)
    if extra:
        gaps.setdefault(0, []).append("records of an unplanned block")
    return gaps


def complete_sessions(records: Iterable[Mapping[str, object]]) -> tuple[int, ...]:
    return tuple(session for session, found in sorted(coverage_gaps(records).items())
                 if session and not found)


def session_arms(session: int) -> tuple[str, ...]:
    return tuple(sorted({EXECUTION_NOTES.blocks[block - 1]
                         for block in EXECUTION_NOTES.session_blocks[session - 1]}))


def opening_position(session: int) -> int:
    """The ledger position of the reading that opens ``session``."""
    return sum(len(blocks) + 1 for blocks in EXECUTION_NOTES.session_blocks[:session - 1])


def bracket_positions(block: int) -> tuple[int, int]:
    """The ledger positions of the two readings around ``block``: the one before it in its
    own session (the session's opening reading for its first block) and its closing one."""
    session = session_of(block)
    blocks = EXECUTION_NOTES.session_blocks[session - 1]
    after = opening_position(session) + 1 + blocks.index(block)
    return after - 1, after


#: The arms whose capture twin exists. ``sdk``'s twin (the dedicated worker under the current
#: GL-2 receipt, EC-CLAUDE-5) lands with the ``sdk`` enablement; until then session 2 refuses.
TWIN_ARMS = frozenset({"print"})


def sdk_readiness_problems(repo: Path) -> list[str]:
    """What an admitted ``sdk`` arm still needs before a session that runs it spends anything:
    its capture twin, the ratified OD-3a section (G1) and a current GL-2 worker receipt."""
    problems = []
    if "sdk" not in TWIN_ARMS:
        problems.append("the sdk arm has no capture twin yet")
    record = repo / _transport.DECISION_RECORD
    raw = record.read_bytes() if record.is_file() else b""
    found = _transport.record_sections(raw).get("4b")
    if found is None or not found[0].startswith("## 4b. OD-3a"):
        problems.append("the decision record has no ratified OD-3a section (G1)")
    try:
        from . import claude_seat_sdk

        claude_seat_sdk.preflight()
    except Exception as exc:  # any refusal or missing piece: no current GL-2 receipt here
        problems.append(f"the sdk worker has no current GL-2 receipt here ({type(exc).__name__})")
    return problems


def session_problems(session: object, directory: Path,
                     admitted: Callable[[str], bool] | None = None,
                     repo: Path | None = None) -> list[str]:
    """What refuses ``run --session``, before credentials, CA or any reading: an unknown
    session, a native arm of this session that is not admitted or (``sdk``) not ready, a
    directory that already holds this session's records, and for session 2 a directory
    without session 1's complete records."""
    if session not in SESSIONS:
        return ["run: --session must be one of " + ", ".join(map(str, SESSIONS))]
    is_admitted = admitted or _transport.is_admitted
    arms = session_arms(int(session))
    problems = [f"the {arm} arm is not admitted on this tree"
                for arm in arms if arm in NATIVE_ARMS and not is_admitted(arm)]
    if "sdk" in arms and is_admitted("sdk"):
        problems += sdk_readiness_problems(repo if repo is not None else Path("."))
    records, found = load_records(directory) if directory.exists() else ([], [])
    problems += [f"evidence: {problem}" for problem in found]
    held = sessions_held(records)
    if any(later >= int(session) for later in held):
        problems.append(f"evidence: session {session}'s or a later session's records are here")
    gaps = coverage_gaps(records)
    for earlier in range(1, int(session)):
        if gaps.get(earlier, ["absent"]):
            problems.append(f"evidence: session {session} needs session {earlier}'s complete "
                            "records here")
    return problems

#: Fields of a run-plan file that the kit takes from the operator (not plan constants). A W0
#: board runs without a landing tier, so it has no president to place on any account.
OPERATOR_FIELDS = ("w0_head", "artifact", "board", "model", "effort")


def artifact_problem(artifact: object) -> str | None:
    """The review artifact is a repo-relative path, read at the W0 head (never a host file)."""
    if (not isinstance(artifact, str) or not artifact or artifact.startswith("/")
            or "\\" in artifact or any(part in ("", ".", "..") for part in artifact.split("/"))):
        return "run plan: artifact is not a repo-relative path"
    return None


def check_run_plan(plan: Mapping[str, object]) -> list[str]:
    """Refuse a run plan that differs from Execution Notes in anything it fixes."""
    problems = []
    expected = {
        "blocks": list(EXECUTION_NOTES.blocks), "runs_per_block": EXECUTION_NOTES.runs_per_block,
        "meter_readings": EXECUTION_NOTES.meter_readings, "settle_s": EXECUTION_NOTES.settle_s,
        "timeout_s": EXECUTION_NOTES.timeout_s,
        "twins_per_native_block": EXECUTION_NOTES.twins_per_native_block,
        "sessions": EXECUTION_NOTES.sessions,
    }  # ``session_blocks`` is the kit's constant, never the operator's
    for key, value in expected.items():
        if plan.get(key) != value:
            problems.append(f"run plan: {key} differs from the phase plan's Execution Notes")
    if "landing_tier" in plan:
        problems.append("run plan: a W0 board runs without a landing tier (no president)")
    unknown = set(plan) - set(expected) - set(OPERATOR_FIELDS) - {"landing_tier"}
    if unknown:
        problems.append("run plan: unknown field(s)")
    if not (isinstance(plan.get("w0_head"), str) and _HEX40.fullmatch(plan["w0_head"])):
        problems.append("run plan: w0_head is not a 40-hex commit")
    problem = artifact_problem(plan.get("artifact"))
    if problem:
        problems.append(problem)
    return problems


def _seat_fields(seat_key: object) -> tuple[str, str, str] | None:
    parts = seat_key.split(":") if isinstance(seat_key, str) else []
    return (parts[0], parts[1], parts[2]) if len(parts) >= 3 and all(parts[:3]) else None


def composition_problems(plan: Mapping[str, object]) -> list[str]:
    """The run plan's board is the exact composed lineup (seat keys,
    ``harness:model:effort[:lens]``). It holds exactly one Claude seat, the jailed arm, at the
    plan's model and effort: on the W0 host every other Claude seat would use the W0 account."""
    board = plan.get("board")
    seats = board.get("seats") if isinstance(board, dict) else None
    if (not isinstance(board, dict) or set(board) != {"seats"} or not isinstance(seats, list)
            or not seats or any(_seat_fields(seat) is None for seat in seats)):
        return ["board: must list exactly its composed seat keys (harness:model:effort[:lens])"]
    claude = [_seat_fields(seat) for seat in seats
              if _seat_fields(seat)[0].lstrip("@") == "claude"  # type: ignore[index]
              or _seat_fields(seat)[1].startswith("claude-")]  # type: ignore[index]
    if len(claude) != 1 or claude[0][0] != "claude":  # type: ignore[index]
        return ["board: exactly one Claude seat, the jailed arm; any other would use the W0 "
                "Claude account"]
    _harness, model, effort = claude[0]  # type: ignore[misc]
    if plan.get("model") != model or plan.get("effort") != effort:
        return ["board: the run plan's model and effort are not the Claude seat's"]
    return []


def effective_composition() -> list[str]:
    """The lineup ``phase-loop advisor-board`` composes on this host, by the same function."""
    from .advisor_board.composition import compose_review_board

    return [seat.seat_key for seat in compose_review_board().seats]


def effective_unconfined_co_seats() -> tuple[str, ...]:
    """The non-Claude vendors this host's production preflight marks unconfined.

    This runs before W0's first meter reading.  A timed-out run or malformed board payload
    can therefore retain the preflight observation instead of publishing an unobserved empty
    list.
    """
    from . import panel_invoker, sandbox_policy
    from .advisor_board.composition import compose_review_board

    if not sandbox_policy.sandbox_enabled():
        return ()
    board = compose_review_board()
    # In the production review route, non-Claude legs without their own jail use the staged
    # tree directly when their tool surface can act on it.  This is the same host predicate
    # the board's pre-launch mode publication uses, evaluated without minting an operation or
    # qualifying a jail.
    return tuple(sorted({str(seat.harness).lower() for seat in board.seats
                         if str(seat.harness).lower() in CO_SEAT_VENDORS
                         and panel_invoker.sandbox_usable_by(
                             str(seat.harness).lower(), True, jailed=False)}))


def head_on_main(repo: Path, head: str) -> bool:
    try:
        done = subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", head,
                               "origin/main"], capture_output=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def checkout_problems(repo: Path, head: str) -> list[str]:
    """The board runs from the W0 tree itself: the checkout is at the W0 head with no local
    change (W0's own records excepted), and this runtime is that tree's."""
    problems = []
    try:
        current = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                 capture_output=True, text=True, timeout=60, check=False)
        status = subprocess.run(["git", "-C", str(repo), "status", "--porcelain=v1", "-z",
                                 "--untracked-files=all"], capture_output=True, timeout=120,
                                check=False)
    except (OSError, subprocess.SubprocessError):
        return ["checkout: the W0 checkout cannot be read"]
    if current.returncode != 0 or current.stdout.strip() != head:
        problems.append("checkout: the repository is not at the W0 head")
    entries = [entry for entry in status.stdout.split(b"\0") if entry]
    if status.returncode != 0 or any(
            not (entry[:3] == b"?? " and entry[3:].decode("utf-8", "replace").startswith(
                EVIDENCE_DIR + "/")) for entry in entries):
        problems.append("checkout: the W0 tree has local changes")
    runtime = Path(_transport.__file__).resolve()
    if not runtime.is_relative_to((Path(repo) / "phase-loop-runtime" / "src").resolve()):
        problems.append("checkout: this runtime is not the W0 tree's")
    return problems


def bundle_artifact(repo: Path, head: str, artifact: object) -> bytes:
    """The review artifact's bytes as committed at the W0 head (the twin's prompt and the
    board's artifact alike)."""
    problem = artifact_problem(artifact)
    if problem:
        raise ValueError(problem)
    data = _git_show(repo, head, str(artifact))
    if data is None:
        raise ValueError("run plan: the artifact is not in the W0 head")
    return data


def staged_path_sha256(artifact: str) -> str:
    """The digest the seat's observations give a completed Read of the artifact in its tree."""
    return hashlib.sha256(f"/seat/tree/{artifact}".encode()).hexdigest()


def cli_version_beside(image: Path) -> str:
    """The Claude CLI version of the native image, from its own package manifest."""
    try:
        version = json.loads((Path(image).parent / "package.json").read_text(encoding="utf-8"))[
            "version"]
    except (OSError, ValueError, KeyError, TypeError):
        return "unknown"
    return version if isinstance(version, str) and _CLI_VERSION.fullmatch(version) else "unknown"


# --------------------------------------------------------------------------------------
# Private storage: meter readings and raw captures (mode 0600, never in the repo).
# --------------------------------------------------------------------------------------

def private_root(window: str, env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    state = env.get("XDG_STATE_HOME")
    base = Path(state) if state and os.path.isabs(state) else Path.home() / ".local" / "state"
    if not re.fullmatch(r"[a-z0-9-]{1,40}", window):
        raise ValueError("window: a short slug")
    return base / "phase-loop" / "claude-w0" / window


class PrivateInputError(OSError, ValueError):
    """A private file that exists but is not a regular file the kit can use. It is a
    ``ValueError`` too, so a late refusal ends a session through its refusal handler."""


#: Private kit files are small; a larger one is not the kit's.
_PRIVATE_CAP = 1 << 20


def _private_diagnostic(path: Path) -> str:
    return dict(PRIVATE_INPUTS).get(path.name, f"{path.name}: not a regular private file")


def _open_pinned_regular(path: Path, flags: int) -> int:
    """Open the regular file at ``path`` with ``flags``, never anything else: the entry is
    pinned first with ``O_PATH | O_NOFOLLOW`` (no I/O, so no device or FIFO side effect and
    no wait), type-checked on that pin, and only then reopened through it, so a path
    swapped after the check is not what gets opened. ``FileNotFoundError`` passes through."""
    pin = os.open(path, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        pinned = os.fstat(pin)
        if not stat.S_ISREG(pinned.st_mode):
            raise PrivateInputError(_private_diagnostic(path))
        fd = os.open(f"/proc/self/fd/{pin}", flags | os.O_NONBLOCK | os.O_CLOEXEC)
    finally:
        os.close(pin)
    opened = os.fstat(fd)
    if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
            pinned.st_dev, pinned.st_ino):
        os.close(fd)
        raise PrivateInputError(_private_diagnostic(path))
    return fd


def write_private(path: Path, data: bytes) -> None:
    """Create or replace a private 0600 regular file without ever blocking: a new file is
    created exclusively; an existing entry must be a regular file, pinned before it is
    opened. A FIFO, socket, device, directory or link refuses with the file's diagnostic."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_NONBLOCK
                     | os.O_CLOEXEC, 0o600)
    except FileExistsError:
        fd = _open_pinned_regular(path, os.O_WRONLY)
    with os.fdopen(fd, "wb") as handle:
        os.ftruncate(handle.fileno(), 0)
        handle.write(data)
        handle.flush()
        os.fchmod(handle.fileno(), 0o600)
        # The write counts only if the path still names the inode written: an entry swapped
        # after the pin (or after the exclusive create) leaves the data off the path.
        written = os.fstat(handle.fileno())
        try:
            now = os.lstat(path)
        except (FileNotFoundError, NotADirectoryError):  # the entry, or its directory, moved
            now = None
        if now is None or not stat.S_ISREG(now.st_mode) or (now.st_dev, now.st_ino) != (
                written.st_dev, written.st_ino):
            raise PrivateInputError(_private_diagnostic(path))


def read_private_regular(path: Path, *, cap: int = _PRIVATE_CAP) -> bytes | None:
    """The bytes of a private regular file, ``None`` when nothing is at ``path``, and
    :class:`PrivateInputError` (or the ``OSError`` of an unreadable file) for anything else.
    It never blocks: the entry is pinned and type-checked before it is opened
    (:func:`_open_pinned_regular`), so a FIFO, socket, device, directory or link is refused,
    never opened or waited on."""
    try:
        fd = _open_pinned_regular(path, os.O_RDONLY)
    except FileNotFoundError:
        return None
    try:
        chunks, size = [], 0
        while size <= cap:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        if size > cap:
            raise PrivateInputError(f"{path.name}: too large")
        return b"".join(chunks)
    finally:
        os.close(fd)


#: The salt the kit writes: 32 random bytes as hex.
_SALT = re.compile(rb"[0-9a-f]{64}")
#: Every private file a session reads, and the diagnostic it refuses with when it exists but
#: cannot be read as a regular file.
PRIVATE_INPUTS = (
    ("meter.json", "meter: the private ledger cannot be read"),
    ("meter.salt", "meter: the private salt cannot be read"),
    ("session-identity.json", "identity: session 1's comparison identity cannot be read"),
    ("security-outcomes.txt", "security notes: the private notes cannot be read"),
    ("control-files.txt", "control files: the private list cannot be read"),
)


def private_input_problems(root: Path) -> list[str]:
    """Each private input that exists but is not a readable regular file of the kit's shape.
    Checked before any credential, CA, reading or native block, without blocking."""
    problems = []
    for name, diagnostic in PRIVATE_INPUTS:
        try:
            raw = read_private_regular(root / name)
        except OSError:
            problems.append(diagnostic)
            continue
        if name == "meter.salt" and raw is not None and not _SALT.fullmatch(raw):
            problems.append("meter: the private salt is not this kit's; archive it first")
    return problems


_READING_NAMES = ("subscription_usage", "extra_usage_spend", "api_spend")
#: A value the owner could not read is ``unavailable``; a spend the account has no meter for
#: (no API organization, no extra usage) is ``none``. Anything else is a number.
UNAVAILABLE = "unavailable"
_PERCENT = re.compile(r"(?P<n>[0-9]{1,3}(?:\.[0-9]{1,2})?) ?%")
_MONEY = re.compile(r"\$? ?(?P<n>[0-9]{1,7}(?:\.[0-9]{1,2})?)")
_STORED = re.compile(r"[0-9]{1,7}\.[0-9]{2}")
#: Prompts per value before it is recorded ``unavailable``.
READING_ATTEMPTS = 3


def normalize_reading(name: str, answer: str) -> str | None:
    """The stored form of one meter value, or ``None`` when ``answer`` is not one: a blank, a
    word, or a number in another unit never stands for a reading."""
    from decimal import Decimal

    text = answer.strip().lower()
    if text == UNAVAILABLE:
        return UNAVAILABLE
    if name != "subscription_usage" and text == "none":
        return "none"
    found = (_PERCENT if name == "subscription_usage" else _MONEY).fullmatch(text)
    if found is None:
        return None
    return str(Decimal(found["n"]).quantize(Decimal("0.01")))


def _stored_reading(item: object) -> bool:
    return isinstance(item, dict) and set(item) == set(_READING_NAMES) and all(
        isinstance(value, str) and (value == UNAVAILABLE or _STORED.fullmatch(value)
                                    or (name != "subscription_usage" and value == "none"))
        for name, value in item.items())


def _movement(before: str, after: str) -> str:
    """``moved``, ``same`` or ``unresolved`` (a value unavailable on either side, a meter on one
    side only, or a reading that went backwards)."""
    from decimal import Decimal

    if before == after == "none":
        return "same"
    if UNAVAILABLE in (before, after) or "none" in (before, after):
        return "unresolved"
    old, new = Decimal(before), Decimal(after)
    return "moved" if new > old else "same" if new == old else "unresolved"


@dataclass
class MeterLedger:
    """The owner's account usage meter readings, kept privately at fixed positions: one opens
    each session and one closes each block, after the settle interval (OQ-2, OQ-4). Session 2
    keeps session 1's readings and salt. A record carries only its block's ``meter_ref`` and
    the salted digest of the two readings that bracket it (:func:`bracket_positions`).
    Readings fill their positions in order, each once; a value is a number, ``none`` or
    ``unavailable``, re-asked when it is not."""

    root: Path
    prompt: Callable[[str], str] = input
    sleep: Callable[[float], None] = time.sleep
    readings: list[dict | None] = field(default_factory=list)
    problem: str | None = None

    def __post_init__(self) -> None:
        size = EXECUTION_NOTES.meter_readings
        path = self.root / "meter.json"
        if self.readings:
            return
        try:
            raw = read_private_regular(path)
        except OSError:
            self.readings = [None] * size
            self.problem = "meter: the private ledger cannot be read"
            return
        if raw is None:
            self.readings = [None] * size
            return
        try:
            kept = json.loads(raw)
        except ValueError:
            kept = None
        if (isinstance(kept, list) and len(kept) == size
                and all(item is None or _stored_reading(item) for item in kept)):
            self.readings = kept
        else:
            self.readings = [None] * size
            self.problem = "meter: the private ledger is not this run plan's; archive it first"

    def read(self, position: int, *, settle_s: float) -> dict:
        if self.readings[position] is not None:
            raise ValueError(f"meter: reading {position + 1} is already taken")
        openings = {opening_position(session) for session in SESSIONS}
        if position not in openings and self.readings[position - 1] is None:
            raise ValueError(f"meter: reading {position + 1} is out of order")
        if settle_s:
            self.sleep(settle_s)
        reading = {}
        for name in _READING_NAMES:
            value = None
            for _attempt in range(READING_ATTEMPTS):
                answer = self.prompt(
                    f"meter reading {position + 1} of {len(self.readings)}: {name} (a number as "
                    f"shown, 'none' if the account has no such meter, or '{UNAVAILABLE}'): ")
                value = normalize_reading(name, answer)
                if value is not None:
                    break
            reading[name] = value or UNAVAILABLE
        self.readings[position] = reading
        write_private(self.root / "meter.json", json.dumps(self.readings, indent=2).encode())
        return reading

    def salt(self) -> bytes:
        path = self.root / "meter.salt"
        try:
            raw = read_private_regular(path)
            if raw is None:
                write_private(path, os.urandom(32).hex().encode())
                raw = read_private_regular(path)
        except OSError:
            raise ValueError("meter: the private salt cannot be read") from None
        if raw is None or not _SALT.fullmatch(raw):
            raise ValueError("meter: the private salt is not this kit's; archive it first")
        return raw

    def _digest(self, block: int, salt: bytes) -> str:
        bracket = [self.readings[position] for position in bracket_positions(block)]
        return hashlib.sha256(salt + json.dumps(bracket, sort_keys=True).encode()).hexdigest()

    def digest(self, block: int) -> str:
        return self._digest(block, self.salt())

    def session_problems(self, session: int, records: Sequence[Mapping[str, object]]
                         ) -> list[str]:
        """Session 1 starts on an empty ledger. Session 2 starts only on the ledger session 1
        wrote: its readings filled, the rest empty, and the same salt, which together still
        give every session-1 record's ``meter_digest``. Nothing is created to check this."""
        first = opening_position(session)
        if any(slot is not None for slot in self.readings[first:]):
            return [f"meter: session {session}'s readings are already taken; archive the ledger"]
        path = self.root / "meter.salt"
        try:  # an existing salt must be readable and the kit's, in every session
            salt = read_private_regular(path)
        except OSError:
            return ["meter: the private salt cannot be read"]
        if salt is not None and not _SALT.fullmatch(salt):
            return ["meter: the private salt is not this kit's; archive it first"]
        if session == 1:
            return []
        if any(slot is None for slot in self.readings[:first]):
            return ["meter: the private ledger lacks the earlier sessions' readings "
                    "(another --window, or a lost ledger)"]
        earlier = [obj for obj in records if session_of(int(obj["block"])) < session]  # type: ignore[call-overload]
        if salt is None or any(obj["meter_digest"] != self._digest(int(obj["block"]), salt)  # type: ignore[call-overload]
                               for obj in earlier):
            return ["meter: the private ledger does not give the earlier sessions' meter digests"]
        return []

    def billing(self, block: int) -> str:
        """Where the block's runs landed: ``api`` or ``extra_usage`` when that spend rose across
        the block, ``subscription`` when only subscription usage rose. Any value that cannot be
        resolved (unavailable, on one side only, or gone backwards), on any meter, leaves
        ``unknown`` before any ranking, and so does a block where nothing rose."""
        before, after = (self.readings[position] for position in bracket_positions(block))
        if before is None or after is None:
            return "unknown"
        ranked = (("api_spend", "api"), ("extra_usage_spend", "extra_usage"),
                  ("subscription_usage", "subscription"))
        movements = {name: _movement(before[name], after[name]) for name, _label in ranked}
        if "unresolved" in movements.values():  # resolve every meter before ranking any
            return "unknown"
        for name, label in ranked:
            if movements[name] == "moved":
                return label
        return "unknown"


# --------------------------------------------------------------------------------------
# The capture twin (principle 5's developer-host measurement).
# --------------------------------------------------------------------------------------

RECORDER = Path(__file__).with_name("claude_bakeoff_recorder.mjs")
#: The ONLY differences the twin's environment may have from the jailed one.
TWIN_DELTA_KEYS = frozenset({"HTTPS_PROXY", "NODE_EXTRA_CA_CERTS"})
#: Jail paths the twin remaps to its own private directories.
TWIN_REMAPPED = frozenset({"HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME",
                           "XDG_STATE_HOME", "TMPDIR", "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_TMPDIR",
                           "PATH"})
_LOOPBACK_PROXY = re.compile(r"http://srt:[^@/:\s]{8,}@127\.0\.0\.1:[0-9]{1,5}")


def twin_environment(jail_env: Mapping[str, str], *, home: Path, proxy: str, ca: Path,
                     bin_dir: Path) -> dict[str, str]:
    """The jailed environment outside the seat: every jail path remapped under a fresh
    empty ``home`` (no host settings, hooks, MCP servers or plugins), plus the proxy and CA
    variables, and nothing else."""
    remap = {
        "HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_CACHE_HOME": str(home / ".cache"), "XDG_DATA_HOME": str(home / ".local/share"),
        "XDG_STATE_HOME": str(home / ".local/state"), "TMPDIR": str(home / ".tmp"),
        "CLAUDE_CONFIG_DIR": str(home / ".claude"), "CLAUDE_CODE_TMPDIR": str(home / ".tmp"),
        "PATH": f"{bin_dir}:/usr/bin:/bin",
    }
    env = {key: (remap[key] if key in remap else value) for key, value in jail_env.items()}
    env["HTTPS_PROXY"] = proxy
    env["NODE_EXTRA_CA_CERTS"] = str(ca)
    return env


def _under(value: object, root: Path) -> bool:
    try:
        return isinstance(value, str) and Path(value).resolve().is_relative_to(Path(root).resolve())
    except (OSError, ValueError):
        return False


def twin_delta_problems(jail_env: Mapping[str, str], twin_env: Mapping[str, str], *,
                        home: Path, bin_dir: Path, ca_root: Path) -> list[str]:
    """The twin's environment is the jailed one plus exactly the declared delta, with every
    remapped path under the fresh home, the declared PATH, the loopback recorder as its only
    proxy and the window's private CA."""
    problems = []
    if set(twin_env) - set(jail_env) - TWIN_DELTA_KEYS or TWIN_DELTA_KEYS - set(twin_env):
        problems.append("twin: an environment variable beyond the declared delta")
    if set(jail_env) - set(twin_env):
        problems.append("twin: a jailed environment variable is missing")
    for key, value in jail_env.items():
        if key in twin_env and key not in TWIN_REMAPPED and twin_env[key] != value:
            problems.append("twin: a jailed environment value changed")
    for key in sorted(TWIN_REMAPPED & set(twin_env)):
        if key == "PATH":
            if twin_env[key] != f"{bin_dir}:/usr/bin:/bin":
                problems.append("twin: PATH is not the declared form")
        elif not _under(twin_env[key], home):
            problems.append("twin: a remapped path is outside the fresh home")
    if not _LOOPBACK_PROXY.fullmatch(twin_env.get("HTTPS_PROXY", "")):
        problems.append("twin: the proxy is not the loopback recorder")
    if not _under(twin_env.get("NODE_EXTRA_CA_CERTS"), ca_root):
        problems.append("twin: the CA is not the window's private CA")
    return list(dict.fromkeys(problems))


def twin_command(arm: str, executable: Path, *, model: str | None, effort: str | None,
                 session_id: str) -> list[str]:
    """The block's transport argv outside the seat: the jailed argv with the host image as
    argv0. Only ``print`` has a twin today (``sdk`` is not admitted)."""
    import types

    from . import claude_seat_print, panel_invoker

    if arm not in TWIN_ARMS:
        raise ValueError(f"no capture twin for the {arm} arm")
    jail = types.SimpleNamespace(leg="claude", provider_argv0=str(executable))
    command = panel_invoker._broker_claude_tui_command(
        model=model, effort=effort, session_id=session_id, sandboxed=jail)
    return [command[0], *claude_seat_print.CLI_DELTA, *command[1:]]


def disposable_bundle(repo: Path, head: str, dest: Path) -> Path:
    """A real, unlinked copy of the W0 head: the tree exported with ``git archive`` into
    ``dest`` and a fresh repository there, with no link to (and no hook from) the owner's."""
    dest.mkdir(mode=0o700)
    archive = dest.parent / (dest.name + ".tar")
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    try:
        subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", "-o", str(archive),
                        head], check=True, capture_output=True, timeout=600, env=env)
        subprocess.run(["tar", "-x", "-f", str(archive), "-C", str(dest)], check=True,
                       capture_output=True, timeout=600, env=env)
    finally:
        archive.unlink(missing_ok=True)
    identity = ["-c", "user.name=w0-bundle", "-c", "user.email=w0-bundle@invalid",
                "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"]
    for args in (["init", "-q"], ["add", "-A"], [*identity, "commit", "-qm", "W0 bundle"]):
        subprocess.run(["git", "-C", str(dest), *args], check=True, capture_output=True,
                       timeout=600, env=env)
    return dest


def kill_group(process: "subprocess.Popen") -> None:
    """Kill ``process``'s whole process group (it was started in its own session)."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        pass


_TWIN_SUPERVISOR = r"""
import base64
import ctypes
import json
import os
import signal
import subprocess
import sys
import time

cfg = json.loads(sys.stdin.buffer.read())
libc = ctypes.CDLL(None, use_errno=True)
if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
    print(json.dumps({"error": "subreaper unavailable", "survivors": []}))
    raise SystemExit(0)

try:
    child = subprocess.Popen(
        cfg["command"], cwd=cfg["cwd"], env=cfg["env"], pass_fds=(cfg["token_fd"],),
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
except Exception:
    print(json.dumps({"error": "twin launch failed", "survivors": []}))
    raise SystemExit(0)

timed_out = False
try:
    try:
        child.communicate(base64.b64decode(cfg["prompt"]), timeout=cfg["timeout_s"])
    except subprocess.TimeoutExpired:
        timed_out = True
finally:
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def children():
    try:
        raw = open(f"/proc/{os.getpid()}/task/{os.getpid()}/children").read()
    except OSError:
        return []
    return [int(value) for value in raw.split() if value.isdigit()]


deadline = time.monotonic() + 30
while time.monotonic() < deadline:
    for pid in children():
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    while True:
        try:
            pid, _status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            pid = -1
        if pid <= 0:
            break
    remaining = children()
    if not remaining:
        break
    time.sleep(0.01)
survivors = children()
print(json.dumps({"returncode": None if timed_out else child.returncode,
                  "survivors": survivors}))
"""


def launch_capture_twin(command: Sequence[str], *, cwd: Path, env: Mapping[str, str],
                        token_fd: int, prompt: bytes, timeout_s: float) -> int | None:
    """The capture twin's one provider launch: an owner-run measurement outside
    ``launch_owned`` (principle 5), under a dedicated subreaper. The supervisor kills and
    reaps the whole descendant tree, including a descendant that starts another session,
    before returning. Its output is discarded. Returns the exit status, ``None`` past the
    timeout; a survivor stops the window."""
    config = json.dumps({"command": list(command), "cwd": str(cwd), "env": dict(env),
                         "token_fd": token_fd, "prompt": base64.b64encode(prompt).decode(),
                         "timeout_s": timeout_s}, sort_keys=True).encode()
    process = subprocess.Popen([sys.executable, "-I", "-B", "-c", _TWIN_SUPERVISOR],
                               pass_fds=(token_fd,), stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               start_new_session=True)
    try:
        try:
            stdout, _stderr = process.communicate(config, timeout=timeout_s + 45)
        except subprocess.TimeoutExpired:
            raise ValueError("twin: descendant supervisor did not finish") from None
    finally:
        kill_group(process)
    try:
        result = json.loads(stdout)
    except (TypeError, ValueError):
        raise ValueError("twin: descendant supervisor returned no result") from None
    if not isinstance(result, dict) or result.get("error") or result.get("survivors"):
        raise ValueError("twin: descendant containment failed")
    returncode = result.get("returncode")
    if returncode is not None and type(returncode) is not int:
        raise ValueError("twin: descendant supervisor returned an invalid status")
    return returncode


def create_window_ca(ca_dir: Path, node: str, srt_index: Path) -> Path:  # pragma: no cover
    """The window's private CA, made fresh by srt's own ``ca.mjs``; a CA left by an earlier
    window refuses (it is deleted at the end of every window)."""
    from . import seat_egress_proxy
    import shutil

    if ca_dir.exists():
        raise ValueError(f"twin: a CA from an earlier window is still at {ca_dir}; remove it")
    ca_dir.mkdir(mode=0o700, parents=False)
    try:
        subprocess.run([node, str(seat_egress_proxy._data_path("ca.mjs")), str(srt_index),
                        str(ca_dir)], check=True, capture_output=True, timeout=120)
    except BaseException:
        shutil.rmtree(ca_dir, ignore_errors=True)
        raise
    return ca_dir


def run_capture_twin(arm: str, plan: Mapping[str, object], *, root: Path, repo: Path,
                     token: bytes, prompt: bytes, timeout_s: int, block: int, ca_dir: Path,
                     srt_index: Path, node: str,
                     dropped: list[str] | None = None) -> dict:  # pragma: no cover - owner window
    """One capture twin (principle 5): the block's transport, outside the seat, on a
    disposable copy of the W0 bundle at a head on ``main``, with the jailed argv, environment
    and token pipe; the delta is path remaps, a fresh empty home, the proxy variable and the
    CA variable. Its output is discarded. Returns the block's public request set."""
    import shutil
    import tempfile
    import uuid

    from . import panel_invoker, seat_jail

    head = str(plan["w0_head"])
    if not head_on_main(repo, head):
        raise ValueError("twin: the W0 bundle head is not on main")
    work = Path(tempfile.mkdtemp(prefix="pl-w0-twin-", dir=root))
    recorder = None
    try:
        bundle = disposable_bundle(repo, head, work / "bundle")
        out = work / "capture.jsonl"
        config = work / "recorder.json"
        write_private(config, json.dumps({"ca_cert": str(ca_dir / "ca.crt"),
                                          "ca_key": str(ca_dir / "ca.key"),
                                          "out": str(out)}).encode())
        recorder = subprocess.Popen([node, str(RECORDER), str(srt_index), str(config)],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                                    start_new_session=True)
        ready = json.loads(recorder.stdout.readline())  # type: ignore[union-attr]
        proxy = f"http://srt:{ready['token']}@127.0.0.1:{int(ready['port'])}"
        home = work / "home"
        home.mkdir(mode=0o700)
        if any(home.iterdir()):
            raise ValueError("twin: the fresh home is not empty")
        executable = panel_invoker._resolve_claude_executable()
        token_fd = seat_jail.token_pipe(token)
        try:
            jail_env = seat_jail.seat_env("claude", token_fd=token_fd)
            env = twin_environment(jail_env, home=home, proxy=proxy, ca=ca_dir / "ca.crt",
                                   bin_dir=executable.parent)
            problems = twin_delta_problems(jail_env, env, home=home, bin_dir=executable.parent,
                                           ca_root=ca_dir)
            if problems:
                raise ValueError("; ".join(problems))
            command = twin_command(arm, executable, model=plan.get("model"),
                                   effort=plan.get("effort"), session_id=str(uuid.uuid4()))
            returncode = launch_capture_twin(command, cwd=bundle, env=env, token_fd=token_fd,
                                             prompt=prompt, timeout_s=timeout_s)
        finally:
            os.close(token_fd)
        if recorder.stdin is not None:
            recorder.stdin.close()
        try:
            recorder.wait(timeout=60)
        except subprocess.TimeoutExpired:
            pass
        raw = out.read_bytes() if out.exists() else b""
        return ingest_recorder_output(raw, token=token, twin_returncode=returncode,
                                      dropped=dropped)
    finally:
        if recorder is not None:
            kill_group(recorder)
        shutil.rmtree(work, ignore_errors=True)  # the raw capture goes with it


def ingest_recorder_output(raw: bytes, *, token: bytes, twin_returncode: int | None = 0,
                           dropped: list[str] | None = None) -> dict:
    """The recorder's JSONL, reduced to a public request set. Refuses a line that holds a
    header, a body, the token or an untemplated path. ``complete`` only with the recorder's
    closing summary present, at least one connection, every accepted connection recorded,
    every one terminated and parsed (attributed to that connection alone), no request it
    could not attribute or publish, and the twin exiting 0. A host that cannot be published
    goes to ``dropped`` (private storage) and makes the set ``partial``."""
    from . import seat_jail

    if seat_jail.contains_secret(raw, token):
        raise ValueError("recorder output carries the token")
    entries: set[tuple[str, str, str]] = set()
    complete = twin_returncode == 0
    connections = 0
    summary: dict | None = None
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except ValueError:
            raise ValueError("recorder output is not JSON lines") from None
        if not isinstance(item, dict):
            raise ValueError("recorder output is not JSON lines")
        kind = item.get("kind")
        if kind == "connection":
            if set(item) != {"kind", "terminated", "parsed"}:
                raise ValueError("recorder connection line carries other fields")
            connections += 1
            complete = complete and item["terminated"] is True and item["parsed"] is True
            continue
        if kind == "summary":
            if (set(item) != {"kind", "accepted", "recorded"} or summary is not None
                    or type(item["accepted"]) is not int or type(item["recorded"]) is not int):
                raise ValueError("recorder summary line is malformed")
            summary = item
            continue
        if kind == "unattributed":
            if set(item) != {"kind"}:
                raise ValueError("recorder line carries other fields")
            complete = False
            continue
        if set(item) != {"kind", "method", "host", "path_template"} or kind != "request":
            raise ValueError("recorder request line carries a header, a body or other fields")
        path_template = item["path_template"]
        if isinstance(path_template, str) and len(path_template) > 512:
            complete = False
            if dropped is not None:
                dropped.append("path-template-too-long")
            continue
        if path_problem(path_template):
            raise ValueError("recorder request line has an untemplated path")
        method, host = item["method"], item["host"]
        if method not in METHODS or host_problem(host) is not None:
            complete = False
            if dropped is not None:
                dropped.append(f"{str(method)[:16]} {str(host)[:253]}")
            continue
        entries.add((method, host, path_template))
    if (summary is None or connections == 0 or summary["accepted"] != summary["recorded"]
            or summary["recorded"] != connections):
        complete = False
    ordered = [{"method": m, "host": h, "path_template": p} for m, h, p in sorted(entries)]
    capture = hashlib.sha256(json.dumps(ordered, sort_keys=True).encode()).hexdigest()
    return {"completeness": "complete" if complete else "partial", "capture_digest": capture,
            "entries": ordered}


# --------------------------------------------------------------------------------------
# One run's record.
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class RunOutcome:
    """What the arm runner observed of one run (never raw text)."""

    canonical_output: str
    code: str = "none"
    admission: Mapping[str, str] = field(default_factory=dict)
    item7: Mapping[str, str] = field(default_factory=dict)
    cli_version: str = "unknown"
    claude_code_entrypoint: str = "unset"
    claude_api_key_source: str = "unknown"
    jail_profile_digest: str = "not_applicable"
    dependency_projection_digest: str = "not_applicable"
    co_seats_unconfined: tuple[str, ...] = ()


def build_record(*, arm: str, block: int, n: int, w0_head: str, outcome: RunOutcome,
                 billing: str, meter_digest: str, request_set: Mapping[str, object],
                 activation_section_sha256: str) -> dict:
    """One record. A security-class outcome publishes only ``withheld_private``: no code, no
    output and no diagnostic (every predicate ``fail``, key source ``unknown``, entrypoint
    ``unset``), so no field says which outcome it was."""
    security = _transport.od10_class(outcome.code) == _transport.SECURITY
    record = {
        "run_id": f"w0-b{block}-r{n}", "arm": arm, "block": block, "w0_head": w0_head,
        "cli_version": outcome.cli_version,
        "canonical_output": "refused" if security else outcome.canonical_output,
        "code": "none" if security else outcome.code,
        "admission": _all("fail", ADMISSION_PREDICATES) if security else dict(outcome.admission),
        "item7": _all("fail", ITEM7_PREDICATES) if security else dict(outcome.item7),
        "billing": billing, "meter_ref": f"w0-block-{block}", "meter_digest": meter_digest,
        "claude_code_entrypoint": "unset" if security else outcome.claude_code_entrypoint,
        "claude_api_key_source": "unknown" if security else outcome.claude_api_key_source,
        "request_set": dict(request_set),
        "jail_profile_digest": outcome.jail_profile_digest,
        "dependency_projection_digest": outcome.dependency_projection_digest,
        "activation_section_sha256": activation_section_sha256,
        "co_seats_unconfined": sorted(set(outcome.co_seats_unconfined)),
        "security_outcome": "withheld_private" if security else "none",
    }
    return record


def write_record(directory: Path, record: Mapping[str, object], *, token: bytes) -> Path:
    """Write one record after the live-credential scan; a hit writes nothing."""
    from . import seat_jail

    problems = validate_record(record)
    if problems:
        raise ValueError("record refused: " + "; ".join(problems))
    data = canonical_bytes(record)
    if seat_jail.contains_secret(data, token):
        raise ValueError("record refused: it carries the live credential")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{record['run_id']}.json"
    try:  # never replaces a record: two sessions cannot both publish one run id
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o644)
    except FileExistsError:
        raise ValueError(f"record refused: {path.name} already exists") from None
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    return path


class EvidenceClaimed(ValueError):
    pass


@contextlib.contextmanager
def claim_evidence(directory: Path) -> Iterator[None]:
    """Hold the evidence directory for one effectful session: an exclusive, non-blocking lock
    on the directory itself, so a second session (under any ``--window``) refuses before its
    first effect instead of racing this one to the same run ids. The lock leaves no file."""
    import fcntl

    directory.mkdir(parents=True, exist_ok=True)
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise EvidenceClaimed("evidence: another W0 session holds this directory") from None
        yield
    finally:
        os.close(fd)


SECURITY_NOTES = "security-outcomes.txt"
#: The private record of what session 1 compared, which session 2 must match.
IDENTITY = "session-identity.json"


def comparison_identity(plan: Mapping[str, object], repo: Path) -> dict:
    """What both sessions must share for their blocks to compare: the review bundle's path and
    bytes, the model, the effort and the board. The W0 head may move between sessions."""
    artifact = bundle_artifact(repo, str(plan.get("w0_head")), plan.get("artifact"))
    board = plan.get("board")
    return {"artifact": plan.get("artifact"), "artifact_sha256": hashlib.sha256(artifact).hexdigest(),
            "model": plan.get("model"), "effort": plan.get("effort"),
            "seats": list(board.get("seats", [])) if isinstance(board, dict) else None}


def identity_problems(root: Path, plan: Mapping[str, object], repo: Path,
                      session: int) -> list[str]:
    """Session 2 compares only with session 1's identity, kept privately when session 1 began."""
    if session == 1:
        return []
    path = root / IDENTITY
    try:
        raw = read_private_regular(path)
        kept = json.loads(raw) if raw is not None else None
    except (OSError, ValueError):
        return ["identity: session 1's comparison identity cannot be read"]
    try:
        current = comparison_identity(plan, repo)
    except ValueError as exc:
        return [f"identity: {exc}"]
    if kept is None:
        return ["identity: session 1's comparison identity is missing from the private ledger"]
    if kept != current:
        return ["identity: the bundle, model, effort or board differs from session 1's"]
    return []


#: The ``<device>:<inode>`` that starts a control-file row.
_IDENTITY_ROW = re.compile(r"[0-9]+:[0-9]+")
#: A control output file is a few hundred bytes; anything past this is not one.
_CONTROL_CAP = 1 << 20


@dataclass
class ControlFiles:
    """The operator's control output files. Each is opened once, without following a final
    link, and checked on that descriptor: a regular file written at or after its block's
    brief (``since``), never the same file (by device and inode) as one already given in
    this window, whatever path names it. Two children may still write identical bytes."""

    root: Path
    prompt: Callable[[str], str] = input
    report: Callable[[str], None] = print
    since: float = 0.0

    def _given(self) -> list[str]:
        """Rows ``<device>:<inode>\t<path>``, the path intact after the first tab. Earlier
        kits wrote a bare path or a bare ``<device>:<inode>``; both still count."""
        try:
            raw = read_private_regular(self.root / "control-files.txt")
        except OSError:
            raise ValueError("control files: the private list cannot be read") from None
        # Rows end in "\n" alone; no other character, Unicode or control, ends a row.
        return [row for row in (raw or b"").decode("utf-8", "surrogateescape").split("\n") if row]

    def _already_given(self, identity: str, path: Path) -> bool:
        for row in self._given():
            head, tab, rest = row.partition("\t")
            if tab and _IDENTITY_ROW.fullmatch(head):
                given_identity, given_path = head, rest
            elif _IDENTITY_ROW.fullmatch(row):
                given_identity, given_path = row, None
            else:
                given_identity, given_path = None, row
            if given_identity == identity or given_path == str(path):
                return True
        return False

    def take(self, path: Path) -> tuple[str | None, bytes, str]:
        """``(problem, bytes, identity)``; ``problem`` is ``None`` when the file is acceptable."""
        if not path.is_absolute():
            return "give an absolute path", b"", ""
        if "\n" in str(path):  # the row delimiter; every other character is kept in a row
            return "give a path without a line break", b"", ""
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        except OSError:
            return "not a regular file, or no such file", b"", ""
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            os.close(fd)
            return "not a regular file, or no such file", b"", ""
        with os.fdopen(fd, "rb") as handle:
            if info.st_mtime < self.since:
                return "written before this block's brief", b"", ""
            identity = f"{info.st_dev}:{info.st_ino}"
            if self._already_given(identity, path):
                return "already given for another run", b"", ""
            raw = handle.read(_CONTROL_CAP + 1)
        if len(raw) > _CONTROL_CAP:
            return "too large for a control output file", b"", ""
        return None, raw, identity

    def problem(self, path: Path) -> str | None:
        return self.take(path)[0]

    def accept(self, block: int, n: int) -> bytes:
        for _attempt in range(READING_ATTEMPTS):
            path = Path(self.prompt(f"control block {block} run {n}: path of the child's "
                                    "output file: ").strip())
            problem, raw, identity = self.take(path)
            if problem is None:
                rows = [*self._given(), f"{identity}\t{path}"]
                write_private(self.root / "control-files.txt",
                              "\n".join(rows).encode("utf-8", "surrogateescape"))
                return raw
            self.report(f"control block {block} run {n}: {problem}; give another file")
        raise ValueError(f"W0 stopped: no acceptable control file for block {block} run {n}")


def control_model_problem(raw: bytes, model: object) -> str | None:
    """A control child that reports another model than the run plan's is not this control."""
    try:
        data = json.loads(raw)
    except ValueError:
        return None  # ingest_control refuses it
    if isinstance(data, dict) and "model" in data and data["model"] != model:
        return "the child reports another model than the run plan's"
    return None


def private_stopped_arms(root: Path) -> set[str]:
    """Arms the private security-outcome notes stop, so an interrupted session that never
    wrote its withheld record still keeps the arm stopped. Notes that exist but cannot be
    read refuse (``ValueError``) rather than read as none."""
    try:
        raw = read_private_regular(root / SECURITY_NOTES)
    except OSError:
        raise ValueError("security notes: the private notes cannot be read") from None
    if raw is None:
        return set()
    lines = raw.decode("utf-8", "replace").splitlines()
    return {line.split(" ", 1)[0] for line in lines if line.split(" ", 1)[0] in ARMS}


# --------------------------------------------------------------------------------------
# The control block (T3 Code's SDK route).
# --------------------------------------------------------------------------------------

CONTROL_FIELDS = ("entrypoint", "api_key_source", "model", "canonical_output", "verdict",
                  "cli_version")


def control_brief(block: int, plan: Mapping[str, object]) -> str:
    return (
        f"W0 control block {block}: run {EXECUTION_NOTES.runs_per_block} reviews of the W0 "
        f"bundle at head {plan.get('w0_head')} through the T3 Code SDK route. In a T3 Code "
        "thread whose own model is not on the W0 account, delegate each run to a Claude child "
        "on the W0 account at model "
        f"{plan.get('model')} and effort {plan.get('effort')}. Each child writes one JSON file "
        "with exactly these keys and nothing else: " + ", ".join(CONTROL_FIELDS) + ". "
        "entrypoint and api_key_source are the child's CLAUDE_CODE_ENTRYPOINT and init "
        "apiKeySource; canonical_output is admitted, absent, refused or timed_out; verdict is "
        "AGREE, DISAGREE or none. Paste the file paths back to the kit."
    )


def ingest_control(raw: bytes) -> RunOutcome:
    """Parse one control child's output file. Values the kit cannot observe are marked
    ``self_reported``; the jail, staged-clone, token-pipe and seat-diagnostics predicates are
    ``not_applicable``."""
    try:
        data = json.loads(raw)
    except ValueError:
        raise ValueError("control output is not JSON") from None
    if not isinstance(data, dict) or set(data) != set(CONTROL_FIELDS):
        raise ValueError("control output must hold exactly " + ", ".join(CONTROL_FIELDS))
    output = data["canonical_output"]
    if output not in CANONICAL_OUTPUTS:
        raise ValueError("control output: canonical_output")
    entrypoint = data["entrypoint"]
    if not (isinstance(entrypoint, str) and _SLUG.fullmatch(entrypoint)):
        raise ValueError("control output: entrypoint")
    source = data["api_key_source"]
    key_source = "none" if source == "none" else ("present" if isinstance(source, str) and source
                                                  else "unknown")
    version = data["cli_version"] if isinstance(data["cli_version"], str) and _CLI_VERSION.fullmatch(
        data["cli_version"]) else "unknown"
    admission = {name: ("not_applicable" if name in CONTROL_NOT_APPLICABLE else "self_reported")
                 for name in ADMISSION_PREDICATES}
    admission["init_api_key_source_none"] = "self_reported"
    item7 = {name: ("not_applicable" if name in CONTROL_NOT_APPLICABLE else "self_reported")
             for name in ITEM7_PREDICATES}
    if data["verdict"] not in ("AGREE", "DISAGREE", "none"):
        raise ValueError("control output: verdict")
    return RunOutcome(canonical_output=output, admission=admission, item7=item7,
                      cli_version=version, claude_code_entrypoint=entrypoint,
                      claude_api_key_source=key_source)


# --------------------------------------------------------------------------------------
# The native arm runner: one board through `phase-loop advisor-board`.
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class NativeExpectation:
    """What one native run must show, fixed before the window: the arm, the W0 head and the
    TUI jail digest at it, the plan's lineup and model, the artifact's staged-path digest and
    the observed CLI version."""

    arm: str
    w0_head: str
    tui_digest: str
    seats: tuple[str, ...]
    model: str
    staged_path_sha256: str
    cli_version: str
    co_seats_unconfined: tuple[str, ...] = ()


def board_command(artifact_copy: Path) -> list[str]:
    """The board of this W0 tree's own runtime (the checkout is checked to be the W0 head)."""
    return _seat_uid.trusted_module_argv(
        "phase_loop_runtime.cli", "advisor-board", str(artifact_copy),
        "--json", "--monitoring-policy", "bounded", "--pointer-brief")


_OBSERVATION_CAP = 1 << 20


def read_observations(raw: bytes) -> list[dict]:
    """The board's bounded W0 observation bytes; malformed input proves nothing."""
    if len(raw) > _OBSERVATION_CAP:
        return []
    observations = []
    for line in raw.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            return []
        if not isinstance(item, dict) or item.get("schema") != _transport.W0_OBSERVATION_SCHEMA:
            return []
        observations.append(item)
    return observations


def co_seats_unconfined(board: Mapping[str, object]) -> tuple[str, ...]:
    """The vendors of the co-seats the board ran unconfined, from its published seat modes."""
    from . import seat_preflight

    rows = board.get("seat_modes") if isinstance(board, dict) else None
    vendors = []
    for row in rows if isinstance(rows, list) else ():
        if not isinstance(row, dict) or row.get("mode") != seat_preflight.MODE_UNCONFINED:
            continue
        vendor = str(row.get("leg", "")).lower()
        if vendor == "claude":
            continue
        if vendor not in CO_SEAT_VENDORS:
            raise ValueError("an unconfined co-seat's vendor is not in the record vocabulary")
        vendors.append(vendor)
    return tuple(sorted(set(vendors)))


def _pass(value: bool) -> str:
    return "pass" if value else "fail"


def native_outcome(board: Mapping[str, object], observations: Sequence[Mapping[str, object]], *,
                   timed_out: bool, expected: NativeExpectation) -> RunOutcome:
    """One run, reduced to closed values, each predicate from its own observation. A run
    whose jailed launch the board did not observe (no observation, another transport, an
    unconfined filesystem or no jail digest) proves nothing: every predicate fails and it
    records the W0 head's TUI digest only as the profile that head builds."""
    modes = board.get("seat_modes") if isinstance(board, dict) else None
    co_seats = (co_seats_unconfined(board) if isinstance(modes, list)
                else expected.co_seats_unconfined)

    def unobserved(output: str, code: str = "none") -> RunOutcome:
        return RunOutcome(output, code, _all("fail", ADMISSION_PREDICATES),
                          _all("fail", ITEM7_PREDICATES), cli_version=expected.cli_version,
                          jail_profile_digest=expected.tui_digest,
                          dependency_projection_digest="0" * 64 if expected.arm == "sdk"
                          else "not_applicable", co_seats_unconfined=co_seats)

    if timed_out:
        return unobserved("timed_out")
    composition = board.get("composition") if isinstance(board, dict) else None
    seats = composition.get("seats") if isinstance(composition, dict) else None
    if board and list(seats or ()) != list(expected.seats):
        raise ValueError("the board ran another lineup than the run plan's")
    legs = [leg for leg in board.get("legs", ()) if isinstance(leg, dict)
            and str(leg.get("leg", "")).lower() == "claude"] if isinstance(board, dict) else []
    leg = legs[0] if len(legs) == 1 else {}
    detail = str(leg.get("detail") or "none")
    leg_code = detail if (_code_problem(detail) is None
                          or _transport.od10_class(detail) == _transport.SECURITY) else "none"
    if len(legs) != 1 or len(observations) != 1:
        return unobserved("refused" if leg_code != "none" else "absent", leg_code)
    seen = observations[0]
    observed_code = str(seen.get("code") or "none")
    code = observed_code if (_code_problem(observed_code) is None or _transport.od10_class(
        observed_code) == _transport.SECURITY) else leg_code
    if seen.get("status") == "timeout" or seen.get("admission") == "timed_out":
        return unobserved("timed_out", code)
    digest = seen.get("jail_profile_digest")
    projection = seen.get("dependency_projection_digest")
    if (seen.get("transport") != expected.arm or seen.get("filesystem_confined") is not True
            or not (isinstance(digest, str) and _HEX64.fullmatch(digest))
            or (expected.arm == "sdk" and not (isinstance(projection, str)
                                               and _HEX64.fullmatch(projection)))):
        return unobserved("refused" if code != "none" else "absent", code)
    admitted = (seen.get("admission") == "admitted" and seen.get("status") == "ok"
                and leg.get("status") == "OK")
    proof = seen.get("login_proof")
    login = (isinstance(proof, list) and len(proof) == 3 and proof[0] in ("login", "override")
             and proof[1:] == ["oauth_token", "none"])
    reads = seen.get("read_path_sha256") if isinstance(seen.get("read_path_sha256"), list) else []
    admission = {
        "jail": _pass(digest == expected.tui_digest),
        "staged_clone": _pass(seen.get("staged_source_commit") == expected.w0_head),
        "token_pipe": _pass(seen.get("token_pipe") is True),
        "login_proof": _pass(login),
        "init_api_key_source_none": _pass(seen.get("api_key_source") == "none"),
        "session_matches": _pass(seen.get("session_matches") is True),
        "single_result": _pass(seen.get("result_count") == 1),
        "result_success": _pass(admitted),
        "exit_zero": _pass(admitted),
        "verdict_conforming": _pass(admitted),
    }
    item7 = {
        "seat_diagnostics": _pass(seen.get("diagnostics_valid") is True
                                  and seen.get("diagnostics_truncated") is False),
        "exact_model_match": _pass(seen.get("model_status") == "match"
                                   and seen.get("model") == expected.model),
        "staged_path_digest": _pass(expected.staged_path_sha256 in reads),
        "read_completed": _pass(bool(reads)),
        "session": _pass(seen.get("session_matches") is True),
        "subscription": _pass(seen.get("api_key_source") == "none" and login),
        "result": _pass(seen.get("result_count") == 1 and admitted),
        "exit": _pass(admitted),
        "verdict": _pass(admitted),
    }
    entrypoint = seen.get("entrypoint") or "unset"
    source = seen.get("api_key_source")
    return RunOutcome(
        canonical_output="admitted" if admitted else ("refused" if code != "none" else "absent"),
        code="none" if admitted else code, admission=admission, item7=item7,
        cli_version=expected.cli_version,
        claude_code_entrypoint=entrypoint if _SLUG.fullmatch(str(entrypoint)) else "other",
        claude_api_key_source=source if source in ("none", "present") else "unknown",
        jail_profile_digest=digest,
        dependency_projection_digest=projection if expected.arm == "sdk" else "not_applicable",
        co_seats_unconfined=co_seats,
    )


def _all(value: str, names: Sequence[str]) -> dict[str, str]:
    return {name: value for name in names}


def run_board(command: Sequence[str], *, cwd: Path, env: Mapping[str, str],
              timeout_s: float, pass_fds: Sequence[int] = ()) -> str:  # pragma: no cover
    """One board in its own session; its whole process group is killed on every exit.
    Returns its stdout; raises ``subprocess.TimeoutExpired`` past the timeout."""
    process = subprocess.Popen(list(command), cwd=cwd, env=dict(env), stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                               start_new_session=True, pass_fds=tuple(pass_fds))
    try:
        stdout, _ = process.communicate(timeout=timeout_s)
        return stdout or ""
    finally:
        kill_group(process)


def run_native(arm: str, *, repo: Path, artifact_copy: Path, observations: Path,
               expected: NativeExpectation, timeout_s: int,
               runner: Callable[..., str] = run_board) -> RunOutcome:
    """One run: this W0 tree's board through ``phase-loop advisor-board`` from the W0
    checkout, with the arm's selector and the observation channel set, bounded by the
    plan's per-run timeout (OQ-3); past it, the run is ``timed_out``.  The observation
    channel is an unnamed 0600 file opened by this parent and inherited only by the board;
    ``observations`` supplies its trusted 0700 parent, never a child-visible path."""
    parent = observations.parent
    try:
        info = os.lstat(parent)
    except OSError as exc:
        raise ValueError("the W0 observation directory is unavailable") from exc
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise ValueError("the W0 observation directory is not private")
    with tempfile.TemporaryFile(prefix=".claude-w0-observation-", dir=parent) as channel:
        os.fchmod(channel.fileno(), 0o600)
        env = {**os.environ, _transport.ROUTE_ENV: arm,
               _transport.W0_OBSERVATION_ENV: str(channel.fileno()),
               _transport.W0_LINEUP_ENV: json.dumps(list(expected.seats))}
        try:
            stdout = runner(board_command(artifact_copy), cwd=repo, env=env,
                            timeout_s=timeout_s, pass_fds=(channel.fileno(),))
        except subprocess.TimeoutExpired:
            return native_outcome({}, [], timed_out=True, expected=expected)
        channel.seek(0)
        observed = channel.read(_OBSERVATION_CAP + 1)
    try:
        board = json.loads(stdout or "{}")
    except ValueError:
        board = {}
    return native_outcome(board if isinstance(board, dict) else {}, read_observations(observed),
                          timed_out=False, expected=expected)


# --------------------------------------------------------------------------------------
# The window.
# --------------------------------------------------------------------------------------

@dataclass
class Window:
    """One W0 session (OQ-4) over its blocks of the plan's six. Every effect is injectable."""

    plan: Mapping[str, object]
    out_dir: Path
    ledger: MeterLedger
    token: bytes = field(repr=False)
    repo: Path = Path(".")
    native: Callable[[str, int], RunOutcome] | None = None
    control: Callable[[int, int], bytes] | None = None
    twin: Callable[[int, str], Mapping[str, object]] | None = None
    report: Callable[[str], None] = print
    compose: Callable[[], Sequence[str]] = effective_composition
    cli_version: str = "unknown"
    session: int | None = None
    #: Called with the block number just before a control block's brief is printed, so a
    #: control file's freshness cutoff never falls after the brief.
    on_brief: Callable[[int], None] | None = None
    #: True when the caller already holds :func:`claim_evidence` on ``out_dir``.
    claimed: bool = False
    stopped_arms: set[str] = field(default_factory=set)
    private_notes: list[str] = field(default_factory=list)

    def preflight(self) -> list[str]:
        """Everything that can refuse the window, before the first meter reading: the run
        plan, the lineup (declared and as this host composes it), the W0 checkout, head and
        artifact, the observed CLI version, the session's evidence, and the activation and
        admission of this session's arms only (session 1 never needs ``sdk``)."""
        problems = check_run_plan(self.plan)
        problems += session_problems(self.session, self.out_dir, repo=self.repo)
        private = private_input_problems(self.ledger.root)
        if private:
            problems += private
        elif self.ledger.problem:
            problems.append(self.ledger.problem)
        elif self.session in SESSIONS:
            records = load_records(self.out_dir)[0] if self.out_dir.exists() else []
            problems += self.ledger.session_problems(int(self.session), records)  # type: ignore[arg-type]
            problems += identity_problems(self.ledger.root, self.plan, self.repo,
                                          int(self.session))  # type: ignore[arg-type]
            try:
                private_stopped_arms(self.ledger.root)
            except ValueError as exc:
                problems.append(str(exc))
        problems += composition_problems(self.plan)
        head = str(self.plan.get("w0_head", ""))
        if _HEX40.fullmatch(head):
            if not head_on_main(self.repo, head):
                problems.append("run plan: the W0 bundle head is not on main")
            problems += checkout_problems(self.repo, head)
            try:
                bundle_artifact(self.repo, head, self.plan.get("artifact"))
            except ValueError as exc:
                problems.append(str(exc))
            arms = session_arms(self.session) if self.session in SESSIONS else ()  # type: ignore[arg-type]
            for arm in sorted(set(arms) & set(NATIVE_ARMS)):
                try:
                    self.activation(arm)
                except ValueError as exc:
                    problems.append(str(exc))
        if self.cli_version == "unknown" or not _CLI_VERSION.fullmatch(self.cli_version):
            problems.append("the Claude CLI version cannot be observed")
        if not problems:
            board = self.plan.get("board")
            if list(self.compose()) != list(board["seats"]):  # type: ignore[index]
                problems.append("board: this host composes another lineup than the run plan's")
        return problems

    def activation(self, arm: str) -> str:
        if arm not in NATIVE_ARMS:
            return "not_applicable"
        section = "4b" if arm == "sdk" else "4a"
        raw = _git_show(self.repo, str(self.plan["w0_head"]), _transport.DECISION_RECORD) or b""
        found = _transport.record_sections(raw).get(section)
        if found is None or (section == "4b" and not found[0].startswith("## 4b. OD-3a")):
            raise ValueError(f"the W0 head has no section {section} for the {arm} arm")
        return found[1]

    def run(self) -> list[Path]:
        if self.claimed:
            return self._run()
        with claim_evidence(self.out_dir):
            return self._run()

    def _control_file(self, block: int, n: int) -> bytes:
        for _attempt in range(READING_ATTEMPTS):
            raw = self.control(block, n)  # type: ignore[misc]
            problem = control_model_problem(raw, self.plan.get("model"))
            if problem is None:
                return raw
            self.report(f"control block {block} run {n}: {problem}; give another file")
        raise ValueError(f"W0 stopped: no control file for block {block} run {n} on the "
                         "run plan's model")

    def _note_security(self, arm: str, block: int, code: str) -> None:
        """Persist a security outcome privately the moment it is seen (OD-10), before any
        reading or record, so an interrupted session still leaves it and keeps the arm
        stopped."""
        self.stopped_arms.add(arm)
        self.private_notes.append(f"{arm} block {block}: {code}")
        path = self.ledger.root / SECURITY_NOTES
        kept = (read_private_regular(path) or b"").decode("utf-8", "replace").splitlines()
        write_private(path, "\n".join(dict.fromkeys(kept + self.private_notes)).encode())

    def _run(self) -> list[Path]:
        problems = self.preflight()
        if problems:
            raise ValueError("W0 refused before any run: " + "; ".join(problems))
        session = int(self.session)  # type: ignore[arg-type]
        records, _found = load_records(self.out_dir) if self.out_dir.exists() else ([], [])
        self.stopped_arms |= {str(obj["arm"]) for obj in records
                              if obj["security_outcome"] == "withheld_private"}
        self.stopped_arms |= private_stopped_arms(self.ledger.root)
        written: list[Path] = []
        if session == 1:
            write_private(self.ledger.root / IDENTITY, json.dumps(
                comparison_identity(self.plan, self.repo), sort_keys=True).encode())
        self.ledger.read(opening_position(session), settle_s=0)
        for block in EXECUTION_NOTES.session_blocks[session - 1]:
            arm = EXECUTION_NOTES.blocks[block - 1]
            outcomes: list[RunOutcome] = []
            request_set = {"completeness": "partial",
                           "capture_digest": hashlib.sha256(b"[]").hexdigest(), "entries": []}
            if arm in self.stopped_arms:
                self.report(f"block {block} ({arm}): skipped, the arm stopped on a private outcome")
            elif arm == CONTROL:
                if self.on_brief is not None:
                    self.on_brief(block)
                self.report(control_brief(block, self.plan))
                for n in range(1, EXECUTION_NOTES.runs_per_block + 1):
                    outcomes.append(ingest_control(self._control_file(block, n)))
            else:
                changed = checkout_problems(self.repo, str(self.plan["w0_head"]))
                if changed:
                    raise ValueError("W0 stopped: " + "; ".join(changed))
                if self.twin is not None:
                    request_set = dict(self.twin(block, arm))
                    changed = checkout_problems(self.repo, str(self.plan["w0_head"]))
                    if changed:
                        raise ValueError("W0 stopped after the capture twin: "
                                         + "; ".join(changed))
                for _n in range(EXECUTION_NOTES.runs_per_block):
                    outcome = self.native(arm, EXECUTION_NOTES.timeout_s)  # type: ignore[misc]
                    outcomes.append(outcome)
                    if _transport.od10_class(outcome.code) == _transport.SECURITY:
                        self._note_security(arm, block, outcome.code)
                        break
                changed = checkout_problems(self.repo, str(self.plan["w0_head"]))
                if changed:
                    raise ValueError("W0 stopped after the block's runs: "
                                     + "; ".join(changed))
            self.ledger.read(bracket_positions(block)[1], settle_s=EXECUTION_NOTES.settle_s)
            billing = self.ledger.billing(block)
            for n, outcome in enumerate(outcomes, start=1):
                record = build_record(
                    arm=arm, block=block, n=n, w0_head=str(self.plan["w0_head"]), outcome=outcome,
                    billing=billing, meter_digest=self.ledger.digest(block),
                    request_set=request_set, activation_section_sha256=self.activation(arm))
                written.append(write_record(self.out_dir, record, token=self.token))
        return written


# --------------------------------------------------------------------------------------
# CLI.
# --------------------------------------------------------------------------------------

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m phase_loop_runtime.claude_bakeoff")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate", help="V7: the shape check of the W0 records")
    validate.add_argument("directory", nargs="?", default=EVIDENCE_DIR)
    validate.add_argument("--repo", default=".")
    validate.add_argument("--tui-digest", default=None,
                          help="the TUI digest to require (default: derived per W0 head "
                               "without running its code)")
    digest = sub.add_parser("digest", help="the W0 evidence digest an OD-3b section cites")
    digest.add_argument("directory", nargs="?", default=EVIDENCE_DIR)
    digest.add_argument("--through-session", type=int, choices=SESSIONS, default=None,
                        help="digest only the records of sessions 1 to N (what an OD-3b "
                             "section naming those sessions cites)")
    run = sub.add_parser("run", help="run W0 (an owner action)")
    run.add_argument("--plan", required=True)
    run.add_argument("--repo", default=".")
    run.add_argument("--window", default="w0")
    run.add_argument("--session", type=int, required=True, choices=SESSIONS,
                     help="OQ-4: 1 runs blocks 1-2 (print, control); 2 runs blocks 3-6 "
                          "once sdk is admitted and session 1's records are here")
    brief = sub.add_parser("control-brief", help="print a control block's brief")
    brief.add_argument("--plan", required=True)
    brief.add_argument("--block", type=int, required=True)
    args = parser.parse_args(argv)
    if args.command == "validate":
        directory = Path(args.repo) / args.directory if not os.path.isabs(args.directory) else Path(args.directory)
        problems = validate_directory(directory, repo=Path(args.repo), tui_digest=args.tui_digest)
        for problem in problems:
            print(f"claude-bakeoff validate: FAIL: {problem}", file=sys.stderr)
        if not problems:
            records = load_records(directory)[0]
            print(f"claude-bakeoff validate: OK ({len(records)} record(s)"
                  f"{coverage_note(records)})")
        return 1 if problems else 0
    if args.command == "digest":
        through = SESSIONS[:args.through_session] if args.through_session else None
        print(evidence_digest(args.directory, sessions=through))
        note = coverage_note(load_records(Path(args.directory))[0])
        if note:
            print(f"claude-bakeoff digest: note: {note.removeprefix('; ')}", file=sys.stderr)
        return 0
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    if args.command == "control-brief":
        print(control_brief(args.block, plan))
        return 0
    return _run_window(plan, Path(args.repo), args.window, args.session)


def coverage_note(records: Sequence[Mapping[str, object]]) -> str:
    """What the directory's sessions mean: only complete sessions count, and session 1 alone is
    never the complete bake-off."""
    gaps = coverage_gaps(records)
    notes = [f"session {session} INCOMPLETE ({'; '.join(found)})"
             for session, found in sorted(gaps.items()) if found]
    held = complete_sessions(records)
    if tuple(held) == SESSIONS:
        notes.insert(0, "sessions " + sessions_label(held) + " complete")
    elif held:
        notes.insert(0, f"session {sessions_label(held)} of {len(SESSIONS)} only: an interim "
                        "set, not the complete bake-off")
    return "".join(f"; {note}" for note in notes)


def keep_dropped_hosts(root: Path, dropped: Sequence[str], *, session: int,
                       evidence: Path) -> str | None:
    """Keep the private dropped-host list. It never raises: a failure comes back as a note
    saying how many of this session's records are already in the evidence directory, so a
    cleanup failure never hides or replaces the session's outcome."""
    if not dropped:
        return None
    try:
        write_private(root / "dropped-hosts.txt", "\n".join(sorted(set(dropped))).encode())
        return None
    except (OSError, ValueError) as exc:
        try:
            held = [obj for obj in load_records(evidence)[0]
                    if session_of(int(obj["block"])) == session]  # type: ignore[call-overload]
            count = f"{len(held)} record(s) of session {session} are already"
        except Exception:  # best effort: the note never replaces the session's outcome
            # (a record file replaced mid-session can make the scan raise, e.g. RecursionError)
            count = f"an unknown number of session {session}'s records may already be"
        return (f"claude-bakeoff run: NOTE: the private dropped-host list was not kept ({exc}); "
                f"{count} in the evidence directory")


def session_outcome(session: int, *, refusal: str | None, written: Sequence[Path] | None,
                    note: str | None) -> int:
    """Print the session's outcome first, then any cleanup note beside it, never in its place."""
    if refusal is not None:
        print(f"claude-bakeoff run: REFUSED: {refusal}", file=sys.stderr)
        code = 1
    else:
        print(f"claude-bakeoff run: session {session} wrote {len(written or [])} record(s); "
              "review them before the records PR")
        code = 0
    if note:
        print(note, file=sys.stderr)
    return code


def _run_window(plan: Mapping[str, object], repo: Path, window: str, session: int) -> int:
    """One session, holding the evidence directory from before its gate to its end."""
    try:
        with claim_evidence(repo / EVIDENCE_DIR):
            return _run_claimed(plan, repo, window, session)
    except EvidenceClaimed as exc:
        print(f"claude-bakeoff run: REFUSED: {exc}", file=sys.stderr)
        return 1


def _run_claimed(plan: Mapping[str, object], repo: Path, window: str,
                 session: int) -> int:  # pragma: no cover - past its gate, an owner window
    import shutil

    from . import panel_invoker, seat_credentials, seat_egress_proxy, seat_jail

    root = private_root(window)

    def refused(problems: Sequence[str]) -> int:
        print("claude-bakeoff run: REFUSED: " + "; ".join(problems), file=sys.stderr)
        return 1

    gate = session_problems(session, repo / EVIDENCE_DIR, repo=repo)
    if gate:  # before any private file is read
        return refused(gate)
    gate = private_input_problems(root)  # every private input, checked without blocking
    if gate:  # before the ledger is loaded
        return refused(gate)
    ledger = MeterLedger(root)  # reads only; nothing is created before the gate passes
    gate = [ledger.problem] if ledger.problem else ledger.session_problems(
        session, load_records(repo / EVIDENCE_DIR)[0])
    if not gate:
        gate = identity_problems(root, plan, repo, session)
    if not gate:
        try:
            private_stopped_arms(root)
        except ValueError as exc:
            gate = [str(exc)]
    if gate:  # before any credential, CA, private directory or reading
        return refused(gate)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    ca_dir = root / "twin-ca"
    ca_created = False
    dropped: list[str] = []
    try:
        head = str(plan["w0_head"])
        artifact = bundle_artifact(repo, head, plan.get("artifact"))
        artifact_copy = root / "artifact" / Path(str(plan["artifact"])).name
        write_private(artifact_copy, artifact)
        credential = seat_credentials.resolve_claude_seat_credential(
            seat_credentials.DEFAULT_MARGIN_S)
        cli_version = cli_version_beside(panel_invoker._resolve_claude_executable())
        expected = NativeExpectation(
            arm="print", w0_head=head, tui_digest=seat_jail.jail_profile_digest("claude"),
            seats=tuple(plan["board"]["seats"]), model=str(plan.get("model")),  # type: ignore[index]
            staged_path_sha256=staged_path_sha256(str(plan["artifact"])),
            cli_version=cli_version, co_seats_unconfined=effective_unconfined_co_seats())
        srt_index = seat_egress_proxy.verify_install()
        node = seat_egress_proxy._node()
        create_window_ca(ca_dir, node, srt_index)
        ca_created = True
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as exc:
        if ca_created:
            shutil.rmtree(ca_dir, ignore_errors=True)
        print(f"claude-bakeoff run: REFUSED: {exc}", file=sys.stderr)
        return 1

    files = ControlFiles(root)

    def on_brief(_block: int) -> None:
        files.since = time.time()  # taken before the brief is printed

    def control(block: int, n: int) -> bytes:
        return files.accept(block, n)

    def twin(block: int, arm: str) -> Mapping[str, object]:
        return run_capture_twin(arm, plan, root=root, repo=repo, token=credential.token,
                                prompt=artifact, timeout_s=EXECUTION_NOTES.timeout_s, block=block,
                                ca_dir=ca_dir, srt_index=srt_index, node=node, dropped=dropped)

    def native(arm: str, timeout: int) -> RunOutcome:
        return run_native(arm, repo=repo, artifact_copy=artifact_copy,
                          observations=root / "observations.jsonl",
                          expected=replace(expected, arm=arm), timeout_s=timeout)

    window_run = Window(plan=plan, out_dir=repo / EVIDENCE_DIR, ledger=ledger,
                        token=credential.token, repo=repo, native=native, control=control,
                        twin=twin, cli_version=cli_version, session=session, claimed=True,
                        on_brief=on_brief)
    written: list[Path] | None = None
    refusal: str | None = None
    note: str | None = None
    try:
        try:
            written = window_run.run()
        except ValueError as exc:
            refusal = str(exc)
    finally:
        if ca_created:
            shutil.rmtree(ca_dir, ignore_errors=True)  # this window's CA ends with it
        note = keep_dropped_hosts(root, dropped, session=session, evidence=repo / EVIDENCE_DIR)
        if note and written is None and refusal is None:  # another exception is propagating
            print(note, file=sys.stderr)
    return session_outcome(session, refusal=refusal, written=written, note=note)


if __name__ == "__main__":
    sys.exit(main())
