# SCHEMA intake receipt

Runner-observed v1 structural intake for agent-harness#1818. This receipt grants
no launch, journal or byte-pin authority. IF-0-SCHEMA-1 completion additionally
requires a green hosted publication and extracted-wheel job; a null hosted
identity explicitly withholds that completion. Every semantic row remains
upstream_phase_unmet for production proof at CLOSEOUT, including zero-vector
obligations and positive controls' effects. No v2 bytes are pinned.

Local checks run as individual targeted files, serially, under timeout 900 with
no cacheprovider, after shared-host load and I/O pressure checks. Intermediate
JUnit stays runner-owned scratch. The separate stamp step compares producer
rows with actual JUnit outcomes, refuses missing/skipped/failed nodes and records
the combined suite artifact digest. The digest identifies that run before this
stamp; it makes no claim about a later head. V3 checks shape and completeness
without requiring scratch to exist in a fresh checkout.

Full regression, required CI checks, Gate A and independent review are outside
these local observations. Spec closeout: canonical_spec_update, metadata_only;
targets are the vendored schema directory and docs/supervised-worker-contracts.md.

```json
{
  "byte_pin_authority": false,
  "coverage_inventory": [
    {
      "absent_keys": [
        "instruction_digest",
        "reference_digests"
      ],
      "id": "instruction-reference",
      "owner": "ENVELOPE/WORKER; CLOSEOUT",
      "source_pointer": "admitted-launch-envelope.schema.json#/properties",
      "status": "upstream_phase_unmet"
    },
    {
      "absent_keys": [
        "argv",
        "argv_digest"
      ],
      "id": "argv",
      "owner": "ENVELOPE/WORKER; CLOSEOUT",
      "source_pointer": "admitted-launch-envelope.schema.json#/properties",
      "status": "upstream_phase_unmet"
    },
    {
      "absent_keys": [
        "executable_digest",
        "wrapper_digest"
      ],
      "id": "executable-wrapper",
      "owner": "ENVELOPE/WORKER; CLOSEOUT",
      "source_pointer": "admitted-launch-envelope.schema.json#/properties/executable_dependencies/properties",
      "status": "upstream_phase_unmet"
    },
    {
      "absent_keys": [
        "source_digest",
        "baseline_digest"
      ],
      "id": "workspace-source-baseline",
      "owner": "ENVELOPE/WORKER; CLOSEOUT",
      "source_pointer": "admitted-launch-envelope.schema.json#/properties/workspace/properties",
      "status": "upstream_phase_unmet"
    },
    {
      "absent_keys": [
        "timeout_seconds",
        "declared_bound"
      ],
      "id": "timeout",
      "owner": "ENVELOPE/WORKER; CLOSEOUT",
      "source_pointer": "admitted-launch-envelope.schema.json#/properties",
      "status": "upstream_phase_unmet"
    },
    {
      "absent_keys": [
        "effective_environment_digest"
      ],
      "id": "effective-environment",
      "owner": "ENVELOPE/WORKER; CLOSEOUT",
      "source_pointer": "admitted-launch-envelope.schema.json#/properties",
      "status": "upstream_phase_unmet"
    },
    {
      "absent_keys": [
        "policy_digest",
        "qualification_digest"
      ],
      "id": "policy-qualification",
      "owner": "ENVELOPE/WORKER; CLOSEOUT",
      "source_pointer": "admitted-launch-envelope.schema.json#/properties/enforcement/properties",
      "status": "upstream_phase_unmet"
    },
    {
      "absent_keys": [
        "action",
        "route",
        "delivery"
      ],
      "id": "action-route-delivery",
      "owner": "ENVELOPE/WORKER; CLOSEOUT",
      "source_pointer": "admitted-launch-envelope.schema.json#/properties",
      "status": "upstream_phase_unmet"
    },
    {
      "absent_keys": [
        "execution_view_digest",
        "egress_grant_digest"
      ],
      "id": "execution-view-egress",
      "owner": "ENVELOPE/WORKER; CLOSEOUT",
      "source_pointer": "admitted-launch-envelope.schema.json#/properties",
      "status": "upstream_phase_unmet"
    }
  ],
  "hosted_job_evidence": {
    "conclusion": "success",
    "head": "37262b2c9647abc3d8c936ef96c4afe079be4f5b",
    "job_id": 127070141798,
    "run_id": "41974509317",
    "wheel_junit_sha256": "c9dc39d4f63024cad60cd1998c92686c9cc1386988d08eb9871ebbe3a3e166d2",
    "wheel_tests_passed": 104
  },
  "hosted_publication": {
    "default_branch": "main",
    "default_branch_head": "93db4b4fcc4e3d40c62f6658b6a67b519c750491",
    "hosted_head": "37262b2c9647abc3d8c936ef96c4afe079be4f5b",
    "hosted_job": "publication",
    "hosted_run_id": "41974509317",
    "input_artifact_sha256": "2c98eafb4950cf4106e1512515dca3199cc4c6095dd5c5d6971e7c0e9b62cf0b",
    "outcome": "passed",
    "protected": true,
    "resources": {
      "admitted-launch-envelope.schema.json": {
        "blob": "1abe40abbb1178295af86b3c6d64f9bffe5a0099",
        "sha256": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d"
      },
      "conformance/README.md": {
        "blob": "9051f4fcfa7bb91b896f3efe60b6a3b238545a75",
        "sha256": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca"
      },
      "conformance/SHA256SUMS": {
        "blob": "ff78301d393ef361f6c476a7117f0d2d97d2193b",
        "sha256": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285"
      },
      "conformance/envelope.vectors.json": {
        "blob": "4fcb908f0ed89f2206efc2fbf4c5a6c7bdbd7e56",
        "sha256": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f"
      },
      "conformance/run-status.vectors.json": {
        "blob": "4a156e4fbf56526d483f729c78b2e94eb6f48f93",
        "sha256": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730"
      },
      "provenance.json": {
        "blob": "cb2d905ba4fc12c9df1244f301c2624a656643ac",
        "sha256": "9444d9285e4fbf9fa78c7e10fb474885c79f77cb65abec2f45527af2ec57ff42"
      },
      "run-status.schema.json": {
        "blob": "8af75b390c1b6dcb5478ac16daec3bd38cb060d1",
        "sha256": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      }
    },
    "source_commit": "93db4b4fcc4e3d40c62f6658b6a67b519c750491"
  },
  "hosted_result_artifact_sha256": "7c0d2db33859e9742bfcae0a179a5805e0baf579f5c3fe9950e61ba2f4a2f824",
  "hosted_run_id": "41974509317",
  "input_artifact_sha256": "2c98eafb4950cf4106e1512515dca3199cc4c6095dd5c5d6971e7c0e9b62cf0b",
  "intake_gate_status": "verified",
  "intake_results": [
    {
      "case_or_control_id": "test_frozen_input_and_production_pins",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_frozen_input_and_production_pins",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_frozen_input_and_production_pins"
    },
    {
      "case_or_control_id": "test_immutable_captured_buffers",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_immutable_captured_buffers",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_immutable_captured_buffers"
    },
    {
      "case_or_control_id": "test_resources_fail_closed[missing-admitted-launch-envelope.schema.json]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_resources_fail_closed[missing-admitted-launch-envelope.schema.json]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_resources_fail_closed[missing-admitted-launch-envelope.schema.json]"
    },
    {
      "case_or_control_id": "test_resources_fail_closed[missing-conformance/README.md]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_resources_fail_closed[missing-conformance/README.md]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_resources_fail_closed[missing-conformance/README.md]"
    },
    {
      "case_or_control_id": "test_resources_fail_closed[missing-conformance/SHA256SUMS]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_resources_fail_closed[missing-conformance/SHA256SUMS]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_resources_fail_closed[missing-conformance/SHA256SUMS]"
    },
    {
      "case_or_control_id": "test_resources_fail_closed[missing-conformance/envelope.vectors.json]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_resources_fail_closed[missing-conformance/envelope.vectors.json]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_resources_fail_closed[missing-conformance/envelope.vectors.json]"
    },
    {
      "case_or_control_id": "test_resources_fail_closed[missing-conformance/run-status.vectors.json]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_resources_fail_closed[missing-conformance/run-status.vectors.json]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_resources_fail_closed[missing-conformance/run-status.vectors.json]"
    },
    {
      "case_or_control_id": "test_resources_fail_closed[missing-run-status.schema.json]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_resources_fail_closed[missing-run-status.schema.json]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_resources_fail_closed[missing-run-status.schema.json]"
    },
    {
      "case_or_control_id": "test_resources_fail_closed[missing-harness-provenance.json]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_resources_fail_closed[missing-harness-provenance.json]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_resources_fail_closed[missing-harness-provenance.json]"
    },
    {
      "case_or_control_id": "test_resources_fail_closed[altered-admitted-launch-envelope.schema.json]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_resources_fail_closed[altered-admitted-launch-envelope.schema.json]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_resources_fail_closed[altered-admitted-launch-envelope.schema.json]"
    },
    {
      "case_or_control_id": "test_resources_fail_closed[altered-conformance/README.md]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_resources_fail_closed[altered-conformance/README.md]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_resources_fail_closed[altered-conformance/README.md]"
    },
    {
      "case_or_control_id": "test_resources_fail_closed[altered-conformance/SHA256SUMS]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_resources_fail_closed[altered-conformance/SHA256SUMS]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_resources_fail_closed[altered-conformance/SHA256SUMS]"
    },
    {
      "case_or_control_id": "test_resources_fail_closed[altered-conformance/envelope.vectors.json]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_resources_fail_closed[altered-conformance/envelope.vectors.json]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_resources_fail_closed[altered-conformance/envelope.vectors.json]"
    },
    {
      "case_or_control_id": "test_resources_fail_closed[altered-conformance/run-status.vectors.json]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_resources_fail_closed[altered-conformance/run-status.vectors.json]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_resources_fail_closed[altered-conformance/run-status.vectors.json]"
    },
    {
      "case_or_control_id": "test_resources_fail_closed[altered-run-status.schema.json]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_resources_fail_closed[altered-run-status.schema.json]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_resources_fail_closed[altered-run-status.schema.json]"
    },
    {
      "case_or_control_id": "test_resources_fail_closed[altered-harness-provenance.json]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_resources_fail_closed[altered-harness-provenance.json]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_resources_fail_closed[altered-harness-provenance.json]"
    },
    {
      "case_or_control_id": "test_single_read_same_buffer",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_single_read_same_buffer",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_single_read_same_buffer"
    },
    {
      "case_or_control_id": "test_resource_allowlist[../provenance.json]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_resource_allowlist[../provenance.json]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_resource_allowlist[../provenance.json]"
    },
    {
      "case_or_control_id": "test_resource_allowlist[provenance.json]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_resource_allowlist[provenance.json]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_resource_allowlist[provenance.json]"
    },
    {
      "case_or_control_id": "test_resource_allowlist[https://example.invalid/s]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_resource_allowlist[https://example.invalid/s]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_resource_allowlist[https://example.invalid/s]"
    },
    {
      "case_or_control_id": "test_resource_allowlist[SENTINEL]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_resource_allowlist[SENTINEL]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_resource_allowlist[SENTINEL]"
    },
    {
      "case_or_control_id": "test_resource_allowlist[None]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_resource_allowlist[None]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_resource_allowlist[None]"
    },
    {
      "case_or_control_id": "test_resource_allowlist[name5]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_resource_allowlist[name5]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_resource_allowlist[name5]"
    },
    {
      "case_or_control_id": "test_selector_refusal[SENTINEL-None]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_selector_refusal[SENTINEL-None]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_selector_refusal[SENTINEL-None]"
    },
    {
      "case_or_control_id": "test_selector_refusal[admitted_launch_envelope.v1-journal_line]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_selector_refusal[admitted_launch_envelope.v1-journal_line]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_selector_refusal[admitted_launch_envelope.v1-journal_line]"
    },
    {
      "case_or_control_id": "test_selector_refusal[supervised_run_status.v1-sha256]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_selector_refusal[supervised_run_status.v1-sha256]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_selector_refusal[supervised_run_status.v1-sha256]"
    },
    {
      "case_or_control_id": "test_selector_refusal[supervised_run_status.v1-SENTINEL]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_selector_refusal[supervised_run_status.v1-SENTINEL]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_selector_refusal[supervised_run_status.v1-SENTINEL]"
    },
    {
      "case_or_control_id": "test_selector_refusal[family4-None]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_selector_refusal[family4-None]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_selector_refusal[family4-None]"
    },
    {
      "case_or_control_id": "test_selector_refusal[supervised_run_status.v1-definition5]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_selector_refusal[supervised_run_status.v1-definition5]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_selector_refusal[supervised_run_status.v1-definition5]"
    },
    {
      "case_or_control_id": "test_strict_record_intake[{\"SENTINEL\":1,\"SENTINEL\":2}]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_strict_record_intake[{\"SENTINEL\":1,\"SENTINEL\":2}]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_strict_record_intake[{\"SENTINEL\":1,\"SENTINEL\":2}]"
    },
    {
      "case_or_control_id": "test_strict_record_intake[{\"SENTINEL\":NaN}]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_strict_record_intake[{\"SENTINEL\":NaN}]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_strict_record_intake[{\"SENTINEL\":NaN}]"
    },
    {
      "case_or_control_id": "test_strict_record_intake[{\"SENTINEL\":Infinity}]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_strict_record_intake[{\"SENTINEL\":Infinity}]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_strict_record_intake[{\"SENTINEL\":Infinity}]"
    },
    {
      "case_or_control_id": "test_strict_record_intake[{\"SENTINEL\":-Infinity}]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_strict_record_intake[{\"SENTINEL\":-Infinity}]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_strict_record_intake[{\"SENTINEL\":-Infinity}]"
    },
    {
      "case_or_control_id": "test_strict_record_intake[{\"SENTINEL\":1e9999}]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_strict_record_intake[{\"SENTINEL\":1e9999}]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_strict_record_intake[{\"SENTINEL\":1e9999}]"
    },
    {
      "case_or_control_id": "test_strict_record_intake[{\"SENTINEL\":9007199254740992}]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_strict_record_intake[{\"SENTINEL\":9007199254740992}]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_strict_record_intake[{\"SENTINEL\":9007199254740992}]"
    },
    {
      "case_or_control_id": "test_strict_record_intake[{\"SENTINEL\":-9007199254740992}]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_strict_record_intake[{\"SENTINEL\":-9007199254740992}]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_strict_record_intake[{\"SENTINEL\":-9007199254740992}]"
    },
    {
      "case_or_control_id": "test_strict_record_intake[{\"SENTINEL\":]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_strict_record_intake[{\"SENTINEL\":]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_strict_record_intake[{\"SENTINEL\":]"
    },
    {
      "case_or_control_id": "test_strict_record_intake[\\xff]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_strict_record_intake[\\xff]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_strict_record_intake[\\xff]"
    },
    {
      "case_or_control_id": "test_strict_record_intake[data9]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_strict_record_intake[data9]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_strict_record_intake[data9]"
    },
    {
      "case_or_control_id": "test_strict_record_intake[SENTINEL]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_strict_record_intake[SENTINEL]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_strict_record_intake[SENTINEL]"
    },
    {
      "case_or_control_id": "test_strict_record_intake[data11]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_strict_record_intake[data11]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_strict_record_intake[data11]"
    },
    {
      "case_or_control_id": "test_strict_record_intake[{\"SENTINEL\":\"\\ud800\"}]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_strict_record_intake[{\"SENTINEL\":\"\\ud800\"}]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_strict_record_intake[{\"SENTINEL\":\"\\ud800\"}]"
    },
    {
      "case_or_control_id": "test_strict_record_intake[{\"\\udfff\":1}]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_strict_record_intake[{\"\\udfff\":1}]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_strict_record_intake[{\"\\udfff\":1}]"
    },
    {
      "case_or_control_id": "test_strict_record_intake[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_strict_record_intake[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_strict_record_intake[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]"
    },
    {
      "case_or_control_id": "test_finite_numbers_preserve_types[0.5]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_finite_numbers_preserve_types[0.5]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_finite_numbers_preserve_types[0.5]"
    },
    {
      "case_or_control_id": "test_finite_numbers_preserve_types[1.0]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_finite_numbers_preserve_types[1.0]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_finite_numbers_preserve_types[1.0]"
    },
    {
      "case_or_control_id": "test_finite_numbers_preserve_types[1e2]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_finite_numbers_preserve_types[1e2]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_finite_numbers_preserve_types[1e2]"
    },
    {
      "case_or_control_id": "test_finite_numbers_preserve_types[-0.25]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_finite_numbers_preserve_types[-0.25]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_finite_numbers_preserve_types[-0.25]"
    },
    {
      "case_or_control_id": "test_finite_numbers_preserve_types[1e-9999]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_finite_numbers_preserve_types[1e-9999]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_finite_numbers_preserve_types[1e-9999]"
    },
    {
      "case_or_control_id": "test_finite_numbers_preserve_types[9007199254740991.1]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_finite_numbers_preserve_types[9007199254740991.1]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_finite_numbers_preserve_types[9007199254740991.1]"
    },
    {
      "case_or_control_id": "test_finite_numbers_preserve_types[9007199254740991]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_finite_numbers_preserve_types[9007199254740991]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_finite_numbers_preserve_types[9007199254740991]"
    },
    {
      "case_or_control_id": "test_finite_numbers_preserve_types[-9007199254740991]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_finite_numbers_preserve_types[-9007199254740991]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_finite_numbers_preserve_types[-9007199254740991]"
    },
    {
      "case_or_control_id": "test_resource_strict_json[{\"x\":0,\"x\":1}]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_resource_strict_json[{\"x\":0,\"x\":1}]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_resource_strict_json[{\"x\":0,\"x\":1}]"
    },
    {
      "case_or_control_id": "test_resource_strict_json[{\"x\":NaN}]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_resource_strict_json[{\"x\":NaN}]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_resource_strict_json[{\"x\":NaN}]"
    },
    {
      "case_or_control_id": "test_resource_strict_json[{\"x\":9007199254740992}]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_resource_strict_json[{\"x\":9007199254740992}]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_resource_strict_json[{\"x\":9007199254740992}]"
    },
    {
      "case_or_control_id": "test_runtime_support_refusal",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_runtime_support_refusal",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_runtime_support_refusal"
    },
    {
      "case_or_control_id": "test_schema_invalid_closed_error",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_schema_invalid_closed_error",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_schema_invalid_closed_error"
    },
    {
      "case_or_control_id": "test_metadata_integrity[byte_pin_authority]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_metadata_integrity[byte_pin_authority]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_metadata_integrity[byte_pin_authority]"
    },
    {
      "case_or_control_id": "test_metadata_integrity[commit]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_metadata_integrity[commit]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_metadata_integrity[commit]"
    },
    {
      "case_or_control_id": "test_metadata_integrity[source_repository]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_metadata_integrity[source_repository]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_metadata_integrity[source_repository]"
    },
    {
      "case_or_control_id": "test_metadata_integrity[root]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_metadata_integrity[root]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_metadata_integrity[root]"
    },
    {
      "case_or_control_id": "test_metadata_integrity[upstream_resources]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_metadata_integrity[upstream_resources]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_metadata_integrity[upstream_resources]"
    },
    {
      "case_or_control_id": "test_metadata_integrity[excluded_metadata]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_metadata_integrity[excluded_metadata]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_metadata_integrity[excluded_metadata]"
    },
    {
      "case_or_control_id": "test_metadata_integrity[input_artifact_sha256]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_metadata_integrity[input_artifact_sha256]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_metadata_integrity[input_artifact_sha256]"
    },
    {
      "case_or_control_id": "test_metadata_integrity[manifest]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_metadata_integrity[manifest]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_metadata_integrity[manifest]"
    },
    {
      "case_or_control_id": "test_metadata_integrity[manifest-entry]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_metadata_integrity[manifest-entry]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_metadata_integrity[manifest-entry]"
    },
    {
      "case_or_control_id": "test_metadata_integrity[manifest-encoding]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_metadata_integrity[manifest-encoding]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_metadata_integrity[manifest-encoding]"
    },
    {
      "case_or_control_id": "test_module_and_installed_resource_origin",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_module_and_installed_resource_origin",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_module_and_installed_resource_origin"
    },
    {
      "case_or_control_id": "test_publication_comparison_offline",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_comparison_offline",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_comparison_offline"
    },
    {
      "case_or_control_id": "test_no_public_injection_surface",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_no_public_injection_surface",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_no_public_injection_surface"
    },
    {
      "case_or_control_id": "test_packaged_resource_inventory[UNLISTED]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_packaged_resource_inventory[UNLISTED]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_packaged_resource_inventory[UNLISTED]"
    },
    {
      "case_or_control_id": "test_packaged_resource_inventory[conformance/UNLISTED]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_packaged_resource_inventory[conformance/UNLISTED]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_packaged_resource_inventory[conformance/UNLISTED]"
    },
    {
      "case_or_control_id": "test_packaged_resource_inventory[nested/file]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_packaged_resource_inventory[nested/file]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_packaged_resource_inventory[nested/file]"
    },
    {
      "case_or_control_id": "test_bundle_input_contract[none]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_bundle_input_contract[none]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_bundle_input_contract[none]"
    },
    {
      "case_or_control_id": "test_bundle_input_contract[text]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_bundle_input_contract[text]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_bundle_input_contract[text]"
    },
    {
      "case_or_control_id": "test_bundle_input_contract[object]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_bundle_input_contract[object]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_bundle_input_contract[object]"
    },
    {
      "case_or_control_id": "test_bundle_input_contract[empty]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_bundle_input_contract[empty]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_bundle_input_contract[empty]"
    },
    {
      "case_or_control_id": "test_bundle_input_contract[altered]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_bundle_input_contract[altered]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_bundle_input_contract[altered]"
    },
    {
      "case_or_control_id": "test_validation_runtime_diagnostic",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_validation_runtime_diagnostic",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_validation_runtime_diagnostic"
    },
    {
      "case_or_control_id": "test_schema_identity_contract",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_schema_identity_contract",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_schema_identity_contract"
    },
    {
      "case_or_control_id": "test_runtime_constructor_contract",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_runtime_constructor_contract",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_runtime_constructor_contract"
    },
    {
      "case_or_control_id": "test_publication_sealed_inputs[baseline]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_sealed_inputs[baseline]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_sealed_inputs[baseline]"
    },
    {
      "case_or_control_id": "test_publication_sealed_inputs[seal]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_sealed_inputs[seal]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_sealed_inputs[seal]"
    },
    {
      "case_or_control_id": "test_publication_sealed_inputs[inventory]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_sealed_inputs[inventory]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_sealed_inputs[inventory]"
    },
    {
      "case_or_control_id": "test_publication_sealed_inputs[commit]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_sealed_inputs[commit]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_sealed_inputs[commit]"
    },
    {
      "case_or_control_id": "test_publication_runner_offline[success]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_runner_offline[success]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_runner_offline[success]"
    },
    {
      "case_or_control_id": "test_publication_runner_offline[seal]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_runner_offline[seal]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_runner_offline[seal]"
    },
    {
      "case_or_control_id": "test_publication_runner_offline[private]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_runner_offline[private]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_runner_offline[private]"
    },
    {
      "case_or_control_id": "test_publication_runner_offline[default]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_runner_offline[default]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_runner_offline[default]"
    },
    {
      "case_or_control_id": "test_publication_runner_offline[protection]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_runner_offline[protection]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_runner_offline[protection]"
    },
    {
      "case_or_control_id": "test_publication_runner_offline[ancestry]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_runner_offline[ancestry]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_runner_offline[ancestry]"
    },
    {
      "case_or_control_id": "test_publication_runner_offline[head]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_runner_offline[head]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_runner_offline[head]"
    },
    {
      "case_or_control_id": "test_publication_runner_offline[advance]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_runner_offline[advance]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_runner_offline[advance]"
    },
    {
      "case_or_control_id": "test_publication_runner_offline[bytes]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_runner_offline[bytes]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_runner_offline[bytes]"
    },
    {
      "case_or_control_id": "test_publication_runner_offline[environment]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_runner_offline[environment]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_runner_offline[environment]"
    },
    {
      "case_or_control_id": "test_publication_change_selection[changed0-False-False]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_change_selection[changed0-False-False]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_change_selection[changed0-False-False]"
    },
    {
      "case_or_control_id": "test_publication_change_selection[changed1-False-False]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_change_selection[changed1-False-False]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_change_selection[changed1-False-False]"
    },
    {
      "case_or_control_id": "test_publication_change_selection[changed2-True-True]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_change_selection[changed2-True-True]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_change_selection[changed2-True-True]"
    },
    {
      "case_or_control_id": "test_publication_change_selection[changed3-False-True]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_change_selection[changed3-False-True]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_change_selection[changed3-False-True]"
    },
    {
      "case_or_control_id": "test_publication_change_selection[changed4-False-True]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_change_selection[changed4-False-True]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_change_selection[changed4-False-True]"
    },
    {
      "case_or_control_id": "test_publication_change_selection[changed5-False-True]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_change_selection[changed5-False-True]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_change_selection[changed5-False-True]"
    },
    {
      "case_or_control_id": "test_publication_change_selection[changed6-False-True]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_change_selection[changed6-False-True]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_change_selection[changed6-False-True]"
    },
    {
      "case_or_control_id": "test_publication_change_selection[changed7-False-True]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_change_selection[changed7-False-True]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_change_selection[changed7-False-True]"
    },
    {
      "case_or_control_id": "test_publication_change_selection[changed8-False-True]",
      "group": "intake_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_change_selection[changed8-False-True]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts.py::test_publication_change_selection[changed8-False-True]"
    }
  ],
  "module_origin": "phase_loop_runtime/supervised_contracts.py",
  "module_sha256": "b6e5b2e926a5b65daab4bb4f6b924845127e30da1b7d1202a6a607d5bcc9544c",
  "mutation_results": [
    {
      "case_or_control_id": "test_production_control[digest]",
      "group": "mutation_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_mutations.py::test_production_control[digest]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_mutations.py::test_production_control[digest]"
    },
    {
      "case_or_control_id": "test_production_control[validation]",
      "group": "mutation_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_mutations.py::test_production_control[validation]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_mutations.py::test_production_control[validation]"
    },
    {
      "case_or_control_id": "test_production_control[pattern]",
      "group": "mutation_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_mutations.py::test_production_control[pattern]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_mutations.py::test_production_control[pattern]"
    },
    {
      "case_or_control_id": "test_production_control[selector]",
      "group": "mutation_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_mutations.py::test_production_control[selector]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_mutations.py::test_production_control[selector]"
    },
    {
      "case_or_control_id": "test_production_control[allowlist]",
      "group": "mutation_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_mutations.py::test_production_control[allowlist]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_mutations.py::test_production_control[allowlist]"
    },
    {
      "case_or_control_id": "test_production_control[captured-buffer]",
      "group": "mutation_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_mutations.py::test_production_control[captured-buffer]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_mutations.py::test_production_control[captured-buffer]"
    },
    {
      "case_or_control_id": "test_every_definition_selector_control[journal_line]",
      "group": "mutation_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_mutations.py::test_every_definition_selector_control[journal_line]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_mutations.py::test_every_definition_selector_control[journal_line]"
    },
    {
      "case_or_control_id": "test_every_definition_selector_control[projection]",
      "group": "mutation_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_mutations.py::test_every_definition_selector_control[projection]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_mutations.py::test_every_definition_selector_control[projection]"
    },
    {
      "case_or_control_id": "test_every_definition_selector_control[page_request]",
      "group": "mutation_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_mutations.py::test_every_definition_selector_control[page_request]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_mutations.py::test_every_definition_selector_control[page_request]"
    },
    {
      "case_or_control_id": "test_every_definition_selector_control[page]",
      "group": "mutation_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_mutations.py::test_every_definition_selector_control[page]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_mutations.py::test_every_definition_selector_control[page]"
    },
    {
      "case_or_control_id": "test_every_definition_selector_control[reader_view]",
      "group": "mutation_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_mutations.py::test_every_definition_selector_control[reader_view]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_mutations.py::test_every_definition_selector_control[reader_view]"
    },
    {
      "case_or_control_id": "test_reference_integrity_complete_repin",
      "group": "mutation_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_mutations.py::test_reference_integrity_complete_repin",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_mutations.py::test_reference_integrity_complete_repin"
    },
    {
      "case_or_control_id": "test_offline_reference_control",
      "group": "mutation_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_mutations.py::test_offline_reference_control",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_mutations.py::test_offline_reference_control"
    },
    {
      "case_or_control_id": "test_vector_helper_control[patch]",
      "group": "mutation_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_mutations.py::test_vector_helper_control[patch]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_mutations.py::test_vector_helper_control[patch]"
    },
    {
      "case_or_control_id": "test_vector_helper_control[rehash]",
      "group": "mutation_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_mutations.py::test_vector_helper_control[rehash]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_mutations.py::test_vector_helper_control[rehash]"
    }
  ],
  "named_controls": [
    "E-admitted",
    "E-echo",
    "E-dependency-declared"
  ],
  "opaque_fields_do_not_prove_coverage": [
    "caller_context",
    "units.snapshot_ref",
    "units.crosswalk_ref",
    "obligations.definition_digests"
  ],
  "resource_sha256": {
    "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
    "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
    "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
    "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
    "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
    "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
    "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
  },
  "schema_results": [
    {
      "case_or_control_id": "test_published_schema_only[E-admitted]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[E-admitted]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[E-admitted]"
    },
    {
      "case_or_control_id": "test_published_schema_only[E-post-write-honest]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[E-post-write-honest]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[E-post-write-honest]"
    },
    {
      "case_or_control_id": "test_published_schema_only[E-dependency-declared]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[E-dependency-declared]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[E-dependency-declared]"
    },
    {
      "case_or_control_id": "test_published_schema_only[RC16-stale-rehashed]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[RC16-stale-rehashed]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[RC16-stale-rehashed]"
    },
    {
      "case_or_control_id": "test_published_schema_only[RC17-foreign-assignment-rehashed]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[RC17-foreign-assignment-rehashed]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[RC17-foreign-assignment-rehashed]"
    },
    {
      "case_or_control_id": "test_published_schema_only[RC17-foreign-project-rehashed]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[RC17-foreign-project-rehashed]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[RC17-foreign-project-rehashed]"
    },
    {
      "case_or_control_id": "test_published_schema_only[S-digest-not-rehashed]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[S-digest-not-rehashed]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[S-digest-not-rehashed]"
    },
    {
      "case_or_control_id": "test_published_schema_only[N21-network-required]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N21-network-required]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N21-network-required]"
    },
    {
      "case_or_control_id": "test_published_schema_only[N21-command-required]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N21-command-required]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N21-command-required]"
    },
    {
      "case_or_control_id": "test_published_schema_only[N21-worktree-under-patch-return]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N21-worktree-under-patch-return]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N21-worktree-under-patch-return]"
    },
    {
      "case_or_control_id": "test_published_schema_only[S-os-enforced-unqualified]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[S-os-enforced-unqualified]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[S-os-enforced-unqualified]"
    },
    {
      "case_or_control_id": "test_published_schema_only[S-dependency-without-digest]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[S-dependency-without-digest]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[S-dependency-without-digest]"
    },
    {
      "case_or_control_id": "test_published_schema_only[S-envelope-absolute-locator]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[S-envelope-absolute-locator]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[S-envelope-absolute-locator]"
    },
    {
      "case_or_control_id": "test_published_schema_only[S-envelope-raw-output]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[S-envelope-raw-output]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[S-envelope-raw-output]"
    },
    {
      "case_or_control_id": "test_published_schema_only[E-echo]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[E-echo]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[E-echo]"
    },
    {
      "case_or_control_id": "test_published_schema_only[S-caller-context-interpreted]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[S-caller-context-interpreted]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[S-caller-context-interpreted]"
    },
    {
      "case_or_control_id": "test_published_schema_only[V-two-attempts]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[V-two-attempts]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[V-two-attempts]"
    },
    {
      "case_or_control_id": "test_published_schema_only[V-running]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[V-running]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[V-running]"
    },
    {
      "case_or_control_id": "test_published_schema_only[V-refused-before-launch]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[V-refused-before-launch]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[V-refused-before-launch]"
    },
    {
      "case_or_control_id": "test_published_schema_only[N04a-seq-skip]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N04a-seq-skip]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N04a-seq-skip]"
    },
    {
      "case_or_control_id": "test_published_schema_only[N04a-seq-regress]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N04a-seq-regress]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N04a-seq-regress]"
    },
    {
      "case_or_control_id": "test_published_schema_only[N04a-replaced-in-place]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N04a-replaced-in-place]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N04a-replaced-in-place]"
    },
    {
      "case_or_control_id": "test_published_schema_only[N04b-foreign-binding]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N04b-foreign-binding]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N04b-foreign-binding]"
    },
    {
      "case_or_control_id": "test_published_schema_only[S-evidence-copied]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[S-evidence-copied]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[S-evidence-copied]"
    },
    {
      "case_or_control_id": "test_published_schema_only[N15-torn-line]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N15-torn-line]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N15-torn-line]"
    },
    {
      "case_or_control_id": "test_published_schema_only[N15-no-final-newline]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N15-no-final-newline]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N15-no-final-newline]"
    },
    {
      "case_or_control_id": "test_published_schema_only[N15-unknown-version]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N15-unknown-version]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N15-unknown-version]"
    },
    {
      "case_or_control_id": "test_published_schema_only[N15-foreign-writer]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N15-foreign-writer]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N15-foreign-writer]"
    },
    {
      "case_or_control_id": "test_published_schema_only[N19-refused-after-start]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N19-refused-after-start]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N19-refused-after-start]"
    },
    {
      "case_or_control_id": "test_published_schema_only[N19-refused-after-running]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N19-refused-after-running]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N19-refused-after-running]"
    },
    {
      "case_or_control_id": "test_published_schema_only[S-finished-without-termination]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[S-finished-without-termination]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[S-finished-without-termination]"
    },
    {
      "case_or_control_id": "test_published_schema_only[N20-raw-stdout-ref]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N20-raw-stdout-ref]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N20-raw-stdout-ref]"
    },
    {
      "case_or_control_id": "test_published_schema_only[N20-raw-message]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N20-raw-message]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N20-raw-message]"
    },
    {
      "case_or_control_id": "test_published_schema_only[N20-absolute-locator]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N20-absolute-locator]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N20-absolute-locator]"
    },
    {
      "case_or_control_id": "test_published_schema_only[N20-parent-locator]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N20-parent-locator]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N20-parent-locator]"
    },
    {
      "case_or_control_id": "test_published_schema_only[V-projection-at-tail]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[V-projection-at-tail]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[V-projection-at-tail]"
    },
    {
      "case_or_control_id": "test_published_schema_only[N16-projection-behind]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N16-projection-behind]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N16-projection-behind]"
    },
    {
      "case_or_control_id": "test_published_schema_only[N16-attempt-missing]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N16-attempt-missing]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N16-attempt-missing]"
    },
    {
      "case_or_control_id": "test_published_schema_only[S-projection-ahead]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[S-projection-ahead]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[S-projection-ahead]"
    },
    {
      "case_or_control_id": "test_published_schema_only[V-owner-live]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[V-owner-live]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[V-owner-live]"
    },
    {
      "case_or_control_id": "test_published_schema_only[N17-owner-not-live]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N17-owner-not-live]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N17-owner-not-live]"
    },
    {
      "case_or_control_id": "test_published_schema_only[N17-pid-reused]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N17-pid-reused]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N17-pid-reused]"
    },
    {
      "case_or_control_id": "test_published_schema_only[V-reader-view]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[V-reader-view]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[V-reader-view]"
    },
    {
      "case_or_control_id": "test_published_schema_only[N18-completed-as-outcome]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N18-completed-as-outcome]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N18-completed-as-outcome]"
    },
    {
      "case_or_control_id": "test_published_schema_only[N18-run-status-as-evidence]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N18-run-status-as-evidence]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[N18-run-status-as-evidence]"
    },
    {
      "case_or_control_id": "test_published_schema_only[RC24-foreign-assignment]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[RC24-foreign-assignment]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[RC24-foreign-assignment]"
    },
    {
      "case_or_control_id": "test_published_schema_only[RC24-foreign-snapshot]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[RC24-foreign-snapshot]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[RC24-foreign-snapshot]"
    },
    {
      "case_or_control_id": "test_published_schema_only[V-page]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[V-page]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[V-page]"
    },
    {
      "case_or_control_id": "test_published_schema_only[RC25-no-page-size]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[RC25-no-page-size]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[RC25-no-page-size]"
    },
    {
      "case_or_control_id": "test_published_schema_only[RC25-no-omitted]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[RC25-no-omitted]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[RC25-no-omitted]"
    },
    {
      "case_or_control_id": "test_published_schema_only[RC25-over-bound]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[RC25-over-bound]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_published_schema_only[RC25-over-bound]"
    },
    {
      "case_or_control_id": "test_inventory_matches_frozen_cases",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_inventory_matches_frozen_cases",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_inventory_matches_frozen_cases"
    },
    {
      "case_or_control_id": "test_default_status_definition",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_default_status_definition",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_default_status_definition"
    },
    {
      "case_or_control_id": "test_equal_proposal_independent_attempt_evidence",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_equal_proposal_independent_attempt_evidence",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_equal_proposal_independent_attempt_evidence"
    },
    {
      "case_or_control_id": "test_definition_structural_negative[admitted_launch_envelope.v1-None]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_definition_structural_negative[admitted_launch_envelope.v1-None]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_definition_structural_negative[admitted_launch_envelope.v1-None]"
    },
    {
      "case_or_control_id": "test_definition_structural_negative[supervised_run_status.v1-journal_line]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_definition_structural_negative[supervised_run_status.v1-journal_line]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_definition_structural_negative[supervised_run_status.v1-journal_line]"
    },
    {
      "case_or_control_id": "test_definition_structural_negative[supervised_run_status.v1-projection]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_definition_structural_negative[supervised_run_status.v1-projection]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_definition_structural_negative[supervised_run_status.v1-projection]"
    },
    {
      "case_or_control_id": "test_definition_structural_negative[supervised_run_status.v1-reader_view]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_definition_structural_negative[supervised_run_status.v1-reader_view]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_definition_structural_negative[supervised_run_status.v1-reader_view]"
    },
    {
      "case_or_control_id": "test_definition_structural_negative[supervised_run_status.v1-page_request]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_definition_structural_negative[supervised_run_status.v1-page_request]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_definition_structural_negative[supervised_run_status.v1-page_request]"
    },
    {
      "case_or_control_id": "test_definition_structural_negative[supervised_run_status.v1-page]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_definition_structural_negative[supervised_run_status.v1-page]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_definition_structural_negative[supervised_run_status.v1-page]"
    },
    {
      "case_or_control_id": "test_every_sha256_position[admitted_launch_envelope/properties/envelope_digest]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[admitted_launch_envelope/properties/envelope_digest]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[admitted_launch_envelope/properties/envelope_digest]"
    },
    {
      "case_or_control_id": "test_every_sha256_position[admitted_launch_envelope/properties/assignment_digest]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[admitted_launch_envelope/properties/assignment_digest]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[admitted_launch_envelope/properties/assignment_digest]"
    },
    {
      "case_or_control_id": "test_every_sha256_position[admitted_launch_envelope/properties/units/properties/snapshot_ref]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[admitted_launch_envelope/properties/units/properties/snapshot_ref]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[admitted_launch_envelope/properties/units/properties/snapshot_ref]"
    },
    {
      "case_or_control_id": "test_every_sha256_position[admitted_launch_envelope/properties/units/properties/crosswalk_ref]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[admitted_launch_envelope/properties/units/properties/crosswalk_ref]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[admitted_launch_envelope/properties/units/properties/crosswalk_ref]"
    },
    {
      "case_or_control_id": "test_every_sha256_position[admitted_launch_envelope/properties/obligations/properties/definition_digests/items]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[admitted_launch_envelope/properties/obligations/properties/definition_digests/items]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[admitted_launch_envelope/properties/obligations/properties/definition_digests/items]"
    },
    {
      "case_or_control_id": "test_every_sha256_position[admitted_launch_envelope/properties/executable_dependencies/properties/admitted_dependency_digest/anyOf/0]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[admitted_launch_envelope/properties/executable_dependencies/properties/admitted_dependency_digest/anyOf/0]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[admitted_launch_envelope/properties/executable_dependencies/properties/admitted_dependency_digest/anyOf/0]"
    },
    {
      "case_or_control_id": "test_every_sha256_position[supervised_run_status/$defs/attempt_identity/properties/assignment_digest]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[supervised_run_status/$defs/attempt_identity/properties/assignment_digest]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[supervised_run_status/$defs/attempt_identity/properties/assignment_digest]"
    },
    {
      "case_or_control_id": "test_every_sha256_position[supervised_run_status/$defs/attempt_identity/properties/envelope_digest]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[supervised_run_status/$defs/attempt_identity/properties/envelope_digest]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[supervised_run_status/$defs/attempt_identity/properties/envelope_digest]"
    },
    {
      "case_or_control_id": "test_every_sha256_position[supervised_run_status/$defs/units/properties/snapshot_ref]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[supervised_run_status/$defs/units/properties/snapshot_ref]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[supervised_run_status/$defs/units/properties/snapshot_ref]"
    },
    {
      "case_or_control_id": "test_every_sha256_position[supervised_run_status/$defs/header_body/properties/previous_segment_sha256/anyOf/0]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[supervised_run_status/$defs/header_body/properties/previous_segment_sha256/anyOf/0]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[supervised_run_status/$defs/header_body/properties/previous_segment_sha256/anyOf/0]"
    },
    {
      "case_or_control_id": "test_every_sha256_position[supervised_run_status/$defs/terminal_body/properties/result_binding/anyOf/1/properties/envelope_digest]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[supervised_run_status/$defs/terminal_body/properties/result_binding/anyOf/1/properties/envelope_digest]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[supervised_run_status/$defs/terminal_body/properties/result_binding/anyOf/1/properties/envelope_digest]"
    },
    {
      "case_or_control_id": "test_every_sha256_position[supervised_run_status/$defs/terminal_body/properties/result_binding/anyOf/1/properties/proposal_bytes_digest/anyOf/0]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[supervised_run_status/$defs/terminal_body/properties/result_binding/anyOf/1/properties/proposal_bytes_digest/anyOf/0]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[supervised_run_status/$defs/terminal_body/properties/result_binding/anyOf/1/properties/proposal_bytes_digest/anyOf/0]"
    },
    {
      "case_or_control_id": "test_every_sha256_position[supervised_run_status/$defs/terminal_body/properties/result_binding/anyOf/1/properties/evidence_envelope_digest]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[supervised_run_status/$defs/terminal_body/properties/result_binding/anyOf/1/properties/evidence_envelope_digest]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[supervised_run_status/$defs/terminal_body/properties/result_binding/anyOf/1/properties/evidence_envelope_digest]"
    },
    {
      "case_or_control_id": "test_every_sha256_position[supervised_run_status/$defs/projection/properties/assignment_digest]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[supervised_run_status/$defs/projection/properties/assignment_digest]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[supervised_run_status/$defs/projection/properties/assignment_digest]"
    },
    {
      "case_or_control_id": "test_every_sha256_position[supervised_run_status/$defs/projection/properties/attempts/items/properties/segment_sha256]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[supervised_run_status/$defs/projection/properties/attempts/items/properties/segment_sha256]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[supervised_run_status/$defs/projection/properties/attempts/items/properties/segment_sha256]"
    },
    {
      "case_or_control_id": "test_every_sha256_position[supervised_run_status/$defs/page_request/properties/assignment_digest]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[supervised_run_status/$defs/page_request/properties/assignment_digest]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[supervised_run_status/$defs/page_request/properties/assignment_digest]"
    },
    {
      "case_or_control_id": "test_every_sha256_position[supervised_run_status/$defs/reader_view/properties/row/properties/assignment_digest]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[supervised_run_status/$defs/reader_view/properties/row/properties/assignment_digest]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[supervised_run_status/$defs/reader_view/properties/row/properties/assignment_digest]"
    },
    {
      "case_or_control_id": "test_every_sha256_position[supervised_run_status/$defs/reader_view/properties/row/properties/snapshot_ref]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[supervised_run_status/$defs/reader_view/properties/row/properties/snapshot_ref]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[supervised_run_status/$defs/reader_view/properties/row/properties/snapshot_ref]"
    },
    {
      "case_or_control_id": "test_every_sha256_position[supervised_run_status/$defs/reader_view/properties/display/properties/work_outcome/anyOf/1/properties/ref/anyOf/0]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[supervised_run_status/$defs/reader_view/properties/display/properties/work_outcome/anyOf/1/properties/ref/anyOf/0]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[supervised_run_status/$defs/reader_view/properties/display/properties/work_outcome/anyOf/1/properties/ref/anyOf/0]"
    },
    {
      "case_or_control_id": "test_every_sha256_position[supervised_run_status/$defs/reader_view/properties/display/properties/evidence/anyOf/1/properties/ref]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[supervised_run_status/$defs/reader_view/properties/display/properties/evidence/anyOf/1/properties/ref]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_every_sha256_position[supervised_run_status/$defs/reader_view/properties/display/properties/evidence/anyOf/1/properties/ref]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[admitted_launch_envelope/properties/envelope_digest]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[admitted_launch_envelope/properties/envelope_digest]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[admitted_launch_envelope/properties/envelope_digest]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[admitted_launch_envelope/properties/assignment_digest]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[admitted_launch_envelope/properties/assignment_digest]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[admitted_launch_envelope/properties/assignment_digest]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[admitted_launch_envelope/properties/units/properties/target_unit_ids/items]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[admitted_launch_envelope/properties/units/properties/target_unit_ids/items]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[admitted_launch_envelope/properties/units/properties/target_unit_ids/items]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[admitted_launch_envelope/properties/units/properties/readonly_neighbor_unit_ids/items]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[admitted_launch_envelope/properties/units/properties/readonly_neighbor_unit_ids/items]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[admitted_launch_envelope/properties/units/properties/readonly_neighbor_unit_ids/items]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[admitted_launch_envelope/properties/units/properties/snapshot_ref]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[admitted_launch_envelope/properties/units/properties/snapshot_ref]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[admitted_launch_envelope/properties/units/properties/snapshot_ref]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[admitted_launch_envelope/properties/units/properties/crosswalk_ref]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[admitted_launch_envelope/properties/units/properties/crosswalk_ref]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[admitted_launch_envelope/properties/units/properties/crosswalk_ref]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[admitted_launch_envelope/properties/obligations/properties/definition_digests/items]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[admitted_launch_envelope/properties/obligations/properties/definition_digests/items]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[admitted_launch_envelope/properties/obligations/properties/definition_digests/items]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[admitted_launch_envelope/properties/executable_dependencies/properties/admitted_dependency_digest/anyOf/0]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[admitted_launch_envelope/properties/executable_dependencies/properties/admitted_dependency_digest/anyOf/0]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[admitted_launch_envelope/properties/executable_dependencies/properties/admitted_dependency_digest/anyOf/0]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[supervised_run_status]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[supervised_run_status/$defs/attempt_identity/properties/assignment_digest]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/attempt_identity/properties/assignment_digest]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/attempt_identity/properties/assignment_digest]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[supervised_run_status/$defs/attempt_identity/properties/envelope_digest]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/attempt_identity/properties/envelope_digest]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/attempt_identity/properties/envelope_digest]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[supervised_run_status/$defs/units/properties/target_unit_ids/items]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/units/properties/target_unit_ids/items]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/units/properties/target_unit_ids/items]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[supervised_run_status/$defs/units/properties/readonly_neighbor_unit_ids/items]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/units/properties/readonly_neighbor_unit_ids/items]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/units/properties/readonly_neighbor_unit_ids/items]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[supervised_run_status/$defs/units/properties/snapshot_ref]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/units/properties/snapshot_ref]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/units/properties/snapshot_ref]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[supervised_run_status/$defs/journal_line/properties/attempt]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/journal_line/properties/attempt]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/journal_line/properties/attempt]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[supervised_run_status/$defs/journal_line/properties/units]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/journal_line/properties/units]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/journal_line/properties/units]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[supervised_run_status/$defs/journal_line/properties/writer]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/journal_line/properties/writer]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/journal_line/properties/writer]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[supervised_run_status/$defs/journal_line/properties/body/oneOf/0]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/journal_line/properties/body/oneOf/0]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/journal_line/properties/body/oneOf/0]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[supervised_run_status/$defs/journal_line/properties/body/oneOf/1]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/journal_line/properties/body/oneOf/1]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/journal_line/properties/body/oneOf/1]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[supervised_run_status/$defs/journal_line/properties/body/oneOf/2]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/journal_line/properties/body/oneOf/2]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/journal_line/properties/body/oneOf/2]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[supervised_run_status/$defs/journal_line/properties/body/oneOf/3]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/journal_line/properties/body/oneOf/3]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/journal_line/properties/body/oneOf/3]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[supervised_run_status/$defs/header_body/properties/previous_segment_sha256/anyOf/0]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/header_body/properties/previous_segment_sha256/anyOf/0]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/header_body/properties/previous_segment_sha256/anyOf/0]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[supervised_run_status/$defs/event_body/properties/refs/items]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/event_body/properties/refs/items]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/event_body/properties/refs/items]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[supervised_run_status/$defs/terminal_body/properties/result_binding/anyOf/1/properties/envelope_digest]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/terminal_body/properties/result_binding/anyOf/1/properties/envelope_digest]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/terminal_body/properties/result_binding/anyOf/1/properties/envelope_digest]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[supervised_run_status/$defs/terminal_body/properties/result_binding/anyOf/1/properties/proposal_bytes_digest/anyOf/0]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/terminal_body/properties/result_binding/anyOf/1/properties/proposal_bytes_digest/anyOf/0]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/terminal_body/properties/result_binding/anyOf/1/properties/proposal_bytes_digest/anyOf/0]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[supervised_run_status/$defs/terminal_body/properties/result_binding/anyOf/1/properties/evidence_envelope_digest]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/terminal_body/properties/result_binding/anyOf/1/properties/evidence_envelope_digest]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/terminal_body/properties/result_binding/anyOf/1/properties/evidence_envelope_digest]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[supervised_run_status/$defs/projection/properties/assignment_digest]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/projection/properties/assignment_digest]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/projection/properties/assignment_digest]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[supervised_run_status/$defs/projection/properties/attempts/items/properties/attempt]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/projection/properties/attempts/items/properties/attempt]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/projection/properties/attempts/items/properties/attempt]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[supervised_run_status/$defs/projection/properties/attempts/items/properties/segment_sha256]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/projection/properties/attempts/items/properties/segment_sha256]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/projection/properties/attempts/items/properties/segment_sha256]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[supervised_run_status/$defs/page_request/properties/assignment_digest]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/page_request/properties/assignment_digest]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/page_request/properties/assignment_digest]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[supervised_run_status/$defs/page/properties/events/items]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/page/properties/events/items]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/page/properties/events/items]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[supervised_run_status/$defs/reader_view/properties/row/properties/assignment_digest]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/reader_view/properties/row/properties/assignment_digest]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/reader_view/properties/row/properties/assignment_digest]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[supervised_run_status/$defs/reader_view/properties/row/properties/snapshot_ref]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/reader_view/properties/row/properties/snapshot_ref]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/reader_view/properties/row/properties/snapshot_ref]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[supervised_run_status/$defs/reader_view/properties/run_record/properties/attempt]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/reader_view/properties/run_record/properties/attempt]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/reader_view/properties/run_record/properties/attempt]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[supervised_run_status/$defs/reader_view/properties/run_record/properties/units]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/reader_view/properties/run_record/properties/units]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/reader_view/properties/run_record/properties/units]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[supervised_run_status/$defs/reader_view/properties/display/properties/work_outcome/anyOf/1/properties/ref/anyOf/0]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/reader_view/properties/display/properties/work_outcome/anyOf/1/properties/ref/anyOf/0]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/reader_view/properties/display/properties/work_outcome/anyOf/1/properties/ref/anyOf/0]"
    },
    {
      "case_or_control_id": "test_nested_reference_negative[supervised_run_status/$defs/reader_view/properties/display/properties/evidence/anyOf/1/properties/ref]",
      "group": "schema_results",
      "outcome": "passed",
      "resource_sha256": {
        "admitted-launch-envelope.schema.json": "0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d",
        "conformance/README.md": "2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca",
        "conformance/SHA256SUMS": "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285",
        "conformance/envelope.vectors.json": "876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f",
        "conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
        "harness-provenance.json": "da50fae8312129c4db8996320247e4edb229fb50d8eaa20584d1d6a055476d4a",
        "run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30"
      },
      "runner_artifact_ref": "schema-suite-junit.xml#phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/reader_view/properties/display/properties/evidence/anyOf/1/properties/ref]",
      "test_node_id": "phase-loop-runtime/tests/test_supervised_contracts_vectors.py::test_nested_reference_negative[supervised_run_status/$defs/reader_view/properties/display/properties/evidence/anyOf/1/properties/ref]"
    }
  ],
  "semantic_cases": [
    {
      "classification": "schema_only",
      "expected_diagnostics": [],
      "expected_effect": {
        "attempt": {
          "state": "queued",
          "worker_invocations": 0
        }
      },
      "family": "admitted_launch_envelope.v1",
      "id": "E-admitted",
      "owner": "ENVELOPE/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [],
      "expected_effect": {
        "attempt": {
          "state": "queued",
          "worker_invocations": 0
        }
      },
      "family": "admitted_launch_envelope.v1",
      "id": "E-post-write-honest",
      "owner": "ENVELOPE/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [],
      "expected_effect": {
        "attempt": {
          "state": "queued",
          "worker_invocations": 0
        }
      },
      "family": "admitted_launch_envelope.v1",
      "id": "E-dependency-declared",
      "owner": "ENVELOPE/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "authority_baseline_stale"
      ],
      "expected_effect": {
        "attempt": {
          "state": "refused",
          "worker_invocations": 0
        }
      },
      "family": "admitted_launch_envelope.v1",
      "id": "RC16-stale-rehashed",
      "owner": "ENVELOPE/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "authority_foreign"
      ],
      "expected_effect": {
        "attempt": {
          "state": "refused",
          "worker_invocations": 0
        }
      },
      "family": "admitted_launch_envelope.v1",
      "id": "RC17-foreign-assignment-rehashed",
      "owner": "ENVELOPE/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "authority_foreign"
      ],
      "expected_effect": {
        "attempt": {
          "state": "refused",
          "worker_invocations": 0
        }
      },
      "family": "admitted_launch_envelope.v1",
      "id": "RC17-foreign-project-rehashed",
      "owner": "ENVELOPE/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "envelope_digest_mismatch"
      ],
      "expected_effect": {
        "attempt": {
          "state": "refused",
          "worker_invocations": 0
        }
      },
      "family": "admitted_launch_envelope.v1",
      "id": "S-digest-not-rehashed",
      "owner": "ENVELOPE/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "constraint_unsupported"
      ],
      "expected_effect": {
        "attempt": {
          "refusal": {
            "constraint": "network_denial",
            "reason": "constraint_unsupported",
            "tier": "provider_readonly_patch_return_audit"
          },
          "state": "refused",
          "worker_invocations": 0
        }
      },
      "family": "admitted_launch_envelope.v1",
      "id": "N21-network-required",
      "owner": "ENVELOPE/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "constraint_unsupported"
      ],
      "expected_effect": {
        "attempt": {
          "refusal": {
            "constraint": "command_denial",
            "reason": "constraint_unsupported",
            "tier": "provider_readonly_patch_return_audit"
          },
          "state": "refused",
          "worker_invocations": 0
        }
      },
      "family": "admitted_launch_envelope.v1",
      "id": "N21-command-required",
      "owner": "ENVELOPE/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "workspace_not_separate_copy"
      ],
      "expected_effect": {
        "attempt": {
          "state": "refused",
          "worker_invocations": 0
        }
      },
      "family": "admitted_launch_envelope.v1",
      "id": "N21-worktree-under-patch-return",
      "owner": "ENVELOPE/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "tier_unqualified"
      ],
      "expected_effect": {
        "attempt": {
          "state": "refused",
          "worker_invocations": 0
        }
      },
      "family": "admitted_launch_envelope.v1",
      "id": "S-os-enforced-unqualified",
      "owner": "ENVELOPE/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "dependency_digest_required"
      ],
      "expected_effect": {
        "attempt": {
          "state": "refused",
          "worker_invocations": 0
        }
      },
      "family": "admitted_launch_envelope.v1",
      "id": "S-dependency-without-digest",
      "owner": "ENVELOPE/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "locator_not_repo_relative"
      ],
      "expected_effect": {
        "attempt": {
          "state": "refused",
          "worker_invocations": 0
        }
      },
      "family": "admitted_launch_envelope.v1",
      "id": "S-envelope-absolute-locator",
      "owner": "ENVELOPE/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "raw_output_in_record"
      ],
      "expected_effect": {
        "attempt": {
          "state": "refused",
          "worker_invocations": 0
        }
      },
      "family": "admitted_launch_envelope.v1",
      "id": "S-envelope-raw-output",
      "owner": "ENVELOPE/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [],
      "expected_effect": null,
      "family": "admitted_launch_envelope.v1",
      "id": "E-echo",
      "owner": "ENVELOPE/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "caller_context_interpreted"
      ],
      "expected_effect": null,
      "family": "admitted_launch_envelope.v1",
      "id": "S-caller-context-interpreted",
      "owner": "ENVELOPE/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [],
      "expected_effect": {
        "display": [
          "finished",
          "finished"
        ]
      },
      "family": "supervised_run_status.v1",
      "id": "V-two-attempts",
      "owner": "JOURNAL/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [],
      "expected_effect": {
        "display": [
          "running"
        ]
      },
      "family": "supervised_run_status.v1",
      "id": "V-running",
      "owner": "JOURNAL/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [],
      "expected_effect": {
        "display": [
          "refused"
        ]
      },
      "family": "supervised_run_status.v1",
      "id": "V-refused-before-launch",
      "owner": "JOURNAL/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "attempt_overwritten"
      ],
      "expected_effect": null,
      "family": "supervised_run_status.v1",
      "id": "N04a-seq-skip",
      "owner": "JOURNAL/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "attempt_overwritten"
      ],
      "expected_effect": null,
      "family": "supervised_run_status.v1",
      "id": "N04a-seq-regress",
      "owner": "JOURNAL/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "attempt_overwritten"
      ],
      "expected_effect": null,
      "family": "supervised_run_status.v1",
      "id": "N04a-replaced-in-place",
      "owner": "JOURNAL/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "attempt_provenance_mismatch"
      ],
      "expected_effect": null,
      "family": "supervised_run_status.v1",
      "id": "N04b-foreign-binding",
      "owner": "JOURNAL/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "attempt_evidence_copied"
      ],
      "expected_effect": null,
      "family": "supervised_run_status.v1",
      "id": "S-evidence-copied",
      "owner": "JOURNAL/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "journal_torn_line"
      ],
      "expected_effect": {
        "display": [
          "unknown"
        ]
      },
      "family": "supervised_run_status.v1",
      "id": "N15-torn-line",
      "owner": "JOURNAL/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "journal_torn_line"
      ],
      "expected_effect": {
        "display": [
          "unknown"
        ]
      },
      "family": "supervised_run_status.v1",
      "id": "N15-no-final-newline",
      "owner": "JOURNAL/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "journal_unknown_version"
      ],
      "expected_effect": {
        "display": [
          "unknown"
        ]
      },
      "family": "supervised_run_status.v1",
      "id": "N15-unknown-version",
      "owner": "JOURNAL/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "journal_foreign_writer"
      ],
      "expected_effect": {
        "display": [
          "unknown"
        ]
      },
      "family": "supervised_run_status.v1",
      "id": "N15-foreign-writer",
      "owner": "JOURNAL/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "refused_after_launch"
      ],
      "expected_effect": null,
      "family": "supervised_run_status.v1",
      "id": "N19-refused-after-start",
      "owner": "JOURNAL/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "refused_after_launch"
      ],
      "expected_effect": null,
      "family": "supervised_run_status.v1",
      "id": "N19-refused-after-running",
      "owner": "JOURNAL/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "lifecycle_invalid"
      ],
      "expected_effect": null,
      "family": "supervised_run_status.v1",
      "id": "S-finished-without-termination",
      "owner": "JOURNAL/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "raw_output_in_record"
      ],
      "expected_effect": null,
      "family": "supervised_run_status.v1",
      "id": "N20-raw-stdout-ref",
      "owner": "JOURNAL/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "raw_output_in_record"
      ],
      "expected_effect": null,
      "family": "supervised_run_status.v1",
      "id": "N20-raw-message",
      "owner": "JOURNAL/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "locator_not_repo_relative"
      ],
      "expected_effect": null,
      "family": "supervised_run_status.v1",
      "id": "N20-absolute-locator",
      "owner": "JOURNAL/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "locator_not_repo_relative"
      ],
      "expected_effect": null,
      "family": "supervised_run_status.v1",
      "id": "N20-parent-locator",
      "owner": "JOURNAL/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [],
      "expected_effect": {
        "display": "current"
      },
      "family": "supervised_run_status.v1",
      "id": "V-projection-at-tail",
      "owner": "JOURNAL/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "projection_behind_journal"
      ],
      "expected_effect": {
        "display": "stale"
      },
      "family": "supervised_run_status.v1",
      "id": "N16-projection-behind",
      "owner": "JOURNAL/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "projection_behind_journal"
      ],
      "expected_effect": {
        "display": "stale"
      },
      "family": "supervised_run_status.v1",
      "id": "N16-attempt-missing",
      "owner": "JOURNAL/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "projection_not_from_journal"
      ],
      "expected_effect": null,
      "family": "supervised_run_status.v1",
      "id": "S-projection-ahead",
      "owner": "JOURNAL/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [],
      "expected_effect": {
        "display": [
          "running"
        ]
      },
      "family": "supervised_run_status.v1",
      "id": "V-owner-live",
      "owner": "JOURNAL/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "owner_not_live"
      ],
      "expected_effect": {
        "display": [
          "stale_unknown"
        ]
      },
      "family": "supervised_run_status.v1",
      "id": "N17-owner-not-live",
      "owner": "JOURNAL/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "owner_not_live"
      ],
      "expected_effect": {
        "display": [
          "stale_unknown"
        ]
      },
      "family": "supervised_run_status.v1",
      "id": "N17-pid-reused",
      "owner": "JOURNAL/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [],
      "expected_effect": null,
      "family": "supervised_run_status.v1",
      "id": "V-reader-view",
      "owner": "JOURNAL/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "runtime_not_work_outcome"
      ],
      "expected_effect": null,
      "family": "supervised_run_status.v1",
      "id": "N18-completed-as-outcome",
      "owner": "JOURNAL/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "runtime_not_work_outcome"
      ],
      "expected_effect": null,
      "family": "supervised_run_status.v1",
      "id": "N18-run-status-as-evidence",
      "owner": "JOURNAL/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "run_record_foreign"
      ],
      "expected_effect": null,
      "family": "supervised_run_status.v1",
      "id": "RC24-foreign-assignment",
      "owner": "JOURNAL/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "run_record_foreign"
      ],
      "expected_effect": null,
      "family": "supervised_run_status.v1",
      "id": "RC24-foreign-snapshot",
      "owner": "JOURNAL/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [],
      "expected_effect": null,
      "family": "supervised_run_status.v1",
      "id": "V-page",
      "owner": "JOURNAL/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "read_unbounded"
      ],
      "expected_effect": null,
      "family": "supervised_run_status.v1",
      "id": "RC25-no-page-size",
      "owner": "JOURNAL/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "read_unbounded"
      ],
      "expected_effect": null,
      "family": "supervised_run_status.v1",
      "id": "RC25-no-omitted",
      "owner": "JOURNAL/WORKER",
      "status": "upstream_phase_unmet"
    },
    {
      "classification": "schema_only",
      "expected_diagnostics": [
        "read_unbounded"
      ],
      "expected_effect": null,
      "family": "supervised_run_status.v1",
      "id": "RC25-over-bound",
      "owner": "JOURNAL/WORKER",
      "status": "upstream_phase_unmet"
    }
  ],
  "semantic_inventory": [
    {
      "id": "envelope:envelope_digest_mismatch",
      "owner": "ENVELOPE/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "admitted-launch-envelope.schema.json#/x-semantic-rules/envelope_digest_mismatch",
      "status": "upstream_phase_unmet",
      "vector_ids": [
        "S-digest-not-rehashed"
      ]
    },
    {
      "id": "envelope:authority_foreign",
      "owner": "ENVELOPE/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "admitted-launch-envelope.schema.json#/x-semantic-rules/authority_foreign",
      "status": "upstream_phase_unmet",
      "vector_ids": [
        "RC17-foreign-assignment-rehashed",
        "RC17-foreign-project-rehashed"
      ]
    },
    {
      "id": "envelope:authority_baseline_stale",
      "owner": "ENVELOPE/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "admitted-launch-envelope.schema.json#/x-semantic-rules/authority_baseline_stale",
      "status": "upstream_phase_unmet",
      "vector_ids": [
        "RC16-stale-rehashed"
      ]
    },
    {
      "id": "envelope:tier_unqualified",
      "owner": "ENVELOPE/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "admitted-launch-envelope.schema.json#/x-semantic-rules/tier_unqualified",
      "status": "upstream_phase_unmet",
      "vector_ids": [
        "S-os-enforced-unqualified"
      ]
    },
    {
      "id": "envelope:constraint_unsupported",
      "owner": "ENVELOPE/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "admitted-launch-envelope.schema.json#/x-semantic-rules/constraint_unsupported",
      "status": "upstream_phase_unmet",
      "vector_ids": [
        "N21-command-required",
        "N21-network-required"
      ]
    },
    {
      "id": "envelope:workspace_not_separate_copy",
      "owner": "ENVELOPE/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "admitted-launch-envelope.schema.json#/x-semantic-rules/workspace_not_separate_copy",
      "status": "upstream_phase_unmet",
      "vector_ids": [
        "N21-worktree-under-patch-return"
      ]
    },
    {
      "id": "envelope:locator_not_repo_relative",
      "owner": "ENVELOPE/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "admitted-launch-envelope.schema.json#/x-semantic-rules/locator_not_repo_relative",
      "status": "upstream_phase_unmet",
      "vector_ids": [
        "S-envelope-absolute-locator"
      ]
    },
    {
      "id": "envelope:dependency_digest_required",
      "owner": "ENVELOPE/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "admitted-launch-envelope.schema.json#/x-semantic-rules/dependency_digest_required",
      "status": "upstream_phase_unmet",
      "vector_ids": [
        "S-dependency-without-digest"
      ]
    },
    {
      "id": "envelope:raw_output_in_record",
      "owner": "ENVELOPE/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "admitted-launch-envelope.schema.json#/x-semantic-rules/raw_output_in_record",
      "status": "upstream_phase_unmet",
      "vector_ids": [
        "S-envelope-raw-output"
      ]
    },
    {
      "id": "envelope:caller_context_interpreted",
      "owner": "ENVELOPE/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "admitted-launch-envelope.schema.json#/x-semantic-rules/caller_context_interpreted",
      "status": "upstream_phase_unmet",
      "vector_ids": [
        "S-caller-context-interpreted"
      ]
    },
    {
      "id": "envelope:refusal_zero_invocations",
      "owner": "ENVELOPE/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "admitted-launch-envelope.schema.json#/x-semantic-rules/refusal_zero_invocations",
      "status": "upstream_phase_unmet",
      "vector_ids": []
    },
    {
      "id": "status:journal_torn_line",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-semantic-rules/journal_torn_line",
      "status": "upstream_phase_unmet",
      "vector_ids": [
        "N15-no-final-newline",
        "N15-torn-line"
      ]
    },
    {
      "id": "status:journal_malformed_line",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-semantic-rules/journal_malformed_line",
      "status": "upstream_phase_unmet",
      "vector_ids": []
    },
    {
      "id": "status:journal_unknown_version",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-semantic-rules/journal_unknown_version",
      "status": "upstream_phase_unmet",
      "vector_ids": [
        "N15-unknown-version"
      ]
    },
    {
      "id": "status:journal_foreign_writer",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-semantic-rules/journal_foreign_writer",
      "status": "upstream_phase_unmet",
      "vector_ids": [
        "N15-foreign-writer"
      ]
    },
    {
      "id": "status:attempt_overwritten",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-semantic-rules/attempt_overwritten",
      "status": "upstream_phase_unmet",
      "vector_ids": [
        "N04a-replaced-in-place",
        "N04a-seq-regress",
        "N04a-seq-skip"
      ]
    },
    {
      "id": "status:attempt_provenance_mismatch",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-semantic-rules/attempt_provenance_mismatch",
      "status": "upstream_phase_unmet",
      "vector_ids": [
        "N04b-foreign-binding"
      ]
    },
    {
      "id": "status:attempt_evidence_copied",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-semantic-rules/attempt_evidence_copied",
      "status": "upstream_phase_unmet",
      "vector_ids": [
        "S-evidence-copied"
      ]
    },
    {
      "id": "status:refused_after_launch",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-semantic-rules/refused_after_launch",
      "status": "upstream_phase_unmet",
      "vector_ids": [
        "N19-refused-after-running",
        "N19-refused-after-start"
      ]
    },
    {
      "id": "status:lifecycle_invalid",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-semantic-rules/lifecycle_invalid",
      "status": "upstream_phase_unmet",
      "vector_ids": [
        "S-finished-without-termination"
      ]
    },
    {
      "id": "status:raw_output_in_record",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-semantic-rules/raw_output_in_record",
      "status": "upstream_phase_unmet",
      "vector_ids": [
        "N20-raw-message",
        "N20-raw-stdout-ref"
      ]
    },
    {
      "id": "status:locator_not_repo_relative",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-semantic-rules/locator_not_repo_relative",
      "status": "upstream_phase_unmet",
      "vector_ids": [
        "N20-absolute-locator",
        "N20-parent-locator"
      ]
    },
    {
      "id": "status:projection_behind_journal",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-semantic-rules/projection_behind_journal",
      "status": "upstream_phase_unmet",
      "vector_ids": [
        "N16-attempt-missing",
        "N16-projection-behind"
      ]
    },
    {
      "id": "status:projection_not_from_journal",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-semantic-rules/projection_not_from_journal",
      "status": "upstream_phase_unmet",
      "vector_ids": [
        "S-projection-ahead"
      ]
    },
    {
      "id": "status:owner_not_live",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-semantic-rules/owner_not_live",
      "status": "upstream_phase_unmet",
      "vector_ids": [
        "N17-owner-not-live",
        "N17-pid-reused"
      ]
    },
    {
      "id": "status:run_record_foreign",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-semantic-rules/run_record_foreign",
      "status": "upstream_phase_unmet",
      "vector_ids": [
        "RC24-foreign-assignment",
        "RC24-foreign-snapshot"
      ]
    },
    {
      "id": "status:runtime_not_work_outcome",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-semantic-rules/runtime_not_work_outcome",
      "status": "upstream_phase_unmet",
      "vector_ids": [
        "N18-completed-as-outcome",
        "N18-run-status-as-evidence"
      ]
    },
    {
      "id": "status:read_unbounded",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-semantic-rules/read_unbounded",
      "status": "upstream_phase_unmet",
      "vector_ids": [
        "RC25-no-omitted",
        "RC25-no-page-size",
        "RC25-over-bound"
      ]
    },
    {
      "id": "journal:/x-journal-rules/location",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-journal-rules/location",
      "status": "upstream_phase_unmet",
      "vector_ids": []
    },
    {
      "id": "journal:/x-journal-rules/writers",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-journal-rules/writers",
      "status": "upstream_phase_unmet",
      "vector_ids": []
    },
    {
      "id": "journal:/x-journal-rules/segments",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-journal-rules/segments",
      "status": "upstream_phase_unmet",
      "vector_ids": []
    },
    {
      "id": "journal:/x-journal-rules/lifecycle",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-journal-rules/lifecycle",
      "status": "upstream_phase_unmet",
      "vector_ids": []
    },
    {
      "id": "journal:/x-journal-rules/lifecycle/queued",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-journal-rules/lifecycle/queued",
      "status": "upstream_phase_unmet",
      "vector_ids": []
    },
    {
      "id": "journal:/x-journal-rules/lifecycle/queued/0",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-journal-rules/lifecycle/queued/0",
      "status": "upstream_phase_unmet",
      "vector_ids": []
    },
    {
      "id": "journal:/x-journal-rules/lifecycle/queued/1",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-journal-rules/lifecycle/queued/1",
      "status": "upstream_phase_unmet",
      "vector_ids": []
    },
    {
      "id": "journal:/x-journal-rules/lifecycle/running",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-journal-rules/lifecycle/running",
      "status": "upstream_phase_unmet",
      "vector_ids": []
    },
    {
      "id": "journal:/x-journal-rules/lifecycle/running/0",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-journal-rules/lifecycle/running/0",
      "status": "upstream_phase_unmet",
      "vector_ids": []
    },
    {
      "id": "journal:/x-journal-rules/lifecycle/running/1",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-journal-rules/lifecycle/running/1",
      "status": "upstream_phase_unmet",
      "vector_ids": []
    },
    {
      "id": "journal:/x-journal-rules/lifecycle/cancelling",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-journal-rules/lifecycle/cancelling",
      "status": "upstream_phase_unmet",
      "vector_ids": []
    },
    {
      "id": "journal:/x-journal-rules/lifecycle/cancelling/0",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-journal-rules/lifecycle/cancelling/0",
      "status": "upstream_phase_unmet",
      "vector_ids": []
    },
    {
      "id": "journal:/x-journal-rules/lifecycle/finished",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-journal-rules/lifecycle/finished",
      "status": "upstream_phase_unmet",
      "vector_ids": []
    },
    {
      "id": "journal:/x-journal-rules/lifecycle/refused",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-journal-rules/lifecycle/refused",
      "status": "upstream_phase_unmet",
      "vector_ids": []
    },
    {
      "id": "journal:/x-journal-rules/bounds",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-journal-rules/bounds",
      "status": "upstream_phase_unmet",
      "vector_ids": []
    },
    {
      "id": "journal:/x-journal-rules/bounds/page_size_max",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-journal-rules/bounds/page_size_max",
      "status": "upstream_phase_unmet",
      "vector_ids": []
    },
    {
      "id": "journal:/x-journal-rules/bounds/event_message_max_chars",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-journal-rules/bounds/event_message_max_chars",
      "status": "upstream_phase_unmet",
      "vector_ids": []
    },
    {
      "id": "journal:/x-journal-rules/bounds/per_attempt_event_cap",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-journal-rules/bounds/per_attempt_event_cap",
      "status": "upstream_phase_unmet",
      "vector_ids": []
    },
    {
      "id": "journal:/x-journal-rules/bounds/attempts_per_page_max",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-journal-rules/bounds/attempts_per_page_max",
      "status": "upstream_phase_unmet",
      "vector_ids": []
    },
    {
      "id": "journal:/x-journal-rules/liveness",
      "owner": "JOURNAL/WORKER",
      "required_proof": "production paths and per-guard mutations at CLOSEOUT",
      "source_pointer": "run-status.schema.json#/x-journal-rules/liveness",
      "status": "upstream_phase_unmet",
      "vector_ids": []
    },
    {
      "id": "named:status-digest-text",
      "owner": "Contract owner; JOURNAL",
      "required_proof": "owner publication reconciliation and production proof at CLOSEOUT",
      "source_pointer": "plans/artifacts/v12-SCHEMA-inputs.md#named-coverage-obligations/status-digest-text",
      "status": "upstream_phase_unmet",
      "vector_ids": []
    },
    {
      "id": "named:lifecycle-shape",
      "owner": "Contract owner; JOURNAL",
      "required_proof": "owner publication reconciliation and production proof at CLOSEOUT",
      "source_pointer": "plans/artifacts/v12-SCHEMA-inputs.md#named-coverage-obligations/lifecycle-shape",
      "status": "upstream_phase_unmet",
      "vector_ids": []
    },
    {
      "id": "named:lifecycle-transitions",
      "owner": "Contract owner; JOURNAL",
      "required_proof": "owner publication reconciliation and production proof at CLOSEOUT",
      "source_pointer": "plans/artifacts/v12-SCHEMA-inputs.md#named-coverage-obligations/lifecycle-transitions",
      "status": "upstream_phase_unmet",
      "vector_ids": []
    },
    {
      "id": "named:lifecycle-process-result",
      "owner": "Contract owner; WORKER/JOURNAL",
      "required_proof": "owner publication reconciliation and production proof at CLOSEOUT",
      "source_pointer": "plans/artifacts/v12-SCHEMA-inputs.md#named-coverage-obligations/lifecycle-process-result",
      "status": "upstream_phase_unmet",
      "vector_ids": []
    },
    {
      "id": "named:identity-units",
      "owner": "Contract owner; ENVELOPE/JOURNAL",
      "required_proof": "owner publication reconciliation and production proof at CLOSEOUT",
      "source_pointer": "plans/artifacts/v12-SCHEMA-inputs.md#named-coverage-obligations/identity-units",
      "status": "upstream_phase_unmet",
      "vector_ids": []
    },
    {
      "id": "named:identity-public-replay",
      "owner": "Contract owner; ENVELOPE/JOURNAL/WORKER",
      "required_proof": "owner publication reconciliation and production proof at CLOSEOUT",
      "source_pointer": "plans/artifacts/v12-SCHEMA-inputs.md#named-coverage-obligations/identity-public-replay",
      "status": "upstream_phase_unmet",
      "vector_ids": []
    },
    {
      "id": "named:identity-journal-correlation",
      "owner": "Contract owner; JOURNAL",
      "required_proof": "owner publication reconciliation and production proof at CLOSEOUT",
      "source_pointer": "plans/artifacts/v12-SCHEMA-inputs.md#named-coverage-obligations/identity-journal-correlation",
      "status": "upstream_phase_unmet",
      "vector_ids": []
    },
    {
      "id": "named:route-public-controls",
      "owner": "Contract owner; ENVELOPE/WORKER",
      "required_proof": "owner publication reconciliation and production proof at CLOSEOUT",
      "source_pointer": "plans/artifacts/v12-SCHEMA-inputs.md#named-coverage-obligations/route-public-controls",
      "status": "upstream_phase_unmet",
      "vector_ids": []
    },
    {
      "id": "named:evidence-producer-binding",
      "owner": "Contract owner; JOURNAL/WORKER",
      "required_proof": "owner publication reconciliation and production proof at CLOSEOUT",
      "source_pointer": "plans/artifacts/v12-SCHEMA-inputs.md#named-coverage-obligations/evidence-producer-binding",
      "status": "upstream_phase_unmet",
      "vector_ids": []
    },
    {
      "id": "named:proposal-attempt-independence",
      "owner": "Contract owner; WORKER/JOURNAL",
      "required_proof": "owner publication reconciliation and production proof at CLOSEOUT",
      "source_pointer": "plans/artifacts/v12-SCHEMA-inputs.md#named-coverage-obligations/proposal-attempt-independence",
      "status": "upstream_phase_unmet",
      "vector_ids": []
    }
  ],
  "source_commit": "93db4b4fcc4e3d40c62f6658b6a67b519c750491",
  "suite_artifact_sha256": "49f9cb9bdfdde8bd9750c53ac89f14ac2034184619ea4998de0e026a8e279727",
  "tier_basis": {
    "os_enforced": {
      "constraints": {
        "command_denial": "not_enforced",
        "network_denial": "not_enforced",
        "write_scope": "not_enforced"
      },
      "qualified": false,
      "workspace_kinds": []
    },
    "post_write_audit_only": {
      "constraints": {
        "command_denial": "not_enforced",
        "network_denial": "not_enforced",
        "write_scope": "not_enforced"
      },
      "qualified": true,
      "workspace_kinds": [
        "separate_clone",
        "separate_copy",
        "git_worktree_of_protected",
        "in_place"
      ]
    },
    "provider_readonly_patch_return_audit": {
      "constraints": {
        "command_denial": "not_enforced",
        "network_denial": "not_enforced",
        "write_scope": "checked_before_apply"
      },
      "qualified": true,
      "workspace_kinds": [
        "separate_clone",
        "separate_copy"
      ]
    }
  }
}
```
