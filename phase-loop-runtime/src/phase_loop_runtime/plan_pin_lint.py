"""Reject phase plans that pin unknowable future repository history."""

from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PlanPinFinding:
    category: str
    line: int
    text: str


PlanPinViolation = PlanPinFinding


_COMMIT_IDENTITY = re.compile(r"\b[0-9a-f]{40}\b|(?<=`)[0-9a-f]{7,39}(?=`)", re.IGNORECASE)
_CONTENT_DIGEST = re.compile(r"sha256:([0-9a-f]{64})\b", re.IGNORECASE)
_PATH = re.compile(r"(?<![\w.-])([\w.-]+(?:/[\w.@+-]+)+)(?![\w.-])")
_COMMIT_ORDINAL = re.compile(
    r"\b(?:commit\s+(?:number|count|index)\s*\d+|exactly\s+(?:one|two|three|\d+)\s+(?:final\s+)?(?:documentation\s+|repair\s+|implementation\s+|test\s+|production\s+)?commits?)",
    re.IGNORECASE,
)
_FUTURE_TOPOLOGY = re.compile(
    r"\b(?:two-parent|second parent|parent vector|future\b[^\n.]*\b(?:parent|merge commit))",
    re.IGNORECASE,
)


def _verified_roadmap_seal(text: str, repo: Path) -> tuple[int, str] | None:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    fields: dict[str, tuple[int, str]] = {}
    for index, line in enumerate(lines[1:], 2):
        if line.strip() == "---":
            break
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = (index, value.strip().strip("'\""))
    roadmap = fields.get("roadmap")
    seal = fields.get("roadmap_sha256")
    if not roadmap or not seal:
        return None
    path = Path(roadmap[1])
    path = path if path.is_absolute() else repo / path
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None
    return seal if seal[1] == digest else None


def _tracked_paths(repo: Path) -> frozenset[str]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=repo, check=False, capture_output=True
    )
    if completed.returncode:
        return frozenset()
    return frozenset(
        value.decode("utf-8") for value in completed.stdout.split(b"\0") if value
    )


def find_plan_pin_violations(
    text: str, repo: Path, plan_path: Path
) -> tuple[PlanPinViolation, ...]:
    del plan_path
    repo = Path(repo).resolve()
    verified_seal = _verified_roadmap_seal(text, repo)
    tracked = _tracked_paths(repo)
    findings: list[PlanPinViolation] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if _COMMIT_IDENTITY.search(line):
            findings.append(PlanPinViolation("future_commit_identity", line_number, line))
        if _CONTENT_DIGEST.search(line) or _COMMIT_IDENTITY.search(line):
            paths = {match.group(1).strip("`.,:;()[]") for match in _PATH.finditer(line)}
            if paths & tracked or any(f"`{path}`" in line for path in tracked):
                findings.append(PlanPinViolation("mutable_tracked_blob_pin", line_number, line))
        if _COMMIT_ORDINAL.search(line):
            findings.append(PlanPinViolation("commit_ordinal", line_number, line))
        if _FUTURE_TOPOLOGY.search(line):
            findings.append(PlanPinViolation("future_topology", line_number, line))
        if verified_seal and line_number == verified_seal[0]:
            findings = [
                finding
                for finding in findings
                if not (finding.line == line_number and finding.category == "future_commit_identity")
            ]
    return tuple(findings)
