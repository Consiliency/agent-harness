---
type: detailed
status: planned
owner_skill: codex-plan-detailed
input_base_commit: b9892d298aa23297e3f37eea5e2b4995c67ec60e
related_issues: [agent-harness#1321]
automation:
  suite_command: 'PYTHONPATH="$PWD/phase-loop-runtime/src:$PWD/phase-loop-runtime/tests" phase-loop-runtime/.venv/bin/python -m pytest -q phase-loop-runtime/tests/test_skill_eval.py phase-loop-runtime/tests/test_skill_eval_runner.py'
---

# Detailed plan: a bounded, blinded skill-eval pilot capability

## Task

Build an opt-in evaluator for **read-only Codex planning tasks**. Compare the current `codex-plan-detailed` skill independently with each of two reflection-derived candidates: installed/deployed-layer selection and acceptance-oracle selection. Deliver runnable experiment preparation, isolated subject execution with observed file access, blinded human scoring, and deterministic reduction. This is a diagnostic pilot, not an installed-skill adherence benchmark.

Do not edit or regenerate skills, archive reflections, implement the execution-skill candidate, add editor/CI promotion gates, or run live model trials as part of implementation acceptance. A subsequent explicitly started pilot qualifies the operational capability. Bulk prose adoption remains gated: a promising pilot is evidence for review, never permission to apply a change. No new roadmap EC is claimed; agent-harness#1321 and REPORT Tier 2.1 supply the rationale.

## Research summary

`spikes/pstack-comparison/REPORT.md` Tier 2.1 calls for blinded behavioral comparison; `handoffs/05-pstack-alignment.md` adds controls, replication, and preregistration. PStack's router/inert-leaf structure makes isolated skill adoption an invalid default. The 416-reflection aggregation produced hypotheses, not measured current failure rates or reproduced incidents.

`launcher.build_codex_command` already supports JSON output and read-only invocation. `launcher.launch(action="review")`, `panel_invoker._seat_command_profile`, and `SeatLaunchRole.PROVIDER_REVIEW` own isolated launches. `test_seat_executor_review.py` exercises the real Linux boundary. `advisor_board/research.py` audits web calls, **not filesystem reads**. No existing comparative skill evaluator was found. Use a separate console entrypoint to avoid the concurrently owned LOOPFIX `cli.py` surface; module-only commands also fail under isolated tool installation.

## Changes

### Experiment protocol and reduction

Create `phase-loop-runtime/src/phase_loop_runtime/skill_eval.py` with `console_main()` (no required parameters; reads `sys.argv`), experiment validation/preparation, judge-packet export, and reduction. Add `phase-loop-skill-eval = "phase_loop_runtime.skill_eval:console_main"` to `[project.scripts]` in `phase-loop-runtime/pyproject.toml` and to the sorted `_CANONICAL_CONSOLE_SCRIPTS` in the located `phase-loop-runtime/src/phase_loop_runtime/agy_canary_evidence.py`; the existing `test_release_console_allowlist_matches_pyproject` requires equality. No new dependencies or shared closeout/roadmap vocabulary.

Commands:

* `validate --spec FILE`: validate a version-1 JSON input without starting a provider.
* `prepare --spec FILE --out DIR`: freeze a new experiment; refuse an existing destination.
* `run --experiment DIR`: execute its scheduled, not-yet-started trials sequentially.
* `packet --experiment DIR --out DIR`: export blinded material and an empty scoring form; add `--calibration` for the separate gold packet.
* `reduce --experiment DIR --scores FILE --out DIR`: verify evidence and emit JSON plus Markdown results; add `--calibration` to seal the one-shot gold judgment and persist its receipt in that experiment.

The spec requires explicit model and effort, `ModelSelection.profile="plan"`, Codex executable identity/version, immutable baseline skill bytes, candidate edits with exact old/new anchors, fixture files, natural task prompts, per-case rubrics and required evidence paths, repetition count, allocation seed, gold-pack bytes/annotations, and decision rule. Reject absolute/traversing fixture names, links, unknown schema fields, duplicate IDs, missing anchors, and inconsistent schedules. Freeze hashes of all inputs, runtime identity, generated arm bytes, effective feature/command configuration, gold pack and schedule before any model call. Never re-resolve a moving skill source during a run. Changed inputs require a new experiment, not an amended result.

Store operator-only allocation, provenance, full redacted transcripts, per-trial launch/access receipts, and result hashes outside subject roots. Use random neutral trial directories and stable relative fixture paths. Generate the schedule with a recorded seed, balancing control-first/treatment-first order across each experiment (six pairs each); this is allocation randomness, not a claimed model sampling seed. The same explicit model/effort/CLI/runtime configuration serves both arms. No resume conversation, shared subject HOME, or cross-trial output is exposed.

Hold an exclusive experiment lock during `run`; a concurrent runner refuses before claiming or launching a trial. Atomically persist a started record before launch and one terminal record afterward. Never silently retry: a crash/interruption or a started trial without a terminal receipt makes the experiment incomplete. A later `run` may execute untouched scheduled trials only. Maximum budget is 48 subject invocations, with no automatic replacements; report elapsed time and usage when emitted, otherwise usage unknown. Preserve existing heartbeat/cancellation semantics: review launches deliberately do not use quiet wall-clock timeouts. Operator cancellation stops the batch and retains incomplete evidence; do not alter that launch policy here.

### Isolated runner and observed access

Create `phase-loop-runtime/src/phase_loop_runtime/skill_eval_runner.py` for staging and `run_trial`. Reuse `ModelSelection`, `build_codex_command(..., read_only=True, json_output=True)`, the existing isolated-network context, `_seat_command_profile`, and `launcher.launch(..., action="review", _review_profile=profile)`. Materialize both the preimage and final copy below `sandbox_policy.staging_root()`, outside the experiment directory. Before workers/probes start, the CLI process sets and freezes `LC_ALL=C` for deterministic diagnostics. At the staging root, preimage and resolved final cwd call `review_stage.host_git(path, "rev-parse", "--git-dir", capture_output=True, text=True, check=False)`. Return code 0 means an enclosing repository: refuse. Return code 128 with stderr beginning `fatal: not a git repository` in that C locale means confirmed absence: allow. Any exception, timeout, other code or other diagnostic means discovery unavailable: refuse before observation. Test all three outcomes; neither every nonzero result nor every failed command is absence. Do not rely on `GIT_CEILING_DIRECTORIES`: `host_git` strips `GIT_*`. This prevents ignored-fixture omission and launcher's snapshots from reading watched untracked files.

The command builder emits `CODEX_REVIEW_STAGE_PREFIX`; direct `launch` does not resolve it. Call `launcher._resolve_review_stage` with `log_path=None` and its owned `materialized` list, before profile construction. Bind the resolved `--cd` directory in `readonly_paths`, use it as cwd, and watch that copy's regular files. Verify completeness/hashes before measurement; refuse placeholders, escaping paths or an in-Git stage before the watch. Logs/receipts may remain under the experiment, but must not determine staging placement. Clean only recorded owned stages after observation ends and receipts are retained. Preserve `sandbox_egress.isolated_network`, `panel_invoker._EGRESS_LAUNCH_PREFIX` and the review wrapper's ephemeral monitoring. No new provider subprocess path, bypass flag, sandbox or judge prompt is introduced.

Before the final prompt argument, add `--ephemeral`, `--ignore-rules`, `--strict-config`, `-c 'web_search="disabled"'`, `-c features.apps=false`, and `-c features.remote_plugin=false`. Also disable each frozen `_BROKER_CODEX_DISABLED_FEATURES` entry except `_BROKER_CODEX_SANDBOX_ENABLED_FEATURES` (`shell_tool`, `code_mode_host`), preserving local read tools. Add no MCP server stanzas. Freeze the expanded feature list/argv; test the exact effective configuration. `--ignore-rules` concerns execpolicy files, not the common `AGENTS.md` guide route. Filtered egress denies private networks; it leaves public networking available and does not itself disable web search. The common task requires fixture-only evidence; this increment makes no air-gap or arbitrary shell-network prevention claim.

Construct the owned profile before observation, then derive the no-inference command with `panel_invoker._codex_sandbox_probe_command` from the resolved Codex argv. Require a supported probe, replace its first word with `owned_command[0]`, use the same profile/cwd/network context, and require exit zero before any subject model invocation. A matching `seat_tool_evidence.launcher_diagnostic_in` failure records `seat_tool_sandbox_unavailable`; every other probe failure/timeout/unavailable result also refuses the subject, rather than adopting the board helper's permissive inconclusive fallback. The probe runs before the watch and is not a subject trial or a model call. Never widen either sandbox. Actual model/tool operational qualification still requires a later completed fixture-reading task.

The no-inference probe alone has the existing `_CODEX_SANDBOX_PROBE_TIMEOUT_S` bound: launch it via `panel_invoker.launch_owned` with that same prepared profile, separate stdout/stderr pipes and a new process session; use `communicate(timeout=...)` and the existing process-group anchor/termination helpers as in `_run_leg_with_liveness`, always reaping on timeout/cancellation. Do not pass this timeout to `launcher.launch(action="review")`, which ignores it. Subject review monitoring remains unchanged. Test probe timeout cleanup and zero subject calls.

Each trial gets regular copied fixtures and `.guidance/plan.md` containing exactly its frozen variant; common `AGENTS.md` routes planning tasks there. Guide access is an **exposure prerequisite**, not a behavioral score: missing guide `IN_ACCESS` makes the trial invalid/unexposed and the comparison inconclusive. Do not drop or replace that trial, or count an unexposed baseline as a treatment win. Missing required **case-fixture** access after valid guide exposure remains a retained behavioral failure. This evaluates guidance after exposure, not trigger reliability.

The common task envelope requests only a final-response plan, states that this is a plain snapshot without `.git`, and overrides artifact/manifest/handoff/reflection writes equally in both arms. It asks for fixture-only facts and relative-path evidence, without quoting the guide or operator paths. Case prompts never supply the candidate rule or answer. Pin/verify the actual executable before profile materialization; use the existing fresh seat environment. Read-only closeout conflicts or failed tools in a real turn can still invalidate qualification; fake-subject acceptance does not establish real-Codex usability.

Require a successful launch, a completed `item.completed`/`agent_message` and a subsequent successful `turn.completed` before scoreable output. Parse the pinned CLI's actual event shapes; `turn.failed`, missing completion, unknown/truncated JSON events or empty final text invalidate the trial. Do not use `_extract_codex_stream_json_text` as completion proof. The monitor merges stderr/stdout: preserve all redacted lines and ignore only a frozen, pinned-version diagnostic allowlist plus blanks; unexpected non-JSON lines invalidate instead of being guessed into another channel. Test complete, partial, failed and mixed-diagnostic streams.

Create `phase-loop-runtime/src/phase_loop_runtime/skill_eval_access.py`: a small Linux inotify observer using standard-library `ctypes`, nonblocking descriptor reads, and an immutable watch-descriptor-to-relative-file map. Watch every regular fixture and guide file, after staging/hashing/profile preparation and before launch. Drain through owned-process completion, stop watching, then perform post-run integrity reads. The parent must not read watched content during that interval. No recursive scans or hash reads inside the measured window.

Record `IN_OPEN` and `IN_ACCESS` separately; only access qualifies as necessary read evidence. Overflow, unexpected watch loss/unmount, mutation/replacement, or post-run hash drift invalidates the trial. Missing guide access invalidates exposure; missing case-fixture access after exposure fails the behavioral criterion. A no-read child through the same launch boundary must produce no fixture access; a known-read child must produce the expected event. Also prove in-Git staging is rejected before the watch. These controls detect launcher/preflight contamination.

Access is evidence that a file was accessed during the isolated trial, **not proof the model understood it, nor per-process attribution**. Inotify cannot report all mmap accesses or identify the reader; use private single-trial roots and prohibit concurrent inspection. An observed access still needs rubric evidence in the delivered plan. Never substitute subject self-report or counts of repeated events. Document these limits from the [Linux inotify manual](https://man7.org/linux/man-pages/man7/inotify.7.html). Non-Linux runs report unsupported; missing observation cannot become a passing trial.

### Pilot cases, scoring, and tests

Create `phase-loop-runtime/tests/fixtures/skill_eval/pilot.json` as a checked-in, synthetic case pack plus candidate definitions. Do not include private reflection text, paths, credentials, or raw reports. Use the canonical baseline at the pinned input commit; materialize variants only in experiment storage. Include these exact candidate edits:

* Layer candidate, after exact anchor `3. Inspect likely implementation and test files.`: “For an installed or deployed defect, identify the failing layer and compare its identity with current source and any existing repair or release owner. Scope the plan to the unresolved layer; record separately owned dependencies and qualification still required.”
* Oracle candidate, replacing that exact step-3 anchor: “Inspect implementation and test files, tracing each proposed acceptance fixture through its real producer and observable consumer. Name a supported alternate path when the change affects one, and choose controls that fail on the intended behavior rather than setup.”

Run **two separate comparisons**, each with three target cases and one negative-control case, three repetitions per case, and two arms: 48 trials total. Neither treatment combines the two edits.

| Comparison | Target cases | Negative control |
|---|---|---|
| Layer | stale installed package with source already repaired; live configuration mismatch with correct source; existing release owner with remaining qualification work | current source truly defective, no repair owner: a source fix is appropriate |
| Oracle | fixture bypasses producer normalization; stale consumer state hidden by manual test reload; supported alternate entrypoint omitted by a helper-only test | supported direct helper contract: no invented producer boundary or extra workflow |

Each case must contain the relevant producer/consumer or source/install identities in files, a plausible distractor, an expected scope, required read-path set, and explicit binary rubric items. Freeze these before trial execution. Rubrics score concrete plan decisions, supported acceptance checks, and refusal of the case's tempting wrong approach; prose length, use of candidate vocabulary, and claimed compliance earn no credit. Keep access coverage and behavioral scores separately visible.

Packet export includes only randomized per-output IDs, natural tasks, sanitized fixture facts, plan text, rubric, and relative-path access evidence. Exclude arm/model/effort labels, schedule/order, guide bytes, candidate rationale, and operator paths. Apply a field allowlist and preregistered identity-marker scan using explicit opaque arm IDs, full model IDs and operator/staging path prefixes; ordinary case words such as producer, consumer or control are not identity markers. Preserve original output/hash privately; an answer disclosing an actual arm/model identity is unblinded and makes that comparison inconclusive rather than being rewritten. A human scorer who has not seen allocation records completes all rubric items with output citations and seals scores before allocation reveal. This is procedural blinding, not protection from a scorer deliberately opening operator files.

Bind every launch/access/terminal receipt to experiment digest, scheduled trial ID, fixture/guide digest and final-output digest; missing or swapped receipts invalidate that trial. Score IDs are required exactly once for each valid completed scoreable output; invalid/no-output scheduled trials need no invented human score. Refuse missing/duplicate/unknown scoreable IDs, changed hashes or foreign packet scores. Report every scheduled trial, including invalid/missing ones.

Every exposed, otherwise valid trial — target or negative control — passes iff all case rubric items and required case-fixture accesses pass. A matched pair is one case repetition: treatment PASS/baseline FAIL is a win; baseline PASS/treatment FAIL is a loss; equal booleans are a tie. Partial rubric totals cannot create wins. Report nine target and three negative-control pairs separately. Any invalid/missing/unblinded trial makes the comparison inconclusive. All three negative-control **baseline** trials must pass, or the comparison is inconclusive for lack of control sensitivity. Otherwise promising requires at least three target wins, zero target losses and zero negative-control losses; a negative-control loss is a regression. Remaining valid comparisons report no demonstrated improvement. All-FAIL negative-control ties cannot qualify. This is a small preregistered pilot, with no significance/fleet-generalization claim or claim that repetitions are independent incidents.

Create `tests/test_skill_eval.py` and `tests/test_skill_eval_runner.py` under `phase-loop-runtime/`. Test artifact round trips, exact variants, freezing/allocation, hidden-label exclusion, receipt joins, incomplete ledgers, locking/no-retry and decision boundaries. Specifically falsify: three otherwise winning pairs with unexposed baselines; all-FAIL negative-control ties; partial-score improvements without trial passes; cross-trial/experiment receipt swaps; missing scores versus invalid no-output trials; reused/failed calibration; ignored/in-Git fixture staging; unresolved placeholders; wrong feature flags; failed/unknown sandbox probes with zero subject calls; open-only/self-reported reads, source-copy contamination, overflow/mutation and launch failure. Use fake subjects and real owned Linux processes; default tests make no model calls. Supply independently annotated good/wrong outputs and citations for every case. Machine tests prove validation/reduction against gold, not human rubric semantics; blinded gold calibration is a separate qualification prerequisite.

## Documentation impact

Create `docs/phase-loop/skill-eval.md` covering commands/schema, blinding, exposure versus behavioral failure, calibration, cost/stop behavior, Linux/Codex limits and pending operational qualification. Update the located console-script paragraph in `phase-loop-runtime/README.md` and Unreleased `CHANGELOG.md`. Fixtures remain repository test data; the installed CLI accepts supplied specs without repository-relative imports. No skill bundle or protocol schema changes.

Both calibration commands require `--experiment DIR` and hold the experiment lock. `packet --calibration` persists only one opaque gold packet; `reduce --calibration` records the sealed attempt (scorer ID, experiment/packet/rubric/gold-pack digests, score bytes/digest and verdict) and immutable receipt in the experiment's calibration ledger. Record that attempt before evaluating scores; any second attempt or incomplete started attempt refuses, even after failure or fresh opaque IDs. All binary gold scores must match and citations must reference valid output spans. Never return gold annotations from either command. Previously disclosed examples are practice, not a new blinded qualification; the scorer declares no prior gold exposure, recorded with the receipt. This remains a procedural human trust boundary. Ordinary reduction loads that experiment's ledger and checks every identity/digest; absent, failed, foreign or changed calibration cannot produce promising. No cross-experiment receipt reuse or automatic retry. Score files require the same scorer ID and packet/rubric digests.

## Dependencies & order

1. Implement the experiment schema, synthetic cases, reducer and falsifying tests.
2. Add runner/observer and prove both read and no-read controls through the existing owner before enabling live invocation.
3. Add console entrypoint/docs, complete checks, and open a PR; stop before merge. No live pilot is required to merge the tested capability. Mark operational qualification pending until an explicitly started pilot produces its complete evidence packet; a failed efficacy result is valid evidence, not a reason to tune the rubric.

No dependency on agent-harness#1692–agent-harness#1694 implementation, LOOPFIX delivery, or an execution-skill edit. If the launch seam cannot isolate observation without changing shared ownership contracts, stop and amend this plan; do not substitute transcript self-report or expand into a new execution framework.

## Verification

From the repository root, when implementing:

```sh
uv sync --project phase-loop-runtime --group test --extra visual --locked
PYTHONPATH="$PWD/phase-loop-runtime/src:$PWD/phase-loop-runtime/tests" phase-loop-runtime/.venv/bin/python -m pytest -q phase-loop-runtime/tests/test_skill_eval.py phase-loop-runtime/tests/test_skill_eval_runner.py
PHASE_LOOP_REQUIRE_SEAT_OWNER=1 PYTHONPATH="$PWD/phase-loop-runtime/src:$PWD/phase-loop-runtime/tests" phase-loop-runtime/.venv/bin/python -m pytest -q phase-loop-runtime/tests/test_skill_eval_runner.py phase-loop-runtime/tests/test_seat_executor_review.py
uv run --project phase-loop-runtime phase-loop-skill-eval --help
PYTHONPATH="$PWD/phase-loop-runtime/src:$PWD/phase-loop-runtime/tests" phase-loop-runtime/.venv/bin/python -m pytest -q phase-loop-runtime/tests/test_closeout_classifier.py phase-loop-runtime/tests/test_console_scripts_are_declared.py
make check
make check-full
```

The required Linux-owner run must not skip its observer controls. Add an installed-entrypoint smoke assertion to `test_skill_eval.py`, exercising `--help` and `validate` from outside the repo. Before merge, follow CONTRIBUTING's required CI and Gate A packaging workflow; opening a PR does not authorize merging it. These commands are planned, not run during planning.

## Acceptance criteria

* [ ] Frozen inputs, independent variants and balanced 48-trial allocation round-trip; mutation, invalid specs and concurrent runners fail — targeted `test_skill_eval.py` command above.
* [ ] Real owned-process controls distinguish access, open-only, and self-report in the resolved stage outside Git, with no parent/source-copy contamination; in-Git stages, missing isolation and overflow fail — required Linux-owner command above.
* [ ] Fresh read-only roots, a positive no-inference inner-sandbox probe, explicit frozen feature controls, no placeholders or silent retries, and bound interruption/failure receipts — targeted `test_skill_eval_runner.py` command above.
* [ ] Blinded packets, exposure/negative-control validity, exact pair outcomes and one-shot calibrated scoring are enforced; malformed/incomplete evidence or missing guide exposure cannot yield promising — targeted `test_skill_eval.py` command above.
* [ ] Console entrypoint works outside the repo, release allowlist matches, docs match commands, and reachable regressions pass — entrypoint smoke, existing packaging tests, `make check`, and `make check-full` above.
* [ ] Default acceptance invokes no live models and changes no canonical skill or reflection; tests assert those side effects are absent — targeted suite above. The PR and handoff explicitly mark live pilot qualification and editor gating as pending.
