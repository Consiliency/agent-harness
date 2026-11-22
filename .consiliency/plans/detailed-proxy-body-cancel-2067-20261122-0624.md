# Detailed plan: refused body-declaring requests must not crash the egress proxy (agent-harness#2067)

## Task

On Node 22, the seat egress proxy exits 1 when it refuses a GET, HEAD or OPTIONS request
that declares a body (`Content-Length` or `Transfer-Encoding`). Fix it so that no refusal of a
body-declaring request, whatever its method, can end the proxy through a cancel after the
refusal. No allow or refuse decision may change, and nor may the allowlists, the named sets
or the jail profiles. Plan the pin movement and requalification, and sequence the fix against
in-flight work.

## Research summary

- **Mechanism (read in srt).** srt 0.0.79 `request-filter.js` `decideAndRespond` tees
  whenever `!bodylessMethod || declaresBody`, but gives a GET, HEAD or OPTIONS callback a
  bodyless `Request`. The agent-harness#2033 drain in `refuseRequest` sees `request.body ===
  null`, and srt then cancels the unread branch.
- **Why only Node 22.** Node 24.22.3's `newReadableStreamFromStreamReadable` (read via
  `--expose-internals`) skips close and enqueue once `wasCanceled` is set. Node 22.12.0, the
  BA-3 job's version (`test.yml` `grok-egress-ns`), lacks that guard [inferred from the
  `proxy.mjs` comment and the CI report].
- **Probe (Node 24.22.3, scratch under `$HOME`).** The adapter calls `close` and `enqueue`
  through `ReadableStreamDefaultController.prototype`. On a cancelled controller either throws
  `ERR_INVALID_STATE` "Controller is already closed", the error `proxy.mjs` names.
- **Hosts.** The dev host has only Node 24. `NODE_MIN_VERSION` is `(22, 12, 0)`, so
  production hosts may run Node 22.
- **Tests to reuse.** `tests/test_grok_measure_egress.py`, which BA-3 runs, has the
  `_FAKE_SRT` stand-in (node only) and `real_proxy_upstream` (pinned srt, loopback upstream),
  plus agent-harness#2033's body test. agent-harness#2064 sent bodies only with POST to avoid
  the trigger; those tests stay as they are.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/seat_egress/proxy.mjs` (modify)

- **Cancelled-controller guard — add.** Place it before `await import(process.argv[2])`.
  - It wraps `ReadableStreamDefaultController.prototype.close` and `.enqueue`.
  - A call that throws a `TypeError` with `code === 'ERR_INVALID_STATE'` and a message
    matching `/Controller is already closed/` returns `undefined`. Every other error is
    rethrown unchanged.
  - The byte-stream controller is not wrapped, because srt's `Readable.toWeb(shim)` passes no
    `type`.
  - Reason: it reproduces Node 24's `wasCanceled` behaviour, so no cancel after a refusal
    can throw, for any method or past the drain's bounds. It acts only after decisions, and
    any chunk it drops was already undeliverable.
- **Guard self-test — add.** It runs after the guard is installed and before the ready line.
  It creates a `ReadableStream`, awaits its `cancel()`, then calls `close()` and
  `enqueue(new Uint8Array(1))` on its controller. If either throws, it writes `stream cancel
  guard is not in force` to stderr and exits 3, like the inner-SNI self-test, which
  `start_proxy` maps to `START_FAILED_CODE`.
- **The `refuseRequest` comment — modify.** One sentence: a body-declaring GET, HEAD or
  OPTIONS reaches the filter bodyless, and the guard covers it. No other code changes.

### `phase-loop-runtime/tests/test_grok_measure_egress.py` (modify)

- **`_FAKE_SRT` — modify.** A request entry may carry `"declared_body": true`. The stand-in
  then builds a `ReadableStream` whose source keeps its controller with no cancel guard, like
  the Node 22 adapter. After the filter denies, it awaits `stream.cancel()` and schedules
  `controller.close()` in a `setImmediate`. Before the fix, that throws an uncaught exception
  on any Node version. This is the deterministic red-first test.
