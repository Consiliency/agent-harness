import importlib.metadata
import re
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib

import phase_loop_runtime
from _outside_agent_canonical import (
    assert_candidate_identity_only_document,
    runner_b2_evidence,
)
from phase_loop_runtime.conformance import (
    EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN,
    build_outside_agent_advisory_evidence,
    build_outside_agent_validation_verdict,
    serialize_outside_agent_advisory_evidence,
    serialize_outside_agent_validation_verdict,
)


RUNTIME_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = RUNTIME_ROOT.parent


def _require_repo_files(*paths: Path):
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        pytest.skip(
            "repo-root release docs/workflows are absent in standalone clean-room: "
            + ", ".join(missing)
        )


def _submission():
    return {
        "submission_schema_version": "outside_agent_submission.v0.1",
        "submission_kind": "work_request",
        "metadata": {
            "submission_id": "oa-release-1",
            "content_digest": "a" * 64,
        },
        "provenance_refs": [
            {"ref": "requests/oa-release-1.json", "digest": "b" * 64},
        ],
        "evidence_refs": [
            {"ref": "evidence/oa-release-1.json", "digest": "c" * 64},
        ],
    }


def _assert_candidate_identity_only_document(
    document: str, evidence: dict[str, object], anchor: str
) -> None:
    candidate_commit = evidence["candidate_commit"]
    candidate_tree = evidence["candidate_tree"]
    final_commit = evidence["final_commit"]
    final_tree = evidence["final_tree"]
    assert isinstance(candidate_commit, str) and isinstance(candidate_tree, str)
    assert isinstance(final_commit, str) and isinstance(final_tree, str)
    assert_candidate_identity_only_document(
        document,
        candidate_commit=candidate_commit,
        candidate_tree=candidate_tree,
        forbidden_identity_values={
            "final_commit": final_commit,
            "final_tree": final_tree,
        },
        anchor=anchor,
        require_candidate_identity=True,
    )


def test_package_version_matches_runtime_version():
    pyproject_path = RUNTIME_ROOT / "pyproject.toml"
    if not pyproject_path.exists():
        assert importlib.metadata.version("phase-loop-runtime") == phase_loop_runtime.__version__
        return

    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    assert pyproject["project"]["name"] == "phase-loop-runtime"
    assert pyproject["project"]["version"] == phase_loop_runtime.__version__


def test_outside_agent_public_release_surface_exports_validator_and_advisory_entrypoints():
    from phase_loop_runtime import conformance

    expected_exports = {
        "EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN",
        "OutsideAgentContractPin",
        "OutsideAgentAdvisoryEvidence",
        "OutsideAgentAdvisoryExitCode",
        "build_outside_agent_advisory_evidence",
        "serialize_outside_agent_advisory_evidence",
        "OutsideAgentValidationExitCode",
        "OutsideAgentValidationVerdict",
        "build_outside_agent_validation_verdict",
        "serialize_outside_agent_validation_verdict",
    }

    assert expected_exports <= set(conformance.__all__)
    for name in expected_exports:
        assert hasattr(conformance, name)


def test_real_validator_and_advisory_outputs_share_pinned_metadata_only_contract_evidence():
    validation_payload = serialize_outside_agent_validation_verdict(
        build_outside_agent_validation_verdict(_submission())
    )
    advisory_payload = serialize_outside_agent_advisory_evidence(
        build_outside_agent_advisory_evidence(_submission())
    )

    assert validation_payload["validator_version"] == phase_loop_runtime.__version__
    assert validation_payload["authority"] == "governed_pipeline_validator"
    assert advisory_payload["authority"] == "advisory"
    assert advisory_payload["redaction_posture"] == "metadata_only"
    assert advisory_payload["contract_pin"] == validation_payload["contract_pin"]
    assert validation_payload["vector_manifest_hash"] == EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN.vector_manifest_hash
    assert "accepted_for_merge" not in validation_payload
    assert "merge_verdict" not in validation_payload
    assert "accepted_for_merge" not in advisory_payload
    assert "merge_verdict" not in advisory_payload


def test_expected_outside_agent_contract_pin_release_fields_are_complete():
    pin = EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN

    assert pin.contract_package == "consiliency-spec"
    assert pin.contract_version
    assert re.fullmatch(r"[0-9a-f]{40}", pin.contract_git_sha)
    assert pin.schema_version == "outside_agent_submission.v0.1"
    assert pin.verdict_schema_version == "outside_agent_route_verdict.v0.1"
    assert pin.vector_manifest_name == "test-vectors/outside-agent/manifest.json"
    assert re.fullmatch(r"[0-9a-f]{64}", pin.vector_manifest_hash)
    assert pin.source_owner == "Consiliency/spec"
    assert pin.redaction_posture == "metadata_only"


