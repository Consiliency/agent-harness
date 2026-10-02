"""agent-harness#1139 — producer provenance for IGNORED closeout outputs.

The closeout audit (``closeout_classifier.audit_ignored_outputs``) blocks on every
ignored path it cannot attribute to a producer. Two legitimate producers were
missing:

* the harness's own workflow-skill handoffs under ``.dev-skills/handoffs/``;
* a project's deterministic build outputs (``dist/``, a generated SDK, a tool
  cache) that its phase verification writes.

Neither is accepted by NAME. Ignored-ness is never evidence (agent-harness#186),
and a directory name is something any process can create.

One rule decides a declared build output. It is evidence the producer's OWN
execution left behind, never an inference from what else happened in the run:

* A TRACKED declaration committed at ``HEAD`` covers the path with a bounded glob.
* The recorder observes each declared producer invocation on its own. It digests
  that producer's declared outputs immediately before and after the invocation. A
  file is attributed to the producer only if that invocation CREATED it or CHANGED
  ITS CONTENT. A timestamp, mode or link change is not a write, and a file another
  command wrote is never attributed.
* An untouched output carries forward from an earlier record only when the same
  producer ran successfully again in this recording and the bytes are unchanged.
  This is how an incremental producer keeps its evidence. ``--record-outputs``
  instead moves existing outputs aside first (a clean, observed rebuild), so
  byte-identical regeneration earns provenance and nothing planted rides along.
* Each invocation records the HEAD it ran at. The record is bound to that commit,
  to the declaration's digest and to the PHASE IDENTITY (``current_phase``: an
  explicit alias, else ``PHASE_LOOP_PHASE_ALIAS``, which the launcher stamps on every
  executor child; never ``state.json``). With a phase identity supplied, evidence
  from another commit or another phase does not satisfy an audit; with none,
  nothing is recorded or accepted. If HEAD moves before the record is persisted,
  nothing is recorded.
* Symlinks, and paths reached through a symlinked directory, are never recorded
  or accepted.
* At audit time, the file's current digest must equal the recorded one.

Threat model: this catches accidental and unaccounted outputs, which is what the
audit is for. It is not a defence against a local actor with write access to the
worktree, who could forge the record as easily as the outputs.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import signal
import stat
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

DECLARATION_PATH = ".phase-loop-generated-outputs.json"
DECLARATION_SCHEMA = "phase-loop.generated-outputs.v1"
RECORD_RELPATH = ".phase-loop/generated-outputs/record.json"
RECORD_SCHEMA = "phase-loop.generated-outputs-record.v2"

# The handoff contract keys shared by every workflow skill (see each skill's
# "Handoff frontmatter must include" line). Phase skills add more; these are the
# common floor.
HANDOFF_REQUIRED_KEYS = (
    "from", "timestamp", "repo", "repo_root", "branch", "branch_slug", "commit",
    "run_id", "artifact",
)
_HANDOFF_MAX_BYTES = 1 << 20

# A declaration may never claim the runner's own state, the handoff root (which
# must stay marker-gated) or git's metadata. Compared case-insensitively: on a
# case-insensitive filesystem `.GIT/` IS `.git/`.
_RESERVED_ROOTS = frozenset({".git", ".phase-loop", ".codex", ".dev-skills"})
_DECLARATION_KEYS = frozenset({"schema", "producers"})
_PRODUCER_KEYS = frozenset({"name", "command", "outputs"})
# `command` is an argv matched token for token, never a shell line: these tokens
# would never match a verification argv, and they signal a misunderstanding.
_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SHELL_PUNCTUATION = re.compile(r"^[();<>|&]+$")


def _shell_syntax_in(command_text: str) -> bool:
    """True when a STRING command uses shell control or redirection syntax anywhere
    (``a&&b``, ``build 2>/dev/null``, ``x;y``, backticks, ``$(...)``), outside quotes.

    ``punctuation_chars`` makes shlex split operators out even with no surrounding
    whitespace, while quoted arguments stay literal. Producers run without a shell, so
    such a line would never do what it says. A LIST command is an explicit argv: only
    an element that is NOTHING but shell punctuation is refused there
    (``["python", "-c", "a; b"]`` is fine).
    """

    lexer = shlex.shlex(command_text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return True
    return any(_SHELL_PUNCTUATION.match(token) for token in tokens) or any(
        "`" in token or "$(" in token for token in tokens
    )


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

    def covers(self, relpath: str) -> bool:
        return any(glob_matches(glob, relpath) for glob in self.outputs)


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
    if parts[0].lower() in _RESERVED_ROOTS:
        raise DeclarationError(f"{where}: output glob {glob!r} claims reserved root {parts[0]!r}")
    return glob


def parse_declaration(text: str) -> Declaration:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise DeclarationError(f"{DECLARATION_PATH}: not valid JSON ({exc})") from None
    if not isinstance(data, dict) or data.get("schema") != DECLARATION_SCHEMA:
        raise DeclarationError(f"{DECLARATION_PATH}: schema must be {DECLARATION_SCHEMA!r}")
    # v1 is closed: an unknown key is an error, never silently ignored, so a later
    # field (cwd, env, ...) cannot change meaning under a runtime that predates it.
    unknown = sorted(set(data) - _DECLARATION_KEYS)
    if unknown:
        raise DeclarationError(f"{DECLARATION_PATH}: unknown key(s) {unknown} in {DECLARATION_SCHEMA}")
    raw_producers = data.get("producers")
    if not isinstance(raw_producers, list) or not raw_producers:
        raise DeclarationError(f"{DECLARATION_PATH}: producers must be a non-empty list")
    producers: list[Producer] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_producers):
        where = f"{DECLARATION_PATH}: producers[{index}]"
        if not isinstance(item, dict):
            raise DeclarationError(f"{where}: must be an object")
        unknown = sorted(set(item) - _PRODUCER_KEYS)
        if unknown:
            raise DeclarationError(f"{where}: unknown key(s) {unknown}")
        name = item.get("name")
        if not isinstance(name, str) or not _NAME_RE.match(name) or name in seen:
            raise DeclarationError(f"{where}: name must be a unique lowercase identifier")
        seen.add(name)
        command = item.get("command")
        if isinstance(command, str) and _shell_syntax_in(command):
            raise DeclarationError(
                f"{where}: command is an argv, not a shell line; declare one producer per command"
            )
        if isinstance(command, str):
            try:
                command = shlex.split(command)
            except ValueError as exc:
                raise DeclarationError(f"{where}: command does not parse ({exc})") from None
        if not isinstance(command, list) or not command or not all(isinstance(p, str) and p for p in command):
            raise DeclarationError(f"{where}: command must be a non-empty argv list or string")
        if any(_SHELL_PUNCTUATION.match(token) for token in command):
            # A bare `|`, `&&`, `;` or `>` element in an argv list is a shell line
            # split on spaces, not an argument anyone means.
            raise DeclarationError(
                f"{where}: command is an argv, not a shell line; declare one producer per command"
            )
        if _ENV_ASSIGNMENT.match(command[0]):
            raise DeclarationError(
                f"{where}: command starts with an environment assignment; producers run without a shell"
            )
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


def head_commit(repo: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", "-q", "HEAD^{commit}"],
            capture_output=True, text=True, check=False,
        )
    except OSError:
        return None
    sha = out.stdout.strip()
    return sha if out.returncode == 0 and sha else None


# --- glob matching / file identity --------------------------------------------


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


def _regular_file_in_repo(repo: Path, relpath: str) -> os.stat_result | None:
    """lstat of a REGULAR file reached with no symlink anywhere on its path."""

    current = repo
    for part in PurePosixPath(relpath).parts:
        current = current / part
        try:
            st = os.lstat(current)
        except OSError:
            return None
        if stat.S_ISLNK(st.st_mode):
            return None
    return st if stat.S_ISREG(st.st_mode) else None


def file_identity(repo: Path, relpath: str) -> tuple[str, int] | None:
    """``(sha256 digest, mtime_ns)`` of a regular in-repo file, else None.

    A symlink, or a path through a symlinked directory, has no identity: its
    content lives wherever the link points, so pinning the link pins nothing.
    """

    st = _regular_file_in_repo(repo, relpath)
    if st is None:
        return None
    try:
        hasher = hashlib.sha256()
        with open(repo / relpath, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                hasher.update(chunk)
    except OSError:
        return None
    return "sha256:" + hasher.hexdigest(), st.st_mtime_ns


def _iter_candidates(repo: Path, root_rel: str):
    base = repo / root_rel
    if _regular_file_in_repo(repo, root_rel) is not None:
        yield root_rel
        return
    if base.is_symlink() or not base.is_dir():
        return
    for dirpath, _dirnames, filenames in os.walk(base, followlinks=False):
        rel_dir = Path(dirpath).relative_to(repo).as_posix()
        for name in filenames:
            yield f"{rel_dir}/{name}"


def output_identities(repo: Path, producer: Producer) -> dict[str, tuple[str, int]]:
    """Identity of every regular file the producer's globs currently cover."""

    found: dict[str, tuple[str, int]] = {}
    for glob in producer.outputs:
        for rel in _iter_candidates(repo, _literal_root(glob)):
            if rel in found or not glob_matches(glob, rel):
                continue
            identity = file_identity(repo, rel)
            if identity is None:
                continue
            found[rel] = identity
            if len(found) > _MAX_SNAPSHOT_FILES:
                raise DeclarationError(
                    f"declared outputs exceed {_MAX_SNAPSHOT_FILES} files; narrow the globs"
                )
    return found


