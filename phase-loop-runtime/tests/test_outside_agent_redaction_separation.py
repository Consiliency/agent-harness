"""Round-2 safety separation for the outside-agent validator (agent-harness#371).

Aligning our validator to the packaged contract DIALECT (agent-harness#371) must
not drop the independent metadata-only safety guarantee this repo publishes.
Three regressions are pinned here so the dialect fix cannot silently relax them:

1. A secret-shaped VALUE in a schema-VALID free-text field (``summary``) must
   BLOCK — not pass while still emitting ``redaction_posture="metadata_only"``.
   (Schema validity and redaction policy are separate concerns.)
2. Schema-validation blocker messages must be built from the failing keyword /
   pointer / schema expectation only — never from ``jsonschema``'s
   ``error.message``, which embeds the offending submitted value verbatim.
3. An unsafe (``..`` traversal) evidence path on a BLOCKED submission must not be
   reflected back into serialized output.

Submissions are sourced from the vendored canonical corpus, so a passing case is
a genuine canonical shape, not a hand-authored fixture.
"""
from __future__ import annotations

import json

import pytest

from _outside_agent_canonical import clean_submission

from phase_loop_runtime.conformance.outside_agent_advisory import (
    OutsideAgentAdvisoryExitCode,
    build_outside_agent_advisory_evidence,
    serialize_outside_agent_advisory_evidence,
)
from phase_loop_runtime.conformance.outside_agent_real import (
    OutsideAgentValidationExitCode,
    build_outside_agent_validation_verdict,
)
from phase_loop_runtime.conformance.outside_agent_real_output import (
    serialize_outside_agent_validation_verdict,
)

# A value-marker secret: trips the free-text VALUE scan (concern 1).
_LIVE_SECRET = "sk-LIVEredactionregressionDEADBEEF01"
# A secret-shaped probe that is NOT a redaction value-marker, so the ONLY channel
# that could echo it is an unsanitized schema message (isolates concern 2).
_LEAK_PROBE = "PROBEcafebabedeadbeef0123456789abc"
# A unique tail for a KEY that DOES trip the redaction walker (the key carries the
# ``secret`` fragment), isolating the ``_safe_path_segment`` ref channel.
_KEY_PROBE = "KEYPROBEcafef00ddeadbeef0123456789"


def _real(submission):
    return serialize_outside_agent_validation_verdict(
        build_outside_agent_validation_verdict(submission)
    )


def _advisory(submission):
    return serialize_outside_agent_advisory_evidence(
        build_outside_agent_advisory_evidence(submission)
    )


def _codes(serialized) -> set[str]:
    return {blocker["code"] for blocker in serialized["blockers"]}


# ---------------------------------------------------------------------------
# Concern 1 (and 3): redaction is a separate pass; the posture claim is backed.
# ---------------------------------------------------------------------------
def test_clean_canonical_submission_still_passes():
    """Positive control: restoring the scan must not block a clean submission."""
    out = _real(clean_submission("implementation_submission"))
    assert out["status"] == "pass"
    assert out["exit_code"] == int(OutsideAgentValidationExitCode.PASS)
    assert out["redaction_posture"] == "metadata_only"


def test_secret_in_schema_valid_summary_blocks_and_does_not_falsely_claim_metadata_only():
    """A secret hidden in a schema-valid free-text field must BLOCK.

    This is also the falsifiable evidence for the posture claim: the old code
    returned ``pass`` here while still emitting ``redaction_posture="metadata_only"``.

    Mutation (kills this test): remove the ``assert_outside_agent_metadata_only``
    pass from ``validate_outside_agent_submission`` -> status flips to ``pass``
    and exit_code to 0, while ``redaction_posture`` still reads ``metadata_only``.
    """
    submission = clean_submission("implementation_submission")
    assert "summary" in submission  # injection anchor
    submission["summary"] = f"deploy failed, provider token was {_LIVE_SECRET}"

    out = _real(submission)

    assert out["status"] == "blocked"
    assert out["exit_code"] == int(OutsideAgentValidationExitCode.REDACTION_VIOLATION)
    assert "secret_like_value_present" in _codes(out)
    # posture is only honest because the scan above actually ran and blocked.
    assert out["redaction_posture"] == "metadata_only"
    assert _LIVE_SECRET not in json.dumps(out)

    advisory = _advisory(submission)
    assert advisory["exit_code"] == int(OutsideAgentAdvisoryExitCode.REDACTION_VIOLATION)
    assert _LIVE_SECRET not in json.dumps(advisory)


def test_secret_in_nested_free_text_field_blocks():
    """The scan reaches nested free-text (``work_request.goal``), not just top level."""
    submission = clean_submission("work_request")
    assert "work_request" in submission and "goal" in submission["work_request"]
    submission["work_request"]["goal"] = f"ship it; leaked {_LIVE_SECRET}"

    out = _real(submission)

    assert out["status"] == "blocked"
    assert "secret_like_value_present" in _codes(out)
    assert _LIVE_SECRET not in json.dumps(out)