def test_release_workflows_keep_version_build_and_publish_boundaries_explicit():
    consistency_path = REPO_ROOT / ".github/workflows/release-consistency.yml"
    publish_path = REPO_ROOT / ".github/workflows/publish-pypi.yml"
    _require_repo_files(consistency_path, publish_path)

    consistency = consistency_path.read_text(encoding="utf-8")
    publish = publish_path.read_text(encoding="utf-8")

    assert "push:" in consistency
    assert "tags: ['v*']" in consistency
    assert "pyproject version == __init__ __version__" in consistency
    assert "github.ref_type == 'tag'" in consistency
    assert "Trusted" in publish
    assert "Publishing (OIDC)" in publish
    assert "workflow_dispatch" in publish
    assert "pull_request:" in publish
    assert "Verify tag matches phase-loop-runtime version" in publish
    assert "python -m build --sdist --wheel --outdir dist phase-loop-runtime" in publish
    assert "Verify exact wheel in an isolated locked environment" in publish
    assert "--group test" in publish
    assert "--locked" in publish
    assert "--no-install-project" in publish
    assert "phase_loop_runtime.agy_canary_evidence" in publish
    # The canary surface is verified as `phase-loop <subcommand> --help` run from
    # the INSTALLED wheel, never as standalone console_scripts. A bare
    # `"agy-canary-finalize" in publish` substring check passed while the workflow
    # asserted `commands <= entry_points` against `[project.scripts]` -- which
    # declares only `phase-loop`/`codex-phase-loop`, so the release job would have
    # failed AFTER the build step, mid-publication. Pin the invocation FORM and the
    # exact subcommand set so neither can regress silently again.
    # Assert against EXECUTABLE lines, not raw file text: the workflow comment
    # explains what is deliberately not used, so a whole-file substring check would
    # collide with its own rationale (and a negative assertion would be satisfied by
    # deleting the explanation -- exactly backwards).
    publish_code = "\n".join(
        line for line in publish.splitlines() if not line.lstrip().startswith("#")
    )
    assert "commands <= entry_points" not in publish_code
    assert "console_scripts" not in publish_code
    assert '/tmp/phase-loop-release-wheel/bin/phase-loop "$sub" --help' in publish_code
    for _sub in (
        "agy-canary-probe",
        "agy-canary-clean-settings",
        "agy-canary-bootstrap-attest",
        "agy-canary-prepare",
        "agy-canary-verify",
        "agy-canary-finalize",
    ):
        assert _sub in publish_code, _sub
    # `agy-canary-cleanup` is not a registered subcommand; the CLI registers
    # `agy-canary-clean-settings`. Guard the name that shipped in the first draft.
    # Word-boundary match so `clean-settings` does not mask a re-introduced typo.
    assert not re.search(r"agy-canary-cleanup\b", publish_code)
    assert "sha256sum dist/* | tee release/SHA256SUMS" in publish
    assert "sha256sum --check release/SHA256SUMS" in publish
    assert "if: startsWith(github.ref, 'refs/tags/v')" in publish
    assert publish.count("python -m build --sdist --wheel") == 1
    assert "pypa/gh-action-pypi-publish" in publish
    assert "id-token: write" in publish
    assert "PYPI_API_TOKEN" not in publish
    assert "secrets." not in publish


def test_release_handoff_records_metadata_only_package_contract_and_dispatch_boundary():
    handoff_path = REPO_ROOT / "docs/releases/outside-agent-release-handoff.md"
    _require_repo_files(handoff_path)

    handoff = handoff_path.read_text(encoding="utf-8")
    pin = EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN

    required_terms = {
        "phase-loop-runtime",
        phase_loop_runtime.__version__,
        "validator version",
        "governed_pipeline_validator",
        "outside-agent-preflight",
        "outside-agent-validate",
        pin.contract_package,
        pin.contract_version,
        pin.contract_git_tag,
        pin.contract_git_sha,
        pin.schema_version,
        pin.verdict_schema_version,
        pin.submission_schema_sha256,
        pin.verdict_schema_sha256,
        pin.vector_manifest_name,
        pin.vector_manifest_hash,
        pin.source_owner,
        pin.redaction_posture,
        f"phase_loop_runtime-{phase_loop_runtime.__version__}-py3-none-any.whl",
        f"phase_loop_runtime-{phase_loop_runtime.__version__}.tar.gz",
        "maintainer",
        "not published",
        "not dispatched",
    }

    lowered = handoff.lower()
    for term in required_terms:
        assert term.lower() in lowered

    forbidden_terms = {
        "accepted_for_merge",
        "merge_verdict",
        "provider payload",
        "local env",
        "tbd",
        "todo",
        "/home/",
        "/mnt/",
    }
    for term in forbidden_terms:
        assert term not in lowered


