---
phase_loop_plan_version: 1
automation:
  suite_command: "PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_native_codex_seat_fill.py phase-loop-runtime/tests/test_native_claude_seat_fill.py phase-loop-runtime/tests/test_native_claude_seat_fill_green.py phase-loop-runtime/tests/test_panel_native_fill_183.py phase-loop-runtime/tests/test_advisor_board_backing_homebrew.py phase-loop-runtime/tests/test_review_monitor_policy.py phase-loop-runtime/tests/test_autosel.py phase-loop-runtime/tests/test_advisor_board_golden.py phase-loop-runtime/tests/test_skills_canon_parity.py phase-loop-runtime/tests/test_skills_bundle_drift.py phase-loop-runtime/tests/test_skills_src_claude_literal_lint.py"
---

# Detailed plan: Codex native review cell — agent-harness#924

- Status: draft for plan review; planning only, execution gates remain closed.
- Authority: EC-REVIEWTRUTH-18, lane D; [implementation handoff](https://github.com/Consiliency/agent-harness/issues/924#issuecomment-5754668344).
- Scope: the Codex/OpenAI cell and its existing emit → fill → invoke seams. This is partial delivery of EC-REVIEWTRUTH-18, not phase completion or closure of agent-harness#924. Google/native-capable hosts and other remaining cells stay on that issue.

## Research and binding limits

Input inspection used main `3fbedb2d073b49797b68695aeebfd7af0d6175da`; that is historical grounding, not a required future base. `harness_env_signatures.detect_run_from_harness` already recognizes `CODEX_THREAD_ID`, prioritizes it over leaked Claude markers, and suppresses inherited markers with `PHASE_LOOP_CHILD=1`. `HostContext` exists, but production native-fill eligibility, request text, ingestion and both invoker paths are Claude-specific. The CLI continuation messages also hardcode `claude=`. The governed and train seams already forward generic fill objects.

Preserve these actual contracts:

- `advisor_board/CONTRACTS.md`, “Host-leg identity”: “The standalone runner (`host_harness=None`) has no host leg”. Host detection supplies routing data, never authorization.
- `panel_invoker.py`, native-fill contract: “A fill is DATA from the first-party session — never a launch, never authority.” Reuse `NativeLegFill`, content digests, `composition_digest`, existing refusal reasons, terminal verdict parsing and president ordering.
- `advisor_board/CONTRACTS.md`, “Review monitoring policy v1”: “It permits no timeout overrides, capture, research, API fallback, gateway or native host seat.” The closed policy vocabulary stays `bounded | heartbeat_only`; `PanelLegResult` status and fill-refusal vocabularies do not expand. The sole new deferred reason is `under_codex`, analogous to `under_claude_code`.
- `plans/phase-plan-v10-REVIEWTRUTH.md`, Execution Notes: “The coordinator enforces CONFORM, HARDEN, and SCHED completion before SL-0”. The EC-14 early-slice record explicitly covers only its named slice. It supplies no EC-18 waiver.

## Decisions

1. **One host resolution, no new heuristic.** Resolve an explicit `HostContext` first, including explicit `HostContext(None)` for a real standalone caller; otherwise reuse the existing detector's first verified candidate. A context is a truthful caller assertion, never a way to disguise a native session as standalone. Implement only the existing Claude cell and new Codex cell; do not enable agy/opencode native routes. Thread the same resolved context through request emission, fill preflight and both invoker paths. Honor the existing child sentinel and Codex-over-leaked-Claude precedence; board routing must not later re-adopt a discarded ambient Claude marker.
2. **Defer the host's eligible seats before any provider dispatch.** On Codex, subscription/homebrew OpenAI seats on the `codex` lane defer as empty-text `UNAVAILABLE/under_codex` with exact cognition, seat identity, artifact and resolved brief. Both the all-native early return and mixed-board matrix path use the same predicate. No own-vendor CLI launch, unavailable-seat backfill or alternate lane is a substitute. Wrong-lane, API-key or gateway configurations for the host vendor fail closed rather than becoming native authority. Preserve `enforce_native_host_leg` and review authorization/revalidation order. Claude seats on a genuine Codex host still use the existing TUI route; non-native CLI lanes remain unchanged.
3. **Extend the existing protocol, not its authority.** Use per-vendor request reasons/affordances; the Codex request names a native Codex subagent, never Claude's Agent tool. `native_fill_request_payload`, loader and preflight use the same resolved eligibility. Accept `--native-leg codex=<dir-or-request.json>` on both commands, retaining the existing Claude spelling and legacy filename compatibility. Derive vendor-correct continuation text and `filled_by` provenance from the emitted seat, never relabel current artifact digests as the old request's digests. A supplied vendor alias must agree with the emitted seat/model. Request, artifact, brief, composition and seat bindings, stale-train refusal, author exclusion, duplicate-fill refusal, verdict-less degradation and bind-before-president behavior remain load-bearing. No new result classifier or approval count is introduced.
4. **State the single-request boundary honestly.** The existing CLI emit envelope selects one seat. This bounded cell qualifies a board containing exactly one eligible Codex seat. If multiple eligible Codex seats are composed, refuse the emit operation as ambiguous before request files or reviewer effects; do not silently fill the first and claim the others satisfied. The library may return a separate typed deferral for each eligible seat, but this plan does not add a multi-request CLI or count an unfilled seat. Keep this residual explicit on agent-harness#924.
5. **Heartbeat-only remains unsupported for native seats.** Resolve host metadata before whole-board monitoring preflight. A detected native seat, explicit native seat or supplied native fill under `heartbeat_only` refuses the requested board before availability/auth, request-directory creation, minting or provider launch. Extend the existing pure monitoring preflight with native-host metadata as necessary; preserve its existing diagnostic family and policy vocabulary. A board with no seat of the host's vendor remains eligible for its existing non-native routes. Never auto-select `bounded`, spawn the host vendor's CLI, clear genuine host markers, substitute a reviewer, add a model-thinking deadline or invent sandbox facts. This delivers a protocol cell under the existing native-fill policy, **not operational native support under this operator's heartbeat-only requirement**.

## Changes and tests-first boundary

| Path / entity | Action and purpose |
| --- | --- |
| `phase-loop-runtime/tests/test_native_codex_seat_fill.py` and `_reviewtruth_native_codex_tdd_guard.py` | Create the tests-only boundary: behavioral RED anchors, always-active guard/positive controls, and explicit force activation using the existing `PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1` convention. Normal collection skips only the new falsifiers until the distinct Codex marker lands; the existing Claude marker must not activate them. |
| `phase-loop-runtime/tests/test_advisor_board_backing_homebrew.py` | Correct only the old `test_inside_claude_homebrew_host_leg_spawns_natively` fixture, which uses “native” for a CLI launch with explicit `HostContext("claude")`; assert a typed native deferral instead. Guard this changed expectation with the new boundary's activation rule, retaining the old expectation while inactive. Land and freeze both arms with the RED boundary. |
| `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` | Modify host resolution, `_under_claude_code`/board routing consistency, native request/loader/preflight/apply helpers and both `invoke_board` paths according to decisions 1–5. Reuse the existing detector and schema; no new provider launch site. |
| `phase-loop-runtime/src/phase_loop_runtime/advisor_board/backing.py` | Modify only `resolve_review_monitoring_policy`'s pure native-host input/refusal. Leave broker execution, launch prefixes, leases, cancellation, cleanup and egress ordering unchanged. |
| `phase-loop-runtime/src/phase_loop_runtime/cli.py` | Modify the two native flag descriptions, emitted continuation messages and pre-effect native/heartbeat refusal. Keep the existing board/train protocol surfaces and exit conventions. |
| `phase-loop-runtime/src/phase_loop_runtime/reviewtruth_native_fill_capability.py` | Add `REVIEWTRUTH_CODEX_NATIVE_FILL_CAPABILITY_VERSION = "reviewtruth.codex-native-fill.v1"` only after this cell's production path is complete. Retain the Claude marker byte/value; this is a distinct test activation marker, not the phase-wide marker or heartbeat/isolation qualification. |

`harness_env_signatures.py`, `advisor_board/schema.py`, `advisor_board/composition.py`, `governed_review.py`, `governed_premerge.py` and `train_runner.py` are inspected reuse seams, not assigned production edits. If their current interfaces cannot carry the reviewed design after integration, stop for a bounded plan correction; do not silently enlarge ownership. Frozen native-Claude tests, phase-wide REVIEWTRUTH tests, LEGIBLE probes/classifiers, provider transports and Claude-owned PRESROUTE/EXECFIND remain unchanged.

The new test file must cover these independent groups, all through real production functions with the existing sanctioned hermetic authorization seam and effect spies, never a raw callback treated as authority:

- `HostResolution`: explicit context/standalone, verified marker, no marker, child sentinel, dual markers, and non-native positive controls; no model-tier inference.
- `Routing`: both invoker paths, no-Fable Codex board, alternate OpenAI model tier, exact request cognition/brief, zero own-vendor launches, vendor-correct text, wrong backing/lane refusal, missing CLI not misreported as a launched reviewer, and each multi-seat residual.
- `Binding`: valid fill plus independently corrupted artifact, brief, composition, model/seat, duplicate, author-excluded, stale-train and verdict-less arms; no bad fill can spend a seat or replace a runtime result; the president observes bound results only.
- `Protocol`: both CLI and governed/train emit/readback/invoke seams with injected provider effects; zero review/mint/publish/merge on emit, alias mismatch refusal, vendor-correct provenance, and unchanged Claude compatibility.
- `Policy`: native-host/fill heartbeat refusal before every effect, no implicit policy change, no-host-seat heartbeat positive control, unchanged standalone/non-native routing and no false sandbox/cleanup success.

For every new RED anchor retain the asserted injection site, observed assertion failure, independent positive control and corresponding killed mutant. Include mutations that remove host deferral, substitute Claude request text, bypass a binding check and bypass native-host heartbeat refusal. Missing imports, a test that never enters its target path, provider unavailability or a constant-pass helper are not RED proof.

## Documentation impact

In the implementation landing update `advisor_board/CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`, `CHANGELOG.md` and the four `skills-src/<harness>/<harness>-advisor-board/SKILL.md` sources. Mark only the qualified single-Codex-seat protocol cell as added, retain other native-cell and multi-request residuals, and prominently retain the heartbeat-only/native incompatibility. Use “native subagent” versus “CLI lane”; use vendor names or backticked concrete harness names in shared prose to avoid the known brand-collapse error. Correct only adjacent native-routing residual wording from agent-harness#924. Regenerate `phase-loop-skills/` and packaged `skills_bundle/` with the existing two scripts, inspect their actual changed path set, and require parity/literal tests. No installed skill, service or deployment is modified.

## Dependencies and order

1. Review/reconcile this plan. Planning and its new manifest row are the only currently authorized writes. Preserve all existing manifest rows, order, lifecycle events and authority prefixes; append only this row. Any later integration replays the delta onto then-current main rather than restoring this manifest. No roadmap edit or reseal is required; historical RUNTIME metadata stays untouched.
2. Before **any RED lane or production execution**, require the phase's CONFORM/HARDEN/SCHED and SL-0/SL-1 gates and the applicable EC-REVIEWTRUTH-15 record/ancestry checks. HARDEN's prior Opus refusal remains controlling; this plan authorizes no retry, reroute or new waiver. Serialize the runtime/CLI writer with active work, including agent-harness#978 and agent-harness#979, and re-ground the inspected seams on current main. The EC-14 early record cannot serve as EC-18 execution authority.
3. After admission, land the reviewed, observed-RED tests-only boundary under EC-REVIEWTRUTH-0. Then implement without editing that frozen boundary. A necessary test correction gets its own reviewed boundary before production resumes. No future output SHA, commit count or fixed topology is prescribed beyond the phase's existing landing invariant.
4. Run the commands below, retain exact-source receipts and cause-specific failure dispositions, reconcile four-vendor implementation review and required CI, and use the phase's gated landing/chronology checks. Operator review uses Opus 5/high instead of exhausted Fable credit, with no model-thinking or silence deadline; this does not change any phase prover requirement or silently substitute a binding prover.
5. Keep agent-harness#924 and EC-REVIEWTRUTH-18 open. Hermetic protocol evidence is not a live native review receipt. A live receipt requires the existing native reviewer capability posture to be enforceable and an admitted route under the operator's actual monitoring policy; neither is granted here. Record that operational hold instead of running a bounded board to obtain a green result.

## Verification (future execution only)

Run the YAML `automation.suite_command` through the native verification runner after admission. It includes the new guarded suite and existing Claude, host-routing, monitoring, AUTOSEL, golden, skill parity and literal controls. The tests-only boundary runs the new suite once forced to retain RED and once unforced to prove its inactive/guard behavior; production repeats the same frozen suite forced and unforced, requiring identical activated assertions and no residual skip caused by a missing Codex marker.

After focused checks pass:

```sh
python3 phase-loop-runtime/scripts/regenerate_skills_bundle.py
python3 phase-loop-runtime/scripts/sync_skills_bundle.py
PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_native_codex_seat_fill.py
env -u PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_native_codex_seat_fill.py
PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests
git diff --check
```

Regeneration is an implementation step before final automation/review, never a planning-time check. Retain native `verification.json`, full logs, exact candidate/tree/plan digest, RED/positive-control/mutant records and the route matrix under the runner-owned run directory. Keep failed full-suite results failed; source-matched baseline comparisons are dispositions, not passing receipts. No operational attestation or phase-completion reducer is manufactured by this plan.

## Acceptance criteria

- [ ] EC-REVIEWTRUTH-18, Codex single-seat scope only — proven by the frozen `HostResolution`, `Routing` and `Protocol` groups in the declared automation; other cells and multi-request CLI remain explicit residuals.
- [ ] EC-REVIEWTRUTH-18 binding/capability scope — proven by `Binding` and `Policy`, preserved native-Claude/monitoring regressions and exact-source review; no operational heartbeat-native qualification is inferred.
- [ ] EC-REVIEWTRUTH-0 for this bounded change — proven by the admitted tests-only RED/positive/mutant receipts, immutable test-boundary comparison and unchanged forced/unforced production assertions.
- [ ] Same-landing capability prose and generated mirrors match the limited cell and policy posture — proven by the declared parity/literal checks and the full changed-path review; no EC-18 completion or agent-harness#924 closure claim.
