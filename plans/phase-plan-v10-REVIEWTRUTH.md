---
phase_loop_plan_version: 1
phase: REVIEWTRUTH
roadmap: specs/phase-plans-v10.md
roadmap_sha256: e94a3bbce91074bbeca0b384f146642265089f93e00e2ba01b3efeaac7d12466
automation:
  suite_command: 'PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration"'
---

# REVIEWTRUTH: Board Reports Its Own Degradation

## Context

REVIEWTRUTH is explicitly selected for this run. Canonical `.phase-loop/state.json` and `.phase-loop/tui-handoff.md` now agree that REVIEWTRUTH is the current `planned` phase, and the newest canonical ledger event records the GPT-5.6 Sol planning run at maximum effort. Relative to HEAD, the live worktree contains only this unstaged plan repair and its matching manifest-digest update. Legacy `.codex/phase-loop/` state is compatibility-only and is not authoritative.

The phase replaces the board's text-derived usability shortcut with a typed per-seat outcome, distinguishes FULL, FLOOR-ONLY, and BELOW-FLOOR delivery, makes lens and artifact grounding load-bearing, wires native Fable fill requests back into board results, persists per-seat and aggregate governed outcomes, fails closed on empty or elided material, and connects the production repair round. It does not implement LEGLIFE timeout enforcement or custom per-repo seats; it only freezes and consumes the `timed_out` outcome that LEGLIFE later produces.

The roadmap names four implementation lanes. This plan maps them to SL-2 through SL-5 and adds three control lanes: SL-0 decides `agent-harness#398`, obtains maintainer ratification, and separately lands the durable posture record before any posture-assuming change; SL-1 lands the literal PANELLED RED tests-only boundary, both chronology modes, every immutable REVIEWTRUTH evidence wrapper, the frozen ordinary-suite collection hook in `phase-loop-runtime/tests/conftest.py`, the complete live floor-2 assertion migration in `test_governed_cross_vendor_floor_358.py` and `test_train_merge.py`, the normative sanctioned-delta amendment in `test_advisor_board_golden.py`, and all five known compatibility migrations in `test_advisor_board_research.py`, `test_panel_invoker_spawn.py`, and `test_panel_native_fill_183.py`, including all three existing under-Claude-Code Fable native-fill reversals in the last file; SL-5 ends at an explicit SL-2-through-SL-5 implementation PR/landing boundary; and SL-6 starts from the resulting canonical-main tip to reduce final chronology, live, source-ownership, structured JUnit, and verification evidence. All ten SL-1 paths are immutable after the tests-only landing. `panel_invoker.py` remains a single-writer file in SL-2. SL-5 owns the driver-side/native integration plus `train_runner.py` and `train_ledger.py`, consumes SL-2's frozen binding API and SL-3/SL-4's grounded classifier, and makes no test edits, so no lane overlaps those files.

`agent-harness#398` remains an open design issue as rechecked read-only with `gh` on 2026-07-30. Its only comment is the coordinator's explicit request that a maintainer ratify Option 2 (evidence staging) or state another bounded posture; no maintainer has supplied that decision. Merged `agent-harness#400` assigns the decision to REVIEWTRUTH but does not decide or ratify the capability posture. The coordinator recommendation is not ratification. Neither the v10 roadmap's blanket execution authorization, this plan's four-seat review, an advisor-board verdict, nor issue discussion substitutes for the missing maintainer-ratified disposition record. SL-0 is therefore an unsatisfied human gate and hard precondition: SL-1 through SL-6 must remain undispatched until explicit maintainer ratification exists and the matching durable record is separately merged as an ancestor of canonical `main`.

An earlier authoritative exact-digest panel at `.phase-loop/reviews/v10-reviewtruth-plan-panel.json` reviewed plan SHA-256 `dcebcaf0df4542f41c853ce205982bf170ed1d634883a7ff4e408334385e1617`. Grok 4.5 and Gemini 3.6 Flash returned AGREE, GPT-5.6 Sol returned DISAGREE, and Fable deferred. Sol identified three blockers: candidate/final JUnit files were generated with unsafe same-command variable expansion and never parsed before their consumers; phase-node zero-skip claims were incorrectly applied to a broad suite with legitimate pre-existing opt-in skips; and SL-1 omitted `phase-loop-runtime/tests/test_panel_native_fill_183.py::DefaultClaudeSeatNeverCarriesNativeFill::test_brief_ref_flows_into_the_request`, a second existing under-Claude-Code Fable native-fill reversal. The prior repair gave every XML a literal runner-owned path, froze generation-before-parse-before-consumer ordering, separated phase-selected accounting from a broad baseline skip-set/digest, and brought all five compatibility migrations into SL-1's immutable ownership with legacy, forced-activation, and automatic post-marker assertions. The follow-up exact-digest review of plan SHA-256 `bebb671c795d16f84c0303346e2897aabae211832791388081b1a03c3819727d` identified one remaining blocker: SL6-T2's durable evidence record claimed the final phase/broad XML and parser-attestation digests that SL6-T3 only generates and parses afterward, so the phase-final wrappers would have consumed a record containing themselves, and any later evidence-doc update would have bound the four-vendor review and the phase-final run to stale evidence-document digests. This repair makes SL-6 evidence acyclic: SL6-T2 stages and boards a pre-final record limited to already-existing artifacts; the phase-final wrappers consume only frozen pre-final inputs plus the broad-final producer attestation; only after the final-mode parse does `finalize-record` write the write-once post-parser record at `docs/research/reviewtruth-final-evidence-record.md`; the separate minimal `final-record` verifier attests that record from outside it; and the four-seat closeout binds the finalized record digest plus that attestation, with verdicts written only to the canonical ledger. The exact-digest review of plan SHA-256 `405b07f458dec59e50cb94cae2902a128031859412d4894b6417d4b2fc217e75` identified one remaining ownership blocker: the plan required a separately digested durable redacted transcript without owning any second transcript path. The next repair designated the already-owned `docs/research/reviewtruth-real-panel-smoke.md` as the single canonical durable redacted transcript and smoke record, with one frozen SHA-256 digest and no second durable transcript path. The latest exact-digest panel in that same review artifact inspected plan SHA-256 `7c80a2d3133c4ad17f2aa8fcc8f7ea738f3e806dd7dafe0a3d72404f45a7957d`; Grok 4.5 found that the five marker-activated post-parser wrappers made ordinary GitHub CI, Gate A, the frontmatter `suite_command`, and every fresh clone permanently red because only special candidate/final commands deselected them, while GPT-5.6 Sol found that `seat_key` cannot bind a native report because it is explicitly non-unique and a late or replayed report can attach to a current colliding seat. This repair gives SL-1 a frozen dual-mode collection hook whose sole strict arm is activated by the immutable final phase runner after broad-final attestation, and freezes per-seat-instance, per-request, and per-attempt native identities plus exact-once report consumption and durable reconstruction. The new digest invalidates every previously reviewed digest. Before SL-0 starts, the coordinator must panel the new exact SHA-256 digest with Fable 5, GPT-5.6 Sol, Gemini 3.6 Flash, and Grok 4.5. Fable and Sol must both return reviewed outcomes. Any unavailable, errored, empty, capped, refused, or timed-out Fable or Sol seat blocks dispatch; every material finding requires a plan edit and a fresh review of the changed digest.

The fresh local panel recorded in that artifact then reviewed exact plan SHA-256 `aebb6159b98dbc98b70a02b1c782476e852c2f1316c05bbaaa6c6fca1569fced` from staged bundle SHA-256 `7ce2b2469591cdaad4d4d17835b744e9ae53b19777b6f801690467e364b4c55c` (176577 bytes) under instructions SHA-256 `700499a4fa5cf1ef7a995f1ee4259f146d32aa4e0b269d5d2b886477f8ef8846`; its recorded staging path was `/tmp/pl-panel-bxisa895/review/`. Grok 4.5 and GPT-5.6 Sol returned DISAGREE and Gemini 3.6 Flash returned AGREE. Grok proved that the normative EC-REVIEWTRUTH-0 and EC-REVIEWTRUTH-9 commands selected only wrappers that ordinary collection deselects, while Sol proved that `-m "not dotfiles_integration"` already contributes the large pre-existing marker-filter deselection baseline (the bootstrap record observed 601), so five cannot be the total broad deselection count. This repair binds both wrapper-backed criteria to the ordered broad-final/final proof chain and freezes marker-filter deselections as their own exact tuple/count/digest, separate from legitimate skips and the five hook-owned wrapper deselections. The changed digest again invalidates the reviewed digest and still requires the mandatory exact-digest Fable 5 + GPT-5.6 Sol + Gemini 3.6 Flash + Grok 4.5 panel before SL-0.

The latest local panel in `.phase-loop/reviews/v10-reviewtruth-plan-panel.json` reviewed exact plan SHA-256 `2b8c23afad5b1f028ec036167f164e430030e07440bb9c11a3d34affc4109ee6`; Grok 4.5 and Gemini 3.6 Flash returned AGREE and GPT-5.6 Sol returned DISAGREE. Sol found one blocker: the first two pre-edit commands produced only collect-only stdout and ordinary JUnit before either the proposed conftest observer or repo parser existed, so a later parser could not retroactively prove same-HEAD/tree/process/argv/runtime/plugin identity or reconstruct the marker-filter deselection tuple. A repository, canonical-runner, sibling-checkout, and dotfiles-source search found no existing coordinator-owned or runner-owned immutable pytest baseline observer. This repair therefore embeds a minimal external bootstrap observer as exact reviewable bytes below, SHA-256 `c782f3b9f503582df25a7489a4be97ed3f2e6853b021c3abf1ee874cf47d619c`. The exact-digest four-seat plan panel reviews both those bytes and their digest before SL-0; after SL-0, the bytes are materialized only into ignored runner evidence and execute once before any SL-1 hook, wrapper, verifier, or test mutation. One pytest process observes the full collected set before marker filtering, the selected set after `-m "not dotfiles_integration"`, the exact `pytest_deselected` multiset and marker membership, legitimate runtime and collection skips, raw stdout/stderr, JUnit, HEAD/tree/index/clean status, plan/roadmap/source digests, process identity, full process and pytest argv, the controlled pytest environment, Python/pytest/module provenance, and the loaded plugin inventory. The later SL-1 parser and mutation tests independently recompute every relation and digest from the raw observation; they do not treat the bootstrap attestation as self-authenticating. The changed plan digest invalidates `2b8c23af…` and again requires the mandatory exact-digest four-seat panel before SL-0.

The newest panel in that artifact reviewed exact plan SHA-256 `3e02663a2b7d4d1472a53cd15ba9fccaa704aad3403bc38c9b5e17ba26faa68f`; Grok 4.5 and Gemini 3.6 Flash returned AGREE and GPT-5.6 Sol returned DISAGREE. Sol found exactly two remaining blockers. First, the normative Gate A command inherited `PHASE_LOOP_SKIP_GATE_A_SUITE=1`, which lets the smoke pass while skipping the standalone pytest suite. This repair replaces every normative Gate A invocation with one owned two-stage `gate-a` evidence reducer that explicitly removes and internally rejects that selector, captures the unmodified script's traced output, requires exactly one installed-wheel full-suite start and GREEN sentinel in order, parses nonzero executed-test and outcome counts plus the exact `-q -p no:cacheprovider -m "not dotfiles_integration"` profile into a write-once canonical artifact, forbids the script's SKIPPED branch, and launches a fresh internal attester that independently re-hashes and verifies the artifact before static checks or closeout. Second, the bootstrap observer sanitized only pytest injection while `conftest.py` and `phase_loop_test_utils.py` can preserve ambient application plugin/root selectors. The repaired observer now starts under `env -i` with an exact seven-key allowlist, rejects every other key, proves suite initialization adds only the two exact in-tree profile/skill-source opt-ins, requires `PHASE_LOOP_RUNNER_REPO_ROOT`, `PHASE_LOOP_CLAUDE_ROUTE`, `CI`, both REVIEWTRUTH activation selectors, and `PHASE_LOOP_SKIP_GATE_A_SUITE` absent, requires both installed application entry-point groups empty, and attests every loaded registrar/provider source byte plus the complete skill-source root mapping. The later parser recomputes and freezes that entire environment/selector/registry/source/root profile and mutation-tests every drift arm. Both repairs stay outside wrapper inputs and the finalized record: their terminal attestations gate and are bound only by the canonical ledger closeout, preserving the existing acyclic final evidence chain.

Current implementation anchors were rechecked rather than copied from drifted roadmap line references: `_render_leg_prompt` is at `panel_invoker.py:1065`; the TUI-policy exclusion and native-request attach are at `panel_invoker.py:4205-4232`; `_default_train_review` is at `train_runner.py:2006`; the count-only train-resume short circuit and ledger write are at `train_runner.py:2911-2957`; the legacy durable fields are at `train_ledger.py:166-180`; the legacy `leg.text.strip()` governed finding branch is at `governed_review.py:137`; and the separate governed pre-merge threshold is `_MIN_USABLE_REVIEWERS` at `governed_premerge.py:57`, consumed at `governed_premerge.py:405`.

A focused live-test scan for `_MIN_USABLE_REVIEWERS`, `below_reviewer_floor`, literal `usable_reviewers=2`, `floor counts LEGS`, and `2-usable` found the authorizing floor-2 pins in exactly `phase-loop-runtime/tests/test_governed_cross_vendor_floor_358.py` and `phase-loop-runtime/tests/test_train_merge.py`. `phase-loop-runtime/tests/test_governed_planning_gate.py` is the explicit non-floor plan/design scope control and remains governed by the preserved `proceed_degraded` policy rather than becoming a merge-floor positive pin. The golden surface was also rechecked: `test_advisor_board_golden.py` currently names `seat_key` as the sole sanctioned delta, with the same rule mirrored in `advisor_board/CONTRACTS.md` and `docs/advisor-board-capabilities-card.md`. REVIEWTRUTH intentionally adds typed result and prompt-lens output, so SL-1 must amend and freeze the normative expected-delta list in the golden test before implementation; SL-6 may mirror that already-frozen rule into its docs but cannot discover or repair it for the first time. A second compatibility scan confirmed five legacy expectations: `phase-loop-runtime/tests/test_advisor_board_research.py::InvocationAndCompatibilityTests::test_disabled_result_serializer_is_unchanged`, `phase-loop-runtime/tests/test_panel_invoker_spawn.py::ClaudeLegNativeAdapterRequestTest::test_native_agent_leg_request_rejects_fable_and_opus`, `phase-loop-runtime/tests/test_panel_native_fill_183.py::DeferredSeatSurfacesNativeFillRequest::test_board_deferred_seat_carries_request_with_seat_cognition`, `phase-loop-runtime/tests/test_panel_native_fill_183.py::DeferredSeatSurfacesNativeFillRequest::test_under_claude_code_requires_tui_adapter_even_without_local_cli`, and `phase-loop-runtime/tests/test_panel_native_fill_183.py::DefaultClaudeSeatNeverCarriesNativeFill::test_brief_ref_flows_into_the_request`. The final three are native-fill reversals: the first currently expects no request for the deferred Fable seat, the second expects no request even though the Claude Code host reaches `tui_adapter_required` before the false local-CLI support probe can govern native Task capability, and the third expects a supported Fable seat with a resolved `brief_ref` under Claude Code to carry no native request. All five must migrate tests-first under their full existing nodeids, retain their legacy/default assertions before the marker, assert the new contract under forced activation, switch automatically to those same new assertions after the exact production marker lands, and freeze every affected request/serializer field including the new identities and digests before SL-1 merges.

The native-fill seam was also rechecked directly. `SeatOutcomeRecord` already documents `seat_key` as explicitly non-unique and carries a unique FAB `seat_instance_id`, while `NativeAgentLegRequest` currently carries only optional seat/artifact/brief cognition and there is no closed `NativeAgentLegReport` binding surface. `test_panel_native_fill_183.py::DeferredSeatSurfacesNativeFillRequest::test_colliding_seat_keys_do_not_hide_a_failed_twin` already proves colliding `seat_key` values are legal. REVIEWTRUTH therefore cannot reuse `seat_key` as request identity: SL-1 freezes collision, retry/late-report, replay, cross-seat substitution, digest-substitution, and exactly-once-count falsifiers; SL-2 allocates one stable `seat_instance_id` per requested seat and fresh non-reused `request_id` plus `attempt_id` for every emission/retry; and SL-5 persists and reconstructs pending, superseded, consumed, and rejected attempt state without accepting a report twice.

## Interface Freeze Gates

