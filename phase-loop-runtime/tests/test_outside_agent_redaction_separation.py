from __future__ import annotations

import hashlib
import importlib
import json
import subprocess
import sys
from pathlib import Path

from _outside_agent_canonical import (
    CAPABILITY_MARKER,
    CANONICAL_DYNAMIC_INPUTS,
    FIXTURE_ROOT,
    REPO_ROOT,
    REDACTION_PROJECTION_CLASSES,
    clean_canonical_submission,
    load_json,
    recursive_schema_channels,
    redaction_channel_assignment,
    valid_submission_entries,
)


_LEGACY_BUILDER_MODULES = (
    "test_outside_agent_advisory",
    "test_outside_agent_advisory_cli",
    "test_outside_agent_authority_boundary",
    "test_outside_agent_core_api",
    "test_outside_agent_provenance",
    "test_outside_agent_real_cli",
    "test_outside_agent_real_output",
    "test_outside_agent_real_runtime",
    "test_outside_agent_redaction",
    "test_outside_agent_release_surface",
    "test_outside_agent_schema_validation",
    "test_outside_agent_vectors",
)
_LEGACY_DYNAMIC_INPUTS = {
    "legacy_submission.unknown_keys[]",
    "legacy_submission.unknown_values[]",
    "legacy_submission.raw_payload",
    "legacy_submission.provider_response",
    "legacy_submission.raw_log",
    "legacy_submission.environment",
}

EC_CONFORM_2_FAIL_CLOSED_BLOCKER_CODE = "schema_validation_failed"
_STRUCTURAL_REQUIRED_DIAGNOSTIC = {
    "code": EC_CONFORM_2_FAIL_CLOSED_BLOCKER_CODE,
    "ref": "/summary",
    "message": "required field is missing",
}
_STRUCTURAL_UNKNOWN_DIAGNOSTIC = {
    "code": EC_CONFORM_2_FAIL_CLOSED_BLOCKER_CODE,
    "ref": "/<unknown>",
    "message": "unknown field is not permitted",
}
_STRUCTURAL_REJECTED_PROJECTION_DIAGNOSTIC = {
    "code": EC_CONFORM_2_FAIL_CLOSED_BLOCKER_CODE,
    "ref": "/",
    "message": "submitted value is not permitted",
}
_STRUCTURAL_INVALID_REFERENCE_DIAGNOSTIC = {
    "code": EC_CONFORM_2_FAIL_CLOSED_BLOCKER_CODE,
    "ref": "/evidence_refs/0/repo_relative_path",
    "message": "repository-relative path is invalid",
}

