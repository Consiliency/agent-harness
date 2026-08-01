"""LEGIBLE (v10 SL-0) — bounded, fixed-adapter roadmap-assumption-probe audit.

Reads the closed ``roadmap_assumption_probe.v1`` sidecar
(``specs/roadmap-assumption-probes-v10.json``), evaluates each declared probe's
``expected`` clause against a real observation, and reports a typed per-probe
verdict. See plans/phase-plan-v10-LEGIBLE.md ("Assumption declarations use one
dedicated ``specs/roadmap-assumption-probes-v10.json`` sidecar...").

Every probe reaches its observation through exactly ONE seam,
:func:`observe_assumption_probe` (dispatched here by ``kind``); no probe row
carries a command, argv, shell, cwd, or env field, and none of the adapters
below accept one either — the closed ``subject``/``expected`` schema per kind
IS the caller-facing surface.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


PROBE_SIDECAR_REL = "specs/roadmap-assumption-probes-v10.json"
PROBE_SCHEMA = "roadmap_assumption_probe.v1"
CANONICAL_ROADMAP_REL = "specs/phase-plans-v10.md"
CANONICAL_PROBES_SHA256 = "bfb08073a28fcd9233b41fd681a879e3a8677435c7bf3c9dc6de6c00360ecc85"
CANONICAL_PROBE_IDS = (
    "LEGIBLE-A1-CONFORM-UNGATED", "LEGIBLE-A1-I118", "LEGIBLE-A1-PIN-SHA",
    "LEGIBLE-A1-PIN-TAG", "LEGIBLE-A1-PR102", "LEGIBLE-A1-PR377",
    "LEGIBLE-A1-SUBMISSION-DIGEST", "LEGIBLE-A1-TAG-DEREF", "LEGIBLE-A1-VERDICT-DIGEST",
    "LEGIBLE-A2-GP-PIN", "LEGIBLE-A2-I128", "LEGIBLE-A2-LOCAL-VERSION",
    "LEGIBLE-A2-NO-DEPENDENCY", "LEGIBLE-A3-EC14", "LEGIBLE-A3-EC4",
    "LEGIBLE-A3-NO-DEGRADED-GATE", "LEGIBLE-A3-REVIEWTRUTH-TRANSITION",
    "LEGIBLE-A4-DISCOVERY", "LEGIBLE-A4-PER-ENTRY", "LEGIBLE-A4-PR170",
    "LEGIBLE-A5-RATIFICATION", "LEGIBLE-A5-RETRACTION", "LEGIBLE-A5-SHARED-EPOCH",
)

_SIDECAR_TOP_KEYS = frozenset({"schema", "roadmap", "roadmap_sha256", "probes"})
_PROBE_KEYS = frozenset(
    {"id", "assumption", "kind", "subject", "expected", "source_anchor", "mutation_id", "positive_control_id"}
)
_FORBIDDEN_KEYS = frozenset({"command", "argv", "shell", "cwd", "env"})
ALLOWED_PROBE_KINDS = frozenset(
    {
        "github_issue", "github_pr", "github_comment", "github_ref", "remote_json_field",
        "repo_constant", "repo_digest", "release_identity", "ast_call_predicate",
        "roadmap_predicate", "manifest_behavior", "reviewtruth_fable_transition",
    }
)


class RoadmapAssumptionError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ProbeFinding:
    code: str
    detail: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.code}: {self.detail}"


@dataclass(frozen=True)
class ProbeVerdict:
    probe_id: str
    ok: bool
    finding: ProbeFinding | None = None


# ---------------------------------------------------------------------------
# Sidecar loading + closed-grammar validation


def _assert_no_executable_keys(node: Any, where: str) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _FORBIDDEN_KEYS:
                raise RoadmapAssumptionError("forbidden_key", f"{where}: forbidden executable key {key!r}")
            _assert_no_executable_keys(value, f"{where}.{key}")
    elif isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            _assert_no_executable_keys(value, f"{where}[{index}]")


def _numbered_assumption_block(roadmap_text: str, number: int) -> str:
    """The live numbered ``## Assumptions (fail-loud if wrong)`` block ``number``."""
    block: list[str] = []
    current: int | None = None
    in_section = False
    for line in roadmap_text.splitlines():
        if line.startswith("## Assumptions"):
            in_section = True
            continue
        if not in_section:
            continue
        if line.startswith("## "):
            break
        if line[:1].isdigit() and line[1:3] == ". ":
            current = int(line[0])
        if current == number:
            block.append(line)
    return "\n".join(block)