- [ ] PC-REVIEWTRUTH-0 — The `agent-harness#398` capability disposition is stated in `docs/research/reviewtruth-leg-capability-ratification.md`, explicitly maintainer-ratified, merged separately before the tests-only landing, and binding on every later posture-assuming change. General roadmap execution authorization and panel approval are non-substitutes. The chronology verifier reads the record and landing metadata, rejects shallow or replacement-ref history, and proves the record/test/implementation ordering and conformance from a trusted full clone.
- [ ] PC-REVIEWTRUTH-1 — Chronology has two non-substitutable modes. The pre-implementation mode can pass immediately after the separate tests-only landing by proving disposition ancestry, distinct PR/head identity, PANELLED RED evidence, allowed test-only paths, and no production change; only that mode unblocks SL-2 through SL-5. The final mode runs only after the separately merged SL-2-through-SL-5 implementation PR and additionally requires a two-parent implementation landing whose first parent already contains the disposition and tests-only landings, a distinct implementation PR/head, no SL-1-owned path in `implementation^1..implementation^2` or the implementation PR range, and no SL-1 tests-only commit carried on the implementation branch. Same-branch, squash, rebase, direct-push, shallow, grafted, replacement-ref, or tests-in-range history fails final evidence but cannot deadlock pre-implementation dispatch.
- [ ] PC-REVIEWTRUTH-2 — Broad compatibility accounting is independent from phase-node accounting, separates marker deselections from skips, and begins with a contemporaneous observation rather than retroactive inference. Before any SL-1-owned file is edited, materialize the exact embedded bootstrap observer bytes at `.phase-loop/evidence/reviewtruth-baseline-observer.py`, require SHA-256 `b5fcd773ec6d14ebacc0aa84e25b0bb2b8a47a11a6860ba2b243028543bae223`, and run the exact operational command below once on the clean production-change-free pre-implementation base. The observer is launched by `/usr/bin/python3` beneath `env -i` and requires the complete initial environment to equal the exact seven-key allowlist `HOME`, `PATH`, `LANG`, `LC_ALL`, `PYTHONNOUSERSITE`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD`, and `PYTHONPATH` with the frozen values in the command; this rejects ambient `PYTEST_ADDOPTS`, `PYTEST_PLUGINS`, every `PHASE_LOOP_*` selector, `CI`, user-site packages, and every unlisted process key rather than merely failing to record them. It invokes one GREEN pytest process with exact argv `phase-loop-runtime/tests -q -m "not dotfiles_integration" -p no:cacheprovider --junitxml=<write-once observation>/broad.xml`. Its try-first hookwrapper records the complete canonical repo-relative item set before built-in marker selection and the selected item set after selection in that same process; its `pytest_deselected`, runtime-report, and collection-report hooks contemporaneously record the exact deselection multiset, each item's marker names, and legitimate item/module skip tuples and reasons. It fails unless `full - selected == pytest_deselected`, every difference member carries `dotfiles_integration`, no selected member carries it, all sets are duplicate-free, the broad run is GREEN, the output path is new, and HEAD, HEAD tree, index tree, and empty porcelain-v1-z status are byte-identical before and after.

  The same process attests the complete post-pytest environment, not a hand-picked subset. Suite initialization may add only `PHASE_LOOP_PROFILE_PLUGINS=phase_loop_runtime.dotfiles_profile_plugin:register_profile_commands` and `PHASE_LOOP_SKILL_SOURCE_PLUGINS=phase_loop_runtime.skill_sources_plugin:register_skill_sources`; `PHASE_LOOP_RUNNER_REPO_ROOT`, `PHASE_LOOP_CLAUDE_ROUTE`, `CI`, `PHASE_LOOP_REVIEWTRUTH_POST_PARSER_COLLECTION`, `PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH`, and `PHASE_LOOP_SKIP_GATE_A_SUITE` must remain absent. Both application entry-point groups `phase_loop_runtime.profile_commands` and `phase_loop_runtime.skill_sources` must be empty under `PYTHONNOUSERSITE=1`. The observer then resolves exactly one profile registrar and one skill-source provider from those two sanctioned opt-ins, requires their loaded module/callable source files to live beneath `phase-loop-runtime/src/phase_loop_runtime/`, records their byte digests, and records the provider's complete harness-to-root output; any extra registrar/provider, entry point, source outside the repo, selector value, absolute/extra root, or missing source fails before sealing. The write-once observation contains `full-nodeids.txt`, `selected-nodeids.txt`, `marker-deselected-nodeids.txt`, `legitimate-skips.json`, raw stdout/stderr, ordinary JUnit, raw plugin events, and a terminal canonical attestation that binds their byte counts/digests plus observation UUID, observer/plan/roadmap digests, exact `sys.orig_argv`, `/proc/self/cmdline`, internal pytest argv and their digests, the exact initial/post-pytest environment maps, every runtime selector and application entry-point group, the loaded application registrar/provider source/digest/root profile, PID/PPID/PGID/SID/UID/GID, boot ID and process-start ticks, CWD, Python executable/realpath/version/implementation/cache tag/prefixes, pytest/`_pytest`/`pluggy` module paths and file digests, pytest version, and every loaded pytest plugin's name/module/class/distribution/version/path/digest.

  After, not before, that observation is sealed, SL-1 authors `verify_reviewtruth_chronology.py` and independently parses the raw files. It must re-hash the exact embedded observer bytes and observation artifacts, recompute the full `REVIEWTRUTH_BROAD_PREIMPLEMENTATION_COLLECTED_NODEIDS`, selected `REVIEWTRUTH_BROAD_PREIMPLEMENTATION_SELECTED_NODEIDS`, exact `REVIEWTRUTH_BROAD_MARKER_DESELECTED_NODEIDS = full - selected`, legitimate `REVIEWTRUTH_BROAD_BASELINE_SKIP_TUPLES`, their counts and sorted-LF/canonical-JSON SHA-256 values, JUnit outcomes, command/runtime/provenance records, the full-minus-selected/deselection/marker relations, both complete environment maps, every forbidden-selector absence, both empty entry-point registries, the exact loaded application registrar/provider sources and digests, and the complete skill-source root mapping without trusting attestation-derived counts or summaries. The exact full and selected pre-edit sets remain frozen, not merely their counts: the immutable test/record surface retains their canonical compressed bytes plus counts/digests, while the explicit marker difference tuple and skip tuples remain readable literals. SL-1 also derives and freezes the only allowed post-SL-1 collection transformation: the pre-edit full/selected sets plus exactly the declared new REVIEWTRUTH nodeids, with migrated nodeids unchanged and exactly five new post-parser wrappers removed by the ordinary hook. Any unexplained environment key, selector/plugin/root value or source, entry point, nodeid, parametrization, marker, skip, pytest version/module, collection-capable plugin, or collection-hook fingerprint change is drift. Mutation tests independently inject each referenced initialization selector, an unknown environment key, an application entry point, an extra/changed plugin spec, an outside-repo plugin source, and a changed root mapping and require the observer or later parser to reject it. Absolute installation roots and Python 3.10/3.11/3.12 executable paths are retained as exact observation provenance but are not portable equality keys; fresh-clone CI and Gate A compare canonical repo-relative nodeids, source/module digests, versions, and the frozen collection-affecting plugin fingerprint, allowing only the explicitly frozen `-p no:cacheprovider` core-profile difference. The bootstrap observer itself is subtracted as the one exact externally supplied observation plugin; any other autoloaded or collection-affecting plugin is forbidden.

  After SL-1 is authored, broad default-premarker must report the disjoint union of exactly the unchanged marker baseline plus exactly the five hook-owned `REVIEWTRUTH_POST_PARSER_NODEIDS`, while its skip set is exactly the broad skip baseline UNION the non-post-parser `REVIEWTRUTH_DEFAULT_PREMARKER_SKIP_NODEIDS`; candidate and broad-final producer must report that same marker-baseline-plus-five deselection union and exactly the unchanged broad skip baseline. The conftest observer rejects nonempty pytest `--deselect`, canonicalizes source-root, CI-working-directory, and Gate-A copied-tree nodeids to the frozen repo-relative form, records built-in marker-filter and hook-owned wrapper categories separately, requires the hook itself to find/remove/notify exactly all five wrappers, and fails the session on any missing, extra, duplicate, arbitrary, category-drifted, plugin-drifted, or collection-drifted result. The plain frontmatter `automation.suite_command`, ordinary GitHub CI across Python 3.10/3.11/3.12, clean-room Gate A, and fresh-clone default suite use this self-contained committed freeze without run-local evidence, remain GREEN after the marker, and attest the immutable post-SL-1 full/selected set digests, marker baseline plus five wrappers, plugin profile, and applicable frozen skip accounting. A new, missing, renamed, newly passing, or drifted collection member, marker deselection, baseline skip, plugin, or hook; a phase skip surviving candidate/final; any `xfail`; a missing/extra/wrong hook deselection; any command-line `--deselect` or other arbitrary deselection; or any failure/error blocks. Every pushed implementation candidate runs the unmodified broad command from a fresh exact-head process, and its generated candidate XML is parsed before the golden, panel, or merge. Final broad producer uses the same ordinary arm and is parsed before exact final collection can be issued. This plan never claims five total broad deselections, never claims whole-suite zero skips, never asks a later parser to manufacture past provenance, and never requires a workflow edit.
- [ ] PC-REVIEWTRUTH-3 — SL-1 freezes a separate phase-selected contract. `PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1` forces the new production contract on the pre-implementation base without importing a missing symbol; otherwise non-post-parser tests use the exact production capability marker `REVIEWTRUTH_CAPABILITY_MARKER = "reviewtruth@1"` from `panel_invoker.py`. The immutable verifier freezes `REVIEWTRUTH_EXPECTED_NODEIDS`, the five-member `REVIEWTRUTH_POST_PARSER_NODEIDS`, and `REVIEWTRUTH_PHASE_NODEIDS = REVIEWTRUTH_EXPECTED_NODEIDS - REVIEWTRUTH_POST_PARSER_NODEIDS`, each with an exact count and sorted-LF SHA-256; the expected set includes every parametrized expansion, floor/train/golden migration, all five full compatibility nodeids, positive controls, and the five strict post-parser wrappers. `junit-run --mode default-premarker`, `activated-red`, and `candidate` invoke pytest with exactly `REVIEWTRUTH_PHASE_NODEIDS` and do not activate post-parser collection. Default-premarker phase JUnit contains that exact phase set: only the non-post-parser `REVIEWTRUTH_DEFAULT_PREMARKER_SKIP_NODEIDS` skip with the one frozen reason, while every migrated existing nodeid runs its legacy assertion branch. Activated-RED phase JUnit contains that same exact phase set, executes each `REVIEWTRUTH_ACTIVATED_RED_NODEIDS` member exactly once and fails only at its mapped raw `REVIEWTRUTH_RED_ANCHORS_BY_NODEID`, passes every positive control, and contains no post-parser wrapper or unrelated skip. For `activated-red` only, `junit-run` records pytest's required nonzero exit and returns control only after the literal XML path exists; it does not bless any failure, and the immediately following `junit --mode activated-red` parser is the sole GREEN/RED authority. Candidate phase JUnit contains exactly `REVIEWTRUTH_PHASE_NODEIDS` with zero phase skips, `xfail`, failures, errors, duplicates, or unexpected/missing nodeids. Only after the broad-final producer parser has emitted and verified its attestation may `junit-run --mode final` reject any inherited activation, set the exact test-owned collection activation, and select all `REVIEWTRUTH_EXPECTED_NODEIDS`; final phase JUnit must contain every expected nodeid exactly once, including all five strict wrappers, with zero phase skips, `xfail`, failures, errors, or deselections. Once SL-2 installs the marker, all migrated and production-dependent assertions switch automatically to the same new branch without test edits, but that marker never activates the post-parser wrappers. No implementation lane may edit tests, conftest, guards, selectors, nodeids, counts, set digests, anchors, parser modes, activation names/values, or skip/deselection reasons; the sole allowed collection-time environment branch is the exact SL-1-owned final-collection predicate, and no import or marker-import failure is permitted.
- [ ] PC-REVIEWTRUTH-4 — Candidate and final proof are process-bound and generation precedes parsing. Candidate phase and broad XML are both generated at literal runner-owned paths in a newly spawned repo-local process after proving `HEAD` equals the exact pushed implementation head and all imported `phase_loop_runtime` and tests/conftest paths and digests resolve beneath that worktree; only then may the frozen parser run in `candidate` mode against those exact two paths, and only its GREEN attestation may unblock golden, panel, or merge. Final evidence uses a different newly spawned repo-local process after proving `HEAD` equals the exact fetched canonical-main head containing the two-parent implementation landing; only SL-6-owned evidence/doc dirt may then exist. That child first generates broad-final producer XML through ordinary collection, whose observer attests exactly the frozen marker-filter baseline plus the hook's five frozen wrapper deselections in separate categories, then parses it in `broad-final-producer` mode. Only after that attestation is GREEN does the immutable `junit-run --mode final` reject a pre-set `PHASE_LOOP_REVIEWTRUTH_POST_PARSER_COLLECTION`, set it to the exact value `junit-run:final:v1` only in its pytest child, and generate phase-final XML whose five strict wrappers consume only already-existing non-self-referential inputs — the frozen pre-final SL-6 evidence document at `docs/research/reviewtruth-phase-verification.md` and the single canonical durable redacted transcript and smoke record at `docs/research/reviewtruth-real-panel-smoke.md`, each at its exact frozen digest, ledger and landing metadata, the phase default/RED/candidate and broad marker/skip baseline/default/candidate XML and parser attestations, and that broad-final XML and attestation — and never the phase-final XML or its digest, the final-mode parser attestation, the finalized record, the `final-record` attestation, or any closeout verdict; it then parses both exact XML paths in `final` mode. Only after that final parse does `verify_reviewtruth_evidence.py finalize-record` write the write-once post-parser durable record at `docs/research/reviewtruth-final-evidence-record.md`, recording the exact broad-final and phase-final XML digests, both parser-attestation digests, and the exact frozen `docs/research/reviewtruth-phase-verification.md` digest and the one frozen `docs/research/reviewtruth-real-panel-smoke.md` digest the live board and wrappers consumed; no pre-final doc is edited after its staging/review point. The separate minimal `final-record` verifier then recomputes every recorded digest from the artifact bytes and emits its attestation to `.phase-loop/evidence/reviewtruth-final-record-attestation.json` and the canonical ledger; its own result is never required inside the record it verifies, and no test wrapper may invoke `finalize-record` or `final-record` or read their outputs. The later Gate A `gate-a` reducer and its fresh internal attester likewise stay outside every wrapper and finalized-record input: they write only `.phase-loop/evidence/reviewtruth-gate-a-suite.{stdout,stderr,json}` and `.phase-loop/evidence/reviewtruth-gate-a-suite-attestation.json`, and only the canonical ledger closeout binds the terminal attestation. The four-seat closeout review and ledger closeout bind the finalized record digest, the `final-record` attestation, and the Gate A suite attestation before closeout, and every closeout verdict is written only to the canonical ledger, never into the record or any wrapper-consumed artifact. Each child emits its own PID/start-time, HEAD/ref, module/conftest paths, source digests, exact command, collection activation/deselection facts, XML path/digest, and parser-attestation path/digest. No invoking shell assigns `REVIEWTRUTH_JUNIT_XML` and expands that newly assigned value itself: task commands use literal paths, while Verification uses `env REVIEWTRUTH_JUNIT_XML=<literal> sh -c '... "$REVIEWTRUTH_JUNIT_XML"'` so expansion occurs only in the child shell after `env` has populated its environment. A TUI, daemon, worker, parent interpreter, or other process that loaded pre-edit `panel_invoker`, `runner`, `train_runner`, `train_ledger`, or related runtime modules may launch the child but may not attest the modified code or panel result itself.
- [ ] PC-REVIEWTRUTH-5 — `phase-loop-runtime/tests/conftest.py` owns the post-bootstrap executable dual-mode collection and deselection-provenance contract. It consumes only the committed literals/digests independently derived from the write-once pre-edit observation; it never claims to have observed the past. It freezes the exact pre-edit full/selected collection digests, their exact allowed post-SL-1 transformation, the exact five full repo-relative nodeids in `REVIEWTRUTH_POST_PARSER_NODEIDS`, the exact pre-edit marker-filter tuple `REVIEWTRUTH_BROAD_MARKER_DESELECTED_NODEIDS`, the legitimate skip tuples, the allowed source/CI versus Gate-A collection-plugin profiles, all counts/digests, the exact environment name `PHASE_LOOP_REVIEWTRUTH_POST_PARSER_COLLECTION`, the sole accepted value `junit-run:final:v1`, and the predicate `os.environ.get("PHASE_LOOP_REVIEWTRUTH_POST_PARSER_COLLECTION") == "junit-run:final:v1"`. Its try-first/try-last hooks canonicalize the full pre-selection and selected nodeids from source-root, `phase-loop-runtime/` working-directory, and Gate-A copied-tree collection; its `pytest_deselected` observer records built-in `-m "not dotfiles_integration"` deselections separately from the wrapper hook's notification and rejects a nonempty `--deselect` option or any arbitrary deselection source. In the ordinary broad arm, the wrapper hook runs after marker selection, requires all five exact wrappers still collected, removes exactly those items, calls `pytest_deselected` for exactly that list, and at session end requires the observed full/selected sets, collection-affecting plugin fingerprint, and deselection multiset to equal the frozen post-SL-1 collection and disjoint marker-baseline UNION wrapper tuple with exact per-category counts/digests. It never converts wrappers to skips and never keys on `REVIEWTRUTH_CAPABILITY_MARKER`, `PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH`, generic truthiness, CI, evidence-file presence, or a run-local baseline file. When the predicate is true, it removes none of the five; each wrapper independently requires the final runner/broad-final attestation before executing its strict assertion, so setting the environment value by hand cannot produce a vacuous pass. SL-1 freezes the hook file digest, observer-payload digest, collection/plugin profiles, all tuples/counts/digests, predicate, category reasons/accounting, final-runner activation, and mutation tests that kill bootstrap-byte/attestation/raw-artifact drift, full/selected-set drift, marker-baseline drift, a missing/renamed/extra wrapper, a truthy/wildcard env predicate, marker-driven collection, failure to notify `pytest_deselected`, external `--deselect`, arbitrary third-party/collection-capable plugin loading, category swapping, and final activation before broad-final attestation. Ordinary suite, GitHub CI, Gate A, default/broad/candidate/broad-final, and fresh-clone subprocess controls prove the immutable post-SL-1 full/selected collections, allowed plugin profile, marker baseline plus exactly five hook-owned deselections, and GREEN; a final-phase subprocess proves all five strict assertions execute exactly once with zero phase deselections. SL-2 through SL-6 may neither edit nor replace this hook.
- [ ] PC-REVIEWTRUTH-6 — Native-fill identity is non-colliding and exactly once. One board invocation allocates a unique stable `seat_instance_id` for every requested seat instance, including twins with the same non-unique `seat_key`. Every emitted `NativeAgentLegRequest` carries a fresh globally unique `request_id` and a fresh `attempt_id`; retry/re-emission keeps only that seat's `seat_instance_id` and allocates both other identities anew, never reusing or reviving an earlier tuple. The request and `NativeAgentLegReport` echo the exact `(request_id, seat_instance_id, attempt_id)` plus `seat_key`, `artifact_digest`, `brief_digest`, `lens_digest`, and `prompt_digest`. `bind_native_agent_leg_result()` can consume exactly one current pending attempt whose entire identity/digest tuple matches and whose report is terminal; successful consumption atomically closes that attempt, updates only its one seat instance, and can increase `PanelResult.reviewed_seat_count` at most once. Unknown request, late superseded attempt, stale prior-board attempt, replayed consumed report, cross-seat substitution, colliding-seat substitution, any identity/digest mismatch, or non-terminal report is rejected with a typed binding disposition, cannot mutate a leg or raw/grounded count, and cannot bind a current retry. The canonical ledger durably records metadata-only emitted/pending/superseded/consumed/rejected transitions and reconstructs those sets before native fill resumes, so process restart cannot forget a consumed identity or re-inflate the reviewed count.
- [ ] IF-0-REVIEWTRUTH-1 — `REVIEWTRUTH_CAPABILITY_MARKER = "reviewtruth@1"` is the production activation marker installed in `panel_invoker.py`; it activates SL-1's immutable production assertions but never the post-parser collection hook. `PanelLegOutcome` is the exact closed vocabulary `reviewed | unavailable | errored | timed_out | refused | capped | empty` carried by `PanelLegResult.outcome`, independent of `PanelLegResult.text`; `PanelLegResult.required` and `PanelLegResult.degraded` are orthogonal typed fields; and the durable `SeatOutcomeRecord.degraded` field is orthogonal to its lifecycle status, defaults false for legacy records, and is omitted on legacy/default serialization only where byte-neutral compatibility requires it. `PanelResult.reviewed_seat_count` is the raw count of identity-bound legs whose outcome is `reviewed`; it does not perform grounding. `PanelLegResult.prompt_lens_digest` is the frozen per-seat carrier for EC-REVIEWTRUTH-5: it is nonempty only when the exact rendered prompt bytes carried the declared lens and binds the declared lens to those bytes. A Fable/Opus seat deferred under a native-capable Claude host produces a `NativeAgentLegRequest` with stable unique `seat_instance_id`, fresh unique `request_id` and `attempt_id`, `seat_key`, `model`, `effort`, `lens`, artifact/brief references, exact `artifact_digest`, `brief_digest`, `lens_digest`, `prompt_digest`, and the same resolved review instructions as CLI seats. `NativeAgentLegReport` echoes that entire identity/digest tuple plus its terminal outcome and payload. Only `bind_native_agent_leg_result()` consuming a valid current pending report exactly once can replace that one seat instance's unfilled outcome and increase the raw count; it returns the typed binding disposition frozen by PC-REVIEWTRUTH-6 for every rejection. `SeatOutcomeRecord` and canonical native-fill ledger events carry the request/seat/attempt identities and content digests needed for lossless reconstruction without raw review text. `ReviewGrounding` and `GovernedBoardEvidence.grounded_reviewed_seats` are the single owned filter over raw reviewed legs; ratification passes that grounded collection to pure `classify_board_delivery(reviewed, target=4, floor=3)`, which returns exactly `full | floor_only | below_floor`, and derives vendor/lens facts only from that collection and its prompt/lens digests, never static `Seat` shape. The train approval schema serializes grounded `delivery_state` plus the exact current `review_policy_version`; `REVIEW_POLICY_VERSION` increments from `usable-reviewer-floor@1` to an explicit grounding/three-state policy identity. Train resume may skip review only when the record is `approved`, its policy version exactly equals the current version, and its typed delivery state is gate-authorizing under the train merge policy. A missing or old version, missing delivery state, a pre-migration/count-only record, `usable_reviewers=2`, or any delivery state derived from raw ungrounded usable legs forces re-review and cannot authorize a merge; valid current-policy grounded FULL/FLOOR-ONLY follows the explicit train gate policy, while BELOW-FLOOR blocks. `timed_out`, `capped`, and `empty` remain retryable and never enter the raw count; `refused` is distinct from unavailability; grounding and material-substance remain independent ratification/gate properties rather than outcome variants. BELOW-FLOOR is a classification, not a universal action: governed pre-merge, merge-class, and CLI consumers governed by EC-REVIEWTRUTH-1/4 block it, while `plan-ratify` and `design-ratify` retain their existing degraded-shortfall policy unless a roadmap criterion explicitly changes it.

## Lane Index & Dependencies

SL-0 — Capability design and maintainer ratification record
  Depends on: (none)
  Blocks: SL-1, SL-2, SL-3, SL-4, SL-5, SL-6
  Parallel-safe: no
SL-1 — Tests-first falsifier lane and RED baseline
  Depends on: SL-0
  Blocks: SL-2, SL-3, SL-4, SL-5, SL-6
  Parallel-safe: no
SL-2 — Typed seat outcome, lens prompt, and native-fill binding
  Depends on: SL-0, SL-1
  Blocks: SL-3, SL-4, SL-5, SL-6
  Parallel-safe: no
SL-3 — Governed classifier, grounding, and substantive-material guard
  Depends on: SL-0, SL-1, SL-2
  Blocks: SL-4, SL-5, SL-6
  Parallel-safe: yes
SL-4 — Ratification facts and three-state delivery policy
  Depends on: SL-0, SL-1, SL-2, SL-3
  Blocks: SL-5, SL-6
  Parallel-safe: no
SL-5 — Production gate, repair, lifecycle ledger, and native driver integration
  Depends on: SL-0, SL-1, SL-2, SL-3, SL-4
  Blocks: SL-6
  Parallel-safe: no
SL-6 — REVIEWTRUTH evidence, documentation, and verification reducer
  Depends on: SL-0, SL-1, SL-2, SL-3, SL-4, SL-5
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Capability Design And Maintainer Ratification Record

- **Scope**: Decide the `agent-harness#398` review-seat capability posture, obtain maintainer ratification, and land the durable disposition on the target before any posture-assuming implementation begins.
- **Owned files**: `docs/research/reviewtruth-leg-capability-ratification.md`
- **Interfaces provided**: `REVIEWTRUTH-capability-ratification`
- **Interfaces consumed**: none
- **Parallel-safe**: no; this is a human decision and ancestry gate whose committed record must precede all tests and production lanes.
- **Tasks**:
  - test: SL0-T1 — Define disposition falsifiers for read-only inspection, throwaway-copy probes, and narrower variants while preserving the real-tree arbitrary-execution prohibition.
  - impl: SL0-T2 — Inspect target protection, obtain the required PR-only and two-parent posture, secure panel and explicit maintainer ratification, and merge the standalone metadata-only disposition record.
  - verify: SL0-T3 — Prove the ratified decision, dedicated merged record, canonical-main ancestry, and absence of posture-assuming implementation; keep downstream lanes blocked until the verifier passes.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command | Work |
