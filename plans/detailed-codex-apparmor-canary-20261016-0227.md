---
status: planned
owner_skill: codex-plan-detailed
scope: credential-free private AppArmor namespace canary before a production Codex policy repair
automation:
  suite_command: "uv run --project phase-loop-runtime --group test python -m pytest -q phase-loop-runtime/tests/test_codex_apparmor_canary.py phase-loop-runtime/tests/test_seat_jail_apparmor.py phase-loop-runtime/tests/test_seat_owner_composition.py phase-loop-runtime/tests/test_codex_seat_tool_sandbox_1335.py"
verification_status: not_run
review_status: approved_by_owner_unanimity
review_decision_ref: plans/evidence/codex-apparmor-canary/review.json
---

# Detailed plan: isolate the Codex AppArmor refusal

## Task

Implement a credential-free, administrator-run policy canary that evaluates the first namespace denial without changing existing host profiles. The live target is dev0; claw is only a review host. This is a prerequisite experiment, not a production repair or permission to install one. Planning base: Consiliency/agent-harness `d47b02609cb637c64e2069684032b288e399a815`. Related defects: Consiliency/agent-harness#1003 and Consiliency/agent-harness#1335.

## Research summary

The prior production probe succeeds directly on the host and fails inside the owned view. The view has zero capability sets, NoNewPrivs=1, and `bwrap//&unpriv_bwrap (enforce)`; namespace clone returns EPERM. Kernel audit serials 2819–2826 deny sys_admin. The shipped child policy explicitly denies capabilities; the installed Consiliency/agent-harness#1276 override covers only setpriv's uid drop. This establishes the first denial, not every capability a nested sandbox needs.

AppArmor parser 5.0.2 and aa-exec support named policy namespaces. Their attachment/stacking behavior needs live observation. Existing `seat_jail_apparmor.py` and its tests provide administrative-script conventions. Neither that module nor `panel_invoker.py` changes here.

The production egress-holder-to-owner mapping was independently observed resolving uid/gid 1000 through `1000 0 1`; it is expressible. This canary instead deliberately uses a **direct-host-bubblewrap** topology to isolate policy attachment. Its mappings will differ from production. Only host-operator identity, the stacked policy denial and hypothesis are compared; production topology equivalence is unclaimed.

## Changes

### `phase-loop-runtime/tests/codex_apparmor_canary.py` (create)

Add a standalone stdlib helper outside the installed package/CLI. `render --out DIR` emits reviewable helper/policies/config/ABI inputs. `run --operator-uid UID --operator-gid GID --evidence DIR` executes the fixed experiment; no arbitrary commands, policy paths or capability additions. Require nonzero operator uid/gid.

**Root staging.** Before invocation, the administrator verifies every staged byte against the reviewed digest manifest. Helper, policy, config and ABI files must be canonical regular files, root-owned, single-link and not group/other writable, beneath root-owned non-writable ancestors. Evidence is a fresh root-owned private directory under equally protected ancestry. Self-checks cannot replace this pre-execution administrator check. Invoke staged code with system Python `-I -S`; import only stdlib.

The root controller stays outside the experiment. Create exactly one unpredictable `phase_loop_codex_canary_<nonce>` policy namespace by exclusive creation in apparmorfs; refuse collisions. Record its directory identity and hold its descriptor. Every load/remove argv must contain that exact nonempty namespace; never target the root policy namespace. Capture before/after on-disk policy digests **and the loaded root-namespace profile set/digests from apparmorfs**. Missing readable loaded-state evidence makes the experiment inconclusive.

**Closed policy inputs.** Use fixed, macro-free profiles with no include, include-if-exists, tunable, variable, or abi directive. Ship an empty parser config and a regular kernel-feature dump from fixed `/usr/bin/aa-features-abi --extract --stdout`. This is a features input, not an ABI policy include. Bind its bytes/hash and boot_id; re-extract and compare before live loads, aborting on change. All parser commands use explicit `--config-file`, `--base`, `--Include` and `--policy-features` paths inside the reviewed render tree, plus `-K`; never add `--write-cache`. The parser's measured help defines -K as skipping cache load/save. Reject include/ABI directives before parsing; -I alone is not an include sandbox. Hash the complete input closure, command and preprocessed policy. Live load uses the exact same closure as compile-only verification.

