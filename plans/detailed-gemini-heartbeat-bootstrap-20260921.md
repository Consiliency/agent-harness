---
type: detailed
status: planned
owner_skill: codex-plan-detailed
input_base_commit: dc47379d6ebc51f7dc2b2536a930be7271d4b4df
related_issues: [agent-harness#905, agent-harness#892, agent-harness#908]
automation:
  suite_command: "PYTHONPATH=phase-loop-runtime/src .venv/bin/python -m pytest -q phase-loop-runtime/tests/test_gemini_heartbeat_bootstrap.py phase-loop-runtime/tests/test_review_monitor_policy.py phase-loop-runtime/tests/test_leg_liveness_monitor.py phase-loop-runtime/tests/test_panel_tui_liveness_188.py phase-loop-runtime/tests/test_panel_invoker_timeout_argv.py phase-loop-runtime/tests/test_advisor_board_cli_legacy.py phase-loop-runtime/tests/test_advisor_board_backcompat.py phase-loop-runtime/tests/test_harden_evidence_verifier.py phase-loop-runtime/tests/test_skill_liveness_contract.py phase-loop-runtime/tests/test_skills_canon_parity.py phase-loop-runtime/tests/test_the_real_launch_carries_the_prefix.py phase-loop-runtime/tests/test_broker_command_builders.py phase-loop-runtime/tests/test_broker_staged_tree_delivery.py phase-loop-runtime/tests/test_egress_prefix_crosses_the_broker_thread.py"
  verification_status: not_run
  human_required: false
---

# Detailed plan: qualify brokered Gemini heartbeat-only reviews

## Task and authority

Complete the separate Gemini route repair needed to resume the v10 HARDEN board.
On 2026-09-21 the operator answered the scoped bootstrap question: **"Proceed
without the fourth panel member."** For this repair's plan, tests and source,
require converged Codex, Claude subscription TUI and Grok reviews, explicitly
recording Gemini absent. This changes the review process, not the requirement to
fix substantive findings. HARDEN's own four-vendor gate is unchanged. No merge,
release, deployment, reviewer substitution or general reduced-vendor policy is
authorized by that sentence.

The initial diagnostic board returned three PARTIALLY AGREE verdicts. This plan
replaces the proposal and incorporates their findings. Execution remains ordered:
plan review, RED tests review, implementation, qualification and final review.
No runtime source has been changed while preparing this plan.

## Research summary and inputs

Main correctly refuses Gemini under heartbeat-only. Its brokered Gemini branch
has a native print timeout, a second-attempt loop, no operation-monitor propagation
and a host temporary HOME. Stream rejection detail is lost at the parent/broker
boundary (agent-harness#905). Merely admitting the route would be incorrect.

Measured candidate `agy` input SHA256:
`9991515b6d5307bcf701069622b0537b6b206e605f3c891c0cf3a3d208dea8b0`.
Its help SHA256 is
`5a03bf7dc9d3d7645f5853906cc117363fd8978a79c2a89521f0ff7590dbe454`;
help explicitly documents print timeout zero as waiting for completion. This is
a capability lead, not live qualification or a proof of arbitrarily long waits.

A synthetic probe on this host established that `bwrap --dev /dev` can hold a
private `/dev/phase-loop-agy` HOME and read-only executable/settings copied from
sealed memfds using `--ro-bind-data`. Killing its owner killed a detached child,
left no host HOME, and preserved a synthetic OAuth target after both in-place
refresh and replacement of the private symlink. Descriptors were absent in the
executed child. `--ro-bind-fd` failed on this host and is not selected. The uv
Python 3.13 build lacks `os.memfd_create`; the system Python 3.10 supports it.
Use the existing `_linux_memfd_seal_abi` / `_sealed_tree_fd` helpers and fail
preflight on an unsupported Python/kernel. Do not add a libc fallback.

Private input evidence is in
`/mnt/workspace/archives/agent-harness-v10-continuation-20260921/`:
`BOOTSTRAP-DECISION.md`, `BOOTSTRAP-AUTHORIZATION.md`,
`GEMINI-CAPABILITY-OBSERVATION.json`, `agy-help.txt`,
`GEMINI-NAMESPACE-PROBE.json`, `probe_gemini_namespace.py`,
`GEMINI-NAMESPACE-EGRESS-PROBE.json`, `probe_gemini_namespace_egress.py`,
`GEMINI-NAMESPACE-HANDSHAKE-PROBE.json`, `probe_gemini_namespace_handshake.py`,
`REVIEW-DISPOSITION.md`, `gemini-diagnostic-r1/{codex,claude,grok}.{json,md}`
and `gemini-plan-r*/{request.json,bundle.md,brief.md,reviewed-plan.md,reviews/**}`.
These exact paths are the execution read allowlist; they contain no credentials.
Task-created verification and qualification output is allowed under this
worktree's `.phase-loop/gemini-heartbeat-bootstrap-20260921/**`.
The synthetic probe is design evidence only. Review packets include complete
relevant functions, particularly monitor pre-cancellation, CLI preflight, argv
grammar, stream parsing and the parent/broker result consumer.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/gemini_heartbeat.py` (create)

- Provide the internal Linux capability/profile helper. Resolve `agy` from the
  actual scrubbed subscription environment; hash its regular executable bytes
  and admit only the measured candidate digest. Require sealed-memfd and pidfd
  support. Map capability-helper `AgyCanaryEvidenceError` to a fixed ValueError
  diagnostic so all public preflight boundaries produce UNAVAILABLE with existing
  monitoring `terminal_reason=policy_refusal`.
  Missing/changed capability is a fixed UNAVAILABLE diagnostic. No help-text
  fallback, environment override or alternative CLI inference path.
- After broker authorization, snapshot the executable into a sealed memfd,
  hash the copied bytes again, and reject a mismatch before launch. Build a second
  sealed fd for the same deny-all settings as the bounded route. Reuse existing
  sealing helpers; copy/write failures close all owned fds. The later launch uses
  only `/dev/phase-loop-agy/agy`, preventing PATH or in-place update races.
- Return a scoped profile containing scrubbed env, extra bwrap mount arguments
  and owned fds. After the existing `--dev /dev`, create private mode-0700 HOME,
  `.gemini/antigravity-cli` and `.config`; mount the executable mode-0500 and
  settings mode-0400 with `--ro-bind-data`; create only a private symlink to the
  existing subscription token. Set HOME and XDG_CONFIG_HOME there. Never read,
  copy, log, remove or restore the actual credential. Preserve legitimate
  refresh writes; symlink replacement stays private and is discarded.
- The mount/PID namespace, not a host TemporaryDirectory finally block, owns
  profile residue. Close parent fds after reaping; SIGKILL closes them in-kernel.
  No new daemon, janitor, service, persistent executable copy or host profile
  directory. Keep `/dev` random/terminal nodes. Providers may spawn helpers, all
  owned by the existing PID namespace. Account for those helpers in qualification.
- Bind teardown to the PID namespace, not just its process group. Add private
  `--info-fd` and `--block-fd` pipes to bwrap. Before releasing the execution gate,
  read the trusted child PID, retain its pidfd and PID-namespace fd, and record its
  start identity and namespace device/inode. This has a finite local admission
  bound; no provider can begin thinking until the gate is released. Failure or
  cancellation before release terminates the blocked wrapper and closes every
  fd. The existing provider latch still owns the launch; an exception between
  creation and registration must also reap the created process.
- After the normal group termination/reap, require the held init pidfd to report
  exit and the held PID namespace to have no live members, using the existing
  finite cleanup grace. Retaining the namespace fd prevents identity reuse while
  checking. A live detached member or unprovable observation fails quiescence;
  do not report cleanup from leader exit alone. Close the namespace fd after
  verification; never retain a mount-namespace fd that would itself hold the HOME.
  Synthetic handshake plus egress evidence confirms this mechanism on the host.

### `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` (modify)

- Add a shared Gemini capability preflight called by `invoke_board` immediately
  after pure policy resolution and before availability/auth/staging/provider
  effects, only when a requested seat uses Gemini under heartbeat-only. Other
  supported boards do not require agy or memfd. Recheck independently in
  `_default_spawn`, including the actual env. At the input base `_LEG_AUTH_PROBE`
  contains only Codex, so `_leg_auth_ok` does not launch agy; preserve that fact.
  A capability failure refuses the whole requested board; never drop a seat.
- `_brokered_gemini_command` gains an explicit internal policy argument. The
  heartbeat form is `[<sealed-image>, --model, <authorized-model>, --sandbox,
  --mode, plan, --disable-slash-commands, --input-format, stream-json,
  --output-format, stream-json, --print=, --print-timeout, 0]`, with no `--add-dir`
  or dangerous permissions. Bounded deadlines must be finite and strictly
  positive; otherwise fail before rendering. Existing valid bounded argv stays
  unchanged. Prompt, argv and no-tool evidence all withhold tool/tree access on
  the heartbeat route, even when staging happened.
- `_exec_leg` independently enforces the coupled brokered-only route: authorized
  model, monitor present, zero token, immutable qualified image, no capture or
  research. Propagate `review_monitor` to `_run_leg_with_liveness`. Gate the
  heartbeat attempt count to one before any soft-failure/retry classification;
  pre-cancel yields zero launches. Bounded retry behavior remains as before.
- Extend the private `_ReviewMonitor.owned_command` and print runner with
  optional profile mount arguments/pass_fds, admitted only with a monitor.
  Insert profile mounts after `--dev /dev` and before the owner wrapper's `--`.
  `launch_provider` still composes the egress prefix and owner namespace before
  capability drop. No new subprocess site or launch-site allowlist change.
- Preserve actual sandbox facts and staged-tree/authorization revalidation before
  egress acquisition. `EgressUnavailable` remains DEGRADED with its exception
  text. The kernel-owned profile gets its own truthful isolation profile identity;
  do not label it as the old host-temp-HOME implementation. Cleanup is recorded
  true only after verified provider namespace/process quiescence and fd closure,
  not merely because the private path was never visible on the host. Failed
  teardown cannot return a usable vote.
- For brokered Gemini, classify each rejection with fixed messages: malformed
  JSON/event, tool/subagent activity, conversation mismatch, result-count/ack
  mismatch, invalid final result, truncation, native exit, explicit cancellation
  and accepted-empty. No arbitrary exception/stdout/stderr interpolation. Keep
  existing stream outcome vocabulary; retain specific detail separately. A
  nonzero native exit with partial NDJSON never becomes review prose or success.
  Preserve bounded stall classification using the original raw stream before
  discarding it as review prose. The accepted-empty tool-denial path must not
  retain its old stderr interpolation. Give native timeout-under-zero a distinct
  fixed diagnostic so qualification can invalidate it mechanically.
- `_parent_infer` stores the validated fixed detail in its per-operation closure
  and returns only status/text over the frozen wire. After join/cleanup, attach
  that detail to `_BrokeredSpawnResult` and retained/streamed `PanelLegResult`.
  Attach a detail only when consistent with the wire's non-OK status, never OK.
  Both cancellation forms are covered. An empty accepted stream remains a
  non-vote and is distinguishable from rejected ingestion.

### `phase-loop-runtime/src/phase_loop_runtime/advisor_board/backing.py` and `cli.py` (modify)

- Permit the logical brokered subscription Gemini route in the pure resolver;
  retain every other unsupported route, native-fill, API and fallback guard.
  Keep the resolver free of environment/filesystem probes.
- The CLI applies the same separate capability check before composition/auth
  effects. A requested heartbeat board keeps its declared vendor membership;
  do not use availability backfill to turn a refusal into another board.
- No broker protocol or status changes. At the input base, backing.py lines
  179–181 declare `{"OK", "EMPTY", "TIMEOUT", "ERROR", "DEGRADED", "UNAVAILABLE"`.
  The response remains exactly schema/status/text. Existing `review_monitoring.v1`
  and authorization evidence retain their vocabulary: null model/silence/operation
  deadlines and finite, single-use admission with admission-only expiry.

### Tests (create/modify; tests-first)

Create `phase-loop-runtime/tests/test_gemini_heartbeat_bootstrap.py` for focused
behavioral and Linux lifecycle controls. Modify the existing Gemini-refusal cases
in `test_review_monitor_policy.py` to check unsupported capability instead of
unconditional unsupported route. After qualification, update the heartbeat
claims in `test_skill_liveness_contract.py` alongside the canonical skills.
Add builder/timeout coverage in
`test_broker_command_builders.py` and `test_panel_invoker_timeout_argv.py` only
where those existing fixtures are the appropriate boundary. Keep frozen HARDEN
tests unchanged. New tests initially fail on the input base for intended reasons;
retain raw RED node IDs and output, review the tests before production edits.

Required controls:

1. Public board/CLI fail before auth, composition, artifact reads or launches for
   unknown image, missing memfd, wrong route and policy mismatch. Pure resolver
   remains pure. Direct spawn cannot bypass capability checks. Executable
   replacement or modification between checks cannot alter the launched image.
   Missing Gemini capabilities leave bounded boards and Gemini-less heartbeat
   boards unaffected. Import the new module inside test bodies so RED is per-node.
2. Exact zero only under the authorized heartbeat route; reject zero/negative/
   NaN/infinity under bounded policy. Final argv, prompt and evidence agree on
   no tools/no tree. All launch/prefix/thread and egress-order regressions pass.
3. One attempt for accepted-empty, native failure, malformed/rejected stream and
   cancellation. Pre-cancel launches zero. Advanced observation clocks across
   old deadlines cannot kill a live silent fixture; cleanup clocks remain real.
4. Real broker + synthetic provider completion/cancel/abrupt owner loss, including
   detached descendants. Exercise sealed executable mutation, mount identity,
   closed inherited fds, immutable settings, random device access, private profile
   residue and synthetic credential in-place/replacement refresh. Enumerate live
   namespace users and retain identities, not just the process group leader.
5. Producer-to-retained-JSON failure diagnostics with empty review text and unchanged
   wire; malformed JSON, tools, session/reset, ack/count/final/truncation failures,
   nonzero exit with partial NDJSON, accepted-empty and both cancellation forms.
6. Negative controls kill finite-print-timeout, dropped-monitor, retry-enabled,
   dropped-detail, interpolated-detail and ingestion-check-removed mutants. Unknown/corrupt profile or
   swapped monitoring/argv/receipt identities fail qualification validation.

### Qualification runner and validator (create)

Add `phase-loop-runtime/scripts/qualify_gemini_heartbeat.py`, a diagnostic driver
of the real `invoke_board` path and receipt validator, not a provider adapter.
It supports offline validation plus separately selected completion, cancel and
owner-loss operations. It never invokes `agy` directly or patches production
functions. It binds exact runtime source hashes, profile/image/help hashes,
actual argv/input digests, operation identity, runtime monitoring and broker
record digests into a separate qualification envelope. Cross-check the records;
never accept an envelope solely because its own hashes agree.

Completion requires one OK terminal review, same-session chunk acknowledgements,
no truncation and verified cleanup. Cancellation/owner-loss instead require their
expected outcome and independently observed local process/mount/fd cleanup;
they never substitute for completion. The owner-loss observer is the external
qualification driver, which survives the killed invocation process. Each observed
  PID includes start identity to exclude reuse. A descendant executing agy bytes
  other than the pinned image invalidates qualification; inspect executable
identity rather than trusting its process name. Report only local quiescence, never
provider billing settlement. No real credential payload or raw private profile
is retained. A modern receipt remains intentionally ineligible for the historical
bounded-success `verify_broker`; do not modify that verifier or its frozen tests.

The qualifier registers helper image hashes before an operation (bwrap/setpriv
by default; explicitly supplied additional helper images remain separate inputs).
Sample executable identities repeatedly, record observed transitions, and reject
unregistered images or a changed entry image. This is sampled process evidence,
not a complete kernel exec audit or a claim that the entry pin covers helpers.
Observe the pinned init's full descendant tree, including nested PID namespaces.
Retain fixed failure reasons, stages and observed/rejected helper image metadata
without credential contents; cleanup failures must not overwrite the first cause.
Cross-check namespace PID/start/device/inode and admission expiry between the
broker, monitor and observer. Observe owned fd tables and accessible mount
namespace users after teardown, recording unreadable foreign entries separately.
Observe credential-target regular-file presence before and after without reading
its contents or requiring identity/content equality across legitimate refreshes.
Directory validation binds retained input bytes and admission observations and
accounts for every preregistration, including missing or failed attempts; it
returns success only for all three distinct operations. Publish a success receipt
only after validation and observer cleanup. These are the source-board round-one
evidence corrections, not substitutes for real qualification.
Also bind terminal runtime records and admission policy/expiry to the envelopes;
owner loss must not fabricate a terminal record. Pin the package's Python source
tree, require a nonempty checked network policy, and trigger real cancellation on
observed output progress after admission. The accessible namespace scan is
corroboration; held namespace-init exit is the cleanup proof for nested members.

The owner-loss record set is deliberately different: the killed process cannot
emit its terminal broker receipt. The external driver retains the observed
argv/image/helper/mount identities, held namespace/init identities, the last
non-terminal monitoring snapshot, the explicit kill event and subsequent empty
namespace/closed-fd observations. Require that set and reject a terminal OK or a
fabricated postmortem broker receipt. Completion and cancellation require their
actual terminal runtime/broker records. All three envelopes bind measured
`sandbox_network_filtered` facts. The executable pin covers the entry image;
helper identities are measured and recorded, not falsely covered by that pin.

## Documentation impact

Update `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`,
`docs/advisor-board-capabilities-card.md`, the four
`skills-src/{codex,claude,gemini,opencode}/*-advisor-board/SKILL.md` sources and
generated bundled copies using the existing regeneration script. Document the
digest/Python capability requirement, zero semantics, one attempt, fixed failure
details and default-board refusal on unknown capability. Preserve the historical
scope of agent-harness#892. Add an Unreleased changelog entry after successful
qualification. Register this plan through the existing manifest helper and add
the interim ratification ledger row before a plan/production landing. Never
rewrite the RUNTIME grounding record or existing authority rows.

## Dependencies & order

1. Review this final plan and the synthetic probe with Codex/Claude TUI/Grok on
   unchanged merged main, under heartbeat-only; require all three AGREE. Diagnostic
   round one is retained. Maximum three substantive plan rounds; a surviving
   blocker must be resolved or its scope deferred, never waived. Do not cancel
   another seat when one reports a finding.
2. Implement and run RED tests, review that exact tests artifact with the same
   three vendors; commit test-first evidence separately before source changes.
3. Implement the coupled route as one unmerged candidate, run the plan automation,
   mutations and complete suite, then qualify the real route. Do not publish a
   partial state that merely changes the resolver to supported.
4. Pre-register **one completion, one cancellation and one owner-loss operation**,
   at most one inference attempt each. Trigger cancellation/owner loss on observed
   provider admission/output, never elapsed thinking time. Observe actual mounts,
   image and helpers without collecting credentials. No API/gateway/native-fill
   route, retry, fallback, process monkeypatch or bounded-thinking timer. A failed
   attempt halts qualification, remains retained, and requires a diagnosed change
   before another attempt; do not select a pass from repeated unchanged runs.
5. A quick real completion proves compatibility, not unbounded duration: the
   latter claim rests on documented CLI zero semantics plus runtime and offline
   clock controls. A native timeout under zero invalidates this candidate profile.
6. Final exact-candidate three-vendor review and CI, draft PR against main with
   route/policy matrix and cleanup evidence, explicitly recording the exception.
   No merge in this task. Only after this route is accepted may a fresh complete
   four-vendor board review HARDEN; no existing vote is transferred to that draft.

## Verification

Use a worktree-local `.venv` created with `/usr/bin/python3` on this host; install
the runtime and its declared test group. Verify Python supports memfd first.
The package admits Python >=3.10. Later four-vendor boards must also run with a
memfd/pidfd-capable interpreter; qualifying once does not repair another install.
Run the frontmatter `automation.suite_command`, then:

```sh
PYTHONPATH=phase-loop-runtime/src .venv/bin/python -m pytest -q phase-loop-runtime/tests
git diff --check
```

The qualification driver exposes `--validate <receipt-directory>` and
`--operation completion|cancel|owner-loss --output <new-private-directory>`.
Run the operations sequentially only after offline controls pass; run the
validator over their retained receipts. Record commands, exact source digests,
all terminal outcomes and failures. Baseline-matching failures are not green;
never label fixtures as real model acceptance. The plan's machine checks plus
the runner-stamped qualification envelope are its evidence contract; there is
no proxy substitution for any of the three real operations.

## Acceptance criteria

- [ ] G1: Qualified route makes at most one inference attempt without a
  model/silence deadline; pre-cancellation launches no provider and unsupported
  capability/route refuses before effects — suite command
  and `qualify_gemini_heartbeat.py --validate`.
- [ ] G2: Cancellation and owner loss reclaim provider helpers, mounts, profile
  and immutable executable, preserving credential targets — lifecycle tests and
  all three real qualification receipts validated by the driver.
- [ ] G3: Failures preserve fixed diagnostic meaning through retained results,
  cannot become review votes and cannot change the broker wire — suite command
  and diagnostic/ingestion negative controls.
- [ ] G4: Existing provider launch, prefix, egress, authorization, truthful facts,
  bounded compatibility and frozen HARDEN contracts hold — automation, full suite
  and `git diff --check`; report any baseline or environment failures explicitly.
- [ ] G5: Three-vendor approval binds the final actual artifact under the recorded
  operator exception; docs and PR match its measured scope. HARDEN, native host
  cells, services, deployments and release tags remain outside this repair.
