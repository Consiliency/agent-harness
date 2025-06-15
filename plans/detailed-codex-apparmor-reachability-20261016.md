---
status: planned
owner_skill: codex-plan-detailed
scope: correct protected namespace entry and preserve strictly private fixture mounts
review_status: pending_owner_directed_t3_cristina
automation:
  suite_command: "uv run --project phase-loop-runtime --group test python -m pytest -q phase-loop-runtime/tests/test_codex_apparmor_canary.py phase-loop-runtime/tests/test_seat_jail_apparmor.py phase-loop-runtime/tests/test_seat_owner_composition.py phase-loop-runtime/tests/test_codex_seat_tool_sandbox_1335.py"
verification_status: not_run
---

# Detailed plan: correct canary entry and fixture propagation

## Task

Resolve T3C-F01 and T3C-F02 from the owner-directed Cristina Opus review of Consiliency/agent-harness#1731 at input `c1211692b58ad3d2a92fa27b27913e6e41de6392`. This is a bounded supplement to `plans/detailed-codex-apparmor-canary-20261016-0227.md`. Preserve that original artifact, both reviewed policy prototypes and original canonical review records byte-for-byte. The owner requested Cristina's account and T3 delegation to finish review; this supplement needs that independent review before implementation.

## Research summary

`trampoline()` currently requires a namespace-prefixed self-label. Upstream AppArmor formats labels relative to the reader's namespace: [aa_getprocattr](https://github.com/torvalds/linux/blob/master/security/apparmor/procattr.c) and [aa_profile_snxprint](https://github.com/torvalds/linux/blob/master/security/apparmor/label.c). Therefore self-view and root-controller view require different checks. The supplied reviewer has not run a privileged label probe; target-kernel confirmation remains live acceptance.

The reviewer's ordinary nonroot bwrap control showed `master:N` on bind mounts. [Bubblewrap](https://github.com/containers/bubblewrap/blob/main/bubblewrap.c) makes its inherited mount tree recursively slave before creating its root. Existing `validate_gate()` requires empty propagation fields. Preserve that strict requirement by detaching the trusted child's mount tree before bwrap; do not reinterpret slave mounts as private or allow inbound host propagation. This adds trusted preparation before the existing privilege drop and must be reviewed explicitly.

## Changes

### `phase-loop-runtime/tests/codex_apparmor_canary.py` (modify)

1. **`trampoline()` and `Experiment.arm()` — distinguish label views with a bounded entry handshake.** The protected Python trampoline accepts exactly self-view `unconfined`, emits fixed `ENTRY\n`, and blocks for exactly byte `E` on its existing stdin before input validation, mount preparation, identity drop or bwrap exec. The root-namespace controller waits for the exact entry marker, revalidates the held direct child's PID/start/pidfd, canonical Python executable and host-user-namespace identity, and reads that child's label as exactly `:<owned-policy-namespace>:unconfined`. A host `unconfined`, foreign namespace, changed identity, malformed/duplicate marker, EOF, wrong byte or expiry refuses continuation. Only after independent checks does it send `E`. Final fixture `READY\n` and primary `G` remain distinct; no primary GO is possible during entry. Count both phases' stdout/stderr against the existing aggregate limit and use the original single startup deadline, without extending it.

2. **Trusted trampoline preparation — make a child-only recursively private mount namespace.** After entry acknowledgment and protected input validation, while still the trusted root child, record its mount-namespace identity, call `unshare(CLONE_NEWNS)` through the existing libc seam, require a different identity, then call `mount(NULL, "/", NULL, MS_REC|MS_PRIVATE, NULL)`. Never attempt the propagation operation if namespace creation failed or identity did not change. Verify all inherited mount propagation fields are empty using the existing parser's host-metadata handling. Keep the same user namespace and existing identity/map topology: this preparation creates no user namespace. Refuse syscall/check/deadline failure before dropping or executing bwrap. Then perform the existing full groups/UID/GID/capabilities/FD drop and NNP sequence unchanged and exec the fixed bwrap. Add no retained capabilities, new tool, host include or fixture bind. Root controller stays in its original mount namespace; the experiment's own worker remains independently gated.

3. **`validate_gate()` — retain exact labels, bind identity and empty propagation checks.** Explicitly test rejection of `master:`, `shared:` and `propagate_from:` fields. This supplement does not authorize a slave-only exception. The added trusted `CLONE_NEWNS` preparation is distinct from the single observed primary `unshare(CLONE_NEWUSER|CLONE_NEWNS)` inside the credential-free fixture; it must not enter the primary trace or count as hypothesis evidence.

4. **Evidence — record the independent namespace-entry proof and trusted mount-namespace preparation alongside existing arm/checkpoint data.** A later failure must retain the owned process and exact recovery target. Both arms use identical setup. Keep all existing baseline attribution, no-candidate, outcome, root-policy invariance and shared cleanup deadlines unchanged.

### `phase-loop-runtime/tests/test_codex_apparmor_canary.py` (modify)