# Rejected EC-CONFORM-2 inputs have no submitter-controlled diagnostic surface.
# The map is deliberately closed: each channel reaches one producer template and
# each template is an exact code/ref/message triple.
EC_CONFORM_2_DIAGNOSTIC_TEMPLATES = {
    "required": _STRUCTURAL_REQUIRED_DIAGNOSTIC,
    "unknown": _STRUCTURAL_UNKNOWN_DIAGNOSTIC,
    "rejected_projection": _STRUCTURAL_REJECTED_PROJECTION_DIAGNOSTIC,
    "invalid_reference": _STRUCTURAL_INVALID_REFERENCE_DIAGNOSTIC,
}
EC_CONFORM_2_CHANNEL_TO_TEMPLATE = {
    "negative-evidence-digest": "unknown",
    "raw-validator-diagnostic": "required",
    "submission.evidence_refs[].repo_relative_path": "invalid_reference",
    "submission.evidence_refs[].immutable_git_ref": "rejected_projection",
    "submission.evidence_refs[].sha256": "rejected_projection",
    "submission.evidence_refs[].source_bundle_refs[].bundle_manifest_sha256": "rejected_projection",
    "submission.evidence_refs[].bundle_manifest_sha256": "rejected_projection",
    "submission.implementation_submission.head_commit_sha": "rejected_projection",
    "submission.submission_schema_version": "rejected_projection",
    "submission.submission_kind": "rejected_projection",
    "submission.claim_posture": "rejected_projection",
    "submission.acceptance_truth_owner": "rejected_projection",
    "submission.evidence_refs[].evidence_ref_schema_version": "rejected_projection",
    "submission.evidence_refs[].digest_algorithm": "rejected_projection",
    "submission.evidence_refs[].source_role": "rejected_projection",
    "submission.evidence_refs[].claimed_path_membership.proof_type": "rejected_projection",
    "submission.evidence_refs[].claimed_path_membership.included": "rejected_projection",
    "submission.evidence_refs[].redaction_posture": "rejected_projection",
    "submission.unknown_keys[]": "unknown",
    "submission.unknown_values[]": "unknown",
    "submission.raw_payload": "unknown",
    "submission.provider_response": "unknown",
    "submission.raw_log": "unknown",
    "submission.environment": "unknown",
    "submission.evidence_refs[].raw_body": "unknown",
    "submission.producer.identity_posture": "unknown",
    "route_verdict.unknown_keys[]": "unknown",
    "route_verdict.unknown_values[]": "unknown",
    "route_verdict.raw_payload": "unknown",
    "route_verdict.provider_response": "unknown",
    "route_verdict.raw_log": "unknown",
    "route_verdict.environment": "unknown",
    "route_verdict.blocker.raw_body": "unknown",
    "route_verdict.verdict_schema_version": "rejected_projection",
    "route_verdict.route": "rejected_projection",
    "route_verdict.claim_posture": "rejected_projection",
    "route_verdict.acceptance_truth_owner": "rejected_projection",
    "route_verdict.blocker.class": "rejected_projection",
    "route_verdict.blocker.human_required": "rejected_projection",
    "legacy_submission.metadata.submission_id": "required",
    "legacy_submission.metadata.content_digest": "required",
    "legacy_submission.unknown_keys[]": "required",
    "legacy_submission.unknown_values[]": "required",
    "legacy_submission.raw_payload": "required",
    "legacy_submission.provider_response": "required",
    "legacy_submission.raw_log": "required",
    "legacy_submission.environment": "required",
    "legacy_submission.provenance_refs[].ref": "required",
    "legacy_submission.evidence_refs[].ref": "required",
    "legacy_submission.provenance_refs[].digest": "required",
    "legacy_submission.evidence_refs[].digest": "required",
    "legacy_submission.submission_schema_version": "required",
    "legacy_submission.submission_kind": "required",
}


def _production_capability_marker_present() -> bool:
    """Keep SL-0's marker-absent lifecycle separate from installed behavior."""
    try:
        from phase_loop_runtime.conformance import outside_agent_schema
    except ImportError:
        return False
    return (
        getattr(outside_agent_schema, "CONFORM_V10_CAPABILITY_MARKER", None)
        == CAPABILITY_MARKER
    )


def _assert_bounded_producer_diagnostic(
    blockers: list[dict], *, sentinel: str, channel: str
) -> None:
    """Only closed producer templates may survive a rejected channel."""
    template_name = EC_CONFORM_2_CHANNEL_TO_TEMPLATE[channel]
    expected = EC_CONFORM_2_DIAGNOSTIC_TEMPLATES[template_name]
    assert blockers == [expected], channel
    assert sentinel not in expected["ref"] + expected["message"], channel
    assert "jsonschema" not in expected["message"].lower(), channel
    assert "is not valid under" not in expected["message"].lower(), channel


def _assert_fail_closed_channel_result(
    returncode: int, payload: dict, *, sentinel: str, channel: str
) -> None:
    """A rejected EC-CONFORM-2 channel has one closed, producer-owned result."""
    assert returncode != 0, channel
    assert payload["status"] == "blocked", channel
    _assert_bounded_producer_diagnostic(
        payload["blockers"], sentinel=sentinel, channel=channel
    )


def _recursive_value_channels(value, prefix: str) -> set[str]:
    if isinstance(value, dict):
        return {
            channel
            for key, child in value.items()
            for channel in _recursive_value_channels(child, f"{prefix}.{key}")
        }
    if isinstance(value, list):
        if not value:
            return {prefix + "[]"}
        return {
            channel
            for child in value
            for channel in _recursive_value_channels(child, prefix + "[]")
        }
    return {prefix}


def _legacy_builder_payloads() -> tuple[dict, ...]:
    payloads = []
    for module_name in _LEGACY_BUILDER_MODULES:
        builder = getattr(importlib.import_module(module_name), "_submission")
        try:
            payload = builder()
        except TypeError:
            payload = builder("work_request")
        assert isinstance(payload, dict)
        payloads.append(payload)
    return tuple(payloads)