|---|---|---|---|---|---|---|
| SL0-T1 | test | (none) | `docs/research/reviewtruth-leg-capability-ratification.md` | disposition falsifiers | `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k ec_reviewtruth_15_capability_ratification` after SL-1 lands the verifier wrapper | Write alternatives and falsifiers for read-only artifact inspection, bounded probes against a throwaway staged copy, and any narrower ratified variant; preserve the invariant that no seat receives arbitrary execution against the real tree. |
| SL0-T2 | impl | SL0-T1 | `docs/research/reviewtruth-leg-capability-ratification.md` | none | `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k ec_reviewtruth_15_capability_ratification` after SL-1 lands the verifier wrapper | Inspect target protection with read-only `gh` metadata, obtain the roadmap-required PR-only and two-parent landing protection through the approved admin path, panel the disposition, obtain explicit maintainer ratification, and merge only this durable record in its own PR. Record the ratified posture, record commit and PR, panel digest and outcomes, and protection observation without secrets. `agent-harness#400`, blanket roadmap execution approval, plan review, and issue discussion do not satisfy this task. |
| SL0-T3 | verify | SL0-T2 | `docs/research/reviewtruth-leg-capability-ratification.md` | none | `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k ec_reviewtruth_15_capability_ratification` | After the verifier wrapper exists, require a stated decision, explicit maintainer ratification, a dedicated server-recorded merged PR, the record commit reachable from canonical `main`, and no posture-assuming implementation in the record landing. Until then, manually inspect the same fields and keep every downstream lane blocked. |

### SL-1 — Tests-First Falsifier Lane And RED Baseline

- **Scope**: On the exact clean pre-edit base, execute the exact-digest external bootstrap observer in one controlled pytest process; then land the complete REVIEWTRUTH falsifier and compatibility migration suite, deterministic marker activation, CI-safe dual-mode post-parser collection, non-colliding native request/attempt identity tests, structured JUnit contract, and panel-reviewed RED record before any production file changes.
- **Owned files**: `phase-loop-runtime/tests/conftest.py`, `phase-loop-runtime/tests/test_reviewtruth_phase.py`, `phase-loop-runtime/tests/test_train_merge.py`, `phase-loop-runtime/tests/test_governed_cross_vendor_floor_358.py`, `phase-loop-runtime/tests/test_advisor_board_golden.py`, `phase-loop-runtime/tests/test_advisor_board_research.py`, `phase-loop-runtime/tests/test_panel_invoker_spawn.py`, `phase-loop-runtime/tests/test_panel_native_fill_183.py`, `phase-loop-runtime/scripts/verify_reviewtruth_chronology.py`, `docs/research/reviewtruth-red-baseline.md`
- **Interfaces provided**: `REVIEWTRUTH-bootstrap-observation`, `REVIEWTRUTH-tests-first-baseline`, `REVIEWTRUTH-preimplementation-chronology`, `REVIEWTRUTH-evidence-wrappers`, `REVIEWTRUTH-post-parser-collection-contract`, `REVIEWTRUTH-native-fill-identity-contract`, `REVIEWTRUTH-golden-delta-baseline`, `REVIEWTRUTH-tdd-activation`, `REVIEWTRUTH-junit-contract`, `REVIEWTRUTH-broad-compatibility-gate`
- **Interfaces consumed**: `REVIEWTRUTH-capability-ratification`
- **Parallel-safe**: no; this lane must start from the separately merged disposition record and land as a tests/evidence-only, production-change-free change before every implementation lane rebases from that target tip.
- **Tasks**:
  - test: SL1-T1 — Before any SL-1 mutation, materialize and hash-check the exact embedded observer, then execute its one-process GREEN broad observation to freeze the full collected set, selected set, exact marker difference, legitimate skips, JUnit/raw output, argv, HEAD/tree/clean/process, Python/module/plugin provenance, and artifact digests; only afterward add every named REVIEWTRUTH falsifier plus mutation-specific injection-anchor and positive-control coverage, migrate every live floor-2, train-resume, serializer, native-request, and all three native-fill expectations, freeze collision/retry/late/replay/cross-seat/exactly-once report tests, and freeze the sanctioned golden delta, marker guard, dual-mode conftest hook, independent phase/broad nodeid sets/counts/digests, raw RED anchors, the exact marker deselection baseline plus five separately owned post-parser deselections, executable JUnit runner/parser modes, both chronology modes, and final evidence wrappers.
  - impl: SL1-T2 — Independently test the exact bootstrap bytes and parser against synthetic repos and tampered observations; recompute and freeze the pre-edit full/selected collections, marker-deselection and broad-skip baselines, provenance, and allowed post-SL-1/plugin-profile transformations as separate categories; then generate and parse default phase/broad JUnit and activated phase JUnit in the stated order, prove ordinary-suite/final-collection dual mode and deselection provenance plus all native-identity falsifiers, panel the exact tests-only digest, and merge the dedicated tests-only landing with all required observer/plan/base/tree, conftest/set, marker/raw/XML, parser-attestation, panel, and landing digests recorded.
  - verify: SL1-T3 — Prove record ancestry, PANELLED and RED status, restricted landing paths, exact observer bytes and contemporaneous observation, independently reproduced full/selected/difference/skip/provenance accounting, exact phase default/activated accounting, exact broad marker/skip baseline and default hook/plugin accounting, native identity/digest falsifiers, fired injection anchors, and no production changes before implementation lanes unblock.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command | Work |
|---|---|---|---|---|---|---|
| SL1-T1 | test | SL-0 | all ten SL-1 owned paths except `docs/research/reviewtruth-red-baseline.md`; ignored `.phase-loop/evidence/reviewtruth-baseline-observer.py` and `.phase-loop/evidence/reviewtruth-baseline-preimplementation/**` are runner evidence, not landing paths | `test_ec_reviewtruth_1_*` through `test_ec_reviewtruth_15_*`; exact bootstrap-byte, synthetic observer, parser-tamper, hook mutation/subprocess, and source/CI/Gate-A collection/plugin controls; EC-14 duplicate-`seat_key`, retry/late, stale, replay, cross-seat/collision/digest substitution, and exactly-once-count controls; the amended EC-6 golden expected-delta assertions; the migrated `agent-harness#358` and train-resume controls; all five full existing compatibility nodeids named by this plan; immutable chronology, live-panel, evidence, collection, and JUnit contracts | the exact three operational bootstrap materialize/collect/parse commands and then the default/activated/golden commands in `## Verification`, in displayed order | Run the exact observer materialization and one-process collection before editing any SL-1 file. Require exact observer, plan, roadmap, clean HEAD/tree/index, process, command/Python/module/plugin, raw output/JUnit, full/selected/difference, skip, and artifact attestations. Only after the write-once observation exists may the ten owned paths be authored. Freeze canonical compressed `REVIEWTRUTH_BROAD_PREIMPLEMENTATION_COLLECTED_NODEIDS` and `REVIEWTRUTH_BROAD_PREIMPLEMENTATION_SELECTED_NODEIDS`; readable literal `REVIEWTRUTH_BROAD_MARKER_DESELECTED_NODEIDS`, `REVIEWTRUTH_BROAD_BASELINE_SKIP_TUPLES`, `REVIEWTRUTH_EXPECTED_NODEIDS`, `REVIEWTRUTH_PHASE_NODEIDS`, `REVIEWTRUTH_POST_PARSER_NODEIDS`, `REVIEWTRUTH_NEW_NODEIDS`, `REVIEWTRUTH_MIGRATED_NODEIDS`, `REVIEWTRUTH_DEFAULT_PREMARKER_SKIP_NODEIDS`, `REVIEWTRUTH_ACTIVATED_RED_NODEIDS`, and `REVIEWTRUTH_RED_ANCHORS_BY_NODEID`; all counts/digests/reasons; exact allowed post-SL-1 collection transformation; and source/CI versus Gate-A collection-plugin profiles. Freeze the five wrappers exactly as `phase-loop-runtime/tests/test_reviewtruth_phase.py::test_ec_reviewtruth_0_tdd_chronology`, `phase-loop-runtime/tests/test_reviewtruth_phase.py::test_ec_reviewtruth_9_live_panel_inspection`, `phase-loop-runtime/tests/test_reviewtruth_phase.py::test_reviewtruth_chronology_all`, `phase-loop-runtime/tests/test_reviewtruth_phase.py::test_reviewtruth_evidence_all`, and `phase-loop-runtime/tests/test_reviewtruth_phase.py::test_reviewtruth_final_evidence_all`. Independently test observer digest/preconditions and parser rejection of every tampered provenance/artifact/set/reason/plugin field. Preserve the exact dual-mode hook, wrapper input boundary, legacy/forced/marker compatibility branches, native identity protocol, activated-RED authority, chronology modes, and all prior acyclic finalization constraints. |
| SL1-T2 | impl | SL1-T1 | `docs/research/reviewtruth-red-baseline.md` | bootstrap-byte/parser mutation tests and synthetic observer subprocess controls | the exact ordered SL1-T1 commands | From the target tip that already contains the separate disposition record, execute the three operational bootstrap commands in `## Verification` before any SL-1 edit. After authoring, independently test that the embedded bytes hash to `b5fcd773ec6d14ebacc0aa84e25b0bb2b8a47a11a6860ba2b243028543bae223`, the observer refuses dirty/tampered/pre-existing-output/non-allowlisted-environment/ambient-selector/application-entry-point runs, and the parser kills altered HEAD/tree/process/argv/environment/selector/application-plugin/source-root/pytest-plugin/artifact/JUnit/full/selected/difference/skip data. Recompute the exact pre-edit full and selected collections, marker difference tuple, legitimate skip tuples, raw artifact digests, exact initial/post-pytest environment maps, empty application entry-point groups, loaded registrar/provider source digests and root mapping, and portable collection-plugin fingerprint; freeze their canonical bytes, counts, and digests plus the only allowed new-nodeid/five-wrapper and Gate-A `no:cacheprovider` transformations. Then run the default phase/broad and activated phase commands in exact order. Default phase JUnit contains exactly `REVIEWTRUTH_PHASE_NODEIDS`, with only the exact non-post-parser phase-default set skipped and every migrated nodeid running its legacy branch; broad default reports exactly the frozen post-SL-1 full/selected collection, disjoint marker baseline UNION five hook-owned wrappers, allowed plugin profile, and skips equal to broad skip baseline UNION phase-default. Activated phase JUnit contains no wrapper, executes every frozen falsifier once, fails only at its raw RED anchor, passes every positive control, and contains no unrelated skip. Source-root, CI Python 3.10/3.11/3.12, Gate-A copied-tree, and fresh-clone subprocess controls prove collection/plugin portability and reject explicit `--deselect`, arbitrary/plugin-added deselection, category substitution, marker/full/selected/plugin drift, and a missing/extra hook wrapper. Native controls preserve every prior collision/retry/late/stale/replay/cross-seat/digest/exactly-once assertion. Panel only after all parser attestations exist; retain raw observation/XML and every observer, plan, provenance, conftest, set/category, XML, and parser-attestation digest. Merge only the ten lane-owned production-free paths, with the ignored bootstrap observation bound by digest in `reviewtruth-red-baseline.md`. |
| SL1-T3 | verify | SL1-T2 | all ten SL-1 owned paths | pre-implementation chronology, bootstrap trust, activation, collection, JUnit, native-identity, and immutable-boundary verification | `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k reviewtruth_preimplementation_chronology_all` | Prove the disposition record was already on the tests-only landing's first parent, the tests-only landing has its own server-recorded two-parent PR/head identity, the landing is PANELLED and RED, its diff is restricted to these ten paths, and no production file changed. Prove the exact embedded observer bytes/digest were panel-bound and ran before every SL-1 mutation; the single recorded process contemporaneously observed the exact full/selected/difference/skip/JUnit data on one clean HEAD/tree/index with exact argv and Python/pytest/module/plugin provenance; and the post-edit parser independently reproduces every relation/count/digest from raw artifacts. Prove the frozen pre-edit and allowed post-SL-1 full/selected collections, marker difference, legitimate skips, and source/CI versus Gate-A plugin profiles; exact phase default/activated outcomes; broad default marker baseline UNION five hook-owned deselections; and skip accounting. Explicit/external/arbitrary/category-swapped deselection, observer/raw/attestation drift, marker/full/selected/plugin/hook drift, and unapproved plugin loading controls fail. Preserve the exact final collection predicate, all five compatibility migrations, every native identity falsifier, every RED anchor and positive control, and all ten immutable path digests. This check intentionally requests no future implementation metadata; SL-2 through SL-5 remain blocked until it passes on canonical `main`. |

### SL-2 — Typed Seat Outcome, Lens Prompt, And Native-Fill Binding

