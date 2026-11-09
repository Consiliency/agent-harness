"""Git-grounded, digest-bound observability projection (agent-harness#152).

The reconciler reads Git facts through ``git_discipline`` and classifies them
against the contract's pipeline-ref registry. Without a .consiliency manifest
it returns a skipped/no-consent result. With consent, its default local output is
``.phase-loop/observability/git-grounded-projection.json``; ``spec-render/git-grounded/``
is the Portal destination namespace. It hashes the exact JSON body bytes with SHA-256.

``build_projection_index_entry`` targets the frozen Portal adapter contract:
``raw-sha256``, the ``proj-code-sbom`` kind and ``text/markdown`` content type.
The body remains JSON; ``kind_is_misnomer`` and ``git_grounded_kind`` make that
compatibility mapping explicit. This module neither signs the projection nor
proves that a separately deployed Portal accepts or renders it.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..consiliency_layout import find_consiliency_manifest
from ..git_discipline import (
    classify_ref,
    evaluate_git_discipline,
    gather_pipeline_ref_states,
    gather_repo_ref_facts,
    load_protocol,
    load_ref_classes,
    self_heal_partition,
)
from ..git_discipline import RefState
from ..runtime_paths import ensure_phase_loop_excluded

#: Wire discriminator for the git-grounded projection body. Versioned; a bump is
#: a body-shape change, never a silent edit.
GIT_GROUNDED_PROJECTION_SCHEMA = "git-grounded-observability-projection.v1"

#: The body-digest domain the portal's projection-index verify path re-derives
#: for a non-cert body: ``sha256`` over the RAW body-file bytes (no domain
#: prefix, no re-canonicalization). We write the body bytes and hash the exact
#: bytes we wrote, so a portal re-derive over the same file binds.
RAW_SHA256_DOMAIN = "raw-sha256"

#: The closed ``projections.index.v1`` ``kind`` enum has no git-grounded value.
#: ``proj-code-sbom`` is the closest non-cert, ``raw-sha256`` slot the portal
#: runtime accepts, but the name is a MISNOMER for a git-reality projection --
#: recorded as provenance so the misfit is visible (see module docstring).
PORTAL_KIND_MISNOMER = "proj-code-sbom"

#: The git-grounded ``kind`` an ADDITIVE contract change would introduce; emitted
#: as provenance so a downstream aggregator can map it once the contract lands.
GIT_GROUNDED_KIND = "proj-git-grounded"


def _canonical_bytes(body: Mapping[str, Any]) -> bytes:
    """Canonical JSON bytes for ``body``: sorted keys, compact separators, one
    trailing newline. The digest is taken over THESE bytes and these exact bytes
    are what gets written to disk, so ``sha256(path.read_bytes())`` re-derives
    the pinned digest (no byte-drift false-green -- XG-4 lesson)."""
    return (
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def _sha256_hex(data: bytes) -> str:
    """``sha256`` over raw bytes, mirroring the portal's ``raw-sha256`` derive."""
    return hashlib.sha256(data).hexdigest()


