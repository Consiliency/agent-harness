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

    raw = (repo_relpath or "").strip()
    norm = raw[2:] if raw.startswith("./") else raw
    norm = norm.lstrip("/")
    if not norm:
        return IgnoredOutputVerdict(UNKNOWN_IGNORED, True, "empty path")

    # Runner-owned lifecycle state, taken from the runtime's OWN declared
    # exclusions rather than a second list here -- a private copy would drift
    # from the paths the runtime actually writes.
    for entry in EXCLUDE_ENTRIES:
        prefix = entry.rstrip("/")
        if norm == prefix or norm.startswith(prefix + "/"):
            return IgnoredOutputVerdict(
                RUNNER_OWNED, False, f"runner lifecycle state under {entry}"
            )

    parts = PurePosixPath(norm).parts
    for part in parts:
        if part in _TOOL_CACHE_DIR_NAMES:
            return IgnoredOutputVerdict(TOOL_CACHE, False, f"toolchain output ({part})")
        if part.endswith(_TOOL_CACHE_DIR_SUFFIXES):
            return IgnoredOutputVerdict(TOOL_CACHE, False, f"build metadata ({part})")

    return IgnoredOutputVerdict(
        UNKNOWN_IGNORED, True, "ignored output with no recognised producer"
    )


def audit_ignored_outputs(repo: Path) -> dict:
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
            RUNNER_OWNED: [], TOOL_CACHE: [], UNKNOWN_IGNORED: [],
        }
    if out.returncode != 0:
        return {
            "probe_failed": True,
            "blocks": True,
            "reason": f"git status failed: {out.stderr.strip()[:120]}",
            RUNNER_OWNED: [], TOOL_CACHE: [], UNKNOWN_IGNORED: [],
        }
    buckets: dict = {RUNNER_OWNED: [], TOOL_CACHE: [], UNKNOWN_IGNORED: []}
    blocking = False
    for line in out.stdout.splitlines():
        # Only `!!` entries are ignored; tracked/untracked dirt is graded by the
        # ownership contract, not by this audit.
        if not line.startswith("!! "):
            continue
        path = line[3:].strip().strip('"')
        if not path:
            continue
        verdict = classify_ignored_output(path)
        buckets[verdict.provenance].append(path)
        # Consume the verdict's own `blocks` rather than re-deriving it from
        # bucket membership: two seams for one fact drift the moment a new
        # provenance is added.
        blocking = blocking or verdict.blocks
    buckets["probe_failed"] = False
    buckets["blocks"] = blocking
    buckets["reason"] = (
        f"{len(buckets[UNKNOWN_IGNORED])} ignored output(s) with no recognised producer"
        if buckets[UNKNOWN_IGNORED]
        else "every ignored path was produced by the runner or its toolchain"
    )
    return buckets


def main(argv: list[str]) -> int:
    """``python -m phase_loop_runtime.closeout_classifier --repo .``

    Exit 0 = no unknown ignored outputs, so ignored dirt is NOT a closeout
    blocker. Exit 1 = unknown ignored outputs present, which still blocks.
    Exit 2 = the probe itself failed.
    """

    repo = Path(argv[argv.index("--repo") + 1]) if "--repo" in argv else Path.cwd()
    result = audit_ignored_outputs(repo)
    if result["probe_failed"]:
        print(f"closeout-ignored-audit: CANNOT EVALUATE — {result['reason']}")
        return 2
    for bucket in (RUNNER_OWNED, TOOL_CACHE, UNKNOWN_IGNORED):
        paths = result[bucket]
        if paths:
            print(f"{bucket} ({len(paths)}):")
            for p in paths[:20]:
                print(f"    {p}")
    print(f"\nverdict: {result['reason']}")
    return 1 if result["blocks"] else 0


if __name__ == "__main__":  # pragma: no cover - thin argv shim
    raise SystemExit(main(sys.argv[1:]))
