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
* ``run --plan PLAN`` -- the W0 kit (an owner action, LA-3). It refuses a run plan that differs
  from the phase plan's Execution Notes, a board whose president or a co-seat would use the W0
  Claude account, and a bundle head that is not on ``main``. Per block it brackets the runs
  with the owner's meter readings, runs the block's arm, and once per native block runs the
  capture twin. A security-class outcome stops the arm, and its records carry only
  ``withheld_private``;
* ``control-brief`` / ``ingest-control`` -- the T3 Code SDK-route control block.

Nothing here runs a provider by itself; the kit drives ``phase-loop advisor-board``.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from . import claude_seat_transport as _transport

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
#: A path segment that carries an identifier and must be ``{id}``.
_IDENTIFIER_SEGMENT = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}|[0-9]{4,}|[0-9a-f]{12,}|[A-Za-z0-9_-]{24,}|.*[0-9].*[0-9].*[0-9].*")


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
    if any(("." + host).endswith(suffix) for suffix in _PRIVATE_SUFFIXES):
        return "private-namespace host"
    return None


def path_problem(path: object) -> str | None:
    if not isinstance(path, str) or not path.startswith("/") or len(path) > 512:
        return "path"
    if any(c in path for c in "?#%@:;= \\"):
        return "path"
    for segment in path.split("/")[1:]:
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
            obj["code"] != "none" or obj["canonical_output"] != "refused"):
        problems.append("security_outcome: a withheld outcome publishes no code and no output")
    for text in _strings(obj):
        if _HEX64.fullmatch(text) or _HEX40.fullmatch(text):
            continue
        for shape, pattern in _REFUSED_SHAPES.items():
            if pattern.search(text):
                problems.append(f"a string carries a refused shape ({shape})")
    return list(dict.fromkeys(problems))


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


def evidence_digest(directory: Path | str) -> str:
    """sha256 over the sorted bytes of every record in ``directory``: independent of file
    order and names. An OD-3b section cites this value."""
    blobs = sorted(path.read_bytes() for path in Path(directory).glob("*.json"))
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


def validate_directory(directory: Path | str, *, repo: Path | str = ".",
                       record_text: bytes | None = None,
                       tui_digest: str | None = None) -> list[str]:
    """V7: every record's shape, then the rules across records. ``record_text`` is the
    decision record as of now (default: the working tree's) for the OD-3b citation rule;
    ``tui_digest``, when given, is the TUI jail profile digest every native record must
    carry."""
    directory, repo = Path(directory), Path(repo)
    problems: list[str] = []
    records: list[dict] = []
    for path in sorted(directory.glob("*.json")):
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
    for head, digests in sorted(native.items()):
        if len(digests) > 1 or (tui_digest is not None and digests != {tui_digest}):
            problems.append("a native record's jail_profile_digest is not the TUI's at its W0 head")
    for obj in records:
        if obj["arm"] not in NATIVE_ARMS:
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
    digest = evidence_digest(directory)
    for sid, (heading, _d) in sorted(_transport.record_sections(record_text).items()):
        if re.match(r"## 4[c-z]\. .*\bOD-3b\b", heading):
            body = _transport.section_bytes(record_text, sid) or b""
            cited = {m["digest"] for m in _OD3B_DIGEST.finditer(body.decode("utf-8", "replace"))}
            if digest not in cited:
                problems.append(f"OD-3b section {sid} does not cite this directory's evidence digest")
    return list(dict.fromkeys(problems))


# --------------------------------------------------------------------------------------
# The run plan (Execution Notes, owner answers OQ-1 to OQ-5).
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class RunPlan:
    blocks: tuple[str, ...] = ("print", CONTROL, "sdk", "sdk", CONTROL, "print")
    runs_per_block: int = 3
    meter_readings: int = 7
    settle_s: int = 300
    timeout_s: int = 1800
    twins_per_native_block: int = 1
    sessions: int = 1


#: The phase plan's Execution Notes, fixed before the window.
EXECUTION_NOTES = RunPlan()

#: Fields of a run-plan file that the kit takes from the operator (not plan constants).
OPERATOR_FIELDS = ("w0_head", "artifact", "landing_tier", "board", "model", "effort")