**Complete policy inputs.** The exact full profile bytes are the planning inputs `plans/evidence/codex-apparmor-canary/baseline.policy` and `candidate.policy`, included verbatim in review bundles. Both define only `bwrap /usr/bin/bwrap` and `unpriv_bwrap`, with `flags=(attach_disconnected,mediate_deleted)`. The sole child-rule difference replaces `audit deny capability,` with `allow capability sys_admin,`. No additional capability permission, unconfined/default-allow/complain flag or loaded profile may augment either arm. An inherited parent or unexpected stack fails the pre-execution gate.

The parent grants capabilities in both arms, so the child's one-rule change is the sole capability-policy difference. The candidate's other capabilities are default-denied only under this complete enforce-mode recipe. Compilation alone does not prove effective semantics. Record actual loaded profile labels and rendered/preprocessed hashes before interpreting outcomes. These broad file/mount rules apply only to trusted synthetic commands in the private namespace, never providers.

**Identity, descriptors and mounts.** Use one trusted fork path. Close all non-stdio descriptors before namespace selection, identity drop and final exec; keep only null/status/control pipes, never writable root files. Use a new environment containing fixed PATH, locale and synthetic HOME/TMPDIR. Reject setuid/setgid or file-capability-marked executables; pin all tool hashes.

The controller stays outside the policy namespace. Its trusted child uses `aa-exec -n NS -p unconfined -- /usr/bin/python3 -I -S <staged-helper> <internal-drop-entry>`: on-exec selection is consumed by the protected Python trampoline, not bwrap. In that trampoline, drop every capability bounding bit while retaining only the temporary privileges needed for groups/gid/uid changes; clear supplementary groups, drop all real/effective/saved ids to the operator, explicitly zero inheritable/permitted/effective/ambient sets, set NoNewPrivs, verify the drop and close non-stdio fds again. Then exec fixed `/usr/bin/bwrap`; its normal path attachment creates the first user namespace. No host-uid-0 task may ever hold bwrap/unpriv_bwrap or execute an experimental inner command. Failure entering the private namespace is inconclusive, without fallback.

Outer bwrap uses `--unshare-user --uid UID --gid GID --cap-drop ALL`, private pid/ipc/uts/net namespaces and die-with-parent. Build a tmpfs root with selected read-only loader/library/executable binds, private proc, minimal synthetic dev, empty HOME, private scratch and a synthetic read-only fixture. Expose no host /etc, /sys, /run, /home, credentials, writable host path, apparmorfs or parent namespace fd. The host controller independently verifies user/mount/pid/net namespace separation, private mount propagation, host-operator map chain, all outer capability sets zero, NoNewPrivs=1, descriptor closure, mount exclusions and the exact owned-namespace bwrap//&unpriv_bwrap enforce stack.

Before **either arm's inner exec**, hold a fixed worker at a one-byte stdin gate. Send GO only after every host-observed precondition passes; the worker replaces stdin with /dev/null before exec. No arbitrary commands are accepted. Unexpected stacking, inheritance, identity, namespace or mounts abort before the inner command starts. Record gate observations for both arms.

**One primary operation, two arms.** Use exactly `unshare --user --map-root-user --mount /usr/bin/true`; remove both the bare-userns probe and nested-bwrap probe. Pin the target syscall as the namespace request containing CLONE_NEWNS. A root observer outside the experiment follows only namespace/capability syscalls of pidfd/start-verified descendants, attaching before GO. No environment, read/write buffers or network payloads are traced.

Preflight readable kernel-journal capture; record its cursor, boot_id, monotonic/realtime bounds and available audit loss/rate-limit counters. Baseline requires successful outer setup, the primary task's CLONE_NEWNS request returning EPERM, and a matching operation=capable/capability=21/sys_admin audit record for that exact task/label/interval. Missing attribution, truncation or known dropped capture is inconclusive; do not run candidate.

