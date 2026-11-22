---
automation:
  suite_command: "uv run --frozen --group test --project phase-loop-runtime python -m pytest -p no:cacheprovider -n 0 -q phase-loop-runtime/tests/test_grok_measure_egress.py phase-loop-runtime/tests/test_seat_egress_allowlist_codex.py phase-loop-runtime/tests/test_seats_teamhost_gemini.py phase-loop-runtime/tests/test_gemini_seat_egress_1170.py"
---

# Detailed plan: refused body-declaring requests must not crash the egress proxy (agent-harness#2067)

Revision r2 (2026-11-22): answers the agent-harness#2075 review with a captured Node 22 stack.

## Task

**Outcome served:** standalone. A seat process on a Node 22 host can no longer kill its own
egress proxy with a refused request that declares a body. Every decision stays the same.

Fix the Node 22 crash on a refused request that declares a body (`Content-Length` or
`Transfer-Encoding`), whatever its method. The fix must change no allow or refuse decision,
no forwarded byte, no allowlist, no named set and no jail profile. The plan also covers the
pin movement, requalification and sequencing.

## Research summary

- **srt 0.0.79, `request-filter.js` `decideAndRespond`.**
  - It pipes the request into a `PassThrough` shim and tees `Readable.toWeb(shim)` whenever
    `!bodylessMethod || declaresBody`.
  - A GET, HEAD or OPTIONS callback gets a bodyless `Request`, so the agent-harness#2033
    drain sees `request.body === null`.
  - On denial, srt cancels the unread branch and destroys the upstream branch, which cancels
    the source.
