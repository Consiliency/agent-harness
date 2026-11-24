---
phase_loop_plan_version: 1
phase: FIRSTSEAT
roadmap: specs/phase-plans-seats-v1.md
roadmap_sha256: 9d1d149a4709dbf7c67dbdbb957228ff8a06d36570e1f9cb77bcc039b96a7ac4
---

# FIRSTSEAT: Standing Gemini W1

## Context

The [FIRSTSEAT amendment](amendments/seats-FIRSTSEAT-w1-standing-policy.md)
records the owner's standing authority. The
[parent plan](phase-plan-v1-seats-FIRSTSEAT.md) retains roadmap goal coverage.
Keep the [proxy amendment](amendments/seats-FIRSTSEAT-gemini-proxy.md) and the
three pinned FIRSTSEAT and K1 inputs intact.

## Interface Freeze Gates

- [x] IF-0-FIRSTSEAT-7 — SL-0 publishes the
  [standing policy contract](artifacts/seats-w1-standing-policy-contract.md).
  The amendment and manifest pin the contract and the three frozen input
  digests. Runtime and installer work consume this gate. The bridge completion
  or cutoff independently gates merge and installation.

## Lane Index & Dependencies

SL-0 — FIRSTSEAT contract and documentation
  Depends on: (none)
  Blocks: SL-1, SL-2
  Parallel-safe: no

SL-1 — FIRSTSEAT runtime
  Depends on: SL-0
  Blocks: SL-2
  Parallel-safe: no

SL-2 — Dotfiles integration
  Depends on: SL-0, SL-1
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — FIRSTSEAT contract and documentation

- **Owned files**: `plans/amendments/seats-FIRSTSEAT-w1-standing-policy.md`, `plans/artifacts/seats-w1-standing-policy-contract.md`, `plans/detailed-w1-standing-policy-20261124.md`, `plans/manifest.json`, `plans/phase-plan-v1-seats-FIRSTSEAT.md`, `CHANGELOG.md`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/review-seats-readiness.md`, `plans/evidence/seat-qualification/README.md`
- **Interfaces provided**: IF-0-FIRSTSEAT-7
- Publish the amendment, freeze, manifest, detailed plan and parent pointer in
  the plans-only PR. Verify all four artifact digests and references.
- After agent-harness#2168 merges, update the board contract, readiness docs
  and evidence README for the standing path. Union-resolve the changelog.

### SL-1 — FIRSTSEAT runtime

- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_window.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_window_w1_policy.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/tests/test_seat_window_w1_policy.py`, `phase-loop-runtime/tests/test_seat_window_grants.py`, `phase-loop-runtime/tests/test_seat_window_vendor_neutral.py`, `phase-loop-runtime/tests/test_seat_qualification_host_context.py`
- **Interfaces consumed**: IF-0-FIRSTSEAT-7
- **Tasks**
  - test: Exercise the production entrypoints with the provider-free controls
    in Verification before implementing the standing path.
  - impl: Start after IF-0-FIRSTSEAT-7 freezes and agent-harness#2168 merges.
    Implement standing admission, claim, launch wiring, evidence, verification
    and reduction. Reuse `seat_window_supply.py`. Keep
    `seat_window_grants.py` for row grants only.

### SL-2 — Dotfiles integration

- **Owned files**: `scripts/refresh-agent-harness-pin`, `scripts/lib/phase-loop-runtime.sh`, `tests/test_agent_harness_refresh.py`
- **Interfaces consumed**: IF-0-FIRSTSEAT-7
- All three paths are in Consiliency/dotfiles.
- **Tasks**
  - test: Exercise verified dispatch, no-spend deferrals, retry boundaries,
    typed completion and failed-W1 isolation in the installer fixtures.
  - impl: After SL-1, queue a serialized asynchronous owner job from the
    verified-install success hook using the installed entrypoint. Reconcile
    already-current installs and check headroom. Read-only `ready` mirrors the
    pre-claim-checkable policy, slot, image, provider-free pass, egress and
    login-presence conditions. Defer before claim and keep live auth inside the
    run. Use `window_review_required` with a retained record even on exit 1,
    verify it automatically and retain its private result.