def test_closed_redaction_projection_inventory_is_exhaustive() -> None:
    assert tuple(REDACTION_PROJECTION_CLASSES) == (
        "read_locator_only",
        "forbidden_free_text",
        "normalized_ref_projection",
        "structural_diagnostic_projection",
        "validated_digest_projection",
        "closed_vocabulary_projection",
        "serialized_sink",
    )
    assert REDACTION_PROJECTION_CLASSES["read_locator_only"] == (
        "outside-agent-preflight:submission_file",
        "outside-agent-validate:submission_file",
    )
    assignment = redaction_channel_assignment()
    assert len(assignment) == sum(len(paths) for paths in REDACTION_PROJECTION_CLASSES.values())
    submission_schema = load_json(FIXTURE_ROOT / "schemas/outside-agent-submission.schema.json")
    route_schema = load_json(FIXTURE_ROOT / "schemas/outside-agent-route-verdict.schema.json")
    derived_inputs = {
        *("submission." + path for path in recursive_schema_channels(submission_schema)),
        *("route_verdict." + path for path in recursive_schema_channels(route_schema)),
    } | CANONICAL_DYNAMIC_INPUTS
    asserted_inputs = {
        channel
        for channel in assignment
        if channel.startswith("submission.") or channel.startswith("route_verdict.")
    }
    assert asserted_inputs == derived_inputs
    rejected_channels = {
        *CANONICAL_DYNAMIC_INPUTS,
        *(
            channel
            for channel, classification in assignment.items()
            if (
                channel.startswith(("submission.", "route_verdict."))
                and channel not in CANONICAL_DYNAMIC_INPUTS
                and classification != "forbidden_free_text"
            )
        ),
        *(channel for channel in assignment if channel.startswith("legacy_submission.")),
    }
    assert set(EC_CONFORM_2_CHANNEL_TO_TEMPLATE) == rejected_channels | {
        "negative-evidence-digest",
        "raw-validator-diagnostic",
    }
    assert {
        "submission.work_request.constraints[]",
        "submission.ambiguity_report.questions[]",
    } <= asserted_inputs
    # A generic status/code-only substitute and raw validator text must not
    # satisfy the EC-CONFORM-2 channel contract.
    status_only = {
        "status": "blocked",
        "blockers": [_STRUCTURAL_REQUIRED_DIAGNOSTIC],
    }
    try:
        _assert_fail_closed_channel_result(
            0,
            status_only,
            sentinel="CONFORM-SL0-STATUS-ONLY",
            channel="status-code-only-replacement",
        )
    except AssertionError:
        pass
    else:
        raise AssertionError("CONFORM_RED::status_code_only_channel_control_survived")
    raw_validator_diagnostic = {
        "status": "blocked",
        "blockers": [
            {
                **_STRUCTURAL_REQUIRED_DIAGNOSTIC,
                "message": "jsonschema says this instance is not valid under any schema",
            }
        ],
    }
    try:
        _assert_fail_closed_channel_result(
            1,
            raw_validator_diagnostic,
            sentinel="CONFORM-SL0-RAW-VALIDATOR",
            channel="raw-validator-diagnostic",
        )
    except AssertionError:
        pass
    else:
        raise AssertionError("CONFORM_RED::raw_validator_diagnostic_survived")
    sol_reproducer = {
        "status": "blocked",
        "blockers": [
            {
                "code": "schema_validation_failed",
                "ref": "/unrelated",
                "message": "submitter supplied but non-sentinel bytes",
            }
        ],
    }
    try:
        _assert_fail_closed_channel_result(
            1,
            sol_reproducer,
            sentinel="CONFORM-SL0-CHANNEL-SENTINEL",
            channel="negative-evidence-digest",
        )
    except AssertionError:
        pass
    else:
        raise AssertionError("CONFORM_RED::sol_unbound_diagnostic_survived")
    assert "submission.work_request.constraints" not in asserted_inputs
    assert "submission.ambiguity_report.questions" not in asserted_inputs
    corpus_inputs = {
        *(
            channel
                for row in valid_submission_entries()
                for channel in _recursive_value_channels(
                    load_json(FIXTURE_ROOT / row["path"]), "submission"
                )
                if not channel.endswith("[]")
        ),
        *(
            channel
            for path in (FIXTURE_ROOT / "test-vectors/outside-agent").glob("invalid-*.json")
                if path.name != "invalid-unsupported-verdict.json"
                for channel in _recursive_value_channels(load_json(path), "submission")
                if not channel.endswith("[]")
        ),
    }
    route_corpus_inputs = {
        channel
            for channel in _recursive_value_channels(
                load_json(FIXTURE_ROOT / "test-vectors/outside-agent/invalid-unsupported-verdict.json"),
                "route_verdict",
            )
            if not channel.endswith("[]")
    }
    assert corpus_inputs | route_corpus_inputs <= derived_inputs
    assert {
        "submission.evidence_refs[].raw_body",
        "submission.producer.identity_posture",
    } <= CANONICAL_DYNAMIC_INPUTS
    legacy_payloads = _legacy_builder_payloads()
    derived_legacy_inputs = {
        channel
        for payload in legacy_payloads
        for channel in _recursive_value_channels(payload, "legacy_submission")
    } | _LEGACY_DYNAMIC_INPUTS
    declared_legacy_inputs = {
        channel for channel in assignment if channel.startswith("legacy_submission.")
    }
    assert declared_legacy_inputs == derived_legacy_inputs

    from phase_loop_runtime.conformance.outside_agent_advisory import (
        build_outside_agent_advisory_evidence,
        serialize_outside_agent_advisory_evidence,
    )
    from phase_loop_runtime.conformance.outside_agent_real import (
        build_outside_agent_validation_verdict,
    )
    from phase_loop_runtime.conformance.outside_agent_real_output import (
        serialize_outside_agent_validation_verdict,
    )

    serialized_channels = set()
    for payload in legacy_payloads:
        serialized_channels |= _recursive_value_channels(
            serialize_outside_agent_advisory_evidence(
                build_outside_agent_advisory_evidence(payload)
            ),
            "advisory_output",
        )
        serialized_channels |= _recursive_value_channels(
            serialize_outside_agent_validation_verdict(
                build_outside_agent_validation_verdict(
                    payload,
                    submitted_refs=("src/agent.py",),
                )
            ),
            "validation_output",
        )
    declared_outputs = {
        channel
        for channel in assignment
        if channel.startswith("advisory_output.") or channel.startswith("validation_output.")
    }
    assert declared_outputs == serialized_channels

    cli_inputs = {
        "outside-agent-preflight:submission_file",
        "outside-agent-validate:submission_file",
        "outside-agent-validate:submitted_ref[]",
    }
    sinks = {
        "outside-agent-preflight:stdout",
        "outside-agent-preflight:--output",
        "outside-agent-validate:stdout",
        "outside-agent-validate:--output",
    }
    assert set(assignment) == derived_inputs | derived_legacy_inputs | serialized_channels | cli_inputs | sinks