Replace incorrect self-label mocks with reader-relative behavior. Add controls for correct self-view paired with wrong controller view, unchanged PID/start but foreign policy namespace, entry-marker/ack confusion, cancellation/EOF/expiry, and no privilege drop/exec/GO on failure. Exercise syscall ordering: private propagation is never requested before successful child-only mount namespace creation; preparation failure prevents drop/exec; no inherited user namespace or capability grant is added.

Add an ordinary nonroot integration control that prepares a recursively private mount namespace inside a disposable user namespace, then launches the same sealed fixture with permanent EOF and captures its actual mountinfo. Require exact fixture bind checks, empty propagation and READY/exit125 with no GO. Clearly label the extra user namespace as test-only: it cannot prove the production mapping or live AppArmor behavior. If the host refuses ordinary user namespaces, report an explicit skip with reason, never a pass. Preserve the existing direct-fixture startup control and a captured unprepared slave-mount negative control. Do not create/load/remove a real AppArmor policy namespace.

### `docs/advisor-board-capabilities-card.md` (modify)

Update only the experimental canary note: label views, entry acknowledgment, trusted child-only mount setup, unchanged strict final gate and unchanged administrator authorization boundary. No public CLI or supported production policy changes.

### `plans/evidence/codex-apparmor-canary/implementation-sol-20261016-r2.json` (modify)

Append the Cristina findings, responses and actual review provenance without rewriting past votes. Advance `current_revision` to the new follow-up, resolving T3C-S03. Retain S01/S02/S04 as nonblocking suggestions with scope rationale; avoid unrelated cleanup refactors. Refresh source/render/approval-packet bindings after verification. Earlier three AGREE votes bind the old input and are not exact-head approvals of future code. The canonical Claude failure and Consiliency/agent-harness#1734 remain separate and unresolved.

This plan and `plans/manifest.json` are plan-owned lifecycle outputs. Executor handoffs/reflections and precise execution evidence amendments are permitted closeout outputs. Do not edit installed runtime, original plan, policy prototypes or canonical board artifacts.

## Documentation impact

Experimental troubleshooting documentation and execution metadata only. No installed API/schema/frozen provider vocabulary changes. `ENTRY`/`E` extend the standalone helper's internal startup protocol; `READY`/`G` retain their purpose and cannot be substituted for each other.

## Dependencies and order

First obtain Cristina's T3 review of these exact supplement bytes. Then implement helper, tests, docs and metadata in the existing owned branch, verify, publish a draft through the supported adapter, and request Cristina's delta review with all findings/responses. Bound this owner-directed completion to the initial review already delivered plus this supplement review and one implementation re-review. Do not run another canonical board, silently extend that cap, merge or execute privileged preparation. A surviving material objection returns to the owner.

## Verification

Execution refreshes declared dependencies in isolated Python 3.12 and runs `automation.suite_command`, then `make check` with its pinned Ruff and supported environment prerequisites. Run the original plan's render and both `apparmor_parser -K -Q` commands against a fresh owned evidence directory; run both ordinary nonroot startup controls. Test entry/drop/exec/GO order, actual mountinfo, identity substitution, deadlines and cancellation. Produce a fresh runner-owned verification artifact bound to current bytes, with statuses for every prescribed command and actual skips/failures preserved.

New exact evidence scope: `/home/viperjuice/workspace/evidence/codex-apparmor-canary-sol-20261016/r5/{*.json,*.txt,*.md,rendered/**}`. Record a scope amendment before use. Read current Cristina `r4/t3-cristina-review/{review.json,review.md,scratch-bwrap-mountinfo.txt,scratch-propagation-falsifier.txt}` and previously allowed execution metadata only. Credentials and raw provider logs/transcripts remain protected. Use the new plan's runner-stamped execution amendment to bind any later authorized live invocation and artifacts; offline results never substitute for original live C1-C4.

## Acceptance criteria

- [ ] Correct self-view plus independently observed exact root-view label is required in both arms before the entry acknowledgment; malformed/foreign/changed/expired states prevent drop, exec and primary GO. Proven by targeted entry controls and the prescribed suite; actual AppArmor label observation remains original live C1/C3.
- [ ] Trusted propagation change follows successful child-only mount namespace creation; user namespace, final zero capabilities and identity/map topology remain unchanged. Failure prevents fixture execution. Proven by ordering/negative controls and supplied source review; privileged execution remains unauthorized.
- [ ] Actual nonroot prepared-fixture mountinfo has no propagation fields and exact binds; unprepared slave/shared rows remain rejected. Proven by the integration/negative controls, reported as unmet on an unsupported host rather than inferred from mocks.
- [ ] Original plan/policies/canonical records remain unchanged; current metadata identifies this follow-up, review route and fresh verification/approval hashes. Proven by digest comparison and runner artifact. No existing vendor vote is rebound to new code.
- [ ] Original baseline/outcome/ownership/cleanup tests and prescribed suite pass without expanded bounds or capability grants. Live C1-C4 remain explicitly unmet; no root canary, production repair, president ruling, merge or host mount/policy operation is claimed.
