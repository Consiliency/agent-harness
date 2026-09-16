---
automation:
  suite_command:
    - bash
    - -lc
    - >-
      set -euo pipefail;
      PHASE_LOOP_TDD_EXPECT_RUNTIME=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q
      phase-loop-runtime/tests/test_runtime_event_log_hardening_720.py
      phase-loop-runtime/tests/test_runtime_adapter_output_720.py
      phase-loop-runtime/tests/test_convergence_event_log.py
      phase-loop-runtime/tests/test_convergence_reconcile.py
      phase-loop-runtime/tests/test_convergence_adapters.py
      phase-loop-runtime/tests/test_convergence_status.py
      phase-loop-runtime/tests/test_convergence_runtime_imports.py
      phase-loop-runtime/tests/test_cli_train_status_45.py
      phase-loop-runtime/tests/test_convergence_event_contracts.py
      phase-loop-runtime/tests/test_convergence_coordination_contracts.py
      phase-loop-runtime/tests/test_convergence_provider_contracts.py
      phase-loop-runtime/tests/test_convergence_fixture_contracts.py;
      ruff check phase-loop-runtime/src/phase_loop_runtime/convergence/event_log.py
      phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/base.py
      phase-loop-runtime/tests/test_runtime_event_log_hardening_720.py
      phase-loop-runtime/tests/test_runtime_adapter_output_720.py;
      git diff --exit-code 2f75797695ed58cbb0f8026b655d5068b23f2e88 --
      phase-loop-runtime/tests/_runtime_tdd_guard.py
      phase-loop-runtime/tests/runtime_content_tdd_adapter.py
      phase-loop-runtime/tests/test_cli_train_status_45.py
      phase-loop-runtime/tests/test_convergence_adapters.py
      phase-loop-runtime/tests/test_convergence_event_log.py
      phase-loop-runtime/tests/test_convergence_reconcile.py
      phase-loop-runtime/tests/test_convergence_runtime_imports.py
      phase-loop-runtime/tests/test_convergence_status.py;
      git diff --check
---

# Detailed plan: close the three runtime hardening defects in agent-harness#720

## Task

Repair items 1–3 of agent-harness#720: committed log corruption must fail closed,
log paths must remain inside their selected coordinator storage, and adapter
output capture must be bounded before allocation. This is a bounded follow-up to
the already merged RUNTIME implementation, agent-harness#719. It does not accept
RUNTIME or INTEG, replace historical evidence, or change HARDEN/provider policy.

## Research summary

Input main is `cfbedcb172bc5ab590ca5c91cca89a5db59382bb`. The original eight SL-0
files match tests landing `2f75797695ed58cbb0f8026b655d5068b23f2e88` byte for byte.
The current native audit passes the focused tests and structural/lint checks,
but the receipt verifier fails because the original receipt is not recovered.
Recovered original CI and reviews are historical records, not substitute receipts.