# ---------------------------------------------------------------------------
# Concern 2: schema messages never echo the offending submitted value.
# ---------------------------------------------------------------------------
def _inject_enum(submission):
    submission["submission_kind"] = _LEAK_PROBE


def _inject_pattern(submission):
    submission["implementation_submission"]["head_commit_sha"] = _LEAK_PROBE


def _inject_type(submission):
    submission["producer"] = _LEAK_PROBE  # schema expects an object


def _inject_minlength(submission):
    # minLength(1) violation whose value still carries the probe in a sibling
    # schema-invalid field so a naive message copy would surface it.
    submission["summary"] = ""
    submission["implementation_submission"]["head_commit_sha"] = _LEAK_PROBE


# ``const`` is deliberately excluded here: jsonschema's ``const`` message echoes the
# schema's EXPECTED value, never the submitted instance, so it cannot exercise the
# instance-echo channel this test pins. The ``const`` sanitizer branch is covered
# instead by ``test_const_failure_uses_sanitized_message_not_jsonschema_message``,
# whose falsifier does fire.
@pytest.mark.parametrize(
    "keyword,inject",
    [
        ("enum", _inject_enum),
        ("pattern", _inject_pattern),
        ("type", _inject_type),
        ("minLength", _inject_minlength),
    ],
)
def test_schema_message_never_echoes_offending_value(keyword, inject):
    """Across schema keyword classes, the probe value must not reach output.

    ``_LEAK_PROBE`` is not a redaction value-marker, so the ONLY way it could
    appear is an unsanitized schema message. Every keyword here is one whose
    jsonschema message embeds the offending INSTANCE verbatim.

    Mutation (kills this test): make ``_safe_schema_message`` return
    ``error.message`` -> the probe rides out verbatim in ``blockers[].message``.
    (Verified: all four params fail under that mutation.)
    """
    submission = clean_submission("implementation_submission")
    inject(submission)

    out = _real(submission)
    advisory = _advisory(submission)

    assert out["status"] == "blocked"
    assert "schema_validation_failed" in _codes(out)
    assert _LEAK_PROBE not in json.dumps(out), keyword
    assert _LEAK_PROBE not in json.dumps(advisory), keyword


def test_const_failure_uses_sanitized_message_not_jsonschema_message():
    """``const`` needs a POSITIVE proof: jsonschema's ``const`` message never carries
    the instance, so 'probe absent' would be vacuous here. Instead pin that the
    sanitized keyword form is emitted, which proves ``_safe_schema_message`` ran
    rather than falling through to ``error.message``.

    Mutation (kills this test): make ``_safe_schema_message`` return ``error.message``
    -> the message becomes ``"'outside_agent_submission.v0.1' was expected"``, which
    lacks the ``schema keyword 'const'`` phrasing this asserts.
    """
    submission = clean_submission("implementation_submission")
    submission["submission_schema_version"] = _LEAK_PROBE  # const violation

    out = _real(submission)

    assert out["status"] == "blocked"
    schema_msgs = [
        blocker["message"]
        for blocker in out["blockers"]
        if blocker["code"] == "schema_validation_failed"
    ]
    assert any("schema keyword 'const'" in message for message in schema_msgs)
    assert _LEAK_PROBE not in json.dumps(out)


def test_unknown_object_key_not_echoed_via_schema_message():
    """An unknown top-level KEY must not ride out through the SCHEMA message channel.

    The key ``x_<probe>`` carries no redaction marker, so it does not trip the
    walker; the only thing that blocks it is ``additionalProperties``, and the only
    way it could echo is an unsanitized schema message.

    Mutation (kills this test): make ``_safe_schema_message`` return ``error.message``
    -> ``additionalProperties`` names the offending key verbatim. (This is the schema
    channel, NOT ``_safe_path_segment`` — see the walker-ref test below for that.)
    """
    submission = clean_submission("implementation_submission")
    submission[f"x_{_LEAK_PROBE}"] = "value"

    out = _real(submission)

    assert out["status"] == "blocked"
    assert _LEAK_PROBE not in json.dumps(out)


def test_secret_shaped_key_is_redacted_in_walker_ref():
    """A KEY that trips the redaction WALKER must not echo the raw key through the
    blocker ``ref``. This exercises ``_safe_path_segment`` specifically: the key
    carries the ``secret`` fragment, so ``_check_key`` emits a
    ``secret_like_value_present`` blocker whose ``ref`` is that key's path — the one
    place ``_safe_path_segment`` sanitizes.

    Mutation (kills this test): ``_safe_path_segment`` returns the key unchanged ->
    the raw key rides out in ``blockers[].ref``. (Verified: that mutation flips this
    red; the older schema-message key test did NOT catch it.)
    """
    key = f"secret_{_KEY_PROBE}"
    submission = clean_submission("implementation_submission")
    submission[key] = "x"

    out = _real(submission)

    assert out["status"] == "blocked"
    # The walker itself fired on the secret-shaped key (not only the schema layer).
    assert "secret_like_value_present" in _codes(out)
    # And the raw key's unique tail is absent from every surfaced field, incl. refs.
    assert _KEY_PROBE not in json.dumps(out)
    assert all(_KEY_PROBE not in blocker["ref"] for blocker in out["blockers"])


