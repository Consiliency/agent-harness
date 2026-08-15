"""Bootstrap writer for the GOVLEAN content-bound RED receipt.

This lives with the frozen tests so the tests-only landing can record the
``content_tdd_receipt.v1`` evidence before the runtime implementation exists.
It intentionally uses only local Git and the supplied test command.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import importlib
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence


SCHEMA = "content_tdd_receipt.v1"
ACTIVATION_ENV = "PHASE_LOOP_TDD_EXPECT_GOVLEAN"
RED_ANCHOR_MARKER = "GOVLEAN deliberate RED anchor"
DEFAULT_FROZEN_SUPPORT_PATHS = (
    "phase-loop-runtime/tests/govlean_freeze_receipt.py",
    "phase-loop-runtime/tests/test_legible_review_repairs.py",
    "phase-loop-runtime/tests/test_skill_plan_manifest_write.py",
)


def govlean_forced() -> bool:
    return os.environ.get(ACTIVATION_ENV) == "1"


def govlean_phase_started(repo_root: Path | None = None) -> bool:
    root = repo_root or Path(__file__).resolve().parents[2]
    manifest = root / "plans" / "manifest.json"
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    for entry in payload.get("plans", ()):
        if entry.get("slug") == "v10-GOVLEAN":
            return entry.get("status") in {"executing", "completed"}
    return False


def govlean_api_available(
    module_name: str, *attributes: str, repo_root: Path | None = None
) -> bool:
    """Activate frozen tests after their API exists, or during forced RED."""
    if govlean_forced() or govlean_phase_started(repo_root):
        return True
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        return exc.name != module_name
    except ImportError:
        return True
    return all(hasattr(module, attribute) for attribute in attributes)


class FreezeReceiptError(RuntimeError):
    """A local receipt-recording precondition was not satisfied."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _git_bytes(repo: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise FreezeReceiptError("git_failure", f"git {' '.join(args)} failed")
    return completed.stdout


def _git_text(repo: Path, *args: str) -> str:
    return _git_bytes(repo, *args).decode("utf-8").strip()


def _command_argv(repo: Path, command: str) -> list[str]:
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        raise FreezeReceiptError("invalid_red_command", str(exc)) from exc
    if not tokens:
        raise FreezeReceiptError("invalid_red_command", "red command must not be empty")

    argv: list[str] = []
    for token in tokens:
        if glob.has_magic(token):
            pattern = token if Path(token).is_absolute() else str(repo / token)
            matches = sorted(Path(match) for match in glob.glob(pattern, recursive=True))
            if not matches:
                argv.append(token)
                continue
            for match in matches:
                try:
                    argv.append(match.relative_to(repo).as_posix())
                except ValueError:
                    argv.append(str(match))
            continue
        argv.append(token)
    return argv


def _test_files(
    repo: Path,
    test_glob: str,
    support_paths: Sequence[str] = (),
) -> tuple[tuple[str, str], ...]:
    pattern = test_glob if Path(test_glob).is_absolute() else str(repo / test_glob)
    matched = {Path(match) for match in glob.glob(pattern, recursive=True)}
    matched.update(repo / path for path in support_paths)
    files: list[tuple[str, str]] = []
    for raw_path in sorted(matched):
        if raw_path.is_symlink() or not raw_path.is_file():
            raise FreezeReceiptError("invalid_test_path", f"test path must be a regular file: {raw_path}")
        try:
            relative = raw_path.relative_to(repo).as_posix()
        except ValueError as exc:
            raise FreezeReceiptError("test_path_outside_repo", str(raw_path)) from exc
        files.append((relative, _sha256(raw_path.read_bytes())))
    if not files:
        raise FreezeReceiptError("no_test_files", f"test glob matched no files: {test_glob}")
    return tuple(files)


def _forced_environment() -> dict[str, str]:
    return {**os.environ, ACTIVATION_ENV: "1"}


def _effective_red_argv(
    repo: Path,
    red_command: str,
    test_files: Sequence[tuple[str, str]],
) -> tuple[list[str], tuple[str, ...]]:
    argv = _command_argv(repo, red_command)
    try:
        argv.index("pytest")
    except ValueError as exc:
        raise FreezeReceiptError("red_command_not_pytest", "red command must invoke pytest") from exc
    expected_test_paths = tuple(
        relative
        for relative, _digest in test_files
        if Path(relative).name.startswith("test_") and Path(relative).suffix == ".py"
    )
    for relative in expected_test_paths:
        if relative not in argv:
            argv.append(relative)
    return argv, expected_test_paths


