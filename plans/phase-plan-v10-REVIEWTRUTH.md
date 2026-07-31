---
phase_loop_plan_version: 1
phase: REVIEWTRUTH
roadmap: specs/phase-plans-v10.md
roadmap_sha256: a289891a6f6bf27e07e3c1a5260d25f813f90931404c47dd2efc487e0aa268ba
automation:
  suite_command: 'PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration"'
---

# REVIEWTRUTH: Board Reports Its Own Degradation

## Context

REVIEWTRUTH is explicitly selected for this run. Canonical `.phase-loop/state.json` and `.phase-loop/tui-handoff.md` now agree that REVIEWTRUTH is the current `planned` phase, and the newest canonical ledger event records the GPT-5.6 Sol planning run at maximum effort. This planning repair is confined to this plan, its matching manifest metadata/digest update, and the force-added `phase-loop-runtime/uv.lock` bootstrap prerequisite. Legacy `.codex/phase-loop/` state is compatibility-only and is not authoritative.

The phase replaces the board's text-derived usability shortcut with a typed per-seat outcome, distinguishes FULL, FLOOR-ONLY, and BELOW-FLOOR delivery, makes lens and artifact grounding load-bearing, wires native Fable fill requests back into board results, persists per-seat and aggregate governed outcomes, fails closed on empty or elided material, and connects the production repair round. It does not implement LEGLIFE timeout enforcement or custom per-repo seats; it only freezes and consumes the `timed_out` outcome that LEGLIFE later produces.

The roadmap names four implementation lanes. This plan maps them to SL-2 through SL-5 and adds three control lanes: SL-0 decides `agent-harness#398`, obtains maintainer ratification, and separately lands the durable posture record before any posture-assuming change; SL-1 lands the literal PANELLED RED tests-only boundary, both chronology modes, every immutable REVIEWTRUTH evidence wrapper, the frozen ordinary-suite collection hook in `phase-loop-runtime/tests/conftest.py`, the complete live floor-2 assertion migration in `test_governed_cross_vendor_floor_358.py` and `test_train_merge.py`, the normative sanctioned-delta amendment in `test_advisor_board_golden.py`, and all five known compatibility migrations in `test_advisor_board_research.py`, `test_panel_invoker_spawn.py`, and `test_panel_native_fill_183.py`, including all three existing under-Claude-Code Fable native-fill reversals in the last file; SL-5 ends at an explicit SL-2-through-SL-5 implementation PR/landing boundary and owns the required `gate_a_cleanroom.sh` neutral persistent-evidence-copy implementation plus the explicit `.github/workflows/test.yml` lifecycle; and SL-6 starts from the resulting canonical-main tip to reduce final chronology, live, source-ownership, structured JUnit, and verification evidence. All ten SL-1 paths are immutable after the tests-only landing. `panel_invoker.py` remains a single-writer file in SL-2. SL-5 owns the driver-side/native integration plus `train_runner.py`, `train_ledger.py`, the Gate A copy boundary, and the workflow caller contract, consumes SL-2's frozen binding API and SL-3/SL-4's grounded classifier, and makes no test edits, so no lane overlaps those files.

Within that mapping, `phase-loop-runtime/scripts/verify_reviewtruth_evidence.py` is exclusively SL-5-owned and lands atomically with `gate_a_cleanroom.sh` and `.github/workflows/test.yml`; SL-6 consumes the immutable executable and cannot author, stage, or repair it.

`agent-harness#398` remains an open design issue as rechecked read-only with `gh` on 2026-07-30. Its only comment is the coordinator's explicit request that a maintainer ratify Option 2 (evidence staging) or state another bounded posture; no maintainer has supplied that decision. Merged `agent-harness#400` assigns the decision to REVIEWTRUTH but does not decide or ratify the capability posture. The coordinator recommendation is not ratification. Neither the v10 roadmap's blanket execution authorization, this plan's four-seat review, an advisor-board verdict, nor issue discussion substitutes for the missing maintainer-ratified disposition record. SL-0 is therefore an unsatisfied human gate and hard precondition: SL-1 through SL-6 must remain undispatched until explicit maintainer ratification exists and the matching durable record is separately merged as an ancestor of canonical `main`.

An earlier authoritative exact-digest panel at `.phase-loop/reviews/v10-reviewtruth-plan-panel.json` reviewed plan SHA-256 `dcebcaf0df4542f41c853ce205982bf170ed1d634883a7ff4e408334385e1617`. Grok 4.5 and Gemini 3.6 Flash returned AGREE, GPT-5.6 Sol returned DISAGREE, and Fable deferred. Sol identified three blockers: candidate/final JUnit files were generated with unsafe same-command variable expansion and never parsed before their consumers; phase-node zero-skip claims were incorrectly applied to a broad suite with legitimate pre-existing opt-in skips; and SL-1 omitted `phase-loop-runtime/tests/test_panel_native_fill_183.py::DefaultClaudeSeatNeverCarriesNativeFill::test_brief_ref_flows_into_the_request`, a second existing under-Claude-Code Fable native-fill reversal. The prior repair gave every XML a literal runner-owned path, froze generation-before-parse-before-consumer ordering, separated phase-selected accounting from a broad baseline skip-set/digest, and brought all five compatibility migrations into SL-1's immutable ownership with legacy, forced-activation, and automatic post-marker assertions. The follow-up exact-digest review of plan SHA-256 `bebb671c795d16f84c0303346e2897aabae211832791388081b1a03c3819727d` identified one remaining blocker: SL6-T2's durable evidence record claimed the final phase/broad XML and parser-attestation digests that SL6-T3 only generates and parses afterward, so the phase-final wrappers would have consumed a record containing themselves, and any later evidence-doc update would have bound the four-vendor review and the phase-final run to stale evidence-document digests. This repair makes SL-6 evidence acyclic: SL6-T2 stages and boards a pre-final record limited to already-existing artifacts; the phase-final wrappers consume only frozen pre-final inputs plus the broad-final producer attestation; only after the final-mode parse does `finalize-record` write the write-once post-parser record at `docs/research/reviewtruth-final-evidence-record.md`; the separate minimal `final-record` verifier attests that record from outside it; and the four-seat closeout binds the finalized record digest plus that attestation, with verdicts written only to the canonical ledger. The exact-digest review of plan SHA-256 `405b07f458dec59e50cb94cae2902a128031859412d4894b6417d4b2fc217e75` identified one remaining ownership blocker: the plan required a separately digested durable redacted transcript without owning any second transcript path. The next repair designated the already-owned `docs/research/reviewtruth-real-panel-smoke.md` as the single canonical durable redacted transcript and smoke record, with one frozen SHA-256 digest and no second durable transcript path. The latest exact-digest panel in that same review artifact inspected plan SHA-256 `7c80a2d3133c4ad17f2aa8fcc8f7ea738f3e806dd7dafe0a3d72404f45a7957d`; Grok 4.5 found that the five marker-activated post-parser wrappers made ordinary GitHub CI, Gate A, the frontmatter `suite_command`, and every fresh clone permanently red because only special candidate/final commands deselected them, while GPT-5.6 Sol found that `seat_key` cannot bind a native report because it is explicitly non-unique and a late or replayed report can attach to a current colliding seat. This repair gives SL-1 a frozen dual-mode collection hook whose sole strict arm is activated by the immutable final phase runner after broad-final attestation, and freezes per-seat-instance, per-request, and per-attempt native identities plus exact-once report consumption and durable reconstruction. The new digest invalidates every previously reviewed digest. Before SL-0 starts, the coordinator must panel the new exact SHA-256 digest with Fable 5, GPT-5.6 Sol, Gemini 3.6 Flash, and Grok 4.5. Fable and Sol must both return reviewed outcomes. Any unavailable, errored, empty, capped, refused, or timed-out Fable or Sol seat blocks dispatch; every material finding requires a plan edit and a fresh review of the changed digest.

The fresh local panel recorded in that artifact then reviewed exact plan SHA-256 `aebb6159b98dbc98b70a02b1c782476e852c2f1316c05bbaaa6c6fca1569fced` from staged bundle SHA-256 `7ce2b2469591cdaad4d4d17835b744e9ae53b19777b6f801690467e364b4c55c` (176577 bytes) under instructions SHA-256 `700499a4fa5cf1ef7a995f1ee4259f146d32aa4e0b269d5d2b886477f8ef8846`; its recorded staging path was `/tmp/pl-panel-bxisa895/review/`. Grok 4.5 and GPT-5.6 Sol returned DISAGREE and Gemini 3.6 Flash returned AGREE. Grok proved that the normative EC-REVIEWTRUTH-0 and EC-REVIEWTRUTH-9 commands selected only wrappers that ordinary collection deselects, while Sol proved that `-m "not dotfiles_integration"` already contributes the large pre-existing marker-filter deselection baseline (the bootstrap record observed 601), so five cannot be the total broad deselection count. This repair binds both wrapper-backed criteria to the ordered broad-final/final proof chain and freezes marker-filter deselections as their own exact tuple/count/digest, separate from legitimate skips and the five hook-owned wrapper deselections. The changed digest again invalidates the reviewed digest and still requires the mandatory exact-digest Fable 5 + GPT-5.6 Sol + Gemini 3.6 Flash + Grok 4.5 panel before SL-0.

The latest local panel in `.phase-loop/reviews/v10-reviewtruth-plan-panel.json` reviewed exact plan SHA-256 `2b8c23afad5b1f028ec036167f164e430030e07440bb9c11a3d34affc4109ee6`; Grok 4.5 and Gemini 3.6 Flash returned AGREE and GPT-5.6 Sol returned DISAGREE. Sol found one blocker: the first two pre-edit commands produced only collect-only stdout and ordinary JUnit before either the proposed conftest observer or repo parser existed, so a later parser could not retroactively prove same-HEAD/tree/process/argv/runtime/plugin identity or reconstruct the marker-filter deselection tuple. A repository, canonical-runner, sibling-checkout, and dotfiles-source search found no existing coordinator-owned or runner-owned immutable pytest baseline observer. This repair therefore embeds a minimal external bootstrap observer as exact reviewable bytes below, SHA-256 `c782f3b9f503582df25a7489a4be97ed3f2e6853b021c3abf1ee874cf47d619c`. The exact-digest four-seat plan panel reviews both those bytes and their digest before SL-0; after SL-0, the bytes are materialized only into ignored runner evidence and execute once before any SL-1 hook, wrapper, verifier, or test mutation. One pytest process observes the full collected set before marker filtering, the selected set after `-m "not dotfiles_integration"`, the exact `pytest_deselected` multiset and marker membership, legitimate runtime and collection skips, raw stdout/stderr, JUnit, HEAD/tree/index/clean status, plan/roadmap/source digests, process identity, full process and pytest argv, the controlled pytest environment, Python/pytest/module provenance, and the loaded plugin inventory. The later SL-1 parser and mutation tests independently recompute every relation and digest from the raw observation; they do not treat the bootstrap attestation as self-authenticating. The changed plan digest invalidates `2b8c23af…` and again requires the mandatory exact-digest four-seat panel before SL-0.

The newest panel in that artifact reviewed exact plan SHA-256 `3e02663a2b7d4d1472a53cd15ba9fccaa704aad3403bc38c9b5e17ba26faa68f`; Grok 4.5 and Gemini 3.6 Flash returned AGREE and GPT-5.6 Sol returned DISAGREE. Sol found exactly two remaining blockers. First, the normative Gate A command inherited `PHASE_LOOP_SKIP_GATE_A_SUITE=1`, which lets the smoke pass while skipping the standalone pytest suite. This repair replaces every normative Gate A invocation with one owned two-stage `gate-a` evidence reducer that explicitly removes and internally rejects that selector, captures the unmodified script's traced output, requires exactly one installed-wheel full-suite start and GREEN sentinel in order, parses nonzero executed-test and outcome counts plus the exact `-q -p no:cacheprovider -m "not dotfiles_integration"` profile into a write-once canonical artifact, forbids the script's SKIPPED branch, and launches a fresh internal attester that independently re-hashes and verifies the artifact before static checks or closeout. Second, the bootstrap observer sanitized only pytest injection while `conftest.py` and `phase_loop_test_utils.py` can preserve ambient application plugin/root selectors. The repaired observer now starts under `env -i` with an exact seven-key allowlist, rejects every other key, proves suite initialization adds only the two exact in-tree profile/skill-source opt-ins, requires `PHASE_LOOP_RUNNER_REPO_ROOT`, `PHASE_LOOP_CLAUDE_ROUTE`, `CI`, both REVIEWTRUTH activation selectors, and `PHASE_LOOP_SKIP_GATE_A_SUITE` absent, requires both installed application entry-point groups empty, and attests every loaded registrar/provider source byte plus the complete skill-source root mapping. The later parser recomputes and freezes that entire environment/selector/registry/source/root profile and mutation-tests every drift arm. Both repairs stay outside wrapper inputs and the finalized record: their terminal attestations gate and are bound only by the canonical ledger closeout, preserving the existing acyclic final evidence chain.

The latest local panel in `.phase-loop/reviews/v10-reviewtruth-plan-panel.json` reviewed exact plan SHA-256 `67a448c622409515ed8c430013a13681ffb9b55446ec964b45142cd0c3cc24fe`; Gemini 3.6 Flash returned AGREE while Grok 4.5 and GPT-5.6 Sol returned DISAGREE. Grok proved that materializing observer source, HOME, and observation output under untracked `.phase-loop/` makes the required `git status --porcelain=v1 -z --untracked-files=all` clean check depend on this worktree's non-portable local exclude and fail in a fresh clone. Sol proved that the prescribed bare `/usr/bin/python3` cannot import `pytest`, `pydantic`, or `consiliency_contract` with user site disabled. This repair moves the complete bootstrap trust domain — managed Python, isolated environment, uv cache, external Git-archive source, built wheel, controlled HOME/TMPDIR, materialized observer, provisioning freeze, and raw observation — beneath one coordinator-provided canonical absolute runner root outside the git toplevel. A new operational provisioning stage uses the repository's established local-wheel-plus-`pytest` CI dependency shape and `phase-loop-runtime/uv.lock`/`pyproject.toml` through `uv`, never writes a build/cache/environment artifact into the worktree, and freezes the exact uv/interpreter/package/source/wheel/installed-distribution/RECORD/`sys.path`/module/plugin identity before observation. The materializer, provisioning freezer, observer, and later parser all require explicit canonical absolute paths, private ownership/modes, no symlinked bootstrap boundary, new write-once destinations, and the exact isolated interpreter. Git HEAD, HEAD tree, index tree, and unfiltered all-untracked clean status remain exactly equal before and after every bootstrap step with no in-worktree evidence allowlist.

The exact-digest local panel then reviewed plan SHA-256 `543e202b13359244d3da8a5a0f37032ed18451da8aae9b31f33439ef8ccfce94`. GPT-5.6 Sol identified one blocker: the plan required the committed `HEAD:phase-loop-runtime` archive to contain `uv.lock`, but that path was absent from Git and existed only as a locally excluded worktree file, so a fresh source could not execute the mandatory frozen sync. This repair force-adds the mechanically checked lock bytes at SHA-256 `b89987030b895131c3de05a316783ac0bcb6423d5531d6e9a04ee4a8f1e9fcce` as part of this planning candidate, requires that exact regular file to land on canonical `main` before any REVIEWTRUTH lane dispatch, and binds it independently inside the embedded observer's exact Git-tree source manifest and `uv_lock_sha256`. The lock is a planning/bootstrap prerequisite, not an SL-1 tests-only artifact, an SL-2-through-SL-5 implementation artifact, or an SL-6 closeout artifact; no later landing may introduce or replace it and thereby retroactively change the pre-SL-1 baseline. This changed plan digest invalidates the reviewed digest and again requires the mandatory exact-digest Fable 5 + GPT-5.6 Sol + Gemini 3.6 Flash + Grok 4.5 panel before SL-0.

The latest panel in `.phase-loop/reviews/v10-reviewtruth-plan-panel.json` reviewed exact plan SHA-256 `4b78d15f9d4f2322da89fac0654cc6ae841bd970281dee87ccdab9662346c8fa`; Grok 4.5 and Gemini 3.6 Flash returned AGREE and GPT-5.6 Sol returned DISAGREE. Sol proved that the plan still treated exact pytest/pluggy distribution versions, absolute module paths, module digests, and version-bearing plugin fingerprints as cross-environment equality keys even though bootstrap, GitHub CI, and Gate A install bare `pytest` and the committed lock does not resolve pytest or pluggy. Tool release drift could therefore create a false divergence with no repository change and no permitted post-SL-1 repair. This repair leaves the exact embedded observer bytes unchanged and keeps those tool fields mandatory, complete, self-consistent provenance and diagnostics, but removes their raw values from semantic equality. Cross-environment authority remains on repo-owned source/test bytes and digests, declared selectors, exact application-plugin entry points and repo-owned origins, repository/root maps, canonical full and selected nodeid sets, marker/hook deselection and skip categories, collection/exit/JUnit/result behavior, and the existing repo-governed hook and activation contracts. A missing, unclassifiable, behavior-changing, or unsupported toolchain still fails; a pytest/pluggy version, absolute path, distribution version, or module-byte change alone does not. The changed plan digest invalidates `4b78d15f…` and again requires the mandatory exact-digest four-seat panel before SL-0.

The exact panel result now recorded in `.phase-loop/reviews/v10-reviewtruth-plan-panel.json` reviewed plan SHA-256 `941b7620fb3ed3ea3c066086ec172231dfb4975352c7e342dde0ba4bec0f0a41`; Grok 4.5 and Gemini 3.6 Flash returned AGREE and GPT-5.6 Sol returned DISAGREE. Sol proved that Gate A cannot equal the source-capable full/selected and skip baseline: the unmodified clean-room script copies only `phase-loop-runtime/tests/`, intentionally omits sibling `phase-loop-skills/`, and therefore collection-skips exactly `test_execute_phase_handoff_mode.py`, `test_validate_plan_doc_docs_lane.py`, `test_validate_plan_doc_goal_coverage.py`, and `test_validate_plan_doc_producer_dependency.py`, whose source-capable collection contributes 48 selected tests. This repair retains exact source-head equality for the external bootstrap, source checkout, GitHub CI, candidate, and broad-final environments where the sibling bundle is present, but freezes a separate Gate-A-specific profile mechanically derived from that clean-room boundary: exact copied repo-owned bytes; exact full/selected sets after subtracting those 48 named nodeids; the exact four normalized collection-skip tuples; every exact clean-room-only runtime skip caused by absent sibling `phase-loop-skills/` or `skills-src/`; and unchanged marker/hook categories over the remaining collection. Gate A must also prove the sibling boundary is absent. Any missing/extra/renamed boundary skip, any other nodeid loss, any source-byte or retained-behavior drift, or unexpected presence of the sibling fails. Pytest/pluggy interpreter/version/path/digest fields remain mandatory provenance-only diagnostics in both profiles. Intermediate SL-1 controls and terminal SL-6 attestation consume the same frozen Gate-A profile, so neither can demand the impossible source-capable set from the clean room.

The newest exact-digest panel in that artifact reviewed plan SHA-256 `9d30d412d2d9d47089b53634e29997591815c3e31f9cbe145f6c35d6b24fc027`; Grok 4.5 and GPT-5.6 Sol returned DISAGREE and Gemini 3.6 Flash returned AGREE. Both blocking reviews proved that the prior Gate-A runtime boundary was still incomplete: it hard-coded only nine skills-bundle skips even though the unmodified script copies only `phase-loop-runtime/tests/` and also omits repo `scripts/`, `skills-src/`, release pins/installers/docs/workflows, the adjacent package `pyproject.toml`, and roadmap/spec inputs. The planning-author pre-edit probe executed the unmodified Gate-A layout and a source-layout control against the same exact test bytes. Canonical `(nodeid, phase, reason)` accounting was: retained source/CI baseline `39` tuples (`call=10`, `collect=23`, `setup=6`), SHA-256 `59dfdd0c70679e8e2356b8dcffbb78faa795c5caa5025ce949e96522923023ea`; Gate-A-only collection boundary `4` tuples (`collect=4`), SHA-256 `09e45269b62ec9c4ac0584600d77e883b9c3fbd67a89415ba6650ee9f6efe3be`; Gate-A-only runtime boundary `59` tuples (`call=26`, `setup=33`), SHA-256 `760925fe088328171cd7dc83172736a10904275d50b4da675e1f4a0a583d4b69`; and their disjoint union `102` tuples (`call=36`, `collect=27`, `setup=39`), SHA-256 `57746ee994520651677a0b0dcdd50334eb52ccdc109ef71d6dd352ce95a8bcce`. The runtime-boundary per-file counts are exact: `test_advisor_board_alias_install.py=5`, `test_contract_floor_guard_378.py=3`, `test_model_id_source_guard.py=11`, `test_outside_agent_release_surface.py=3`, `test_prune_merged_worktrees_script.py=5`, `test_release_pin_autotrack.py=4`, `test_roadmap_representation_consistency.py=8`, `test_skill_bundle_pinned.py=1`, `test_skills_bundle_drift.py=1`, `test_skills_canon_parity.py=7`, `test_skills_src_claude_literal_lint.py=1`, `test_sweep_fleet_worktrees_script.py=9`, and `test_train_roadmap.py=1`. SL-1 must reproduce and literalize the complete sorted tuples, counts, and canonical-JSON digests again on its exact clean pre-edit base before touching any owned path; these planning-author values are an exact second witness, not permission to substitute a hand-maintained list. The empirical run also exposed four interpreter-availability failures on this Python-3.10-only host; they are not skips, not accepted baseline, and do not weaken the final GREEN Gate-A requirement. This repair changes only skip-boundary rigor, preserves literal TDD and roadmap scope, invalidates `9d30d412…`, and requires a fresh exact-digest four-seat panel before SL-0.