- **Scope**: Publish IF-0-REVIEWTRUTH-1 in the single-writer panel runtime, bind fillable-seat versus lens-distinct-backfill composition, and make seat cognition, grounding inputs, retry state, and native-result binding explicit while matching SL-1's frozen sanctioned golden delta and preserving every non-sanctioned legacy behavior.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py`
- **Interfaces provided**: `IF-0-REVIEWTRUTH-1`, `PanelLegOutcome`, `PanelLegResult.outcome`, `PanelLegResult.required`, `PanelLegResult.degraded`, `PanelLegResult.prompt_lens_digest`, `PanelResult.reviewed_seat_count`, `SeatOutcomeRecord.degraded`, `NativeAgentLegRequest.request_id`, `NativeAgentLegRequest.seat_instance_id`, `NativeAgentLegRequest.attempt_id`, `NativeAgentLegReport`, `NativeAgentLegBindingDisposition`, `bind_native_agent_leg_result()`
- **Interfaces consumed**: `REVIEWTRUTH-capability-ratification`, `REVIEWTRUTH-tests-first-baseline`, `REVIEWTRUTH-preimplementation-chronology`, `REVIEWTRUTH-native-fill-identity-contract`, `REVIEWTRUTH-golden-delta-baseline`, `REVIEWTRUTH-tdd-activation`, `REVIEWTRUTH-junit-contract`
- **Parallel-safe**: no; this lane is the sole writer for `panel_invoker.py` and combines the roadmap's lane-A freeze with the low-level lane-C/lane-D prompt and native-fill seams.
- **Tasks**:
  - test: SL2-T1 — Consume the landed outcome, lens, native-fill, collision, retry/late/stale/replay/cross-seat/exactly-once, grounding, capability, and golden falsifiers; confirm `timed_out` is retry-not-count and ratified posture governs launch.
  - impl: SL2-T2 — Implement typed outcomes, orthogonal lifecycle flags, the rendered-prompt lens carrier, boundary mapping, lens-bound native requests, stable seat-instance plus fresh request/attempt identities, strict one-pending-attempt terminal report binding, retry semantics, typed rejection diagnostics, the exact SL-1-sanctioned additive delta, and byte-neutral non-sanctioned behavior.
  - verify: SL2-T3 — Prove outcome-vs-text behavior, spawn failure handling, composition and lens propagation, native collision safety, fresh retry identities, late/stale/replay/cross-seat rejection, exactly-once count, posture conformance, and exact compliance with the frozen golden delta before any downstream implementation work or landing decision.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command | Work |
|---|---|---|---|---|---|---|
| SL2-T1 | test | SL-0, SL-1 | `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py` | consume landed EC-2, EC-3, EC-4, EC-5, EC-6, EC-7, EC-12, EC-14, golden, serializer, native-request, all three native-fill migrations, collision, retry/late/stale/replay/cross-seat/digest substitution, and exactly-once-count tests without editing | `env PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_reviewtruth_phase.py -q -k reviewtruth_sl2`<br>`env PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_advisor_board_research.py::InvocationAndCompatibilityTests::test_disabled_result_serializer_is_unchanged phase-loop-runtime/tests/test_panel_invoker_spawn.py::ClaudeLegNativeAdapterRequestTest::test_native_agent_leg_request_rejects_fable_and_opus phase-loop-runtime/tests/test_panel_native_fill_183.py::DeferredSeatSurfacesNativeFillRequest::test_board_deferred_seat_carries_request_with_seat_cognition phase-loop-runtime/tests/test_panel_native_fill_183.py::DeferredSeatSurfacesNativeFillRequest::test_under_claude_code_requires_tui_adapter_even_without_local_cli phase-loop-runtime/tests/test_panel_native_fill_183.py::DefaultClaudeSeatNeverCarriesNativeFill::test_brief_ref_flows_into_the_request -q`<br>`env PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_advisor_board_golden.py -q` | Confirm the focused SL-2 tests and all five compatibility migrations fail at their frozen raw RED anchors on the pre-marker base. The three full native-fill nodeids must fail on the new request expectation and exact identity/digest shape; `DeferredSeatSurfacesNativeFillRequest::test_under_claude_code_requires_tui_adapter_even_without_local_cli` must prove the false local-CLI support result does not suppress a native request on a detected Claude Code host, and `DefaultClaudeSeatNeverCarriesNativeFill::test_brief_ref_flows_into_the_request` must additionally prove the request carries the resolved `brief_ref`, matching resolved instructions, and matching brief/prompt digests rather than merely becoming non-`None`. Require twins with one duplicate `seat_key` to receive distinct stable seat-instance identities; retry to allocate new request/attempt identities; old/unknown/stale/replayed/cross-seat/collision/digest-substituted reports to be rejected without mutation; and a valid report to increment only its own seat exactly once. Confirm the injected `timed_out` value reaches retry-not-count without implementing LEGLIFE timeout enforcement and establish the ratified capability posture as the launch-policy input. No later-lane or final wrapper is selected. |
| SL2-T2 | impl | SL2-T1 | `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py` | none | `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_reviewtruth_phase.py -q -k reviewtruth_sl2`<br>`PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_advisor_board_research.py::InvocationAndCompatibilityTests::test_disabled_result_serializer_is_unchanged phase-loop-runtime/tests/test_panel_invoker_spawn.py::ClaudeLegNativeAdapterRequestTest::test_native_agent_leg_request_rejects_fable_and_opus phase-loop-runtime/tests/test_panel_native_fill_183.py::DeferredSeatSurfacesNativeFillRequest::test_board_deferred_seat_carries_request_with_seat_cognition phase-loop-runtime/tests/test_panel_native_fill_183.py::DeferredSeatSurfacesNativeFillRequest::test_under_claude_code_requires_tui_adapter_even_without_local_cli phase-loop-runtime/tests/test_panel_native_fill_183.py::DefaultClaudeSeatNeverCarriesNativeFill::test_brief_ref_flows_into_the_request -q`<br>`PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_advisor_board_golden.py -q` | Install the exact `REVIEWTRUTH_CAPABILITY_MARKER = "reviewtruth@1"` before relying on default new assertions. Add the closed lowercase outcome contract and orthogonal `required` and `degraded`; extend `SeatOutcomeRecord` with orthogonal `degraded`; map legacy statuses at the boundary; remove text-derived seat classification; preserve diagnostics; thread each declared lens into the exact CLI/native rendered prompt and bind `prompt_lens_digest` to those bytes; distinguish a natively fillable seat from a lens-distinct backfill; emit native Fable/Opus requests only on a declared native-capable host under the ratified posture, with detected Claude Code native capability independent of a local CLI support probe that the deferred path does not consume. Allocate a unique stable `seat_instance_id` for each requested board seat even when `seat_key` collides; allocate fresh unique `request_id` and `attempt_id` for every emission and retry; and carry the exact resolved artifact, `brief_ref`, review instructions, and `artifact_digest`/`brief_digest`/`lens_digest`/`prompt_digest` through the request and terminal report. Maintain an explicit pending-attempt table keyed by the complete identity tuple. `bind_native_agent_leg_result()` must atomically consume exactly one matching current terminal report, update only its seat instance, and return the frozen typed disposition; reject unknown, late superseded, stale prior-board, replayed consumed, cross-seat/colliding-seat, identity/digest-mismatched, and non-terminal reports without mutating any leg or count. Retry missing, empty, capped, or timed-out attempts by superseding the pending attempt and allocating a new request/attempt pair while preserving only the seat-instance identity; a late old report can never bind the retry. Count raw identity-bound `reviewed` outcomes without claiming grounding and at most once per seat instance. Implement only the additive result/prompt/request/report changes frozen in SL-1's sanctioned-delta list and preserve all non-sanctioned legacy serializer, launch, ordering, status, text, detail, and `seat_key` behavior. Do not edit the tests, conftest, or their guards to obtain GREEN. |
| SL2-T3 | verify | SL2-T2 | `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py` | none | the three default marker-driven SL2-T2 commands | Require all focused commands GREEN on the exact lane tip while later-lane falsifiers may remain RED and are not selected. Prove marker-driven automatic activation, outcome-vs-text, spawn-raise, fillable-seat composition, the frozen serializer migration, Fable/Opus request migration, all three under-Claude-Code Fable native-fill reversals under their unchanged nodeids, local-CLI-probe independence on the detected Claude Code path, resolved `brief_ref`/instructions and all four content digests, rendered-prompt lens carrier and blank-lens negative case, stable unique seat-instance identity under duplicate `seat_key`, fresh non-reused request/attempt identities on retry, typed rejection and no mutation for unknown/late/stale/replayed/cross-seat/collision/digest-substitution reports, exactly-once consumption/count, dropped-report behavior, orthogonal durable degraded state, posture conformance, raw-count semantics, exact sanctioned additions, and byte-neutral non-sanctioned behavior. |

### SL-3 — Governed Classifier, Grounding, And Substantive-Material Guard

- **Scope**: Consume typed outcomes in governed review, own the single artifact-grounding and material helper surfaces, apply them on SL-3-owned governed-review/FAB paths, and publish grounded evidence for gate-specific and train consumers.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/governed_review.py`, `phase-loop-runtime/src/phase_loop_runtime/governed_bundle.py`, `phase-loop-runtime/src/phase_loop_runtime/fab_producer.py`
- **Interfaces provided**: `ReviewGrounding`, `classify_review_grounding()`, `review_material_issue()`, `GovernedBoardEvidence`, `GovernedBoardEvidence.grounded_reviewed_seats`
- **Interfaces consumed**: `REVIEWTRUTH-capability-ratification`, `REVIEWTRUTH-tests-first-baseline`, `REVIEWTRUTH-golden-delta-baseline`, `REVIEWTRUTH-tdd-activation`, `IF-0-REVIEWTRUTH-1`, `PanelLegResult.outcome`, `PanelLegResult.prompt_lens_digest`, `PanelResult.reviewed_seat_count`
- **Parallel-safe**: yes with respect to file ownership, but SL-4 consumes this lane's grounded evidence and therefore starts only after SL-3; any scheduler-owned worktree remains under the same selected author vendor.
- **Tasks**:
  - test: SL3-T1 — Consume the landed outcome, grounding, refusal, repo-substitution, and material falsifiers, including valid filename and substantive-material positive controls.
  - impl: SL3-T2 — Base findings on typed outcomes, publish one staged-byte grounding filter and one shared material helper, and apply them only on owned governed-review/FAB paths for downstream gate and train consumption.
  - verify: SL3-T3 — Prove grounding and refusal behavior, substitution detection, owned-path empty/elided guards, retained FAB behavior, healthy positive controls, reusable helper outputs for SL-4/SL-5, and continued EC-REVIEWTRUTH-6 compliance.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command | Work |
|---|---|---|---|---|---|---|
| SL3-T1 | test | SL-0, SL-1, SL-2 | `phase-loop-runtime/src/phase_loop_runtime/governed_review.py`, `phase-loop-runtime/src/phase_loop_runtime/governed_bundle.py`, `phase-loop-runtime/src/phase_loop_runtime/fab_producer.py` | consume landed EC-2, EC-3, EC-6, EC-12, and EC-13 tests without editing | `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_reviewtruth_phase.py -q -k reviewtruth_sl3`<br>`PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_advisor_board_golden.py -q` | On the marker-present partial implementation, require the focused SL-3 falsifiers still RED at their frozen anchors before editing SL-3, while the inherited golden remains GREEN. Require raised or unusable legs not to manufacture BLOCK findings; only one artifact-grounding classifier to produce `grounded_reviewed_seats`; non-inspection, silent repo substitution, SHA mismatch, or missing prompt-lens proof to filter the affected seat; hyphenated and digit-bearing filenames to remain valid; and empty, sentinel, or binary-elided material to block while substantive material passes. |
| SL3-T2 | impl | SL3-T1 | `phase-loop-runtime/src/phase_loop_runtime/governed_review.py`, `phase-loop-runtime/src/phase_loop_runtime/governed_bundle.py`, `phase-loop-runtime/src/phase_loop_runtime/fab_producer.py` | none | the focused SL3-T1 commands | Rewrite governed findings around typed outcome plus `classify_review_grounding()`. Define grounding as evidence derived from staged artifact bytes, not a filename regex, and publish the resulting grounded reviewed collection without rewriting the raw `PanelResult.reviewed_seat_count`. Share the existing FAB material predicate through `governed_bundle.review_material_issue()` and apply it on this lane's governed-review and FAB paths independent of the FAB flag. Leave CLI, governed planning, pre-merge, runner, and train bundle/review/resume wiring explicitly to SL-5 as consumers of these helpers. Do not alter the frozen golden, tests, activation guard, or sanctioned-delta list. |
| SL3-T3 | verify | SL3-T2 | `phase-loop-runtime/src/phase_loop_runtime/governed_review.py`, `phase-loop-runtime/src/phase_loop_runtime/governed_bundle.py`, `phase-loop-runtime/src/phase_loop_runtime/fab_producer.py` | none | the focused SL3-T1 commands | Require both focused commands GREEN on the exact lane tip while later-lane falsifiers remain unselected. Prove the single grounding implementation, refusal, repo-substitution detection, prompt-lens proof propagation, empty/elided guards on owned non-FAB paths, retained FAB behavior, healthy non-empty positive controls, stable helper results for downstream delivery/vendor/lens, gate, and train consumers, and no EC-REVIEWTRUTH-6 regression. |

### SL-4 — Ratification Facts And Three-State Delivery Policy

- **Scope**: Consume SL-3's grounded reviewed collection, derive delivery/vendor/lens facts without a second grounding implementation, and expose a pure FULL, FLOOR-ONLY, and BELOW-FLOOR classification without changing gate policy.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/ratification_policy.py`
- **Interfaces provided**: `BoardDeliveryState`, `classify_board_delivery()`, `BoardFacts.delivery_state`, `BoardFacts.reviewed_seat_count`
- **Interfaces consumed**: `REVIEWTRUTH-capability-ratification`, `REVIEWTRUTH-tests-first-baseline`, `REVIEWTRUTH-golden-delta-baseline`, `REVIEWTRUTH-tdd-activation`, `IF-0-REVIEWTRUTH-1`, `PanelLegResult.outcome`, `PanelLegResult.prompt_lens_digest`, `PanelResult.reviewed_seat_count`, `ReviewGrounding`, `classify_review_grounding()`, `GovernedBoardEvidence`, `GovernedBoardEvidence.grounded_reviewed_seats`
- **Parallel-safe**: no; file ownership is disjoint from SL-3, but this lane consumes SL-3's grounded evidence and may not start from prose order alone.
- **Tasks**:
  - test: SL4-T1 — Cover FULL, FLOOR-ONLY, and BELOW-FLOOR, typed shortfall, lens coverage, reviewed-no-findings counting, and retryable outcomes that never count.
  - impl: SL4-T2 — Derive vendor, lens, and delivery facts only from SL-3's grounded reviewed seats, persist state and shortfall, and keep classification pure for gate-specific consumers.
  - verify: SL4-T3 — Prove all three classifications, shortfall propagation, no silent FULL rendering, load-bearing prompt-lens proofs, reviewed-no-findings separation, unchanged plan/design degraded policy, and continued EC-REVIEWTRUTH-6 compliance.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command | Work |
|---|---|---|---|---|---|---|
| SL4-T1 | test | SL-0, SL-1, SL-2, SL-3 | `phase-loop-runtime/src/phase_loop_runtime/ratification_policy.py` | consume landed EC-1, EC-4, EC-5, EC-6, and EC-7 tests without editing | `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_reviewtruth_phase.py -q -k reviewtruth_sl4`<br>`PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_advisor_board_golden.py -q` | On the marker-present partial implementation, require focused SL-4 falsifiers RED at their frozen anchors before editing SL-4 and the inherited golden GREEN. Cover grounded 4-of-4 FULL without shortfall, grounded 3-of-4 FLOOR-ONLY with typed shortfall and never FULL, grounded 2-of-4 BELOW-FLOOR with no convergence claim, reviewed-prompt lens coverage from `prompt_lens_digest`, reviewed-no-findings counting, retryable outcomes not counting, and a 2-seat plan/design gate retaining `proceed_degraded` rather than inheriting merge-gate hard blocking. |
| SL4-T2 | impl | SL4-T1 | `phase-loop-runtime/src/phase_loop_runtime/ratification_policy.py` | none | the focused SL4-T1 commands | Derive `BoardFacts.reviewed_seat_count`, vendor coverage, and lens coverage from `GovernedBoardEvidence.grounded_reviewed_seats`, never from raw caller counts or static `Seat` shape. Pass the grounded count to pure `classify_board_delivery()`, persist typed delivery state and shortfall, and return facts without deciding whether a gate blocks or proceeds. Preserve the existing `plan-ratify`/`design-ratify` degraded-shortfall policy; no REVIEWTRUTH criterion changes it. Do not alter the frozen golden, tests, activation guard, or sanctioned-delta list. |
| SL4-T3 | verify | SL4-T2 | `phase-loop-runtime/src/phase_loop_runtime/ratification_policy.py` | none | the focused SL4-T1 commands | Require both focused commands GREEN on the exact lane tip while later-lane falsifiers remain unselected. Prove all three classifications, raw-versus-grounded count separation, shortfall propagation, no silent FULL rendering, prompt-lens proof load-bearing behavior, reviewed-no-findings versus capped/empty/timed-out separation, no duplicate grounding classifier, unchanged plan/design degraded policy, and no EC-REVIEWTRUTH-6 regression. |

### SL-5 — Production Gate, Repair, Lifecycle Ledger, And Native Driver Integration

