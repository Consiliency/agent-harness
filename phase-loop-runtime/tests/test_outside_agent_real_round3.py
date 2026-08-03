"""Round-3 hardening for the governed-pipeline outside-agent validator.

Two blockers, each failing-first against the pre-fix base:

* **Blocker 1 — crash-open on non-list evidence containers.** The semantic
  cross-field pass iterated ``evidence_refs`` / ``source_bundle_refs`` before
  checking they were lists, so a scalar (``evidence_refs: 1``) raised
  ``TypeError`` — the caller got an exception, not the required blocked
  ``MALFORMED_INPUT`` verdict. A validator that *crashes* on malformed input is
  failing open operationally. The fix must return a BLOCKED verdict with
  ``exit_code == MALFORMED_INPUT`` (proving the schema catches the non-array),
  NOT merely "no exception" — a silent skip that returned PASS would be a
  strictly-worse fail-open (agent-harness#371 round 3).

* **Blocker 2 — sixth secret-leak channel: ``--submitted-ref``.** Submitted
  refs were path-normalized but never secret-scanned, then serialized
  unconditionally. A ref carrying the validator's own ``sk-`` marker rode out
  with ``status="pass"``; and any submitted ref rode out even when the body made
  the verdict BLOCKED. Structural (path) validation and safety redaction are
  SEPARATE passes: a secret ref must flip the verdict BLOCKED
  (``REDACTION_VIOLATION``), and every BLOCKED verdict must surface an EMPTY
  ``submitted_refs`` projection — mirroring the evidence_refs projection gate.
"""
from __future__ import annotations

import json

import pytest
from _outside_agent_canonical import clean_submission, source_bundle_mismatch_submission

from phase_loop_runtime.conformance import (
    OutsideAgentValidationExitCode,
    build_outside_agent_validation_verdict,
    serialize_outside_agent_validation_verdict,
)
from phase_loop_runtime.conformance.outside_agent_core import (
    OutsideAgentConformanceVerdict,
    OutsideAgentEvidenceRef,
    OutsideAgentVerdictStatus,
)
from phase_loop_runtime.conformance.outside_agent_pin import (
    EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN,
)
from phase_loop_runtime.conformance.outside_agent_real import (
    OutsideAgentSubmittedRef,
    OutsideAgentValidationVerdict,
)

_SECRET_REF = "notes/sk-ABCDEF0123456789deadbeefcafef00d.md"


# --------------------------------------------------------------------------
# Blocker 1 — non-list evidence containers must BLOCK (MALFORMED), never crash.
# --------------------------------------------------------------------------


# A battery of malformed evidence-container shapes (upstream Consiliency/spec#118
# pins the same standard across 11 shapes). ``[]`` is EXCLUDED — an empty array is
# schema-VALID under the vendored contract, so it belongs to the drift finding, not
# here. Every other shape is a schema-type violation that must BLOCK, never crash.
_MALFORMED_CONTAINER_SHAPES = [
    pytest.param(1, id="int"),
    pytest.param(3.14, id="float"),
    pytest.param(True, id="bool"),
    pytest.param("not-a-list", id="str"),
    pytest.param(None, id="none"),
    pytest.param({}, id="empty-dict"),
    pytest.param({"a": 1}, id="nonempty-dict"),
    pytest.param([1], id="list-of-scalar"),
    pytest.param([None], id="list-of-null"),
    pytest.param([[]], id="list-of-list"),
    pytest.param([{}], id="list-of-empty-object"),
]


@pytest.mark.parametrize("bad", _MALFORMED_CONTAINER_SHAPES)
def test_malformed_evidence_refs_blocks_malformed_not_crash(bad: object) -> None:
    """Totality, not sequencing luck. The guard lives INSIDE the traversal helper,
    so the crash cannot recur even if a future edit reorders the semantic pass ahead
    of schema validation. Pre-fix, the scalar shapes raised TypeError (RED); the
    assertion is BLOCKED + ``MALFORMED_INPUT`` (schema supplies the block), NOT
    merely "no exception" — a guard that skipped the scalar and returned PASS would
    be a strictly-worse fail-open."""
    submission = clean_submission("work_request")
    submission["evidence_refs"] = bad

    verdict = build_outside_agent_validation_verdict(submission)

    assert verdict.verdict.status is OutsideAgentVerdictStatus.BLOCKED
    assert verdict.exit_code == OutsideAgentValidationExitCode.MALFORMED_INPUT
    assert any(b.code == "schema_validation_failed" for b in verdict.verdict.blockers)