# --- recording -----------------------------------------------------------------


PHASE_ENV_KEYS = ("PHASE_LOOP_PHASE_ALIAS", "PHASE_ALIAS")


def current_phase(provided: str | None = None) -> str | None:
    """The phase identity evidence is bound to, or None when it is UNKNOWN.

    In order: an explicit alias (the runner's live alias, or ``--phase``), then
    ``PHASE_LOOP_PHASE_ALIAS``, which the launcher stamps with the dispatched phase on
    every executor child (``launcher.launch(phase_alias=...)``), then ``PHASE_ALIAS``.

    There is deliberately NO fallback to ``.phase-loop/state.json``: the runner writes
    it only after a loop ends, so mid-loop it names the PREVIOUS phase (or nothing),
    and two phases would share one identity. Unknown identity is treated as no
    evidence: nothing is recorded and nothing is accepted.
    """

    if provided and provided.strip():
        return provided.strip()
    for key in PHASE_ENV_KEYS:
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return None


@dataclass
class _Invocation:
    producer: Producer
    exit_code: int
    written: dict[str, str]          # files this invocation created or changed -> digest
    present: dict[str, str]          # every covered file after it -> digest
    head: str | None                 # HEAD while it ran (before == after, else None)


@dataclass
class ProducerRecorder:
    """Observes declared producer invocations one at a time and records them.

    ``before``/``after`` bracket ONE command. Only a command whose argv exactly
    equals a declared producer's is observed; every other command is invisible
    to attribution, so nothing it writes can borrow a producer's identity.
    """

    repo: Path
    declaration: Declaration
    invocations: list[_Invocation] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @classmethod
    def for_repo(cls, repo: Path) -> "ProducerRecorder | None":
        declaration = load_declaration(repo)
        return None if declaration is None else cls(Path(repo), declaration)

    def producer_for(self, argv: Sequence[str]) -> Producer | None:
        argv = tuple(str(part) for part in argv)
        return next((p for p in self.declaration.producers if p.command == argv), None)

    def before(self, argv: Sequence[str]):
        producer = self.producer_for(argv)
        if producer is None:
            return None
        try:
            return producer, output_identities(self.repo, producer), head_commit(self.repo)
        except Exception as exc:  # noqa: BLE001 - an unobserved producer records nothing (blocks)
            self.errors.append(f"{producer.name}: pre-run snapshot failed: {exc}")
            return None

    def after(self, token, exit_code: int) -> None:
        if token is None:
            return
        producer, pre, head_before = token
        try:
            post = output_identities(self.repo, producer)
        except Exception as exc:  # noqa: BLE001
            self.errors.append(f"{producer.name}: post-run snapshot failed: {exc}")
            post = {}
            exit_code = exit_code or 1  # an unobservable run taints, never credits
        # HEAD is part of what was observed: an invocation that straddles a commit
        # belongs to neither commit.
        head_after = head_commit(self.repo)
        head = head_before if head_before is not None and head_before == head_after else None
        # Written = created, or its CONTENT changed. A timestamp, mode or link change is
        # not a write: `touch`, `utime`, `chmod` and `ln` on a planted file credit nothing.
        written = {
            rel: digest for rel, (digest, _mtime) in post.items()
            if rel not in pre or pre[rel][0] != digest
        }
        present = {rel: digest for rel, (digest, _mtime) in post.items()}
        self.invocations.append(_Invocation(producer, int(exit_code), written, present, head))

    def run(self, producer: Producer, timeout_s: float | None = None) -> int:
        token = self.before(producer.command)
        code = _run_bounded(list(producer.command), self.repo, timeout_s, producer.name)
        self.after(token, code)
        return code

    def write(self, *, source: str, run_id: str | None, phase_alias: str | None = None) -> dict[str, Any] | None:
        if not self.invocations:
            return None
        head = head_commit(self.repo)
        if head is None:
            self.errors.append("no HEAD commit to bind the record to")
            return None
        # Bind to the commit the producers were OBSERVED at, not the one current at
        # persistence: a commit landing in between would relabel old outputs.
        if any(inv.head != head for inv in self.invocations):
            self.errors.append(
                "HEAD moved while or after the producers ran; nothing recorded, re-record at the new commit"
            )
            return None
        phase = current_phase(phase_alias)
        if phase is None:
            self.errors.append(
                "no phase identity (no live runner alias, PHASE_LOOP_PHASE_ALIAS or --phase); "
                "nothing recorded"
            )
            return None
        previous = load_record(self.repo)
        if previous is not None and previous.get("declaration_sha256") != self.declaration.sha256:
            previous = None
        prior_files: dict[str, dict[str, str]] = dict(previous["files"]) if previous else {}
        # Same commit, declaration AND phase: this recording EXTENDS the record, so a
        # repair turn or relaunch that re-runs one producer keeps the others' evidence.
        # Anything else starts empty: another phase's evidence never satisfies this one.
        same_epoch = (
            previous is not None and previous.get("head") == head and previous.get("phase") == phase
        )
        files: dict[str, dict[str, str]] = dict(prior_files) if same_epoch else {}
        history = list(previous.get("invocations", [])) if same_epoch else []
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for inv in self.invocations:
            name = inv.producer.name
            # This producer's evidence so far: the earlier record, then anything an
            # earlier invocation in THIS recording already credited to it.
            mine = {rel: e for rel, e in prior_files.items() if e["producer"] == name}
            mine.update({rel: e for rel, e in files.items() if e["producer"] == name})
            files = {rel: e for rel, e in files.items() if e["producer"] != name}
            if inv.exit_code == 0:
                # Carry forward only what this producer, having just run successfully,
                # left byte-identical: incremental and deterministic producers. (An
                # output the producer has STOPPED producing but that nobody deleted
                # also passes this test; see the doc.)
                for rel, entry in mine.items():
                    if rel not in inv.written and inv.present.get(rel) == entry["digest"] \
                            and rel not in files:
                        files[rel] = {"producer": name, "digest": entry["digest"]}
                # Last writer wins, whichever producer's glob also covers the file.
                for rel, digest in inv.written.items():
                    files[rel] = {"producer": name, "digest": digest}
            history.append({
                "producer": name, "command": list(inv.producer.command), "exit_code": inv.exit_code,
                "source": source, "run_id": run_id, "phase_alias": phase, "recorded_at": now,
            })
        record = {
            "schema": RECORD_SCHEMA,
            "head": head,
            "phase": phase,
            "declaration_sha256": self.declaration.sha256,
            "invocations": history,
            "files": dict(sorted(files.items())),
        }
        from .runtime_paths import ensure_phase_loop_excluded

        path = self.repo / RECORD_RELPATH
        path.parent.mkdir(parents=True, exist_ok=True)
        ensure_phase_loop_excluded(self.repo)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        return record


