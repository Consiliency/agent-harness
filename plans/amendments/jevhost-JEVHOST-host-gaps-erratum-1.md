# JEVHOST host-gaps erratum 1: where GAPS §3.1 rows 1c and 1d are enforced

This erratum amends `plans/amendments/jevhost-JEVHOST-host-gaps.md`. It does not edit the
frozen artifact `plans/artifacts/jevhost-host-gaps-v1.md` (GAPS), whose sha256 stays
`89ac72d9d7e77601b99940508191991c6d256db586223a7c1afcfb6e5e86958d`.

## Why

Two GAPS §3.1 rules refuse **before route**. Two frozen tests (GAPS §6) require route to be
reached in the same situations. The frozen tests win. Each rule keeps its safety property,
and only the enforcement point moves.

## Row 1d: a supplied context with no ledger entry

- **Forced by:** `phase-loop-runtime/tests/test_jevdrill_adapter.py::test_requested_ceiling_rejects_unproven_executor_limits[retry_spend]`.
  It supplies a retry context to a fresh adapter and requires a `route` call, followed by an
  "unverified" refusal with empty candidates.
- **Replaces** "A supplied context with no ledger entry is refused" and the no-ledger part of
  row 1d ("refused with no `route`"):
  - such a request may be routed;
  - the existing unverified-ceiling check runs first;
  - then, before any launchable decision is returned, the adapter raises
    `JevDrillUnavailable` with no executor or launch contact;
  - the context is never forwarded as accepted retry authority, and it never reaches launch.
- **Proof:** `test_jevdrill_host_gaps.py::test_unrecorded_supplied_context_never_launches`, using a
  forged context without `remaining_spend`. On the base it fails with its named assertion.
- **Unchanged:** the refusals with a ledger entry (widened, mismatched, exhausted) still happen
  before route.

## Row 1c: an attempt with no verdict at route

- **Forced by:** `phase-loop-runtime/tests/test_jevdrill_adapter.py::test_guidance_is_verified_injected_once_and_deactivated`.
  With `max_attempts = 1`, it routes the same task again after one launch that has no verdict.
- **Replaces** "including when the latest attempt has no acceptance verdict" and the row-1c
  assertion "an exhausted context-free route with no verdict is refused with no CLI contact":
  - route-time exhaustion counts judged attempts and the time budget;
  - every launched attempt, judged or not, is counted atomically at launch admission, under the
    ledger lock;
  - a further launch for an exhausted task is refused before any executor contact.
- **Proof:** `test_jevdrill_host_gaps.py::test_unjudged_attempt_is_refused_at_launch_admission`. It
  uses `max_attempts = 1`, one launch with no verdict, and a second prepare: route may occur,
  admission refuses, and the executor is never called. On the base it fails with its named
  assertion.
- **Unchanged:** time exhaustion with no verdict is still refused before any CLI contact.

## Unchanged

Everything else is unchanged: the other GAPS rows, IF-0-JEVHOST-5, the lanes, the frozen
files and the acceptance criteria. The PR body's coverage map lists the two new node IDs
under Item 1.