Reap baseline descendants, replace only the owned arm profiles, verify unchanged inputs, and construct a fresh identical outer fixture. Candidate `hypothesis_supported` requires **positive syscall progression**: the corresponding verified CLONE_NEWNS request returns 0. Later command failure is separately recorded and proves no working sandbox. `hypothesis_refuted` requires the same request to fail with the same attributed sys_admin denial. If the request is not reached/observed or neither condition holds, report inconclusive. Absence of an audit row never supports a conclusion. Never widen capabilities or aggregate evidence from different probes.

**Cleanup/evidence.** Track children with pidfds or verified PID/start identities and a private process group/pid namespace; never signal a reused PID. Reap owned descendants before removing profiles; close the held namespace directory fd immediately before removing only that namespace. Prove namespace absence in apparmorfs and unchanged loaded/disk root policy. Concurrent unexplained global changes are inconclusive, never repaired automatically. Cleanup failure blocks successful closeout and names only the exact owned remediation target. SIGKILL recovery remains administrator-owned.

Bound parser commands to 30s, each inner operation to 10s and cleanup to 30s (TERM then KILL for verified owned descendants). Limit child metadata to 64 KiB and audit/trace collection to 1 MiB; overflow/timeout is inconclusive and still triggers cleanup. Retain root-owned result metadata: timestamps, boot_id, tool/kernel/executable/helper/input hashes, identities/maps/labels, observations, statuses, sanitized audit correlation and cleanup. Never retain credentials, arbitrary environment/file contents, provider text or unrestricted strace. Outcomes `hypothesis_supported/refuted/inconclusive` are experiment metadata, not new runtime notices.

### `phase-loop-runtime/tests/test_codex_apparmor_canary.py` (create)

Use scratch fake parser/namespace/process adapters to test staging integrity and symlink/hardlink refusal; non-root drops/fd closure; namespace collisions; mandatory namespace/config/ABI/cache argv; include rejection/closure changes; strict labels/maps/mounts and no GO before validation; trampoline/on-exec ordering; feature-input changes; positive syscall progression versus silence; denied-capability attribution; baseline not reproducing; all three outcomes; no automatic widening; partial loads; cancellation, PID reuse and cleanup failure. Assert unrelated files/namespaces survive. Test observed orchestration, not only string snapshots. Mocks prove no kernel enforcement.

### `docs/advisor-board-capabilities-card.md` (modify)

Add an explicitly experimental troubleshooting note: existing uid-drop override versus canary, render/review/root-stage/run order, topology/interpretation limits, and exact owned-namespace cleanup. Do not expand capability support or advise disabling AppArmor, changing sysctls or disabling Codex's sandbox.

No production runtime, contract vocabulary, shared installation, release pin or GP branch changes. Planning/closeout owns this plan, manifest, the review.json and two full .policy inputs under `plans/evidence/codex-apparmor-canary/`, and skill handoffs/reflections.

## Documentation impact

Only that experimental note; no new public phase-loop command or supported production policy.

## Dependencies and order

Resolve independent review objections first (maximum three substantive rounds, no cancelling peers). Then implement helper/tests/docs in an owned execution tree. Before root invocation, present the exact rendered/staged digests and cleanup procedure for administrator authorization. This planning run executes no implementation test, policy canary or root policy load.

A later production repair needs its own scoped plan, review/president and host-policy authorization. Consiliency/agent-harness#1555 is merged, but managed Gemini adoption and release Consiliency/agent-harness#1547 remain separate work.

## Verification

Execution refreshes declared test dependencies in an isolated Python 3.12 environment and runs `automation.suite_command`. Then render to a fresh external evidence root and run both:
```sh
python phase-loop-runtime/tests/codex_apparmor_canary.py render --out "$EVIDENCE_ROOT/rendered"
apparmor_parser -K -Q --config-file "$EVIDENCE_ROOT/rendered/parser.conf" --base "$EVIDENCE_ROOT/rendered" --Include "$EVIDENCE_ROOT/rendered" --policy-features "$EVIDENCE_ROOT/rendered/features.dump" "$EVIDENCE_ROOT/rendered/baseline.policy"
apparmor_parser -K -Q --config-file "$EVIDENCE_ROOT/rendered/parser.conf" --base "$EVIDENCE_ROOT/rendered" --Include "$EVIDENCE_ROOT/rendered" --policy-features "$EVIDENCE_ROOT/rendered/features.dump" "$EVIDENCE_ROOT/rendered/candidate.policy"
```