def build_git_grounded_body(
    repo: Path,
    *,
    registry: Mapping[str, Any] | None = None,
    protocol: Mapping[str, Any] | None = None,
    ref_states: Sequence[RefState] | None = None,
    repo_label: str = "repo",
    predicate: str = "git-grounded-observability",
) -> dict[str, Any]:
    """Reconcile RAW GIT REALITY into a producer-agnostic projection BODY.

    Pure-ish: reads git through the injectable ``git_discipline`` readers and
    classifies against the contract SoT registry. The returned dict is the body
    that gets digest-bound; it carries NO absolute paths, credentials, or raw
    diffs -- only ref names, classifications, and dirty/owned path lists.
    """
    reg = load_ref_classes() if registry is None else registry
    if reg is None:
        # Contract-absent (< 0.4): no ref-class SoT to classify against.
        raise GitGroundedContractAbsent(
            "pipeline_ref_classes registry unavailable -- git-discipline contract "
            "predates 0.4; cannot reconcile git reality against a contract SoT."
        )
    proto = load_protocol() if protocol is None else protocol

    facts = gather_repo_ref_facts(repo)
    states = (
        list(ref_states)
        if ref_states is not None
        else gather_pipeline_ref_states(repo, reg)
    )
    partition = self_heal_partition(states, reg)
    findings = evaluate_git_discipline(
        current_branch=facts["current_branch"],
        dirty_paths=facts["dirty_paths"],
        local_branches=facts["local_branches"],
        registry=reg,
        protocol=proto,
    )

    current_cls = classify_ref(facts["current_branch"], reg) if facts["current_branch"] else None
    ref_classes = sorted(
        (
            {
                "name": branch,
                "owner": (cls := classify_ref(branch, reg)).owner,
                "class_id": cls.class_id,
                "lease_required": cls.lease_required,
                "deletable_by_self_heal": cls.deletable_by_self_heal,
            }
            for branch in facts["local_branches"]
        ),
        key=lambda entry: entry["name"],
    )

    # Discipline verdict: clean when no findings AND no unauthorized pipeline
    # writes surfaced. Producer-agnostic -- a human, an agent, or the pipeline
    # all reconcile identically because the verdict is a function of git reality
    # against the SoT, not of who wrote the change.
    discipline_verdict = "clean" if not findings else "findings"

    return {
        "schema": GIT_GROUNDED_PROJECTION_SCHEMA,
        "repo": repo_label,
        "predicate": predicate,
        "current_branch": facts["current_branch"],
        "current_branch_owner": current_cls.owner if current_cls else None,
        "ref_classes": ref_classes,
        "dirty_paths": sorted(facts["dirty_paths"]),
        "self_heal_partition": {
            "deletable_by_self_heal": sorted(partition["deletable_by_self_heal"]),
            "protected": sorted(partition["protected"]),
            "human_refs": sorted(partition["human_refs"]),
            "never_deleted_human_refs": sorted(partition["never_deleted_human_refs"]),
        },
        "discipline_verdict": discipline_verdict,
        "discipline_findings": sorted(
            (dict(finding) for finding in findings),
            key=lambda finding: (finding.get("code", ""), finding.get("branch", ""), finding.get("path", "")),
        ),
        "producer_agnostic": True,
    }


class GitGroundedContractAbsent(RuntimeError):
    """Raised when the git-discipline ref-class contract SoT is unavailable."""


class GitGroundedProjection:
    """A digest-bound git-grounded projection: the body, the exact bytes that
    body serializes to, and the ``raw-sha256`` digest over those bytes.

    The digest is the trust anchor. :meth:`write` persists the exact bytes and
    :meth:`verify` re-derives the digest from what is on disk, so the runtime's
    green means the portal's ``raw-sha256`` re-derive over the same file binds.
    """

    def __init__(self, body: Mapping[str, Any]) -> None:
        self.body: dict[str, Any] = dict(body)
        self.body_bytes: bytes = _canonical_bytes(self.body)
        self.body_digest: str = _sha256_hex(self.body_bytes)
        self.body_digest_domain: str = RAW_SHA256_DOMAIN

    def write(self, path: Path) -> Path:
        """Write the EXACT digested bytes to ``path`` (never a re-serialization,
        so on-disk bytes == digested bytes)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.body_bytes)
        return path

    def verify(self, path: Path) -> bool:
        """Re-derive the ``raw-sha256`` digest from the bytes ON DISK (not from
        a re-serialized dict) and bind against the pinned digest. This is the
        exact check the portal's verify path performs."""
        if not path.is_file():
            return False
        return _sha256_hex(path.read_bytes()) == self.body_digest