- **`test_a_cancel_after_a_refused_declared_body_leaves_the_proxy_running` — add.** It runs on
  the fake srt and covers GET, HEAD and OPTIONS, each with `declared_body`, refused by
  `rules`. It asserts the verdicts are `deny`, `seat_egress_proxy.completion(proxy).complete`,
  exit status 0 in `completion_detail` and the expected `outside_events` causes.
- **`test_a_refused_bodyless_method_that_declares_a_body_leaves_the_real_proxy_running` —
  add.** It uses `real_proxy_upstream` and the Node 22 crash shape: GET, HEAD and OPTIONS,
  each sent twice, once with `Content-Length: 2` and a `{}` body and once with
  `Transfer-Encoding: chunked` (`2\r\n{}\r\n0\r\n\r\n`).
  - Each is refused by `rules`. GET is also refused by `budget` (`request_budget=0`) and
    `inner_host` (Host `auth.x.ai`).
  - It asserts each status line is `HTTP/1.1 403`, `upstream.requests == []`, the completion
    is complete with `requests` equal to the number sent, and the `(method, host, path,
    decision)` and `cause` of each event are as expected.
  - It is red on BA-3 (Node 22.12.0) before the fix, and it is the Node 24 control on the dev
    host.
- **`test_the_cancel_guard_rethrows_other_errors` — add.** A node child runs the guard
  prelude, cut from `proxy.mjs` at a marker comment. An `enqueue` whose `size()` throws still
  throws, and `close` on an open stream closes it.
- **`test_a_proxy_without_the_cancel_guard_does_not_start` — add.** It follows the
  `unattested-proxy.mjs` pattern: a copy with the guard installation removed. On the fake
  srt, `start_proxy` raises `EgressLayerUnavailable` with `START_FAILED_CODE`. Any Node
  version shows this.

### `CHANGELOG.md` (modify)

- **A Fixed entry — add.** Unreleased. It gives the failure, the fix and a **Pins** line,
  following the table below in the agent-harness#2033 entry's style. Values are not
  recorded.

## Documentation impact

- `CHANGELOG.md`: as above.
- `docs/releases/outside-agent-release-handoff.md` already covers the `proxy_sha256` move.
- **Frozen protocol.** `plans/seats-firstseat-containment-contract.md` section 14 (around
  lines 409–426) holds that a fence "never … changes a decision or its reason … or alters the
  readiness line". Its regressions list keeps "the readiness line's keys and values" and
  "every decision and reason of the existing request matrix".
- **No new vocabulary.** The fix adds no stdout line, ready key, event field, `cause`, exit
  code or stdin form. The new stderr text is not protocol, because `start_proxy` sends stderr
  to `DEVNULL`.

## Pin movement

| Pin | Moves? | Why |
|---|---|---|
| `proxy_sha256` (`seat_jail_qualification._PROXY_IMPLEMENTATION_SHA256`) | **yes** | It hashes `seat_egress_proxy.py` and `proxy.mjs` bytes |
| `seat_window.runtime_digest()` and window `qualification_keys` | **yes** | It hashes `seat_egress/*` |
| `seat_window.release_identity()` | **yes** | It hashes the same files, less `seat_window_grants.py` |
| `ROW_GRANTS`, `OWNER_W1_GRANT_SHA256` and `OWNER_W1_PACKET_SHA256` | no in-repo edit | They are empty or `None` at this base. A grant packet drafted elsewhere against the old `release_identity` is stale |
| agy QCI (`agy_qualification.seat_qci` / `agy_profile_digest`) | no | It covers the profile description and operations only |
| Claude SDK proof (`sdk_proof_inputs_sha256`) | no | `proxy.mjs` is in no `SDK_PROOF_FILES` entry or region |
| `tests/data/seat_launch_references.json` | no | It is a Python call-site inventory, and no Python source is edited |
| Jail profile digests (`seat_jail.jail_profile_digest`) | no | They cover leg, owner and filter |
| Allowlist digests (gemini, codex, grok-review), `config.named` | no | Not edited |
| `watch_sha256`, `validator_sha256`, `CONTAINMENT_CONTRACT_SHA256`, `SRT_TREE_SHA256`, the package lock | no | Not edited |
| grok `context_digest` | no | It does not cover the proxy. Grok records still go stale through `runtime_digest` |
| `plans/evidence/seat-jail-1132/mutation-receipts-1170.json` | no | Historical. It is pinned to an older `proxy.mjs` that agent-harness#2033 already superseded |

