# v12 CLOSEOUT: location of the production launch binding

Frozen input for `plans/phase-plan-v12-CLOSEOUT.md`, sealed by the manifest
amendment row `v12-CLOSEOUT-amend-binding-location`. It resolves one gap that the
CLOSEOUT build reported at preflight, and adds no other change.

## Gap

`plans/artifacts/v12-CLOSEOUT-inputs.md:369` requires that the "Production CLI
always selects the installed v2 binding from trusted operator configuration".
The landed loader, `supervised_launch_binding.load_validator_binding(path, ...)`,
takes an explicit path and refuses `binding_unavailable` when it is `None`. The
landed `supervised_worker_cli._production_codec()` is a pathless stub. Neither
frozen artifact said where the trusted operator configuration lives.

## Decision (coordinator, 2026-11-09, revised after the build's ownership check)

The landed loader is written for **operator-owned** configuration. `LaunchConfig`
describes "operator-owned config", and `load_validator_binding` reads the binding
and every file it references through `trusted_bytes`. With its default
`operator_owned=True`, that check accepts only the current uid as the final
file's owner (`supervised_launch.py:133`). A root-owned record therefore cannot
satisfy it. The binding is an operator record, not a root-managed one.

1. `supervised_launch_binding.MANAGED_BINDING` resolves to
   `<home>/.local/state/phase-loop/supervised-launch-binding.json`, where
   `<home>` is the operator's home directory from the password database
   (`pwd.getpwuid(os.getuid()).pw_dir`). SL-1 owns `MANAGED_BINDING` in
   `supervised_launch_binding.py`. Construct the path directly from the passwd
   entry, without resolving symlinks before trusted reads. SL-2 owns wiring
   `supervised_worker_cli._production_codec()` and the production launch path to
   this location through the frozen `load_v2_binding` interface. The landed
   `load_validator_binding` describes the existing trust checks; it is not a
   substitute for the required public v2 loader.
2. Nothing else can select a different binding: no argv flag, environment
   variable (`HOME`, `XDG_STATE_HOME` and `XDG_CONFIG_HOME` included),
   controller document, config file or working-directory lookup. The CLI never
   discovers a binding.
3. The file and everything it references are read through the existing,
   unchanged `trusted_bytes` checks:
   - the final file is owned by the operator;
   - no path component is group- or other-writable;
   - every directory is owned by root or the operator;
   - nothing is followed through a symlink, and the file has a single link;
   - the excluded roots are honoured.
   
   No reader is weakened.
4. If passwd-home lookup fails, or the binding is absent or untrusted, production
   refuses before launch, without fallback or provisioning. Preserve code-only
   refusal handling: the landed `load_validator_binding(None, ...)` returns
   `binding_unavailable`, a missing concrete path returns `binding_invalid`, and
   trusted-check failures retain their closed refusal reasons. Today the CLI stub
   refuses `codec_unavailable`; this amendment preserves refusal until
   installation, not that exact diagnostic.
5. Tests use temporary operator records through in-process loader/test seams.
   Production has no binding-path override. No test writes into the real home
   directory.
6. Provisioning the record on hosts is deployment work outside CLOSEOUT, and
   EC-CLOSEOUT acceptance stays as the plan states.

## Bootstrap order

The frozen `load_v2_binding(path, *, workspace, target, reference_roots)` needs the exclusion roots before reading the binding. Those roots come from the per-attempt controller document located by the binding's `controller_root` (landed-binding §4.2). Bootstrap therefore uses a locator snapshot followed by a passive full load and an agreement barrier. The public signatures remain unchanged. The existing eager `load_validator_binding` remains an offline seam and is not called by this production bootstrap.

