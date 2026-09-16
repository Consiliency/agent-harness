### Phase 14 — Review-Seat Executor Core (SBXEXEC)

**Objective**
Give review seats a per-call executor that satisfies EC-HARDEN-5 on its own new spawn path. It is
network-less, credential-less, and works over content-addressed read-only layers, as ruled in the
agent-harness#848 consensus design. The Phase-0 gates below are that design's numbered gates.

**Exit criteria**
- [ ] EC-SBXEXEC-0 — **TEST LANE LANDED FIRST.** This phase's tests satisfy the v10 Execution Notes TDD-chronology gate, in the content-bound receipt form of EC-GOVLEAN-2. Falsified by a frozen test whose merge-time bytes differ from its freeze-time receipt, or by absent RED output.
- [ ] EC-SBXEXEC-1 — An executor call runs with no network route and no inherited credential, environment variable, or host socket, and its `/work` does not persist. Falsified by any of these probes succeeding from inside a call:
  - a TCP connect;
  - a read of the invoking user's credential home;
  - reading a parent-set canary environment variable;
  - connecting to a host AF_UNIX socket;
  - reading a previous call's `/work` file.
- [ ] EC-SBXEXEC-2 — Seccomp is enforced fail-closed as ruled. Falsified by any check of agent-harness#848 Phase-0 gate 9 failing.
- [ ] EC-SBXEXEC-3 — Host protection and cleanup hold. Falsified by any check of agent-harness#848 Phase-0 gate 12 failing.
- [ ] EC-SBXEXEC-4 — Layers bind only through a verified derivation-key → output-manifest digest, with conflicting outputs quarantined, and admitted objects are immutable to review code. Falsified by any check of agent-harness#848 Phase-0 gate 8 failing.
- [ ] EC-SBXEXEC-5 — Execution is authorized only when the base-branch `.harden/execution.toml` hashes to the harness-held `recipes/<owner>/<repo>.pin.json`. The pin is read from the base revision or the installed harness, never from the reviewed tree. Falsified by either of:
  - an unpinned or edited base recipe producing anything other than `not runnable: recipe-unpinned`;
  - a change to the PR-head recipe or pin, alone, altering what executes.
- [ ] EC-SBXEXEC-6 — Every non-success outcome carries exactly one class from the agent-harness#848 result taxonomy, and only `test-failed` can surface as a repository finding. Falsified by either of:
  - an infrastructure failure reaching a seat verdict as a finding;
  - a non-success outcome carrying no class, or more than one.
- [ ] EC-SBXEXEC-7 — The executor spawn path, sandbox setup, and every fetch or layer effect are execution-capable paths under EC-HARDEN-5. Falsified by any EC-HARDEN-5 falsifier firing on such a path.

**Scope notes**
Decompose into 2 lanes:
- **Lane A** owns the namespace launcher, seccomp, and limits.
- **Lane B** owns the layer store, publisher, and recipe pin verification.

Lane B publishes the layer-store interface (IF-0-SBXEXEC-1) on day 1 so lane A can mount against it.
`panel_invoker.py` has a single writer, so the authorization hook that routes an authorized call to
the executor lands last, in lane A.

Gate 9's positive control ("the real test subset passes") must pass at this phase's closeout, before
the fetch and publish pipeline that EC-SBXFETCH-4 later requires exists. This phase's detailed plan
names the test subset and the fixture layer that satisfy it.

**Non-goals**
- Dependency fetching (SBXFETCH).
- Seat tool transport and activation (SBXSEAT).
- Ecosystems other than Python/uv.

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
- IF-0-SBXEXEC-1 — layer-store interface: bind derivation key → verified output-manifest digest, lease, and quarantine operations
- IF-0-SBXEXEC-2 — executor call contract: request, result-taxonomy class, and journal record

### Phase 15 — Dependency Acquisition Pipeline (SBXFETCH)

**Objective**
Keep executor layers current with repository dependencies. No process may hold both network access
and attacker-controlled code execution.

**Exit criteria**
- [ ] EC-SBXFETCH-0 — **TEST LANE LANDED FIRST.** This phase's tests satisfy the v10 Execution Notes TDD-chronology gate, in the content-bound receipt form of EC-GOVLEAN-2. Falsified by a frozen test whose merge-time bytes differ from its freeze-time receipt, or by absent RED output.
- [ ] EC-SBXFETCH-1 — Lockfiles are parsed only in a credential-less, network-less jail. The parent admits only strictly validated `(url, sha256, size)` records whose origin is a recipe origin within the harness allowlist. Hostile wheels leave the parent and the shared store unchanged. Falsified by either of:
  - any check of agent-harness#848 Phase-0 gate 7 failing, for hostile locks or hostile wheels;
  - a record from a non-allowlisted origin being admitted.
- [ ] EC-SBXFETCH-2 — The fetcher reaches the network only through the vetting CONNECT proxy. Falsified by any check of agent-harness#848 Phase-0 gate 1 failing.
- [ ] EC-SBXFETCH-3 — The fetcher is not a resolver. Falsified by any check of agent-harness#848 Phase-0 gate 2 failing.
- [ ] EC-SBXFETCH-4 — Only the fetch → publish pipeline admits artifacts. Prewarm uses that same pipeline, and policy is rechecked on every cache hit. Falsified by any of:
  - an object admitted through any other path, prewarm included;
  - a cache hit served after its source policy no longer allows it.
