"""Round-4 hardening for the governed-pipeline outside-agent validator.

Three blockers from Consiliency/agent-harness#372 round 4, each failing-first against
the pre-fix base:

* **Blocker 1 — the process exit code is a SEVENTH outcome channel, and it was
  ungated.** ``cli.py`` returned ``int(validation.exit_code)`` — the PRE-sink verdict
  code. But the serialization sink can downgrade a PASS verdict to a fail-closed
  ``REDACTION_VIOLATION`` when a construction scan was bypassed. So the emitted JSON
  document said ``blocked``/3 while the process exited ``0`` (PASS) — and CI branches on
  ``returncode``. The process exit code MUST match the document the sink actually
  emitted. Non-vacuity: two validations with the SAME pre-sink code (PASS) but
  DIFFERENT post-sink documents must yield DIFFERENT return codes.

* **Blocker 2 — the fail-closed document repeated the value that tripped the sweep.**
  ``_secret_free_blocked_document`` copied ``validator_version`` / ``input_digest`` /
  the contract-pin fields from the REJECTED object. The round-3 structural argument
  checked the *projection* fields and the digest alphabet; it did NOT check the
  metadata copied from the rejected object. If the sweep tripped ON one of those
  channels, the redaction document echoed the secret verbatim — the exact shape of the
  leak it closes. Swept across all three named channels.

* **Blocker 3 — ``submitted_refs`` was traversed twice.** ``build_*`` iterates the
  iterable once to normalize and again to secret-scan. A one-shot generator is
  exhausted by the first pass, so the secret scan sees nothing and a PASS/exit-0
  verdict carries the secret ref past the construction-time contract. Materializing
  once fixes it; the tuple positive control isolates generator-vs-materialized as the
  only variable.
"""
from __future__ import annotations

import argparse
import dataclasses
import json

import pytest
from _outside_agent_canonical import clean_submission

from phase_loop_runtime import cli
from phase_loop_runtime.conformance import (
    OutsideAgentValidationExitCode,
    build_outside_agent_validation_verdict,
    serialize_outside_agent_validation_verdict,
)
from phase_loop_runtime.conformance import outside_agent_real
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


def _pass_validation(
    *,
    validator_version: str = "test-version",
    input_digest: str = "a" * 64,
    contract_pin=EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN,
    evidence_refs=(),
    submitted_refs=(),
) -> OutsideAgentValidationVerdict:
    """A directly-built PASS validation (construction scans bypassed).

    Built by hand rather than via ``build_*`` so a secret injected into a metadata
    channel reaches the SINK — constructing through ``build_*`` would let the
    construction scan catch it first and the falsifier would die upstream (the vacuity
    the reviewer named in round 3).
    """
    verdict = OutsideAgentConformanceVerdict(
        verdict_schema_version=contract_pin.verdict_schema_version,
        submission_kind=None,
        status=OutsideAgentVerdictStatus.PASS,
        blockers=(),
        contract_pin=contract_pin,
        input_digest=input_digest,
        provenance_refs=tuple(ref.ref for ref in evidence_refs),
        evidence_refs=tuple(evidence_refs),
        redaction_posture=contract_pin.redaction_posture,
        metadata={"source_owner": contract_pin.source_owner},
    )
    return OutsideAgentValidationVerdict(
        authority="governed_pipeline_validator",
        validator_version=validator_version,
        exit_code=OutsideAgentValidationExitCode.PASS,
        verdict=verdict,
        submitted_refs=tuple(OutsideAgentSubmittedRef(ref=ref) for ref in submitted_refs),
    )


# --------------------------------------------------------------------------
# Blocker 1 — the process exit code must match the post-sink document.
# --------------------------------------------------------------------------


def _run_validate_in_process(monkeypatch, tmp_path, validation) -> tuple[int, dict]:
    """Drive the real CLI command with a builder patched to return ``validation``.

    A real submission cannot produce the disagreeing state — the sink only fires when a
    construction scan was bypassed — so the bypass is simulated at the builder seam. The
    CLI still serializes and writes exactly as in production.
    """
    monkeypatch.setattr(
        outside_agent_real,
        "build_outside_agent_validation_verdict",
        lambda *a, **k: validation,
    )
    submission_path = tmp_path / "submission.json"
    submission_path.write_text(json.dumps(clean_submission("work_request")), encoding="utf-8")
    output_path = tmp_path / "verdict.json"
    args = argparse.Namespace(
        submission_file=str(submission_path),
        output=str(output_path),
        submitted_ref=[],
    )
    rc = cli._outside_agent_validate_command(args)
    doc = json.loads(output_path.read_text(encoding="utf-8"))
    return rc, doc


