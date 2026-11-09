# JOURNAL local seam receipt

Runner-observed offline results for v12 Phase 2 (JOURNAL) within agent-harness#1818,
executed against `plans/phase-plan-v12-JOURNAL.md` and the sealed
`plans/artifacts/v12-JOURNAL-interface.md`. IF-0-JOURNAL-1 is a local interface.
This receipt grants no public-contract, readiness or live-use authority. CLOSEOUT
still discharges authoritative acceptance, and hosted CI, Gate A and independent
review are pending. Source hashes bind the implementation snapshot without
predicting its eventual commit.

## Observed verification

The commands are the plan's V0–V4 and the frontmatter suite, run from the
repository root, serially and without `-n`, under `timeout 900` with
`-p no:cacheprovider`. Each used
`uv run --project phase-loop-runtime --locked --group test --extra visual` and an
absolute source/test `PYTHONPATH`, and `phase_loop_runtime.__file__` resolved
inside the checkout. Interpreters were uv's Python 3.12.14 and the system
`/usr/bin/python3.14` (3.14.4), each in its own locked environment. Host load,
available memory and memory/IO pressure were checked before each command.

| Check | Python 3.12 | Python 3.14 |
| --- | --- | --- |
| V0 `test_run_status.py` | 189 passed, 0 failed, 0 skipped | 189 passed, 0 failed, 0 skipped |
| V1 `test_run_status_projection.py` | 88 passed, 0 failed, 0 skipped | 88 passed, 0 failed, 0 skipped |
| V2 `test_run_status_receipt.py` | 12 passed, 0 failed, 0 skipped | 12 passed, 0 failed, 0 skipped |
| V3 `test_seat_reference_inventory.py` | 7 passed, 0 failed, 0 skipped | 7 passed, 0 failed, 0 skipped |
| V4 `test_runtime_consumers_remain_independent` | 1 passed, 0 failed, 0 skipped | 1 passed, 0 failed, 0 skipped |
| Effective suite (frontmatter `suite_command`) | 296 passed, 0 failed, 0 skipped | 296 passed, 0 failed, 0 skipped |

V2 and the effective suite ran after this record's producer rows were stamped. Their rows were then added, and V2 was rerun against the final receipt.

Before implementation, `--collect-only` over the V0–V2 paths selected zero nodes,
because the files were absent. IF-0-VC-2 (`validate_verification_commands`)
reported no finding for the V0–V4 argv or the effective suite once the V0–V2 files
existed. The 277 producer nodes below equal a fresh
`--collect-only` of the two producer files. The outcomes agreed on both
interpreters.

One failure was observed and repaired before this stamp. The effective suite on
Python 3.12 failed `test_pid_reuse_and_observer_failures_are_stale`: the test had
used its parent process's start identity as the "reused" identity, and under the
suite command that parent (`timeout`) can start in the same clock tick. The
`linux-proc:<boot_id>:<starttime>` encoding carries no pid (artifact section 4),
so the test now derives a later start tick instead. Production code did not change.

- **Vectors.** All 35 pinned `run-status.vectors.json` cases ran through production
  entries: the 19 journal vectors through `read_index`/`read_attempt`, and the 16
  projection, liveness, reader_view and page vectors through SL-1. Each returned
  its exact expected diagnostic set and display. This is early reconciliation
  evidence only.
- **Mutation controls.** All 46 named controls in
  artifact section 13 (30 SL-0, 16 SL-1) were killed. Each control's witness passed
  on production and failed on a one-fragment source copy.

## Deferred obligations

Every pinned obligation stays owned by CLOSEOUT and is listed below as
`upstream_phase_unmet`. That covers each SCHEMA receipt `semantic_inventory` row
whose owner names JOURNAL, and every `semantic_cases` row, even though all 35 cases
passed locally. The artifact section 11 consumer obligations are recorded by pointer
for their owning plans. This phase makes none of those amendments.

## Review repair (revision 3)

The independent review of agent-harness#1934 returned BLOCK, and this stamp
covers the repair.

- Every reservation, root creation and writer-lock open now completes its fsync
  barriers on adopted entries. Barrier tests cover pre-created entries, a failed
  fsync at each of the seven chain positions, and a creator killed before each
  barrier.
- `read_page`, `project_assignment` and `check_projection` stream through
  `read_attempt_window`. They make one index load, never rescan an earlier
  attempt, and retain at most one page of events. A `tracemalloc` bound over a
  multi-megabyte synthetic history checks this.
- Quarantine keeps run records in place as permanent tombstones.
- The sealed interface was amended to revision 3 and resealed in the manifest.
  It lists `AttemptStatus.identity`/`units`, the nullable projection, the added
  records, checker, window reader and local codes, and the quarantine wording.
  WORKER's J1–J6 names and signatures are unchanged.
- A re-check of that repair returned BLOCK on two bounded-read gaps. Revision 4
  closes them:
  - `project_assignment` and `check_projection` each make one replay, with one
    index load and one window per attempt. Each attempt keeps only its head row
    and one digest verdict.
  - `project_assignment` validates against that replay.
  - `AttemptWindow` carries only the requested segment summary.
  - A multi-segment memory test shows that peaks for both projection APIs and
    `read_page` do not grow with the segment count.