- [ ] EC-SBXFETCH-5 — Cold-cache coverage holds. Falsified by any check of agent-harness#848 Phase-0 gate 10 failing.
- [ ] EC-SBXFETCH-6 — The shared layer is built offline with `--no-build --require-hashes` in an executor-class sandbox without the snapshot. The built environment is never started for inspection, and validation and compilation use an independent pinned `-I -S` interpreter. The per-call editable install uses the recipe-pinned, hash-admitted build backend, ignores the PR's `[build-system].requires`, and keeps outputs inside `/work`. Falsified by any of:
  - a `.pth` or console-script sentinel in an admitted wheel executing during build or validation;
  - a PR-declared build requirement being installed, or any build backend outside the pin's admitted set running;
  - the PR snapshot being readable from the shared-layer build;
  - an install output appearing outside `/work`.
- [ ] EC-SBXFETCH-7 — Cache GC evicts only unleased objects, keeps every leased graph complete, and refuses admission below the free-space floor. Falsified by either of:
  - an object in an active lease being evicted;
  - an admission succeeding below the floor.

**Scope notes**
Decompose into 2 lanes:
- **Lane A** owns the parser jail and the fetcher with its proxy.
- **Lane B** owns publisher admission, the shared-layer build, prewarm, and cache GC.

Both lanes consume IF-0-SBXEXEC-1 and share no files.

**Non-goals**
- Package-manager resolution.
- sdist, git, URL, and extra-index sources.
- A runtime approval queue.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/review_sandbox/`

**Depends on**
- SBXEXEC

**Produces**
- (none)

### Phase 16 — Seat Tool Transport and Activation (SBXSEAT)

**Objective**
Let brokered review seats request executor calls through a strictly validated transport. Activate
execution per vendor only on passing evidence.

**Exit criteria**
- [ ] EC-SBXSEAT-0 — **TEST LANE LANDED FIRST.** This phase's tests satisfy the v10 Execution Notes TDD-chronology gate, in the content-bound receipt form of EC-GOVLEAN-2. Falsified by a frozen test whose merge-time bytes differ from its freeze-time receipt, or by absent RED output.
- [ ] EC-SBXSEAT-1 — Every executable seat path runs inside the outer CLI wrapper, with an isolated netns and provider-only egress. It has no live tree, no `/run`, and no docker socket. Its per-run credential home is never copied back. A vendor that cannot authenticate through the wrapper stays sealed. Falsified by any of:
  - a seat process reaching a non-provider destination, the live tree, `/run`, or a docker socket;
  - credential-home writes appearing in the host home;
  - a vendor that fails wrapper authentication gaining an executable path.
- [ ] EC-SBXSEAT-2 — The text-request loop dispatcher is strict. Falsified by any check of agent-harness#848 Phase-0 gate 6 failing.
- [ ] EC-SBXSEAT-3 — A vendor's MCP transport is enabled only by a recorded pass of its agent-harness#848 Phase-0 gate (3, 4, or 5); otherwise that vendor stays on the loop or sealed. The record is content-bound to the built code in the EC-GOVLEAN-2 form. Falsified by either of:
  - a vendor dispatching over MCP without a recorded passing gate;
  - a record binding to code other than what runs.
- [ ] EC-SBXSEAT-4 — Evidence follows the agent-harness#848 evidence ruling. A finding that quotes executor output is accepted only when the quoted span matches the journal. An unexecuted runtime claim is capped below DISAGREE. Falsified by either of:
  - a finding with a valid `call_id` but an altered quoted span being accepted;
  - an unexecuted runtime claim reaching DISAGREE.
- [ ] EC-SBXSEAT-5 — The full-suite execution class stays disabled until a passing gate-11 calibration is recorded. Falsified by either of:
  - any check of agent-harness#848 Phase-0 gate 11 failing while the class is enabled;
  - a full-suite call being accepted with no passing calibration record, or with a record not content-bound to the built code in the EC-GOVLEAN-2 form.
- [ ] EC-SBXSEAT-6 — No seat gains an executable path while EC-HARDEN-5 is UNMET. Falsified by an executable seat path being enabled while EC-HARDEN-5's recorded state is anything other than MET, an absent record included.

**Scope notes**
Decompose into 2 lanes:
- **Lane A** owns the CLI wrapper and per-vendor activation.
- **Lane B** owns the loop dispatcher, journal span validation, and suite-class calibration.

`panel_invoker.py` has a single writer, and lane A holds it. Share one per-call options object with
agent-harness#648.

**Non-goals**
- Promoting any vendor to MCP without its gate.
- Ecosystems other than Python/uv.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/review_sandbox/`
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py`
- `phase-loop-runtime/scripts/verify_harden_evidence.py`

**Depends on**
- SBXEXEC
- SBXFETCH

**Produces**
- (none)