def check_run_plan(plan: Mapping[str, object]) -> list[str]:
    """Refuse a run plan that differs from Execution Notes in anything it fixes."""
    problems = []
    expected = {
        "blocks": list(EXECUTION_NOTES.blocks), "runs_per_block": EXECUTION_NOTES.runs_per_block,
        "meter_readings": EXECUTION_NOTES.meter_readings, "settle_s": EXECUTION_NOTES.settle_s,
        "timeout_s": EXECUTION_NOTES.timeout_s,
        "twins_per_native_block": EXECUTION_NOTES.twins_per_native_block,
        "sessions": EXECUTION_NOTES.sessions,
    }
    for key, value in expected.items():
        if plan.get(key) != value:
            problems.append(f"run plan: {key} differs from the phase plan's Execution Notes")
    unknown = set(plan) - set(expected) - set(OPERATOR_FIELDS)
    if unknown:
        problems.append("run plan: unknown field(s)")
    if not (isinstance(plan.get("w0_head"), str) and _HEX40.fullmatch(plan["w0_head"])):
        problems.append("run plan: w0_head is not a 40-hex commit")
    return problems


def composition_problems(board: Mapping[str, object]) -> list[str]:
    """Refuse a board whose president or any co-seat would use the W0 Claude account. On the
    W0 host every Claude seat runs on the operator's one login, so any Claude president or
    Claude co-seat other than the arm's own jailed seat is refused, unless the run plan names
    it on another operator account."""
    problems = []
    president = board.get("president") if isinstance(board, dict) else None
    seats = board.get("seats") if isinstance(board, dict) else None
    if not isinstance(seats, list) or not isinstance(president, dict):
        return ["board: must name its president and seats"]
    if _uses_w0_claude(president):
        problems.append("board: the president would use the W0 Claude account")
    claude_seats = [seat for seat in seats if isinstance(seat, dict) and _is_claude(seat)]
    if len(claude_seats) != 1:
        problems.append("board: exactly one Claude seat, the arm under test")
    for seat in seats:
        if isinstance(seat, dict) and _is_claude(seat) and seat.get("role") != "w0_arm":
            if _uses_w0_claude(seat):
                problems.append("board: a co-seat would use the W0 Claude account")
    return problems


def _is_claude(seat: Mapping[str, object]) -> bool:
    return str(seat.get("harness", "")).lower() == "claude" or str(
        seat.get("model", "")).lower().startswith("claude-")


def _uses_w0_claude(seat: Mapping[str, object]) -> bool:
    return _is_claude(seat) and seat.get("account") != "other_operator"


def head_on_main(repo: Path, head: str) -> bool:
    try:
        done = subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", head,
                               "origin/main"], capture_output=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


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