def load_probe_sidecar(repo: Path) -> dict:
    """Load and fully validate the closed assumption-probe sidecar."""
    repo = Path(repo)
    path = repo / PROBE_SIDECAR_REL
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RoadmapAssumptionError("missing_sidecar", f"cannot read {path}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RoadmapAssumptionError("malformed_sidecar", f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or set(data) != _SIDECAR_TOP_KEYS:
        raise RoadmapAssumptionError(
            "malformed_sidecar", "sidecar must contain exactly schema/roadmap/roadmap_sha256/probes"
        )
    if data["schema"] != PROBE_SCHEMA:
        raise RoadmapAssumptionError("unsupported_schema", f"unsupported sidecar schema: {data['schema']!r}")

    roadmap_rel = data["roadmap"]
    if roadmap_rel != CANONICAL_ROADMAP_REL:
        raise RoadmapAssumptionError(
            "sidecar_contract_drift", f"roadmap must be exactly {CANONICAL_ROADMAP_REL!r}"
        )
    roadmap_path = repo / roadmap_rel
    try:
        roadmap_bytes = roadmap_path.read_bytes()
    except OSError as exc:
        raise RoadmapAssumptionError("missing_roadmap", f"cannot read {roadmap_path}: {exc}") from exc
    digest = hashlib.sha256(roadmap_bytes).hexdigest()
    if digest != data["roadmap_sha256"]:
        raise RoadmapAssumptionError(
            "roadmap_digest_mismatch",
            f"sidecar roadmap_sha256 {data['roadmap_sha256']!r} != computed {digest!r}",
        )
    roadmap_text = roadmap_bytes.decode("utf-8")

    probes = data["probes"]
    if not isinstance(probes, list) or not probes:
        raise RoadmapAssumptionError("malformed_sidecar", "probes must be a nonempty array")
    ids = [probe.get("id") if isinstance(probe, dict) else None for probe in probes]
    if any(pid is None for pid in ids) or ids != sorted(ids):
        raise RoadmapAssumptionError("malformed_sidecar", "probes must be stable-sorted by id")
    probes_digest = hashlib.sha256(
        json.dumps(probes, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if tuple(ids) != CANONICAL_PROBE_IDS or probes_digest != CANONICAL_PROBES_SHA256:
        raise RoadmapAssumptionError(
            "probe_contract_drift",
            "probe declarations must equal the frozen 23-row v10 contract",
        )
    seen: set[str] = set()
    for probe in probes:
        if not isinstance(probe, dict) or set(probe) != _PROBE_KEYS:
            raise RoadmapAssumptionError(
                "malformed_probe", "probe must contain exactly the eight roadmap_assumption_probe.v1 keys"
            )
        probe_id = probe["id"]
        if not isinstance(probe_id, str) or not probe_id:
            raise RoadmapAssumptionError("malformed_probe", "probe id must be a nonempty string")
        if probe_id in seen:
            raise RoadmapAssumptionError("duplicate_probe_id", f"duplicate probe id: {probe_id}")
        seen.add(probe_id)
        if probe["kind"] not in ALLOWED_PROBE_KINDS:
            raise RoadmapAssumptionError("unsupported_kind", f"{probe_id}: unsupported kind {probe['kind']!r}")
        if probe["assumption"] not in (1, 2, 3, 4, 5):
            raise RoadmapAssumptionError("malformed_probe", f"{probe_id}: assumption must be 1..5")
        for field_name in ("subject", "expected"):
            value = probe[field_name]
            if not isinstance(value, dict) or not value:
                raise RoadmapAssumptionError("malformed_probe", f"{probe_id}.{field_name} must be a nonempty object")
            _assert_no_executable_keys(value, f"{probe_id}.{field_name}")
        anchor = probe["source_anchor"]
        if not isinstance(anchor, str) or not anchor:
            raise RoadmapAssumptionError("malformed_probe", f"{probe_id}: source_anchor must be nonempty")
        block = _numbered_assumption_block(roadmap_text, probe["assumption"])
        if anchor not in block:
            raise RoadmapAssumptionError(
                "anchor_not_found",
                f"{probe_id}: source_anchor not found in assumption block {probe['assumption']}",
            )
        for field_name in ("mutation_id", "positive_control_id"):
            if not isinstance(probe[field_name], str) or not probe[field_name]:
                raise RoadmapAssumptionError("malformed_probe", f"{probe_id}.{field_name} must be nonempty")

    return data


# ---------------------------------------------------------------------------
# Verdict evaluation — one generic, kind-agnostic vocabulary


def _classify_reviewtruth_transition(observation: Mapping[str, Any]) -> str | None:
    """Classify a raw reviewtruth_fable_transition observation into
    ``"pending"``, ``"resolved"``, or ``None`` (neither — fails loud)."""
    if (
        observation.get("issue_state") == "OPEN"
        and observation.get("native_fill_request") is False
        and observation.get("seat_result") == "UNAVAILABLE/tui_adapter_required"
        and observation.get("first_party_route_available") is True
        and observation.get("fable_leg") == "succeeded"
    ):
        return "pending"
    if (
        observation.get("issue_state") == "CLOSED"
        and observation.get("issue_disposition") in ("completed", "ratified")
        and observation.get("native_fill_request") is True
        and observation.get("verdict_bound") is True
        and observation.get("seat_count") == "FULL"
    ):
        return "resolved"
    return None


def _evaluate(expected: Mapping[str, Any], observation: Mapping[str, Any]) -> ProbeFinding | None:
    for key, value in expected.items():
        if key == "required_present":
            for field_name in value:
                if observation.get(field_name) is None:
                    return ProbeFinding("required_present_missing", f"{field_name} is missing or null")
        elif key == "required_atoms":
            atoms = observation.get("atoms", [])
            for atom in value:
                if atom not in atoms:
                    return ProbeFinding("required_atom_missing", f"missing atom: {atom!r}")
        elif key == "forbidden_atoms":
            atoms = observation.get("atoms", [])
            for atom in value:
                if atom in atoms:
                    return ProbeFinding("forbidden_atom_present", f"forbidden atom present: {atom!r}")
        elif key == "required_edges":
            edges = {tuple(edge) for edge in observation.get("edges", [])}
            for pair in value:
                if tuple(pair) not in edges:
                    return ProbeFinding("required_edge_missing", f"missing call edge: {tuple(pair)!r}")
        elif key == "fields":
            observed_fields = observation.get("fields", {})
            for field_name, expected_value in value.items():
                if observed_fields.get(field_name) != expected_value:
                    return ProbeFinding(
                        "field_mismatch",
                        f"{field_name}: expected {expected_value!r}, observed {observed_fields.get(field_name)!r}",
                    )
        elif key == "must_agree":
            if value:
                agreed = expected.get("agreed_value")
                values = observation.get("values", [])
                if not values or any(item != agreed for item in values):
                    return ProbeFinding("values_disagree", f"values {values!r} do not all equal {agreed!r}")
        elif key == "agreed_value":
            continue  # consumed by must_agree above
        elif key == "declared_states":
            classified = _classify_reviewtruth_transition(observation)
            if classified not in value:
                return ProbeFinding(
                    "unrecognized_transition_state",
                    f"observation classified as {classified!r}, expected one of {tuple(value)}",
                )
        else:
            if observation.get(key) != value:
                return ProbeFinding("value_mismatch", f"{key}: expected {value!r}, observed {observation.get(key)!r}")
    return None


def audit_roadmap_assumptions(
    repo: Path, probe_ids: Sequence[str] | None = None
) -> dict[str, ProbeVerdict]:
    """Audit every (or the named) probe in the roadmap-assumption sidecar.

    Returns ``{probe_id: ProbeVerdict}``. Every observation is obtained
    through exactly one seam, :func:`observe_assumption_probe`; a probe whose
    observation cannot be obtained (adapter/network/external failure) is
    reported as a typed ``not ok`` verdict rather than raised, so one probe's
    unavailability does not abort the audit of the others.
    """
    repo = Path(repo)
    data = load_probe_sidecar(repo)
    probes_by_id = {probe["id"]: probe for probe in data["probes"]}
    selected = tuple(probe_ids) if probe_ids is not None else tuple(probes_by_id)
    results: dict[str, ProbeVerdict] = {}
    for probe_id in selected:
        probe = probes_by_id[probe_id]
        try:
            observation = observe_assumption_probe(repo, probe)
        except Exception as exc:  # noqa: BLE001 - deliberately typed as a not-ok verdict
            results[probe_id] = ProbeVerdict(probe_id, False, ProbeFinding("observation_unavailable", str(exc)))
            continue
        finding = _evaluate(probe["expected"], observation)
        results[probe_id] = ProbeVerdict(probe_id, finding is None, finding)
    return results


# ---------------------------------------------------------------------------
# observe_assumption_probe — the ONE fixed adapter-dispatch boundary


def observe_assumption_probe(repo: Path, probe: Mapping[str, Any]) -> dict:
    """Dispatch ``probe["kind"]`` to its fixed adapter and return a raw
    observation dict. This is the ONE seam every probe's evidence crosses;
    callers (production and tests alike) never supply a command/route/env."""
    repo = Path(repo)
    kind = probe["kind"]
    subject = probe["subject"]
    if kind == "github_issue":
        return _observe_github_issue(subject)
    if kind == "github_pr":
        return _observe_github_pr(subject)
    if kind == "github_comment":
        return _observe_github_comment(subject, probe.get("expected", {}))
    if kind == "github_ref":
        return _observe_github_ref(subject)
    if kind == "remote_json_field":
        return _observe_remote_json_field(subject)
    if kind == "repo_constant":
        return _observe_repo_constant(repo, subject)
    if kind == "repo_digest":
        return _observe_repo_digest(subject)
    if kind == "release_identity":
        return _observe_release_identity(subject)
    if kind == "ast_call_predicate":
        return _observe_ast_call_predicate(subject)
    if kind == "roadmap_predicate":
        return _observe_roadmap_predicate(repo, subject)
    if kind == "manifest_behavior":
        return _observe_manifest_behavior(repo, subject)
    if kind == "reviewtruth_fable_transition":
        return _observe_reviewtruth_fable_transition(repo, subject)
    raise RoadmapAssumptionError("unsupported_kind", f"unsupported probe kind: {kind!r}")


# ---------------------------------------------------------------------------
# GitHub-backed adapters (require network + `gh` CLI auth; fail loud, never
# fabricated, when that external prerequisite is unavailable)


def _gh_json(*args: str, timeout: int = 20) -> Any:
    try:
        proc = subprocess.run(
            ["gh", *args], capture_output=True, text=True, timeout=timeout, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RoadmapAssumptionError("gh_unavailable", f"gh CLI unavailable: {exc}") from exc
    if proc.returncode != 0:
        raise RoadmapAssumptionError(
            "gh_call_failed", f"gh {' '.join(args)} failed (exit {proc.returncode}): {proc.stderr.strip()}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RoadmapAssumptionError("gh_bad_json", f"gh {' '.join(args)} returned non-JSON output") from exc


def _observe_github_issue(subject: Mapping[str, Any]) -> dict:
    data = _gh_json(
        "issue", "view", str(subject["number"]), "--repo", subject["repository"], "--json", "state",
    )
    return {"state": data.get("state")}


def _observe_github_pr(subject: Mapping[str, Any]) -> dict:
    data = _gh_json(
        "pr", "view", str(subject["number"]), "--repo", subject["repository"],
        "--json", "state,mergedAt,mergeCommit,baseRefName",
    )
    merge_commit = (data.get("mergeCommit") or {}).get("oid")
    observation: dict[str, Any] = {
        "state": data.get("state"),
        "merged_at": data.get("mergedAt"),
        "merge_commit_oid": merge_commit,
    }
    if merge_commit:
        observation["ancestor_of_default_branch"] = _remote_is_ancestor_of_default_branch(
            subject["repository"], merge_commit
        )
    else:
        observation["ancestor_of_default_branch"] = False
    return observation


def _observe_github_comment(subject: Mapping[str, Any], expected: Mapping[str, Any]) -> dict:
    data = _gh_json(
        "api", f"repos/{subject['repository']}/issues/comments/{subject['comment_id']}",
    )
    body = data.get("body", "")
    author = (data.get("user") or {}).get("login")
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    lowered = body.lower()
    atoms = [atom for atom in expected.get("required_atoms", []) if atom.lower() in lowered]
    return {"author": author, "sha256": digest, "atoms": atoms}


def _remote_default_branch(repository: str) -> str:
    data = _gh_json("api", f"repos/{repository}")
    branch = data.get("default_branch")
    if not branch:
        raise RoadmapAssumptionError("gh_bad_response", f"{repository} has no default_branch")
    return branch


def _remote_is_ancestor_of_default_branch(repository: str, sha: str) -> bool:
    """True iff ``sha`` is an ancestor of ``repository``'s default-branch tip,
    via GitHub's compare API (no local clone of the remote repository required:
    ``status`` is ``"behind"``/``"identical"`` exactly when ``head`` is reachable
    from ``base``)."""
    default_branch = _remote_default_branch(repository)
    data = _gh_json("api", f"repos/{repository}/compare/{default_branch}...{sha}")
    return data.get("status") in ("behind", "identical")


def _observe_github_ref(subject: Mapping[str, Any]) -> dict:
    data = _gh_json("api", f"repos/{subject['repository']}/git/refs/tags/{subject['tag']}")
    tag_object = data.get("object", {})
    peeled_sha = tag_object.get("sha")
    if tag_object.get("type") == "tag" and peeled_sha:
        # An annotated tag object; peel it to the commit it targets.
        tag_data = _gh_json("api", f"repos/{subject['repository']}/git/tags/{peeled_sha}")
        peeled_sha = tag_data.get("object", {}).get("sha", peeled_sha)
    if not peeled_sha:
        raise RoadmapAssumptionError("gh_bad_response", f"cannot resolve tag {subject['tag']!r}")
    reachable = _remote_is_ancestor_of_default_branch(subject["repository"], peeled_sha)
    return {"peeled_sha": peeled_sha, "reachable_from_default_branch": reachable}


def _observe_remote_json_field(subject: Mapping[str, Any]) -> dict:
    import base64

    data = _gh_json("api", f"repos/{subject['repository']}/contents/{subject['path']}")
    content = data.get("content", "")
    raw = base64.b64decode(content)
    parsed = json.loads(raw.decode("utf-8"))
    return {"fields": parsed}


# ---------------------------------------------------------------------------
# Local-repository adapters (no network required)


def _read_surface_value(repo: Path, surface: Mapping[str, Any]) -> str:
    if "file" in surface:
        text = (repo / surface["file"]).read_text(encoding="utf-8")
        match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
        if not match:
            raise RoadmapAssumptionError("surface_field_not_found", f"no version field in {surface['file']}")
        return match.group(1)
    module = importlib.import_module(surface["module"])
    return getattr(module, surface["attribute"])


def _observe_repo_constant(repo: Path, subject: Mapping[str, Any]) -> dict:
    if "surfaces" in subject:
        values = [_read_surface_value(repo, surface) for surface in subject["surfaces"]]
        return {"values": values}
    module = importlib.import_module(subject["module"])
    attribute = getattr(module, subject["attribute"])
    field_name = subject["field"]
    value = getattr(attribute, field_name) if not isinstance(attribute, Mapping) else attribute[field_name]
    return {"value": value}


def _observe_repo_digest(subject: Mapping[str, Any]) -> dict:
    module = importlib.import_module(subject["module"])
    attribute = getattr(module, subject["attribute"])
    pinned = getattr(attribute, subject["field"])
    git_sha = getattr(attribute, "contract_git_sha", None)
    source_owner = getattr(attribute, "source_owner", None)
    resource = subject["resource"]
    basename = resource.rsplit("/", 1)[-1]
    if git_sha and source_owner:
        try:
            data = _gh_json(
                "api", f"repos/{source_owner}/contents/schemas/{basename}?ref={git_sha}",
            )
            import base64

            computed = hashlib.sha256(base64.b64decode(data.get("content", ""))).hexdigest()
        except RoadmapAssumptionError:
            computed = _local_resource_digest(resource)
    else:
        computed = _local_resource_digest(resource)
    return {"algorithm": "sha256", "pinned": pinned, "computed": computed}


def _local_resource_digest(resource: str) -> str:
    try:
        from importlib import resources

        package_name, _, resource_rel = resource.partition("/")
        package_root = resources.files(package_name)
        return hashlib.sha256((package_root / resource_rel).read_bytes()).hexdigest()
    except Exception as exc:  # noqa: BLE001 - external contract package may be absent
        raise RoadmapAssumptionError(
            "vendored_contract_unavailable", f"cannot resolve {resource}: {exc}"
        ) from exc


def _observe_release_identity(subject: Mapping[str, Any]) -> dict:  # pragma: no cover - no probe uses this kind yet
    raise RoadmapAssumptionError("unsupported_kind", "release_identity has no bound probe in this landing")


def _observe_ast_call_predicate(subject: Mapping[str, Any]) -> dict:
    import ast as ast_module

    module_name = subject["module"]
    spec = importlib.util.find_spec(module_name)
    if spec is None or spec.origin is None:
        raise RoadmapAssumptionError("module_not_found", f"module not found: {module_name}")
    source = Path(spec.origin).read_text(encoding="utf-8")
    tree = ast_module.parse(source, filename=spec.origin)

    call_edges: set[tuple[str, str]] = set()

    class _Visitor(ast_module.NodeVisitor):
        def __init__(self) -> None:
            self._stack: list[str] = []

        def visit_FunctionDef(self, node: ast_module.FunctionDef) -> None:  # noqa: N802
            self._stack.append(node.name)
            self.generic_visit(node)
            self._stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef  # noqa: N815

        def visit_Call(self, node: ast_module.Call) -> None:  # noqa: N802
            callee = None
            if isinstance(node.func, ast_module.Name):
                callee = node.func.id
            elif isinstance(node.func, ast_module.Attribute):
                callee = node.func.attr
            if callee and self._stack:
                call_edges.add((self._stack[-1], callee))
            self.generic_visit(node)

    _Visitor().visit(tree)
    return {"edges": [list(edge) for edge in sorted(call_edges)]}


def _observe_manifest_behavior(repo: Path, subject: Mapping[str, Any]) -> dict:
    """LEGIBLE-A4-PER-ENTRY: one malformed manifest row must not hide valid siblings."""
    import json as _json
    import tempfile

    from . import plan_manifest

    valid_roadmap_rel = subject.get("valid_entry_roadmap", "specs/phase-plans-v10.md")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_repo = Path(tmp)
        (tmp_repo / "specs").mkdir(parents=True, exist_ok=True)
        (tmp_repo / "plans").mkdir(parents=True, exist_ok=True)
        roadmap_path = tmp_repo / valid_roadmap_rel
        roadmap_path.parent.mkdir(parents=True, exist_ok=True)
        roadmap_path.write_text("# Fixture roadmap\n\ncontent\n", encoding="utf-8")
        valid_plan = tmp_repo / "plans" / "phase-plan-v10-PROBEVALID.md"
        valid_plan.write_text(
            "---\nphase: PROBEVALID\nroadmap: " + valid_roadmap_rel + "\n---\n# PROBEVALID\n",
            encoding="utf-8",
        )
        manifest_path = tmp_repo / "plans" / "manifest.json"
        manifest_path.write_text(
            _json.dumps(
                {
                    "schema_version": 1,
                    "plans": [
                        {
                            "acceptance_criteria_count": None,
                            "created_at": "2026-06-01T00:00:00Z",
                            "file": "plans/phase-plan-v10-PROBEVALID.md",
                            "handoff_ref": None,
                            "if_gates_produced": [],
                            "lanes": [],
                            "lifecycle": [],
                            "owner_skill": "codex-plan-phase",
                            "phase_alias": "PROBEVALID",
                            "reflection_ref": None,
                            "roadmap_ref": {
                                "file": valid_roadmap_rel, "slug": "phase-plans-v10",
                                "status": "executing", "type": "phase",
                            },
                            "slug": "v10-PROBEVALID",
                            "status": "executing",
                            "task_summary": None,
                            "type": "phase",
                            "updated_at": "2026-06-01T00:00:00Z",
                        },
                        # A per-entry MALFORMED sibling row (missing required
                        # `file`) — validated per-entry per agent-harness#170.
                        {
                            "acceptance_criteria_count": None,
                            "created_at": "2026-06-01T00:00:00Z",
                            "file": "",
                            "handoff_ref": None,
                            "if_gates_produced": [],
                            "lanes": [],
                            "lifecycle": [],
                            "owner_skill": "codex-plan-phase",
                            "phase_alias": "PROBEINVALID",
                            "reflection_ref": None,
                            "roadmap_ref": None,
                            "slug": "v10-PROBEINVALID",
                            "status": "executing",
                            "task_summary": None,
                            "type": "phase",
                            "updated_at": "2026-06-01T00:00:00Z",
                        },
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        entries = plan_manifest.valid_phase_entries(manifest_path)
        slugs = {entry.slug for entry in (entries or ())}
        return {
            "invalid_sibling_excluded": "v10-PROBEINVALID" not in slugs,
            "valid_entry_discoverable": "v10-PROBEVALID" in slugs,
        }


# ---------------------------------------------------------------------------
# roadmap_predicate — bespoke, per-probe grounded checks over live roadmap text
#
# The frozen probe vocabulary (`atoms`) is a normalized description of a real
# textual/structural condition, not a literal quote requirement; each check
# below independently verifies the underlying condition against the roadmap's
# real committed bytes and reports the matching atom label only when the
# condition genuinely holds.

_CONFORM_UNGATED_ATOM = "CONFORM pin work is satisfiable against merged sources"
_CONFORM_GATED_ATOM = "CONFORM depends on spec#118 closing"
_NO_DEPENDENCY_ATOM = "phase requires governed-pipeline#128 closed"
_NO_DEGRADED_ATOM = "four-vendor exact-digest review required"
_DEGRADED_AUTHORIZED_ATOM = "degraded 3-of-4 promotion authorized"
_SHARED_EPOCH_ASSUMPTION_ATOM = "assumption-5: ONE shared monotonic epoch allocator"
_SHARED_EPOCH_FABPUB_ATOM = "FABPUB: ONE shared monotonic epoch allocator"
_RETRACTION_ASSUMPTION_ATOM = "assumption-5: publish byte-neutrality is RETRACTED"
_RETRACTION_FABPUB_ATOM = "EC-FABPUB-7: publish byte-neutrality is RETRACTED"
_NEUTRALITY_CLAIM_ATOM = "publish is byte-neutral"


def _phase_block(roadmap_text: str, alias: str) -> str:
    lines = roadmap_text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if re.match(rf"^### +Phase\s+\d+.*\({re.escape(alias)}\)\s*$", line):
            start = index
            continue
        if start is not None and line.startswith("### Phase"):
            return "\n".join(lines[start:index])
    if start is None:
        return ""
    return "\n".join(lines[start:])


def _ec_criterion_text(roadmap_text: str, criterion_id: str) -> str:
    for line in roadmap_text.splitlines():
        if line.lstrip().startswith(f"- [ ] {criterion_id} ") or line.lstrip().startswith(f"- [x] {criterion_id} "):
            return line
    return ""


def _observe_roadmap_predicate(repo: Path, subject: Mapping[str, Any]) -> dict:
    roadmap_path = repo / subject["roadmap"]
    text = roadmap_path.read_text(encoding="utf-8")
    predicate = subject.get("predicate")
    phase = subject.get("phase")
    criterion = subject.get("criterion")
    atoms: list[str] = []

    if predicate == "dependencies" and phase == "CONFORM":
        block = _phase_block(text, "CONFORM")
        assumption_block = _numbered_assumption_block(text, 1)
        haystack = block + "\n" + assumption_block
        gated = bool(re.search(r"spec#118\s+must\s+close|depends\s+on\s+spec#118\s+closing", haystack, re.IGNORECASE))
        if gated:
            atoms.append(_CONFORM_GATED_ATOM)
        if "NO LONGER externally gated" in haystack or "no longer externally gated" in haystack.lower():
            atoms.append(_CONFORM_UNGATED_ATOM)

    elif predicate == "closure-prerequisites":
        required = bool(re.search(r"phase\s+requires\s+governed-pipeline#128\s+closed", text, re.IGNORECASE))
        if required:
            atoms.append(_NO_DEPENDENCY_ATOM)

    elif predicate == "execution-policy":
        four_vendor = bool(re.search(r"four-vendor board|four reviewing seats|four-vendor exact-digest", text))
        no_degraded = "No degraded promotion" in text
        degraded_authorized = bool(re.search(r"degraded\s+3-of-4\s+promotion\s+authorized", text, re.IGNORECASE))
        if four_vendor and no_degraded:
            atoms.append(_NO_DEGRADED_ATOM)
        if degraded_authorized:
            atoms.append(_DEGRADED_AUTHORIZED_ATOM)

    elif criterion == "EC-REVIEWTRUTH-4":
        line = _ec_criterion_text(text, "EC-REVIEWTRUTH-4")
        for candidate_atom in ("FULL", "FLOOR-ONLY", "BELOW-FLOOR", "typed unfillable signal"):
            if candidate_atom in line:
                atoms.append(candidate_atom)

    elif criterion == "EC-REVIEWTRUTH-14":
        line = _ec_criterion_text(text, "EC-REVIEWTRUTH-14")
        for candidate_atom in ("NativeAgentLegRequest", "VERDICT is BOUND"):
            if candidate_atom in line:
                atoms.append(candidate_atom)
        if "rather than through a CLI/adapter" in line:
            atoms.append("no TUI adapter")

    elif predicate == "epoch-allocation":
        assumption_block = _numbered_assumption_block(text, 5)
        fabpub_block = _phase_block(text, "FABPUB")
        if "shared monotonic epoch" in assumption_block.lower():
            atoms.append(_SHARED_EPOCH_ASSUMPTION_ATOM)
        if "shared" in fabpub_block.lower() and "monotonic" in fabpub_block.lower() and "allocator" in fabpub_block.lower():
            atoms.append(_SHARED_EPOCH_FABPUB_ATOM)

    elif predicate == "publish-byte-neutrality":
        assumption_block = _numbered_assumption_block(text, 5)
        ec7 = _ec_criterion_text(text, "EC-FABPUB-7")
        if "retracted" in assumption_block.lower() and "byte-neutrality" in assumption_block.lower():
            atoms.append(_RETRACTION_ASSUMPTION_ATOM)
        if "retracted" in ec7.lower() and "byte-neutrality" in ec7.lower():
            atoms.append(_RETRACTION_FABPUB_ATOM)
        if re.search(r"publish is byte-neutral\b", text, re.IGNORECASE):
            atoms.append(_NEUTRALITY_CLAIM_ATOM)

    else:
        raise RoadmapAssumptionError("unsupported_predicate", f"unsupported roadmap_predicate: {subject!r}")

    return {"atoms": atoms}


# ---------------------------------------------------------------------------
# reviewtruth_fable_transition — closed subject, fixed adapter
#
# The real observation (a live GitHub issue snapshot, a metadata-only
# first-party Claude subscription capability probe, and one bounded Fable
# self-PTY leg) is performed by the ONE fixed adapter boundary owned by
# `legible_evidence` (`legible_evidence._invoke_reviewtruth_fable_adapter`),
# so both callers of `reviewtruth_fable_transition` observe the identical
# live state through the identical bounded/closed seam rather than each
# re-implementing its own external invocation. This module only flattens
# that nested raw observation into the flat classification vocabulary
# `_classify_reviewtruth_transition` consumes. A caller wanting the
# mocked/deterministic path patches `observe_assumption_probe` (as the frozen
# test suite does), never this function's public signature.


def _invoke_reviewtruth_fable_adapter(repo: Path, subject: Mapping[str, Any]) -> dict:
    from . import legible_evidence

    raw = legible_evidence._invoke_reviewtruth_fable_adapter(subject, repo=repo)
    return legible_evidence._flatten_reviewtruth_observation(raw)


def _observe_reviewtruth_fable_transition(repo: Path, subject: Mapping[str, Any]) -> dict:
    allowed_keys = {"repository", "issue", "model", "source_anchor"}
    if set(subject) - allowed_keys:
        raise RoadmapAssumptionError(
            "closed_subject_violation", f"unexpected reviewtruth_fable_transition subject keys: {set(subject) - allowed_keys}"
        )
    return _invoke_reviewtruth_fable_adapter(repo, subject)


__all__ = [
    "ALLOWED_PROBE_KINDS",
    "CANONICAL_PROBE_IDS",
    "PROBE_SCHEMA",
    "PROBE_SIDECAR_REL",
    "ProbeFinding",
    "ProbeVerdict",
    "RoadmapAssumptionError",
    "audit_roadmap_assumptions",
    "load_probe_sidecar",
    "observe_assumption_probe",
]
