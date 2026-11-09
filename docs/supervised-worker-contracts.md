# Supervised worker schema intake

`phase_loop_runtime.supervised_contracts` provides an internal, offline JSON Schema
seam for the frozen v1 public distribution. `load_contract_bundle()` returns an
immutable `ContractBundle`; `resource_bytes(name)` returns the captured bytes for
an exact allowlisted resource. `validate_record(bundle, family, record: bytes,
definition=None)` returns `None` for schema validity and raises a closed
`ContractError(code, resource)` otherwise. It performs no admission or runtime
semantic evaluation. Launch and journal modules do not consume this seam.

The families are `admitted_launch_envelope.v1` (no definition selector) and
`supervised_run_status.v1` (default `journal_line`, also `projection`,
`page_request`, `page`, `reader_view`). Strict JSON intake rejects duplicate
keys, lone Unicode surrogates, nonfinite numbers and integer literals outside the exact interoperable
integer domain. Finite numeric forms keep their JSON Schema types. These
conditions are distinct from the schemas' structural rules and from JCS byte
canonicalization. Record objects must be supplied as UTF-8 JSON bytes.

The loader hashes and parses one captured buffer per resource. It uses
`importlib.resources` inside the runtime package, an offline `referencing`
registry and draft 2020-12 validation. It checks support for jsonschema 4.18+
and compatible referencing APIs; older installations refuse with
`runtime_unsupported`. The dependency floor is unchanged. Pattern compatibility
preserves ECMA-262 end-anchor behavior for every declared SHA-256 reference
without editing upstream bytes. Errors contain only approved codes and resource
names, with no instance values or underlying exception text.

## Publication and provenance

The sole input commit is public `Consiliency/consiliency-contract` revision
`93db4b4fcc4e3d40c62f6658b6a67b519c750491`, path `core/supervised-run/`.
The complete reviewed digest/blob inventory is
[`v12-SCHEMA-inputs.md`](../plans/artifacts/v12-SCHEMA-inputs.md), sealed by
the SCHEMA entry in `plans/manifest.json`. The code-owned pin table and an
independent SHA256SUMS anchor are compared with that inventory. Changed bytes
require reviewed repinning.

Six resources are byte-identical: both schemas, both vector files, the conformance
README and SHA256SUMS. Upstream `provenance.json` is inventoried by digest/blob
only and is excluded from the runtime closure. The separately named
`harness-provenance.json` is harness-authored, digest-pinned metadata, outside the
six upstream files. The installed package carries the complete nested closure.

The `supervised contract publication` check is required and is a successful no-op
on non-contract changes. Its `supervised-contract-intake` workflow runs on every
pull request and every push to main with no path filter. The workflow pins the
vendored resource subtree, loader, packaging declarations, comparison script,
independent anchor test, frozen artifact and workflow paths; manifest changes
count only when the SCHEMA frozen-input seal changes. For contract changes it fetches the public commit
read-only, checks protected default
branch ancestry, compares actual vendor bytes/blobs and sealed inputs, and runs
intake tests with an extracted wheel ahead of the checkout. Ordinary tests never
fetch the network. Hosted run/job/head and result artifact identities belong in
the receipt; a failed hosted comparison blocks intake completion and landing.
The check is required by the current `main` branch protection. The workflow
itself does not modify repository settings.

## Authority and coverage

[`SCHEMA.md`](../plans/evidence/supervised-worker/SCHEMA.md) separates intake,
structural schema and mutation runner results. Published negative cases are
schema-valid by construction: schema success never proves their expected
semantic diagnostics or effects. All 16 envelope and 35 status cases are
inventoried, along with every semantic rule, recursive journal-rule entry and
named obligation. Even obligations without vectors stay explicit and unresolved
as `upstream_phase_unmet` until production proof at CLOSEOUT.

`IF-0-SCHEMA-1` records the v1 intake interface independently of
`byte_pin_authority`, which remains **false**. No v2 revision or digest is pinned.
The owner will publish v2 alongside unchanged v1 through a reviewed squash merge.
Publication alone cannot resolve the outstanding runtime obligations.

The launch coverage reconciliation includes instruction/reference bytes, argv
JCS digest, executable/wrapper identity, workspace source/baseline and integer
timeout bounds. It also covers effective environment, trusted policy and tool
qualification, action/route/delivery, and conditional execution-view/egress
grants. Opaque caller context, snapshot/crosswalk references and obligation
digests cannot stand in for those bindings. v2 has no caller_context or
harness-local fields. Local wire additions are outside this phase.

The v1 tier annotations describe semantics and limits; they do not qualify a
provider. `provider_readonly_patch_return_audit` has `checked_before_apply`
write scope, `post_write_audit_only` has `not_enforced`, and `os_enforced` is
unqualified. Preserve independent qualification and `route_not_qualified`.
`E-admitted`, `E-echo` and `E-dependency-declared` each need write-scope
reconciliation; declared dependencies also need an owner-approved route mapping.
Standalone dependency refusal remains in effect.

The runtime proof inventory covers the public-codec envelope/attempt join, fresh
sequential/concurrent/restart identity, unit/snapshot/crosswalk provenance and
EC-JOURNAL-4 correlation. It includes lifecycle shape, transitions, process
results, all four journal numeric bounds, projection and liveness behavior,
producer-owned event and terminal evidence, and exact digest text.
`S-evidence-copied` must eventually be refused through production journal/worker
paths. `V-two-attempts` permits equal proposal digests while requiring distinct
evidence and envelope/run/attempt identities. Equal proposals transfer no
acceptance or freshness; baseline identity and evidence remain independently
bound. `N20-raw-stdout-ref` and `N18-run-status-as-evidence` remain explicit
runtime obligations too.

This internal intake adds no CLI or release behavior. WORKER owns integrated
feature documentation. Full regression, Gate A and independent review belong
to hosted CI and CLOSEOUT; targeted local results are not those gates.
