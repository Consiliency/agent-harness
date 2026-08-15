"""Verification for content-bound tests-first receipts."""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


SCHEMA = "content_tdd_receipt.v1"
ACTIVATION_ENV = "PHASE_LOOP_TDD_EXPECT_GOVLEAN"
RED_ANCHOR_MARKER = "GOVLEAN deliberate RED anchor"


class ContentTddReceiptError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ContentTddReceipt:
    schema: str
    test_files: tuple[tuple[str, str], ...]
    red_command: str
    red_argv: tuple[str, ...]
    red_environment: tuple[tuple[str, str], ...]
    red_nodeids: tuple[str, ...]
    red_exit_status: int
    red_stdout_path: str
    red_stdout_sha256: str
    red_stderr_path: str
    red_stderr_sha256: str
    base_commit: str
    base_tree_digest: str
    landing_ref: str
    landing_commit: str
    landing_tree_digest: str
    receipt_path: Path

    @property
    def ok(self) -> bool:
        return True

    @classmethod
    def from_payload(cls, payload: dict[str, Any], receipt_path: Path) -> ContentTddReceipt:
        return cls(
            schema=payload["schema"],
            test_files=tuple((item["path"], item["sha256"]) for item in payload["test_files"]),
            red_command=payload["red_command"],
            red_argv=tuple(payload["red_argv"]),
            red_environment=tuple(sorted(payload["red_environment"].items())),
            red_nodeids=tuple(payload["red_nodeids"]),
            red_exit_status=payload["red_exit_status"],
            red_stdout_path=payload["red_stdout_path"],
            red_stdout_sha256=payload["red_stdout_sha256"],
            red_stderr_path=payload["red_stderr_path"],
            red_stderr_sha256=payload["red_stderr_sha256"],
            base_commit=payload["base_commit"],
            base_tree_digest=payload["base_tree_digest"],
            landing_ref=payload["landing_ref"],
            landing_commit=payload["landing_commit"],
            landing_tree_digest=payload["landing_tree_digest"],
            receipt_path=receipt_path,
        )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=repo, check=False, capture_output=True, text=True
    )
    if completed.returncode:
        raise ContentTddReceiptError("git_failure", completed.stderr.strip())
    return completed.stdout.strip()


def _load_receipt(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContentTddReceiptError("invalid_receipt", str(exc)) from exc
    if payload.get("schema") != SCHEMA:
        raise ContentTddReceiptError("invalid_receipt_schema", "unsupported receipt schema")
    return payload


def verify_content_tdd_receipt(*, receipt_path: Path, repo: Path) -> ContentTddReceipt:
    receipt_path = Path(receipt_path).resolve()
    repo = Path(repo).resolve()
    payload = _load_receipt(receipt_path)

    base_commit = str(payload.get("base_commit", ""))
    landing_commit = str(payload.get("landing_commit", ""))
    actual_base_tree = _git(repo, "rev-parse", f"{base_commit}^{{tree}}")
    if actual_base_tree != payload.get("base_tree_digest"):
        raise ContentTddReceiptError(
            "base_tree_not_in_landing", "receipt base tree does not match its declared commit"
        )
    actual_landing_tree = _git(repo, "rev-parse", f"{landing_commit}^{{tree}}")
    if actual_landing_tree != payload.get("landing_tree_digest"):
        raise ContentTddReceiptError(
            "landing_tree_drift", "receipt landing tree does not match its declared commit"
        )
    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", base_commit, landing_commit],
        cwd=repo,
        check=False,
        capture_output=True,
    )
    if ancestry.returncode:
        raise ContentTddReceiptError(
            "base_tree_not_in_landing", "receipt base is not contained in the declared landing"
        )

    for item in payload.get("test_files", ()):
        relative = item.get("path", "")
        path = repo / relative
        if not path.is_file() or path.is_symlink() or _sha256(path) != item.get("sha256"):
            raise ContentTddReceiptError(
                "frozen_test_drift", f"frozen test content changed: {relative}"
            )
    for path_key, digest_key in (
        ("red_stdout_path", "red_stdout_sha256"),
        ("red_stderr_path", "red_stderr_sha256"),
    ):
        log_path = receipt_path.parent / str(payload.get(path_key, ""))
        if not log_path.is_file() or _sha256(log_path) != payload.get(digest_key):
            raise ContentTddReceiptError("red_log_drift", f"RED log changed: {log_path}")
    return ContentTddReceipt.from_payload(payload, receipt_path)


def _expanded_argv(repo: Path, command: str) -> list[str]:
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        raise ContentTddReceiptError("invalid_red_command", str(exc)) from exc
    argv: list[str] = []
    for token in tokens:
        if glob.has_magic(token):
            matches = sorted(glob.glob(str(repo / token), recursive=True))
            argv.extend(Path(match).relative_to(repo).as_posix() for match in matches)
        else:
            argv.append(token)
    if "pytest" not in argv:
        raise ContentTddReceiptError("red_command_not_pytest", "RED command must invoke pytest")
    return argv


