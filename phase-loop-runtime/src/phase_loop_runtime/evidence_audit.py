"""Operator-callable evidence audit.

Spot-checks dirty-tree artifacts for the fake-evidence patterns surfaced
in the regen VISUALMATCH 2026-05-22 incident:

1. duplicate-content — multiple cited files share the same sha256
   (e.g., "19 prototype PNGs" all having md5 8d7f1750)
2. uniform-numeric — numeric arrays > 3 elements where all values are
   within epsilon (e.g., 19/19 similarity values at 0.999999)
3. missing-references — JSON artifacts cite path-shaped strings that
   don't exist on disk

This is a Tier 1.5 helper: codifies the operator spot-check protocol
that catches evidence faking the v20 IF-gate Tier 1 validator (which
only matches names, not content) can't see. Full Tier 2 evidence
verification with runner enforcement is deferred to a future roadmap.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


# Heuristic-shaped string that might be a file path. Triggers on slashes;
# we filter out URLs and obviously non-path strings downstream.
_PATH_HINT_RE = re.compile(r"^[A-Za-z0-9_.\-/]+\.[A-Za-z0-9]{1,8}$")
# Skip when the "string" is actually a URL or known non-path
_NON_PATH_PREFIXES = ("http://", "https://", "git@", "ssh://", "file://")


@dataclass(frozen=True)
class DuplicateContentFinding:
    sha256: str
    paths: tuple[str, ...]
    size_bytes: int


@dataclass(frozen=True)
class UniformNumericFinding:
    json_artifact: str
    json_pointer: str  # e.g., "$.routes[*].similarity"
    array_length: int
    unique_values: int
    sample_value: float


@dataclass(frozen=True)
class MissingReferenceFinding:
    json_artifact: str
    json_pointer: str
    missing_path: str


@dataclass(frozen=True)
class LooseUniformFinding:
    json_artifact: str
    json_pointer: str
    array_length: int
    mean: float
    stdev: float
    coefficient_of_variation: float


@dataclass(frozen=True)
class BoilerplateFinding:
    paths: tuple[str, ...]
    token_overlap: float
    shared_token_count: int
    sample_tokens: tuple[str, ...]


@dataclass(frozen=True)
class SizeDistributionFinding:
    sibling_directory: str
    paths: tuple[str, ...]
    mean_size_bytes: float
    stdev_size_bytes: float
    coefficient_of_variation: float


@dataclass
class EvidenceAuditResult:
    repo: str
    files_scanned: int = 0
    json_artifacts_scanned: int = 0
    duplicate_content: list[DuplicateContentFinding] = field(default_factory=list)
    uniform_numeric: list[UniformNumericFinding] = field(default_factory=list)
    missing_references: list[MissingReferenceFinding] = field(default_factory=list)
    tier2_enabled: bool = False
    loose_uniform: list[LooseUniformFinding] = field(default_factory=list)
    boilerplate_text: list[BoilerplateFinding] = field(default_factory=list)
    size_distribution: list[SizeDistributionFinding] = field(default_factory=list)

    def is_clean(self) -> bool:
        return not (
            self.duplicate_content
            or self.uniform_numeric
            or self.missing_references
            or self.loose_uniform
            or self.boilerplate_text
            or self.size_distribution
        )

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "repo": self.repo,
            "files_scanned": self.files_scanned,
            "json_artifacts_scanned": self.json_artifacts_scanned,
            "is_clean": self.is_clean(),
            "duplicate_content": [
                {"sha256": f.sha256, "paths": list(f.paths), "size_bytes": f.size_bytes}
                for f in self.duplicate_content
            ],
            "uniform_numeric": [
                {
                    "json_artifact": f.json_artifact,
                    "json_pointer": f.json_pointer,
                    "array_length": f.array_length,
                    "unique_values": f.unique_values,
                    "sample_value": f.sample_value,
                }
                for f in self.uniform_numeric
            ],
            "missing_references": [
                {"json_artifact": f.json_artifact, "json_pointer": f.json_pointer, "missing_path": f.missing_path}
                for f in self.missing_references
            ],
        }
        if self.tier2_enabled:
            payload["tier2_findings"] = {
                "loose_uniform": [
                    {
                        "json_artifact": f.json_artifact,
                        "json_pointer": f.json_pointer,
                        "array_length": f.array_length,
                        "mean": f.mean,
                        "stdev": f.stdev,
                        "coefficient_of_variation": f.coefficient_of_variation,
                    }
                    for f in self.loose_uniform
                ],
                "boilerplate_text": [
                    {
                        "paths": list(f.paths),
                        "token_overlap": f.token_overlap,
                        "shared_token_count": f.shared_token_count,
                        "sample_tokens": list(f.sample_tokens),
                    }
                    for f in self.boilerplate_text
                ],
                "size_distribution": [
                    {
                        "sibling_directory": f.sibling_directory,
                        "paths": list(f.paths),
                        "mean_size_bytes": f.mean_size_bytes,
                        "stdev_size_bytes": f.stdev_size_bytes,
                        "coefficient_of_variation": f.coefficient_of_variation,
                    }
                    for f in self.size_distribution
                ],
            }
        return payload


def _git_dirty_paths(repo: Path) -> list[str]:
    # --untracked-files=all so untracked directories are expanded to
    # individual file entries rather than collapsed to "dir/" — otherwise
    # we miss the actual files-in-untracked-dir case.
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=all"],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    paths: list[str] = []
    for line in result.stdout.splitlines():
        if len(line) < 3:
            continue
        # First 2 chars are status; rest is path (possibly with -> for renames)
        path = line[3:]
        if "->" in path:
            path = path.split("->", 1)[1].strip()
        paths.append(path.strip().strip('"'))
    return paths


def _sha256_of_file(path: Path, max_bytes: int = 50 * 1024 * 1024) -> tuple[str, int] | None:
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size > max_bytes:
        return None
    try:
        with open(path, "rb") as f:
            h = hashlib.sha256()
            h.update(f.read())
        return h.hexdigest(), size
    except OSError:
        return None


def detect_duplicate_content(
    files: Iterable[Path], min_duplicates: int = 3
) -> list[DuplicateContentFinding]:
    """Flag when N or more files share the same sha256.

    min_duplicates default of 3 is intentional — the regen incident had
    19 identical files; a value of 2 would false-positive on legitimate
    duplicates (e.g., template files copied verbatim). The pattern we
    want to catch is "many supposedly-distinct artifacts all the same."
    """
    by_hash: dict[str, list[tuple[str, int]]] = {}
    for p in files:
        if not p.is_file():
            continue
        h = _sha256_of_file(p)
        if h is None:
            continue
        sha, size = h
        by_hash.setdefault(sha, []).append((str(p), size))
    findings: list[DuplicateContentFinding] = []
    for sha, entries in by_hash.items():
        if len(entries) < min_duplicates:
            continue
        findings.append(
            DuplicateContentFinding(
                sha256=sha,
                paths=tuple(p for p, _ in entries),
                size_bytes=entries[0][1],
            )
        )
    return findings


def _walk_json(obj: Any, pointer: str = "$") -> Iterable[tuple[str, Any]]:
    yield pointer, obj
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_json(v, f"{pointer}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_json(v, f"{pointer}[{i}]")


def detect_uniform_numeric(
    json_path: Path, min_array_length: int = 4, epsilon: float = 1e-6
) -> list[UniformNumericFinding]:
    """Flag numeric arrays where all values are within epsilon of each other.

    Catches the regen pattern: 19/19 similarity scores at exactly 0.999999.
    Real comparison output has natural variance; uniform-to-6-decimals across
    a >=4-element array is a strong template-fill signal.

    Default min_array_length=4 because legitimate 2-3 element arrays often
    DO have identical values (e.g., [true, true] or [0, 0, 0] for a 3-axis
    score). 4+ identical values is suspicious.
    """
    try:
        text = json_path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []
    findings: list[UniformNumericFinding] = []
    # Collect all numeric arrays we encounter directly
    for pointer, value in _walk_json(data):
        if not isinstance(value, list):
            continue
        numerics = [x for x in value if isinstance(x, (int, float)) and not isinstance(x, bool)]
        if len(numerics) != len(value):
            # mixed-type arrays don't count
            continue
        if len(numerics) < min_array_length:
            continue
        unique = {round(x / epsilon) for x in numerics}
        if len(unique) == 1:
            findings.append(
                UniformNumericFinding(
                    json_artifact=str(json_path),
                    json_pointer=pointer,
                    array_length=len(numerics),
                    unique_values=1,
                    sample_value=float(numerics[0]),
                )
            )
            continue
        # Also catch the "all entries in an array of objects have identical numeric field"
        # pattern: iterate first-level-object-array → extract each object's numeric fields →
        # check uniformity. This catches "every entry has similarity=0.999999".
    # Second pass: object arrays where every object shares an identical numeric field
    for pointer, value in _walk_json(data):
        if not isinstance(value, list) or len(value) < min_array_length:
            continue
        if not all(isinstance(item, dict) for item in value):
            continue
        # For each common numeric field, check uniformity
        common_keys = set(value[0].keys())
        for item in value[1:]:
            common_keys &= set(item.keys())
        for key in common_keys:
            field_values = [item.get(key) for item in value]
            numerics = [v for v in field_values if isinstance(v, (int, float)) and not isinstance(v, bool)]
            if len(numerics) != len(field_values):
                continue
            unique = {round(x / epsilon) for x in numerics}
            if len(unique) == 1:
                findings.append(
                    UniformNumericFinding(
                        json_artifact=str(json_path),
                        json_pointer=f"{pointer}[*].{key}",
                        array_length=len(numerics),
                        unique_values=1,
                        sample_value=float(numerics[0]),
                    )
                )
    return findings


def detect_missing_references(
    json_path: Path, repo: Path
) -> list[MissingReferenceFinding]:
    """Flag JSON string values that look like paths but don't resolve on disk.

    Catches the pattern where artifacts cite paths that were never created
    (a planted manifest with no actual files behind it).
    """
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return []
    findings: list[MissingReferenceFinding] = []
    for pointer, value in _walk_json(data):
        if not isinstance(value, str) or not value:
            continue
        if any(value.startswith(prefix) for prefix in _NON_PATH_PREFIXES):
            continue
        if not _PATH_HINT_RE.match(value):
            continue
        if "/" not in value:
            continue
        # Resolve relative to repo
        candidate = (repo / value).resolve() if not Path(value).is_absolute() else Path(value)
        if not candidate.exists():
            findings.append(
                MissingReferenceFinding(
                    json_artifact=str(json_path),
                    json_pointer=pointer,
                    missing_path=value,
                )
            )
    return findings


def _population_stdev(values: list[float], mean: float) -> float:
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


def _loose_uniform_finding(
    *,
    json_path: Path,
    pointer: str,
    values: list[float],
    stdev_threshold: float,
) -> LooseUniformFinding | None:
    if len(set(values)) == 1:
        return None
    mean = sum(values) / len(values)
    stdev = _population_stdev(values, mean)
    coefficient = stdev if mean == 0 else stdev / abs(mean)
    if coefficient >= stdev_threshold:
        return None
    return LooseUniformFinding(
        json_artifact=str(json_path),
        json_pointer=pointer,
        array_length=len(values),
        mean=mean,
        stdev=stdev,
        coefficient_of_variation=coefficient,
    )


def detect_loose_uniform(
    json_path: Path, min_array_length: int = 4, stdev_threshold: float = 1e-3
) -> list[LooseUniformFinding]:
    """Flag near-uniform numeric arrays without double-reporting exact uniformity."""
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return []
    findings: list[LooseUniformFinding] = []
    for pointer, value in _walk_json(data):
        if isinstance(value, list):
            numerics = [float(x) for x in value if isinstance(x, (int, float)) and not isinstance(x, bool)]
            if len(numerics) == len(value) and len(numerics) >= min_array_length:
                finding = _loose_uniform_finding(
                    json_path=json_path,
                    pointer=pointer,
                    values=numerics,
                    stdev_threshold=stdev_threshold,
                )
                if finding is not None:
                    findings.append(finding)
            if len(value) < min_array_length or not all(isinstance(item, dict) for item in value):
                continue
            common_keys = set(value[0].keys())
            for item in value[1:]:
                common_keys &= set(item.keys())
            for key in common_keys:
                field_values = [item.get(key) for item in value]
                numerics = [
                    float(v)
                    for v in field_values
                    if isinstance(v, (int, float)) and not isinstance(v, bool)
                ]
                if len(numerics) != len(field_values):
                    continue
                finding = _loose_uniform_finding(
                    json_path=json_path,
                    pointer=f"{pointer}[*].{key}",
                    values=numerics,
                    stdev_threshold=stdev_threshold,
                )
                if finding is not None:
                    findings.append(finding)
    return findings


_TEXT_TOKEN_RE = re.compile(r"[A-Za-z0-9_./\\:-]+")


def _text_tokens(path: Path) -> set[str] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    tokens: set[str] = set()
    for raw in _TEXT_TOKEN_RE.findall(text.lower()):
        token = raw.strip("._-:/\\")
        if not token:
            continue
        if "/" in raw or "\\" in raw or _PATH_HINT_RE.match(raw):
            continue
        tokens.add(token)
    return tokens


def _token_overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def detect_boilerplate_text(
    file_group: Iterable[Path], token_overlap_threshold: float = 0.80, min_group_size: int = 3
) -> list[BoilerplateFinding]:
    """Flag groups of text files with high non-path token overlap."""
    entries: list[tuple[Path, set[str]]] = []
    for path in file_group:
        if not path.is_file():
            continue
        tokens = _text_tokens(path)
        if tokens:
            entries.append((path, tokens))

    neighbors: dict[int, set[int]] = {i: set() for i in range(len(entries))}
    for i, (_, left) in enumerate(entries):
        for j in range(i + 1, len(entries)):
            _, right = entries[j]
            if _token_overlap(left, right) >= token_overlap_threshold:
                neighbors[i].add(j)
                neighbors[j].add(i)

    findings: list[BoilerplateFinding] = []
    seen: set[int] = set()
    for start in range(len(entries)):
        if start in seen:
            continue
        stack = [start]
        component: set[int] = set()
        while stack:
            item = stack.pop()
            if item in component:
                continue
            component.add(item)
            stack.extend(neighbors[item] - component)
        seen |= component
        if len(component) < min_group_size:
            continue
        token_sets = [entries[i][1] for i in sorted(component)]
        shared = set.intersection(*token_sets)
        overlap = min(
            _token_overlap(token_sets[i], token_sets[j])
            for i in range(len(token_sets))
            for j in range(i + 1, len(token_sets))
        )
        if overlap < token_overlap_threshold:
            continue
        findings.append(
            BoilerplateFinding(
                paths=tuple(str(entries[i][0]) for i in sorted(component)),
                token_overlap=overlap,
                shared_token_count=len(shared),
                sample_tokens=tuple(sorted(shared)[:12]),
            )
        )
    return findings


def detect_size_distribution(
    file_paths: Iterable[Path], variance_threshold: float = 0.05, min_group_size: int = 3
) -> list[SizeDistributionFinding]:
    """Flag sibling-directory groups whose byte sizes are tightly clustered."""
    by_parent: dict[Path, list[Path]] = {}
    for path in file_paths:
        if path.is_file():
            by_parent.setdefault(path.parent, []).append(path)

    findings: list[SizeDistributionFinding] = []
    for parent, paths in sorted(by_parent.items(), key=lambda item: str(item[0])):
        if len(paths) < min_group_size:
            continue
        sizes = [float(path.stat().st_size) for path in paths]
        mean = sum(sizes) / len(sizes)
        stdev = _population_stdev(sizes, mean)
        coefficient = 0.0 if mean == 0 else stdev / mean
        if coefficient >= variance_threshold:
            continue
        findings.append(
            SizeDistributionFinding(
                sibling_directory=str(parent),
                paths=tuple(str(path) for path in sorted(paths)),
                mean_size_bytes=mean,
                stdev_size_bytes=stdev,
                coefficient_of_variation=coefficient,
            )
        )
    return findings


def run_evidence_audit(
    repo: Path,
    *,
    dirty_only: bool = True,
    min_duplicates: int = 3,
    uniform_epsilon: float = 1e-6,
    uniform_min_length: int = 4,
    tier2_enabled: bool = False,
    loose_uniform_stdev_threshold: float = 1e-3,
    boilerplate_token_overlap_threshold: float = 0.80,
    boilerplate_min_group_size: int = 3,
    size_distribution_variance_threshold: float = 0.05,
    size_distribution_min_group_size: int = 3,
) -> EvidenceAuditResult:
    """Run all three detectors against the repo's dirty (or full) tree.

    dirty_only=True scopes the audit to currently-modified/untracked paths,
    which is the typical pre-reconcile use case. dirty_only=False audits
    every tracked file (slower; useful for forensic sweeps).
    """
    repo = repo.expanduser().resolve()
    result = EvidenceAuditResult(repo=str(repo), tier2_enabled=tier2_enabled)

    if dirty_only:
        rels = _git_dirty_paths(repo)
        files = [repo / p for p in rels if (repo / p).is_file()]
    else:
        files = [p for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts]

    result.files_scanned = len(files)

    # Duplicate-content detector
    result.duplicate_content = detect_duplicate_content(files, min_duplicates=min_duplicates)

    # Per-JSON-artifact detectors
    json_artifacts = [p for p in files if p.suffix == ".json"]
    result.json_artifacts_scanned = len(json_artifacts)
    for jp in json_artifacts:
        result.uniform_numeric.extend(
            detect_uniform_numeric(jp, min_array_length=uniform_min_length, epsilon=uniform_epsilon)
        )
        result.missing_references.extend(detect_missing_references(jp, repo))
        if tier2_enabled:
            result.loose_uniform.extend(
                detect_loose_uniform(
                    jp,
                    min_array_length=uniform_min_length,
                    stdev_threshold=loose_uniform_stdev_threshold,
                )
            )

    if tier2_enabled:
        result.boilerplate_text = detect_boilerplate_text(
            files,
            token_overlap_threshold=boilerplate_token_overlap_threshold,
            min_group_size=boilerplate_min_group_size,
        )
        result.size_distribution = detect_size_distribution(
            files,
            variance_threshold=size_distribution_variance_threshold,
            min_group_size=size_distribution_min_group_size,
        )

    return result


def render_text(result: EvidenceAuditResult) -> str:
    """Human-readable rendering for the CLI."""
    lines = [
        f"evidence-audit: {result.repo}",
        f"  files scanned:           {result.files_scanned}",
        f"  json artifacts scanned:  {result.json_artifacts_scanned}",
        f"  duplicate-content findings:  {len(result.duplicate_content)}",
        f"  uniform-numeric findings:    {len(result.uniform_numeric)}",
        f"  missing-references findings: {len(result.missing_references)}",
    ]
    if result.tier2_enabled:
        lines.extend(
            [
                f"  tier2: loose-uniform findings:       {len(result.loose_uniform)}",
                f"  tier2: boilerplate-text findings:    {len(result.boilerplate_text)}",
                f"  tier2: size-distribution findings:   {len(result.size_distribution)}",
            ]
        )
    if result.is_clean():
        lines.append("")
        lines.append("CLEAN — no fake-evidence patterns detected.")
        return "\n".join(lines)
    lines.append("")
    lines.append("SUSPECT — review before reconciling:")
    for f in result.duplicate_content:
        lines.append(
            f"  duplicate-content (sha256={f.sha256[:12]}, size={f.size_bytes}B): {len(f.paths)} files share this hash"
        )
        for p in f.paths[:5]:
            lines.append(f"    {p}")
        if len(f.paths) > 5:
            lines.append(f"    ...and {len(f.paths) - 5} more")
    for f in result.uniform_numeric:
        lines.append(
            f"  uniform-numeric: {f.json_artifact} {f.json_pointer} — "
            f"{f.array_length} entries all = {f.sample_value!r}"
        )
    for f in result.missing_references:
        lines.append(
            f"  missing-reference: {f.json_artifact} {f.json_pointer} -> {f.missing_path!r}"
        )
    for f in result.loose_uniform:
        lines.append(
            f"  tier2: loose-uniform: {f.json_artifact} {f.json_pointer} — "
            f"{f.array_length} entries cv={f.coefficient_of_variation:.6g}"
        )
    for f in result.boilerplate_text:
        lines.append(
            f"  tier2: boilerplate-text: {len(f.paths)} files overlap={f.token_overlap:.2f}"
        )
        for p in f.paths[:5]:
            lines.append(f"    {p}")
        if len(f.paths) > 5:
            lines.append(f"    ...and {len(f.paths) - 5} more")
    for f in result.size_distribution:
        lines.append(
            f"  tier2: size-distribution: {f.sibling_directory} — "
            f"{len(f.paths)} files cv={f.coefficient_of_variation:.6g}"
        )
    return "\n".join(lines)
