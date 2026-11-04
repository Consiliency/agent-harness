# ENVELOPE local seam receipt

Runner-observed offline results for agent-harness#1818 / agent-harness#1819.
This freezes IF-0-ENVELOPE-1 locally; it grants no public contract or live-use authority.
The observed input head identifies the approved plan input; source hashes bind the
implementation without predicting its eventual commit.

## Observed verification

Run from the repository root with the locked venv and absolute source/test PYTHONPATH.
V0: 59 passed. V1: 48 passed (24 intact production witnesses and 24 killed mutants).
V2: 53 passed, including 17 mutation cases. Startup regression: 16 passed.
The 23 collection-time skips in each broad selector are existing unrelated modules
requiring an unavailable optional tree; **zero selected producer tests were skipped**.
The effective producer suite has 160 nodes, all in the four owned producer modules.
V3 adds five receipt nodes, including three receipt falsifications after production entry.
The final whole-phase result is runner-recorded in the private implementation report.

Pre-implementation union collection: zero matches, 16809 deselected, pytest exit 5.
The approved plan review separately recorded all three distinct selector expressions as
zero; each of the five command locations is a subset of that verified empty union.
After implementation every owned producer file contributes nodes below; the receipt
collector also verifies the exact observed node inventory. No existing launcher or
startup regression can satisfy an ENVELOPE acceptance selector.

Commands (use `python3` from the locked venv):

- V0: `python3 -m pytest -q phase-loop-runtime/tests -k "test_supervised_launch.py"`
- V1: `python3 -m pytest -q phase-loop-runtime/tests -k supervised_launch_mutations`
- V2: `python3 -m pytest -q phase-loop-runtime/tests -k "supervised_launch_binding or supervised_launch_route"`
- Startup: `python3 -m pytest -q phase-loop-runtime/tests -k executable_dependency_startup`
- V3: `python3 -m pytest -q phase-loop-runtime/tests -k supervised_launch_receipt`
- Suite: `python3 -m pytest -q phase-loop-runtime/tests -k "test_supervised_launch.py or test_supervised_launch_mutations.py or test_supervised_launch_binding.py or test_supervised_launch_route.py or test_supervised_launch_receipt.py"`

## Mutation witnesses

SL-0 removes each named production guard from an isolated compiled copy of the actual
module. Each unchanged rejection assertion passes against the intact module and turns
red against its mutant. No test-only admission model is used. The list below names
all 24 controls: verdict digest/attempt binding, exact typed admit, identity-only launch
digest, atomic single-use consumption, qualification, workspace classification, tier,
constraints, reference digest, five separate consumption checks and six reference/size
checks, shared physical storage, unreadable storage and root/operator executable ownership,
and single parse/hash capture.
The FIFO witness is synthetic and nonblocking; device identity uses synthetic
stat returns, with no mount trial. Reference cap witnesses isolate the cap from the
digest comparison. All copies are discarded; production sources stay intact.

SL-1 kills uid and mode mutants independently for binding, validator, codec,
qualification, template and config (12 cases); one absolute import resolution mutant;
one classification mutant; one declared-dependency mutant; and two direct required
session guard mutants. UID mismatches are synthetic fstat metadata, without chown.
The binding witness stops at the loader to avoid an intact downstream recheck masking
a removed loader guard. Isolated Python children print their checkout module path;
the absolute paths are recorded in the private runner log, and resolve to
`phase-loop-runtime/src/phase_loop_runtime/__init__.py` here. Ambient stdlib,
validator, package and codec shadows never supply the trusted implementation.
Mode-sensitive fixtures pin umask 077 and restore it; unsafe modes use chmod.

SL-2 first consumes a real production admission and proves refusal, then falsifies a
source binding, result inventory or authority label in a temporary receipt. All three
must turn the receipt validation assertion red. Fixture text is not a behavior oracle.

## Limitations and handoff

Public codec/schema reconciliation, production semantic vectors, installed-tool
qualification, lifecycle activation, exact-head CI/Gate A and independent CLOSEOUT
review remain pending. JOURNAL must add durable replay reservation; WORKER must add
the module CLI, safe envelope-file ingestion, bounded probes/subprocesses and immediate
pre-spawn identity checks. No live providers, credentials, network, sandbox or mounts
were exercised. No private contract or repository is required.