## Requalification

These records bind `proxy_sha256` and/or `runtime_digest` and become stale:

- **Gemini W1 window records:** host-local. Both values move. The refresh is **owner-gated**,
  live, on the designated seat host (`ai`).
- **Codex window records**, if K-1 SL-6 registers or qualifies any before this lands: both
  values move. **Owner-gated**, live, on the seat host.
- **Grok measurement grants and rehearsals:** stale through `runtime_digest`. A new grant runs
  on the integrated head (grok contract section 8). **Owner-gated**, with a live provider.

These records are not stale:

- **Seat jail-qualification passes** from `qualify`: their own qualification key carries
  neither value [inferred; grok contract section 8]. V4 confirms this provider-free.
- **agy QCI and release-qualified records** (`plans/evidence/agy-*-qualification.json`).
- **The Claude SDK receipt.**

Provider-free work on the dev host: V1 to V4, and a printout of the new `proxy_sha256`,
`runtime_digest` and `release_identity` for the PR body. Nothing live is scheduled here.

## Dependencies & order

1. **Tests first.** Push a state with the tests and no fix. Record that V1 fails on the dev
   host (fake srt) and that BA-3 fails on Node 22.12.0 at the real-srt test (proxy exit 1 in
   `completion_detail`). Record the link to that BA-3 run in the PR body.
2. Then the `proxy.mjs` change and `CHANGELOG.md`.
3. **K-1 SL-6** (`t3/k1-sl6-codex`, which edits `panel_invoker.py` named refusals): land
   agent-harness#2067 **before** SL-6. The reasons:
   - The two share no file other than `CHANGELOG.md`.
   - SL-6 already recomputes pins after its own `runtime_digest` move, so rebasing onto this
     fix costs it nothing.
   - Any Codex window that SL-6 qualifies afterwards binds a head with the fixed
     `proxy_sha256` once. Landing after SL-6 would make those records stale a second time on
     both keys.
   - It removes a Node 22 crash source from SL-6's own runs.
