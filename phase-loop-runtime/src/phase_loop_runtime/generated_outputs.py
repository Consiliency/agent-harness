"""agent-harness#1139 — producer provenance for IGNORED closeout outputs.

The closeout audit (``closeout_classifier.audit_ignored_outputs``) blocks on every
ignored path it cannot attribute to a producer. Two legitimate producers were
missing:

* the harness's own workflow-skill handoffs under ``.dev-skills/handoffs/``;
* a project's deterministic build outputs (``dist/``, a generated SDK, a tool
  cache) that its phase verification writes.

Neither is accepted by NAME. Ignored-ness is never evidence (agent-harness#186),
and a directory name is something any process can create. Instead:

* A handoff is accepted only when the file itself carries the handoff contract
  every workflow skill writes: frontmatter with the common required keys,
  ``from`` equal to its skill directory, and that skill one the harness ships.
* A build output is accepted only when (1) a TRACKED declaration committed at
  ``HEAD`` covers the path with a bounded glob, (2) a recorded producer run shows
  the declared command exited 0 and created or rewrote the file, and (3) the file's
  current content digest equals the digest captured when that run finished. A file
  the run did not write (including one planted before it), or one edited
  afterwards, stays ``unknown_ignored``.

Threat model: this catches accidental and unaccounted outputs, which is what the
audit is for. It is not a defence against a local actor with write access to the
worktree, who could forge the record as easily as the outputs.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

DECLARATION_PATH = ".phase-loop-generated-outputs.json"
DECLARATION_SCHEMA = "phase-loop.generated-outputs.v1"
RECORD_RELPATH = ".phase-loop/generated-outputs/record.json"
RECORD_SCHEMA = "phase-loop.generated-outputs-record.v1"

# The handoff contract keys shared by every workflow skill (see each skill's
# "Handoff frontmatter must include" line). Phase skills add more; these are the
# common floor.
HANDOFF_REQUIRED_KEYS = (
    "from", "timestamp", "repo", "repo_root", "branch", "branch_slug", "commit",
    "run_id", "artifact",
)
_HANDOFF_MAX_BYTES = 1 << 20

# A declaration may never claim the runner's own state, the handoff root (which
# must stay marker-gated) or git's metadata.
_RESERVED_ROOTS = frozenset({".git", ".phase-loop", ".codex", ".dev-skills"})
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_GLOB_CHARS = re.compile(r"[*?\[\]]")
_MAX_SNAPSHOT_FILES = 200_000


class DeclarationError(ValueError):
    """The committed declaration exists but is malformed or over-broad."""


@dataclass(frozen=True)
class Producer:
    name: str
    command: tuple[str, ...]
    outputs: tuple[str, ...]


@dataclass(frozen=True)
class Declaration:
    producers: tuple[Producer, ...]
    sha256: str


# --- declaration -----------------------------------------------------------


def _validate_glob(glob: object, where: str) -> str:
    if not isinstance(glob, str) or not glob or glob != glob.strip():
        raise DeclarationError(f"{where}: output glob must be a non-empty string without surrounding whitespace")
    if glob.startswith("/") or "\\" in glob:
        raise DeclarationError(f"{where}: output glob {glob!r} must be repo-relative POSIX")
    parts = glob.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise DeclarationError(f"{where}: output glob {glob!r} has an empty, '.' or '..' segment")
    if _GLOB_CHARS.search(parts[0]):
        # Bounded by construction: the first segment is a literal directory or
        # file, so no declaration can claim "every ignored path".
        raise DeclarationError(f"{where}: output glob {glob!r} must start with a literal path segment")
    if parts[0] in _RESERVED_ROOTS:
        raise DeclarationError(f"{where}: output glob {glob!r} claims reserved root {parts[0]!r}")
    return glob


def parse_declaration(text: str) -> Declaration:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise DeclarationError(f"{DECLARATION_PATH}: not valid JSON ({exc})") from None
    if not isinstance(data, dict) or data.get("schema") != DECLARATION_SCHEMA:
        raise DeclarationError(f"{DECLARATION_PATH}: schema must be {DECLARATION_SCHEMA!r}")
    raw_producers = data.get("producers")
    if not isinstance(raw_producers, list) or not raw_producers:
        raise DeclarationError(f"{DECLARATION_PATH}: producers must be a non-empty list")
    producers: list[Producer] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_producers):
        where = f"{DECLARATION_PATH}: producers[{index}]"
        if not isinstance(item, dict):
            raise DeclarationError(f"{where}: must be an object")
        name = item.get("name")
        if not isinstance(name, str) or not _NAME_RE.match(name) or name in seen:
            raise DeclarationError(f"{where}: name must be a unique lowercase identifier")
        seen.add(name)
        command = item.get("command")
        if isinstance(command, str):
            try:
                command = shlex.split(command)
            except ValueError as exc:
                raise DeclarationError(f"{where}: command does not parse ({exc})") from None
        if not isinstance(command, list) or not command or not all(isinstance(p, str) and p for p in command):
            raise DeclarationError(f"{where}: command must be a non-empty argv list or string")
        outputs = item.get("outputs")
        if not isinstance(outputs, list) or not outputs:
            raise DeclarationError(f"{where}: outputs must be a non-empty list of globs")
        producers.append(
            Producer(name, tuple(command), tuple(_validate_glob(g, where) for g in outputs))
        )
    return Declaration(tuple(producers), hashlib.sha256(text.encode("utf-8")).hexdigest())


def load_declaration(repo: Path) -> Declaration | None:
    """The declaration as committed at HEAD, or None when HEAD has none.

    Read from HEAD, not the worktree: a declaration counts only once it is
    committed (and so reviewable). An uncommitted edit that widens it, or an
    untracked/ignored file of the same name, is not honoured.
    """

    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "show", f"HEAD:{DECLARATION_PATH}"],
            capture_output=True, check=False,
        )
    except OSError:
        return None
    if out.returncode != 0:
        return None
    try:
        text = out.stdout.decode("utf-8")
    except UnicodeDecodeError:
        raise DeclarationError(f"{DECLARATION_PATH}: not UTF-8") from None
    return parse_declaration(text)


# --- glob matching / snapshot ------------------------------------------------


def glob_matches(glob: str, relpath: str) -> bool:
    """Segment-wise match; ``**`` spans zero or more whole segments."""

    return _match(glob.split("/"), relpath.split("/"))


def _match(pattern: list[str], parts: list[str]) -> bool:
    if not pattern:
        return not parts
    head = pattern[0]
    if head == "**":
        return any(_match(pattern[1:], parts[i:]) for i in range(len(parts) + 1))
    if not parts or not fnmatch.fnmatchcase(parts[0], head):
        return False
    return _match(pattern[1:], parts[1:])


def _literal_root(glob: str) -> str:
    literal: list[str] = []
    for part in glob.split("/"):
        if _GLOB_CHARS.search(part):
            break
        literal.append(part)
    return "/".join(literal)


def digest_path(path: Path) -> str | None:
    """Content identity of one worktree entry, never following a symlink."""

    try:
        if path.is_symlink():
            return "symlink:" + os.readlink(path)
        if not path.is_file():
            return None
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                hasher.update(chunk)
        return "sha256:" + hasher.hexdigest()
    except OSError:
        return None


def _iter_files(repo: Path, root_rel: str):
    base = repo / root_rel
    if base.is_symlink() or base.is_file():
        yield root_rel
        return
    if not base.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        rel_dir = Path(dirpath).relative_to(repo).as_posix()
        for name in dirnames:
            if (Path(dirpath) / name).is_symlink():
                yield f"{rel_dir}/{name}"
        for name in filenames:
            yield f"{rel_dir}/{name}"


def _declared_entries(repo: Path, producers: Sequence[Producer]):
    """Yield ``(relpath, producer)`` once per worktree entry a producer's globs cover."""

    seen: set[str] = set()
    for producer in producers:
        for glob in producer.outputs:
            for rel in _iter_files(repo, _literal_root(glob)):
                if rel in seen or not glob_matches(glob, rel):
                    continue
                seen.add(rel)
                if len(seen) > _MAX_SNAPSHOT_FILES:
                    raise DeclarationError(
                        f"declared outputs exceed {_MAX_SNAPSHOT_FILES} files; narrow the globs"
                    )
                yield rel, producer


