"""Harness-run executable review findings against an exact staged Git tree."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from . import review_stage
from .advisor_board import backing

if TYPE_CHECKING:
    from .panel_invoker import FindingFalsifier


FALSIFIER_OUTCOMES: tuple[str, ...] = (
    "red_on_head", "green_on_head", "apply_failed", "node_missing", "error",
)


@dataclass(frozen=True)
class FalsifierRunResult:
    outcome: str
    nodeid: str
    red_output_digest: str | None
    diff_digest: str
    junit_path: str | None
    detail: str | None
    record: dict[str, object]


def _git(repo: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, check=True,
    ).stdout


def _clean_exact_source(repo: Path, sha: str) -> None:
    root = _git(repo, "rev-parse", "--show-toplevel").decode().strip()
    if Path(root).resolve() != repo.resolve():
        raise ValueError("falsifier repository is not its canonical Git root")
    if _git(repo, "rev-parse", "HEAD").decode().strip() != sha:
        raise ValueError("falsifier reviewed SHA does not match source HEAD")
    if _git(repo, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("falsifier source is not clean")


def _one_new_test_diff(falsifier: FindingFalsifier) -> bool:
    finding_id = falsifier.finding_id
    path = f"phase-loop-runtime/tests/test_finding_{finding_id}.py"
    if not re.fullmatch(r"[A-Za-z0-9_]+", finding_id):
        return False
    if falsifier.new_test_path != path or not falsifier.expected_nodeid.startswith(path + "::"):
        return False
    suffix = falsifier.expected_nodeid[len(path) + 2:]
    if not suffix or any(character in suffix for character in "\x00\r\n"):
        return False
    lines = falsifier.diff.splitlines(keepends=True)
    if len(lines) < 5 or lines[:2] != [
        f"diff --git a/{path} b/{path}\n", "new file mode 100644\n",
    ]:
        return False
    position = 2
    if lines[position].startswith("index "):
        if not re.fullmatch(r"index [0-9a-f]{7,64}\.\.[0-9a-f]{7,64}(?: 100644)?\n", lines[position]):
            return False
        position += 1
    if lines[position:position + 2] != ["--- /dev/null\n", f"+++ b/{path}\n"]:
        return False
    position += 2
    if len(lines) <= position:
        return False
    match = re.fullmatch(r"@@ -0,0 \+1(?:,([0-9]+))? @@(?:[^\n]*)\n", lines[position])
    if match is None or len(lines[position + 1:]) != int(match.group(1) or "1"):
        return False
    return all(line.startswith("+") for line in lines[position + 1:])


def _outcome_from_report(
    report: dict[str, object] | None, nodeid: str, returncode: int | None,
) -> str:
    if returncode != 0 or not isinstance(report, dict):
        return "error"
    if report.get("schema") != "falsifier_pytest_report.v1":
        return "error"
    exit_code = report.get("exit")
    calls = report.get("calls")
    if exit_code in (4, 5) and calls == []:
        return "node_missing"
    if not isinstance(calls, list) or len(calls) != 1:
        return "error"
    call = calls[0]
    if not isinstance(call, dict) or call.get("nodeid") != nodeid or call.get("wasxfail"):
        return "error"
    if call.get("outcome") == "failed" and exit_code == 1:
        return "red_on_head"
    if call.get("outcome") == "passed" and exit_code == 0:
        return "green_on_head"
    return "error"


def run_finding_falsifier(
    *, falsifier: FindingFalsifier, seat_key: str,
    authorization: backing.FalsifierIsolationAuthorization, repo: Path,
    wall_clock_s: float, output_cap_bytes: int,
) -> FalsifierRunResult:
    """Run the attached node and record its observed, untrusted outcome."""
    repo = Path(repo).resolve(strict=True)
    backing.revalidate_falsifier_isolation_authorization(authorization, repo=repo)
    if (isinstance(wall_clock_s, bool) or not isinstance(wall_clock_s, (int, float))
            or not math.isfinite(wall_clock_s) or wall_clock_s <= 0):
        raise ValueError("invalid falsifier wall-clock bound")
    if (isinstance(output_cap_bytes, bool) or not isinstance(output_cap_bytes, int)
            or output_cap_bytes <= 0):
        raise ValueError("invalid falsifier output cap")
    diff_digest = hashlib.sha256(falsifier.diff.encode("utf-8")).hexdigest()
    outcome = "error"
    detail: str | None = None
    red_digest: str | None = None
    junit_path: str | None = None
    staged: Path | None = None
    try:
        _clean_exact_source(repo, authorization.reviewed_sha)
        backing.activate_falsifier_isolation_authorization(authorization, repo=repo)
        candidate_stage = review_stage.stage_review_tree(repo)
        if (candidate_stage.is_symlink()
                or candidate_stage.parent.resolve() != Path(tempfile.gettempdir()).resolve()
                or not candidate_stage.name.startswith(review_stage.REVIEW_STAGE_DIR_PREFIX)
                or candidate_stage.resolve() == repo
                or repo in candidate_stage.resolve().parents):
            raise ValueError("falsifier stage is not an independent clone")
        staged = candidate_stage
        review_stage.revalidate_falsifier_staged_tree(
            staged=staged, reviewed_sha=authorization.reviewed_sha,
        )
        _clean_exact_source(repo, authorization.reviewed_sha)
        if not _one_new_test_diff(falsifier):
            outcome = "apply_failed"
            detail = "diff does not create exactly the named new test"
        else:
            candidate = staged / falsifier.new_test_path
            if candidate.exists() or candidate.is_symlink():
                outcome = "apply_failed"
                detail = "falsifier test path already exists"
            else:
                applied = subprocess.run(
                    ["git", "-C", str(staged), "apply", "--no-index", "--", "-"],
                    input=falsifier.diff.encode("utf-8"), capture_output=True, check=False,
                )
                if applied.returncode or not candidate.is_file() or candidate.is_symlink():
                    outcome = "apply_failed"
                    detail = "new test diff did not apply"
                else:
                    returncode, stdout, stderr, failure, report = review_stage.run_bounded_falsifier_node(
                        staged=staged, nodeid=falsifier.expected_nodeid,
                        wall_clock_s=float(wall_clock_s), output_cap_bytes=output_cap_bytes,
                    )
                    if failure:
                        detail = failure
                    else:
                        outcome = _outcome_from_report(report, falsifier.expected_nodeid, returncode)
                        if outcome == "red_on_head":
                            red_digest = hashlib.sha256(stdout + stderr).hexdigest()
                        # The clone is removed below; no live JUnit path is retained.
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        detail = str(exc)
    finally:
        try:
            if staged is not None:
                review_stage.remove_review_stage(staged)
                if os.path.lexists(staged):
                    raise OSError("stage remains after removal")
        except Exception as exc:
            outcome = "error"
            red_digest = None
            detail = f"falsifier stage cleanup failed: {exc}"
        finally:
            backing.close_falsifier_isolation_authorization(authorization)
    record: dict[str, object] = {
        "schema": "finding_falsifier.v1",
        "authorization_identity": "public_board_falsifier.v1",
        "seat_key": seat_key,
        "reviewed_sha": authorization.reviewed_sha,
        "finding_id": falsifier.finding_id,
        "nodeid": falsifier.expected_nodeid,
        "outcome": outcome,
        "red_output_digest": red_digest,
        "diff_digest": diff_digest,
        "wall_clock_bound_s": float(wall_clock_s),
        "output_cap_bytes": output_cap_bytes,
    }
    return FalsifierRunResult(
        outcome=outcome, nodeid=falsifier.expected_nodeid,
        red_output_digest=red_digest, diff_digest=diff_digest,
        junit_path=junit_path, detail=detail, record=record,
    )