@pytest.mark.parametrize("bad", _MALFORMED_CONTAINER_SHAPES)
def test_malformed_source_bundle_refs_blocks_malformed_not_crash(bad: object) -> None:
    """Nested container, same standard: a non-array ``source_bundle_refs`` inside an
    otherwise-valid evidence ref must BLOCK via the schema, never crash the traversal."""
    submission = clean_submission("work_request")
    assert submission.get("evidence_refs"), "canonical work_request must carry evidence_refs"
    submission["evidence_refs"][0]["source_bundle_refs"] = bad

    verdict = build_outside_agent_validation_verdict(submission)

    assert verdict.verdict.status is OutsideAgentVerdictStatus.BLOCKED
    assert verdict.exit_code == OutsideAgentValidationExitCode.MALFORMED_INPUT
    assert any(b.code == "schema_validation_failed" for b in verdict.verdict.blockers)


# --------------------------------------------------------------------------
# Blocker 2 — submitted-ref secret channel + blocked-projection gate.
# --------------------------------------------------------------------------


def test_clean_submitted_ref_on_pass_is_emitted_positive_control() -> None:
    """Positive control: the emit path is real, so the emptiness assertions below
    are non-vacuous — a clean ref on a PASS body IS serialized."""
    payload = serialize_outside_agent_validation_verdict(
        build_outside_agent_validation_verdict(
            clean_submission("work_request"),
            submitted_refs=("docs/legit-result.md",),
        )
    )
    assert payload["status"] == "pass"
    assert payload["submitted_refs"] == ["docs/legit-result.md"]


def test_secret_submitted_ref_blocks_and_is_never_emitted() -> None:
    validation = build_outside_agent_validation_verdict(
        clean_submission("work_request"),
        submitted_refs=(_SECRET_REF,),
    )
    payload = serialize_outside_agent_validation_verdict(validation)

    # Safety pass flips an otherwise-PASS body to BLOCKED (redaction posture),
    # independent of structural path validation.
    assert payload["status"] == "blocked"
    assert payload["exit_code"] == int(OutsideAgentValidationExitCode.REDACTION_VIOLATION)
    # The blocked projection is empty AND the secret marker appears nowhere.
    assert payload["submitted_refs"] == []
    assert "sk-" not in json.dumps(payload)


def test_blocked_body_empties_submitted_refs() -> None:
    """Blocker 2b: a clean ref must not ride out when the BODY is blocked."""
    payload = serialize_outside_agent_validation_verdict(
        build_outside_agent_validation_verdict(
            source_bundle_mismatch_submission(),
            submitted_refs=("docs/legit-result.md",),
        )
    )
    assert payload["status"] == "blocked"
    assert payload["submitted_refs"] == []


@pytest.mark.parametrize(
    "inject",
    [
        # top-level open map (additionalProperties error at the parent object),
        lambda s: s.__setitem__("sk-DEADBEEFsecretkey0123456789abcdef", "x"),
        # nested inside a conditional 'then' target object,
        lambda s: s.setdefault("work_request", {}).__setitem__(
            "sk-DEADBEEFsecretkey0123456789abcdef", "x"
        ),
        # nested inside an evidence ref ($defs.evidence_ref, closed object),
        lambda s: s["evidence_refs"][0].__setitem__(
            "sk-DEADBEEFsecretkey0123456789abcdef", "x"
        ),
    ],
)
def test_secret_shaped_key_never_rides_out_via_blocker_ref(inject) -> None:
    """`blocker.ref` is the OTHER ref-producer (`_ref_for_error`), and it does NOT
    apply the redaction walker's key-redaction. That is safe ONLY because the
    packaged schema is closed at every object level (no patternProperties /
    propertyNames / additionalProperties:true), so a schema error's json_path can
    never include an arbitrary submitter key — it points at the closed parent. This
    guard makes that premise executable: if a future schema opens a map and a
    secret-shaped key starts riding out through a blocker ref, this fails."""
    submission = clean_submission("work_request")
    assert submission.get("evidence_refs")
    inject(submission)

    payload = serialize_outside_agent_validation_verdict(
        build_outside_agent_validation_verdict(submission)
    )
    assert payload["status"] == "blocked"
    assert "sk-" not in json.dumps(payload)