The latest immutable local-three panel at
`.phase-loop/reviews/v10-reviewtruth-plan-panel.json` has SHA-256
`03cfa5530ee33c0eb5a2a5982d26ca25c2893b7235a87608c37b71dffa7256e9`.
It reviewed predecessor plan SHA-256
`fb6e8c1ec83c74f02abfa8b0c22c612e86a06bc4d2677483c58a90699a47d2c5`,
roadmap SHA-256 `1e8ea70ceae55d326cd84b092e1b9e879180d7b0e774140c3dd00e6ed63b7071`,
bundle SHA-256 `43cd7ad8a963597b74054dbaa876a774611cd56666304be01bd7e4b2e45a7e3e`,
and instructions SHA-256
`0315045f8d03308717e5ec218b7341cfb996263d4205029e0679b0a05760d177`;
Grok and Gemini returned usable `AGREE`, GPT-5.6 Sol returned usable `DISAGREE`,
and Fable was absent, so it authorizes nothing. Sol proved that the proposed terminal attester
could not independently rehash its claimed inputs: the live Gate A script copied only tests,
deleted that temporary tree on exit, and the chronology parser is not wheel-packaged. This repair
freezes a tests-first persistent-copy falsifier in SL-1, adds the script implementation to SL-5,
and makes the executed tests/conftest plus exact parser survive cleanup as a sealed write-once
copy that a fresh process rehashes only after stdout/stderr close. The predecessor panel remains
immutable historical dissent; this changed plan/roadmap pair requires a fresh full four-seat
panel before SL-0.

The newest immutable local-three review at
`.phase-loop/reviews/v10-reviewtruth-plan-panel.json` has file SHA-256
`e90e5b5e9a0ec08e6526beebd8f4259cf7b542dd059bd6cfe86ec4ab4baa0328`.
It reviewed predecessor plan SHA-256
`ea668b6ebd5f09633d86d716d872c7da6a9cec73adcb903d52dcae82f70102ba`,
roadmap SHA-256 `4d652aaff71b484806ea6d1770c9475e0c1e8de90c39e5447c6fadb8d0fa2c6f`,
bundle SHA-256 `46e6cf1dca8ce0916ba403de707e48b8dd5e1f7a8c7bda8e3a857731846be035`
(`293204` bytes), and instructions SHA-256
`0315045f8d03308717e5ec218b7341cfb996263d4205029e0679b0a05760d177`.
Two legs returned usable `AGREE`; GPT-5.6 Sol returned usable `DISAGREE`, identifying two
blockers: REVIEWTRUTH collided with CONFORM on `tests/conftest.py` and with HARDEN on
`advisor_board/composition.py` plus `panel_invoker.py`, and raw source/CI skip equality could not
hold across Python 3.10–3.12 because one legacy node names host-dependent interpreter paths. This
immutable historical dissent authorizes nothing. The amended DAG puts CONFORM and HARDEN before
REVIEWTRUTH, and PC-REVIEWTRUTH-5A freezes the sole portable disposition without weakening Gate A.

The current immutable local-three artifact at this planning head has SHA-256
`a012d88c93ef788754f83d65b9fac2892bcd187bf65146be3c790c8c3aea163f`. It reviewed
plan SHA-256 `23c9274c927890b636dcbdc5e3d89e0c21819cd33703fc774ad4ff0444525a93`,
roadmap SHA-256 `158c9f28857ef1df02a6b8ca72aef93f3a8a2acc8e591ca6adc70dd53ddb854d`,
bundle SHA-256 `3007e612ab8515255527a4f2ee947e79e2263a88d82191becfb5ac87383d23c7`
(`300663` bytes), and instructions SHA-256
`0315045f8d03308717e5ec218b7341cfb996263d4205029e0679b0a05760d177`.
Two legs returned usable `AGREE`; GPT-5.6 Sol returned usable `DISAGREE`. Sol proved two
load-bearing contradictions: the persistent evidence copy recreated
`phase-loop-runtime/scripts/` even though the clean-room runtime copy is required to lack that
root, and SL-5 required `PHASE_LOOP_GATE_A_INPUT_COPY_ROOT` while the GitHub workflow still
invoked `gate_a_cleanroom.sh` without it. This immutable dissent authorizes nothing. The repair
below separates the clean-room and evidence namespaces and makes `.github/workflows/test.yml` an
explicit implementation-owned contract after tests-only RED.

The exact local panel now recorded at
`.phase-loop/reviews/v10-reviewtruth-plan-panel.json` has file SHA-256
`1c434bf67d6e22c7e1d90ef240525aba1efea22d0bc1174b59782be1a5ae0cb0`. It reviewed
plan SHA-256 `7a56bccd4b19188e4d3faadfc074c6781e696207d0b74ce0854faffb20380c77`,
roadmap SHA-256 `a289891a6f6bf27e07e3c1a5260d25f813f90931404c47dd2efc487e0aa268ba`,
bundle SHA-256 `4292eccce9037a7407e4b3d7fcbc7fd3e7796375deec2892a3a7d1dc202a8b8a`
(`300690` bytes), and instructions SHA-256
`0315045f8d03308717e5ec218b7341cfb996263d4205029e0679b0a05760d177`. Grok 4.5 and
GPT-5.6 Sol returned usable `DISAGREE`; Gemini 3.6 Flash returned usable `AGREE`; Fable
produced no leg, so the artifact authorizes nothing. Grok proved an ordering/ownership deadlock:
SL-5 required the GitHub workflow and its frozen falsifier to invoke a terminal attester, required
that CI to be GREEN before SL-6, but assigned the only attester executable to SL-6. Sol proved a
second contradiction: PC-REVIEWTRUTH-4 named repo-local `.phase-loop/evidence/` Gate A suite
artifacts while every normative Gate A command wrote them beneath the private external
`$REVIEWTRUTH_RUNNER_ROOT/evidence/` boundary. This repair transfers single-writer ownership of
`phase-loop-runtime/scripts/verify_reviewtruth_evidence.py` to SL-5, so the workflow, Gate A
producer, and terminal attester land together and can be GREEN at the implementation head; SL-6
only consumes that immutable executable after the implementation landing. The sole canonical Gate
A suite artifact namespace is
`$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite.{stdout,stderr,json}` plus
`$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite-attestation.json`; no Gate A suite
artifact is written or aliased under `.phase-loop/evidence/`. The changed plan digest invalidates
the reviewed digest and requires a fresh exact-digest four-seat panel before SL-0.

REVIEWTRUTH must begin only from an exact fetched canonical base containing the two-parent
CONFORM and HARDEN landings. Before any SL-0 or bootstrap edit, the coordinator must recreate the
external runner root and rerun the complete provision/observe/broad-baseline chain, freeze fresh
source, owned-path, collection, skip, plugin, and root digests, and compare every retained
assumption to that post-upstream base. Any changed owned-path byte or invalidated anchor requires
plan repair and a fresh exact-digest panel; no predecessor exact-head evidence may be reused.
This re-anchoring occurs before the still-unresolved `agent-harness#398` human gate, so that gate
cannot block CONFORM or HARDEN.

Current implementation anchors were rechecked rather than copied from drifted roadmap line references: `_render_leg_prompt` is at `panel_invoker.py:1065`; the TUI-policy exclusion and native-request attach are at `panel_invoker.py:4205-4232`; `_default_train_review` is at `train_runner.py:2006`; the count-only train-resume short circuit and ledger write are at `train_runner.py:2911-2957`; the legacy durable fields are at `train_ledger.py:166-180`; the legacy `leg.text.strip()` governed finding branch is at `governed_review.py:137`; and the separate governed pre-merge threshold is `_MIN_USABLE_REVIEWERS` at `governed_premerge.py:57`, consumed at `governed_premerge.py:405`.

A focused live-test scan for `_MIN_USABLE_REVIEWERS`, `below_reviewer_floor`, literal `usable_reviewers=2`, `floor counts LEGS`, and `2-usable` found the authorizing floor-2 pins in exactly `phase-loop-runtime/tests/test_governed_cross_vendor_floor_358.py` and `phase-loop-runtime/tests/test_train_merge.py`. `phase-loop-runtime/tests/test_governed_planning_gate.py` is the explicit non-floor plan/design scope control and remains governed by the preserved `proceed_degraded` policy rather than becoming a merge-floor positive pin. The golden surface was also rechecked: `test_advisor_board_golden.py` currently names `seat_key` as the sole sanctioned delta, with the same rule mirrored in `advisor_board/CONTRACTS.md` and `docs/advisor-board-capabilities-card.md`. REVIEWTRUTH intentionally adds typed result and prompt-lens output, so SL-1 must amend and freeze the normative expected-delta list in the golden test before implementation; SL-6 may mirror that already-frozen rule into its docs but cannot discover or repair it for the first time. A second compatibility scan confirmed five legacy expectations: `phase-loop-runtime/tests/test_advisor_board_research.py::InvocationAndCompatibilityTests::test_disabled_result_serializer_is_unchanged`, `phase-loop-runtime/tests/test_panel_invoker_spawn.py::ClaudeLegNativeAdapterRequestTest::test_native_agent_leg_request_rejects_fable_and_opus`, `phase-loop-runtime/tests/test_panel_native_fill_183.py::DeferredSeatSurfacesNativeFillRequest::test_board_deferred_seat_carries_request_with_seat_cognition`, `phase-loop-runtime/tests/test_panel_native_fill_183.py::DeferredSeatSurfacesNativeFillRequest::test_under_claude_code_requires_tui_adapter_even_without_local_cli`, and `phase-loop-runtime/tests/test_panel_native_fill_183.py::DefaultClaudeSeatNeverCarriesNativeFill::test_brief_ref_flows_into_the_request`. The final three are native-fill reversals: the first currently expects no request for the deferred Fable seat, the second expects no request even though the Claude Code host reaches `tui_adapter_required` before the false local-CLI support probe can govern native Task capability, and the third expects a supported Fable seat with a resolved `brief_ref` under Claude Code to carry no native request. All five must migrate tests-first under their full existing nodeids, retain their legacy/default assertions before the marker, assert the new contract under forced activation, switch automatically to those same new assertions after the exact production marker lands, and freeze every affected request/serializer field including the new identities and digests before SL-1 merges.

The native-fill seam was also rechecked directly. `SeatOutcomeRecord` already documents `seat_key` as explicitly non-unique and carries a unique FAB `seat_instance_id`, while `NativeAgentLegRequest` currently carries only optional seat/artifact/brief cognition and there is no closed `NativeAgentLegReport` binding surface. `test_panel_native_fill_183.py::DeferredSeatSurfacesNativeFillRequest::test_colliding_seat_keys_do_not_hide_a_failed_twin` already proves colliding `seat_key` values are legal. REVIEWTRUTH therefore cannot reuse `seat_key` as request identity: SL-1 freezes collision, retry/late-report, replay, cross-seat substitution, digest-substitution, and exactly-once-count falsifiers; SL-2 allocates one stable `seat_instance_id` per requested seat and fresh non-reused `request_id` plus `attempt_id` for every emission/retry; and SL-5 persists and reconstructs pending, superseded, consumed, and rejected attempt state without accepting a report twice.

## Interface Freeze Gates