def test_redaction_mutation_definitions_are_independent() -> None:
    from _outside_agent_canonical import CONFORM_MUTATION_DEFINITIONS

    construction = CONFORM_MUTATION_DEFINITIONS["M-CONFORM-2-RAW-CONSTRUCTION-GUARD"]
    serializer = CONFORM_MUTATION_DEFINITIONS["M-CONFORM-3-FINAL-SERIALIZER-GUARD"]
    assert construction.source_path != serializer.source_path
    assert construction.anchor != serializer.anchor
    assert construction.expected_nodeid != serializer.expected_nodeid


def _run(command: str, submission_path, output_path):
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "phase_loop_runtime.cli",
            command,
            str(submission_path),
            "--output",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )


def _set_channel(value: dict, channel: str, replacement: object) -> None:
    """Set every concrete value reached by one frozen dotted/array channel."""
    parts = channel.split(".")

    def visit(current, remaining: list[str]) -> None:
        part = remaining[0]
        is_array = part.endswith("[]")
        key = part.removesuffix("[]")
        if len(remaining) == 1:
            if is_array:
                assert isinstance(current[key], list)
                for index in range(len(current[key])):
                    current[key][index] = replacement
            else:
                current[key] = replacement
            return
        next_value = current[key]
        if is_array:
            assert isinstance(next_value, list)
            for item in next_value:
                visit(item, remaining[1:])
        else:
            visit(next_value, remaining[1:])

    visit(value, parts)