def test_cli_returncode_is_zero_when_document_passes_control(monkeypatch, tmp_path) -> None:
    """Positive control: a clean validation writes a PASS document and returns 0 — so
    the blocked case below proves the return code TRACKS the document, not that it is
    constant."""
    rc, doc = _run_validate_in_process(monkeypatch, tmp_path, _pass_validation())
    assert doc["status"] == "pass"
    assert doc["exit_code"] == int(OutsideAgentValidationExitCode.PASS)
    assert rc == doc["exit_code"] == 0


def test_cli_returncode_matches_fail_closed_document_seventh_channel(monkeypatch, tmp_path) -> None:
    """The disagreeing state: pre-sink exit_code is PASS, but a secret in a projection
    trips the sink and the emitted document is blocked/REDACTION_VIOLATION. The process
    exit code — the channel CI branches on — must equal the document's, not PASS."""
    bypassed = _pass_validation(
        evidence_refs=(OutsideAgentEvidenceRef(ref=_SECRET_REF, digest="a" * 64, kind="documentation"),),
    )
    rc, doc = _run_validate_in_process(monkeypatch, tmp_path, bypassed)

    # Positive control FIRST: the sink actually fired, so this scenario is real and the
    # return-code assertion is non-vacuous (not a silently-skipped precondition).
    assert doc["status"] == "blocked"
    assert doc["exit_code"] == int(OutsideAgentValidationExitCode.REDACTION_VIOLATION)
    # The bug: pre-fix the CLI returned int(validation.exit_code) == PASS(0).
    assert rc == doc["exit_code"] == int(OutsideAgentValidationExitCode.REDACTION_VIOLATION)


# --------------------------------------------------------------------------
# Blocker 2 — the fail-closed document must not repeat the trigger value,
# including in metadata COPIED from the rejected object (not just projections).
# --------------------------------------------------------------------------

_MARKER = "sk-SEVENTHCHANNEL0123456789abcdef"


def _validation_with_secret_in(channel: str) -> OutsideAgentValidationVerdict:
    if channel == "validator_version":
        return _pass_validation(validator_version=_MARKER)
    if channel == "input_digest":
        return _pass_validation(input_digest=_MARKER)
    if channel == "contract_pin.source_owner":
        pin = dataclasses.replace(EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN, source_owner=_MARKER)
        return _pass_validation(contract_pin=pin)
    raise AssertionError(f"unknown channel {channel}")


@pytest.mark.parametrize(
    "channel",
    ["validator_version", "input_digest", "contract_pin.source_owner"],
)
def test_fail_closed_document_never_repeats_secret_in_copied_metadata(channel: str) -> None:
    """Blocker 2, swept across all three named metadata channels. Each carries a secret
    marker on a field the fail-closed document COPIES from the rejected object — a
    channel the projection-emptying does not reach. Pre-fix the marker rode out verbatim."""
    payload = serialize_outside_agent_validation_verdict(_validation_with_secret_in(channel))

    # Positive control: the sweep tripped on this metadata channel and the sink fired.
    assert payload["status"] == "blocked", channel
    assert payload["exit_code"] == int(OutsideAgentValidationExitCode.REDACTION_VIOLATION), channel
    # The document must not echo the value that tripped the sweep.
    assert _MARKER not in json.dumps(payload), channel


# --------------------------------------------------------------------------
# Blocker 3 — submitted_refs must be materialized before the two passes.
# --------------------------------------------------------------------------


def test_secret_submitted_ref_in_a_generator_is_still_caught() -> None:
    """A one-shot generator carrying a secret-shaped ref must still BLOCK. The tuple
    positive control proves the ref is genuinely caught when materialized, isolating
    generator-consumption as the sole failing variable."""
    # Positive control: the same ref as a tuple is caught (scan works, ref is secret-shaped).
    tuple_verdict = build_outside_agent_validation_verdict(
        clean_submission("work_request"), submitted_refs=(_SECRET_REF,)
    )
    assert tuple_verdict.verdict.status is OutsideAgentVerdictStatus.BLOCKED
    assert tuple_verdict.exit_code == OutsideAgentValidationExitCode.REDACTION_VIOLATION

    # The bug: a one-shot generator is exhausted by _normalize before the secret scan runs.
    gen_verdict = build_outside_agent_validation_verdict(
        clean_submission("work_request"),
        submitted_refs=(ref for ref in (_SECRET_REF,)),
    )
    assert gen_verdict.verdict.status is OutsideAgentVerdictStatus.BLOCKED
    assert gen_verdict.exit_code == OutsideAgentValidationExitCode.REDACTION_VIOLATION