- [ ] PC-REVIEWTRUTH-0 — The `agent-harness#398` capability disposition is stated in `docs/research/reviewtruth-leg-capability-ratification.md`, explicitly maintainer-ratified, merged separately before the tests-only landing, and binding on every later posture-assuming change. General roadmap execution authorization and panel approval are non-substitutes. The chronology verifier reads the record and landing metadata, rejects shallow or replacement-ref history, and proves the record/test/implementation ordering and conformance from a trusted full clone.
- [ ] PC-REVIEWTRUTH-1 — Chronology has two non-substitutable modes. The pre-implementation mode can pass immediately after the separate tests-only landing by proving disposition ancestry, distinct PR/head identity, PANELLED RED evidence, allowed test-only paths, and no production change; only that mode unblocks SL-2 through SL-5. The final mode runs only after the separately merged SL-2-through-SL-5 implementation PR and additionally requires a two-parent implementation landing whose first parent already contains the disposition and tests-only landings, a distinct implementation PR/head, no SL-1-owned path in `implementation^1..implementation^2` or the implementation PR range, and no SL-1 tests-only commit carried on the implementation branch. Same-branch, squash, rebase, direct-push, shallow, grafted, replacement-ref, or tests-in-range history fails final evidence but cannot deadlock pre-implementation dispatch.
- [ ] PC-REVIEWTRUTH-2 — Broad compatibility accounting is independent from phase-node accounting, separates marker deselections from skips, and begins with a contemporaneous observation rather than retroactive inference. Before any SL-1-owned file is edited, the coordinator supplies `REVIEWTRUTH_RUNNER_ROOT` as a new canonical absolute path outside the exact git toplevel and `REVIEWTRUTH_UV` as a canonical absolute executable path. Execute the five operational commands below in order: provision the isolated external environment, materialize the exact embedded observer, freeze provisioning with that environment's exact interpreter, run the one-process observation, then verify the sealed result after the tracked parser exists. The runner root and every non-venv bootstrap boundary must be newly created, owned by the effective UID, private (`0700` directories and `0600`/`0700` files), canonical, non-symlinked, and disjoint from the worktree; the only permitted internal symlink is the venv's interpreter link whose real target must remain beneath the runner root's uv-managed Python directory. No bootstrap path may be covered by a Git status allowlist.

  `phase-loop-runtime/uv.lock` is a plan-authoring/bootstrap prerequisite at exact SHA-256 `b89987030b895131c3de05a316783ac0bcb6423d5531d6e9a04ee4a8f1e9fcce`. It must already be a regular tracked blob on canonical `main` before SL-0 dispatch, remain byte-identical through the SL-1 observation, and appear exactly once in both `git ls-tree -r HEAD -- phase-loop-runtime` and the `git archive HEAD:phase-loop-runtime` source. The plan/lock/manifest prerequisite landing precedes and is separate from the later `agent-harness#398` disposition, tests-only, implementation, and closeout landings. The lock is excluded from every REVIEWTRUTH lane's owned files: a later tests, implementation, or closeout edit cannot supply, regenerate, or amend it and cannot retroactively redefine the untouched baseline.

  Provisioning runs beneath `env -i`, exports HOME, TMPDIR, uv cache, and uv-managed-Python storage only under the runner root, archives the exact committed `phase-loop-runtime` tree — including that exact lock blob — to an external source directory, builds the exact local wheel from that copy, installs the lockfile-resolved runtime and `visual` dependencies with `uv sync --frozen --no-install-project`, then installs that exact wheel with `--no-deps` and the repository's explicit `pytest` test dependency under strict uv checks in the new external venv. This is the repository's established full-suite CI dependency shape; the checkout has no root `pyproject.toml`, while `phase-loop-runtime/pyproject.toml`, `phase-loop-runtime/uv.lock`, and `.github/workflows/test.yml` are the grounded package/lock/test sources. The provisioning freeze must import at least `pytest`, `pydantic`, `consiliency_contract`, `PIL`, and `phase_loop_runtime`, enumerate every installed distribution, verify every hashed installed `RECORD` member, and record the exact uv executable/version/digest, uv-managed interpreter and `pyvenv.cfg`, package inventory, external source manifest, wheel members/digest/RECORD, installed distribution metadata/RECORD, `sys.path`, required module paths/digests, and entry-point inventory. Every recorded digest must match the bytes it describes, every required field must be present, and the same-run provision/observe chain must remain internally consistent. The source manifest independently records every committed runtime path/blob/file digest plus `pyproject_sha256` and `uv_lock_sha256`; absence of the archive lock fails the freeze, repo/archive substitution fails byte equality, and the later parser requires the recorded lock digest to equal the exact plan-bound digest. It also rejects `include-system-site-packages`, enabled user site, a user/system `site-packages` or `dist-packages` path outside the venv, a distribution outside the venv, repo-owned source or local-wheel drift, a tampered/self-inconsistent installed `RECORD`, or any missing collected-suite import before observation. Pytest/pluggy distribution versions, absolute module/distribution paths, and module/file digests describe this observed environment only; they are mandatory provenance and diagnostics, not cross-environment semantic equality keys.

  Materialize the exact embedded bootstrap observer bytes only at `$REVIEWTRUTH_RUNNER_ROOT/materialized/reviewtruth-baseline-observer.py`, require SHA-256 `841cfb8bbac1d9b4ea0bb14a1f3600165550227b680b2e5689c79c13c61b1f6d`, and run both observer modes with `$REVIEWTRUTH_RUNNER_ROOT/venv/bin/python`, never a bare system interpreter. Each mode starts beneath `env -i` and requires the complete initial environment to equal the exact nine-key allowlist `HOME`, `PATH`, `LANG`, `LC_ALL`, `PYTHONNOUSERSITE`, `PYTHONDONTWRITEBYTECODE`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD`, `PYTHONPATH`, and `TMPDIR` with the frozen external values in the command; this rejects ambient `PYTEST_ADDOPTS`, `PYTEST_PLUGINS`, every `PHASE_LOOP_*` selector, `CI`, user/system-site fallback, bytecode/cache writes into the worktree, and every unlisted process key rather than merely failing to record them. Provision-freeze writes one canonical file at `$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-bootstrap-provisioning.json`; observation requires and rechecks that exact file before invoking one GREEN pytest process with exact argv `phase-loop-runtime/tests -q -m "not dotfiles_integration" -p no:cacheprovider --junitxml=<external write-once observation>/broad.xml`. Its try-first hookwrapper records the complete canonical repo-relative item set before built-in marker selection and the selected item set after selection in that same process; its `pytest_deselected`, runtime-report, and collection-report hooks contemporaneously record the exact deselection multiset, each item's marker names, and legitimate item/module skip tuples and reasons. Every provisioning/materialization/freeze/observation snapshot requires empty `git status --porcelain=v1 -z --untracked-files=all` before and after and byte-identical HEAD, HEAD tree, and index tree; no relative or in-worktree bootstrap output is accepted.

  The same process attests the complete post-pytest environment, not a hand-picked subset. Suite initialization may add only `PHASE_LOOP_PROFILE_PLUGINS=phase_loop_runtime.dotfiles_profile_plugin:register_profile_commands` and `PHASE_LOOP_SKILL_SOURCE_PLUGINS=phase_loop_runtime.skill_sources_plugin:register_skill_sources`; `PHASE_LOOP_RUNNER_REPO_ROOT`, `PHASE_LOOP_CLAUDE_ROUTE`, `CI`, `PHASE_LOOP_REVIEWTRUTH_POST_PARSER_COLLECTION`, `PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH`, and `PHASE_LOOP_SKIP_GATE_A_SUITE` must remain absent. Because the isolated environment installs the exact local wheel, both application entry-point groups must contain exactly the wheel's one `dotfiles` entry and no ambient distribution; source-mode opt-ins and installed entry points must deduplicate to exactly one profile registrar and one skill-source provider. Their loaded module/callable source files must live beneath `phase-loop-runtime/src/phase_loop_runtime/`, their repo-relative paths and source digests remain semantic equality keys, their distribution metadata/RECORD must live beneath the external venv, and the provider's complete harness-to-root output is frozen. Any extra registrar/provider, entry point, distribution, source outside the repo/venv boundary, selector value, absolute/extra root, or missing source fails before sealing. The write-once external observation contains `full-nodeids.txt`, `selected-nodeids.txt`, `marker-deselected-nodeids.txt`, `legitimate-skips.json`, raw stdout/stderr, ordinary JUnit, raw plugin events, and a terminal canonical attestation that binds their byte counts/digests plus observation UUID, provisioning-file digest, observer/plan/roadmap digests, exact `sys.orig_argv`, `/proc/self/cmdline`, internal pytest argv and their digests, the exact initial/post-pytest environment maps, every runtime selector and application entry point, the loaded registrar/provider source/digest/root profile, PID/PPID/PGID/SID/UID/GID, boot ID and process-start ticks, CWD, uv/interpreter/package/source/wheel/distribution/RECORD/`sys.path` provenance, pytest/`_pytest`/`pluggy` module paths and file digests, pytest version, and every loaded pytest plugin's name/module/class/distribution/version/path/digest. Those pytest/pluggy and non-repo core-plugin version/path/digest fields are mandatory diagnostic provenance; recording and self-consistency are required, but their raw values do not define semantic parity across bootstrap, CI, Gate A, or another supported environment.

  After, not before, that observation is sealed, SL-1 authors `verify_reviewtruth_chronology.py` and independently parses the raw files from the explicit canonical absolute `--runner-root`, `--provisioning`, `--observation-dir`, and `--observer-source` arguments. It must re-hash the exact embedded observer bytes, provisioning freeze, and observation artifacts; independently verify the private external-root boundary; require the exact tracked/archive `phase-loop-runtime/uv.lock` digest; recompute the uv/interpreter/package/source/wheel/distribution/RECORD/`sys.path`/module/plugin provenance; and recompute the full `REVIEWTRUTH_BROAD_PREIMPLEMENTATION_COLLECTED_NODEIDS`, selected `REVIEWTRUTH_BROAD_PREIMPLEMENTATION_SELECTED_NODEIDS`, exact `REVIEWTRUTH_BROAD_MARKER_DESELECTED_NODEIDS = full - selected`, legitimate `REVIEWTRUTH_BROAD_BASELINE_SKIP_TUPLES`, their counts and sorted-LF/canonical-JSON SHA-256 values, JUnit outcomes, command/runtime/provenance records, the full-minus-selected/deselection/marker relations, both complete environment maps, every forbidden-selector absence, both exact local-wheel entry-point registries, the exact loaded application registrar/provider sources and digests, and the complete skill-source root mapping without trusting attestation-derived counts or summaries. The exact full and selected pre-edit sets remain frozen, not merely their counts: the immutable test/record surface retains their canonical compressed bytes plus counts/digests, while the explicit marker difference tuple and skip tuples remain readable literals. SL-1 also derives and freezes the only allowed source-capable post-SL-1 collection transformation: the pre-edit full/selected sets plus exactly the declared new REVIEWTRUTH nodeids, with migrated nodeids unchanged and exactly five new post-parser wrappers removed by the ordinary hook.

  SL-1 separately freezes the Gate-A-specific transformation imposed by the unmodified clean-room script from paired source-layout and copied-tree observations made before any SL-1 edit. Both observers emit sorted canonical JSON rows shaped exactly as `{"nodeid": <repo-relative nodeid>, "phase": "collect"|"setup"|"call"|"teardown", "reason": <repo-root-normalized longrepr>}`; collection reports and runtime reports are stored in separate tuples before any union is formed. `REVIEWTRUTH_GATE_A_OMITTED_SELECTED_NODEIDS` is the exact 48-nodeid source-capable set contributed by `phase-loop-runtime/tests/test_execute_phase_handoff_mode.py`, `phase-loop-runtime/tests/test_validate_plan_doc_docs_lane.py`, `phase-loop-runtime/tests/test_validate_plan_doc_goal_coverage.py`, and `phase-loop-runtime/tests/test_validate_plan_doc_producer_dependency.py`; `REVIEWTRUTH_GATE_A_COLLECTED_NODEIDS` and `REVIEWTRUTH_GATE_A_SELECTED_NODEIDS` equal the corresponding source/CI post-SL-1 sets minus exactly those nodeids. `REVIEWTRUTH_GATE_A_RESTRICTED_SOURCE_COLLECTION_SKIP_TUPLES` and `REVIEWTRUTH_GATE_A_RESTRICTED_SOURCE_RUNTIME_SKIP_TUPLES` are the exact source/CI baseline tuples that remain byte-identical in the Gate-A retained collection. `REVIEWTRUTH_GATE_A_BOUNDARY_COLLECTION_SKIP_TUPLES` is the exact four-module Gate-A-minus-source collection delta, count `4`, canonical-JSON SHA-256 `09e45269b62ec9c4ac0584600d77e883b9c3fbd67a89415ba6650ee9f6efe3be`. `REVIEWTRUTH_GATE_A_BOUNDARY_RUNTIME_SKIP_TUPLES` is the complete Gate-A-minus-source runtime delta, not a hand-picked skills subset: count `59`, canonical-JSON SHA-256 `760925fe088328171cd7dc83172736a10904275d50b4da675e1f4a0a583d4b69`, with exact per-file counts `5,3,11,3,5,4,8,1,1,7,1,9,1` for, respectively, `test_advisor_board_alias_install.py`, `test_contract_floor_guard_378.py`, `test_model_id_source_guard.py`, `test_outside_agent_release_surface.py`, `test_prune_merged_worktrees_script.py`, `test_release_pin_autotrack.py`, `test_roadmap_representation_consistency.py`, `test_skill_bundle_pinned.py`, `test_skills_bundle_drift.py`, `test_skills_canon_parity.py`, `test_skills_src_claude_literal_lint.py`, `test_sweep_fleet_worktrees_script.py`, and `test_train_roadmap.py`; all 59 complete nodeid/phase/reason tuples remain readable literals in the immutable SL-1 surface. `REVIEWTRUTH_GATE_A_EXPECTED_COLLECTION_SKIP_TUPLES` is the disjoint union of the restricted source collection baseline and the four collection-boundary tuples; `REVIEWTRUTH_GATE_A_EXPECTED_RUNTIME_SKIP_TUPLES` is the disjoint union of the restricted source runtime baseline and all 59 runtime-boundary tuples; `REVIEWTRUTH_GATE_A_EXPECTED_SKIP_TUPLES` is their disjoint union. On the empirically inspected pre-edit tree, the restricted source baseline is count `39` and SHA-256 `59dfdd0c70679e8e2356b8dcffbb78faa795c5caa5025ce949e96522923023ea`, while the complete Gate-A expected union is count `102` and SHA-256 `57746ee994520651677a0b0dcdd50334eb52ccdc109ef71d6dd352ce95a8bcce`; SL-1 must reproduce all tuples/counts/digests on its exact clean pre-edit base and fail instead of editing if they differ. The immutable surface proves the temporary copied runtime tree contains only the standalone `phase-loop-runtime/tests/**` namespace and lacks every root whose absence explains those deltas — sibling `phase-loop-skills/`, repo `skills-src/`, `phase-loop-runtime/scripts/`, the adjacent package `pyproject.toml`, root release pins/installers/docs/workflows, and roadmap/spec inputs. A separate external persistent evidence copy uses only `input-copy/tests/**` (including `input-copy/tests/conftest.py`), `input-copy/chronology-parser/verify_reviewtruth_chronology.py`, and its manifest; it is non-importable and never creates `input-copy/phase-loop-runtime/scripts/` or mutates the temporary runtime tree. Every copied test/conftest/parser byte equals its exact committed repo-owned byte and the 48 omitted nodeids are unmarked and are the complete full/selected delta. Unexpected source-only tuple loss outside the four omitted modules, unexpected sibling/root presence or absence, any `phase-loop-runtime/scripts` root in either copied namespace, a parser anywhere outside `input-copy/chronology-parser/`, a fifth collection-boundary module, 47 or 49 omitted nodeids, a boundary skip becoming pass/fail, a category or phase change, or any unrelated skip is a hard failure.

  The cross-environment semantic record is deliberately narrower than the diagnostic provenance record and explicitly profile-aware. Source-capable bootstrap, source checkout, GitHub CI, candidate, and broad-final environments require exact equality to the frozen source/CI full/selected and skip sets. Gate A requires exact equality to the separately frozen Gate-A full/selected sets, expected collection/runtime skip unions, and their complete baseline-plus-boundary total; it must not be compared to the impossible source-capable nodeid/skip sets. Both profiles require exact repo-owned test/conftest/parser bytes and digests; declared environment selector names and values; exact application-plugin entry-point groups/names/values/distribution origin plus repo-relative registrar/provider source paths and digests; their declared repository/source/root maps; absence of ambient, autoloaded, or unapproved third-party collection plugins; their own canonical full and selected nodeid sets; marker and hook deselection tuples/categories/reasons; profile-specific legitimate skip tuples/reasons; hook activation and notification behavior; pytest command/profile; collection/import success; exit status; JUnit nodeid/outcome/result accounting; and every other repo-governed behavior already frozen here. The collection-plugin behavioral profile normalizes approved pytest-core/pluggy implementation details to their role and trusted origin and excludes their distribution versions, absolute module/distribution paths, module/file digests, and version-bearing metadata. Those excluded values must still be present, parseable, bound to the artifact that reported them, and emitted in mismatch diagnostics, but changing only one or more of them across environments is not drift and cannot fail the phase.

  Any unexplained environment key, selector/application-plugin/root value or source, application entry point, unapproved distribution origin, user/system-site escape, nodeid, parametrization, marker, skip, deselection category, repo-owned source digest, hook contract, or collection/exit/JUnit/result behavior change is semantic drift. A pytest/pluggy or approved core-plugin release is unsupported and fails when it cannot import or collect the suite, cannot expose enough provenance to classify plugin origin, loads an unapproved plugin origin, changes canonical collection/selection, skip/deselection accounting, exit status, JUnit/result behavior, or violates any repo-governed hook/selector contract; raw byte or version difference alone is insufficient. Mutation tests independently inject each referenced initialization selector, an unknown environment key, an application entry point/distribution, a user/system-site path, an extra/changed plugin origin or spec, an outside-repo application-plugin source, a changed root mapping, a symlinked/reused/wrong-mode runner path, and changed lock/provisioning/local-wheel/RECORD bytes and require the observer or later parser to reject it. Separate positive controls vary only recorded pytest/pluggy distribution versions, absolute module paths, module digests, and approved core-plugin version/path/digest metadata while holding the semantic record fixed and require parity to pass; paired negative controls use a changed/unsupported toolchain to alter collection, plugin origin, nodeids, skip/deselect categories, exit status, or JUnit/result behavior and require parity to fail. Absolute installation roots and Python 3.10/3.11/3.12 executable paths are likewise retained as exact observation provenance but are not portable equality keys. The bootstrap observer itself is subtracted as the one exact externally supplied observation plugin; any other autoloaded or unapproved collection-affecting plugin origin is forbidden.

  After SL-1 is authored, source/CI broad default-premarker must report the disjoint union of exactly the unchanged marker baseline plus exactly the five hook-owned `REVIEWTRUTH_POST_PARSER_NODEIDS`, while its skip set is exactly the source/CI broad skip baseline UNION the non-post-parser `REVIEWTRUTH_DEFAULT_PREMARKER_SKIP_NODEIDS`; source/CI candidate and broad-final producer must report that same marker-baseline-plus-five deselection union and exactly the unchanged source/CI broad skip baseline. Gate A must instead report its exact frozen full/selected sets and the same unchanged marker baseline plus five hook-owned wrapper deselections over the retained collection, while skip accounting is category-exact: collection skips equal `REVIEWTRUTH_GATE_A_EXPECTED_COLLECTION_SKIP_TUPLES = REVIEWTRUTH_GATE_A_RESTRICTED_SOURCE_COLLECTION_SKIP_TUPLES ∪ REVIEWTRUTH_GATE_A_BOUNDARY_COLLECTION_SKIP_TUPLES`; runtime skips equal `REVIEWTRUTH_GATE_A_EXPECTED_RUNTIME_SKIP_TUPLES = REVIEWTRUTH_GATE_A_RESTRICTED_SOURCE_RUNTIME_SKIP_TUPLES ∪ REVIEWTRUTH_GATE_A_BOUNDARY_RUNTIME_SKIP_TUPLES`; and their disjoint union equals `REVIEWTRUTH_GATE_A_EXPECTED_SKIP_TUPLES`. The four collection-boundary tuples account for all 48 omitted source-selected nodeids, while the 59 runtime-boundary tuples account for every retained nodeid whose source control ran but whose Gate-A copy skips because a proved repo/root input is absent. The pre-edit counts/digests (`39` retained source tuples at `59dfdd0c…`, `4` collection-boundary tuples at `09e45269…`, `59` runtime-boundary tuples at `760925fe…`, and `102` expected Gate-A tuples at `57746ee9…`) are independently recomputed and then literalized in full; Gate A is never compared to the unfiltered source/CI skip set and is never allowed to omit its retained source baseline. The conftest observer rejects nonempty pytest `--deselect`, canonicalizes source-root, CI-working-directory, and Gate-A copied-tree nodeids to the frozen repo-relative form, selects the expected profile only from the proved sibling-boundary/root shape rather than an ambient flag, records built-in marker-filter and hook-owned wrapper categories separately from collection/runtime skips, requires the hook itself to find/remove/notify exactly all five wrappers, and fails the session on any missing, extra, duplicate, arbitrary, category-drifted, plugin-drifted, boundary-drifted, or collection-drifted result. The plain frontmatter `automation.suite_command`, the explicitly amended GitHub CI workflow across Python 3.10/3.11/3.12, and fresh-clone source suites use the source/CI profile; clean-room Gate A uses only the Gate-A-specific profile. All remain GREEN after the marker without run-local evidence and attest exact repo-owned bytes, their profile's immutable full/selected digests, marker baseline plus five wrappers, allowed plugin/root profile, and applicable frozen skip accounting. A new, missing, renamed, newly passing, or drifted collection member, marker deselection, boundary skip, retained-baseline skip, plugin, root, or hook; a phase skip surviving candidate/final; any `xfail`; a missing/extra/wrong hook deselection; any command-line `--deselect` or other arbitrary deselection; or any failure/error blocks. Every pushed implementation candidate runs the unmodified source/CI broad command from a fresh exact-head process, and its generated candidate XML is parsed before the golden, panel, or merge. Final broad producer uses the same source/CI ordinary arm and is parsed before exact final collection can be issued. This plan never claims five total broad deselections, never claims whole-suite zero skips, and never asks a later parser to manufacture past provenance. The required workflow edit is owned by SL-5 and occurs only after the SL-1 tests-only RED landing.
- [ ] PC-REVIEWTRUTH-3 — SL-1 freezes a separate phase-selected contract. `PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1` forces the new production contract on the pre-implementation base without importing a missing symbol; otherwise non-post-parser tests use the exact production capability marker `REVIEWTRUTH_CAPABILITY_MARKER = "reviewtruth@1"` from `panel_invoker.py`. The immutable verifier freezes `REVIEWTRUTH_EXPECTED_NODEIDS`, the five-member `REVIEWTRUTH_POST_PARSER_NODEIDS`, and `REVIEWTRUTH_PHASE_NODEIDS = REVIEWTRUTH_EXPECTED_NODEIDS - REVIEWTRUTH_POST_PARSER_NODEIDS`, each with an exact count and sorted-LF SHA-256; the expected set includes every parametrized expansion, floor/train/golden migration, all five full compatibility nodeids, positive controls, and the five strict post-parser wrappers. `junit-run --mode default-premarker`, `activated-red`, and `candidate` invoke pytest with exactly `REVIEWTRUTH_PHASE_NODEIDS` and do not activate post-parser collection. Default-premarker phase JUnit contains that exact phase set: only the non-post-parser `REVIEWTRUTH_DEFAULT_PREMARKER_SKIP_NODEIDS` skip with the one frozen reason, while every migrated existing nodeid runs its legacy assertion branch. Activated-RED phase JUnit contains that same exact phase set, executes each `REVIEWTRUTH_ACTIVATED_RED_NODEIDS` member exactly once and fails only at its mapped raw `REVIEWTRUTH_RED_ANCHORS_BY_NODEID`, passes every positive control, and contains no post-parser wrapper or unrelated skip. For `activated-red` only, `junit-run` records pytest's required nonzero exit and returns control only after the literal XML path exists; it does not bless any failure, and the immediately following `junit --mode activated-red` parser is the sole GREEN/RED authority. Candidate phase JUnit contains exactly `REVIEWTRUTH_PHASE_NODEIDS` with zero phase skips, `xfail`, failures, errors, duplicates, or unexpected/missing nodeids. Only after the broad-final producer parser has emitted and verified its attestation may `junit-run --mode final` reject any inherited activation, set the exact test-owned collection activation, and select all `REVIEWTRUTH_EXPECTED_NODEIDS`; final phase JUnit must contain every expected nodeid exactly once, including all five strict wrappers, with zero phase skips, `xfail`, failures, errors, or deselections. Once SL-2 installs the marker, all migrated and production-dependent assertions switch automatically to the same new branch without test edits, but that marker never activates the post-parser wrappers. No implementation lane may edit tests, conftest, guards, selectors, nodeids, counts, set digests, anchors, parser modes, activation names/values, or skip/deselection reasons; the sole allowed collection-time environment branch is the exact SL-1-owned final-collection predicate, and no import or marker-import failure is permitted.
- [ ] PC-REVIEWTRUTH-4 — Candidate and final proof are process-bound and generation precedes parsing. Candidate phase and broad XML are both generated at literal runner-owned paths in a newly spawned repo-local process after proving `HEAD` equals the exact pushed implementation head and all imported `phase_loop_runtime` and tests/conftest paths and digests resolve beneath that worktree; only then may the frozen parser run in `candidate` mode against those exact two paths, and only its GREEN attestation may unblock golden, panel, or merge.

  Final evidence uses a different newly spawned repo-local process after proving `HEAD` equals the exact fetched canonical-main head containing the two-parent implementation landing; only SL-6-owned evidence/doc dirt may then exist. That child first generates broad-final producer XML through ordinary collection, whose observer attests exactly the frozen marker-filter baseline plus the hook's five frozen wrapper deselections in separate categories, then parses it in `broad-final-producer` mode. Only after that attestation is GREEN does the immutable `junit-run --mode final` reject a pre-set `PHASE_LOOP_REVIEWTRUTH_POST_PARSER_COLLECTION`, set it to the exact value `junit-run:final:v1` only in its pytest child, and generate phase-final XML whose five strict wrappers consume only already-existing non-self-referential inputs — the frozen pre-final SL-6 evidence document at `docs/research/reviewtruth-phase-verification.md` and the single canonical durable redacted transcript and smoke record at `docs/research/reviewtruth-real-panel-smoke.md`, each at its exact frozen digest, ledger and landing metadata, the phase default/RED/candidate and broad marker/skip baseline/default/candidate XML and parser attestations, and that broad-final XML and attestation — and never the phase-final XML or its digest, the final-mode parser attestation, the finalized record, the `final-record` attestation, or any closeout verdict; it then parses both exact XML paths in `final` mode.

  Only after that final parse does the already-landed, SL-5-owned `verify_reviewtruth_evidence.py finalize-record` mode write the write-once post-parser durable record at `docs/research/reviewtruth-final-evidence-record.md`, recording the exact broad-final and phase-final XML digests, both parser-attestation digests, and the exact frozen `docs/research/reviewtruth-phase-verification.md` digest and the one frozen `docs/research/reviewtruth-real-panel-smoke.md` digest the live board and wrappers consumed; no pre-final doc is edited after its staging/review point. The separate minimal `final-record` mode then recomputes every recorded digest from the artifact bytes and emits its attestation to `.phase-loop/evidence/reviewtruth-final-record-attestation.json` and the canonical ledger; its own result is never required inside the record it verifies, and no test wrapper may invoke `finalize-record` or `final-record` or read their outputs.

  The same immutable SL-5 executable owns the later Gate A `gate-a` reducer and its fresh internal `gate-a-attest` process. They stay outside every wrapper and finalized-record input and write only the canonical external paths `$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite.stdout`, `$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite.stderr`, `$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite.json`, and `$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite-attestation.json`. A Gate A suite output or alias beneath `.phase-loop/evidence/` is forbidden. The canonical ledger closeout binds the external absolute paths plus their recomputed digests; it does not copy them into the repo-local namespace.

  The four-seat closeout review and ledger closeout bind the finalized record digest, the `final-record` attestation, and the Gate A suite attestation before closeout, and every closeout verdict is written only to the canonical ledger, never into the record or any wrapper-consumed artifact. Each child emits its own PID/start-time, HEAD/ref, module/conftest paths, source digests, exact command, collection activation/deselection facts, XML path/digest, and parser-attestation path/digest. No invoking shell assigns `REVIEWTRUTH_JUNIT_XML` and expands that newly assigned value itself: task commands use literal paths, while Verification uses `env REVIEWTRUTH_JUNIT_XML=<literal> sh -c '... "$REVIEWTRUTH_JUNIT_XML"'` so expansion occurs only in the child shell after `env` has populated its environment. A TUI, daemon, worker, parent interpreter, or other process that loaded pre-edit `panel_invoker`, `runner`, `train_runner`, `train_ledger`, or related runtime modules may launch the child but may not attest the modified code or panel result itself.
- [ ] PC-REVIEWTRUTH-5 — `phase-loop-runtime/tests/conftest.py` owns the post-bootstrap executable dual-mode collection and deselection-provenance contract. It consumes only committed literals/digests independently derived from the write-once pre-edit source observation plus the paired unmodified Gate-A-layout observation; it never claims to have observed the past. It freezes the exact pre-edit source/CI full/selected collection digests and allowed post-SL-1 transformation; the separately derived Gate-A full/selected sets and exact 48-nodeid delta; the restricted source collection/runtime skip baselines; the exact four-tuple collection boundary and complete 59-tuple runtime boundary; the three expected Gate-A union sets; every tuple's full canonical nodeid/phase/reason plus per-set count/digest; the exact five full repo-relative nodeids in `REVIEWTRUTH_POST_PARSER_NODEIDS`; the exact pre-edit marker-filter tuple `REVIEWTRUTH_BROAD_MARKER_DESELECTED_NODEIDS`; the allowed source/CI versus Gate-A collection-plugin/root behavioral origin profiles; the exact environment name `PHASE_LOOP_REVIEWTRUTH_POST_PARSER_COLLECTION`; the sole accepted value `junit-run:final:v1`; and the predicate `os.environ.get("PHASE_LOOP_REVIEWTRUTH_POST_PARSER_COLLECTION") == "junit-run:final:v1"`. Its try-first/try-last hooks canonicalize the full pre-selection and selected nodeids from source-root, `phase-loop-runtime/` working-directory, and Gate-A copied-tree collection; select the expected profile only from the verified source-root/sibling boundary; and record built-in `-m "not dotfiles_integration"` deselections, wrapper-hook notification, collection skips, and runtime skips as four non-substitutable categories. Its `pytest_deselected` observer rejects a nonempty `--deselect` option or any arbitrary deselection source. In the ordinary broad arm, the wrapper hook runs after marker selection, requires all five exact wrappers still collected, removes exactly those items, calls `pytest_deselected` for exactly that list, and at session end requires the observed full/selected sets, normalized collection-plugin/root profile, deselection multiset, collection skips, and runtime skips to equal the selected profile with exact per-category counts/digests. The source/CI profile requires the frozen post-SL-1 source collection and source skip baseline. The Gate-A profile separately requires `observed_collection_skips == REVIEWTRUTH_GATE_A_RESTRICTED_SOURCE_COLLECTION_SKIP_TUPLES ∪ REVIEWTRUTH_GATE_A_BOUNDARY_COLLECTION_SKIP_TUPLES`, `observed_runtime_skips == REVIEWTRUTH_GATE_A_RESTRICTED_SOURCE_RUNTIME_SKIP_TUPLES ∪ REVIEWTRUTH_GATE_A_BOUNDARY_RUNTIME_SKIP_TUPLES`, and their union equal `REVIEWTRUTH_GATE_A_EXPECTED_SKIP_TUPLES`; it therefore consumes both the retained source/CI baseline and the complete clean-room-only boundary, never just the boundary delta. Neither profile may be substituted for the other, and collection/runtime tuples cannot cross categories. The normalized profile preserves exact application-plugin entry points and repo-owned origins and rejects ambient, autoloaded, unapproved, or origin-changed collection plugins; it does not compare pytest/pluggy or approved core-plugin distribution versions, absolute module paths, or module digests. It never converts wrappers or boundary collection skips to another category and never keys on `REVIEWTRUTH_CAPABILITY_MARKER`, `PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH`, generic truthiness, CI, evidence-file presence, a run-local baseline file, or a caller-selected profile flag. When the final predicate is true, it removes none of the five; each wrapper independently requires the final runner/broad-final attestation before executing its strict assertion, so setting the environment value by hand cannot produce a vacuous pass. SL-1 freezes the hook file digest, observer-payload digest, behavioral collection/plugin/root profiles, all tuples/counts/digests, predicate, category reasons/accounting, final-runner activation, and mutation tests that kill bootstrap-byte/attestation/raw-artifact drift; source or Gate-A full/selected-set drift; removal/addition/reason/phase/category mutation of each one of the four collection-boundary or 59 runtime-boundary tuples; loss/addition of any retained source-baseline tuple; a wrong `39 + 4 + 59 = 102` union; unexpected sibling/root presence or unrelated absence; marker-baseline drift; a missing/renamed/extra wrapper; a truthy/wildcard env predicate; marker-driven collection; failure to notify `pytest_deselected`; external `--deselect`; arbitrary third-party/collection-capable plugin loading or origin substitution; category swapping; and final activation before broad-final attestation. It also freezes the paired controls from PC-REVIEWTRUTH-2: provenance-only pytest/pluggy version/path/digest substitutions with identical semantic behavior pass, while a toolchain change that alters collection/plugin origin/nodeids/skip/deselect/exit/JUnit/result behavior fails. Ordinary suite, GitHub CI, default/broad/candidate/broad-final, and fresh source-clone subprocess controls prove the immutable source/CI post-SL-1 profile; Gate A copied-tree controls prove only the immutable Gate-A profile and the complete baseline-plus-boundary union; both prove exact repo-owned bytes, marker baseline plus exactly five hook-owned deselections, their allowed behavioral plugin/root profile, and GREEN. A final-phase subprocess proves all five strict assertions execute exactly once with zero phase deselections. SL-2 through SL-6 may neither edit nor replace this hook.
- [ ] PC-REVIEWTRUTH-5A — Portable skip classification has exactly one narrowly named environment-dependent disposition. `REVIEWTRUTH_PORTABLE_ENVIRONMENT_DISPOSITION_NODEIDS` is the literal singleton `phase-loop-runtime/tests/test_cr_fixes_pr220.py::test_bare_python_below_floor_shims_even_when_python3_satisfies`, count `1`, sorted-LF SHA-256 `866c44921f3cba820cd182671f5df21ed4f51191105effa047958924de916d8a`. Source checkout and GitHub CI must collect and execute that node exactly once; it is never excluded, deselected, xfailed, moved into a broad exemption, or admitted to Gate A's boundary sets. Its normalized semantic outcome is exactly one of: `portable_pass` when both literal interpreter paths exist and the test passes, or `environment_interpreter_pair_unavailable` only when the node skips for the exact reason `need both python3.10 and python3.12 on host` and at least one of `/usr/bin/python3.10` or `/home/viperjuice/.local/bin/python3.12` is absent. The source/CI raw skip-set comparison removes only that one validated disposition before comparing the remaining canonical baseline; a different reason, both paths present with a skip, either path absent with failure/error, missing/duplicate node, or any second normalized node is drift. Gate A retains its independent exact 39+4+59 tuple contract unchanged and cannot use this normalization to erase a Gate-A skip. The literal RED falsifier `phase-loop-runtime/tests/test_reviewtruth_phase.py::test_reviewtruth_portable_interpreter_pair_disposition_normalizes_host_dependent_skip`, singleton sorted-LF SHA-256 `c36541be134c6256e39693869d2038efb47eb8efe2ab099dd701f24c7dfe70cd`, exercises pass, legal unavailable, wrong-reason, both-present-skip, failure, error, duplicate, and broad-exclusion arms and binds the normalized disposition into bootstrap, candidate, CI-matrix, final, and closeout evidence.
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

- **Scope**: On the exact clean pre-edit base that already contains the separately committed planning lock prerequisite, execute the exact-digest external bootstrap observer in one controlled pytest process; then land the complete REVIEWTRUTH falsifier and compatibility migration suite, deterministic marker activation, CI-safe dual-mode post-parser collection, non-colliding native request/attempt identity tests, structured JUnit contract, and panel-reviewed RED record before any production file changes.
- **Owned files**: `phase-loop-runtime/tests/conftest.py`, `phase-loop-runtime/tests/test_reviewtruth_phase.py`, `phase-loop-runtime/tests/test_train_merge.py`, `phase-loop-runtime/tests/test_governed_cross_vendor_floor_358.py`, `phase-loop-runtime/tests/test_advisor_board_golden.py`, `phase-loop-runtime/tests/test_advisor_board_research.py`, `phase-loop-runtime/tests/test_panel_invoker_spawn.py`, `phase-loop-runtime/tests/test_panel_native_fill_183.py`, `phase-loop-runtime/scripts/verify_reviewtruth_chronology.py`, `docs/research/reviewtruth-red-baseline.md`
- **Interfaces provided**: `REVIEWTRUTH-bootstrap-observation`, `REVIEWTRUTH-tests-first-baseline`, `REVIEWTRUTH-preimplementation-chronology`, `REVIEWTRUTH-evidence-wrappers`, `REVIEWTRUTH-post-parser-collection-contract`, `REVIEWTRUTH-native-fill-identity-contract`, `REVIEWTRUTH-golden-delta-baseline`, `REVIEWTRUTH-tdd-activation`, `REVIEWTRUTH-junit-contract`, `REVIEWTRUTH-broad-compatibility-gate`
- **Interfaces consumed**: `REVIEWTRUTH-capability-ratification`
- **Parallel-safe**: no; this lane must start from the separately merged disposition record and land as a tests/evidence-only, production-change-free change before every implementation lane rebases from that target tip.
- **Tasks**:
  - test: SL1-T1 — Before any SL-1 mutation, require the planning candidate's exact lock blob to be committed and reachable on canonical `main`, provision a new private absolute runner root outside Git from the exact lock-bearing archive, build/install/freeze the exact isolated local-wheel-plus-test environment, materialize and hash-check the exact embedded observer there, then execute its one-process GREEN broad observation to freeze the source-capable full collected set, selected set, exact marker difference, legitimate skips, JUnit/raw output, argv, empty all-untracked Git status, HEAD/tree/index/process, lock/uv/interpreter/package/source/wheel/distribution/RECORD/`sys.path`/module/plugin provenance, and artifact digests; only afterward add every named REVIEWTRUTH falsifier plus mutation-specific injection-anchor and positive-control coverage, including paired controls proving pytest/pluggy version/path/digest-only changes preserve parity while behavior-changing or unsupported toolchains fail; migrate every live floor-2, train-resume, serializer, native-request, and all three native-fill expectations; independently reproduce the exact Gate-A profile from the unmodified tests-only copy boundary before editing, split collection reports from runtime reports, and freeze the 39-tuple restricted source baseline, four named collection-boundary tuples with the exact 48 omitted selected nodeids, complete 59-tuple runtime boundary, 102-tuple expected union, all canonical nodeid/phase/reason rows and digests, sibling/root-absence proof, and retained repo-byte/behavior equality. Freeze `phase-loop-runtime/tests/test_reviewtruth_phase.py::test_gate_a_persists_independently_attestable_tests_conftest_and_parser_copy`, which requires the temporary pytest runtime tree to lack `phase-loop-runtime/scripts/`, the external copy to use only `tests/**` plus `chronology-parser/verify_reviewtruth_chronology.py`, and any implementation that recreates either forbidden scripts root to fail at `REVIEWTRUTH_RED::gate_a_persistent_attestable_input_copy`. Also freeze `phase-loop-runtime/tests/test_reviewtruth_phase.py::test_gate_a_workflow_exports_private_copy_attests_before_external_cleanup`, which rejects the old workflow invocation, either inherited selector, attestation after cleanup, reuse/symlinking of the copy root, or external cleanup before terminal attestation. Freeze collision/retry/late/replay/cross-seat/exactly-once report tests; and freeze the sanctioned golden delta, marker guard, dual-mode conftest hook, independent phase/broad nodeid sets/counts/digests, raw RED anchors, the exact marker deselection baseline plus five separately owned post-parser deselections, executable JUnit runner/parser modes, both chronology modes, and final evidence wrappers.
  - impl: SL1-T2 — Independently test the exact bootstrap bytes, provisioning contract, and parser against synthetic repos and tampered external roots/observations; recompute and freeze the pre-edit source/CI full/selected collections, marker-deselection and broad-skip baselines, isolated environment provenance, allowed source/CI post-SL-1 transformation, and the separate Gate-A full/selected/collection-skip/runtime-skip/root transformation as non-substitutable behavioral profiles; retain complete pytest/pluggy provenance for diagnostics while excluding its raw distribution versions, absolute module paths, and module digests from cross-environment equality; mutation-test every boundary count/digest/category and unexpected sibling-present/extra-absence arm; then generate and parse default phase/broad JUnit and activated phase JUnit in the stated order, prove ordinary-suite/final-collection dual mode and deselection provenance plus all native-identity falsifiers, panel the exact tests-only digest, and merge the dedicated tests-only landing with all required provisioning/observer/plan/base/tree, conftest/set, marker/raw/XML, parser-attestation, panel, and landing digests recorded.
  - verify: SL1-T3 — Prove record ancestry, PANELLED and RED status, restricted landing paths, exact observer bytes and contemporaneous observation, independently reproduced source/CI full/selected/difference/skip/provenance accounting, and the independently reproduced Gate-A four-module/48-nodeid collection boundary plus complete 39-retained/4-collection/59-runtime/102-total skip freeze and repo-byte equality; then prove exact phase default/activated accounting, exact broad marker/skip baseline and default hook/plugin/root accounting, the provenance-only drift positive controls and behavior-changing toolchain negative controls, native identity/digest falsifiers, fired injection anchors, and no production changes before implementation lanes unblock.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command | Work |
|---|---|---|---|---|---|---|
| SL1-T1 | test | SL-0 | all ten SL-1 owned paths except `docs/research/reviewtruth-red-baseline.md`; the coordinator-provided absolute external runner root is operational evidence, never a landing path | `test_ec_reviewtruth_1_*` through `test_ec_reviewtruth_15_*`; exact bootstrap-byte, provisioning/source/wheel/RECORD/parser mutation, synthetic observer, hook mutation/subprocess, source/CI collection/plugin controls, Gate-A four-module/48-nodeid plus complete 39-retained/4-collection/59-runtime/102-total boundary controls, exact `test_gate_a_persists_independently_attestable_tests_conftest_and_parser_copy`, and exact `test_gate_a_workflow_exports_private_copy_attests_before_external_cleanup`; EC-14 duplicate-`seat_key`, retry/late, stale, replay, cross-seat/collision/digest substitution, and exactly-once-count controls; the amended EC-6 golden expected-delta assertions; the migrated `agent-harness#358` and train-resume controls; all five full existing compatibility nodeids named by this plan; immutable chronology, live-panel, evidence, collection, and JUnit contracts | the exact five operational provision/materialize/freeze/observe/parse commands and then the default/activated/golden commands in `## Verification`, in displayed order | Provision the new external root and exact isolated suite environment, materialize the observer there, freeze provisioning, and run the one-process collection before editing any SL-1 file. Require exact private canonical runner paths; no non-venv symlinks; exact uv/interpreter/package/source/wheel/distribution/RECORD/`sys.path`/module/plugin provenance; exact observer, plan, roadmap, empty all-untracked Git status, HEAD/tree/index, process, raw output/JUnit, full/selected/difference, skip, and artifact attestations. Only after the write-once external observation exists may the ten owned paths be authored. Freeze canonical compressed `REVIEWTRUTH_BROAD_PREIMPLEMENTATION_COLLECTED_NODEIDS` and `REVIEWTRUTH_BROAD_PREIMPLEMENTATION_SELECTED_NODEIDS`; readable literal `REVIEWTRUTH_BROAD_MARKER_DESELECTED_NODEIDS`, `REVIEWTRUTH_BROAD_BASELINE_SKIP_TUPLES`, `REVIEWTRUTH_GATE_A_OMITTED_SELECTED_NODEIDS`, `REVIEWTRUTH_GATE_A_COLLECTED_NODEIDS`, `REVIEWTRUTH_GATE_A_SELECTED_NODEIDS`, `REVIEWTRUTH_GATE_A_RESTRICTED_SOURCE_COLLECTION_SKIP_TUPLES`, `REVIEWTRUTH_GATE_A_RESTRICTED_SOURCE_RUNTIME_SKIP_TUPLES`, `REVIEWTRUTH_GATE_A_BOUNDARY_COLLECTION_SKIP_TUPLES`, `REVIEWTRUTH_GATE_A_BOUNDARY_RUNTIME_SKIP_TUPLES`, `REVIEWTRUTH_GATE_A_EXPECTED_COLLECTION_SKIP_TUPLES`, `REVIEWTRUTH_GATE_A_EXPECTED_RUNTIME_SKIP_TUPLES`, `REVIEWTRUTH_GATE_A_EXPECTED_SKIP_TUPLES`, `REVIEWTRUTH_EXPECTED_NODEIDS`, `REVIEWTRUTH_PHASE_NODEIDS`, `REVIEWTRUTH_POST_PARSER_NODEIDS`, `REVIEWTRUTH_NEW_NODEIDS`, `REVIEWTRUTH_MIGRATED_NODEIDS`, `REVIEWTRUTH_DEFAULT_PREMARKER_SKIP_NODEIDS`, `REVIEWTRUTH_ACTIVATED_RED_NODEIDS`, and `REVIEWTRUTH_RED_ANCHORS_BY_NODEID`; all counts/digests/reasons; exact allowed source/CI post-SL-1 transformation; exact Gate-A four-module/48-nodeid plus 39-retained/4-collection/59-runtime/102-total transformation and sibling/root proof; and source/CI versus Gate-A collection-plugin/root profiles. Freeze the five wrappers exactly as `phase-loop-runtime/tests/test_reviewtruth_phase.py::test_ec_reviewtruth_0_tdd_chronology`, `phase-loop-runtime/tests/test_reviewtruth_phase.py::test_ec_reviewtruth_9_live_panel_inspection`, `phase-loop-runtime/tests/test_reviewtruth_phase.py::test_reviewtruth_chronology_all`, `phase-loop-runtime/tests/test_reviewtruth_phase.py::test_reviewtruth_evidence_all`, and `phase-loop-runtime/tests/test_reviewtruth_phase.py::test_reviewtruth_final_evidence_all`. Freeze the two Gate A namespace/workflow nodeids as separate production assertions; their sorted-LF pair digest is `d17d8a218765ba3ce0ccea954a8a3cd082a828a7d9a4517810af0de53563a6dd`, and the workflow nodeid alone has SHA-256 `35e39b1f6a676a24231aab1bb6cf3c97dddeab0c9011017dffee015081e5f99d`. Include both in every expected/new/activated/node-anchor count and sorted-LF digest. Independently test observer digest/preconditions and parser rejection of every tampered provenance/artifact/set/reason/plugin/boundary field. Preserve the exact dual-mode hook, wrapper input boundary, legacy/forced/marker compatibility branches, native identity protocol, activated-RED authority, chronology modes, and all prior acyclic finalization constraints. |
| SL1-T2 | impl | SL1-T1 | `docs/research/reviewtruth-red-baseline.md` | bootstrap-byte/provisioning/parser mutation tests and synthetic observer subprocess controls | the exact ordered SL1-T1 commands | From the target tip that already contains the separate disposition record, execute the five operational bootstrap commands in `## Verification` before any SL-1 edit. After authoring, independently test the exact embedded digest and require the provisioner/observer to refuse a relative, in-worktree, reused, symlinked, wrong-owner, wrong-mode, nonempty, or pre-existing-output root; bare/system interpreter; dirty tree; tampered source/wheel/distribution/RECORD; user/system-site fallback; missing required package; non-allowlisted environment; ambient selector; or extra application entry point. The parser kills altered HEAD/tree/process/argv/environment/selector/application-plugin/source-root/pytest-plugin/artifact/JUnit/full/selected/difference/skip data. Recompute the exact pre-edit source/CI full and selected collections, marker difference tuple, legitimate skip tuples, raw artifact digests, exact initial/post-pytest environment maps, exact local-wheel application entry-point groups, loaded registrar/provider source digests and root mapping, and portable collection-plugin fingerprint; freeze their canonical bytes, counts, and digests plus the only allowed source/CI new-nodeid/five-wrapper transformation and the separately derived Gate-A `no:cacheprovider`, copied-root, four-module/48-nodeid plus 39-retained/4-collection/59-runtime/102-total transformation. Then run the default phase/broad and activated phase commands in exact order. Default phase JUnit contains exactly `REVIEWTRUTH_PHASE_NODEIDS`, with only the exact non-post-parser phase-default set skipped and every migrated nodeid running its legacy branch; source/CI broad default reports exactly the frozen source/CI post-SL-1 full/selected collection, disjoint marker baseline UNION five hook-owned wrappers, allowed plugin/root profile, and skips equal to the source/CI broad skip baseline UNION phase-default. Activated phase JUnit contains no wrapper, executes every frozen falsifier once, fails only at its raw RED anchor, passes every positive control, and contains no unrelated skip. Source-root, CI Python 3.10/3.11/3.12, and fresh source-clone subprocess controls prove exact source/CI equality. Gate-A copied-tree controls prove exact committed repo-owned bytes, intentional sibling/root absence, the exact Gate-A full/selected sets, the expected collection union containing the four boundary skips and retained source baseline, the expected runtime union containing all 59 boundary tuples and retained source baseline, unchanged marker-plus-wrapper categories, and GREEN. Both reject explicit `--deselect`, arbitrary/plugin-added deselection, category substitution, marker/plugin drift, a missing/extra hook wrapper, or any profile/boundary drift. Native controls preserve every prior collision/retry/late/stale/replay/cross-seat/digest/exactly-once assertion. Panel only after all parser attestations exist; retain every provisioning, observer, plan, provenance, raw observation/XML, conftest, set/category, and parser-attestation digest. Merge only the ten lane-owned production-free paths, with the external bootstrap records bound by digest in `reviewtruth-red-baseline.md`. |
| SL1-T3 | verify | SL1-T2 | all ten SL-1 owned paths | pre-implementation chronology, bootstrap trust, activation, collection, JUnit, native-identity, and immutable-boundary verification | `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k reviewtruth_preimplementation_chronology_all` | Prove the disposition record was already on the tests-only landing's first parent, the tests-only landing has its own server-recorded two-parent PR/head identity, the landing is PANELLED and RED, its diff is restricted to these ten paths, and no production file changed. Prove the exact embedded observer bytes/digest were panel-bound and ran before every SL-1 mutation; the single recorded process contemporaneously observed the exact source-capable full/selected/difference/skip/JUnit data on one clean HEAD/tree/index with exact argv and Python/pytest/module/plugin provenance; and the post-edit parser independently reproduces every relation/count/digest from raw artifacts. Prove the frozen pre-edit and allowed source/CI post-SL-1 full/selected collections, marker difference, legitimate skips, and source/CI plugin/root profile. Separately prove the Gate-A profile is derived from the unmodified copy boundary, matches exact repo-owned bytes, subtracts exactly the 48 nodeids from the four named collection-skipped modules, records the retained-source-plus-four-boundary expected collection union and the retained-source-plus-59-boundary expected runtime union, and recombines them to the exact 102-tuple total, retains the exact marker UNION five wrapper categories, and cannot be selected by an ambient flag. Exact phase default/activated outcomes and source/CI broad default skip accounting remain unchanged. Explicit/external/arbitrary/category-swapped deselection, observer/raw/attestation drift, marker/source/CI/Gate-A/plugin/root/hook drift, unexpected sibling presence, unrelated path absence, and unapproved plugin loading controls fail. Preserve the exact final collection predicate, all five compatibility migrations, every native identity falsifier, every RED anchor and positive control, and all ten immutable path digests. This check intentionally requests no future implementation metadata; SL-2 through SL-5 remain blocked until it passes on canonical `main`. |

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

- **Scope**: Wire the frozen review truth through gate-specific and train consumers, bounded production repair, canonical lifecycle/summary persistence, Claude native fill, durable typed train approval/resume evidence, and the single immutable evidence executable used by both implementation-head GitHub CI and the post-landing reducer, then cross one distinct SL-2-through-SL-5 implementation PR/landing boundary.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/src/phase_loop_runtime/governed_premerge.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `phase-loop-runtime/src/phase_loop_runtime/train_runner.py`, `phase-loop-runtime/src/phase_loop_runtime/train_ledger.py`, `phase-loop-runtime/scripts/gate_a_cleanroom.sh`, `phase-loop-runtime/scripts/verify_reviewtruth_evidence.py`, `.github/workflows/test.yml`, `skills-src/claude/claude-advisor-board/SKILL.md`, `phase-loop-skills/advisor-board/**`, `phase-loop-runtime/src/phase_loop_runtime/skills_bundle/*-advisor-board/**`, `phase-loop-runtime/src/phase_loop_runtime/skills_bundle/*-advisor-panel/**`
- **Interfaces provided**: `REVIEWTRUTH-production-gates`, `REVIEWTRUTH-native-driver-contract`, `REVIEWTRUTH-seat-outcome-ledger`, `REVIEWTRUTH-panel-verdict-ledger`, `REVIEWTRUTH-train-approval-evidence`, `REVIEWTRUTH-production-apply-fix`, `REVIEWTRUTH-evidence-executable`, `REVIEWTRUTH-gate-a-suite-attestation`, `REVIEWTRUTH-implementation-landing`
- **Interfaces consumed**: `REVIEWTRUTH-capability-ratification`, `REVIEWTRUTH-tests-first-baseline`, `REVIEWTRUTH-preimplementation-chronology`, `REVIEWTRUTH-post-parser-collection-contract`, `REVIEWTRUTH-native-fill-identity-contract`, `REVIEWTRUTH-golden-delta-baseline`, `REVIEWTRUTH-tdd-activation`, `REVIEWTRUTH-junit-contract`, `REVIEWTRUTH-broad-compatibility-gate`, `IF-0-REVIEWTRUTH-1`, `NativeAgentLegRequest.request_id`, `NativeAgentLegRequest.seat_instance_id`, `NativeAgentLegRequest.attempt_id`, `NativeAgentLegReport`, `NativeAgentLegBindingDisposition`, `bind_native_agent_leg_result()`, `ReviewGrounding`, `GovernedBoardEvidence.grounded_reviewed_seats`, `review_material_issue()`, `BoardDeliveryState`, `classify_board_delivery()`
- **Parallel-safe**: no; this is the serialized integration lane and the single writer for production gate orchestration, the evidence executable, the GitHub Gate A lifecycle, and generated skill surfaces.
- **Tasks**:
  - test: SL5-T1 — Consume the immutable real-production gate, train-resume migration, repair, planning-policy, ledger/native-attempt reconstruction, collision/late/replay/cross-seat/exactly-once binding, CLI material, evidence-executable, Gate A attester, and workflow-order falsifiers without editing tests.
  - impl: SL5-T2 — Wire production repair, gate-specific and train classification consumers, typed current-policy train approval evidence, aggregate/per-seat/native-attempt events, empty-material failure, eligible native Fable fulfillment with fresh retry identities, crash-safe exactly-once reconstruction, the immutable evidence executable with all closeout and Gate A modes, the Gate A neutral write-once persistent evidence copy, the explicit GitHub workflow lifecycle that invokes the co-landed attester, and regenerated skill mirrors.
  - verify: SL5-T3 — Prove production reachability, both live/resume policy migrations, durable native attempt reconstruction, and the co-landed workflow/attester contract; push the candidate; generate and parse phase/broad candidate XML before the ordinary suite and required GitHub CI; require CI to invoke the SL-5-owned attester and finish GREEN at that same head before golden/panel/merge; then use another fresh exact-head invocation for each implementation panel attempt and merge the distinct tests-immutable implementation PR before SL-6.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command | Work |
|---|---|---|---|---|---|---|
| SL5-T1 | test | SL-0, SL-1, SL-2, SL-3, SL-4 | all SL-5 owned paths | consume landed EC-4, EC-6, EC-8, EC-10, EC-11, EC-13, EC-14, floor-suite migration, train-resume migration, native-attempt reconstruction/collision/late/replay/cross-seat/exactly-once, and known compatibility tests without editing | `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_reviewtruth_phase.py -q -k reviewtruth_sl5`<br>`PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_advisor_board_golden.py -q` | On the marker-present partial implementation, require focused SL-5 falsifiers RED at their frozen anchors before editing SL-5 and the inherited golden GREEN. Drive real production gates for block-then-pass repair; grounded FULL/FLOOR-ONLY/BELOW-FLOOR; hard BELOW-FLOOR blocking at governed pre-merge, train merge/resume, merge-class, and CLI gates; valid current-policy grounded FULL/FLOOR-ONLY following the train gate's explicit policy; count-only, stale-policy, missing-state, and raw-ungrounded train approvals forcing re-review; unchanged degraded handling at plan-ratify/design-ratify; non-FAB per-seat ledger reconstruction including orthogonal `degraded`; metadata-only native request/attempt emitted, superseded, consumed, and rejected reconstruction; duplicate-`seat_key` isolation; fresh retry identities; late/stale/replayed/cross-seat/digest-substituted report rejection across restart; exactly-once reviewed count; and CLI/train empty/non-empty material controls. |
| SL5-T2 | impl | SL5-T1 | all SL-5 owned paths | none | the focused SL5-T1 commands during implementation; the broad candidate command only after the lane is complete | Wire the production `apply_fix` closure from `_build_repair_context`, `build_prompt`, and `launch_with_spec`; fold block findings into repair context, redispatch repair, rebuild the staged bundle, and keep its bounded rounds independent from recent-failure accounting. Consume `review_material_issue()` in CLI/planning/pre-merge/runner paths and make `_build_train_review_bundle()` carry substantive committed change material rather than PR-summary-only prose. Replace governed pre-merge's separate `_MIN_USABLE_REVIEWERS=2` decision with the gate-specific `classify_board_delivery()` consumer over grounded reviewed seats so no dual threshold survives: FULL passes, FLOOR-ONLY may proceed only with explicit degraded/shortfall state and never reports FULL, and two usable/reviewed seats are BELOW-FLOOR and block. Apply the same hard-block action only to EC-REVIEWTRUTH-1/4 governed pre-merge, train merge/resume, merge-class, and CLI gates; preserve `plan-ratify`/`design-ratify` degraded policy while forbidding them from reporting degraded progress as FULL convergence. In `train_runner.py`, use `GovernedBoardEvidence.grounded_reviewed_seats` and `classify_board_delivery()` for live train review, approval, ledger write, and resume. In `train_ledger.py`, migrate durable review evidence from raw `usable_reviewers` to typed `delivery_state` plus an incremented current `REVIEW_POLICY_VERSION`; legacy `usable_reviewers` may remain readable as non-authorizing provenance only. Resume requires exact current-policy identity and a grounded gate-authorizing delivery state; every pre-migration, count-only, missing-state, old/missing-policy, raw-ungrounded, or BELOW-FLOOR record re-enters review and cannot short-circuit merges. Emit aggregate verdicts on every governed outcome and one metadata-only `SeatOutcomeRecord` per requested non-FAB seat, including orthogonal `degraded`, through canonical events. Persist native fill as metadata-only lifecycle events carrying `seat_instance_id`, `request_id`, `attempt_id`, `seat_key`, all four content digests, transition, and typed binding disposition, never raw prompt/review text. Before dispatch/resume, reconstruct pending, superseded, consumed, and rejected identities from the canonical ledger; never re-emit a consumed identity, never accept a superseded/prior-board/replayed tuple, and allocate fresh request/attempt identities for every retry. Fulfill eligible native Fable requests through the Claude source skill under the ratified posture, echo the complete identity/digest tuple in its report, bind valid reports exactly once, preserve colliding seat instances and the real-tree execution boundary, and regenerate all neutral and packaged skill mirrors. In `gate_a_cleanroom.sh`, require a runner-supplied canonical absolute `PHASE_LOOP_GATE_A_INPUT_COPY_ROOT` that is new, private, non-symlinked, outside the script's temporary cleanup tree, and beneath the declared runner evidence root. Preserve the observed pytest namespace exactly: build and run the installed-wheel suite from the script-owned temporary `<WORK>/standalone/phase-loop-runtime/tests/**` tree, where `<WORK>/standalone/phase-loop-runtime/scripts/` is absent. Independently copy those exact executed test bytes to `<input-copy>/tests/**` and copy the committed parser only to `<input-copy>/chronology-parser/verify_reviewtruth_chronology.py`; require `<input-copy>/tests/conftest.py`, forbid `<input-copy>/phase-loop-runtime/`, fsync files/directories, and seal a canonical manifest of path, mode, byte length, and SHA-256. The existing cleanup trap removes only `WORK`; it never removes the external copy. In `.github/workflows/test.yml`, replace the old bare `bash scripts/gate_a_cleanroom.sh` step with an explicit private lifecycle: allocate a fresh canonical root beneath `${RUNNER_TEMP}`, set mode `0700`, export/pass `PHASE_LOOP_GATE_A_INPUT_COPY_ROOT`, unset and reject both selectors, invoke the script, prove its internal `WORK` cleanup completed, invoke the terminal attester while `<input-copy>/tests/**`, `<input-copy>/chronology-parser/**`, and the manifest remain readable, and clean the external root only after the attester exits. A workflow trap retains failure status while performing that final cleanup; neither success nor failure may attest after cleanup. Do not package the parser into the wheel and do not edit any of SL-1's ten frozen paths, including conftest, floor, train, golden, serializer, native-request, native-fill, chronology, and RED evidence owners. |
| SL5-T3 | verify | SL5-T2 | all SL-5 owned paths | none | `PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit-run --mode candidate --xml .phase-loop/evidence/reviewtruth-phase-candidate.xml`<br>`PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration" --junitxml=.phase-loop/evidence/reviewtruth-broad-candidate.xml`<br>`PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit --mode candidate --phase-xml .phase-loop/evidence/reviewtruth-phase-candidate.xml --broad-xml .phase-loop/evidence/reviewtruth-broad-candidate.xml`<br>`PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_advisor_board_golden.py -q` | Push the complete implementation candidate, then discard any proof from the already-loaded authoring process. In a fresh repo-local child, prove `HEAD` equals the server-reported pushed implementation head, attest repo-local module/conftest paths and digests, and run these four commands in the displayed order. The phase runner selects exactly frozen `REVIEWTRUTH_PHASE_NODEIDS` and requires zero phase skips. The unmodified broad command leaves `PHASE_LOOP_REVIEWTRUTH_POST_PARSER_COLLECTION` unset; built-in marker selection must report exactly `REVIEWTRUTH_BROAD_MARKER_DESELECTED_NODEIDS`, and the frozen try-last wrapper hook must separately find, remove, and notify exactly all five `REVIEWTRUTH_POST_PARSER_NODEIDS`, while every other collected runtime test, including all five compatibility migrations and every marker-activated new/migrated production assertion, runs. A nonempty external `--deselect`, arbitrary/category-swapped deselection, marker-baseline drift, missing/extra/wrong hook deselection, or final collection activation is forbidden. Broad skips must equal the unchanged pre-implementation skip baseline set/count/digest exactly; zero broad skips is neither required nor claimed. The candidate parser runs only after both exact XML files exist and requires zero selected phase skips, zero `xfail`, broad deselections equal to the disjoint marker baseline UNION five hook-owned wrappers with both categories attested, zero failures/errors, no missing/duplicate/unexpected phase nodeid, and no new/missing/drifted broad baseline skip. The ordinary frontmatter suite command and required GitHub CI must also be GREEN at this exact head under the same marker-baseline-plus-five deselection and broad-skip contract before merge; their absence or red status blocks the merge even if the special parser is green. The golden runs only after that parser is GREEN. Prove production repair reachability; aggregate/per-seat lifecycle persistence; native request/attempt lifecycle reconstruction across restart; unique colliding seat instances; fresh retry identities; rejection of late/stale/replayed/cross-seat/digest-substituted reports; exactly-once count; resolved brief propagation and all four content digests; material-helper consumption; exact delivery-state output; floor/train migration; generated parity; exact sanctioned golden output; and conformance to the separately ratified capability record. Only after this fresh exact-pushed-head phase/broad/parser/suite/CI/golden proof is GREEN, launch the mandatory Fable 5 + GPT-5.6 Sol + Gemini 3.6 Flash + Grok 4.5 panel from another fresh repo-local process bound to the same exact pushed head. Record its child attestation and all XML/parser/suite/CI/golden digests. Every material finding forces a new pushed head and a new fresh ordered proof and panel; no loaded parent attestation is reusable. Merge one dedicated implementation PR as a two-parent commit whose first parent already contains the disposition and tests-only landings. The implementation PR must use a distinct head identity, contain no SL-1-owned path or SL-1 tests-only commit in `implementation^1..implementation^2` or its server-recorded PR range, cite the full disposition SHA in the landing message, and be reachable from canonical `main` before SL-6 starts. |

The SL-5 executable/workflow ownership contract is atomic and binds SL5-T1, SL5-T2, and SL5-T3. SL5-T1's immutable falsifiers require the real `phase-loop-runtime/scripts/verify_reviewtruth_evidence.py` entrypoint, all `source-ownership`, `live-panel`, `ledger`, `junit`, `all`, `finalize-record`, `final-record`, `gate-a`, and `gate-a-attest` modes, explicit external path arguments, and workflow call order. SL5-T2 implements that executable in the same landing as `gate_a_cleanroom.sh` and `.github/workflows/test.yml`; `gate-a` requires `--runner-root`, `--input-copy`, `--stdout`, `--stderr`, `--artifact`, and `--attestation`, with the four output arguments equal only to the canonical `$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite.{stdout,stderr,json}` and `$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite-attestation.json` paths. The workflow must invoke this co-landed executable, retain the private external copy through its fresh `gate-a-attest` child, and clean it only afterward. SL5-T3 proves the workflow references that exact executable blob at the pushed implementation head, verifies the exact external paths and absence of Gate A suite aliases under `.phase-loop/evidence/`, and requires GitHub CI GREEN at that head before golden, panel, or merge. No later lane may edit the executable or workflow.

Within SL5-T2's workflow description, “invoke the script” and “invoke the terminal attester” are the ordered internal stages of the single `verify_reviewtruth_evidence.py gate-a` workflow call; a direct workflow call to `gate_a_cleanroom.sh` followed by an SL-6-supplied attester is forbidden.

### SL-6 — REVIEWTRUTH Evidence, Documentation, And Verification Reducer

- **Scope**: From a new repo-local process at the exact post-implementation canonical-main tip, reduce final chronology, capability ancestry, live panel inspection, governed ledger output, structured JUnit accounting, and whole-phase verification into durable metadata-linked evidence — staged as a board-reviewed pre-final record and a post-parser finalized record in an acyclic order — without modifying producer-owned tests or code.
- **Owned files**: `docs/research/reviewtruth-phase-verification.md`, `docs/research/reviewtruth-real-panel-smoke.md`, `docs/research/reviewtruth-final-evidence-record.md`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`
- **Interfaces provided**: `REVIEWTRUTH-closeout-evidence`, `IF-0-REVIEWTRUTH-1`
- **Interfaces consumed**: `REVIEWTRUTH-capability-ratification`, `REVIEWTRUTH-tests-first-baseline`, `REVIEWTRUTH-evidence-wrappers`, `REVIEWTRUTH-post-parser-collection-contract`, `REVIEWTRUTH-native-fill-identity-contract`, `REVIEWTRUTH-golden-delta-baseline`, `REVIEWTRUTH-junit-contract`, `REVIEWTRUTH-broad-compatibility-gate`, `IF-0-REVIEWTRUTH-1`, `REVIEWTRUTH-production-gates`, `REVIEWTRUTH-native-driver-contract`, `REVIEWTRUTH-seat-outcome-ledger`, `REVIEWTRUTH-panel-verdict-ledger`, `REVIEWTRUTH-production-apply-fix`, `REVIEWTRUTH-evidence-executable`, `REVIEWTRUTH-gate-a-suite-attestation`, `REVIEWTRUTH-implementation-landing`
- **Parallel-safe**: no; this terminal reducer consumes every producer lane and the immutable SL-5 evidence executable and is the only writer for synthesized evidence and final contract documentation.
- **Tasks**:
  - test: SL6-T1 — From merged canonical `main`, prove the implementation-landing precondition and immutable test-owner boundary without invoking any final chronology, live-panel, or final-evidence wrapper.
  - impl: SL6-T2 — Write only the owned pre-final evidence docs and contract/card updates while consuming, but never editing, the SL-5-owned evidence executable and its frozen `source-ownership`, `live-panel`, `ledger`, `junit`, `all`, `finalize-record`, `final-record`, `gate-a`, and fresh-child `gate-a-attest` modes; run the real four-vendor by-reference board over the exact staged digests, record exact already-existing source/proof digests and operational traces while deferring every final XML/attestation digest to SL6-T3's post-parser finalized record.
  - verify: SL6-T3 — Only after the pre-final evidence/docs exist, generate and parse source/CI broad-final producer XML, generate phase-final XML whose wrappers consume only already-existing pre-final inputs plus that attestation, parse both in final mode, finalize the post-parser evidence record, run the separate `final-record` verifier, then run the single sanitized Gate A reducer against the distinct frozen Gate-A profile and finish the golden/static and attestation-bound closeout checks; fail closed on any evidence, source/CI or Gate-A profile/skip/nodeid/count, ordering, process, or digest gap.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command | Work |
|---|---|---|---|---|---|---|
| SL6-T1 | test | SL-0, SL-1, SL-2, SL-3, SL-4, SL-5 | all SL-6 owned paths | consume immutable ownership/precondition contracts without editing | `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k reviewtruth_preimplementation_chronology_all` | Fetch canonical `main`, create a fresh branch/worktree exactly at that fetched tip already containing `REVIEWTRUTH-implementation-landing`, and launch a new repo-local process that proves `HEAD` equals the canonical-main SHA and imports every runtime module and the frozen conftest beneath this worktree. Record the child attestation before reading runtime results. Prove the implementation landing is reachable and all ten SL-1-owned paths remain byte-identical to the tests-only landing and absent from the implementation PR range. Only SL-6-owned evidence/doc paths may become dirty. Do not activate or run any of the five exact post-parser evidence nodeids before SL6-T2 writes their owned inputs and the broad-final producer XML/parser attestation exists. |
| SL6-T2 | impl | SL6-T1 | all SL-6 owned paths | none | `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k reviewtruth_preimplementation_chronology_all` | In that fresh exact-canonical-main child, consume the already-landed, byte-identical SL-5-owned evidence executable and its wrapper-consumable `source-ownership`, `live-panel`, `ledger`, `junit`, and `all` checks over already-existing artifacts; its post-parser `finalize-record` writer and separate `final-record` verifier modes remain unavailable to every test wrapper. Do not add, edit, or stage `phase-loop-runtime/scripts/verify_reviewtruth_evidence.py`. Its non-wrapper `gate-a` mode refuses to start if `PHASE_LOOP_SKIP_GATE_A_SUITE` or final collection activation is present; requires the runner-supplied canonical `REVIEWTRUTH_RUNNER_ROOT`, the new private persistent input-copy root beneath its evidence directory, and all four exact external output paths; passes the copy root to the SL-5-owned Gate A script; and writes only `$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite.stdout`, `$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite.stderr`, `$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite.json`, and `$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite-attestation.json`. Only after the script process exits and the stdout, stderr, artifact, copy manifest, and every copied file descriptor are closed may it launch a fresh internal `gate-a-attest` OS process with the same selector rejection. That process independently walks and hashes the persistent copy, requires exact set/mode/byte equality with committed `phase-loop-runtime/tests/**` plus `phase-loop-runtime/scripts/verify_reviewtruth_chronology.py`, explicitly rehashes copied `conftest.py` and parser bytes, proves the pytest argv selected that same copied tests tree, re-parses raw sidecars/artifact, and writes the terminal external attestation. It may not use producer-supplied digests without recomputation, and the copy must still exist after the Gate A temporary cleanup completes. A Gate A suite output or alias under `.phase-loop/evidence/` is forbidden. Do not add or edit test wrappers, conftest, or production runtime. Stage only `docs/research/reviewtruth-phase-verification.md` and the contract/card updates first, then run a real four-vendor board over a by-reference bundle naming those exact staged files, the immutable executable, and their digests; write `docs/research/reviewtruth-real-panel-smoke.md` as the single canonical durable redacted transcript and smoke record from that run, freeze its one SHA-256 digest, create no second durable transcript path, and freeze every pre-final SL-6 doc byte-identical from its own staging/review point through closeout. Require reviewed Fable and Sol plus the two remaining vendor seats to cite facts obtainable only by opening those files; reject no-file-read disclosure, blank material, missing native report, repo substitution, or digest mismatch. Record exact plan, all ten tests-only paths including the hook, implementation code, generated, ledger, phase default/RED/candidate XML, broad baseline/default/candidate XML, parser-attestation, evidence, and canonical `docs/research/reviewtruth-real-panel-smoke.md` digests, with exactly one digest for its combined transcript/smoke identity; distinct PR/head identities; child process attestations; source-owner mapping; candidate ordered gate, ordinary suite/CI, and golden GREEN commands; artifact-specific citations; native request/report binding including stable seat-instance, fresh request/attempt identities, resolved brief identity, all four content digests, typed rejected reports, exactly-once consumption/count, and durable reconstruction; material-guard outcomes; production repair trace; per-seat reconstruction; and typed current-policy train approval/resume evidence. The pre-final record deliberately excludes the broad-final/phase-final XML digests, final parser attestations, finalized record, `final-record` attestation, Gate A run/output/artifact/attestation, and run-end verdict: none of those exist yet, and they are recorded only by SL6-T3's post-parser finalized record where applicable and the ledger closeout. Update the canonical contract and capability card from SL-1's already-frozen sanctioned golden delta plus the narrow native-fill reversal, exact-once identity binding, and retained real-tree capability boundary; SL-6 may not add a newly discovered delta or repair production output. |
| SL6-T3 | verify | SL6-T2 | all SL-6 owned paths | none | `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration" --junitxml=.phase-loop/evidence/reviewtruth-broad-final.xml`<br>`PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit --mode broad-final-producer --xml .phase-loop/evidence/reviewtruth-broad-final.xml`<br>`PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit-run --mode final --xml .phase-loop/evidence/reviewtruth-phase-final.xml`<br>`PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit --mode final --phase-xml .phase-loop/evidence/reviewtruth-phase-final.xml --broad-xml .phase-loop/evidence/reviewtruth-broad-final.xml`<br>`PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_evidence.py finalize-record --phase-xml .phase-loop/evidence/reviewtruth-phase-final.xml --broad-xml .phase-loop/evidence/reviewtruth-broad-final.xml --record docs/research/reviewtruth-final-evidence-record.md`<br>`PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_evidence.py final-record --record docs/research/reviewtruth-final-evidence-record.md --attestation .phase-loop/evidence/reviewtruth-final-record-attestation.json`<br>`PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_advisor_board_golden.py -q`<br>`PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration"`<br>`env -u PHASE_LOOP_SKIP_GATE_A_SUITE -u PHASE_LOOP_REVIEWTRUTH_POST_PARSER_COLLECTION REVIEWTRUTH_RUNNER_ROOT="$REVIEWTRUTH_RUNNER_ROOT" PHASE_LOOP_GATE_A_INPUT_COPY_ROOT="$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-inputs" sh -c 'PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_evidence.py gate-a --runner-root "$REVIEWTRUTH_RUNNER_ROOT" --script phase-loop-runtime/scripts/gate_a_cleanroom.sh --input-copy "$PHASE_LOOP_GATE_A_INPUT_COPY_ROOT" --stdout "$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite.stdout" --stderr "$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite.stderr" --artifact "$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite.json" --attestation "$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite-attestation.json"'`<br>`ruff check phase-loop-runtime/src/phase_loop_runtime/`<br>`phase-loop validate-roadmap specs/phase-plans-v10.md`<br>`git diff --check` | Run these commands in the displayed order only after SL6-T2, from the fresh child whose exact canonical-main/runtime attestation is already recorded; a loaded parent may not substitute. The broad/final ordering and acyclic record rules remain unchanged. For Gate A, invoke the immutable SL-5-owned evidence executable with the declared runner root, input-copy root, and four exact canonical external output paths; its `gate-a` mode runs the script and then its fresh `gate-a-attest` child while the external copy remains readable. `.github/workflows/test.yml` uses that same co-landed executable and ordering at the implementation head before SL-6: it allocates a fresh private external copy root, unsets both selectors, exports `PHASE_LOOP_GATE_A_INPUT_COPY_ROOT`, runs the reducer, proves the script's internal temporary `<WORK>` cleanup completed, invokes the terminal attester while the external copy remains readable, and only then removes that external root. The script's pytest runtime tree remains `<WORK>/standalone/phase-loop-runtime/tests/**` and must lack `<WORK>/standalone/phase-loop-runtime/scripts/`; the neutral external evidence copy contains only `tests/**` (including `tests/conftest.py`), `chronology-parser/verify_reviewtruth_chronology.py`, and its manifest, and must lack every `phase-loop-runtime/scripts/` root. The reducer rejects either inherited selector, the old workflow invocation without the exported root, a reused/symlinked root, parser misnamespace, any Gate A suite output or alias under `.phase-loop/evidence/`, attestation after cleanup, external cleanup before attestation, or any implementation that recreates scripts in the temporary runtime tree. It independently verifies the same frozen 48-node omission, 4 collection-boundary tuples, 59 runtime-boundary tuples, 102-tuple union, marker/hook categories, sentinels, profile, committed bytes, and zero-failure outcome described above. Every other SL6-T3 closeout, owner-map, immutable-test, native-report, panel, ledger, and digest requirement remains unchanged. |

## Execution Policy

- work-unit defaults: work-unit=`lane_execute`, effort=`high`, unsupported=`inherit_default`, inherit-default=`true`
- SL-6: work-unit=`phase_reducer`, effort=`high`, unsupported=`inherit_default`, inherit-default=`true`, reason=`terminal evidence and documentation reducer`

## Execution Notes

- Policy precedence is CLI/operator override, phase-plan policy, roadmap policy, `Dispatch Hints`, then registry defaults. This plan does not select the implementation author: the coordinator must explicitly rotate one whole-phase author vendor and keep both runtime schedulers off. Silent executor/model/effort downgrade is forbidden without explicit fallback or inherited defaults.
- Every model/reviewer invocation uses the existing subscription-authenticated CLI or native harness path only; API-key/provider-key execution and PI provider fallback are forbidden. REVIEWTRUTH performs no release publication, release creation, or tag creation.
- Plan review is a pre-dispatch gate, not a lane. Record the exact plan digest, executor/model/effort, Fable/Sol reviewed outcomes, all four seat outcomes, and resolution of every material finding in the canonical runner ledger before SL-0.
- Before the REVIEWTRUTH lane DAG begins, this planning candidate owns and lands `phase-loop-runtime/uv.lock` at SHA-256 `b89987030b895131c3de05a316783ac0bcb6423d5531d6e9a04ee4a8f1e9fcce` together with this plan and its manifest metadata. That prerequisite must be on canonical `main` before SL-0 dispatch and is intentionally absent from every lane's `Owned files`: SL-0 through SL-6 consume the frozen committed input but may not create, regenerate, replace, or claim it in tests-only, implementation, or closeout history. A different or later lock invalidates the reviewed plan/bootstrap identity; it cannot retroactively alter the observation.
- The complete tracked phase-owned write set is the sorted 34-pattern union of SL-0 through SL-6, SHA-256 `3d096f13a72f825f77f0f1897ff29af58c82fe36b68ca0ba87d80a7995c8ec91` over LF-joined repo-relative patterns plus terminal LF. The immutable ten-path SL-1 tests/evidence boundary uses the same framing and SHA-256 `3828b5cd50a38b7665d6520ba437e410ac77a34f15488ce035fb1b6febfdeb6f`. The current repair adds no SL-1 path, but adds two literal nodes in already-owned `phase-loop-runtime/tests/test_reviewtruth_phase.py`: `phase-loop-runtime/tests/test_reviewtruth_phase.py::test_gate_a_persists_independently_attestable_tests_conftest_and_parser_copy` and `phase-loop-runtime/tests/test_reviewtruth_phase.py::test_gate_a_workflow_exports_private_copy_attests_before_external_cleanup`; their sorted-LF digest is `d17d8a218765ba3ce0ccea954a8a3cd082a828a7d9a4517810af0de53563a6dd`. Transferring `phase-loop-runtime/scripts/verify_reviewtruth_evidence.py` from SL-6 to SL-5 changes only its single-writer lane, not the union, count, or digest. That executable, `phase-loop-runtime/scripts/gate_a_cleanroom.sh`, and `.github/workflows/test.yml` are the atomic SL-5 implementation boundary paths and participate in the unchanged 34-pattern count/digest.
- SL-0 and SL-1 require separate landings before production work. The capability record must reach canonical `main` first in its own PR after the plan/lock prerequisite landing. The tests-only change starts from that main tip and, before editing any SL-1 file, creates a coordinator-selected private absolute runner root outside Git; provisions an isolated uv-managed environment from the exact lock-bearing external Git-archive source and exact local wheel; materializes the exact panel-reviewed bootstrap bytes there; freezes environment provenance; and executes one controlled GREEN `-m "not dotfiles_integration"` process with the environment's exact interpreter. The bootstrap chain freezes exact plan/roadmap/observer/provisioning/lock digests; empty all-untracked status plus identical HEAD/tree/index before and after every step; process and argv; uv/interpreter/package/source/wheel/distribution/RECORD/`sys.path`/pytest/module/plugin provenance; raw output/JUnit; full pre-marker and selected post-marker collections; exact marker difference; and legitimate skips. Only afterward are the tests/conftest/parser authored; the parser independently recomputes the external observation from explicit absolute paths and the runner generates/parses phase default, broad default, and activated phase XML in the exact SL1-T1 order. Only after those parser attestations and the provisioning/observer/parser/collection/native-identity mutation controls exist is the exact tests-only digest PANELLED by the required four-seat board and landed in a separate production-change-free PR. `reviewtruth_preimplementation_chronology_all` is the only chronology gate that unblocks implementation and intentionally needs no future landing. Implementation starts from the tests-only canonical-main tip under a distinct PR/head identity. The ten frozen SL-1 paths are exactly `phase-loop-runtime/tests/conftest.py`, `phase-loop-runtime/tests/test_reviewtruth_phase.py`, `phase-loop-runtime/tests/test_train_merge.py`, `phase-loop-runtime/tests/test_governed_cross_vendor_floor_358.py`, `phase-loop-runtime/tests/test_advisor_board_golden.py`, `phase-loop-runtime/tests/test_advisor_board_research.py`, `phase-loop-runtime/tests/test_panel_invoker_spawn.py`, `phase-loop-runtime/tests/test_panel_native_fill_183.py`, `phase-loop-runtime/scripts/verify_reviewtruth_chronology.py`, and `docs/research/reviewtruth-red-baseline.md`; the external runner root is bound evidence, never a landing path, and none of the ten tracked paths may appear in `implementation^1..implementation^2`, the server-recorded implementation PR diff/range, or any tests-only commit carried on the implementation branch.
- The tests-only production-activation boundary, post-parser collection boundary, exact source/CI and Gate-A collection-profile freezes, collection-plugin/root profiles, and all marker/hook/collection-skip/runtime-skip accounting categories are immutable. `PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1` forces new production behavior only for the pre-implementation RED proof; absent that variable, the exact `REVIEWTRUTH_CAPABILITY_MARKER = "reviewtruth@1"` switches the same non-wrapper test bodies from default legacy/skip behavior to new assertions. Neither activates the five post-parser wrappers. Ordinary/default tests-only CI, marker-present implementation CI, the frontmatter suite command, the explicitly amended workflow, and fresh source-clone default suites are GREEN because their canonical collection must equal the frozen source-capable pre-edit sets plus exactly the declared new REVIEWTRUTH nodeids; built-in `-m "not dotfiles_integration"` selection contributes exactly the frozen pre-edit marker deselection baseline; and the try-last conftest hook separately contributes exactly the five wrapper deselections unless the exact value `PHASE_LOOP_REVIEWTRUTH_POST_PARSER_COLLECTION=junit-run:final:v1` is set by final `junit-run` after broad-final attestation. Clean-room Gate A is GREEN under its separate exact profile: identical copied repo-owned bytes; source/CI sets minus exactly the 48 unmarked nodeids from the four named collection-skipped modules; the exact expected collection/runtime skip unions composed from the retained source baselines plus the proved four-tuple collection and 59-tuple runtime boundaries; and the same retained marker baseline UNION exact five wrapper deselections. Phase-selected default/RED/candidate use the frozen non-wrapper phase set; final uses the full expected set and requires zero phase skips/deselections. Source/CI broad default/candidate/broad-final retain exact source-capable full/selected and skip equality; Gate A must equal only its separately frozen profile. The implementation installs only the marker and production behavior. It cannot edit conftest, test imports, guards, branch/collection predicates, activation name/value, nodeids, selectors, expected counts/digests, collection/plugin/root profiles, any skip set/reason, any deselection tuple/category/reason, RED anchors, JUnit runner/parser, or evidence wrappers. No `xfail`, external `--deselect`, arbitrary deselection, unapproved collection-capable plugin, category substitution, source/CI or Gate-A full/selected/marker/plugin/root drift, or hook drift is permitted; any collection/import failure or skip beyond the exact frozen Gate-A expected collection-skip union, unexpected/drifted skip or deselection, ordinary-suite/CI/Gate-A red status, or compatibility test that first fails after merge is a hard failure.
- Pytest/pluggy distribution versions, interpreter and absolute module or distribution paths, module/file digests, and version-bearing approved core-plugin metadata remain mandatory in every bootstrap, source/CI, and Gate-A provenance record and mismatch diagnostic, but are never semantic equality keys by themselves. Cross-environment parity compares the repo-owned test/conftest/parser bytes and digests, declared selectors, exact application-plugin entry points and repo-owned origins, declared repository/root maps, normalized approved core-plugin roles/origins, and each environment's frozen source/CI or Gate-A canonical nodeid/skip profile, hook behavior, command profile, collection outcome, exit status, and JUnit/result accounting. The parser and conftest controls must accept a fixture that changes only those pytest/pluggy diagnostic values while preserving the applicable semantic profile, and must reject a paired toolchain fixture that changes plugin origin, repo-owned bytes, profile selection, collection, nodeids, skip/deselect accounting, hook behavior, exit status, or results. Missing or internally inconsistent provenance also fails; provenance-only release drift does not.
- Source/CI skip parity applies PC-REVIEWTRUTH-5A before equality: the one collected hard-coded-interpreter node is classified as `portable_pass` or the exact verified `environment_interpreter_pair_unavailable` disposition, removed from the raw skip tuple only after that validation, and recorded separately with path-existence facts and raw reason. The remaining source/CI skip set must equal the frozen baseline exactly across Python 3.10, 3.11, and 3.12. The literal normalization falsifier is part of `REVIEWTRUTH_EXPECTED_NODEIDS`, `REVIEWTRUTH_NEW_NODEIDS`, activation/RED maps, candidate/final JUnit, and evidence digests; SL-1 freezes its exact membership/count/digest. Gate A is not normalized and its 39+4+59 contract is unchanged. No broad environment exclusion or additional portable node may be added after the tests-only freeze.
- SL-2 through SL-5 are authored by one explicitly rotated whole-phase author vendor, remain together on the distinct implementation branch, and cross one implementation review/landing boundary before SL-6. Both runtime schedulers stay off; file-disjointness does not authorize a second author vendor. Intermediate lane checks use their immutable focused selectors because installing the marker intentionally exposes downstream RED tests until their owner lane is implemented; no intermediate candidate may panel or merge. After SL-5, every implementation candidate is pushed. A fresh repo-local process proves it is bound to the exact server-reported pushed head, generates phase-candidate XML at `.phase-loop/evidence/reviewtruth-phase-candidate.xml` over the frozen non-wrapper phase set, generates broad-candidate XML at `.phase-loop/evidence/reviewtruth-broad-candidate.xml` with the immutable marker-selection baseline and ordinary conftest hook separately attested, and invokes the frozen parser in candidate mode against those exact existing paths. The parser requires zero selected phase skips, total broad deselections equal to marker baseline UNION the five hook-owned wrappers with each category exact, and the unchanged broad skip baseline after the one PC-REVIEWTRUTH-5A disposition is validated and separately recorded; it never claims five total broad deselections or broad zero skips. The suite command and required amended GitHub CI must be GREEN at the same exact pushed head before the exact golden, fresh exact-head panel, or merge decision. The workflow falsifier must prove its private-copy allocation, selector rejection, script-then-attester ordering, and attester-then-cleanup order at that head. Every finding repair creates a new pushed head and invalidates all prior XML, parser, suite/CI, golden, and panel evidence. The mandatory Fable 5 + GPT-5.6 Sol + Gemini 3.6 Flash + Grok 4.5 panel is itself launched from a new repo-local process at that exact head. The implementation PR then lands as a two-parent merge whose first parent already contains both prior landings. SL-6 starts only from a different fresh process at the exact fetched post-merge canonical-main head.
- The owned chronology verifier has separate `pre-implementation` and `final` ancestry modes over full immutable SHAs and server-recorded PR/head identities, exact-selector `junit-run` modes `default-premarker`, `activated-red`, `candidate`, and `final`, and parser modes `broad-baseline`, `default-premarker`, `activated-red`, `candidate`, `broad-final-producer`, and `final`. Its `broad-baseline` mode accepts only explicit canonical absolute external-root/provisioning/observation/observer paths after the observer ran: it independently verifies the private disjoint runner boundary, exact embedded observer and provisioning digests, raw artifact/JUnit digests and outcomes, plan/roadmap SHA, empty all-untracked status and same HEAD/tree/index, same process identity, command and uv/interpreter/package/source/wheel/distribution/RECORD/`sys.path`/pytest/module/plugin provenance, exact source-capable full and selected collections, exact marker difference, and legitimate skips. It then freezes the allowed source/CI post-SL-1 full/selected transform; the separately derived Gate-A full/selected transform, exact four-module/48-nodeid collection boundary, 59-tuple runtime boundary, 39-tuple retained source baseline, and 102-tuple expected union, and sibling/root absence proof; source/CI versus Gate-A plugin/root profiles; full/non-wrapper/post-parser and broad nodeid sets/counts/sorted-LF SHA-256 digests; the conftest digest and exact collection name/value/predicate; migrated legacy run set; activated RED nodeids/raw anchors; the exact marker-filter deselection tuple/count/digest and five exact hook-owned ordinary deselections as disjoint categories; candidate zero-phase-skip plus source/CI collection/plugin/marker/hook/skip-baseline accounting; and final all-expected-ran-once zero-phase-skip/deselection plus unchanged source/CI broad accounting. Both ancestry modes refuse a shallow repository, grafts, or `refs/replace`. Final mode resolves the implementation landing with `git rev-list --parents -n 1`, requires exactly two parents, treats its first parent as the pre-landing target tip, applies `git merge-base --is-ancestor` to both the recorded disposition SHA and tests-only landing SHA against that first parent, requires the landing message to contain the full record SHA, and matches all three landings to distinct server-recorded PR metadata. It also rejects a reused tests-only head identity, any SL-1 tests-only commit in `implementation^1..implementation^2`, any of the ten frozen SL-1 paths in that range or the server-recorded implementation PR diff, and any implementation source that diverges from the ratified posture. The five exact post-parser wrappers are absent from non-final phase selectors, hook-deselected in addition to the marker baseline from ordinary source/CI broad/default/fresh-clone collection and the retained Gate-A collection, and must all run exactly once with zero phase skips/deselections in phase-final XML only after `junit-run --mode final` verifies broad-final and sets its child-only exact activation. Their frozen assertions consume only pre-phase-final inputs, so the phase-final XML, final-mode parser attestation, post-parser finalized record, `final-record` attestation, and closeout verdicts stay outside every wrapper; after the final parse, `finalize-record` writes the finalized record, the separate `final-record` verifier attests it from outside, the sanitized Gate A reducer emits its independently checked profile attestation later, and only then does the closeout bind all three terminal evidence identities. Squash, rebase, direct-push, single-parent landing, same-branch history, a record carried only on the implementation branch, tests in the implementation range, bootstrap-root/provisioning/observer/provenance/raw-artifact drift, user/system-site fallback, external/arbitrary/category-swapped deselection, source/CI or Gate-A profile/full/selected/skip/marker/plugin/root/hook drift, marker-driven wrapper collection, final activation before broad-final attestation, parser-before-generation, wrapper-before-attestation, finalization-before-final-parse, record-verification-before-finalization, closeout-before-record-attestation, or blanket roadmap authorization is a phase failure.
- SL-3 and SL-4 are file-disjoint, but SL-4 has a real data dependency on SL-3's `GovernedBoardEvidence.grounded_reviewed_seats`; prose order is not a substitute for that edge. SL-3 only publishes grounding/material helpers. SL-5 exclusively owns `train_runner.py` and `train_ledger.py`, runs after SL-4, and consumes those helpers plus `BoardDeliveryState`/`classify_board_delivery()` for live train review, ledger write, and resume. The coordinated v10 runtime lane scheduler stays off to preserve a single author vendor.
- Durable train review approval is schema/policy evidence, not a count snapshot: `REVIEW_POLICY_VERSION` is incremented for the grounding/three-state migration, `delivery_state` is derived only from grounded reviewed seats, and resume requires both the exact current version and a train-gate-authorizing typed state. Every existing `test_train_merge.py` honor/crash/recovery fixture that currently plants `usable_reviewers=2` or count-only evidence is migrated in SL-1; existing pre-migration/count-only approvals, two-reviewed evidence, raw ungrounded usable evidence, missing state, BELOW-FLOOR, and stale/missing policy identity never short-circuit review. Only valid current-policy grounded FULL/FLOOR-ONLY is a positive resume control and follows the explicit train gate policy.
- Native fill is a durable attempt protocol, not an in-memory `seat_key` lookup. A unique stable `seat_instance_id` identifies one requested seat through retries even when two seats share the same non-unique `seat_key`; every request emission/retry allocates fresh non-reused `request_id` and `attempt_id`; and request/report both carry the exact artifact/brief/lens/prompt digests. Binding consumes one current pending tuple atomically and at most once. Unknown, late, stale, replayed, cross-seat/colliding-seat, identity/digest-mismatched, and non-terminal reports produce typed rejected transitions and never mutate a seat or count. Canonical metadata-only events reconstruct emitted, pending, superseded, consumed, and rejected identities before retry/resume, so a process restart or late first-attempt report cannot re-inflate reviewed or grounded counts.
- `test_advisor_board_golden.py` is an SL-1-owned normative contract, not an SL-6 discovery aid. Its sanctioned-delta list freezes the additive typed result fields, prompt/lens carrier, and native request/report identity/digest surface required by IF-0-REVIEWTRUTH-1 while preserving every unlisted legacy launch/result/serialization behavior. The adjacent SL-1 compatibility migrations freeze the exact `dataclasses.asdict` shape transition, Fable/Opus native-request reversal, and all three under-Claude-Code Fable native-fill reversals under their five unchanged full nodeids. Each migrated nodeid has immutable legacy/default, forced-activation/new, and automatic post-marker/new assertions over every affected field, including stable seat-instance, fresh request/attempt identities, and artifact/brief/lens/prompt digests; the no-local-CLI node proves the local support probe is irrelevant after the host is identified as Claude Code, while the brief-flow node binds the resolved `brief_ref`, instructions, and their digests. SL-2 through SL-5 cannot edit or rebaseline any of them; the ordered candidate phase/broad parser, ordinary suite/CI, and exact golden command gate every implementation panel/merge. SL-6 only mirrors the frozen rule into `advisor_board/CONTRACTS.md` and `docs/advisor-board-capabilities-card.md` and re-runs it.
- The coordinated run retains its bootstrap no-degraded-promotion interlock: planning, tests, implementation review, and closeout require all four intended seats with Fable and Sol reviewed. The closeout board reviews the exact finalized evidence record digest, the `final-record` attestation, and the terminal Gate A suite attestation, and its verdict is written only to the canonical ledger. The runtime implementation may represent FLOOR-ONLY and follow an explicit downstream policy, but this phase cannot use its own new degraded semantics to waive the board that authorizes it.
- `timed_out` is frozen and consumed here; subprocess timeout enforcement, process-group killing, and child reaping stay owned by LEGLIFE. Per-repo custom seats and RISCO lenses also stay out of scope.
- The `REVIEWTRUTH-redacted-transcript-policy` designates `docs/research/reviewtruth-real-panel-smoke.md` as the single canonical durable redacted transcript and smoke record and requires it to prove inspection, not command construction. Raw model output remains only in the protected live artifact. The canonical repo file contains only redacted transcript material, artifact-specific citations, seat identities/outcomes, and metadata, has one frozen SHA-256 digest for its combined transcript/smoke identity, and may not be accompanied by a second durable transcript path; do not substitute argv goldens or a hand-built `panel_verdict` event. Metadata-only closeout records only that exact path and single digest, seat identities/outcomes, and citations, never raw model output. The post-parser finalized evidence record and `final-record` attestation are likewise metadata-only: digests, paths, identities, and outcomes, never raw model output.
- This plan is intentionally pre-PROOFGATE. Its Acceptance Criteria use the currently accepted `proven by <command>` plan grammar; each roadmap criterion's `falsified by` mutation is bound in SL-1 to a named test, asserted injection anchor, and positive control, and the RED/evidence records retain that mapping. `IF-0-PROOFGATE-1` is produced and mechanically required only by the later PROOFGATE phase, so this plan neither claims that future interface nor drops its falsifiers.
- Documentation impact: SL-6 updates the normative board contract and capability card because the roadmap reverses the Fable native-fill prohibition narrowly. Record `no_doc_delta` for `README.md`, `CHANGELOG.md`, packaging dependency declarations, env examples, migrations, and release notes because REVIEWTRUTH changes no public release/package surface. The newly tracked `phase-loop-runtime/uv.lock` is instead this plan repair's frozen bootstrap prerequisite and is complete before SL-0; it is not an SL-6 documentation delta or a later REVIEWTRUTH implementation change.

### Exact bootstrap observer payload

No suitable immutable coordinator/runner observer exists. The materialization command in `## Verification` extracts the exact bytes between the sentinels below, appends the one displayed terminal LF, and refuses any digest other than `841cfb8bbac1d9b4ea0bb14a1f3600165550227b680b2e5689c79c13c61b1f6d` (`39420` bytes). The bootstrap is intentionally external to every SL-1 tracked path: a coordinator supplies a new canonical absolute runner root outside Git, and the provisioning environment, exact lock-bearing external Git-archive source, wheel, uv-managed Python, HOME/TMPDIR, materialized observer, provisioning freeze, and successful observation all stay beneath it. The root, its direct bootstrap directories, observer, freeze, and evidence paths are write-once, privately owned/mode-checked, and non-symlinked; a venv interpreter link is accepted only when its real target stays under the root's uv-managed Python directory. Its trust chain is: exact bytes and digest reviewed with this plan; committed planning lock digest `b89987030b895131c3de05a316783ac0bcb6423d5531d6e9a04ee4a8f1e9fcce`; external provisioning from grounded repository package/CI sources; exact `env -i` allowlist and uv/interpreter/package/source/wheel/distribution/RECORD/`sys.path`/module/application-selector/plugin/root profile frozen by the observer's provision mode; plan digest and empty all-untracked Git status recorded before any SL-1 edit; one-process raw observation sealed before repo verifier authorship; independent post-observation parser and synthetic/tamper tests over the same exact bytes and provisioning/environment/plugin/root contract; tests-only four-seat panel binding of provisioning, observer, raw-observation, parser, and record digests; and immutable final chronology. The observer's own attestation is necessary raw evidence, not sufficient authority.

<!-- REVIEWTRUTH_BASELINE_OBSERVER_BEGIN -->
```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import contextlib
import csv
import hashlib
import importlib
import importlib.metadata
import inspect
import io
import json
import os
from pathlib import Path
import platform
import site
import stat
import subprocess
import sys
import uuid
import zipfile

import pytest

SCHEMA = "reviewtruth.baseline-observation.v3"
PROVISION_SCHEMA = "reviewtruth.bootstrap-provisioning.v1"
MARKER = "dotfiles_integration"
PROFILE_SELECTOR = "phase_loop_runtime.dotfiles_profile_plugin:register_profile_commands"
SKILL_SOURCE_SELECTOR = "phase_loop_runtime.skill_sources_plugin:register_skill_sources"
APPLICATION_PLUGIN_GROUPS = (
    "phase_loop_runtime.profile_commands",
    "phase_loop_runtime.skill_sources",
)
EXPECTED_ENTRY_POINTS = {
    "phase_loop_runtime.profile_commands": (
        "dotfiles",
        PROFILE_SELECTOR,
    ),
    "phase_loop_runtime.skill_sources": (
        "dotfiles",
        SKILL_SOURCE_SELECTOR,
    ),
}
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


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def require_private_dir(path: Path, *, exact_mode: int | None = None) -> None:
    if not path.is_absolute() or path != path.resolve(strict=True):
        raise RuntimeError(f"directory must be an existing canonical absolute non-symlink: {path}")
    st = path.lstat()
    if not stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode):
        raise RuntimeError(f"expected real directory, not symlink: {path}")
    if st.st_uid != os.getuid():
        raise RuntimeError(f"directory owner mismatch: {path}")
    mode = stat.S_IMODE(st.st_mode)
    if exact_mode is not None and mode != exact_mode:
        raise RuntimeError(f"directory mode must be {oct(exact_mode)}: {path} is {oct(mode)}")
    if mode & 0o077:
        raise RuntimeError(f"directory is not private: {path} is {oct(mode)}")


def validate_runner_root(repo: Path, runner_root: Path) -> None:
    require_private_dir(runner_root, exact_mode=0o700)
    if is_within(runner_root, repo) or is_within(repo, runner_root):
        raise RuntimeError("runner root and git toplevel must be disjoint")
    for name in (
        "build",
        "evidence",
        "home",
        "materialized",
        "python",
        "source",
        "tmp",
        "uv-cache",
        "venv",
        "wheels",
    ):
        require_private_dir(runner_root / name)
    for name in ("build", "evidence", "home", "materialized", "source", "tmp", "wheels"):
        for path in (runner_root / name).rglob("*"):
            if path.is_symlink():
                raise RuntimeError(f"symlink in bootstrap artifact tree is forbidden: {path}")
            st = path.lstat()
            if st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
                raise RuntimeError(f"bootstrap artifact owner/mode is not private: {path}")


def expected_initial_environment(repo: Path, runner_root: Path) -> dict[str, str]:
    return {
        "HOME": str(runner_root / "home"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": f"{runner_root / 'venv' / 'bin'}:/usr/bin:/bin",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": str(repo / "phase-loop-runtime" / "src"),
        "TMPDIR": str(runner_root / "tmp"),
    }


def expected_post_pytest_environment(repo: Path, runner_root: Path) -> dict[str, str]:
    return {
        **expected_initial_environment(repo, runner_root),
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
    if path.is_symlink():
        raise RuntimeError(f"provenance file may not be a symlink: {path}")
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
        "mode": oct(stat.S_IMODE(resolved.stat().st_mode)),
    }


def module_record(name: str, repo: Path) -> dict[str, object]:
    module = sys.modules.get(name)
    path = Path(module.__file__) if module is not None and getattr(module, "__file__", None) else None
    return {
        "name": name,
        "version": getattr(module, "__version__", None) if module is not None else None,
        "file": file_record(path, repo),
    }


def git_source_record(repo: Path, external_source: Path) -> dict[str, object]:
    raw = git(repo, "ls-tree", "-r", "-z", "HEAD", "--", "phase-loop-runtime")
    records: list[dict[str, object]] = []
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode, kind, oid = metadata.decode().split()
        path = raw_path.decode()
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise RuntimeError(f"unsupported tracked runtime source entry: {entry!r}")
        repo_path = repo / path
        external_path = external_source / path.removeprefix("phase-loop-runtime/")
        if repo_path.is_symlink() or external_path.is_symlink():
            raise RuntimeError(f"runtime source symlink is forbidden: {path}")
        repo_bytes = repo_path.read_bytes()
        external_bytes = external_path.read_bytes()
        if repo_bytes != external_bytes:
            raise RuntimeError(f"external Git-archive source drift: {path}")
        records.append(
            {
                "path": path,
                "mode": mode,
                "git_oid": oid,
                "sha256": sha(repo_bytes),
                "bytes": len(repo_bytes),
            }
        )
    if not records:
        raise RuntimeError("runtime source manifest is empty")
    return {
        "head_tree": git(repo, "rev-parse", "HEAD:phase-loop-runtime").decode().strip(),
        "files": len(records),
        "manifest_sha256": sha(canonical_json(records)),
        "pyproject_sha256": sha((external_source / "pyproject.toml").read_bytes()),
        "uv_lock_sha256": sha((external_source / "uv.lock").read_bytes()),
    }


def wheel_record(path: Path, runner_root: Path) -> dict[str, object]:
    if (
        not path.is_absolute()
        or path != path.resolve(strict=True)
        or path.is_symlink()
        or not is_within(path, runner_root / "wheels")
    ):
        raise RuntimeError("wheel must be one canonical non-symlink file under runner-root/wheels")
    wheel_bytes = path.read_bytes()
    members: list[dict[str, object]] = []
    with zipfile.ZipFile(path) as archive:
        for info in sorted(archive.infolist(), key=lambda value: value.filename):
            if info.is_dir():
                continue
            data = archive.read(info)
            members.append(
                {
                    "path": info.filename,
                    "sha256": sha(data),
                    "bytes": len(data),
                }
            )
    record_members = [
        row for row in members if str(row["path"]).endswith(".dist-info/RECORD")
    ]
    if len(record_members) != 1:
        raise RuntimeError("local wheel must contain exactly one distribution RECORD")
    return {
        "path": str(path),
        "sha256": sha(wheel_bytes),
        "bytes": len(wheel_bytes),
        "members": len(members),
        "members_sha256": sha(canonical_json(members)),
        "record_sha256": record_members[0]["sha256"],
    }


def distribution_record(
    distribution: importlib.metadata.Distribution,
    runner_root: Path,
) -> dict[str, object]:
    dist_path = Path(distribution._path).resolve()
    venv = (runner_root / "venv").resolve()
    if not is_within(dist_path, venv):
        raise RuntimeError(f"installed distribution escaped the isolated venv: {dist_path}")
    metadata_path = dist_path / "METADATA"
    record_path = dist_path / "RECORD"
    if not metadata_path.is_file() or not record_path.is_file():
        raise RuntimeError(f"wheel distribution lacks METADATA or RECORD: {dist_path}")
    rows: list[dict[str, object]] = []
    with record_path.open(newline="", encoding="utf-8") as stream:
        for rel, encoded_hash, _size in csv.reader(stream):
            candidate = Path(distribution.locate_file(rel))
            if candidate.is_symlink():
                raise RuntimeError(f"installed RECORD member is symlinked: {rel}")
            installed = candidate.resolve(strict=True)
            if not is_within(installed, venv):
                raise RuntimeError(f"installed RECORD member escaped venv or is symlinked: {rel}")
            data = installed.read_bytes()
            if encoded_hash:
                algorithm, encoded = encoded_hash.split("=", 1)
                if algorithm != "sha256":
                    raise RuntimeError(f"non-SHA256 RECORD member: {rel}")
                actual = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
                if actual != encoded:
                    raise RuntimeError(f"installed RECORD hash mismatch: {rel}")
            rows.append({"path": rel, "sha256": sha(data), "bytes": len(data)})
    name = distribution.metadata.get("Name")
    if not name:
        raise RuntimeError(f"installed distribution has no Name: {dist_path}")
    return {
        "name": name,
        "version": distribution.version,
        "path": str(dist_path),
        "metadata_sha256": sha(metadata_path.read_bytes()),
        "record_sha256": sha(record_path.read_bytes()),
        "installed_files": len(rows),
        "installed_files_sha256": sha(canonical_json(rows)),
    }


def distribution_inventory(runner_root: Path) -> list[dict[str, object]]:
    records = [
        distribution_record(distribution, runner_root)
        for distribution in importlib.metadata.distributions()
    ]
    records.sort(key=lambda row: (str(row["name"]).lower(), str(row["version"])))
    if len({str(row["name"]).lower() for row in records}) != len(records):
        raise RuntimeError("duplicate installed distribution name")
    required = {
        "phase-loop-runtime",
        "pytest",
        "pydantic",
        "consiliency-contract",
        "pillow",
    }
    present = {str(row["name"]).lower() for row in records}
    missing = required - present
    if missing:
        raise RuntimeError(f"isolated environment lacks required distributions: {sorted(missing)!r}")
    return records


def sys_path_record(repo: Path, runner_root: Path) -> dict[str, object]:
    venv = (runner_root / "venv").resolve()
    managed_python = (runner_root / "python").resolve()
    if Path(sys.prefix).resolve() != venv or not is_within(Path(sys.base_prefix).resolve(), managed_python):
        raise RuntimeError("interpreter prefix escaped the external venv/managed-Python roots")
    config = (venv / "pyvenv.cfg").read_bytes()
    if b"include-system-site-packages = false" not in config.lower():
        raise RuntimeError("isolated venv does not reject system site packages")
    if site.ENABLE_USER_SITE:
        raise RuntimeError("user site is enabled")
    entries: list[dict[str, object]] = []
    for raw in sys.path:
        resolved = Path(raw or os.getcwd()).resolve()
        parts = set(resolved.parts)
        if {"site-packages", "dist-packages"} & parts and not is_within(resolved, venv):
            raise RuntimeError(f"user/system site fallback on sys.path: {resolved}")
        entries.append({"raw": raw, "resolved": str(resolved)})
    return {
        "entries": entries,
        "sha256": sha(canonical_json(entries)),
        "user_site": site.getusersitepackages(),
        "enable_user_site": site.ENABLE_USER_SITE,
        "pyvenv_cfg_sha256": sha(config),
    }


def environment_contract(
    repo: Path,
    runner_root: Path,
    wheel: Path,
    uv: Path,
) -> dict[str, object]:
    uv_path = uv.resolve(strict=True)
    if not uv.is_absolute() or uv != uv_path or uv.is_symlink() or not os.access(uv, os.X_OK):
        raise RuntimeError("uv must be a canonical absolute non-symlink executable")
    uv_version = subprocess.run(
        [str(uv), "--version"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=expected_initial_environment(repo, runner_root),
    ).stdout.decode().strip()
    required_modules = (
        "pytest",
        "_pytest",
        "pluggy",
        "pydantic",
        "consiliency_contract",
        "PIL",
        "phase_loop_runtime",
    )
    for name in required_modules:
        importlib.import_module(name)
    source = git_source_record(repo, runner_root / "source")
    build_source = git_source_record(repo, runner_root / "build")
    if source != build_source:
        raise RuntimeError("wheel build source drifted from the external Git-archive source")
    distributions = distribution_inventory(runner_root)
    return {
        "uv": {
            "path": str(uv),
            "sha256": sha(uv.read_bytes()),
            "version": uv_version,
        },
        "python": {
            "executable": sys.executable,
            "executable_realpath": str(Path(sys.executable).resolve(strict=True)),
            "executable_sha256": sha(Path(sys.executable).resolve(strict=True).read_bytes()),
            "version": sys.version,
            "version_info": list(sys.version_info),
            "implementation": platform.python_implementation(),
            "cache_tag": sys.implementation.cache_tag,
            "prefix": sys.prefix,
            "base_prefix": sys.base_prefix,
        },
        "sys_path": sys_path_record(repo, runner_root),
        "source": source,
        "build_source": build_source,
        "wheel": wheel_record(wheel, runner_root),
        "distributions": distributions,
        "distributions_sha256": sha(canonical_json(distributions)),
        "modules": [module_record(name, repo) for name in required_modules],
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


def application_plugin_profile(repo: Path, runner_root: Path) -> dict[str, object]:
    post_environment = environment_snapshot()
    if post_environment != expected_post_pytest_environment(repo, runner_root):
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
    for group, expected in EXPECTED_ENTRY_POINTS.items():
        records = entry_points[group]
        if len(records) != 1:
            raise RuntimeError(f"expected one local-wheel entry point for {group}: {records!r}")
        record = records[0]
        actual = (record["name"], record["value"])
        if actual != expected or str(record["distribution"]).lower() != "phase-loop-runtime":
            raise RuntimeError(f"application entry-point drift for {group}: {record!r}")
        dist_path = Path(str(record["distribution_path"])).resolve()
        if not is_within(dist_path, (runner_root / "venv").resolve()):
            raise RuntimeError(f"application entry point escaped isolated venv: {record!r}")

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
    def __init__(
        self,
        repo: Path,
        runner_root: Path,
        initial_environment: dict[str, str],
    ) -> None:
        self.repo = repo
        self.runner_root = runner_root
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
        self.application_plugins = application_plugin_profile(self.repo, self.runner_root)

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
        if post_environment != expected_post_pytest_environment(self.repo, self.runner_root):
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


def write_new(path: Path, data: bytes, mode: int = 0o600) -> None:
    if not path.is_absolute() or path.parent != path.parent.resolve(strict=True):
        raise RuntimeError(f"output parent must be canonical and absolute: {path}")
    if path.exists() or path.is_symlink():
        raise RuntimeError(f"output must be new and non-symlinked: {path}")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def exact_absolute(raw: str, label: str, *, exists: bool = True) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        raise RuntimeError(f"{label} must be absolute")
    resolved = path.resolve(strict=exists)
    if path != resolved:
        raise RuntimeError(f"{label} must be canonical and non-symlinked")
    return path


def common_inputs(args) -> tuple[Path, Path, Path, Path, Path, Path, bytes, dict[str, str]]:
    repo = exact_absolute(args.repo, "--repo")
    if Path(git(repo, "rev-parse", "--show-toplevel").decode().strip()).resolve() != repo:
        raise RuntimeError("--repo is not the exact git toplevel")
    runner_root = exact_absolute(args.runner_root, "--runner-root")
    validate_runner_root(repo, runner_root)
    plan = exact_absolute(args.plan, "--plan")
    roadmap = exact_absolute(args.roadmap, "--roadmap")
    wheel = exact_absolute(args.wheel, "--wheel")
    uv = exact_absolute(args.uv, "--uv")
    for path, label in ((plan, "plan"), (roadmap, "roadmap")):
        if not is_within(path, repo):
            raise RuntimeError(f"{label} escaped repository")
    observer_path = exact_absolute(str(Path(__file__)), "observer source")
    expected_observer = runner_root / "materialized" / "reviewtruth-baseline-observer.py"
    if observer_path != expected_observer:
        raise RuntimeError("observer source is not at the exact external materialization path")
    observer_bytes = observer_path.read_bytes()
    if sha(observer_bytes) != args.observer_sha256:
        raise RuntimeError("observer source digest mismatch")
    initial_environment = environment_snapshot()
    expected_environment = expected_initial_environment(repo, runner_root)
    if initial_environment != expected_environment:
        raise RuntimeError(
            f"initial environment is not the exact controlled allowlist: {initial_environment!r}"
        )
    home = runner_root / "home"
    if any(home.iterdir()):
        raise RuntimeError("controlled external HOME must exist and be empty")
    executable = Path(sys.executable)
    if executable != runner_root / "venv" / "bin" / "python":
        raise RuntimeError("observer did not run through the exact isolated interpreter path")
    if not is_within(executable.resolve(strict=True), runner_root / "python"):
        raise RuntimeError("isolated interpreter target escaped uv-managed Python root")
    return repo, runner_root, plan, roadmap, wheel, uv, observer_bytes, initial_environment


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--roadmap", required=True)
    parser.add_argument("--runner-root", required=True)
    parser.add_argument("--wheel", required=True)
    parser.add_argument("--uv", required=True)
    parser.add_argument("--mode", choices=("provision", "observe"), required=True)
    parser.add_argument("--provisioning")
    parser.add_argument("--out", required=True)
    parser.add_argument("--observer-sha256", required=True)
    args = parser.parse_args()

    (
        repo,
        runner_root,
        plan,
        roadmap,
        wheel,
        uv,
        observer_bytes,
        initial_environment,
    ) = common_inputs(args)
    observer_path = Path(__file__)
    final = exact_absolute(args.out, "--out", exists=False)
    evidence_root = runner_root / "evidence"
    expected_output = (
        evidence_root / "reviewtruth-bootstrap-provisioning.json"
        if args.mode == "provision"
        else evidence_root / "reviewtruth-baseline-preimplementation"
    )
    if final != expected_output or final.exists() or final.is_symlink():
        raise RuntimeError("output must be the exact new write-once path for the selected mode")

    before = snapshot(repo)
    if not before["clean"]:
        raise RuntimeError("bootstrap requires an unfiltered all-untracked clean tree")
    contract = environment_contract(repo, runner_root, wheel, uv)
    if environment_snapshot() != initial_environment:
        raise RuntimeError("provenance freeze mutated the strict initial environment")

    if args.mode == "provision":
        if args.provisioning is not None:
            raise RuntimeError("provision mode does not accept --provisioning")
        after = snapshot(repo)
        if before != after or not after["clean"]:
            raise RuntimeError("HEAD/tree/index/clean status changed during provisioning freeze")
        if any((runner_root / "home").iterdir()):
            raise RuntimeError("controlled external HOME changed during provisioning freeze")
        payload = {
            "schema": PROVISION_SCHEMA,
            "observer": {"path": str(observer_path), "sha256": sha(observer_bytes)},
            "plan": {"path": str(plan), "sha256": sha(plan.read_bytes())},
            "roadmap": {"path": str(roadmap), "sha256": sha(roadmap.read_bytes())},
            "runner_root": str(runner_root),
            "git_before": before,
            "git_after": after,
            "process": process_identity(),
            "initial_environment": initial_environment,
            "environment_contract": contract,
        }
        write_new(final, canonical_json(payload))
        return 0

    if args.provisioning is None:
        raise RuntimeError("observe mode requires --provisioning")
    provisioning_path = exact_absolute(args.provisioning, "--provisioning")
    expected_provisioning = evidence_root / "reviewtruth-bootstrap-provisioning.json"
    if provisioning_path != expected_provisioning:
        raise RuntimeError("provisioning path must be the exact external write-once record")
    provisioning_bytes = provisioning_path.read_bytes()
    provisioning = json.loads(provisioning_bytes)
    if provisioning.get("schema") != PROVISION_SCHEMA:
        raise RuntimeError("provisioning schema mismatch")
    if provisioning.get("environment_contract") != contract:
        raise RuntimeError("isolated environment drifted after provisioning freeze")
    if provisioning.get("observer", {}).get("sha256") != sha(observer_bytes):
        raise RuntimeError("provisioning observer digest mismatch")
    if provisioning.get("plan", {}).get("sha256") != sha(plan.read_bytes()):
        raise RuntimeError("plan changed after provisioning freeze")
    if provisioning.get("roadmap", {}).get("sha256") != sha(roadmap.read_bytes()):
        raise RuntimeError("roadmap changed after provisioning freeze")

    observation_id = str(uuid.uuid4())
    temporary = final.with_name(final.name + ".tmp-" + observation_id)
    temporary.mkdir(mode=0o700, parents=False, exist_ok=False)
    require_private_dir(temporary, exact_mode=0o700)
    pytest_argv = [
        "phase-loop-runtime/tests",
        "-q",
        "-m",
        "not dotfiles_integration",
        "-p",
        "no:cacheprovider",
        f"--junitxml={temporary / 'broad.xml'}",
    ]
    observer = Observer(repo, runner_root, initial_environment)
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = int(pytest.main(pytest_argv, plugins=[observer]))
    stdout_bytes = stdout.getvalue().encode()
    stderr_bytes = stderr.getvalue().encode()
    write_new(temporary / "stdout.txt", stdout_bytes)
    write_new(temporary / "stderr.txt", stderr_bytes)

    events = observer.payload(pytest_argv, exit_code)
    write_new(temporary / "plugin-events.json", canonical_json(events))
    for name, values in (
        ("full-nodeids.txt", events["full_nodeids"]),
        ("selected-nodeids.txt", events["selected_nodeids"]),
        ("marker-deselected-nodeids.txt", events["marker_deselected_nodeids"]),
    ):
        write_new(temporary / name, ("".join(f"{value}\n" for value in values)).encode())
    write_new(temporary / "legitimate-skips.json", canonical_json(events["legitimate_skips"]))

    after = snapshot(repo)
    if exit_code != 0:
        raise RuntimeError(f"broad baseline exited {exit_code}")
    if before != after or not after["clean"]:
        raise RuntimeError("HEAD/tree/index/clean status changed during observation")
    if events["process"] != process_identity():
        raise RuntimeError("collection and attestation process identity differ")
    if any((runner_root / "home").iterdir()):
        raise RuntimeError("controlled external HOME changed during observation")

    artifacts = {}
    for path in sorted(temporary.iterdir()):
        if path.is_file():
            data = path.read_bytes()
            artifacts[path.name] = {"sha256": sha(data), "bytes": len(data)}
    command_argv = list(sys.argv)
    attestation = {
        "schema": SCHEMA,
        "observation_id": observation_id,
        "runner_root": str(runner_root),
        "observer": {"path": str(observer_path), "sha256": sha(observer_bytes)},
        "provisioning": {
            "path": str(provisioning_path),
            "sha256": sha(provisioning_bytes),
        },
        "command_argv": command_argv,
        "command_argv_sha256": sha(canonical_json(command_argv)),
        "git_before": before,
        "git_after": after,
        "plan": {"path": str(plan), "sha256": sha(plan.read_bytes())},
        "roadmap": {"path": str(roadmap), "sha256": sha(roadmap.read_bytes())},
        "process": process_identity(),
        "environment": {
            "initial_allowlist": events["environment_before_pytest"],
            "post_pytest": events["environment_after_pytest"],
            "runtime_selectors": events["application_plugins"]["selectors"],
        },
        "application_plugins": events["application_plugins"],
        "environment_contract": contract,
        "sys_path_after_pytest": sys_path_record(repo, runner_root),
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
    write_new(temporary / "attestation.json", canonical_json(attestation))
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
- evidence paths: `plans/phase-plan-v10-REVIEWTRUTH.md`, `phase-loop-runtime/uv.lock`, `docs/research/reviewtruth-leg-capability-ratification.md`, `docs/research/reviewtruth-red-baseline.md`, `docs/research/reviewtruth-phase-verification.md`, `docs/research/reviewtruth-real-panel-smoke.md`, `docs/research/reviewtruth-final-evidence-record.md`, `phase-loop-runtime/tests/conftest.py`, `phase-loop-runtime/tests/test_reviewtruth_phase.py`, `phase-loop-runtime/tests/test_train_merge.py`, `phase-loop-runtime/tests/test_governed_cross_vendor_floor_358.py`, `phase-loop-runtime/tests/test_advisor_board_golden.py`, `phase-loop-runtime/tests/test_advisor_board_research.py`, `phase-loop-runtime/tests/test_panel_invoker_spawn.py`, `phase-loop-runtime/tests/test_panel_native_fill_183.py`
- redaction posture: `metadata_only`
- downstream handling: `none`; the plan/lock/manifest prerequisite is committed before the lane DAG and closeout may verify but never claim or rewrite the lock, while REVIEWTRUTH closeout follows `REVIEWTRUTH-redacted-transcript-policy` and carries only the exact canonical transcript/smoke path `docs/research/reviewtruth-real-panel-smoke.md` and its single frozen digest, seat metadata, and artifact-specific citations

## Verification

SL-1 executes these command bullets from top to bottom in exact order. Before the first command, the exact `phase-loop-runtime/uv.lock` planning prerequisite and this plan must already be committed on canonical `main`; the lock must retain SHA-256 `b89987030b895131c3de05a316783ac0bcb6423d5531d6e9a04ee4a8f1e9fcce` and be visible in the exact `HEAD` tree/archive. The coordinator supplies an unset/nonexistent canonical absolute `REVIEWTRUTH_RUNNER_ROOT` whose existing parent is privately owned and not group/world-writable, plus canonical absolute `REVIEWTRUTH_UV`. The first command creates and provisions the external trust root from that exact lock-bearing archive without touching the worktree. The second materializes the exact reviewed observer payload without overwriting an existing path. The third uses the isolated environment's exact interpreter to freeze provisioning and its source/lock digests. The fourth runs the single-process observation on the untouched clean base before any SL-1 edit, when the wrappers and tracked parser do not exist. The fifth runs only after `verify_reviewtruth_chronology.py` and its independent bootstrap/parser tests have been authored and consumes the explicit absolute write-once records. These five bullets are executable operational evidence commands deliberately marked `evidence: operational`: plan intake records them but never auto-executes them against a later tree. All remaining bullets are ordinary non-operational verifier commands, and every parser runs only after all named inputs exist:

- `env -i REVIEWTRUTH_RUNNER_ROOT="$REVIEWTRUTH_RUNNER_ROOT" REVIEWTRUTH_UV="$REVIEWTRUTH_UV" PATH=/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 /bin/bash -euo pipefail -c 'repo=$(git rev-parse --show-toplevel); root=$REVIEWTRUTH_RUNNER_ROOT; uv=$REVIEWTRUTH_UV; case "$root" in /*) ;; *) exit 71;; esac; case "$uv" in /*) ;; *) exit 72;; esac; test "$repo" = "$(realpath -e -- "$repo")"; test "$uv" = "$(realpath -e -- "$uv")"; test -x "$uv"; test ! -L "$uv"; parent=${root%/*}; test -n "$parent"; test "$parent" = "$(realpath -e -- "$parent")"; test "$(stat -c %u -- "$parent")" = "$(id -u)"; test $((8#$(stat -c %a -- "$parent") & 8#22)) -eq 0; case "$root/" in "$repo/"*) exit 73;; esac; case "$repo/" in "$root/"*) exit 74;; esac; test ! -e "$root"; test ! -L "$root"; test -z "$(git -C "$repo" status --porcelain=v1 --untracked-files=all)"; before_head=$(git -C "$repo" rev-parse HEAD); before_tree=$(git -C "$repo" rev-parse "HEAD^{tree}"); before_index=$(git -C "$repo" write-tree); umask 077; mkdir -m 700 -- "$root"; mkdir -m 700 -- "$root"/{build,evidence,home,materialized,python,source,tmp,uv-cache,venv,wheels}; export HOME="$root/home" TMPDIR="$root/tmp" UV_CACHE_DIR="$root/uv-cache" UV_PYTHON_INSTALL_DIR="$root/python"; git -C "$repo" archive --format=tar HEAD:phase-loop-runtime | tar -xf - -C "$root/source"; cp -a -- "$root/source/." "$root/build/"; "$uv" venv --no-project --managed-python --python 3.12 --link-mode copy "$root/venv"; "$uv" build --wheel --no-create-gitignore --cache-dir "$root/uv-cache" --out-dir "$root/wheels" "$root/build"; wheels=("$root"/wheels/*.whl); test "${#wheels[@]}" -eq 1; test "${wheels[0]}" = "$root/wheels/phase_loop_runtime-0.7.13-py3-none-any.whl"; UV_PROJECT_ENVIRONMENT="$root/venv" "$uv" sync --frozen --extra visual --no-install-project --project "$root/source" --cache-dir "$root/uv-cache" --link-mode copy; "$uv" pip install --python "$root/venv/bin/python" --strict --link-mode copy --no-deps "${wheels[0]}"; "$uv" pip install --python "$root/venv/bin/python" --strict --link-mode copy pytest; "$uv" pip check --python "$root/venv/bin/python"; find "$root"/{build,evidence,home,materialized,source,tmp,wheels} -type d -exec chmod 700 {} +; find "$root"/{build,evidence,home,materialized,source,tmp,wheels} -type f -exec chmod 600 {} +; test -z "$(find "$root"/{build,evidence,home,materialized,source,tmp,wheels} ! -user "$(id -u)" -print -quit)"; test -z "$(find "$root"/{build,evidence,home,materialized,source,tmp,wheels} -perm /077 -print -quit)"; for name in build evidence home materialized python source tmp uv-cache venv wheels; do path="$root/$name"; test "$path" = "$(realpath -e -- "$path")"; test ! -L "$path"; test "$(stat -c %u -- "$path")" = "$(id -u)"; test $((8#$(stat -c %a -- "$path") & 8#77)) -eq 0; done; test -z "$(find "$root/source" "$root/build" "$root/evidence" "$root/home" "$root/materialized" "$root/tmp" "$root/wheels" -type l -print -quit)"; python_real=$(realpath -e -- "$root/venv/bin/python"); case "$python_real/" in "$root/python/"*) ;; *) exit 75;; esac; test "$before_head" = "$(git -C "$repo" rev-parse HEAD)"; test "$before_tree" = "$(git -C "$repo" rev-parse "HEAD^{tree}")"; test "$before_index" = "$(git -C "$repo" write-tree)"; test -z "$(git -C "$repo" status --porcelain=v1 --untracked-files=all)"'` evidence: operational
- `env -i REVIEWTRUTH_RUNNER_ROOT="$REVIEWTRUTH_RUNNER_ROOT" PATH=/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 /bin/bash -euo pipefail -c 'repo=$(git rev-parse --show-toplevel); root=$(realpath -e -- "$REVIEWTRUTH_RUNNER_ROOT"); test "$root" = "$REVIEWTRUTH_RUNNER_ROOT"; test "$(stat -c %u -- "$root")" = "$(id -u)"; test "$(stat -c %a -- "$root")" = 700; observer="$root/materialized/reviewtruth-baseline-observer.py"; temporary="$observer.tmp"; test ! -e "$observer"; test ! -L "$observer"; test ! -e "$temporary"; before_head=$(git -C "$repo" rev-parse HEAD); before_tree=$(git -C "$repo" rev-parse "HEAD^{tree}"); before_index=$(git -C "$repo" write-tree); test -z "$(git -C "$repo" status --porcelain=v1 --untracked-files=all)"; awk '\''BEGIN { fence=sprintf("%c%c%c",96,96,96) } /^<!-- REVIEWTRUTH_BASELINE_OBSERVER_BEGIN -->$/ { begin=1; next } begin == 1 { if ($0 != fence "python") exit 81; begin=2; next } begin == 2 && $0 == fence { done=1; exit } begin == 2 { print } END { if (begin != 2 || done != 1) exit 82 }'\'' "$repo/plans/phase-plan-v10-REVIEWTRUTH.md" >"$temporary"; test "$(sha256sum "$temporary" | cut -d" " -f1)" = 841cfb8bbac1d9b4ea0bb14a1f3600165550227b680b2e5689c79c13c61b1f6d; chmod 700 "$temporary"; mv -T -- "$temporary" "$observer"; test "$observer" = "$(realpath -e -- "$observer")"; test ! -L "$observer"; test "$(stat -c %u -- "$observer")" = "$(id -u)"; test "$(stat -c %a -- "$observer")" = 700; test "$before_head" = "$(git -C "$repo" rev-parse HEAD)"; test "$before_tree" = "$(git -C "$repo" rev-parse "HEAD^{tree}")"; test "$before_index" = "$(git -C "$repo" write-tree)"; test -z "$(git -C "$repo" status --porcelain=v1 --untracked-files=all)"'` evidence: operational
- `env -i HOME="$REVIEWTRUTH_RUNNER_ROOT/home" PATH="$REVIEWTRUTH_RUNNER_ROOT/venv/bin:/usr/bin:/bin" LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH="$PWD/phase-loop-runtime/src" TMPDIR="$REVIEWTRUTH_RUNNER_ROOT/tmp" "$REVIEWTRUTH_RUNNER_ROOT/venv/bin/python" "$REVIEWTRUTH_RUNNER_ROOT/materialized/reviewtruth-baseline-observer.py" --mode provision --repo "$PWD" --plan "$PWD/plans/phase-plan-v10-REVIEWTRUTH.md" --roadmap "$PWD/specs/phase-plans-v10.md" --runner-root "$REVIEWTRUTH_RUNNER_ROOT" --wheel "$REVIEWTRUTH_RUNNER_ROOT/wheels/phase_loop_runtime-0.7.13-py3-none-any.whl" --uv "$REVIEWTRUTH_UV" --out "$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-bootstrap-provisioning.json" --observer-sha256 841cfb8bbac1d9b4ea0bb14a1f3600165550227b680b2e5689c79c13c61b1f6d` evidence: operational
- `env -i HOME="$REVIEWTRUTH_RUNNER_ROOT/home" PATH="$REVIEWTRUTH_RUNNER_ROOT/venv/bin:/usr/bin:/bin" LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH="$PWD/phase-loop-runtime/src" TMPDIR="$REVIEWTRUTH_RUNNER_ROOT/tmp" "$REVIEWTRUTH_RUNNER_ROOT/venv/bin/python" "$REVIEWTRUTH_RUNNER_ROOT/materialized/reviewtruth-baseline-observer.py" --mode observe --repo "$PWD" --plan "$PWD/plans/phase-plan-v10-REVIEWTRUTH.md" --roadmap "$PWD/specs/phase-plans-v10.md" --runner-root "$REVIEWTRUTH_RUNNER_ROOT" --wheel "$REVIEWTRUTH_RUNNER_ROOT/wheels/phase_loop_runtime-0.7.13-py3-none-any.whl" --uv "$REVIEWTRUTH_UV" --provisioning "$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-bootstrap-provisioning.json" --out "$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-baseline-preimplementation" --observer-sha256 841cfb8bbac1d9b4ea0bb14a1f3600165550227b680b2e5689c79c13c61b1f6d` evidence: operational
- `env -i HOME="$REVIEWTRUTH_RUNNER_ROOT/home" PATH="$REVIEWTRUTH_RUNNER_ROOT/venv/bin:/usr/bin:/bin" LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH="$PWD/phase-loop-runtime/src" TMPDIR="$REVIEWTRUTH_RUNNER_ROOT/tmp" "$REVIEWTRUTH_RUNNER_ROOT/venv/bin/python" "$PWD/phase-loop-runtime/scripts/verify_reviewtruth_chronology.py" junit --mode broad-baseline --runner-root "$REVIEWTRUTH_RUNNER_ROOT" --provisioning "$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-bootstrap-provisioning.json" --observation-dir "$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-baseline-preimplementation" --observer-source "$REVIEWTRUTH_RUNNER_ROOT/materialized/reviewtruth-baseline-observer.py" --observer-sha256 841cfb8bbac1d9b4ea0bb14a1f3600165550227b680b2e5689c79c13c61b1f6d` evidence: operational
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

The broad and plain suite commands leave `PHASE_LOOP_REVIEWTRUTH_POST_PARSER_COLLECTION` unset and require the canonical full/selected collections and normalized behavioral collection-plugin origin profile to equal the frozen post-SL-1 source/CI profile, plus total deselections equal to the immutable marker-filter baseline UNION exactly the hook's five wrappers, with the marker and hook categories attested separately from each other and from skips. The profile preserves exact application-plugin entry points and repo-owned origins and forbids ambient or unapproved plugin origins, but excludes pytest/pluggy interpreter identity, distribution versions, absolute module/distribution paths, and module/file digests from equality while still requiring them as complete self-consistent diagnostics. The candidate parser rejects full/selected-set or behavioral plugin-origin drift, marker drift, a missing/extra hook wrapper, any external `--deselect`, arbitrary/category-swapped deselection, skip/deselection substitution, missing provenance, or a toolchain that changes collection/exit/JUnit/result behavior; interpreter/version/path/digest-only tool provenance drift is accepted. Only after all five commands and required GitHub CI across Python 3.10/3.11/3.12 are GREEN at the same exact pushed head may the exact-head four-seat implementation panel launch and the merge decision occur.

After the distinct implementation landing is on canonical `main` and SL-6 has written only its owned pre-final evidence/docs, SL-6 executes these command bullets from top to bottom in exact order from its different fresh process. The broad-final parser must be GREEN before the phase-final runner starts; the final parser must be GREEN before the record is finalized; the finalized record must exist before its verifier runs; and the `final-record` attestation must be GREEN before the golden/default-suite/Gate-A/static checks and the record-bound closeout start:

- `env REVIEWTRUTH_JUNIT_XML=.phase-loop/evidence/reviewtruth-broad-final.xml sh -c 'PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration" --junitxml="$REVIEWTRUTH_JUNIT_XML"'`
- `env REVIEWTRUTH_JUNIT_XML=.phase-loop/evidence/reviewtruth-broad-final.xml sh -c 'PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit --mode broad-final-producer --xml "$REVIEWTRUTH_JUNIT_XML"'`
- `env REVIEWTRUTH_JUNIT_XML=.phase-loop/evidence/reviewtruth-phase-final.xml sh -c 'PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit-run --mode final --xml "$REVIEWTRUTH_JUNIT_XML"'`
- `env REVIEWTRUTH_PHASE_JUNIT_XML=.phase-loop/evidence/reviewtruth-phase-final.xml REVIEWTRUTH_BROAD_JUNIT_XML=.phase-loop/evidence/reviewtruth-broad-final.xml sh -c 'PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit --mode final --phase-xml "$REVIEWTRUTH_PHASE_JUNIT_XML" --broad-xml "$REVIEWTRUTH_BROAD_JUNIT_XML"'`
- `PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_evidence.py finalize-record --phase-xml .phase-loop/evidence/reviewtruth-phase-final.xml --broad-xml .phase-loop/evidence/reviewtruth-broad-final.xml --record docs/research/reviewtruth-final-evidence-record.md` (literal paths only; assigns and expands no shell variable)
- `PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_evidence.py final-record --record docs/research/reviewtruth-final-evidence-record.md --attestation .phase-loop/evidence/reviewtruth-final-record-attestation.json` (literal paths only; assigns and expands no shell variable)
- `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_advisor_board_golden.py -q`
- `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration"`
- `env -u PHASE_LOOP_SKIP_GATE_A_SUITE -u PHASE_LOOP_REVIEWTRUTH_POST_PARSER_COLLECTION REVIEWTRUTH_RUNNER_ROOT="$REVIEWTRUTH_RUNNER_ROOT" PHASE_LOOP_GATE_A_INPUT_COPY_ROOT="$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-inputs" sh -c 'PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_evidence.py gate-a --runner-root "$REVIEWTRUTH_RUNNER_ROOT" --script phase-loop-runtime/scripts/gate_a_cleanroom.sh --input-copy "$PHASE_LOOP_GATE_A_INPUT_COPY_ROOT" --stdout "$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite.stdout" --stderr "$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite.stderr" --artifact "$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite.json" --attestation "$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite-attestation.json"'`
- `ruff check phase-loop-runtime/src/phase_loop_runtime/`
- `phase-loop validate-roadmap specs/phase-plans-v10.md`
- `git diff --check`

Candidate phase-selected JUnit uses the frozen non-wrapper phase set and requires zero phase skips; final phase-selected JUnit uses the full expected set, runs every strict wrapper exactly once after broad-final attestation, and requires zero phase skips or deselections. Candidate and final broad JUnit require exact equality to the frozen source/CI post-SL-1 full/selected collections, the allowed source/CI behavioral collection-plugin/root profile, exactly the unchanged marker-filter deselection baseline plus exactly the five hook-owned wrappers as disjoint categories, and exactly the unchanged source/CI legitimate pre-implementation skip baseline after validating and separating the one PC-REVIEWTRUTH-5A portable disposition; they reject new, missing, external, arbitrary, category-swapped, plugin-origin-drifted, collection-drifted, or otherwise changed skip/deselection accounting and do not require or claim five total deselections or whole-suite zero skips. The frontmatter suite command and explicitly amended GitHub CI also use that normalized source/CI profile and must collect the portable node exactly once on Python 3.10, 3.11, and 3.12. The sole normative clean-room Gate A command explicitly unsets both `PHASE_LOOP_SKIP_GATE_A_SUITE` and final collection activation, supplies the fresh external `PHASE_LOOP_GATE_A_INPUT_COPY_ROOT`, and requires the reducer to reject either selector when invoked without that sanitization. The reducer runs the SL-5-owned script under trace and emits write-once stdout/stderr, machine-checkable suite-count/profile/sentinel JSON, and a fresh-child attestation. Gate A is GREEN only when the script's temporary cleanup is complete, the neutral sealed evidence copy still exists, and that fresh process independently proves the full temporary standalone pytest tree actually executed once under exact `-q -p no:cacheprovider -m "not dotfiles_integration"` and equals the separately frozen Gate-A profile: `input-copy/tests/**` and `input-copy/tests/conftest.py` match the executed and committed tests, `input-copy/chronology-parser/verify_reviewtruth_chronology.py` matches HEAD, neither the temporary tree nor the external copy contains `phase-loop-runtime/scripts/`, sibling `phase-loop-skills/` and `skills-src/` are absent, full/selected sets equal the source/CI sets minus exactly the 48 unmarked nodeids from the four named collection-skipped modules, collection skips equal the restricted source collection baseline UNION the exact four boundary tuples, runtime skips equal the restricted source runtime baseline UNION all 59 boundary tuples, their disjoint union equals the frozen 102-tuple expected set, marker filtering and the five hook deselections remain exact and disjoint over the retained collection, at least one test executed, the terminal outcome has no failures/errors, and the SKIPPED sentinel is absent after the ordered start sentinel and before the GREEN sentinel. Missing/extra boundary skips, source/CI-profile substitution, unrelated nodeid loss, copied-byte or retained-behavior drift, parser omission/misnamespace, cleanup before attestation, producer-hash substitution, or unexpected sibling presence fails. Every environment still emits pytest/pluggy interpreter, distribution version, module/distribution path, module/file digest, and approved core-plugin provenance for complete self-consistent diagnostics, but the reducers ignore raw differences in those fields unless they coincide with an applicable semantic-profile or behavior mismatch. All suites remain GREEN without bootstrap run-local evidence on fresh clones. The post-parser finalized record, its `final-record` attestation, and the later Gate A artifacts are never consumed by any test wrapper; the finalized record deliberately excludes Gate A, and the four-seat closeout review plus canonical ledger closeout bind the finalized-record attestation and terminal Gate A attestation without creating a cycle.

## Acceptance Criteria

The normative EC-REVIEWTRUTH-0 and EC-REVIEWTRUTH-9 commands run only at SL6-T3 after SL6-T2 has frozen every wrapper input. Each command explicitly clears inherited final collection, generates and parses broad-final first, delegates final activation only to immutable `junit-run --mode final`, and then parses phase-final; neither a plain pytest selector, hand-set activation, nor wrapper-before-attestation can satisfy either criterion.

Every criterion below also inherits two non-substitutable Gate A prerequisites. Before SL-6, GitHub CI at the exact pushed SL-5 implementation head must invoke the co-landed SL-5-owned `phase-loop-runtime/scripts/verify_reviewtruth_evidence.py gate-a`/`gate-a-attest` lifecycle and finish GREEN before golden, panel, or merge. At SL6-T3, the sole normative Gate A invocation must write and independently attest only `$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite.stdout`, `$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite.stderr`, `$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite.json`, and `$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite-attestation.json`; a missing path, different path, repo-local Gate A suite alias, selector inheritance, pre-attestation cleanup, or executable/workflow digest mismatch fails acceptance. Neither prerequisite may be deferred to an SL-6 implementation edit.

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