def build_projection_index_entry(
    projection: GitGroundedProjection,
    *,
    repo_label: str,
    body_path: str,
    manifest_path: str,
    predicate: str = "git-grounded-observability",
    gate_state: str | None = None,
) -> dict[str, Any]:
    """An index entry the portal's RUNTIME verify path (``isProjectionIndexEntry``
    + ``verifyProjCode``) ingests -- NOT a schema-valid ``projections.index.v1``
    entry (it deliberately omits the ``facts_path``/``facts_digest``/
    ``pinned_commit`` the schema requires for ``proj-code-*`` kinds; the portal
    runtime does not schema-validate, its load-bearing gate is the digest bind).

    The entry pins ``body_digest`` = the projection's ``raw-sha256`` digest over
    the emitted body bytes. The portal reads ``body_path`` relative to its OWN
    vendored root (not the producing repo), so a portal re-derive over the
    vendored COPY of those exact bytes binds the same digest -- the digest is the
    transport-integrity check ("these bytes, this digest"). ``body_path`` is the
    portal-vendor DESTINATION, not a path in the observed repo.

    ``kind`` is forced to the closed-enum ``proj-code-sbom`` MISNOMER (the only
    non-cert, ``raw-sha256`` slot the portal runtime accepts). The misfit is made
    explicit via ``git_grounded_kind`` / ``kind_is_misnomer`` provenance rather
    than hidden -- honest finding, not a forced fit (see module docstring).

    ``gate_state`` is a pure function of the projection's own
    ``discipline_verdict`` and is DERIVED here when not supplied (``clean`` ->
    ``pass``, anything else -> ``fail``). The portal surfaces ``gate_state``
    verbatim once the digest binds, so hardcoding ``"pass"`` would render a
    false-green for a repo whose body carries discipline findings. Deriving it
    from the body makes that false-green structurally impossible on the default
    path; an explicit override is honored only for callers that already hold an
    authoritative verdict.
    """
    if gate_state is None:
        verdict = projection.body.get("discipline_verdict")
        gate_state = "pass" if verdict == "clean" else "fail"
    return {
        "repo": repo_label,
        "kind": PORTAL_KIND_MISNOMER,
        "predicate": predicate,
        "body_path": body_path,
        "body_content_type": "text/markdown",
        "manifest_path": manifest_path,
        "body_digest": projection.body_digest,
        "body_digest_domain": projection.body_digest_domain,
        "maturity_label": "hash-checked",
        "gate_state": gate_state,
        # Provenance surfacing the honest contract-fit finding (NOT a schema
        # field the portal reads; an additive marker so the misnomer is visible
        # and a future git-grounded kind can map cleanly).
        "git_grounded_kind": GIT_GROUNDED_KIND,
        "kind_is_misnomer": True,
    }