## Execution Notes

### Authority and admission


Use a closed, size-bounded `seat_window_w1_policy.v1` JSON document and a detached SSH signature over exact UTF-8 bytes. Reuse `agy_catalog_policy.py`'s `ssh-keygen -Y sign/verify` and `allowed_signers` with namespace `seat-window-w1-policy`. The owner keeps a passphrase-protected software Ed25519 SSH key on their own machine. Never copy the key to dev0 or the seat/Dotfiles account, or forward the SSH agent to dev0. Enroll the public key in root-owned `allowed_signers`. The root-pinned active digest controls host admission and the signature independently proves owner intent offline.

Enroll on dev0 under the owner account. For OD-12, designate that single operator context as `standard` and classify a passing record as `done-local`. dev0's team-host status and collaborator accounts establish no `done-team` coverage. The owner administers the root trust store. Collaborators need their own provider-free passes and cannot use the standing policy.

Bind policy ID, signer, machine-ID digest, owner numeric real and effective UID, Gemini W1, standard context, one attempt, UTC validity and `attendance: "standing"` with a UTC schedule. Require a readable machine ID without hostname fallback and LA-1 managed install/host readiness, LA-2 four current logins and LA-3 satisfied by the signed schedule and bounded supervision with automatic cleanup. Keep `seat-window qualify --window W1 --monitoring-policy bounded` with the default model and peer/launch overrides disabled. Standing admission derives attendance from policy. The recurring-path human steps are one-time key/policy/store enrollment, quarterly re-signing and activation, and keeping logins current. Asynchronous owner review gates only public export and the records PR.

Use the fixed, descriptor-walked trust and admission stores in IF-0-FIRSTSEAT-7.
Root pins the journal genesis, path and enrollment instant. Missing state,
anchor mismatch or journal and witness disagreement refuses. Use append-only
activation history for quarterly renewal. Retirement preserves historical
verification. Compromise disables new claims and applies the root-admin
`revoked_after` boundary to historical claims. Compromise of the signing machine
plus the owner's sudo on the primary board host amounts to full owner compromise.
Revoke the key in response. Trust the owner account, host administration,
installed code and clock. Rolling back the journal tail and witness together
is outside the guard.

### Trigger, debit and verification


Derive the tuple from the verified installed release: K1 `release_identity()`, the actual Gemini qualification key with architecture, and admitted agy image SHA-256. Missing components refuse admission. Keep `runtime_digest()` out of the key and record it as provenance. Bind and verify the managed artifact's official ref and identity. Refuse checkout shadows or stale candidates. Use the production image admission path and bind the digest to the image actually launched. `release_identity()` excludes `data/agy_catalog.json`, so a catalog-only release that changes the admitted image triggers W1. Test that Gemini launch and containment changes move the qualification key while unrelated changes leave it stable.

At cutover seed the prior-input baseline from verified managed state and reconcile any bridge claim to its tuple using the private ledger. Ambiguous matching bridge state refuses. If no prior managed state exists, queue the first eligible install. Persist the last verified input pair and pending work with admission state. Queue one eligible tuple when the Gemini key or admitted image changes. Record `window_unchanged_inputs` for identity-only changes. Coalesce unclaimed pending work onto the current verified tuple for the same inputs. Reinstall, superseded events, rollback to a spent tuple, renewal and unrelated updates after a claimed failure cannot authorize another attempt for that change.

Generate the context ID before claim. Under a stable lock recheck policy, installed tuple and both stores. Append and fsync the chained debit, then exclusively create and fsync its witness and parent directory before composition, auth or model work. Both entries carry the tuple, context ID, claim time and policy digest. Partial writes, duplicates and orphan witnesses fail closed. Log every claim privately. Refusals and timeouts stay spent. Verify only attempt one per tuple. Preserve the bridge journal, witness and pin literals for verification. Standing builds disable legacy starts without fallback.