4. **GROK SL-1 and SL-2** (agent-harness#2070, then SL-2): no ordering constraint.
   agent-harness#2070 touches no proxy file. SL-2 owns `seat_jail_qualification.py`, which
   this fix does not edit; the proxy digest there is computed from file bytes. Rebase on
   whichever merges first. `CHANGELOG.md` is the only shared file.
5. **Grok E8-C** (not yet open) also edits `proxy.mjs` and moves `proxy_sha256`. Land it
   consecutively with this fix and requalify once, on the integrated rollout build (grok
   contract section 8, batching).

## Verification

Narrow tests only, `-n 0` with a timeout, after a headroom check; no full suite.

```bash
cd phase-loop-runtime
# V1 red-first then green, any Node (fake srt):
PYTHONPATH=src:tests timeout 600 python -m pytest -p no:cacheprovider -n 0 -q \
  tests/test_grok_measure_egress.py -k "declared_body or cancel_guard"
# V2 Node 24 control and unchanged refusal semantics (real srt, loopback upstream):
PYTHONPATH=src:tests timeout 900 python -m pytest -p no:cacheprovider -n 0 -q -rs \
  tests/test_grok_measure_egress.py -k "real_proxy or refused or probe_row or listed"
# V3 other seats' proxy regressions:
PYTHONPATH=src:tests timeout 900 python -m pytest -p no:cacheprovider -n 0 -q \
  tests/test_seat_egress_allowlist_codex.py tests/test_seats_teamhost_gemini.py \
  tests/test_gemini_seat_egress_1170.py
# V4 jail-qualification pass keys and pins:
PYTHONPATH=src:tests timeout 600 python -m pytest -p no:cacheprovider -n 0 -q \
  tests/test_seat_jail_qualification_entry.py tests/test_seat_window_vendor_neutral.py
# V5 nothing outside scope moved:
git diff --exit-code origin/main -- src/phase_loop_runtime/seat_egress/*.json \
  src/phase_loop_runtime/seat_egress/package*.json src/phase_loop_runtime/seat_egress_proxy.py \
  src/phase_loop_runtime/seat_jail.py src/phase_loop_runtime/panel_invoker.py
```

- **V6** is the hosted BA-3 job on Node 22.12.0, with no skip: red at step 1, then green.
- `automation.suite_command` is V1, then V2, V3 and V4.
- The existing tests run unchanged and must pass:
  - `test_a_refused_request_with_a_body_leaves_the_real_proxy_running`;
  - `test_a_refused_body_is_read_only_within_its_bounds`;
  - `test_the_real_proxy_denies_counted_request_n_plus_one`;
  - the probe-row matrix.

## Scope boundaries

- **In scope:** `proxy.mjs`, `tests/test_grok_measure_egress.py` and `CHANGELOG.md`.
- **Out of scope:**
  - `seat_egress_proxy.py`, the srt version and tree pin, the allowlists, the `named` sets,
    jail profiles and `panel_invoker.py`;
  - the workflow (no Node 24 BA-3 leg, so required check names keep their meaning), and
    `NODE_MIN_VERSION`;
  - the drain bounds and the agent-harness#2064 tests;
  - any live run.
- **Rejected:** a timed wait in `refuseRequest` (not deterministic); an
  `uncaughtException` filter (broad, unsafe to resume); patching srt (moves
  `SRT_TREE_SHA256`); a Node 24 floor (hides the bug).

## Stop rules

Stop and report, without landing on inference, if any of these happens:

- BA-3 at step 1 is not red at the new real-srt test, or it shows an exit status other than 1.
  That would mean the mechanism is wrong.
- Node 22.12's throw is not `ERR_INVALID_STATE` "Controller is already closed", so the guard
  cannot stay narrow.
- An existing allow, refuse, cause or event expectation would have to change.
- The fix needs a file listed as out of scope, or a pin outside the table moves.
- E8-C or SL-6 lands a `proxy.mjs`, `refuseRequest` or `filterRequest` edit first, and the
  rebase conflicts.

## Execution Policy

- execute: effort=high, reason=a security-boundary proxy, a Node-version stream race, and
  fail-closed start-up

## Acceptance criteria

- [ ] On the fake srt, GET, HEAD and OPTIONS with a declared body, once refused, leave the
  proxy complete with exit 0. This is red before the fix. Proven by V1.
- [ ] On the real srt, every body-declaring GET, HEAD and OPTIONS refusal (`rules`, `budget`,
  `inner_host`) returns 403, forwards nothing and completes the observation. It is green on
  Node 24, and red then green on BA-3 Node 22.12.0. Proven by V2 and V6.
- [ ] A proxy without the guard fails to start with `START_FAILED_CODE`, and the guard
  rethrows other errors. Proven by V1.
- [ ] Existing decisions, causes and events are unchanged, and the out-of-scope files are
  byte-identical to main. Proven by V2, V3, V4 and V5.
- [ ] The `CHANGELOG.md` Pins line matches the pin table: `proxy_sha256`, `runtime_digest` and
  `release_identity` move, and nothing else does. Proven by review against V4 and V5.
