"""GATE (roadmap v40) — sensitivity classifier for beyond-ownership dirty paths.

`classify_unowned_path(repo_relpath)` maps a repo-relative path to a
``SensitivityVerdict`` whose ``sensitivity_class`` is a member of
``models.SENSITIVITY_CLASSES``. The graduated closeout gate auto-commits a
verified beyond-ownership path only when its verdict is ``safe``; everything else
blocks (deny-by-default).

Precedence is load-bearing and deny-by-default:
  1. UNSAFE-specific patterns first — secrets, lockfiles, CI config. These must win
     over any broad SAFE rule (e.g. a ``.github/workflows/*.yml`` is CI, not docs).
  2. tests → ``source`` (UNSAFE). Test paths only ever earn owned status via
     structural sibling matching upstream; a test reaching this classifier failed
     that and must not auto-commit.
  3. narrow SAFE rules — plans, handoffs, docs, and a *tight* config_nonsource
     allowlist (never a ``.toml``/``.yaml``/``.json`` suffix rule).
  4. fall through → ``source`` (UNSAFE). Unmatched is never SAFE.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .models import SAFE_SENSITIVITY_CLASSES
from . import generated_outputs
from .runtime_paths import EXCLUDE_ENTRIES


@dataclass(frozen=True)
class SensitivityVerdict:
    sensitivity_class: str
    safe: bool


# Tight allowlists — membership, not broad suffix rules.
_CONFIG_NONSOURCE_NAMES = frozenset(
    {".gitignore", ".gitattributes", ".editorconfig", ".dockerignore", ".npmrc", ".prettierrc"}
)
_CONFIG_NONSOURCE_SUFFIXES = frozenset({".cfg", ".ini"})

_SECRET_SUFFIXES = frozenset({".pem", ".key", ".p12", ".pfx", ".crt", ".keystore", ".jks"})
_LOCKFILE_NAMES = frozenset(
    {
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "uv.lock",
        "poetry.lock",
        "cargo.lock",
        "go.sum",
        "gemfile.lock",
        "composer.lock",
        "requirements.txt",
    }
)
# Bare suffix → docs only for unambiguous documentation formats. A `.txt` is NOT
# auto-docs (e.g. src/foo.txt is source-adjacent); it is docs only under docs/.
_DOC_SUFFIXES = frozenset({".md", ".rst"})


def _verdict(sensitivity_class: str) -> SensitivityVerdict:
    return SensitivityVerdict(
        sensitivity_class=sensitivity_class,
        safe=sensitivity_class in SAFE_SENSITIVITY_CLASSES,
    )


def classify_unowned_path(repo_relpath: str) -> SensitivityVerdict:
    raw = (repo_relpath or "").strip()
    # Normalize: strip leading "./", lowercase for matching.
    norm = raw[2:] if raw.startswith("./") else raw
    lower = norm.lower()
    posix = PurePosixPath(lower)
    name = posix.name
    suffix = posix.suffix
    parts = posix.parts
    slashed = "/" + lower  # so "/tests/" infix matches a leading "tests/" too

    # --- 1. UNSAFE-specific patterns first (precedence) ---
    # secrets
    if (
        name == ".env"
        or name.startswith(".env.")
        or suffix in _SECRET_SUFFIXES
        or "secrets" in parts
    ):
        return _verdict("secrets")
    # lockfiles
    if name in _LOCKFILE_NAMES or name.endswith(".lock") or name.endswith("-lock.json"):
        return _verdict("lockfile")
    # CI config
    if (
        any(part in {".github", ".gitlab", ".circleci", ".gitea"} for part in parts)
        or lower.startswith("ci/")
        or "/workflows/" in slashed
    ):
        return _verdict("ci")
    # tests → source (UNSAFE) — GATE decision (see plan/IF-0-GATE-1)
    if (
        "/tests/" in slashed
        or "__tests__" in parts
        or "__fixtures__" in parts
        or name.startswith("test_")
        or name.endswith("_test.py")
        or ".test." in name
        or ".spec." in name
    ):
        return _verdict("source")

    # --- 2. narrow SAFE rules ---
    if lower.startswith("plans/"):
        return _verdict("plans")
    if ".dev-skills/handoffs/" in slashed:
        return _verdict("handoffs")
    if "/docs/" in slashed or name == "readme.md" or suffix in _DOC_SUFFIXES:
        return _verdict("docs")
    if name in _CONFIG_NONSOURCE_NAMES or suffix in _CONFIG_NONSOURCE_SUFFIXES:
        return _verdict("config_nonsource")

    # --- 3. deny-by-default: everything else (incl. .py/.toml/.yaml/.json/.sh) ---
    return _verdict("source")


# --- ah#670: typed provenance for IGNORED outputs -------------------------
#
# Distinct from `classify_unowned_path` above, which grades TRACKED beyond-
# ownership paths. This grades paths git already considers ignored, answering a
# different question: did the governed command itself produce this, or did
# something unaccounted-for appear?
#
# The defect it closes: an executor, following the closeout audit contract
# literally, reported `dirty_worktree_conflict` for `.phase-loop/**`,
# `.ruff_cache/`, `.pytest_cache/` and `.venv/` -- outputs the runner and its own
# verification step had just created -- while its 13-file tracked diff was fully
# owned and verified. Blocking on artifacts the governed command produces is a
# loop: the repair turn re-runs the command and recreates them.

RUNNER_OWNED = "runner_owned"
TOOL_CACHE = "tool_cache"
UNKNOWN_IGNORED = "unknown_ignored"
# agent-harness#1139: an ignored build output a committed declaration covers AND a
# recorded producer run left behind with the same content digest.
DECLARED_OUTPUT = "declared_output"
_BUCKETS = (RUNNER_OWNED, TOOL_CACHE, DECLARED_OUTPUT, UNKNOWN_IGNORED)


@dataclass(frozen=True)
class IgnoredOutputVerdict:
    provenance: str
    blocks: bool
    reason: str


# Deterministic, regenerable outputs of the build/test toolchain. Membership by
# directory NAME, so a nested `phase-loop-runtime/.pytest_cache/` matches as
# readily as a root one -- the reported defect had caches at both depths.
_TOOL_CACHE_DIR_NAMES = frozenset(
    {
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".pytype",
        ".tox",
        ".nox",
        ".coverage_cache",
        "node_modules",
        # `.venv` is an ENVIRONMENT rather than a cache, and is listed
        # deliberately: the governed verification step creates it (uv/pip), it is
        # gitignored, it is fully regenerable from the lockfile, and it carries no
        # phase evidence. Treating it as unknown reproduces exactly the loop this
        # closes, because every verified phase that installs its deps would block.
        ".venv",
        "venv",
    }
)
_TOOL_CACHE_DIR_SUFFIXES = (".egg-info",)

def classify_ignored_output(repo_relpath: str) -> IgnoredOutputVerdict:
    """Grade one gitignored path by WHO produced it.

    Deny-by-default: anything not recognisably runner- or toolchain-produced is
    ``unknown_ignored`` and still blocks. The point is to stop blocking on the
    runner's own footprint, NOT to stop blocking.
    """

    # Do NOT strip whitespace: " .phase-loop/x" is a DIFFERENT path from
    # ".phase-loop/x", and stripping it hands trusted provenance to a directory
    # an attacker (or an accident) can create. Only a trailing newline, which is
    # line-reading debris rather than part of the name, is removed.
    raw = (repo_relpath or "").rstrip("\n")
    norm = raw[2:] if raw.startswith("./") else raw
    if not norm:
        return IgnoredOutputVerdict(UNKNOWN_IGNORED, True, "empty path")
    if norm.startswith("/") or ".." in PurePosixPath(norm.rstrip("/")).parts:
        # Repo-relative, traversal-free paths only. Neither shape comes from the
        # porcelain this grades, so nothing about them is trustworthy -- and the
        # rationale that rejects an absolute path applies verbatim to `..`.
        return IgnoredOutputVerdict(UNKNOWN_IGNORED, True, "not a repo-relative path")

    # Runner-owned lifecycle state, taken from the runtime's OWN declared
    # exclusions rather than a second list here -- a private copy would drift
    # from the paths the runtime actually writes.
    for entry in EXCLUDE_ENTRIES:
        prefix = entry.rstrip("/")
        # `norm == prefix` is deliberately NOT trusted: a bare `.phase-loop`
        # with no trailing slash is a FILE of that name, not the runner's state
        # directory.
        if norm == prefix + "/" or norm.startswith(prefix + "/"):
            return IgnoredOutputVerdict(
                RUNNER_OWNED, False, f"runner lifecycle state under {entry}"
            )

    # agent-harness#1139: the skill handoff root (agent-harness#1084) is NOT trusted by
    # name here. A path string cannot show who wrote the file, so a handoff is graded in
    # `audit_ignored_outputs` against the handoff contract the file itself carries
    # (generated_outputs.is_harness_handoff).

    # A cache name only earns trust as a DIRECTORY. Git renders a collapsed
    # directory with a trailing slash and a file without one, so a bare `.venv`
    # or `node_modules` entry is an ordinary FILE (or a symlink) that merely
    # borrowed the name -- classifying it as a cache would let any ignored
    # payload pick a trusted name and skip the block.
    is_dir_form = norm.endswith("/")
    parts = PurePosixPath(norm.rstrip("/")).parts
    for index, part in enumerate(parts):
        directory_component = is_dir_form or index < len(parts) - 1
        if not directory_component:
            continue
        if part in _TOOL_CACHE_DIR_NAMES:
            return IgnoredOutputVerdict(TOOL_CACHE, False, f"toolchain output ({part})")
        if part.endswith(_TOOL_CACHE_DIR_SUFFIXES):
            return IgnoredOutputVerdict(TOOL_CACHE, False, f"build metadata ({part})")

    return IgnoredOutputVerdict(
        UNKNOWN_IGNORED, True, "ignored output with no recognised producer"
    )


def _ignored_members(repo: Path, directory: str) -> list[str] | None:
    """The ignored, untracked FILES under a collapsed directory entry.

    `git ls-files` rather than a filesystem walk, so a tracked file or a negated
    (un-ignored) file inside the directory is never graded as ignored output.
    None means the probe failed.
    """

    try:
        out = subprocess.run(
            # Literal pathspec, defence in depth: the directory name is data, never a glob.
            ["git", "-C", str(repo), "--literal-pathspecs", "ls-files", "-z", "--others", "--ignored",
             "--exclude-standard", "--", directory],
            capture_output=True, check=False,
        )
    except OSError:
        return None
    if out.returncode != 0:
        return None
    try:
        return [entry for entry in out.stdout.decode("utf-8").split("\0") if entry]
    except UnicodeDecodeError:
        return None


def _grade_by_provenance(repo: Path, path: str, context):
    """Yield ``(provenance, member, reason)`` for one path the path rules left unknown."""

    if path.endswith("/"):
        members = _ignored_members(repo, path)
        if not members:
            # A failed probe, or nothing to attribute: fail closed on the directory.
            yield UNKNOWN_IGNORED, path, "could not enumerate the ignored directory's files"
            return
    else:
        members = [path]
    for member in members:
        verdict = classify_ignored_output(member)
        if not verdict.blocks:
            yield verdict.provenance, member, verdict.reason
            continue
        is_handoff, handoff_reason = generated_outputs.is_harness_handoff(repo, member)
        if is_handoff:
            yield RUNNER_OWNED, member, handoff_reason
            continue
        declared, declared_reason = generated_outputs.verify_declared_output(repo, member, context)
        if declared:
            yield DECLARED_OUTPUT, member, declared_reason
            continue
        # A path under the handoff root reports why the MARKER failed, which is the
        # actionable fact there; anything else reports the declaration verdict.
        reason = handoff_reason if handoff_reason != "not a handoff file path" else declared_reason
        yield UNKNOWN_IGNORED, member, reason


def audit_ignored_outputs(repo: Path, phase: str | None = None) -> dict:
    """Bucket a worktree's IGNORED paths by producer.

    Exists so the closeout audit is a field read rather than a judgement call.
    The executor that hit ah#670 reasoned correctly from the prose it was given
    and still produced a false blocker; asking it to run this instead removes
    the judgement from the loop.

    Fails CLOSED: if the git probe fails, the result reports the failure and
    ``blocks`` is True. "Could not read the tree" must never present as clean.
    """

    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain", "--ignored=matching",
             "--untracked-files=all"],
            capture_output=True, text=True, check=False,
        )
    except OSError as exc:
        # No git binary at all. Still fail closed, but as a typed probe failure
        # rather than a traceback -- "could not run git" and "unknown outputs"
        # are different facts and the caller has to tell them apart.
        return {
            "probe_failed": True,
            "blocks": True,
            "reason": f"git unavailable: {type(exc).__name__}",
            **{bucket: [] for bucket in _BUCKETS}, "unknown_reasons": {},
        }
    if out.returncode != 0:
        return {
            "probe_failed": True,
            "blocks": True,
            "reason": f"git status failed: {out.stderr.strip()[:120]}",
            **{bucket: [] for bucket in _BUCKETS}, "unknown_reasons": {},
        }
    # agent-harness#1139: provenance beyond the path rules. A malformed committed
    # declaration is a typed failure, never "no declaration": silently ignoring it would
    # turn the consumer's intent into a mystery block.
    try:
        context = generated_outputs.AuditContext.for_repo(repo, phase)
    except generated_outputs.DeclarationError as exc:
        return {
            "probe_failed": True,
            "blocks": True,
            "reason": f"invalid generated-outputs declaration: {exc}",
            **{bucket: [] for bucket in _BUCKETS}, "unknown_reasons": {},
        }

    buckets: dict = {bucket: [] for bucket in _BUCKETS}
    unknown_reasons: dict[str, str] = {}
    blocking = False
    for line in out.stdout.splitlines():
        # Only `!!` entries are ignored; tracked/untracked dirt is graded by the
        # ownership contract, not by this audit.
        if not line.startswith("!! "):
            continue
        # Unquote WITHOUT stripping whitespace. Git does quote a path with a
        # leading space (verified: `!! " .phase-loop/"`), so `.strip()` would
        # hit the quotes rather than the space -- but that makes correctness
        # depend on git's quoting rules. Peeling the quotes explicitly and
        # never stripping whitespace is safe by construction instead.
        raw = line[3:].rstrip("\n").rstrip("\r")
        if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"'):
            raw = raw[1:-1]
        path = raw
        if not path:
            continue
        verdict = classify_ignored_output(path)
        if not verdict.blocks:
            buckets[verdict.provenance].append(path)
            continue
        # The path rules could not attribute it. Grade its FILES by provenance:
        # git renders a wholly-ignored directory collapsed (`!! dist/`), and a
        # directory is attributable only if every ignored file in it is.
        for provenance, member, reason in _grade_by_provenance(repo, path, context):
            buckets[provenance].append(member)
            if provenance == UNKNOWN_IGNORED:
                unknown_reasons[member] = reason
                # One seam for the blocking fact: only unknown blocks here.
                blocking = True
    buckets["unknown_reasons"] = unknown_reasons
    buckets["probe_failed"] = False
    buckets["blocks"] = blocking
    # `reason` reads the SAME seam as `blocks`, not the UNKNOWN bucket: deriving
    # them separately drifts the moment a provenance other than unknown blocks.
    buckets["reason"] = (
        f"{len(buckets[UNKNOWN_IGNORED])} ignored output(s) with no recognised producer"
        if blocking
        else "every ignored path was produced by the runner, its toolchain or a declared producer"
    )
    return buckets


# The required closeout action for each exit, printed by `main` as its last line.
# The execute-phase skills carry the same mapping only as a fallback for a pinned
# runtime that predates this line (agent-harness#1303).
CLOSEOUT_ACTIONS = {
    0: "action: exit 0 (no unknown ignored outputs) -> ignored paths do not block "
       "closeout; the dirty-path classification still decides the terminal status",
    1: "action: exit 1 (unknown ignored outputs) -> BLOCKS: stop with "
       "terminal_status=dirty_worktree_conflict; never report complete",
    2: "action: exit 2 (probe failed) -> BLOCKS: stop with "
       "terminal_status=dirty_worktree_conflict; inability to measure is never "
       "evidence of a clean tree",
}


def _exit(code: int) -> int:
    print(CLOSEOUT_ACTIONS[code])
    return code


def main(argv: list[str]) -> int:
    """``python -m phase_loop_runtime.closeout_classifier --repo .``

    Exit 0 = no unknown ignored outputs, so ignored dirt is NOT a closeout
    blocker. Exit 1 = unknown ignored outputs present, which still blocks.
    Exit 2 = the probe itself failed (including an invalid committed
    generated-outputs declaration). Every exit prints its ``CLOSEOUT_ACTIONS``
    line last, so the executor reads the required terminal action from the
    tool instead of re-deriving it from skill prose (agent-harness#1303).

    ``--record-outputs`` (agent-harness#1139) first runs, one at a time and under
    observation, every producer the committed ``.phase-loop-generated-outputs.json``
    declares. It records what each invocation wrote, bound to HEAD, then audits.
    With no declaration it is a no-op, so executors pass it in every repo. With a
    declaration it needs ``--phase "<ALIAS>"`` (substituted) and exits 2, before touching anything,
    without one. The
    runner's verification records the same evidence when it runs a declared
    producer command.
    """

    repo = Path(argv[argv.index("--repo") + 1]) if "--repo" in argv else Path.cwd()
    # The phase the evidence must belong to: ONLY this explicit argument (the runner's
    # prompts write it literally). Never the environment or `.phase-loop/state.json`.
    phase = argv[argv.index("--phase") + 1] if "--phase" in argv else None
    if "--record-outputs" in argv:
        try:
            generated_outputs.run_declared_producers(repo, phase=phase)
        except (generated_outputs.DeclarationError, generated_outputs.PhaseIdentityError) as exc:
            print(f"closeout-ignored-audit: CANNOT RECORD — {exc}")
            return _exit(2)
    result = audit_ignored_outputs(repo, phase)
    if result["probe_failed"]:
        print(f"closeout-ignored-audit: CANNOT EVALUATE — {result['reason']}")
        return _exit(2)
    reasons = result.get("unknown_reasons", {})
    for bucket in _BUCKETS:
        paths = result[bucket]
        if paths:
            print(f"{bucket} ({len(paths)}):")
            for p in paths[:20]:
                suffix = f"  -- {reasons[p]}" if p in reasons else ""
                print(f"    {p}{suffix}")
    print(f"\nverdict: {result['reason']}")
    return _exit(1 if result["blocks"] else 0)


def console_main() -> int:
    """Console-script entrypoint (``phase-loop-closeout-audit``).

    A ``[project.scripts]`` target is invoked with NO arguments, so it cannot be
    ``main`` directly -- that signature takes an argv list.

    This exists because the module form does not work on the primary
    installation path: `uv tool install` puts the package in an isolated
    environment where `python -m phase_loop_runtime...` fails to import. Under
    the closeout contract that failure exits 1, which the contract reads as
    "unknown ignored outputs" -- so an audit instruction that only had a module
    form would recreate the very false blocker this closes, on the supported
    install.
    """

    return main(sys.argv[1:])


if __name__ == "__main__":  # pragma: no cover - thin argv shim
    raise SystemExit(main(sys.argv[1:]))