Use the earlier of slot end and policy expiry with at least 10,800 seconds remaining at claim. Run for 7,200 seconds with 120 seconds of kill grace and reserve 3,480 seconds for cleanup and collection. Bind the contemporaneous context link, activation at claim, policy validity through completion, tuple, claim/witness, sources, K1 run binding, snapshot and completion receipt. Use the four-seat board and approved ladder with the K1 §9.2 Gemini envelope of 14 model-capable starts and per-item ancillary caps. Reserve before dispatch and check actual route expiry before credential-bearing spawn, including queued work. Verify current subject inputs and exception, dispatch-time exceptions and the 30-day age limit.

Scope standing R3 duplicates to the authenticated tuple. For unscoped `matrix --record`, reduce the installed tuple first. Keep duplicates and unreadable evidence fail-closed within their attributed partition. Only a recorded unchanged-input skip may reuse the latest independently valid W1 with proven matching Gemini key and image. A failed, pending or ambiguous attempt for that input change disables reuse across subsequent identity-only updates. Keep the legacy partition separate and require private bridge input proof for that equivalence. Across eligible W1 and row partitions use the latest completion, with row winning ties. Verify and export explicit records without mixing releases. Keep historical exports subject to normal freshness/expiry. A failed or pending W1 leaves Gemini's W1 row unqualified. Owner decision 4 says, “A failed W1 leaves the Gemini row unqualified and blocks nothing else.” Routing admits Gemini on the launching host/account's current provider-free EC-EXECFIND-2 pass. After 30 days, unchanged inputs can leave the W1 row at `candidate`. This accepted lapse blocks nothing and triggers no rerun. Only `vendor:gemini` can advance on automated verification. Keep raw evidence and findings private under OD-10. Publish only the passing, owner-reviewed closed-field export.

Claude's `open egress` expires 2026-12-04. Post-cutoff composition needs its separately approved and packaged renewal for about 30 days pending CLAUDENET. Renewal is out of scope. Every co-seat and president exception retains its own expiry. Missing legal routes defer W1 before claim when detectable.

### agent-harness#2157 bridge


Option A is primary for this release. Target 2026-12-01 go/no-go on both pins landed and the verified fix installed. Book by **2026-12-03 12:00 UTC** for an attended start by noon. The absolute latest start is **2026-12-03 21:00 UTC** only if the grant ends at cutoff. The owner approves the exact private packet once. Mint the grant on the designated host/account with `not_after` matching the booked end, then land the owner-reviewed two-line pin edit in `seat_window.py` (`OWNER_W1_GRANT_SHA256` and `OWNER_W1_PACKET_SHA256`) outside the lanes. SL-1 rebases across the edit and preserves both literals. Confirm the actual installed fix and pins, admitted image, Gemini provider-free pass, egress and logins. Run once and satisfy the proxy amendment's live EC-FIRSTSEAT-7 proof. Review, verify and export before **2026-12-04 00:00 UTC**, the unchanged `OWNER_W1_APPROVED_UNTIL` cutoff. The legacy producer has no contemporaneous K1-T2 link. Preserve the conservative check. A missed or spent bridge leaves the candidate unqualified. A later standing attempt requires a release carrying the fix and current route authority.

SL-1 may merge and dev0 may install a standing build only after the Option A bridge run completes or 2026-12-04T00:00Z passes, whichever comes first.

## Verification