Both tiers refuse all requested constraint cells, and os_enforced always refuses.
Standalone routing preserves task_unbound and dependency_route_unwired. There is no
same-login containment, network denial, journal authenticity against same-login
writers or protection of on-disk git/gh credentials. Descriptor execution is absent
from this process-free seam; the future check-to-exec race must remain disclosed.

Doc decision: docs_updated for the local API guide. README/release notes need no delta;
WORKER owns the integrated CHANGELOG update. Spec closeout: spec_delta_closeout.v1,
canonical_spec_update, target docs/supervised-worker.md, redaction_posture metadata_only.
No roadmap amendment or public-schema acceptance is claimed. The optional manifest
lifecycle write was withheld because plans/manifest.json is outside the plan's owned
files; this is a nonfatal ledger warning, not an ownership transfer.

## Runner-stamped producer record

```json
{
  "authority": "synthetic_fixture_only",
  "gate": "IF-0-ENVELOPE-1",
  "ec_status": {
    "EC-ENVELOPE-1": "local_fixture_pass",
    "EC-ENVELOPE-2": "local_fixture_pass",
    "EC-ENVELOPE-3": "local_fixture_pass"
  },
  "runner_stamp": {
    "observed_utc": "2026-11-04T21:12:24.882783+00:00",
    "observed_input_head": "c1aac3c19b711f9688bddc2bda11128d928b3ad9",
    "source_tree_digest": "e2dfeb0884e1736822ca72e2f64be9d7076c72360bbdcfa0d9deffdaa2795983"
  },
  "source_hashes": {
    "phase-loop-runtime/src/phase_loop_runtime/supervised_launch.py": "e64b0f4f90d4f9d8d7f305831a8778511ad7a43e0890661784d09b5ffdd953a1",
    "phase-loop-runtime/src/phase_loop_runtime/supervised_launch_binding.py": "d33f237ec183659f0e323561cad132c11563924f91ac1ecd7e87b00dcbf9fd15",
    "phase-loop-runtime/src/phase_loop_runtime/supervised_dependency.py": "fbe509362cd3f9bd79df0b733275df77ef210166a9db1487daf90a066427a664",
    "phase-loop-runtime/src/phase_loop_runtime/executable_dependency_startup.py": "a222e325045721980e7f0e7cdbe3945acd6b73c9b072355bc3181e5ae10f4693",
    "phase-loop-runtime/tests/test_supervised_launch.py": "21204eb006ed1723128f4b45ad06b3bf25db45b223688017f1ec88940f6789fd",
    "phase-loop-runtime/tests/test_supervised_launch_mutations.py": "45e3c479a54068d06816715aca90325e06283f0067dd599226a4b233ee4240a8",
    "phase-loop-runtime/tests/test_supervised_launch_binding.py": "da9986280583d9b67b72f549fbb475bc0af527992008059e71350f38e6be334c",
    "phase-loop-runtime/tests/test_supervised_launch_route.py": "5c356c65731037f068facbc56af17f15426a5fc5678f4fcdd73f7bb54f231ff1",
    "phase-loop-runtime/tests/test_supervised_launch_receipt.py": "e762eb6ccf01a4fe9a8f7775401c08afbcab04d899dbd178135dfc71bc457d60",
    "phase-loop-runtime/tests/fixtures/supervised_launch_local/envelope.json": "2c69f75c4bdcaf8f28b8ff40a92b9db21e4403bf7fd2ab8ff10d4df622463298",
    "docs/supervised-worker.md": "42a24b9087a70ec89d64b6750074e8f7b5c5c33777781826092a5c664dfbe300"
  },
  "producer_nodes": [
    "tests/test_supervised_launch.py::test_ambiguous_json_before_codec[{\"x\":1,\"x\":2}]",
    "tests/test_supervised_launch.py::test_ambiguous_json_before_codec[{\"x\":Infinity}]",
    "tests/test_supervised_launch.py::test_ambiguous_json_before_codec[{\"x\":NaN}]",
    "tests/test_supervised_launch.py::test_audit_worktree_and_in_place",
    "tests/test_supervised_launch.py::test_constraint_matrix[False-command_denial]",
    "tests/test_supervised_launch.py::test_constraint_matrix[False-network_denial]",
    "tests/test_supervised_launch.py::test_constraint_matrix[False-unknown]",
    "tests/test_supervised_launch.py::test_constraint_matrix[False-write_scope]",
    "tests/test_supervised_launch.py::test_constraint_matrix[True-command_denial]",
    "tests/test_supervised_launch.py::test_constraint_matrix[True-network_denial]",
    "tests/test_supervised_launch.py::test_constraint_matrix[True-unknown]",
    "tests/test_supervised_launch.py::test_constraint_matrix[True-write_scope]",
    "tests/test_supervised_launch.py::test_consumption_rechecks[consume_class]",
    "tests/test_supervised_launch.py::test_consumption_rechecks[consume_device]",
    "tests/test_supervised_launch.py::test_consumption_rechecks[consume_executable]",
    "tests/test_supervised_launch.py::test_consumption_rechecks[consume_inode]",
    "tests/test_supervised_launch.py::test_consumption_rechecks[consume_wrapper]",
    "tests/test_supervised_launch.py::test_every_launch_input_substitution[baseline]",
    "tests/test_supervised_launch.py::test_every_launch_input_substitution[constraints]",
    "tests/test_supervised_launch.py::test_every_launch_input_substitution[executable]",
    "tests/test_supervised_launch.py::test_every_launch_input_substitution[instruction]",
    "tests/test_supervised_launch.py::test_every_launch_input_substitution[target]",
    "tests/test_supervised_launch.py::test_every_launch_input_substitution[tier]",
    "tests/test_supervised_launch.py::test_every_launch_input_substitution[timeout]",
    "tests/test_supervised_launch.py::test_every_launch_input_substitution[workspace]",
    "tests/test_supervised_launch.py::test_every_launch_input_substitution[wrappers]",
    "tests/test_supervised_launch.py::test_exception_and_unavailable_validator",
    "tests/test_supervised_launch.py::test_executable_path_refusal[empty_path]",
    "tests/test_supervised_launch.py::test_executable_path_refusal[missing]",
    "tests/test_supervised_launch.py::test_executable_path_refusal[relative_path]",
    "tests/test_supervised_launch.py::test_executable_path_refusal[symlink]",
    "tests/test_supervised_launch.py::test_executable_path_refusal[workspace]",
    "tests/test_supervised_launch.py::test_executable_path_refusal[writable]",
    "tests/test_supervised_launch.py::test_identity_only_launch_digest",
    "tests/test_supervised_launch.py::test_non_admit[1]",
    "tests/test_supervised_launch.py::test_non_admit[None]",
    "tests/test_supervised_launch.py::test_non_admit[True]",
    "tests/test_supervised_launch.py::test_non_admit[admit]",
    "tests/test_supervised_launch.py::test_provider_physical_shared_storage",
    "tests/test_supervised_launch.py::test_provider_uninspectable_storage",
    "tests/test_supervised_launch.py::test_qualification_missing_mismatched_and_positive",
    "tests/test_supervised_launch.py::test_reference_controls[aggregate_cap]",
    "tests/test_supervised_launch.py::test_reference_controls[envelope_cap]",
    "tests/test_supervised_launch.py::test_reference_controls[reference_cap]",
    "tests/test_supervised_launch.py::test_reference_controls[reference_nofollow]",
    "tests/test_supervised_launch.py::test_reference_controls[reference_regular]",
    "tests/test_supervised_launch.py::test_reference_controls[reference_root]",
    "tests/test_supervised_launch.py::test_root_owned_executable_identity",
    "tests/test_supervised_launch.py::test_side_channels_and_missing_inputs",
    "tests/test_supervised_launch.py::test_single_use_immutable_snapshots_and_identities",
    "tests/test_supervised_launch.py::test_tier_refusal[os_enforced]",
    "tests/test_supervised_launch.py::test_tier_refusal[unknown]",
    "tests/test_supervised_launch.py::test_verdict_binding[attempt_id]",
    "tests/test_supervised_launch.py::test_verdict_binding[launch_digest]",
    "tests/test_supervised_launch.py::test_workspace_provider_storage[alternates]",
    "tests/test_supervised_launch.py::test_workspace_provider_storage[commondir]",
    "tests/test_supervised_launch.py::test_workspace_provider_storage[gitfile]",
    "tests/test_supervised_launch.py::test_workspace_provider_storage[hardlink]",
    "tests/test_supervised_launch.py::test_workspace_provider_storage[symlink]",
    "tests/test_supervised_launch_binding.py::test_binding_absent_and_unisolated",
    "tests/test_supervised_launch_binding.py::test_binding_isolated_absolute_and_transitive_shadowing",
    "tests/test_supervised_launch_binding.py::test_binding_trusted_import_mutation",
    "tests/test_supervised_launch_binding.py::test_binding_trusted_inputs[group-binding]",
    "tests/test_supervised_launch_binding.py::test_binding_trusted_inputs[group-codec]",
    "tests/test_supervised_launch_binding.py::test_binding_trusted_inputs[group-config]",
    "tests/test_supervised_launch_binding.py::test_binding_trusted_inputs[group-qualification]",
    "tests/test_supervised_launch_binding.py::test_binding_trusted_inputs[group-template]",
    "tests/test_supervised_launch_binding.py::test_binding_trusted_inputs[group-validator]",
    "tests/test_supervised_launch_binding.py::test_binding_trusted_inputs[owner-binding]",
    "tests/test_supervised_launch_binding.py::test_binding_trusted_inputs[owner-codec]",
    "tests/test_supervised_launch_binding.py::test_binding_trusted_inputs[owner-config]",
    "tests/test_supervised_launch_binding.py::test_binding_trusted_inputs[owner-qualification]",
    "tests/test_supervised_launch_binding.py::test_binding_trusted_inputs[owner-template]",
    "tests/test_supervised_launch_binding.py::test_binding_trusted_inputs[owner-validator]",
    "tests/test_supervised_launch_binding.py::test_binding_trusted_inputs[symlink-binding]",
    "tests/test_supervised_launch_binding.py::test_binding_trusted_inputs[symlink-codec]",
    "tests/test_supervised_launch_binding.py::test_binding_trusted_inputs[symlink-config]",
    "tests/test_supervised_launch_binding.py::test_binding_trusted_inputs[symlink-qualification]",
    "tests/test_supervised_launch_binding.py::test_binding_trusted_inputs[symlink-template]",
    "tests/test_supervised_launch_binding.py::test_binding_trusted_inputs[symlink-validator]",
    "tests/test_supervised_launch_binding.py::test_binding_trusted_inputs[world-binding]",
    "tests/test_supervised_launch_binding.py::test_binding_trusted_inputs[world-codec]",
    "tests/test_supervised_launch_binding.py::test_binding_trusted_inputs[world-config]",
    "tests/test_supervised_launch_binding.py::test_binding_trusted_inputs[world-qualification]",
    "tests/test_supervised_launch_binding.py::test_binding_trusted_inputs[world-template]",
    "tests/test_supervised_launch_binding.py::test_binding_trusted_inputs[world-validator]",
    "tests/test_supervised_launch_binding.py::test_binding_uid_mode_mutations[trusted_mode-binding]",
    "tests/test_supervised_launch_binding.py::test_binding_uid_mode_mutations[trusted_mode-codec]",
    "tests/test_supervised_launch_binding.py::test_binding_uid_mode_mutations[trusted_mode-config]",
    "tests/test_supervised_launch_binding.py::test_binding_uid_mode_mutations[trusted_mode-qualification]",
    "tests/test_supervised_launch_binding.py::test_binding_uid_mode_mutations[trusted_mode-template]",
    "tests/test_supervised_launch_binding.py::test_binding_uid_mode_mutations[trusted_mode-validator]",
    "tests/test_supervised_launch_binding.py::test_binding_uid_mode_mutations[trusted_uid-binding]",
    "tests/test_supervised_launch_binding.py::test_binding_uid_mode_mutations[trusted_uid-codec]",
    "tests/test_supervised_launch_binding.py::test_binding_uid_mode_mutations[trusted_uid-config]",
    "tests/test_supervised_launch_binding.py::test_binding_uid_mode_mutations[trusted_uid-qualification]",
    "tests/test_supervised_launch_binding.py::test_binding_uid_mode_mutations[trusted_uid-template]",
    "tests/test_supervised_launch_binding.py::test_binding_uid_mode_mutations[trusted_uid-validator]",
    "tests/test_supervised_launch_binding.py::test_binding_workspace_location",
    "tests/test_supervised_launch_binding.py::test_external_binding_non_admit",
    "tests/test_supervised_launch_mutations.py::test_production_control_witness[admit_binding]",
    "tests/test_supervised_launch_mutations.py::test_production_control_witness[aggregate_cap]",
    "tests/test_supervised_launch_mutations.py::test_production_control_witness[capture_once]",
    "tests/test_supervised_launch_mutations.py::test_production_control_witness[constraints_unsupported]",
    "tests/test_supervised_launch_mutations.py::test_production_control_witness[consume_class]",
    "tests/test_supervised_launch_mutations.py::test_production_control_witness[consume_device]",
    "tests/test_supervised_launch_mutations.py::test_production_control_witness[consume_executable]",
    "tests/test_supervised_launch_mutations.py::test_production_control_witness[consume_inode]",
    "tests/test_supervised_launch_mutations.py::test_production_control_witness[consume_wrapper]",
    "tests/test_supervised_launch_mutations.py::test_production_control_witness[envelope_cap]",
    "tests/test_supervised_launch_mutations.py::test_production_control_witness[executable_owner_policy]",
    "tests/test_supervised_launch_mutations.py::test_production_control_witness[identity_digest]",
    "tests/test_supervised_launch_mutations.py::test_production_control_witness[qualification]",
    "tests/test_supervised_launch_mutations.py::test_production_control_witness[reference_cap]",
    "tests/test_supervised_launch_mutations.py::test_production_control_witness[reference_digest]",
    "tests/test_supervised_launch_mutations.py::test_production_control_witness[reference_nofollow]",
    "tests/test_supervised_launch_mutations.py::test_production_control_witness[reference_regular]",
    "tests/test_supervised_launch_mutations.py::test_production_control_witness[reference_root]",
    "tests/test_supervised_launch_mutations.py::test_production_control_witness[tier_unsupported]",
    "tests/test_supervised_launch_mutations.py::test_production_control_witness[token]",
    "tests/test_supervised_launch_mutations.py::test_production_control_witness[typed_admit]",
    "tests/test_supervised_launch_mutations.py::test_production_control_witness[workspace]",
    "tests/test_supervised_launch_mutations.py::test_production_control_witness[workspace_shared]",
    "tests/test_supervised_launch_mutations.py::test_production_control_witness[workspace_uninspectable]",
    "tests/test_supervised_launch_mutations.py::test_supervised_launch_mutations[admit_binding]",
    "tests/test_supervised_launch_mutations.py::test_supervised_launch_mutations[aggregate_cap]",
    "tests/test_supervised_launch_mutations.py::test_supervised_launch_mutations[capture_once]",
    "tests/test_supervised_launch_mutations.py::test_supervised_launch_mutations[constraints_unsupported]",
    "tests/test_supervised_launch_mutations.py::test_supervised_launch_mutations[consume_class]",
    "tests/test_supervised_launch_mutations.py::test_supervised_launch_mutations[consume_device]",
    "tests/test_supervised_launch_mutations.py::test_supervised_launch_mutations[consume_executable]",
    "tests/test_supervised_launch_mutations.py::test_supervised_launch_mutations[consume_inode]",
    "tests/test_supervised_launch_mutations.py::test_supervised_launch_mutations[consume_wrapper]",
    "tests/test_supervised_launch_mutations.py::test_supervised_launch_mutations[envelope_cap]",
    "tests/test_supervised_launch_mutations.py::test_supervised_launch_mutations[executable_owner_policy]",
    "tests/test_supervised_launch_mutations.py::test_supervised_launch_mutations[identity_digest]",
    "tests/test_supervised_launch_mutations.py::test_supervised_launch_mutations[qualification]",
    "tests/test_supervised_launch_mutations.py::test_supervised_launch_mutations[reference_cap]",
    "tests/test_supervised_launch_mutations.py::test_supervised_launch_mutations[reference_digest]",
    "tests/test_supervised_launch_mutations.py::test_supervised_launch_mutations[reference_nofollow]",
    "tests/test_supervised_launch_mutations.py::test_supervised_launch_mutations[reference_regular]",
    "tests/test_supervised_launch_mutations.py::test_supervised_launch_mutations[reference_root]",
    "tests/test_supervised_launch_mutations.py::test_supervised_launch_mutations[tier_unsupported]",
    "tests/test_supervised_launch_mutations.py::test_supervised_launch_mutations[token]",
    "tests/test_supervised_launch_mutations.py::test_supervised_launch_mutations[typed_admit]",
    "tests/test_supervised_launch_mutations.py::test_supervised_launch_mutations[workspace]",
    "tests/test_supervised_launch_mutations.py::test_supervised_launch_mutations[workspace_shared]",
    "tests/test_supervised_launch_mutations.py::test_supervised_launch_mutations[workspace_uninspectable]",
    "tests/test_supervised_launch_route.py::test_classification_and_status_preserve_generic_inventory",
    "tests/test_supervised_launch_route.py::test_declared_dependency_mutation",
    "tests/test_supervised_launch_route.py::test_direct_api_guard_before_decode[False-task_unbound]",
    "tests/test_supervised_launch_route.py::test_direct_api_guard_before_decode[True-dependency_route_unwired]",
    "tests/test_supervised_launch_route.py::test_direct_api_guard_mutation[False-task_unbound]",
    "tests/test_supervised_launch_route.py::test_direct_api_guard_mutation[True-dependency_route_unwired]",
    "tests/test_supervised_launch_route.py::test_required_route_before_effects[supervised-cancel-False-task_unbound]",
    "tests/test_supervised_launch_route.py::test_required_route_before_effects[supervised-cancel-True-dependency_route_unwired]",
    "tests/test_supervised_launch_route.py::test_required_route_before_effects[supervised-launch-False-task_unbound]",
    "tests/test_supervised_launch_route.py::test_required_route_before_effects[supervised-launch-True-dependency_route_unwired]",
    "tests/test_supervised_launch_route.py::test_route_classification_mutation",
    "tests/test_supervised_launch_route.py::test_standalone_dependency_declaration"
  ],
  "producer_passed": 160,
  "producer_skipped": 0,
  "preimplementation_selected": 0,
  "observed_checks": {
    "v0": {
      "passed": 59,
      "collection_skipped": 23,
      "deselected": 16915,
      "seconds": 22.56
    },
    "v1": {
      "passed": 48,
      "collection_skipped": 23,
      "deselected": 16926,
      "seconds": 23.94
    },
    "v2": {
      "passed": 53,
      "collection_skipped": 23,
      "deselected": 16921,
      "seconds": 12.3
    },
    "startup": {
      "passed": 16,
      "collection_skipped": 23,
      "deselected": 16919,
      "seconds": 2.43
    }
  },
  "mutation_controls": [
    "admit_binding",
    "typed_admit",
    "identity_digest",
    "token",
    "qualification",
    "workspace",
    "tier_unsupported",
    "constraints_unsupported",
    "reference_digest",
    "workspace_shared",
    "workspace_uninspectable",
    "executable_owner_policy",
    "capture_once",
    "consume_class",
    "consume_device",
    "consume_inode",
    "consume_executable",
    "consume_wrapper",
    "reference_root",
    "reference_nofollow",
    "reference_regular",
    "reference_cap",
    "aggregate_cap",
    "envelope_cap",
    "trusted_uid_each_input",
    "trusted_mode_each_input",
    "trusted_import",
    "route_classification",
    "declared_dependency",
    "direct_required_unleased",
    "direct_required_bound",
    "receipt_stale_binding",
    "receipt_missing_results",
    "receipt_false_authority"
  ],
  "pending": [
    "public_schema_reconciliation",
    "installed_tool_qualification",
    "registry_activation",
    "exact_head_ci_gate_a",
    "independent_closeout_review",
    "live_use_authority"
  ]
}
```