def _assert_cli_channel_control(
    payload: dict,
    *,
    sentinel: str,
    channel: str,
    tmp_path: Path,
    expected_success: bool = False,
) -> None:
    """Exercise both commands and both byte-equivalent serialization sinks."""
    for command in ("outside-agent-preflight", "outside-agent-validate"):
        safe_path = tmp_path / f"{channel.replace('.', '-')}-{command}-safe.json"
        safe_output = tmp_path / f"{channel.replace('.', '-')}-{command}-safe-output.json"
        safe_path.write_text(json.dumps(clean_canonical_submission()), encoding="utf-8")
        safe = _run(command, safe_path, safe_output)
        assert safe.returncode == 0, channel
        assert safe_output.read_text(encoding="utf-8") == safe.stdout, channel

        entered_path = tmp_path / f"{channel.replace('.', '-')}-{command}-negative.json"
        output_path = tmp_path / f"{channel.replace('.', '-')}-{command}-negative-output.json"
        entered_path.write_text(json.dumps(payload), encoding="utf-8")
        rejected = _run(command, entered_path, output_path)
        rendered = rejected.stdout + output_path.read_text(encoding="utf-8")
        assert output_path.read_text(encoding="utf-8") == rejected.stdout, channel
        assert sentinel not in rendered, channel
        if expected_success:
            assert rejected.returncode == 0, channel
            assert json.loads(rejected.stdout)["status"] == "pass", channel
        elif _production_capability_marker_present():
            rejected_payload = json.loads(rejected.stdout)
            _assert_fail_closed_channel_result(
                rejected.returncode,
                rejected_payload,
                sentinel=sentinel,
                channel=channel,
            )


def _assert_final_serializer_guard() -> None:
    """Prove the final sink omits a raw submission-file locator."""
    from phase_loop_runtime.conformance import EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN
    from phase_loop_runtime.conformance.outside_agent_core import (
        OutsideAgentConformanceVerdict,
        OutsideAgentSubmissionKind,
        OutsideAgentVerdictStatus,
    )
    from phase_loop_runtime.conformance.outside_agent_real import (
        OutsideAgentValidationExitCode,
        OutsideAgentValidationVerdict,
    )
    from phase_loop_runtime.conformance.outside_agent_real_output import (
        serialize_outside_agent_validation_verdict,
    )

    sentinel = "CONFORM-SL0-FINAL-SERIALIZER-GUARD-SUBMISSION-FILE"
    verdict = OutsideAgentConformanceVerdict(
        verdict_schema_version="outside_agent_route_verdict.v0.1",
        submission_kind=OutsideAgentSubmissionKind.WORK_REQUEST,
        status=OutsideAgentVerdictStatus.BLOCKED,
        blockers=(),
        contract_pin=EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN,
        input_digest="a" * 64,
        provenance_refs=(),
        evidence_refs=(),
        metadata={},
    )
    validation = OutsideAgentValidationVerdict(
        authority="governed_pipeline_validator",
        validator_version="test",
        exit_code=OutsideAgentValidationExitCode.CONFORMANCE_BLOCKED,
        verdict=verdict,
        submitted_refs=(),
    )
    # The frozen future serializer receives this boundary attribute from the CLI
    # construction path.  Bypass dataclass construction so SL-0 remains runnable
    # before that future production field exists.
    object.__setattr__(validation, "submission_file", sentinel)
    rendered = serialize_outside_agent_validation_verdict(validation)
    assert sentinel not in json.dumps(rendered, sort_keys=True)
    assert "submission_file" not in rendered