def _valid_entry(entry: object) -> bool:
    return (
        isinstance(entry, dict)
        and isinstance(entry.get("producer"), str)
        and isinstance(entry.get("digest"), str)
    )


def load_record(repo: Path) -> dict[str, Any] | None:
    """The persisted record, or None. Malformed entries are dropped (treated as
    absent, so the file they name blocks) rather than crashing a reader."""

    try:
        data = json.loads((Path(repo) / RECORD_RELPATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema") != RECORD_SCHEMA:
        return None
    if not isinstance(data.get("files"), dict) or not isinstance(data.get("head"), str):
        return None
    if not isinstance(data.get("phase"), str):
        return None
    data["files"] = {rel: e for rel, e in data["files"].items() if isinstance(rel, str) and _valid_entry(e)}
    if not isinstance(data.get("invocations"), list):
        data["invocations"] = []
    return data


DEFAULT_PRODUCER_TIMEOUT_S = 1200.0
DISPLACED_KEEP = 5


def producer_timeout(value: object = None) -> float:
    """A finite, positive per-producer timeout in seconds.

    ``value`` (else ``PHASE_LOOP_VERIFY_TIMEOUT_SECONDS``, else 1200). Zero, a
    negative number, NaN, infinity or garbage would mean "no bound" or "fail at
    once", so it is refused in favour of the default, with a warning.
    """

    raw = os.environ.get("PHASE_LOOP_VERIFY_TIMEOUT_SECONDS") if value is None else value
    if raw is None or raw == "":
        return DEFAULT_PRODUCER_TIMEOUT_S
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        seconds = float("nan")
    if not math.isfinite(seconds) or seconds <= 0:
        print(
            f"closeout-audit: ignoring invalid producer timeout {raw!r}; "
            f"using {DEFAULT_PRODUCER_TIMEOUT_S:g}s",
            flush=True,
        )
        return DEFAULT_PRODUCER_TIMEOUT_S
    return seconds


def _run_bounded(argv: list[str], cwd: Path, timeout_s: float | None, name: str) -> int:
    """Run one producer in its OWN process group; on timeout kill the whole group, so
    a producer that forked (npm -> node -> workers) leaves nothing running."""

    try:
        proc = subprocess.Popen(argv, cwd=cwd, start_new_session=True)
    except OSError as exc:
        print(f"closeout-audit: producer {name} failed: {type(exc).__name__}", flush=True)
        return 127
    try:
        return int(proc.wait(timeout=timeout_s))
    except subprocess.TimeoutExpired:
        print(f"closeout-audit: producer {name} timed out after {timeout_s:g}s; killed", flush=True)
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        proc.wait()
        return 124


def _prune_displaced(repo: Path) -> None:
    """Keep only the newest ``DISPLACED_KEEP`` displacement directories."""

    root = repo / DISPLACED_RELDIR
    try:
        stamps = sorted(entry for entry in root.iterdir() if entry.is_dir() and not entry.is_symlink())
    except OSError:
        return
    for old in stamps[:-DISPLACED_KEEP]:
        shutil.rmtree(old, ignore_errors=True)

DISPLACED_RELDIR = ".phase-loop/generated-outputs/displaced"


def _ignored_declared_entries(repo: Path, producers: Sequence[Producer]) -> list[str] | None:
    """Every IGNORED, untracked entry (file or symlink) the producers' globs cover.

    Asked of git, so a tracked file, or an untracked-but-not-ignored one (which is
    ownership-contract dirt, not generated output), is never moved. None means the
    probe failed.
    """

    roots = sorted({_literal_root(glob) for p in producers for glob in p.outputs})
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "--literal-pathspecs", "ls-files", "-z", "--others",
             "--ignored", "--exclude-standard", "--", *roots],
            capture_output=True, check=False,
        )
    except OSError:
        return None
    if out.returncode != 0:
        return None
    try:
        listed = [entry for entry in out.stdout.decode("utf-8").split("\0") if entry]
    except UnicodeDecodeError:
        return None
    return sorted(
        rel for rel in listed
        if any(glob_matches(glob, rel) for p in producers for glob in p.outputs)
    )