# ---------------------------------------------------------------------------
# Concern 5 (CR round 2): the PROJECTION channel. `_extract_evidence_refs` copies
# submitter content (repo_relative_path, sha256, source_role) into serialized
# output. On a BLOCKED submission NONE of it may be reflected back: evidence_refs
# and provenance_refs are omitted entirely, field-agnostically.
# ---------------------------------------------------------------------------
_PROJECTION_SECRETS = {
    "repo_relative_path": "sk-LEAKpath0123456789abcdefdeadbeef",
    "sha256": "sk-LEAKdigest0123456789abcdefdeadbe",
    "source_role": "sk-LEAKrole0123456789abcdefdeadbeef",
}


def test_clean_pass_still_projects_evidence_refs():
    """Positive control: the gate must not be 'always empty'. A clean canonical
    submission PASSES and still surfaces its evidence/provenance refs, so the
    blocked-path emptiness below is meaningful rather than universal.

    (The real serializer exposes ``evidence_refs``; ``provenance_refs`` is surfaced
    only by the advisory serializer — assert each where it actually appears.)"""
    submission = clean_submission("implementation_submission")
    out = _real(submission)
    advisory = _advisory(submission)
    assert out["status"] == "pass"
    assert out["evidence_refs"], "PASS must still project evidence_refs (real)"
    assert advisory["provenance_refs"], "PASS must still project provenance_refs (advisory)"


@pytest.mark.parametrize("field", ["repo_relative_path", "sha256", "source_role"])
def test_blocked_submission_projects_no_evidence_ref_field(field):
    """A secret in ANY evidence-ref field must not ride out through the projection.

    The value trips the redaction walker (``sk-`` marker) so the submission is
    BLOCKED; the projection gate then omits evidence_refs/provenance_refs entirely,
    so the secret cannot reach ``evidence_refs[].ref/.digest/.kind`` or
    ``provenance_refs``. Reproduced in BOTH the real and advisory output paths (they
    project the same core verdict).

    Mutation (kills this test): remove the status gate in
    ``validate_outside_agent_submission`` (project on every status) -> the offending
    field is echoed verbatim.
    """
    secret = _PROJECTION_SECRETS[field]
    submission = clean_submission("implementation_submission")
    assert submission.get("evidence_refs"), "canonical vector must carry evidence_refs"
    submission["evidence_refs"][0][field] = secret

    out = _real(submission)
    advisory = _advisory(submission)

    # Real serializer surfaces evidence_refs (+ submitted_refs); advisory surfaces
    # evidence_refs + provenance_refs. Assert each projection where it appears.
    assert out["status"] == "blocked"
    assert out["evidence_refs"] == []
    assert secret not in json.dumps(out), field
    assert advisory["status"] == "blocked"
    assert advisory["evidence_refs"] == []
    assert advisory["provenance_refs"] == []
    assert secret not in json.dumps(advisory), field


def test_traversal_evidence_path_is_omitted_from_output():
    """A ``..`` traversal path (schema-rejected, so BLOCKED) must not appear in
    output. Distinct route to the same gate: blocked by SCHEMA, not the redaction
    walker, yet the projection is still omitted.

    Mutation (kills this test): remove the status gate in
    ``validate_outside_agent_submission`` -> the traversal path is surfaced in
    ``evidence_refs``/``provenance_refs`` verbatim.
    """
    traversal = "../../etc/passwd"
    submission = clean_submission("implementation_submission")
    assert submission.get("evidence_refs"), "canonical vector must carry evidence_refs"
    submission["evidence_refs"][0]["repo_relative_path"] = traversal

    out = _real(submission)

    assert out["status"] == "blocked"  # schema pattern rejects the path
    assert out["evidence_refs"] == []
    assert traversal not in json.dumps(out)


def test_blocked_via_submitted_ref_still_empties_projection():
    """The flip path: a core-PASS submission turned BLOCKED by an unsafe CLI
    ``submitted_refs`` entry must ALSO drop its (clean) projection, so the invariant
    'every blocked verdict has empty refs' is universal. Real path only — advisory
    has no ``submitted_refs`` channel.

    Mutation (kills this test): drop ``provenance_refs=(), evidence_refs=()`` from
    ``_verdict_with_extra_blockers`` -> the core-PASS projection survives on the
    now-blocked verdict.
    """
    submission = clean_submission("implementation_submission")
    serialized = serialize_outside_agent_validation_verdict(
        build_outside_agent_validation_verdict(
            submission, submitted_refs=("../../etc/passwd",)
        )
    )
    assert serialized["status"] == "blocked"
    assert serialized["evidence_refs"] == []  # real serializer has no provenance_refs key
    assert serialized["submitted_refs"] == []  # unsafe ref dropped -> becomes a blocker
