"""Harness-run executable review findings against an exact staged Git tree."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Iterable
import xml.etree.ElementTree as ET

from . import review_stage
from .advisor_board import backing

if TYPE_CHECKING:
    from .panel_invoker import FindingFalsifier


FALSIFIER_OUTCOMES: tuple[str, ...] = (
    "red_on_head", "green_on_head", "apply_failed", "node_missing", "error",
)
_MAX_JUNIT_BYTES = 1_048_576


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
    if len(lines) < 5 or lines[:4] != [
        f"diff --git a/{path} b/{path}\n", "new file mode 100644\n",
        "--- /dev/null\n", f"+++ b/{path}\n",
    ]:
        return False
    match = re.fullmatch(r"@@ -0,0 \+1,([0-9]+) @@\n", lines[4])
    if match is None or len(lines[5:]) != int(match.group(1)):
        return False
    return all(line.startswith("+") for line in lines[5:])


def _outcome_from_junit(staged: Path, nodeid: str, returncode: int | None) -> str:
    path = staged / ".falsifier-junit.xml"
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return "node_missing" if returncode in (4, 5) else "error"
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_JUNIT_BYTES:
            return "error"
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            payload = stream.read(_MAX_JUNIT_BYTES + 1)
        if len(payload) > _MAX_JUNIT_BYTES:
            return "error"
        suite = ET.fromstring(payload)
    except (OSError, ET.ParseError, ValueError):
        return "error"
    finally:
        os.close(descriptor)
    cases = suite.findall(".//testcase")
    expected_name = nodeid.rsplit("::", 1)[-1]
    if not cases:
        return "node_missing" if returncode in (4, 5) else "error"
    if len(cases) != 1 or cases[0].get("name") != expected_name:
        return "error"
    case = cases[0]
    if case.find("skipped") is not None or case.find("error") is not None:
        return "error"
    if case.find("failure") is not None:
        return "red_on_head" if returncode == 1 else "error"
    return "green_on_head" if returncode == 0 else "error"


def run_finding_falsifier(
    *, falsifier: FindingFalsifier, seat_key: str,
    authorization: backing.FalsifierIsolationAuthorization, repo: Path,
    wall_clock_s: float, output_cap_bytes: int,
) -> FalsifierRunResult:
    """Run exactly the attached test node, never the seat's claimed result."""
    repo = Path(repo).resolve(strict=True)
    backing.revalidate_falsifier_isolation_authorization(authorization, repo=repo)
    if not isinstance(wall_clock_s, (int, float)) or wall_clock_s <= 0:
        raise ValueError("invalid falsifier wall-clock bound")
    if not isinstance(output_cap_bytes, int) or output_cap_bytes <= 0:
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
                    returncode, stdout, stderr, failure = review_stage.run_bounded_falsifier_node(
                        staged=staged, nodeid=falsifier.expected_nodeid,
                        wall_clock_s=float(wall_clock_s), output_cap_bytes=output_cap_bytes,
                    )
                    if failure:
                        detail = failure
                    else:
                        outcome = _outcome_from_junit(staged, falsifier.expected_nodeid, returncode)
                        if outcome == "red_on_head":
                            red_digest = hashlib.sha256(stdout + stderr).hexdigest()
                        # The clone is removed below; no live JUnit path is retained.
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        detail = str(exc)
    finally:
        if staged is not None:
            review_stage.remove_review_stage(staged)
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


def bound_findings_repair_context(findings: Iterable[object]) -> tuple[tuple[str, str], ...]:
    """Project bound node IDs and RED digests for a later repair step."""
    return tuple(
        (str(getattr(finding, "nodeid")), str(getattr(finding, "red_output_digest")))
        for finding in findings if getattr(finding, "code", None) == "finding_bound"
    )


def president_blocked_by_red_findings(findings: Iterable[object]) -> bool:
    """An unresolved bound RED finding cannot be sent to a president."""
    return any(getattr(finding, "code", None) == "finding_bound" for finding in findings)