def _assert_sentinel_never_reaches_serialized_sinks(tmp_path: Path) -> None:
    from phase_loop_runtime.conformance.outside_agent_advisory import (
        build_outside_agent_advisory_evidence,
        serialize_outside_agent_advisory_evidence,
    )
    from phase_loop_runtime.conformance.outside_agent_real import (
        build_outside_agent_validation_verdict,
    )
    from phase_loop_runtime.conformance.outside_agent_real_output import (
        serialize_outside_agent_validation_verdict,
    )

    sentinel = "CONFORM-SL0-CHANNEL-SENTINEL"
    red_anchor = (
        "CONFORM_RED::"
        "submission_file_locator_never_serializes_and_digest_tracks_only_captured_bytes"
    )
    assignment = redaction_channel_assignment()
    canonical_channels = {
        channel: classification
        for channel, classification in assignment.items()
        if channel.startswith(("submission.", "route_verdict."))
        and channel not in CANONICAL_DYNAMIC_INPUTS
        and classification
        in {
            "forbidden_free_text",
            "normalized_ref_projection",
            "validated_digest_projection",
            "closed_vocabulary_projection",
        }
    }
    def canonical_payload_for(channel: str) -> dict:
        owners = {
            "submission.work_request.": "work_request",
            "submission.implementation_submission.": "implementation_submission",
            "submission.ambiguity_report.": "ambiguity_report",
        }
        kind = next(
            (kind for prefix, kind in owners.items() if channel.startswith(prefix)),
            "work_request",
        )
        return next(
            load_json(FIXTURE_ROOT / row["path"])
            for row in valid_submission_entries()
            if row["submission_kind"] == kind
        )

    def canonical_route_verdict_for(channel: str) -> dict:
        payload = {
            "verdict_schema_version": "outside_agent_route_verdict.v0.1",
            "route": "review_candidate",
            "claim_posture": "claims_only",
            "acceptance_truth_owner": "governed_pipeline",
        }
        if channel.startswith("route_verdict.blocker."):
            payload["blocker"] = {
                "class": "policy_gap",
                "summary": "producer-safe test summary",
                "human_required": False,
            }
        return payload

    def inject_dynamic_channel(payload: dict, channel: str) -> None:
        relative = channel.removeprefix("submission.").removeprefix("route_verdict.")
        if relative == "unknown_keys[]":
            payload[sentinel] = True
        elif relative == "unknown_values[]":
            payload["unclassified"] = sentinel
        else:
            _set_channel(payload, relative, sentinel)

    def assert_route_channel_control(
        payload: dict, channel: str, *, expected_success: bool = False
    ) -> None:
        try:
            from phase_loop_runtime.conformance.outside_agent_schema import (
                validate_outside_agent_route_verdict_schema,
            )

            result = validate_outside_agent_route_verdict_schema(
                payload, schema_target="outside_agent_route_verdict.v0.1"
            )
        except (AttributeError, ImportError, TypeError) as exc:
            raise AssertionError(
                f"{red_anchor}: route-verdict channel unavailable ({type(exc).__name__})"
            ) from exc
        blockers = [
            {"code": blocker.code, "ref": blocker.ref, "message": blocker.message}
            for blocker in result.blockers
        ]
        rendered = {
            "status": result.status.value,
            "blockers": blockers,
            "dispatch_observation": getattr(result, "dispatch_observation", None),
        }
        if expected_success:
            assert result.status.value == "pass", f"{red_anchor}: {channel}"
            assert blockers == [], f"{red_anchor}: {channel}"
        else:
            assert result.status.value == "blocked", f"{red_anchor}: {channel}"
            _assert_bounded_producer_diagnostic(
                blockers, sentinel=sentinel, channel=channel
            )
        observation = rendered["dispatch_observation"]
        assert observation is not None and observation["entered"] is True, (
            f"{red_anchor}: {channel}"
        )
        assert observation["schema_target"] == "outside_agent_route_verdict.v0.1", (
            f"{red_anchor}: {channel}"
        )
        assert observation["selected_schema_id"], f"{red_anchor}: {channel}"
        assert observation["selected_schema_sha256"], f"{red_anchor}: {channel}"
        assert sentinel not in json.dumps(rendered, sort_keys=True), (
            f"{red_anchor}: {channel}"
        )

    for channel, classification in canonical_channels.items():
        payload = canonical_payload_for(channel)
        relative = channel.removeprefix("submission.")
        if channel.startswith("route_verdict."):
            payload = canonical_route_verdict_for(channel)
            relative = channel.removeprefix("route_verdict.")
        replacement = sentinel
        if classification == "normalized_ref_projection":
            replacement = "../" + sentinel
        elif classification == "validated_digest_projection":
            replacement = sentinel + "-not-a-digest"
        _set_channel(payload, relative, replacement)
        if channel.startswith("route_verdict."):
            assert_route_channel_control(
                payload,
                channel,
                expected_success=classification == "forbidden_free_text",
            )
        else:
            rendered = json.dumps(
                {
                    "advisory": serialize_outside_agent_advisory_evidence(
                        build_outside_agent_advisory_evidence(payload)
                    ),
                    "validation": serialize_outside_agent_validation_verdict(
                        build_outside_agent_validation_verdict(payload)
                    ),
                },
                sort_keys=True,
            )
            assert sentinel not in rendered, channel
            _assert_cli_channel_control(
                payload,
                sentinel=sentinel,
                channel=channel,
                tmp_path=tmp_path,
                expected_success=(
                    channel.startswith("submission.")
                    and classification == "forbidden_free_text"
                ),
            )

    for channel in sorted(CANONICAL_DYNAMIC_INPUTS):
        payload = (
            canonical_route_verdict_for(channel)
            if channel.startswith("route_verdict.")
            else canonical_payload_for(channel)
        )
        inject_dynamic_channel(payload, channel)
        if channel.startswith("route_verdict."):
            assert_route_channel_control(payload, channel)
        else:
            rendered = json.dumps(
                {
                    "advisory": serialize_outside_agent_advisory_evidence(
                        build_outside_agent_advisory_evidence(payload)
                    ),
                    "validation": serialize_outside_agent_validation_verdict(
                        build_outside_agent_validation_verdict(payload)
                    ),
                },
                sort_keys=True,
            )
            assert sentinel not in rendered, channel
            _assert_cli_channel_control(
                payload,
                sentinel=sentinel,
                channel=channel,
                tmp_path=tmp_path,
            )

    legacy = _legacy_builder_payloads()[0]
    for channel, classification in assignment.items():
        if not channel.startswith("legacy_submission."):
            continue
        payload = json.loads(json.dumps(legacy))
        relative = channel.removeprefix("legacy_submission.")
        if relative == "unknown_keys[]":
            payload[sentinel] = True
        elif relative == "unknown_values[]":
            payload["unclassified"] = sentinel
        elif relative in {"raw_payload", "provider_response", "raw_log", "environment"}:
            payload[relative] = sentinel
        else:
            replacement = "../" + sentinel if classification == "normalized_ref_projection" else sentinel
            _set_channel(payload, relative, replacement)
        rendered = json.dumps(
            {
                "advisory": serialize_outside_agent_advisory_evidence(
                    build_outside_agent_advisory_evidence(payload)
                ),
                "validation": serialize_outside_agent_validation_verdict(
                    build_outside_agent_validation_verdict(payload)
                ),
            },
            sort_keys=True,
        )
        assert sentinel not in rendered, channel
        _assert_cli_channel_control(
            payload,
            sentinel=sentinel,
            channel=channel,
            tmp_path=tmp_path,
        )

    safe = clean_canonical_submission()
    validation = serialize_outside_agent_validation_verdict(
        build_outside_agent_validation_verdict(safe, submitted_refs=("src/agent.py",))
    )
    advisory = serialize_outside_agent_advisory_evidence(
        build_outside_agent_advisory_evidence(safe)
    )
    assert validation["submitted_refs"] == ["src/agent.py"]
    assert validation["evidence_refs"] == [
        {
            "ref": safe["evidence_refs"][0]["repo_relative_path"],
            "digest": safe["evidence_refs"][0]["sha256"],
            "kind": "metadata",
        }
    ]
    assert validation["blockers"] == []
    assert advisory["redaction_posture"] == "metadata_only"
    assert advisory["contract_pin"]["schema_version"] == "outside_agent_submission.v0.1"
    assert validation["contract_pin"]["verdict_schema_version"] == (
        "outside_agent_route_verdict.v0.1"
    )
    rejected_ref = serialize_outside_agent_validation_verdict(
        build_outside_agent_validation_verdict(
            safe,
            submitted_refs=("../" + sentinel,),
        )
    )
    assert sentinel not in json.dumps(rejected_ref, sort_keys=True)

    # Each retained projection class gets a positive control from an actual
    # serializer, not merely a declaration in the inventory.  The values below
    # are safe closed projections; none is submitter free text.
    assert validation["submitted_refs"] == ["src/agent.py"]
    assert validation["evidence_refs"] == [
        {
            "ref": safe["evidence_refs"][0]["repo_relative_path"],
            "digest": safe["evidence_refs"][0]["sha256"],
            "kind": "metadata",
        }
    ]
    assert all(len(value) == 64 for value in (
        validation["input_digest"],
        validation["evidence_refs"][0]["digest"],
        validation["vector_manifest_hash"],
    ))
    assert validation["blockers"] == []
    assert {
        validation["authority"],
        validation["status"],
        validation["redaction_posture"],
    } == {"governed_pipeline_validator", "pass", "metadata_only"}

    if _production_capability_marker_present():
        _assert_structural_diagnostic_positive_control(tmp_path)