def capture_pre_run_state(repo: Path) -> dict[str, int] | None:
    """The status-change time of every declared-output entry BEFORE a run.

    ``st_ctime_ns`` rather than mtime: a process can set mtime back with utime, but
    any write moves ctime to "now". None when there is no committed declaration.
    """

    declaration = load_declaration(repo)
    if declaration is None:
        return None
    state: dict[str, int] = {}
    for rel, _producer in _declared_entries(repo, declaration.producers):
        try:
            state[rel] = os.lstat(repo / rel).st_ctime_ns
        except OSError:
            continue
    return state


def snapshot(
    repo: Path,
    producers: Sequence[Producer],
    pre_run: Mapping[str, int],
    previous: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, str]]:
    """Attribute to a producer only what the run actually left behind.

    An entry counts when the run created or rewrote it (absent before, or its ctime
    moved). A file that was already sitting under a declared glob before the run and
    was not touched is NOT attributed, so pre-placed junk cannot ride along. The one
    exception keeps incremental tools working: an untouched file that a previous
    record for the SAME declaration already attributed to the same producer, still at
    the recorded digest, is carried forward.
    """

    prior_files = previous.get("files", {}) if isinstance(previous, Mapping) else {}
    files: dict[str, dict[str, str]] = {}
    for rel, producer in _declared_entries(repo, producers):
        digest = digest_path(repo / rel)
        if digest is None:
            continue
        try:
            ctime = os.lstat(repo / rel).st_ctime_ns
        except OSError:
            continue
        touched = rel not in pre_run or pre_run[rel] != ctime
        if not touched:
            prior = prior_files.get(rel)
            if not (isinstance(prior, Mapping) and prior.get("producer") == producer.name
                    and prior.get("digest") == digest):
                continue
        files[rel] = {"producer": producer.name, "digest": digest}
    return files


