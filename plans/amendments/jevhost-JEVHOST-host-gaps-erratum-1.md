# JEVHOST host-gaps erratum 1: GAPS §3.1 enforcement points and the item-3 hook

This erratum amends `plans/amendments/jevhost-JEVHOST-host-gaps.md`. It does not edit the
frozen artifact `plans/artifacts/jevhost-host-gaps-v1.md` (GAPS), whose sha256 stays
`89ac72d9d7e77601b99940508191991c6d256db586223a7c1afcfb6e5e86958d`.

## Why

Two GAPS §3.1 rules refuse **before route**. Two frozen tests (GAPS §6) require route to be
reached in those cases. The frozen tests win. Each rule keeps its safety property, and only
the enforcement point moves.

## Row 1d: a supplied context with no ledger entry

- **Forced by:** `phase-loop-runtime/tests/test_jevdrill_adapter.py::test_requested_ceiling_rejects_unproven_executor_limits[retry_spend]`,
  which requires a `route` call and then an "unverified" refusal.
- **Replaces** "A supplied context with no ledger entry is refused", and row 1d's no-ledger
  "refused with no `route`":
  - such a request may be routed;
  - the existing unverified-ceiling check runs first;
  - the adapter then raises `JevDrillUnavailable` before any launchable decision;
  - the context is never forwarded as accepted retry authority, and never reaches launch.
- **Unchanged:** refusals with a ledger entry (widened, mismatched, exhausted) still happen
  before route.

## Row 1c: an attempt with no verdict at route

- **Forced by:** `phase-loop-runtime/tests/test_jevdrill_adapter.py::test_guidance_is_verified_injected_once_and_deactivated`,
  which routes again after one launch with no verdict under `max_attempts = 1`.
- **Replaces** "including when the latest attempt has no acceptance verdict", and row 1c's
  "an exhausted context-free route with no verdict is refused with no CLI contact":
  - route-time exhaustion counts judged attempts and the time budget;
  - every launched attempt is counted atomically at launch admission, under the ledger lock.
- **Kept:** when retry context is generated from a recorded failure, `attempts_used` counts
  every launched attempt, as in the GAPS construction rule. Time exhaustion with no verdict is
  still refused before any CLI contact.

## Launch-time boundary

A binding that is spent, consumed, refused, from a closed ledger generation, or whose budget
is exhausted is refused before **any** launch-time CLI request (including linked
revalidation) and before any executor callback or executor contact. A refused prepare holds
no ledger slot.

## Item 1 falsifier, narrowed

The amendment's Item 1 falsifier is narrowed as follows:
- "an exhausted budget that still routes" excludes the two ruled cases:
  - a route for a no-ledger supplied context that is refused before any launchable decision;
  - a route after an attempt with no verdict, where the attempt count alone is exhausted.
- It adds two falsifiers:
  - such a request reaching launch;
  - a spent binding making a launch-time CLI request or executor contact.

The node IDs proving Item 1 also include `test_jevdrill_host_gaps.py::test_unrecorded_supplied_context_never_launches`
and `::test_unjudged_attempt_is_refused_at_launch_admission`.

## Item 3 scope change (approved)

The amendment deferred the item-3 hook until JEV Drill requested it. JEV Drill requested it
after planning, and the coordinator approved it as a generic host practice. It is part of
SL-8:
- **Run identity:** `run_event_identity` gives a launched run's `task_id`,
  `routing_decision_id` and `execution_run_id`, its `source_id` and its next
  `source_sequence`.
- **Public enqueue:** `enqueue_run_event` allocates the sequence and enqueues under the same
  lock as host reports. Enqueue order is sequence order; delivery order is not guaranteed.
- **Counts:** `run_report_counts` counts queue entries and losses per run at enqueue time.
  Losses after enqueue are counted queue-wide, as documented.

The CHANGELOG entry stays in SL-8 and is reconciled by SL-9.

## Unchanged

Everything else is unchanged: the other GAPS rows, IF-0-JEVHOST-5, the lanes and the frozen
files.