def _assert_structural_diagnostic_positive_control(tmp_path: Path) -> None:
    """Freeze stable, producer-derived diagnostics without raw schema echoes."""
    sentinel = "CONFORM-SL0-STRUCTURAL-DIAGNOSTIC-SENTINEL"
    for command in ("outside-agent-preflight", "outside-agent-validate"):
        missing_summary = clean_canonical_submission()
        missing_summary.pop("summary")
        missing_path = tmp_path / f"{command}-missing-summary.json"
        missing_output = tmp_path / f"{command}-missing-summary-output.json"
        missing_path.write_text(json.dumps(missing_summary), encoding="utf-8")
        missing = _run(command, missing_path, missing_output)
        missing_payload = json.loads(missing.stdout)
        assert missing.returncode != 0
        assert missing_output.read_text(encoding="utf-8") == missing.stdout
        assert missing_payload["status"] == "blocked"
        assert missing_payload["blockers"] == [_STRUCTURAL_REQUIRED_DIAGNOSTIC]

        unknown = clean_canonical_submission()
        unknown[sentinel] = {"submitter": sentinel}
        unknown_path = tmp_path / f"{command}-unknown-property.json"
        unknown_output = tmp_path / f"{command}-unknown-property-output.json"
        unknown_path.write_text(json.dumps(unknown), encoding="utf-8")
        unknown_result = _run(command, unknown_path, unknown_output)
        unknown_payload = json.loads(unknown_result.stdout)
        rendered = unknown_result.stdout + unknown_output.read_text(encoding="utf-8")
        assert unknown_result.returncode != 0
        assert unknown_output.read_text(encoding="utf-8") == unknown_result.stdout
        assert unknown_payload["status"] == "blocked"
        assert unknown_payload["blockers"] == [_STRUCTURAL_UNKNOWN_DIAGNOSTIC]
        assert sentinel not in rendered