def write_private(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    os.chmod(path, 0o600)


@dataclass
class MeterLedger:
    """The owner's account usage meter readings, one before the first block and one after
    each block (after the settle interval), kept privately. A record carries only its
    block's ``meter_ref`` and the salted digest of the two readings that bracket it."""

    root: Path
    prompt: Callable[[str], str] = input
    sleep: Callable[[float], None] = time.sleep
    readings: list[dict] = field(default_factory=list)

    def read(self, index: int, *, settle_s: float) -> dict:
        if index:
            self.sleep(settle_s)
        reading = {}
        for name in ("subscription_usage", "extra_usage_spend", "api_spend"):
            answer = self.prompt(f"meter reading {index}: {name} (as shown, or 'none'): ").strip()
            reading[name] = answer[:64]
        self.readings.append(reading)
        write_private(self.root / "meter.json", json.dumps(self.readings, indent=2).encode())
        return reading

    def salt(self) -> bytes:
        path = self.root / "meter.salt"
        if not path.exists():
            write_private(path, os.urandom(32).hex().encode())
        return path.read_bytes()

    def digest(self, block: int) -> str:
        bracket = self.readings[block - 1:block + 1]
        return hashlib.sha256(self.salt() + json.dumps(bracket, sort_keys=True).encode()).hexdigest()

    def billing(self, block: int, moved: Callable[[str, str], bool] | None = None) -> str:
        """Where the block's runs landed: ``extra_usage`` or ``api`` when that spend moved
        across the block, ``subscription`` when only subscription usage moved, otherwise
        ``unknown``."""
        if len(self.readings) <= block:
            return "unknown"
        before, after = self.readings[block - 1], self.readings[block]
        changed = moved or (lambda a, b: a != b)
        if changed(before["api_spend"], after["api_spend"]):
            return "api"
        if changed(before["extra_usage_spend"], after["extra_usage_spend"]):
            return "extra_usage"
        if changed(before["subscription_usage"], after["subscription_usage"]):
            return "subscription"
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


def twin_delta_problems(jail_env: Mapping[str, str], twin_env: Mapping[str, str]) -> list[str]:
    problems = []
    if set(twin_env) - set(jail_env) - TWIN_DELTA_KEYS:
        problems.append("twin: an environment variable beyond the declared delta")
    if set(jail_env) - set(twin_env):
        problems.append("twin: a jailed environment variable is missing")
    for key, value in jail_env.items():
        if key in twin_env and key not in TWIN_REMAPPED and twin_env[key] != value:
            problems.append("twin: a jailed environment value changed")
    return problems


def twin_command(arm: str, executable: Path, *, model: str | None, effort: str | None,
                 session_id: str) -> list[str]:
    """The block's transport argv outside the seat: the jailed argv with the host image as
    argv0. Only ``print`` has a twin today (``sdk`` is not admitted)."""
    import types

    from . import claude_seat_print, panel_invoker

    if arm != "print":
        raise ValueError(f"no capture twin for the {arm} arm")
    jail = types.SimpleNamespace(leg="claude", provider_argv0=str(executable))
    command = panel_invoker._broker_claude_tui_command(
        model=model, effort=effort, session_id=session_id, sandboxed=jail)
    return [command[0], *claude_seat_print.CLI_DELTA, *command[1:]]


def run_capture_twin(arm: str, plan: Mapping[str, object], *, root: Path, repo: Path,
                     token: bytes, prompt: str, timeout_s: int, block: int,
                     srt_index: Path | None = None) -> dict:  # pragma: no cover - owner window
    """One capture twin (principle 5): the block's transport, outside the seat, on a
    disposable copy of the W0 bundle at a head on ``main``, with the jailed argv, environment
    and token pipe; the delta is path remaps, a fresh empty home, the proxy variable and the
    CA variable. Its output is discarded. Returns the block's public request set."""
    import shutil
    import tempfile
    import uuid

    from . import panel_invoker, seat_egress_proxy, seat_jail

    head = str(plan["w0_head"])
    if not head_on_main(repo, head):
        raise ValueError("twin: the W0 bundle head is not on main")
    srt_index = srt_index or seat_egress_proxy.verify_install()
    node = seat_egress_proxy._node()
    work = Path(tempfile.mkdtemp(prefix="pl-w0-twin-", dir=root))
    ca_dir = root / "twin-ca"
    try:
        if not (ca_dir / "ca.crt").exists():
            ca_dir.mkdir(mode=0o700, exist_ok=True)
            subprocess.run([node, str(seat_egress_proxy._data_path("ca.mjs")), str(srt_index),
                            str(ca_dir)], check=True, capture_output=True, timeout=120)
        bundle = work / "bundle"
        subprocess.run(["git", "-C", str(repo), "worktree", "add", "--detach", str(bundle), head],
                       check=True, capture_output=True, timeout=300)
        out = work / "capture.jsonl"
        config = work / "recorder.json"
        write_private(config, json.dumps({"ca_cert": str(ca_dir / "ca.crt"),
                                          "ca_key": str(ca_dir / "ca.key"),
                                          "out": str(out)}).encode())
        recorder = subprocess.Popen([node, str(RECORDER), str(srt_index), str(config)],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            ready = json.loads(recorder.stdout.readline())
            proxy = f"http://srt:{ready['token']}@127.0.0.1:{int(ready['port'])}"
            home = work / "home"
            home.mkdir(mode=0o700)
            executable = panel_invoker._resolve_claude_executable()
            token_fd = seat_jail.token_pipe(token)
            try:
                jail_env = seat_jail.seat_env("claude", token_fd=token_fd)
                env = twin_environment(jail_env, home=home, proxy=proxy, ca=ca_dir / "ca.crt",
                                       bin_dir=executable.parent)
                problems = twin_delta_problems(jail_env, env)
                if problems:
                    raise ValueError("; ".join(problems))
                command = twin_command(arm, executable, model=plan.get("model"),
                                       effort=plan.get("effort"), session_id=str(uuid.uuid4()))
                subprocess.run(command, input=prompt, text=True, cwd=bundle, env=env,
                               pass_fds=(token_fd,), capture_output=True, timeout=timeout_s,
                               check=False)  # the twin's output is discarded
            finally:
                os.close(token_fd)
        finally:
            if recorder.stdin is not None:
                recorder.stdin.close()
            recorder.wait(timeout=60)
        raw = out.read_bytes() if out.exists() else b""
        return ingest_recorder_output(raw, token=token)
    finally:
        subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force",
                        str(work / "bundle")], capture_output=True, timeout=300, check=False)
        shutil.rmtree(work, ignore_errors=True)  # the raw capture goes with it


