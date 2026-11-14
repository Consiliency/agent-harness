# Supervised worker contracts

`phase_loop_runtime.supervised_contracts.load_contract_bundle()` preserves the
v1 default. `load_contract_bundle(version="v2")` selects the separately pinned
public v2 envelope and unchanged `supervised_run_status.v1`. Both return captured,
immutable resource bytes. `validate_record(bundle, family, raw, definition=None)`
checks structure and returns `None`, or a closed `ContractError`. Structural
validity alone grants no admission or qualification.

The reviewed inputs are [SCHEMA](../plans/artifacts/v12-SCHEMA-inputs.md) and
[CLOSEOUT](../plans/artifacts/v12-CLOSEOUT-inputs.md). The latter pins
`Consiliency/consiliency-contract` revision
`2b91ef85bfdc76239ae52806b3318513951543ab`. Package resources preserve the
approved original bytes and version declarations. The manifest seals the inputs;
changing pins requires a reviewed input amendment on the trusted base before an
implementation uses them. Historical SCHEMA, ENVELOPE, JOURNAL and WORKER receipts
retain their original bytes and describe their original runs.

Strict public intake rejects duplicate keys, nonfinite numbers, invalid Unicode
scalars and numbers outside the v2 interoperable binary64 domain. The codec
implements RFC 8785 bytes and digest computation. The private corpus extractor
retains deliberately invalid number tokens and scalar strings for negative
controls; it cannot produce an admissible public record. Verified schemas use
an offline reference registry. Resource bytes are hashed before parsing.

## Production binding and held inputs

The isolated worker chooses one operator-owned record:
`<passwd-home>/.local/state/phase-loop/supervised-launch-binding.json`. The home
comes from `pwd.getpwuid(os.getuid()).pw_dir`; environment variables, argv,
controller documents and cwd cannot select another location. Provisioning that
record is deployment work. Missing or untrusted configuration refuses before
launch, without discovery or fallback. The
[binding-location decision](../plans/artifacts/v12-CLOSEOUT-binding-location.md)
fixes the exact sequence and refusal mapping.

Route preflight and isolation precede envelope intake. The CLI holds the envelope
bytes, reads only the trusted binding locator, then holds the complete controller
document named by the envelope-bytes SHA-256. The document supplies the
`AttemptBinding`, independent expected assignment/snapshot/crosswalk context and
complete root/argv slots. A passive `load_v2_binding` checks all referenced inputs
under those exclusions. Literal binding-byte agreement and controller
reconciliation precede separate activation from the held implementation bytes.
Production never calls the eager fixture loader for this full load.

`capture_launch_v2` holds the effective launch material. `prepare_launch_v2`
validates that capture with the independent context and public codec. The
process-local admission token is spent once; `discard_admission` closes an unused
capture. Rechecks at consumption and the final spawn boundary preserve the
captured launch. Actual environment delivery is separate from the public
`{non_secret, secret_names}` commitment. Credentials and their value hashes are
excluded from public material, validators, receipts and diagnostics.

## Trusted boot and evidence

Helpers and the production worker launch through
`seat_uid.trusted_module_argv("phase_loop_runtime.supervised_worker_cli", ...)`.
The isolated installation-root boot is part of the production launcher identity,
including native cancellation matching (agent-harness#1132 and
agent-harness#1957). This is the WORKER contract section 6 clarification tracked
by agent-harness#1960 item 6; the other follow-ups remain separate.

The `supervised contract publication` check compares the complete approved
resource distribution and an extracted wheel. Only its full-path artifact with
`contract=true` supplies publication proof. The CLOSEOUT verifier resolves live
protected-main requirements and hosted run/job/artifact identities through the
GitHub API. It checks content identity, receipt-only stamp deltas and verified
post-landing correspondence. A governing-content change invalidates the old
assessment.

Both versions' harness provenance and the CLOSEOUT assessment retain
`byte_pin_authority=false`. The pinned publisher is provisional. Independently
owned controller/display evidence and approved board/president publisher
bindings remain required. Read [readiness](supervised-worker-readiness.md) for
those blocked edges and the separate offline, installed and live statuses.