The retained `known-faults-r1/observations.json` demonstrates that the current
reader accepts a newline-terminated malformed record and the writer discards it;
the path helper accepts traversal and a convergence-directory symlink redirects
a real append into `.phase-loop`; and `run_bounded` captures 262144 bytes on each
stream despite its 65536-byte limit. All probes used synthetic local files and
one synthetic executable, with no provider request or production side effect.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/convergence/event_log.py` (modify)

- `_durable_records`, `_parse`, `read_convergence_events`: use the newline boundary
  to distinguish a possibly interrupted final append from a committed record.
  Only an unterminated final fragment may be ignored/repaired. A malformed
  newline-terminated record, including the last one, raises `ValueError`; neither
  reading nor a rejected append may alter any byte. Cover invalid JSON, UTF-8,
  field shape and event kind consistently. Reader and writer share byte-level
  LF tokenization and decode complete lines individually; a carriage return alone
  is not a record boundary. Non-object values, missing fields (including `kind`),
  and invalid field shapes raise `ValueError`, not `KeyError` or `TypeError`.
  Preserve blank-line handling, canonical serialization, flock and fsync.
  Validate replay/conflict before mutation; an identical replay may repair an
  unterminated tail under the lock, but a rejected append changes no bytes.
  Keep `fcntl.flock` inside `_append`, called through its module attribute for
  the frozen source-text probe and recorder. Reading an absent log returns `()`.
- `default_convergence_event_log_path`: reject an empty train ID, dot components,
  NUL, and either slash as separators. Accept ordinary opaque single-component
  identifiers, including interior dots, without a stricter grammar. Return the
  compatible lexical `Path`; each later I/O call validates afresh. Resolve
  the operator-selected root and require the resolved candidate to remain under
  its `convergence` directory. Reject every descendant directory or leaf symlink and
  every resolved `.phase-loop` component before creating files.
- `_reject_phase_loop`, `_append`, `read_convergence_events`: enforce the resolved
  `.phase-loop` exclusion for direct callers too. Bind the validated parent and
  file used for I/O so replacing a symlink between validation and open cannot
  redirect an operation. Use directory-relative, no-follow opens where needed;
  retain signatures and avoid a new global path registry. Preserve normal root
  aliases such as `/mnt/workspace`; validate their canonical destination. Before
  effects, open the root by its canonical path and compare its descriptor's
  device/inode with the reference identity taken on that same canonical path;
  walk descendants relative to descriptors
  without following symlinks. An alias retarget cannot redirect the operation.
  Each I/O call validates and binds its own path; no earlier helper call grants
  lasting authority. The selected storage owner must keep every bound directory
  and file in place during I/O, including descendants and canonical ancestors;
  cooperative concurrent appenders are serialized by flock. Descriptor binding
  preserves object identity, not namespace location against a hostile storage
  owner or privileged actor who relocates an open object. That host-isolation
  problem is outside this pathname repair. Tests cover alias and symlink
  replacement during path binding, unchanged
  outside bytes, and refusal of non-escaping descendant symlinks too.

### `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/base.py` (modify)

- `run_bounded`: replace `communicate()` accumulation with concurrent binary
  draining of stdout and stderr, using a monotonic deadline and bounded reads.
  Maintain a separate 65536-byte budget per stream. Retain at most that stdout
  budget for parsing; stderr need not be retained. Detect overflow with at most
  one extra byte, then stop the whole owned process group, close pipes, and reap
  the leader. Never drain unlimited output during cleanup.
- Overflow returns existing `BLOCKED` with a fixed metadata-only diagnostic.
  Either stream exceeding its budget violates this primitive's bounded-output
  contract, including verbose stderr; discarding stderr is not an unlimited
  output allowance. This compatibility change is documented and synthetically
  tested, not claimed as live-provider qualification.
  Timeout retains `DEGRADED`; nonzero exit retains `FAILED`; valid bounded JSON
  retains its existing status and attempt ID. An oversized payload beginning
  with valid JSON must still block. Decode only bounded stdout, handle malformed
  UTF-8 without leaking provider text, and count bytes rather than characters.
- Observe leader exit without reaping it before group cleanup. On exit, drain
  already readable bytes non-blocking until EOF/EAGAIN, still enforcing both
  byte budgets and the original deadline; do not wait for descendant-held EOF.
  Reclaim the owned group before reaping its leader so its identity cannot be
  reused before signaling. A zero-exit leader with bounded complete JSON retains
  its declared status even if a descendant held a pipe; malformed output blocks.
  Obtain the leader's original exit status from the non-reaping observation or
  the collecting reap, never a later Popen poll after an independent waitpid
  consumed it. Nonzero exit returns `FAILED`, including with complete success
  JSON and descendant-held pipes, subject to the precedence below.
- Cleanup runs on every exit, including `BaseException`. Keep the actual
  `os.killpg` call inside `run_bounded` for the frozen source-text probe. Close
  pipes and bound the final leader wait to one second after the kill; inability
  to reap yields a fixed cleanup-failure `DEGRADED` diagnostic rather than success.
  Terminal precedence is: preserve an existing `BaseException`; otherwise cleanup
  failure returns `DEGRADED`; otherwise observed overflow returns `BLOCKED`;
  otherwise expiry returns `DEGRADED`; otherwise nonzero exit returns `FAILED`;
  otherwise parse the bounded output. Never drain, join or wait without a bound
  or signal unrelated groups.
  These remain one-action primitives; no route, scrubber or coordination change.

### New regression tests (create)

- `phase-loop-runtime/tests/test_runtime_event_log_hardening_720.py`: complete
  corruption at the final and earlier records; unchanged rejected bytes;
  unterminated torn-tail positive control; ordinary restart/replay; invalid
  train IDs; escaping leaf/parent symlinks; resolved `.phase-loop` through an
  alias; deterministic path replacement before open; normal root aliases.
- `phase-loop-runtime/tests/test_runtime_adapter_output_720.py`: actual synthetic
  subprocesses emitting stdout-only, stderr-only and simultaneous overflow;
  exactly-at-limit and over-limit UTF-8 payloads; valid JSON plus excess padding;
  a descendant retaining pipes; nonzero exit with and without such a descendant
  (including complete success JSON); timeout and interruption cleanup; malformed and
  bounded-success controls. Assert entered paths, bounded captured/read sizes,
  prompt termination and no surviving owned process. Do not use a large-memory
  stress test or invoke a real provider. Keep these fixtures and failed evidence.

Include paired read/append controls for missing-kind and non-object records,
carriage returns, invalid UTF-8 in an unterminated tail, and replay-tail repair;
root-alias swaps; complete valid output plus descendant-held pipes; and finite
cleanup failure preserving an existing exception, plus combined overflow and
cleanup failure selecting `DEGRADED`. A storage crash that persists
the newline but loses earlier bytes is complete corruption: refusal rather than
automatic repair is the accepted residual, preserving the evidence for recovery.

The original eight SL-0 files and every existing assertion remain untouched.
New tests must not introduce `outside_agent` node IDs into CONFORM's frozen
inventory. No missing historical data is regenerated under an old run identity.

### Documentation and recording (modify)

- `docs/phase-loop/convergence-runtime.md`: distinguish unterminated fragments
  from complete corruption, describe containment and real per-stream capture
  limits, and preserve the existing authority and ownership boundary.
- `CHANGELOG.md`: record the three corrected behaviors without claiming phase
  acceptance. `plans/manifest.json`: only this detailed plan's typed registration
  and lifecycle. Preserve original authoring events; each amendment records its
  previous/current digests through the supported typed registration upsert. The
  exact reviewed bytes and current amendment digest must agree, with an explicit
  native manifest-validation receipt in the review packet. After plan approval,
  the native `executing` transition records the actual approved digest. Do not
  invent a `committed` to `committed` transition or rewrite historical events.
  Publication recording may append the actual PR to the existing interim
  decision ledger if that policy remains in force; historical rows stay intact.

## Frozen protocol

`train_ledger.py`'s `ConvergenceResultStatus` vocabulary remains:
`completed`, `verified`, `blocked`, `needs_clarification`, `degraded`, `failed`.
`ConvergenceResultEnvelope(status, attempt_id, detail)` and the seven-field
`AdmissionRequest` remain unchanged. No new status, envelope field, broker verb,
advisory operation or authority is introduced.

## Dependencies and order

1. Obtain a fresh four-vendor plan review under the current governed policy.
2. Use the native bounded author workflow to add the two new regression files,
   run them against unchanged current source and retain actual RED outcomes and
   positive controls. Freeze their bytes before implementation; preserve all
   eight original test/support hashes throughout. Review the tests-first change
   under its applicable landing policy before the production author proceeds.
3. Repair only the two producer files; then run the native verification suite,
   applicable docs checks, and installed-wheel controls. Reconcile current main
   and ownership before mutation. The coordinator serializes this bounded author
   against any writer of these paths; no parallel fanout is required.
4. Obtain fresh source and final committed-head Panel reviews, preserve all
   evidence privately, use native publication, pass required CI and merge only
   when eligible. Install and qualify the merged package for subsequent work.
   Archive and independently verify ignored evidence before normal cleanup.

Item 4 of agent-harness#720 (transition-version integration) remains INTEG-owned.
Item 5 and `IF-0-RUNTIME-1` remain unaccepted until genuine historical evidence and
the required closeout checks pass. Comment on partial completion; do not close
the umbrella issue merely because these three bugs are fixed. This work does not
modify the original phase plan, roadmap, frozen tests, coordinator, broker,
publisher, Panel runtime or protected HARDEN trees.

## Verification

- `PHASE_LOOP_TDD_EXPECT_RUNTIME=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_runtime_event_log_hardening_720.py phase-loop-runtime/tests/test_runtime_adapter_output_720.py phase-loop-runtime/tests/test_convergence_event_log.py phase-loop-runtime/tests/test_convergence_adapters.py`
- `ruff check phase-loop-runtime/src/phase_loop_runtime/convergence/event_log.py phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/base.py phase-loop-runtime/tests/test_runtime_event_log_hardening_720.py phase-loop-runtime/tests/test_runtime_adapter_output_720.py`
- `git diff --exit-code 2f75797695ed58cbb0f8026b655d5068b23f2e88 -- phase-loop-runtime/tests/_runtime_tdd_guard.py phase-loop-runtime/tests/runtime_content_tdd_adapter.py phase-loop-runtime/tests/test_cli_train_status_45.py phase-loop-runtime/tests/test_convergence_adapters.py phase-loop-runtime/tests/test_convergence_event_log.py phase-loop-runtime/tests/test_convergence_reconcile.py phase-loop-runtime/tests/test_convergence_runtime_imports.py phase-loop-runtime/tests/test_convergence_status.py`
- `git diff --check`

The frontmatter suite adds the full focused RUNTIME inventory. Run through the
native verification writer with a qualified explicit interpreter, retained JUnit,
and a fresh fixture directory outside `.phase-loop` (the storage rejection is
intentional). Run the new and original event-log/adapter checks against a fresh
wheel installed in an owned environment with source PYTHONPATH absent; record
actual installed module identities and the supported interpreter controls used.
Required CI supplies the broader supported matrix. The original expensive
non-dotfiles result remains red history; do not relabel it using these checks.

## Acceptance criteria

- [ ] Complete malformed records are rejected without changing log bytes;
  unterminated-fragment recovery still works — new event-log tests and installed
  controls, plus unchanged original event-log tests.
- [ ] Traversal, symlink escape and resolved `.phase-loop` destinations cannot
  redirect reads/appends; normal selected storage works — new containment and
  deterministic path-swap tests, repeated against the installed package.
- [ ] Each captured stream stays bounded in bytes, overflow blocks and cleanup
  terminates owned processes without hanging — new actual-subprocess output and
  cleanup tests, repeated against the installed package.
- [ ] Existing protocol, focused RUNTIME behavior and frozen input bytes hold —
  frontmatter suite, frozen-inventory diff, lint and required CI.
- [ ] The repaired code and final landing receive fresh required reviews; retained
  evidence, installed-package identity and cleanup receipts are verified. The
  original phase receipt and INTEG obligations remain separately tracked.