def write_record(
    repo: Path,
    declaration: Declaration,
    ran: Sequence[tuple[Producer, int]],
    *,
    pre_run: Mapping[str, int],
    source: str,
    run_id: str | None,
) -> dict[str, Any]:
    """Snapshot what the producers that exited 0 left behind, then persist.

    The snapshot is taken ONCE, after the whole run: a verification run is the
    unit of evidence, so a later declared producer legitimately rewriting an
    earlier one's outputs (e.g. both touching ``.cache/``) is not a mismatch.
    A producer that failed contributes no files, so its outputs stay unknown.
    """

    from .runtime_paths import ensure_phase_loop_excluded

    succeeded = [producer for producer, exit_code in ran if exit_code == 0]
    previous = load_record(repo)
    if previous is not None and previous.get("declaration_sha256") != declaration.sha256:
        previous = None
    record = {
        "schema": RECORD_SCHEMA,
        "declaration_sha256": declaration.sha256,
        "source": source,
        "run_id": run_id,
        "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "producers": [
            {"name": p.name, "command": list(p.command), "exit_code": code} for p, code in ran
        ],
        "files": snapshot(repo, succeeded, pre_run, previous),
    }
    path = repo / RECORD_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    ensure_phase_loop_excluded(repo)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return record


def load_record(repo: Path) -> dict[str, Any] | None:
    try:
        data = json.loads((repo / RECORD_RELPATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema") != RECORD_SCHEMA:
        return None
    if not isinstance(data.get("files"), dict) or not isinstance(data.get("producers"), list):
        return None
    return data


def record_verification_outputs(
    repo: Path, result: Any, pre_run: Mapping[str, int] | None
) -> dict[str, Any] | None:
    """Runner hook: attribute a finished verification run's declared outputs.

    A declared producer "ran" when its argv EXACTLY equals a verification command
    or suite argv from this run. No declaration at HEAD means nothing is written.
    """

    declaration = load_declaration(repo)
    if declaration is None or pre_run is None:
        # No pre-run state means nothing can show what THIS run touched.
        return None
    stages: list[tuple[tuple[str, ...], int]] = [
        (tuple(stage.argv), int(stage.exit_code)) for stage in (result.commands or [])
    ]
    if result.suite is not None:
        stages.append((tuple(result.suite.argv), int(result.suite.exit_code)))
    ran: list[tuple[Producer, int]] = []
    for producer in declaration.producers:
        codes = [code for argv, code in stages if argv == producer.command]
        if codes:
            # Every invocation must have passed; one failed run taints the outputs.
            ran.append((producer, next((code for code in codes if code != 0), 0)))
    if not ran:
        return None
    return write_record(
        repo, declaration, ran, pre_run=pre_run, source="runner-verification", run_id=result.run_id
    )


def run_declared_producers(repo: Path, timeout_s: float | None = None) -> dict[str, Any]:
    """CLI path for skill-driven phases: run every declared producer, then record."""

    declaration = load_declaration(repo)
    if declaration is None:
        raise DeclarationError(f"no {DECLARATION_PATH} committed at HEAD")
    pre_run = capture_pre_run_state(repo) or {}
    ran: list[tuple[Producer, int]] = []
    for producer in declaration.producers:
        print(f"closeout-audit: running producer {producer.name}: {shlex.join(producer.command)}", flush=True)
        try:
            code = subprocess.run(
                list(producer.command), cwd=repo, check=False,
                timeout=timeout_s if timeout_s and timeout_s > 0 else None,
            ).returncode
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"closeout-audit: producer {producer.name} failed: {type(exc).__name__}", flush=True)
            code = 127
        ran.append((producer, int(code)))
    return write_record(repo, declaration, ran, pre_run=pre_run, source="closeout-audit", run_id=None)


# --- verification of one ignored file ---------------------------------------


def verify_declared_output(
    repo: Path, relpath: str, declaration: Declaration | None, record: Mapping[str, Any] | None
) -> tuple[bool, str]:
    if declaration is None:
        return False, "no recognised producer"
    covering = {p.name for p in declaration.producers if any(glob_matches(g, relpath) for g in p.outputs)}
    if not covering:
        return False, "no recognised producer (not covered by a declared output glob)"
    hint = "run `phase-loop-closeout-audit --repo . --record-outputs` or the runner's verification"
    if record is None:
        return False, f"declared output with no producer record; {hint}"
    if record.get("declaration_sha256") != declaration.sha256:
        return False, f"producer record predates the committed declaration; {hint}"
    entry = record["files"].get(relpath)
    if not isinstance(entry, dict) or entry.get("producer") not in covering:
        return False, (
            "declared output the recorded producer run did not create or rewrite; "
            "remove it, or re-record if a producer should have written it"
        )
    if digest_path(repo / relpath) != entry.get("digest"):
        return False, f"declared output changed after the recorded producer run; {hint}"
    return True, f"declared output of producer {entry['producer']}"


# --- harness handoffs --------------------------------------------------------


def _bundled_skill_names() -> frozenset[str]:
    try:
        from importlib import resources

        root = resources.files("phase_loop_runtime") / "skills_bundle"
        return frozenset(
            entry.name for entry in root.iterdir()
            if entry.is_dir() and (entry / "SKILL.md").is_file()
        )
    except Exception:  # noqa: BLE001 - no bundle means no handoff is trusted
        return frozenset()


def is_harness_handoff(repo: Path, relpath: str) -> tuple[bool, str]:
    """True only for a file carrying the workflow-skill handoff contract."""

    from .discovery import parse_frontmatter_document
    from .skill_paths import resolve_handoff_root

    root_rel = resolve_handoff_root(Path("/")).relative_to(Path("/").resolve()).as_posix()
    parts = PurePosixPath(relpath).parts
    root_parts = PurePosixPath(root_rel).parts
    if parts[: len(root_parts)] != root_parts or len(parts) != len(root_parts) + 2:
        return False, "not a handoff file path"
    skill, filename = parts[-2], parts[-1]
    if not filename.endswith(".md"):
        return False, "handoff path is not a .md file"
    if skill not in _bundled_skill_names():
        return False, f"handoff directory {skill!r} is not a skill this harness ships"
    path = repo / relpath
    try:
        # Every component must be a real directory inside the repo: a symlinked
        # `.dev-skills` would let a file elsewhere borrow the marker.
        if path.resolve() != repo.resolve() / relpath or path.is_symlink() or not path.is_file():
            return False, "handoff is not a regular file inside the repo"
        if path.stat().st_size > _HANDOFF_MAX_BYTES:
            return False, "handoff exceeds size limit"
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False, "handoff unreadable"
    front = parse_frontmatter_document(text)
    missing = [key for key in HANDOFF_REQUIRED_KEYS if front.get(key) in (None, "")]
    if missing:
        return False, f"handoff frontmatter missing {', '.join(missing)}"
    if str(front.get("from")) != skill:
        return False, f"handoff `from` does not match its directory {skill!r}"
    return True, f"harness handoff written by {skill}"