def displace_declared_outputs(repo: Path, producers: Sequence[Producer]) -> Path | None:
    """Move every existing declared output aside before a clean, observed rebuild.

    After this, everything the producers leave under their globs was CREATED by an
    observed invocation, so a byte-identical regeneration earns provenance and a
    planted or orphaned file cannot ride along. The files are moved, not deleted, to a
    timestamped directory under ``.phase-loop/generated-outputs/displaced/`` (runner
    state), from which an operator can restore anything they meant to keep. Only the
    newest ``DISPLACED_KEEP`` such directories are kept.
    """

    entries = _ignored_declared_entries(repo, producers)
    if entries is None:
        raise DeclarationError("could not list the existing declared outputs to move aside")
    if not entries:
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target_root = repo / DISPLACED_RELDIR / stamp
    for rel in entries:
        target = target_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        os.rename(repo / rel, target)
    _prune_displaced(repo)
    return target_root



def run_declared_producers(
    repo: Path, timeout_s: float | None = None, phase: str | None = None
) -> dict[str, Any] | None:
    """``--record-outputs``: a clean, observed rebuild of the declared outputs.

    Existing declared outputs are first moved aside (``displace_declared_outputs``),
    then every declared producer runs under observation, then the record is written.
    Returns None when HEAD declares nothing (a no-op, so the flag is safe to pass
    in every repo). Each producer is bounded by ``timeout_s``, defaulting to
    ``PHASE_LOOP_VERIFY_TIMEOUT_SECONDS`` like the runner's verification; a producer
    that times out counts as failed.
    """

    recorder = ProducerRecorder.for_repo(repo)
    if recorder is None:
        return None
    timeout_s = producer_timeout(timeout_s)
    from .runtime_paths import ensure_phase_loop_excluded

    ensure_phase_loop_excluded(repo)
    displaced = displace_declared_outputs(repo, recorder.declaration.producers)  # raises: exit 2
    if displaced is not None:
        print(f"closeout-audit: moved existing declared outputs aside to {displaced}", flush=True)
    for producer in recorder.declaration.producers:
        print(f"closeout-audit: running producer {producer.name}: {shlex.join(producer.command)}", flush=True)
        recorder.run(producer, timeout_s)
    record = recorder.write(source="closeout-audit", run_id=None, phase_alias=phase)
    for error in recorder.errors:
        print(f"closeout-audit: recording problem: {error}", flush=True)
    return record


