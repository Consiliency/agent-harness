# Human publication scope preflight

## Task
Prevent the commit-then-scope-refusal failure observed in Consiliency/jev-assembler. Its caller supplied dirty paths but omitted already-committed branch changes. The broker refused after the SDK created a commit; corrected scope selected a new checkpoint, and prebuilt refused the existing FABPUB trailer.

## Changes
- Add the versioned `PublishScopeCorrection.v1` SDK/broker operation in `phase-loop-runtime/src/phase_loop_runtime/publish_scope_correction.py`, with additive request lineage in `convergence/contracts.py` and broker validation/idempotency in `convergence/broker/verbs.py`. Keep original commit/checkpoint/evidence intact. Authenticate only an exact sealed ownership-scope rejection in the active broker generation, reserve one successor receipt under the existing admission lock, and apply existing generation/admission/provider ownership to that successor. Generic no-effect, ambiguity, changed proof or commit, scope shrink, conflicting successor and unsealed owners refuse. Add real production-entrypoint tests in `tests/test_publish_scope_correction.py`.
- phase-loop-runtime/src/phase_loop_runtime/publishing.py: before deriving publication authority or staging/committing, check the already-committed branch diff against the caller's owned paths using the broker's base validation, exact path decoding and directory coverage semantics. Return a typed repairable refusal for invalid/unavailable bases or uncovered committed paths. Leave broker validation authoritative and unchanged.
- phase-loop-runtime/tests/test_publishing.py: real temporary Git fixtures cover omitted committed paths, corrected scope succeeding through the next boundary without altering HEAD/index, rename-source coverage, directory coverage and unusual path bytes, and unavailable/invalid bases. No provider calls or live authority state.
- docs/fabpub-partition-rotation-runbook.md: explain that corrected scope changes human publication context and that same-context recovery must not be represented as corrected-scope recovery.
- Add the operation's bounded exception to `convergence/provider_contracts.py`, user-visible changelog, and CLI/SDK documentation as needed. The operation is distinct from ordinary canonical-effect replay; old callers and old readers retain their existing refusal/replay behavior. The shared original effect row is never changed.
- This plan and ignored test outputs in .phase-loop/runs/human-publish-scope-preflight-20261018/**.

## Verification
Run targeted new pytest controls before and after repair, then the complete publishing and broker-credential-separation test modules. Run git diff --check. Use installed dependency environment with source PYTHONPATH; do not replace the installed runtime or access host publisher stores.
Run correction tests, existing sealed-head recovery/owner/evidence modules and repository-mandated `make check` as applicable. Live application is a separate action from isolated implementation and testing.

## Acceptance criteria
- Omitted committed paths refuse before authority construction, staging or commit; adding complete ownership reaches the existing publication path.
- Path/base semantics match the broker, including rename deletions and whitespace/non-UTF-8 names.
- Existing publication tests pass without weakening broker scope, trailer, replay or authority checks.
- Existing Jev commit remains untouched. The versioned operation supports the already-rejected commit through broker-authenticated predecessor evidence and a new successor receipt; no fabricated attestation, empty commit or direct push.
