---
phase_loop_plan_version: 1
phase: FIRSTSEAT
roadmap: specs/phase-plans-seats-v1.md
roadmap_sha256: 9d1d149a4709dbf7c67dbdbb957228ff8a06d36570e1f9cb77bcc039b96a7ac4
---

# FIRSTSEAT: Gemini credential-free proxy mode

## Context

Implement [Consiliency/agent-harness#2157](https://github.com/Consiliency/agent-harness/issues/2157)
under the [owner-approved amendment](amendments/seats-FIRSTSEAT-gemini-proxy.md).
Use the reviewed pre-amendment tree as the regression comparison and record
its identity in the test evidence. The parent plan retains goal coverage.
[Consiliency/agent-harness#2166](https://github.com/Consiliency/agent-harness/issues/2166)
tracks the equivalent Codex and Grok exposure.

Today the launch sets `HTTPS_PROXY` with per-launch proxy userinfo in the provider
environment and bwrap's setup argv. bwrap uses `--unshare-pid` without `--as-pid-1`.
Its PID 1 reaper forks without exec, so its argv remains readable inside the
seat at `/proc/1/cmdline` even if agy scrubs a tool child's environment.
Same-UID seat processes can read `/proc/<pid>/environ`, inherited environment
reaches tool children, and agy's writable log/cache directories could retain
environment values. Host `ps` exposes the outer bwrap and setpriv argv to local
users. This change removes the proxy credential from each of those paths.

The authority boundary is reachability of the launch's loopback listener and
owner-only host Unix front. Other host users cannot reach the `0700` front
directory. Other seats have separate network namespaces and a private
`/tmp` tmpfs. Processes in the same seat can use its allowlisted proxy. Host
root and the operator UID remain trusted. A same-UID host process can access
the front and add W1 observation events, and already controls the installed
runtime and CA key. The delivered model bearer stays readable in the seat's
read-only config. Output that contains it can still end the leg with
`gemini_seat_token_in_output`.

## Interface Freeze Gates

The amendment freezes admission, readiness and §11's credential-free bracket
step. Use the existing IF-0-FIRSTSEAT-2 and IF-0-FIRSTSEAT-5 contracts with the
amendment. Preserve readiness-line keys and values, plus request/fence record shapes.

## Lane Index & Dependencies

SL-10 — Host front and private bridge
  Depends on: (none)
  Blocks: SL-11, SL-12
  Parallel-safe: no

SL-11 — Gemini launch and output guard
  Depends on: SL-10
  Blocks: SL-12
  Parallel-safe: no

SL-12 — Qualification and documentation
  Depends on: SL-10, SL-11
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-10 — Host front and private bridge

- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_egress_proxy.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_egress/proxy.mjs`, `phase-loop-runtime/src/phase_loop_runtime/sandbox_egress.py`, `phase-loop-runtime/tests/test_seat_jail_proxy_reach_1915.py`, `phase-loop-runtime/tests/test_sandbox_egress.py`
- **Tasks**
  - test: Exercise the amendment matrix using synthetic rules, credentials and a
    mock upstream. Base denies header-free CONNECT with 407. Require allowed
    TLS on head, zero events for dummy-header readiness, and refuse stale,
    dead and cross-wired launch components. Assert the original default-mode
    matrix and 407 tests pass as written.
  - impl: Add explicit, default-off front mode restricted to jailed Gemini.
    Reject all unsupported provider/mode combinations before dispatch. Keep the
    credential in host memory and the private launcher-owned startup pipe. Pass
    the plain URL to the seat and keep the scan token in parent-side state.
    Update the proxy-result URL docstring.
  - impl: Before starting the bridge, require the ready socket's parent to be
    an operator-owned, non-symlink directory with mode `0700`. Bind the live
    listener, bridge and Unix front to the expected holder network namespace
    and launch. Perform the dummy-header 407 readiness probe only after those
    checks. Retain direct-egress negatives and test the launch bindings against
    cross-wiring. Neither host Unix socket is mounted in the seat.
  - impl: Preserve firewall rules, proxy-only namespace, exact CONNECT authority,
    bounded ClientHello/SNI, TLS termination, inner host/SNI and method/path
    rules, CA projection, SRT pins, observations and teardown.

### SL-11 — Gemini launch and output guard

- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_profiles.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`, `phase-loop-runtime/tests/test_gemini_seat_egress_1170.py`, `phase-loop-runtime/tests/test_seat_secret_match_1823.py`, `phase-loop-runtime/tests/test_panel_invoker.py`, `phase-loop-runtime/tests/test_seat_profiles.py`, `phase-loop-runtime/tests/test_seat_jail.py`, `phase-loop-runtime/tests/data/seat_profile_digests_jailcore.json`
- SL-11 also owns only `_gemini_shape` in
  `phase-loop-runtime/src/phase_loop_runtime/seat_jail_qualification.py`.
  SL-12 owns the remaining qualification edits and starts after SL-11 verifies.
- **Tasks**
  - test: Run a provider-free command child with a synthetic token through the
    real jail. Assert no userinfo at `/proc/1/cmdline` and `/proc/self/environ`.
    Cover the same-UID provider environment, readable files and descriptors,
    host launch argv and client CONNECT traffic. Record only booleans. Verify
    the in-seat assertion fails against the comparison base. Add cases to
    `test_gemini_seat_egress_1170.py` and keep its existing §14 live 407 test
    unmodified.
  - test: Cover board, W1 control and measurement, and real and probe profiles.
    Require `seat_sandbox_refused:gemini_proxy_token_missing` for missing
    parent token and `seat_sandbox_refused:gemini_proxy_url_invalid` for a
    noncanonical URL. Compare real/probe and standalone/dependency profile
    digests through the qualification entry in `test_seat_jail.py` and reject
    the old qualified Gemini digest.
    Exercise split-chunk and combined post-exit scans with synthetic proxy
    and bearer values, including existing encodings and match-position fields.
    Accept harmless mentions of the loopback URL. Compare both architectures'
    non-Gemini jail profile pins and the Claude SDK inventory against base.
  - impl: Opt in at the jailed Gemini branch of `_default_spawn` and the
    Gemini branch of `_open_window_launch`, including refuse-all controls.
    Enforce the launch contract in `_prepare_jailed_gemini`. With egress
    present, `_gemini_env` emits the literal endpoint and rejects any other
    non-placeholder input. Accept the existing
    placeholder only for canonical profile construction and emit the literal
    there too. Remove the proxy entry from `_gemini_placeholders` and update
    `_gemini_shape` to pass the literal in the same lane. Leave
    `_owner_argv`, `actual_profile_digest` and shared `_PLACEHOLDERS` byte-identical.
    Keep redacted owner and broker evidence on `<egress-proxy>` and verify no
    validator treats that diagnostic shape as canonical argv. Correct the
    `seat_env` URL docstring.
  - impl: Use a Gemini subclass of parent-side `_JailedSeat` to hold
    non-repr proxy scan bytes. Keep the SDK-bound `_JailedSeat`,
    `launch_provider`, `_run_leg_with_liveness`, `_cleanup_jailed_seat`
    and `build_seat_jail` byte-identical. Reuse `_jailed_gemini_secrets` as the single
    source for streaming, post-exit and W1 supplier `scan_secrets`. Refuse
    with the named typed code before spawn when the token is absent, including on
    controls. Scan token bytes and their existing encodings. Never use the URL
    as a search value. Preserve `proxy_credential`, the 0.7.43 diagnostics,
    typed output refusals and board notice.

### SL-12 — Qualification and documentation

- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_jail_qualification.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `phase-loop-runtime/tests/test_seat_jail_qualification_entry.py`, `phase-loop-runtime/tests/test_seat_jail_qualification_bracket_steps.py`, `phase-loop-runtime/tests/test_seat_qualification_host_context.py`, `CHANGELOG.md`
- **Tasks**
  - test: Enter the qualification and bracket paths with the literal URL.
    Require §11's completed zero-upstream-byte result. Prove that a 407 in
    the bracket, unexpected upstream data, missing attempts or incomplete
    observations cannot qualify. Supply a synthetic URL with userinfo
    and assert a nonqualifying exit before the first socket dial.
  - impl: Update `_FAIL_CLOSED_FRONT` per the amendment.
    Preserve refuse-all, fences, bracket oracles and historical P3/P4 receipts.
    Document credential delivery and both typed refusals in the contract. Add
    the Unreleased changelog entry. Record the candidate pin comparison and reconcile release evidence
    after the rollout window using the installed runtime's observed identity.

## Execution Notes

Run lanes in dependency order and deploy their changes together. All lane work
starts after the amendment lands. Provider-free fixtures carry no live
credentials. Keep the existing Windows and macOS `platform_unsupported`
no-spawn controls. This plan adds no runtime fallback.

### Pin accounting

| Binding | Expected result |
| --- | --- |
| Gemini jail profile and L8 | Profile digest moves on x86_64 and aarch64. The active L8 qualification key and grants that bind the Gemini profile move. Unrelated EXECFIND keys stay stable. |
| Proxy and watch | Gemini and Codex `proxy_sha256` move because both bind the Python wrapper and Node front. Gemini `watch_sha256` and `validator_sha256` move with the qualification runner. Codex `watch_sha256` moves through its mechanics dependency. Codex validator stays stable. |
| Window runtime | `runtime_digest` and release identity move for all rows. Reissue authorized grants and qualify affected deployed contexts, including fresh Codex windows wherever its row windows are deployed. Any Grok series requiring same-runtime evidence restarts on the new runtime. |
| Stable inputs | FIRSTSEAT `contract_sha256`, interfaces, K1, production and refuse-all rules, SRT, agy image/help, heartbeat profile, QCI, validator version, non-Gemini jail profile digests, Grok `jail_context_digest`, `falsifier_layout_identity` and catalogued context inputs. |
| Claude SDK and agy package evidence | Keep the SDK input inventory and shared executable regions byte-identical. The SDK proof hashes of the whole `seat_profiles.py` file and the `seat_env` region (docstring-only edit) move. The whole-file change already requires a single fresh SDK proof. The docstring correction adds no proof run. Check those are the only changes in the SDK proof map and run `audit-order`. Record new package source pins in agy qualification evidence while retaining the admitted image. |

### Rollback

Revert the release as a unit. Keep old EC-EXECFIND-2 passes and W1 records at
least until the new release is qualified in every intended context. A revert
restores the old bindings, so otherwise eligible existing passes and receipts
can count again. Retain historical records with their original bindings.

## Verification

Run targeted lane tests serially with timeouts and shared-host headroom
checks. Use hosted CI and Gate A for the implementation PR as required by
`CONTRIBUTING.md`. Record the provider-free Linux jail integration result and
compare candidate pins with the base. Record only metadata in evidence.

For the integrated W1 gate, use the admitted agy image and the owner's
delivered credential under the owner account on the owner's primary board
host, where the refusal was seen. Prove the model transport, including gRPC
if used by this image, dials a remote model via the unauthenticated loopback
CONNECT front. If it uses grpc-go, confirm its proxy dialer honors
`ProxyFromEnvironment` and omits client Basic auth for the userinfo-free URL. Go's loopback bypass applies to the destination. Check the
effective agy process does not set, and its transport does not apply, a `NO_PROXY` bypass for model
destinations. Do not infer transport compatibility from symbol presence alone.
Node tool clients may use an explicit proxy agent. The gate must show a usable
W1 review and a real command child reporting only credential absence/presence
flags. Preserve grant and bracket requirements. The integrated run stays
outside CI and collaborator accounts. Then collect each host/account pair's
own provider-free EC-EXECFIND-2 pass, including collaborator accounts on every
host that launches jailed Gemini.

## Acceptance Criteria

- [ ] EC-FIRSTSEAT-5 — proven by `test_seat_jail_proxy_reach_1915.py` and
  `test_gemini_seat_egress_1170.py` entering the real bridge and synthetic
  jailed child. Falsified by any proxy credential in the seat, a missing
  readiness 407, a readiness observation, a cross-wired launch passing, or
  any direct egress succeeding. Path-entered control: an allowed TLS request.
- [ ] EC-FIRSTSEAT-3 — proven by `test_seat_secret_match_1823.py` and the W1
  supplier scan. Falsified by a missing parent-token launch, a missed encoded
  or split-stream match, a changed diagnostic, or refusal on a harmless URL
  mention. Path-entered control: the production guard with synthetic tokens.
- [ ] EC-FIRSTSEAT-7 — proven by `test_seat_jail_qualification_bracket_steps.py`
  and the admitted-image W1 gate. Falsified by a passing nonzero-upstream
  bracket result, a changed frozen input, a model request bypassing the proxy,
  or a usable review missing from W1. Path-entered control: the measured
  jail's §11 probe and the board launch.
- [ ] EC-FIRSTSEAT-1 — proven by parent `V-B`, falsified by its path-entered negative composition replay.
- [ ] EC-FIRSTSEAT-2 — proven by parent `V-C`, falsified by its path-entered silent-transport control.
- [ ] EC-FIRSTSEAT-4 — proven by parent `V-G` and `V-C`, falsified by its path-entered leg-route control.
- [ ] EC-FIRSTSEAT-6 — proven by parent `V-E` and `seat-window verify --window W1`, falsified by its path-entered matrix and kit controls.

The last four items retain the [parent verification](phase-plan-v1-seats-FIRSTSEAT.md#verification).

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- target surfaces: FIRSTSEAT amendment and phase-plan pointer in this planning PR, `advisor_board/CONTRACTS.md` and `CHANGELOG.md` in implementation
- evidence paths: `plans/evidence/seat-qualification/`, `phase-loop-runtime/tests/test_gemini_seat_egress_1170.py`, `phase-loop-runtime/tests/test_seat_jail_qualification_bracket_steps.py`
- redaction posture: `metadata_only`