def _collect_nodeids(repo: Path, red_argv: Sequence[str]) -> tuple[str, ...]:
    argv = list(red_argv)
    pytest_index = argv.index("pytest")
    collect_argv = [*argv[: pytest_index + 1], "--collect-only", *argv[pytest_index + 1 :]]
    completed = subprocess.run(
        collect_argv,
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
        env=_forced_environment(),
    )
    if completed.returncode != 0:
        raise FreezeReceiptError("node_collection_failed", "pytest --collect-only must succeed")
    nodeids = tuple(
        line.strip()
        for line in completed.stdout.splitlines()
        if "::" in line and not line.lstrip().startswith("ERROR")
    )
    if not nodeids:
        raise FreezeReceiptError("no_test_nodes", "pytest collected no test nodeids")
    return nodeids


def _write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)


def record_content_tdd_receipt(
    *,
    repo: Path,
    test_glob: str,
    red_command: str,
    landing_ref: str,
    out: Path,
    support_paths: Sequence[str] = (),
) -> dict[str, Any]:
    """Run a required RED command and write a content-bound receipt plus raw logs."""
    repo = Path(repo).resolve()
    out = Path(out)
    if not out.is_absolute():
        out = repo / out
    test_files = _test_files(repo, test_glob, support_paths)

    landing_commit = _git_text(repo, "rev-parse", f"{landing_ref}^{{commit}}")
    landing_tree_digest = _git_text(repo, "rev-parse", f"{landing_commit}^{{tree}}")
    base_commit = _git_text(repo, "rev-parse", "HEAD")
    base_tree_digest = _git_text(repo, "rev-parse", "HEAD^{tree}")
    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", base_commit, landing_commit],
        cwd=repo,
        check=False,
        capture_output=True,
    )
    if ancestry.returncode != 0:
        raise FreezeReceiptError(
            "base_not_in_landing",
            "the current base commit must be contained in the declared tests-only landing",
        )

    for relative, digest in test_files:
        landed_bytes = _git_bytes(repo, "show", f"{landing_commit}:{relative}")
        if _sha256(landed_bytes) != digest:
            raise FreezeReceiptError(
                "frozen_test_not_in_landing",
                f"{relative} differs from the declared tests-only landing",
            )

    red_argv, expected_test_paths = _effective_red_argv(repo, red_command, test_files)
    red = subprocess.run(
        red_argv,
        cwd=repo,
        check=False,
        capture_output=True,
        env=_forced_environment(),
    )
    if red.returncode != 1:
        code = "red_command_succeeded" if red.returncode == 0 else "red_command_invalid_exit"
        raise FreezeReceiptError(code, "the recorded pytest command must exit with test failures")
    if RED_ANCHOR_MARKER.encode("utf-8") not in red.stdout + red.stderr:
        raise FreezeReceiptError(
            "red_anchor_missing",
            "the recorded pytest failure did not fire the GOVLEAN RED anchor",
        )
    nodeids = _collect_nodeids(repo, red_argv)
    collected_paths = {nodeid.split("::", 1)[0] for nodeid in nodeids}
    missing_paths = sorted(set(expected_test_paths) - collected_paths)
    if missing_paths:
        raise FreezeReceiptError(
            "red_test_coverage_incomplete",
            f"pytest did not collect every frozen test file: {missing_paths}",
        )

    stdout_path = out.with_name(f"{out.stem}.red.stdout.log")
    stderr_path = out.with_name(f"{out.stem}.red.stderr.log")
    _write_bytes(stdout_path, red.stdout)
    _write_bytes(stderr_path, red.stderr)
    payload = {
        "schema": SCHEMA,
        "test_files": [
            {"path": relative, "sha256": digest} for relative, digest in test_files
        ],
        "red_command": red_command,
        "red_argv": red_argv,
        "red_environment": {ACTIVATION_ENV: "1"},
        "red_nodeids": list(nodeids),
        "red_exit_status": red.returncode,
        "red_stdout_path": stdout_path.relative_to(out.parent).as_posix(),
        "red_stdout_sha256": _sha256(red.stdout),
        "red_stderr_path": stderr_path.relative_to(out.parent).as_posix(),
        "red_stderr_sha256": _sha256(red.stderr),
        "base_commit": base_commit,
        "base_tree_digest": base_tree_digest,
        "landing_ref": landing_ref,
        "landing_commit": landing_commit,
        "landing_tree_digest": landing_tree_digest,
    }
    _write_bytes(out, (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record GOVLEAN content-bound RED evidence")
    subparsers = parser.add_subparsers(dest="command", required=True)
    record = subparsers.add_parser("record")
    record.add_argument("--repo", type=Path, required=True)
    record.add_argument("--test-glob", required=True)
    record.add_argument("--red-command", required=True)
    record.add_argument("--landing-ref", required=True)
    record.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        payload = record_content_tdd_receipt(
            repo=args.repo,
            test_glob=args.test_glob,
            red_command=args.red_command,
            landing_ref=args.landing_ref,
            out=args.out,
            support_paths=DEFAULT_FROZEN_SUPPORT_PATHS,
        )
    except FreezeReceiptError as exc:
        print(f"govlean_freeze_receipt: {exc.code}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"schema": payload["schema"], "receipt": str(args.out)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
