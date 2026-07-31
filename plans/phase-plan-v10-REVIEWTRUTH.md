---
phase_loop_plan_version: 1
phase: REVIEWTRUTH
roadmap: specs/phase-plans-v10.md
roadmap_sha256: b26b4fd76efb7882578eae5e102fd577b26e66f590a531d3b3a738d840e5106e
automation:
  suite_command: 'PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration"'
---

# REVIEWTRUTH: Board Reports Its Own Degradation

## Context

REVIEWTRUTH is explicitly selected for this run. Canonical `.phase-loop/state.json` and `.phase-loop/tui-handoff.md` now agree that REVIEWTRUTH is the current `planned` phase, and the newest canonical ledger event records the GPT-5.6 Sol planning run at maximum effort. This repair edits only this plan and the REVIEWTRUTH row in `plans/manifest.json`; `specs/phase-plans-v10.md`, every other phase plan and manifest row, the tracked lock, and every unrelated coordinator-owned digest remain untouched. Legacy `.codex/phase-loop/` state is compatibility-only and is not authoritative.

The phase replaces the board's text-derived usability shortcut with a typed per-seat outcome, distinguishes FULL, FLOOR-ONLY, and BELOW-FLOOR delivery, makes lens and artifact grounding load-bearing, attests and persists the bounded Fable binding-prover capability from preflight through policy facts, wires native Fable fill requests back into board results, persists per-seat and aggregate governed outcomes, fails closed on empty or elided material or a missing effectively-required prover, connects the production repair round, and adds the separately bounded early-prover evidence path required by maintainer comment `5139955591`. It does not implement LEGLIFE timeout enforcement or custom per-repo seats; it only freezes and consumes the `timed_out` outcome that LEGLIFE later produces. It never grants live-tree/shared-data authority, never equates early Codex/Grok `can_probe` with Fable `binding_prover`, and never alters `PANEL_LEGS` or non-review goldens.

The roadmap names four implementation lanes. This plan maps them to SL-2 through SL-5 and adds three control lanes: SL-0 binds all three `agent-harness#398` maintainer directives into a separately merged durable posture record and proves the remaining target-rule and merge-topology conditions before any posture-assuming change; SL-1 lands the literal PANELLED RED tests-only boundary, both chronology modes, every immutable REVIEWTRUTH evidence wrapper, the frozen ordinary-suite collection hook in `phase-loop-runtime/tests/conftest.py`, the complete live floor-2 assertion migration in `test_governed_cross_vendor_floor_358.py` and `test_train_merge.py`, the normative sanctioned-delta amendment in `test_advisor_board_golden.py`, all five known compatibility migrations, and the exact sixteen-node early-prover contract split across `test_reviewtruth_phase.py` and `test_phase_worktree_executor.py`; SL-2 is the single writer for `panel_invoker.py`, `launcher.py`, `advisor_board/schema.py`, `advisor_board/composition.py`, `fab_gate.py`, and `phase_worktree_executor.py`, including capability/sandbox fields, additive wave staging, fail-closed external-tool and explicit workspace-mount preflight/receipts, worktree/data isolation, coordinator reaping, and strict seat-outcome/native-fill seams; SL-4 owns both `ratification_policy.py` and `gate_posture.py`; SL-5 ends at an explicit SL-2-through-SL-5 implementation PR/landing boundary and owns the production gate consumers, the required `gate_a_cleanroom.sh` neutral persistent-evidence-copy implementation, and the explicit `.github/workflows/test.yml` lifecycle; and SL-6 starts from the resulting canonical-main tip to reduce final chronology, live, source-ownership, structured JUnit, and verification evidence. All eleven SL-1 paths are immutable after the tests-only landing. SL-5 consumes SL-2's frozen early-prover/binding/lossless seat-outcome APIs and SL-3/SL-4's grounded classifier, and makes no test edits, so no lane overlaps those files.

Within that mapping, `phase-loop-runtime/scripts/verify_reviewtruth_evidence.py` is exclusively SL-5-owned and lands atomically with `gate_a_cleanroom.sh` and `.github/workflows/test.yml`; SL-6 consumes the immutable executable and cannot author, stage, or repair it.

Read-only GitHub metadata rechecked on 2026-07-31 establishes that the human decision requested by `agent-harness#398` is now satisfied by maintainer comment `5139465317` at `https://github.com/Consiliency/agent-harness/issues/398#issuecomment-5139465317`. The exact UTF-8 body is `2479` bytes at SHA-256 `a2dc69639b89743ba351bebf4cd46e81ef8d97901bc5545c00f4777f737238a7`; author `ViperJuice` has repository permission `admin` and author association `MEMBER`; and `.created_at` and `.updated_at` are both `2026-07-31T05:04:41Z`. The comment expressly identifies itself as the maintainer decision rather than the coordinator recommendation and ratifies Option 2 evidence staging: codex/gemini/grok vendor review legs stay read-only over the exact by-reference bundle, the prover stages redacted digest-bound evidence, arbitrary real-tree and shared-development-database execution stays forbidden, and the byte-frozen `PANEL_LEGS` tuple and non-review goldens do not shift. At ratification time, open `agent-harness#405` reserved a separate non-authorizing follow-on pilot with database isolation as a prerequisite, Codex first, Gemini only after demonstrated value, and Grok excluded. Maintainer comment `5139955591` and the tracker update staged below supersede that pilot sequencing without changing Option 2, supplying ratification, or widening `PANEL_LEGS`.

That live human decision does not complete SL-0. The durable record has not yet been separately merged, and the effective `main` rules response remained canonical `[]` (sorted compact JSON plus terminal-LF SHA-256 `37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570`) on 2026-07-31, with no effective `pull_request` rule. SL-1 through SL-6 remain undispatched until the record-only two-parent landing is reachable from fetched canonical `main`, the effective rule exists, and SL0-T3 proves every independent condition. Merged `agent-harness#400`, blanket roadmap execution authorization, plan review, advisor verdicts, and `agent-harness#405` remain non-substitutes.

Maintainer comment `5139609713` (`IC_kwDOTFEWvM8AAAABMlg4cQ`) at `https://github.com/Consiliency/agent-harness/issues/398#issuecomment-5139609713` is a binding follow-on directive to Option 2. Its exact UTF-8 body is `2697` bytes at SHA-256 `284e37117787f653ae91cebc2c04454ddb54ef0cc6434e26dc08b0875cddccfc`; author `ViperJuice` has association `MEMBER` and repository permission/role `admin`; and `.created_at` and `.updated_at` are both `2026-07-31T05:29:20Z`. It requires execution-capability attestation, a shipped-default-true prover requirement that cannot be waived by `on_shortfall`, typed per-repo policy resolution including a valid explicit `required_prover=false` override, vendor/lens floor 3 at all four shipped default gates with existing gate actions otherwise unchanged, and immediate self-application to every not-yet-bound v10 verdict. This follow-on does not change Option 2 or authorize `agent-harness#405`: only the Fable correctness seat is currently prover-capable, codex/gemini/grok remain read-only, and arbitrary real-tree/shared-DB execution plus `PANEL_LEGS`/non-review-golden changes remain forbidden.

Maintainer comment `5139955591` at `https://github.com/Consiliency/agent-harness/issues/398#issuecomment-5139955591` is a third, separate binding directive, not an edit or paraphrase of either predecessor. Its exact UTF-8 body is the `3684` bytes staged at `.phase-loop/planning-inputs/agent-harness-398-addendum.md`, SHA-256 `e0d61155a0d3ee9898d17ac89cdf029120109f198072f25c7517be20ddad5c4c`; `.created_at` and `.updated_at` are both `2026-07-31T06:20:15Z`. It distinguishes execution roles: an early Codex leg may attest only `can_probe`; only a usable, grounded, artifact-bound Fable result attests `binding_prover` and can satisfy an effective `required_prover=true`. At plan/design gates critics-first remains allowed, but at pre-merge/release gates early prover evidence must be staged before critic dispatch and critic verdicts produced without that evidence do not count. Every later review wave includes the write-capable early prover in its initial wave; a contradicting prover finding invalidates every earlier `AGREE` and requires a fresh review of the updated evidence bundle. The current in-flight LEGIBLE and REVIEWTRUTH local critic artifacts are predecessor evidence only: early Codex evidence must be produced before Fable is asked to bind the repaired bundle.

`agent-harness#405` is an implementation tracker and updated design record, not an authorization source. Its staged text at `.phase-loop/planning-inputs/agent-harness-405.txt` is `838` bytes at SHA-256 `ccb79a23ed9978dc211f231bd4d5f9951dc2158a9902a782cf9ea8bf400c2f84`. It confirms Codex as the primary bounded early prover, Grok only after Codex preflight failure and only under real OS confinement, and Gemini as ineligible; it cannot replace any of the three exact maintainer comments or authorize a verdict.

Every older reference below to a simultaneous “mandatory four-seat panel” describes predecessor evidence only. Runtime policy still permits critics-first at plan/design gates, provided the initial wave includes an early prover and its evidence reaches Fable; pre-merge/release requires prover evidence before critics. For this candidate's Stage-B plan and change reviews, the coordinator voluntarily uses the stricter serial order: isolated early Codex evidence first, critics including GPT-5.6 Sol against the evidence-bearing exact bundle second, and a usable grounded artifact-bound Fable review last. The critic roster may still use the byte-frozen `PANEL_LEGS`; this coordinator ordering does not rewrite that tuple or hardcode runtime gate behavior.

This coordinated repair updates only the roadmap's EC-REVIEWTRUTH-17 contract from the superseded 13-node set to the exact 16-node set already required here, then reseals all six root plans' current roadmap bindings; only REVIEWTRUTH, CONFORM, and HARDEN receive semantic plan changes. Historical review and predecessor digests remain labeled as such. This branch binds the repaired producer/consumer dependency-completion contract and corrected roadmap input, and neither authorizes lane dispatch before the required Stage-B freeze and ordered review.

The CONFORM and HARDEN completion event consumed by Stage A now carries one strict nested `review_wave` object rather than independent SHA-shaped claims. `metadata.phase_completion_landing` has exactly `audited_implementation_landing`, `audited_implementation_tree`, `canonical_origin`, `canonical_ref`, `final_audit`, `final_evidence`, `phase_alias`, `plan_sha256`, `review_wave`, `roadmap_sha256`, `run_id`, and `schema`; its only review evidence is `review_wave`. `review_wave` has exactly `schema`, `canonical_json`, `receipt`, and `receipt_sha256`; `schema="v10.review-wave-receipt.v1"`; and `canonical_json="utf8-sorted-keys-compact-lf.v1"`. Canonical bytes are UTF-8 JSON with duplicate keys, floats, NaN/Infinity, and surrogate code points rejected, keys sorted bytewise, separators exactly `,` and `:`, no insignificant whitespace, and one terminal LF. `receipt_sha256` is SHA-256 of only the canonical `receipt` bytes. The wrapper, its parent event, `FH`, and `F` are excluded from those hashed bytes, so neither the event nor any receipt self-references. `final_audit` and `final_evidence` are exact file references and must equal `review_wave.receipt.base.final_audit` and `.final_evidence`.

`receipt` has exactly `attempt`, `base`, `bundle_staging`, `completed_at`, `early_prover`, `effective_policy`, `evidence_root_id`, `gate`, `phase_alias`, `restart_chain`, `seats`, and `wave_id`. Every time is fixed-width UTC RFC3339 with six fractional digits and `Z`; comparison is chronological over parsed instants, not lexical trust. `base` has exactly `commit`, `tree`, `plan_sha256`, `roadmap_sha256`, `final_audit`, and `final_evidence`; the two artifact values and every other retained file reference have exactly `path`, `bytes`, and `sha256`. A path is a normalized immutable relative locator: nonempty UTF-8, no absolute form, backslash, empty segment, `.`/`..` segment, or symlink at any ancestor. It resolves beneath the explicit coordinator-supplied canonical evidence root for the matching `evidence_root_id`; the resolved regular file must be owned by the coordinator identity, not group/other-writable, and match both integer byte count and recomputed lowercase SHA-256.

`early_prover` has exactly `artifact`, `binding_prover`, `capability`, `completed_at`, `outcome`, `receipt`, `role`, `seat`, `started_at`, `usable`, and `vendor`; those facts are derived rather than accepted. Its `artifact` is strict canonical `v10.review-early-prover-artifact.v1` with exactly `attempt`, `base`, `binding_prover`, `capability`, `completed_at`, `effort`, `execution_attestation`, `grounding`, `harness`, `lens`, `model`, `native_result`, `outcome`, `phase_alias`, `position`, `probe_report`, `rendered_prompt`, `role`, `schema`, `seat`, `seat_instance_id`, `started_at`, `status`, `vendor`, and `wave_id`. Before launch, composition/auth preflight writes the distinct immutable canonical `v10.review-early-prover-execution-attestation.v1` and binds a distinct immutable rendered-prompt reference; after launch, the worktree executor writes the distinct immutable canonical `v10.review-early-prover-native-result.v1`; only then may a separate reducer write the artifact. The prompt must contain exactly one `REVIEW_LENS: live-probe`, seat-instance marker, output-citation grammar marker, and canonical `REQUIRED_EVIDENCE_REF` marker for each final artifact, with no extra or conflicting marker in those families. Stage A derives Codex identity, `role="early_prover"`, `capability="can_probe"`, and `binding_prover=false` from the preflight attestation; derives status, exact raw probe report, exact terminal `PROBE_STATUS: CLEAR`, chronology, and grounding from the native result; and requires the report itself to contain canonical `EVIDENCE_REF` lines exactly equal to both final-artifact references. Citation lines do not count toward the substantive-content floor. A self-authored or opaque artifact, reducer-only grounding list, absent/swapped/aliased prompt or producer record, missing/extra/wrong prompt marker or native citation, citation-only report, padded terminal token, embedded elision marker, or disagreement among those records fails. Its strict canonical receipt mirrors only the derived facts plus the same phase/wave/attempt/base. `bundle_staging` has exactly `bundle`, `early_artifact`, `early_receipt`, and `staged_at`; both early references equal the `early_prover` references exactly, and `early_prover.completed_at < bundle_staging.staged_at`. The referenced bundle is itself canonical `v10.review-evidence-bundle.v1` JSON with exactly `schema`, `base`, and sorted unique `entries`; its `base` equals the receipt base and its direct file entries include the exact final-audit, final-evidence, early receipt, early artifact, early execution-attestation, early rendered prompt, and early native-result references. The bundle contains no receipt or bundle self-digest. This is the sole evidence-bearing Option-2 bundle: every reviewer receives only this by-reference bundle and read-only referenced bytes, with no arbitrary working-tree or shared-development-database execution.

`seats` is the ordered four-entry array for Grok, GPT-5.6 Sol, Gemini, and Fable. Each strict entry has exactly `artifact`, `binding_prover`, `capability`, `completed_at`, `consumed_bundle`, `counts_toward_floor`, `lens`, `material_findings`, `outcome`, `position`, `receipt`, `role`, `seat`, `started_at`, `usable`, `vendor`, and `verdict`. `artifact` is canonical `v10.review-seat-artifact.v1` with exactly `attempt`, `base`, `binding_prover`, `capability`, `completed_at`, `consumed_bundle`, `effort`, `execution_attestation`, `grounding`, `harness`, `lens`, `material_findings`, `model`, `native_result`, `outcome`, `phase_alias`, `position`, `rendered_prompt`, `review_text`, `role`, `schema`, `seat`, `seat_instance_id`, `started_at`, `status`, `vendor`, and `wave_id`. It is a reducer output, not the trust root. Before each launch, composition/auth preflight writes a distinct immutable canonical `v10.review-seat-execution-attestation.v1` binding the exact roster identity, model/effort/lens, role, capability, binding flag, seat instance, base, bundle, wave, and distinct immutable rendered prompt. That prompt must contain exactly one marker each for the attested lens, seat instance, exact bundle digest, output citation grammar, and both canonical required final-artifact references, with no extra or conflicting marker in those families. After each critic exits, `panel_invoker.invoke_board` writes a distinct immutable canonical `v10.review-seat-native-result.v1`; after the subscription-TUI native Fable report binds exactly once, `panel_invoker.bind_native_agent_leg_result` writes the same native-result schema. Each native result binds that exact prompt. Only then may the reducer write the seat artifact. Stage A derives identity, role, capability, Fable-only binding, and lens coverage from the execution attestation plus actual prompt bytes; derives canonical status, exact raw review text, start/completion instants, bundle consumption, and a unique native-result identity from the native result; maps the canonical statuses `OK`, `UNAVAILABLE`, `ERROR`, `TIMEOUT`, `REFUSED`, `CAPPED`, and `EMPTY` totally and one-to-one onto `reviewed`, `unavailable`, `errored`, `timed_out`, `refused`, `capped`, and `empty`; derives grounding only from canonical native `EVIDENCE_REF` lines that exactly name both staged final artifacts; and requires the reducer artifact to mirror every derived fact. Citation lines do not count toward the substantive-content floor. A reducer grounding list cannot create grounding, a static lens without its rendered-prompt marker cannot count, and one native status cannot be relabeled as another outcome. The last nonempty line, after the optional exact `VERDICT:` label and formatting trim, must full-match only `AGREE`, `PARTIALLY AGREE`, or `DISAGREE`; prefixes or suffixes such as `AGREE, but not approval` fail. Any `[elided]`, `<elided>`, standalone `...`, or `elided`/`omitted` marker anywhere in the body fails even when padded past the byte floor. A zero-byte/noncanonical or self-authored artifact, absent/swapped/aliased prompt or producer record, missing/extra/wrong prompt marker or native citation, citation-only or otherwise empty/sentinel/verdict-only review, malformed terminal verdict, duplicate seat/native-result identity, ungrounded review, producer/identity/capability/outcome substitution, or bundle/text/status/chronology substitution is non-review evidence and cannot count. Each retained seat receipt then mirrors only those independently derived values plus the same phase/wave/attempt/base; Stage A rejects disagreement among prompt, producer records, artifact, seat entry, and receipt. Every counting critic and Fable consumes exactly `bundle_staging.bundle` after staging. Positions 1 through 3 are critics with `binding_prover=false`; position 4 is Fable, the only `role="binding_prover"`, the only `binding_prover=true`, and starts strictly after all three critic completion instants. The final authorizing wave has no retained contradiction or material finding, and its effective-policy facts are derived from the validated producer chain rather than asserted wrappers: Stage A recomputes the roadmap-specific typed resolver input/output, vendor/lens counts, consensus, and prover fact. GPT-5.6 Sol and Fable must each derive `outcome="reviewed"`, `usable=true`, and `verdict="AGREE"`; Fable alone supplies the prover fact.

For every usable critic and Fable seat, the sorted native citation list must equal exactly the two staged final-artifact references. A third citation fails even when it is canonical, resolves inside the common bundle, and is mirrored by the reducer artifact.

`effective_policy` has exactly `consensus`, `gate`, `on_shortfall`, `required_lens_coverage`, `required_prover`, `required_vendors`, `resolver_input`, and `resolver_output`. The completion wave uses `gate="pre-merge-CR"` and resolves the shipped default `required_vendors=3`, `required_lens_coverage=3`, and `required_prover=true`; the common policy machinery remains parameterized for all four gates and retains a valid explicit boolean `required_prover=false` override that removes only the prover shortfall. The shipped defaults for plan-ratify, design-ratify, pre-merge-CR, and release-dispatch remain 3/3/true. Stage A re-hashes both policy artifacts, re-runs their strict typed resolution, and derives counted vendors, lenses, Sol AGREE, and the Fable prover fact only from the parsed and independently validated seat artifacts.

`restart_chain` is a chronological array of strict objects with exactly `attempt`, `finding`, `invalidated_agree_artifacts`, `prior_bundle`, `prior_receipt`, and `replacement_bundle_sha256`. An empty array means no contradiction occurred. Otherwise Stage A recursively rebuilds every earlier receipt and finding reference, requires contiguous attempts ending at the final `attempt`, requires each material finding or contradiction to invalidate every prior retained `AGREE`, requires a different replacement bundle digest, and requires the last replacement digest to equal the final staged bundle. A finding, contradiction, changed phase byte, or evidence change therefore invalidates the complete prior wave—not one seat—then repeats early prover CLEAR, bundle staging, all critics, and Fable in full. The producer closes every descriptor, makes the evidence tree immutable, and has a fresh coordinator process recompute all file references, canonical early/seat execution attestations and native results, bundle and reducer artifacts, producer-derived review facts, mirrored receipts, chronology, effective policy, restart chain, and inner receipt digest before `update_lifecycle(..., "completed", ...)` is allowed to emit the event. The artifact reducer is contractually unable to create or rewrite either producer record: execution attestations are write-once outputs of preflight before launch, native results are write-once outputs of the invoker/native binder after termination, and artifact reduction starts only from already-closed retained descriptors.

The exact predecessor panel now being repaired has SHA-256 `950a08facce1df02337d626301fc24af223812ef32c1cb99d18be6abc5ecd19b`. It reviewed REVIEWTRUTH plan SHA-256 `335e4dfa1af4ba14d97ce8102642234e58d8da0cbbd6a098298a1dc3c62f70e3`, roadmap SHA-256 `70c2ca94cc1b43f92cbcc2cd8298c9e713cf742c3e06d51a343708760342740c`, evidence-bearing bundle SHA-256 `5a2c6c4d892aee180ce3b7ea05dd86d2b46228138e855db86959467d8aa991e8` (`557138` bytes), instructions SHA-256 `bd6550e88bd8944a8a384b50b55561cee88b8e683ab5095992da79855090e91a`, and CLEAR early evidence SHA-256 `35c4ec83250bb32fba8599530a11aebcf0088c98a41b87b07cd9df8ce47d8d8f`. Grok and Gemini returned usable `AGREE`, GPT-5.6 Sol returned usable `DISAGREE`, and Fable deferred. The artifact is immutable, non-authorizing predecessor dissent: Sol proved that Stage A accepted arbitrary or identical ancestor SHAs as CONFORM/HARDEN landings and hardcoded a repository name without authenticating `origin`. The repair below changes the plan bytes, so its new digest is `unreviewed_not_approved` and must pass a fresh exact-digest ordered early-Codex/critics/Fable review before Stage A may execute. Nothing here claims review approval.

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

The historical content-addressed local-three artifact captured at that planning head has SHA-256
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

The fresh exact-digest local panel artifact now present at
`.phase-loop/reviews/v10-reviewtruth-plan-panel.json` has independently computed file SHA-256
`971065025e1714fb032643c8638180489fc7bed45b14f5d1582cd486b99421af`. It reviewed
predecessor plan SHA-256 `1b7f2683ec9ffcffebe85228e3853dac55a5f6cd554ce1fa66428a27dd63b6c8`,
roadmap SHA-256 `a289891a6f6bf27e07e3c1a5260d25f813f90931404c47dd2efc487e0aa268ba`,
bundle SHA-256 `c10032320ebef39f6bd24390b7b677cf9c3aed128df835457e14c1e06b7d7df3`
(`308801` bytes), and instructions SHA-256
`0315045f8d03308717e5ec218b7341cfb996263d4205029e0679b0a05760d177`. Grok 4.5 and
Gemini 3.6 Flash returned usable `AGREE`; GPT-5.6 Sol returned usable `DISAGREE`; Fable was
deferred and was not invoked, so this immutable historical panel authorizes nothing. Sol proved
that the proposed durable `SeatOutcomeRecord.degraded` field would be accepted by
`fab_gate.py`'s dataclass-derived allowed-field set but silently dropped by its hard-coded
constructor, so a strict read followed by rewrite could erase `degraded=true`. No lane owned that
reader. This repair assigns `fab_gate.py` to SL-2 with the schema and serializer, freezes one
literal tests-first append → strict read → rewrite → strict reread node in the already-owned
`test_reviewtruth_phase.py`, preserves absent-field/default byte neutrality, and keeps unknown
fields fail-closed. The changed plan digest is unreviewed and not approved; it requires a fresh
exact-digest Fable 5 + GPT-5.6 Sol + Gemini 3.6 Flash + Grok 4.5 panel with reviewed Fable and Sol
outcomes before SL-0.

This narrow correction preserves that historical panel identity and its non-authorizing status.
The repaired SL2-T2 prescription had still used Python truthiness for the known `degraded` key,
which would coerce wrong-typed JSON values instead of preserving the trust-root type boundary.
The final contract is exact: an absent key reconstructs `False`; a present key must be an actual
JSON boolean/Python `bool`, with present `true` and present `false` reconstructed unchanged; and
every other present type reaches the existing malformed-record/`ProvenanceInvalid` rejection path
before record construction or rewrite. The serializer remains asymmetric only on the wire:
default/false omits the key and true emits the key. The changed digest remains unreviewed and not
approved and requires the same fresh exact-digest four-seat panel before SL-0.

The historical panel content then stored at the run-local
`.phase-loop/reviews/v10-reviewtruth-plan-panel.json` path has file SHA-256
`8a30abffe37a9060ccf8bacdca668dc8e1a236fd2aac1062887646c2b7fdba0b`.
It reviewed predecessor plan SHA-256
`4c7a4411c28c89ca365bb2b37d6961affa84c4845de84a370d6f5821b0760668`, roadmap SHA-256
`a289891a6f6bf27e07e3c1a5260d25f813f90931404c47dd2efc487e0aa268ba`, bundle SHA-256
`08541485569d46d8ebe27f99fa78dea4d5fe7f3e2bb334d8c3b92d8c82f19770` (`324985` bytes), and
instructions SHA-256 `3256b7b304f46fca6b2978c78a432f92ddf5338401f3c90712290234e9c13cd7`.
Grok 4.5 and Gemini 3.6 Flash returned usable `AGREE`; GPT-5.6 Sol returned usable `DISAGREE`;
the artifact contains no Fable leg, so it authorizes nothing. Sol proved that exact source/CI skip
reason equality was nondeterministic: the selected node
`phase-loop-runtime/tests/test_release_pin_autotrack.py::test_release_pin_is_not_behind_pypi_latest`
performs a live PyPI request and lines 115-116 emit exception-dependent skip text on a caught
transport failure, while the bootstrap observer only normalizes repository paths. This repair adds
the exact-node PC-REVIEWTRUTH-5B disposition below. It accepts a pass when PyPI metadata is
reachable or one source-attributed transport-unavailable tuple with its raw reason and exception
diagnostic retained; it removes only that validated tuple before source/CI semantic skip equality,
rejects every broader network exemption, and leaves Gate A's standalone/root-missing skip and exact
`39 + 4 + 59 = 102` contract unchanged. The embedded observer bytes, `39420` byte count, SHA-256
`841cfb8bbac1d9b4ea0bb14a1f3600165550227b680b2e5689c79c13c61b1f6d`, and every reference to
them remain unchanged because its sealed full longrepr, raw stdout/stderr, and JUnit already retain
the evidence the SL-1 parser must classify. The changed plan digest is unreviewed and not approved
and requires a fresh exact-digest four-seat panel before SL-0.

At repair time, the content stored at the same run-local panel path has independently computed file
SHA-256 `aa2e270f72c9dcfe190b17d80b6108b58346fbe30313e795b09153ac9c3366c1`. It reviewed
predecessor plan SHA-256 `d58b36bf56f1911ef70cf475d6eb0caab01facdb306a71b3679332010ec42229`,
roadmap SHA-256 `a289891a6f6bf27e07e3c1a5260d25f813f90931404c47dd2efc487e0aa268ba`, bundle SHA-256
`5f2cb7273caa7e760dfb43fcb8d10e492c6363034254f0c23a94fd3e64a979ef` (`342446` bytes), and
instructions SHA-256 `9862f27d04ade47c3480342284ee1b5046e6261f9ac016c20f416eae52e13db0`.
Grok 4.5 and Gemini 3.6 Flash returned usable `AGREE`; GPT-5.6 Sol returned usable `DISAGREE`;
the artifact contains no Fable leg, so it authorizes nothing. Sol proved an SL-0/SL-1 authority
cycle: SL0-T3 blocked SL-1 on a verifier and wrapper first owned and authored by SL-1, while the
pre-SL-0 provision/observe/broad-baseline wording also required parsing by that absent future
parser. This repair gives SL-0 the exact coordinator proof below using only pre-existing
`git`, `gh`, `jq`, `awk`, and `sha256sum` surfaces plus its landed record. That proof alone can
complete SL-0 and unblock SL-1. After SL-0, the complete pre-edit bootstrap operations provision,
materialize both observers, freeze provisioning, and observe the untouched source plus exact
installed-wheel Gate-A copy before any SL-1 mutation; SL-1 then authors the parser, parses both
sealed observations, and retrospectively and independently re-verifies every SL-0 fact before SL-2
through SL-5. The digest identifies historical predecessor evidence at repair time; the run-local
path is overwriteable and is not claimed to remain current or immutable after the next panel run.
The changed plan digest is unreviewed and not approved and requires a fresh exact-digest four-seat
panel before SL-0.

At repair time, the overwriteable run-local panel path contained historical predecessor content
with independently computed SHA-256 `9760fc9f5d9df3e6392d76e08d1b9d1502f04bbd987c3ed9017ee6864b33962c`.
That content reviewed plan SHA-256 `864270f3b9f32c02f0717cb9ad53c8d27bedbdb2b484deb4b19ffcdecf3989f1`,
roadmap SHA-256 `a289891a6f6bf27e07e3c1a5260d25f813f90931404c47dd2efc487e0aa268ba`,
bundle SHA-256 `45026434ccd799f451463023847b02bf9dcc628dae16f88770832f6d982ed429`
(`358541` bytes), and instructions SHA-256
`2f2fe5c18974619c7006c1075cdca1756cf7b029045539ecdfae092243723fcb`. Grok 4.5 and Gemini
3.6 Flash returned usable `AGREE`; GPT-5.6 Sol returned usable `DISAGREE`; the artifact contains no
Fable leg, so it authorizes nothing. Sol proved that PC-REVIEWTRUTH-2 required paired source-layout
and Gate-A copied-tree observations before any SL-1 edit, while the executable pre-mutation chain
observed only source; the exact four-module/48-node collection boundary and `39 + 4 + 59 = 102`
skip profile therefore lacked contemporaneous Gate-A evidence and could only have been supplied by
forbidden historical constants or post-edit reconstruction. This repair preserves the exact
`39420`-byte source observer and adds a separately embedded `45116`-byte Gate-A observer at SHA-256
`d51199649bf0c4a2ed3c647e210128ecd07112c5229143b976de7600943af3c9`. A second payload is the
smaller sound boundary because copied-tree Gate A uses the installed wheel, tests-only
`PYTHONPATH`, external standalone root, and absent sibling/root profile rather than the source
observer's source-layout environment. The predecessor repair prescribed five post-SL-0 commands
and a comparison against the then-current four-module/48-node and `39 + 4 + 59 = 102` constants;
that prescription is historical and non-authorizing. The two-stage protocol below supersedes it:
after both dependencies land, an exact-base preflight plus five bootstrap commands provision,
materialize both observers, freeze provisioning, observe source, and observe the private
committed-tests-only Gate-A copy without comparing to those constants. Only after the required
Stage-B rewrite and literal tests-first transition does the newly
authored SL-1 parser independently consume both sealed directories and retrospectively re-verify
the already-proved SL-0 facts. The content digest above is historical predecessor evidence at
repair time; the path is not claimed to remain current or immutable after a later review rewrites
it. The changed plan digest is unreviewed and not approved and requires a fresh exact-digest
four-seat panel before SL-0.

An independent follow-up audit of repaired plan SHA-256
`d9bd1ddb7e23ad9af217604c764942349dbbc46992faacffa6a1dfe44436d559` found two fail-closed
gaps in that pre-edit pair. The Gate-A observer did not validate or freeze the complete already
sealed source observation, and the fifth operational command did not enforce the exact source,
Gate-A, marker, and omitted-nodeid identities promised by PC-REVIEWTRUTH-2. This repair preserves
the source observer byte-for-byte at `39420` bytes and SHA-256
`841cfb8bbac1d9b4ea0bb14a1f3600165550227b680b2e5689c79c13c61b1f6d`. It extends only the Gate-A
observer so that, before pairing, it validates the exact complete source artifact set, byte counts,
SHA-256 values, private canonical paths and modes, and source-observer/plan/roadmap/provisioning
bindings; freezes a canonical complete source-observation manifest as a Gate-A artifact; and
requires the manifest plus all four bound files to remain byte-identical after Gate A. The repaired
Gate-A payload is `45116` bytes at SHA-256
`d51199649bf0c4a2ed3c647e210128ecd07112c5229143b976de7600943af3c9`.

The following collection constants are historical, non-authorizing evidence from exact committed Git `HEAD`
`cee6cdc25f753a0f096444ee6f86fe724ef607e8`: archive the committed tree, build and install its
exact wheel in a uv `0.10.9` managed Python 3.12 environment from the frozen project, and collect
once with `-q -p no:cacheprovider -m "not dotfiles_integration" --collect-only` in source-layout
mode and once from the private external committed-tests-only Gate-A layout with tests-only
`PYTHONPATH` and the installed wheel. Both passes used the embedded observer's canonical nodeid
mapping. Sorted-LF hashing produced source full `4251` /
`e25173c29fb2fc1964bf052cfbf8613160a6cce87f153dd513d6244bdfd37d24`, source selected `3650` /
`f4139af6cc291ee5867cf04807cdca25f5c39f4dd7f212c83cff4bfe75316b87`, Gate-A full `4203` /
`d2047b8e53d19310a428b6728d46f47901b5a225d1ac6f4ff45abf566019b4a7`, Gate-A selected `3602` /
`d57ade2c1a0a0d5292191efaca00b0fa18ba2b7e7b27c352f94dc3d9416bb803`, and both marker-deselected
sets `601` / `76c54e5747a26dd58da2d68ece04e72cf894f518c7dec042de927299b6c6d907`. Both full and selected
source-minus-Gate-A sets are the same exact `48` nodeids at sorted-LF SHA-256
`da81279e6120f3f26db5590c66b17e32943ccee20993e82ca4b80002adbf4527`. None of those counts,
digests, tuple identities, or their `39 + 4 + 59 = 102` relation may authorize SL-0 or SL-1 after
CONFORM and HARDEN. They remain only a reproducibility witness for the observer protocol. The
`9760fc9f...` panel content remains historical predecessor dissent only; it did not review or
approve this follow-up repair.

At repair time, the overwriteable run-local panel path contained the authoritative exact-digest
review artifact at SHA-256 `f30d7a582e54d21bc5931e8b0aee2c95285f5195fb0b31b0dfc4c023fd4e012b`.
It reviewed predecessor plan SHA-256
`7284e0e660851068f7599643286ff6387b2c118b8b0dbef48e0627b2a91a2b5f`, unchanged roadmap
SHA-256 `a289891a6f6bf27e07e3c1a5260d25f813f90931404c47dd2efc487e0aa268ba`, bundle SHA-256
`d0ba9da3ba4a6b11843f0d484f11aaaadf039f405649f0f3790579e00d5ccd7d` (`430313` bytes), and
instructions SHA-256 `e1b9544cfd128fa1a94069bc5b64c936a194e9a7b1ac165e717b7831e982464d`.
Grok 4.5 and Gemini 3.6 Flash returned usable `AGREE`; GPT-5.6 Sol returned usable `DISAGREE`;
Fable was deferred, so the artifact authorizes nothing. Sol proved that the installed-wheel source
observer and GitHub CI have a `phase-loop` console script adjacent to their interpreter, while the
normative frontmatter, fresh-clone, default, candidate, and final source commands use
`PYTHONPATH=phase-loop-runtime/src` with bare `python3` and need not have that sibling. The exact
`phase-loop-runtime/tests/test_export_schema.py::test_console_script_check_smoke` node can therefore
pass in the frozen baseline but skip in an otherwise identical normative source run, outside the
two dispositions then permitted by PC-REVIEWTRUTH-5.

This repair adds only PC-REVIEWTRUTH-5C, a third exact singleton classifier. It preserves the raw
call-phase longrepr and provenance and removes the one source-layout tuple only when the exact
line-189 branch in `test_export_schema.py` at SHA-256
`355d74e6bbe823ecd0091e4cdb109b491e07ac5090d1a18a18e3e4a68bee4f06` reports the literal reason
`Skipped: phase-loop console script not on this interpreter`, the loaded runtime is the repo-owned
source tree, `CI` is absent, and `Path(sys.executable).with_name("phase-loop").exists()` is false.
It cannot normalize bootstrap, Gate A, GitHub CI, any package-installed run, any other reason or
line, or any second node. A new literal synthetic falsifier in the already-owned
`test_reviewtruth_phase.py` proves pass/unavailable and every rejection arm without external
dependencies, first RED and then GREEN before broad-baseline parsing. The source observer remains
exactly `39420` bytes at SHA-256
`841cfb8bbac1d9b4ea0bb14a1f3600165550227b680b2e5689c79c13c61b1f6d`; the Gate-A observer remains
exactly `45116` bytes at SHA-256
`d51199649bf0c4a2ed3c647e210128ecd07112c5229143b976de7600943af3c9`. The changed plan digest is
unreviewed and not approved and requires a fresh exact-digest four-seat panel before SL-0.

The latest predecessor review artifact has SHA-256
`ee125a63e4259cda103b432465f967fa47d9b2266ae37f7c11f6f2cf1e96e642`. It reviewed exact plan
SHA-256 `a3b5d97890f3551ba8813a947c8cf892aa10c98f910d177873ed78b61a4a4a50`, unchanged roadmap
SHA-256 `70c2ca94cc1b43f92cbcc2cd8298c9e713cf742c3e06d51a343708760342740c`, bundle SHA-256
`3f3952b4d29e1dfc5ef710fcfc5aab9d63811b83537527cb8b1b8074328dc171` (`538155` bytes), and
instructions SHA-256 `c03bbe6bee8638d7c8b29b112106b2c38771a8240b4fe0bb21455d57b5796654`; its isolated early-Codex
evidence has SHA-256 `20271a6a76ae20e758b96e26bd61d7779a14458fd91469e066005f5860382578`.
Grok 4.5 and Gemini 3.6 Flash returned usable `AGREE`; GPT-5.6 Sol returned usable `DISAGREE`; Fable
was deferred, so the artifact authorizes nothing. Sol proved two blockers. First, the reviewed
early-prover helper left `/tmp` as additional writable authority because the Codex workspace-write
policy omitted both `sandbox_workspace_write.exclude_tmpdir_env_var=true` and
`sandbox_workspace_write.exclude_slash_tmp=true`. Second, Stage A bound the mutable live
`plans/phase-plan-v10-REVIEWTRUTH.md` into its candidate manifest even though Stage B must revise
that file and then byte-regenerate the Stage-A manifest. This repair requires both sandbox
exclusions throughout policy, preflight, effective-config receipt, launch receipt, tests, and
positive controls, and replaces the live plan/roadmap manifest entries with private immutable
external Stage-A snapshots. This repaired digest is unreviewed and not approved and requires a
fresh exact-digest ordered early-Codex/critics/Fable four-seat review before SL-0.

REVIEWTRUTH therefore has an explicit two-stage detailed-plan lifecycle. This document is Stage A:
it freezes the reanchor protocol and the immutable source-observer bytes (`39420` bytes,
`841cfb8b...`) and Gate-A-observer bytes (`45116` bytes, `d5119964...`), but it does not freeze or
authorize a future source/Gate-A profile. Only after both CONFORM and HARDEN complete does the
coordinator supply their two distinct full immutable completion-control merge `F` SHAs to the
exact-base preflight, authenticate canonical origin before fetch, fetch canonical `main`, derive
both audited implementation `M` identities from strict `F`/`FH` topology and phase events, and
resolve one exact dependency-complete base commit and tree,
verify a full clean clone with replacement refs and grafts absent, and run the operational
provision/materialize/freeze/source-observe/Gate-A-observe commands below without mutating any
tracked test or production path. Those are the only five operational commands after the
operational exact-base preflight; the Codex external-tool preflight and every review, SL-0, RED,
GREEN, and closeout command remain non-operational Stage-B templates. That Stage-A run emits a
sealed candidate under a new private external runner root. Before it emits the candidate manifest,
bootstrap command five atomically copies the exact live Stage-A plan and roadmap bytes through
private temporary files into the new write-once mode-`0600` snapshots
`$REVIEWTRUTH_RUNNER_ROOT/stage-a-snapshots/plans/phase-plan-v10-REVIEWTRUTH.md` and
`$REVIEWTRUTH_RUNNER_ROOT/stage-a-snapshots/specs/phase-plans-v10.md`. It requires absent,
non-symlink destinations and temporaries before creation; regular canonical live sources; private
mode and owner on every snapshot directory and file; atomic rename; and immediate `cmp` plus
source/snapshot SHA-256 equality while the live files still contain the Stage-A bytes. Those frozen
external files are never revised in Stage B. Bootstrap command five then writes the mode-`0600`,
write-once canonical manifest
`$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-stage-a-candidate-artifacts.json`, outside both
observation directories. Its sorted entries use canonical relative identities and bind each file's
mode, byte count, and SHA-256: every file in both complete observation directories including both
attestations and all raw JUnit/plugin/stdout/stderr/set/skip/profile artifacts; both materialized
observer files; the provisioning record; the exact frozen Stage-A plan and roadmap snapshots under
explicit `repository-stage-a/` identities; every file in the
authoritative `phase-loop-runtime` tree and the copied Gate-A tests tree; and the sibling exact-base
sidecar. The command independently regenerates those entries from the current filesystem and
compares the canonical bytes immediately before writing and re-verifying
`$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-stage-a-candidate-profile.sha256`. That digest binds
the SHA-256 of the exact-base sidecar and the SHA-256 of the complete manifest through the
domain-separated canonical input defined in `## Verification`; neither the manifest nor the digest
is an input to the manifest, so the chain is acyclic. The candidate must be internally
self-consistent and bind the exact base commit/tree, canonical origin, both dependency `F`/`M`/`FH` triples, runtime/tests
tree, observer bytes, frozen Stage-A plan/roadmap snapshot bytes, provisioning identity, source observation, Gate-A
observation, and every raw set/tuple/count/digest; it is not compared with or authorized by the
historical `cee6cdc...` constants.

Stage B is a required second revision of this detailed plan after that candidate exists. The live
Stage-B plan is deliberately distinct from, and is never required to equal, the frozen Stage-A plan
snapshot. Stage B must replace every current-head aggregate count/digest and selector with the exact observed
dependency-complete base values; freeze the exact base commit/tree and runtime/tests tree; bind the
immutable observer payloads and the Stage-A plan/protocol digest; freeze the complete canonical
candidate-artifact manifest and the sealed candidate-profile digest; independently regenerate the
manifest from the filesystem by rehashing the two immutable external snapshots under their exact
`repository-stage-a/` identities, compare it byte-for-byte, and recompute the domain-separated
digest immediately before SL-0 or SL-1. Separately, it must bind the revised live Stage-B plan's
exact reviewed SHA-256 through the REVIEWTRUTH manifest row, isolated early-Codex evidence, exact
review bundle, and ordered four-seat review. After that review, the coordinator atomically stages
the exact reviewed plan, manifest, early-evidence, bundle, and panel artifacts beneath the private
external runner root and writes the mode-`0600`, write-once
`$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-stage-b-plan-binding.json`. That strict record binds
the computed plan SHA-256, every staged artifact path/byte-count/SHA-256, all four seat outcomes,
and the usable Fable and Sol requirements. The plan never embeds its own digest as a literal. A
fresh process re-hashes the live plan and every staged artifact and validates the record immediately
before SL-0 or SL-1; freeze the canonical installed Codex executable realpath/digest, version/help digests,
complete feature-name/value and configured MCP/plugin inventories, exact external-tool policy,
effective preflight shape, and receipt schema described by PC-REVIEWTRUTH-8; mechanically
recompute every REVIEWTRUTH expected/new/phase/activated node count, sorted-LF
digest, and anchor map including EC-REVIEWTRUTH-17; and make every SL-0/SL-1 command compare against
those Stage-B literals. Stage B then requires an exact-digest plan review in the directive's order:
the same fail-closed external-tool preflight passes before write-capable early Codex evidence is
staged, critic verdicts including GPT-5.6 Sol review that
same bundle, and only a usable grounded artifact-bound Fable result can bind the prover requirement.
Any material or contradictory finding changes the bundle, invalidates prior `AGREE` verdicts, and
restarts the entire ordered review. Only the reviewed Stage-B digest may authorize SL-0 and the
tests-only SL-1 mutation. Before either SL-0 or SL-1 and again immediately before mutation, the
coordinator fails closed on any missing or extra bound file, non-canonical or changed relative
identity, mode, byte count, SHA-256, manifest byte, candidate digest, or upstream
base/observer/provisioning/Stage-A-snapshot binding, or separate reviewed Stage-B-plan/manifest-row/
early-evidence/bundle/panel binding; it also re-verifies that canonical base/tree and the
runtime/tests tree are byte-identical to the Stage-B freeze. The revised Stage-B plan must never be
compared for equality with the immutable Stage-A plan snapshot. No future count or
hash is invented here, no predecessor local panel is authorizing, and CONFORM/HARDEN are never
blocked by REVIEWTRUTH's not-yet-executable SL-0 gate.

The executable contract is grounded in installed `codex-cli 0.145.0` and the live launcher seams,
not in the shell sandbox name. `codex exec --help` states that `--sandbox` governs
model-generated shell commands and that `--ignore-user-config` ignores only
`$CODEX_HOME/config.toml`; `launcher.py` separately documents that MCP servers from user, system,
or enterprise configuration run outside that sandbox. The installed effective feature inventory
also exposes apps, browser/computer variants, hooks, plugins/remote plugins, collaboration and
multi-agent variants, MCP dependency/elicitation paths, and other dynamic surfaces. A layered MCP
entry is not removed by `-c 'mcp_servers={}'` alone; the effective preflight must discover every
server and overlay a complete same-transport inert definition with `enabled=false`, then prove the
post-override enabled set is empty. Stage B must refresh and exact-digest this observation from its
canonical executable: version-specific names here are grounding evidence, while an unknown,
enabled, locked, changed, or uninspectable future surface is a fail-closed no-launch condition.

The full predecessor artifact staged at
`.phase-loop/planning-inputs/reviewtruth-predecessor-panel.json` is `19449` bytes at SHA-256
`4e1329c114d7e63b38ffae5395fc7f34776c896fc8aa291e6dff1ed9462a1523`. It reviewed predecessor
plan SHA-256 `d0aae91c87b5d28606b5216f43b91a1858302b1c798a57cc656b497b09423a51`,
roadmap SHA-256 `a5becca4edac8b58660a17421b314cbe389b98c93ad1dc824b587221b9e91b18`,
and bundle SHA-256 `2e9ec1bd1afce5db31d360c601b5b7b08898a62e97aeaf4d19568860eef4b4dc`
(`491202` bytes) under instructions SHA-256
`7c3aee0f9344abb15cb6ca002cfbbb30f9f072755afffa2757ead5f31be32a58`.
Grok 4.5 and Gemini 3.6 Flash returned `AGREE`; GPT-5.6 Sol returned blocking `DISAGREE`; no usable
Fable result exists. Sol proved both defects repaired here: fixed current-head profile constants
cannot authorize a post-CONFORM/HARDEN SL-1, and the concrete lane tasks omitted production seams
claimed by their criteria. This artifact is predecessor critic evidence only.

The newest local-three panel at `.phase-loop/reviews/v10-reviewtruth-plan-panel.json`, SHA-256 `0094458231f79e9b6b5355131133f8ed4abd3e67da574f87267d0c870dd34f5c`, reviewed predecessor plan SHA-256 `db2cc256593e717bcb0a23fc7ec9295727e6b713928b8ec451cef29e651b24ed` and current roadmap SHA-256 `b26b4fd76efb7882578eae5e102fd577b26e66f590a531d3b3a738d840e5106e` through the exact early-evidence-bearing bundle SHA-256 `960080998ef9836ea3d0c1ddca152dcbfb467326174a2cdc6ace0b8aab905d03` (`634342` bytes), instructions SHA-256 `e371ff950971a4b029a743b5da4b6af274d7c3ab2527a5e8a4cd3bc8934f5f67`, and CLEAR non-binding Codex evidence SHA-256 `42a01b771100a43c65b40035dac25e1988e1f18899feed192a58258483147cad`. Grok and Gemini returned usable `AGREE`, GPT-5.6 Sol returned usable `DISAGREE`, and Fable remained deferred, so the panel authorizes nothing. Sol proved that Stage A merely hashed opaque seat files while trusting receipt assertions for usability, outcome, verdict, identity, lens, bundle consumption, and capability; a zero-byte file with a matching descriptor and self-consistent receipt could therefore manufacture Sol/Fable AGREE and 3/3/true. This repair replaces that trust path with strict authoritative `v10.review-seat-artifact.v1` parsing and artifact-derived voting/prover facts, plus the zero-byte, empty/elided, forged-wrapper, duplicate-instance, grounding, and bundle substitution falsifiers above. The changed plan and producer-plan digests require a fresh early Codex pass and full local-three re-review before Fable can bind.

The next required initial-wave Codex probe at `.phase-loop/reviews/v10-reviewtruth-early-prover.json`, SHA-256 `f20d5d0c18899f7d4c9b5de310d4a4a29722144da954bbf90b7d361bfbc52381`, reviewed predecessor plan SHA-256 `3b4da713b4e3ac42461dd8efa6aff07b32dbac163b4eaaf598a56ab60dbd2ad`, current roadmap SHA-256 `b26b4fd76efb7882578eae5e102fd577b26e66f590a531d3b3a738d840e5106e`, and exact base bundle SHA-256 `0dd6d17ea889b56617bcd146e2c96f9720d7c0d3cda15fdb6bad13f3d5599373` at source head `adc0d60c07abfa2346f8c7f9c9169c4011683136`. It ran one CLI-enforced workspace-write Codex leg in the required disposable detached worktree with database/environment and external-tool isolation, then removed both the worktree and isolated auth home. It returned `BLOCKED` before any critic or Fable launch: the extracted verifier accepted a body containing `[elided]` plus padding and a final `AGREE`, accepted `AGREE` as a prefix rather than an exact terminal token, treated the early artifact as opaque bytes, and let the evidence-root writer synthesize seat identity/capability without independently produced preflight/native-result records. This repair therefore full-matches terminal tokens, rejects embedded elision markers, strictly parses the early artifact, and inserts write-once preflight and native-result producer records ahead of every early/critic/Fable reducer artifact. The two accepted attacks are mandatory negative fixtures in the unchanged named review-wave test node, alongside producer-record absence/substitution cases. This evidence authorizes nothing; the changed plan and producer-plan digests require another initial-wave Codex probe and fresh local-three review before Fable can bind.

The repaired initial-wave Codex evidence SHA-256 `f7fb68e0f51b7922561d5261450b231720d46eaf30ea2bf87cdf315fa9148a73` then returned `CLEAR` for predecessor plan SHA-256 `2468ad0d0e165880d30b3241fb8ce9c18b72a45ff23deff9ba7b35833a33ff9e` at source head `ce0a81f4e84da4a49a5e6bcf84f993bf2aba17ae`, exact base bundle SHA-256 `801b7ccaf6c6c422718f06983bb886939f6ae6d0bfbb030be0fc3a58253a1aca`, and unchanged roadmap. The following local-three artifact SHA-256 `93002b2c6f0d9da77e3ed9ed8a6e4f8ab846e2073a1be0558ab38938386ea6e5` reviewed evidence-bearing bundle SHA-256 `1b156d8ecd874e40547944862acacf2b1522d23799341b639b8529449f659395`: Grok and Gemini returned usable `AGREE`, GPT-5.6 Sol returned usable `DISAGREE`, and Fable was not launched. Sol proved three remaining vote-manufacture paths: reducer-authored grounding could promote generic native text; attested lens labels were not bound to rendered prompt bytes; and non-reviewed native statuses could be mirrored under any non-reviewed typed outcome. This repair makes exact native `EVIDENCE_REF` citations the sole grounding source, binds each lens/seat/bundle and required evidence ref into retained rendered-prompt bytes referenced by preflight and native result, and totally maps seven canonical native statuses onto seven typed outcomes. The unchanged named tests retain RED fixtures for all three attacks. Neither the CLEAR evidence nor the split local panel authorizes dispatch; all changed digests require a full new ordered wave.

The next isolated initial-wave Codex evidence at `.phase-loop/reviews/v10-reviewtruth-early-prover.json`, SHA-256 `94d810588a1bd5c32b79ec8abd344c25ee23620b6a75a9e3b5369d446ec4da6e`, reviewed predecessor plan SHA-256 `d684c27ccbbb038b8194fdffb7d0c1438cfe522eebe2321859e8348941c1db39` at source head `4aca617e85653fde22e89c11a013b195e0693b3f`, exact base bundle SHA-256 `b2323e4cfecf0940cb42cd99f757bc9f8679835da878dd0c2ca7e92bb54dbebf`, and unchanged roadmap. It returned `BLOCKED` with report SHA-256 `28908f7473932cb1bf88b9403e9d00141592633462c2153b8ecdf9e963cf9632` before any critic or Fable launch, after successful external-tool preflight, stable recheck, and complete worktree/auth-home cleanup. Reducer-only grounding, citation-only content, conflicting prompt markers, padded elision, verdict suffixes, and all 42 cross-class status/outcome substitutions failed as intended, but a substantive review citing the two final artifacts plus a third valid in-bundle artifact still counted. This repair requires exact citation-set equality and retains that third-citation attack as literal RED. It also labels the coordinator's early-first plan/design ordering as voluntarily stricter than the parameterized runtime permission and records the latest tracker sequencing without treating `agent-harness#405` as authority. This evidence authorizes nothing; the changed plan and producer-plan digests require another full ordered wave.

Current implementation anchors were rechecked rather than copied from drifted roadmap line references: `_render_leg_prompt` is at `panel_invoker.py:1065`; the TUI-policy exclusion and native-request attach are at `panel_invoker.py:4205-4232`; `_default_train_review` is at `train_runner.py:2006`; the count-only train-resume short circuit and ledger write are at `train_runner.py:2911-2957`; the legacy durable fields are at `train_ledger.py:166-180`; the legacy `leg.text.strip()` governed finding branch is at `governed_review.py:137`; and the separate governed pre-merge threshold is `_MIN_USABLE_REVIEWERS` at `governed_premerge.py:57`, consumed at `governed_premerge.py:405`.

The narrow durable-reader seam was rechecked directly. `fab_gate.py` derives
`_SEAT_OUTCOME_FIELDS` from `dataclasses.fields(SeatOutcomeRecord)`, rejects keys outside that set,
and uses `serialize_seat_outcome()` for append and rewrite, but `_seat_outcome_from_dict()` names
the pre-REVIEWTRUTH constructor fields individually. Without an explicit `degraded` reconstruction,
the new key would pass the trust-root allowlist, reconstruct as the dataclass default `False`, and
be omitted by the next byte-neutral rewrite. SL-2 therefore owns this reader alongside the
dataclass and serializer; no tolerant parse, unknown-key filtering, `**payload` construction, or
other weakening of the strict trust root is permitted.

A focused live-test scan for `_MIN_USABLE_REVIEWERS`, `below_reviewer_floor`, literal `usable_reviewers=2`, `floor counts LEGS`, and `2-usable` found the authorizing floor-2 pins in exactly `phase-loop-runtime/tests/test_governed_cross_vendor_floor_358.py` and `phase-loop-runtime/tests/test_train_merge.py`. `phase-loop-runtime/tests/test_governed_planning_gate.py` is the explicit non-floor plan/design scope control and remains governed by the preserved `proceed_degraded` policy rather than becoming a merge-floor positive pin. The golden surface was also rechecked: `test_advisor_board_golden.py` currently names `seat_key` as the sole sanctioned delta, with the same rule mirrored in `advisor_board/CONTRACTS.md` and `docs/advisor-board-capabilities-card.md`. REVIEWTRUTH intentionally adds typed result and prompt-lens output, so SL-1 must amend and freeze the normative expected-delta list in the golden test before implementation; SL-6 may mirror that already-frozen rule into its docs but cannot discover or repair it for the first time. A second compatibility scan confirmed five legacy expectations: `phase-loop-runtime/tests/test_advisor_board_research.py::InvocationAndCompatibilityTests::test_disabled_result_serializer_is_unchanged`, `phase-loop-runtime/tests/test_panel_invoker_spawn.py::ClaudeLegNativeAdapterRequestTest::test_native_agent_leg_request_rejects_fable_and_opus`, `phase-loop-runtime/tests/test_panel_native_fill_183.py::DeferredSeatSurfacesNativeFillRequest::test_board_deferred_seat_carries_request_with_seat_cognition`, `phase-loop-runtime/tests/test_panel_native_fill_183.py::DeferredSeatSurfacesNativeFillRequest::test_under_claude_code_requires_tui_adapter_even_without_local_cli`, and `phase-loop-runtime/tests/test_panel_native_fill_183.py::DefaultClaudeSeatNeverCarriesNativeFill::test_brief_ref_flows_into_the_request`. The final three are native-fill reversals: the first currently expects no request for the deferred Fable seat, the second expects no request even though the Claude Code host reaches `tui_adapter_required` before the false local-CLI support probe can govern native Task capability, and the third expects a supported Fable seat with a resolved `brief_ref` under Claude Code to carry no native request. All five must migrate tests-first under their full existing nodeids, retain their legacy/default assertions before the marker, assert the new contract under forced activation, switch automatically to those same new assertions after the exact production marker lands, and freeze every affected request/serializer field including the new identities and digests before SL-1 merges.

The native-fill seam was also rechecked directly. `SeatOutcomeRecord` already documents `seat_key` as explicitly non-unique and carries a unique FAB `seat_instance_id`, while `NativeAgentLegRequest` currently carries only optional seat/artifact/brief cognition and there is no closed `NativeAgentLegReport` binding surface. `test_panel_native_fill_183.py::DeferredSeatSurfacesNativeFillRequest::test_colliding_seat_keys_do_not_hide_a_failed_twin` already proves colliding `seat_key` values are legal. REVIEWTRUTH therefore cannot reuse `seat_key` as request identity: SL-1 freezes collision, retry/late-report, replay, cross-seat substitution, digest-substitution, and exactly-once-count falsifiers; SL-2 allocates one stable `seat_instance_id` per requested seat and fresh non-reused `request_id` plus `attempt_id` for every emission/retry; and SL-5 persists and reconstructs pending, superseded, consumed, and rejected attempt state without accepting a report twice.

## Interface Freeze Gates

- [ ] PC-REVIEWTRUTH-0 — All three issued `agent-harness#398` maintainer decisions are bound in `docs/research/reviewtruth-leg-capability-ratification.md`, merged separately before the tests-only landing, and binding on every later posture-assuming change. General roadmap execution authorization, panel approval, and `agent-harness#405` are non-substitutes.

  The record contains exactly one `REVIEWTRUTH_CAPABILITY_RATIFICATION_JSON` envelope with the strict keys `schema`, `issue`, `disposition_id`, `disposition_summary`, `option_2_posture`, `real_tree_arbitrary_execution`, `ratification_comment_id`, `ratification_comment_sha256`, `ratifier_login`, `follow_up_pilot`, `prover_directive`, and `ordering_addendum`. The existing Option-2 fields remain byte-semantically unchanged. `prover_directive` retains the exact comment `5139609713` identity, node ID `IC_kwDOTFEWvM8AAAABMlg4cQ`, URL, `2697` body bytes, SHA-256 `284e37117787f653ae91cebc2c04454ddb54ef0cc6434e26dc08b0875cddccfc`, both timestamps `2026-07-31T05:29:20Z`, and the additive/defaulted 3/3/true parameterized policy semantics frozen by PC-REVIEWTRUTH-7. `ordering_addendum` has exactly: `issue="Consiliency/agent-harness#398"`; comment ID `5139955591`; exact URL; body bytes `3684`; body SHA-256 `e0d61155a0d3ee9898d17ac89cdf029120109f198072f25c7517be20ddad5c4c`; created and updated timestamps `2026-07-31T06:20:15Z`; exact body bytes equal to `.phase-loop/planning-inputs/agent-harness-398-addendum.md`; `plan_design_critics_first_allowed=true`; `premerge_release_prover_first=true`; `subsequent_waves_early_prover_initial=true`; `contradiction_invalidates_prior_agree=true`; `codex_primary_sandbox="workspace-write"`; `grok_fallback_requires_codex_preflight_failure=true`; `grok_fallback_requires_os_confinement=true`; `unconfined_grok_launch=false`; `gemini_write_eligible=false`; `early_capability="can_probe"`; `binding_capability="binding_prover"`; `binding_vendor="claude-fable-5"`; `inflight_local_critics="predecessor_evidence_only"`; and `direct_claude_p=false`. `follow_up_pilot` records the exact staged `agent-harness#405` tracker bytes/digest and `authorizing=false`. Unknown, missing, extra, body-normalized, or semantically substituted keys fail.

  SL0-T3 uses only existing tools plus the merged record. It proves all three exact comment identities, issue/comment URLs, byte counts/digests and fixed timestamps; the available ratifier/association/permission metadata for the first two comments; the exact stored addendum body bytes for the third; and every semantic clause. It requires every directive timestamp no later than the record PR merge; proves the strict Option-2, non-authorizing tracker, prover-directive, and ordering-addendum objects; and separately retains the effective-rule, canonical-rules-digest, record-only PR/diff, two-parent/PR-head, fetched-main reachability, and no-posture-implementation checks. Its canonical proof emits all three comment identities, all directive-object digests, tracker-status digest, rules digest/boolean, and topology. Only zero exit completes SL-0. After SL-1 lands, chronology independently repeats those checks and compares the retained identities; neither a future wrapper nor `agent-harness#405` can authorize backward.
- [ ] PC-REVIEWTRUTH-1 — Chronology has three non-substitutable proof moments. First, the existing-tool SL-0 coordinator proof completes the durable ratification-record/protection lane and alone unblocks SL-1; the already-satisfied human decision is one exact input, not completion evidence. Second, the SL-1-owned pre-implementation mode can pass only after the separate tests-only landing by retrospectively re-verifying every SL-0 fact, then proving disposition ancestry, distinct PR/head identity, PANELLED RED evidence, allowed test-only paths, and no production change; only that mode unblocks SL-2 through SL-5. Third, final mode runs only after the separately merged SL-2-through-SL-5 implementation PR and additionally requires a two-parent implementation landing whose first parent already contains the disposition and tests-only landings, a distinct implementation PR/head, no SL-1-owned path in `implementation^1..implementation^2` or the implementation PR range, and no SL-1 tests-only commit carried on the implementation branch. Same-branch, squash, rebase, direct-push, shallow, grafted, replacement-ref, or tests-in-range history fails the applicable proof without creating a dependency back from SL-0 to SL-1.
- [ ] PC-REVIEWTRUTH-2 — Broad compatibility accounting is independent from phase-node accounting, separates marker deselections from skips, and uses the two-stage exact-base reanchor protocol above. Stage A runs only after CONFORM and HARDEN are both present in one exact fetched canonical base through two distinct operator-supplied completion-control merge identities `CONFORM_F` and `HARDEN_F`; identical values are rejected. Before any network fetch, the preflight authenticates remote `origin` as canonical `Consiliency/agent-harness`: fetch and push each have exactly one URL, each URL is exactly one of `git@github.com:Consiliency/agent-harness.git`, `ssh://git@github.com/Consiliency/agent-harness.git`, or `https://github.com/Consiliency/agent-harness.git`, both parse to the same case-sensitive owner/repository identity, and no effective `url.*.insteadOf` or `url.*.pushInsteadOf` rule exists at any config origin. A missing/extra origin URL, helper/rewritten/noncanonical URL, different fetch/push identity, or noncanonical owner/repository fails before fetch. The coordinator also supplies `REVIEWTRUTH_RUNNER_ROOT` as a new canonical absolute path outside the exact git toplevel, `REVIEWTRUTH_UV` as a canonical absolute executable path, and distinct nonempty `REVIEWTRUTH_CONFORM_COMPLETION_EVIDENCE_ROOT_ID` and `REVIEWTRUTH_HARDEN_COMPLETION_EVIDENCE_ROOT_ID` values independently obtained with the corresponding immutable evidence roots.

  After origin authentication the preflight fetches exact `refs/remotes/origin/main`, requires the clean full worktree HEAD to equal that fetched commit, and treats each supplied `F` as a completion-control merge rather than an arbitrary ancestor. For phase `P` in `{CONFORM,HARDEN}`, it proves `F` is a non-base, non-identical ancestor of fetched main with exactly ordered parents `[M,FH]`; `FH` has the sole parent `M`; both `M..FH` and `M..F` change only `plans/manifest.json` and preserve every other blob; and the fetched manifest has exactly one phase-qualified row. In that row, the exact unique strict `completed` event carrying `metadata.phase_completion_landing.schema=v10.phase-completion-landing.v1` is absent at `M`, appended in `FH` after an exact lifecycle prefix, byte-semantically unchanged in `F` and fetched main, and consistent with row status/timestamp. Its payload has exactly the producer-frozen top-level keys and the one nested `review_wave` contract above. Stage A requires explicit canonical evidence roots and independently supplied expected root IDs for both phases, rejects equal expected IDs, requires each `review_wave.receipt.evidence_root_id` to equal the corresponding expected ID before artifact validation, resolves every immutable relative locator beneath only that root, recomputes every byte count and SHA-256, parses and canonicalizes the bundle, every early/seat execution attestation, native result, reducer artifact, and receipt, rebuilds `review_wave.receipt_sha256`, and validates common base, bundle, policy, producer identity, chronology, role, and complete-restart bindings. It derives roster/capability/binding from the preflight records; status, exact raw text, chronology, bundle consumption, and unique native identity from invoker/native-binder records; and only then exact terminal verdict, substantive non-elided material, outcome, floor eligibility, usable `AGREE` Sol/Fable, and Fable-only prover facts. No SHA regex, aggregate claim, artifact/producer boolean, receipt assertion, prefix verdict, or equality among un-opened metadata values is evidence. Mandatory mutation fixtures include the formerly accepted `[elided]`-plus-padding body ending in `AGREE`, `AGREE, but not approval`, a fully synthetic four-seat artifact/receipt set with no producer records, an opaque early artifact, absent/swapped/aliased preflight or native-result references, forged producer/identity/text/status/bundle/chronology fields, duplicate native-result identities, and every prior zero-byte, empty, grounding, stale, restart, and wrapper substitution; each must fail the extracted verifier. Any missing, zero-byte, empty/elided, duplicate, drifted, wrong-phase, stale-plan/roadmap, unreadable or unrehashable locator, noncanonical JSON, arbitrary digest/outcome, wrong evidence-root ID, wrong bundle, chronology or policy mismatch, stale `AGREE`, incomplete restart, self-referential receipt/`FH`/`F`, or topology/delta mismatch fails. Only topology derives `FH` and `F`; neither may appear in the event or receipt. The preflight writes a private write-once sidecar recording the authenticated origin fetch/push spellings and identity, exact fetched base commit/tree, both derived `{completion_control_merge:F,audited_implementation_landing:M,control_head:FH}` triples, both verified evidence-root identities including the independently supplied IDs, and both recomputed review-wave receipt/bundle digests while retaining `conform_landing=CONFORM_F` and `harden_landing=HARDEN_F` only as explicit compatibility aliases.

  It then executes exactly five bootstrap commands: provision, materialize both immutable observers, freeze provisioning, observe source layout, and observe the installed-wheel Gate-A copied tree plus candidate seal. Inside the fifth command, before candidate emission, the coordinator atomically copies the exact live Stage-A plan and unchanged roadmap through private temporary files into new mode-`0600`, canonical, owner-private, non-symlink external snapshots beneath `$REVIEWTRUTH_RUNNER_ROOT/stage-a-snapshots/`; it requires every destination and temporary absent and non-symlinked before creation, every live source regular and canonical, atomic rename, and immediate `cmp` and SHA-256 equality against the still-live Stage-A source bytes. After validating the internally self-consistent `paired-profile.json`, the coordinator writes the complete canonical candidate-artifact manifest outside both observation directories, independently regenerates and byte-compares it from current file bytes and metadata, and writes/re-verifies the candidate-profile digest over the exact-base sidecar plus that manifest. Direct file entries, not `paired-profile.json` or any producer-supplied aggregate alone, bind every complete observation artifact and attestation, both observers, provisioning, the frozen external Stage-A plan and roadmap snapshots under `repository-stage-a/` identities, copied-tests/runtime-tree authority, and exact-base sidecar. The mutable live plan is not a candidate-manifest input. No tracked test, parser, record, or production byte changes during Stage A.

  Stage B then freezes that observed profile, the canonical candidate-artifact manifest, and the domain-separated candidate-profile digest into a revised exact-base plan; recomputes all aggregate suite/node/anchor counts and digests; and passes the ordered exact-digest Codex/critics/Fable review before SL-0 or SL-1 can begin. Only Stage B may replace “candidate” checks with literal equality against its reviewed exact values. In a fresh process before SL-0 or SL-1, and again after its SL-0 coordinator proof before any SL-1-owned file is edited, the coordinator independently re-authenticates the exact origin under the same no-rewrite allow-list, refetches main, requires the sidecar's canonical origin and base unchanged, and replays both completion-control proofs from the sidecar's exact `F`, `M`, and `FH` identities before it enumerates the complete frozen inventory, re-hashes every current file, rebuilds the canonical manifest byte-for-byte using the immutable external Stage-A plan and roadmap snapshots for the two `repository-stage-a/` entries, and re-verifies the candidate digest and every upstream binding. Separately, after the ordered review, it atomically stages the exact reviewed plan, manifest, early evidence, bundle, and panel beneath `$REVIEWTRUTH_RUNNER_ROOT/stage-b-plan-review/`, writes the strict mode-`0600` record at `$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-stage-b-plan-binding.json`, and requires that record to bind the computed live plan SHA, canonical origin, both dependency `F` and `M` identities, every staged artifact byte count and digest, all four seat outcomes, and usable Fable and Sol. Before SL-0 or SL-1 it re-hashes the mutable live revised plan and all staged artifacts and requires exact agreement among the record, REVIEWTRUTH manifest row, isolated early-Codex evidence, exact review bundle, ordered panel, and Stage-A sidecar. The plan contains no self-digest literal and is never required to equal the Stage-A plan snapshot. A missing/extra/drifted file, mode, byte count, SHA-256, relative identity, manifest byte, digest value/label, origin, dependency `F`/`M`/`FH`, topology, upstream base/observer/provisioning/Stage-A-snapshot relation, or separate Stage-B plan/review binding fails. Only then may SL-1 author the literal RED tests, followed by the parser/conftest implementations and the sixth operational parse. The parser cannot be required before it exists and cannot authorize SL-0. The runner root and every non-venv bootstrap boundary, including `stage-a-snapshots/`, `stage-b-plan-review/`, and their child directories, must be newly created, owned by the effective UID, private (`0700` directories and `0600`/`0700` files), canonical, non-symlinked, and disjoint from the worktree; the only permitted internal symlink is the venv's interpreter link whose real target must remain beneath the runner root's uv-managed Python directory. No bootstrap path may be covered by a Git status allowlist.

  `phase-loop-runtime/uv.lock` is a plan-authoring/bootstrap prerequisite at exact SHA-256 `b89987030b895131c3de05a316783ac0bcb6423d5531d6e9a04ee4a8f1e9fcce`. It must already be a regular tracked blob on canonical `main` before SL-0 dispatch, remain byte-identical through the SL-1 observation, and appear exactly once in both `git ls-tree -r HEAD -- phase-loop-runtime` and the `git archive HEAD:phase-loop-runtime` source. The plan/lock/manifest prerequisite landing precedes and is separate from the later `agent-harness#398` disposition, tests-only, implementation, and closeout landings. The lock is excluded from every REVIEWTRUTH lane's owned files: a later tests, implementation, or closeout edit cannot supply, regenerate, or amend it and cannot retroactively redefine the untouched baseline.

  Provisioning runs beneath `env -i`, exports HOME, TMPDIR, uv cache, and uv-managed-Python storage only under the runner root, archives the exact committed `phase-loop-runtime` tree — including that exact lock blob — to an external source directory, builds the exact local wheel from that copy, installs the lockfile-resolved runtime and `visual` dependencies with `uv sync --frozen --no-install-project`, then installs that exact wheel with `--no-deps` and the repository's explicit `pytest` test dependency under strict uv checks in the new external venv. This is the repository's established full-suite CI dependency shape; the checkout has no root `pyproject.toml`, while `phase-loop-runtime/pyproject.toml`, `phase-loop-runtime/uv.lock`, and `.github/workflows/test.yml` are the grounded package/lock/test sources. The provisioning freeze must import at least `pytest`, `pydantic`, `consiliency_contract`, `PIL`, and `phase_loop_runtime`, enumerate every installed distribution, verify every hashed installed `RECORD` member, and record the exact uv executable/version/digest, uv-managed interpreter and `pyvenv.cfg`, package inventory, external source manifest, wheel members/digest/RECORD, installed distribution metadata/RECORD, `sys.path`, required module paths/digests, and entry-point inventory. Every recorded digest must match the bytes it describes, every required field must be present, and the same-run provision/observe chain must remain internally consistent. The source manifest independently records every committed runtime path/blob/file digest plus `pyproject_sha256` and `uv_lock_sha256`; absence of the archive lock fails the freeze, repo/archive substitution fails byte equality, and the later parser requires the recorded lock digest to equal the exact plan-bound digest. It also rejects `include-system-site-packages`, enabled user site, a user/system `site-packages` or `dist-packages` path outside the venv, a distribution outside the venv, repo-owned source or local-wheel drift, a tampered/self-inconsistent installed `RECORD`, or any missing collected-suite import before observation. Pytest/pluggy distribution versions, absolute module/distribution paths, and module/file digests describe this observed environment only; they are mandatory provenance and diagnostics, not cross-environment semantic equality keys.

  Materialize the source bootstrap observer's exact `39420` bytes only at `$REVIEWTRUTH_RUNNER_ROOT/materialized/reviewtruth-baseline-observer.py`, require SHA-256 `841cfb8bbac1d9b4ea0bb14a1f3600165550227b680b2e5689c79c13c61b1f6d`, and in the same write-once operation materialize the dedicated Gate-A observer's exact `45116` bytes only at `$REVIEWTRUTH_RUNNER_ROOT/materialized/reviewtruth-gate-a-baseline-observer.py`, requiring SHA-256 `d51199649bf0c4a2ed3c647e210128ecd07112c5229143b976de7600943af3c9`. Run all modes with `$REVIEWTRUTH_RUNNER_ROOT/venv/bin/python`, never a bare system interpreter. Each mode starts beneath `env -i` and requires the complete initial environment to equal the exact nine-key allowlist `HOME`, `PATH`, `LANG`, `LC_ALL`, `PYTHONNOUSERSITE`, `PYTHONDONTWRITEBYTECODE`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD`, `PYTHONPATH`, and `TMPDIR` with the mode-specific frozen external values in the commands; this rejects ambient `PYTEST_ADDOPTS`, `PYTEST_PLUGINS`, every `PHASE_LOOP_*` selector, `CI`, user/system-site fallback, bytecode/cache writes into the worktree, and every unlisted process key rather than merely failing to record them. Provision-freeze writes one canonical file at `$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-bootstrap-provisioning.json`; source observation requires and rechecks that exact file before invoking one GREEN pytest process with exact argv `phase-loop-runtime/tests -q -m "not dotfiles_integration" -p no:cacheprovider --junitxml=<external write-once source observation>/broad.xml`. Its try-first hookwrapper records the complete canonical repo-relative item set before built-in marker selection and the selected item set after selection in that same process; its `pytest_deselected`, runtime-report, and collection-report hooks contemporaneously record the exact deselection multiset, each item's marker names, and legitimate item/module skip tuples and reasons. Every provisioning/materialization/freeze/source-observation/Gate-A-observation snapshot requires empty `git status --porcelain=v1 -z --untracked-files=all` before and after and byte-identical HEAD, HEAD tree, and index tree; no relative or in-worktree bootstrap output is accepted.

  The same process attests the complete post-pytest environment, not a hand-picked subset. Suite initialization may add only `PHASE_LOOP_PROFILE_PLUGINS=phase_loop_runtime.dotfiles_profile_plugin:register_profile_commands` and `PHASE_LOOP_SKILL_SOURCE_PLUGINS=phase_loop_runtime.skill_sources_plugin:register_skill_sources`; `PHASE_LOOP_RUNNER_REPO_ROOT`, `PHASE_LOOP_CLAUDE_ROUTE`, `CI`, `PHASE_LOOP_REVIEWTRUTH_POST_PARSER_COLLECTION`, `PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH`, and `PHASE_LOOP_SKIP_GATE_A_SUITE` must remain absent. Because the isolated environment installs the exact local wheel, both application entry-point groups must contain exactly the wheel's one `dotfiles` entry and no ambient distribution; source-mode opt-ins and installed entry points must deduplicate to exactly one profile registrar and one skill-source provider. Their loaded module/callable source files must live beneath `phase-loop-runtime/src/phase_loop_runtime/`, their repo-relative paths and source digests remain semantic equality keys, their distribution metadata/RECORD must live beneath the external venv, and the provider's complete harness-to-root output is frozen. Any extra registrar/provider, entry point, distribution, source outside the repo/venv boundary, selector value, absolute/extra root, or missing source fails before sealing. The write-once external observation contains `full-nodeids.txt`, `selected-nodeids.txt`, `marker-deselected-nodeids.txt`, `legitimate-skips.json`, raw stdout/stderr, ordinary JUnit, raw plugin events, and a terminal canonical attestation that binds their byte counts/digests plus observation UUID, provisioning-file digest, observer/plan/roadmap digests, exact `sys.orig_argv`, `/proc/self/cmdline`, internal pytest argv and their digests, the exact initial/post-pytest environment maps, every runtime selector and application entry point, the loaded registrar/provider source/digest/root profile, PID/PPID/PGID/SID/UID/GID, boot ID and process-start ticks, CWD, uv/interpreter/package/source/wheel/distribution/RECORD/`sys.path` provenance, pytest/`_pytest`/`pluggy` module paths and file digests, pytest version, and every loaded pytest plugin's name/module/class/distribution/version/path/digest. Those pytest/pluggy and non-repo core-plugin version/path/digest fields are mandatory diagnostic provenance; recording and self-consistency are required, but their raw values do not define semantic parity across bootstrap, CI, Gate A, or another supported environment.

  After, not before, both observations are sealed and Stage B has reviewed and frozen their exact identities, SL-1 authors `verify_reviewtruth_chronology.py` and independently parses the raw files from explicit canonical absolute `--runner-root`, `--stage-a-base`, `--provisioning`, `--observation-dir`, `--observer-source`, `--gate-a-observation-dir`, `--gate-a-tests-root`, `--gate-a-observer-source`, `--stage-a-plan-snapshot`, `--stage-a-roadmap-snapshot`, `--stage-b-plan`, `--stage-b-plan-binding`, `--stage-b-plan-review-dir`, and both observer-digest arguments. Before consuming any observation, the parser re-authenticates canonical `origin`, refetches exact main, byte-validates the Stage-A base sidecar, and replays both sidecar-bound `F`/`M`/`FH` completion proofs including origin, topology, manifest-only deltas, and strict events; the Stage-B binding record must name the same canonical origin and both `F`/`M` pairs. It must re-hash both exact embedded observer payloads, the provisioning freeze, both observation directories, and both immutable external snapshots; require the source and Gate-A attested plan/roadmap digests to equal those Stage-A snapshot digests rather than the revised live plan bytes; separately require the live Stage-B plan digest and every staged review artifact to equal the strict write-once binding record, then parse those staged artifacts and require the same digest in the manifest row, early evidence, bundle, and ordered panel; independently verify the private external-root and copied-tree boundaries; require the exact tracked/archive `phase-loop-runtime/uv.lock` digest; recompute the uv/interpreter/package/source/wheel/distribution/RECORD/`sys.path`/module/plugin provenance; and recompute the full `REVIEWTRUTH_BROAD_PREIMPLEMENTATION_COLLECTED_NODEIDS`, selected `REVIEWTRUTH_BROAD_PREIMPLEMENTATION_SELECTED_NODEIDS`, exact `REVIEWTRUTH_BROAD_MARKER_DESELECTED_NODEIDS = full - selected`, legitimate raw `REVIEWTRUTH_BROAD_BASELINE_SKIP_TUPLES`, their counts and sorted-LF/canonical-JSON SHA-256 values, JUnit outcomes, command/runtime/provenance records, the full-minus-selected/deselection/marker relations, both complete environment maps, every forbidden-selector absence, both exact local-wheel entry-point registries, the exact loaded application registrar/provider sources and digests, and the complete skill-source root mapping without trusting attestation-derived counts or summaries. The exact full and selected pre-edit sets remain frozen, not merely their counts: the immutable test/record surface retains their canonical compressed bytes plus counts/digests, while the explicit marker difference tuple and raw skip tuples remain readable literals. For source/CI semantic parity, the parser then applies PC-REVIEWTRUTH-5A, PC-REVIEWTRUTH-5B, and PC-REVIEWTRUTH-5C as three exact singleton classifiers: it retains each raw tuple and provenance, structurally validates the PyPI longrepr before removing at most its one transport tuple, and validates the exact console-script source branch plus interpreter/module/CI/sibling-path facts before removing at most its one source-layout tuple. Neither observer performs broad normalization; Gate A applies none of the three dispositions. SL-1 also derives and freezes the only allowed source-capable post-SL-1 collection transformation: the pre-edit full/selected sets plus exactly the declared new REVIEWTRUTH nodeids, with migrated nodeids unchanged and exactly five new post-parser wrappers removed by the ordinary hook.

  SL-1 separately freezes the Gate-A-specific transformation imposed by the unmodified clean-room script from the paired source-layout and copied-tree observations already made before any SL-1 edit. The dedicated pre-edit Gate-A observer runs from `$REVIEWTRUTH_RUNNER_ROOT/gate-a-preimplementation-input/standalone` with `PYTHONPATH` equal only to its copied `phase-loop-runtime/tests` directory and imports `phase_loop_runtime` only from the exact installed wheel. Before invoking pytest, it requires the sealed source observation to contain exactly `attestation.json` plus the eight artifacts declared by that attestation, verifies every direct child as canonical, regular, owner-private, exact-mode, and byte/count/SHA-256-equal to its declaration, independently recomputes all raw source sets and skip artifacts from `plugin-events.json`, and verifies the exact source observer, plan, roadmap, provisioning, environment, runner-root, and clean-Git bindings. It canonicalizes all nine source files into `source-observation-manifest.json`, records that manifest's digest and all four upstream binding digests in the Gate-A attestation, and after pytest re-reads the complete source directory and all four bound files and rejects any byte change. Its input is produced directly from `git archive HEAD phase-loop-runtime/tests`, includes the exact committed `tests/**` inventory and `tests/conftest.py`, contains no ignored/untracked additions, and is recursively private. It proves the runtime directory contains only `tests`, the standalone directory contains only `phase-loop-runtime`, the tests' `parents[3]` detector directory contains only `standalone`, and every intentional omission is absent at both relevant roots: sibling `phase-loop-skills/`, repo `skills-src/`, `phase-loop-runtime/scripts/`, adjacent package `pyproject.toml` and lock, root release pins/installers/docs/workflows, plans, and specs. It records exact Git blob IDs, modes, byte counts, and SHA-256 values for every copied file, rejects any symlink/extra/missing byte, canonicalizes copied nodeids back to `phase-loop-runtime/tests/...`, and emits full/selected sets, marker accounting, raw stdout/stderr/JUnit, complete plugin/environment/wheel provenance, and collection/runtime skips as separate full normalized-longrepr rows. It invokes neither future SL-5 code nor any post-edit conftest/parser and requires the worktree HEAD/tree/index/empty all-untracked status and complete source observation manifest to remain unchanged.

  The independent planning-author collection witness below was mechanically derived from committed Git `HEAD` `cee6cdc25f753a0f096444ee6f86fe724ef607e8`, before the dependency-complete REVIEWTRUTH base exists. Every count, digest, delta, and tuple in that witness is historical and non-authorizing. Stage B must replace it with exact observed values from its fetched dependency-complete base; equality to these historical values is neither required nor sufficient.

  Both observers emit sorted canonical JSON rows shaped exactly as `{"nodeid": <repo-relative nodeid>, "phase": "collect"|"setup"|"call"|"teardown", "reason": <repo-root-normalized longrepr>}`; collection reports and runtime reports are stored in separate tuples before any union is formed. The Gate-A observer independently derives the pair profile into its write-once directory. In Stage A, the fifth bootstrap command validates only internal relations and emits that candidate profile, while its terminal digest binds the exact-base preflight sidecar. In Stage B, the revised fifth bootstrap command refuses to return until the candidate and fresh observation match the reviewed Stage-B literals exactly. The historical four-module/48-node and 39/4/59/102 values below remain diagnostic examples of the relation to freeze, never authority for the dependency-complete base. A separate SL-5 external persistent evidence copy later uses only `input-copy/tests/**` (including `input-copy/tests/conftest.py`), `input-copy/chronology-parser/verify_reviewtruth_chronology.py`, and its manifest; it is non-importable and never creates `input-copy/phase-loop-runtime/scripts/` or mutates the temporary runtime tree. Every copied test/conftest/parser byte equals its exact committed repo-owned byte. Unexpected source-only tuple loss, unexpected sibling/root presence or absence, any `phase-loop-runtime/scripts` root in either copied namespace, a parser anywhere outside `input-copy/chronology-parser/`, an unexplained boundary module, a boundary skip becoming pass/fail, a category or phase change, or any unrelated skip is a hard failure.

  The cross-environment semantic record is deliberately narrower than the diagnostic provenance record and explicitly profile-aware. Source-capable bootstrap, source checkout, GitHub CI, candidate, and broad-final environments require exact equality to the frozen source/CI full/selected and skip sets. Gate A requires exact equality to the separately frozen Gate-A full/selected sets, expected collection/runtime skip unions, and their complete baseline-plus-boundary total; it must not be compared to the impossible source-capable nodeid/skip sets. Both profiles require exact repo-owned test/conftest/parser bytes and digests; declared environment selector names and values; exact application-plugin entry-point groups/names/values/distribution origin plus repo-relative registrar/provider source paths and digests; their declared repository/source/root maps; absence of ambient, autoloaded, or unapproved third-party collection plugins; their own canonical full and selected nodeid sets; marker and hook deselection tuples/categories/reasons; profile-specific legitimate skip tuples/reasons; hook activation and notification behavior; pytest command/profile; collection/import success; exit status; JUnit nodeid/outcome/result accounting; and every other repo-governed behavior already frozen here. The collection-plugin behavioral profile normalizes approved pytest-core/pluggy implementation details to their role and trusted origin and excludes their distribution versions, absolute module/distribution paths, module/file digests, and version-bearing metadata. Those excluded values must still be present, parseable, bound to the artifact that reported them, and emitted in mismatch diagnostics, but changing only one or more of them across environments is not drift and cannot fail the phase.

  Any unexplained environment key, selector/application-plugin/root value or source, application entry point, unapproved distribution origin, user/system-site escape, nodeid, parametrization, marker, skip, deselection category, repo-owned source digest, hook contract, or collection/exit/JUnit/result behavior change is semantic drift. A pytest/pluggy or approved core-plugin release is unsupported and fails when it cannot import or collect the suite, cannot expose enough provenance to classify plugin origin, loads an unapproved plugin origin, changes canonical collection/selection, skip/deselection accounting, exit status, JUnit/result behavior, or violates any repo-governed hook/selector contract; raw byte or version difference alone is insufficient. Mutation tests independently inject each referenced initialization selector, an unknown environment key, an application entry point/distribution, a user/system-site path, an extra/changed plugin origin or spec, an outside-repo application-plugin source, a changed root mapping, a symlinked/reused/wrong-mode runner path, and changed lock/provisioning/local-wheel/RECORD bytes and require the observer or later parser to reject it. Separate positive controls vary only recorded pytest/pluggy distribution versions, absolute module paths, module digests, and approved core-plugin version/path/digest metadata while holding the semantic record fixed and require parity to pass; paired negative controls use a changed/unsupported toolchain to alter collection, plugin origin, nodeids, skip/deselect categories, exit status, or JUnit/result behavior and require parity to fail. Absolute installation roots and Python 3.10/3.11/3.12 executable paths are likewise retained as exact observation provenance but are not portable equality keys. The bootstrap observer itself is subtracted as the one exact externally supplied observation plugin; any other autoloaded or unapproved collection-affecting plugin origin is forbidden.

  After SL-1 is authored, source/CI broad default-premarker must report the disjoint union of exactly the unchanged marker baseline plus exactly the five hook-owned `REVIEWTRUTH_POST_PARSER_NODEIDS`, while its semantic skip set is exactly the source/CI broad baseline after independent PC-REVIEWTRUTH-5A/5B/5C validation UNION the non-post-parser `REVIEWTRUTH_DEFAULT_PREMARKER_SKIP_NODEIDS`; source/CI candidate and broad-final producer must report that same marker-baseline-plus-five deselection union and exactly the unchanged semantic source/CI broad skip baseline after those three dispositions. The raw skip tuple and disposition evidence remain separately attested. Gate A must instead report its exact frozen full/selected sets and the same unchanged marker baseline plus five hook-owned wrapper deselections over the retained collection, while skip accounting is category-exact: collection skips equal `REVIEWTRUTH_GATE_A_EXPECTED_COLLECTION_SKIP_TUPLES = REVIEWTRUTH_GATE_A_RESTRICTED_SOURCE_COLLECTION_SKIP_TUPLES ∪ REVIEWTRUTH_GATE_A_BOUNDARY_COLLECTION_SKIP_TUPLES`; runtime skips equal `REVIEWTRUTH_GATE_A_EXPECTED_RUNTIME_SKIP_TUPLES = REVIEWTRUTH_GATE_A_RESTRICTED_SOURCE_RUNTIME_SKIP_TUPLES ∪ REVIEWTRUTH_GATE_A_BOUNDARY_RUNTIME_SKIP_TUPLES`; and their disjoint union equals `REVIEWTRUTH_GATE_A_EXPECTED_SKIP_TUPLES`. The four collection-boundary tuples account for all 48 omitted source-selected nodeids, while the 59 runtime-boundary tuples account for every retained nodeid whose source control ran but whose Gate-A copy skips because a proved repo/root input is absent. The pre-edit counts/digests (`39` retained source tuples at `59dfdd0c…`, `4` collection-boundary tuples at `09e45269…`, `59` runtime-boundary tuples at `760925fe…`, and `102` expected Gate-A tuples at `57746ee9…`) are independently recomputed and then literalized in full; Gate A is never compared to the unfiltered source/CI skip set and is never allowed to omit its retained source baseline or normalize its line-111 release-pin root-missing tuple. The conftest observer rejects nonempty pytest `--deselect`, canonicalizes source-root, CI-working-directory, and Gate-A copied-tree nodeids to the frozen repo-relative form, selects the expected profile only from the proved sibling-boundary/root shape rather than an ambient flag, records built-in marker-filter and hook-owned wrapper categories separately from collection/runtime skips, requires the hook itself to find/remove/notify exactly all five wrappers, and fails the session on any missing, extra, duplicate, arbitrary, category-drifted, plugin-drifted, boundary-drifted, collection-drifted, or second network-normalized result, second console-normalized result, or console normalization outside the exact source-layout predicate. The plain frontmatter `automation.suite_command`, the explicitly amended GitHub CI workflow across Python 3.10/3.11/3.12, and fresh-clone source suites use the source/CI profile; clean-room Gate A uses only the Gate-A-specific profile. All remain GREEN after the marker without run-local evidence or guaranteed live internet and attest exact repo-owned bytes, their profile's immutable full/selected digests, marker baseline plus five wrappers, allowed plugin/root profile, applicable frozen skip accounting, and raw plus semantic disposition evidence. A new, missing, renamed, newly passing, or drifted collection member, marker deselection, boundary skip, retained-baseline skip, plugin, root, or hook; a phase skip surviving candidate/final; any `xfail`; a missing/extra/wrong hook deselection; any command-line `--deselect` or other arbitrary deselection; or any failure/error blocks. Every pushed implementation candidate runs the unmodified source/CI broad command from a fresh exact-head process, and its generated candidate XML is parsed before the golden, panel, or merge. Final broad producer uses the same source/CI ordinary arm and is parsed before exact final collection can be issued. This plan never claims five total broad deselections, never claims whole-suite zero skips, never creates a broad network or command-availability exemption, and never asks a later parser to manufacture past provenance. The required workflow edit is owned by SL-5 and occurs only after the SL-1 tests-only RED landing.
- [ ] PC-REVIEWTRUTH-3 — SL-1 freezes a separate phase-selected contract. `PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1` forces the new production contract on the pre-implementation base without importing a missing symbol; otherwise non-post-parser tests use the exact production capability marker `REVIEWTRUTH_CAPABILITY_MARKER = "reviewtruth@1"` from `panel_invoker.py`. The immutable verifier freezes `REVIEWTRUTH_EXPECTED_NODEIDS`, the five-member `REVIEWTRUTH_POST_PARSER_NODEIDS`, and `REVIEWTRUTH_PHASE_NODEIDS = REVIEWTRUTH_EXPECTED_NODEIDS - REVIEWTRUTH_POST_PARSER_NODEIDS`, each with an exact count and sorted-LF SHA-256; the expected set includes every parametrized expansion, floor/train/golden migration, all five full compatibility nodeids, positive controls, and the five strict post-parser wrappers. `junit-run --mode default-premarker`, `activated-red`, and `candidate` invoke pytest with exactly `REVIEWTRUTH_PHASE_NODEIDS` and do not activate post-parser collection. Default-premarker phase JUnit contains that exact phase set: only the non-post-parser `REVIEWTRUTH_DEFAULT_PREMARKER_SKIP_NODEIDS` skip with the one frozen reason, while every migrated existing nodeid runs its legacy assertion branch. Activated-RED phase JUnit contains that same exact phase set, executes each `REVIEWTRUTH_ACTIVATED_RED_NODEIDS` member exactly once and fails only at its mapped raw `REVIEWTRUTH_RED_ANCHORS_BY_NODEID`, passes every positive control, and contains no post-parser wrapper or unrelated skip. For `activated-red` only, `junit-run` records pytest's required nonzero exit and returns control only after the literal XML path exists; it does not bless any failure, and the immediately following `junit --mode activated-red` parser is the sole GREEN/RED authority. Candidate phase JUnit contains exactly `REVIEWTRUTH_PHASE_NODEIDS` with zero phase skips, `xfail`, failures, errors, duplicates, or unexpected/missing nodeids. Only after the broad-final producer parser has emitted and verified its attestation may `junit-run --mode final` reject any inherited activation, set the exact test-owned collection activation, and select all `REVIEWTRUTH_EXPECTED_NODEIDS`; final phase JUnit must contain every expected nodeid exactly once, including all five strict wrappers, with zero phase skips, `xfail`, failures, errors, or deselections. Once SL-2 installs the marker, all migrated and production-dependent assertions switch automatically to the same new branch without test edits, but that marker never activates the post-parser wrappers. No implementation lane may edit tests, conftest, guards, selectors, nodeids, counts, set digests, anchors, parser modes, activation names/values, or skip/deselection reasons; the sole allowed collection-time environment branch is the exact SL-1-owned final-collection predicate, and no import or marker-import failure is permitted.
- [ ] PC-REVIEWTRUTH-4 — Candidate and final proof are process-bound and generation precedes parsing. Candidate phase and broad XML are both generated at literal runner-owned paths in a newly spawned repo-local process after proving `HEAD` equals the exact pushed implementation head and all imported `phase_loop_runtime` and tests/conftest paths and digests resolve beneath that worktree; only then may the frozen parser run in `candidate` mode against those exact two paths, and only its GREEN attestation may unblock golden, panel, or merge.

  Final evidence uses a different newly spawned repo-local process after proving `HEAD` equals the exact fetched canonical-main head containing the two-parent implementation landing; only SL-6-owned evidence/doc dirt may then exist. That child first generates broad-final producer XML through ordinary collection, whose observer attests exactly the frozen marker-filter baseline plus the hook's five frozen wrapper deselections in separate categories, then parses it in `broad-final-producer` mode. Only after that attestation is GREEN does the immutable `junit-run --mode final` reject a pre-set `PHASE_LOOP_REVIEWTRUTH_POST_PARSER_COLLECTION`, set it to the exact value `junit-run:final:v1` only in its pytest child, and generate phase-final XML whose five strict wrappers consume only already-existing non-self-referential inputs — the frozen pre-final SL-6 evidence document at `docs/research/reviewtruth-phase-verification.md` and the single canonical durable redacted transcript and smoke record at `docs/research/reviewtruth-real-panel-smoke.md`, each at its exact frozen digest, ledger and landing metadata, the phase default/RED/candidate and broad marker/skip baseline/default/candidate XML and parser attestations, and that broad-final XML and attestation — and never the phase-final XML or its digest, the final-mode parser attestation, the finalized record, the `final-record` attestation, or any closeout verdict; it then parses both exact XML paths in `final` mode.

  Only after that final parse does the already-landed, SL-5-owned `verify_reviewtruth_evidence.py finalize-record` mode write the write-once post-parser durable record at `docs/research/reviewtruth-final-evidence-record.md`, recording the exact broad-final and phase-final XML digests, both parser-attestation digests, and the exact frozen `docs/research/reviewtruth-phase-verification.md` digest and the one frozen `docs/research/reviewtruth-real-panel-smoke.md` digest the live board and wrappers consumed; no pre-final doc is edited after its staging/review point. The separate minimal `final-record` mode then recomputes every recorded digest from the artifact bytes and emits its attestation to `.phase-loop/evidence/reviewtruth-final-record-attestation.json` and the canonical ledger; its own result is never required inside the record it verifies, and no test wrapper may invoke `finalize-record` or `final-record` or read their outputs.

  The same immutable SL-5 executable owns the later Gate A `gate-a` reducer and its fresh internal `gate-a-attest` process. They stay outside every wrapper and finalized-record input and write only the canonical external paths `$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite.stdout`, `$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite.stderr`, `$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite.json`, and `$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite-attestation.json`. A Gate A suite output or alias beneath `.phase-loop/evidence/` is forbidden. The canonical ledger closeout binds the external absolute paths plus their recomputed digests; it does not copy them into the repo-local namespace.

  The four-seat closeout review and ledger closeout bind the finalized record digest, the `final-record` attestation, and the Gate A suite attestation before closeout, and every closeout verdict is written only to the canonical ledger, never into the record or any wrapper-consumed artifact. Each child emits its own PID/start-time, HEAD/ref, module/conftest paths, source digests, exact command, collection activation/deselection facts, XML path/digest, and parser-attestation path/digest. No invoking shell assigns `REVIEWTRUTH_JUNIT_XML` and expands that newly assigned value itself: task commands use literal paths, while Verification uses `env REVIEWTRUTH_JUNIT_XML=<literal> sh -c '... "$REVIEWTRUTH_JUNIT_XML"'` so expansion occurs only in the child shell after `env` has populated its environment. A TUI, daemon, worker, parent interpreter, or other process that loaded pre-edit `panel_invoker`, `runner`, `train_runner`, `train_ledger`, or related runtime modules may launch the child but may not attest the modified code or panel result itself.
- [ ] PC-REVIEWTRUTH-5 — `phase-loop-runtime/tests/conftest.py` owns the post-bootstrap executable dual-mode collection and deselection-provenance contract. It consumes only committed literals/digests independently derived from the write-once pre-edit source observation plus the paired unmodified Gate-A-layout observation; it never claims to have observed the past. It freezes the exact pre-edit source/CI full/selected collection digests and allowed post-SL-1 transformation; the separately derived Gate-A full/selected sets and exact 48-nodeid delta; the restricted source collection/runtime skip baselines; the exact four-tuple collection boundary and complete 59-tuple runtime boundary; the three expected Gate-A union sets; every tuple's full canonical nodeid/phase/reason plus per-set count/digest; the exact five full repo-relative nodeids in `REVIEWTRUTH_POST_PARSER_NODEIDS`; the exact pre-edit marker-filter tuple `REVIEWTRUTH_BROAD_MARKER_DESELECTED_NODEIDS`; the allowed source/CI versus Gate-A collection-plugin/root behavioral origin profiles; the exact environment name `PHASE_LOOP_REVIEWTRUTH_POST_PARSER_COLLECTION`; the sole accepted value `junit-run:final:v1`; and the predicate `os.environ.get("PHASE_LOOP_REVIEWTRUTH_POST_PARSER_COLLECTION") == "junit-run:final:v1"`. Its try-first/try-last hooks canonicalize the full pre-selection and selected nodeids from source-root, `phase-loop-runtime/` working-directory, and Gate-A copied-tree collection; select the expected profile only from the verified source-root/sibling boundary; and record built-in `-m "not dotfiles_integration"` deselections, wrapper-hook notification, collection skips, and runtime skips as four non-substitutable categories. Its `pytest_deselected` observer rejects a nonempty `--deselect` option or any arbitrary deselection source. In the ordinary broad arm, the wrapper hook runs after marker selection, requires all five exact wrappers still collected, removes exactly those items, calls `pytest_deselected` for exactly that list, and at session end requires the observed full/selected sets, normalized collection-plugin/root profile, deselection multiset, collection skips, and runtime skips to equal the selected profile with exact per-category counts/digests. The source/CI profile requires the frozen post-SL-1 source collection and semantic source skip baseline after applying only PC-REVIEWTRUTH-5A/5B/5C and retaining each disposition's raw evidence. The Gate-A profile separately requires `observed_collection_skips == REVIEWTRUTH_GATE_A_RESTRICTED_SOURCE_COLLECTION_SKIP_TUPLES ∪ REVIEWTRUTH_GATE_A_BOUNDARY_COLLECTION_SKIP_TUPLES`, `observed_runtime_skips == REVIEWTRUTH_GATE_A_RESTRICTED_SOURCE_RUNTIME_SKIP_TUPLES ∪ REVIEWTRUTH_GATE_A_BOUNDARY_RUNTIME_SKIP_TUPLES`, and their union equal `REVIEWTRUTH_GATE_A_EXPECTED_SKIP_TUPLES`; it therefore consumes both the retained source/CI baseline and the complete clean-room-only boundary, never just the boundary delta, and applies none of the three dispositions. Neither profile may be substituted for the other, and collection/runtime tuples cannot cross categories. The normalized profile preserves exact application-plugin entry points and repo-owned origins and rejects ambient, autoloaded, unapproved, or origin-changed collection plugins; it does not compare pytest/pluggy or approved core-plugin distribution versions, absolute module paths, or module digests. It never converts wrappers or boundary collection skips to another category and never keys on `REVIEWTRUTH_CAPABILITY_MARKER`, `PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH`, generic truthiness, CI, evidence-file presence, a run-local baseline file, or a caller-selected profile flag. When the final predicate is true, it removes none of the five; each wrapper independently requires the final runner/broad-final attestation before executing its strict assertion, so setting the environment value by hand cannot produce a vacuous pass. SL-1 freezes the hook file digest, observer-payload digest, behavioral collection/plugin/root profiles, all tuples/counts/digests, predicate, category reasons/accounting, all three singleton disposition contracts, final-runner activation, and mutation tests that kill bootstrap-byte/attestation/raw-artifact drift; source or Gate-A full/selected-set drift; removal/addition/reason/phase/category mutation of each one of the four collection-boundary or 59 runtime-boundary tuples; loss/addition of any retained source-baseline tuple; a wrong `39 + 4 + 59 = 102` union; unexpected sibling/root presence or unrelated absence; marker-baseline drift; a missing/renamed/extra wrapper; a truthy/wildcard env predicate; marker-driven collection; failure to notify `pytest_deselected`; external `--deselect`; arbitrary third-party/collection-capable plugin loading or origin substitution; category swapping; any malformed/unattributed PyPI skip, malformed/unattributed console-script skip, second network-normalized node, second console-normalized node, or console normalization outside exact source-layout provenance; and final activation before broad-final attestation. It also freezes the paired controls from PC-REVIEWTRUTH-2: provenance-only pytest/pluggy version/path/digest substitutions with identical semantic behavior pass, while a toolchain change that alters collection/plugin origin/nodeids/skip/deselect/exit/JUnit/result behavior fails. Ordinary suite, GitHub CI, default/broad/candidate/broad-final, and fresh source-clone subprocess controls prove the immutable source/CI post-SL-1 profile and exact PC-REVIEWTRUTH-5A/5B/5C dispositions; Gate A copied-tree controls prove only the immutable Gate-A profile and the complete unnormalized baseline-plus-boundary union; both prove exact repo-owned bytes, marker baseline plus exactly five hook-owned deselections, their allowed behavioral plugin/root profile, and GREEN. A final-phase subprocess proves all five strict assertions execute exactly once with zero phase deselections. SL-2 through SL-6 may neither edit nor replace this hook.
- [ ] PC-REVIEWTRUTH-5A — Portable skip classification has exactly one narrowly named environment-dependent disposition. `REVIEWTRUTH_PORTABLE_ENVIRONMENT_DISPOSITION_NODEIDS` is the literal singleton `phase-loop-runtime/tests/test_cr_fixes_pr220.py::test_bare_python_below_floor_shims_even_when_python3_satisfies`, count `1`, sorted-LF SHA-256 `866c44921f3cba820cd182671f5df21ed4f51191105effa047958924de916d8a`. Source checkout and GitHub CI must collect and execute that node exactly once; it is never excluded, deselected, xfailed, moved into a broad exemption, or admitted to Gate A's boundary sets. Its normalized semantic outcome is exactly one of: `portable_pass` when both literal interpreter paths exist and the test passes, or `environment_interpreter_pair_unavailable` only when the node skips for the exact reason `need both python3.10 and python3.12 on host` and at least one of `/usr/bin/python3.10` or `/home/viperjuice/.local/bin/python3.12` is absent. The source/CI raw skip-set comparison removes only that one validated interpreter disposition before comparing the remaining canonical baseline; a different reason, both paths present with a skip, either path absent with failure/error, missing/duplicate node, or any second interpreter-normalized node is drift. Gate A retains its independent exact 39+4+59 tuple contract unchanged and cannot use this normalization to erase a Gate-A skip. The literal RED falsifier `phase-loop-runtime/tests/test_reviewtruth_phase.py::test_reviewtruth_portable_interpreter_pair_disposition_normalizes_host_dependent_skip`, singleton sorted-LF SHA-256 `c36541be134c6256e39693869d2038efb47eb8efe2ab099dd701f24c7dfe70cd`, exercises pass, legal unavailable, wrong-reason, both-present-skip, failure, error, duplicate, and broad-exclusion arms and binds the normalized disposition into bootstrap, candidate, CI-matrix, final, and closeout evidence.
- [ ] PC-REVIEWTRUTH-5B — Exact-node PyPI availability has one separate, non-portable and non-broad network disposition. `REVIEWTRUTH_PYPI_AVAILABILITY_DISPOSITION_NODEIDS` is the literal singleton `phase-loop-runtime/tests/test_release_pin_autotrack.py::test_release_pin_is_not_behind_pypi_latest`, count `1`, sorted-LF SHA-256 `7a54c34a8defee59045a9dfe403a5d89b2d87085ceb99358dde782184b87de6c`. Source bootstrap, source checkout, candidate, broad-final/final, and each required GitHub CI job on Python 3.10, 3.11, and 3.12 must collect and execute that node exactly once; it is never excluded, deselected, xfailed, converted to a session-wide network posture, admitted to PC-REVIEWTRUTH-5A, or admitted to a Gate-A boundary set. Its normalized semantic outcome is exactly one of: `pypi_metadata_available_pass` when the node passes, or `pypi_transport_unavailable` only when the call-phase report is a skip attributed to the exact line-116 branch in `phase-loop-runtime/tests/test_release_pin_autotrack.py` at file SHA-256 `6b6c7f9f38bc815f37e2a3d86311867ea5a8ea907db2bad7d52fdeb0132b4d24`. For the unavailable arm, the structured report longrepr must be the exact three-tuple `(repo-owned source path, 116, message)` and the message must equal the literal prefix `Skipped: PyPI unreachable (` plus one nonempty raw exception diagnostic plus the literal suffix `); auto-track vs registry not checked offline`. The parser must parse the sealed bootstrap longrepr structurally, not by substring replacement, and must independently verify the bound source bytes/AST still contain the line-115 caught transport tuple `(urllib.error.URLError, TimeoutError, OSError) as exc` immediately governing that exact f-string `pytest.skip` call; direct conftest observation validates the same tuple fields before normalization. This source/line/AST binding is what proves the skip arose from a qualifying caught transport exception rather than arbitrary matching text. Every source/CI record retains the complete raw normalized longrepr, raw message, unmodified exception diagnostic, phase, line, nodeid, source digest, and semantic disposition for diagnostics. Only after all checks pass may that one raw tuple be removed before semantic source/CI skip equality. A wrong reason; empty diagnostic; malformed, missing, or extra prefix/suffix; wrong path, line, phase, or source digest/AST; a skip not attributable to that branch; failure, error, or xfail; a missing or duplicate node; or any second network-normalized node is drift. Gate A never applies this disposition: its same node's line-111 standalone/root-missing skip `Skipped: RELEASE_PIN not reachable (standalone package)` remains one of the exact four `test_release_pin_autotrack.py` runtime-boundary tuples, all Gate-A tuple bytes/counts/digests remain unchanged, and `39 + 4 + 59 = 102` remains exact. The literal RED falsifier `phase-loop-runtime/tests/test_reviewtruth_phase.py::test_reviewtruth_exact_pypi_transport_disposition_normalizes_only_source_attributed_skip`, singleton sorted-LF SHA-256 `b8d7fedfe0b72b0f6e23d83a026c747a1a868630459bdb692b26b99b48b411a5`, uses synthetic structured reports and source fixtures to exercise reachable pass; each qualifying caught transport class; legal unavailable with raw diagnostic retention; wrong/malformed reason; wrong line/source/phase; unattributable same-text skip; failure, error, xfail, missing, duplicate, and second-network-node arms; and explicit rejection of Gate A normalization. Its RED anchor is `REVIEWTRUTH_RED::exact_pypi_transport_disposition`. The exact-PyPI falsifier is one member of the two-node `REVIEWTRUTH_SL1_INFRASTRUCTURE_TDD_NODEIDS` pair frozen by PC-REVIEWTRUTH-5C; both nodes follow the displayed literal RED/then-GREEN order before broad-baseline parsing and neither enters the downstream activated-RED set. Its raw/semantic evidence is bound into bootstrap/broad-baseline, source/default, candidate, the Python 3.10/3.11/3.12 CI matrix, broad-final/final, finalized-record and `final-record` attestations, the implementation panel, the four-seat closeout, and the canonical ledger. No live internet is required for GREEN.
- [ ] PC-REVIEWTRUTH-5C — Exact-node source-layout console-script availability has one separate, local, non-broad disposition. `REVIEWTRUTH_CONSOLE_SCRIPT_AVAILABILITY_DISPOSITION_NODEIDS` is the literal singleton `phase-loop-runtime/tests/test_export_schema.py::test_console_script_check_smoke`, count `1`, sorted-LF SHA-256 `582d2f4aa8395d9fa1205c9c7d52ea3b6a31b2f5750357c012a5c688b028def9`. Source bootstrap, source checkout, default, candidate, broad-final/final, every fresh-clone source suite, each required GitHub CI job on Python 3.10, 3.11, and 3.12, and Gate A must collect and execute that node exactly once; it is never excluded, deselected, xfailed, admitted to PC-REVIEWTRUTH-5A or PC-REVIEWTRUTH-5B, converted into a command/PATH-wide exemption, or admitted to a Gate-A boundary set. Its normalized semantic outcome is exactly one of: `console_script_available_pass` when the node passes, or `source_layout_console_script_unavailable` only when a call-phase skip is attributed to the exact line-189 branch in `phase-loop-runtime/tests/test_export_schema.py` at file SHA-256 `355d74e6bbe823ecd0091e4cdb109b491e07ac5090d1a18a18e3e4a68bee4f06`. The unavailable structured longrepr must be the exact three-tuple `(repo-owned source path, 189, "Skipped: phase-loop console script not on this interpreter")`. The parser and direct conftest observer must independently bind the loaded `phase_loop_runtime` module to the exact repo-owned `phase-loop-runtime/src/phase_loop_runtime/` tree, require the observed `CI` key absent, record the exact absolute `sys.executable`, derive exactly `Path(sys.executable).with_name("phase-loop")`, and contemporaneously require `.exists()` false when the skip report is observed. The parser also verifies the bound source bytes/AST still contain the exact line-187 sibling derivation, line-188 negated existence guard, and immediately governed literal line-189 `pytest.skip` call. Every source record retains the complete raw normalized longrepr, raw message, phase, line, nodeid, source digest, interpreter path, derived sibling path, source-module provenance, `CI` observation, existence result, and semantic disposition. Only after every check passes may that one tuple be removed before source-layout semantic skip equality. A wrong reason, path, line, phase, source digest/AST, interpreter-derived path, module origin, missing provenance, `CI` present, sibling `.exists()` true, failure, error, xfail, missing or duplicate node, or any second console-normalized node is drift. Bootstrap, Gate A, GitHub CI, and every other package-installed environment must have the adjacent generated console script and the node must pass; the classifier rejects unavailable normalization there even if a matching raw reason is injected. Gate A therefore applies none of PC-REVIEWTRUTH-5A, PC-REVIEWTRUTH-5B, or PC-REVIEWTRUTH-5C and its exact `39 + 4 + 59 = 102` tuple contract remains unchanged. The literal RED falsifier `phase-loop-runtime/tests/test_reviewtruth_phase.py::test_reviewtruth_exact_console_script_availability_disposition_normalizes_only_source_layout_skip`, singleton sorted-LF SHA-256 `f548fec9689ec46975a085dd4dd1fee250ee6f199a0d6ae970b20beeb2a41640`, uses only synthetic structured reports, source AST fixtures, and path/provenance records to exercise source pass; legal source-layout unavailable with all raw diagnostics retained; wrong reason/path/line/phase/source/AST; wrong sibling derivation; present sibling; package-installed, `CI`, bootstrap, and Gate-A matching skips; failure, error, xfail, missing, duplicate, and second-console-node arms. Its RED anchor is `REVIEWTRUTH_RED::exact_console_script_availability_disposition`. Together with the exact-PyPI falsifier, `REVIEWTRUTH_SL1_INFRASTRUCTURE_TDD_NODEIDS` is the exact sorted pair, count `2`, sorted-LF SHA-256 `ad528b11ad08a3989aee135fcaf6fc5449d00da8188a074c5a126712924e2758`. SL1-T1 authors only those two literal falsifiers and proves each immutable node RED at its own anchor; SL1-T2 implements only their parser/conftest classifier contracts and proves each same node GREEN before broad-baseline parsing and the tests-only panel/landing. The console falsifier is added mechanically to `REVIEWTRUTH_EXPECTED_NODEIDS`, `REVIEWTRUTH_PHASE_NODEIDS`, `REVIEWTRUTH_NEW_NODEIDS`, `REVIEWTRUTH_SL1_INFRASTRUCTURE_TDD_NODEIDS`, and every corresponding count/sorted-LF digest and anchor map, but is excluded from `REVIEWTRUTH_ACTIVATED_RED_NODEIDS` after its own SL-1 GREEN transition. Its raw/semantic evidence is bound into source bootstrap/default, fresh clone, candidate, the Python 3.10/3.11/3.12 CI matrix, broad-final/final, finalized-record and `final-record` attestations, the implementation panel, four-seat closeout, and canonical ledger. GREEN requires no live network or external command.
- [ ] PC-REVIEWTRUTH-6 — Native-fill identity is non-colliding and exactly once. One board invocation allocates a unique stable `seat_instance_id` for every requested seat instance, including twins with the same non-unique `seat_key`. Every emitted `NativeAgentLegRequest` carries a fresh globally unique `request_id` and a fresh `attempt_id`; retry/re-emission keeps only that seat's `seat_instance_id` and allocates both other identities anew, never reusing or reviving an earlier tuple. The request and `NativeAgentLegReport` echo the exact `(request_id, seat_instance_id, attempt_id)` plus `seat_key`, `artifact_digest`, `brief_digest`, `lens_digest`, and `prompt_digest`. `bind_native_agent_leg_result()` can consume exactly one current pending attempt whose entire identity/digest tuple matches and whose report is terminal; successful consumption atomically closes that attempt, updates only its one seat instance, and can increase `PanelResult.reviewed_seat_count` at most once. Unknown request, late superseded attempt, stale prior-board attempt, replayed consumed report, cross-seat substitution, colliding-seat substitution, any identity/digest mismatch, or non-terminal report is rejected with a typed binding disposition, cannot mutate a leg or raw/grounded count, and cannot bind a current retry. The canonical ledger durably records metadata-only emitted/pending/superseded/consumed/rejected transitions and reconstructs those sets before native fill resumes, so process restart cannot forget a consumed identity or re-inflate the reviewed count.
- [ ] PC-REVIEWTRUTH-7 — EC-REVIEWTRUTH-16 is a three-node literal TDD contract in the already-owned `phase-loop-runtime/tests/test_reviewtruth_phase.py`: `test_reviewtruth_sl2_ec_reviewtruth_16_preflight_composition_attests_only_fable_prover` (singleton sorted-LF SHA-256 `25df82bfae34123dfa0f86ee6e5b9ec8abb47bd37599930fdc3a98658623058f`, RED anchor `REVIEWTRUTH_RED::prover_capability_attestation`), `test_reviewtruth_sl4_ec_reviewtruth_16_required_prover_hard_blocks_even_proceed_degraded` (`4e3a976a1de1a00208c4098f6bf46f2af1b4084d7afd9cfa1348c01d86bc7dbd`, `REVIEWTRUTH_RED::required_prover_hard_block`), and `test_reviewtruth_sl5_ec_reviewtruth_16_capability_flows_to_durable_output_and_self_application` (`b6fd64fb1a9fc605d3f9c723b9f135f88fd0c1f9bf7379869e1470ea53318ff6`, `REVIEWTRUTH_RED::prover_self_application`). Their exact sorted triple has count `3` and sorted-LF SHA-256 `a0c5e27f76e5eec8349cc65196fed6dc5806aca9f0f211eb81287c93436935e3`; SL-1 adds all three to `REVIEWTRUTH_EXPECTED_NODEIDS`, `REVIEWTRUTH_PHASE_NODEIDS`, `REVIEWTRUTH_NEW_NODEIDS`, `REVIEWTRUTH_ACTIVATED_RED_NODEIDS`, and the exact anchor map, then mechanically recomputes every affected count/digest. The tests freeze `AuthPreflightResult.metadata.execution_capability` as a strict seat-bound record; composition's exact per-seat capability rows with only `claude`/`claude-fable-5`/`correctness` prover-capable; static-capable versus actually usable separation; existing `Seat`/`Board` positional constructor compatibility through append-only defaulted schema fields; `RatificationPolicy.required_prover: bool = True` appended after `on_shortfall`; four-argument policy constructor compatibility; `BoardFacts.reviewed_sha` retained in slot five and `prover_usable: bool = False` appended after it; exact all-four-gate `DEFAULT_RATIFICATION_POLICIES` values `required_vendors=3`, `required_lens_coverage=3`, `required_prover=true`, and unchanged consensus/action values; `gate_posture.resolve_ratification_policy` accepting typed additive `required_prover` overrides alongside every existing field without fixed-gate hardcoding; hard `ESCALATE` plus `prover` shortfall only when the effective policy requires a prover and one is absent, even under `proceed_degraded`; an explicit `required_prover=false` override removing only that shortfall while preserving all other effective fields/actions; ordinary vendor/lens shortfalls still following `on_shortfall`; strict manifest parsing; capability flow only from an attested Fable seat whose identity-bound result is reviewed, grounded, and artifact-bound; durable effective-policy/facts/verdict/ledger/run-summary output; and the no-direct-`claude -p` four-usable-AGREE procedural root-panel record for not-yet-bound v10 gates. PATH/auth alone, any vendor prover grant, static composition/native-request/spawn without a usable bound review, malformed/missing capability metadata, default-true `prover_usable`, moved `reviewed_sha`, constructor breakage, default floor 2, ignored/rejected/overbroad override, hardcoded gate/consensus/shortfall behavior, downgraded missing-prover status under an effective required policy, omitted durable fields, `agent-harness#405` authority, or v10 self-application without usable Fable fails. This is the maintainer-named `IF-0-POLICY-1` contract and is published through owner-qualified roadmap gate `IF-0-REVIEWTRUTH-2`.
- [ ] PC-REVIEWTRUTH-8 — EC-REVIEWTRUTH-17 is an exact 16-node literal TDD contract: eight nodes in `phase-loop-runtime/tests/test_reviewtruth_phase.py` and eight in the already-owned `phase-loop-runtime/tests/test_phase_worktree_executor.py`, count `16`, exact sorted-LF SHA-256 `c54d268bafd176e0d22c179eac2a175f208eb2c28f73027982d9c7780dc2219a`. The exact nodeids are `test_review_wave_plan_design_allows_critics_first_but_requires_early_probe_before_fable`, `test_review_wave_premerge_release_stages_early_prover_evidence_before_critics`, `test_review_wave_capabilities_distinguish_can_probe_from_binding_prover`, `test_review_wave_bundle_binds_input_head_bundle_and_evidence_digests`, `test_review_wave_contradicting_prover_invalidates_agree_and_requires_updated_bundle_rereview`, `test_review_wave_unconfined_grok_records_degraded_evidence_without_launch`, `test_review_wave_gemini_is_never_selected_as_write_capable_prover`, and `test_review_wave_predecessor_critic_artifacts_do_not_count_before_early_codex_evidence` under the first file; and `test_early_prover_codex_uses_cli_workspace_write_in_per_leg_ephemeral_worktree`, `test_early_prover_serial_holder_gets_distinct_data_scope_and_exact_digest_binding`, `test_early_prover_external_reaper_cleans_crash_residue_without_leg_authority`, `test_early_prover_codex_external_tool_policy_and_effective_preflight_fail_closed`, `test_early_prover_external_tool_policy_preflight_and_receipt_are_digest_bound`, `test_early_prover_coordinator_rejects_unusable_workspace_mount_before_leg_launch`, `test_early_prover_custom_writable_workspace_mount_flows_through_worktree_creation`, and `test_early_prover_real_workspace_mount_is_used_when_safely_available` under the second. The artifact-bound evidence node includes zero-byte/noncanonical artifact, empty/sentinel/verdict-only review, forged outer usability/outcome/verdict/vendor/lens/capability, duplicate seat-instance, grounding-entry, and consumed-bundle substitutions; its positive control derives all seat facts from strict authoritative `v10.review-seat-artifact.v1` bytes. Their exact corresponding anchors are `REVIEWTRUTH_RED::plan_design_gate_order`, `REVIEWTRUTH_RED::premerge_release_prover_first`, `REVIEWTRUTH_RED::capability_role_separation`, `REVIEWTRUTH_RED::artifact_bound_evidence`, `REVIEWTRUTH_RED::contradiction_re_review`, `REVIEWTRUTH_RED::degraded_unconfined_grok`, `REVIEWTRUTH_RED::gemini_ineligible`, `REVIEWTRUTH_RED::predecessor_critic_evidence`, `REVIEWTRUTH_RED::codex_workspace_write`, `REVIEWTRUTH_RED::per_leg_worktree_data_isolation`, `REVIEWTRUTH_RED::external_reaper`, `REVIEWTRUTH_RED::codex_external_tool_preflight`, `REVIEWTRUTH_RED::external_tool_receipt_digest_binding`, `REVIEWTRUTH_RED::workspace_mount_preflight`, `REVIEWTRUTH_RED::workspace_mount_custom_positive`, and `REVIEWTRUTH_RED::workspace_mount_real_positive`; exact sorted-LF anchor digest `8d175395fd67f2a9297a5b8fdb06f57bfa8595a268746a165ab9878d4d371e05`.

  SL-1 authors all 16 tests before any implementation and proves every exact node RED only at its mapped anchor. Stage B mechanically adds them to `REVIEWTRUTH_EXPECTED_NODEIDS`, `REVIEWTRUTH_PHASE_NODEIDS`, `REVIEWTRUTH_NEW_NODEIDS`, `REVIEWTRUTH_ACTIVATED_RED_NODEIDS`, and `REVIEWTRUTH_RED_ANCHORS_BY_NODEID` and recomputes every aggregate count/digest; this Stage-A plan deliberately does not invent those future aggregates. The tests freeze additive defaulted `ExecutionCapabilityAttestation(can_probe, binding_prover, sandbox_mode, os_confinement)` fields on the existing schema/composition path; a gate-aware `ReviewWavePolicy`/`ReviewWaveEvidence` staging contract in `panel_invoker.py`; `CodexExternalToolPolicy`, `CodexExternalToolPreflightReceipt`, `CodexEarlyProverLaunchReceipt`, and `run_codex_external_tool_preflight()` (or equivalently named additions to the existing launcher/worktree seams); and the existing `phase_worktree_executor.py` worktree/reaper seam extended for explicit mount preflight and early prover leases. Codex primary must be launched only through an explicit additive `launcher.py` mode whose argv contains `--sandbox workspace-write`, `--strict-config`, `--ephemeral`, `--ignore-user-config`, and `--ignore-rules`; contains exact config overrides `approval_policy="never"`, `web_search="disabled"`, `sandbox_workspace_write.network_access=false`, `sandbox_workspace_write.writable_roots=[]`, `sandbox_workspace_write.exclude_tmpdir_env_var=true`, and `sandbox_workspace_write.exclude_slash_tmp=true`; contains no `--add-dir`, remote, search, browser, computer, hook-trust, profile, sandbox-bypass, or temporary-directory grant; explicitly overlays `mcp_servers={}` and a complete same-transport inert `enabled=false` replacement for every discovered layered MCP server; and passes one explicit `--disable <name>` for every member of the frozen Stage-B external-feature denylist. Both exclusion booleans are mandatory launch-policy facts, not optional defaults: `/tmp` and the `TMPDIR` variable confer no additional writable authority, while launch `TMPDIR` resolves canonically inside the per-leg worktree/data-scope boundary and is writable only because that containing worktree is already authorized. The minimum denylist grounded in installed `codex-cli 0.145.0` is exactly `apps`, `apps_mcp_path_override`, `auth_elicitation`, `browser_use`, `browser_use_external`, `browser_use_full_cdp_access`, `code_mode`, `code_mode_buffered_exec`, `code_mode_host`, `code_mode_only`, `collaboration_modes`, `computer_use`, `deferred_executor`, `enable_fanout`, `enable_mcp_apps`, `exec_permission_approvals`, `executor_capability_discovery`, `external_agent_memory_import`, `external_migration`, `goals`, `guardian_approval`, `hooks`, `image_generation`, `in_app_browser`, `memories`, `mentions_v2`, `multi_agent`, `multi_agent_mode`, `multi_agent_v2`, `network_proxy`, `plugin_hooks`, `plugin_sharing`, `plugins`, `realtime_conversation`, `remote_control`, `remote_models`, `remote_plugin`, `request_permissions_tool`, `request_rule`, `respect_system_proxy`, `responses_websockets`, `responses_websockets_v2`, `search_tool`, `skill_env_var_dependency_prompt`, `skill_mcp_dependency_install`, `skill_search`, `standalone_web_search`, `tool_call_mcp_elicitation`, `tool_search`, `tool_suggest`, `use_agent_identity`, `web_search_cached`, `web_search_request`, and `workspace_dependencies`. Stage B must classify the complete canonical feature inventory, retain at least this set unless the canonical CLI removes a name, add every new semantically external/dynamic surface, and reject any unknown row rather than guessing it safe. The installed removed rows `tool_search_always_defer_mcp_tools=true` and `tui_app_server=true` are not callable `codex exec` tool surfaces and are classified only as inert dependency-routing/internal-transport metadata after `tool_search=false`, `apps=false`, and zero enabled MCP/plugin rows are independently proved; if a future CLI makes either callable or otherwise authority-bearing, it moves into the denylist and an ineffective override rejects launch.

  Before launch, the coordinator runs the exact canonical Codex executable with the exact launch override tuple in read-only effective probes. It freezes the executable realpath/digest, version and relevant help digests, the complete feature-name/value inventory, the effective workspace-write network/writable-root settings, both effective temporary-directory exclusion booleans, the canonical launch `TMPDIR` path and its containment under the per-leg worktree/data scope, the pre-override configured MCP name/transport inventory, the generated complete replacement tuple, a post-override zero-enabled MCP inventory, and the effective plugin inventory. It requires network access false, no writable root beyond the per-leg worktree, `exclude_tmpdir_env_var=true`, `exclude_slash_tmp=true`, no `/tmp` authority, no `TMPDIR`-derived authority outside the already-authorized worktree boundary, every prohibited feature false, every discovered MCP entry still present only as the expected inert disabled same-transport replacement, zero enabled MCP servers, and plugins disabled/empty. Nonzero or unparseable output, an unknown relevant surface, either missing/false exclusion, a `TMPDIR` outside the worktree/data-scope boundary, enabled value, locked or ineffective override, executable/config/inventory drift between probes and launch, or any uninspectable surface returns a typed preflight failure. That failure emits a canonical degraded no-launch receipt with `codex_process_count=0`; it must never fall through to a Codex launch. If the CLI cannot prove effective state, Codex may run only under a positive OS-level confinement receipt independently proving that the process cannot reach the live tree, shared data, `/tmp`, an external `TMPDIR`, configured external tools, browser/computer services, or other host authority; absent that receipt, no Codex process launches. `--sandbox workspace-write` and `--ignore-user-config` are never accepted as proof of those host-side properties.

  `CodexExternalToolPolicy` is strict canonical JSON with schema, required flags and config overrides in launch order, prohibited argv grants, sorted feature denylist, MCP discovery/replacement rule, required zero enabled MCP/plugin counts, required network/writable-root values, both required exclusion booleans set to true, the contained-`TMPDIR` rule, unknown-surface action, uninspectable-surface action, and OS-confinement fallback rule. The strict effective-config receipt, whether a named `CodexEffectiveConfigReceipt` or an equivalently explicit subrecord of `CodexExternalToolPreflightReceipt`, contains the exact canonical `TMPDIR`, worktree/data-scope boundary, empty extra-writable-root set, `network_access=false`, `exclude_tmpdir_env_var=true`, `exclude_slash_tmp=true`, and proof that neither `/tmp` nor `TMPDIR` added authority. `CodexExternalToolPreflightReceipt` is strict canonical JSON with schema; policy and effective-config-receipt digests; executable realpath/digest; version/help digests; exact override-argv digest; full feature inventory/digest and classified-name coverage; the same effective network/writable-root/exclusion/contained-`TMPDIR` values; pre-override MCP rows/digest, replacement rows/digest, post-override rows/digest, and enabled count; plugin rows/digest and enabled count; raw input/HEAD/tree/worktree/data-scope receipt digests; verdict/reasons; and optional OS-confinement receipt digest. `CodexEarlyProverLaunchReceipt` is strict canonical JSON with schema; policy, effective-config, and preflight digests; the same raw context digests and exact network/writable-root/exclusion/contained-`TMPDIR` values; one-use authorization identity; `launched`; PID/process-start identity when launched; exit/output digest; and `codex_process_count`. Unknown or extra trust-root fields fail. A preflight PASS requires zero enabled external rows, complete classification, exact network/writable-root values, both exclusions true, contained `TMPDIR`, and no failure reason; launch authorization is a separate one-use transition bound to that receipt. A FAIL requires a launch receipt carrying both exclusions as true policy requirements with `launched=false` and `codex_process_count=0`.

  Before any early-prover or critic leg can launch, the external coordinator selects one explicit `workspace_mount`; ambient defaulting inside the confined leg is forbidden. The coordinator canonicalizes the supplied absolute path with all ancestors resolved, requires the mount and its coordinator-created `worktrees/` parent to be real non-symlink directories owned by the coordinator UID, writable and searchable by that UID, not group/other-writable, outside the source worktree and its Git common directory, and backed by at least the Stage-B-frozen minimum free bytes and inodes. It creates and removes an owner-only probe file and directory, proves the canonical `lane_worktree_root(repo, workspace_mount=workspace_mount)` is exactly `<workspace_mount>/worktrees`, and passes that same explicit `workspace_mount` through every `create_phase_worktree(..., workspace_mount=workspace_mount)` and early-prover worktree call. Missing, implicit, relative, noncanonical, symlinked, wrong-owner, insufficient-permission, insufficient-space/inode, escaping, or source-containing mounts fail closed with `leg_launch_count=0`, `codex_process_count=0`, and `grok_process_count=0`; no leg is asked to create its parent.

  Only after that preflight does the coordinator create one owner-only per-leg ephemeral Git worktree strictly beneath the selected `lane_worktree_root`, allocate a distinct nested per-leg data-scope and `TMPDIR`, and hand the already-created worktree to the confined leg. Every resulting real path must remain contained beneath the selected root; names are fresh and non-reused per attempt; one serial write-capable lease exists at a time; and cleanup authority belongs only to an out-of-leg external coordinator reaper that records normal and crash teardown without granting the leg parent-creation or reap authority. The custom-mount positive control uses `tmp_path` to create and preflight a writable non-symlink mount, passes it explicitly through both APIs, launches the confined fake leg only after the parent/worktree exists, proves worktree and nested-`TMPDIR` writes, then proves reaper-only cleanup. The real-path positive control exercises `/mnt/workspace` with the same explicit call path only when the coordinator's safety preflight says it is owned/usable and has the frozen free-space/inode floor; otherwise it records the typed safe-unavailable zero-launch result rather than failing because the confined leg cannot create `/mnt/workspace/worktrees`. Neither control permits writes to `/tmp`, an unrelated external `TMPDIR`, the live tree, or shared data.

  The digest chain is deliberately acyclic: first compute the raw exact input, HEAD, tree, canonical selected-mount/preflight, worktree, data-scope, and bundle-input receipt digests; next bind those raw digests and the external-tool policy and effective-config-receipt digests into the effective preflight receipt; then bind the policy/config/preflight/launch-or-no-launch receipt digests back into the final input/head, worktree, and data evidence envelopes; finally bind every raw and envelope digest plus output into the evidence-bearing bundle. A substitution, omission, reordering, mismatch, defaulted mount, or attempted self-referential digest invalidates the evidence. The leg cannot create the parent mount, reap itself, access the live worktree/shared data, gain `/tmp` or external-`TMPDIR` authority, or claim `binding_prover`.

  Grok is selected only after a typed Codex preflight failure and only with a real `OSConfinementAttestation` proving a throwaway container or dedicated low-privilege identity has access solely to the ephemeral worktree and isolated data scope. Without that proof, no Grok process is launched and a digest-bound degraded-evidence audit is staged. Gemini is never eligible. `PANEL_LEGS`, existing non-review `danger-full-access`, existing review `read-only`, and non-review goldens remain byte-compatible; none satisfies this new path. Plan/design may collect critics first but must stage early evidence before Fable. Pre-merge/release must stage early evidence before any counting critic. Every subsequent wave begins with the write-capable early leg. Any contradicting probe finding atomically invalidates prior `AGREE` records, produces an updated bundle/evidence digest, and forces all counted critics and Fable to re-review it. Only a usable grounded artifact-bound Fable result sets `binding_prover=true` or `BoardFacts.prover_usable=true`.
- [ ] IF-0-REVIEWTRUTH-1 — `REVIEWTRUTH_CAPABILITY_MARKER = "reviewtruth@1"` is the production activation marker installed in `panel_invoker.py`; it activates SL-1's immutable production assertions but never the post-parser collection hook. `PanelLegOutcome` is the exact closed vocabulary `reviewed | unavailable | errored | timed_out | refused | capped | empty` carried by `PanelLegResult.outcome`, independent of `PanelLegResult.text`; `PanelLegResult.required` and `PanelLegResult.degraded` are orthogonal typed fields; and the durable `SeatOutcomeRecord.degraded` field is orthogonal to its lifecycle status. The conditional serializer emits `"degraded":true` only when true and emits no `degraded` key when false, preserving the exact legacy/default bytes. `fab_gate._seat_outcome_from_dict()` reconstructs a present true value losslessly and maps a legacy absent key to `False`; append → strict read → rewrite → strict reread must preserve true. The dataclass-derived allowlist and explicit unknown-field rejection remain load-bearing: the implementation may add only the known `degraded` constructor argument and may not filter, ignore, or forward unknown trust-root keys. `PanelResult.reviewed_seat_count` is the raw count of identity-bound legs whose outcome is `reviewed`; it does not perform grounding. `PanelLegResult.prompt_lens_digest` is the frozen per-seat carrier for EC-REVIEWTRUTH-5: it is nonempty only when the exact rendered prompt bytes carried the declared lens and binds the declared lens to those bytes. A Fable/Opus seat deferred under a native-capable Claude host produces a `NativeAgentLegRequest` with stable unique `seat_instance_id`, fresh unique `request_id` and `attempt_id`, `seat_key`, `model`, `effort`, `lens`, artifact/brief references, exact `artifact_digest`, `brief_digest`, `lens_digest`, `prompt_digest`, and the same resolved review instructions as CLI seats. `NativeAgentLegReport` echoes that entire identity/digest tuple plus its terminal outcome and payload. Only `bind_native_agent_leg_result()` consuming a valid current pending report exactly once can replace that one seat instance's unfilled outcome and increase the raw count; it returns the typed binding disposition frozen by PC-REVIEWTRUTH-6 for every rejection. `SeatOutcomeRecord` and canonical native-fill ledger events carry the request/seat/attempt identities and content digests needed for lossless reconstruction without raw review text. `ReviewGrounding` and `GovernedBoardEvidence.grounded_reviewed_seats` are the single owned filter over raw reviewed legs; ratification passes that grounded collection to pure `classify_board_delivery(reviewed, target=4, floor=3)`, which returns exactly `full | floor_only | below_floor`, and derives vendor/lens facts only from that collection and its prompt/lens digests, never static `Seat` shape. The train approval schema serializes grounded `delivery_state` plus the exact current `review_policy_version`; `REVIEW_POLICY_VERSION` increments from `usable-reviewer-floor@1` to an explicit grounding/three-state policy identity. Train resume may skip review only when the record is `approved`, its policy version exactly equals the current version, and its typed delivery state is gate-authorizing under the train merge policy. A missing or old version, missing delivery state, a pre-migration/count-only record, `usable_reviewers=2`, or any delivery state derived from raw ungrounded usable legs forces re-review and cannot authorize a merge; valid current-policy grounded FULL/FLOOR-ONLY follows the explicit train gate policy, while BELOW-FLOOR blocks. `timed_out`, `capped`, and `empty` remain retryable and never enter the raw count; `refused` is distinct from unavailability; grounding and material-substance remain independent ratification/gate properties rather than outcome variants. BELOW-FLOOR is a classification, not a universal action: governed pre-merge, merge-class, and CLI consumers governed by EC-REVIEWTRUTH-1/4 block it, while each ratification gate consumes its typed resolved policy. Ordinary vendor/lens/consensus shortfall follows the effective `on_shortfall`; prover absence hard-blocks only when effective `required_prover=true`, including plan/design defaults, and an explicit valid false override removes only that prover requirement.
- [ ] IF-0-REVIEWTRUTH-2 — the owner-qualified roadmap gate for the maintainer-named additive `IF-0-POLICY-1` surface. It appends defaulted `RatificationPolicy.required_prover` and `BoardFacts.prover_usable`, preserves positional compatibility, extends the typed per-repo resolver with a valid boolean override including `false`, keeps gate/consensus/shortfall behavior parameterized, places only the shipped defaults at 3/3/true, and hard-blocks missing prover only when the resolved effective policy requires one.
- [ ] IF-0-REVIEWTRUTH-3 — the owner-qualified roadmap gate for PC-REVIEWTRUTH-8. It preserves legacy panel and launcher paths while adding the gate-ordered, serial, isolated, digest-bound early-prover wave whose Codex/Grok result is evidence-only and whose Fable result alone can bind an effective prover requirement. Codex launch is further gated by the exact canonical `CodexExternalToolPolicy` and effective preflight/config/launch-receipt contract: the launch tuple explicitly disables all frozen external/dynamic surfaces, requires `sandbox_workspace_write.exclude_tmpdir_env_var=true` and `sandbox_workspace_write.exclude_slash_tmp=true`, and replaces every layered MCP entry with an inert disabled same-transport definition; preflight proves the same executable/config tuple has no enabled or unknown relevant surface, no `/tmp` authority, and no `TMPDIR` authority beyond a canonical path already inside the per-leg worktree/data scope; unknown, enabled, locked, changed, uninspectable, missing-exclusion, false-exclusion, or external-`TMPDIR` state emits a digest-bound degraded receipt and launches no Codex process unless independent OS-level confinement proves the missing boundary. Before any leg launch, the external coordinator must also supply and preflight one explicit canonical writable non-symlink `workspace_mount`, pass it unchanged through `lane_worktree_root(..., workspace_mount=...)` and `create_phase_worktree(..., workspace_mount=...)`, create the isolated per-leg worktree and its parent itself, and retain sole external reaper authority; a failed mount, containment, ownership, permission, free-space/inode, ephemerality, or pass-through check produces zero leg launches. Policy/config/preflight/launch/mount/worktree/reaper receipt digests are required inputs to every head/worktree/data/output/evidence digest, and shell sandbox coverage alone is never sufficient. The final wave emits the acyclic strict `v10.review-wave-receipt.v1` wrapper above and no independent SHA-shaped review claims. This fixed safety boundary does not alter the parameterized gate policy: a valid per-repo `required_prover=false` override remains valid and changes only whether a prover is required, never the confinement or mount contract for a launch that is attempted.

  For the durable `degraded` trust-root value specifically, absence alone supplies `False`.
  Presence requires `type(value) is bool`; present `True` and present `False` pass through exactly,
  while string, integer, null, array, and object values take the existing malformed-record/
  `ProvenanceInvalid` path before construction or rewrite. Truthiness coercion is forbidden.

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

- **Scope**: Bind all three exact already-issued `agent-harness#398` maintainer directives — Option 2, parameterized prover/floor posture, and gate-dependent early-prover ordering — land one durable disposition on the target, and prove the independent protection and landing conditions before any posture-assuming implementation begins.
- **Owned files**: `docs/research/reviewtruth-leg-capability-ratification.md`
- **Interfaces provided**: `REVIEWTRUTH-capability-ratification`
- **Interfaces consumed**: none
- **Parallel-safe**: no; the human decision is satisfied, but its committed record and the independent protection/ancestry proof must precede all tests and production lanes.
- **Tasks**:
  - test: SL0-T1 — Define disposition falsifiers for read-only inspection, bounded isolated probes, execution-capability/prover policy, and gate ordering while preserving the live-tree/shared-data prohibition; freeze the strict three-comment record envelope and every rejection arm of the existing-tool coordinator proof before the record PR lands.
  - impl: SL0-T2 — Inspect effective target rules, obtain the required effective `pull_request` rule plus separate two-parent landing posture, bind exact `agent-harness#398` comments `5139465317`, `5139609713`, and `5139955591` with their immutable body digests, identities, timestamps, Option-2/prover/ordering semantics, parameterized-policy/default posture, and current-v10 procedural self-application into the strict record, bind `agent-harness#405` only as a non-authorizing implementation tracker, and merge the standalone metadata-only disposition record.
  - verify: SL0-T3 — Run the Stage-B exact coordinator proof block in `## Verification`; complete SL-0 only when it proves all three directive comments no later than merge, current effective PR-only protection and its canonical digest, available maintainer metadata, dedicated server-recorded merged PR, separate two-parent landing, fetched canonical-main reachability, unchanged record, and record-only PR/diff with no posture-assuming implementation.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command | Work |
|---|---|---|---|---|---|---|
| SL0-T1 | test | (none) | `docs/research/reviewtruth-leg-capability-ratification.md` | disposition and coordinator-proof falsifiers | exact Stage-B `REVIEWTRUTH_SL0_COORDINATOR_PROOF` block in `## Verification` after SL0-T2 | Write alternatives and falsifiers for read-only artifact inspection, bounded probes against a throwaway staged copy, execution-capability attestation, parameterized prover policy, and any narrower ratified variant; preserve the invariant that no vendor seat receives arbitrary execution against the real tree. Freeze the exact envelope keys and reject any directive's wrong issue/schema/disposition/comment/node when available/URL/body bytes/body digest/timestamps/login/association/permission when available, a missing or altered Option-2/prover/ordering semantic clause, fixed-policy hardcoding disguised as a default, any posture-object drift, any `agent-harness#405` authority/ratification/`PANEL_LEGS` widening claim, absent or insufficient available permission, any directive's creation or last edit after merge, absent/malformed effective rules, no effective `pull_request` rule, branch-rules digest drift, shallow/grafted/replaced history, missing/duplicate/non-main PR, squash/rebase/direct push, non-two-parent landing, PR-head mismatch, record drift, extra PR/diff path, and unreachable record commit. |
| SL0-T2 | impl | SL0-T1 | `docs/research/reviewtruth-leg-capability-ratification.md` | none | exact Stage-B `REVIEWTRUTH_SL0_COORDINATOR_PROOF` block in `## Verification` after merge | Inspect effective `main` rules with read-only `gh` metadata and obtain an effective `pull_request` rule through the approved admin path; this is distinct from the Git proof of an actual two-parent landing. Bind all three exact maintainer comment IDs/body SHA-256 values/timestamps, the available ratifier metadata, the disposition ID, strict Option-2 posture, parameterized prover directive, ordering/role/isolation directive, current-v10 procedural self-application, and non-authorizing `agent-harness#405` tracker object. Merge only this durable record in its own PR. The record cannot self-claim its future PR, merge commit, or run-time rules digest; SL0-T3 derives them from fetched Git/GitHub metadata. |
| SL0-T3 | verify | SL0-T2 | `docs/research/reviewtruth-leg-capability-ratification.md` | none | exact Stage-B `REVIEWTRUTH_SL0_COORDINATOR_PROOF` block in `## Verification` | Run the command from a full clone with authenticated read-only `gh` access. Its zero exit and canonical JSON stdout prove all three decisions and exact body/timestamp bindings, effective PR-only branch protection and its canonical response digest, dedicated server-recorded merged PR, separate two-parent record landing, fetched canonical-main reachability, unchanged record, and no posture-assuming implementation because both server PR files and first-parent landing diff equal the record singleton. Retain all three comment bindings and branch-rules digest/boolean for later independent comparison. |

### SL-1 — Tests-First Falsifier Lane And RED Baseline

- **Scope**: Only after the dependency-complete Stage-B plan is exact-base frozen and reviewed, land the complete REVIEWTRUTH falsifier and compatibility suite before production mutation, including the literal three-node EC-REVIEWTRUTH-16 policy contract and exact 16-node EC-REVIEWTRUTH-17 gate-order, role-separation, explicit writable-mount preflight/pass-through, external-tool preflight/receipt, isolation, reaper, evidence, contradiction, and degraded-fallback contract.
- **Owned files**: `phase-loop-runtime/tests/conftest.py`, `phase-loop-runtime/tests/test_reviewtruth_phase.py`, `phase-loop-runtime/tests/test_phase_worktree_executor.py`, `phase-loop-runtime/tests/test_train_merge.py`, `phase-loop-runtime/tests/test_governed_cross_vendor_floor_358.py`, `phase-loop-runtime/tests/test_advisor_board_golden.py`, `phase-loop-runtime/tests/test_advisor_board_research.py`, `phase-loop-runtime/tests/test_panel_invoker_spawn.py`, `phase-loop-runtime/tests/test_panel_native_fill_183.py`, `phase-loop-runtime/scripts/verify_reviewtruth_chronology.py`, `docs/research/reviewtruth-red-baseline.md`
- **Interfaces provided**: `REVIEWTRUTH-bootstrap-observation`, `REVIEWTRUTH-tests-first-baseline`, `REVIEWTRUTH-preimplementation-chronology`, `REVIEWTRUTH-evidence-wrappers`, `REVIEWTRUTH-post-parser-collection-contract`, `REVIEWTRUTH-seat-outcome-degraded-roundtrip-contract`, `REVIEWTRUTH-exact-pypi-availability-contract`, `REVIEWTRUTH-exact-console-script-availability-contract`, `REVIEWTRUTH-native-fill-identity-contract`, `REVIEWTRUTH-early-prover-wave-contract`, `REVIEWTRUTH-golden-delta-baseline`, `REVIEWTRUTH-tdd-activation`, `REVIEWTRUTH-junit-contract`, `REVIEWTRUTH-broad-compatibility-gate`
- **Interfaces consumed**: `REVIEWTRUTH-capability-ratification`
- **Parallel-safe**: no; this lane must start from the separately merged disposition record and land as a tests/evidence-only, production-change-free change before every implementation lane rebases from that target tip.
- **Tasks**:
  - test: SL1-T1 predecessor-contract preservation — After the Stage-B SL0-T3 proof and before mutation, retain the canonical rules digest and all six timestamps for all three binding comments. Use only Stage-B's exact dependency-complete base/profile literals; the historical 39/4/59/102 and 4251/3650/4203/3602 values in this Stage-A document cannot satisfy this task. Preserve and rerun every predecessor observer, collection, disposition, compatibility, native-fill, golden, chronology, and evidence falsifier, but mechanically recompute their aggregate sets/digests with the EC-REVIEWTRUTH-17 additions.
  - test: SL1-T1 EC-REVIEWTRUTH-17 arm — This arm is unavailable in Stage A and becomes executable only in the exact-base Stage-B revision. Before any production edit, author all 16 exact PC-REVIEWTRUTH-8 nodes in the two already-owned test files, add them mechanically to every Stage-B aggregate node/anchor set, and run each exact node under forced activation. Every one must fail only at its mapped `REVIEWTRUTH_RED::*` anchor; retain command, exit, stdout/stderr, exact base/tree, test bytes, nodeid-set digest `c54d268bafd176e0d22c179eac2a175f208eb2c28f73027982d9c7780dc2219a`, and anchor-set digest `8d175395fd67f2a9297a5b8fdb06f57bfa8595a268746a165ab9878d4d371e05`. The external-tool nodes inject unknown, enabled, locked, changed, and uninspectable surfaces; ineffective MCP replacement; CLI preflight failure; either temporary-directory exclusion missing or false in policy/argv/effective config/preflight/launch receipt; `/tmp` or external-`TMPDIR` write authority; falsely claimed contained `TMPDIR`; attempted launch-after-failure; and policy/config/preflight/launch-receipt digest substitution. The three mount nodes inject missing/defaulted, relative, symlinked, wrong-owner, permission-denied, too-small, inode-starved, escaping, non-ephemeral, child-created-parent, and non-reaper-owned workspace mounts and require zero leg launch. Their positive controls exercise both a coordinator-created `tmp_path` custom mount and the real `/mnt/workspace` call path when its same safety preflight passes; the confined leg begins only after the coordinator creates its parent and isolated worktree. No parser, launcher, panel, schema, composition, worktree/reaper, external-tool preflight/receipt, or policy implementation may exist in that RED landing.
  - test: SL1-T1 degraded trust-root type arm — Within that same immutable node and unchanged nodeid, construct legacy absent, present `true`, and present `false` records and require exact reconstruction of `False`, `True`, and `False`, respectively. Feed known-key wrong types including the JSON string `"false"` and integer `1` and require the existing malformed-record/`ProvenanceInvalid` path before construction or rewrite; retain the unknown-field rejection in the same node. No coercive truthiness helper may satisfy the test.
  - test: SL1-T1 dependency-completion provenance arm — In the already-owned `phase-loop-runtime/tests/test_reviewtruth_phase.py`, add the exact future falsifiers `test_dependency_completion_preflight_rejects_noncanonical_or_rewritten_origin`, `test_dependency_completion_preflight_rejects_identical_or_arbitrary_ancestor_f`, `test_dependency_completion_preflight_rejects_wrong_order_or_non_manifest_delta`, `test_dependency_completion_preflight_rejects_missing_duplicate_drifted_or_wrong_phase_event`, `test_dependency_completion_preflight_rebuilds_review_wave_receipt_and_artifact_digests`, `test_dependency_completion_preflight_rejects_review_wave_chronology_bundle_or_policy_mismatch`, `test_dependency_completion_preflight_rejects_stale_agree_or_incomplete_restart_chain`, and `test_dependency_completion_stage_b_rejects_origin_f_or_m_sidecar_drift`. Their shared positive fixture builds two distinct legal `M -> FH -> F` histories and two immutable evidence roots, then proves canonical origin authentication, exact ordered parents, manifest-only deltas, strict event addition/preservation, canonical receipt/bundle/producer/artifact bytes, direct re-hashing of every relative locator, preflight-derived identity/capability/binding, native-result-derived status/text/chronology/bundle, rendered-prompt lens/seat/bundle binding, exact native `EVIDENCE_REF` grounding in both final artifacts, total canonical status-to-outcome derivation, reducer mirroring, exact terminal verdict, non-elided substance, floor facts, early-Codex → staging → critics → Fable chronology, one common bundle, effective 3/3/true pre-merge policy with Sol/Fable usable `AGREE`, sole Fable binding, and Stage-B sidecar rebinding. The unchanged named review-wave bundle test must first retain RED fixtures for the formerly accepted `[elided]` plus 41-byte padding ending in `AGREE`, the synthetic all-AGREE four-seat artifact/receipt set with no producer records, a generic Fable `AGREE` whose reducer alone lists grounding refs, a citation-only native body ending in `AGREE`, a substantive native body citing both final artifacts plus a third valid bundled artifact, a three-lens wave whose rendered prompts omit the lens markers, a prompt with the expected marker beside an extra conflicting marker, and every cross-class native status/outcome substitution. Separate mutations cover absent/malformed/duplicate/extra/wrong-digest native `EVIDENCE_REF` lines, prompt omission/substitution/aliasing, dropped, duplicated, extra, or wrong lens/bundle/seat markers, `AGREE, but not approval`, an opaque early artifact, absent/swapped/aliased preflight or native-result refs, forged producer/identity/text/status/bundle/chronology values, duplicate native-result IDs, a regex-valid false digest, byte-count drift, locator escape/symlink, zero-byte or noncanonical artifact, empty/sentinel/verdict-only review text, forged wrapper usability/outcome/verdict/vendor/lens/capability, duplicate seat-instance, grounding-entry or consumed-bundle substitution, self-referential JSON, a critic before staging, Fable before critic completion, stale `AGREE`, missing invalidation, unchanged restart bundle, and incomplete full-wave restart without contacting the network; production/parser code is not written in this repair.
  - impl: SL1-T2 — Author the chronology parser only after both raw observations and their Stage-B exact-profile comparison are sealed; independently test both exact observer payloads, both immutable Stage-A snapshots and their candidate-manifest identities, the separately reviewed live Stage-B plan digest, the provisioning contract, and retrospective SL-0 Git/GitHub proof including all three comments' six timestamps, exact bodies/identities/semantic objects, and canonical effective-rules equality. Preserve the predecessor parser, disposition, collection, native-identity, JUnit, and panel contracts, with Stage-B values and EC-REVIEWTRUTH-17 aggregates.
  - verify: SL1-T3 — Retrospectively and independently re-prove all three exact SL-0 comment identities/body bytes/body digests and six timestamps, Option-2/prover/ordering semantics, parameterized-policy/default distinction, non-authorizing `agent-harness#405`, Stage-B exact-base/profile facts, immutable Stage-A snapshot manifest regeneration, separate reviewed Stage-B plan binding, chronology, paired observations, and all predecessor plus EC-REVIEWTRUTH-17 RED invariants. This verifier gates SL-2 through SL-5 and cannot be used to skip Stage B.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command | Work |
|---|---|---|---|---|---|---|
| SL1-T1 | test | SL-0 | all eleven SL-1 owned paths except `docs/research/reviewtruth-red-baseline.md`; the coordinator-provided absolute external runner root is operational evidence, never a landing path | all predecessor EC-REVIEWTRUTH-1-through-16 nodes, the exact PC-REVIEWTRUTH-7 triple, the separately named PC-REVIEWTRUTH-8 16-node set/digests, and the eight exact dependency-completion provenance falsifiers above; all predecessor compatibility, chronology, collection, native-identity, golden, evidence, and JUnit contracts | the Stage-B exact operational chain, then the literal EC-REVIEWTRUTH-17 16-node RED command in `## Verification`, then existing focused/default/activated/golden commands | Verify the exact dependency-complete Stage-B base/tree, both recomputed dependency review-wave receipts, and sealed paired profile before mutation. Author the eight dependency provenance tests and all 16 EC-REVIEWTRUTH-17 tests in the already-owned test files; prove their literal RED anchors before any production implementation. Stage B, not this document's historical constants, supplies every aggregate collection/count/digest literal. Preserve all predecessor falsifiers and mechanically recompute every aggregate node/anchor set. |
| SL1-T2 | impl | SL1-T1 | `phase-loop-runtime/scripts/verify_reviewtruth_chronology.py`, `phase-loop-runtime/tests/conftest.py`, `docs/research/reviewtruth-red-baseline.md` | dual-observer-byte/provisioning/parser mutation tests, retrospective SL-0 controls, and synthetic observer subprocess controls | the exact ordered SL1-T1 commands | Consume the Stage-B-frozen observations and all three maintainer directives, then implement only the tests-lane parser/conftest infrastructure after its RED tests. Merge only the eleven lane-owned production-free paths and bind exact SL-0, base/tree, rules, observer/profile, EC-REVIEWTRUTH-17 RED, parser, and ordered panel digests. |
| SL1-T3 | verify | SL1-T2 | all eleven SL-1 owned paths | retrospective SL-0 authority, pre-implementation chronology, bootstrap trust, activation, collection, EC-REVIEWTRUTH-17 RED, JUnit, native-identity, and immutable-boundary verification | `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k reviewtruth_preimplementation_chronology_all` | Independently re-prove all three maintainer comment identities/body bytes/body digests/semantic clauses, the strict Option-2 and parameterized prover/ordering contracts, non-authorizing `agent-harness#405`, Stage-B exact base/profile, both dependency review-wave roots/receipts, dedicated record and tests-only landings, and that only the eleven frozen tests/evidence paths changed. Require all 16 EC-REVIEWTRUTH-17 nodes to remain RED at their exact anchors and no production implementation to exist. |

### SL-2 — Typed Seat Outcome, Lens Prompt, And Native-Fill Binding

- **Scope**: Publish IF-0-REVIEWTRUTH-1 and IF-0-REVIEWTRUTH-3 in the single-writer panel runtime: preserve the existing review read-only and non-review danger-full-access paths, add the explicit bounded Codex workspace-write launch branch plus fail-closed external-tool and explicit coordinator-selected workspace-mount policy/effective config/preflight/launch receipts, capability/sandbox schema, gate-aware acyclic evidence wave, and coordinator-owned ephemeral worktree/data-scope/reaper seam, while retaining the durable outcome/native-fill contracts.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/launcher.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/schema.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py`, `phase-loop-runtime/src/phase_loop_runtime/fab_gate.py`, `phase-loop-runtime/src/phase_loop_runtime/phase_worktree_executor.py`
- **Interfaces provided**: `IF-0-REVIEWTRUTH-1`, `IF-0-REVIEWTRUTH-3`, `ExecutionCapabilityAttestation`, `ReviewWavePolicy`, `ReviewWaveEvidence`, `invoke_review_wave()`, `CodexExternalToolPolicy`, `CodexEffectiveConfigReceipt` or equivalent strict effective-config subrecord, `CodexExternalToolPreflightReceipt`, `CodexEarlyProverLaunchReceipt`, `run_codex_external_tool_preflight()`, `EarlyProverWorktreeHandle`, `create_early_prover_worktree()`, `reap_early_prover_worktrees()`, `REVIEWTRUTH-prover-capability-attestation`, `AuthPreflightResult.metadata.execution_capability`, `Board.capability_attestations`, `PanelLegOutcome`, `PanelLegResult.outcome`, `PanelLegResult.required`, `PanelLegResult.degraded`, `PanelLegResult.prompt_lens_digest`, `PanelResult.reviewed_seat_count`, `SeatOutcomeRecord.degraded`, `REVIEWTRUTH-seat-outcome-degraded-lossless-reader`, `NativeAgentLegRequest.request_id`, `NativeAgentLegRequest.seat_instance_id`, `NativeAgentLegRequest.attempt_id`, `NativeAgentLegReport`, `NativeAgentLegBindingDisposition`, `bind_native_agent_leg_result()`
- **Interfaces consumed**: `REVIEWTRUTH-capability-ratification`, `REVIEWTRUTH-tests-first-baseline`, `REVIEWTRUTH-preimplementation-chronology`, `REVIEWTRUTH-seat-outcome-degraded-roundtrip-contract`, `REVIEWTRUTH-native-fill-identity-contract`, `REVIEWTRUTH-early-prover-wave-contract`, `REVIEWTRUTH-golden-delta-baseline`, `REVIEWTRUTH-tdd-activation`, `REVIEWTRUTH-junit-contract`
- **Parallel-safe**: no; this lane is the sole writer for all six owned files. The early-prover coordinator grants one serial write-capable holder, and no other lane may mutate these seams concurrently.
- **Tasks**:
  - test: SL2-T1 — Consume all landed outcome/native-fill tests plus the exact EC-REVIEWTRUTH-17 set; require all 16 early-prover nodes RED at their frozen anchors before editing any of the six files.
  - impl: SL2-T2 — In `launcher.py`, add only an explicit early-prover Codex branch containing the exact PC-REVIEWTRUTH-8 argv and fail-closed `CodexExternalToolPolicy`/effective config/preflight/launch receipts, with both exclusion overrides true and `TMPDIR` canonical inside the already-authorized per-leg worktree/data scope; preserve existing review `read-only` and non-review `danger-full-access` branches. In `advisor_board/schema.py` and `composition.py`, add defaulted capability/sandbox/role fields without constructor breakage and never grant early evidence authority to bind. In `panel_invoker.py`, add `invoke_review_wave()` without changing `PANEL_LEGS` or legacy invocation/goldens; require a passing effective receipt or independent OS-confinement receipt before Codex, stage a typed zero-launch degraded record otherwise, enforce the acyclic receipt/bundle/seat chronology and complete restart rule, and preserve Grok/Gemini rules. In `phase_worktree_executor.py`, require an external-coordinator-selected explicit `workspace_mount`; add one fail-closed preflight for canonicalization, non-symlink ancestry, coordinator ownership, private writable/searchable permissions, free bytes/inodes, source/Git-common-dir disjointness, and exact `lane_worktree_root` containment; pass that mount explicitly through `create_phase_worktree`; and extend the existing create/teardown utilities with per-leg lease/data-scope/mount/external-tool receipts, fresh ephemerality, and an external crash reaper. The coordinator creates the parent/worktree before the confined leg starts. Preserve `fab_gate.py`'s strict durable-reader/native-fill work.
  - verify: SL2-T3 — Prove every exact PC-REVIEWTRUTH-8 node GREEN plus all predecessor focused/golden tests; inspect the emitted Codex argv, full frozen feature/MCP/plugin classification, zero-enabled effective state, both exclusions true in policy/effective config/preflight/launch receipts, contained `TMPDIR`, explicit mount preflight/pass-through, positive custom-`tmp_path` and safely available real-`/mnt/workspace` controls, rejected unusable mounts with zero leg launch, positive worktree/nested-`TMPDIR` writes, rejected `/tmp`/external-`TMPDIR`/live-tree/shared-data writes, worktree/data-scope/reaper receipts, acyclic review-wave digests, zero-launch degraded Codex/Grok records, Gemini ineligibility, and contradiction-triggered complete re-review. Prove `can_probe` never satisfies `binding_prover`.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command | Work |
|---|---|---|---|---|---|---|
| SL2-T1 | test | SL-0, SL-1 | all six SL-2 owned files | consume landed EC-2 through EC-17 tests without editing, including the exact 16 PC-REVIEWTRUTH-8 nodes | the literal EC-REVIEWTRUTH-17 RED command followed by existing forced-activation focused and golden commands | Before any SL-2 edit, prove all 16 nodes fail only at their exact mapped anchors and retain their exact node/anchor digests. Confirm legacy review/non-review launcher paths, `PANEL_LEGS`, and goldens remain GREEN. |
| SL2-T2 | impl | SL2-T1 | all six SL-2 owned files | none | the literal EC-REVIEWTRUTH-17 GREEN command followed by existing focused and golden commands | Implement the exact file-by-file contract above. Reuse existing `create_phase_worktree()`/`teardown_phase_worktree()` and `lane_worktree_root()` seams; remove ambient mount selection from the early-prover path and pass the externally selected mount explicitly through both APIs. The coordinator, never a leg, owns mount selection/preflight, parent/worktree creation, external-tool probing/classification, launch authorization, serial leases, data-scope reset/create/teardown receipts, digest binding, and the external reaper. |
| SL2-T3 | verify | SL2-T2 | all six SL-2 owned files | none | the EC-REVIEWTRUTH-17 GREEN command plus existing marker-driven SL2 commands | Require all focused commands GREEN. Prove exact Codex argv and effective external-tool closure, rejection of unknown/enabled/locked/changed/uninspectable surfaces or either false/missing temporary exclusion, zero launch on failed proof without OS confinement, explicit canonical mount pass-through and zero launch on any mount-preflight failure, fresh contained worktree/data-scope isolation, contained `TMPDIR` with no extra writable authority, custom `tmp_path` and safely available real `/mnt/workspace` positives, denied `/tmp` and external-`TMPDIR` writes, serial holder, external crash reaping, policy/config/preflight/launch/mount/worktree/reaper-bound evidence, gate ordering, zero-launch degraded Grok, Gemini ineligibility, complete contradiction invalidation/re-review, Fable-only binding, and legacy path/golden compatibility. |

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

- **Scope**: Consume SL-3's grounded reviewed collection, derive delivery/vendor/lens/prover facts without a second grounding implementation, expose a pure FULL, FLOOR-ONLY, and BELOW-FLOOR classification, and extend the existing parameterized gate-policy resolver additively: its per-repo override allowlist includes typed `required_prover`, including `false`; only shipped defaults and the current v10 procedural directive are fixed at `3/3/true`.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/ratification_policy.py`, `phase-loop-runtime/src/phase_loop_runtime/gate_posture.py`
- **Interfaces provided**: owner-qualified `IF-0-REVIEWTRUTH-2` implementing the maintainer-named additive `IF-0-POLICY-1` contract, `RatificationPolicy.required_prover`, `BoardFacts.prover_usable`, parameterized `gate_posture.resolve_ratification_policy`, `BoardDeliveryState`, `classify_board_delivery()`, `BoardFacts.delivery_state`, `BoardFacts.reviewed_seat_count`
- **Interfaces consumed**: `REVIEWTRUTH-capability-ratification`, `REVIEWTRUTH-tests-first-baseline`, `REVIEWTRUTH-golden-delta-baseline`, `REVIEWTRUTH-tdd-activation`, `IF-0-REVIEWTRUTH-1`, `PanelLegResult.outcome`, `PanelLegResult.prompt_lens_digest`, `PanelResult.reviewed_seat_count`, `ReviewGrounding`, `classify_review_grounding()`, `GovernedBoardEvidence`, `GovernedBoardEvidence.grounded_reviewed_seats`
- **Parallel-safe**: no; file ownership is disjoint from SL-3, but this lane consumes SL-3's grounded evidence and may not start from prose order alone.
- **Tasks**:
  - test: SL4-T1 — Cover FULL, FLOOR-ONLY, and BELOW-FLOOR; typed shortfall; lens coverage; reviewed-no-findings counting; retryable outcomes that never count; exact all-gate shipped defaults `3/3/true` with unchanged consensus/`on_shortfall`; and a per-repo override proving `required_prover=false` is accepted without changing unrelated effective fields.
  - impl: SL4-T2 — Derive vendor, lens, prover, and delivery facts only from SL-3's grounded reviewed seats; append `required_prover` to the existing typed override allowlist; keep every gate, consensus, threshold, and `on_shortfall` parameterized; set only `DEFAULT_RATIFICATION_POLICIES` to the directive's `3/3/true`; and hard-block missing prover only when the resolved effective policy has `required_prover=true`.
  - verify: SL4-T3 — Prove all three classifications, shortfall propagation, no silent FULL rendering, load-bearing prompt-lens proofs, reviewed-no-findings separation, unchanged per-gate consensus/`on_shortfall`, exact shipped defaults, effective `required_prover=true` hard block, effective `required_prover=false` positive override, and continued EC-REVIEWTRUTH-6 compliance.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command | Work |
|---|---|---|---|---|---|---|
| SL4-T1 | test | SL-0, SL-1, SL-2, SL-3 | `phase-loop-runtime/src/phase_loop_runtime/ratification_policy.py`, `phase-loop-runtime/src/phase_loop_runtime/gate_posture.py` | consume landed EC-1, EC-4, EC-5, EC-6, EC-7, and exact EC-16 policy tests without editing | `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_reviewtruth_phase.py -q -k reviewtruth_sl4`<br>`PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_advisor_board_golden.py -q` | Require RED for append-only/defaulted `required_prover` and `prover_usable`, exact shipped 3/3/true defaults, unchanged consensus/action parameters, and typed `required_prover=false` override while preserving every unrelated resolved field. |
| SL4-T2 | impl | SL4-T1 | `phase-loop-runtime/src/phase_loop_runtime/ratification_policy.py`, `phase-loop-runtime/src/phase_loop_runtime/gate_posture.py` | none | the focused SL4-T1 commands | In `ratification_policy.py`, append defaulted `RatificationPolicy.required_prover` and `BoardFacts.prover_usable` without moving existing positional fields; derive usable prover only from grounded artifact-bound Fable; keep consensus and `on_shortfall` parameterized; set only shipped defaults/current v10 effective posture to 3/3/true; and hard-block missing prover only when effective `required_prover=true`. In `gate_posture.py`, extend the existing typed override allowlist/resolver with a real boolean `required_prover`, accepting both true and false and rejecting coercion, while preserving all unrelated fields/actions. |
| SL4-T3 | verify | SL4-T2 | `phase-loop-runtime/src/phase_loop_runtime/ratification_policy.py`, `phase-loop-runtime/src/phase_loop_runtime/gate_posture.py` | none | the focused SL4-T1 commands | Require both focused commands GREEN and prove constructor compatibility, exact defaults, per-gate consensus/action preservation, valid false override, other-field preservation, and the conditional hard prover block. |

### SL-5 — Production Gate, Repair, Lifecycle Ledger, And Native Driver Integration

- **Scope**: Wire the frozen review truth and early-prover evidence-wave contract through gate-specific and train consumers, bounded production repair, canonical lifecycle/summary persistence, Claude native fill, durable typed train approval/resume evidence, and the single immutable evidence executable used by both implementation-head GitHub CI and the post-landing reducer, then cross one distinct SL-2-through-SL-5 implementation PR/landing boundary.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/src/phase_loop_runtime/governed_premerge.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `phase-loop-runtime/src/phase_loop_runtime/train_runner.py`, `phase-loop-runtime/src/phase_loop_runtime/train_ledger.py`, `phase-loop-runtime/scripts/gate_a_cleanroom.sh`, `phase-loop-runtime/scripts/verify_reviewtruth_evidence.py`, `.github/workflows/test.yml`, `skills-src/claude/claude-advisor-board/SKILL.md`, `phase-loop-skills/advisor-board/**`, `phase-loop-runtime/src/phase_loop_runtime/skills_bundle/*-advisor-board/**`, `phase-loop-runtime/src/phase_loop_runtime/skills_bundle/*-advisor-panel/**`
- **Interfaces provided**: `REVIEWTRUTH-production-gates`, `REVIEWTRUTH-native-driver-contract`, `REVIEWTRUTH-seat-outcome-ledger`, `REVIEWTRUTH-panel-verdict-ledger`, `REVIEWTRUTH-train-approval-evidence`, `REVIEWTRUTH-production-apply-fix`, `REVIEWTRUTH-evidence-executable`, `REVIEWTRUTH-gate-a-suite-attestation`, `REVIEWTRUTH-implementation-landing`
- **Interfaces consumed**: `REVIEWTRUTH-capability-ratification`, `REVIEWTRUTH-tests-first-baseline`, `REVIEWTRUTH-preimplementation-chronology`, `REVIEWTRUTH-post-parser-collection-contract`, `REVIEWTRUTH-seat-outcome-degraded-lossless-reader`, `REVIEWTRUTH-native-fill-identity-contract`, `REVIEWTRUTH-early-prover-wave-contract`, `REVIEWTRUTH-golden-delta-baseline`, `REVIEWTRUTH-tdd-activation`, `REVIEWTRUTH-junit-contract`, `REVIEWTRUTH-broad-compatibility-gate`, `IF-0-REVIEWTRUTH-1`, `IF-0-REVIEWTRUTH-3`, `ReviewWaveEvidence`, `CodexExternalToolPolicy`, `CodexEffectiveConfigReceipt` or equivalent strict effective-config subrecord, `CodexExternalToolPreflightReceipt`, `CodexEarlyProverLaunchReceipt`, `NativeAgentLegRequest.request_id`, `NativeAgentLegRequest.seat_instance_id`, `NativeAgentLegRequest.attempt_id`, `NativeAgentLegReport`, `NativeAgentLegBindingDisposition`, `bind_native_agent_leg_result()`, `ReviewGrounding`, `GovernedBoardEvidence.grounded_reviewed_seats`, `review_material_issue()`, `BoardDeliveryState`, `classify_board_delivery()`
- **Parallel-safe**: no; this is the serialized integration lane and the single writer for production gate orchestration, the evidence executable, the GitHub Gate A lifecycle, and generated skill surfaces.
- **Tasks**:
  - test: SL5-T1 — Consume the immutable real-production gate, train-resume migration, repair, planning-policy, lossless degraded-seat ledger/native-attempt reconstruction, collision/late/replay/cross-seat/exactly-once binding, CLI material, evidence-executable, Gate A attester, and workflow-order falsifiers without editing tests.
  - impl: SL5-T2 — Wire production repair, gate-specific and train classification consumers, typed current-policy train approval evidence, aggregate/per-seat/native-attempt events that consume SL-2's already-lossless degraded-seat reader without reimplementing it, empty-material failure, eligible native Fable fulfillment with fresh retry identities, crash-safe exactly-once reconstruction, the immutable evidence executable with all closeout and Gate A modes, the Gate A neutral write-once persistent evidence copy, the explicit GitHub workflow lifecycle that invokes the co-landed attester, and regenerated skill mirrors.
  - impl: SL5-T2 early-wave consumer — At plan/design gates permit critics-first scheduling but require the digest-bound early evidence before Fable; at pre-merge/release gates call the SL-2 review-wave interface before any critic and exclude verdicts without the staged evidence digest from floor calculations. Persist the exact input/HEAD/tree/bundle/evidence/worktree/data-scope and capability-role fields; canonical external-tool policy, effective-config, preflight, and launch/no-launch receipt digests; both exclusion booleans, contained `TMPDIR`, and no-extra-writable-authority proof; Codex-preflight or OS-confinement/Grok-confinement decision; degraded zero-launch audit and process count; reaper outcome; and counted-verdict bundle digest. A failed or uninspectable Codex external-tool preflight, either false/missing exclusion, or external `TMPDIR` cannot dispatch Codex unless the independent OS-level confinement receipt authorizes the same digests and proves the missing boundary. On any contradicting early finding, mark prior `AGREE` rows invalid, rebuild the bundle, and require every counted critic plus Fable to review the new digest.
  - verify: SL5-T3 — Prove production reachability, gate-dependent ordering, role separation, durable early-evidence/degraded/reaper/contradiction records, both live/resume policy migrations, durable native attempt reconstruction, and the co-landed workflow/attester contract; then run candidate/CI/panel/merge verification. Each change-panel attempt uses the directive order: early Codex evidence in the initial wave, critics including Sol on that digest, then usable grounded artifact-bound Fable; no direct `claude -p`.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command | Work |
|---|---|---|---|---|---|---|
| SL5-T1 | test | SL-0, SL-1, SL-2, SL-3, SL-4 | all SL-5 owned paths | consume landed EC-4, EC-6, EC-8, EC-10, EC-11, EC-13, EC-14, EC-16, EC-17, floor/train/native compatibility tests without editing | `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_reviewtruth_phase.py -q -k 'reviewtruth_sl5 or review_wave'`<br>`PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_advisor_board_golden.py -q` | Require focused consumer falsifiers RED for prover-first pre-merge/release, evidence-gated critic counting, Fable-only binding, persisted external-tool policy/preflight/receipt and degraded zero-launch audit, and contradiction invalidation/re-review; inherited SL-2 early-prover and golden tests remain GREEN. |
| SL5-T2 | impl | SL5-T1 | all SL-5 owned paths | none | the focused SL5-T1 commands during implementation; the broad candidate command only after the lane is complete | Wire the production `apply_fix` closure from `_build_repair_context`, `build_prompt`, and `launch_with_spec`; fold block findings into repair context, redispatch repair, rebuild the staged bundle, and keep its bounded rounds independent from recent-failure accounting. Consume `review_material_issue()` in CLI/planning/pre-merge/runner paths and make `_build_train_review_bundle()` carry substantive committed change material rather than PR-summary-only prose. Replace governed pre-merge's separate `_MIN_USABLE_REVIEWERS=2` decision with the gate-specific `classify_board_delivery()` consumer over grounded reviewed seats so no dual threshold survives: FULL passes, FLOOR-ONLY may proceed only with explicit degraded/shortfall state and never reports FULL, and two usable/reviewed seats are BELOW-FLOOR and block. Apply the same hard-block action only to EC-REVIEWTRUTH-1/4 governed pre-merge, train merge/resume, merge-class, and CLI gates; preserve `plan-ratify`/`design-ratify` degraded policy while forbidding them from reporting degraded progress as FULL convergence. In `train_runner.py`, use `GovernedBoardEvidence.grounded_reviewed_seats` and `classify_board_delivery()` for live train review, approval, ledger write, and resume. In `train_ledger.py`, migrate durable review evidence from raw `usable_reviewers` to typed `delivery_state` plus an incremented current `REVIEW_POLICY_VERSION`; legacy `usable_reviewers` may remain readable as non-authorizing provenance only. Resume requires exact current-policy identity and a grounded gate-authorizing delivery state; every pre-migration, count-only, missing-state, old/missing-policy, raw-ungrounded, or BELOW-FLOOR record re-enters review and cannot short-circuit merges. Emit aggregate verdicts on every governed outcome and one metadata-only `SeatOutcomeRecord` per requested non-FAB seat, including orthogonal `degraded`, through canonical events; consume SL-2's strict `fab_gate.py` reconstruction and do not edit, duplicate, or weaken it in this lane. Persist native fill as metadata-only lifecycle events carrying `seat_instance_id`, `request_id`, `attempt_id`, `seat_key`, all four content digests, transition, and typed binding disposition, never raw prompt/review text. Before dispatch/resume, reconstruct pending, superseded, consumed, and rejected identities from the canonical ledger; never re-emit a consumed identity, never accept a superseded/prior-board/replayed tuple, and allocate fresh request/attempt identities for every retry. Fulfill eligible native Fable requests through the Claude source skill under the ratified posture, echo the complete identity/digest tuple in its report, bind valid reports exactly once, preserve colliding seat instances and the real-tree execution boundary, and regenerate all neutral and packaged skill mirrors. In `gate_a_cleanroom.sh`, require a runner-supplied canonical absolute `PHASE_LOOP_GATE_A_INPUT_COPY_ROOT` that is new, private, non-symlinked, outside the script's temporary cleanup tree, and beneath the declared runner evidence root. Preserve the observed pytest namespace exactly: build and run the installed-wheel suite from the script-owned temporary `<WORK>/standalone/phase-loop-runtime/tests/**` tree, where `<WORK>/standalone/phase-loop-runtime/scripts/` is absent. Independently copy those exact executed test bytes to `<input-copy>/tests/**` and copy the committed parser only to `<input-copy>/chronology-parser/verify_reviewtruth_chronology.py`; require `<input-copy>/tests/conftest.py`, forbid `<input-copy>/phase-loop-runtime/`, fsync files/directories, and seal a canonical manifest of path, mode, byte length, and SHA-256. The existing cleanup trap removes only `WORK`; it never removes the external copy. In `.github/workflows/test.yml`, replace the old bare `bash scripts/gate_a_cleanroom.sh` step with an explicit private lifecycle: allocate a fresh canonical root beneath `${RUNNER_TEMP}`, set mode `0700`, export/pass `PHASE_LOOP_GATE_A_INPUT_COPY_ROOT`, unset and reject both selectors, invoke the script, prove its internal `WORK` cleanup completed, invoke the terminal attester while `<input-copy>/tests/**`, `<input-copy>/chronology-parser/**`, and the manifest remain readable, and clean the external root only after the attester exits. A workflow trap retains failure status while performing that final cleanup; neither success nor failure may attest after cleanup. Do not package the parser into the wheel and do not edit any of SL-1's eleven frozen paths, including conftest, floor, train, golden, serializer, native-request, native-fill, chronology, and RED evidence owners. |
| SL5-T3 | verify | SL5-T2 | all SL-5 owned paths | none | `PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit-run --mode candidate --xml .phase-loop/evidence/reviewtruth-phase-candidate.xml`<br>`PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration" --junitxml=.phase-loop/evidence/reviewtruth-broad-candidate.xml`<br>`PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit --mode candidate --phase-xml .phase-loop/evidence/reviewtruth-phase-candidate.xml --broad-xml .phase-loop/evidence/reviewtruth-broad-candidate.xml`<br>`PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_advisor_board_golden.py -q` | Push the complete implementation candidate, then discard any proof from the already-loaded authoring process. In a fresh repo-local child, prove `HEAD` equals the server-reported pushed implementation head, attest repo-local module/conftest paths and digests, and run these four commands in the displayed order. The phase runner selects exactly frozen `REVIEWTRUTH_PHASE_NODEIDS` and requires zero phase skips. The unmodified broad command leaves `PHASE_LOOP_REVIEWTRUTH_POST_PARSER_COLLECTION` unset; built-in marker selection must report exactly `REVIEWTRUTH_BROAD_MARKER_DESELECTED_NODEIDS`, and the frozen try-last wrapper hook must separately find, remove, and notify exactly all five `REVIEWTRUTH_POST_PARSER_NODEIDS`, while every other collected runtime test, including all five compatibility migrations and every marker-activated new/migrated production assertion, runs. A nonempty external `--deselect`, arbitrary/category-swapped deselection, marker-baseline drift, missing/extra/wrong hook deselection, or final collection activation is forbidden. Broad semantic skips must equal the unchanged pre-implementation baseline set/count/digest after independent PC-REVIEWTRUTH-5A/5B/5C validation; the exact PyPI and console-script nodes must each run once. PyPI either passes or contributes one fully source-attributed `pypi_transport_unavailable` disposition with raw longrepr/reason/exception evidence retained. The console-script node either passes under its adjacent package-installed command or contributes one exact `source_layout_console_script_unavailable` disposition only under the source-module, absent-CI, absent-sibling predicate with raw reason/interpreter/sibling/module-origin evidence retained. Zero broad skips is neither required nor claimed, and live internet is not required. The candidate parser runs only after both exact XML files exist and requires zero selected phase skips, zero `xfail`, broad deselections equal to the disjoint marker baseline UNION five hook-owned wrappers with both categories attested, zero failures/errors, no missing/duplicate/unexpected phase nodeid, no new/missing/drifted semantic broad baseline skip, no second network-normalized node, no second console-normalized node, and no console normalization outside the exact source-layout predicate. The ordinary frontmatter suite command and each required GitHub CI job on Python 3.10, 3.11, and 3.12 must also be GREEN at this exact head under the same marker-baseline-plus-five deselection, all three exact-node dispositions, and semantic broad-skip contract before merge; their absence or red status blocks the merge even if the special parser is green. Gate A applies none of the three dispositions and must retain the exact line-111 root-missing tuple and 39+4+59=102 contract. The golden runs only after that parser and required CI are GREEN. Prove production repair reachability; aggregate/per-seat lifecycle persistence; native request/attempt lifecycle reconstruction across restart; unique colliding seat instances; fresh retry identities; rejection of late/stale/replayed/cross-seat/digest-substituted reports; exactly-once count; resolved brief propagation and all four content digests; material-helper consumption; exact delivery-state output; floor/train migration; generated parity; exact sanctioned golden output; and conformance to the separately ratified capability record. Only after this fresh exact-pushed-head phase/broad/parser/suite/CI/golden proof is GREEN, launch the ordered change review from another fresh repo-local process bound to the same exact pushed head: serial isolated Codex evidence first, critics including GPT-5.6 Sol on that evidence-bearing bundle second, and usable grounded artifact-bound Fable binding review last. The frozen critic panel still contains Gemini 3.6 Flash and Grok 4.5. Record child attestations and all XML/parser/suite/CI/golden/disposition/evidence digests. Every material or contradictory finding forces a new pushed head or bundle as applicable and a new fresh ordered proof and review; no loaded parent attestation is reusable. Merge one dedicated implementation PR as a two-parent commit whose first parent already contains the disposition and tests-only landings. The implementation PR must use a distinct head identity, contain no SL-1-owned path or SL-1 tests-only commit in `implementation^1..implementation^2` or its server-recorded PR range, cite the full disposition SHA in the landing message, and be reachable from canonical `main` before SL-6 starts. |

The SL-5 executable/workflow ownership contract is atomic and binds SL5-T1, SL5-T2, and SL5-T3. SL5-T1's immutable falsifiers require the real `phase-loop-runtime/scripts/verify_reviewtruth_evidence.py` entrypoint, all `source-ownership`, `live-panel`, `ledger`, `junit`, `all`, `finalize-record`, `final-record`, `gate-a`, and `gate-a-attest` modes, explicit external path arguments, and workflow call order. SL5-T2 implements that executable in the same landing as `gate_a_cleanroom.sh` and `.github/workflows/test.yml`; `gate-a` requires `--runner-root`, `--input-copy`, `--stdout`, `--stderr`, `--artifact`, and `--attestation`, with the four output arguments equal only to the canonical `$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite.{stdout,stderr,json}` and `$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite-attestation.json` paths. The workflow must invoke this co-landed executable, retain the private external copy through its fresh `gate-a-attest` child, and clean it only afterward. SL5-T3 proves the workflow references that exact executable blob at the pushed implementation head, verifies the exact external paths and absence of Gate A suite aliases under `.phase-loop/evidence/`, and requires GitHub CI GREEN at that head before golden, panel, or merge. No later lane may edit the executable or workflow.

Within SL5-T2's workflow description, “invoke the script” and “invoke the terminal attester” are the ordered internal stages of the single `verify_reviewtruth_evidence.py gate-a` workflow call; a direct workflow call to `gate_a_cleanroom.sh` followed by an SL-6-supplied attester is forbidden.

### SL-6 — REVIEWTRUTH Evidence, Documentation, And Verification Reducer

- **Scope**: From a new repo-local process at the exact post-implementation canonical-main tip, reduce final chronology, capability ancestry, live panel inspection, governed ledger output, structured JUnit accounting, and whole-phase verification into durable metadata-linked evidence — staged as a board-reviewed pre-final record and a post-parser finalized record in an acyclic order — without modifying producer-owned tests or code.
- **Owned files**: `docs/research/reviewtruth-phase-verification.md`, `docs/research/reviewtruth-real-panel-smoke.md`, `docs/research/reviewtruth-final-evidence-record.md`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`
- **Interfaces provided**: `REVIEWTRUTH-closeout-evidence`, `IF-0-REVIEWTRUTH-1`, `IF-0-REVIEWTRUTH-3`
- **Interfaces consumed**: `REVIEWTRUTH-capability-ratification`, `REVIEWTRUTH-tests-first-baseline`, `REVIEWTRUTH-evidence-wrappers`, `REVIEWTRUTH-post-parser-collection-contract`, `REVIEWTRUTH-seat-outcome-degraded-lossless-reader`, `REVIEWTRUTH-exact-pypi-availability-contract`, `REVIEWTRUTH-exact-console-script-availability-contract`, `REVIEWTRUTH-native-fill-identity-contract`, `REVIEWTRUTH-early-prover-wave-contract`, `REVIEWTRUTH-golden-delta-baseline`, `REVIEWTRUTH-junit-contract`, `REVIEWTRUTH-broad-compatibility-gate`, `IF-0-REVIEWTRUTH-1`, `IF-0-REVIEWTRUTH-3`, `REVIEWTRUTH-production-gates`, `REVIEWTRUTH-native-driver-contract`, `REVIEWTRUTH-seat-outcome-ledger`, `REVIEWTRUTH-panel-verdict-ledger`, `REVIEWTRUTH-production-apply-fix`, `REVIEWTRUTH-evidence-executable`, `REVIEWTRUTH-gate-a-suite-attestation`, `REVIEWTRUTH-implementation-landing`
- **Parallel-safe**: no; this terminal reducer consumes every producer lane and the immutable SL-5 evidence executable and is the only writer for synthesized evidence and final contract documentation.
- **Tasks**:
  - test: SL6-T1 — From merged canonical `main`, prove the implementation-landing precondition and immutable test-owner boundary without invoking any final chronology, live-panel, or final-evidence wrapper.
  - impl: SL6-T2 — Write only the owned pre-final evidence docs and contract/card updates while consuming the immutable evidence executable. Bind all three exact maintainer directives, both frozen Stage-A snapshot digests and their regenerated manifest identities, the separately reviewed Stage-B plan digest, the Stage-B exact base/profile and frozen Codex executable/version/help/feature/MCP/plugin facts, all eleven tests-only path digests, Codex external-tool policy/effective-config/preflight/launch-or-no-launch receipts including both true exclusions and contained `TMPDIR`, workspace-write/worktree/data-scope/reaper evidence, gate-order records, critic bundle digests, contradiction invalidations, degraded Codex/Grok no-launch audits, and a distinct usable grounded artifact-bound Fable result. Run the closeout review in early-Codex/critics/Fable order; no direct `claude -p`.
  - verify: SL6-T3 — Preserve the acyclic final XML/record/Gate-A order and additionally fail on any missing early-prover initial wave, wrong gate order, counted critic without the required evidence digest, unknown/enabled/locked/changed/uninspectable Codex external surface, either false/missing temporary exclusion, `/tmp` or external-`TMPDIR` authority, Codex launch after failed proof without OS confinement, unconfined Grok launch, Gemini write selection, Codex-as-binding substitution, stale `AGREE`, missing re-review, or any policy/config/preflight/launch-receipt/worktree/data-scope/reaper/digest gap.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command | Work |
|---|---|---|---|---|---|---|
| SL6-T1 | test | SL-0, SL-1, SL-2, SL-3, SL-4, SL-5 | all SL-6 owned paths | consume immutable ownership/precondition contracts without editing | `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k reviewtruth_preimplementation_chronology_all` | Prove the implementation landing is reachable and all eleven SL-1-owned paths remain byte-identical to the tests-only landing and absent from the implementation PR range. Only SL-6-owned evidence/doc paths may become dirty. |
| SL6-T2 | impl | SL6-T1 | all SL-6 owned paths | none | `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k reviewtruth_preimplementation_chronology_all` | In that fresh exact-canonical-main child, consume the already-landed, byte-identical SL-5-owned evidence executable and its wrapper-consumable `source-ownership`, `live-panel`, `ledger`, `junit`, and `all` checks over already-existing artifacts; its post-parser `finalize-record` writer and separate `final-record` verifier modes remain unavailable to every test wrapper. Do not add, edit, or stage `phase-loop-runtime/scripts/verify_reviewtruth_evidence.py`. Its non-wrapper `gate-a` mode refuses to start if `PHASE_LOOP_SKIP_GATE_A_SUITE` or final collection activation is present; requires the runner-supplied canonical `REVIEWTRUTH_RUNNER_ROOT`, the new private persistent input-copy root beneath its evidence directory, and all four exact external output paths; passes the copy root to the SL-5-owned Gate A script; and writes only `$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite.stdout`, `$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite.stderr`, `$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite.json`, and `$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite-attestation.json`. Only after the script process exits and the stdout, stderr, artifact, copy manifest, and every copied file descriptor are closed may it launch a fresh internal `gate-a-attest` OS process with the same selector rejection. That process independently walks and hashes the persistent copy, requires exact set/mode/byte equality with committed `phase-loop-runtime/tests/**` plus `phase-loop-runtime/scripts/verify_reviewtruth_chronology.py`, explicitly rehashes copied `conftest.py` and parser bytes, proves the pytest argv selected that same copied tests tree, re-parses raw sidecars/artifact, and writes the terminal external attestation. It may not use producer-supplied digests without recomputation, and the copy must still exist after the Gate A temporary cleanup completes. It must preserve the exact line-111 `test_release_pin_autotrack.py` root-missing tuple and reject every PC-REVIEWTRUTH-5A/5B/5C normalization or any change to the 39+4+59=102 profile. A Gate A suite output or alias under `.phase-loop/evidence/` is forbidden. Do not add or edit test wrappers, conftest, or production runtime. Stage only `docs/research/reviewtruth-phase-verification.md` and the contract/card updates first, then run a real four-vendor board over a by-reference bundle naming those exact staged files, the immutable executable, and their digests; write `docs/research/reviewtruth-real-panel-smoke.md` as the single canonical durable redacted transcript and smoke record from that run, freeze its one SHA-256 digest, create no second durable transcript path, and freeze every pre-final SL-6 doc byte-identical from its own staging/review point through closeout. Require reviewed Fable and Sol plus the two remaining vendor seats to cite facts obtainable only by opening those files; reject no-file-read disclosure, blank material, missing native report, repo substitution, or digest mismatch. Record exact plan, all eleven tests-only paths including the hook and both exact-PyPI and exact-console-script falsifiers, implementation code, generated, ledger, phase default/RED/candidate XML, broad baseline/default/candidate XML, parser-attestation, PC-REVIEWTRUTH-5A/5B/5C raw and semantic disposition evidence, evidence, and canonical `docs/research/reviewtruth-real-panel-smoke.md` digests, with exactly one digest for its combined transcript/smoke identity; distinct PR/head identities; child process attestations; source-owner mapping; candidate ordered gate, ordinary suite/three-job CI, and golden GREEN commands; artifact-specific citations; native request/report binding including stable seat-instance, fresh request/attempt identities, resolved brief identity, all four content digests, typed rejected reports, exactly-once consumption/count, and durable reconstruction; material-guard outcomes; production repair trace; per-seat reconstruction; and typed current-policy train approval/resume evidence. The pre-final record deliberately excludes the broad-final/phase-final XML digests, final parser attestations, finalized record, `final-record` attestation, Gate A run/output/artifact/attestation, and run-end verdict: none of those exist yet, and they are recorded only by SL6-T3's post-parser finalized record where applicable and the ledger closeout. Update the canonical contract and capability card from SL-1's already-frozen sanctioned golden delta plus the narrow native-fill reversal, exact-once identity binding, and retained real-tree capability boundary; SL-6 may not add a newly discovered delta or repair production output. |
| SL6-T3 | verify | SL6-T2 | all SL-6 owned paths | none | `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration" --junitxml=.phase-loop/evidence/reviewtruth-broad-final.xml`<br>`PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit --mode broad-final-producer --xml .phase-loop/evidence/reviewtruth-broad-final.xml`<br>`PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit-run --mode final --xml .phase-loop/evidence/reviewtruth-phase-final.xml`<br>`PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit --mode final --phase-xml .phase-loop/evidence/reviewtruth-phase-final.xml --broad-xml .phase-loop/evidence/reviewtruth-broad-final.xml`<br>`PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_evidence.py finalize-record --phase-xml .phase-loop/evidence/reviewtruth-phase-final.xml --broad-xml .phase-loop/evidence/reviewtruth-broad-final.xml --record docs/research/reviewtruth-final-evidence-record.md`<br>`PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_evidence.py final-record --record docs/research/reviewtruth-final-evidence-record.md --attestation .phase-loop/evidence/reviewtruth-final-record-attestation.json`<br>`PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_advisor_board_golden.py -q`<br>`PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration"`<br>`env -u PHASE_LOOP_SKIP_GATE_A_SUITE -u PHASE_LOOP_REVIEWTRUTH_POST_PARSER_COLLECTION REVIEWTRUTH_RUNNER_ROOT="$REVIEWTRUTH_RUNNER_ROOT" PHASE_LOOP_GATE_A_INPUT_COPY_ROOT="$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-inputs" sh -c 'PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_evidence.py gate-a --runner-root "$REVIEWTRUTH_RUNNER_ROOT" --script phase-loop-runtime/scripts/gate_a_cleanroom.sh --input-copy "$PHASE_LOOP_GATE_A_INPUT_COPY_ROOT" --stdout "$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite.stdout" --stderr "$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite.stderr" --artifact "$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite.json" --attestation "$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-suite-attestation.json"'`<br>`ruff check phase-loop-runtime/src/phase_loop_runtime/`<br>`phase-loop validate-roadmap specs/phase-plans-v10.md`<br>`git diff --check` | Run these commands in the displayed order only after SL6-T2, from the fresh child whose exact canonical-main/runtime attestation is already recorded; a loaded parent may not substitute. The broad/final ordering and acyclic record rules remain unchanged. Broad-final and final must each collect/execute the exact PyPI and exact console-script nodes once. PyPI classifies only pass or its source-attributed transport-unavailable tuple and retains raw exception evidence. The console-script node classifies only adjacent-command pass or its exact source-layout-unavailable tuple under the source-module, absent-CI, absent-sibling predicate and retains raw reason/interpreter/sibling/module-origin evidence. Both reject every PC-REVIEWTRUTH-5B/5C malformed, duplicate, second-node, and wrong-profile arm and bind all three semantic dispositions into the finalized record and separate `final-record` attestation before closeout. For Gate A, invoke the immutable SL-5-owned evidence executable with the declared runner root, input-copy root, and four exact canonical external output paths; its `gate-a` mode runs the script and then its fresh `gate-a-attest` child while the external copy remains readable. `.github/workflows/test.yml` uses that same co-landed executable and ordering at the implementation head before SL-6: it allocates a fresh private external copy root, unsets both selectors, exports `PHASE_LOOP_GATE_A_INPUT_COPY_ROOT`, runs the reducer, proves the script's internal temporary `<WORK>` cleanup completed, invokes the terminal attester while the external copy remains readable, and only then removes that external root. The script's pytest runtime tree remains `<WORK>/standalone/phase-loop-runtime/tests/**` and must lack `<WORK>/standalone/phase-loop-runtime/scripts/`; the neutral external evidence copy contains only `tests/**` (including `tests/conftest.py`), `chronology-parser/verify_reviewtruth_chronology.py`, and its manifest, and must lack every `phase-loop-runtime/scripts/` root. The reducer rejects either inherited selector, the old workflow invocation without the exported root, a reused/symlinked root, parser misnamespace, any Gate A suite output or alias under `.phase-loop/evidence/`, attestation after cleanup, external cleanup before attestation, any PC-REVIEWTRUTH-5A/5B/5C normalization, or any implementation that recreates scripts in the temporary runtime tree. It independently verifies the same frozen 48-node omission, 4 collection-boundary tuples, 59 runtime-boundary tuples including the exact line-111 release-pin root-missing tuple, 102-tuple union, marker/hook categories, sentinels, profile, committed bytes, and zero-failure outcome described above. The four-seat closeout and canonical ledger bind the broad-final/final raw and semantic PC-REVIEWTRUTH-5A/5B/5C disposition records, finalized-record digest, `final-record` attestation, and unchanged Gate A attestation. Every other SL6-T3 closeout, owner-map, immutable-test, native-report, panel, ledger, and digest requirement remains unchanged. |

## Execution Policy

- work-unit defaults: work-unit=`lane_execute`, effort=`high`, unsupported=`inherit_default`, inherit-default=`true`
- SL-6: work-unit=`phase_reducer`, effort=`high`, unsupported=`inherit_default`, inherit-default=`true`, reason=`terminal evidence and documentation reducer`

## Execution Notes

- Policy precedence is CLI/operator override, phase-plan policy, roadmap policy, `Dispatch Hints`, then registry defaults. This plan does not select the implementation author: the coordinator must explicitly rotate one whole-phase author vendor and keep both runtime schedulers off. Silent executor/model/effort downgrade is forbidden without explicit fallback or inherited defaults.
- Every model/reviewer invocation uses the existing subscription-authenticated CLI or native harness path only; API-key/provider-key execution and PI provider fallback are forbidden. REVIEWTRUTH performs no release publication, release creation, or tag creation.
- Plan review is a pre-dispatch gate, not a lane. At repair time the overwriteable run-local panel path contained historical predecessor content SHA-256 `ee125a63e4259cda103b432465f967fa47d9b2266ae37f7c11f6f2cf1e96e642`; that content reviewed predecessor plan `a3b5d97890f3551ba8813a947c8cf892aa10c98f910d177873ed78b61a4a4a50`, roadmap `70c2ca94cc1b43f92cbcc2cd8298c9e713cf742c3e06d51a343708760342740c`, bundle `3f3952b4d29e1dfc5ef710fcfc5aab9d63811b83537527cb8b1b8074328dc171` (`538155` bytes), instructions `c03bbe6bee8638d7c8b29b112106b2c38771a8240b4fe0bb21455d57b5796654`, and early evidence `20271a6a76ae20e758b96e26bd61d7779a14458fd91469e066005f5860382578`. Grok and Gemini agreed, Sol dissented on the extra `/tmp` authority and impossible live-plan Stage-A regeneration, and Fable deferred, so it authorizes nothing. The path itself is neither immutable nor promised to remain current after the next review. This repaired digest is unreviewed and not approved. Record a fresh exact repaired-plan digest, executor/model/effort, Fable/Sol reviewed outcomes, all four seat outcomes, and resolution of every material finding in the canonical runner ledger before SL-0. Any changed byte after that review requires another exact-digest panel.
- Before the REVIEWTRUTH lane DAG begins, this planning candidate owns and lands `phase-loop-runtime/uv.lock` at SHA-256 `b89987030b895131c3de05a316783ac0bcb6423d5531d6e9a04ee4a8f1e9fcce` together with this plan and its manifest metadata. That prerequisite must be on canonical `main` before SL-0 dispatch and is intentionally absent from every lane's `Owned files`: SL-0 through SL-6 consume the frozen committed input but may not create, regenerate, replace, or claim it in tests-only, implementation, or closeout history. A different or later lock invalidates the reviewed plan/bootstrap identity; it cannot retroactively alter the observation.
- The predecessor 35-pattern phase-write-set digest and ten-path SL-1 digest are historical only. This repair adds `phase-loop-runtime/tests/test_phase_worktree_executor.py` to SL-1 and `phase-loop-runtime/src/phase_loop_runtime/phase_worktree_executor.py` to SL-2, while making the already-listed `launcher.py`, `advisor_board/schema.py`, and `gate_posture.py` operational rather than nominal. Stage B must recompute the complete sorted write-set count/digest and the exact eleven-path SL-1 boundary; no predecessor union digest authorizes dispatch.
- SL-0 and SL-1 require separate landings after Stage B. Stage A first observes the dependency-complete base without tracked mutation and freezes its exact plan/roadmap bytes as immutable external snapshots. Stage B regenerates the Stage-A manifest from those snapshots, separately binds its revised live plan digest through the manifest row, early evidence, bundle, and ordered plan review, and never equates the two plan byte sets. The capability record then binds all three comments in its own PR; the tests-only change adds the exact eleven SL-1 paths, including `test_phase_worktree_executor.py`, and passes literal RED, parser, collection and ordered Codex/critics/Fable review before production work. The external runner root is evidence, never a landing path, and none of the eleven tracked paths may appear in the implementation range.
- Stage-B SL0-T3 is the only gate that completes SL-0. It proves all three exact directives, effective PR-only target protection, two-parent record topology, and record-only contents. `agent-harness#405` supplies no authority. `reviewtruth_preimplementation_chronology_all` independently repeats those facts and the exact-base/profile binding and alone unblocks SL-2 through SL-5.
- The tests-only production-activation boundary, post-parser collection boundary, exact source/CI and Gate-A collection-profile freezes, collection-plugin/root profiles, and all marker/hook/collection-skip/runtime-skip accounting categories are immutable. `PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1` forces new production behavior only for the pre-implementation RED proof; absent that variable, the exact `REVIEWTRUTH_CAPABILITY_MARKER = "reviewtruth@1"` switches the same non-wrapper test bodies from default legacy/skip behavior to new assertions. Neither activates the five post-parser wrappers. Ordinary/default tests-only CI, marker-present implementation CI, the frontmatter suite command, the explicitly amended workflow, and fresh source-clone default suites are GREEN because their canonical collection must equal the frozen source-capable pre-edit sets plus exactly the declared new REVIEWTRUTH nodeids; built-in `-m "not dotfiles_integration"` selection contributes exactly the frozen pre-edit marker deselection baseline; and the try-last conftest hook separately contributes exactly the five wrapper deselections unless the exact value `PHASE_LOOP_REVIEWTRUTH_POST_PARSER_COLLECTION=junit-run:final:v1` is set by final `junit-run` after broad-final attestation. Clean-room Gate A is GREEN under its separate exact profile: identical copied repo-owned bytes; source/CI sets minus exactly the 48 unmarked nodeids from the four named collection-skipped modules; the exact expected collection/runtime skip unions composed from the retained source baselines plus the proved four-tuple collection and 59-tuple runtime boundaries; and the same retained marker baseline UNION exact five wrapper deselections. Phase-selected default/RED/candidate use the frozen non-wrapper phase set; final uses the full expected set and requires zero phase skips/deselections. Source/CI broad default/candidate/broad-final retain exact source-capable full/selected and skip equality; Gate A must equal only its separately frozen profile. The implementation installs only the marker and production behavior. It cannot edit conftest, test imports, guards, branch/collection predicates, activation name/value, nodeids, selectors, expected counts/digests, collection/plugin/root profiles, any skip set/reason, any deselection tuple/category/reason, RED anchors, JUnit runner/parser, or evidence wrappers. No `xfail`, external `--deselect`, arbitrary deselection, unapproved collection-capable plugin, category substitution, source/CI or Gate-A full/selected/marker/plugin/root drift, or hook drift is permitted; any collection/import failure or skip beyond the exact frozen Gate-A expected collection-skip union, unexpected/drifted skip or deselection, ordinary-suite/CI/Gate-A red status, or compatibility test that first fails after merge is a hard failure.
- SL-2 changes exactly its six owned production files: `panel_invoker.py`, `launcher.py`, `advisor_board/schema.py`, `advisor_board/composition.py`, `fab_gate.py`, and `phase_worktree_executor.py`. It preserves the degraded-seat trust-root contract while implementing the EC-REVIEWTRUTH-17 capability, sandbox, worktree/data-scope, reaper, evidence-wave, and ordering seams. No later lane may weaken or duplicate those contracts.
- Pytest/pluggy distribution versions, interpreter and absolute module or distribution paths, module/file digests, and version-bearing approved core-plugin metadata remain mandatory in every bootstrap, source/CI, and Gate-A provenance record and mismatch diagnostic, but are never semantic equality keys by themselves. Cross-environment parity compares the repo-owned test/conftest/parser bytes and digests, declared selectors, exact application-plugin entry points and repo-owned origins, declared repository/root maps, normalized approved core-plugin roles/origins, and each environment's frozen source/CI or Gate-A canonical nodeid/skip profile, hook behavior, command profile, collection outcome, exit status, and JUnit/result accounting. The parser and conftest controls must accept a fixture that changes only those pytest/pluggy diagnostic values while preserving the applicable semantic profile, and must reject a paired toolchain fixture that changes plugin origin, repo-owned bytes, profile selection, collection, nodeids, skip/deselect accounting, hook behavior, exit status, or results. Missing or internally inconsistent provenance also fails; provenance-only release drift does not.
- Source/CI skip parity applies PC-REVIEWTRUTH-5A, PC-REVIEWTRUTH-5B, and PC-REVIEWTRUTH-5C independently before equality. The one collected hard-coded-interpreter node is classified as `portable_pass` or exact `environment_interpreter_pair_unavailable`; the exact PyPI node is classified as `pypi_metadata_available_pass` or exact source-attributed `pypi_transport_unavailable`; and the exact console-script node is classified as `console_script_available_pass` or exact `source_layout_console_script_unavailable` only under the source-module, absent-CI, absent-sibling predicate. Each of the three validators can remove at most its own one validated raw tuple, records its own raw facts and diagnostics, and rejects a tuple belonging to the other disposition. The remaining semantic source/CI skip set must equal the frozen baseline exactly across bootstrap, source/default, candidate, Python 3.10/3.11/3.12 CI, broad-final, and final. All three literal normalization falsifiers are part of `REVIEWTRUTH_EXPECTED_NODEIDS`, `REVIEWTRUTH_PHASE_NODEIDS`, `REVIEWTRUTH_NEW_NODEIDS`, candidate/final JUnit, attestations, and evidence digests; PC-REVIEWTRUTH-5A retains its existing activation/RED mapping, while the exact-PyPI and exact-console nodes form the separately frozen count-2 `REVIEWTRUTH_SL1_INFRASTRUCTURE_TDD_NODEIDS` RED/then-GREEN pair and are absent from the downstream activated-RED set. SL-1 freezes all exact memberships/counts/digests. Gate A applies none of the three normalizations: its line-111 release-pin root-missing skip remains literal and its 39+4+59 contract is unchanged. No broad environment/network/command exclusion, additional portable node, second network-normalized node, second console-normalized node, or package-installed/CI/Gate-A console normalization may be added after the tests-only freeze.
- SL-2 through SL-5 are authored by one explicitly rotated whole-phase author vendor, remain together on the distinct implementation branch, and cross one implementation review/landing boundary before SL-6. Both runtime schedulers stay off; file-disjointness does not authorize a second author vendor. Intermediate lane checks use their immutable focused selectors because installing the marker intentionally exposes downstream RED tests until their owner lane is implemented; no intermediate candidate may panel or merge. After SL-5, every implementation candidate is pushed. A fresh repo-local process proves it is bound to the exact server-reported pushed head, generates phase-candidate XML at `.phase-loop/evidence/reviewtruth-phase-candidate.xml` over the frozen non-wrapper phase set, generates broad-candidate XML at `.phase-loop/evidence/reviewtruth-broad-candidate.xml` with the immutable marker-selection baseline and ordinary conftest hook separately attested, and invokes the frozen parser in candidate mode against those exact existing paths. The parser requires zero selected phase skips, total broad deselections equal to marker baseline UNION the five hook-owned wrappers with each category exact, and the unchanged semantic broad skip baseline after PC-REVIEWTRUTH-5A, PC-REVIEWTRUTH-5B, and PC-REVIEWTRUTH-5C are independently validated and separately recorded with raw evidence; it never claims five total broad deselections or broad zero skips. The suite command and required amended GitHub CI on Python 3.10, 3.11, and 3.12 must apply the same exact-node dispositions and be GREEN at the same exact pushed head before the exact golden, fresh exact-head review, or merge decision. The workflow falsifier must prove its private-copy allocation, selector rejection, script-then-attester ordering, attester-then-cleanup order, and unchanged Gate-A line-111 skip profile at that head. Every finding repair creates a new pushed head and invalidates all prior XML, parser, suite/CI, golden, and review evidence. The exact-head review is ordered: isolated early Codex evidence, critics including GPT-5.6 Sol, then usable grounded artifact-bound Fable; Gemini 3.6 Flash and Grok 4.5 remain in the critic roster. The implementation PR then lands as a two-parent merge whose first parent already contains both prior landings. SL-6 starts only from a different fresh process at the exact fetched post-merge canonical-main head.
- The owned chronology verifier has separate `pre-implementation` and `final` ancestry modes over full immutable SHAs and server-recorded PR/head identities, exact-selector `junit-run` modes `default-premarker`, `activated-red`, `candidate`, and `final`, and parser modes `broad-baseline`, `default-premarker`, `activated-red`, `candidate`, `broad-final-producer`, and `final`. Its `broad-baseline` mode accepts only explicit canonical absolute external-root/provisioning/observation/observer paths after the observer ran: it independently verifies the private disjoint runner boundary, exact embedded observer and provisioning digests, raw artifact/JUnit digests and outcomes, plan/roadmap SHA, empty all-untracked status and same HEAD/tree/index, same process identity, command and uv/interpreter/package/source/wheel/distribution/RECORD/`sys.path`/pytest/module/plugin provenance, exact source-capable full and selected collections, exact marker difference, and legitimate skips. It then freezes the allowed source/CI post-SL-1 full/selected transform; the separately derived Gate-A full/selected transform, exact four-module/48-nodeid collection boundary, 59-tuple runtime boundary, 39-tuple retained source baseline, and 102-tuple expected union, and sibling/root absence proof; source/CI versus Gate-A plugin/root profiles; full/non-wrapper/post-parser and broad nodeid sets/counts/sorted-LF SHA-256 digests; the conftest digest and exact collection name/value/predicate; migrated legacy run set; activated RED nodeids/raw anchors; the exact marker-filter deselection tuple/count/digest and five exact hook-owned ordinary deselections as disjoint categories; candidate zero-phase-skip plus source/CI collection/plugin/marker/hook/skip-baseline accounting; and final all-expected-ran-once zero-phase-skip/deselection plus unchanged source/CI broad accounting. Both ancestry modes refuse a shallow repository, grafts, or `refs/replace`. Final mode resolves the implementation landing with `git rev-list --parents -n 1`, requires exactly two parents, treats its first parent as the pre-landing target tip, applies `git merge-base --is-ancestor` to both the recorded disposition SHA and tests-only landing SHA against that first parent, requires the landing message to contain the full record SHA, and matches all three landings to distinct server-recorded PR metadata. It also rejects a reused tests-only head identity, any SL-1 tests-only commit in `implementation^1..implementation^2`, any of the eleven frozen SL-1 paths in that range or the server-recorded implementation PR diff, and any implementation source that diverges from the ratified posture. The five exact post-parser wrappers are absent from non-final phase selectors, hook-deselected in addition to the marker baseline from ordinary source/CI broad/default/fresh-clone collection and the retained Gate-A collection, and must all run exactly once with zero phase skips/deselections in phase-final XML only after `junit-run --mode final` verifies broad-final and sets its child-only exact activation. Their frozen assertions consume only pre-phase-final inputs, so the phase-final XML, final-mode parser attestation, post-parser finalized record, `final-record` attestation, and closeout verdicts stay outside every wrapper; after the final parse, `finalize-record` writes the finalized record, the separate `final-record` verifier attests it from outside, the sanitized Gate A reducer emits its independently checked profile attestation later, and only then does the closeout bind all three terminal evidence identities. Squash, rebase, direct-push, single-parent landing, same-branch history, a record carried only on the implementation branch, tests in the implementation range, bootstrap-root/provisioning/observer/provenance/raw-artifact drift, user/system-site fallback, external/arbitrary/category-swapped deselection, source/CI or Gate-A profile/full/selected/skip/marker/plugin/root/hook drift, marker-driven wrapper collection, final activation before broad-final attestation, parser-before-generation, wrapper-before-attestation, finalization-before-final-parse, record-verification-before-finalization, closeout-before-record-attestation, or blanket roadmap authorization is a phase failure.
- Before evaluating tests-only ancestry, the owned chronology verifier independently repeats the frozen SL0-T3 record-envelope, comment digest/token, maintainer-permission, all-three-comment-timestamps-before-or-at-merge, canonical effective-rules query, required `pull_request` rule, server PR, two-parent/second-parent-head, record-only path, unchanged-record, and canonical-main ancestry checks from fresh Git/GitHub metadata. It must recompute sorted compact JSON plus terminal-LF SHA-256 for the rules response and require both that digest and `effective_pull_request_rule=true` to equal the retained SL0-T3 proof; it may compare all other retained fields for diagnostics but cannot trust the proof as input authority. Effective protection and actual merge topology remain separate assertions. This retrospective check gates only SL-2 through SL-5; SL-1 was already authorized by the standalone coordinator proof.
- SL-3 and SL-4 are file-disjoint, but SL-4 has a real data dependency on SL-3's `GovernedBoardEvidence.grounded_reviewed_seats`; prose order is not a substitute for that edge. SL-3 only publishes grounding/material helpers. SL-5 exclusively owns `train_runner.py` and `train_ledger.py`, runs after SL-4, and consumes those helpers plus `BoardDeliveryState`/`classify_board_delivery()` for live train review, ledger write, and resume. The coordinated v10 runtime lane scheduler stays off to preserve a single author vendor.
- Durable train review approval is schema/policy evidence, not a count snapshot: `REVIEW_POLICY_VERSION` is incremented for the grounding/three-state migration, `delivery_state` is derived only from grounded reviewed seats, and resume requires both the exact current version and a train-gate-authorizing typed state. Every existing `test_train_merge.py` honor/crash/recovery fixture that currently plants `usable_reviewers=2` or count-only evidence is migrated in SL-1; existing pre-migration/count-only approvals, two-reviewed evidence, raw ungrounded usable evidence, missing state, BELOW-FLOOR, and stale/missing policy identity never short-circuit review. Only valid current-policy grounded FULL/FLOOR-ONLY is a positive resume control and follows the explicit train gate policy.
- Native fill is a durable attempt protocol, not an in-memory `seat_key` lookup. A unique stable `seat_instance_id` identifies one requested seat through retries even when two seats share the same non-unique `seat_key`; every request emission/retry allocates fresh non-reused `request_id` and `attempt_id`; and request/report both carry the exact artifact/brief/lens/prompt digests. Binding consumes one current pending tuple atomically and at most once. Unknown, late, stale, replayed, cross-seat/colliding-seat, identity/digest-mismatched, and non-terminal reports produce typed rejected transitions and never mutate a seat or count. Canonical metadata-only events reconstruct emitted, pending, superseded, consumed, and rejected identities before retry/resume, so a process restart or late first-attempt report cannot re-inflate reviewed or grounded counts.
- `test_advisor_board_golden.py` is an SL-1-owned normative contract, not an SL-6 discovery aid. Its sanctioned-delta list freezes the additive typed result fields, prompt/lens carrier, and native request/report identity/digest surface required by IF-0-REVIEWTRUTH-1 while preserving every unlisted legacy launch/result/serialization behavior. The adjacent SL-1 compatibility migrations freeze the exact `dataclasses.asdict` shape transition, Fable/Opus native-request reversal, and all three under-Claude-Code Fable native-fill reversals under their five unchanged full nodeids. Each migrated nodeid has immutable legacy/default, forced-activation/new, and automatic post-marker/new assertions over every affected field, including stable seat-instance, fresh request/attempt identities, and artifact/brief/lens/prompt digests; the no-local-CLI node proves the local support probe is irrelevant after the host is identified as Claude Code, while the brief-flow node binds the resolved `brief_ref`, instructions, and their digests. SL-2 through SL-5 cannot edit or rebaseline any of them; the ordered candidate phase/broad parser, ordinary suite/CI, and exact golden command gate every implementation panel/merge. SL-6 only mirrors the frozen rule into `advisor_board/CONTRACTS.md` and `docs/advisor-board-capabilities-card.md` and re-runs it.
- The coordinated run retains its bootstrap no-degraded-promotion interlock: planning, tests, implementation review, and closeout require all four intended seats with Fable and Sol reviewed. The closeout board reviews the exact finalized evidence record digest, the `final-record` attestation, and the terminal Gate A suite attestation, and its verdict is written only to the canonical ledger. The runtime implementation may represent FLOOR-ONLY and follow an explicit downstream policy, but this phase cannot use its own new degraded semantics to waive the board that authorizes it.
- `timed_out` is frozen and consumed here; subprocess timeout enforcement, process-group killing, and child reaping stay owned by LEGLIFE. Per-repo custom seats and RISCO lenses also stay out of scope.
- The `REVIEWTRUTH-redacted-transcript-policy` designates `docs/research/reviewtruth-real-panel-smoke.md` as the single canonical durable redacted transcript and smoke record and requires it to prove inspection, not command construction. Raw model output remains only in the protected live artifact. The canonical repo file contains only redacted transcript material, artifact-specific citations, seat identities/outcomes, and metadata, has one frozen SHA-256 digest for its combined transcript/smoke identity, and may not be accompanied by a second durable transcript path; do not substitute argv goldens or a hand-built `panel_verdict` event. Metadata-only closeout records only that exact path and single digest, seat identities/outcomes, and citations, never raw model output. The post-parser finalized evidence record and `final-record` attestation are likewise metadata-only: digests, paths, identities, and outcomes, never raw model output.
- This plan is intentionally pre-PROOFGATE. Its Acceptance Criteria use the currently accepted `proven by <command>` plan grammar; each roadmap criterion's `falsified by` mutation is bound in SL-1 to a named test, asserted injection anchor, and positive control, and the RED/evidence records retain that mapping. `IF-0-PROOFGATE-1` is produced and mechanically required only by the later PROOFGATE phase, so this plan neither claims that future interface nor drops its falsifiers.
- Documentation impact: SL-6 updates the normative board contract and capability card because the roadmap reverses the Fable native-fill prohibition narrowly. Record `no_doc_delta` for `README.md`, `CHANGELOG.md`, packaging dependency declarations, env examples, migrations, and release notes because REVIEWTRUTH changes no public release/package surface. The newly tracked `phase-loop-runtime/uv.lock` is instead this plan repair's frozen bootstrap prerequisite and is complete before SL-0; it is not an SL-6 documentation delta or a later REVIEWTRUTH implementation change.

### Exact bootstrap observer payloads

No suitable immutable coordinator/runner observer exists for either complete pre-edit profile. The materialization command in `## Verification` extracts both exact payloads between their separate sentinels, appends each displayed terminal LF, and refuses any source-observer digest other than `841cfb8bbac1d9b4ea0bb14a1f3600165550227b680b2e5689c79c13c61b1f6d` (`39420` bytes) or Gate-A-observer digest other than `d51199649bf0c4a2ed3c647e210128ecd07112c5229143b976de7600943af3c9` (`45116` bytes). The dedicated second payload preserves the already-reviewed source observer and keeps the installed-wheel/tests-only copied namespace, external standalone cwd, and absent sibling/root profile explicit rather than branching the source-layout contract. The bootstrap is intentionally external to every SL-1 tracked path: a coordinator supplies a new canonical absolute runner root outside Git, and the provisioning environment, exact lock-bearing external Git-archive source, wheel, uv-managed Python, HOME/TMPDIR, both materialized observers, provisioning freeze, exact committed Gate-A input copy, both immutable Stage-A plan/roadmap snapshots, and both successful observations all stay beneath it. The root, its direct bootstrap directories, observers, freeze, copied input, snapshots, and evidence paths are write-once, privately owned/mode-checked, and non-symlinked; a venv interpreter link is accepted only when its real target stays under the root's uv-managed Python directory. Its trust chain is: both exact payloads and digests reviewed with this plan; committed planning lock digest `b89987030b895131c3de05a316783ac0bcb6423d5531d6e9a04ee4a8f1e9fcce`; external provisioning from grounded repository package/CI sources; exact mode-specific `env -i` allowlists and uv/interpreter/package/source/wheel/distribution/RECORD/`sys.path`/module/application-selector/plugin/root profiles; Stage-A plan digest and empty all-untracked Git status recorded before any SL-1 edit; source-layout and copied-tree raw observations sealed before repo verifier authorship; atomic external Stage-A plan/roadmap snapshots immediately proved equal to their live sources; Stage-A internal-relation validation, complete direct-file candidate-artifact manifest over those snapshots, immediate filesystem regeneration/byte comparison, and domain-separated candidate-profile digest; Stage-B exact-base/manifest/digest freezing and independent fresh-process re-verification from the snapshots plus a separate reviewed live Stage-B plan digest check; independent post-observation parser and synthetic/tamper tests over both exact payloads and their provisioning/environment/plugin/root contracts; tests-only ordered early-Codex/critics/Fable review binding of provisioning, both observers, both raw observations, parser, and record digests; and immutable final chronology. Each observer's own attestation is necessary raw evidence, not sufficient authority.

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

<!-- REVIEWTRUTH_GATE_A_BASELINE_OBSERVER_BEGIN -->
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
import site
import stat
import subprocess
import sys
import uuid
import zipfile

import pytest

SCHEMA = "reviewtruth.gate-a-preimplementation-observation.v1"
SOURCE_SCHEMA = "reviewtruth.baseline-observation.v3"
PROVISION_SCHEMA = "reviewtruth.bootstrap-provisioning.v1"
SOURCE_OBSERVER_SHA256 = "841cfb8bbac1d9b4ea0bb14a1f3600165550227b680b2e5689c79c13c61b1f6d"
SOURCE_ARTIFACT_NAMES = (
    "broad.xml",
    "full-nodeids.txt",
    "legitimate-skips.json",
    "marker-deselected-nodeids.txt",
    "plugin-events.json",
    "selected-nodeids.txt",
    "stderr.txt",
    "stdout.txt",
)
MARKER = "dotfiles_integration"
PROFILE_SELECTOR = "phase_loop_runtime.dotfiles_profile_plugin:register_profile_commands"
SKILL_SOURCE_SELECTOR = "phase_loop_runtime.skill_sources_plugin:register_skill_sources"
APPLICATION_PLUGIN_GROUPS = (
    "phase_loop_runtime.profile_commands",
    "phase_loop_runtime.skill_sources",
)
EXPECTED_ENTRY_POINTS = {
    "phase_loop_runtime.profile_commands": ("dotfiles", PROFILE_SELECTOR),
    "phase_loop_runtime.skill_sources": ("dotfiles", SKILL_SOURCE_SELECTOR),
}
OMITTED_STANDALONE_PATHS = (
    ".github/workflows",
    "RELEASE_PIN",
    "bootstrap.sh",
    "docs",
    "install.sh",
    "phase-loop-runtime/pyproject.toml",
    "phase-loop-runtime/scripts",
    "phase-loop-runtime/uv.lock",
    "phase-loop-skills",
    "plans",
    "skills-src",
    "specs",
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sorted_lf(values: list[str]) -> bytes:
    return "".join(f"{value}\n" for value in sorted(values)).encode()


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def exact_absolute(raw: str, label: str, *, exists: bool = True) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        raise RuntimeError(f"{label} must be absolute")
    resolved = path.resolve(strict=exists)
    if path != resolved:
        raise RuntimeError(f"{label} must be canonical and non-symlinked")
    return path


def require_private(path: Path, *, directory: bool) -> None:
    if not path.is_absolute() or path != path.resolve(strict=True):
        raise RuntimeError(f"private path is not canonical: {path}")
    metadata = path.lstat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise RuntimeError(f"private path has wrong type: {path}")
    if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
        raise RuntimeError(f"private path has wrong owner or mode: {path}")


def git(repo: Path, *argv: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), *argv],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


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


def source_observation_manifest(
    source_observation: Path, source_attestation: dict[str, object]
) -> list[dict[str, object]]:
    require_private(source_observation, directory=True)
    if stat.S_IMODE(source_observation.stat().st_mode) != 0o700:
        raise RuntimeError("source observation directory mode is not exactly 0700")
    artifacts = source_attestation.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != set(SOURCE_ARTIFACT_NAMES):
        raise RuntimeError("source attestation artifact set is not exact")
    expected_names = set(SOURCE_ARTIFACT_NAMES) | {"attestation.json"}
    children = sorted(source_observation.iterdir(), key=lambda path: path.name)
    if {path.name for path in children} != expected_names:
        raise RuntimeError("complete source observation file set drifted")
    records = []
    for path in children:
        require_private(path, directory=False)
        if path.parent != source_observation or path != path.resolve(strict=True):
            raise RuntimeError(f"source observation path is not canonical and direct: {path}")
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode != 0o600:
            raise RuntimeError(f"source observation file mode is not exactly 0600: {path}")
        data = path.read_bytes()
        record = {
            "relative_path": path.name,
            "mode": "0600",
            "bytes": len(data),
            "sha256": sha(data),
        }
        if path.name != "attestation.json":
            expected = artifacts.get(path.name)
            if not isinstance(expected, dict) or set(expected) != {"bytes", "sha256"}:
                raise RuntimeError(f"source artifact metadata is malformed: {path.name}")
            if expected != {"bytes": len(data), "sha256": sha(data)}:
                raise RuntimeError(f"source artifact bytes or digest drifted: {path.name}")
        records.append(record)
    return records


def expected_initial_environment(runner_root: Path, tests_root: Path) -> dict[str, str]:
    return {
        "HOME": str(runner_root / "home"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": f"{runner_root / 'venv' / 'bin'}:/usr/bin:/bin",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": str(tests_root),
        "TMPDIR": str(runner_root / "tmp"),
    }


def expected_post_environment(runner_root: Path, tests_root: Path) -> dict[str, str]:
    return {
        **expected_initial_environment(runner_root, tests_root),
        "PHASE_LOOP_PROFILE_PLUGINS": PROFILE_SELECTOR,
        "PHASE_LOOP_SKILL_SOURCE_PLUGINS": SKILL_SOURCE_SELECTOR,
    }


def environment_snapshot() -> dict[str, str]:
    return {key: os.environ[key] for key in sorted(os.environ)}


def copied_tests_manifest(repo: Path, tests_root: Path) -> list[dict[str, object]]:
    raw = git(repo, "ls-tree", "-r", "-z", "HEAD", "--", "phase-loop-runtime/tests")
    expected_paths: set[str] = set()
    records: list[dict[str, object]] = []
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        metadata, encoded_path = entry.split(b"\t", 1)
        mode, kind, oid = metadata.decode().split()
        repo_path_text = encoded_path.decode()
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise RuntimeError(f"unsupported committed tests entry: {repo_path_text}")
        relative = Path(repo_path_text).relative_to("phase-loop-runtime/tests").as_posix()
        expected_paths.add(relative)
        repo_path = repo / repo_path_text
        copied_path = tests_root / relative
        if repo_path.is_symlink() or copied_path.is_symlink():
            raise RuntimeError(f"symlinked test input is forbidden: {repo_path_text}")
        repo_bytes = repo_path.read_bytes()
        copied_bytes = copied_path.read_bytes()
        blob_bytes = git(repo, "cat-file", "blob", oid)
        if repo_bytes != blob_bytes or copied_bytes != blob_bytes:
            raise RuntimeError(f"copied test differs from committed blob: {repo_path_text}")
        copied_mode = stat.S_IMODE(copied_path.stat().st_mode)
        if copied_path.stat().st_uid != os.getuid() or copied_mode & 0o077:
            raise RuntimeError(f"copied test is not private: {copied_path}")
        records.append(
            {
                "repo_path": repo_path_text,
                "copied_relative_path": relative,
                "git_mode": mode,
                "git_oid": oid,
                "copied_mode": oct(copied_mode),
                "sha256": sha(copied_bytes),
                "bytes": len(copied_bytes),
            }
        )
    actual_paths: set[str] = set()
    for path in tests_root.rglob("*"):
        if path.is_symlink():
            raise RuntimeError(f"symlink in copied tests tree: {path}")
        metadata = path.lstat()
        if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
            raise RuntimeError(f"copied tests owner or mode escaped privacy: {path}")
        if path.is_file():
            actual_paths.add(path.relative_to(tests_root).as_posix())
    if actual_paths != expected_paths or not records:
        raise RuntimeError("copied tests inventory differs from exact committed tests inventory")
    return sorted(records, key=lambda row: str(row["repo_path"]))


def omitted_roots_record(tests_root: Path) -> dict[str, object]:
    runtime_root = tests_root.parent
    standalone_root = runtime_root.parent
    detector_root = (tests_root / "x").resolve().parents[3]
    if sorted(path.name for path in runtime_root.iterdir()) != ["tests"]:
        raise RuntimeError("standalone runtime root must contain only tests")
    if sorted(path.name for path in standalone_root.iterdir()) != ["phase-loop-runtime"]:
        raise RuntimeError("standalone root must contain only phase-loop-runtime")
    if sorted(path.name for path in detector_root.iterdir()) != ["standalone"]:
        raise RuntimeError("parents[3] detector root must contain only standalone")
    rows = []
    for scope, root in (("standalone", standalone_root), ("parents_3", detector_root)):
        for relative in OMITTED_STANDALONE_PATHS:
            path = root / relative
            rows.append(
                {
                    "scope": scope,
                    "relative_path": relative,
                    "exists": path.exists() or path.is_symlink(),
                }
            )
    if any(row["exists"] for row in rows):
        raise RuntimeError(f"intentional standalone omission unexpectedly exists: {rows!r}")
    detector_present = (detector_root / "claude-config").is_dir() and (
        detector_root / "bootstrap.sh"
    ).is_file()
    if detector_present:
        raise RuntimeError("copied tests parents[3] resolves a dotfiles tree")
    return {
        "standalone_root": str(standalone_root),
        "runtime_root": str(runtime_root),
        "tests_root": str(tests_root),
        "parents_3_detector_root": str(detector_root),
        "parents_3_dotfiles_present": detector_present,
        "omitted": rows,
        "omitted_sha256": sha(canonical_json(rows)),
    }


def canonical_nodeid(nodeid: str, tests_root: Path, rootpath: Path) -> str:
    path_text, marker, suffix = nodeid.partition("::")
    path = Path(path_text)
    if not path.is_absolute():
        path = rootpath / path
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(tests_root).as_posix()
    except ValueError as exc:
        raise RuntimeError(f"nodeid escaped copied tests tree: {nodeid}") from exc
    return "phase-loop-runtime/tests/" + relative + ((marker + suffix) if marker else "")


def normalized_reason(value: object, repo: Path, standalone_root: Path) -> str:
    text = str(value).replace(str(standalone_root), "<REPO>")
    return text.replace(str(repo), "<REPO>")


def file_record(path: Path | None, repo: Path, tests_root: Path, venv: Path) -> dict[str, object] | None:
    if path is None or not path.exists():
        return None
    resolved = path.resolve()
    if is_within(resolved, repo):
        raise RuntimeError(f"Gate A loaded source from the git worktree: {resolved}")
    if is_within(resolved, tests_root):
        location = "copied_tests"
        relative = resolved.relative_to(tests_root).as_posix()
    elif is_within(resolved, venv):
        location = "isolated_venv"
        relative = resolved.relative_to(venv).as_posix()
    else:
        location = "managed_python_or_stdlib"
        relative = None
    data = resolved.read_bytes() if resolved.is_file() else b""
    return {
        "path": str(resolved),
        "location": location,
        "relative_path": relative,
        "sha256": sha(data) if data else None,
        "bytes": len(data) if data else None,
    }


def wheel_module_record(module_name: str, wheel: Path, runner_root: Path) -> dict[str, object]:
    module = importlib.import_module(module_name)
    module_path = Path(module.__file__).resolve()
    venv = (runner_root / "venv").resolve()
    if not is_within(module_path, venv):
        raise RuntimeError(f"installed module escaped isolated venv: {module_name}")
    distribution = importlib.metadata.distribution("phase-loop-runtime")
    distribution_root = Path(distribution.locate_file("")).resolve()
    member = module_path.relative_to(distribution_root).as_posix()
    with zipfile.ZipFile(wheel) as archive:
        wheel_bytes = archive.read(member)
    installed_bytes = module_path.read_bytes()
    if installed_bytes != wheel_bytes:
        raise RuntimeError(f"installed module differs from local wheel member: {member}")
    return {
        "module": module_name,
        "installed_path": str(module_path),
        "wheel_member": member,
        "sha256": sha(installed_bytes),
        "bytes": len(installed_bytes),
    }


def entry_point_records(group: str) -> list[dict[str, object]]:
    try:
        points = importlib.metadata.entry_points(group=group)
    except TypeError:
        points = importlib.metadata.entry_points().get(group, [])
    return sorted(
        [
            {
                "group": group,
                "name": point.name,
                "value": point.value,
                "distribution": getattr(getattr(point, "dist", None), "name", None),
                "distribution_version": getattr(getattr(point, "dist", None), "version", None),
                "distribution_path": str(getattr(getattr(point, "dist", None), "_path", "")),
            }
            for point in points
        ],
        key=lambda row: (str(row["name"]), str(row["value"])),
    )


def application_profile(repo: Path, runner_root: Path, tests_root: Path, wheel: Path) -> dict[str, object]:
    post_environment = environment_snapshot()
    if post_environment != expected_post_environment(runner_root, tests_root):
        raise RuntimeError(f"Gate A post-pytest environment drift: {post_environment!r}")
    entry_points = {group: entry_point_records(group) for group in APPLICATION_PLUGIN_GROUPS}
    for group, expected in EXPECTED_ENTRY_POINTS.items():
        records = entry_points[group]
        if len(records) != 1:
            raise RuntimeError(f"Gate A expected one installed entry point for {group}")
        record = records[0]
        if (record["name"], record["value"]) != expected:
            raise RuntimeError(f"Gate A entry-point value drift for {group}")
        if str(record["distribution"]).lower() != "phase-loop-runtime":
            raise RuntimeError(f"Gate A entry point is not from phase-loop-runtime: {record!r}")
        if not is_within(Path(str(record["distribution_path"])).resolve(), runner_root / "venv"):
            raise RuntimeError(f"Gate A entry point escaped isolated venv: {record!r}")
    from phase_loop_runtime.cli import _profile_command_registrars
    from phase_loop_runtime.skill_inventory import iter_skill_source_roots

    registrars = list(_profile_command_registrars())
    if len(registrars) != 1:
        raise RuntimeError("Gate A did not load exactly one profile registrar")
    module_name, _, attribute = SKILL_SOURCE_SELECTOR.partition(":")
    provider = getattr(importlib.import_module(module_name), attribute)
    if getattr(registrars[0], "__module__", None) != "phase_loop_runtime.dotfiles_profile_plugin":
        raise RuntimeError("Gate A loaded wrong profile registrar")
    if getattr(provider, "__module__", None) != "phase_loop_runtime.skill_sources_plugin":
        raise RuntimeError("Gate A loaded wrong skill-source provider")
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
        raise RuntimeError(f"Gate A skill-source declaration drift: {roots!r}")
    modules = [
        wheel_module_record("phase_loop_runtime", wheel, runner_root),
        wheel_module_record("phase_loop_runtime.dotfiles_profile_plugin", wheel, runner_root),
        wheel_module_record("phase_loop_runtime.skill_sources_plugin", wheel, runner_root),
    ]
    if any(is_within(Path(entry or os.getcwd()).resolve(), repo) for entry in sys.path):
        raise RuntimeError("Gate A sys.path reaches the git worktree")
    if site.ENABLE_USER_SITE:
        raise RuntimeError("Gate A user site is enabled")
    return {
        "post_pytest_environment": post_environment,
        "entry_points": entry_points,
        "installed_wheel_modules": modules,
        "skill_source_roots": roots,
        "sys_path": list(sys.path),
        "enable_user_site": site.ENABLE_USER_SITE,
    }


class Observer:
    def __init__(self, repo: Path, runner_root: Path, tests_root: Path, wheel: Path) -> None:
        self.repo = repo
        self.runner_root = runner_root
        self.tests_root = tests_root
        self.standalone_root = tests_root.parent.parent
        self.wheel = wheel
        self.rootpath = tests_root
        self.process = {"pid": os.getpid(), "ppid": os.getppid(), "cwd": os.getcwd()}
        self.initial_environment = environment_snapshot()
        self.full: list[str] = []
        self.selected: list[str] = []
        self.deselected: list[str] = []
        self.markers: dict[str, list[str]] = {}
        self.collection_skips: list[dict[str, str]] = []
        self.runtime_skips: list[dict[str, str]] = []
        self.plugins: list[dict[str, object]] = []
        self.application_plugins: dict[str, object] = {}

    def nodeid(self, value: str) -> str:
        return canonical_nodeid(value, self.tests_root, self.rootpath)

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_collection_modifyitems(self, session, config, items):
        self.rootpath = Path(config.rootpath).resolve()
        self.full = [self.nodeid(item.nodeid) for item in items]
        self.markers = {
            self.nodeid(item.nodeid): sorted({marker.name for marker in item.iter_markers()})
            for item in items
        }
        yield
        self.selected = [self.nodeid(item.nodeid) for item in items]

    def pytest_deselected(self, items):
        self.deselected.extend(self.nodeid(item.nodeid) for item in items)

    def pytest_runtest_logreport(self, report):
        if report.skipped:
            self.runtime_skips.append(
                {
                    "nodeid": self.nodeid(report.nodeid),
                    "phase": report.when,
                    "reason": normalized_reason(report.longrepr, self.repo, self.standalone_root),
                }
            )

    def pytest_collectreport(self, report):
        if report.skipped:
            self.collection_skips.append(
                {
                    "nodeid": self.nodeid(report.nodeid),
                    "phase": "collect",
                    "reason": normalized_reason(report.longrepr, self.repo, self.standalone_root),
                }
            )

    def pytest_sessionfinish(self, session, exitstatus):
        manager = session.config.pluginmanager
        distributions = {id(plugin): dist for plugin, dist in manager.list_plugin_distinfo()}
        venv = (self.runner_root / "venv").resolve()
        records = []
        for name, plugin in manager.list_name_plugin():
            module = plugin if inspect.ismodule(plugin) else inspect.getmodule(plugin)
            module_name = getattr(module, "__name__", type(plugin).__module__)
            module_path = (
                Path(module.__file__)
                if module is not None and getattr(module, "__file__", None)
                else None
            )
            dist = distributions.get(id(plugin))
            records.append(
                {
                    "plugin_name": str(name),
                    "module": module_name,
                    "class": type(plugin).__qualname__,
                    "distribution": getattr(dist, "project_name", None),
                    "distribution_version": getattr(dist, "version", None),
                    "file": file_record(module_path, self.repo, self.tests_root, venv),
                }
            )
        self.plugins = sorted(records, key=lambda row: (row["plugin_name"], row["module"]))
        self.application_plugins = application_profile(
            self.repo, self.runner_root, self.tests_root, self.wheel
        )

    def payload(self, pytest_argv: list[str], exit_code: int) -> dict[str, object]:
        full = sorted(self.full)
        selected = sorted(self.selected)
        deselected = sorted(self.deselected)
        difference = sorted(set(full) - set(selected))
        if len(full) != len(set(full)) or len(selected) != len(set(selected)):
            raise RuntimeError("Gate A duplicate collected or selected nodeid")
        if difference != deselected or len(deselected) != len(set(deselected)):
            raise RuntimeError("Gate A deselection notification differs from full-minus-selected")
        if any(MARKER not in self.markers.get(nodeid, []) for nodeid in difference):
            raise RuntimeError("Gate A non-marker nodeid appeared in marker difference")
        if any(MARKER in self.markers.get(nodeid, []) for nodeid in selected):
            raise RuntimeError("Gate A marker-filtered nodeid survived selection")
        post_environment = environment_snapshot()
        if post_environment != expected_post_environment(self.runner_root, self.tests_root):
            raise RuntimeError("Gate A environment drifted after pytest")
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
            "collection_skips": sorted(
                self.collection_skips,
                key=lambda row: (row["nodeid"], row["phase"], row["reason"]),
            ),
            "runtime_skips": sorted(
                self.runtime_skips,
                key=lambda row: (row["nodeid"], row["phase"], row["reason"]),
            ),
            "plugins": self.plugins,
            "environment_before_pytest": self.initial_environment,
            "environment_after_pytest": post_environment,
            "application_plugins": self.application_plugins,
        }


def row_key(row: dict[str, str]) -> tuple[str, str, str]:
    return row["nodeid"], row["phase"], row["reason"]


def rows_from_keys(values: set[tuple[str, str, str]]) -> list[dict[str, str]]:
    return [
        {"nodeid": nodeid, "phase": phase, "reason": reason}
        for nodeid, phase, reason in sorted(values)
    ]


def rows_digest(rows: list[dict[str, str]]) -> str:
    return sha(canonical_json(rows))


def paired_profile(source: dict[str, object], gate: dict[str, object]) -> dict[str, object]:
    if len(source["full_nodeids"]) != len(set(source["full_nodeids"])):
        raise RuntimeError("source observation contains duplicate full nodeids")
    if len(source["selected_nodeids"]) != len(set(source["selected_nodeids"])):
        raise RuntimeError("source observation contains duplicate selected nodeids")
    source_full = set(source["full_nodeids"])
    source_selected = set(source["selected_nodeids"])
    gate_full = set(gate["full_nodeids"])
    gate_selected = set(gate["selected_nodeids"])
    if not gate_full <= source_full or not gate_selected <= source_selected:
        raise RuntimeError("Gate A introduced a nodeid absent from source observation")
    omitted_full = sorted(source_full - gate_full)
    omitted_selected = sorted(source_selected - gate_selected)
    omitted_modules = sorted({nodeid.split("::", 1)[0] for nodeid in omitted_selected})
    source_rows = source["legitimate_skips"]
    source_collection = {row_key(row) for row in source_rows if row["phase"] == "collect"}
    source_runtime = {row_key(row) for row in source_rows if row["phase"] != "collect"}
    gate_collection = {row_key(row) for row in gate["collection_skips"]}
    gate_runtime = {row_key(row) for row in gate["runtime_skips"]}
    restricted_collection = rows_from_keys(source_collection & gate_collection)
    restricted_runtime = rows_from_keys(source_runtime & gate_runtime)
    boundary_collection = rows_from_keys(gate_collection - source_collection)
    boundary_runtime = rows_from_keys(gate_runtime - source_runtime)
    expected_collection = rows_from_keys(
        {row_key(row) for row in restricted_collection + boundary_collection}
    )
    expected_runtime = rows_from_keys(
        {row_key(row) for row in restricted_runtime + boundary_runtime}
    )
    restricted_union = rows_from_keys(
        {row_key(row) for row in restricted_collection + restricted_runtime}
    )
    expected_union = rows_from_keys(
        {row_key(row) for row in expected_collection + expected_runtime}
    )
    if expected_collection != rows_from_keys(gate_collection):
        raise RuntimeError("Gate A collection pair decomposition is incomplete")
    if expected_runtime != rows_from_keys(gate_runtime):
        raise RuntimeError("Gate A runtime pair decomposition is incomplete")
    source_marker = set(source["marker_deselected_nodeids"])
    gate_marker = set(gate["marker_deselected_nodeids"])
    if gate_marker != source_marker - set(omitted_selected):
        raise RuntimeError("Gate A marker accounting is not the source marker set minus omissions")
    return {
        "source_full_count": len(source_full),
        "source_full_sha256": sha(sorted_lf(list(source_full))),
        "source_selected_count": len(source_selected),
        "source_selected_sha256": sha(sorted_lf(list(source_selected))),
        "gate_a_full_count": len(gate_full),
        "gate_a_full_sha256": sha(sorted_lf(list(gate_full))),
        "gate_a_selected_count": len(gate_selected),
        "gate_a_selected_sha256": sha(sorted_lf(list(gate_selected))),
        "omitted_full_count": len(omitted_full),
        "omitted_full_sha256": sha(sorted_lf(omitted_full)),
        "omitted_selected_count": len(omitted_selected),
        "omitted_selected_sha256": sha(sorted_lf(omitted_selected)),
        "omitted_full_equals_omitted_selected": omitted_full == omitted_selected,
        "omitted_modules": omitted_modules,
        "omitted_modules_count": len(omitted_modules),
        "restricted_source_collection_count": len(restricted_collection),
        "restricted_source_collection_sha256": rows_digest(restricted_collection),
        "restricted_source_runtime_count": len(restricted_runtime),
        "restricted_source_runtime_sha256": rows_digest(restricted_runtime),
        "restricted_source_count": len(restricted_union),
        "restricted_source_sha256": rows_digest(restricted_union),
        "boundary_collection_count": len(boundary_collection),
        "boundary_collection_sha256": rows_digest(boundary_collection),
        "boundary_runtime_count": len(boundary_runtime),
        "boundary_runtime_sha256": rows_digest(boundary_runtime),
        "expected_collection_count": len(expected_collection),
        "expected_collection_sha256": rows_digest(expected_collection),
        "expected_runtime_count": len(expected_runtime),
        "expected_runtime_sha256": rows_digest(expected_runtime),
        "expected_gate_a_count": len(expected_union),
        "expected_gate_a_sha256": rows_digest(expected_union),
        "source_marker_deselected_count": len(source_marker),
        "source_marker_deselected_sha256": sha(sorted_lf(list(source_marker))),
        "gate_a_marker_deselected_count": len(gate_marker),
        "gate_a_marker_deselected_sha256": sha(sorted_lf(list(gate_marker))),
    }


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--roadmap", required=True)
    parser.add_argument("--runner-root", required=True)
    parser.add_argument("--wheel", required=True)
    parser.add_argument("--provisioning", required=True)
    parser.add_argument("--source-observation-dir", required=True)
    parser.add_argument("--tests-root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--observer-sha256", required=True)
    args = parser.parse_args()

    repo = exact_absolute(args.repo, "--repo")
    if Path(git(repo, "rev-parse", "--show-toplevel").decode().strip()).resolve() != repo:
        raise RuntimeError("--repo is not the exact git toplevel")
    runner_root = exact_absolute(args.runner_root, "--runner-root")
    require_private(runner_root, directory=True)
    plan = exact_absolute(args.plan, "--plan")
    roadmap = exact_absolute(args.roadmap, "--roadmap")
    wheel = exact_absolute(args.wheel, "--wheel")
    provisioning_path = exact_absolute(args.provisioning, "--provisioning")
    source_observation = exact_absolute(args.source_observation_dir, "--source-observation-dir")
    tests_root = exact_absolute(args.tests_root, "--tests-root")
    final = exact_absolute(args.out, "--out", exists=False)
    expected_tests_root = (
        runner_root
        / "gate-a-preimplementation-input"
        / "standalone"
        / "phase-loop-runtime"
        / "tests"
    )
    expected_source_observation = runner_root / "evidence" / "reviewtruth-baseline-preimplementation"
    expected_final = runner_root / "evidence" / "reviewtruth-gate-a-preimplementation"
    expected_provisioning = runner_root / "evidence" / "reviewtruth-bootstrap-provisioning.json"
    if plan != repo / "plans" / "phase-plan-v10-REVIEWTRUTH.md":
        raise RuntimeError("Gate A plan path is not exact")
    if roadmap != repo / "specs" / "phase-plans-v10.md":
        raise RuntimeError("Gate A roadmap path is not exact")
    if provisioning_path != expected_provisioning:
        raise RuntimeError("Gate A provisioning path is not exact")
    if tests_root != expected_tests_root:
        raise RuntimeError("Gate A tests root is not the exact external standalone copy path")
    if source_observation != expected_source_observation:
        raise RuntimeError("source observation path is not the exact paired write-once path")
    if final != expected_final or final.exists() or final.is_symlink():
        raise RuntimeError("Gate A output is not the exact new write-once path")
    observer_path = exact_absolute(str(Path(__file__)), "observer source")
    expected_observer = runner_root / "materialized" / "reviewtruth-gate-a-baseline-observer.py"
    observer_bytes = observer_path.read_bytes()
    if observer_path != expected_observer or sha(observer_bytes) != args.observer_sha256:
        raise RuntimeError("Gate A observer path or digest mismatch")
    initial_environment = environment_snapshot()
    if initial_environment != expected_initial_environment(runner_root, tests_root):
        raise RuntimeError(f"Gate A initial environment drift: {initial_environment!r}")
    if Path(sys.executable) != runner_root / "venv" / "bin" / "python":
        raise RuntimeError("Gate A observer did not use exact isolated interpreter")
    if any((runner_root / "home").iterdir()):
        raise RuntimeError("Gate A controlled HOME must be empty")

    provisioning_bytes = provisioning_path.read_bytes()
    provisioning = json.loads(provisioning_bytes)
    if provisioning.get("schema") != PROVISION_SCHEMA:
        raise RuntimeError("Gate A provisioning schema mismatch")
    if canonical_json(provisioning) != provisioning_bytes:
        raise RuntimeError("Gate A provisioning record is not canonical JSON")
    source_observer_path = exact_absolute(
        str(runner_root / "materialized" / "reviewtruth-baseline-observer.py"),
        "source observer",
    )
    source_observer_bytes = source_observer_path.read_bytes()
    if sha(source_observer_bytes) != SOURCE_OBSERVER_SHA256:
        raise RuntimeError("source observer bytes differ from exact embedded payload")
    expected_plan_binding = {"path": str(plan), "sha256": sha(plan.read_bytes())}
    expected_roadmap_binding = {"path": str(roadmap), "sha256": sha(roadmap.read_bytes())}
    expected_source_observer_binding = {
        "path": str(source_observer_path),
        "sha256": SOURCE_OBSERVER_SHA256,
    }
    if provisioning.get("observer") != expected_source_observer_binding:
        raise RuntimeError("provisioning record is not bound to exact source observer")
    if provisioning.get("plan") != expected_plan_binding:
        raise RuntimeError("provisioning record is not bound to exact plan")
    if provisioning.get("roadmap") != expected_roadmap_binding:
        raise RuntimeError("provisioning record is not bound to exact roadmap")
    if provisioning.get("plan", {}).get("sha256") != sha(plan.read_bytes()):
        raise RuntimeError("plan changed after provisioning freeze")
    if provisioning.get("roadmap", {}).get("sha256") != sha(roadmap.read_bytes()):
        raise RuntimeError("roadmap changed after provisioning freeze")
    wheel_record = provisioning.get("environment_contract", {}).get("wheel", {})
    if wheel_record.get("path") != str(wheel) or wheel_record.get("sha256") != sha(wheel.read_bytes()):
        raise RuntimeError("Gate A wheel differs from provisioning freeze")

    source_attestation_path = source_observation / "attestation.json"
    source_events_path = source_observation / "plugin-events.json"
    source_attestation_bytes = source_attestation_path.read_bytes()
    source_events_bytes = source_events_path.read_bytes()
    source_attestation = json.loads(source_attestation_bytes)
    source_events = json.loads(source_events_bytes)
    if canonical_json(source_attestation) != source_attestation_bytes:
        raise RuntimeError("source attestation is not canonical JSON")
    if canonical_json(source_events) != source_events_bytes:
        raise RuntimeError("source plugin events are not canonical JSON")
    if source_attestation.get("schema") != SOURCE_SCHEMA or source_events.get("schema") != SOURCE_SCHEMA:
        raise RuntimeError("source observation schema mismatch")
    if source_attestation.get("runner_root") != str(runner_root):
        raise RuntimeError("source observation runner root mismatch")
    if source_attestation.get("observer") != expected_source_observer_binding:
        raise RuntimeError("source observation is not bound to exact source observer")
    if source_attestation.get("plan") != expected_plan_binding:
        raise RuntimeError("source observation is not bound to exact plan")
    if source_attestation.get("roadmap") != expected_roadmap_binding:
        raise RuntimeError("source observation is not bound to exact roadmap")
    if source_attestation.get("provisioning") != {
        "path": str(provisioning_path),
        "sha256": sha(provisioning_bytes),
    }:
        raise RuntimeError("source observation provisioning binding mismatch")
    if source_attestation.get("environment_contract") != provisioning.get("environment_contract"):
        raise RuntimeError("source observation environment contract mismatch")
    if source_attestation.get("git_before") != source_attestation.get("git_after"):
        raise RuntimeError("source observation did not preserve Git state")
    if source_attestation.get("provisioning", {}).get("sha256") != sha(provisioning_bytes):
        raise RuntimeError("source observation is not bound to exact provisioning record")
    source_counts = source_attestation.get("counts")
    expected_source_counts = {
        "full": len(source_events["full_nodeids"]),
        "selected": len(source_events["selected_nodeids"]),
        "marker_deselected": len(source_events["marker_deselected_nodeids"]),
        "legitimate_skips": len(source_events["legitimate_skips"]),
    }
    if source_counts != expected_source_counts:
        raise RuntimeError("source observation counts do not match raw plugin events")
    source_event_files = {
        "full-nodeids.txt": sorted_lf(source_events["full_nodeids"]),
        "selected-nodeids.txt": sorted_lf(source_events["selected_nodeids"]),
        "marker-deselected-nodeids.txt": sorted_lf(source_events["marker_deselected_nodeids"]),
        "legitimate-skips.json": canonical_json(source_events["legitimate_skips"]),
    }
    for name, expected_bytes in source_event_files.items():
        if (source_observation / name).read_bytes() != expected_bytes:
            raise RuntimeError(f"source raw event artifact differs from plugin events: {name}")
    expected_source_set_sha256 = {
        "full_sorted_lf": sha(source_event_files["full-nodeids.txt"]),
        "selected_sorted_lf": sha(source_event_files["selected-nodeids.txt"]),
        "marker_deselected_sorted_lf": sha(source_event_files["marker-deselected-nodeids.txt"]),
    }
    if source_attestation.get("set_sha256") != expected_source_set_sha256:
        raise RuntimeError("source observation set digests differ from raw plugin events")
    source_manifest_before = source_observation_manifest(source_observation, source_attestation)
    source_manifest_bytes = canonical_json(source_manifest_before)
    source_bound_bytes_before = {
        "source_observer": source_observer_bytes,
        "provisioning": provisioning_bytes,
        "plan": plan.read_bytes(),
        "roadmap": roadmap.read_bytes(),
    }

    before = snapshot(repo)
    if not before["clean"] or before != source_attestation.get("git_after"):
        raise RuntimeError("Gate A observation is not paired to the exact clean source HEAD")
    tests_manifest_before = copied_tests_manifest(repo, tests_root)
    omitted_roots = omitted_roots_record(tests_root)
    observation_id = str(uuid.uuid4())
    temporary = final.with_name(final.name + ".tmp-" + observation_id)
    temporary.mkdir(mode=0o700, parents=False, exist_ok=False)
    require_private(temporary, directory=True)
    pytest_argv = [
        str(tests_root),
        "-q",
        "-p",
        "no:cacheprovider",
        "-m",
        "not dotfiles_integration",
        f"--junitxml={temporary / 'broad.xml'}",
    ]
    observer = Observer(repo, runner_root, tests_root, wheel)
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = int(pytest.main(pytest_argv, plugins=[observer]))
    events = observer.payload(pytest_argv, exit_code)
    tests_manifest_after = copied_tests_manifest(repo, tests_root)
    after = snapshot(repo)
    if exit_code != 0:
        raise RuntimeError(f"Gate A preimplementation suite exited {exit_code}")
    if before != after or not after["clean"]:
        raise RuntimeError("Git state changed during Gate A observation")
    source_manifest_after = source_observation_manifest(source_observation, source_attestation)
    if canonical_json(source_manifest_after) != source_manifest_bytes:
        raise RuntimeError("complete source observation changed during Gate A observation")
    source_bound_bytes_after = {
        "source_observer": source_observer_path.read_bytes(),
        "provisioning": provisioning_path.read_bytes(),
        "plan": plan.read_bytes(),
        "roadmap": roadmap.read_bytes(),
    }
    if source_bound_bytes_after != source_bound_bytes_before:
        raise RuntimeError("source observer/plan/roadmap/provisioning binding changed during Gate A")
    if tests_manifest_after != tests_manifest_before:
        raise RuntimeError("copied tests changed during Gate A observation")
    if any((runner_root / "home").iterdir()):
        raise RuntimeError("Gate A controlled HOME changed during observation")

    pair = paired_profile(source_events, events)
    write_new(temporary / "stdout.txt", stdout.getvalue().encode())
    write_new(temporary / "stderr.txt", stderr.getvalue().encode())
    write_new(temporary / "plugin-events.json", canonical_json(events))
    write_new(temporary / "full-nodeids.txt", sorted_lf(events["full_nodeids"]))
    write_new(temporary / "selected-nodeids.txt", sorted_lf(events["selected_nodeids"]))
    write_new(
        temporary / "marker-deselected-nodeids.txt",
        sorted_lf(events["marker_deselected_nodeids"]),
    )
    write_new(temporary / "collection-skips.json", canonical_json(events["collection_skips"]))
    write_new(temporary / "runtime-skips.json", canonical_json(events["runtime_skips"]))
    write_new(temporary / "copied-tests-manifest.json", canonical_json(tests_manifest_before))
    write_new(temporary / "omitted-roots.json", canonical_json(omitted_roots))
    write_new(temporary / "paired-profile.json", canonical_json(pair))
    write_new(temporary / "source-observation-manifest.json", source_manifest_bytes)
    artifacts = {}
    for path in sorted(temporary.iterdir()):
        if path.is_file():
            data = path.read_bytes()
            artifacts[path.name] = {"sha256": sha(data), "bytes": len(data)}
    attestation = {
        "schema": SCHEMA,
        "observation_id": observation_id,
        "runner_root": str(runner_root),
        "tests_root": str(tests_root),
        "observer": {"path": str(observer_path), "sha256": sha(observer_bytes)},
        "provisioning": {"path": str(provisioning_path), "sha256": sha(provisioning_bytes)},
        "source_observation": {
            "path": str(source_observation),
            "attestation_sha256": sha(source_attestation_bytes),
            "plugin_events_sha256": sha(source_events_bytes),
            "manifest_sha256": sha(source_manifest_bytes),
            "manifest_entries": len(source_manifest_before),
            "source_observer_sha256": sha(source_observer_bytes),
            "plan_sha256": sha(source_bound_bytes_before["plan"]),
            "roadmap_sha256": sha(source_bound_bytes_before["roadmap"]),
            "provisioning_sha256": sha(provisioning_bytes),
        },
        "plan": {"path": str(plan), "sha256": sha(plan.read_bytes())},
        "roadmap": {"path": str(roadmap), "sha256": sha(roadmap.read_bytes())},
        "git_before": before,
        "git_after": after,
        "environment": {
            "initial_allowlist": events["environment_before_pytest"],
            "post_pytest": events["environment_after_pytest"],
        },
        "wheel": {"path": str(wheel), "sha256": sha(wheel.read_bytes())},
        "pytest": {
            "version": pytest.__version__,
            "argv": pytest_argv,
            "argv_sha256": events["pytest_argv_sha256"],
            "plugins": events["plugins"],
        },
        "counts": {
            "full": len(events["full_nodeids"]),
            "selected": len(events["selected_nodeids"]),
            "marker_deselected": len(events["marker_deselected_nodeids"]),
            "collection_skips": len(events["collection_skips"]),
            "runtime_skips": len(events["runtime_skips"]),
        },
        "pair_profile": pair,
        "copied_tests_manifest_sha256": sha(canonical_json(tests_manifest_before)),
        "omitted_roots_sha256": sha(canonical_json(omitted_roots)),
        "artifacts": artifacts,
    }
    write_new(temporary / "attestation.json", canonical_json(attestation))
    temporary.rename(final)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```
<!-- REVIEWTRUTH_GATE_A_BASELINE_OBSERVER_END -->

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- target surfaces: `none outside this repo`
- evidence paths: `plans/phase-plan-v10-REVIEWTRUTH.md`, `phase-loop-runtime/uv.lock`, `docs/research/reviewtruth-leg-capability-ratification.md`, `docs/research/reviewtruth-red-baseline.md`, `docs/research/reviewtruth-phase-verification.md`, `docs/research/reviewtruth-real-panel-smoke.md`, `docs/research/reviewtruth-final-evidence-record.md`, `phase-loop-runtime/tests/conftest.py`, `phase-loop-runtime/tests/test_reviewtruth_phase.py`, `phase-loop-runtime/tests/test_phase_worktree_executor.py`, `phase-loop-runtime/tests/test_train_merge.py`, `phase-loop-runtime/tests/test_governed_cross_vendor_floor_358.py`, `phase-loop-runtime/tests/test_advisor_board_golden.py`, `phase-loop-runtime/tests/test_advisor_board_research.py`, `phase-loop-runtime/tests/test_panel_invoker_spawn.py`, `phase-loop-runtime/tests/test_panel_native_fill_183.py`
- redaction posture: `metadata_only`
- downstream handling: `none`; the plan/lock/manifest prerequisite is committed before the lane DAG and closeout may verify but never claim or rewrite the lock, while REVIEWTRUTH closeout follows `REVIEWTRUTH-redacted-transcript-policy` and carries only the exact canonical transcript/smoke path `docs/research/reviewtruth-real-panel-smoke.md` and its single frozen digest, seat metadata, and artifact-specific citations

## Verification

The following `REVIEWTRUTH_SL0_COORDINATOR_PROOF` block is retained only as the predecessor plan's historical two-comment proof template. It is non-authorizing at the current head and must not be run as an SL0 gate: it neither binds ordering addendum comment `5139955591` nor derives the post-CONFORM/post-HARDEN exact base. Stage B must replace the entire block with the strict three-comment proof frozen by PC-REVIEWTRUTH-0, run that replacement from a full clone with authenticated read-only `gh` access, and require zero exit before SL-1. This retained block exists solely to make the superseded assumptions auditable.

```bash
/bin/bash -euo pipefail <<'REVIEWTRUTH_SL0_COORDINATOR_PROOF'
record=docs/research/reviewtruth-leg-capability-ratification.md
repo_expected=Consiliency/agent-harness
git fetch --no-tags --prune origin '+refs/heads/main:refs/remotes/origin/main'
test "$(git rev-parse --is-shallow-repository)" = false
test ! -e "$(git rev-parse --git-path info/grafts)"
test -z "$(git for-each-ref refs/replace --format='%(refname)')"
repo=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
test "$repo" = "$repo_expected"
test "$(gh repo view --json defaultBranchRef --jq .defaultBranchRef.name)" = main
branch_rules=$(gh api -H 'Accept: application/vnd.github+json' "repos/$repo/rules/branches/main")
branch_rules_canonical=$(jq -cS . <<<"$branch_rules")
branch_rules_sha256=$(printf '%s\n' "$branch_rules_canonical" | sha256sum | awk '{print $1}')
jq -e 'type == "array" and any(.[]; .type == "pull_request")' <<<"$branch_rules" >/dev/null
effective_pull_request_rule=true

landings=()
while IFS= read -r commit; do
  if git cat-file -e "$commit:$record" 2>/dev/null && ! git cat-file -e "$commit^1:$record" 2>/dev/null; then
    landings+=("$commit")
  fi
done < <(git rev-list --first-parent --reverse refs/remotes/origin/main)
test "${#landings[@]}" -eq 1
record_commit=${landings[0]}
git merge-base --is-ancestor "$record_commit" refs/remotes/origin/main
git diff --quiet "$record_commit" refs/remotes/origin/main -- "$record"
read -r commit first_parent second_parent extra < <(git rev-list --parents -n 1 "$record_commit")
test "$commit" = "$record_commit"
test -n "$first_parent"
test -n "$second_parent"
test -z "${extra:-}"

mapfile -t landing_paths < <(git diff --name-only "$first_parent" "$record_commit" -- | LC_ALL=C sort -u)
test "${#landing_paths[@]}" -eq 1
test "${landing_paths[0]}" = "$record"

record_text=$(git show "refs/remotes/origin/main:$record")
metadata=$(printf '%s\n' "$record_text" | awk '
  $0 == "<!-- REVIEWTRUTH_CAPABILITY_RATIFICATION_JSON_BEGIN -->" { if (++begins != 1) exit 81; inside=1; next }
  $0 == "<!-- REVIEWTRUTH_CAPABILITY_RATIFICATION_JSON_END -->" { if (!inside || ++ends != 1) exit 82; inside=0; next }
  inside { print }
  END { if (begins != 1 || ends != 1 || inside) exit 83 }
')
jq -e '
  type == "object" and
  (keys | sort) == (["schema", "issue", "disposition_id", "disposition_summary", "option_2_posture", "real_tree_arbitrary_execution", "ratification_comment_id", "ratification_comment_sha256", "ratifier_login", "follow_up_pilot", "prover_directive"] | sort) and
  .schema == "reviewtruth.capability-ratification.v1" and
  .issue == "Consiliency/agent-harness#398" and
  .disposition_id == "option-2-evidence-staging" and
  (.disposition_summary | type == "string" and length > 0) and
  .real_tree_arbitrary_execution == "forbidden" and
  .ratification_comment_id == 5139465317 and
  .ratification_comment_sha256 == "a2dc69639b89743ba351bebf4cd46e81ef8d97901bc5545c00f4777f737238a7" and
  .ratifier_login == "ViperJuice" and
  .option_2_posture == {
    "vendor_review_legs":["codex","gemini","grok"],
    "vendor_review_mode":"read_only_exact_by_reference_bundle",
    "prover_evidence":"redacted_digest_bound",
    "arbitrary_real_tree_execution":"forbidden",
    "shared_database_execution":"forbidden",
    "panel_legs":"unchanged",
    "non_review_goldens":"unchanged"
  } and
  .follow_up_pilot == {
    "issue":"Consiliency/agent-harness#405",
    "authorizing":false,
    "satisfies_ratification":false,
    "option_2_unchanged":true,
    "database_isolation_prerequisite":true,
    "first_eligible_vendor":"codex",
    "gemini_eligibility":"after_demonstrated_value",
    "excluded_vendors":["grok"],
    "panel_legs_widening_authorized":false
  } and
  .prover_directive == {
    "issue":"Consiliency/agent-harness#398",
    "comment_id":5139609713,
    "comment_node_id":"IC_kwDOTFEWvM8AAAABMlg4cQ",
    "comment_url":"https://github.com/Consiliency/agent-harness/issues/398#issuecomment-5139609713",
    "comment_body_bytes":2697,
    "comment_sha256":"284e37117787f653ae91cebc2c04454ddb54ef0cc6434e26dc08b0875cddccfc",
    "ratifier_login":"ViperJuice",
    "author_association":"MEMBER",
    "created_at":"2026-07-31T05:29:20Z",
    "updated_at":"2026-07-31T05:29:20Z",
    "required_prover_all_gates":true,
    "required_vendors_all_gates":3,
    "required_lens_coverage_all_gates":3,
    "plan_design_on_shortfall":"proceed_degraded",
    "merge_release_on_shortfall":"escalate",
    "missing_prover_action":"escalate_nonwaivable",
    "current_prover_seat":{"harness":"claude","model":"claude-fable-5","lens":"correctness"},
    "already_bound_verdicts":"stand",
    "unbound_verdicts":"floor3_plus_usable_fable",
    "runtime_gap_enforcement":"procedural",
    "root_panel_binding":"grok_sol_gemini_fable_usable_agree",
    "direct_claude_p":false,
    "option_2_unchanged":true,
    "follow_up_pilot_authorizing":false
  }
' <<<"$metadata" >/dev/null
disposition_id=$(jq -r .disposition_id <<<"$metadata")
comment_id=$(jq -r .ratification_comment_id <<<"$metadata")
comment_sha=$(jq -r .ratification_comment_sha256 <<<"$metadata")
ratifier=$(jq -r .ratifier_login <<<"$metadata")
option_2_posture_sha256=$(jq -cS .option_2_posture <<<"$metadata" | sha256sum | awk '{print $1}')
follow_up_pilot_sha256=$(jq -cS .follow_up_pilot <<<"$metadata" | sha256sum | awk '{print $1}')
prover_directive_sha256=$(jq -cS .prover_directive <<<"$metadata" | sha256sum | awk '{print $1}')

comment=$(gh api -H 'Accept: application/vnd.github+json' "repos/$repo/issues/comments/$comment_id")
jq -e --arg login "$ratifier" --argjson comment_id "$comment_id" '
  .id == $comment_id and
  .html_url == "https://github.com/Consiliency/agent-harness/issues/398#issuecomment-5139465317" and
  .user.login == $login and
  .issue_url == "https://api.github.com/repos/Consiliency/agent-harness/issues/398" and
  .author_association == "MEMBER" and
  .created_at == "2026-07-31T05:04:41Z" and
  .updated_at == "2026-07-31T05:04:41Z"
' <<<"$comment" >/dev/null
test "$(jq -j .body <<<"$comment" | wc -c)" -eq 2479
test "$(jq -j .body <<<"$comment" | sha256sum | awk '{print $1}')" = "$comment_sha"
jq -e '
  (.body | contains("This comment is the **maintainer decision** requested above")) and
  (.body | contains("distinct from the coordinator")) and
  (.body | contains("I ratify Option 2 (evidence staging, find -> verify) as the durable posture")) and
  (.body | contains("Vendor review legs (codex/gemini/grok) remain **read-only** over the exact by-reference bundle.")) and
  (.body | contains("stages redacted, digest-bound evidence for all four seats to inspect")) and
  (.body | contains("No reviewer receives arbitrary execution")) and
  (.body | contains("shared development database")) and
  (.body | contains("The byte-frozen `PANEL_LEGS` tuple")) and
  (.body | contains("default (non-review) panel goldens **must not shift**")) and
  (.body | contains("A live-probe capability for any vendor leg remains a **separately designed change**"))
' <<<"$comment" >/dev/null
directive=$(gh api -H 'Accept: application/vnd.github+json' "repos/$repo/issues/comments/5139609713")
jq -e '
  .id == 5139609713 and
  .node_id == "IC_kwDOTFEWvM8AAAABMlg4cQ" and
  .html_url == "https://github.com/Consiliency/agent-harness/issues/398#issuecomment-5139609713" and
  .issue_url == "https://api.github.com/repos/Consiliency/agent-harness/issues/398" and
  .user.login == "ViperJuice" and
  .author_association == "MEMBER" and
  .created_at == "2026-07-31T05:29:20Z" and
  .updated_at == "2026-07-31T05:29:20Z"
' <<<"$directive" >/dev/null
test "$(jq -j .body <<<"$directive" | wc -c)" -eq 2697
test "$(jq -j .body <<<"$directive" | sha256sum | awk '{print $1}')" = 284e37117787f653ae91cebc2c04454ddb54ef0cc6434e26dc08b0875cddccfc
jq -e '
  (.body | contains("Preflight must attest capability, not just presence")) and
  (.body | contains("only the claude/Fable seat")) and
  (.body | contains("`required_prover: bool` (default true for all four gates)")) and
  (.body | contains("cannot ratify, full stop")) and
  (.body | contains("NOT waivable by the `on_shortfall` dial")) and
  (.body | contains("`required_vendors = 3`")) and
  (.body | contains("`required_lens_coverage = 3`")) and
  (.body | contains("Keep `on_shortfall` as-is")) and
  (.body | contains("Any panel verdict **not yet bound** must satisfy floor-3 + usable-prover")) and
  (.body | contains("Verdicts **already bound** before this directive stand")) and
  (.body | contains("verify the claude/Fable seat produced a usable review before binding any verdict"))
' <<<"$directive" >/dev/null
permission=$(gh api -H 'Accept: application/vnd.github+json' "repos/$repo/collaborators/$ratifier/permission")
jq -e '.user.login == "ViperJuice" and .permission == "admin" and .role_name == "admin"' <<<"$permission" >/dev/null

associated=$(gh api -H 'Accept: application/vnd.github+json' "repos/$repo/commits/$record_commit/pulls")
matching=$(jq -c --arg commit "$record_commit" '[.[] | select(.state == "closed" and .merged_at != null and .merge_commit_sha == $commit and .base.ref == "main")]' <<<"$associated")
test "$(jq 'length' <<<"$matching")" -eq 1
pr=$(jq -c '.[0]' <<<"$matching")
pr_number=$(jq -r .number <<<"$pr")
test "$(jq -r .head.sha <<<"$pr")" = "$second_parent"
merged_at=$(jq -r .merged_at <<<"$pr")
jq -e --arg merged_at "$merged_at" '
  (.created_at | type == "string") and
  (.updated_at | type == "string") and
  .created_at <= $merged_at and
  .updated_at <= $merged_at
' <<<"$comment" >/dev/null
jq -e --arg merged_at "$merged_at" '
  .created_at <= $merged_at and
  .updated_at <= $merged_at
' <<<"$directive" >/dev/null
comment_created_at=$(jq -r .created_at <<<"$comment")
comment_updated_at=$(jq -r .updated_at <<<"$comment")
directive_created_at=$(jq -r .created_at <<<"$directive")
directive_updated_at=$(jq -r .updated_at <<<"$directive")
mapfile -t pr_paths < <(gh api --paginate -H 'Accept: application/vnd.github+json' "repos/$repo/pulls/$pr_number/files?per_page=100" --jq '.[].filename' | LC_ALL=C sort -u)
test "${#pr_paths[@]}" -eq 1
test "${pr_paths[0]}" = "$record"

jq -cn \
  --arg schema reviewtruth.sl0-coordinator-proof.v1 \
  --arg repo "$repo" \
  --arg canonical_ref refs/remotes/origin/main \
  --arg record_path "$record" \
  --arg record_commit "$record_commit" \
  --arg first_parent "$first_parent" \
  --arg second_parent "$second_parent" \
  --argjson record_pr "$pr_number" \
  --arg record_pr_url "$(jq -r .html_url <<<"$pr")" \
  --arg merged_at "$merged_at" \
  --arg disposition_id "$disposition_id" \
  --arg ratifier_login "$ratifier" \
  --arg ratifier_permission admin \
  --arg ratification_comment_url https://github.com/Consiliency/agent-harness/issues/398#issuecomment-5139465317 \
  --argjson ratification_comment_id "$comment_id" \
  --arg ratification_comment_sha256 "$comment_sha" \
  --argjson ratification_comment_body_bytes 2479 \
  --arg ratification_comment_author_association MEMBER \
  --arg ratification_comment_created_at "$comment_created_at" \
  --arg ratification_comment_updated_at "$comment_updated_at" \
  --arg option_2_posture_sha256 "$option_2_posture_sha256" \
  --arg follow_up_pilot_sha256 "$follow_up_pilot_sha256" \
  --arg prover_directive_sha256 "$prover_directive_sha256" \
  --argjson prover_directive_comment_id 5139609713 \
  --arg prover_directive_comment_node_id IC_kwDOTFEWvM8AAAABMlg4cQ \
  --arg prover_directive_comment_sha256 284e37117787f653ae91cebc2c04454ddb54ef0cc6434e26dc08b0875cddccfc \
  --arg prover_directive_created_at "$directive_created_at" \
  --arg prover_directive_updated_at "$directive_updated_at" \
  --arg follow_up_issue Consiliency/agent-harness#405 \
  --argjson follow_up_authorizing false \
  --arg branch_rules_sha256 "$branch_rules_sha256" \
  --argjson effective_pull_request_rule "$effective_pull_request_rule" \
  '{schema:$schema,repo:$repo,canonical_ref:$canonical_ref,record_path:$record_path,record_commit:$record_commit,first_parent:$first_parent,second_parent:$second_parent,record_pr:$record_pr,record_pr_url:$record_pr_url,merged_at:$merged_at,disposition_id:$disposition_id,ratifier_login:$ratifier_login,ratifier_permission:$ratifier_permission,ratification_comment_url:$ratification_comment_url,ratification_comment_id:$ratification_comment_id,ratification_comment_sha256:$ratification_comment_sha256,ratification_comment_body_bytes:$ratification_comment_body_bytes,ratification_comment_author_association:$ratification_comment_author_association,ratification_comment_created_at:$ratification_comment_created_at,ratification_comment_updated_at:$ratification_comment_updated_at,option_2_posture_sha256:$option_2_posture_sha256,follow_up_pilot_sha256:$follow_up_pilot_sha256,prover_directive_sha256:$prover_directive_sha256,prover_directive_comment_id:$prover_directive_comment_id,prover_directive_comment_node_id:$prover_directive_comment_node_id,prover_directive_comment_sha256:$prover_directive_comment_sha256,prover_directive_created_at:$prover_directive_created_at,prover_directive_updated_at:$prover_directive_updated_at,follow_up_issue:$follow_up_issue,follow_up_authorizing:$follow_up_authorizing,branch_rules_sha256:$branch_rules_sha256,effective_pull_request_rule:$effective_pull_request_rule,record_only_landing:true,two_parent_landing:true,posture_assuming_implementation:false}'
REVIEWTRUTH_SL0_COORDINATOR_PROOF
```

The current executable Stage-A surface is exactly the strict dependency-review-wave preflight, the existing topology/origin exact-base preflight, and the following five `evidence: operational` bootstrap commands, run only after CONFORM and HARDEN land and before SL-0 or any tracked mutation. The coordinator supplies two distinct full immutable `REVIEWTRUTH_CONFORM_COMPLETION_F` and `REVIEWTRUTH_HARDEN_COMPLETION_F` SHAs, explicit canonical immutable evidence roots `REVIEWTRUTH_CONFORM_COMPLETION_EVIDENCE_ROOT` and `REVIEWTRUTH_HARDEN_COMPLETION_EVIDENCE_ROOT`, their distinct independently obtained nonempty expected IDs in `REVIEWTRUTH_CONFORM_COMPLETION_EVIDENCE_ROOT_ID` and `REVIEWTRUTH_HARDEN_COMPLETION_EVIDENCE_ROOT_ID`, an unset canonical absolute `REVIEWTRUTH_RUNNER_ROOT`, and canonical absolute `REVIEWTRUTH_UV`. Before fetching, the topology preflight rejects URL rewriting and authenticates the sole fetch and effective push URL for `origin` against the three explicit canonical GitHub spellings for case-sensitive `Consiliency/agent-harness`. It then fetches exact `origin/main`, proves each supplied SHA is the phase-qualified strict completion-control merge `F` with ordered parents `[M,FH]`, proves `FH` has sole parent `M`, proves both deltas are manifest-only while every other blob is preserved, and verifies the unique completion event from absence at `M` through unchanged presence at `FH`, `F`, and fetched base. The dependency-review-wave preflight independently opens the same events, binds each receipt ID to the independently supplied expected ID, resolves and re-hashes the two evidence roots, rebuilds each canonical bundle, early/seat execution attestation, native result, reducer artifact, receipt, and inner receipt digest, derives every counting/voting/prover fact from the independent producer chain plus exact native text, and validates the complete chronology/common-bundle/effective-policy/restart contract. The private sibling sidecars `$REVIEWTRUTH_RUNNER_ROOT.stage-a-base.json` and `$REVIEWTRUTH_RUNNER_ROOT.stage-a-review-waves.json` bind canonical origin, both `F`/`M`/`FH` triples, both evidence-root identities, and both recomputed receipt/bundle digests; arbitrary ancestors, equal phase landings, the base SHA itself, a SHA-shaped but byte-false value, or any stale/mismatched event, producer record, or artifact fails. Bootstrap commands one through four provision and observe that base. Inside bootstrap command five, the command creates the two exact private immutable external Stage-A snapshots through absent private temporaries and atomic renames, immediately proves each snapshot byte- and SHA-equal to its regular canonical live source, then runs Gate A and validates `paired-profile.json`; requires the exact 9-file source-observation inventory and exact 14-file Gate-A-observation inventory; directly inventories those 23 files, both observers, provisioning, both dependency sidecars, the two snapshots under `repository-stage-a/` identities, every authoritative runtime-tree file, every copied-test file, and the exact-base sidecar; and writes the sorted canonical manifest at `$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-stage-a-candidate-artifacts.json`. Each entry has exactly `path`, four-digit octal `mode`, integer `bytes`, and lowercase `sha256`; identities are relative, nonempty, non-absolute, dot-segment-free, and unique. The command regenerates that manifest from current filesystem bytes and metadata and compares it byte-for-byte immediately before writing and re-verifying `reviewtruth-stage-a-candidate-profile.sha256`, without any current-head constant comparison. Its success authorizes only the Stage-B plan rewrite.

The candidate digest file has exactly one line, `<64 lowercase hex><two spaces>reviewtruth-stage-a-candidate-profile.v1<LF>`. The hex is SHA-256 of the terminal-LF compact sorted-key JSON object with schema `reviewtruth_stage_a_candidate_profile_input.v1` and exactly two path/digest bindings: `exact-base/reviewtruth-stage-a-base.json` to the sibling sidecar, and `evidence/reviewtruth-stage-a-candidate-artifacts.json` to the complete manifest. Manifest identities map unambiguously through the fixed `observations/source/`, `observations/gate-a/`, `materialized/`, `evidence/`, `repository-stage-a/`, `runtime-tree/phase-loop-runtime/`, `copied-tests/phase-loop-runtime/tests/`, and `exact-base/` namespaces used in command five. The manifest excludes its own path, the candidate digest path, and the mutable live Stage-B plan; the digest consumes the manifest but the manifest never consumes the digest.

The displayed SL0 proof above and every command after bootstrap command five are predecessor-shaped Stage-B templates, not executable gates in this Stage-A plan. The fail-closed Codex external-tool preflight is likewise only a Stage-B contract here, never a seventh Stage-A operation. Stage B must replace the SL0 proof with the strict three-comment schema/proof, replace all suite/profile literals with its observed exact-base values, freeze the canonical manifest and candidate digest, independently regenerate and compare the complete manifest in a fresh process by rehashing the immutable external Stage-A snapshots under `repository-stage-a/` identities, and re-compute the digest before SL-0 or SL-1. In a separate check it must hash the revised live Stage-B plan, require exact equality to the reviewed SHA in the REVIEWTRUTH manifest row, early-Codex evidence, bundle, and ordered panel, and never compare that live plan to the Stage-A snapshot. It must also freeze the installed Codex executable/version/help/feature/MCP/plugin inventory and the exact policy/effective-config/preflight/launch-receipt contract, including both temporary-directory exclusions true and contained `TMPDIR`, then pass the ordered early-Codex/critics/Fable exact-digest review. Missing/extra/drifted files, any path/mode/byte-count/SHA/manifest/digest/upstream-binding mismatch, either false/missing exclusion, or any separate Stage-B plan/review mismatch fails before either lane. Only that reviewed revision may label the later commands operational or run the literal RED/then-GREEN sequence. This separation is mandatory: no operator may skip Stage B by running a historical command.

The strict dependency verifier is the following exact `57676`-byte UTF-8/LF Python source at SHA-256 `97a4fd4e8614e0127b8ddf5a57bf9e3db02c3c94b8c364c6b82c054b8b8cbac0`. The second Stage-A command extracts only these marked bytes from this plan into the private external `$REVIEWTRUTH_RUNNER_ROOT.stage-a-review-wave-verifier.py`, verifies both constants before execution, and never imports REVIEWTRUTH production code.

<!-- REVIEWTRUTH_STAGE_A_REVIEW_WAVE_VERIFIER_BEGIN -->
```python
#!/usr/bin/env python3
import datetime as dt
import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path

SHA40 = re.compile(r"[0-9a-f]{40}\Z")
SHA64 = re.compile(r"[0-9a-f]{64}\Z")
STAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z\Z")
VERDICT = re.compile(r"(PARTIALLY\s+AGREE|DISAGREE|AGREE)", re.IGNORECASE)
PROBE_STATUS = re.compile(r"(?:CLEAR|BLOCKED)", re.IGNORECASE)
ELISION_MARKER = re.compile(
    r"(?:\[\s*elided\s*\]|<\s*elided\s*>|\b(?:elided|omitted)\b|(?:^|\s)\.\.\.(?:\s|$))",
    re.IGNORECASE,
)
LEADING_MARKUP = re.compile(r"^(?:[-*>\s`#]+|\d+[.)]\s*)+")
CANONICAL_JSON = "utf8-sorted-keys-compact-lf.v1"
GATES = ("plan-ratify", "design-ratify", "pre-merge-CR", "release-dispatch")
POLICY_KEYS = {"consensus", "on_shortfall", "required_lens_coverage", "required_prover", "required_vendors"}
STATUS_OUTCOME = {
    "OK": "reviewed",
    "UNAVAILABLE": "unavailable",
    "ERROR": "errored",
    "TIMEOUT": "timed_out",
    "REFUSED": "refused",
    "CAPPED": "capped",
    "EMPTY": "empty",
}


def fail(message):
    raise SystemExit(message)


def need(condition, message):
    if not condition:
        fail(message)


def exact_keys(value, keys, label):
    need(type(value) is dict, f"{label}: not object")
    need(set(value) == set(keys), f"{label}: keys")


def text(value, label):
    need(type(value) is str and value != "", f"{label}: text")
    return value


def boolean(value, label):
    need(type(value) is bool, f"{label}: bool")
    return value


def integer(value, label, minimum=0):
    need(type(value) is int and value >= minimum, f"{label}: integer")
    return value


def reject_float(value):
    fail(f"floating JSON number forbidden: {value}")


def reject_constant(value):
    fail(f"non-finite JSON number forbidden: {value}")


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_surrogates(value, label="json"):
    if type(value) is str:
        need(not any(0xD800 <= ord(char) <= 0xDFFF for char in value), f"{label}: surrogate")
    elif type(value) is list:
        for index, item in enumerate(value):
            reject_surrogates(item, f"{label}[{index}]")
    elif type(value) is dict:
        for key, item in value.items():
            reject_surrogates(key, f"{label}.key")
            reject_surrogates(item, f"{label}.{key}")


def canonical_bytes(value):
    reject_surrogates(value)
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def load_json_bytes(data, label, canonical=False):
    try:
        decoded = data.decode("utf-8")
        value = json.loads(
            decoded,
            object_pairs_hook=unique_pairs,
            parse_float=reject_float,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"{label}: invalid JSON: {exc}")
    reject_surrogates(value, label)
    if canonical:
        need(data == canonical_bytes(value), f"{label}: noncanonical bytes")
    return value


def digest(data):
    return hashlib.sha256(data).hexdigest()


def scalars(value):
    if type(value) is dict:
        for key, item in value.items():
            yield key
            yield from scalars(item)
    elif type(value) is list:
        for item in value:
            yield from scalars(item)
    else:
        yield value


def reject_forbidden(value, forbidden, label):
    hits = {item for item in scalars(value) if type(item) is str and item in forbidden}
    need(not hits, f"{label}: forbidden self/control reference")


def timestamp(value, label):
    need(type(value) is str and STAMP.fullmatch(value), f"{label}: timestamp")
    try:
        return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=dt.timezone.utc)
    except ValueError as exc:
        fail(f"{label}: timestamp: {exc}")


def event_timestamp(value, label):
    need(type(value) is str and value.endswith("Z"), f"{label}: timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        fail(f"{label}: timestamp: {exc}")
    need(parsed.tzinfo is not None, f"{label}: timezone")
    return parsed.astimezone(dt.timezone.utc)


def git(repo, *args, allowed=(0,)):
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    need(result.returncode in allowed, f"git {' '.join(args)}: exit {result.returncode}")
    return result.stdout


def git_text(repo, *args, allowed=(0,)):
    return git(repo, *args, allowed=allowed).decode("utf-8").strip()


class EvidenceRoot:
    def __init__(self, supplied, expected_id, label):
        need(type(supplied) is str and supplied.startswith("/"), f"{label}: absolute root")
        need(supplied == os.path.realpath(supplied), f"{label}: canonical root")
        self.expected_id = text(expected_id, f"{label}: expected id")
        cursor = Path("/")
        for part in Path(supplied).parts[1:]:
            cursor /= part
            info = os.lstat(cursor)
            need(not stat.S_ISLNK(info.st_mode), f"{label}: symlink ancestor")
        info = os.stat(supplied, follow_symlinks=False)
        need(stat.S_ISDIR(info.st_mode), f"{label}: not directory")
        need(info.st_uid == os.getuid(), f"{label}: owner")
        need(info.st_mode & 0o022 == 0, f"{label}: writable mode")
        self.path = supplied
        self.label = label
        self.info = info
        self.fd = os.open(supplied, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.cache = {}

    def close(self):
        os.close(self.fd)

    def identity(self):
        return {
            "canonical_path": self.path,
            "device": self.info.st_dev,
            "evidence_root_id": self.expected_id,
            "inode": self.info.st_ino,
            "mode": f"0{stat.S_IMODE(self.info.st_mode):03o}",
            "owner_uid": self.info.st_uid,
        }

    def read_ref(self, reference, label):
        exact_keys(reference, {"path", "bytes", "sha256"}, f"{label}.ref")
        relative = text(reference["path"], f"{label}.path")
        need("\\" not in relative and not relative.startswith("/"), f"{label}: path form")
        parts = relative.split("/")
        need(all(part not in ("", ".", "..") for part in parts), f"{label}: path segment")
        integer(reference["bytes"], f"{label}.bytes")
        need(type(reference["sha256"]) is str and SHA64.fullmatch(reference["sha256"]), f"{label}: sha256")
        cached = self.cache.get(relative)
        if cached is None:
            directory = os.dup(self.fd)
            try:
                for part in parts[:-1]:
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                    child_info = os.fstat(child)
                    need(stat.S_ISDIR(child_info.st_mode), f"{label}: ancestor type")
                    need(child_info.st_uid == os.getuid(), f"{label}: ancestor owner")
                    need(child_info.st_mode & 0o022 == 0, f"{label}: ancestor mode")
                    os.close(directory)
                    directory = child
                handle = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
                try:
                    before = os.fstat(handle)
                    need(stat.S_ISREG(before.st_mode), f"{label}: not regular")
                    need(before.st_uid == os.getuid(), f"{label}: owner")
                    need(before.st_mode & 0o022 == 0, f"{label}: writable mode")
                    chunks = []
                    while True:
                        chunk = os.read(handle, 1024 * 1024)
                        if not chunk:
                            break
                        chunks.append(chunk)
                    after = os.fstat(handle)
                    stable = (before.st_dev, before.st_ino, before.st_mode, before.st_size, before.st_mtime_ns)
                    need(stable == (after.st_dev, after.st_ino, after.st_mode, after.st_size, after.st_mtime_ns), f"{label}: changed while read")
                    data = b"".join(chunks)
                finally:
                    os.close(handle)
            finally:
                os.close(directory)
            cached = (data, digest(data))
            self.cache[relative] = cached
        data, actual_digest = cached
        need(len(data) == reference["bytes"], f"{label}: byte drift")
        need(actual_digest == reference["sha256"], f"{label}: hash drift")
        if relative.endswith(".json"):
            load_json_bytes(data, label, canonical=True)
        return data, actual_digest

    def json_ref(self, reference, label):
        data, actual_digest = self.read_ref(reference, label)
        return load_json_bytes(data, label, canonical=True), actual_digest


def file_ref(value, label):
    exact_keys(value, {"path", "bytes", "sha256"}, label)
    text(value["path"], f"{label}.path")
    integer(value["bytes"], f"{label}.bytes")
    need(type(value["sha256"]) is str and SHA64.fullmatch(value["sha256"]), f"{label}.sha256")
    return value


def validate_rendered_prompt(reference, root, *, lens, seat_instance_id, bundle_digest, required_evidence, label):
    prompt_ref = file_ref(reference, label)
    prompt_bytes, prompt_digest = root.read_ref(prompt_ref, label)
    try:
        prompt = prompt_bytes.decode("utf-8")
    except UnicodeDecodeError:
        fail(f"{label}: utf8")
    need(prompt.endswith("\n") and "\x00" not in prompt, f"{label}: text framing")
    lines = prompt.splitlines()
    marker_groups = {
        "REVIEW_LENS:": [f"REVIEW_LENS: {lens}"],
        "SEAT_INSTANCE_ID:": [f"SEAT_INSTANCE_ID: {seat_instance_id}"],
        "OUTPUT_EVIDENCE_PREFIX:": ["OUTPUT_EVIDENCE_PREFIX: EVIDENCE_REF:"],
    }
    if bundle_digest is not None:
        marker_groups["EVIDENCE_BUNDLE_SHA256:"] = [f"EVIDENCE_BUNDLE_SHA256: {bundle_digest}"]
    marker_groups["REQUIRED_EVIDENCE_REF:"] = [
        f"REQUIRED_EVIDENCE_REF: {canonical_bytes(evidence_ref).decode('utf-8').removesuffix(chr(10))}"
        for evidence_ref in required_evidence
    ]
    for prefix, expected in marker_groups.items():
        actual = [line for line in lines if line.startswith(prefix)]
        need(actual == expected, f"{label}: missing, duplicate, unexpected, or reordered {prefix} marker")
    return prompt_ref, prompt_digest


def validate_base(base, expected, root, label):
    exact_keys(base, {"commit", "tree", "plan_sha256", "roadmap_sha256", "final_audit", "final_evidence"}, label)
    need(base == expected, f"{label}: binding")
    need(SHA40.fullmatch(base["commit"]) and SHA40.fullmatch(base["tree"]), f"{label}: git ids")
    need(SHA64.fullmatch(base["plan_sha256"]) and SHA64.fullmatch(base["roadmap_sha256"]), f"{label}: source hashes")
    root.read_ref(file_ref(base["final_audit"], f"{label}.final_audit"), f"{label}.final_audit")
    root.read_ref(file_ref(base["final_evidence"], f"{label}.final_evidence"), f"{label}.final_evidence")


def validate_finding(reference, root, forbidden, label):
    finding, finding_digest = root.json_ref(file_ref(reference, label), label)
    exact_keys(finding, {"schema", "contradiction", "material", "reported_at"}, label)
    need(finding["schema"] == "v10.review-wave-finding.v1", f"{label}: schema")
    contradiction = boolean(finding["contradiction"], f"{label}.contradiction")
    material = boolean(finding["material"], f"{label}.material")
    need(contradiction or material, f"{label}: immaterial")
    reported_at = timestamp(finding["reported_at"], f"{label}.reported_at")
    reject_forbidden(finding, forbidden | {finding_digest}, label)
    return reported_at


def evidence_refs_from_text(value, label):
    references = []
    for index, line in enumerate(value.splitlines()):
        normalized = LEADING_MARKUP.sub("", line.strip()).strip()
        if not normalized.startswith("EVIDENCE_REF:"):
            continue
        encoded = normalized[len("EVIDENCE_REF:"):].strip()
        need(encoded != "", f"{label}: empty evidence ref")
        reference = load_json_bytes((encoded + "\n").encode("utf-8"), f"{label}.evidence_ref[{index}]", canonical=True)
        references.append(file_ref(reference, f"{label}.evidence_ref[{index}]"))
    paths = [reference["path"] for reference in references]
    need(len(paths) == len(set(paths)), f"{label}: duplicate evidence ref")
    return sorted(references, key=lambda reference: reference["path"])


def review_text_facts(value, label):
    need(type(value) is str and "\x00" not in value, f"{label}: review text")
    lines = [line for line in value.splitlines() if line.strip()]
    if not lines:
        return None, False, []
    terminal = LEADING_MARKUP.sub("", lines[-1].strip()).strip().strip("*`").strip()
    if terminal.upper().startswith("VERDICT:"):
        terminal = terminal[len("VERDICT:"):].strip().strip("*`").strip()
    terminal = LEADING_MARKUP.sub("", terminal).strip()
    match = VERDICT.fullmatch(terminal)
    verdict = re.sub(r"\s+", " ", match.group(1).upper()) if match else None
    evidence_refs = evidence_refs_from_text(value, label)
    analytical_lines = [
        line for line in lines[:-1]
        if not LEADING_MARKUP.sub("", line.strip()).strip().startswith("EVIDENCE_REF:")
    ]
    body = "\n".join(analytical_lines).strip()
    sentinels = {"...", "[elided]", "<elided>", "elided", "omitted", "n/a", "no review"}
    substantive = (
        verdict is not None
        and len(body.encode("utf-8")) >= 40
        and body.casefold() not in sentinels
        and ELISION_MARKER.search(body) is None
    )
    return verdict, substantive, evidence_refs


def probe_text_facts(value, label):
    need(type(value) is str and "\x00" not in value, f"{label}: probe text")
    lines = [line for line in value.splitlines() if line.strip()]
    if not lines:
        return None, False, []
    terminal = LEADING_MARKUP.sub("", lines[-1].strip()).strip().strip("*`").strip()
    if terminal.upper().startswith("PROBE_STATUS:"):
        terminal = terminal[len("PROBE_STATUS:"):].strip().strip("*`").strip()
    terminal = LEADING_MARKUP.sub("", terminal).strip()
    match = PROBE_STATUS.fullmatch(terminal)
    status = match.group(0).upper() if match else None
    evidence_refs = evidence_refs_from_text(value, label)
    analytical_lines = [
        line for line in lines[:-1]
        if not LEADING_MARKUP.sub("", line.strip()).strip().startswith("EVIDENCE_REF:")
    ]
    body = "\n".join(analytical_lines).strip()
    sentinels = {"...", "[elided]", "<elided>", "elided", "omitted", "n/a", "no probe"}
    substantive = (
        status is not None
        and len(body.encode("utf-8")) >= 40
        and body.casefold() not in sentinels
        and ELISION_MARKER.search(body) is None
    )
    return status, substantive, evidence_refs


def validate_policy(policy, seats, root, forbidden, final, label):
    exact_keys(policy, {"consensus", "gate", "on_shortfall", "required_lens_coverage", "required_prover", "required_vendors", "resolver_input", "resolver_output"}, label)
    input_ref = file_ref(policy["resolver_input"], f"{label}.resolver_input")
    output_ref = file_ref(policy["resolver_output"], f"{label}.resolver_output")
    need(input_ref != output_ref, f"{label}: resolver alias")
    resolver_input, input_digest = root.json_ref(input_ref, f"{label}.resolver_input")
    resolver_output, output_digest = root.json_ref(output_ref, f"{label}.resolver_output")
    exact_keys(resolver_input, {"schema", "defaults", "gate", "repository_override", "required_prover_false_probe"}, f"{label}.resolver_input")
    need(resolver_input["schema"] == "v10.review-policy-resolver-input.v1", f"{label}: input schema")
    need(resolver_input["gate"] == "pre-merge-CR", f"{label}: input gate")
    defaults = resolver_input["defaults"]
    exact_keys(defaults, set(GATES), f"{label}.defaults")
    expected_modes = {
        "plan-ratify": ("majority", "proceed_degraded"),
        "design-ratify": ("majority", "proceed_degraded"),
        "pre-merge-CR": ("majority", "escalate"),
        "release-dispatch": ("unanimous", "escalate"),
    }
    for gate in GATES:
        current = defaults[gate]
        exact_keys(current, POLICY_KEYS, f"{label}.defaults.{gate}")
        integer(current["required_vendors"], f"{label}.{gate}.vendors", 1)
        integer(current["required_lens_coverage"], f"{label}.{gate}.lenses", 1)
        boolean(current["required_prover"], f"{label}.{gate}.prover")
        need((current["required_vendors"], current["required_lens_coverage"], current["required_prover"]) == (3, 3, True), f"{label}.{gate}: shipped floor")
        need((current["consensus"], current["on_shortfall"]) == expected_modes[gate], f"{label}.{gate}: retained policy")
    override = resolver_input["repository_override"]
    need(type(override) is dict and set(override) <= POLICY_KEYS, f"{label}: override keys")
    for key, value in override.items():
        if key in {"required_vendors", "required_lens_coverage"}:
            integer(value, f"{label}.override.{key}", 1)
        elif key == "required_prover":
            boolean(value, f"{label}.override.{key}")
        elif key == "consensus":
            need(value in {"majority", "unanimous"}, f"{label}.override.consensus")
        else:
            need(value in {"escalate", "proceed_degraded"}, f"{label}.override.on_shortfall")
    probe = resolver_input["required_prover_false_probe"]
    need(probe == {"required_prover": False}, f"{label}: false override probe")
    effective = dict(defaults["pre-merge-CR"])
    effective.update(override)
    false_effective = dict(effective)
    false_effective.update(probe)
    expected_output = {
        "effective": effective,
        "required_prover_false_probe": false_effective,
        "schema": "v10.review-policy-resolver-output.v1",
    }
    need(resolver_output == expected_output, f"{label}: resolver output")
    reject_forbidden(resolver_input, forbidden | {input_digest}, f"{label}.resolver_input")
    reject_forbidden(resolver_output, forbidden | {output_digest}, f"{label}.resolver_output")
    need(policy["gate"] == "pre-merge-CR", f"{label}: gate")
    for key in ("consensus", "on_shortfall", "required_lens_coverage", "required_prover", "required_vendors"):
        need(policy[key] == effective[key], f"{label}: effective {key}")
    need((effective["required_vendors"], effective["required_lens_coverage"], effective["required_prover"]) == (3, 3, True), f"{label}: effective floor")
    need(false_effective["required_prover"] is False and all(false_effective[key] == effective[key] for key in POLICY_KEYS - {"required_prover"}), f"{label}: false override isolation")
    counted = [seat for seat in seats if seat["counts_toward_floor"]]
    vendors = {seat["vendor"] for seat in counted}
    lenses = {seat["lens"] for seat in counted}
    agreeing = sum(seat["verdict"] == "AGREE" for seat in counted)
    reviewing = len(counted)
    consensus = agreeing == reviewing and reviewing > 0 if effective["consensus"] == "unanimous" else agreeing * 2 > reviewing
    fable = seats[3]
    prover = fable["binding_prover"] and fable["usable"] and fable["outcome"] == "reviewed" and fable["verdict"] == "AGREE"
    if final:
        need(len(vendors) >= effective["required_vendors"], f"{label}: vendor shortfall")
        need(len(lenses) >= effective["required_lens_coverage"], f"{label}: lens shortfall")
        need(consensus, f"{label}: consensus shortfall")
        need(prover, f"{label}: prover shortfall")
        need(seats[1]["usable"] and seats[1]["outcome"] == "reviewed" and seats[1]["verdict"] == "AGREE", f"{label}: Sol AGREE")


def validate_receipt(receipt, expected_base, root, forbidden, receipt_digest, final, label):
    exact_keys(receipt, {"attempt", "base", "bundle_staging", "completed_at", "early_prover", "effective_policy", "evidence_root_id", "gate", "phase_alias", "restart_chain", "seats", "wave_id"}, label)
    attempt = integer(receipt["attempt"], f"{label}.attempt", 1)
    need(receipt["phase_alias"] in {"CONFORM", "HARDEN"}, f"{label}: phase")
    need(receipt["gate"] == "pre-merge-CR", f"{label}: gate")
    text(receipt["wave_id"], f"{label}.wave_id")
    text(receipt["evidence_root_id"], f"{label}.evidence_root_id")
    need(receipt["evidence_root_id"] == root.expected_id, f"{label}: evidence root id")
    validate_base(receipt["base"], expected_base, root, f"{label}.base")
    completed_at = timestamp(receipt["completed_at"], f"{label}.completed_at")

    early = receipt["early_prover"]
    exact_keys(early, {"artifact", "binding_prover", "capability", "completed_at", "outcome", "receipt", "role", "seat", "started_at", "usable", "vendor"}, f"{label}.early")
    early_artifact_ref = file_ref(early["artifact"], f"{label}.early.artifact")
    early_artifact, early_artifact_digest = root.json_ref(early_artifact_ref, f"{label}.early.artifact")
    early_artifact_keys = {"attempt", "base", "binding_prover", "capability", "completed_at", "effort", "execution_attestation", "grounding", "harness", "lens", "model", "native_result", "outcome", "phase_alias", "position", "probe_report", "rendered_prompt", "role", "schema", "seat", "seat_instance_id", "started_at", "status", "vendor", "wave_id"}
    exact_keys(early_artifact, early_artifact_keys, f"{label}.early.artifact")
    need(early_artifact["schema"] == "v10.review-early-prover-artifact.v1", f"{label}: early artifact schema")
    need((early_artifact["attempt"], early_artifact["base"], early_artifact["phase_alias"], early_artifact["wave_id"]) == (attempt, receipt["base"], receipt["phase_alias"], receipt["wave_id"]), f"{label}: early artifact wave binding")
    early_identity = (0, "codex", "codex", "openai", "gpt-5.6-terra", "xhigh", "live-probe", "early_prover", "can_probe", False)
    actual_early_identity = (early_artifact["position"], early_artifact["seat"], early_artifact["harness"], early_artifact["vendor"], early_artifact["model"], early_artifact["effort"], early_artifact["lens"], early_artifact["role"], early_artifact["capability"], early_artifact["binding_prover"])
    need(actual_early_identity == early_identity, f"{label}: early artifact identity")
    integer(early_artifact["position"], f"{label}.early.artifact.position", 0)
    boolean(early_artifact["binding_prover"], f"{label}.early.artifact.binding")
    early_instance_id = text(early_artifact["seat_instance_id"], f"{label}.early.artifact.seat_instance_id")

    early_execution_ref = file_ref(early_artifact["execution_attestation"], f"{label}.early.execution_attestation")
    early_execution, early_execution_digest = root.json_ref(early_execution_ref, f"{label}.early.execution_attestation")
    early_execution_keys = {"attempt", "attested_at", "base", "binding_prover", "capability", "effort", "harness", "lens", "model", "phase_alias", "position", "producer", "rendered_prompt", "role", "schema", "seat", "seat_instance_id", "vendor", "wave_id"}
    exact_keys(early_execution, early_execution_keys, f"{label}.early.execution_attestation")
    need(early_execution["schema"] == "v10.review-early-prover-execution-attestation.v1", f"{label}: early execution schema")
    need(early_execution["producer"] == "phase_loop_runtime.composition.run_auth_preflight", f"{label}: early execution producer")
    need((early_execution["attempt"], early_execution["base"], early_execution["phase_alias"], early_execution["wave_id"]) == (attempt, receipt["base"], receipt["phase_alias"], receipt["wave_id"]), f"{label}: early execution wave binding")
    execution_identity = (early_execution["position"], early_execution["seat"], early_execution["harness"], early_execution["vendor"], early_execution["model"], early_execution["effort"], early_execution["lens"], early_execution["role"], early_execution["capability"], early_execution["binding_prover"])
    need(execution_identity == early_identity and early_execution["seat_instance_id"] == early_instance_id, f"{label}: early execution identity")
    early_attested = timestamp(early_execution["attested_at"], f"{label}.early.execution_attested_at")
    required_early_evidence = sorted([receipt["base"]["final_audit"], receipt["base"]["final_evidence"]], key=lambda reference: reference["path"])
    early_prompt_ref, early_prompt_digest = validate_rendered_prompt(
        early_execution["rendered_prompt"],
        root,
        lens="live-probe",
        seat_instance_id=early_instance_id,
        bundle_digest=None,
        required_evidence=required_early_evidence,
        label=f"{label}.early.rendered_prompt",
    )
    need(early_artifact["rendered_prompt"] == early_prompt_ref, f"{label}: early artifact prompt")

    early_native_ref = file_ref(early_artifact["native_result"], f"{label}.early.native_result")
    early_native, early_native_digest = root.json_ref(early_native_ref, f"{label}.early.native_result")
    early_native_keys = {"attempt", "base", "completed_at", "execution_attestation", "native_result_id", "phase_alias", "probe_report", "producer", "rendered_prompt", "schema", "seat_instance_id", "started_at", "status", "wave_id"}
    exact_keys(early_native, early_native_keys, f"{label}.early.native_result")
    need(early_native["schema"] == "v10.review-early-prover-native-result.v1", f"{label}: early native schema")
    need(early_native["producer"] == "phase_loop_runtime.phase_worktree_executor", f"{label}: early native producer")
    text(early_native["native_result_id"], f"{label}.early.native_result_id")
    need((early_native["attempt"], early_native["base"], early_native["phase_alias"], early_native["wave_id"]) == (attempt, receipt["base"], receipt["phase_alias"], receipt["wave_id"]), f"{label}: early native wave binding")
    need(early_native["execution_attestation"] == early_execution_ref and early_native["seat_instance_id"] == early_instance_id, f"{label}: early native execution binding")
    need(early_native["rendered_prompt"] == early_prompt_ref, f"{label}: early native prompt")
    need(len({early_artifact_ref["path"], early_execution_ref["path"], early_native_ref["path"], early_prompt_ref["path"]}) == 4, f"{label}: early producer artifact alias")
    need(len({early_artifact_digest, early_execution_digest, early_native_digest, early_prompt_digest}) == 4, f"{label}: early producer digest alias")
    early_started = timestamp(early_native["started_at"], f"{label}.early.native.started_at")
    early_completed = timestamp(early_native["completed_at"], f"{label}.early.native.completed_at")
    need(early_attested < early_started < early_completed, f"{label}: early producer chronology")
    need(early_native["status"] in STATUS_OUTCOME, f"{label}: early native status")
    probe_status, probe_substantive, native_early_grounding = probe_text_facts(early_native["probe_report"], f"{label}.early.native.probe_report")
    need(native_early_grounding == required_early_evidence, f"{label}: early native grounding")
    need(early_artifact["grounding"] == native_early_grounding, f"{label}: early artifact grounding")
    for grounding_ref in native_early_grounding:
        root.read_ref(grounding_ref, f"{label}.early.grounding")
    early_usable = early_native["status"] == "OK" and probe_status is not None and probe_substantive and native_early_grounding == required_early_evidence
    derived_early_outcome = probe_status if early_usable else "BLOCKED"
    need(early_artifact["started_at"] == early_native["started_at"] and early_artifact["completed_at"] == early_native["completed_at"], f"{label}: early artifact native chronology")
    need(early_artifact["status"] == early_native["status"] and early_artifact["probe_report"] == early_native["probe_report"], f"{label}: early artifact native result")
    need(early_artifact["outcome"] == derived_early_outcome, f"{label}: early artifact derived outcome")
    derived_early = {
        "artifact": early_artifact_ref,
        "binding_prover": False,
        "capability": "can_probe",
        "completed_at": early_native["completed_at"],
        "outcome": derived_early_outcome,
        "role": "early_prover",
        "seat": "codex",
        "started_at": early_native["started_at"],
        "usable": early_usable,
        "vendor": "openai",
    }
    need({key: value for key, value in early.items() if key != "receipt"} == derived_early, f"{label}: early artifact-derived wrapper")
    need(early_usable and derived_early_outcome == "CLEAR", f"{label}: early CLEAR")
    early_receipt, early_digest = root.json_ref(file_ref(early["receipt"], f"{label}.early.receipt"), f"{label}.early.receipt")
    expected_early = dict(derived_early)
    expected_early.update({"attempt": attempt, "base": receipt["base"], "phase_alias": receipt["phase_alias"], "wave_id": receipt["wave_id"]})
    need(early_receipt == expected_early, f"{label}: early receipt binding")
    reject_forbidden(early_execution, forbidden | {early_execution_digest}, f"{label}.early.execution_attestation")
    reject_forbidden(early_native, forbidden | {early_native_digest}, f"{label}.early.native_result")
    reject_forbidden(early_artifact, forbidden | {early_artifact_digest}, f"{label}.early.artifact")
    reject_forbidden(early_receipt, forbidden | {early_digest}, f"{label}.early.receipt")

    staging = receipt["bundle_staging"]
    exact_keys(staging, {"bundle", "early_artifact", "early_receipt", "staged_at"}, f"{label}.staging")
    need(staging["early_artifact"] == early["artifact"] and staging["early_receipt"] == early["receipt"], f"{label}: staged early refs")
    staged_at = timestamp(staging["staged_at"], f"{label}.staged_at")
    need(early_completed < staged_at, f"{label}: early-before-staging")
    bundle_ref = file_ref(staging["bundle"], f"{label}.bundle")
    bundle, bundle_digest = root.json_ref(bundle_ref, f"{label}.bundle")
    exact_keys(bundle, {"schema", "base", "entries"}, f"{label}.bundle")
    need(bundle["schema"] == "v10.review-evidence-bundle.v1" and bundle["base"] == receipt["base"], f"{label}: bundle binding")
    need(type(bundle["entries"]) is list, f"{label}: bundle entries")
    entries = [file_ref(entry, f"{label}.bundle.entry") for entry in bundle["entries"]]
    paths = [entry["path"] for entry in entries]
    need(paths == sorted(paths) and len(paths) == len(set(paths)), f"{label}: bundle ordering")
    for index, entry in enumerate(entries):
        root.read_ref(entry, f"{label}.bundle.entry[{index}]")
    for required in (receipt["base"]["final_audit"], receipt["base"]["final_evidence"], early["receipt"], early["artifact"], early_execution_ref, early_native_ref, early_prompt_ref):
        need(required in entries, f"{label}: bundle required entry")
    reject_forbidden(bundle, forbidden | {bundle_digest, receipt_digest}, f"{label}.bundle")

    seats = receipt["seats"]
    need(type(seats) is list and len(seats) == 4, f"{label}: seats")
    roster = (
        (1, "grok", "grok", "xai", "grok-4.5", "max", "adversarial", "critic", "read_only", False),
        (2, "gpt-5.6-sol", "codex", "openai", "gpt-5.6-sol", "max", "red-team", "critic", "read_only", False),
        (3, "gemini", "gemini", "google", "gemini-3.6-flash", "high", "alternative-approach", "critic", "read_only", False),
        (4, "fable", "claude", "anthropic", "claude-fable-5", "max", "correctness", "binding_prover", "binding_prover", True),
    )
    seat_completed = []
    seat_instance_ids = []
    native_result_ids = []
    validated_seats = []
    agree_artifacts = []
    finding_refs = []
    artifact_keys = {"attempt", "base", "binding_prover", "capability", "completed_at", "consumed_bundle", "effort", "execution_attestation", "grounding", "harness", "lens", "material_findings", "model", "native_result", "outcome", "phase_alias", "position", "rendered_prompt", "review_text", "role", "schema", "seat", "seat_instance_id", "started_at", "status", "vendor", "wave_id"}
    for index, (seat, expected) in enumerate(zip(seats, roster)):
        seat_label = f"{label}.seat[{index}]"
        exact_keys(seat, {"artifact", "binding_prover", "capability", "completed_at", "consumed_bundle", "counts_toward_floor", "lens", "material_findings", "outcome", "position", "receipt", "role", "seat", "started_at", "usable", "vendor", "verdict"}, seat_label)
        artifact_ref = file_ref(seat["artifact"], f"{seat_label}.artifact")
        artifact, artifact_digest = root.json_ref(artifact_ref, f"{seat_label}.artifact")
        exact_keys(artifact, artifact_keys, f"{seat_label}.artifact")
        need(artifact["schema"] == "v10.review-seat-artifact.v1", f"{seat_label}: artifact schema")
        need((artifact["attempt"], artifact["base"], artifact["phase_alias"], artifact["wave_id"]) == (attempt, receipt["base"], receipt["phase_alias"], receipt["wave_id"]), f"{seat_label}: artifact wave binding")
        position, seat_name, harness, vendor, model, effort, lens, role, capability, binding = expected
        identity = (artifact["position"], artifact["seat"], artifact["harness"], artifact["vendor"], artifact["model"], artifact["effort"], artifact["lens"], artifact["role"], artifact["capability"], artifact["binding_prover"])
        need(identity == expected, f"{seat_label}: artifact identity")
        integer(artifact["position"], f"{seat_label}.artifact.position", 1)
        boolean(artifact["binding_prover"], f"{seat_label}.artifact.binding")
        seat_instance_id = text(artifact["seat_instance_id"], f"{seat_label}.artifact.seat_instance_id")
        seat_instance_ids.append(seat_instance_id)

        execution_ref = file_ref(artifact["execution_attestation"], f"{seat_label}.execution_attestation")
        execution, execution_digest = root.json_ref(execution_ref, f"{seat_label}.execution_attestation")
        execution_keys = {"attempt", "attested_at", "base", "binding_prover", "capability", "consumed_bundle", "effort", "harness", "lens", "model", "phase_alias", "position", "producer", "rendered_prompt", "role", "schema", "seat", "seat_instance_id", "vendor", "wave_id"}
        exact_keys(execution, execution_keys, f"{seat_label}.execution_attestation")
        need(execution["schema"] == "v10.review-seat-execution-attestation.v1", f"{seat_label}: execution schema")
        need(execution["producer"] == "phase_loop_runtime.composition.run_auth_preflight", f"{seat_label}: execution producer")
        need((execution["attempt"], execution["base"], execution["phase_alias"], execution["wave_id"]) == (attempt, receipt["base"], receipt["phase_alias"], receipt["wave_id"]), f"{seat_label}: execution wave binding")
        execution_identity = (execution["position"], execution["seat"], execution["harness"], execution["vendor"], execution["model"], execution["effort"], execution["lens"], execution["role"], execution["capability"], execution["binding_prover"])
        need(execution_identity == expected and execution["seat_instance_id"] == seat_instance_id, f"{seat_label}: execution identity")
        attested_at = timestamp(execution["attested_at"], f"{seat_label}.execution_attested_at")
        execution_bundle = file_ref(execution["consumed_bundle"], f"{seat_label}.execution_bundle")
        need(execution_bundle == bundle_ref, f"{seat_label}: execution bundle")
        required_seat_evidence = sorted(
            [receipt["base"]["final_audit"], receipt["base"]["final_evidence"]],
            key=lambda reference: reference["path"],
        )
        prompt_ref, prompt_digest = validate_rendered_prompt(
            execution["rendered_prompt"],
            root,
            lens=lens,
            seat_instance_id=seat_instance_id,
            bundle_digest=bundle_digest,
            required_evidence=required_seat_evidence,
            label=f"{seat_label}.rendered_prompt",
        )
        need(artifact["rendered_prompt"] == prompt_ref, f"{seat_label}: artifact prompt")

        native_ref = file_ref(artifact["native_result"], f"{seat_label}.native_result")
        native, native_digest = root.json_ref(native_ref, f"{seat_label}.native_result")
        native_keys = {"attempt", "base", "completed_at", "consumed_bundle", "execution_attestation", "native_result_id", "phase_alias", "producer", "rendered_prompt", "review_text", "schema", "seat_instance_id", "started_at", "status", "wave_id"}
        exact_keys(native, native_keys, f"{seat_label}.native_result")
        need(native["schema"] == "v10.review-seat-native-result.v1", f"{seat_label}: native schema")
        expected_producer = "phase_loop_runtime.panel_invoker.bind_native_agent_leg_result" if position == 4 else "phase_loop_runtime.panel_invoker.invoke_board"
        need(native["producer"] == expected_producer, f"{seat_label}: native producer")
        native_result_ids.append(text(native["native_result_id"], f"{seat_label}.native_result_id"))
        need((native["attempt"], native["base"], native["phase_alias"], native["wave_id"]) == (attempt, receipt["base"], receipt["phase_alias"], receipt["wave_id"]), f"{seat_label}: native wave binding")
        need(native["execution_attestation"] == execution_ref and native["seat_instance_id"] == seat_instance_id, f"{seat_label}: native execution binding")
        native_bundle = file_ref(native["consumed_bundle"], f"{seat_label}.native_bundle")
        need(native_bundle == bundle_ref, f"{seat_label}: native bundle")
        need(native["rendered_prompt"] == prompt_ref, f"{seat_label}: native prompt")
        need(len({artifact_ref["path"], execution_ref["path"], native_ref["path"], prompt_ref["path"]}) == 4, f"{seat_label}: producer artifact alias")
        need(len({artifact_digest, execution_digest, native_digest, prompt_digest}) == 4, f"{seat_label}: producer digest alias")
        started = timestamp(native["started_at"], f"{seat_label}.native.started_at")
        finished = timestamp(native["completed_at"], f"{seat_label}.native.completed_at")
        need(staged_at < attested_at < started < finished, f"{seat_label}: producer chronology")
        need(native["status"] in STATUS_OUTCOME, f"{seat_label}: native status")
        need(artifact["started_at"] == native["started_at"] and artifact["completed_at"] == native["completed_at"], f"{seat_label}: artifact native chronology")
        need(artifact["status"] == native["status"] and artifact["review_text"] == native["review_text"], f"{seat_label}: artifact native result")
        need(artifact["consumed_bundle"] == native_bundle, f"{seat_label}: artifact native bundle")
        seat_completed.append(finished)
        consumed_bundle = file_ref(artifact["consumed_bundle"], f"{seat_label}.artifact.consumed_bundle")
        need(consumed_bundle == bundle_ref, f"{seat_label}: artifact bundle")
        root.read_ref(consumed_bundle, f"{seat_label}.artifact.consumed_bundle")
        grounding = artifact["grounding"]
        need(type(grounding) is list, f"{seat_label}: grounding")
        grounding_refs = [file_ref(item, f"{seat_label}.grounding[{grounding_index}]") for grounding_index, item in enumerate(grounding)]
        need(grounding_refs == sorted(grounding_refs, key=lambda ref: ref["path"]) and len({item["path"] for item in grounding_refs}) == len(grounding_refs), f"{seat_label}: grounding order")
        need(type(artifact["material_findings"]) is list, f"{seat_label}: findings")
        seat_findings = []
        for finding_index, finding in enumerate(artifact["material_findings"]):
            ref = file_ref(finding, f"{seat_label}.finding[{finding_index}]")
            validate_finding(ref, root, forbidden, f"{seat_label}.finding[{finding_index}]")
            seat_findings.append(ref)
        finding_refs.extend(seat_findings)
        need(artifact["outcome"] in set(STATUS_OUTCOME.values()), f"{seat_label}: outcome")
        terminal, substantive, native_grounding = review_text_facts(native["review_text"], f"{seat_label}.native.review_text")
        need(native_grounding == grounding_refs, f"{seat_label}: native grounding mirror")
        for grounding_ref in native_grounding:
            need(grounding_ref in entries, f"{seat_label}: grounding outside bundle")
            root.read_ref(grounding_ref, f"{seat_label}.grounding")
        need(native_grounding == required_seat_evidence, f"{seat_label}: exact native grounding set")
        grounded = native_grounding == required_seat_evidence
        derived_outcome = STATUS_OUTCOME[native["status"]]
        need(artifact["outcome"] == derived_outcome, f"{seat_label}: native-derived outcome")
        usable = native["status"] == "OK" and derived_outcome == "reviewed" and terminal is not None and substantive and grounded
        verdict = terminal if usable else "DEFER"
        derived_seat = {
            "artifact": artifact_ref,
            "binding_prover": artifact["binding_prover"],
            "capability": artifact["capability"],
            "completed_at": artifact["completed_at"],
            "consumed_bundle": consumed_bundle,
            "counts_toward_floor": usable,
            "lens": artifact["lens"],
            "material_findings": seat_findings,
            "outcome": derived_outcome,
            "position": artifact["position"],
            "role": artifact["role"],
            "seat": artifact["seat"],
            "started_at": artifact["started_at"],
            "usable": usable,
            "vendor": artifact["vendor"],
            "verdict": verdict,
        }
        need({key: value for key, value in seat.items() if key != "receipt"} == derived_seat, f"{seat_label}: artifact-derived wrapper")
        seat_receipt, seat_digest = root.json_ref(file_ref(seat["receipt"], f"{seat_label}.receipt"), f"{seat_label}.receipt")
        expected_receipt = dict(derived_seat)
        expected_receipt.update({"attempt": attempt, "base": receipt["base"], "phase_alias": receipt["phase_alias"], "wave_id": receipt["wave_id"]})
        need(seat_receipt == expected_receipt, f"{seat_label}: receipt binding")
        reject_forbidden(execution, forbidden | {execution_digest}, f"{seat_label}.execution_attestation")
        reject_forbidden(native, forbidden | {native_digest}, f"{seat_label}.native_result")
        reject_forbidden(artifact, forbidden | {artifact_digest}, f"{seat_label}.artifact")
        reject_forbidden(seat_receipt, forbidden | {seat_digest}, f"{seat_label}.receipt")
        validated_seats.append(derived_seat)
        if usable and verdict == "AGREE":
            agree_artifacts.append(artifact_ref)
    need(len(set(seat_instance_ids)) == len(seat_instance_ids), f"{label}: duplicate seat instance")
    need(len(set(native_result_ids)) == len(native_result_ids), f"{label}: duplicate native result")
    need(timestamp(validated_seats[3]["started_at"], f"{label}.fable.started_at") > max(seat_completed[:3]), f"{label}: Fable order")
    need(completed_at > max(seat_completed), f"{label}: receipt completion")
    need(sum(seat["binding_prover"] for seat in validated_seats) == 1 and validated_seats[3]["binding_prover"], f"{label}: Fable-only binding")
    if final:
        need(not finding_refs, f"{label}: final material finding")
        need(validated_seats[1]["outcome"] == "reviewed" and validated_seats[1]["usable"] and validated_seats[1]["verdict"] == "AGREE", f"{label}: Sol result")
        need(validated_seats[3]["outcome"] == "reviewed" and validated_seats[3]["usable"] and validated_seats[3]["verdict"] == "AGREE", f"{label}: Fable result")

    validate_policy(receipt["effective_policy"], validated_seats, root, forbidden, final, f"{label}.policy")
    chain = receipt["restart_chain"]
    need(type(chain) is list and len(chain) == attempt - 1, f"{label}: restart cardinality")
    prior_metadata = []
    for index, item in enumerate(chain, start=1):
        exact_keys(item, {"attempt", "finding", "invalidated_agree_artifacts", "prior_bundle", "prior_receipt", "replacement_bundle_sha256"}, f"{label}.restart[{index}]")
        need(item["attempt"] == index, f"{label}.restart[{index}]: attempt")
        prior_receipt_ref = file_ref(item["prior_receipt"], f"{label}.restart[{index}].prior_receipt")
        prior_receipt, prior_digest = root.json_ref(prior_receipt_ref, f"{label}.restart[{index}].prior_receipt")
        need(prior_receipt.get("attempt") == index and prior_receipt.get("restart_chain") == chain[: index - 1], f"{label}.restart[{index}]: prior chain")
        metadata = validate_receipt(prior_receipt, expected_base, root, forbidden, prior_digest, False, f"{label}.attempt[{index}]")
        need(item["prior_bundle"] == metadata["bundle_ref"], f"{label}.restart[{index}]: prior bundle")
        root.read_ref(file_ref(item["prior_bundle"], f"{label}.restart[{index}].prior_bundle"), f"{label}.restart[{index}].prior_bundle")
        invalidated = item["invalidated_agree_artifacts"]
        need(type(invalidated) is list, f"{label}.restart[{index}]: invalidated")
        for invalidated_index, artifact in enumerate(invalidated):
            root.read_ref(file_ref(artifact, f"{label}.restart[{index}].invalidated[{invalidated_index}]"), f"{label}.restart[{index}].invalidated[{invalidated_index}]")
        need(invalidated == sorted(metadata["agree_artifacts"], key=lambda ref: ref["path"]), f"{label}.restart[{index}]: incomplete invalidation")
        finding_ref = file_ref(item["finding"], f"{label}.restart[{index}].finding")
        finding_time = validate_finding(finding_ref, root, forbidden, f"{label}.restart[{index}].finding")
        need(finding_ref in metadata["finding_refs"] or load_json_bytes(root.read_ref(finding_ref, f"{label}.restart[{index}].finding")[0], f"{label}.restart[{index}].finding", canonical=True)["contradiction"], f"{label}.restart[{index}]: unbound finding")
        need(finding_time <= metadata["completed_at"], f"{label}.restart[{index}]: finding chronology")
        need(type(item["replacement_bundle_sha256"]) is str and SHA64.fullmatch(item["replacement_bundle_sha256"]), f"{label}.restart[{index}]: replacement hash")
        need(item["replacement_bundle_sha256"] != metadata["bundle_digest"], f"{label}.restart[{index}]: unchanged bundle")
        prior_metadata.append((item, metadata))
    for index, (item, metadata) in enumerate(prior_metadata):
        next_metadata = prior_metadata[index + 1][1] if index + 1 < len(prior_metadata) else {"bundle_digest": bundle_digest, "early_started": early_started}
        need(item["replacement_bundle_sha256"] == next_metadata["bundle_digest"], f"{label}.restart[{index + 1}]: replacement binding")
        need(metadata["completed_at"] < next_metadata["early_started"], f"{label}.restart[{index + 1}]: complete restart")
    reject_forbidden(receipt, forbidden | {receipt_digest}, label)
    return {
        "agree_artifacts": agree_artifacts,
        "bundle_digest": bundle_digest,
        "bundle_ref": bundle_ref,
        "completed_at": completed_at,
        "early_started": early_started,
        "evidence_root_id": receipt["evidence_root_id"],
        "finding_refs": finding_refs,
    }


def strict_manifest(repo, commit):
    return load_json_bytes(git(repo, "show", f"{commit}:plans/manifest.json"), f"manifest@{commit}")


def phase_row(manifest, phase):
    slug = f"v10-{phase}"
    file_name = f"plans/phase-plan-v10-{phase}.md"
    rows = [row for row in manifest.get("plans", []) if row.get("slug") == slug and row.get("file") == file_name]
    need(len(rows) == 1, f"{phase}: row cardinality")
    return rows[0]


def completion_events(row):
    result = []
    for event in row.get("lifecycle", []):
        landing = event.get("metadata", {}).get("phase_completion_landing") if type(event) is dict else None
        if type(landing) is dict and landing.get("schema") == "v10.phase-completion-landing.v1":
            result.append(event)
    return result


def validate_completion(repo, base, phase, supplied_f, root):
    need(type(supplied_f) is str and SHA40.fullmatch(supplied_f), f"{phase}: supplied F")
    resolved_f = git_text(repo, "rev-parse", "--verify", f"{supplied_f}^{{commit}}")
    need(resolved_f == supplied_f and supplied_f != base, f"{phase}: F identity")
    git(repo, "merge-base", "--is-ancestor", supplied_f, base)
    f_parents = git_text(repo, "rev-list", "--parents", "-n", "1", supplied_f).split()
    need(len(f_parents) == 3 and f_parents[0] == supplied_f, f"{phase}: F topology")
    implementation, control = f_parents[1:]
    need(len({supplied_f, implementation, control, base}) == 4, f"{phase}: control identities")
    control_parents = git_text(repo, "rev-list", "--parents", "-n", "1", control).split()
    need(control_parents == [control, implementation], f"{phase}: FH topology")
    for left, right in ((implementation, control), (implementation, supplied_f)):
        changed = git_text(repo, "diff", "--name-only", left, right).splitlines()
        need(changed == ["plans/manifest.json"], f"{phase}: manifest-only delta")
        git(repo, "diff", "--quiet", left, right, "--", ".", ":(exclude)plans/manifest.json")
    manifests = {commit: strict_manifest(repo, commit) for commit in (implementation, control, supplied_f, base)}
    rows = {commit: phase_row(manifest, phase) for commit, manifest in manifests.items()}
    need(len(completion_events(rows[implementation])) == 0, f"{phase}: event exists at M")
    for commit in (control, supplied_f, base):
        need(len(completion_events(rows[commit])) == 1, f"{phase}: event cardinality at {commit}")
    event = completion_events(rows[control])[0]
    need(event == completion_events(rows[supplied_f])[0] == completion_events(rows[base])[0], f"{phase}: event drift")
    need(event == rows[control]["lifecycle"][-1], f"{phase}: event not terminal")
    need(rows[control] == rows[supplied_f] == rows[base], f"{phase}: completion row drift")
    need(rows[implementation].get("status") == "executing" and rows[control].get("status") == "completed", f"{phase}: status")
    executing = [item for item in rows[implementation].get("lifecycle", []) if item.get("transition") == "executing"]
    need(len(executing) == 1, f"{phase}: executing event")
    exact_keys(event, {"at", "by", "metadata", "transition"}, f"{phase}.event")
    need(event["transition"] == "completed" and event["by"] == executing[0].get("by"), f"{phase}: event actor")
    exact_keys(event["metadata"], {"phase_completion_landing"}, f"{phase}.metadata")
    landing = event["metadata"]["phase_completion_landing"]
    exact_keys(landing, {"audited_implementation_landing", "audited_implementation_tree", "canonical_origin", "canonical_ref", "final_audit", "final_evidence", "phase_alias", "plan_sha256", "review_wave", "roadmap_sha256", "run_id", "schema"}, f"{phase}.landing")
    need(landing["schema"] == "v10.phase-completion-landing.v1" and landing["phase_alias"] == phase, f"{phase}: landing schema")
    need(landing["canonical_origin"] == "Consiliency/agent-harness" and landing["canonical_ref"] == "refs/remotes/origin/main", f"{phase}: canonical source")
    need(landing["audited_implementation_landing"] == implementation, f"{phase}: audited landing")
    implementation_tree = git_text(repo, "rev-parse", f"{implementation}^{{tree}}")
    need(landing["audited_implementation_tree"] == implementation_tree, f"{phase}: audited tree")
    plan_path = f"plans/phase-plan-v10-{phase}.md"
    plan_sha = digest(git(repo, "show", f"{implementation}:{plan_path}"))
    roadmap_sha = digest(git(repo, "show", f"{implementation}:specs/phase-plans-v10.md"))
    need(landing["plan_sha256"] == plan_sha and landing["roadmap_sha256"] == roadmap_sha, f"{phase}: source digest")
    need(landing["run_id"] == executing[0].get("metadata", {}).get("run_id"), f"{phase}: run binding")
    wrapper = landing["review_wave"]
    exact_keys(wrapper, {"schema", "canonical_json", "receipt", "receipt_sha256"}, f"{phase}.review_wave")
    need(wrapper["schema"] == "v10.review-wave-receipt.v1" and wrapper["canonical_json"] == CANONICAL_JSON, f"{phase}: wrapper schema")
    need(type(wrapper["receipt_sha256"]) is str and SHA64.fullmatch(wrapper["receipt_sha256"]), f"{phase}: receipt hash")
    receipt_bytes = canonical_bytes(wrapper["receipt"])
    receipt_digest = digest(receipt_bytes)
    need(receipt_digest == wrapper["receipt_sha256"], f"{phase}: inner receipt digest")
    final_audit = file_ref(landing["final_audit"], f"{phase}.final_audit")
    final_evidence = file_ref(landing["final_evidence"], f"{phase}.final_evidence")
    expected_base = {
        "commit": implementation,
        "final_audit": final_audit,
        "final_evidence": final_evidence,
        "plan_sha256": plan_sha,
        "roadmap_sha256": roadmap_sha,
        "tree": implementation_tree,
    }
    event_digest = digest(canonical_bytes(event))
    metadata = validate_receipt(wrapper["receipt"], expected_base, root, {supplied_f, control, event_digest}, receipt_digest, True, f"{phase}.receipt")
    need(landing["final_audit"] == wrapper["receipt"]["base"]["final_audit"] and landing["final_evidence"] == wrapper["receipt"]["base"]["final_evidence"], f"{phase}: final artifact alias")
    need(event_timestamp(event["at"], f"{phase}.event.at") > metadata["completed_at"], f"{phase}: event chronology")
    return {
        "audited_implementation_landing": implementation,
        "completion_control_merge": supplied_f,
        "control_head": control,
        "evidence_bundle_sha256": metadata["bundle_digest"],
        "evidence_root": root.identity(),
        "review_wave_receipt_sha256": receipt_digest,
    }


def main():
    repo = Path(git_text(Path.cwd(), "rev-parse", "--show-toplevel"))
    need(str(repo) == os.path.realpath(repo), "repository root")
    need(git_text(repo, "rev-parse", "--is-shallow-repository") == "false", "shallow repository")
    need(git_text(repo, "replace", "-l") == "", "replace refs")
    grafts = Path(git_text(repo, "rev-parse", "--git-path", "info/grafts"))
    need(not grafts.exists() or grafts.stat().st_size == 0, "grafts")
    rewrites = git_text(repo, "config", "--show-origin", "--get-regexp", r"^url\..*\.(insteadOf|pushInsteadOf)$", allowed=(0, 1))
    need(rewrites == "", "URL rewriting")
    need(git_text(repo, "remote").splitlines() == ["origin"], "remote set")
    fetch_urls = git_text(repo, "config", "--get-all", "remote.origin.url").splitlines()
    push_urls = git_text(repo, "config", "--get-all", "remote.origin.pushurl", allowed=(0, 1)).splitlines()
    need(len(fetch_urls) == 1 and len(push_urls) <= 1, "origin URL cardinality")
    fetch_url = fetch_urls[0]
    push_url = push_urls[0] if push_urls else fetch_url
    canonical_urls = {
        "git@github.com:Consiliency/agent-harness.git",
        "ssh://git@github.com/Consiliency/agent-harness.git",
        "https://github.com/Consiliency/agent-harness.git",
    }
    need(fetch_url in canonical_urls and push_url in canonical_urls, "origin identity")
    base = git_text(repo, "rev-parse", "--verify", "refs/remotes/origin/main^{commit}")
    need(git_text(repo, "rev-parse", "HEAD") == base, "HEAD is not fetched canonical main")
    conform_root = EvidenceRoot(
        os.environ["REVIEWTRUTH_CONFORM_COMPLETION_EVIDENCE_ROOT"],
        os.environ["REVIEWTRUTH_CONFORM_COMPLETION_EVIDENCE_ROOT_ID"],
        "CONFORM root",
    )
    harden_root = EvidenceRoot(
        os.environ["REVIEWTRUTH_HARDEN_COMPLETION_EVIDENCE_ROOT"],
        os.environ["REVIEWTRUTH_HARDEN_COMPLETION_EVIDENCE_ROOT_ID"],
        "HARDEN root",
    )
    try:
        need(conform_root.path != harden_root.path and (conform_root.info.st_dev, conform_root.info.st_ino) != (harden_root.info.st_dev, harden_root.info.st_ino), "evidence roots alias")
        need(conform_root.expected_id != harden_root.expected_id, "evidence root ids alias")
        dependencies = {
            "CONFORM": validate_completion(repo, base, "CONFORM", os.environ["REVIEWTRUTH_CONFORM_COMPLETION_F"], conform_root),
            "HARDEN": validate_completion(repo, base, "HARDEN", os.environ["REVIEWTRUTH_HARDEN_COMPLETION_F"], harden_root),
        }
    finally:
        conform_root.close()
        harden_root.close()
    sidecar = {
        "canonical_origin": {
            "canonical_ref": "refs/remotes/origin/main",
            "fetch_url": fetch_url,
            "identity": "Consiliency/agent-harness",
            "push_url": push_url,
            "rewrite_rules": "absent",
        },
        "dependencies": dependencies,
        "schema": "reviewtruth_stage_a_review_waves.v1",
    }
    output = Path(os.environ["REVIEWTRUTH_RUNNER_ROOT"] + ".stage-a-review-waves.json")
    temporary = Path(str(output) + ".tmp")
    need(output.is_absolute() and not output.exists() and not output.is_symlink(), "review-wave sidecar exists")
    need(not temporary.exists() and not temporary.is_symlink(), "review-wave temporary exists")
    payload = canonical_bytes(sidecar)
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, output)
    output_info = os.stat(output, follow_symlinks=False)
    need(stat.S_ISREG(output_info.st_mode) and output_info.st_uid == os.getuid() and stat.S_IMODE(output_info.st_mode) == 0o600, "review-wave sidecar metadata")


if __name__ == "__main__":
    main()
```
<!-- REVIEWTRUTH_STAGE_A_REVIEW_WAVE_VERIFIER_END -->

- `env -i REVIEWTRUTH_RUNNER_ROOT="$REVIEWTRUTH_RUNNER_ROOT" REVIEWTRUTH_CONFORM_COMPLETION_F="$REVIEWTRUTH_CONFORM_COMPLETION_F" REVIEWTRUTH_HARDEN_COMPLETION_F="$REVIEWTRUTH_HARDEN_COMPLETION_F" PATH=/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 /bin/bash -euo pipefail -c 'repo=$(realpath -e -- "$(git rev-parse --show-toplevel)"); root=$REVIEWTRUTH_RUNNER_ROOT; record="$root.stage-a-base.json"; manifest_path=plans/manifest.json; roadmap_path=specs/phase-plans-v10.md; case "$root" in /*) ;; *) exit 61;; esac; case "$root/" in "$repo/"*) exit 62;; esac; parent=${root%/*}; test -n "$parent"; test "$parent" = "$(realpath -e -- "$parent")"; test "$(stat -c %u -- "$parent")" = "$(id -u)"; test $((8#$(stat -c %a -- "$parent") & 8#22)) -eq 0; test ! -e "$root"; test ! -L "$root"; test ! -e "$record"; test ! -L "$record"; test "$(git -C "$repo" rev-parse --is-shallow-repository)" = false; test -z "$(git -C "$repo" replace -l)"; grafts=$(git -C "$repo" rev-parse --git-path info/grafts); test ! -s "$grafts"; test -z "$(git -C "$repo" status --porcelain=v1 --untracked-files=all)"; rewrite_rules=$(git -C "$repo" config --show-origin --get-regexp "^url\\..*\\.(insteadOf|pushInsteadOf)$" || :); test -z "$rewrite_rules"; mapfile -t remotes < <(git -C "$repo" remote); test ${#remotes[@]} -eq 1; test "${remotes[0]}" = origin; mapfile -t fetch_urls < <(git -C "$repo" config --get-all remote.origin.url); test ${#fetch_urls[@]} -eq 1; fetch_url=${fetch_urls[0]}; mapfile -t configured_push_urls < <(git -C "$repo" config --get-all remote.origin.pushurl); test ${#configured_push_urls[@]} -le 1; if test ${#configured_push_urls[@]} -eq 0; then push_url=$fetch_url; else push_url=${configured_push_urls[0]}; fi; canonical_identity() { case "$1" in git@github.com:Consiliency/agent-harness.git|ssh://git@github.com/Consiliency/agent-harness.git|https://github.com/Consiliency/agent-harness.git) printf "%s" Consiliency/agent-harness;; *) return 1;; esac; }; fetch_identity=$(canonical_identity "$fetch_url"); push_identity=$(canonical_identity "$push_url"); test "$fetch_identity" = Consiliency/agent-harness; test "$push_identity" = "$fetch_identity"; git -C "$repo" fetch --no-tags --prune origin "+refs/heads/main:refs/remotes/origin/main"; base=$(git -C "$repo" rev-parse --verify "refs/remotes/origin/main^{commit}"); test "$(git -C "$repo" rev-parse HEAD)" = "$base"; tree=$(git -C "$repo" rev-parse "$base^{tree}"); verify_completion() { local phase=$1 supplied=$2 plan_file=$3 m_out=$4 fh_out=$5; local slug="v10-$phase"; [[ "$supplied" =~ ^[0-9a-f]{40}$ ]]; local f; f=$(git -C "$repo" rev-parse --verify "$supplied^{commit}"); test "$f" = "$supplied"; test "$f" != "$base"; git -C "$repo" merge-base --is-ancestor "$f" "$base"; local -a fparents fhparents changed_fh changed_f; read -r -a fparents <<<"$(git -C "$repo" rev-list --parents -n 1 "$f")"; test ${#fparents[@]} -eq 3; test "${fparents[0]}" = "$f"; local m=${fparents[1]} fh=${fparents[2]}; test "$m" != "$fh"; test "$m" != "$f"; read -r -a fhparents <<<"$(git -C "$repo" rev-list --parents -n 1 "$fh")"; test ${#fhparents[@]} -eq 2; test "${fhparents[0]}" = "$fh"; test "${fhparents[1]}" = "$m"; mapfile -t changed_fh < <(git -C "$repo" diff --name-only "$m" "$fh"); mapfile -t changed_f < <(git -C "$repo" diff --name-only "$m" "$f"); test ${#changed_fh[@]} -eq 1; test "${changed_fh[0]}" = "$manifest_path"; test ${#changed_f[@]} -eq 1; test "${changed_f[0]}" = "$manifest_path"; git -C "$repo" diff --quiet "$m" "$fh" -- . ":(exclude)$manifest_path"; git -C "$repo" diff --quiet "$m" "$f" -- . ":(exclude)$manifest_path"; test "$(git -C "$repo" rev-parse "$fh:$manifest_path")" = "$(git -C "$repo" rev-parse "$f:$manifest_path")"; row_at() { git -C "$repo" show "$1:$manifest_path" | jq -S -c --arg slug "$slug" --arg file "$plan_file" '\''[.plans[] | select(.slug == $slug and .file == $file)] | if length == 1 then .[0] else error("phase-row-cardinality") end'\''; }; events_for() { jq -S -c '\''[.lifecycle[]? | select(.metadata.phase_completion_landing.schema? == "v10.phase-completion-landing.v1")]'\'' <<<"$1"; }; local m_row fh_row f_row base_row m_events fh_events f_events base_events event executing executing_event m_static fh_static plan_sha base_plan_sha roadmap_sha base_roadmap_sha m_tree; m_row=$(row_at "$m"); fh_row=$(row_at "$fh"); f_row=$(row_at "$f"); base_row=$(row_at "$base"); m_events=$(events_for "$m_row"); fh_events=$(events_for "$fh_row"); f_events=$(events_for "$f_row"); base_events=$(events_for "$base_row"); test "$(jq -r length <<<"$m_events")" -eq 0; test "$(jq -r length <<<"$fh_events")" -eq 1; test "$(jq -r length <<<"$f_events")" -eq 1; test "$(jq -r length <<<"$base_events")" -eq 1; event=$(jq -S -c ".[0]" <<<"$fh_events"); test "$event" = "$(jq -S -c ".[0]" <<<"$f_events")"; test "$event" = "$(jq -S -c ".[0]" <<<"$base_events")"; test "$event" = "$(jq -S -c ".lifecycle[-1]" <<<"$fh_row")"; test "$(jq -S -c ".lifecycle" <<<"$m_row")" = "$(jq -S -c ".lifecycle[0:-1]" <<<"$fh_row")"; m_static=$(jq -S -c "del(.status,.updated_at,.lifecycle)" <<<"$m_row"); fh_static=$(jq -S -c "del(.status,.updated_at,.lifecycle)" <<<"$fh_row"); test "$m_static" = "$fh_static"; test "$fh_row" = "$f_row"; test "$fh_row" = "$base_row"; test "$(jq -r ".status" <<<"$m_row")" = executing; test "$(jq -r ".status" <<<"$fh_row")" = completed; test "$(jq -r ".updated_at" <<<"$fh_row")" = "$(jq -r ".at" <<<"$event")"; executing=$(jq -S -c '\''[.lifecycle[] | select(.transition == "executing")]'\'' <<<"$m_row"); test "$(jq -r length <<<"$executing")" -eq 1; executing_event=$(jq -S -c ".[0]" <<<"$executing"); plan_sha=$(git -C "$repo" show "$m:$plan_file" | sha256sum | cut -d" " -f1); base_plan_sha=$(git -C "$repo" show "$base:$plan_file" | sha256sum | cut -d" " -f1); roadmap_sha=$(git -C "$repo" show "$m:$roadmap_path" | sha256sum | cut -d" " -f1); base_roadmap_sha=$(git -C "$repo" show "$base:$roadmap_path" | sha256sum | cut -d" " -f1); test "$plan_sha" = "$base_plan_sha"; test "$roadmap_sha" = "$base_roadmap_sha"; m_tree=$(git -C "$repo" rev-parse "$m^{tree}"); jq -e --arg phase "$phase" --arg m "$m" --arg fh "$fh" --arg f "$f" --arg m_tree "$m_tree" --arg plan_sha "$plan_sha" --arg roadmap_sha "$roadmap_sha" --arg executing_by "$(jq -r ".by" <<<"$executing_event")" --arg executing_run "$(jq -r ".metadata.run_id" <<<"$executing_event")" '\''(keys == ["at","by","metadata","transition"]) and .transition == "completed" and (.by | type == "string" and length > 0) and .by == $executing_by and ($executing_run | length > 0) and ($executing_run != "null") and (.metadata | keys == ["phase_completion_landing"]) and (.metadata.phase_completion_landing as $p | ($p | keys == ["audited_implementation_landing","audited_implementation_tree","canonical_origin","canonical_ref","final_audit","final_evidence","phase_alias","plan_sha256","review_wave","roadmap_sha256","run_id","schema"]) and $p.schema == "v10.phase-completion-landing.v1" and $p.phase_alias == $phase and $p.plan_sha256 == $plan_sha and $p.roadmap_sha256 == $roadmap_sha and $p.run_id == $executing_run and $p.canonical_origin == "Consiliency/agent-harness" and $p.canonical_ref == "refs/remotes/origin/main" and $p.audited_implementation_landing == $m and $p.audited_implementation_tree == $m_tree and ($p.final_audit | keys == ["bytes","path","sha256"]) and ($p.final_evidence | keys == ["bytes","path","sha256"]) and ($p.review_wave | keys == ["canonical_json","receipt","receipt_sha256","schema"]) and $p.review_wave.schema == "v10.review-wave-receipt.v1" and $p.review_wave.canonical_json == "utf8-sorted-keys-compact-lf.v1" and ($p.review_wave.receipt | type == "object") and ($p.review_wave.receipt_sha256 | type == "string" and test("^[0-9a-f]{64}$")) and $p.final_audit == $p.review_wave.receipt.base.final_audit and $p.final_evidence == $p.review_wave.receipt.base.final_evidence and ($p.review_wave.receipt.completed_at | type == "string" and test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{6}Z$")) and .at > $p.review_wave.receipt.completed_at and ([ $p.review_wave.receipt | .. | scalars | select(. == $f or . == $fh or . == $p.review_wave.receipt_sha256) ] | length == 0))'\'' <<<"$event" >/dev/null; printf -v "$m_out" "%s" "$m"; printf -v "$fh_out" "%s" "$fh"; }; test "$REVIEWTRUTH_CONFORM_COMPLETION_F" != "$REVIEWTRUTH_HARDEN_COMPLETION_F"; conform_m= conform_fh= harden_m= harden_fh=; verify_completion CONFORM "$REVIEWTRUTH_CONFORM_COMPLETION_F" plans/phase-plan-v10-CONFORM.md conform_m conform_fh; verify_completion HARDEN "$REVIEWTRUTH_HARDEN_COMPLETION_F" plans/phase-plan-v10-HARDEN.md harden_m harden_fh; umask 077; temporary="$record.tmp"; test ! -e "$temporary"; jq -S -c -n --arg schema reviewtruth_stage_a_base.v1 --arg repo "$fetch_identity" --arg canonical_ref refs/remotes/origin/main --arg fetch_url "$fetch_url" --arg push_url "$push_url" --arg base_commit "$base" --arg base_tree "$tree" --arg conform_f "$REVIEWTRUTH_CONFORM_COMPLETION_F" --arg conform_m "$conform_m" --arg conform_fh "$conform_fh" --arg harden_f "$REVIEWTRUTH_HARDEN_COMPLETION_F" --arg harden_m "$harden_m" --arg harden_fh "$harden_fh" '\''{schema:$schema,repo:$repo,canonical_ref:$canonical_ref,canonical_origin:{identity:$repo,fetch_url:$fetch_url,push_url:$push_url,rewrite_rules:"absent"},base_commit:$base_commit,base_tree:$base_tree,conform_landing:$conform_f,harden_landing:$harden_f,dependencies:{CONFORM:{completion_control_merge:$conform_f,audited_implementation_landing:$conform_m,control_head:$conform_fh},HARDEN:{completion_control_merge:$harden_f,audited_implementation_landing:$harden_m,control_head:$harden_fh}}}'\'' >"$temporary"; chmod 600 "$temporary"; mv -T -- "$temporary" "$record"; test "$record" = "$(realpath -e -- "$record")"; test ! -L "$record"; test "$(stat -c %u -- "$record")" = "$(id -u)"; test "$(stat -c %a -- "$record")" = 600; test "$(git -C "$repo" rev-parse HEAD)" = "$base"; test "$(git -C "$repo" rev-parse "HEAD^{tree}")" = "$tree"; test -z "$(git -C "$repo" status --porcelain=v1 --untracked-files=all)"; sha256sum "$record"'` evidence: operational topology/exact-base preflight; run first
- `env -i REVIEWTRUTH_RUNNER_ROOT="$REVIEWTRUTH_RUNNER_ROOT" REVIEWTRUTH_CONFORM_COMPLETION_F="$REVIEWTRUTH_CONFORM_COMPLETION_F" REVIEWTRUTH_HARDEN_COMPLETION_F="$REVIEWTRUTH_HARDEN_COMPLETION_F" REVIEWTRUTH_CONFORM_COMPLETION_EVIDENCE_ROOT="$REVIEWTRUTH_CONFORM_COMPLETION_EVIDENCE_ROOT" REVIEWTRUTH_HARDEN_COMPLETION_EVIDENCE_ROOT="$REVIEWTRUTH_HARDEN_COMPLETION_EVIDENCE_ROOT" REVIEWTRUTH_CONFORM_COMPLETION_EVIDENCE_ROOT_ID="$REVIEWTRUTH_CONFORM_COMPLETION_EVIDENCE_ROOT_ID" REVIEWTRUTH_HARDEN_COMPLETION_EVIDENCE_ROOT_ID="$REVIEWTRUTH_HARDEN_COMPLETION_EVIDENCE_ROOT_ID" PATH=/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 /bin/bash -euo pipefail -c 'repo=$(realpath -e -- "$(git rev-parse --show-toplevel)"); root=$REVIEWTRUTH_RUNNER_ROOT; source_path="$root.stage-a-review-wave-verifier.py"; source_temporary="$source_path.tmp"; sidecar="$root.stage-a-review-waves.json"; base_record="$root.stage-a-base.json"; case "$root" in /*) ;; *) exit 101;; esac; case "$root/" in "$repo/"*) exit 102;; esac; test ! -e "$root"; test ! -L "$root"; for path in "$source_path" "$source_temporary" "$sidecar" "$sidecar.tmp"; do test ! -e "$path"; test ! -L "$path"; done; test "$base_record" = "$(realpath -e -- "$base_record")"; test -f "$base_record"; test ! -L "$base_record"; test "$(stat -c %u -- "$base_record")" = "$(id -u)"; test "$(stat -c %a -- "$base_record")" = 600; before_head=$(git -C "$repo" rev-parse HEAD); before_tree=$(git -C "$repo" rev-parse "HEAD^{tree}"); before_index=$(git -C "$repo" write-tree); test -z "$(git -C "$repo" status --porcelain=v1 --untracked-files=all)"; awk '\''BEGIN { fence=sprintf("%c%c%c",96,96,96) } /^<!-- REVIEWTRUTH_STAGE_A_REVIEW_WAVE_VERIFIER_BEGIN -->$/ { begin=1; next } begin == 1 { if ($0 != fence "python") exit 103; begin=2; next } begin == 2 && $0 == fence { done=1; exit } begin == 2 { print } END { if (begin != 2 || done != 1) exit 104 }'\'' "$repo/plans/phase-plan-v10-REVIEWTRUTH.md" >"$source_temporary"; test "$(wc -c <"$source_temporary")" -eq 57676; test "$(sha256sum -- "$source_temporary" | cut -d" " -f1)" = 97a4fd4e8614e0127b8ddf5a57bf9e3db02c3c94b8c364c6b82c054b8b8cbac0; chmod 700 "$source_temporary"; mv -T -- "$source_temporary" "$source_path"; test "$source_path" = "$(realpath -e -- "$source_path")"; test -f "$source_path"; test ! -L "$source_path"; test "$(stat -c %u -- "$source_path")" = "$(id -u)"; test "$(stat -c %a -- "$source_path")" = 700; env -i REVIEWTRUTH_RUNNER_ROOT="$root" REVIEWTRUTH_CONFORM_COMPLETION_F="$REVIEWTRUTH_CONFORM_COMPLETION_F" REVIEWTRUTH_HARDEN_COMPLETION_F="$REVIEWTRUTH_HARDEN_COMPLETION_F" REVIEWTRUTH_CONFORM_COMPLETION_EVIDENCE_ROOT="$REVIEWTRUTH_CONFORM_COMPLETION_EVIDENCE_ROOT" REVIEWTRUTH_HARDEN_COMPLETION_EVIDENCE_ROOT="$REVIEWTRUTH_HARDEN_COMPLETION_EVIDENCE_ROOT" REVIEWTRUTH_CONFORM_COMPLETION_EVIDENCE_ROOT_ID="$REVIEWTRUTH_CONFORM_COMPLETION_EVIDENCE_ROOT_ID" REVIEWTRUTH_HARDEN_COMPLETION_EVIDENCE_ROOT_ID="$REVIEWTRUTH_HARDEN_COMPLETION_EVIDENCE_ROOT_ID" PATH=/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 "$source_path"; test "$sidecar" = "$(realpath -e -- "$sidecar")"; test -f "$sidecar"; test ! -L "$sidecar"; test "$(stat -c %u -- "$sidecar")" = "$(id -u)"; test "$(stat -c %a -- "$sidecar")" = 600; jq -e '\''(keys == ["canonical_origin","dependencies","schema"]) and .schema == "reviewtruth_stage_a_review_waves.v1" and (.canonical_origin | keys == ["canonical_ref","fetch_url","identity","push_url","rewrite_rules"]) and .canonical_origin.identity == "Consiliency/agent-harness" and .canonical_origin.canonical_ref == "refs/remotes/origin/main" and .canonical_origin.rewrite_rules == "absent" and (.dependencies | keys == ["CONFORM","HARDEN"]) and all(.dependencies[]; (keys == ["audited_implementation_landing","completion_control_merge","control_head","evidence_bundle_sha256","evidence_root","review_wave_receipt_sha256"]) and (.evidence_root | keys == ["canonical_path","device","evidence_root_id","inode","mode","owner_uid"]) and (.evidence_root.canonical_path | type == "string" and startswith("/")) and (.evidence_root.evidence_root_id | type == "string" and length > 0) and (.evidence_root.mode | test("^0[0-7]{3}$")) and ([.evidence_bundle_sha256,.review_wave_receipt_sha256] | all(.[]; test("^[0-9a-f]{64}$"))))'\'' "$sidecar" >/dev/null; cmp -s "$sidecar" <(jq -S -c . "$sidecar"); test "$before_head" = "$(git -C "$repo" rev-parse HEAD)"; test "$before_tree" = "$(git -C "$repo" rev-parse "HEAD^{tree}")"; test "$before_index" = "$(git -C "$repo" write-tree)"; test -z "$(git -C "$repo" status --porcelain=v1 --untracked-files=all)"'` evidence: operational strict dependency review-wave verifier; run second
- `env -i REVIEWTRUTH_RUNNER_ROOT="$REVIEWTRUTH_RUNNER_ROOT" REVIEWTRUTH_UV="$REVIEWTRUTH_UV" PATH=/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 /bin/bash -euo pipefail -c 'repo=$(git rev-parse --show-toplevel); root=$REVIEWTRUTH_RUNNER_ROOT; uv=$REVIEWTRUTH_UV; case "$root" in /*) ;; *) exit 71;; esac; case "$uv" in /*) ;; *) exit 72;; esac; test "$repo" = "$(realpath -e -- "$repo")"; test "$uv" = "$(realpath -e -- "$uv")"; test -x "$uv"; test ! -L "$uv"; parent=${root%/*}; test -n "$parent"; test "$parent" = "$(realpath -e -- "$parent")"; test "$(stat -c %u -- "$parent")" = "$(id -u)"; test $((8#$(stat -c %a -- "$parent") & 8#22)) -eq 0; case "$root/" in "$repo/"*) exit 73;; esac; case "$repo/" in "$root/"*) exit 74;; esac; test ! -e "$root"; test ! -L "$root"; test -z "$(git -C "$repo" status --porcelain=v1 --untracked-files=all)"; before_head=$(git -C "$repo" rev-parse HEAD); before_tree=$(git -C "$repo" rev-parse "HEAD^{tree}"); before_index=$(git -C "$repo" write-tree); umask 077; mkdir -m 700 -- "$root"; mkdir -m 700 -- "$root"/{build,evidence,home,materialized,python,source,tmp,uv-cache,venv,wheels}; export HOME="$root/home" TMPDIR="$root/tmp" UV_CACHE_DIR="$root/uv-cache" UV_PYTHON_INSTALL_DIR="$root/python"; git -C "$repo" archive --format=tar HEAD:phase-loop-runtime | tar -xf - -C "$root/source"; cp -a -- "$root/source/." "$root/build/"; "$uv" venv --no-project --managed-python --python 3.12 --link-mode copy "$root/venv"; "$uv" build --wheel --no-create-gitignore --cache-dir "$root/uv-cache" --out-dir "$root/wheels" "$root/build"; wheels=("$root"/wheels/*.whl); test "${#wheels[@]}" -eq 1; wheel_path_file="$root/evidence/reviewtruth-wheel-path.txt"; test ! -e "$wheel_path_file"; printf "%s\n" "${wheels[0]}" >"$wheel_path_file"; chmod 600 "$wheel_path_file"; UV_PROJECT_ENVIRONMENT="$root/venv" "$uv" sync --frozen --extra visual --no-install-project --project "$root/source" --cache-dir "$root/uv-cache" --link-mode copy; "$uv" pip install --python "$root/venv/bin/python" --strict --link-mode copy --no-deps "${wheels[0]}"; "$uv" pip install --python "$root/venv/bin/python" --strict --link-mode copy pytest; "$uv" pip check --python "$root/venv/bin/python"; find "$root"/{build,evidence,home,materialized,source,tmp,wheels} -type d -exec chmod 700 {} +; find "$root"/{build,evidence,home,materialized,source,tmp,wheels} -type f -exec chmod 600 {} +; test -z "$(find "$root"/{build,evidence,home,materialized,source,tmp,wheels} ! -user "$(id -u)" -print -quit)"; test -z "$(find "$root"/{build,evidence,home,materialized,source,tmp,wheels} -perm /077 -print -quit)"; for name in build evidence home materialized python source tmp uv-cache venv wheels; do path="$root/$name"; test "$path" = "$(realpath -e -- "$path")"; test ! -L "$path"; test "$(stat -c %u -- "$path")" = "$(id -u)"; test $((8#$(stat -c %a -- "$path") & 8#77)) -eq 0; done; test -z "$(find "$root/source" "$root/build" "$root/evidence" "$root/home" "$root/materialized" "$root/tmp" "$root/wheels" -type l -print -quit)"; python_real=$(realpath -e -- "$root/venv/bin/python"); case "$python_real/" in "$root/python/"*) ;; *) exit 75;; esac; test "$before_head" = "$(git -C "$repo" rev-parse HEAD)"; test "$before_tree" = "$(git -C "$repo" rev-parse "HEAD^{tree}")"; test "$before_index" = "$(git -C "$repo" write-tree)"; test -z "$(git -C "$repo" status --porcelain=v1 --untracked-files=all)"'` evidence: operational
- `env -i REVIEWTRUTH_RUNNER_ROOT="$REVIEWTRUTH_RUNNER_ROOT" PATH=/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 /bin/bash -euo pipefail -c 'repo=$(git rev-parse --show-toplevel); root=$(realpath -e -- "$REVIEWTRUTH_RUNNER_ROOT"); test "$root" = "$REVIEWTRUTH_RUNNER_ROOT"; test "$(stat -c %u -- "$root")" = "$(id -u)"; test "$(stat -c %a -- "$root")" = 700; source_observer="$root/materialized/reviewtruth-baseline-observer.py"; gate_observer="$root/materialized/reviewtruth-gate-a-baseline-observer.py"; source_temporary="$source_observer.tmp"; gate_temporary="$gate_observer.tmp"; for path in "$source_observer" "$gate_observer" "$source_temporary" "$gate_temporary"; do test ! -e "$path"; test ! -L "$path"; done; before_head=$(git -C "$repo" rev-parse HEAD); before_tree=$(git -C "$repo" rev-parse "HEAD^{tree}"); before_index=$(git -C "$repo" write-tree); test -z "$(git -C "$repo" status --porcelain=v1 --untracked-files=all)"; awk '\''BEGIN { fence=sprintf("%c%c%c",96,96,96) } /^<!-- REVIEWTRUTH_BASELINE_OBSERVER_BEGIN -->$/ { begin=1; next } begin == 1 { if ($0 != fence "python") exit 81; begin=2; next } begin == 2 && $0 == fence { done=1; exit } begin == 2 { print } END { if (begin != 2 || done != 1) exit 82 }'\'' "$repo/plans/phase-plan-v10-REVIEWTRUTH.md" >"$source_temporary"; awk '\''BEGIN { fence=sprintf("%c%c%c",96,96,96) } /^<!-- REVIEWTRUTH_GATE_A_BASELINE_OBSERVER_BEGIN -->$/ { begin=1; next } begin == 1 { if ($0 != fence "python") exit 83; begin=2; next } begin == 2 && $0 == fence { done=1; exit } begin == 2 { print } END { if (begin != 2 || done != 1) exit 84 }'\'' "$repo/plans/phase-plan-v10-REVIEWTRUTH.md" >"$gate_temporary"; test "$(wc -c <"$source_temporary")" -eq 39420; test "$(sha256sum "$source_temporary" | cut -d" " -f1)" = 841cfb8bbac1d9b4ea0bb14a1f3600165550227b680b2e5689c79c13c61b1f6d; test "$(wc -c <"$gate_temporary")" -eq 45116; test "$(sha256sum "$gate_temporary" | cut -d" " -f1)" = d51199649bf0c4a2ed3c647e210128ecd07112c5229143b976de7600943af3c9; chmod 700 "$source_temporary" "$gate_temporary"; mv -T -- "$source_temporary" "$source_observer"; mv -T -- "$gate_temporary" "$gate_observer"; for observer in "$source_observer" "$gate_observer"; do test "$observer" = "$(realpath -e -- "$observer")"; test ! -L "$observer"; test "$(stat -c %u -- "$observer")" = "$(id -u)"; test "$(stat -c %a -- "$observer")" = 700; done; test "$before_head" = "$(git -C "$repo" rev-parse HEAD)"; test "$before_tree" = "$(git -C "$repo" rev-parse "HEAD^{tree}")"; test "$before_index" = "$(git -C "$repo" write-tree)"; test -z "$(git -C "$repo" status --porcelain=v1 --untracked-files=all)"'` evidence: operational
- `env -i HOME="$REVIEWTRUTH_RUNNER_ROOT/home" PATH="$REVIEWTRUTH_RUNNER_ROOT/venv/bin:/usr/bin:/bin" LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH="$PWD/phase-loop-runtime/src" TMPDIR="$REVIEWTRUTH_RUNNER_ROOT/tmp" "$REVIEWTRUTH_RUNNER_ROOT/venv/bin/python" "$REVIEWTRUTH_RUNNER_ROOT/materialized/reviewtruth-baseline-observer.py" --mode provision --repo "$PWD" --plan "$PWD/plans/phase-plan-v10-REVIEWTRUTH.md" --roadmap "$PWD/specs/phase-plans-v10.md" --runner-root "$REVIEWTRUTH_RUNNER_ROOT" --wheel "$(cat "$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-wheel-path.txt")" --uv "$REVIEWTRUTH_UV" --out "$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-bootstrap-provisioning.json" --observer-sha256 841cfb8bbac1d9b4ea0bb14a1f3600165550227b680b2e5689c79c13c61b1f6d` evidence: operational
- `env -i HOME="$REVIEWTRUTH_RUNNER_ROOT/home" PATH="$REVIEWTRUTH_RUNNER_ROOT/venv/bin:/usr/bin:/bin" LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH="$PWD/phase-loop-runtime/src" TMPDIR="$REVIEWTRUTH_RUNNER_ROOT/tmp" "$REVIEWTRUTH_RUNNER_ROOT/venv/bin/python" "$REVIEWTRUTH_RUNNER_ROOT/materialized/reviewtruth-baseline-observer.py" --mode observe --repo "$PWD" --plan "$PWD/plans/phase-plan-v10-REVIEWTRUTH.md" --roadmap "$PWD/specs/phase-plans-v10.md" --runner-root "$REVIEWTRUTH_RUNNER_ROOT" --wheel "$(cat "$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-wheel-path.txt")" --uv "$REVIEWTRUTH_UV" --provisioning "$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-bootstrap-provisioning.json" --out "$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-baseline-preimplementation" --observer-sha256 841cfb8bbac1d9b4ea0bb14a1f3600165550227b680b2e5689c79c13c61b1f6d` evidence: operational
- `env -i REVIEWTRUTH_RUNNER_ROOT="$REVIEWTRUTH_RUNNER_ROOT" PATH=/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 /bin/bash -euo pipefail -c 'repo=$(git rev-parse --show-toplevel); root=$(realpath -e -- "$REVIEWTRUTH_RUNNER_ROOT"); input="$root/gate-a-preimplementation-input"; standalone="$input/standalone"; tests="$standalone/phase-loop-runtime/tests"; output="$root/evidence/reviewtruth-gate-a-preimplementation"; source_output="$root/evidence/reviewtruth-baseline-preimplementation"; manifest="$root/evidence/reviewtruth-stage-a-candidate-artifacts.json"; profile_digest="$root/evidence/reviewtruth-stage-a-candidate-profile.sha256"; manifest_temporary="$manifest.tmp"; profile_temporary="$profile_digest.tmp"; stage_a_snapshots="$root/stage-a-snapshots"; stage_a_plan="$stage_a_snapshots/plans/phase-plan-v10-REVIEWTRUTH.md"; stage_a_roadmap="$stage_a_snapshots/specs/phase-plans-v10.md"; plan_temporary="$stage_a_plan.tmp"; roadmap_temporary="$stage_a_roadmap.tmp"; live_plan="$repo/plans/phase-plan-v10-REVIEWTRUTH.md"; live_roadmap="$repo/specs/phase-plans-v10.md"; for path in "$input" "$output" "$manifest" "$profile_digest" "$manifest_temporary" "$profile_temporary" "$stage_a_snapshots" "$stage_a_snapshots/plans" "$stage_a_snapshots/specs" "$stage_a_plan" "$stage_a_roadmap" "$plan_temporary" "$roadmap_temporary"; do test ! -e "$path"; test ! -L "$path"; done; before_head=$(git -C "$repo" rev-parse HEAD); before_tree=$(git -C "$repo" rev-parse "HEAD^{tree}"); before_index=$(git -C "$repo" write-tree); test -z "$(git -C "$repo" status --porcelain=v1 --untracked-files=all)"; test "$repo" = "$(realpath -e -- "$repo")"; for source in "$live_plan" "$live_roadmap"; do test "$source" = "$(realpath -e -- "$source")"; test -f "$source"; test ! -L "$source"; done; plan_source_sha=$(sha256sum -- "$live_plan" | cut -d" " -f1); roadmap_source_sha=$(sha256sum -- "$live_roadmap" | cut -d" " -f1); umask 077; mkdir -m 700 "$input" "$standalone"; mkdir -m 700 "$stage_a_snapshots"; mkdir -m 700 "$stage_a_snapshots/plans" "$stage_a_snapshots/specs"; cp -- "$live_plan" "$plan_temporary"; cp -- "$live_roadmap" "$roadmap_temporary"; chmod 600 "$plan_temporary" "$roadmap_temporary"; for temporary in "$plan_temporary" "$roadmap_temporary"; do test "$temporary" = "$(realpath -e -- "$temporary")"; test -f "$temporary"; test ! -L "$temporary"; test "$(stat -c %u -- "$temporary")" = "$(id -u)"; test "$(stat -c %a -- "$temporary")" = 600; done; mv -T -- "$plan_temporary" "$stage_a_plan"; mv -T -- "$roadmap_temporary" "$stage_a_roadmap"; for directory in "$stage_a_snapshots" "$stage_a_snapshots/plans" "$stage_a_snapshots/specs"; do test "$directory" = "$(realpath -e -- "$directory")"; test -d "$directory"; test ! -L "$directory"; test "$(stat -c %u -- "$directory")" = "$(id -u)"; test "$(stat -c %a -- "$directory")" = 700; done; for snapshot in "$stage_a_plan" "$stage_a_roadmap"; do test "$snapshot" = "$(realpath -e -- "$snapshot")"; test -f "$snapshot"; test ! -L "$snapshot"; test "$(stat -c %u -- "$snapshot")" = "$(id -u)"; test "$(stat -c %a -- "$snapshot")" = 600; done; cmp -s "$stage_a_plan" "$live_plan"; cmp -s "$stage_a_roadmap" "$live_roadmap"; test "$(sha256sum -- "$stage_a_plan" | cut -d" " -f1)" = "$plan_source_sha"; test "$(sha256sum -- "$live_plan" | cut -d" " -f1)" = "$plan_source_sha"; test "$(sha256sum -- "$stage_a_roadmap" | cut -d" " -f1)" = "$roadmap_source_sha"; test "$(sha256sum -- "$live_roadmap" | cut -d" " -f1)" = "$roadmap_source_sha"; git -C "$repo" archive --format=tar HEAD phase-loop-runtime/tests | tar -xf - -C "$standalone"; find "$input" -type d -exec chmod 700 {} +; find "$input" -type f -exec chmod go-rwx {} +; test -z "$(find "$input" ! -user "$(id -u)" -print -quit)"; test -z "$(find "$input" -perm /077 -print -quit)"; test -z "$(find "$input" -type l -print -quit)"; test "$tests" = "$(realpath -e -- "$tests")"; (cd "$standalone"; env -i HOME="$root/home" PATH="$root/venv/bin:/usr/bin:/bin" LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH="$tests" TMPDIR="$root/tmp" "$root/venv/bin/python" "$root/materialized/reviewtruth-gate-a-baseline-observer.py" --repo "$repo" --plan "$repo/plans/phase-plan-v10-REVIEWTRUTH.md" --roadmap "$repo/specs/phase-plans-v10.md" --runner-root "$root" --wheel "$(cat "$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-wheel-path.txt")" --provisioning "$root/evidence/reviewtruth-bootstrap-provisioning.json" --source-observation-dir "$root/evidence/reviewtruth-baseline-preimplementation" --tests-root "$tests" --out "$output" --observer-sha256 d51199649bf0c4a2ed3c647e210128ecd07112c5229143b976de7600943af3c9); jq -e '\''type == "object" and ((.source_full_count | type) == "number") and ((.source_selected_count | type) == "number") and ((.gate_a_full_count | type) == "number") and ((.gate_a_selected_count | type) == "number") and (.source_full_count >= .source_selected_count) and (.gate_a_full_count >= .gate_a_selected_count) and (.omitted_full_equals_omitted_selected == true) and (.omitted_full_count == (.source_full_count - .gate_a_full_count)) and (.omitted_selected_count == (.source_selected_count - .gate_a_selected_count)) and (.omitted_modules_count == (.omitted_modules | length)) and (.expected_gate_a_count == (.restricted_source_count + .boundary_collection_count + .boundary_runtime_count)) and ([.source_full_sha256,.source_selected_sha256,.gate_a_full_sha256,.gate_a_selected_sha256,.source_marker_deselected_sha256,.gate_a_marker_deselected_sha256,.omitted_full_sha256,.omitted_selected_sha256,.restricted_source_sha256,.boundary_collection_sha256,.boundary_runtime_sha256,.expected_gate_a_sha256] | all(.[]; ((type == "string") and test("^[0-9a-f]{64}$"))))'\'' "$output/paired-profile.json" >/dev/null; base_record="$root.stage-a-base.json"; review_waves_record="$root.stage-a-review-waves.json"; test "$base_record" = "$(realpath -e -- "$base_record")"; test ! -L "$base_record"; test "$(stat -c %u -- "$base_record")" = "$(id -u)"; test "$(stat -c %a -- "$base_record")" = 600; jq -e --arg base "$before_head" --arg tree "$before_tree" '\''(keys == ["base_commit","base_tree","canonical_origin","canonical_ref","conform_landing","dependencies","harden_landing","repo","schema"]) and .schema == "reviewtruth_stage_a_base.v1" and .repo == "Consiliency/agent-harness" and .canonical_ref == "refs/remotes/origin/main" and .base_commit == $base and .base_tree == $tree and (.canonical_origin | keys == ["fetch_url","identity","push_url","rewrite_rules"]) and .canonical_origin.identity == "Consiliency/agent-harness" and .canonical_origin.rewrite_rules == "absent" and (.canonical_origin.fetch_url == "git@github.com:Consiliency/agent-harness.git" or .canonical_origin.fetch_url == "ssh://git@github.com/Consiliency/agent-harness.git" or .canonical_origin.fetch_url == "https://github.com/Consiliency/agent-harness.git") and (.canonical_origin.push_url == "git@github.com:Consiliency/agent-harness.git" or .canonical_origin.push_url == "ssh://git@github.com/Consiliency/agent-harness.git" or .canonical_origin.push_url == "https://github.com/Consiliency/agent-harness.git") and (.dependencies | keys == ["CONFORM","HARDEN"]) and (.dependencies.CONFORM | keys == ["audited_implementation_landing","completion_control_merge","control_head"]) and (.dependencies.HARDEN | keys == ["audited_implementation_landing","completion_control_merge","control_head"]) and .conform_landing == .dependencies.CONFORM.completion_control_merge and .harden_landing == .dependencies.HARDEN.completion_control_merge and .conform_landing != .harden_landing and ([.dependencies.CONFORM.completion_control_merge,.dependencies.CONFORM.audited_implementation_landing,.dependencies.CONFORM.control_head,.dependencies.HARDEN.completion_control_merge,.dependencies.HARDEN.audited_implementation_landing,.dependencies.HARDEN.control_head] | all(.[]; test("^[0-9a-f]{40}$")))'\'' "$base_record" >/dev/null; cmp -s "$base_record" <(jq -S -c . "$base_record"); test "$review_waves_record" = "$(realpath -e -- "$review_waves_record")"; test ! -L "$review_waves_record"; test "$(stat -c %u -- "$review_waves_record")" = "$(id -u)"; test "$(stat -c %a -- "$review_waves_record")" = 600; jq -e '\''(keys == ["canonical_origin","dependencies","schema"]) and .schema == "reviewtruth_stage_a_review_waves.v1" and (.canonical_origin | keys == ["canonical_ref","fetch_url","identity","push_url","rewrite_rules"]) and .canonical_origin.identity == "Consiliency/agent-harness" and .canonical_origin.canonical_ref == "refs/remotes/origin/main" and .canonical_origin.rewrite_rules == "absent" and (.dependencies | keys == ["CONFORM","HARDEN"]) and ([.dependencies.CONFORM,.dependencies.HARDEN] | all(.[]; keys == ["audited_implementation_landing","completion_control_merge","control_head","evidence_bundle_sha256","evidence_root","review_wave_receipt_sha256"] and (.evidence_root | keys == ["canonical_path","device","evidence_root_id","inode","mode","owner_uid"]) and ([.audited_implementation_landing,.completion_control_merge,.control_head] | all(.[]; test("^[0-9a-f]{40}$"))) and ([.evidence_bundle_sha256,.review_wave_receipt_sha256] | all(.[]; test("^[0-9a-f]{64}$")))))'\'' "$review_waves_record" >/dev/null; cmp -s "$review_waves_record" <(jq -S -c . "$review_waves_record"); add_file() { local identity=$1 physical=$2 mode bytes digest; case "$identity" in ""|/*|.|..|./*|../*|*//*|*/./*|*/../*|*/.|*/..) return 91;; esac; test "$physical" = "$(realpath -e -- "$physical")"; test -f "$physical"; test ! -L "$physical"; test "$(stat -c %u -- "$physical")" = "$(id -u)"; mode="0$(stat -c %a -- "$physical")"; bytes=$(stat -c %s -- "$physical"); digest=$(sha256sum -- "$physical" | cut -d" " -f1); jq -S -c -n --arg path "$identity" --arg mode "$mode" --argjson bytes "$bytes" --arg sha256 "$digest" '\''{path:$path,mode:$mode,bytes:$bytes,sha256:$sha256}'\''; }; assert_observation() { local directory=$1 expected=$2 name; shift 2; test "$directory" = "$(realpath -e -- "$directory")"; test ! -L "$directory"; test -d "$directory"; test "$(stat -c %u -- "$directory")" = "$(id -u)"; test "$(stat -c %a -- "$directory")" = 700; test -z "$(find "$directory" -mindepth 1 -maxdepth 1 ! -type f -print -quit)"; test "$(find "$directory" -mindepth 1 -maxdepth 1 -type f -printf x | wc -c)" -eq "$expected"; for name in "$@"; do test -f "$directory/$name"; test ! -L "$directory/$name"; test "$(stat -c %a -- "$directory/$name")" = 600; done; }; add_tree() { local prefix=$1 tree=$2 physical relative count=0; test "$tree" = "$(realpath -e -- "$tree")"; test -d "$tree"; test ! -L "$tree"; while IFS= read -r -d "" physical; do test ! -L "$physical"; test "$(stat -c %u -- "$physical")" = "$(id -u)"; if test -d "$physical"; then continue; fi; test -f "$physical"; relative=$(realpath --relative-to="$tree" -- "$physical"); add_file "$prefix/$relative" "$physical"; count=$((count + 1)); done < <(find "$tree" -mindepth 1 -print0 | sort -z); test "$count" -gt 0; }; emit_entries() { local name; assert_observation "$source_output" 9 attestation.json broad.xml full-nodeids.txt legitimate-skips.json marker-deselected-nodeids.txt plugin-events.json selected-nodeids.txt stderr.txt stdout.txt; assert_observation "$output" 14 attestation.json broad.xml collection-skips.json copied-tests-manifest.json full-nodeids.txt marker-deselected-nodeids.txt omitted-roots.json paired-profile.json plugin-events.json runtime-skips.json selected-nodeids.txt source-observation-manifest.json stderr.txt stdout.txt; for name in attestation.json broad.xml full-nodeids.txt legitimate-skips.json marker-deselected-nodeids.txt plugin-events.json selected-nodeids.txt stderr.txt stdout.txt; do add_file "observations/source/$name" "$source_output/$name"; done; for name in attestation.json broad.xml collection-skips.json copied-tests-manifest.json full-nodeids.txt marker-deselected-nodeids.txt omitted-roots.json paired-profile.json plugin-events.json runtime-skips.json selected-nodeids.txt source-observation-manifest.json stderr.txt stdout.txt; do add_file "observations/gate-a/$name" "$output/$name"; done; add_file materialized/reviewtruth-baseline-observer.py "$root/materialized/reviewtruth-baseline-observer.py"; add_file materialized/reviewtruth-gate-a-baseline-observer.py "$root/materialized/reviewtruth-gate-a-baseline-observer.py"; add_file evidence/reviewtruth-bootstrap-provisioning.json "$root/evidence/reviewtruth-bootstrap-provisioning.json"; add_file repository-stage-a/plans/phase-plan-v10-REVIEWTRUTH.md "$stage_a_plan"; add_file repository-stage-a/specs/phase-plans-v10.md "$stage_a_roadmap"; add_file exact-base/reviewtruth-stage-a-base.json "$base_record"; add_file exact-base/reviewtruth-stage-a-review-waves.json "$review_waves_record"; add_tree runtime-tree/phase-loop-runtime "$repo/phase-loop-runtime"; add_tree copied-tests/phase-loop-runtime/tests "$tests"; }; emit_manifest() { emit_entries | jq -S -c -s '\''{schema:"reviewtruth_stage_a_candidate_artifacts.v1",digest_algorithm:"sha256",identity_scheme:"canonical-relative-path.v1",entries:(sort_by(.path))}'\''; }; emit_manifest >"$manifest_temporary"; chmod 600 "$manifest_temporary"; jq -e '\''type == "object" and (keys == ["digest_algorithm","entries","identity_scheme","schema"]) and .schema == "reviewtruth_stage_a_candidate_artifacts.v1" and .digest_algorithm == "sha256" and .identity_scheme == "canonical-relative-path.v1" and (.entries | (type == "array") and length > 0 and (map(.path) == (map(.path) | sort)) and ((map(.path) | length) == (map(.path) | unique | length)) and all(.[]; (keys == ["bytes","mode","path","sha256"]) and ((.path | type) == "string") and (.path | length > 0) and (.path | startswith("/") | not) and (.path | contains("//") | not) and (.path | test("(^|/)\\.\\.?(/|$)") | not) and ((.mode | type) == "string") and (.mode | test("^0[0-7]{3}$")) and ((.bytes | type) == "number") and (.bytes >= 0) and (.bytes == (.bytes | floor)) and ((.sha256 | type) == "string") and (.sha256 | test("^[0-9a-f]{64}$"))))'\'' "$manifest_temporary" >/dev/null; cmp -s "$manifest_temporary" <(jq -S -c . "$manifest_temporary"); mv -T -- "$manifest_temporary" "$manifest"; test "$manifest" = "$(realpath -e -- "$manifest")"; test ! -L "$manifest"; test "$(stat -c %u -- "$manifest")" = "$(id -u)"; test "$(stat -c %a -- "$manifest")" = 600; cmp -s "$manifest" <(emit_manifest); base_sha=$(sha256sum -- "$base_record" | cut -d" " -f1); manifest_sha=$(sha256sum -- "$manifest" | cut -d" " -f1); profile_input() { jq -S -c -n --arg schema reviewtruth_stage_a_candidate_profile_input.v1 --arg base_path exact-base/reviewtruth-stage-a-base.json --arg base_sha256 "$base_sha" --arg manifest_path evidence/reviewtruth-stage-a-candidate-artifacts.json --arg manifest_sha256 "$manifest_sha" '\''{schema:$schema,exact_base:{path:$base_path,sha256:$base_sha256},candidate_artifact_manifest:{path:$manifest_path,sha256:$manifest_sha256}}'\''; }; profile_value=$(profile_input | sha256sum | cut -d" " -f1); printf "%s  reviewtruth-stage-a-candidate-profile.v1\n" "$profile_value" >"$profile_temporary"; chmod 600 "$profile_temporary"; mv -T -- "$profile_temporary" "$profile_digest"; test "$profile_digest" = "$(realpath -e -- "$profile_digest")"; test ! -L "$profile_digest"; test "$(stat -c %u -- "$profile_digest")" = "$(id -u)"; test "$(stat -c %a -- "$profile_digest")" = 600; cmp -s "$manifest" <(emit_manifest); verified_value=$(profile_input | sha256sum | cut -d" " -f1); cmp -s "$profile_digest" <(printf "%s  reviewtruth-stage-a-candidate-profile.v1\n" "$verified_value"); cmp -s "$stage_a_plan" "$live_plan"; cmp -s "$stage_a_roadmap" "$live_roadmap"; test "$(sha256sum -- "$stage_a_plan" | cut -d" " -f1)" = "$plan_source_sha"; test "$(sha256sum -- "$live_plan" | cut -d" " -f1)" = "$plan_source_sha"; test "$(sha256sum -- "$stage_a_roadmap" | cut -d" " -f1)" = "$roadmap_source_sha"; test "$(sha256sum -- "$live_roadmap" | cut -d" " -f1)" = "$roadmap_source_sha"; test "$before_head" = "$(git -C "$repo" rev-parse HEAD)"; test "$before_tree" = "$(git -C "$repo" rev-parse "HEAD^{tree}")"; test "$before_index" = "$(git -C "$repo" write-tree)"; test -z "$(git -C "$repo" status --porcelain=v1 --untracked-files=all)"'` evidence: operational
- `env PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_reviewtruth_phase.py::test_review_wave_plan_design_allows_critics_first_but_requires_early_probe_before_fable phase-loop-runtime/tests/test_reviewtruth_phase.py::test_review_wave_premerge_release_stages_early_prover_evidence_before_critics phase-loop-runtime/tests/test_reviewtruth_phase.py::test_review_wave_capabilities_distinguish_can_probe_from_binding_prover phase-loop-runtime/tests/test_reviewtruth_phase.py::test_review_wave_bundle_binds_input_head_bundle_and_evidence_digests phase-loop-runtime/tests/test_reviewtruth_phase.py::test_review_wave_contradicting_prover_invalidates_agree_and_requires_updated_bundle_rereview phase-loop-runtime/tests/test_reviewtruth_phase.py::test_review_wave_unconfined_grok_records_degraded_evidence_without_launch phase-loop-runtime/tests/test_reviewtruth_phase.py::test_review_wave_gemini_is_never_selected_as_write_capable_prover phase-loop-runtime/tests/test_reviewtruth_phase.py::test_review_wave_predecessor_critic_artifacts_do_not_count_before_early_codex_evidence phase-loop-runtime/tests/test_phase_worktree_executor.py::test_early_prover_codex_uses_cli_workspace_write_in_per_leg_ephemeral_worktree phase-loop-runtime/tests/test_phase_worktree_executor.py::test_early_prover_serial_holder_gets_distinct_data_scope_and_exact_digest_binding phase-loop-runtime/tests/test_phase_worktree_executor.py::test_early_prover_external_reaper_cleans_crash_residue_without_leg_authority phase-loop-runtime/tests/test_phase_worktree_executor.py::test_early_prover_codex_external_tool_policy_and_effective_preflight_fail_closed phase-loop-runtime/tests/test_phase_worktree_executor.py::test_early_prover_external_tool_policy_preflight_and_receipt_are_digest_bound phase-loop-runtime/tests/test_phase_worktree_executor.py::test_early_prover_coordinator_rejects_unusable_workspace_mount_before_leg_launch phase-loop-runtime/tests/test_phase_worktree_executor.py::test_early_prover_custom_writable_workspace_mount_flows_through_worktree_creation phase-loop-runtime/tests/test_phase_worktree_executor.py::test_early_prover_real_workspace_mount_is_used_when_safely_available -q` (Stage-B SL1-T1 literal RED; all 16 exact nodes must fail only at their mapped anchors before any production edit; node digest `c54d268bafd176e0d22c179eac2a175f208eb2c28f73027982d9c7780dc2219a`, anchor digest `8d175395fd67f2a9297a5b8fdb06f57bfa8595a268746a165ab9878d4d371e05`)
- `env PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_reviewtruth_phase.py::test_reviewtruth_exact_pypi_transport_disposition_normalizes_only_source_attributed_skip -q` (SL1-T1 expected RED at `REVIEWTRUTH_RED::exact_pypi_transport_disposition` after both falsifiers are authored and before parser/conftest implementation; retain exact output)
- `env PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_reviewtruth_phase.py::test_reviewtruth_exact_console_script_availability_disposition_normalizes_only_source_layout_skip -q` (SL1-T1 expected RED at `REVIEWTRUTH_RED::exact_console_script_availability_disposition` after both falsifiers are authored and before parser/conftest implementation; retain exact output)
- `env PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_reviewtruth_phase.py::test_reviewtruth_exact_pypi_transport_disposition_normalizes_only_source_attributed_skip -q` (SL1-T2 required GREEN for the same immutable node after only both parser/conftest disposition contracts are implemented; uses synthetic fixtures and requires no live internet)
- `env PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_reviewtruth_phase.py::test_reviewtruth_exact_console_script_availability_disposition_normalizes_only_source_layout_skip -q` (SL1-T2 required GREEN for the same immutable node after only both parser/conftest disposition contracts are implemented; uses synthetic fixtures, requires no PATH mutation or live command installation, and runs before broad-baseline parsing)
- `env PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_reviewtruth_phase.py::test_review_wave_plan_design_allows_critics_first_but_requires_early_probe_before_fable phase-loop-runtime/tests/test_reviewtruth_phase.py::test_review_wave_premerge_release_stages_early_prover_evidence_before_critics phase-loop-runtime/tests/test_reviewtruth_phase.py::test_review_wave_capabilities_distinguish_can_probe_from_binding_prover phase-loop-runtime/tests/test_reviewtruth_phase.py::test_review_wave_bundle_binds_input_head_bundle_and_evidence_digests phase-loop-runtime/tests/test_reviewtruth_phase.py::test_review_wave_contradicting_prover_invalidates_agree_and_requires_updated_bundle_rereview phase-loop-runtime/tests/test_reviewtruth_phase.py::test_review_wave_unconfined_grok_records_degraded_evidence_without_launch phase-loop-runtime/tests/test_reviewtruth_phase.py::test_review_wave_gemini_is_never_selected_as_write_capable_prover phase-loop-runtime/tests/test_reviewtruth_phase.py::test_review_wave_predecessor_critic_artifacts_do_not_count_before_early_codex_evidence phase-loop-runtime/tests/test_phase_worktree_executor.py::test_early_prover_codex_uses_cli_workspace_write_in_per_leg_ephemeral_worktree phase-loop-runtime/tests/test_phase_worktree_executor.py::test_early_prover_serial_holder_gets_distinct_data_scope_and_exact_digest_binding phase-loop-runtime/tests/test_phase_worktree_executor.py::test_early_prover_external_reaper_cleans_crash_residue_without_leg_authority phase-loop-runtime/tests/test_phase_worktree_executor.py::test_early_prover_codex_external_tool_policy_and_effective_preflight_fail_closed phase-loop-runtime/tests/test_phase_worktree_executor.py::test_early_prover_external_tool_policy_preflight_and_receipt_are_digest_bound phase-loop-runtime/tests/test_phase_worktree_executor.py::test_early_prover_coordinator_rejects_unusable_workspace_mount_before_leg_launch phase-loop-runtime/tests/test_phase_worktree_executor.py::test_early_prover_custom_writable_workspace_mount_flows_through_worktree_creation phase-loop-runtime/tests/test_phase_worktree_executor.py::test_early_prover_real_workspace_mount_is_used_when_safely_available -q` (Stage-B SL2-T3 literal GREEN for the same immutable 16-node set after only the six SL-2 production files are implemented)
- `env -i HOME="$REVIEWTRUTH_RUNNER_ROOT/home" PATH="$REVIEWTRUTH_RUNNER_ROOT/venv/bin:/usr/bin:/bin" LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH="$PWD/phase-loop-runtime/src" TMPDIR="$REVIEWTRUTH_RUNNER_ROOT/tmp" "$REVIEWTRUTH_RUNNER_ROOT/venv/bin/python" "$PWD/phase-loop-runtime/scripts/verify_reviewtruth_chronology.py" junit --mode broad-baseline --runner-root "$REVIEWTRUTH_RUNNER_ROOT" --stage-a-base "$REVIEWTRUTH_RUNNER_ROOT.stage-a-base.json" --provisioning "$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-bootstrap-provisioning.json" --observation-dir "$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-baseline-preimplementation" --observer-source "$REVIEWTRUTH_RUNNER_ROOT/materialized/reviewtruth-baseline-observer.py" --observer-sha256 841cfb8bbac1d9b4ea0bb14a1f3600165550227b680b2e5689c79c13c61b1f6d --gate-a-observation-dir "$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-gate-a-preimplementation" --gate-a-tests-root "$REVIEWTRUTH_RUNNER_ROOT/gate-a-preimplementation-input/standalone/phase-loop-runtime/tests" --gate-a-observer-source "$REVIEWTRUTH_RUNNER_ROOT/materialized/reviewtruth-gate-a-baseline-observer.py" --gate-a-observer-sha256 d51199649bf0c4a2ed3c647e210128ecd07112c5229143b976de7600943af3c9 --candidate-artifact-manifest "$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-stage-a-candidate-artifacts.json" --candidate-profile-digest "$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-stage-a-candidate-profile.sha256" --stage-a-plan-snapshot "$REVIEWTRUTH_RUNNER_ROOT/stage-a-snapshots/plans/phase-plan-v10-REVIEWTRUTH.md" --stage-a-roadmap-snapshot "$REVIEWTRUTH_RUNNER_ROOT/stage-a-snapshots/specs/phase-plans-v10.md" --stage-b-plan "$PWD/plans/phase-plan-v10-REVIEWTRUTH.md" --stage-b-plan-binding "$REVIEWTRUTH_RUNNER_ROOT/evidence/reviewtruth-stage-b-plan-binding.json" --stage-b-plan-review-dir "$REVIEWTRUTH_RUNNER_ROOT/stage-b-plan-review"` Stage-B template; it becomes operational only after the ordered review artifacts and strict binding record have been atomically staged outside the worktree
- `env REVIEWTRUTH_JUNIT_XML=.phase-loop/evidence/reviewtruth-phase-default.xml sh -c 'PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit-run --mode default-premarker --xml "$REVIEWTRUTH_JUNIT_XML"'`
- `env REVIEWTRUTH_JUNIT_XML=.phase-loop/evidence/reviewtruth-broad-default.xml sh -c 'PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration" --junitxml="$REVIEWTRUTH_JUNIT_XML"'`
- `env REVIEWTRUTH_PHASE_JUNIT_XML=.phase-loop/evidence/reviewtruth-phase-default.xml REVIEWTRUTH_BROAD_JUNIT_XML=.phase-loop/evidence/reviewtruth-broad-default.xml sh -c 'PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit --mode default-premarker --phase-xml "$REVIEWTRUTH_PHASE_JUNIT_XML" --broad-xml "$REVIEWTRUTH_BROAD_JUNIT_XML"'`
- `env PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1 REVIEWTRUTH_JUNIT_XML=.phase-loop/evidence/reviewtruth-phase-red.xml sh -c 'PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit-run --mode activated-red --xml "$REVIEWTRUTH_JUNIT_XML"'` (records pytest's expected nonzero after the XML exists and returns control without judging failures)
- `env REVIEWTRUTH_JUNIT_XML=.phase-loop/evidence/reviewtruth-phase-red.xml sh -c 'PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit --mode activated-red --phase-xml "$REVIEWTRUTH_JUNIT_XML"'`
- `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_advisor_board_golden.py -q`

After the immutable eleven-path tests-only landing and before any SL-2 implementation edit, SL2-T1
must consume the frozen degraded-seat compatibility node RED by running the first command below.
It must fail at exactly `REVIEWTRUTH_RED::seat_outcome_degraded_strict_roundtrip`, with the
nodeid/base/tree/output retained in the RED record. After SL2-T2 installs the marker and changes
only its six owned files, the second command runs the same immutable node without forced
activation and must be GREEN. The node literally covers append → strict read → rewrite → strict
reread for `degraded=true`; exact present-`true` and present-`false` reconstruction; legacy
absent-field → `False`; exact byte-neutral default serialization; conditional true-only emission;
known-key string `"false"` and integer `1` rejection through the existing
malformed-record/`ProvenanceInvalid` path before construction or rewrite; and continued strict
unknown-field rejection:

- `env PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_reviewtruth_phase.py::test_reviewtruth_sl2_seat_outcome_degraded_true_survives_append_strict_read_rewrite_strict_reread -q` (SL2-T1 expected RED before any SL-2 edit)
- `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_reviewtruth_phase.py::test_reviewtruth_sl2_seat_outcome_degraded_true_survives_append_strict_read_rewrite_strict_reread -q` (SL2-T3 required GREEN after marker-driven implementation)

After SL-5 is complete, every pushed implementation candidate, panel attempt, and merge decision executes these command bullets from top to bottom in exact order from a fresh exact-head process:

- `env REVIEWTRUTH_JUNIT_XML=.phase-loop/evidence/reviewtruth-phase-candidate.xml sh -c 'PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit-run --mode candidate --xml "$REVIEWTRUTH_JUNIT_XML"'`
- `env REVIEWTRUTH_JUNIT_XML=.phase-loop/evidence/reviewtruth-broad-candidate.xml sh -c 'PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration" --junitxml="$REVIEWTRUTH_JUNIT_XML"'`
- `env REVIEWTRUTH_PHASE_JUNIT_XML=.phase-loop/evidence/reviewtruth-phase-candidate.xml REVIEWTRUTH_BROAD_JUNIT_XML=.phase-loop/evidence/reviewtruth-broad-candidate.xml sh -c 'PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/verify_reviewtruth_chronology.py junit --mode candidate --phase-xml "$REVIEWTRUTH_PHASE_JUNIT_XML" --broad-xml "$REVIEWTRUTH_BROAD_JUNIT_XML"'`
- `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration"`
- `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_advisor_board_golden.py -q`

The broad and plain suite commands leave `PHASE_LOOP_REVIEWTRUTH_POST_PARSER_COLLECTION` unset and require the Stage-B-frozen source/CI collection, plugin, skip, and deselection profile. Only after all five commands and required GitHub CI across Python 3.10/3.11/3.12 are GREEN at the same exact pushed head may implementation review start. That review is not one simultaneous legacy panel: the coordinator first runs the serial isolated Codex `can_probe` leg and stages its exact evidence digest, then dispatches critics including GPT-5.6 Sol against that bundle, then obtains a usable grounded artifact-bound Fable `binding_prover` review. Gemini and Grok may remain critics, but Grok cannot be the write leg except after typed Codex preflight failure plus OS confinement. Any contradiction or material finding invalidates earlier `AGREE`, changes the bundle/head as applicable, and restarts the ordered proof and review. No direct `claude -p` is permitted.

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

Candidate phase-selected JUnit uses the frozen non-wrapper phase set and requires zero phase skips; final phase-selected JUnit uses the full expected set, including both new infrastructure disposition falsifiers, runs every strict wrapper exactly once after broad-final attestation, and requires zero phase skips or deselections. Candidate and final broad JUnit require exact equality to the frozen source/CI post-SL-1 full/selected collections, the allowed source/CI behavioral collection-plugin/root profile, exactly the unchanged marker-filter deselection baseline plus exactly the five hook-owned wrappers as disjoint categories, and exactly the unchanged semantic source/CI pre-implementation skip baseline after independently validating and separating PC-REVIEWTRUTH-5A, PC-REVIEWTRUTH-5B, and PC-REVIEWTRUTH-5C; they retain each disposition's raw evidence, reject new, missing, external, arbitrary, category-swapped, plugin-origin-drifted, collection-drifted, malformed/unattributed PyPI, malformed/unattributed console-script, second-network-node, second-console-node, wrong-profile console normalization, or otherwise changed skip/deselection accounting, and do not require or claim five total deselections, whole-suite zero skips, or live internet. The frontmatter suite command and explicitly amended GitHub CI also use that normalized source/CI profile and must collect all three exact disposition nodes once on Python 3.10, 3.11, and 3.12. The sole normative clean-room Gate A command explicitly unsets both `PHASE_LOOP_SKIP_GATE_A_SUITE` and final collection activation, supplies the fresh external `PHASE_LOOP_GATE_A_INPUT_COPY_ROOT`, and requires the reducer to reject either selector when invoked without that sanitization. The reducer runs the SL-5-owned script under trace and emits write-once stdout/stderr, machine-checkable suite-count/profile/sentinel JSON, and a fresh-child attestation. Gate A is GREEN only when the script's temporary cleanup is complete, the neutral sealed evidence copy still exists, and that fresh process independently proves the full temporary standalone pytest tree actually executed once under exact `-q -p no:cacheprovider -m "not dotfiles_integration"` and equals the separately frozen Gate-A profile: `input-copy/tests/**` and `input-copy/tests/conftest.py` match the executed and committed tests, `input-copy/chronology-parser/verify_reviewtruth_chronology.py` matches HEAD, neither the temporary tree nor the external copy contains `phase-loop-runtime/scripts/`, sibling `phase-loop-skills/` and `skills-src/` are absent, full/selected sets equal the source/CI sets minus exactly the 48 unmarked nodeids from the four named collection-skipped modules, collection skips equal the restricted source collection baseline UNION the exact four boundary tuples, runtime skips equal the restricted source runtime baseline UNION all 59 boundary tuples including the exact line-111 `test_release_pin_autotrack.py` standalone/root-missing skip, their disjoint union equals the frozen 102-tuple expected set, marker filtering and the five hook deselections remain exact and disjoint over the retained collection, all PC-REVIEWTRUTH-5A/5B/5C normalization is forbidden, at least one test executed, the terminal outcome has no failures/errors, and the SKIPPED sentinel is absent after the ordered start sentinel and before the GREEN sentinel. Missing/extra boundary skips, source/CI-profile substitution, unrelated nodeid loss, copied-byte or retained-behavior drift, parser omission/misnamespace, cleanup before attestation, producer-hash substitution, network or console-script normalization, or unexpected sibling presence fails. Every environment still emits pytest/pluggy interpreter, distribution version, module/distribution path, module/file digest, and approved core-plugin provenance for complete self-consistent diagnostics, but the reducers ignore raw differences in those fields unless they coincide with an applicable semantic-profile or behavior mismatch. All suites remain GREEN without bootstrap run-local evidence on fresh clones. The post-parser finalized record, its `final-record` attestation, and the later Gate A artifacts are never consumed by any test wrapper; the finalized record deliberately excludes Gate A, records the broad-final/final raw and semantic PC-REVIEWTRUTH-5A/5B/5C evidence before its separate attestation, and the four-seat closeout review plus canonical ledger closeout bind that finalized-record attestation and the unchanged terminal Gate A attestation without creating a cycle.

## Acceptance Criteria

Every criterion first inherits the Stage-A/Stage-B lifecycle. This Stage-A plan authorizes only dependency-complete reanchor observation and immutable external snapshot creation. The reviewed Stage-B plan must freeze the exact base/profile, complete candidate-artifact manifest over the frozen Stage-A plan and roadmap snapshots, domain-separated candidate-profile digest, and a separate exact reviewed digest for the revised live Stage-B plan, and supply the independently executable SL0-T3 proof for all three exact `agent-harness#398` directives, the non-authorizing `agent-harness#405` tracker, an effective `pull_request` rule and canonical response digest, and separate two-parent record landing. The Stage-B plan must not equal the Stage-A plan snapshot. No historical constant, predecessor panel, wrapper, future parser, or manual inspection can substitute.

Every criterion first also inherits the authenticated dependency-completion boundary. Stage A must reject any noncanonical or rewritten origin before fetch, reject identical or arbitrary ancestor values, and derive each exact audited implementation `M` only from a distinct supplied completion-control `F` whose topology is `[M,FH]`. Its private sidecar binds canonical fetch/push origin plus both `F`/`M`/`FH` triples. Stage B and the later chronology parser must independently reauthenticate origin, refetch main, replay the same topology, manifest-only, strict-event, plan/roadmap, evidence/panel, and Fable/Sol checks, and require their binding record to preserve both `F` and `M` identities. A mismatch cannot be normalized into a new base or waived by a successful observation.

Every criterion also inherits PC-REVIEWTRUTH-2's paired observations. Stage A atomically snapshots
the exact live Stage-A plan and unchanged roadmap into private external mode-`0600` files, proves
each snapshot immediately equal by bytes and SHA-256 to its regular canonical live source, seals
the candidate profile only as one raw Gate-A artifact inside the complete direct-file manifest,
enumerates the snapshots only under explicit `repository-stage-a/` identities, immediately
regenerates and byte-compares that manifest, and seals/re-verifies the exact-base-plus-manifest
candidate digest. Stage B freezes those exact observed values and artifact bytes, reviews them in
directive order, and independently rebuilds the manifest and digest from the frozen external
snapshots and other current candidate files in a fresh process before SL-0 or SL-1. Separately it
requires the revised live plan digest and atomically staged review artifacts to equal the strict
external Stage-B binding record and the same exact digest bound by the REVIEWTRUTH manifest row,
early evidence, bundle, and ordered panel; it never embeds a self-digest literal, substitutes the
live plan for the Stage-A snapshot, or requires them equal. Any missing, extra, or drifted file, relative
identity, mode, byte count, SHA-256, manifest byte, digest format/value, upstream Stage-A binding,
or separate Stage-B plan/review binding fails. The historical
`4251/3650`, `4203/3602`, `601/601`, `48`, and `39 + 4 + 59 = 102` values cannot satisfy this
prerequisite. After parser authorship, the Stage-B sixth command independently consumes both
directories, both immutable Stage-A snapshots, the frozen manifest and candidate digest, and the
separately reviewed live Stage-B plan plus its strict external binding record before implementation
mutation.

Every criterion also inherits the literal two-node infrastructure TDD sequence. After the fifth
operational command and before the sixth, the exact PyPI and console-script falsifiers must fail in
the displayed order at their distinct RED anchors, then pass in that same order only after both
PC-REVIEWTRUTH-5B/5C parser/conftest contracts are implemented. The frozen pair has count `2` and
sorted-LF SHA-256 `ad528b11ad08a3989aee135fcaf6fc5449d00da8188a074c5a126712924e2758`.
No broad-baseline parse, later reconstruction, live network, PATH mutation, or external command
installation can substitute for those four retained results.

Every criterion also inherits PC-REVIEWTRUTH-8's literal 16-node TDD sequence. The exact set has
count `16`, sorted-LF SHA-256 `c54d268bafd176e0d22c179eac2a175f208eb2c28f73027982d9c7780dc2219a`,
and exact anchor digest `8d175395fd67f2a9297a5b8fdb06f57bfa8595a268746a165ab9878d4d371e05`.
All 16 run RED at only their mapped anchors before any of the six SL-2 production files changes;
the identical set runs GREEN afterward. Those unchanged nodes require both
`sandbox_workspace_write.exclude_tmpdir_env_var=true` and
`sandbox_workspace_write.exclude_slash_tmp=true` in policy, argv/effective preflight,
effective-config receipt, and launch/no-launch receipt; require launch `TMPDIR` canonical inside the
already-authorized worktree/data scope; prove worktree and nested-`TMPDIR` positive writes; and
reject `/tmp`, external-`TMPDIR`, live-tree, and shared-data authority plus either missing/false
exclusion or any receipt substitution. They also require the coordinator-selected explicit
`workspace_mount` preflight/pass-through and zero launch on any mount failure, with a `tmp_path`
custom-mount positive and a real `/mnt/workspace` positive only when the identical safety preflight
passes. No aggregate count/digest is accepted until Stage B
mechanically incorporates those nodes, and the parameterized `required_prover=false` override
remains valid without weakening the confinement required for any attempted launch.

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
- [ ] EC-REVIEWTRUTH-16 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k ec_reviewtruth_16`
- [ ] EC-REVIEWTRUTH-17 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_reviewtruth_phase.py::test_review_wave_plan_design_allows_critics_first_but_requires_early_probe_before_fable phase-loop-runtime/tests/test_reviewtruth_phase.py::test_review_wave_premerge_release_stages_early_prover_evidence_before_critics phase-loop-runtime/tests/test_reviewtruth_phase.py::test_review_wave_capabilities_distinguish_can_probe_from_binding_prover phase-loop-runtime/tests/test_reviewtruth_phase.py::test_review_wave_bundle_binds_input_head_bundle_and_evidence_digests phase-loop-runtime/tests/test_reviewtruth_phase.py::test_review_wave_contradicting_prover_invalidates_agree_and_requires_updated_bundle_rereview phase-loop-runtime/tests/test_reviewtruth_phase.py::test_review_wave_unconfined_grok_records_degraded_evidence_without_launch phase-loop-runtime/tests/test_reviewtruth_phase.py::test_review_wave_gemini_is_never_selected_as_write_capable_prover phase-loop-runtime/tests/test_reviewtruth_phase.py::test_review_wave_predecessor_critic_artifacts_do_not_count_before_early_codex_evidence phase-loop-runtime/tests/test_phase_worktree_executor.py::test_early_prover_codex_uses_cli_workspace_write_in_per_leg_ephemeral_worktree phase-loop-runtime/tests/test_phase_worktree_executor.py::test_early_prover_serial_holder_gets_distinct_data_scope_and_exact_digest_binding phase-loop-runtime/tests/test_phase_worktree_executor.py::test_early_prover_external_reaper_cleans_crash_residue_without_leg_authority phase-loop-runtime/tests/test_phase_worktree_executor.py::test_early_prover_codex_external_tool_policy_and_effective_preflight_fail_closed phase-loop-runtime/tests/test_phase_worktree_executor.py::test_early_prover_external_tool_policy_preflight_and_receipt_are_digest_bound phase-loop-runtime/tests/test_phase_worktree_executor.py::test_early_prover_coordinator_rejects_unusable_workspace_mount_before_leg_launch phase-loop-runtime/tests/test_phase_worktree_executor.py::test_early_prover_custom_writable_workspace_mount_flows_through_worktree_creation phase-loop-runtime/tests/test_phase_worktree_executor.py::test_early_prover_real_workspace_mount_is_used_when_safely_available -q`; exactly those 16 PC-REVIEWTRUTH-8 nodes run, with node-set SHA-256 `c54d268bafd176e0d22c179eac2a175f208eb2c28f73027982d9c7780dc2219a`, and the retained pre-implementation run must have failed only at the exact anchor set SHA-256 `8d175395fd67f2a9297a5b8fdb06f57bfa8595a268746a165ab9878d4d371e05`. The mount nodes must prove explicit coordinator preflight/pass-through, zero launch on every unusable root, a coordinator-created `tmp_path` custom mount, and the real `/mnt/workspace` path only when the same safety preflight passes.
- [ ] Plan-internal degraded-seat trust-root compatibility — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_reviewtruth_phase.py::test_reviewtruth_sl2_seat_outcome_degraded_true_survives_append_strict_read_rewrite_strict_reread -q`; the same immutable node must first have been retained RED under the forced-activation command before any SL-2 edit, and GREEN must prove present true/false exact reconstruction, true append/read/rewrite/reread preservation, absent legacy false, exact default bytes, true-only key emission, known-key string `"false"` and integer `1` rejection before construction/rewrite, and unchanged unknown-field rejection.
- [ ] Plan-internal source-layout console-script portability — proven by `env PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_reviewtruth_phase.py::test_reviewtruth_exact_console_script_availability_disposition_normalizes_only_source_layout_skip -q`; its retained RED precedes both classifier GREEN runs, and GREEN proves exact source-layout unavailability plus raw provenance retention while rejecting wrong reason/path/line/source/AST/interpreter/sibling/module-origin/CI, present sibling, package-installed/bootstrap/CI/Gate-A normalization, failure/error/xfail, missing/duplicate node, and any second console-normalized node without a live command dependency.