- **Captured failure (r2 evidence).**
  - **Setup.** Pinned Node 22.12.0 (nodejs.org tarball, `SHASUMS256` verified) under a
    private `$HOME` directory. It ran the real `proxy.mjs` over the installed srt 0.0.79 with
    the grok-review rules, loopback only, with stderr kept.
  - **Requests.** `GET`, `HEAD` and `OPTIONS` to `/v1/models`, each with `Content-Length: 2`
    and `{}` or with a chunked `{}`.
  - **Result.** Each request was observed as `deny`/`rules` and the proxy then exited 1,
    leaving no marker. The stack:

    ```
    TypeError [ERR_INVALID_STATE]: Invalid state: Controller is already closed
        at ReadableStreamDefaultController.enqueue (node:internal/webstreams/readablestream:1076:13)
        at PassThrough.onData (node:internal/webstreams/adapters:468:16)
        at PassThrough.emit (node:events:524:28)
        at Readable.read (node:internal/streams/readable:782:10)
        at flow (node:internal/streams/readable:1283:53)
        at resume_ (node:internal/streams/readable:1262:3)
    ```

  - **What it means.** The throw is a late **`enqueue` in the adapter's `onData`**, after the
    cancel. It is not a close: Node 22.12.0 already guards `close()` with `wasCanceled`, and
    only Node 24.22.3 also guards `onData`.
  - **Controls.** A POST with a body (the agent-harness#2033 drain) and a GET without one
    survive on Node 22. All cases survive on Node 24.22.3.
  - **Not reproduced.** Plain-stream stand-ins without the HTTP parser never crashed, so
    none is planned.
- **The launcher discards proxy stderr.** `seat_egress_proxy.py:942` passes
  `stderr=subprocess.DEVNULL`.
- **Allowlists.** grok-review allows only `POST`. Codex allows
  `GET chatgpt.com /backend-api/wham/accounts/check`. `filterRequest` checks inner Host, then
  rules, then budget.
- **Test harness.** `tests/test_grok_measure_egress.py` (in BA-3) has `real_proxy_upstream`.
  `FixtureUpstream._handle` reads but does not keep `Content-Length` bodies.
- **Hosts.** Repository tests on the dev host run Node 24 (the only trusted node); BA-3 runs
  Node 22.12.0.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/seat_egress/proxy.mjs` (modify)

- **The `Readable.toWeb` listener guard — add.** Place it before `await
  import(process.argv[2])` and import `Readable` from `node:stream`.
  - It wraps `Readable.toWeb`. srt calls it as `Readable.toWeb(shim)`, which is the same
    static.
  - It snapshots the source's `'data'` listeners, calls the original, and then replaces only
    the listeners that call added. Each replacement forwards the call only while
    `!source.destroyed`.
  - Reason: it reproduces Node 24's `onData` `wasCanceled` check on exactly the captured
    path. The adapter's cancel destroys the source, and a chunk emitted after that has no
    reader.
  - It swallows no error and touches no live source, so allowed forwarding is unchanged (T2).
  - Verified in r2 on a scratch copy under Node 22.12.0: the crashing GET, HEAD and OPTIONS
    cases, plus a POST, return 403 with unchanged events, and the proxy exits 0. Through srt's `decideAndRespond`,
    allowed CL, chunked and 300 KB bodies are forwarded byte-identical with and without the
    guard.
- **A start-up structural check — add.** It replaces r1's synthetic self-test.
  - It runs `Readable.toWeb` on a probe `PassThrough`, using Node's real adapter.
  - If the adapter did not add exactly one `'data'` listener, or that listener is not the
    guard, it writes `toWeb data guard is not in force` to stderr and exits 3 before the
    ready line.
  - Justification: it attests the guard on the real adapter's listener, the path in the
    stack. No synthetic sequence reproduces the race, so a behavioural self-test cannot.
- **The `refuseRequest` comment — modify.** It cites this path.

### `phase-loop-runtime/tests/test_grok_measure_egress.py` (modify)

- **A `proxy_diagnostics` fixture — add.** It is test-only. It wraps
  `seat_egress_proxy.subprocess.Popen` so that, for a `proxy.mjs` argv only, `stderr` goes to
  a private file under `tmp_path`. Every new assertion message carries
  `completion_detail(proxy)` and the stderr tail. Each exchange's `OSError` is caught and
  recorded, so a crash before the status line keeps its evidence. Production launch is
  unchanged.
- **`FixtureUpstream._handle` — modify.** It appends each `Content-Length` body to a new
  `self.bodies` list.
- **T1, `test_a_refused_request_that_declares_a_body_leaves_the_real_proxy_running` — add.**
  It uses `real_proxy_upstream` and `proxy_diagnostics`. The bodies are `Content-Length: 2`
  with `{}`, and chunked `2\r\n{}\r\n0\r\n\r\n`.

  | Case | Allowlist and budget | Request | Cause |
  |---|---|---|---|
  | (a) | `grok-review`, `request_budget=1` | GET, HEAD and OPTIONS to `/v1/models` on the inference host, each with both bodies | `rules` |
  | (b) | `grok-review`, `request_budget=1` | GET with Host `auth.x.ai` | `inner_host` |
  | (c) | `codex`, `request_budget=0` | `GET chatgpt.com /backend-api/wham/accounts/check` with `Content-Length` | `budget` |

  Each case asserts:
  - a `HTTP/1.1 403` status line, since every body is complete;
  - `upstream.requests == []`;
  - its event's `(method, host, path, decision, cause)`;
  - `completion(proxy).complete` with the expected request count, exit status 0, and no
    `ERR_INVALID_STATE` in stderr.
- **T2, `test_an_allowed_request_with_a_body_is_forwarded_unchanged` — add.** Real srt,
  `Content-Length` bodies only, because the fixture reads only those.
  - Codex `GET /backend-api/wham/accounts/check` with `{}`, no budget.
  - grok-review `POST` to the inference path with `{}` and with 256 KiB, `request_budget=2`.
  - It asserts a 200 status, `upstream.bodies` byte-equal to what was sent, `allow` events
    and a complete observation.
- **T3, `test_a_proxy_without_the_data_guard_does_not_start` — add.** It follows the
  `unattested-proxy.mjs` pattern: a copy whose replacement listener is the original
  listener. On the fake srt, `start_proxy` raises `START_FAILED_CODE` on any Node.

### `CHANGELOG.md` (modify)

- **A Fixed entry — add.** It gives the captured failure, the fix and a Pins line that
  matches the table. Values are not recorded.

## Documentation impact

- `CHANGELOG.md`: as above.
- `docs/releases/outside-agent-release-handoff.md` already covers the `proxy_sha256` move.
- **Frozen protocol.** `plans/seats-firstseat-containment-contract.md` section 14 (around
  lines 409–426) keeps "the readiness line's keys and values" and "every decision and reason
  of the existing request matrix".
- **No new vocabulary.** The fix adds no stdout line, ready key, event field, `cause`, exit
  code (3 already exists) or stdin form.

## Pin movement

| Pin | Moves? | Why |
|---|---|---|
| `proxy_sha256` (`seat_jail_qualification._PROXY_IMPLEMENTATION_SHA256`) | **yes** | It hashes `seat_egress_proxy.py` and `proxy.mjs` |
| `seat_window.runtime_digest()` and window `qualification_keys` | **yes** | It hashes `seat_egress/*` |
| `seat_window.release_identity()` | **yes** | Same files, less `seat_window_grants.py` |
| `ROW_GRANTS`, `OWNER_W1_GRANT_SHA256` and `OWNER_W1_PACKET_SHA256` | no in-repo edit | Empty or `None` at this base. A grant packet drafted elsewhere is stale |
| agy QCI (`agy_profile_digest`) | no | It covers the profile description and operations only |
| Claude SDK proof inputs | no | `proxy.mjs` is in no `SDK_PROOF_FILES` entry or region |
| `tests/data/seat_launch_references.json` | no | Python call sites only |
| Jail profile digests | no | They cover leg, owner and filter |
| Allowlists, `config.named`, `SRT_TREE_SHA256`, package lock, `watch_sha256`, `validator_sha256`, `CONTAINMENT_CONTRACT_SHA256`, grok `context_digest` | no | Not edited, and they do not depend on the proxy bytes |
| `plans/evidence/seat-jail-1132/mutation-receipts-1170.json` | no | Historical, pinned to an already-superseded `proxy.mjs` |

## Requalification

These need current rollout evidence: the coordinator compares each live record's
`runtime_digest` and `proxy_sha256` with the installed release.

- **Gemini W1:** **owner-gated**, live, on the designated seat host (`ai`).
- **Any Codex window** already qualified under K-1 SL-6: **owner-gated**, live, on the seat
  host.
- **Grok grants and rehearsals:** stale through `runtime_digest` (`grok_tool_surface.py`
  runtime check). A new grant runs on the integrated release. **Owner-gated**, with a live
  provider.

These are not stale:

- **Jail-qualification passes:** their keys omit both values (`seat_qualification_key.py`).
- **agy records.**
- **The Claude SDK receipt.**

Provider-free on the dev host: T1 to T3 (Node 24), V3, the new pin values, and optionally the
standalone Node 22.12.0 capture (private `$HOME`, loopback). Nothing live is scheduled.

## Dependencies & order

1. **Draft-only red evidence.** The implementation PR stays draft while a tests-only head of
   it runs the hosted BA-3 job on Node 22.12.0. Keep that run's link and T1's retained stderr
   in the PR body.
   - A red required check, or exit 1 alone, does not confirm the mechanism. The retained
     stack must match the captured frames: `onData` in adapters, then `enqueue`.
   - That head is never merged.
2. **Then the guard and `CHANGELOG.md`.** The final head must pass BA-3 with no skips, and
   every required check green (`CONTRIBUTING.md` local and required checks). No red required
   check may remain at merge.
3. **K-1 SL-6** (`t3/k1-sl6-codex`): land this fix first when it is ready. They share only
   `CHANGELOG.md`, and SL-6 recomputes its own pins. What matters is that Codex qualification
   runs on the integrated installed release.
4. **GROK SL-1 and SL-2** (agent-harness#2070, then SL-2): no code-ordering dependency.
   Rebase on whichever merges first.
5. **Grok E8-C** also edits `proxy.mjs`.
   - Allow one writer at a time. Whichever lands second rebases and reruns T1 to T3 with the
     diagnostics integrated.
   - Batch the rollout with E8-C and the next grant's jail lanes
     (`grok-tool-surface-contract-v1.md` around lines 1604–1609;
     `grok-jail-tool-surface-contract-v1.md` around 635–652). Separately installed trains can
     each need their own refresh.

## Verification

Narrow tests only, `-n 0` with a timeout, after a headroom check; no full suite.

```bash
# V1 Node 24 control: refusals, allowed forwarding and start-up check (dev host)
PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests timeout 900 python -m pytest \
  -p no:cacheprovider -n 0 -q -rs phase-loop-runtime/tests/test_grok_measure_egress.py \
  -k "declares_a_body or forwarded_unchanged or data_guard or refused or probe_row or listed"
# V2 other seats' proxy regressions
PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests timeout 900 python -m pytest \
  -p no:cacheprovider -n 0 -q phase-loop-runtime/tests/test_seat_egress_allowlist_codex.py \
  phase-loop-runtime/tests/test_seats_teamhost_gemini.py phase-loop-runtime/tests/test_gemini_seat_egress_1170.py
# V3 nothing outside scope moved
git diff --exit-code origin/main -- phase-loop-runtime/src/phase_loop_runtime/seat_egress/*.json \
  phase-loop-runtime/src/phase_loop_runtime/seat_egress/package*.json \
  phase-loop-runtime/src/phase_loop_runtime/seat_egress_proxy.py \
  phase-loop-runtime/src/phase_loop_runtime/seat_jail.py phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py
```

- **V4** is the hosted BA-3 job on Node 22.12.0 with no skip: red on the draft-only tests
  head (step 1), and green on the final head.
- The existing body, bound, budget and probe-row tests run unchanged.

## Scope boundaries

- **In scope:** `proxy.mjs`, `tests/test_grok_measure_egress.py` and `CHANGELOG.md`.
- **Out of scope:**
  - `seat_egress_proxy.py`, srt and its pins, the allowlists, the `named` sets, jail profiles
    and `panel_invoker.py`;
  - the workflow and `NODE_MIN_VERSION`;
  - the agent-harness#2064 tests;
  - any live run.
- **Rejected:** r1's global controller guard (it swallows errors after ordinary closure); a
  timed wait; an `uncaughtException` filter; patching srt or Node; a Node 24 floor.

## Stop rules

Stop and report if any of these happens:

- The BA-3 red stack differs from the captured frames.
- T2 shows any forwarded byte or allowed status changing.
- An existing allow, refuse, cause or event expectation would have to change.
- The fix needs an out-of-scope file, or a pin outside the table moves.
- srt or Node stops reaching the adapter through `Readable.toWeb`, so the start-up check
  fails on a supported Node.
- An E8-C or SL-6 rebase conflicts in `refuseRequest`, `filterRequest` or the guard.

## Execution Policy

- execute: effort=high, reason=a security-boundary proxy, a Node-version stream race, and
  fail-closed start-up

## Acceptance criteria

- [ ] T1's refusal matrix (`rules` × GET, HEAD and OPTIONS × CL and chunked; `inner_host`
  GET; codex `budget` GET) returns 403, forwards nothing, and completes with exit 0 and no
  `ERR_INVALID_STATE`. Proven by V1 (Node 24) and V4 (Node 22.12.0, final head).
- [ ] T2: allowed codex GET and grok POST bodies, including 256 KiB, reach the upstream
  byte-identical with 200. Proven by V1 and V4.
- [ ] T3: a proxy whose data guard is not in force fails with `START_FAILED_CODE`. Proven by
  V1.
- [ ] V4 on the draft-only tests head is red with retained stderr matching the captured
  `onData` → `enqueue` frames, and the final head passes every required check. Proven by the
  BA-3 run links in the PR body.
- [ ] Out-of-scope files are byte-identical, and the `CHANGELOG.md` Pins line matches the
  table. Proven by V3 and V2.