def record_content_tdd_receipt(
    *,
    repo: Path,
    test_glob: str,
    red_command: str,
    landing_ref: str,
    out: Path,
    support_paths: Sequence[str] = (),
) -> ContentTddReceipt:
    repo = Path(repo).resolve()
    out = Path(out)
    if not out.is_absolute():
        out = repo / out
    matches = {Path(path) for path in glob.glob(str(repo / test_glob), recursive=True)}
    matches.update(repo / path for path in support_paths)
    files: list[tuple[str, str]] = []
    for path in sorted(matches):
        if not path.is_file() or path.is_symlink():
            raise ContentTddReceiptError("invalid_test_path", str(path))
        files.append((path.relative_to(repo).as_posix(), _sha256(path)))
    if not files:
        raise ContentTddReceiptError("no_test_files", test_glob)

    landing_commit = _git(repo, "rev-parse", f"{landing_ref}^{{commit}}")
    base_commit = _git(repo, "rev-parse", "HEAD")
    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", base_commit, landing_commit], cwd=repo
    ).returncode:
        raise ContentTddReceiptError("base_not_in_landing", "base is not in landing")
    for relative, digest in files:
        completed = subprocess.run(
            ["git", "show", f"{landing_commit}:{relative}"], cwd=repo, capture_output=True
        )
        if completed.returncode or hashlib.sha256(completed.stdout).hexdigest() != digest:
            raise ContentTddReceiptError("frozen_test_not_in_landing", relative)

    argv = _expanded_argv(repo, red_command)
    for relative, _digest in files:
        if Path(relative).name.startswith("test_") and relative not in argv:
            argv.append(relative)
    environment = {**os.environ, ACTIVATION_ENV: "1"}
    red = subprocess.run(argv, cwd=repo, capture_output=True, env=environment)
    if red.returncode != 1:
        code = "red_command_succeeded" if red.returncode == 0 else "red_command_invalid_exit"
        raise ContentTddReceiptError(code, "RED command must exit with test failures")
    if RED_ANCHOR_MARKER.encode() not in red.stdout + red.stderr:
        raise ContentTddReceiptError("red_anchor_missing", "deliberate RED anchor did not fire")
    pytest_index = argv.index("pytest")
    collect_argv = [*argv[: pytest_index + 1], "--collect-only", *argv[pytest_index + 1 :]]
    collected = subprocess.run(
        collect_argv, cwd=repo, capture_output=True, text=True, env=environment
    )
    if collected.returncode:
        raise ContentTddReceiptError("node_collection_failed", collected.stderr)
    nodeids = [line.strip() for line in collected.stdout.splitlines() if "::" in line]
    collected_paths = {nodeid.split("::", 1)[0] for nodeid in nodeids}
    missing = [
        relative
        for relative, _digest in files
        if Path(relative).name.startswith("test_")
        and not any(
            observed == relative or relative.endswith(f"/{observed}")
            for observed in collected_paths
        )
    ]
    if missing:
        raise ContentTddReceiptError(
            "red_test_coverage_incomplete", f"pytest did not collect frozen tests: {missing}"
        )

    stdout_path = out.with_name(f"{out.stem}.red.stdout.log")
    stderr_path = out.with_name(f"{out.stem}.red.stderr.log")
    out.parent.mkdir(parents=True, exist_ok=True)
    stdout_path.write_bytes(red.stdout)
    stderr_path.write_bytes(red.stderr)
    payload = {
        "schema": SCHEMA,
        "test_files": [{"path": path, "sha256": digest} for path, digest in files],
        "red_command": red_command,
        "red_argv": argv,
        "red_environment": {ACTIVATION_ENV: "1"},
        "red_nodeids": nodeids,
        "red_exit_status": red.returncode,
        "red_stdout_path": stdout_path.name,
        "red_stdout_sha256": _sha256(stdout_path),
        "red_stderr_path": stderr_path.name,
        "red_stderr_sha256": _sha256(stderr_path),
        "base_commit": base_commit,
        "base_tree_digest": _git(repo, "rev-parse", f"{base_commit}^{{tree}}"),
        "landing_ref": landing_ref,
        "landing_commit": landing_commit,
        "landing_tree_digest": _git(repo, "rev-parse", f"{landing_commit}^{{tree}}"),
    }
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return ContentTddReceipt.from_payload(payload, out)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify GOVLEAN content-bound TDD receipts")
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--receipt", type=Path, required=True)
    verify.add_argument("--repo", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = verify_content_tdd_receipt(receipt_path=args.receipt, repo=args.repo)
    except ContentTddReceiptError as exc:
        print(f"tdd_receipts: {exc.code}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"ok": result.ok, "landing_commit": result.landing_commit}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