- **Scope**: Wire the frozen review truth through gate-specific and train consumers, bounded production repair, canonical lifecycle/summary persistence, Claude native fill, durable typed train approval/resume evidence, and a distinct SL-2-through-SL-5 implementation PR/landing boundary.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/src/phase_loop_runtime/governed_premerge.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `phase-loop-runtime/src/phase_loop_runtime/train_runner.py`, `phase-loop-runtime/src/phase_loop_runtime/train_ledger.py`, `skills-src/claude/claude-advisor-board/SKILL.md`, `phase-loop-skills/advisor-board/**`, `phase-loop-runtime/src/phase_loop_runtime/skills_bundle/*-advisor-board/**`, `phase-loop-runtime/src/phase_loop_runtime/skills_bundle/*-advisor-panel/**`
- **Interfaces provided**: `REVIEWTRUTH-production-gates`, `REVIEWTRUTH-native-driver-contract`, `REVIEWTRUTH-seat-outcome-ledger`, `REVIEWTRUTH-panel-verdict-ledger`, `REVIEWTRUTH-train-approval-evidence`, `REVIEWTRUTH-production-apply-fix`, `REVIEWTRUTH-implementation-landing`
- **Interfaces consumed**: `REVIEWTRUTH-capability-ratification`, `REVIEWTRUTH-tests-first-baseline`, `REVIEWTRUTH-preimplementation-chronology`, `REVIEWTRUTH-post-parser-collection-contract`, `REVIEWTRUTH-native-fill-identity-contract`, `REVIEWTRUTH-golden-delta-baseline`, `REVIEWTRUTH-tdd-activation`, `REVIEWTRUTH-junit-contract`, `REVIEWTRUTH-broad-compatibility-gate`, `IF-0-REVIEWTRUTH-1`, `NativeAgentLegRequest.request_id`, `NativeAgentLegRequest.seat_instance_id`, `NativeAgentLegRequest.attempt_id`, `NativeAgentLegReport`, `NativeAgentLegBindingDisposition`, `bind_native_agent_leg_result()`, `ReviewGrounding`, `GovernedBoardEvidence.grounded_reviewed_seats`, `review_material_issue()`, `BoardDeliveryState`, `classify_board_delivery()`
- **Parallel-safe**: no; this is the serialized integration lane and the single writer for production gate orchestration and generated skill surfaces.
- **Tasks**:
  - test: SL5-T1 — Consume the immutable real-production gate, train-resume migration, repair, planning-policy, ledger/native-attempt reconstruction, collision/late/replay/cross-seat/exactly-once binding, and CLI material falsifiers without editing tests.
  - impl: SL5-T2 — Wire production repair, gate-specific and train classification consumers, typed current-policy train approval evidence, aggregate/per-seat/native-attempt events, empty-material failure, eligible native Fable fulfillment with fresh retry identities, crash-safe exactly-once reconstruction, and regenerated skill mirrors.
  - verify: SL5-T3 — Prove production reachability, both live/resume policy migrations, and durable native attempt reconstruction; push the candidate; generate phase and broad candidate XML through the immutable ordinary collection arm from a fresh repo-local exact-head process; parse both before ordinary CI/golden/panel/merge; then use another fresh exact-head invocation for each implementation panel attempt and merge the distinct tests-immutable implementation PR before SL-6.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command | Work |
|---|---|---|---|---|---|---|
| SL5-T1 | test | SL-0, SL-1, SL-2, SL-3, SL-4 | all SL-5 owned paths | consume landed EC-4, EC-6, EC-8, EC-10, EC-11, EC-13, EC-14, floor-suite migration, train-resume migration, native-attempt reconstruction/collision/late/replay/cross-seat/exactly-once, and known compatibility tests without editing | `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_reviewtruth_phase.py -q -k reviewtruth_sl5`<br>`PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_advisor_board_golden.py -q` | On the marker-present partial implementation, require focused SL-5 falsifiers RED at their frozen anchors before editing SL-5 and the inherited golden GREEN. Drive real production gates for block-then-pass repair; grounded FULL/FLOOR-ONLY/BELOW-FLOOR; hard BELOW-FLOOR blocking at governed pre-merge, train merge/resume, merge-class, and CLI gates; valid current-policy grounded FULL/FLOOR-ONLY following the train gate's explicit policy; count-only, stale-policy, missing-state, and raw-ungrounded train approvals forcing re-review; unchanged degraded handling at plan-ratify/design-ratify; non-FAB per-seat ledger reconstruction including orthogonal `degraded`; metadata-only native request/attempt emitted, superseded, consumed, and rejected reconstruction; duplicate-`seat_key` isolation; fresh retry identities; late/stale/replayed/cross-seat/digest-substituted report rejection across restart; exactly-once reviewed count; and CLI/train empty/non-empty material controls. |
| SL5-T2 | impl | SL5-T1 | all SL-5 owned paths | none | the focused SL5-T1 commands during implementation; the broad candidate command only after the lane is complete | Wire the production `apply_fix` closure from `_build_repair_context`, `build_prompt`, and `launch_with_spec`; fold block findings into repair context, redispatch repair, rebuild the staged bundle, and keep its bounded rounds independent from recent-failure accounting. Consume `review_material_issue()` in CLI/planning/pre-merge/runner paths and make `_build_train_review_bundle()` carry substantive committed change material rather than PR-summary-only prose. Replace governed pre-merge's separate `_MIN_USABLE_REVIEWERS=2` decision with the gate-specific `classify_board_delivery()` consumer over grounded reviewed seats so no dual threshold survives: FULL passes, FLOOR-ONLY may proceed only with explicit degraded/shortfall state and never reports FULL, and two usable/reviewed seats are BELOW-FLOOR and block. Apply the same hard-block action only to EC-REVIEWTRUTH-1/4 governed pre-merge, train merge/resume, merge-class, and CLI gates; preserve `plan-ratify`/`design-ratify` degraded policy while forbidding them from reporting degraded progress as FULL convergence. In `train_runner.py`, use `GovernedBoardEvidence.grounded_reviewed_seats` and `classify_board_delivery()` for live train review, approval, ledger write, and resume. In `train_ledger.py`, migrate durable review evidence from raw `usable_reviewers` to typed `delivery_state` plus an incremented current `REVIEW_POLICY_VERSION`; legacy `usable_reviewers` may remain readable as non-authorizing provenance only. Resume requires exact current-policy identity and a grounded gate-authorizing delivery state; every pre-migration, count-only, missing-state, old/missing-policy, raw-ungrounded, or BELOW-FLOOR record re-enters review and cannot short-circuit merges. Emit aggregate verdicts on every governed outcome and one metadata-only `SeatOutcomeRecord` per requested non-FAB seat, including orthogonal `degraded`, through canonical events. Persist native fill as metadata-only lifecycle events carrying `seat_instance_id`, `request_id`, `attempt_id`, `seat_key`, all four content digests, transition, and typed binding disposition, never raw prompt/review text. Before dispatch/resume, reconstruct pending, superseded, consumed, and rejected identities from the canonical ledger; never re-emit a consumed identity, never accept a superseded/prior-board/replayed tuple, and allocate fresh request/attempt identities for every retry. Fulfill eligible native Fable requests through the Claude source skill under the ratified posture, echo the complete identity/digest tuple in its report, bind valid reports exactly once, preserve colliding seat instances and the real-tree execution boundary, and regenerate all neutral and packaged skill mirrors. Do not edit any of SL-1's ten frozen paths, including conftest, floor, train, golden, serializer, native-request, native-fill, chronology, and RED evidence owners. |
| SL5-T3 | verify | SL5-T2 | all SL-5 owned paths | none | `PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit-run --mode candidate --xml .phase-loop/evidence/reviewtruth-phase-candidate.xml`<br>`PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration" --junitxml=.phase-loop/evidence/reviewtruth-broad-candidate.xml`<br>`PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit --mode candidate --phase-xml .phase-loop/evidence/reviewtruth-phase-candidate.xml --broad-xml .phase-loop/evidence/reviewtruth-broad-candidate.xml`<br>`PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_advisor_board_golden.py -q` | Push the complete implementation candidate, then discard any proof from the already-loaded authoring process. In a fresh repo-local child, prove `HEAD` equals the server-reported pushed implementation head, attest repo-local module/conftest paths and digests, and run these four commands in the displayed order. The phase runner selects exactly frozen `REVIEWTRUTH_PHASE_NODEIDS` and requires zero phase skips. The unmodified broad command leaves `PHASE_LOOP_REVIEWTRUTH_POST_PARSER_COLLECTION` unset; built-in marker selection must report exactly `REVIEWTRUTH_BROAD_MARKER_DESELECTED_NODEIDS`, and the frozen try-last wrapper hook must separately find, remove, and notify exactly all five `REVIEWTRUTH_POST_PARSER_NODEIDS`, while every other collected runtime test, including all five compatibility migrations and every marker-activated new/migrated production assertion, runs. A nonempty external `--deselect`, arbitrary/category-swapped deselection, marker-baseline drift, missing/extra/wrong hook deselection, or final collection activation is forbidden. Broad skips must equal the unchanged pre-implementation skip baseline set/count/digest exactly; zero broad skips is neither required nor claimed. The candidate parser runs only after both exact XML files exist and requires zero selected phase skips, zero `xfail`, broad deselections equal to the disjoint marker baseline UNION five hook-owned wrappers with both categories attested, zero failures/errors, no missing/duplicate/unexpected phase nodeid, and no new/missing/drifted broad baseline skip. The ordinary frontmatter suite command and required GitHub CI must also be GREEN at this exact head under the same marker-baseline-plus-five deselection and broad-skip contract before merge; their absence or red status blocks the merge even if the special parser is green. The golden runs only after that parser is GREEN. Prove production repair reachability; aggregate/per-seat lifecycle persistence; native request/attempt lifecycle reconstruction across restart; unique colliding seat instances; fresh retry identities; rejection of late/stale/replayed/cross-seat/digest-substituted reports; exactly-once count; resolved brief propagation and all four content digests; material-helper consumption; exact delivery-state output; floor/train migration; generated parity; exact sanctioned golden output; and conformance to the separately ratified capability record. Only after this fresh exact-pushed-head phase/broad/parser/suite/CI/golden proof is GREEN, launch the mandatory Fable 5 + GPT-5.6 Sol + Gemini 3.6 Flash + Grok 4.5 panel from another fresh repo-local process bound to the same exact pushed head. Record its child attestation and all XML/parser/suite/CI/golden digests. Every material finding forces a new pushed head and a new fresh ordered proof and panel; no loaded parent attestation is reusable. Merge one dedicated implementation PR as a two-parent commit whose first parent already contains the disposition and tests-only landings. The implementation PR must use a distinct head identity, contain no SL-1-owned path or SL-1 tests-only commit in `implementation^1..implementation^2` or its server-recorded PR range, cite the full disposition SHA in the landing message, and be reachable from canonical `main` before SL-6 starts. |

### SL-6 — REVIEWTRUTH Evidence, Documentation, And Verification Reducer