Compile is not enforcement proof. After administrator staging/authorization, the fixed root run command records root-owned result.json. A runner-stamped amendment binds the actual invocation/artifact/digests. Machine-check all acceptance observations below; a refuted hypothesis may satisfy diagnostic acceptance, but is not a repair. Inconclusive execution never satisfies C3.

## Acceptance criteria

- [ ] C1: reviewed-byte administrator checks precede root invocation; protected single-link staging/evidence paths, verified non-root identity/map chain, fd closure and bounded orchestration pass targeted tests and live root metadata checks.
- [ ] C2: complete default-deny enforce profiles and sole candidate rule are reviewed; identical closed config/kernel-feature/policy inputs pass both compile-only commands and bind live load. No host includes/cache writes.
- [ ] C3: live baseline proves successful outer setup and attributed inner sys_admin denial; candidate uses positive observed syscall progression for that single operation, never missing-audit inference. Before inner exec, both arms prove strict labels, host-operator map chain, empty outer capability sets, NoNewPrivs, mount/fd exclusions and non-init userns. Missing proof is inconclusive and unmet.
- [ ] C4: disk **and loaded** root policy remain unchanged, all owned descendants are reaped, and the recorded private namespace is absent. Targeted tests plus live before/after metadata prove this; incomplete cleanup fails closeout.
- [ ] C5: record review findings, responses and actual verdict/ruling bindings accurately; no advisory result, hypothesis, mock or regression test becomes production approval.

## Review history and read scope

The sanitized `plans/evidence/codex-apparmor-canary/review.json` records each input, finding, response and outcome. Earlier plan-tier ruling requested changes; advisory re-review requested explicit positive progression, one primary operation, pre-execution gating and namespace-entry semantics. Those are incorporated above. Neither advisory feedback nor a failed/partial board is formal approval. The next normal staged plan-tier request runs on claw, where the real Codex probe and Claude proof pass and the normal Gemini admission/egress prerequisites have been established. No source, runtime, seat or president gate is disabled; no prior verdict is carried. The original three substantive-round cap remains.

Metadata/canonical review reads only are allowlisted under:
- Local `/home/viperjuice/workspace/evidence/codex-apparmor-plan-20261016/`: root `*.json`, `*.err`, `*review-bundle.md`, `review-api.py`, `plan-{bundle,brief}.md`; `round{2,3}/{*.json,*.err,review-api.py,review-bundle.md,plan-{bundle,brief}.md,stream/*.verdict.json,stream/seat-modes.json,stream/**/president.ruling.json}`; `plan-stream-{3,4}/{*.verdict.json,seat-modes.json,**/president.ruling.json}`.
- Claw `/mnt/workspace/e/aa16r/{*.json,*.err,review-bundle.md,native-fill/president/*.verdict.json,native-fill/president/seat-modes.json,native-fill/president/president.ruling.json,stream/*.verdict.json,stream/seat-modes.json,stream/**/president.ruling.json}`.

Raw provider logs/transcripts, login files and unrelated payloads remain protected. Past narrowly scoped launch/store diagnostics are closed. Future root-canary evidence needs an executor amendment. Preserve all foreign primary-checkout changes; only the new owned review worktrees may be edited. No installation, root load or implementation test occurred in planning.

References: [Ubuntu AppArmor](https://documentation.ubuntu.com/security/security-features/privilege-restriction/apparmor/), [upstream bwrap policy](https://gitlab.com/apparmor/apparmor/-/blob/master/profiles/apparmor/profiles/extras/bwrap-userns-restrict), [bubblewrap source](https://github.com/containers/bubblewrap/blob/main/bubblewrap.c). Measured host inputs take precedence over upstream main.