def reconcile_git_grounded_projection(
    repo: Path,
    *,
    body_path: Path | None = None,
    registry: Mapping[str, Any] | None = None,
    protocol: Mapping[str, Any] | None = None,
    ref_states: Sequence[RefState] | None = None,
    repo_label: str = "repo",
    predicate: str = "git-grounded-observability",
    write: bool = True,
) -> dict[str, Any]:
    """Reconciler entrypoint: raw git reality -> digest-bound projection.

    Consent-gated (the liberty model): an opted-in repo (a
    ``.consiliency/manifest.json`` present) emits; an un-adopted repo is a clean
    no-op. Producer-agnostic -- reconciles ANY change in the repo, never
    tool-specific artifacts, so a human, this harness, an arbitrary agent, or
    the pipeline are all observed against the same contract SoT.

    Returns ``{"status": "skipped"|"emitted", ...}``. On ``emitted`` the result
    carries the ``body``, ``body_digest``, ``body_digest_domain``, the written
    ``body_path`` (when ``write``), and a portal-ingestable ``index_entry``.
    Never raises for consent/contract-absent; those are typed skips.
    """
    # Consent gate: opt-in, any tool. Mirrors reconcile_git_discipline.
    try:
        if find_consiliency_manifest(Path(repo)) is None:
            return {"status": "skipped", "reason": "no-consent"}
    except Exception:
        return {"status": "skipped", "reason": "no-consent"}

    try:
        body = build_git_grounded_body(
            repo,
            registry=registry,
            protocol=protocol,
            ref_states=ref_states,
            repo_label=repo_label,
            predicate=predicate,
        )
    except GitGroundedContractAbsent:
        return {"status": "skipped", "reason": "contract-absent"}

    projection = GitGroundedProjection(body)

    # EMIT + HANDOFF (the transport-agnostic model). The runtime EMITS the
    # digested bytes to its OWN native, git-EXCLUDED observability surface under
    # ``.phase-loop/`` (never a repo-tracked file, so the artifact never appears
    # in the repo's own ``git status`` and the reconcile stays deterministic --
    # the observer does not perturb the observed). ``entry.body_path`` is the
    # portal-vendor DESTINATION (``spec-render/...``, the portal's own vendored
    # namespace, NOT a directory in the observed repo); a portal-side vendoring
    # step places THESE EXACT BYTES there. ``body_digest`` is precisely the
    # integrity check that transport did not alter them -- so the guarantee is
    # "these bytes, this digest", invariant of which root serves them (exactly
    # how certified/portal projections already work: producer emits, portal
    # vendors, digest binds across).
    portal_body_rel = _portal_vendor_body_path()
    manifest_rel = "spec-render/git-grounded/manifest.json"
    target = body_path if body_path is not None else _default_body_path(repo)

    index_entry = build_projection_index_entry(
        projection,
        repo_label=repo_label,
        body_path=portal_body_rel,
        manifest_path=manifest_rel,
        predicate=predicate,
    )

    result: dict[str, Any] = {
        "status": "emitted",
        "schema": GIT_GROUNDED_PROJECTION_SCHEMA,
        "body": projection.body,
        "body_digest": projection.body_digest,
        "body_digest_domain": projection.body_digest_domain,
        # The portal-vendor destination the emitted bytes hand off to.
        "portal_body_path": portal_body_rel,
        "index_entry": index_entry,
    }
    if write:
        # Exclude BEFORE writing so the artifact never lands in git status even
        # on the first reconcile (deterministic self-observation).
        ensure_phase_loop_excluded(Path(repo))
        written = projection.write(target)
        result["body_path"] = str(written)
        # Verify against the exact bytes we emitted -- the transport-invariant
        # guarantee (sha256(emitted bytes) == pinned digest), which is what a
        # portal re-derive over the vendored copy of these bytes also checks.
        result["verified"] = projection.verify(written)
    return result


def _portal_vendor_body_path() -> str:
    """The portal-vendor DESTINATION for the emitted body: the portal's own
    ``spec-render/``-prefixed vendored namespace (satisfies the portal's
    ``isSafeVendoredPath``), NOT a path in the observed repo. A portal-side
    vendoring step places the emitted bytes here; the digest binds across."""
    return "spec-render/git-grounded/observability.json"


def _default_body_path(repo: Path) -> Path:
    """Runtime-native emission location: under the canonical, git-excluded
    ``.phase-loop/`` observability surface (never a repo-tracked file, never a
    sibling repo). This is where the runtime WRITES; the portal-vendor
    destination is where those bytes hand off to."""
    return Path(repo) / ".phase-loop" / "observability" / "git-grounded-projection.json"


__all__ = [
    "GIT_GROUNDED_PROJECTION_SCHEMA",
    "RAW_SHA256_DOMAIN",
    "PORTAL_KIND_MISNOMER",
    "GIT_GROUNDED_KIND",
    "GitGroundedContractAbsent",
    "GitGroundedProjection",
    "build_git_grounded_body",
    "build_projection_index_entry",
    "reconcile_git_grounded_projection",
]