def test_public_docs_point_to_handoff_without_claiming_release_dispatch():
    readme_path = REPO_ROOT / "README.md"
    changelog_path = REPO_ROOT / "CHANGELOG.md"
    _require_repo_files(readme_path, changelog_path)

    readme = readme_path.read_text(encoding="utf-8").lower()
    changelog = changelog_path.read_text(encoding="utf-8").lower()

    assert "docs/releases/outside-agent-release-handoff.md" in readme
    assert "docs/outside-agent-conformance.md" in readme
    assert "outside-agent-preflight" in readme
    assert "outside-agent-validate" in readme
    assert "governed-pipeline" in readme
    assert "outside-agent conformance runtime (oarelease)" in changelog
    assert "release handoff" in changelog
    assert "governed-pipeline pinning instructions" in changelog
    assert "maintainer-owned publish/tag/workflow-dispatch" in changelog
    assert "0.7.13" in changelog


def test_v7_disposition_records_merged_contract_and_final_installed_behavior(tmp_path):
    if not (RUNTIME_ROOT / "pyproject.toml").is_file():
        pytest.skip("repository-mode v7 disposition is absent in standalone clean-room")
    disposition_path = REPO_ROOT / "specs" / "phase-plans-v7.md"
    _require_repo_files(disposition_path)
    disposition = disposition_path.read_text(encoding="utf-8")

    assert "Consiliency/spec@v0.2.1" in disposition, (
        "CONFORM_RED::v7_disposition_records_merged_contract_and_final_installed_behavior"
    )
    assert EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN.contract_git_sha in disposition, (
        "CONFORM_RED::v7_disposition_records_merged_contract_and_final_installed_behavior"
    )
    pin = EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN
    required = {
        "OACORE-3",
        "OAREAL-2",
        pin.contract_git_tag,
        pin.contract_git_sha,
        pin.submission_schema_sha256,
        pin.verdict_schema_sha256,
        pin.vector_manifest_hash,
        "installed-package",
        "direct-wheel",
        "sdist-derived-wheel",
        "outside-agent-preflight",
        "outside-agent-validate",
        "three valid submissions",
        "route-verdict",
        "metadata_only",
        "not published",
        "not dispatched",
    }
    assert all(term.lower() in disposition.lower() for term in required), (
        "CONFORM_RED::v7_disposition_records_merged_contract_and_final_installed_behavior"
    )

    # Do not rebuild ambient HEAD or infer the last source-only commit.  The
    # disposition can bind only the pushed pre-document candidate; the runner
    # owns final identities after the document bytes have been sealed.
    evidence = runner_b2_evidence()
    if evidence is None:
        return
    anchor = "CONFORM_RED::v7_disposition_candidate_identity_only"
    assert evidence["candidate_commit"] != evidence["candidate_tree"], anchor
    assert evidence["final_commit"] != evidence["final_tree"], anchor
    _assert_candidate_identity_only_document(disposition, evidence, anchor)
    for label, archive in evidence["archives"].items():
        assert archive["sha256"] in disposition, (anchor, label)
        assert "phase_loop_runtime/conformance/_contract/VENDOR.json" in archive["members"], (anchor, label)

    candidate_document = tmp_path / "candidate-v7-disposition.md"
    candidate_document.write_text(
        "\n".join(
            (
                f"candidate implementation commit: `{evidence['candidate_commit']}`",
                f"candidate implementation tree: `{evidence['candidate_tree']}`",
                "Pre-doc A2 package evidence sha256: "
                + evidence["a2_package_evidence_sha256"],
                *(
                    f"{label} sha256: {archive['sha256']}"
                    for label, archive in evidence["archives"].items()
                ),
                "",
            )
        ),
        encoding="utf-8",
    )
    candidate_document_text = candidate_document.read_text(encoding="utf-8")
    _assert_candidate_identity_only_document(candidate_document_text, evidence, anchor)
    for forged in (
        candidate_document_text.replace(
            f"candidate implementation commit: `{evidence['candidate_commit']}`",
            f"final implementation commit: `{evidence['final_commit']}`",
        ),
        candidate_document_text.replace(
            evidence["candidate_tree"], evidence["final_tree"],
        ),
    ):
        assert forged != candidate_document_text
        with pytest.raises(AssertionError, match=anchor):
            _assert_candidate_identity_only_document(forged, evidence, anchor)