def test_malformed_non_object_submission_empties_submitted_refs() -> None:
    """The ``not isinstance(submission, Mapping)`` path must also gate the
    projection — a malformed verdict is BLOCKED, so submitted_refs stays empty."""
    payload = serialize_outside_agent_validation_verdict(
        build_outside_agent_validation_verdict(
            ["not", "an", "object"],
            submitted_refs=("docs/legit-result.md",),
        )
    )
    assert payload["status"] == "blocked"
    assert payload["submitted_refs"] == []


# --------------------------------------------------------------------------
# Option C — serialization-boundary backstop (single choke point).
#
# The construction-time scans give the CORRECT verdict/exit for secrets they see;
# the boundary makes "no secret-shaped value is ever serialized" a property of the
# ONE sink, independent of channel enumeration. To prove the sink holds on its own
# it must be driven DIRECTLY — constructing via build_* would let the construction
# scan catch the secret first, and the falsifier would die upstream (the vacuity the
# reviewer named). So these build an OutsideAgentValidationVerdict by hand.
# --------------------------------------------------------------------------


def _direct_validation(*, evidence_refs=(), submitted_refs=(), status=OutsideAgentVerdictStatus.PASS):
    pin = EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN
    verdict = OutsideAgentConformanceVerdict(
        verdict_schema_version=pin.verdict_schema_version,
        submission_kind=None,
        status=status,
        blockers=(),
        contract_pin=pin,
        input_digest="a" * 64,
        provenance_refs=tuple(ref.ref for ref in evidence_refs),
        evidence_refs=tuple(evidence_refs),
        redaction_posture=pin.redaction_posture,
        metadata={"source_owner": pin.source_owner},
    )
    return OutsideAgentValidationVerdict(
        authority="governed_pipeline_validator",
        validator_version="test-version",
        exit_code=OutsideAgentValidationExitCode.PASS,
        verdict=verdict,
        submitted_refs=tuple(OutsideAgentSubmittedRef(ref=ref) for ref in submitted_refs),
    )


def test_boundary_backstop_passes_clean_verdict_positive_control() -> None:
    """Non-vacuity: the boundary is NOT always-on. A clean directly-built verdict
    serializes normally and its projections are emitted — so the fail-closed
    assertions below prove the sweep fired, not that the sink is inert."""
    payload = serialize_outside_agent_validation_verdict(
        _direct_validation(
            evidence_refs=(OutsideAgentEvidenceRef(ref="docs/clean.md", digest="a" * 64, kind="documentation"),),
            submitted_refs=("src/agent.py",),
        )
    )
    assert payload["status"] == "pass"
    assert payload["evidence_refs"] == [{"ref": "docs/clean.md", "digest": "a" * 64, "kind": "documentation"}]
    assert payload["submitted_refs"] == ["src/agent.py"]


def test_boundary_backstop_blocks_secret_that_bypassed_construction_scan() -> None:
    """Forced fire: a secret injected straight into the verdict (construction scan
    bypassed) must be caught by the SINK, which fails closed to a blocked doc."""
    secret_ref = "notes/sk-ABCDEF0123456789deadbeefcafef00d.md"
    payload = serialize_outside_agent_validation_verdict(
        _direct_validation(
            evidence_refs=(OutsideAgentEvidenceRef(ref=secret_ref, digest="a" * 64, kind="documentation"),),
        )
    )
    assert payload["status"] == "blocked"
    assert payload["exit_code"] == int(OutsideAgentValidationExitCode.REDACTION_VIOLATION)
    assert payload["evidence_refs"] == []
    assert payload["submitted_refs"] == []
    assert "sk-" not in json.dumps(payload)


def test_boundary_fail_closed_document_echoes_no_submitter_content() -> None:
    """Condition 3: the fail-closed document is built from constants + the frozen pin
    only, so it echoes NEITHER the secret marker NOR the submitter ref/path/kind that
    tripped the sweep — a redaction doc that repeated the redacted value would be the
    exact shape of the leak it closes. Inject through BOTH projection channels."""
    marker = "sk-DEADBEEFcafef00d0123456789abcdef"
    token = "UNIQUESUBMITTERPATHTOKEN"
    secret_ref = f"{token}/{marker}.md"
    dumped = json.dumps(
        serialize_outside_agent_validation_verdict(
            _direct_validation(
                evidence_refs=(OutsideAgentEvidenceRef(ref=secret_ref, digest="b" * 64, kind=token),),
                submitted_refs=(secret_ref,),
            )
        )
    )
    assert marker not in dumped
    assert token not in dumped