def ingest_recorder_output(raw: bytes, *, token: bytes) -> dict:
    """The recorder's JSONL, reduced to a public request set. Refuses a line that holds a
    header, a body, the token or an untemplated path; ``complete`` only when every connection
    the recorder saw was terminated and parsed."""
    from . import seat_jail

    if seat_jail.contains_secret(raw, token):
        raise ValueError("recorder output carries the token")
    entries: set[tuple[str, str, str]] = set()
    complete = True
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except ValueError:
            raise ValueError("recorder output is not JSON lines") from None
        if not isinstance(item, dict):
            raise ValueError("recorder output is not JSON lines")
        if item.get("kind") == "connection":
            if set(item) != {"kind", "terminated", "parsed"}:
                raise ValueError("recorder connection line carries other fields")
            complete = complete and item["terminated"] is True and item["parsed"] is True
            continue
        if set(item) != {"kind", "method", "host", "path_template"} or item.get("kind") != "request":
            raise ValueError("recorder request line carries a header, a body or other fields")
        if item["method"] not in METHODS or host_problem(item["host"]) == "host":
            raise ValueError("recorder request line is malformed")
        if path_problem(item["path_template"]):
            raise ValueError("recorder request line has an untemplated path")
        entries.add((item["method"], item["host"], item["path_template"]))
    ordered = [{"method": m, "host": h, "path_template": p} for m, h, p in sorted(entries)]
    capture = hashlib.sha256(json.dumps(ordered, sort_keys=True).encode()).hexdigest()
    return {"completeness": "complete" if complete else "partial", "capture_digest": capture,
            "entries": [entry for entry in ordered if host_problem(entry["host"]) is None]}


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
    security = _transport.od10_class(outcome.code) == _transport.SECURITY
    record = {
        "run_id": f"w0-b{block}-r{n}", "arm": arm, "block": block, "w0_head": w0_head,
        "cli_version": outcome.cli_version,
        "canonical_output": "refused" if security else outcome.canonical_output,
        "code": "none" if security else outcome.code,
        "admission": dict(outcome.admission), "item7": dict(outcome.item7),
        "billing": billing, "meter_ref": f"w0-block-{block}", "meter_digest": meter_digest,
        "claude_code_entrypoint": outcome.claude_code_entrypoint,
        "claude_api_key_source": outcome.claude_api_key_source,
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
    path.write_bytes(data)
    return path


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

def board_command(plan: Mapping[str, object]) -> list[str]:
    command = ["phase-loop", "advisor-board", str(plan["artifact"]), "--json",
               "--monitoring-policy", "bounded", "--pointer-brief"]
    if plan.get("landing_tier"):
        command += ["--landing-tier", str(plan["landing_tier"])]
    return command


def native_outcome(board: Mapping[str, object], *, timed_out: bool,
                   tui_digest: str) -> RunOutcome:
    """The Claude leg of one board result, reduced to closed values. ``tui_digest`` is the
    TUI jail profile digest on this host: every native arm runs in that jail, and a run's own
    recorded digest, when the board result carries one, is kept instead (V7 compares)."""
    if timed_out:
        return RunOutcome("timed_out", "none", _all("fail", ADMISSION_PREDICATES),
                          _all("fail", ITEM7_PREDICATES), jail_profile_digest=tui_digest)
    legs = [leg for leg in board.get("legs", ()) if isinstance(leg, dict)
            and str(leg.get("leg", "")).lower() == "claude"] if isinstance(board, dict) else []
    if len(legs) != 1:
        return RunOutcome("absent", "none", _all("fail", ADMISSION_PREDICATES),
                          _all("fail", ITEM7_PREDICATES), jail_profile_digest=tui_digest)
    leg = legs[0]
    evidence = leg.get("broker_evidence") if isinstance(leg.get("broker_evidence"), dict) else {}
    detail = str(leg.get("detail") or "none")
    code = detail if (_code_problem(detail) is None
                      or _transport.od10_class(detail) == _transport.SECURITY) else "none"
    admitted = leg.get("status") == "OK" and (evidence.get("claude_admission") or {}).get(
        "outcome") in (None, "admitted")
    output = "admitted" if admitted else ("refused" if code != "none" else "absent")
    admission = _all("pass" if admitted else "fail", ADMISSION_PREDICATES)
    item7 = _all("fail", ITEM7_PREDICATES)
    diagnostics = evidence.get("claude_item7_diagnostics") if isinstance(evidence, dict) else None
    if isinstance(diagnostics, dict):
        item7.update({
            "seat_diagnostics": "pass" if diagnostics.get("valid") and not diagnostics.get(
                "truncated") else "fail",
            "exact_model_match": "pass" if diagnostics.get("model_status") == "match" else "fail",
            "read_completed": "pass" if any(t.get("read_completed") for t in diagnostics.get(
                "tools", ()) if isinstance(t, dict)) else "fail",
        })
    for name in ("session", "subscription", "result", "exit", "verdict", "staged_path_digest"):
        item7[name] = "pass" if admitted else "fail"
    key_source = evidence.get("claude_api_key_source")
    return RunOutcome(
        canonical_output=output, code=code, admission=admission, item7=item7,
        claude_code_entrypoint=str(evidence.get("claude_code_entrypoint") or "unset")[:32],
        claude_api_key_source="none" if key_source == "none" else (
            "present" if key_source else "unknown"),
        jail_profile_digest=str(evidence.get("seat_jail_profile_digest") or tui_digest),
        dependency_projection_digest=str(
            evidence.get("executable_dependency_projection_sha256") or "not_applicable"),
    )


def _all(value: str, names: Sequence[str]) -> dict[str, str]:
    return {name: value for name in names}


def run_native(arm: str, plan: Mapping[str, object], *, timeout_s: int, tui_digest: str,
               runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> RunOutcome:
    """One run: the native board seat path through ``phase-loop advisor-board`` with the
    arm's selector set, bounded by the plan's per-run timeout (OQ-3); past it, the run is
    ``timed_out``."""
    env = {**os.environ, _transport.ROUTE_ENV: arm}
    try:
        done = runner(board_command(plan), capture_output=True, text=True, timeout=timeout_s,
                      env=env, check=False)
    except subprocess.TimeoutExpired:
        return native_outcome({}, timed_out=True, tui_digest=tui_digest)
    try:
        board = json.loads(done.stdout or "{}")
    except ValueError:
        board = {}
    return native_outcome(board, timed_out=False, tui_digest=tui_digest)


# --------------------------------------------------------------------------------------
# The window.
# --------------------------------------------------------------------------------------

@dataclass
class Window:
    """One W0 session over the plan's six blocks. Every effect is injectable."""

    plan: Mapping[str, object]
    out_dir: Path
    ledger: MeterLedger
    token: bytes = field(repr=False)
    repo: Path = Path(".")
    native: Callable[[str, int], RunOutcome] | None = None
    control: Callable[[int, int], bytes] | None = None
    twin: Callable[[int, str], Mapping[str, object]] | None = None
    report: Callable[[str], None] = print
    stopped_arms: set[str] = field(default_factory=set)
    private_notes: list[str] = field(default_factory=list)

    def preflight(self) -> list[str]:
        problems = check_run_plan(self.plan)
        problems += composition_problems(self.plan.get("board") or {})
        head = str(self.plan.get("w0_head", ""))
        if _HEX40.fullmatch(head) and not head_on_main(self.repo, head):
            problems.append("run plan: the W0 bundle head is not on main")
        return problems

    def activation(self, arm: str) -> str:
        if arm not in NATIVE_ARMS:
            return "not_applicable"
        section = "4b" if arm == "sdk" else "4a"
        raw = _git_show(self.repo, str(self.plan["w0_head"]), _transport.DECISION_RECORD) or b""
        found = _transport.record_sections(raw).get(section)
        if found is None:
            raise ValueError(f"the W0 head has no section {section} for the {arm} arm")
        return found[1]

    def run(self) -> list[Path]:
        problems = self.preflight()
        if problems:
            raise ValueError("W0 refused before any run: " + "; ".join(problems))
        written: list[Path] = []
        self.ledger.read(0, settle_s=0)
        for block, arm in enumerate(EXECUTION_NOTES.blocks, start=1):
            outcomes: list[RunOutcome] = []
            request_set = {"completeness": "partial",
                           "capture_digest": hashlib.sha256(b"[]").hexdigest(), "entries": []}
            if arm in self.stopped_arms:
                self.report(f"block {block} ({arm}): skipped, the arm stopped on a private outcome")
            elif arm == CONTROL:
                self.report(control_brief(block, self.plan))
                for n in range(1, EXECUTION_NOTES.runs_per_block + 1):
                    outcomes.append(ingest_control(self.control(block, n)))  # type: ignore[misc]
            else:
                if self.twin is not None:
                    request_set = dict(self.twin(block, arm))
                for _n in range(EXECUTION_NOTES.runs_per_block):
                    outcome = self.native(arm, EXECUTION_NOTES.timeout_s)  # type: ignore[misc]
                    outcomes.append(outcome)
                    if _transport.od10_class(outcome.code) == _transport.SECURITY:
                        self.stopped_arms.add(arm)
                        self.private_notes.append(f"{arm} block {block}: {outcome.code}")
                        break
            self.ledger.read(block, settle_s=EXECUTION_NOTES.settle_s)
            billing = self.ledger.billing(block)
            for n, outcome in enumerate(outcomes, start=1):
                record = build_record(
                    arm=arm, block=block, n=n, w0_head=str(self.plan["w0_head"]), outcome=outcome,
                    billing=billing, meter_digest=self.ledger.digest(block),
                    request_set=request_set, activation_section_sha256=self.activation(arm))
                written.append(write_record(self.out_dir, record, token=self.token))
        if self.private_notes:
            write_private(self.ledger.root / "security-outcomes.txt",
                          "\n".join(self.private_notes).encode())
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
    validate.add_argument("--tui-digest", default=None)
    digest = sub.add_parser("digest", help="the W0 evidence digest an OD-3b section cites")
    digest.add_argument("directory", nargs="?", default=EVIDENCE_DIR)
    run = sub.add_parser("run", help="run W0 (an owner action)")
    run.add_argument("--plan", required=True)
    run.add_argument("--repo", default=".")
    run.add_argument("--window", default="w0")
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
            count = len(list(directory.glob("*.json")))
            print(f"claude-bakeoff validate: OK ({count} record(s))")
        return 1 if problems else 0
    if args.command == "digest":
        print(evidence_digest(args.directory))
        return 0
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    if args.command == "control-brief":
        print(control_brief(args.block, plan))
        return 0
    return _run_window(plan, Path(args.repo), args.window)


def _run_window(plan: Mapping[str, object], repo: Path, window: str) -> int:  # pragma: no cover
    from . import seat_credentials

    root = private_root(window)
    credential = seat_credentials.resolve_claude_seat_credential(seat_credentials.DEFAULT_MARGIN_S)

    def control(block: int, n: int) -> bytes:
        path = input(f"control block {block} run {n}: path of the child's output file: ").strip()
        return Path(path).read_bytes()

    from . import seat_jail

    tui_digest = seat_jail.jail_profile_digest("claude")
    prompt = Path(str(plan["artifact"])).read_text(encoding="utf-8")

    def twin(block: int, arm: str) -> Mapping[str, object]:
        return run_capture_twin(arm, plan, root=root, repo=repo, token=credential.token,
                                prompt=prompt, timeout_s=EXECUTION_NOTES.timeout_s, block=block)

    window_run = Window(plan=plan, out_dir=repo / EVIDENCE_DIR, ledger=MeterLedger(root),
                        token=credential.token, repo=repo,
                        native=lambda arm, timeout: run_native(arm, plan, timeout_s=timeout,
                                                               tui_digest=tui_digest),
                        control=control, twin=twin)
    try:
        written = window_run.run()
    except ValueError as exc:
        print(f"claude-bakeoff run: REFUSED: {exc}", file=sys.stderr)
        return 1
    print(f"claude-bakeoff run: wrote {len(written)} record(s); review them before the records PR")
    return 0


if __name__ == "__main__":
    sys.exit(main())
