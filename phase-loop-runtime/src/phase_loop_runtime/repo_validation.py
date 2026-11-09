"""Resolve and run explicit repo validation contracts.

``phase-loop repo-validate`` supports ``fast``, ``gate``, ``full``, ``fix``,
``affected``, and ``doctor``. Resolution prefers a Justfile contract: an
``agent::<target>`` recipe in a declared agent module, or a flat
``agent:<target>`` recipe in the root Justfile. Otherwise it looks for a
``package.json`` script named ``agent:<target>``. It does not infer a contract
from generic test commands. See ``docs/repo-validation-contract.md``.

This is the behavioural twin of dotfiles' ``scripts/agent-validation``: for the
same repo and target it must make the same dispatch decision and preserve the
same exit-code contract. The intentional refinement is JSON reading: the Python
stdlib needs no Node reader, so exit 21 for a package contract means the selected
package-manager runner is missing, rather than Node being absent just for parsing.

The stdlib resolver reads JSON directly and chooses the package manager using
lockfile precedence, then available-runner fallback. Missing contracts return
exit 20; missing selected runners return 21. ``run_plan`` maps a nonzero command
exit to 30. Discovery and execution are separate APIs for testing without a live
Just or package-manager subprocess.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Frozen exit-code contract (docs/repo-validation-contract.md).
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_NO_REPO = 10
EXIT_NO_CONTRACT = 20
EXIT_MISSING_RUNNER = 21
EXIT_COMMAND_FAILED = 30

# The six neutral targets plus the ``check`` alias for ``doctor``.
TARGETS = ("fast", "gate", "full", "fix", "affected", "doctor")
TARGET_ALIASES = {"check": "doctor"}
ALL_TARGET_TOKENS = TARGETS + tuple(TARGET_ALIASES)

# ``agent.just`` module candidates, in the same order the bash wrapper probes.
_AGENT_JUST_CANDIDATES = (
    "agent.just",
    "agent/mod.just",
    "agent/Justfile",
    "agent/justfile",
    "agent/.justfile",
)

# Lockfile -> package-manager mapping, probed before the generic fallback order.
_LOCKFILE_MANAGERS = (
    ("pnpm-lock.yaml", "pnpm"),
    ("package-lock.json", "npm"),
    ("yarn.lock", "yarn"),
    ("bun.lock", "bun"),
    ("bun.lockb", "bun"),
)
_FALLBACK_MANAGERS = ("pnpm", "npm", "yarn", "bun")


@dataclass(frozen=True)
class ValidationPlan:
    """The resolved dispatch for one ``(repo_root, target)`` pair.

    Exactly one of ``argv`` (a runnable command) or ``exit_code`` (a terminal
    no-run outcome, 20 or 21) is set. ``resolve`` never touches the network or
    mutates state; ``run_plan`` turns an ``argv`` plan into a 0/30 result.
    """

    target: str
    repo_root: Path
    contract_kind: str | None  # "just" | "package" | None
    contract: str | None  # e.g. "agent::gate" or "agent:gate"
    argv: tuple[str, ...] | None
    exit_code: int | None
    note: str | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "target": self.target,
            "repo_root": str(self.repo_root),
            "contract_kind": self.contract_kind,
            "contract": self.contract,
            "argv": list(self.argv) if self.argv is not None else None,
            "exit_code": self.exit_code,
            "note": self.note,
        }


# --------------------------------------------------------------------------- #
# Repo-root resolution (git worktree aware).
# --------------------------------------------------------------------------- #
def find_repo_root(cwd: str | Path) -> Path | None:
    """Return the git work-tree root for ``cwd``, or ``None`` when outside git.

    Uses ``git rev-parse --show-toplevel`` so it resolves correctly from
    subdirectories and from linked worktrees, matching the bash wrapper.
    """

    try:
        proc = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if proc.returncode != 0:
        return None
    root = proc.stdout.strip()
    return Path(root) if root else None


# --------------------------------------------------------------------------- #
# Justfile contract discovery (pure filesystem).
# --------------------------------------------------------------------------- #
_COMMENT_RE = re.compile(r"^\s*#")
_MOD_AGENT_RE = re.compile(r"^\s*mod\??\s+agent(\s|$)")


def find_justfile(root: Path) -> Path | None:
    for name in ("Justfile", "justfile"):
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def _iter_noncomment_lines(path: Path):
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for line in text.splitlines():
        if _COMMENT_RE.match(line):
            continue
        yield line


def has_agent_just_module(justfile: Path) -> bool:
    """True when the Justfile declares ``mod agent`` (or ``mod? agent``)."""

    return any(_MOD_AGENT_RE.match(line) for line in _iter_noncomment_lines(justfile))


def find_agent_just_module(root: Path) -> Path | None:
    for candidate in _AGENT_JUST_CANDIDATES:
        path = root / candidate
        if path.is_file():
            return path
    return None


def has_just_recipe(justfile: Path, recipe: str) -> bool:
    """True when ``justfile`` declares a recipe named ``recipe``."""

    pattern = re.compile(rf"^\s*{re.escape(recipe)}([\s:]|$)")
    return any(pattern.match(line) for line in _iter_noncomment_lines(justfile))


def just_contract_command(root: Path, target: str) -> str | None:
    """Return the just invocation (``agent::<t>`` or ``agent:<t>``) or ``None``.

    Mirrors the bash ``just_contract_command``: prefer the ``mod agent`` module
    recipe, then a flat ``agent:<target>`` recipe in the root Justfile.
    """

    justfile = find_justfile(root)
    if justfile is None:
        return None
    if has_agent_just_module(justfile):
        module = find_agent_just_module(root)
        if module is not None and has_just_recipe(module, target):
            return f"agent::{target}"
    if has_just_recipe(justfile, f"agent:{target}"):
        return f"agent:{target}"
    return None


# --------------------------------------------------------------------------- #
# package.json contract discovery (stdlib JSON, no node required).
# --------------------------------------------------------------------------- #
def package_has_script(root: Path, script: str) -> bool:
    package_json = root / "package.json"
    if not package_json.is_file():
        return False
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    scripts = data.get("scripts") if isinstance(data, dict) else None
    return isinstance(scripts, dict) and script in scripts


def package_manager_for(root: Path) -> str | None:
    """Pick the package-manager runner, honoring a present lockfile first.

    When a lockfile pins a manager, that manager must be on PATH (else ``None``,
    which the caller maps to exit 21). With no lockfile, fall back to the first
    available manager, matching the bash wrapper's probe order.
    """

    for lockfile, manager in _LOCKFILE_MANAGERS:
        if (root / lockfile).is_file():
            return manager if shutil.which(manager) else None
    for manager in _FALLBACK_MANAGERS:
        if shutil.which(manager):
            return manager
    return None


# --------------------------------------------------------------------------- #
# Resolution (pure) + execution (subprocess).
# --------------------------------------------------------------------------- #
def resolve(repo_root: Path, target: str) -> ValidationPlan:
    """Resolve the dispatch for a non-doctor target without running anything.

    Precedence (identical to the bash wrapper):
      1. just contract + ``just`` on PATH  -> run it.
      2. package script present            -> run it (or 21 if no manager).
      3. just contract but ``just`` absent -> 21.
      4. nothing                           -> 20 (fail closed).
    """

    just_contract = just_contract_command(repo_root, target)
    has_pkg = package_has_script(repo_root, f"agent:{target}")
    just_present = shutil.which("just") is not None

    if just_contract is not None and just_present:
        return ValidationPlan(
            target=target,
            repo_root=repo_root,
            contract_kind="just",
            contract=just_contract,
            argv=("just", just_contract),
            exit_code=None,
        )

    if has_pkg:
        script = f"agent:{target}"
        note = None
        if just_contract is not None and not just_present:
            note = (
                f"{just_contract} is declared, but just is not on PATH; "
                f"running explicit package script {script}."
            )
        manager = package_manager_for(repo_root)
        if manager is None:
            return ValidationPlan(
                target=target,
                repo_root=repo_root,
                contract_kind="package",
                contract=script,
                argv=None,
                exit_code=EXIT_MISSING_RUNNER,
                note=f"package.json declares {script}, but no supported package manager is on PATH.",
            )
        return ValidationPlan(
            target=target,
            repo_root=repo_root,
            contract_kind="package",
            contract=script,
            argv=(manager, "run", script),
            exit_code=None,
            note=note,
        )

    if just_contract is not None:
        return ValidationPlan(
            target=target,
            repo_root=repo_root,
            contract_kind="just",
            contract=just_contract,
            argv=None,
            exit_code=EXIT_MISSING_RUNNER,
            note=f"{just_contract} is declared, but just is not on PATH.",
        )

    return ValidationPlan(
        target=target,
        repo_root=repo_root,
        contract_kind=None,
        contract=None,
        argv=None,
        exit_code=EXIT_NO_CONTRACT,
        note=(
            f"no explicit agent validation contract for agent:{target}. "
            f"Declare just agent::{target} or a package.json script named agent:{target}."
        ),
    )


def run_plan(plan: ValidationPlan) -> int:
    """Execute a resolved plan and map the result to the exit-code contract.

    A no-run plan returns its terminal code (20/21). A runnable plan returns 0 on
    success and 30 when the repo-local validation command fails.
    """

    if plan.argv is None:
        return int(plan.exit_code if plan.exit_code is not None else EXIT_NO_CONTRACT)
    try:
        proc = subprocess.run(list(plan.argv), cwd=str(plan.repo_root), check=False)
    except FileNotFoundError:
        # The runner vanished between discovery and exec (race / PATH change).
        return EXIT_MISSING_RUNNER
    return EXIT_OK if proc.returncode == 0 else EXIT_COMMAND_FAILED


# --------------------------------------------------------------------------- #
# doctor: a neutral environment/contract report (always exits 0).
# --------------------------------------------------------------------------- #
def _declared_contracts(root: Path) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for target in TARGETS:
        just_contract = just_contract_command(root, target)
        if just_contract is not None:
            found.append((target, f"just {just_contract}"))
        elif package_has_script(root, f"agent:{target}"):
            found.append((target, f"package script agent:{target}"))
    return found


def doctor_report(root: Path) -> dict[str, object]:
    tools = {
        name: shutil.which(name)
        for name in ("git", "just", "dagger", "docker", "node", "pnpm", "npm", "yarn", "bun", "uv", "python3", "cargo")
    }
    stack_hints = [
        name
        for name in (
            "package.json",
            "pyproject.toml",
            "Cargo.toml",
            "dagger.json",
            "Dockerfile",
            "docker-compose.yml",
            ".pre-commit-config.yaml",
        )
        if (root / name).is_file()
    ]
    return {
        "repo_root": str(root),
        "tools": tools,
        "stack_hints": stack_hints,
        "declared_contracts": [{"target": t, "runner": r} for t, r in _declared_contracts(root)],
    }


def _print_doctor(report: dict[str, object]) -> None:
    print("Agent validation doctor")
    print(f"  repo-root        {report['repo_root']}")
    print("")
    print("Tools:")
    for name, path in report["tools"].items():  # type: ignore[index]
        print(f"  {name:<16} {'present (' + path + ')' if path else 'missing'}")
    print("")
    print("Repo stack hints:")
    for hint in report["stack_hints"]:  # type: ignore[index]
        print(f"  {hint}")
    print("")
    print("Declared agent contracts:")
    contracts = report["declared_contracts"]  # type: ignore[index]
    if contracts:
        for entry in contracts:  # type: ignore[union-attr]
            print(f"  {entry['target']:<16} {entry['runner']}")
    else:
        print("  none")
        print("")
        print(
            "This repo is not migrated yet. Validation targets fail closed (exit 20) "
            "until it declares agent:* commands."
        )


# --------------------------------------------------------------------------- #
# CLI entry point (wired from cli.py as the ``repo-validate`` subcommand).
# --------------------------------------------------------------------------- #
def cli_main(*, target: str, cwd: str | Path = ".", as_json: bool = False) -> int:
    """Resolve and run a repo's explicit validation contract; return its code."""

    normalized = TARGET_ALIASES.get(target, target)
    if normalized not in TARGETS:
        print(f"ERROR: unknown validation target '{target}'.", flush=True)
        return EXIT_USAGE

    root = find_repo_root(cwd)
    if root is None:
        print("ERROR: not inside a git work tree.", flush=True)
        return EXIT_NO_REPO

    if normalized == "doctor":
        report = doctor_report(root)
        if as_json:
            print(json.dumps(report, indent=2))
        else:
            _print_doctor(report)
        return EXIT_OK

    plan = resolve(root, normalized)
    if as_json:
        # --json is inspection-only: print the resolved plan and DO NOT execute
        # the repo-local command (keeping stdout clean, machine-parseable JSON).
        # A no-run plan returns its terminal code (20/21); a runnable plan returns
        # 0, meaning "a runnable contract was resolved" -- not "the command ran".
        print(json.dumps(plan.to_json(), indent=2))
        return EXIT_OK if plan.argv is not None else run_plan(plan)
    if plan.note:
        stream_prefix = "WARN" if plan.argv is not None else "ERROR"
        print(f"{stream_prefix}: {plan.note}", flush=True)
    return run_plan(plan)