Provider-free red controls cover unpinned/post-cutoff admission, agy-only change, identity-only skip, multi-release/bridge R3, same-tuple duplicates, current selection, revocation/retirement, store deletion, path ownership/modes, and wrong signature/host/UID/context/release. Cover expiry/margin, renewal without replay, concurrency, restart and crash boundaries, tampered sources, budget and expired routes, and unchanged F10 legacy golden. Spy on preflight/auth/model for refusals and prove failed `ready` spends nothing. Installer fixtures cover verified dispatch once, mismatches, duplicate events, deferrals, timeouts, stale work, typed completion and failed-W1 isolation. Assert changed-input failure cannot reuse older evidence. For unchanged inputs, test valid reuse and the >30-day return to `candidate` without a new debit or blocked routing.

Compare profile/qualification keys, tool surfaces, allowlists, agy QCI, Claude SDK inputs and reference inventory against the landed base. Reissue affected pending row grants and requalify affected bindings under existing rules. Use timed, headroom-checked `-n 0` tests and hosted CI/Gate A per `CONTRIBUTING.md`. Reserve credentialed proof for dev0.

## Acceptance Criteria

- [x] IF-0-FIRSTSEAT-7 — proven by `validate_plan_doc.py`, the manifest audit,
  and `sha256sum`, falsified by validator failure, missing registration or
  digest mismatch.
- [ ] EC-FIRSTSEAT-7 — proven by `test_seat_window_w1_policy.py`,
  `test_seat_window_vendor_neutral.py` and the live bridge proof, falsified by
  a passing record with an invalid claim, mismatched input tuple or expired
  dispatch authority.
- [ ] EC-FIRSTSEAT-6 — proven by `test_seat_qualification_host_context.py`,
  `test_seat_window_grants.py` and `test_agent_harness_refresh.py`, falsified by
  a failed or aged-out W1 advancing the row, retrying the debit or blocking
  other routing.
- [ ] EC-FIRSTSEAT-1 — proven by parent `V-B`, falsified by its composition replay control.
- [ ] EC-FIRSTSEAT-2 — proven by parent `V-C`, falsified by its silent-transport control.
- [ ] EC-FIRSTSEAT-3 — proven by parent `V-D`, falsified by its hostile-input and record-boundary controls.
- [ ] EC-FIRSTSEAT-4 — proven by parent `V-G` and `V-C`, falsified by the leg-route control.
- [ ] EC-FIRSTSEAT-5 — proven by parent `V-A` and `V-R`, falsified by their host controls.

These five items retain the [parent verification](phase-plan-v1-seats-FIRSTSEAT.md#verification).

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- target surfaces: FIRSTSEAT amendment, frozen standing policy contract and parent pointer in the planning PR, board contract, readiness docs and evidence README in implementation
- evidence paths: `plans/evidence/seat-qualification/`, `phase-loop-runtime/tests/test_seat_window_w1_policy.py`, `phase-loop-runtime/tests/test_seat_window_vendor_neutral.py`
- redaction posture: `metadata_only`

## Review changelog

- H1 removed prior-runtime retention and binding promotion. Failed W1 leaves Gemini unqualified by W1.
- H2 made signed policy count as attendance and owner review gate public export only.
- H3 added the three-part debit and skips for unchanged Gemini inputs.
- M1 scoped R3 duplicates and matrix reduction by tuple, with a separate legacy partition.
- M2 reused SSH signing, added compromise revocation and anchored and secured admission paths.
- M3 designated the owner-only dev0 context as standard and its passing evidence as done-local.
- M4 assigned the shared files after agent-harness#2168 and union-resolved the changelog.
- M5 recorded the separate, bounded Claude renewal dependency.
- M6 added IF-0-FIRSTSEAT-7, the frozen artifact and amendment precedence.
- L1 preserved K1 r5.2 and its historical evidence.
- L2 made Option A primary and added booking, cutoff and verification timing.
- L3 mirrored pre-claim checks in read-only `ready`.
- L4 expanded regression coverage and kept provider-free checks capped.

Round 2 covered N1–N6 with lapse coverage, bridge sequencing, key custody, repository and test ownership, trust-directory creation and the owner fail-safe quote.