```json
{
 "authority": "local_reconciliation_evidence",
 "deferred_obligations": {
  "consumer_obligations": {
   "CLOSEOUT": [
    {
     "pointer": "plans/artifacts/v12-JOURNAL-interface.md#11/CLOSEOUT/1",
     "status": "deferred_to_owner"
    },
    {
     "pointer": "plans/artifacts/v12-JOURNAL-interface.md#11/CLOSEOUT/2",
     "status": "deferred_to_owner"
    },
    {
     "pointer": "plans/artifacts/v12-JOURNAL-interface.md#11/CLOSEOUT/3",
     "status": "deferred_to_owner"
    },
    {
     "pointer": "plans/artifacts/v12-JOURNAL-interface.md#11/CLOSEOUT/4",
     "status": "deferred_to_owner"
    },
    {
     "pointer": "plans/artifacts/v12-JOURNAL-interface.md#11/CLOSEOUT/5",
     "status": "deferred_to_owner"
    }
   ],
   "LANEEXEC": [
    {
     "pointer": "plans/artifacts/v12-JOURNAL-interface.md#11/LANEEXEC/1",
     "status": "deferred_to_owner"
    },
    {
     "pointer": "plans/artifacts/v12-JOURNAL-interface.md#11/LANEEXEC/2",
     "status": "deferred_to_owner"
    },
    {
     "pointer": "plans/artifacts/v12-JOURNAL-interface.md#11/LANEEXEC/3",
     "status": "deferred_to_owner"
    },
    {
     "pointer": "plans/artifacts/v12-JOURNAL-interface.md#11/LANEEXEC/4",
     "status": "deferred_to_owner"
    },
    {
     "pointer": "plans/artifacts/v12-JOURNAL-interface.md#11/LANEEXEC/5",
     "status": "deferred_to_owner"
    }
   ],
   "PLACECLI": [
    {
     "pointer": "plans/artifacts/v12-JOURNAL-interface.md#11/PLACECLI/1",
     "status": "deferred_to_owner"
    },
    {
     "pointer": "plans/artifacts/v12-JOURNAL-interface.md#11/PLACECLI/2",
     "status": "deferred_to_owner"
    },
    {
     "pointer": "plans/artifacts/v12-JOURNAL-interface.md#11/PLACECLI/3",
     "status": "deferred_to_owner"
    }
   ],
   "WORKER": [
    {
     "pointer": "plans/artifacts/v12-JOURNAL-interface.md#11/WORKER/1",
     "status": "deferred_to_owner"
    },
    {
     "pointer": "plans/artifacts/v12-JOURNAL-interface.md#11/WORKER/2",
     "status": "deferred_to_owner"
    },
    {
     "pointer": "plans/artifacts/v12-JOURNAL-interface.md#11/WORKER/3",
     "status": "deferred_to_owner"
    },
    {
     "pointer": "plans/artifacts/v12-JOURNAL-interface.md#11/WORKER/4",
     "status": "deferred_to_owner"
    },
    {
     "pointer": "plans/artifacts/v12-JOURNAL-interface.md#11/WORKER/5",
     "status": "deferred_to_owner"
    },
    {
     "pointer": "plans/artifacts/v12-JOURNAL-interface.md#11/WORKER/6",
     "status": "deferred_to_owner"
    },
    {
     "pointer": "plans/artifacts/v12-JOURNAL-interface.md#11/WORKER/7",
     "status": "deferred_to_owner"
    },
    {
     "pointer": "plans/artifacts/v12-JOURNAL-interface.md#11/WORKER/8",
     "status": "deferred_to_owner"
    },
    {
     "pointer": "plans/artifacts/v12-JOURNAL-interface.md#11/WORKER/9",
     "status": "deferred_to_owner"
    },
    {
     "pointer": "plans/artifacts/v12-JOURNAL-interface.md#11/WORKER/10",
     "status": "deferred_to_owner"
    },
    {
     "pointer": "plans/artifacts/v12-JOURNAL-interface.md#11/WORKER/11",
     "status": "deferred_to_owner"
    }
   ]
  },
  "schema_cases": [
   {
    "id": "N04a-replaced-in-place",
    "local_result": "passed",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "N04a-seq-regress",
    "local_result": "passed",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "N04a-seq-skip",
    "local_result": "passed",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "N04b-foreign-binding",
    "local_result": "passed",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "N15-foreign-writer",
    "local_result": "passed",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "N15-no-final-newline",
    "local_result": "passed",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "N15-torn-line",
    "local_result": "passed",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "N15-unknown-version",
    "local_result": "passed",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "N16-attempt-missing",
    "local_result": "passed",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "N16-projection-behind",
    "local_result": "passed",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "N17-owner-not-live",
    "local_result": "passed",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "N17-pid-reused",
    "local_result": "passed",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "N18-completed-as-outcome",
    "local_result": "passed",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "N18-run-status-as-evidence",
    "local_result": "passed",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "N19-refused-after-running",
    "local_result": "passed",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "N19-refused-after-start",
    "local_result": "passed",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "N20-absolute-locator",
    "local_result": "passed",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "N20-parent-locator",
    "local_result": "passed",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "N20-raw-message",
    "local_result": "passed",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "N20-raw-stdout-ref",
    "local_result": "passed",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "RC24-foreign-assignment",
    "local_result": "passed",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "RC24-foreign-snapshot",
    "local_result": "passed",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "RC25-no-omitted",
    "local_result": "passed",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "RC25-no-page-size",
    "local_result": "passed",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "RC25-over-bound",
    "local_result": "passed",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "S-evidence-copied",
    "local_result": "passed",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "S-finished-without-termination",
    "local_result": "passed",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "S-projection-ahead",
    "local_result": "passed",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "V-owner-live",
    "local_result": "passed",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "V-page",
    "local_result": "passed",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "V-projection-at-tail",
    "local_result": "passed",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "V-reader-view",
    "local_result": "passed",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "V-refused-before-launch",
    "local_result": "passed",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "V-running",
    "local_result": "passed",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "V-two-attempts",
    "local_result": "passed",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   }
  ],
  "schema_named": [
   {
    "id": "journal:/x-journal-rules/bounds",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "journal:/x-journal-rules/bounds/attempts_per_page_max",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "journal:/x-journal-rules/bounds/event_message_max_chars",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "journal:/x-journal-rules/bounds/page_size_max",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "journal:/x-journal-rules/bounds/per_attempt_event_cap",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "journal:/x-journal-rules/lifecycle",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "journal:/x-journal-rules/lifecycle/cancelling",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "journal:/x-journal-rules/lifecycle/cancelling/0",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "journal:/x-journal-rules/lifecycle/finished",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "journal:/x-journal-rules/lifecycle/queued",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "journal:/x-journal-rules/lifecycle/queued/0",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "journal:/x-journal-rules/lifecycle/queued/1",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "journal:/x-journal-rules/lifecycle/refused",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "journal:/x-journal-rules/lifecycle/running",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "journal:/x-journal-rules/lifecycle/running/0",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "journal:/x-journal-rules/lifecycle/running/1",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "journal:/x-journal-rules/liveness",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "journal:/x-journal-rules/location",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "journal:/x-journal-rules/segments",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "journal:/x-journal-rules/writers",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "named:evidence-producer-binding",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "named:identity-journal-correlation",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "named:identity-public-replay",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "named:identity-units",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "named:lifecycle-process-result",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "named:lifecycle-shape",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "named:lifecycle-transitions",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "named:proposal-attempt-independence",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "named:status-digest-text",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "status:attempt_evidence_copied",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "status:attempt_overwritten",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "status:attempt_provenance_mismatch",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "status:journal_foreign_writer",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "status:journal_malformed_line",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "status:journal_torn_line",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "status:journal_unknown_version",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "status:lifecycle_invalid",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "status:locator_not_repo_relative",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "status:owner_not_live",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "status:projection_behind_journal",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "status:projection_not_from_journal",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "status:raw_output_in_record",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "status:read_unbounded",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "status:refused_after_launch",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "status:run_record_foreign",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   },
   {
    "id": "status:runtime_not_work_outcome",
    "owner": "CLOSEOUT",
    "status": "upstream_phase_unmet"
   }
  ]
 },
 "ec_status": {
  "EC-JOURNAL-1": "pending_hosted_ci",
  "EC-JOURNAL-2": "pending_hosted_ci",
  "EC-JOURNAL-3": "pending_hosted_ci",
  "EC-JOURNAL-4": "pending_hosted_ci"
 },
 "final_tree_validated": false,
 "frozen_artifact": {
  "path": "plans/artifacts/v12-JOURNAL-interface.md",
  "sha256": "c9100f04e8fef192b21ec0037ed5fea1b4a5ab882b56c52e7e9aab87ffd7bd05"
 },
 "gate": "IF-0-JOURNAL-1",
 "mutation_outcomes": {
  "assignment_dir_fsync": "killed",
  "attempt_excl": "killed",
  "component_nofollow": "killed",
  "cursor_binding": "killed",
  "foreign_writer": "killed",
  "header_not_event": "killed",
  "identity_key": "killed",
  "index_chain": "killed",
  "index_fsync": "killed",
  "index_lock": "killed",
  "index_order": "killed",
  "index_torn_refusal": "killed",
  "latest_fallback": "killed",
  "lifecycle_order": "killed",
  "line_cap": "killed",
  "locator_rule": "killed",
  "missing_segment": "killed",
  "mode_check": "killed",
  "next_cursor": "killed",
  "nlink_check": "killed",
  "omitted_counts": "killed",
  "outcome_source": "killed",
  "owner_check": "killed",
  "owner_live": "killed",
  "page_attempt_bound": "killed",
  "page_bound": "killed",
  "phrase_set": "killed",
  "pid_reuse": "killed",
  "projection_ahead": "killed",
  "projection_behind": "killed",
  "reader_readonly": "killed",
  "ref_digest_only": "killed",
  "refused_after_launch": "killed",
  "retention_count": "killed",
  "row_join": "killed",
  "run_claim": "killed",
  "run_claim_fsync": "killed",
  "runtime_phrase_set": "killed",
  "segment_chain": "killed",
  "seq_gap": "killed",
  "structural_check": "killed",
  "terminal_headroom": "killed",
  "torn_line": "killed",
  "unknown_version": "killed",
  "writer_instance_reuse": "killed",
  "writer_poison": "killed"
 },
 "observed_checks": {
  "V0": {
   "3.12": {
    "failed": 0,
    "junit_sha256": "539b7ff39c8ad4efc4c47078e3f377e75d2554739a16a979e14bbad2f1f6ff9c",
    "passed": 189,
    "seconds": 4.066,
    "skipped": 0
   },
   "3.14": {
    "failed": 0,
    "junit_sha256": "7a40b6e3699439f668ca167845294c3f2f2ce29afcaa5d693724549eff472200",
    "passed": 189,
    "seconds": 6.617,
    "skipped": 0
   }
  },
  "V1": {
   "3.12": {
    "failed": 0,
    "junit_sha256": "70a61f0dbe324d3fc6645d0600e5c449be8977386ba389851971eaf65b52d5bc",
    "passed": 88,
    "seconds": 19.381,
    "skipped": 0
   },
   "3.14": {
    "failed": 0,
    "junit_sha256": "deeeb920e8a4cf0a2772add2ca927eb13b197b8da76bb4c2428d523e1c681c62",
    "passed": 88,
    "seconds": 15.652,
    "skipped": 0
   }
  },
  "V2": {
   "3.12": {
    "failed": 0,
    "junit_sha256": "beff9310ac3e4d7133a14bd093ae89838dfa54577332eb36c35561d5c32e513b",
    "passed": 12,
    "seconds": 4.537,
    "skipped": 0
   },
   "3.14": {
    "failed": 0,
    "junit_sha256": "863d8d10fdbc69fd115aa1cca403f03dd30b2cfa3947a38da94b325c04376f9b",
    "passed": 12,
    "seconds": 4.093,
    "skipped": 0
   }
  },
  "V3": {
   "3.12": {
    "failed": 0,
    "junit_sha256": "82afd276080190786d56728d2dbf8ea09b8520ec2d8e98f9b6a13519eb519f9a",
    "passed": 7,
    "seconds": 3.178,
    "skipped": 0
   },
   "3.14": {
    "failed": 0,
    "junit_sha256": "a5c0157927f5e12e4473a5e360e03a3cc09de79bee87afbfddea67a285e7542a",
    "passed": 7,
    "seconds": 2.968,
    "skipped": 0
   }
  },
  "V4": {
   "3.12": {
    "failed": 0,
    "junit_sha256": "66e107f3facb00bdbca5e4166a8f64e0dd104176f8bfb72278fb2553cb923d78",
    "passed": 1,
    "seconds": 1.434,
    "skipped": 0
   },
   "3.14": {
    "failed": 0,
    "junit_sha256": "839ab07b0998c5e66e315640c4c29825fc564b94630c9d172ba75146a71e9500",
    "passed": 1,
    "seconds": 1.601,
    "skipped": 0
   }
  },
  "suite": {
   "3.12": {
    "failed": 0,
    "junit_sha256": "cca53e9a8e65d7e00115b3c96c1719b9b0473b7ad7081416adbd9f7a0d674a8c",
    "passed": 296,
    "seconds": 29.06,
    "skipped": 0
   },
   "3.14": {
    "failed": 0,
    "junit_sha256": "cf82ba1436678386305cb4ef074b62c010afa667e1fc6ee20a7589e5c4c7d027",
    "passed": 296,
    "seconds": 25.822,
    "skipped": 0
   }
  }
 },
 "pending": [
  "closeout_v2_reconciliation",
  "exact_head_gate_a",
  "final_tree_revalidation",
  "full_repository_suite",
  "hosted_ci",
  "independent_review",
  "installed_tool_qualification",
  "registry_activation"
 ],
 "phase": "JOURNAL",
 "preimplementation_selected": 0,
 "producer_nodes": [
  "tests/test_run_status.py::test_adopted_entries_complete_every_barrier",
  "tests/test_run_status.py::test_control_inventory_matches_artifact",
  "tests/test_run_status.py::test_crash_after_directory_claim_never_reuses_the_id",
  "tests/test_run_status.py::test_creator_killed_before_a_barrier_is_completed_by_the_next_reservation[/assignments/ce9c9ffdf06bece5d034886c3e1b51aa0a730cc2cfd13d5b82d139fc4cb1cbe5]",
  "tests/test_run_status.py::test_creator_killed_before_a_barrier_is_completed_by_the_next_reservation[/assignments]",
  "tests/test_run_status.py::test_creator_killed_before_a_barrier_is_completed_by_the_next_reservation[/attempts]",
  "tests/test_run_status.py::test_creator_killed_before_a_barrier_is_completed_by_the_next_reservation[/index.jsonl]",
  "tests/test_run_status.py::test_creator_killed_before_a_barrier_is_completed_by_the_next_reservation[/runs/run-1]",
  "tests/test_run_status.py::test_creator_killed_before_a_barrier_is_completed_by_the_next_reservation[/runs]",
  "tests/test_run_status.py::test_default_root_ignores_hostile_environment",
  "tests/test_run_status.py::test_digest_and_unit_refusals",
  "tests/test_run_status.py::test_event_phrase_set_is_closed[None]",
  "tests/test_run_status.py::test_event_phrase_set_is_closed[]",
  "tests/test_run_status.py::test_event_phrase_set_is_closed[attempt queued\\n]",
  "tests/test_run_status.py::test_event_phrase_set_is_closed[phrase4]",
  "tests/test_run_status.py::test_event_phrase_set_is_closed[worker returned a proposal]",
  "tests/test_run_status.py::test_event_refs_built_only_by_make_ref",
  "tests/test_run_status.py::test_excluded_root_by_inode_through_alias",
  "tests/test_run_status.py::test_failed_barrier_then_recovery_completes_the_chain[0]",
  "tests/test_run_status.py::test_failed_barrier_then_recovery_completes_the_chain[1]",
  "tests/test_run_status.py::test_failed_barrier_then_recovery_completes_the_chain[2]",
  "tests/test_run_status.py::test_failed_barrier_then_recovery_completes_the_chain[3]",
  "tests/test_run_status.py::test_failed_barrier_then_recovery_completes_the_chain[4]",
  "tests/test_run_status.py::test_failed_barrier_then_recovery_completes_the_chain[5]",
  "tests/test_run_status.py::test_failed_barrier_then_recovery_completes_the_chain[6]",
  "tests/test_run_status.py::test_hardlinked_segment_and_nonregular_entries",
  "tests/test_run_status.py::test_identifiers_refused_before_any_effect[-lead]",
  "tests/test_run_status.py::test_identifiers_refused_before_any_effect[..]",
  "tests/test_run_status.py::test_identifiers_refused_before_any_effect[.]",
  "tests/test_run_status.py::test_identifiers_refused_before_any_effect[7]",
  "tests/test_run_status.py::test_identifiers_refused_before_any_effect[None]",
  "tests/test_run_status.py::test_identifiers_refused_before_any_effect[\\xe4]",
  "tests/test_run_status.py::test_identifiers_refused_before_any_effect[]",
  "tests/test_run_status.py::test_identifiers_refused_before_any_effect[a b]",
  "tests/test_run_status.py::test_identifiers_refused_before_any_effect[a/b]",
  "tests/test_run_status.py::test_identifiers_refused_before_any_effect[x\\n]",
  "tests/test_run_status.py::test_identifiers_refused_before_any_effect[xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx]",
  "tests/test_run_status.py::test_identity_and_records_are_immutable",
  "tests/test_run_status.py::test_identity_versus_directory_and_index",
  "tests/test_run_status.py::test_index_defects_are_unverifiable",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[N04a-replaced-in-place]",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[N04a-seq-regress]",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[N04a-seq-skip]",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[N04b-foreign-binding]",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[N15-foreign-writer]",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[N15-no-final-newline]",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[N15-torn-line]",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[N15-unknown-version]",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[N19-refused-after-running]",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[N19-refused-after-start]",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[N20-absolute-locator]",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[N20-parent-locator]",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[N20-raw-message]",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[N20-raw-stdout-ref]",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[S-evidence-copied]",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[S-finished-without-termination]",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[V-refused-before-launch]",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[V-running]",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[V-two-attempts]",
  "tests/test_run_status.py::test_lifecycle_violations_write_nothing",
  "tests/test_run_status.py::test_limits_validated",
  "tests/test_run_status.py::test_line_cap_reserves_terminal_headroom_across_rotation",
  "tests/test_run_status.py::test_longest_identifier_accepted",
  "tests/test_run_status.py::test_missing_interior_segment_is_overwritten",
  "tests/test_run_status.py::test_missing_journal_and_reserved_without_writer",
  "tests/test_run_status.py::test_partial_line_reads_torn_after_poison",
  "tests/test_run_status.py::test_production_control_witness[assignment_dir_fsync]",
  "tests/test_run_status.py::test_production_control_witness[attempt_excl]",
  "tests/test_run_status.py::test_production_control_witness[component_nofollow]",
  "tests/test_run_status.py::test_production_control_witness[foreign_writer]",
  "tests/test_run_status.py::test_production_control_witness[identity_key]",
  "tests/test_run_status.py::test_production_control_witness[index_chain]",
  "tests/test_run_status.py::test_production_control_witness[index_fsync]",
  "tests/test_run_status.py::test_production_control_witness[index_lock]",
  "tests/test_run_status.py::test_production_control_witness[index_torn_refusal]",
  "tests/test_run_status.py::test_production_control_witness[lifecycle_order]",
  "tests/test_run_status.py::test_production_control_witness[line_cap]",
  "tests/test_run_status.py::test_production_control_witness[locator_rule]",
  "tests/test_run_status.py::test_production_control_witness[missing_segment]",
  "tests/test_run_status.py::test_production_control_witness[mode_check]",
  "tests/test_run_status.py::test_production_control_witness[nlink_check]",
  "tests/test_run_status.py::test_production_control_witness[owner_check]",
  "tests/test_run_status.py::test_production_control_witness[phrase_set]",
  "tests/test_run_status.py::test_production_control_witness[reader_readonly]",
  "tests/test_run_status.py::test_production_control_witness[ref_digest_only]",
  "tests/test_run_status.py::test_production_control_witness[refused_after_launch]",
  "tests/test_run_status.py::test_production_control_witness[run_claim]",
  "tests/test_run_status.py::test_production_control_witness[run_claim_fsync]",
  "tests/test_run_status.py::test_production_control_witness[segment_chain]",
  "tests/test_run_status.py::test_production_control_witness[seq_gap]",
  "tests/test_run_status.py::test_production_control_witness[structural_check]",
  "tests/test_run_status.py::test_production_control_witness[terminal_headroom]",
  "tests/test_run_status.py::test_production_control_witness[torn_line]",
  "tests/test_run_status.py::test_production_control_witness[unknown_version]",
  "tests/test_run_status.py::test_production_control_witness[writer_instance_reuse]",
  "tests/test_run_status.py::test_production_control_witness[writer_poison]",
  "tests/test_run_status.py::test_quarantined_assignment_keeps_every_claim",
  "tests/test_run_status.py::test_reader_leaves_bytes_modes_and_mtimes",
  "tests/test_run_status.py::test_refused_before_launch_round_trip",
  "tests/test_run_status.py::test_reservation_fsync_order",
  "tests/test_run_status.py::test_reservation_race_across_assignments_has_one_winner",
  "tests/test_run_status.py::test_reservation_race_distinct_attempts_stay_gapless",
  "tests/test_run_status.py::test_reservation_race_same_attempt_has_one_winner",
  "tests/test_run_status.py::test_reservation_refusals",
  "tests/test_run_status.py::test_reservation_refuses_broken_index[chain]",
  "tests/test_run_status.py::test_reservation_refuses_broken_index[torn]",
  "tests/test_run_status.py::test_root_and_excluded_roots_disjoint[containing]",
  "tests/test_run_status.py::test_root_and_excluded_roots_disjoint[equal]",
  "tests/test_run_status.py::test_root_and_excluded_roots_disjoint[inside]",
  "tests/test_run_status.py::test_root_creation_adopts_and_completes_barriers",
  "tests/test_run_status.py::test_root_creation_modes_and_layout",
  "tests/test_run_status.py::test_root_missing_without_create",
  "tests/test_run_status.py::test_root_mode_refused[453]",
  "tests/test_run_status.py::test_root_mode_refused[455]",
  "tests/test_run_status.py::test_root_mode_refused[488]",
  "tests/test_run_status.py::test_root_mode_refused[504]",
  "tests/test_run_status.py::test_root_mode_refused[960]",
  "tests/test_run_status.py::test_root_path_refusals[/x/../journal]",
  "tests/test_run_status.py::test_root_path_refusals[/x/\\x00journal]",
  "tests/test_run_status.py::test_root_path_refusals[relative/journal]",
  "tests/test_run_status.py::test_rotation_chains_segments",
  "tests/test_run_status.py::test_run_status_mutation_killed[assignment_dir_fsync]",
  "tests/test_run_status.py::test_run_status_mutation_killed[attempt_excl]",
  "tests/test_run_status.py::test_run_status_mutation_killed[component_nofollow]",
  "tests/test_run_status.py::test_run_status_mutation_killed[foreign_writer]",
  "tests/test_run_status.py::test_run_status_mutation_killed[identity_key]",
  "tests/test_run_status.py::test_run_status_mutation_killed[index_chain]",
  "tests/test_run_status.py::test_run_status_mutation_killed[index_fsync]",
  "tests/test_run_status.py::test_run_status_mutation_killed[index_lock]",
  "tests/test_run_status.py::test_run_status_mutation_killed[index_torn_refusal]",
  "tests/test_run_status.py::test_run_status_mutation_killed[lifecycle_order]",
  "tests/test_run_status.py::test_run_status_mutation_killed[line_cap]",
  "tests/test_run_status.py::test_run_status_mutation_killed[locator_rule]",
  "tests/test_run_status.py::test_run_status_mutation_killed[missing_segment]",
  "tests/test_run_status.py::test_run_status_mutation_killed[mode_check]",
  "tests/test_run_status.py::test_run_status_mutation_killed[nlink_check]",
  "tests/test_run_status.py::test_run_status_mutation_killed[owner_check]",
  "tests/test_run_status.py::test_run_status_mutation_killed[phrase_set]",
  "tests/test_run_status.py::test_run_status_mutation_killed[reader_readonly]",
  "tests/test_run_status.py::test_run_status_mutation_killed[ref_digest_only]",
  "tests/test_run_status.py::test_run_status_mutation_killed[refused_after_launch]",
  "tests/test_run_status.py::test_run_status_mutation_killed[run_claim]",
  "tests/test_run_status.py::test_run_status_mutation_killed[run_claim_fsync]",
  "tests/test_run_status.py::test_run_status_mutation_killed[segment_chain]",
  "tests/test_run_status.py::test_run_status_mutation_killed[seq_gap]",
  "tests/test_run_status.py::test_run_status_mutation_killed[structural_check]",
  "tests/test_run_status.py::test_run_status_mutation_killed[terminal_headroom]",
  "tests/test_run_status.py::test_run_status_mutation_killed[torn_line]",
  "tests/test_run_status.py::test_run_status_mutation_killed[unknown_version]",
  "tests/test_run_status.py::test_run_status_mutation_killed[writer_instance_reuse]",
  "tests/test_run_status.py::test_run_status_mutation_killed[writer_poison]",
  "tests/test_run_status.py::test_sentinels_never_reach_journal_bytes",
  "tests/test_run_status.py::test_structural_checker_agrees_on_produced_records",
  "tests/test_run_status.py::test_structural_checker_agrees_with_pinned_validator",
  "tests/test_run_status.py::test_structure_tables_equal_pinned_schema",
  "tests/test_run_status.py::test_symlinked_components_refused",
  "tests/test_run_status.py::test_unexpected_entry_and_unsafe_modes",
  "tests/test_run_status.py::test_unindexed_attempt_reads_unknown",
  "tests/test_run_status.py::test_unreadable_run_record_is_a_permanent_tombstone",
  "tests/test_run_status.py::test_vector_harness_asserts_every_edit",
  "tests/test_run_status.py::test_vector_ownership_counts",
  "tests/test_run_status.py::test_window_matches_read_attempt[N04a-replaced-in-place]",
  "tests/test_run_status.py::test_window_matches_read_attempt[N04a-seq-regress]",
  "tests/test_run_status.py::test_window_matches_read_attempt[N04a-seq-skip]",
  "tests/test_run_status.py::test_window_matches_read_attempt[N04b-foreign-binding]",
  "tests/test_run_status.py::test_window_matches_read_attempt[N15-foreign-writer]",
  "tests/test_run_status.py::test_window_matches_read_attempt[N15-no-final-newline]",
  "tests/test_run_status.py::test_window_matches_read_attempt[N15-torn-line]",
  "tests/test_run_status.py::test_window_matches_read_attempt[N15-unknown-version]",
  "tests/test_run_status.py::test_window_matches_read_attempt[N19-refused-after-running]",
  "tests/test_run_status.py::test_window_matches_read_attempt[N19-refused-after-start]",
  "tests/test_run_status.py::test_window_matches_read_attempt[N20-absolute-locator]",
  "tests/test_run_status.py::test_window_matches_read_attempt[N20-parent-locator]",
  "tests/test_run_status.py::test_window_matches_read_attempt[N20-raw-message]",
  "tests/test_run_status.py::test_window_matches_read_attempt[N20-raw-stdout-ref]",
  "tests/test_run_status.py::test_window_matches_read_attempt[S-evidence-copied]",
  "tests/test_run_status.py::test_window_matches_read_attempt[S-finished-without-termination]",
  "tests/test_run_status.py::test_window_matches_read_attempt[V-refused-before-launch]",
  "tests/test_run_status.py::test_window_matches_read_attempt[V-running]",
  "tests/test_run_status.py::test_window_matches_read_attempt[V-two-attempts]",
  "tests/test_run_status.py::test_window_slices_without_retaining_history",
  "tests/test_run_status.py::test_writer_adopts_an_existing_lock_and_completes_its_barrier",
  "tests/test_run_status.py::test_writer_fsync_order",
  "tests/test_run_status.py::test_writer_identity_minted_once",
  "tests/test_run_status.py::test_writer_ownership",
  "tests/test_run_status.py::test_writer_poisoned_after_failed_write_or_fsync[fsync]",
  "tests/test_run_status.py::test_writer_poisoned_after_failed_write_or_fsync[short]",
  "tests/test_run_status.py::test_writer_poisoned_after_failed_write_or_fsync[write]",
  "tests/test_run_status.py::test_wrong_owner_refused",
  "tests/test_run_status_projection.py::test_admission_order_defeats_lexical_mtime_and_observed_at",
  "tests/test_run_status_projection.py::test_bounds_match_pinned_schema",
  "tests/test_run_status_projection.py::test_cached_projection_is_stale_or_refused_never_current",
  "tests/test_run_status_projection.py::test_check_page_structure",
  "tests/test_run_status_projection.py::test_control_inventory_matches_artifact",
  "tests/test_run_status_projection.py::test_cursor_continues_after_further_appends",
  "tests/test_run_status_projection.py::test_cursor_tamper_foreign_and_range_refused",
  "tests/test_run_status_projection.py::test_index_defect_has_no_projection",
  "tests/test_run_status_projection.py::test_killed_subprocess_writer_reads_stale_unknown",
  "tests/test_run_status_projection.py::test_liveness_vector[N17-owner-not-live]",
  "tests/test_run_status_projection.py::test_liveness_vector[N17-pid-reused]",
  "tests/test_run_status_projection.py::test_liveness_vector[V-owner-live]",
  "tests/test_run_status_projection.py::test_malformed_page_request_refused[[]]",
  "tests/test_run_status_projection.py::test_malformed_page_request_refused[text]",
  "tests/test_run_status_projection.py::test_malformed_page_request_refused[{\"assignment_digest\":\"ce9c9ffdf06bece5d034886c3e1b51aa0a730cc2cfd13d5b82d139fc4cb1cbe5\",\"cursor\":null,\"page_size\":\"2\"}]",
  "tests/test_run_status_projection.py::test_malformed_page_request_refused[{\"assignment_digest\":\"ce9c9ffdf06bece5d034886c3e1b51aa0a730cc2cfd13d5b82d139fc4cb1cbe5\",\"cursor\":null,\"page_size\":2.5}]",
  "tests/test_run_status_projection.py::test_malformed_page_request_refused[{\"assignment_digest\":\"ce9c9ffdf06bece5d034886c3e1b51aa0a730cc2cfd13d5b82d139fc4cb1cbe5\",\"page_size\":2,\"page_size\":3,\"cursor\":null}]",
  "tests/test_run_status_projection.py::test_malformed_page_request_refused[{\"assignment_digest\":\"ce9c9ffdf06bece5d034886c3e1b51aa0a730cc2cfd13d5b82d139fc4cb1cbe5\",\"page_size\":2}]",
  "tests/test_run_status_projection.py::test_malformed_page_request_refused[{]",
  "tests/test_run_status_projection.py::test_module_has_no_filesystem_primitive",
  "tests/test_run_status_projection.py::test_non_phrase_runtime_state_refused",
  "tests/test_run_status_projection.py::test_page_size_bounds[0-page_size_invalid]",
  "tests/test_run_status_projection.py::test_page_size_bounds[1-1]",
  "tests/test_run_status_projection.py::test_page_size_bounds[100-5]",
  "tests/test_run_status_projection.py::test_page_size_bounds[101-read_unbounded]",
  "tests/test_run_status_projection.py::test_page_size_bounds[None-read_unbounded]",
  "tests/test_run_status_projection.py::test_page_spans_at_most_twenty_attempts",
  "tests/test_run_status_projection.py::test_page_vector[RC25-no-omitted]",
  "tests/test_run_status_projection.py::test_page_vector[RC25-no-page-size]",
  "tests/test_run_status_projection.py::test_page_vector[RC25-over-bound]",
  "tests/test_run_status_projection.py::test_page_vector[V-page]",
  "tests/test_run_status_projection.py::test_page_vector_rederived_through_read_page",
  "tests/test_run_status_projection.py::test_pid_reuse_and_observer_failures_are_stale",
  "tests/test_run_status_projection.py::test_production_control_witness[cursor_binding]",
  "tests/test_run_status_projection.py::test_production_control_witness[header_not_event]",
  "tests/test_run_status_projection.py::test_production_control_witness[index_order]",
  "tests/test_run_status_projection.py::test_production_control_witness[latest_fallback]",
  "tests/test_run_status_projection.py::test_production_control_witness[next_cursor]",
  "tests/test_run_status_projection.py::test_production_control_witness[omitted_counts]",
  "tests/test_run_status_projection.py::test_production_control_witness[outcome_source]",
  "tests/test_run_status_projection.py::test_production_control_witness[owner_live]",
  "tests/test_run_status_projection.py::test_production_control_witness[page_attempt_bound]",
  "tests/test_run_status_projection.py::test_production_control_witness[page_bound]",
  "tests/test_run_status_projection.py::test_production_control_witness[pid_reuse]",
  "tests/test_run_status_projection.py::test_production_control_witness[projection_ahead]",
  "tests/test_run_status_projection.py::test_production_control_witness[projection_behind]",
  "tests/test_run_status_projection.py::test_production_control_witness[retention_count]",
  "tests/test_run_status_projection.py::test_production_control_witness[row_join]",
  "tests/test_run_status_projection.py::test_production_control_witness[runtime_phrase_set]",
  "tests/test_run_status_projection.py::test_projection_and_page_memory_do_not_grow_with_segment_count",
  "tests/test_run_status_projection.py::test_projection_attempt_order_must_follow_index",
  "tests/test_run_status_projection.py::test_projection_vector[N16-attempt-missing]",
  "tests/test_run_status_projection.py::test_projection_vector[N16-projection-behind]",
  "tests/test_run_status_projection.py::test_projection_vector[S-projection-ahead]",
  "tests/test_run_status_projection.py::test_projection_vector[V-projection-at-tail]",
  "tests/test_run_status_projection.py::test_read_page_memory_is_bounded_on_a_large_history",
  "tests/test_run_status_projection.py::test_reader_view_input_shapes",
  "tests/test_run_status_projection.py::test_reader_view_vector[N18-completed-as-outcome]",
  "tests/test_run_status_projection.py::test_reader_view_vector[N18-run-status-as-evidence]",
  "tests/test_run_status_projection.py::test_reader_view_vector[RC24-foreign-assignment]",
  "tests/test_run_status_projection.py::test_reader_view_vector[RC24-foreign-snapshot]",
  "tests/test_run_status_projection.py::test_reader_view_vector[V-reader-view]",
  "tests/test_run_status_projection.py::test_refusal_passes_through_unchanged",
  "tests/test_run_status_projection.py::test_resolver_failures_are_unknown",
  "tests/test_run_status_projection.py::test_retention_dropped_counts_go_through_the_resolver",
  "tests/test_run_status_projection.py::test_run_status_projection_mutation_killed[cursor_binding]",
  "tests/test_run_status_projection.py::test_run_status_projection_mutation_killed[header_not_event]",
  "tests/test_run_status_projection.py::test_run_status_projection_mutation_killed[index_order]",
  "tests/test_run_status_projection.py::test_run_status_projection_mutation_killed[latest_fallback]",
  "tests/test_run_status_projection.py::test_run_status_projection_mutation_killed[next_cursor]",
  "tests/test_run_status_projection.py::test_run_status_projection_mutation_killed[omitted_counts]",
  "tests/test_run_status_projection.py::test_run_status_projection_mutation_killed[outcome_source]",
  "tests/test_run_status_projection.py::test_run_status_projection_mutation_killed[owner_live]",
  "tests/test_run_status_projection.py::test_run_status_projection_mutation_killed[page_attempt_bound]",
  "tests/test_run_status_projection.py::test_run_status_projection_mutation_killed[page_bound]",
  "tests/test_run_status_projection.py::test_run_status_projection_mutation_killed[pid_reuse]",
  "tests/test_run_status_projection.py::test_run_status_projection_mutation_killed[projection_ahead]",
  "tests/test_run_status_projection.py::test_run_status_projection_mutation_killed[projection_behind]",
  "tests/test_run_status_projection.py::test_run_status_projection_mutation_killed[retention_count]",
  "tests/test_run_status_projection.py::test_run_status_projection_mutation_killed[row_join]",
  "tests/test_run_status_projection.py::test_run_status_projection_mutation_killed[runtime_phrase_set]",
  "tests/test_run_status_projection.py::test_runtime_state_comes_from_the_closed_phrase_set",
  "tests/test_run_status_projection.py::test_sentinels_never_reach_projections_statuses_pages_or_views",
  "tests/test_run_status_projection.py::test_streaming_reads_load_the_index_once_and_never_rescan",
  "tests/test_run_status_projection.py::test_terminal_attempts_never_consult_the_observer",
  "tests/test_run_status_projection.py::test_unknown_attempts_contribute_no_lines",
  "tests/test_run_status_projection.py::test_unknown_earlier_attempt_is_listed_separately",
  "tests/test_run_status_projection.py::test_unknown_latest_attempt_never_falls_back"
 ],
 "producer_outcomes": {
  "tests/test_run_status.py::test_adopted_entries_complete_every_barrier": "passed",
  "tests/test_run_status.py::test_control_inventory_matches_artifact": "passed",
  "tests/test_run_status.py::test_crash_after_directory_claim_never_reuses_the_id": "passed",
  "tests/test_run_status.py::test_creator_killed_before_a_barrier_is_completed_by_the_next_reservation[/assignments/ce9c9ffdf06bece5d034886c3e1b51aa0a730cc2cfd13d5b82d139fc4cb1cbe5]": "passed",
  "tests/test_run_status.py::test_creator_killed_before_a_barrier_is_completed_by_the_next_reservation[/assignments]": "passed",
  "tests/test_run_status.py::test_creator_killed_before_a_barrier_is_completed_by_the_next_reservation[/attempts]": "passed",
  "tests/test_run_status.py::test_creator_killed_before_a_barrier_is_completed_by_the_next_reservation[/index.jsonl]": "passed",
  "tests/test_run_status.py::test_creator_killed_before_a_barrier_is_completed_by_the_next_reservation[/runs/run-1]": "passed",
  "tests/test_run_status.py::test_creator_killed_before_a_barrier_is_completed_by_the_next_reservation[/runs]": "passed",
  "tests/test_run_status.py::test_default_root_ignores_hostile_environment": "passed",
  "tests/test_run_status.py::test_digest_and_unit_refusals": "passed",
  "tests/test_run_status.py::test_event_phrase_set_is_closed[None]": "passed",
  "tests/test_run_status.py::test_event_phrase_set_is_closed[]": "passed",
  "tests/test_run_status.py::test_event_phrase_set_is_closed[attempt queued\\n]": "passed",
  "tests/test_run_status.py::test_event_phrase_set_is_closed[phrase4]": "passed",
  "tests/test_run_status.py::test_event_phrase_set_is_closed[worker returned a proposal]": "passed",
  "tests/test_run_status.py::test_event_refs_built_only_by_make_ref": "passed",
  "tests/test_run_status.py::test_excluded_root_by_inode_through_alias": "passed",
  "tests/test_run_status.py::test_failed_barrier_then_recovery_completes_the_chain[0]": "passed",
  "tests/test_run_status.py::test_failed_barrier_then_recovery_completes_the_chain[1]": "passed",
  "tests/test_run_status.py::test_failed_barrier_then_recovery_completes_the_chain[2]": "passed",
  "tests/test_run_status.py::test_failed_barrier_then_recovery_completes_the_chain[3]": "passed",
  "tests/test_run_status.py::test_failed_barrier_then_recovery_completes_the_chain[4]": "passed",
  "tests/test_run_status.py::test_failed_barrier_then_recovery_completes_the_chain[5]": "passed",
  "tests/test_run_status.py::test_failed_barrier_then_recovery_completes_the_chain[6]": "passed",
  "tests/test_run_status.py::test_hardlinked_segment_and_nonregular_entries": "passed",
  "tests/test_run_status.py::test_identifiers_refused_before_any_effect[-lead]": "passed",
  "tests/test_run_status.py::test_identifiers_refused_before_any_effect[..]": "passed",
  "tests/test_run_status.py::test_identifiers_refused_before_any_effect[.]": "passed",
  "tests/test_run_status.py::test_identifiers_refused_before_any_effect[7]": "passed",
  "tests/test_run_status.py::test_identifiers_refused_before_any_effect[None]": "passed",
  "tests/test_run_status.py::test_identifiers_refused_before_any_effect[\\xe4]": "passed",
  "tests/test_run_status.py::test_identifiers_refused_before_any_effect[]": "passed",
  "tests/test_run_status.py::test_identifiers_refused_before_any_effect[a b]": "passed",
  "tests/test_run_status.py::test_identifiers_refused_before_any_effect[a/b]": "passed",
  "tests/test_run_status.py::test_identifiers_refused_before_any_effect[x\\n]": "passed",
  "tests/test_run_status.py::test_identifiers_refused_before_any_effect[xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx]": "passed",
  "tests/test_run_status.py::test_identity_and_records_are_immutable": "passed",
  "tests/test_run_status.py::test_identity_versus_directory_and_index": "passed",
  "tests/test_run_status.py::test_index_defects_are_unverifiable": "passed",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[N04a-replaced-in-place]": "passed",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[N04a-seq-regress]": "passed",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[N04a-seq-skip]": "passed",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[N04b-foreign-binding]": "passed",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[N15-foreign-writer]": "passed",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[N15-no-final-newline]": "passed",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[N15-torn-line]": "passed",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[N15-unknown-version]": "passed",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[N19-refused-after-running]": "passed",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[N19-refused-after-start]": "passed",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[N20-absolute-locator]": "passed",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[N20-parent-locator]": "passed",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[N20-raw-message]": "passed",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[N20-raw-stdout-ref]": "passed",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[S-evidence-copied]": "passed",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[S-finished-without-termination]": "passed",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[V-refused-before-launch]": "passed",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[V-running]": "passed",
  "tests/test_run_status.py::test_journal_vector_through_production_readers[V-two-attempts]": "passed",
  "tests/test_run_status.py::test_lifecycle_violations_write_nothing": "passed",
  "tests/test_run_status.py::test_limits_validated": "passed",
  "tests/test_run_status.py::test_line_cap_reserves_terminal_headroom_across_rotation": "passed",
  "tests/test_run_status.py::test_longest_identifier_accepted": "passed",
  "tests/test_run_status.py::test_missing_interior_segment_is_overwritten": "passed",
  "tests/test_run_status.py::test_missing_journal_and_reserved_without_writer": "passed",
  "tests/test_run_status.py::test_partial_line_reads_torn_after_poison": "passed",
  "tests/test_run_status.py::test_production_control_witness[assignment_dir_fsync]": "passed",
  "tests/test_run_status.py::test_production_control_witness[attempt_excl]": "passed",
  "tests/test_run_status.py::test_production_control_witness[component_nofollow]": "passed",
  "tests/test_run_status.py::test_production_control_witness[foreign_writer]": "passed",
  "tests/test_run_status.py::test_production_control_witness[identity_key]": "passed",
  "tests/test_run_status.py::test_production_control_witness[index_chain]": "passed",
  "tests/test_run_status.py::test_production_control_witness[index_fsync]": "passed",
  "tests/test_run_status.py::test_production_control_witness[index_lock]": "passed",
  "tests/test_run_status.py::test_production_control_witness[index_torn_refusal]": "passed",
  "tests/test_run_status.py::test_production_control_witness[lifecycle_order]": "passed",
  "tests/test_run_status.py::test_production_control_witness[line_cap]": "passed",
  "tests/test_run_status.py::test_production_control_witness[locator_rule]": "passed",
  "tests/test_run_status.py::test_production_control_witness[missing_segment]": "passed",
  "tests/test_run_status.py::test_production_control_witness[mode_check]": "passed",
  "tests/test_run_status.py::test_production_control_witness[nlink_check]": "passed",
  "tests/test_run_status.py::test_production_control_witness[owner_check]": "passed",
  "tests/test_run_status.py::test_production_control_witness[phrase_set]": "passed",
  "tests/test_run_status.py::test_production_control_witness[reader_readonly]": "passed",
  "tests/test_run_status.py::test_production_control_witness[ref_digest_only]": "passed",
  "tests/test_run_status.py::test_production_control_witness[refused_after_launch]": "passed",
  "tests/test_run_status.py::test_production_control_witness[run_claim]": "passed",
  "tests/test_run_status.py::test_production_control_witness[run_claim_fsync]": "passed",
  "tests/test_run_status.py::test_production_control_witness[segment_chain]": "passed",
  "tests/test_run_status.py::test_production_control_witness[seq_gap]": "passed",
  "tests/test_run_status.py::test_production_control_witness[structural_check]": "passed",
  "tests/test_run_status.py::test_production_control_witness[terminal_headroom]": "passed",
  "tests/test_run_status.py::test_production_control_witness[torn_line]": "passed",
  "tests/test_run_status.py::test_production_control_witness[unknown_version]": "passed",
  "tests/test_run_status.py::test_production_control_witness[writer_instance_reuse]": "passed",
  "tests/test_run_status.py::test_production_control_witness[writer_poison]": "passed",
  "tests/test_run_status.py::test_quarantined_assignment_keeps_every_claim": "passed",
  "tests/test_run_status.py::test_reader_leaves_bytes_modes_and_mtimes": "passed",
  "tests/test_run_status.py::test_refused_before_launch_round_trip": "passed",
  "tests/test_run_status.py::test_reservation_fsync_order": "passed",
  "tests/test_run_status.py::test_reservation_race_across_assignments_has_one_winner": "passed",
  "tests/test_run_status.py::test_reservation_race_distinct_attempts_stay_gapless": "passed",
  "tests/test_run_status.py::test_reservation_race_same_attempt_has_one_winner": "passed",
  "tests/test_run_status.py::test_reservation_refusals": "passed",
  "tests/test_run_status.py::test_reservation_refuses_broken_index[chain]": "passed",
  "tests/test_run_status.py::test_reservation_refuses_broken_index[torn]": "passed",
  "tests/test_run_status.py::test_root_and_excluded_roots_disjoint[containing]": "passed",
  "tests/test_run_status.py::test_root_and_excluded_roots_disjoint[equal]": "passed",
  "tests/test_run_status.py::test_root_and_excluded_roots_disjoint[inside]": "passed",
  "tests/test_run_status.py::test_root_creation_adopts_and_completes_barriers": "passed",
  "tests/test_run_status.py::test_root_creation_modes_and_layout": "passed",
  "tests/test_run_status.py::test_root_missing_without_create": "passed",
  "tests/test_run_status.py::test_root_mode_refused[453]": "passed",
  "tests/test_run_status.py::test_root_mode_refused[455]": "passed",
  "tests/test_run_status.py::test_root_mode_refused[488]": "passed",
  "tests/test_run_status.py::test_root_mode_refused[504]": "passed",
  "tests/test_run_status.py::test_root_mode_refused[960]": "passed",
  "tests/test_run_status.py::test_root_path_refusals[/x/../journal]": "passed",
  "tests/test_run_status.py::test_root_path_refusals[/x/\\x00journal]": "passed",
  "tests/test_run_status.py::test_root_path_refusals[relative/journal]": "passed",
  "tests/test_run_status.py::test_rotation_chains_segments": "passed",
  "tests/test_run_status.py::test_run_status_mutation_killed[assignment_dir_fsync]": "passed",
  "tests/test_run_status.py::test_run_status_mutation_killed[attempt_excl]": "passed",
  "tests/test_run_status.py::test_run_status_mutation_killed[component_nofollow]": "passed",
  "tests/test_run_status.py::test_run_status_mutation_killed[foreign_writer]": "passed",
  "tests/test_run_status.py::test_run_status_mutation_killed[identity_key]": "passed",
  "tests/test_run_status.py::test_run_status_mutation_killed[index_chain]": "passed",
  "tests/test_run_status.py::test_run_status_mutation_killed[index_fsync]": "passed",
  "tests/test_run_status.py::test_run_status_mutation_killed[index_lock]": "passed",
  "tests/test_run_status.py::test_run_status_mutation_killed[index_torn_refusal]": "passed",
  "tests/test_run_status.py::test_run_status_mutation_killed[lifecycle_order]": "passed",
  "tests/test_run_status.py::test_run_status_mutation_killed[line_cap]": "passed",
  "tests/test_run_status.py::test_run_status_mutation_killed[locator_rule]": "passed",
  "tests/test_run_status.py::test_run_status_mutation_killed[missing_segment]": "passed",
  "tests/test_run_status.py::test_run_status_mutation_killed[mode_check]": "passed",
  "tests/test_run_status.py::test_run_status_mutation_killed[nlink_check]": "passed",
  "tests/test_run_status.py::test_run_status_mutation_killed[owner_check]": "passed",
  "tests/test_run_status.py::test_run_status_mutation_killed[phrase_set]": "passed",
  "tests/test_run_status.py::test_run_status_mutation_killed[reader_readonly]": "passed",
  "tests/test_run_status.py::test_run_status_mutation_killed[ref_digest_only]": "passed",
  "tests/test_run_status.py::test_run_status_mutation_killed[refused_after_launch]": "passed",
  "tests/test_run_status.py::test_run_status_mutation_killed[run_claim]": "passed",
  "tests/test_run_status.py::test_run_status_mutation_killed[run_claim_fsync]": "passed",
  "tests/test_run_status.py::test_run_status_mutation_killed[segment_chain]": "passed",
  "tests/test_run_status.py::test_run_status_mutation_killed[seq_gap]": "passed",
  "tests/test_run_status.py::test_run_status_mutation_killed[structural_check]": "passed",
  "tests/test_run_status.py::test_run_status_mutation_killed[terminal_headroom]": "passed",
  "tests/test_run_status.py::test_run_status_mutation_killed[torn_line]": "passed",
  "tests/test_run_status.py::test_run_status_mutation_killed[unknown_version]": "passed",
  "tests/test_run_status.py::test_run_status_mutation_killed[writer_instance_reuse]": "passed",
  "tests/test_run_status.py::test_run_status_mutation_killed[writer_poison]": "passed",
  "tests/test_run_status.py::test_sentinels_never_reach_journal_bytes": "passed",
  "tests/test_run_status.py::test_structural_checker_agrees_on_produced_records": "passed",
  "tests/test_run_status.py::test_structural_checker_agrees_with_pinned_validator": "passed",
  "tests/test_run_status.py::test_structure_tables_equal_pinned_schema": "passed",
  "tests/test_run_status.py::test_symlinked_components_refused": "passed",
  "tests/test_run_status.py::test_unexpected_entry_and_unsafe_modes": "passed",
  "tests/test_run_status.py::test_unindexed_attempt_reads_unknown": "passed",
  "tests/test_run_status.py::test_unreadable_run_record_is_a_permanent_tombstone": "passed",
  "tests/test_run_status.py::test_vector_harness_asserts_every_edit": "passed",
  "tests/test_run_status.py::test_vector_ownership_counts": "passed",
  "tests/test_run_status.py::test_window_matches_read_attempt[N04a-replaced-in-place]": "passed",
  "tests/test_run_status.py::test_window_matches_read_attempt[N04a-seq-regress]": "passed",
  "tests/test_run_status.py::test_window_matches_read_attempt[N04a-seq-skip]": "passed",
  "tests/test_run_status.py::test_window_matches_read_attempt[N04b-foreign-binding]": "passed",
  "tests/test_run_status.py::test_window_matches_read_attempt[N15-foreign-writer]": "passed",
  "tests/test_run_status.py::test_window_matches_read_attempt[N15-no-final-newline]": "passed",
  "tests/test_run_status.py::test_window_matches_read_attempt[N15-torn-line]": "passed",
  "tests/test_run_status.py::test_window_matches_read_attempt[N15-unknown-version]": "passed",
  "tests/test_run_status.py::test_window_matches_read_attempt[N19-refused-after-running]": "passed",
  "tests/test_run_status.py::test_window_matches_read_attempt[N19-refused-after-start]": "passed",
  "tests/test_run_status.py::test_window_matches_read_attempt[N20-absolute-locator]": "passed",
  "tests/test_run_status.py::test_window_matches_read_attempt[N20-parent-locator]": "passed",
  "tests/test_run_status.py::test_window_matches_read_attempt[N20-raw-message]": "passed",
  "tests/test_run_status.py::test_window_matches_read_attempt[N20-raw-stdout-ref]": "passed",
  "tests/test_run_status.py::test_window_matches_read_attempt[S-evidence-copied]": "passed",
  "tests/test_run_status.py::test_window_matches_read_attempt[S-finished-without-termination]": "passed",
  "tests/test_run_status.py::test_window_matches_read_attempt[V-refused-before-launch]": "passed",
  "tests/test_run_status.py::test_window_matches_read_attempt[V-running]": "passed",
  "tests/test_run_status.py::test_window_matches_read_attempt[V-two-attempts]": "passed",
  "tests/test_run_status.py::test_window_slices_without_retaining_history": "passed",
  "tests/test_run_status.py::test_writer_adopts_an_existing_lock_and_completes_its_barrier": "passed",
  "tests/test_run_status.py::test_writer_fsync_order": "passed",
  "tests/test_run_status.py::test_writer_identity_minted_once": "passed",
  "tests/test_run_status.py::test_writer_ownership": "passed",
  "tests/test_run_status.py::test_writer_poisoned_after_failed_write_or_fsync[fsync]": "passed",
  "tests/test_run_status.py::test_writer_poisoned_after_failed_write_or_fsync[short]": "passed",
  "tests/test_run_status.py::test_writer_poisoned_after_failed_write_or_fsync[write]": "passed",
  "tests/test_run_status.py::test_wrong_owner_refused": "passed",
  "tests/test_run_status_projection.py::test_admission_order_defeats_lexical_mtime_and_observed_at": "passed",
  "tests/test_run_status_projection.py::test_bounds_match_pinned_schema": "passed",
  "tests/test_run_status_projection.py::test_cached_projection_is_stale_or_refused_never_current": "passed",
  "tests/test_run_status_projection.py::test_check_page_structure": "passed",
  "tests/test_run_status_projection.py::test_control_inventory_matches_artifact": "passed",
  "tests/test_run_status_projection.py::test_cursor_continues_after_further_appends": "passed",
  "tests/test_run_status_projection.py::test_cursor_tamper_foreign_and_range_refused": "passed",
  "tests/test_run_status_projection.py::test_index_defect_has_no_projection": "passed",
  "tests/test_run_status_projection.py::test_killed_subprocess_writer_reads_stale_unknown": "passed",
  "tests/test_run_status_projection.py::test_liveness_vector[N17-owner-not-live]": "passed",
  "tests/test_run_status_projection.py::test_liveness_vector[N17-pid-reused]": "passed",
  "tests/test_run_status_projection.py::test_liveness_vector[V-owner-live]": "passed",
  "tests/test_run_status_projection.py::test_malformed_page_request_refused[[]]": "passed",
  "tests/test_run_status_projection.py::test_malformed_page_request_refused[text]": "passed",
  "tests/test_run_status_projection.py::test_malformed_page_request_refused[{\"assignment_digest\":\"ce9c9ffdf06bece5d034886c3e1b51aa0a730cc2cfd13d5b82d139fc4cb1cbe5\",\"cursor\":null,\"page_size\":\"2\"}]": "passed",
  "tests/test_run_status_projection.py::test_malformed_page_request_refused[{\"assignment_digest\":\"ce9c9ffdf06bece5d034886c3e1b51aa0a730cc2cfd13d5b82d139fc4cb1cbe5\",\"cursor\":null,\"page_size\":2.5}]": "passed",
  "tests/test_run_status_projection.py::test_malformed_page_request_refused[{\"assignment_digest\":\"ce9c9ffdf06bece5d034886c3e1b51aa0a730cc2cfd13d5b82d139fc4cb1cbe5\",\"page_size\":2,\"page_size\":3,\"cursor\":null}]": "passed",
  "tests/test_run_status_projection.py::test_malformed_page_request_refused[{\"assignment_digest\":\"ce9c9ffdf06bece5d034886c3e1b51aa0a730cc2cfd13d5b82d139fc4cb1cbe5\",\"page_size\":2}]": "passed",
  "tests/test_run_status_projection.py::test_malformed_page_request_refused[{]": "passed",
  "tests/test_run_status_projection.py::test_module_has_no_filesystem_primitive": "passed",
  "tests/test_run_status_projection.py::test_non_phrase_runtime_state_refused": "passed",
  "tests/test_run_status_projection.py::test_page_size_bounds[0-page_size_invalid]": "passed",
  "tests/test_run_status_projection.py::test_page_size_bounds[1-1]": "passed",
  "tests/test_run_status_projection.py::test_page_size_bounds[100-5]": "passed",
  "tests/test_run_status_projection.py::test_page_size_bounds[101-read_unbounded]": "passed",
  "tests/test_run_status_projection.py::test_page_size_bounds[None-read_unbounded]": "passed",
  "tests/test_run_status_projection.py::test_page_spans_at_most_twenty_attempts": "passed",
  "tests/test_run_status_projection.py::test_page_vector[RC25-no-omitted]": "passed",
  "tests/test_run_status_projection.py::test_page_vector[RC25-no-page-size]": "passed",
  "tests/test_run_status_projection.py::test_page_vector[RC25-over-bound]": "passed",
  "tests/test_run_status_projection.py::test_page_vector[V-page]": "passed",
  "tests/test_run_status_projection.py::test_page_vector_rederived_through_read_page": "passed",
  "tests/test_run_status_projection.py::test_pid_reuse_and_observer_failures_are_stale": "passed",
  "tests/test_run_status_projection.py::test_production_control_witness[cursor_binding]": "passed",
  "tests/test_run_status_projection.py::test_production_control_witness[header_not_event]": "passed",
  "tests/test_run_status_projection.py::test_production_control_witness[index_order]": "passed",
  "tests/test_run_status_projection.py::test_production_control_witness[latest_fallback]": "passed",
  "tests/test_run_status_projection.py::test_production_control_witness[next_cursor]": "passed",
  "tests/test_run_status_projection.py::test_production_control_witness[omitted_counts]": "passed",
  "tests/test_run_status_projection.py::test_production_control_witness[outcome_source]": "passed",
  "tests/test_run_status_projection.py::test_production_control_witness[owner_live]": "passed",
  "tests/test_run_status_projection.py::test_production_control_witness[page_attempt_bound]": "passed",
  "tests/test_run_status_projection.py::test_production_control_witness[page_bound]": "passed",
  "tests/test_run_status_projection.py::test_production_control_witness[pid_reuse]": "passed",
  "tests/test_run_status_projection.py::test_production_control_witness[projection_ahead]": "passed",
  "tests/test_run_status_projection.py::test_production_control_witness[projection_behind]": "passed",
  "tests/test_run_status_projection.py::test_production_control_witness[retention_count]": "passed",
  "tests/test_run_status_projection.py::test_production_control_witness[row_join]": "passed",
  "tests/test_run_status_projection.py::test_production_control_witness[runtime_phrase_set]": "passed",
  "tests/test_run_status_projection.py::test_projection_and_page_memory_do_not_grow_with_segment_count": "passed",
  "tests/test_run_status_projection.py::test_projection_attempt_order_must_follow_index": "passed",
  "tests/test_run_status_projection.py::test_projection_vector[N16-attempt-missing]": "passed",
  "tests/test_run_status_projection.py::test_projection_vector[N16-projection-behind]": "passed",
  "tests/test_run_status_projection.py::test_projection_vector[S-projection-ahead]": "passed",
  "tests/test_run_status_projection.py::test_projection_vector[V-projection-at-tail]": "passed",
  "tests/test_run_status_projection.py::test_read_page_memory_is_bounded_on_a_large_history": "passed",
  "tests/test_run_status_projection.py::test_reader_view_input_shapes": "passed",
  "tests/test_run_status_projection.py::test_reader_view_vector[N18-completed-as-outcome]": "passed",
  "tests/test_run_status_projection.py::test_reader_view_vector[N18-run-status-as-evidence]": "passed",
  "tests/test_run_status_projection.py::test_reader_view_vector[RC24-foreign-assignment]": "passed",
  "tests/test_run_status_projection.py::test_reader_view_vector[RC24-foreign-snapshot]": "passed",
  "tests/test_run_status_projection.py::test_reader_view_vector[V-reader-view]": "passed",
  "tests/test_run_status_projection.py::test_refusal_passes_through_unchanged": "passed",
  "tests/test_run_status_projection.py::test_resolver_failures_are_unknown": "passed",
  "tests/test_run_status_projection.py::test_retention_dropped_counts_go_through_the_resolver": "passed",
  "tests/test_run_status_projection.py::test_run_status_projection_mutation_killed[cursor_binding]": "passed",
  "tests/test_run_status_projection.py::test_run_status_projection_mutation_killed[header_not_event]": "passed",
  "tests/test_run_status_projection.py::test_run_status_projection_mutation_killed[index_order]": "passed",
  "tests/test_run_status_projection.py::test_run_status_projection_mutation_killed[latest_fallback]": "passed",
  "tests/test_run_status_projection.py::test_run_status_projection_mutation_killed[next_cursor]": "passed",
  "tests/test_run_status_projection.py::test_run_status_projection_mutation_killed[omitted_counts]": "passed",
  "tests/test_run_status_projection.py::test_run_status_projection_mutation_killed[outcome_source]": "passed",
  "tests/test_run_status_projection.py::test_run_status_projection_mutation_killed[owner_live]": "passed",
  "tests/test_run_status_projection.py::test_run_status_projection_mutation_killed[page_attempt_bound]": "passed",
  "tests/test_run_status_projection.py::test_run_status_projection_mutation_killed[page_bound]": "passed",
  "tests/test_run_status_projection.py::test_run_status_projection_mutation_killed[pid_reuse]": "passed",
  "tests/test_run_status_projection.py::test_run_status_projection_mutation_killed[projection_ahead]": "passed",
  "tests/test_run_status_projection.py::test_run_status_projection_mutation_killed[projection_behind]": "passed",
  "tests/test_run_status_projection.py::test_run_status_projection_mutation_killed[retention_count]": "passed",
  "tests/test_run_status_projection.py::test_run_status_projection_mutation_killed[row_join]": "passed",
  "tests/test_run_status_projection.py::test_run_status_projection_mutation_killed[runtime_phrase_set]": "passed",
  "tests/test_run_status_projection.py::test_runtime_state_comes_from_the_closed_phrase_set": "passed",
  "tests/test_run_status_projection.py::test_sentinels_never_reach_projections_statuses_pages_or_views": "passed",
  "tests/test_run_status_projection.py::test_streaming_reads_load_the_index_once_and_never_rescan": "passed",
  "tests/test_run_status_projection.py::test_terminal_attempts_never_consult_the_observer": "passed",
  "tests/test_run_status_projection.py::test_unknown_attempts_contribute_no_lines": "passed",
  "tests/test_run_status_projection.py::test_unknown_earlier_attempt_is_listed_separately": "passed",
  "tests/test_run_status_projection.py::test_unknown_latest_attempt_never_falls_back": "passed"
 },
 "producer_runs": {
  "3.12": {
   "failed": 0,
   "junit_sha256": "cff8a97682fa23ed91aabf8b40986dc76b34d92078b34784577ce0b0615afc8e",
   "passed": 277,
   "seconds": 23.447,
   "skipped": 0
  },
  "3.14": {
   "failed": 0,
   "junit_sha256": "1ac8314641f4b80bfab0cc6ee13faa45ebe1cff1f1d1ada9bb7b3557152055fd",
   "passed": 277,
   "seconds": 22.269,
   "skipped": 0
  }
 },
 "runner_stamp": {
  "approved_plan_input": "309c9e92",
  "observed_input_base": "5a04c10bc34c1b8d9c1424c043db11e5898eae72",
  "observed_utc": "2026-11-09T02:09:57.445129+00:00",
  "source_tree_digest": "fd131498edfb7073c48883a23f4bb3df58ee9944d9d8545d06f1ed24119c38d3"
 },
 "source_hashes": {
  "docs/supervised-run-status.md": "8f2485af4b284edc2a8fcd9b51126610b91261b4f392743f6b0fd36bade589aa",
  "phase-loop-runtime/src/phase_loop_runtime/run_status.py": "e7722187bfa5187ea1da174472055cd94e6b35099e5ab157864ec789bbe78098",
  "phase-loop-runtime/src/phase_loop_runtime/run_status_projection.py": "72568d1af57255552968b9e378860b89c9d5e838d206266db5423039c22fa7c1",
  "phase-loop-runtime/src/phase_loop_runtime/schemas/supervised-worker-v1/conformance/run-status.vectors.json": "5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730",
  "phase-loop-runtime/src/phase_loop_runtime/schemas/supervised-worker-v1/run-status.schema.json": "5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30",
  "phase-loop-runtime/tests/_run_status_vectors.py": "3710194953ef6d552584ce2ce9186197f63d19c2108c74e60d44ac64b6495237",
  "phase-loop-runtime/tests/data/seat_launch_references.json": "f9190444032dc91a7b089ad0c3218556b1b8a5ba4274387d39981dbe8cce8b2f",
  "phase-loop-runtime/tests/test_run_status.py": "9e9db80dac4859bb8f256a74219544e9548ab3af1c451bb9cd65930818014e5e",
  "phase-loop-runtime/tests/test_run_status_projection.py": "8d8f9c863f4bf8d8490da9fd753ecaaf206268d8e8c999aae37b2609e1d0763d",
  "phase-loop-runtime/tests/test_run_status_receipt.py": "9c4ff949fbb911e23d8950b678512f3dbbf198839567555c41053eae5a7da608",
  "plans/artifacts/v12-JOURNAL-interface.md": "c9100f04e8fef192b21ec0037ed5fea1b4a5ab882b56c52e7e9aab87ffd7bd05"
 },
 "vector_outcomes": {
  "N04a-replaced-in-place": "passed",
  "N04a-seq-regress": "passed",
  "N04a-seq-skip": "passed",
  "N04b-foreign-binding": "passed",
  "N15-foreign-writer": "passed",
  "N15-no-final-newline": "passed",
  "N15-torn-line": "passed",
  "N15-unknown-version": "passed",
  "N16-attempt-missing": "passed",
  "N16-projection-behind": "passed",
  "N17-owner-not-live": "passed",
  "N17-pid-reused": "passed",
  "N18-completed-as-outcome": "passed",
  "N18-run-status-as-evidence": "passed",
  "N19-refused-after-running": "passed",
  "N19-refused-after-start": "passed",
  "N20-absolute-locator": "passed",
  "N20-parent-locator": "passed",
  "N20-raw-message": "passed",
  "N20-raw-stdout-ref": "passed",
  "RC24-foreign-assignment": "passed",
  "RC24-foreign-snapshot": "passed",
  "RC25-no-omitted": "passed",
  "RC25-no-page-size": "passed",
  "RC25-over-bound": "passed",
  "S-evidence-copied": "passed",
  "S-finished-without-termination": "passed",
  "S-projection-ahead": "passed",
  "V-owner-live": "passed",
  "V-page": "passed",
  "V-projection-at-tail": "passed",
  "V-reader-view": "passed",
  "V-refused-before-launch": "passed",
  "V-running": "passed",
  "V-two-attempts": "passed"
 }
}
```
