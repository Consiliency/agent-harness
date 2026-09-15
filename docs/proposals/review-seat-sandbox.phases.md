### Phase 14 — Review-Seat Executor Core (SBXEXEC)

**Objective**
Give review seats an execution capability that holds no mutation or credentialed side-effect
capability. It is a network-less, credential-less, per-call executor over content-addressed read-only
layers, as ruled in the agent-harness#848 consensus design.

**Exit criteria**
- [ ] EC-SBXEXEC-0 — **TEST LANE LANDED FIRST.** This phase's tests satisfy the v10 Execution Notes TDD-chronology gate literally. Falsified by an implementation commit predating the test landing, or a test diff inside the implementation PR.
- [ ] EC-SBXEXEC-1 — An executor call runs with no network namespace route, no inherited credential, environment variable, or host socket, and a fresh `/work` that does not persist. Falsified by any of these probes succeeding from inside a call: a TCP connect, a read of the invoking user's credential home, or a read of a previous call's `/work` file.
- [ ] EC-SBXEXEC-2 — The seccomp filter from agent-harness#848 Phase-0 gate 9 loads fail-closed. Falsified by `unshare -U` or `mount` succeeding inside a call, or by a missing or invalid filter blob still launching.
- [ ] EC-SBXEXEC-3 — Per-job and slice resource limits hold, and cancel or timeout leaves zero descendants (agent-harness#848 Phase-0 gate 12). Falsified by an adversarial job exceeding its memory or task limit outside the slice, or by a surviving descendant PID after cancel.
- [ ] EC-SBXEXEC-4 — A layer is bound only when its derivation key maps to a verified output-manifest digest; a conflicting output is quarantined, and bind-time verification fails closed. Falsified by a corrupted or conflicting layer being mounted into a call (agent-harness#848 Phase-0 gate 8).
- [ ] EC-SBXEXEC-5 — Execution is authorized only when the base-branch `.harden/execution.toml` hashes to the harness-held `recipes/<owner>/<repo>.pin.json`. The PR-head recipe is never read. Falsified by an unpinned or edited recipe producing anything other than `not runnable: recipe-unpinned`.
- [ ] EC-SBXEXEC-6 — Every non-success outcome carries exactly one class from the agent-harness#848 result taxonomy, and only `test-failed` can surface as a repository finding. Falsified by an infrastructure failure reaching a seat verdict as a finding.

**Scope notes**
Decompose into 2 lanes. Lane A owns the namespace launcher, seccomp, and limits. Lane B owns the layer
store, publisher, and recipe pin verification. Lane B publishes the layer-store interface
(IF-0-SBXEXEC-1) on day 1 so lane A can mount against it. `panel_invoker.py` is a single writer, so
the authorization hook that routes an authorized call to the executor lands last, in lane A.

**Non-goals**
Dependency fetching (SBXFETCH). Seat tool transport and activation (SBXSEAT). Ecosystems other than
Python/uv.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/review_sandbox/`
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/backing.py`
- `recipes/`
- `.harden/execution.toml`

**Depends on**
- HARDEN
- REVIEWTRUTH
- LEGLIFE

**Produces**
- IF-0-SBXEXEC-1 — layer-store interface: derivation key → verified output-manifest digest bind, lease, and quarantine operations
- IF-0-SBXEXEC-2 — executor call contract: request, result-taxonomy class, and journal record

### Phase 15 — Dependency Acquisition Pipeline (SBXFETCH)

**Objective**
Keep executor layers current with repository dependencies without giving any process both network
access and attacker-controlled code execution.

**Exit criteria**
- [ ] EC-SBXFETCH-0 — **TEST LANE LANDED FIRST.** This phase's tests satisfy the v10 Execution Notes TDD-chronology gate literally. Falsified by an implementation commit predating the test landing, or a test diff inside the implementation PR.
- [ ] EC-SBXFETCH-1 — The lockfile is parsed only inside a credential-less, network-less jail, and the parent admits only strictly validated `(url, sha256, size)` records. Falsified by any agent-harness#848 Phase-0 gate 7 hostile-lock fixture changing parent or shared-store state.
- [ ] EC-SBXFETCH-2 — The fetcher reaches the network only through the vetting CONNECT proxy. Falsified by any agent-harness#848 Phase-0 gate 1 forbidden destination connecting.
- [ ] EC-SBXFETCH-3 — The fetcher is not a resolver. Falsified by a trace showing any exec other than the fetch binary, or by an sdist-only fixture issuing a request (agent-harness#848 Phase-0 gate 2).
- [ ] EC-SBXFETCH-4 — Only the publisher admits artifacts, and prewarm uses the same pipeline. Falsified by a cache object whose admission record does not come from the publisher.
- [ ] EC-SBXFETCH-5 — From an empty cache, `phase-loop-runtime` fetches, provisions, installs editable with the recipe-pinned backend, and passes an offline subset that includes its entry-point test, while `ci/dagger` reports `generated-source-absent` (agent-harness#848 Phase-0 gate 10). Falsified by either outcome differing.

**Scope notes**
Decompose into 2 lanes. Lane A owns the parser jail and the fetcher with its proxy. Lane B owns
publisher admission, prewarm, and cache GC. Both lanes consume IF-0-SBXEXEC-1 and share no files.

**Non-goals**
Package-manager resolution, sdists, git, URL, or extra-index sources, and a runtime approval queue.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/review_sandbox/`

**Depends on**
- SBXEXEC

**Produces**
- (none)

### Phase 16 — Seat Tool Transport and Activation (SBXSEAT)

**Objective**
Let brokered review seats request executor calls through a strictly validated transport, and
activate execution per vendor only on passing evidence.

**Exit criteria**
- [ ] EC-SBXSEAT-0 — **TEST LANE LANDED FIRST.** This phase's tests satisfy the v10 Execution Notes TDD-chronology gate literally. Falsified by an implementation commit predating the test landing, or a test diff inside the implementation PR.
- [ ] EC-SBXSEAT-1 — Every executable seat path runs inside the outer CLI wrapper, which provides an isolated netns with provider-only egress and a per-run credential home that is never copied back. Falsified by a seat process reaching a non-provider destination, or by credential-home writes appearing in the host home.
- [ ] EC-SBXSEAT-2 — The text-request loop dispatcher rejects 100% of the agent-harness#848 Phase-0 gate 6 fuzz corpus with no authority change. Falsified by any corpus entry dispatching.
- [ ] EC-SBXSEAT-3 — A vendor's MCP transport is enabled only by a recorded pass of its agent-harness#848 Phase-0 gate (3, 4, or 5); otherwise that vendor stays on the loop or sealed. Falsified by a vendor dispatching over MCP without a recorded passing gate.
- [ ] EC-SBXSEAT-4 — A seat finding that quotes executor output is accepted only when the quoted span matches the journal. Falsified by a finding with a valid `call_id` but an altered quoted span being accepted.
- [ ] EC-SBXSEAT-5 — The full-suite execution class stays disabled until the agent-harness#848 Phase-0 gate 11 calibration is recorded. Falsified by a full-suite call being accepted with no calibration record.

**Scope notes**
Decompose into 2 lanes. Lane A owns the CLI wrapper and per-vendor activation. Lane B owns the loop
dispatcher, journal span validation, and suite-class calibration. `panel_invoker.py` is a single
writer, and lane A holds it. Share one per-call options object with agent-harness#648.

**Non-goals**
Promoting any vendor to MCP without its gate, and ecosystems other than Python/uv.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/review_sandbox/`
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py`
- `scripts/verify_harden_evidence.py`

**Depends on**
- SBXEXEC
- SBXFETCH

**Produces**
- (none)