def test_submission_file_locator_never_serializes_and_digest_tracks_only_captured_bytes(tmp_path) -> None:
    relative = Path("phase-loop-runtime/tests/fixtures/outside_agent_contract_v0_2_1/test-vectors/outside-agent/valid-work-request.json")
    absolute = (REPO_ROOT / relative).resolve()
    raw = absolute.read_bytes()
    expected_digest = hashlib.sha256(raw).hexdigest()

    for command in ("outside-agent-preflight", "outside-agent-validate"):
        relative_output = tmp_path / f"{command}-relative.json"
        absolute_output = tmp_path / f"{command}-absolute.json"
        relative_result = _run(command, relative, relative_output)
        absolute_result = _run(command, absolute, absolute_output)
        relative_payload = json.loads(relative_result.stdout)
        absolute_payload = json.loads(absolute_result.stdout)
        assert relative_payload["input_digest"] == expected_digest, (
            "CONFORM_RED::submission_file_locator_never_serializes_and_digest_tracks_only_captured_bytes"
        )
        assert absolute_payload["input_digest"] == expected_digest, (
            "CONFORM_RED::submission_file_locator_never_serializes_and_digest_tracks_only_captured_bytes"
        )
        assert relative_payload == absolute_payload, (
            "CONFORM_RED::submission_file_locator_never_serializes_and_digest_tracks_only_captured_bytes"
        )
        assert relative_result.returncode == absolute_result.returncode == 0
        assert relative_output.read_text(encoding="utf-8") == relative_result.stdout
        assert absolute_output.read_text(encoding="utf-8") == absolute_result.stdout
        output_bytes = relative_result.stdout + absolute_result.stdout + relative_output.read_text(encoding="utf-8")
        assert str(relative) not in output_bytes and str(absolute) not in output_bytes, (
            "CONFORM_RED::submission_file_locator_never_serializes_and_digest_tracks_only_captured_bytes"
        )
    _assert_sentinel_never_reaches_serialized_sinks(tmp_path)


def test_submission_file_missing_unreadable_paths_fail_closed_without_path_derived_digest(tmp_path) -> None:
    _assert_final_serializer_guard()
    missing = tmp_path / "missing-SL0-secret-sentinel.json"
    unreadable = tmp_path / "unreadable-SL0-secret-sentinel.json"
    unreadable.mkdir()
    empty_digest = hashlib.sha256(b"").hexdigest()
    for command in ("outside-agent-preflight", "outside-agent-validate"):
        for label, locator in (
            ("traversal", Path("../SL0-secret-sentinel.json")),
            ("free-text", Path("SL0-secret-sentinel-not-a-locator")),
            ("missing", missing),
            ("unreadable", unreadable),
        ):
            output_path = tmp_path / f"{command}-{label}.json"
            result = _run(command, locator, output_path)
            payload = json.loads(result.stdout)
            rendered = result.stdout + output_path.read_text(encoding="utf-8")
            assert result.returncode != 0, (
                "CONFORM_RED::submission_file_missing_unreadable_paths_fail_closed_without_path_derived_digest"
            )
            assert payload["input_digest"] == empty_digest, (
                "CONFORM_RED::submission_file_missing_unreadable_paths_fail_closed_without_path_derived_digest"
            )
            assert output_path.read_text(encoding="utf-8") == result.stdout
            assert str(locator) not in rendered and "SL0-secret-sentinel" not in rendered, (
                "CONFORM_RED::submission_file_missing_unreadable_paths_fail_closed_without_path_derived_digest"
            )