- **Scope**: From a new repo-local process at the exact post-implementation canonical-main tip, reduce final chronology, capability ancestry, live panel inspection, governed ledger output, structured JUnit accounting, and whole-phase verification into durable metadata-linked evidence — staged as a board-reviewed pre-final record and a post-parser finalized record in an acyclic order — without modifying producer-owned tests or code.
- **Owned files**: `phase-loop-runtime/scripts/verify_reviewtruth_evidence.py`, `docs/research/reviewtruth-phase-verification.md`, `docs/research/reviewtruth-real-panel-smoke.md`, `docs/research/reviewtruth-final-evidence-record.md`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`
- **Interfaces provided**: `REVIEWTRUTH-closeout-evidence`, `REVIEWTRUTH-gate-a-suite-attestation`, `IF-0-REVIEWTRUTH-1`
- **Interfaces consumed**: `REVIEWTRUTH-capability-ratification`, `REVIEWTRUTH-tests-first-baseline`, `REVIEWTRUTH-evidence-wrappers`, `REVIEWTRUTH-post-parser-collection-contract`, `REVIEWTRUTH-native-fill-identity-contract`, `REVIEWTRUTH-golden-delta-baseline`, `REVIEWTRUTH-junit-contract`, `REVIEWTRUTH-broad-compatibility-gate`, `IF-0-REVIEWTRUTH-1`, `REVIEWTRUTH-production-gates`, `REVIEWTRUTH-native-driver-contract`, `REVIEWTRUTH-seat-outcome-ledger`, `REVIEWTRUTH-panel-verdict-ledger`, `REVIEWTRUTH-production-apply-fix`, `REVIEWTRUTH-implementation-landing`
- **Parallel-safe**: no; this terminal reducer consumes every producer lane and is the only writer for synthesized evidence and final contract documentation.
- **Tasks**:
  - test: SL6-T1 — From merged canonical `main`, prove the implementation-landing precondition and immutable test-owner boundary without invoking any final chronology, live-panel, or final-evidence wrapper.
  - impl: SL6-T2 — Write only the owned evidence verifier and pre-final evidence docs, including the non-wrapper `gate-a` runner plus its fresh internal `gate-a-attest` verifier, run the real four-vendor by-reference board over those exact staged digests, record exact already-existing source/proof digests and operational traces while deferring every final XML/attestation digest to SL6-T3's post-parser finalized record, and update the canonical contract and capability card.
  - verify: SL6-T3 — Only after the pre-final evidence/docs exist, generate and parse broad-final producer XML, generate phase-final XML whose wrappers consume only already-existing pre-final inputs plus that attestation, parse both in final mode, finalize the post-parser evidence record, run the separate `final-record` verifier, then run the single sanitized Gate A reducer and finish the golden/static and attestation-bound closeout checks; fail closed on any evidence, skip, nodeid/count, ordering, process, or digest gap.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command | Work |
|---|---|---|---|---|---|---|
| SL6-T1 | test | SL-0, SL-1, SL-2, SL-3, SL-4, SL-5 | all SL-6 owned paths | consume immutable ownership/precondition contracts without editing | `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k reviewtruth_preimplementation_chronology_all` | Fetch canonical `main`, create a fresh branch/worktree exactly at that fetched tip already containing `REVIEWTRUTH-implementation-landing`, and launch a new repo-local process that proves `HEAD` equals the canonical-main SHA and imports every runtime module and the frozen conftest beneath this worktree. Record the child attestation before reading runtime results. Prove the implementation landing is reachable and all ten SL-1-owned paths remain byte-identical to the tests-only landing and absent from the implementation PR range. Only SL-6-owned evidence/doc paths may become dirty. Do not activate or run any of the five exact post-parser evidence nodeids before SL6-T2 writes their owned inputs and the broad-final producer XML/parser attestation exists. |
| SL6-T2 | impl | SL6-T1 | all SL-6 owned paths | none | `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k reviewtruth_preimplementation_chronology_all` | In that fresh exact-canonical-main child, add the metadata-only evidence verifier with wrapper-consumable `source-ownership`, `live-panel`, `ledger`, `junit`, and `all` checks scoped to already-existing artifacts, plus the post-parser `finalize-record` writer and separate `final-record` verifier modes that no test wrapper may invoke. Add a non-wrapper `gate-a` mode that refuses to start if `PHASE_LOOP_SKIP_GATE_A_SUITE` or final collection activation is present, launches the unmodified Gate A script under traced execution with both selectors absent, and writes new sibling stdout/stderr plus canonical JSON; after sealing those bytes it must launch a fresh internal `gate-a-attest` process with the same selector rejection to independently parse and hash them and write the terminal attestation. Do not add or edit test wrappers, conftest, or production runtime. Stage the verifier, `docs/research/reviewtruth-phase-verification.md`, and the contract/card updates first, then run a real four-vendor board over a by-reference bundle naming those exact staged files and digests; write `docs/research/reviewtruth-real-panel-smoke.md` as the single canonical durable redacted transcript and smoke record from that run, freeze its one SHA-256 digest, create no second durable transcript path, and freeze every pre-final SL-6 doc byte-identical from its own staging/review point through closeout. Require reviewed Fable and Sol plus the two remaining vendor seats to cite facts obtainable only by opening those files; reject no-file-read disclosure, blank material, missing native report, repo substitution, or digest mismatch. Record exact plan, all ten tests-only paths including the hook, implementation code, generated, ledger, phase default/RED/candidate XML, broad baseline/default/candidate XML, parser-attestation, evidence, and canonical `docs/research/reviewtruth-real-panel-smoke.md` digests, with exactly one digest for its combined transcript/smoke identity; distinct PR/head identities; child process attestations; source-owner mapping; candidate ordered gate, ordinary suite/CI, and golden GREEN commands; artifact-specific citations; native request/report binding including stable seat-instance, fresh request/attempt identities, resolved brief identity, all four content digests, typed rejected reports, exactly-once consumption/count, and durable reconstruction; material-guard outcomes; production repair trace; per-seat reconstruction; and typed current-policy train approval/resume evidence. The pre-final record deliberately excludes the broad-final/phase-final XML digests, final parser attestations, finalized record, `final-record` attestation, Gate A run/output/artifact/attestation, and run-end verdict: none of those exist yet, and they are recorded only by SL6-T3's post-parser finalized record where applicable and the ledger closeout. Update the canonical contract and capability card from SL-1's already-frozen sanctioned golden delta plus the narrow native-fill reversal, exact-once identity binding, and retained real-tree capability boundary; SL-6 may not add a newly discovered delta or repair production output. |
| SL6-T3 | verify | SL6-T2 | all SL-6 owned paths | none | `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration" --junitxml=.phase-loop/evidence/reviewtruth-broad-final.xml`<br>`PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit --mode broad-final-producer --xml .phase-loop/evidence/reviewtruth-broad-final.xml`<br>`PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit-run --mode final --xml .phase-loop/evidence/reviewtruth-phase-final.xml`<br>`PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit --mode final --phase-xml .phase-loop/evidence/reviewtruth-phase-final.xml --broad-xml .phase-loop/evidence/reviewtruth-broad-final.xml`<br>`PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_evidence.py finalize-record --phase-xml .phase-loop/evidence/reviewtruth-phase-final.xml --broad-xml .phase-loop/evidence/reviewtruth-broad-final.xml --record docs/research/reviewtruth-final-evidence-record.md`<br>`PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_evidence.py final-record --record docs/research/reviewtruth-final-evidence-record.md --attestation .phase-loop/evidence/reviewtruth-final-record-attestation.json`<br>`PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_advisor_board_golden.py -q`<br>`PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration"`<br>`env -u PHASE_LOOP_SKIP_GATE_A_SUITE -u PHASE_LOOP_REVIEWTRUTH_POST_PARSER_COLLECTION sh -c 'PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_evidence.py gate-a --script phase-loop-runtime/scripts/gate_a_cleanroom.sh --artifact .phase-loop/evidence/reviewtruth-gate-a-suite.json --attestation .phase-loop/evidence/reviewtruth-gate-a-suite-attestation.json'`<br>`ruff check phase-loop-runtime/src/phase_loop_runtime/`<br>`phase-loop validate-roadmap specs/phase-plans-v10.md`<br>`git diff --check` | Run these commands in the displayed order only after SL6-T2, from the fresh child whose exact canonical-main/runtime attestation is already recorded; a loaded parent may not substitute. The first command leaves final collection unset and generates broad-final XML through the ordinary arm; built-in marker selection must attest exactly the frozen marker baseline and the try-last hook must separately find/remove/notify exactly the five frozen wrappers, with no external `--deselect`, arbitrary deselection, missing/extra wrapper, or category drift. The second command must parse that exact existing path, require total broad deselections equal to the disjoint marker baseline UNION five hook-owned wrappers, require the unchanged legitimate broad skip set/count/digest, and reject any `xfail`, failure, error, or collection/import drift before emitting the attestation consumed by the wrappers. Only then may `junit-run --mode final` reject any inherited collection activation, set `PHASE_LOOP_REVIEWTRUTH_POST_PARSER_COLLECTION=junit-run:final:v1` in its child, and generate phase-final XML over all exact `REVIEWTRUTH_EXPECTED_NODEIDS`, including the five strict wrappers; those wrappers independently confirm exact runner activation and broad-final attestation, consume only already-existing pre-final inputs — including the frozen `docs/research/reviewtruth-phase-verification.md` digest and the one frozen `docs/research/reviewtruth-real-panel-smoke.md` transcript/smoke digest — plus the broad-final parser attestation, and never consume a future XML, the finalized record, the `final-record` attestation, or any closeout output. The fourth command parses both exact existing XML paths in final mode and requires every phase nodeid exactly once with zero phase skips, `xfail`, errors/failures, duplicates, unexpected nodeids, or deselections; it rechecks the broad marker baseline, five hook-owned wrapper deselections, and broad skip baseline as separate categories. Only after that final parse is GREEN does the fifth command write the write-once post-parser finalized record at `docs/research/reviewtruth-final-evidence-record.md`, recording the exact broad-final and phase-final XML digests, both parser-attestation digests, the frozen `docs/research/reviewtruth-phase-verification.md` digest, and the one frozen `docs/research/reviewtruth-real-panel-smoke.md` digest the board and wrappers consumed. The sixth command is the separate minimal verifier: it recomputes every recorded digest from the artifact bytes, confirms each pre-final doc is byte-identical to its frozen staged digest, and writes its attestation only to `.phase-loop/evidence/reviewtruth-final-record-attestation.json` and the canonical ledger, never into the record it verifies; that attestation gates the remaining golden/default-suite/Gate-A/static checks and the record-bound closeout. The plain frontmatter suite command must remain GREEN on post-marker/fresh-clone collection with the immutable marker baseline plus exactly five wrappers and the appropriate frozen broad skips. The single Gate A reducer must reject either `PHASE_LOOP_SKIP_GATE_A_SUITE` or final collection activation in its own environment, launch the exact unmodified script under Bash xtrace with both absent, and fail unless the raw output contains exactly one installed-wheel full-suite start sentinel followed by exactly one GREEN sentinel, contains no standalone-suite SKIPPED sentinel, and the normalized trace proves exactly one pytest invocation of the copied complete `tests` tree with profile `-q -p no:cacheprovider -m "not dotfiles_integration"`. It must independently parse the terminal pytest summary into nonzero collected/executed and per-outcome counts, require a successful exit with no failed/error outcome, and seal new stdout/stderr sidecars plus a canonical JSON artifact binding their byte counts/digests, the Gate A script digest, exact canonical profile, sentinel offsets/counts, pytest counts, process identity, HEAD, and command. Only after those files are closed may a fresh internal `gate-a-attest` process with the same selector rejection re-hash and re-parse the script, raw sidecars, and artifact and write the new terminal attestation. Neither suite may require the temporary baseline file or wrapper/final-record inputs, and an existing/missing/drifted artifact, smoke-only trace, zero-test summary, selector inheritance, profile change, sentinel reorder/duplication, or attester mismatch fails before static checks or closeout. The SL-6 owner-map check accepts `docs/research/reviewtruth-real-panel-smoke.md` as the already-owned sole durable transcript/smoke path with one digest and rejects any second durable transcript path or split transcript/smoke digest. The golden remains a re-run of the mandatory pre-merge gate, never first detection. Fail close on an unsanctioned golden delta, same-branch/tests-in-implementation-range history, any of the ten immutable path digests changing, collection-hook/predicate/nodeid drift, marker-baseline drift, any external/arbitrary/category-swapped ordinary deselection, a missing/extra hook wrapper deselection, owner-map escape, unratified posture, stale/mismatched child attestation, missing or multiply consumed native report binding, reused request/attempt identity, colliding-seat alias, late/stale/replayed/cross-seat/digest-substituted report acceptance, absent durable native attempt reconstruction, prose-only grounding or material claim, unexercised production repair, absent aggregate/per-seat ledger or typed current-policy train approval record, non-inspecting panel seat, missing operational field, parser-before-generation or wrapper-before-attestation ordering, final collection activation before the broad-final attestation, record finalization before the final parse, a `final-record` run before the record exists, a closeout not bound to the finalized record digest, `final-record` attestation, and terminal Gate A suite attestation, any post-finalization edit to the record or any post-freeze edit to a pre-final evidence doc, a wrapper consuming the finalized record or either final attestation, or digest mismatch. Stamp the already-landed implementation commit and server-recorded PR metadata before closeout; never manufacture a future implementation landing from SL-6 evidence. The canonical ledger closeout records the finalized record digest, the `final-record` attestation, the terminal Gate A suite attestation, all four closeout seat outcomes, and the run-end verdict; none of these is written back into the finalized record or any wrapper-consumed artifact. |

## Execution Policy

- work-unit defaults: work-unit=`lane_execute`, effort=`high`, unsupported=`inherit_default`, inherit-default=`true`
- SL-6: work-unit=`phase_reducer`, effort=`high`, unsupported=`inherit_default`, inherit-default=`true`, reason=`terminal evidence and documentation reducer`

## Execution Notes

- Policy precedence is CLI/operator override, phase-plan policy, roadmap policy, `Dispatch Hints`, then registry defaults. This plan does not select the implementation author: the coordinator must explicitly rotate one whole-phase author vendor and keep both runtime schedulers off. Silent executor/model/effort downgrade is forbidden without explicit fallback or inherited defaults.
- Plan review is a pre-dispatch gate, not a lane. Record the exact plan digest, executor/model/effort, Fable/Sol reviewed outcomes, all four seat outcomes, and resolution of every material finding in the canonical runner ledger before SL-0.
- SL-0 and SL-1 require separate landings before production work. The capability record must reach canonical `main` first in its own PR. The tests-only change starts from that main tip and, before editing any SL-1 file, materializes the exact panel-reviewed bootstrap bytes into ignored runner evidence and executes one controlled GREEN `-m "not dotfiles_integration"` process. That process freezes exact plan/roadmap/observer digests; clean HEAD/tree/index; process, argv, Python/pytest/module/plugin provenance; raw output/JUnit; full pre-marker and selected post-marker collections; exact marker difference; and legitimate skips. Only afterward are the tests/conftest/parser authored; the parser independently recomputes the observation and the runner generates/parses phase default, broad default, and activated phase XML in the exact SL1-T1 order. Only after those parser attestations and the observer/parser/collection/native-identity mutation controls exist is the exact tests-only digest PANELLED by the required four-seat board and landed in a separate production-change-free PR. `reviewtruth_preimplementation_chronology_all` is the only chronology gate that unblocks implementation and intentionally needs no future landing. Implementation starts from the tests-only canonical-main tip under a distinct PR/head identity. The ten frozen SL-1 paths are exactly `phase-loop-runtime/tests/conftest.py`, `phase-loop-runtime/tests/test_reviewtruth_phase.py`, `phase-loop-runtime/tests/test_train_merge.py`, `phase-loop-runtime/tests/test_governed_cross_vendor_floor_358.py`, `phase-loop-runtime/tests/test_advisor_board_golden.py`, `phase-loop-runtime/tests/test_advisor_board_research.py`, `phase-loop-runtime/tests/test_panel_invoker_spawn.py`, `phase-loop-runtime/tests/test_panel_native_fill_183.py`, `phase-loop-runtime/scripts/verify_reviewtruth_chronology.py`, and `docs/research/reviewtruth-red-baseline.md`; ignored `.phase-loop/evidence/**` is bound evidence, never a landing path, and none of the ten tracked paths may appear in `implementation^1..implementation^2`, the server-recorded implementation PR diff/range, or any tests-only commit carried on the implementation branch.
- The tests-only production-activation boundary, post-parser collection boundary, exact full/selected collection freeze, collection-plugin profiles, and all three broad accounting categories are immutable. `PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1` forces new production behavior only for the pre-implementation RED proof; absent that variable, the exact `REVIEWTRUTH_CAPABILITY_MARKER = "reviewtruth@1"` switches the same non-wrapper test bodies from default legacy/skip behavior to new assertions. Neither activates the five post-parser wrappers. Ordinary/default tests-only CI, marker-present implementation CI, the unchanged frontmatter suite command, clean-room Gate A, and fresh-clone default suites are GREEN because their canonical collection must equal the frozen pre-edit sets plus exactly the declared new REVIEWTRUTH nodeids, built-in `-m "not dotfiles_integration"` selection contributes exactly the frozen pre-edit marker deselection baseline, and the try-last conftest hook separately contributes exactly the five wrapper deselections unless the exact value `PHASE_LOOP_REVIEWTRUTH_POST_PARSER_COLLECTION=junit-run:final:v1` is set by final `junit-run` after broad-final attestation. Legitimate broad skips remain their own frozen category. Phase-selected default/RED/candidate use the frozen non-wrapper phase set; final uses the full expected set and requires zero phase skips/deselections. Broad default/candidate/broad-final require the exact frozen full/selected collection, approved source/CI or Gate-A plugin profile, marker baseline UNION exact five wrappers, and separately frozen legitimate pre-implementation skip baseline plus non-wrapper default skips only where applicable. The implementation installs only the marker and production behavior. It cannot edit conftest, test imports, guards, branch/collection predicates, activation name/value, nodeids, selectors, expected counts/digests, collection/plugin profiles, either skip set/reason, either deselection tuple/category/reason, RED anchors, JUnit runner/parser, or evidence wrappers. No `xfail`, external `--deselect`, arbitrary deselection, unapproved collection-capable plugin, category substitution, full/selected/marker/plugin drift, or hook drift is permitted; any collection/import failure, unexpected/drifted skip or deselection, ordinary-suite/CI/Gate-A red status, or compatibility test that first fails after merge is a hard failure.
- SL-2 through SL-5 are authored by one explicitly rotated whole-phase author vendor, remain together on the distinct implementation branch, and cross one implementation review/landing boundary before SL-6. Both runtime schedulers stay off; file-disjointness does not authorize a second author vendor. Intermediate lane checks use their immutable focused selectors because installing the marker intentionally exposes downstream RED tests until their owner lane is implemented; no intermediate candidate may panel or merge. After SL-5, every implementation candidate is pushed. A fresh repo-local process proves it is bound to the exact server-reported pushed head, generates phase-candidate XML at `.phase-loop/evidence/reviewtruth-phase-candidate.xml` over the frozen non-wrapper phase set, generates broad-candidate XML at `.phase-loop/evidence/reviewtruth-broad-candidate.xml` with the immutable marker-selection baseline and ordinary conftest hook separately attested, and invokes the frozen parser in candidate mode against those exact existing paths. The parser requires zero selected phase skips, total broad deselections equal to marker baseline UNION the five hook-owned wrappers with each category exact, and exactly the unchanged broad skip baseline; it never claims five total broad deselections or broad zero skips. The unchanged suite command and required GitHub CI must be GREEN at the same exact pushed head before the exact golden, fresh exact-head panel, or merge decision. Every finding repair creates a new pushed head and invalidates all prior XML, parser, suite/CI, golden, and panel evidence. The mandatory Fable 5 + GPT-5.6 Sol + Gemini 3.6 Flash + Grok 4.5 panel is itself launched from a new repo-local process at that exact head. The implementation PR then lands as a two-parent merge whose first parent already contains both prior landings. SL-6 starts only from a different fresh process at the exact fetched post-merge canonical-main head.
- The owned chronology verifier has separate `pre-implementation` and `final` ancestry modes over full immutable SHAs and server-recorded PR/head identities, exact-selector `junit-run` modes `default-premarker`, `activated-red`, `candidate`, and `final`, and parser modes `broad-baseline`, `default-premarker`, `activated-red`, `candidate`, `broad-final-producer`, and `final`. Its `broad-baseline` mode consumes the write-once observation directory only after the observer ran: it independently verifies the exact embedded observer digest, raw artifact/JUnit digests and outcomes, plan/roadmap SHA, clean same HEAD/tree/index, same process identity, command/Python/pytest/module/plugin provenance, exact full and selected collections, exact marker difference, and legitimate skips. It then freezes the allowed post-SL-1 full/selected transform and source/CI versus Gate-A plugin profiles alongside full/non-wrapper/post-parser and broad nodeid sets/counts/sorted-LF SHA-256 digests; the conftest digest and exact collection name/value/predicate; migrated legacy run set; activated RED nodeids/raw anchors; the exact marker-filter deselection tuple/count/digest and five exact hook-owned ordinary deselections as disjoint categories; candidate zero-phase-skip plus collection/plugin/marker/hook/skip-baseline accounting; and final all-expected-ran-once zero-phase-skip/deselection plus unchanged broad accounting. Both ancestry modes refuse a shallow repository, grafts, or `refs/replace`. Final mode resolves the implementation landing with `git rev-list --parents -n 1`, requires exactly two parents, treats its first parent as the pre-landing target tip, applies `git merge-base --is-ancestor` to both the recorded disposition SHA and tests-only landing SHA against that first parent, requires the landing message to contain the full record SHA, and matches all three landings to distinct server-recorded PR metadata. It also rejects a reused tests-only head identity, any SL-1 tests-only commit in `implementation^1..implementation^2`, any of the ten frozen SL-1 paths in that range or the server-recorded implementation PR diff, and any implementation source that diverges from the ratified posture. The five exact post-parser wrappers are absent from non-final phase selectors, hook-deselected in addition to the marker baseline from ordinary broad/default/CI/Gate-A/fresh-clone collection, and must all run exactly once with zero phase skips/deselections in phase-final XML only after `junit-run --mode final` verifies broad-final and sets its child-only exact activation. Their frozen assertions consume only pre-phase-final inputs, so the phase-final XML, final-mode parser attestation, post-parser finalized record, `final-record` attestation, and closeout verdicts stay outside every wrapper; after the final parse, `finalize-record` writes the finalized record, the separate `final-record` verifier attests it from outside, the sanitized Gate A reducer emits its independently checked suite attestation later, and only then does the closeout bind all three terminal evidence identities. Squash, rebase, direct-push, single-parent landing, same-branch history, a record carried only on the implementation branch, tests in the implementation range, observer/provenance/raw-artifact drift, external/arbitrary/category-swapped deselection, full/selected/marker/plugin/hook drift, marker-driven wrapper collection, final activation before broad-final attestation, parser-before-generation, wrapper-before-attestation, finalization-before-final-parse, record-verification-before-finalization, closeout-before-record-attestation, or blanket roadmap authorization is a phase failure.
- SL-3 and SL-4 are file-disjoint, but SL-4 has a real data dependency on SL-3's `GovernedBoardEvidence.grounded_reviewed_seats`; prose order is not a substitute for that edge. SL-3 only publishes grounding/material helpers. SL-5 exclusively owns `train_runner.py` and `train_ledger.py`, runs after SL-4, and consumes those helpers plus `BoardDeliveryState`/`classify_board_delivery()` for live train review, ledger write, and resume. The coordinated v10 runtime lane scheduler stays off to preserve a single author vendor.
- Durable train review approval is schema/policy evidence, not a count snapshot: `REVIEW_POLICY_VERSION` is incremented for the grounding/three-state migration, `delivery_state` is derived only from grounded reviewed seats, and resume requires both the exact current version and a train-gate-authorizing typed state. Every existing `test_train_merge.py` honor/crash/recovery fixture that currently plants `usable_reviewers=2` or count-only evidence is migrated in SL-1; existing pre-migration/count-only approvals, two-reviewed evidence, raw ungrounded usable evidence, missing state, BELOW-FLOOR, and stale/missing policy identity never short-circuit review. Only valid current-policy grounded FULL/FLOOR-ONLY is a positive resume control and follows the explicit train gate policy.
- Native fill is a durable attempt protocol, not an in-memory `seat_key` lookup. A unique stable `seat_instance_id` identifies one requested seat through retries even when two seats share the same non-unique `seat_key`; every request emission/retry allocates fresh non-reused `request_id` and `attempt_id`; and request/report both carry the exact artifact/brief/lens/prompt digests. Binding consumes one current pending tuple atomically and at most once. Unknown, late, stale, replayed, cross-seat/colliding-seat, identity/digest-mismatched, and non-terminal reports produce typed rejected transitions and never mutate a seat or count. Canonical metadata-only events reconstruct emitted, pending, superseded, consumed, and rejected identities before retry/resume, so a process restart or late first-attempt report cannot re-inflate reviewed or grounded counts.
- `test_advisor_board_golden.py` is an SL-1-owned normative contract, not an SL-6 discovery aid. Its sanctioned-delta list freezes the additive typed result fields, prompt/lens carrier, and native request/report identity/digest surface required by IF-0-REVIEWTRUTH-1 while preserving every unlisted legacy launch/result/serialization behavior. The adjacent SL-1 compatibility migrations freeze the exact `dataclasses.asdict` shape transition, Fable/Opus native-request reversal, and all three under-Claude-Code Fable native-fill reversals under their five unchanged full nodeids. Each migrated nodeid has immutable legacy/default, forced-activation/new, and automatic post-marker/new assertions over every affected field, including stable seat-instance, fresh request/attempt identities, and artifact/brief/lens/prompt digests; the no-local-CLI node proves the local support probe is irrelevant after the host is identified as Claude Code, while the brief-flow node binds the resolved `brief_ref`, instructions, and their digests. SL-2 through SL-5 cannot edit or rebaseline any of them; the ordered candidate phase/broad parser, ordinary suite/CI, and exact golden command gate every implementation panel/merge. SL-6 only mirrors the frozen rule into `advisor_board/CONTRACTS.md` and `docs/advisor-board-capabilities-card.md` and re-runs it.
- The coordinated run retains its bootstrap no-degraded-promotion interlock: planning, tests, implementation review, and closeout require all four intended seats with Fable and Sol reviewed. The closeout board reviews the exact finalized evidence record digest, the `final-record` attestation, and the terminal Gate A suite attestation, and its verdict is written only to the canonical ledger. The runtime implementation may represent FLOOR-ONLY and follow an explicit downstream policy, but this phase cannot use its own new degraded semantics to waive the board that authorizes it.
- `timed_out` is frozen and consumed here; subprocess timeout enforcement, process-group killing, and child reaping stay owned by LEGLIFE. Per-repo custom seats and RISCO lenses also stay out of scope.
- The `REVIEWTRUTH-redacted-transcript-policy` designates `docs/research/reviewtruth-real-panel-smoke.md` as the single canonical durable redacted transcript and smoke record and requires it to prove inspection, not command construction. Raw model output remains only in the protected live artifact. The canonical repo file contains only redacted transcript material, artifact-specific citations, seat identities/outcomes, and metadata, has one frozen SHA-256 digest for its combined transcript/smoke identity, and may not be accompanied by a second durable transcript path; do not substitute argv goldens or a hand-built `panel_verdict` event. Metadata-only closeout records only that exact path and single digest, seat identities/outcomes, and citations, never raw model output. The post-parser finalized evidence record and `final-record` attestation are likewise metadata-only: digests, paths, identities, and outcomes, never raw model output.
- This plan is intentionally pre-PROOFGATE. Its Acceptance Criteria use the currently accepted `proven by <command>` plan grammar; each roadmap criterion's `falsified by` mutation is bound in SL-1 to a named test, asserted injection anchor, and positive control, and the RED/evidence records retain that mapping. `IF-0-PROOFGATE-1` is produced and mechanically required only by the later PROOFGATE phase, so this plan neither claims that future interface nor drops its falsifiers.
- Documentation impact: SL-6 updates the normative board contract and capability card because the roadmap reverses the Fable native-fill prohibition narrowly. Record `no_doc_delta` for `README.md`, `CHANGELOG.md`, packaging dependencies, lockfiles, env examples, migrations, and release notes because REVIEWTRUTH changes no public release/package surface.

### Exact bootstrap observer payload

No suitable immutable coordinator/runner observer exists. The materialization command in `## Verification` extracts the exact bytes between the sentinels below, appends the one displayed terminal LF, and refuses any digest other than `b5fcd773ec6d14ebacc0aa84e25b0bb2b8a47a11a6860ba2b243028543bae223` (`21217` bytes). The bootstrap is intentionally external to every SL-1 tracked path, runs before those paths are mutated, writes only ignored `.phase-loop/evidence/**`, and cannot overwrite a prior observer, controlled HOME, or successful observation. Its trust chain is: exact bytes and digest reviewed with this plan; exact `env -i` allowlist and application selector/source/root profile recorded by the observer; plan digest recorded by the observer; one-process raw observation sealed before repo verifier authorship; independent post-observation parser and synthetic/tamper tests over the same exact bytes and environment/plugin/root contract; tests-only four-seat panel binding of observer, raw-observation, parser, and record digests; and immutable final chronology. The observer's own attestation is necessary raw evidence, not sufficient authority.

<!-- REVIEWTRUTH_BASELINE_OBSERVER_BEGIN -->
```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib
import importlib.metadata
import inspect
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import uuid

import pytest

SCHEMA = "reviewtruth.baseline-observation.v2"
MARKER = "dotfiles_integration"
PROFILE_SELECTOR = "phase_loop_runtime.dotfiles_profile_plugin:register_profile_commands"
SKILL_SOURCE_SELECTOR = "phase_loop_runtime.skill_sources_plugin:register_skill_sources"
APPLICATION_PLUGIN_GROUPS = (
    "phase_loop_runtime.profile_commands",
    "phase_loop_runtime.skill_sources",
)
RUNTIME_SELECTOR_KEYS = (
    "PHASE_LOOP_PROFILE_PLUGINS",
    "PHASE_LOOP_SKILL_SOURCE_PLUGINS",
    "PHASE_LOOP_RUNNER_REPO_ROOT",
    "PHASE_LOOP_CLAUDE_ROUTE",
    "CI",
    "PHASE_LOOP_REVIEWTRUTH_POST_PARSER_COLLECTION",
    "PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH",
    "PHASE_LOOP_SKIP_GATE_A_SUITE",
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def environment_snapshot() -> dict[str, str]:
    return {key: os.environ[key] for key in sorted(os.environ)}


def expected_initial_environment(repo: Path) -> dict[str, str]:
    return {
        "HOME": str(repo / ".phase-loop" / "evidence" / "reviewtruth-baseline-home"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": str(repo / "phase-loop-runtime" / "src"),
    }


def expected_post_pytest_environment(repo: Path) -> dict[str, str]:
    return {
        **expected_initial_environment(repo),
        "PHASE_LOOP_PROFILE_PLUGINS": PROFILE_SELECTOR,
        "PHASE_LOOP_SKILL_SOURCE_PLUGINS": SKILL_SOURCE_SELECTOR,
    }


def git(repo: Path, *argv: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), *argv],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def process_identity() -> dict[str, object]:
    start_ticks = None
    try:
        start_ticks = Path("/proc/self/stat").read_text().split()[21]
    except OSError:
        pass
    cmdline = b""
    try:
        cmdline = Path("/proc/self/cmdline").read_bytes()
    except OSError:
        pass
    boot_id = None
    try:
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        pass
    orig_argv = list(getattr(sys, "orig_argv", sys.argv))
    return {
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "pgid": os.getpgid(0),
        "sid": os.getsid(0),
        "uid": os.getuid(),
        "gid": os.getgid(),
        "proc_start_ticks": start_ticks,
        "proc_cmdline_hex": cmdline.hex(),
        "proc_cmdline_sha256": sha(cmdline),
        "orig_argv": orig_argv,
        "orig_argv_sha256": sha(canonical_json(orig_argv)),
        "boot_id": boot_id,
        "cwd": str(Path.cwd().resolve()),
    }


def file_record(path: Path | None, repo: Path) -> dict[str, object] | None:
    if path is None:
        return None
    resolved = path.resolve()
    try:
        rel = resolved.relative_to(repo).as_posix()
    except ValueError:
        rel = None
    data = resolved.read_bytes() if resolved.is_file() else b""
    return {
        "path": str(resolved),
        "repo_relative_path": rel,
        "sha256": sha(data) if data else None,
    }


def module_record(name: str, repo: Path) -> dict[str, object]:
    module = sys.modules.get(name)
    path = Path(module.__file__) if module is not None and getattr(module, "__file__", None) else None
    return {
        "name": name,
        "version": getattr(module, "__version__", None) if module is not None else None,
        "file": file_record(path, repo),
    }


def callable_record(value: object, repo: Path) -> dict[str, object]:
    module_name = getattr(value, "__module__", None)
    module = sys.modules.get(module_name) if module_name else None
    if module is None or not getattr(module, "__file__", None):
        raise RuntimeError(f"application plugin callable has no loaded source module: {value!r}")
    source = file_record(Path(module.__file__), repo)
    if source is None or source["repo_relative_path"] is None or source["sha256"] is None:
        raise RuntimeError(f"application plugin source is outside repository or unreadable: {module_name}")
    return {
        "module": module_name,
        "callable": getattr(value, "__name__", None),
        "qualname": getattr(value, "__qualname__", None),
        "source": source,
    }


def entry_point_records(group: str) -> list[dict[str, object]]:
    try:
        points = importlib.metadata.entry_points(group=group)
    except TypeError:
        points = importlib.metadata.entry_points().get(group, [])
    records = []
    for point in points:
        dist = getattr(point, "dist", None)
        records.append(
            {
                "group": group,
                "name": point.name,
                "value": point.value,
                "distribution": getattr(dist, "name", None),
                "distribution_version": getattr(dist, "version", None),
                "distribution_path": str(getattr(dist, "_path", "")),
            }
        )
    return sorted(records, key=lambda row: (str(row["name"]), str(row["value"])))


def application_plugin_profile(repo: Path) -> dict[str, object]:
    post_environment = environment_snapshot()
    if post_environment != expected_post_pytest_environment(repo):
        raise RuntimeError(
            f"post-pytest environment escaped the exact allowlist: {post_environment!r}"
        )
    selectors = {key: os.environ.get(key) for key in RUNTIME_SELECTOR_KEYS}
    expected_selectors = {
        "PHASE_LOOP_PROFILE_PLUGINS": PROFILE_SELECTOR,
        "PHASE_LOOP_SKILL_SOURCE_PLUGINS": SKILL_SOURCE_SELECTOR,
        "PHASE_LOOP_RUNNER_REPO_ROOT": None,
        "PHASE_LOOP_CLAUDE_ROUTE": None,
        "CI": None,
        "PHASE_LOOP_REVIEWTRUTH_POST_PARSER_COLLECTION": None,
        "PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH": None,
        "PHASE_LOOP_SKIP_GATE_A_SUITE": None,
    }
    if selectors != expected_selectors:
        raise RuntimeError(f"runtime selector drift after pytest: {selectors!r}")

    entry_points = {group: entry_point_records(group) for group in APPLICATION_PLUGIN_GROUPS}
    if any(entry_points.values()):
        raise RuntimeError(f"application plugin entry points are forbidden in baseline: {entry_points!r}")

    from phase_loop_runtime.cli import _profile_command_registrars
    from phase_loop_runtime.skill_inventory import iter_skill_source_roots

    registrars = list(_profile_command_registrars())
    if len(registrars) != 1:
        raise RuntimeError(f"expected exactly one profile registrar, got {len(registrars)}")
    profile_registrars = [callable_record(value, repo) for value in registrars]

    module_name, _, attr = SKILL_SOURCE_SELECTOR.partition(":")
    provider = getattr(importlib.import_module(module_name), attr)
    provider_records = [callable_record(provider, repo)]
    roots = [
        {"harness": harness, "roots": list(values)}
        for harness, values in iter_skill_source_roots()
    ]
    expected_roots = [
        {"harness": "claude", "roots": ["skills-src/claude"]},
        {"harness": "codex", "roots": ["skills-src/codex"]},
        {"harness": "gemini", "roots": ["skills-src/gemini"]},
        {"harness": "opencode", "roots": ["skills-src/opencode"]},
    ]
    if roots != expected_roots:
        raise RuntimeError(f"skill-source root drift: {roots!r}")

    expected_sources = {
        "phase-loop-runtime/src/phase_loop_runtime/dotfiles_profile_plugin.py",
        "phase-loop-runtime/src/phase_loop_runtime/skill_sources_plugin.py",
    }
    actual_sources = {
        str(profile_registrars[0]["source"]["repo_relative_path"]),
        str(provider_records[0]["source"]["repo_relative_path"]),
    }
    if actual_sources != expected_sources:
        raise RuntimeError(f"application plugin source drift: {sorted(actual_sources)!r}")
    return {
        "post_pytest_environment": post_environment,
        "selectors": selectors,
        "entry_points": entry_points,
        "profile_registrars": profile_registrars,
        "skill_source_providers": provider_records,
        "skill_source_roots": roots,
    }


def canonical_nodeid(nodeid: str, repo: Path, rootpath: Path) -> str:
    path_text, marker, suffix = nodeid.partition("::")
    path = Path(path_text)
    if not path.is_absolute():
        path = rootpath / path
    resolved = path.resolve()
    try:
        rel = resolved.relative_to(repo).as_posix()
    except ValueError as exc:
        raise RuntimeError(f"nodeid outside repository: {nodeid}") from exc
    return rel + ((marker + suffix) if marker else "")


def normalized_reason(value: object, repo: Path) -> str:
    return str(value).replace(str(repo), "<REPO>")


class Observer:
    def __init__(self, repo: Path, initial_environment: dict[str, str]) -> None:
        self.repo = repo
        self.rootpath = repo
        self.process = process_identity()
        self.initial_environment = initial_environment
        self.full: list[str] = []
        self.selected: list[str] = []
        self.deselected: list[str] = []
        self.markers: dict[str, list[str]] = {}
        self.skips: list[dict[str, str]] = []
        self.plugins: list[dict[str, object]] = []
        self.application_plugins: dict[str, object] = {}

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_collection_modifyitems(self, session, config, items):
        self.rootpath = Path(config.rootpath).resolve()
        self.full = [canonical_nodeid(item.nodeid, self.repo, self.rootpath) for item in items]
        self.markers = {
            canonical_nodeid(item.nodeid, self.repo, self.rootpath): sorted(
                {marker.name for marker in item.iter_markers()}
            )
            for item in items
        }
        yield
        self.selected = [canonical_nodeid(item.nodeid, self.repo, self.rootpath) for item in items]

    def pytest_deselected(self, items):
        self.deselected.extend(
            canonical_nodeid(item.nodeid, self.repo, self.rootpath) for item in items
        )

    def pytest_runtest_logreport(self, report):
        if report.skipped:
            self.skips.append(
                {
                    "nodeid": canonical_nodeid(report.nodeid, self.repo, self.rootpath),
                    "phase": report.when,
                    "reason": normalized_reason(report.longrepr, self.repo),
                }
            )

    def pytest_collectreport(self, report):
        if report.skipped:
            self.skips.append(
                {
                    "nodeid": canonical_nodeid(report.nodeid, self.repo, self.rootpath),
                    "phase": "collect",
                    "reason": normalized_reason(report.longrepr, self.repo),
                }
            )

    def pytest_sessionfinish(self, session, exitstatus):
        manager = session.config.pluginmanager
        distributions = {id(plugin): dist for plugin, dist in manager.list_plugin_distinfo()}
        records = []
        for name, plugin in manager.list_name_plugin():
            module = plugin if inspect.ismodule(plugin) else inspect.getmodule(plugin)
            module_name = getattr(module, "__name__", type(plugin).__module__)
            module_path = Path(module.__file__) if module is not None and getattr(module, "__file__", None) else None
            dist = distributions.get(id(plugin))
            records.append(
                {
                    "plugin_name": str(name),
                    "module": module_name,
                    "class": type(plugin).__qualname__,
                    "distribution": getattr(dist, "project_name", None),
                    "distribution_version": getattr(dist, "version", None),
                    "file": file_record(module_path, self.repo),
                }
            )
        self.plugins = sorted(records, key=lambda row: (row["plugin_name"], row["module"]))
        self.application_plugins = application_plugin_profile(self.repo)

    def payload(self, pytest_argv: list[str], exit_code: int) -> dict[str, object]:
        full = sorted(self.full)
        selected = sorted(self.selected)
        deselected = sorted(self.deselected)
        difference = sorted(set(full) - set(selected))
        if len(full) != len(set(full)) or len(selected) != len(set(selected)):
            raise RuntimeError("duplicate collected or selected nodeid")
        if difference != deselected or len(deselected) != len(set(deselected)):
            raise RuntimeError("deselection notification does not equal full-minus-selected")
        if any(MARKER not in self.markers.get(nodeid, []) for nodeid in difference):
            raise RuntimeError("non-marker nodeid appeared in marker-filter difference")
        if any(MARKER in self.markers.get(nodeid, []) for nodeid in selected):
            raise RuntimeError("marker-filtered nodeid survived selection")
        post_environment = environment_snapshot()
        if post_environment != expected_post_pytest_environment(self.repo):
            raise RuntimeError(
                f"environment drifted after pytest session finish: {post_environment!r}"
            )
        if post_environment != self.application_plugins.get("post_pytest_environment"):
            raise RuntimeError("post-pytest environment changed after application-plugin sealing")
        return {
            "schema": SCHEMA,
            "process": self.process,
            "pytest_argv": pytest_argv,
            "pytest_argv_sha256": sha(canonical_json(pytest_argv)),
            "exit_code": exit_code,
            "full_nodeids": full,
            "selected_nodeids": selected,
            "marker_deselected_nodeids": difference,
            "markers_by_nodeid": {key: self.markers[key] for key in sorted(self.markers)},
            "legitimate_skips": sorted(
                self.skips, key=lambda row: (row["nodeid"], row["phase"], row["reason"])
            ),
            "plugins": self.plugins,
            "environment_before_pytest": self.initial_environment,
            "environment_after_pytest": post_environment,
            "application_plugins": self.application_plugins,
        }


def snapshot(repo: Path) -> dict[str, object]:
    status = git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    return {
        "head": git(repo, "rev-parse", "HEAD").decode().strip(),
        "head_tree": git(repo, "rev-parse", "HEAD^{tree}").decode().strip(),
        "index_tree": git(repo, "write-tree").decode().strip(),
        "status_porcelain_v1_z_hex": status.hex(),
        "status_sha256": sha(status),
        "clean": status == b"",
    }


def write(path: Path, data: bytes) -> None:
    path.write_bytes(data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--roadmap", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--observer-sha256", required=True)
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    if Path(git(repo, "rev-parse", "--show-toplevel").decode().strip()).resolve() != repo:
        raise RuntimeError("--repo is not the exact git toplevel")
    observer_path = Path(__file__).resolve()
    observer_bytes = observer_path.read_bytes()
    if sha(observer_bytes) != args.observer_sha256:
        raise RuntimeError("observer source digest mismatch")
    final = (repo / args.out).resolve()
    evidence_root = (repo / ".phase-loop" / "evidence").resolve()
    if evidence_root not in final.parents or final.exists():
        raise RuntimeError("output must be a new child of .phase-loop/evidence")
    initial_environment = environment_snapshot()
    expected_environment = expected_initial_environment(repo)
    if initial_environment != expected_environment:
        raise RuntimeError(
            f"initial environment is not the exact controlled allowlist: {initial_environment!r}"
        )
    baseline_home = Path(expected_environment["HOME"])
    if not baseline_home.is_dir() or any(baseline_home.iterdir()):
        raise RuntimeError("controlled baseline HOME must exist and be empty")
    observation_id = str(uuid.uuid4())
    temporary = final.with_name(final.name + ".tmp-" + observation_id)
    temporary.mkdir(parents=True, exist_ok=False)

    before = snapshot(repo)
    if not before["clean"]:
        raise RuntimeError("baseline requires a clean tree before collection")
    plan = (repo / args.plan).resolve()
    roadmap = (repo / args.roadmap).resolve()
    pytest_argv = [
        "phase-loop-runtime/tests",
        "-q",
        "-m",
        "not dotfiles_integration",
        "-p",
        "no:cacheprovider",
        f"--junitxml={temporary / 'broad.xml'}",
    ]
    observer = Observer(repo, initial_environment)
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = int(pytest.main(pytest_argv, plugins=[observer]))
    stdout_bytes = stdout.getvalue().encode()
    stderr_bytes = stderr.getvalue().encode()
    write(temporary / "stdout.txt", stdout_bytes)
    write(temporary / "stderr.txt", stderr_bytes)

    events = observer.payload(pytest_argv, exit_code)
    write(temporary / "plugin-events.json", canonical_json(events))
    for name, values in (
        ("full-nodeids.txt", events["full_nodeids"]),
        ("selected-nodeids.txt", events["selected_nodeids"]),
        ("marker-deselected-nodeids.txt", events["marker_deselected_nodeids"]),
    ):
        write(temporary / name, ("".join(f"{value}\n" for value in values)).encode())
    write(temporary / "legitimate-skips.json", canonical_json(events["legitimate_skips"]))

    after = snapshot(repo)
    if exit_code != 0:
        raise RuntimeError(f"broad baseline exited {exit_code}")
    if before != after or not after["clean"]:
        raise RuntimeError("HEAD/tree/index/clean status changed during observation")
    if events["process"] != process_identity():
        raise RuntimeError("collection and attestation process identity differ")

    artifacts = {}
    for path in sorted(temporary.iterdir()):
        if path.is_file():
            data = path.read_bytes()
            artifacts[path.name] = {"sha256": sha(data), "bytes": len(data)}
    command_argv = list(sys.argv)
    attestation = {
        "schema": SCHEMA,
        "observation_id": observation_id,
        "observer": {"path": str(observer_path), "sha256": sha(observer_bytes)},
        "command_argv": command_argv,
        "command_argv_sha256": sha(canonical_json(command_argv)),
        "git_before": before,
        "git_after": after,
        "plan": {"path": args.plan, "sha256": sha(plan.read_bytes())},
        "roadmap": {"path": args.roadmap, "sha256": sha(roadmap.read_bytes())},
        "process": process_identity(),
        "environment": {
            "initial_allowlist": events["environment_before_pytest"],
            "post_pytest": events["environment_after_pytest"],
            "runtime_selectors": events["application_plugins"]["selectors"],
        },
        "application_plugins": events["application_plugins"],
        "python": {
            "executable": sys.executable,
            "executable_realpath": str(Path(sys.executable).resolve()),
            "version": sys.version,
            "version_info": list(sys.version_info),
            "implementation": platform.python_implementation(),
            "cache_tag": sys.implementation.cache_tag,
            "prefix": sys.prefix,
            "base_prefix": sys.base_prefix,
        },
        "modules": [module_record(name, repo) for name in ("pytest", "_pytest", "pluggy")],
        "pytest": {
            "version": pytest.__version__,
            "module": module_record("pytest", repo),
            "argv": pytest_argv,
            "argv_sha256": events["pytest_argv_sha256"],
            "plugins": events["plugins"],
        },
        "counts": {
            "full": len(events["full_nodeids"]),
            "selected": len(events["selected_nodeids"]),
            "marker_deselected": len(events["marker_deselected_nodeids"]),
            "legitimate_skips": len(events["legitimate_skips"]),
        },
        "set_sha256": {
            "full_sorted_lf": artifacts["full-nodeids.txt"]["sha256"],
            "selected_sorted_lf": artifacts["selected-nodeids.txt"]["sha256"],
            "marker_deselected_sorted_lf": artifacts["marker-deselected-nodeids.txt"]["sha256"],
        },
        "artifacts": artifacts,
    }
    write(temporary / "attestation.json", canonical_json(attestation))
    temporary.rename(final)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```
<!-- REVIEWTRUTH_BASELINE_OBSERVER_END -->

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- target surfaces: `none outside this repo`
- evidence paths: `plans/phase-plan-v10-REVIEWTRUTH.md`, `docs/research/reviewtruth-leg-capability-ratification.md`, `docs/research/reviewtruth-red-baseline.md`, `docs/research/reviewtruth-phase-verification.md`, `docs/research/reviewtruth-real-panel-smoke.md`, `docs/research/reviewtruth-final-evidence-record.md`, `phase-loop-runtime/tests/conftest.py`, `phase-loop-runtime/tests/test_reviewtruth_phase.py`, `phase-loop-runtime/tests/test_train_merge.py`, `phase-loop-runtime/tests/test_governed_cross_vendor_floor_358.py`, `phase-loop-runtime/tests/test_advisor_board_golden.py`, `phase-loop-runtime/tests/test_advisor_board_research.py`, `phase-loop-runtime/tests/test_panel_invoker_spawn.py`, `phase-loop-runtime/tests/test_panel_native_fill_183.py`
- redaction posture: `metadata_only`
- downstream handling: `none`; closeout follows `REVIEWTRUTH-redacted-transcript-policy` and carries only the exact canonical transcript/smoke path `docs/research/reviewtruth-real-panel-smoke.md` and its single frozen digest, seat metadata, and artifact-specific citations

## Verification

SL-1 executes these command bullets from top to bottom in exact order. The first command materializes the exact reviewed observer payload without overwriting an existing file. The second command runs the single-process observation on the untouched clean base before any SL-1 edit, when the wrappers, repo observer, and parser do not exist. The third command runs only after `verify_reviewtruth_chronology.py` and its independent bootstrap/parser tests have been authored, and consumes the already-sealed write-once observation. These three bullets are executable operational evidence commands deliberately marked `evidence: operational`: plan intake records but does not auto-execute them against a later tree. All remaining bullets are ordinary non-operational verifier commands, and every parser runs only after all named inputs exist:

- `python3 -c 'import hashlib,pathlib; s=pathlib.Path("plans/phase-plan-v10-REVIEWTRUTH.md").read_text(encoding="utf-8"); fence=chr(96)*3; b=(s.split("<!-- REVIEWTRUTH_BASELINE_OBSERVER_BEGIN -->\n"+fence+"python\n",1)[1].split("\n"+fence+"\n<!-- REVIEWTRUTH_BASELINE_OBSERVER_END -->",1)[0]+"\n").encode(); assert hashlib.sha256(b).hexdigest()=="b5fcd773ec6d14ebacc0aa84e25b0bb2b8a47a11a6860ba2b243028543bae223"; p=pathlib.Path(".phase-loop/evidence/reviewtruth-baseline-observer.py"); h=pathlib.Path(".phase-loop/evidence/reviewtruth-baseline-home").resolve(); p.parent.mkdir(parents=True,exist_ok=True); assert not p.exists() and not h.exists(); h.mkdir(); p.write_bytes(b); p.chmod(0o700)'` evidence: operational
- `env -i HOME="$PWD/.phase-loop/evidence/reviewtruth-baseline-home" PATH=/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH="$PWD/phase-loop-runtime/src" /usr/bin/python3 .phase-loop/evidence/reviewtruth-baseline-observer.py --repo . --plan plans/phase-plan-v10-REVIEWTRUTH.md --roadmap specs/phase-plans-v10.md --out .phase-loop/evidence/reviewtruth-baseline-preimplementation --observer-sha256 b5fcd773ec6d14ebacc0aa84e25b0bb2b8a47a11a6860ba2b243028543bae223` evidence: operational
- `PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit --mode broad-baseline --observation-dir .phase-loop/evidence/reviewtruth-baseline-preimplementation --observer-source .phase-loop/evidence/reviewtruth-baseline-observer.py --observer-sha256 b5fcd773ec6d14ebacc0aa84e25b0bb2b8a47a11a6860ba2b243028543bae223` evidence: operational
- `env REVIEWTRUTH_JUNIT_XML=.phase-loop/evidence/reviewtruth-phase-default.xml sh -c 'PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit-run --mode default-premarker --xml "$REVIEWTRUTH_JUNIT_XML"'`
- `env REVIEWTRUTH_JUNIT_XML=.phase-loop/evidence/reviewtruth-broad-default.xml sh -c 'PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration" --junitxml="$REVIEWTRUTH_JUNIT_XML"'`
- `env REVIEWTRUTH_PHASE_JUNIT_XML=.phase-loop/evidence/reviewtruth-phase-default.xml REVIEWTRUTH_BROAD_JUNIT_XML=.phase-loop/evidence/reviewtruth-broad-default.xml sh -c 'PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit --mode default-premarker --phase-xml "$REVIEWTRUTH_PHASE_JUNIT_XML" --broad-xml "$REVIEWTRUTH_BROAD_JUNIT_XML"'`
- `env PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1 REVIEWTRUTH_JUNIT_XML=.phase-loop/evidence/reviewtruth-phase-red.xml sh -c 'PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit-run --mode activated-red --xml "$REVIEWTRUTH_JUNIT_XML"'` (records pytest's expected nonzero after the XML exists and returns control without judging failures)
- `env REVIEWTRUTH_JUNIT_XML=.phase-loop/evidence/reviewtruth-phase-red.xml sh -c 'PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit --mode activated-red --phase-xml "$REVIEWTRUTH_JUNIT_XML"'`
- `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_advisor_board_golden.py -q`

After SL-5 is complete, every pushed implementation candidate, panel attempt, and merge decision executes these command bullets from top to bottom in exact order from a fresh exact-head process:

- `env REVIEWTRUTH_JUNIT_XML=.phase-loop/evidence/reviewtruth-phase-candidate.xml sh -c 'PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit-run --mode candidate --xml "$REVIEWTRUTH_JUNIT_XML"'`
- `env REVIEWTRUTH_JUNIT_XML=.phase-loop/evidence/reviewtruth-broad-candidate.xml sh -c 'PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration" --junitxml="$REVIEWTRUTH_JUNIT_XML"'`
- `env REVIEWTRUTH_PHASE_JUNIT_XML=.phase-loop/evidence/reviewtruth-phase-candidate.xml REVIEWTRUTH_BROAD_JUNIT_XML=.phase-loop/evidence/reviewtruth-broad-candidate.xml sh -c 'PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit --mode candidate --phase-xml "$REVIEWTRUTH_PHASE_JUNIT_XML" --broad-xml "$REVIEWTRUTH_BROAD_JUNIT_XML"'`
- `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration"`
- `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_advisor_board_golden.py -q`

The broad and plain suite commands leave `PHASE_LOOP_REVIEWTRUTH_POST_PARSER_COLLECTION` unset and require the canonical full/selected collections and collection-plugin fingerprint to equal the frozen post-SL-1 source/CI profile, plus total deselections equal to the immutable marker-filter baseline UNION exactly the hook's five wrappers, with the marker and hook categories attested separately from each other and from skips. The candidate parser rejects full/selected-set or plugin drift, marker drift, a missing/extra hook wrapper, any external `--deselect`, arbitrary/category-swapped deselection, or skip/deselection substitution. Only after all five commands and required GitHub CI across Python 3.10/3.11/3.12 are GREEN at the same exact pushed head may the exact-head four-seat implementation panel launch and the merge decision occur.

After the distinct implementation landing is on canonical `main` and SL-6 has written only its owned pre-final evidence/docs, SL-6 executes these command bullets from top to bottom in exact order from its different fresh process. The broad-final parser must be GREEN before the phase-final runner starts; the final parser must be GREEN before the record is finalized; the finalized record must exist before its verifier runs; and the `final-record` attestation must be GREEN before the golden/default-suite/Gate-A/static checks and the record-bound closeout start:

- `env REVIEWTRUTH_JUNIT_XML=.phase-loop/evidence/reviewtruth-broad-final.xml sh -c 'PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration" --junitxml="$REVIEWTRUTH_JUNIT_XML"'`
- `env REVIEWTRUTH_JUNIT_XML=.phase-loop/evidence/reviewtruth-broad-final.xml sh -c 'PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit --mode broad-final-producer --xml "$REVIEWTRUTH_JUNIT_XML"'`
- `env REVIEWTRUTH_JUNIT_XML=.phase-loop/evidence/reviewtruth-phase-final.xml sh -c 'PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit-run --mode final --xml "$REVIEWTRUTH_JUNIT_XML"'`
- `env REVIEWTRUTH_PHASE_JUNIT_XML=.phase-loop/evidence/reviewtruth-phase-final.xml REVIEWTRUTH_BROAD_JUNIT_XML=.phase-loop/evidence/reviewtruth-broad-final.xml sh -c 'PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit --mode final --phase-xml "$REVIEWTRUTH_PHASE_JUNIT_XML" --broad-xml "$REVIEWTRUTH_BROAD_JUNIT_XML"'`
- `PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_evidence.py finalize-record --phase-xml .phase-loop/evidence/reviewtruth-phase-final.xml --broad-xml .phase-loop/evidence/reviewtruth-broad-final.xml --record docs/research/reviewtruth-final-evidence-record.md` (literal paths only; assigns and expands no shell variable)
- `PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_evidence.py final-record --record docs/research/reviewtruth-final-evidence-record.md --attestation .phase-loop/evidence/reviewtruth-final-record-attestation.json` (literal paths only; assigns and expands no shell variable)
- `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_advisor_board_golden.py -q`
- `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration"`
- `env -u PHASE_LOOP_SKIP_GATE_A_SUITE -u PHASE_LOOP_REVIEWTRUTH_POST_PARSER_COLLECTION sh -c 'PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_evidence.py gate-a --script phase-loop-runtime/scripts/gate_a_cleanroom.sh --artifact .phase-loop/evidence/reviewtruth-gate-a-suite.json --attestation .phase-loop/evidence/reviewtruth-gate-a-suite-attestation.json'`
- `ruff check phase-loop-runtime/src/phase_loop_runtime/`
- `phase-loop validate-roadmap specs/phase-plans-v10.md`
- `git diff --check`

Candidate phase-selected JUnit uses the frozen non-wrapper phase set and requires zero phase skips; final phase-selected JUnit uses the full expected set, runs every strict wrapper exactly once after broad-final attestation, and requires zero phase skips or deselections. Candidate and final broad JUnit require the exact frozen post-SL-1 full/selected collections, the allowed source/CI collection-plugin profile, exactly the unchanged marker-filter deselection baseline plus exactly the five hook-owned wrappers as disjoint categories, and exactly the unchanged legitimate pre-implementation skip baseline; they reject new, missing, external, arbitrary, category-swapped, plugin-drifted, collection-drifted, or otherwise changed skip/deselection accounting and do not require or claim five total deselections or whole-suite zero skips. The unchanged frontmatter suite command and GitHub CI use the source/CI profile. The sole normative clean-room Gate A command explicitly unsets both `PHASE_LOOP_SKIP_GATE_A_SUITE` and final collection activation; its reducer also rejects either selector when invoked without that sanitization, runs the unmodified script under trace, and emits write-once stdout/stderr, machine-checkable suite-count/profile/sentinel JSON, and a fresh-child attestation. Gate A is GREEN only when that attestation proves the full copied standalone pytest tree actually executed once under exact `-q -p no:cacheprovider -m "not dotfiles_integration"`, at least one test executed, the terminal outcome has no failures/errors, the SKIPPED sentinel is absent, and the ordered start/GREEN sentinels and all bound digests match. All suites remain GREEN without bootstrap run-local evidence on fresh clones. The post-parser finalized record, its `final-record` attestation, and the later Gate A artifacts are never consumed by any test wrapper; the finalized record deliberately excludes Gate A, and the four-seat closeout review plus canonical ledger closeout bind the finalized-record attestation and terminal Gate A attestation without creating a cycle.

## Acceptance Criteria

The normative EC-REVIEWTRUTH-0 and EC-REVIEWTRUTH-9 commands run only at SL6-T3 after SL6-T2 has frozen every wrapper input. Each command explicitly clears inherited final collection, generates and parses broad-final first, delegates final activation only to immutable `junit-run --mode final`, and then parses phase-final; neither a plain pytest selector, hand-set activation, nor wrapper-before-attestation can satisfy either criterion.

- [ ] EC-REVIEWTRUTH-0 — proven by `env -u PHASE_LOOP_REVIEWTRUTH_POST_PARSER_COLLECTION REVIEWTRUTH_BROAD_JUNIT_XML=.phase-loop/evidence/reviewtruth-broad-final.xml REVIEWTRUTH_PHASE_JUNIT_XML=.phase-loop/evidence/reviewtruth-phase-final.xml sh -c 'PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration" --junitxml="$REVIEWTRUTH_BROAD_JUNIT_XML" && PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit --mode broad-final-producer --xml "$REVIEWTRUTH_BROAD_JUNIT_XML" && PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit-run --mode final --xml "$REVIEWTRUTH_PHASE_JUNIT_XML" && PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit --mode final --phase-xml "$REVIEWTRUTH_PHASE_JUNIT_XML" --broad-xml "$REVIEWTRUTH_BROAD_JUNIT_XML"'`
- [ ] EC-REVIEWTRUTH-1 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k ec_reviewtruth_1_delivery_states_and_shortfall`
- [ ] EC-REVIEWTRUTH-2 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k ec_reviewtruth_2_outcome_not_text`
- [ ] EC-REVIEWTRUTH-3 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k ec_reviewtruth_3_spawn_raise_never_becomes_block`
- [ ] EC-REVIEWTRUTH-4 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k ec_reviewtruth_4_harness_board_three_state`
- [ ] EC-REVIEWTRUTH-5 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k ec_reviewtruth_5_lens_prompt_and_coverage`
- [ ] EC-REVIEWTRUTH-6 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_advisor_board_golden.py -q`
- [ ] EC-REVIEWTRUTH-7 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k ec_reviewtruth_7_retry_not_count`
- [ ] EC-REVIEWTRUTH-8 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k ec_reviewtruth_8_production_apply_fix`
- [ ] EC-REVIEWTRUTH-9 — proven by `env -u PHASE_LOOP_REVIEWTRUTH_POST_PARSER_COLLECTION REVIEWTRUTH_BROAD_JUNIT_XML=.phase-loop/evidence/reviewtruth-broad-final.xml REVIEWTRUTH_PHASE_JUNIT_XML=.phase-loop/evidence/reviewtruth-phase-final.xml sh -c 'PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration" --junitxml="$REVIEWTRUTH_BROAD_JUNIT_XML" && PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit --mode broad-final-producer --xml "$REVIEWTRUTH_BROAD_JUNIT_XML" && PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit-run --mode final --xml "$REVIEWTRUTH_PHASE_JUNIT_XML" && PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit --mode final --phase-xml "$REVIEWTRUTH_PHASE_JUNIT_XML" --broad-xml "$REVIEWTRUTH_BROAD_JUNIT_XML"'`
- [ ] EC-REVIEWTRUTH-10 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k ec_reviewtruth_10_production_panel_verdict`
- [ ] EC-REVIEWTRUTH-11 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k ec_reviewtruth_11_live_non_fab_ledger`
- [ ] EC-REVIEWTRUTH-12 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k ec_reviewtruth_12_grounding_refusal_and_repo_substitution`
- [ ] EC-REVIEWTRUTH-13 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k ec_reviewtruth_13_substantive_material_guard`
- [ ] EC-REVIEWTRUTH-14 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k ec_reviewtruth_14_native_fable_request_report_binding`
- [ ] EC-REVIEWTRUTH-15 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k ec_reviewtruth_15_capability_ratification`