1. Run route preflight and the existing isolation check before binding or envelope intake. Read the envelope once as WORKER requires and compute `h`, the SHA-256 of those exact bytes. Retain that snapshot for subsequent decoding and admission.
2. Read `MANAGED_BINDING` once through unchanged `trusted_bytes`, with no excluded roots solely for this locator read. Strictly parse data and validate `controller_root` as an absolute canonical path without resolving symlinks. Use only that field; do not read references, import or execute binding-selected code, invoke a decoder, prepare admission, create a result file, journal or spawn. Retain the exact locator bytes.
3. Read `<controller_root>/<h>.json` once with the single-descriptor checks in landed-binding §4.2 and the unchanged trusted-file checks of the location decision. Retain its bounded raw bytes, immutable parsed document and checked location identities. Require `h`, the complete `AttemptBinding`, all required `ValidatorContext` fields from the inputs artifact, and the declared per-attempt slot values; missing, malformed or mismatched fields refuse `binding_invalid`. In particular retain `expected_assignment_digest`, `expected_snapshot_ref` and `expected_crosswalk_ref`, without deriving them from the envelope. Require `AttemptBinding.assignment_digest == expected_assignment_digest`. Extract the complete workspace, target and reference-root exclusions. Check the held document location against those roots without rereading the document; a failed controller check, including an excluded controller location, refuses `binding_invalid`.
4. Call `load_v2_binding(MANAGED_BINDING, workspace=..., target=..., reference_roots=...)` with those exclusions. This v2 loader is passive: it reads and verifies the binding and every referenced configuration, context, implementation and resource under the complete exclusions, and calls `load_v2_context` as frozen. It neither imports nor executes binding-selected modules nor invokes their codec or validator. Its `V2Binding` retains immutable exact `binding_bytes`, parsed `controller_root`, the verified implementation/resource byte snapshots and approved digests/seal, context and spec. Codec/validator handles defer module execution to a separate post-agreement activation in the owning module. No ambient state or lazy path reread supplies these snapshots. A binding or reference inside an excluded root refuses `untrusted_location`; existing trusted-read refusal reasons remain closed and unchanged. The eager fixture loader is not a substitute for this passive v2 implementation.
5. Compare the locator bytes literally with `V2Binding.binding_bytes` and compare the controller root used for step 3 with the loaded root; disagreement refuses `binding_invalid`. Reconcile the held controller document against the held operator context/spec: accept only the per-attempt context fields and local-root/argv slots allowed by §4.2 and the operator declarations, leaving operator policy, issuer, epoch, revocation authority and codec selection fixed. Require the complete effective exclusion roots to agree with the roots used at step 4; no omitted or substituted root is accepted. Bind the effective immutable context/spec and AttemptBinding to that same controller snapshot, never a reread. Missing, inconsistent or undeclared hand-off values refuse `binding_invalid`. Preserve subsequent public admission's foreign-assignment, snapshot and crosswalk diagnostics and their pinned evaluation order.
6. Only after all preceding checks succeed may a separate activation execute the already verified held implementation bytes and resolve callable symbols. It preserves the approved implementation set and isolated import checks; it never reopens the selected module paths. Activation errors use the closed binding refusal mapping. Only then may decoding, capture/admission, result creation, journal work or spawn begin through their existing gates. All refusals in steps 1–5 occur before any of those effects. Snapshot lifetimes extend through comparison and activation; later consumers use the same held values.

SL-1 owns passive loading, immutable byte retention, the locator/agreement helpers and post-agreement activation in `supervised_launch_binding.py`. SL-2 owns the single controller snapshot, its complete hand-off validation and calling these operations in order from `supervised_worker_cli`. Additive internal helpers and immutable result fields implement this sequence without changing any frozen public input signature or introducing a production selector.

SL-1/SL-2 tests use temporary operator records and cover:
- bindings and each referenced-input category in workspace, target and reference roots, refusing `untrusted_location` during full load;
- a binding replaced between locator and full load, including a replacement that selects a different controller root or implementation, refusing `binding_invalid` before any selected module top-level execution;
- a controller document inside any excluded root, refusing `binding_invalid` before execution;
- absent/malformed controller fields, wrong `h`, assignment inconsistency, disallowed slot/policy changes and incomplete effective roots, refusing `binding_invalid`;
- retained expected snapshot/crosswalk context reaching admission, with existing pinned mismatch diagnostics;
- a controller pathname changed after its read, proving that only the held validated snapshot supplies context, slots and identity;
- an event-order witness covering module top-level execution, codec invocation, validator invocation, result creation, admission preparation, journal and spawn: none occurs before successful full load, literal byte agreement and controller reconciliation;
- equal locator/full-load bytes proceeding to activation from the held approved module bytes, without a third binding read or a module-path reread;
- missing binding/passwd-home and trusted-read failures retaining the location decision's closed refusal behavior and tested public-status mapping.