# --- verification of one ignored file ---------------------------------------


@dataclass(frozen=True)
class AuditContext:
    """Facts resolved ONCE per audit, not once per file."""

    declaration: Declaration | None
    record: Mapping[str, Any] | None
    head: str | None
    phase: str | None

    @classmethod
    def for_repo(cls, repo: Path, phase: str | None = None) -> "AuditContext":
        declaration = load_declaration(repo)
        return cls(
            declaration=declaration,
            record=load_record(repo) if declaration is not None else None,
            head=head_commit(repo),
            phase=current_phase(phase),
        )


def verify_declared_output(repo: Path, relpath: str, context: AuditContext) -> tuple[bool, str]:
    declaration, record = context.declaration, context.record
    if declaration is None:
        return False, "no recognised producer"
    covering = {p.name for p in declaration.producers if p.covers(relpath)}
    if not covering:
        return False, "no recognised producer (not covered by a declared output glob)"
    hint = "run `phase-loop-closeout-audit --repo . --record-outputs`"
    if record is None:
        return False, f"declared output with no producer record; {hint}"
    if record.get("declaration_sha256") != declaration.sha256:
        return False, f"producer record predates the committed declaration; {hint}"
    if context.head is None or record.get("head") != context.head:
        return False, f"producer record was taken at a different commit; {hint}"
    if context.phase is None:
        return False, (
            "no phase identity to check the record against (run under the phase-loop runner, "
            "or pass --phase ALIAS)"
        )
    if record.get("phase") != context.phase:
        return False, (
            f"producer record belongs to phase {record.get('phase')!r}, not {context.phase!r}; {hint}"
        )
    entry = record["files"].get(relpath)
    if entry is None or entry["producer"] not in covering:
        return False, (
            "declared output no recorded producer invocation wrote; "
            "remove it, or re-record if a producer should have written it"
        )
    identity = file_identity(repo, relpath)
    if identity is None:
        return False, "declared output is not a regular in-repo file (symlink or symlinked path)"
    if identity[0] != entry["digest"]:
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
    # Every component must be a real directory inside the repo: a symlinked
    # `.dev-skills` would let a file elsewhere borrow the marker.
    st = _regular_file_in_repo(repo, relpath)
    if st is None:
        return False, "handoff is not a regular file inside the repo"
    if st.st_size > _HANDOFF_MAX_BYTES:
        return False, "handoff exceeds size limit"
    try:
        text = (repo / relpath).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False, "handoff unreadable"
    front = parse_frontmatter_document(text)
    missing = [key for key in HANDOFF_REQUIRED_KEYS if front.get(key) in (None, "")]
    if missing:
        return False, f"handoff frontmatter missing {', '.join(missing)}"
    if str(front.get("from")) != skill:
        return False, f"handoff `from` does not match its directory {skill!r}"
    # Bound to THIS repo: a handoff copied from another checkout names another root,
    # and one from another repository names a commit this one does not have.
    try:
        if Path(str(front.get("repo_root"))).expanduser().resolve() != Path(repo).resolve():
            return False, "handoff `repo_root` is not this repository"
    except (OSError, RuntimeError):
        return False, "handoff `repo_root` does not resolve"
    # Read the raw scalar: YAML turns an all-digit short sha into an integer.
    end = text.find("\n---", 4)
    frontmatter = text[4:end] if text.startswith("---\n") and end != -1 else ""
    match = re.search(r"^commit:\s*['\"]?([0-9a-fA-F]{4,64})['\"]?\s*$", frontmatter, re.MULTILINE)
    if match is None or not _commit_exists(repo, match.group(1)):
        return False, "handoff `commit` is not a commit in this repository"
    return True, f"harness handoff written by {skill}"


def _commit_exists(repo: Path, sha: str) -> bool:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "cat-file", "-e", f"{sha}^{{commit}}"],
            capture_output=True, check=False,
        )
    except OSError:
        return False
    return out.returncode == 0
