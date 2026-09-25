"""Staged review trees for board seats, and the digest that attests them.

Until now the staged review dir held only ``review-bundle.md`` and
``review-instructions.md``, so a seat could not open the code under review and every
fact it might need had to be inlined into the bundle -- the pressure behind 200-340 KiB
bundles against the 512 KiB transport cap (agent-harness#848).

**Scope, stated plainly.** This module materializes and attests a staged tree. It does
NOT yet deliver that tree to a brokered seat. The ``bwrap --unshare-all --clearenv``
child in ``advisor_board/backing.py`` is a fixed parent-generated posture probe, not a
seat: the seats run in the PARENT via ``_parent_infer``/``_exec_leg``, where brokered
codex is launched with ``--cd <out_dir>`` and brokered gemini drops ``--add-dir``
entirely. Neither argv, nor the broker prompt, nor ``review-instructions.md`` names this
tree. Wiring that delivery changes the attested provider argv and is deliberately not
done here (ah#890 board round 1, fable seat).

Two rules shape this module:

* **A stage is a copy, never the live tree.** It excludes ``.git`` entirely, so no
  live gitdir and no shared object alternates can be reached through it, and it
  refuses any symlink that leaves the source tree. A seat's write can only ever
  land on the copy.
* **What the seat read is attested.** :func:`review_tree_manifest_sha256` binds the
  path set AND the bytes, so a tree swapped between authorization and launch fails
  closed instead of being reviewed silently.

This module deliberately imports nothing from ``advisor_board`` or ``launcher``:
``launcher`` already imports ``advisor_board``, so a helper either of them could
import must sit below both. ``launcher._stage_review_tree`` implements the same
selection for the product-loop review action; converging the two is tracked
separately, because ``launcher.py`` belongs to an executing phase lane.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib.metadata
import json
import os
import re
import selectors
import secrets
import shutil
import signal
import stat
import subprocess
import tempfile
import time
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import Requirement

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 floor
    import tomli as tomllib

__all__ = [
    "REVIEW_STAGE_DIR_PREFIX",
    "review_tree_paths",
    "review_tree_manifest_sha256",
    "revalidate_falsifier_staged_tree",
    "run_bounded_falsifier_node",
    "stage_review_tree",
    "remove_review_stage",
    "staged_source_commit",
    "is_stale",
    "CLONE_DEPTH",
    "REVIEW_STAGE_TREE_DIRNAME",
]

REVIEW_STAGE_DIR_PREFIX = "pl-panel-stage-"

# Fixed name of the staged tree INSIDE the authorized staged dir. Fixed, not
# caller-chosen, so the authorization's digest and the validator refer to the same
# path by construction -- a caller-supplied name could point the check at one
# directory while the seat reads another.
REVIEW_STAGE_TREE_DIRNAME = "reviewed-tree"

# The stage is WRITABLE on purpose: a panelist has to be able to run tests in it, and
# pytest writes caches before it does anything. Cleanup still restores modes on the way
# down, because a panelist may create read-only directories of its own.


def review_tree_paths(repo: Path) -> list[str] | None:
    """Repo-relative paths a reviewer should see: tracked, plus untracked-but-not-ignored.

    ``None`` when ``repo`` is not a git checkout or git is unavailable, so the
    caller can fall back to a contained full copy.
    """
    try:
        tracked = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "-z"],
            capture_output=True, text=True, check=False,
        )
        if tracked.returncode != 0:
            return None
        untracked = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "-z", "--others", "--exclude-standard"],
            capture_output=True, text=True, check=False,
        )
        if untracked.returncode != 0:
            return None
    except OSError:
        return None
    seen: set[str] = set()
    for chunk in (tracked.stdout, untracked.stdout):
        for rel in chunk.split("\0"):
            if rel:
                seen.add(rel)
    return sorted(seen)


def _refuse_escaping_symlinks(repo: Path, root: Path) -> None:
    """Fail closed on any symlink that could leave the tree, at any mount point.

    Containment is decided TEXTUALLY on the link target rather than by resolving it:
    an absolute target is refused, and a relative target may never traverse above the
    tree root. A textual rule is relocation invariant, so the verdict does not change
    when the stage is bind-mounted at ``/run/phase-loop-review/reviewed-tree``, and it
    does not depend on resolving through intermediate symlinks (each of which is itself
    checked by this same pass, so the whole link graph is covered inductively).

    Note a target that leaves and RE-ENTERS the tree -- e.g.
    ``proc/sys/kernel/leak -> ../../../proc/sys/kernel/hostname`` from three levels down
    -- normalizes back inside and is allowed: ``../../../`` lands exactly on the root,
    not above it. It is in-tree under any mount point. A real escape needs more ``..``
    components than the link's depth.
    """
    # Scoped to the SELECTED paths, not the whole tree. Walking `rglob` scanned
    # gitignored paths that staging would never copy, so an ordinary `.venv/bin/python
    # -> /usr/bin/python3` (absolute, ignored, never staged) refused the entire stage and
    # degraded every seat in the round -- on this repo, which gitignores `.venv`.
    for rel in _selected_paths(repo):
        candidate = repo / rel
        if not candidate.is_symlink():
            continue
        target = os.readlink(candidate)
        if Path(target).is_absolute():
            raise ValueError(f"review staging refuses absolute symlink: {candidate}")
        rel_dir = candidate.parent.relative_to(root)
        normalized = os.path.normpath(os.path.join(str(rel_dir), target))
        if normalized == ".." or normalized.startswith(".." + os.sep):
            raise ValueError(
                f"review staging refuses symlink escaping source tree: {candidate}"
                f" -> {target} (normalizes to {normalized})"
            )
        # Belt and braces: also refuse anything that RESOLVES outside. The two rules
        # catch different things and the board split on which to keep, so both are
        # applied. Lexical is relocation invariant and does not read the filesystem;
        # resolution catches a target reached through an intermediate symlink. A
        # dangling in-tree link is fine -- the stage is a partial copy by design, so
        # absence is expected and is not an escape.
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(
                f"review staging refuses symlink escaping source tree: {candidate}"
                f" -> {target} (resolves to {resolved})"
            ) from exc


def is_review_stage(root: Path) -> bool:
    """Is this directory a stage this runtime produced, rather than a source repo?

    Keyed on the marker `stage_review_tree` writes into the clone's own gitdir, so it
    cannot be confused with an ordinary checkout that happens to sit under the same root.
    """
    return (Path(root) / ".git" / "phase-loop-source-commit").is_file()


def _selected_paths(root: Path) -> list[str]:
    """The path set to hash, on EITHER side of the copy.

    A stage has no ``.git``, so ``review_tree_paths`` returns ``None`` there and the
    walk below is used. The source uses git selection. Both must therefore agree on a
    faithful copy, which means only MATERIALIZED files may be hashed: a tracked file
    deleted from the working tree is listed by ``git ls-files`` but cannot exist in the
    stage, and hashing it on one side only made an honest tree fail validation.
    Dropping it loses nothing -- a deletion still removes the path from the set, which
    still moves the digest.
    """
    # A REVIEW STAGE is enumerated from the FILESYSTEM, never from git. This docstring
    # used to say "a stage has no `.git`, so the walk below is used" -- true when staging
    # was a file copy, false since it became a git CLONE. The clone's index describes the
    # COMMIT, so anything staged that git would not list there is silently dropped from
    # the digest: board round 11, codex, a force-added file matching an ignore rule
    # reached the stage correctly and then failed revalidation because only the SOURCE
    # side counted it. The premise went stale under a change three rounds earlier.
    rel_paths = None if is_review_stage(root) else review_tree_paths(root)
    if rel_paths is None:
        rel_paths = [
            str(p.relative_to(root))
            for p in root.rglob("*")
            if (p.is_file() or p.is_symlink()) and ".git" not in p.relative_to(root).parts
        ]
    return sorted(
        rel for rel in rel_paths
        if (root / rel).is_symlink() or (root / rel).is_file()
    )


def review_tree_manifest_sha256(root: Path) -> str:
    """Digest binding the reviewed PATH SET and its BYTES.

    Both halves matter: hashing content alone would let a rename pass unnoticed, and
    hashing paths alone would let a length-preserving edit pass.

    **Every field is fixed width.** A delimited record such as
    ``blob <sha> <len> <path>\n`` is NOT injective, because a path may contain a
    newline (git permits it and ``ls-files -z`` preserves it), so a single file named
    ``"a\nblob <sha-of-empty> 0 b"`` serialized byte-identically to two empty files
    ``a`` and ``b``. Hashing the path instead of embedding it makes every record the
    same length, so the concatenation can be parsed exactly one way.

    Symlinks are recorded by their target text rather than followed, so a stage cannot
    be made to hash like its source by pointing at different bytes.
    """
    root = Path(root).resolve(strict=True)
    digest = hashlib.sha256()
    for rel in _selected_paths(root):
        target = root / rel
        if target.is_symlink():
            payload = os.readlink(target).encode("utf-8")
            kind = b"link"
        else:
            payload = target.read_bytes()
            kind = b"blob"
        # The EXECUTABLE BIT is execution-relevant state, so it belongs in the digest.
        # Without it a stage that silently dropped `chmod +x` still matched the source and
        # the authorization accepted it -- the reviewer got a script it could not run and
        # nothing said so (board round 9, codex). One bit, fixed width, and a mode change
        # now moves the digest instead of hiding inside it. Only the executable bit: the
        # rest of the mode is noise that would make the digest depend on umask.
        executable = b"1" if (not target.is_symlink() and os.access(target, os.X_OK)) else b"0"
        digest.update(
            kind                                                    # 4 bytes, fixed
            + executable                                            # 1 byte, fixed
            + hashlib.sha256(payload).hexdigest().encode("ascii")   # 64 bytes, fixed
            + b"%020d" % len(payload)                               # 20 bytes, fixed
            + hashlib.sha256(rel.encode("utf-8")).hexdigest().encode("ascii")  # 64, fixed
        )
    return digest.hexdigest()


def revalidate_falsifier_staged_tree(*, staged: Path, reviewed_sha: str) -> None:
    """Refuse any materialized stage path or byte absent from the reviewed Git tree."""
    staged = Path(staged).resolve(strict=True)
    if _git(staged, "rev-parse", "HEAD").strip() != reviewed_sha:
        raise ValueError("falsifier staged HEAD differs from reviewed SHA")
    object_format = _git(staged, "rev-parse", "--show-object-format").strip()
    if object_format not in ("sha1", "sha256"):
        raise ValueError("unsupported falsifier Git object format")
    tree = subprocess.run(
        ["git", "-C", str(staged), "ls-tree", "-rz", "--full-tree", reviewed_sha],
        capture_output=True, check=True,
    ).stdout
    expected: dict[str, tuple[str, str]] = {}
    for entry in tree.split(b"\0"):
        if not entry:
            continue
        header, raw_path = entry.split(b"\t", 1)
        mode, kind, oid = header.decode("ascii").split(" ")
        path = raw_path.decode("utf-8", "surrogateescape")
        if kind != "blob" or mode not in ("100644", "100755", "120000"):
            raise ValueError("unsupported falsifier Git tree entry")
        expected[path] = (mode, oid)
    observed: set[str] = set()
    for directory, dirs, files in os.walk(staged, topdown=True, followlinks=False):
        current = Path(directory)
        if current == staged and ".git" in dirs:
            dirs.remove(".git")
        for name in list(dirs):
            if (current / name).is_symlink():
                dirs.remove(name)
                files.append(name)
        for name in files:
            target = current / name
            rel = target.relative_to(staged).as_posix()
            observed.add(rel)
            if rel not in expected:
                raise ValueError("falsifier staged tree has an extra path")
            mode, oid = expected[rel]
            if target.is_symlink():
                if mode != "120000":
                    raise ValueError("falsifier staged file became a symlink")
                payload = os.readlink(target).encode("utf-8", "surrogateescape")
            elif target.is_file():
                actual_mode = "100755" if os.access(target, os.X_OK) else "100644"
                if actual_mode != mode:
                    raise ValueError("falsifier staged executable bit changed")
                payload = target.read_bytes()
            else:
                raise ValueError("falsifier staged path is not a regular file")
            blob = b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload
            if hashlib.new(object_format, blob).hexdigest() != oid:
                raise ValueError("falsifier staged bytes differ from reviewed Git tree")
    if observed != expected.keys():
        raise ValueError("falsifier staged tree is missing reviewed paths")


def _snapshot_falsifier_dependencies(stage: Path, destination: Path) -> None:
    """Copy only installed distribution-owned files into a disposable import root."""
    inventory = subprocess.run(
        ["/usr/bin/python3", "-c",
         "import json,sys; print(json.dumps({'paths':sys.path, "
         "'version':list(sys.version_info[:3])}))"],
        capture_output=True, text=True, check=True, timeout=3,
        env={"HOME": str(Path.home()), "PATH": "/usr/bin:/bin"},
    )
    interpreter = json.loads(inventory.stdout)
    paths = [path for path in interpreter["paths"] if isinstance(path, str) and path.startswith("/")]
    version = interpreter["version"]
    marker_environment = default_environment()
    marker_environment["python_version"] = f"{version[0]}.{version[1]}"
    marker_environment["python_full_version"] = ".".join(map(str, version))
    marker_environment["extra"] = ""
    available: dict[str, importlib.metadata.Distribution] = {}
    for distribution in importlib.metadata.distributions(path=paths):
        declared_name = distribution.metadata.get("Name")
        if declared_name:
            available.setdefault(re.sub(r"[-_.]+", "-", declared_name).lower(), distribution)
    requirements = ["pytest"]
    project = stage / "phase-loop-runtime" / "pyproject.toml"
    if project.is_file():
        payload = tomllib.loads(project.read_text(encoding="utf-8"))
        declared = payload.get("project", {}).get("dependencies", ())
        if not isinstance(declared, list) or not all(isinstance(item, str) for item in declared):
            raise ValueError("falsifier project dependencies are invalid")
        requirements.extend(declared)
    pending = list(requirements)
    seen: set[str] = set()
    copied_bytes = 0
    while pending:
        requirement = Requirement(pending.pop())
        if requirement.marker is not None and not requirement.marker.evaluate(marker_environment):
            continue
        name = re.sub(r"[-_.]+", "-", requirement.name).lower()
        if name in seen:
            continue
        seen.add(name)
        distribution = available.get(name)
        if distribution is None:
            continue  # An unavailable import remains a typed test-run error.
        pending.extend(distribution.requires or ())
        root = Path(distribution.locate_file("")).resolve(strict=True)
        for entry in distribution.files or ():
            parts = entry.parts
            if (not parts or entry.is_absolute() or ".." in parts
                    or "__pycache__" in parts or entry.suffix == ".pth"):
                continue
            if any(part.startswith(".env") or part.endswith((".key", ".pem")) for part in parts):
                continue
            original = Path(distribution.locate_file(entry))
            if original.is_symlink() or not original.is_file():
                continue
            source = original.resolve(strict=True)
            if not source.is_relative_to(root):
                continue
            target = destination.joinpath(*parts)
            if target.exists():
                if target.read_bytes() != source.read_bytes():
                    raise ValueError("falsifier dependency file collision")
                continue
            copied_bytes += source.stat().st_size
            if copied_bytes > 268_435_456:
                raise ValueError("falsifier dependency snapshot exceeds 256 MiB")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)


def run_bounded_falsifier_node(
    *, staged: Path, nodeid: str, wall_clock_s: float, output_cap_bytes: int,
) -> tuple[int | None, bytes, bytes, str | None, dict[str, object] | None]:
    """Run one pytest node in a credentialless, networkless staged-tree mount."""
    stage = Path(staged).resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="pl-falsifier-deps-") as temporary:
        dependencies = Path(temporary)
        _snapshot_falsifier_dependencies(stage, dependencies)
        return _run_bounded_falsifier_node(
            staged=stage, dependencies=dependencies, nodeid=nodeid,
            wall_clock_s=wall_clock_s, output_cap_bytes=output_cap_bytes,
        )


def _run_bounded_falsifier_node(
    *, staged: Path, dependencies: Path, nodeid: str,
    wall_clock_s: float, output_cap_bytes: int,
) -> tuple[int | None, bytes, bytes, str | None, dict[str, object] | None]:
    if wall_clock_s <= 0 or output_cap_bytes <= 0:
        raise ValueError("falsifier bounds must be positive")
    bwrap = Path("/usr/bin/bwrap")
    python = Path("/usr/bin/python3")
    if not bwrap.is_file() or not python.is_file():
        raise ValueError("falsifier requires canonical bwrap and python3")
    stage = Path(staged).resolve(strict=True)
    argv = [str(bwrap), "--unshare-all", "--die-with-parent", "--new-session", "--clearenv"]
    for system_root in ("/usr", "/lib", "/lib64", "/bin"):
        if Path(system_root).exists():
            argv.extend(("--ro-bind", system_root, system_root))
    argv.extend(("--ro-bind", str(dependencies), "/deps"))
    token = secrets.token_hex(24)
    reporting_key = secrets.token_hex(32).encode("ascii")
    # This trusted wrapper reads pytest's call-phase reports before interpreter
    # shutdown. Test-registered atexit handlers never run; a test that aborts the
    # process before pytest returns leaves no completed report and is an error.
    wrapper = (
        "import hashlib,hmac,json,os,pytest,sys\n"
        "def main():\n"
        " secret=sys.stdin.buffer.readline().rstrip(b'\\n')\n"
        " sys.stdin=open('/dev/null')\n"
        " calls=[]\n"
        " class Reporter:\n"
        "  def pytest_runtest_logreport(self, report):\n"
        "   if report.when == 'call':\n"
        "    calls.append({'nodeid': report.nodeid, 'outcome': report.outcome, "
        "'wasxfail': bool(getattr(report, 'wasxfail', False))})\n"
        " code=pytest.main(['-q','-c','/dev/null','--rootdir=/work','-o','addopts=',"
        "'-p','no:cacheprovider','--junitxml=/work/.falsifier-junit.xml',"
        "sys.argv[1]], plugins=[Reporter()])\n"
        " sys.stdout.flush(); sys.stderr.flush()\n"
        " payload=json.dumps({'schema':'falsifier_pytest_report.v1',"
        "'exit':int(code),'calls':calls},separators=(',',':'))\n"
        " signature=hmac.new(secret,payload.encode(),hashlib.sha256).hexdigest()\n"
        " os.write(1, ('\\nFALSIFIER_RESULT::'+sys.argv[2]+':'+signature+':'+payload+'\\n').encode())\n"
        " os._exit(0)\n"
        "main()\n"
    )
    argv.extend((
        "--bind", str(stage), "/work", "--tmpfs", "/tmp", "--proc", "/proc",
        "--dev", "/dev", "--dir", "/home", "--dir", "/home/falsifier",
        "--chdir", "/work", "--setenv", "HOME", "/home/falsifier",
        "--setenv", "PATH", "/usr/bin:/bin", "--setenv", "PYTHONPATH",
        "/work/phase-loop-runtime/src:/work/phase-loop-runtime/tests:/deps",
        "--setenv", "PYTHONNOUSERSITE", "1", "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
        "--setenv", "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1",
        str(python), "-s", "-c", wrapper, nodeid, token,
    ))
    proc = subprocess.Popen(
        argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}, start_new_session=True,
    )
    assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None
    try:
        proc.stdin.write(reporting_key + b"\n")
        proc.stdin.flush()
    except BrokenPipeError:
        pass
    finally:
        proc.stdin.close()
    streams = {proc.stdout: bytearray(), proc.stderr: bytearray()}
    selector = selectors.DefaultSelector()
    for stream in streams:
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ)
    deadline = time.monotonic() + wall_clock_s
    failure: str | None = None
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                failure = "falsifier wall-clock bound expired"
                break
            for key, _ in selector.select(min(remaining, 0.1)):
                chunk = os.read(key.fileobj.fileno(), min(65536, output_cap_bytes + 1))
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                streams[key.fileobj].extend(chunk)
                if sum(len(data) for data in streams.values()) > output_cap_bytes:
                    failure = "falsifier output cap exceeded"
                    break
            if failure:
                break
        if failure is None and proc.poll() is None:
            remaining = deadline - time.monotonic()
            try:
                proc.wait(timeout=max(0, remaining))
            except subprocess.TimeoutExpired:
                failure = "falsifier wall-clock bound expired"
    finally:
        selector.close()
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        proc.wait()
        proc.stdout.close()
        proc.stderr.close()
    stdout = bytes(streams[proc.stdout])
    stderr = bytes(streams[proc.stderr])
    report: dict[str, object] | None = None
    if failure is None and proc.returncode == 0:
        marker = ("\nFALSIFIER_RESULT::" + token + ":").encode()
        if stdout.count(marker) == 1:
            body, framed = stdout.split(marker, 1)
            if framed.endswith(b"\n") and b"\n" not in framed[:-1]:
                try:
                    signature, payload = framed[:-1].split(b":", 1)
                    authenticated = hmac.compare_digest(
                        signature, hmac.new(reporting_key, payload, hashlib.sha256).hexdigest().encode(),
                    )
                    parsed = json.loads(payload) if authenticated else None
                except (UnicodeError, json.JSONDecodeError):
                    parsed = None
                if isinstance(parsed, dict):
                    report = parsed
                    stdout = body
    return proc.returncode, stdout, stderr, failure, report


CLONE_DEPTH = 50


def _git(repo: Path, *args: str, check: bool = True) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=check,
    ).stdout


def staged_source_commit(staged: Path) -> str | None:
    """The commit this sandbox was staged from, or ``None`` if it is not a clone."""
    marker = Path(staged) / ".git" / "phase-loop-source-commit"
    if marker.is_file():
        return marker.read_text(encoding="utf-8").strip() or None
    return None


def is_stale(staged: Path, source: Path) -> bool:
    """Has the source moved since this sandbox was staged?

    Resuming a sandbox against code that has changed underneath it is not a cosmetic
    problem: the panelist reports on lines that no longer exist, with citations, and
    nothing in its output signals that it is out of date.
    """
    recorded = staged_source_commit(staged)
    if recorded is None:
        return False
    try:
        current = _git(Path(source), "rev-parse", "HEAD").strip()
    except (OSError, subprocess.SubprocessError):
        return False
    return bool(current) and current != recorded


def stage_review_tree(repo: Path, parent: Path | None = None) -> Path:
    """Materialize a writable, independent shallow clone of ``repo`` for a review seat.

    A clone rather than a copy, so a panelist can run ``git log``/``blame``/``diff`` --
    the cheapest way to answer "when did this change and why". Depth is bounded
    (:data:`CLONE_DEPTH`) because full history costs ~8x more for history a review will
    not read.

    Independent by construction: cloned from a ``file://`` URL, which forces a real object
    copy. A plain path clone would hardlink into the source object store, and ``--shared``
    or a linked worktree would leave the sandbox resolving objects through the LIVE gitdir
    -- at which point it is not a copy at all.

    The clone lands at the source's HEAD, so the working tree is then overlaid: a reviewer
    is shown the working tree, and a sandbox that silently showed the last commit instead
    would have the panelist review code nobody proposed.

    Writable on purpose. ``pytest`` writes caches before it does anything, so a read-only
    tree cannot host the test run this sandbox exists for.
    """
    root = Path(repo).resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"review root is not a directory: {repo}")

    parent = Path(parent) if parent is not None else Path(tempfile.gettempdir())
    parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix=REVIEW_STAGE_DIR_PREFIX, dir=str(parent)))

    try:
        _refuse_escaping_symlinks(root, root)
        head = _git(root, "rev-parse", "HEAD", check=False).strip()
        if not head:
            # Not a git checkout (or no commits yet): fall back to a contained copy so a
            # non-git tree is still reviewable, just without history.
            _copy_selected(root, staged)
            return staged

        subprocess.run(
            ["git", "clone", "--quiet", "--depth", str(CLONE_DEPTH), "--no-single-branch",
             f"file://{root}", str(staged)],
            capture_output=True, text=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(staged), "checkout", "--quiet", "--detach", head],
            capture_output=True, text=True, check=False,
        )
        _overlay_working_tree(root, staged)
        # Inside `.git` on purpose: the marker describes the clone, and anything in the
        # tree itself would be hashed into the manifest and break source/stage equality.
        (staged / ".git" / "phase-loop-source-commit").write_text(head + "\n", encoding="utf-8")
    except Exception:
        remove_review_stage(staged)
        raise
    return staged


def _copy_selected(root: Path, staged: Path) -> None:
    """Copy the selected paths verbatim (the no-git fallback)."""
    for rel in _selected_paths(root):
        source = root / rel
        destination = staged / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_symlink():
            if destination.is_symlink() or destination.exists():
                destination.unlink()
            os.symlink(os.readlink(source), destination)
        else:
            # Same class as `_overlay_working_tree`: never follow a destination link.
            if destination.is_symlink():
                destination.unlink()
            shutil.copy2(source, destination)


def _overlay_working_tree(root: Path, staged: Path) -> None:
    """Make the clone match the source's WORKING TREE, not just its last commit.

    Three kinds of divergence, all of which a reviewer is shown and a bare clone would
    hide: modified tracked files, tracked files deleted but not yet committed, and
    untracked-but-not-ignored additions.
    """
    selected = set(_selected_paths(root))

    # `-z`, like the source side. Plain `ls-files` QUOTES any name containing a tab or a
    # newline (`"docs\there"`), so the clone set and the source set spelled the same path
    # differently -- stale removal looked for the quoted form, missed the real entry, and
    # left a committed symlink standing for the overlay to write through. Board round 8,
    # codex; reproduced with a tabbed directory name (agent-harness#890).
    tracked_in_clone = {
        rel for rel in _git(staged, "ls-files", "-z", check=False).split("\0") if rel
    }
    for rel in tracked_in_clone - selected:
        stale_path = staged / rel
        if stale_path.is_file() or stale_path.is_symlink():
            stale_path.unlink()

    # A committed DIRECTORY replaced by a regular file in the working tree. Stale removal
    # above unlinks files and leaves their directories, so `slot/` survived and
    # `copy2(source, staged/"slot")` wrote `slot/slot` -- the staged tree diverged from
    # the source and the leg refused its own faithful copy (board round 11, codex;
    # reproduced). Clear a destination whose TYPE no longer matches the source.
    for rel in selected:
        source, destination = root / rel, staged / rel
        if destination.is_dir() and not destination.is_symlink() and not source.is_dir():
            shutil.rmtree(destination)

    stage_root = staged.resolve()
    for rel in selected:
        source = root / rel
        destination = staged / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        # CONTAINMENT, checked on the RESOLVED parent. Unlinking a symlink at the LEAF is
        # not enough: the escape can sit at any ANCESTOR. A committed directory symlink
        # pointing outside is recreated by the clone, `mkdir(exist_ok=True)` happily
        # accepts it, the leaf check sees an ordinary name, and `copy2` writes through it
        # to wherever the ancestor points. Resolving the parent catches every spelling and
        # every depth at once, instead of another special case per shape.
        resolved_parent = destination.parent.resolve()
        if resolved_parent != stage_root and stage_root not in resolved_parent.parents:
            raise ValueError(
                f"refusing to stage {rel!r}: its destination resolves outside the "
                f"sandbox ({resolved_parent}). A committed symlink is pointing out of "
                "the tree."
            )
        if source.is_symlink():
            if destination.is_symlink() or destination.exists():
                destination.unlink()
            os.symlink(os.readlink(source), destination)
        elif source.is_file():
            # NEVER write THROUGH a destination symlink. The clone recreates whatever the
            # COMMIT held, so a committed symlink pointing outside the repo can still be
            # sitting at `destination` when the working tree has since replaced it with a
            # regular file. `_refuse_escaping_symlinks` inspects the SOURCE, where the
            # symlink no longer exists, so it accepts -- and `shutil.copy2` then follows
            # the destination link and overwrites the victim with the parent's
            # permissions. Demonstrated on agent-harness#890 board round 5: staging wrote
            # outside the clone, before any reviewer acted.
            #
            # `is_symlink()` MUST be tested before `is_file()`, which follows links: the
            # content short-circuit below would otherwise compare the VICTIM's bytes.
            if destination.is_symlink():
                destination.unlink()
            elif destination.is_file() and destination.read_bytes() == source.read_bytes():
                # Bytes match, so the CONTENT copy is unnecessary -- but `copy2` also
                # carries the MODE, and skipping it dropped an executable bit the working
                # tree had and the commit did not. Board round 9, codex; reproduced:
                #
                #     source mode 0o755 executable      staged mode 0o664 NOT executable
                #     ./check.sh -> PermissionError
                #
                # A reviewer could not run a script its author can, in a sandbox whose
                # whole purpose is "form a hypothesis and RUN it". Copy the mode anyway.
                shutil.copymode(source, destination)
                continue
            shutil.copy2(source, destination)


def remove_review_stage(staged: Path) -> None:
    """Remove a stage created by :func:`stage_review_tree`.

    Walk iteratively through directory descriptors so a seat-created deep tree
    cannot exceed Python's recursion limit or escape through a symlink.

    Never raises: cleanup runs on failure paths, where losing the original error to
    a cleanup error would be worse. Callers that need proof of removal must check
    the path after this best-effort operation.
    """
    staged = Path(staged)
    try:
        mode = staged.lstat().st_mode
    except OSError:
        return
    if not stat.S_ISDIR(mode):
        try:
            staged.unlink()
        except OSError:
            pass
        return

    if not (hasattr(os, "O_DIRECTORY") and hasattr(os, "O_NOFOLLOW")
            and os.open in os.supports_dir_fd):
        for path in sorted(staged.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if not path.is_symlink():
                try:
                    path.chmod(0o700)
                except OSError:
                    pass
        try:
            staged.chmod(0o700)
        except OSError:
            pass
        shutil.rmtree(staged, ignore_errors=True)
        return

    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    anchor: int | None = None
    current: int | None = None

    def open_relative(parts: tuple[str, ...]) -> int:
        assert anchor is not None
        fd = os.dup(anchor)
        try:
            for part in parts:
                child = os.open(part, flags, dir_fd=fd)
                os.close(fd)
                fd = child
            return fd
        except OSError:
            os.close(fd)
            raise

    try:
        # The isolated child has exited before cleanup, so it cannot swap the root.
        staged.chmod(0o700)
        anchor = os.open(staged, flags)
        os.fchmod(anchor, 0o700)
        current = os.dup(anchor)
        stack: list[tuple[tuple[str, ...], list[str]]] = [
            ((), os.listdir(current)),
        ]
        while stack:
            parts, names = stack[-1]
            if names:
                name = names.pop()
                try:
                    child_mode = os.stat(name, dir_fd=current, follow_symlinks=False).st_mode
                except FileNotFoundError:
                    continue
                if stat.S_ISDIR(child_mode):
                    try:
                        child = os.open(name, flags, dir_fd=current)
                    except PermissionError:
                        os.chmod(name, 0o700, dir_fd=current)
                        child = os.open(name, flags, dir_fd=current)
                    os.fchmod(child, 0o700)
                    os.close(current)
                    current = child
                    stack.append((parts + (name,), os.listdir(current)))
                else:
                    os.unlink(name, dir_fd=current)
                continue
            os.close(current)
            current = None
            stack.pop()
            if stack:
                current = open_relative(stack[-1][0])
                os.rmdir(parts[-1], dir_fd=current)
        os.close(anchor)
        anchor = None
        staged.rmdir()
    except OSError:
        pass
    finally:
        if current is not None:
            os.close(current)
        if anchor is not None:
            os.close(anchor)
