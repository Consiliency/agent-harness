---
phase_loop_plan_version: 1
phase: HARDEN
roadmap: specs/phase-plans-v10.md
roadmap_sha256: b26b4fd76efb7882578eae5e102fd577b26e66f590a531d3b3a738d840e5106e
automation:
  # The manifest contract seal binds the pure-control topology independently
  # of the separately recomputed current plan digest.
  suite_command:
    - bash
    - -lc
    - >-
      set -euo pipefail;
      harden_junit="${PHASE_LOOP_RUN_DIR:+$PHASE_LOOP_RUN_DIR/harden-compatible-suite.xml}";
      pure_name="${PHASE_LOOP_HARDEN_PURE_JUNIT:-harden-pure-control-bootstrap.xml}";
      pure_junit="${PHASE_LOOP_RUN_DIR:+$PHASE_LOOP_RUN_DIR/$pure_name}";
      if [[ -z "$harden_junit" ]]; then harden_junit="$(mktemp "${TMPDIR:-/tmp}/harden-bootstrap-suite.XXXXXX.xml")"; fi;
      if [[ -z "$pure_junit" ]]; then pure_junit="$(mktemp "${TMPDIR:-/tmp}/harden-bootstrap-pure.XXXXXX.xml")"; fi;
      [[ "$harden_junit" != "$pure_junit" ]];
      PYTHONPATH=phase-loop-runtime/src python3 -c 'import hashlib, json; from pathlib import Path; from phase_loop_runtime.plan_manifest import validate_manifest; p = Path("plans").joinpath("manifest.json"); plan_file = Path("plans").joinpath("phase-plan-v10-HARDEN.md"); roadmap_file = Path("specs").joinpath("phase-plans-v10.md"); v = validate_manifest(p); assert v.valid, "; ".join(v.errors); doc = json.loads(p.read_text()); rows = [r for r in doc["plans"] if r.get("slug") == "v10-HARDEN" or r.get("file") == plan_file.as_posix() or r.get("phase_alias") == "HARDEN"]; assert len(rows) == 1; r = rows[0]; events = r.get("lifecycle"); bearing = [e for e in events if isinstance(e, dict) and isinstance(e.get("metadata"), dict) and ("harden_plan_contract" in e["metadata"] or "harden_plan_contract_record_id" in e["metadata"])]; assert len(bearing) == 1; metadata = bearing[0]["metadata"]; assert metadata.get("harden_plan_contract_record_id") == "v10-HARDEN.harden-plan-contract.v1"; c = metadata.get("harden_plan_contract"); payload = {k: value for k, value in c.items() if k != "plan_sha256"}; assert hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest() == "79c4bb52ebe25573c6d4eb98da1fc8ca0a90c2caea3a58badd8204577c061908"; assert c["plan_sha256"] == hashlib.sha256(plan_file.read_bytes()).hexdigest(); assert c["roadmap_sha256"] == hashlib.sha256(roadmap_file.read_bytes()).hexdigest() == "b26b4fd76efb7882578eae5e102fd577b26e66f590a531d3b3a738d840e5106e"; assert (c["expected_nodeids"], c["sl1_nodeids"], c["sl2_nodeids"], c["sl3_evidence_nodeids"], c["default_skip_nodeids"], c["nodeid_delta"], c["nodeid_inventory_sha256"]) == (126, 115, 7, 4, 21, 104, "6b642b3a4a7f22b51c41c5a84383a09833b8af0c57e1a10e9c97cd2e3c623728"); assert (c["public_board_execution_nodeids"], c["public_board_pure_control_nodeids"], c["public_board_execution_pure_overlap_nodeids"], c["public_board_callers"], c["public_board_pure_only_nodeids"]) == (100, 54, 20, 134, 34); assert c["public_board_execution_pure_overlap_nodeids_sha256"] == "3ce722d31e283cd455b3c7d23ed3d755e076e0fd09402518fbe9c10ba11488d6"; assert (c["pure_control_proof_mode"], c["pure_control_junit_contract"]) == ("PHASE_LOOP_HARDEN_PROOF_MODE=pure_control", "distinct_from_focused_and_broad"); assert c["pure_control_proof_stages"] == ["preimplementation_red", "checkpoint_c", "prepush_i", "candidate_i", "canonical_m"]';
      PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration" --junitxml="$harden_junit";
      env -u PHASE_LOOP_TDD_EXPECT_HARDEN PHASE_LOOP_HARDEN_PROOF_MODE=pure_control PURE_JUNIT="$pure_junit" PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -c 'import hashlib, os, subprocess, sys; from harden_tdd_guard import EXPECTED_PHASE_NODEIDS, PUBLIC_BOARD_EXECUTION_NODEIDS, PURE_CONTROL_NODEIDS, EXECUTION_PURE_OVERLAP_NODEIDS, PUBLIC_BOARD_CALLER_NODEIDS; digest = lambda xs: hashlib.sha256((chr(10).join(xs) + chr(10)).encode()).hexdigest(); assert (len(PUBLIC_BOARD_EXECUTION_NODEIDS), len(PURE_CONTROL_NODEIDS), len(EXECUTION_PURE_OVERLAP_NODEIDS), len(PUBLIC_BOARD_CALLER_NODEIDS)) == (100, 54, 20, 134); assert len(set(PURE_CONTROL_NODEIDS) - set(EXPECTED_PHASE_NODEIDS)) == 34; assert set(PUBLIC_BOARD_EXECUTION_NODEIDS) & set(PURE_CONTROL_NODEIDS) == set(EXECUTION_PURE_OVERLAP_NODEIDS); assert set(PUBLIC_BOARD_EXECUTION_NODEIDS) | set(PURE_CONTROL_NODEIDS) == set(PUBLIC_BOARD_CALLER_NODEIDS); assert set(PURE_CONTROL_NODEIDS) & set(EXPECTED_PHASE_NODEIDS) == set(EXECUTION_PURE_OVERLAP_NODEIDS); assert all(len(xs) == len(set(xs)) and tuple(xs) == tuple(sorted(xs)) for xs in (PUBLIC_BOARD_EXECUTION_NODEIDS, PURE_CONTROL_NODEIDS, EXECUTION_PURE_OVERLAP_NODEIDS, PUBLIC_BOARD_CALLER_NODEIDS)); assert digest(PUBLIC_BOARD_EXECUTION_NODEIDS) == "90e36e87f2d93504c63bfefd850bdceb9c3cc869f62c7969b5815e2e49950ac7"; assert digest(PURE_CONTROL_NODEIDS) == "7d4b4f994f04b0926d0318fd5d7d983c0a81488d171c0755e94d9b1c8b66eef4"; assert digest(EXECUTION_PURE_OVERLAP_NODEIDS) == "3ce722d31e283cd455b3c7d23ed3d755e076e0fd09402518fbe9c10ba11488d6"; assert digest(PUBLIC_BOARD_CALLER_NODEIDS) == "cecbef4c0f550f16a0e5e033be9d88216dcd7a8b9d127f6c91c920cd2359bb6e"; raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", *PURE_CONTROL_NODEIDS, "-q", "--junitxml=" + os.environ["PURE_JUNIT"]]))'
---

# HARDEN: Isolation and Verification Hardening

## Context

HARDEN closes the reachable review-isolation and verification gaps tracked by
`Consiliency/agent-harness#259`, `Consiliency/agent-harness#248`,
`Consiliency/agent-harness#264`, `Consiliency/agent-harness#246`, and
`Consiliency/agent-harness#241`. Live source inspection at
`9a7df7cafa651c20a9a6322e8eeaea4648de072b` confirms that review staging preserves
symlinks, every CLI launch still inherits `wrapped_cwd=str(request.repo)`,
review workflow text can contain live absolute paths, and
`child_executor_env` preserves the ambient environment except for Claude
self-markers. The product capability registry currently exposes sixteen
product-loop review cells: codex; Claude print, Channel, and Agent View across
solo, subagent, and agent-team modes; gemini/agy; grok; opencode; pi; command;
and manual/nonlaunch. The complete live review surface is larger: Advisor Board
adds registered homebrew and Omnigent harness lanes, subscription and opted-in
API-key auth lanes, native-host execution, and optional scoped-research routes.
The isolation checklist therefore derives normalized route identities from the
live product and advisor registries instead of treating the sixteen product
cells or the coordinated run's subscription-only panel as the whole fleet.

The roadmap prescribes two functional implementation lanes. `SL-0` is the
literal panelled RED test-only landing required by `EC-HARDEN-0`; `SL-1` and
`SL-2` are the two roadmap-owned functional lanes; and `SL-3` owns the HARDEN
evidence executable, documentation reduction, and read-only landing lifecycle.
The already-installed external v10 coordinator is the immutable bootstrap
boundary. Before dispatch it records the resolved `codex-phase-loop` console
script, installed `phase_loop_runtime` package root, version, Git identity when
available, file SHA-256 values, PID, and start nonce, and proves that this
installation is outside the HARDEN worktree. It launches the pre-change runtime
with `--closeout-mode manual`, rejects any terminal `complete` that runtime
writes after loaded runner/reducer bytes change, and alone owns candidate
commit, push, false-closeout reopening, process termination, fresh repo-local
launch, and merge. Neither the implementation child nor the already-loaded
pre-change runtime may author transition evidence or attest the candidate.

`plans/manifest.json` is a runner-owned lifecycle-control path outside every
HARDEN lane and outside the immutable 46/26/18 phase/test/checkpoint path sets.
This repaired planning package normalizes every current manifest row to the
exact sixteen-key shape emitted by `plan_manifest._entry_to_json()`: the sole
pre-repair exception, `v10-PROOFGATE`, receives only
`acceptance_criteria_count: null` and `task_summary: null`, with no lifecycle or
semantic change. That one-time normalization is part of the planning package,
not lifecycle-control PR `L` or `F`. Before dispatch, the coordinator requires
the frozen manifest pre-image to survive
`_manifest_to_json(read_manifest(repo))` with exact parsed row equality and
uses the real `update_lifecycle()` on a disposable copy to simulate the exact
`committed -> executing -> completed` HARDEN sequence. Each simulated step must
change only the API-defined HARDEN fields and must leave every parsed sibling
row exactly equal; any shape, optional-field, key, or value drift blocks before
`SL-0`.
After plan validation and before any `SL-0` write, the installed executor must
perform its normal
`update_lifecycle(repo, "v10-HARDEN", "executing", "codex-execute-phase",
{"run_id": <run-id>, "phase_alias": "HARDEN"})` call. The external coordinator
freezes the pre-image and permits exactly the API-defined delta: the unique
HARDEN row changes `status` from `committed` to `executing`, `updated_at`
equals the new event's `at`, and one `executing` event with that exact writer
and run identity is appended; every prior lifecycle event, immutable contract
record, unrelated row, and other field remains equal. While that delta is
unlanded, `plans/manifest.json` must be the only Git-visible dirty path and no
lane work may start. The coordinator commits it alone on a distinct control
branch, lands it through a manifest-only two-parent control PR, records the
server merge as `L`, fetches the exact post-`L` target, and proves the worktree
clean before the tests-only branch is created. A missing append, direct edit,
second append, wrong transition/writer/run identity, extra manifest change,
other dirty path, or failure to land `L` blocks before `SL-0`.

The immutable contract is not the latest lifecycle state. Its committed event
is located by metadata identity
`v10-HARDEN.harden-plan-contract.v1`; the lookup treats every event carrying
either that identity or `harden_plan_contract` as contract-bearing and requires
exactly one such event. Missing, duplicate, identity-conflicting, malformed, or
payload-drifted records fail closed. The frontmatter suite and the ordinary
manifest verification command use the byte-identical lookup and seal the
contract payload independently of mutable lifecycle status. A normal terminal
`completed` append, if reached after the exact-`M` final audit, is handled by
the same control-only rule on a distinct branch: the coordinator lands a
manifest-only two-parent closeout PR as `F`, proves `M..F` is exactly the
API-defined `executing -> completed` delta and that every runtime/code blob is
unchanged, and only then permits terminal `complete`. A failed execution stops
outside the successful `F` chronology and cannot claim completion.

That already-planned `F` now carries the same strict producer contract consumed by REVIEWTRUTH. Only after the fresh exact-`M` post-landing replay and final evidence reduction pass may the executor produce the receipt-bearing exact-`M` review wave and append one strict `completed` event to the unique `v10-HARDEN` manifest row in a separate clean control worktree rooted at `M`. The event uses the existing `update_lifecycle` four-key envelope `at`, `by`, `metadata`, and `transition`; its sole contract payload is `metadata.phase_completion_landing`, whose exact key set is `audited_implementation_landing`, `audited_implementation_tree`, `canonical_origin`, `canonical_ref`, `final_audit`, `final_evidence`, `phase_alias`, `plan_sha256`, `review_wave`, `roadmap_sha256`, `run_id`, and `schema`. `schema="v10.phase-completion-landing.v1"`; `phase_alias="HARDEN"`; the plan and roadmap digests name the exact blobs at `M`; `canonical_origin="Consiliency/agent-harness"`; `canonical_ref="refs/remotes/origin/main"`; and `audited_implementation_landing=M`. `final_audit` and `final_evidence` are exact retained file references and equal `review_wave.receipt.base.final_audit` and `.final_evidence`; `review_wave` is the payload's only review evidence.

`review_wave` has exactly `schema`, `canonical_json`, `receipt`, and `receipt_sha256`; `schema="v10.review-wave-receipt.v1"`; and `canonical_json="utf8-sorted-keys-compact-lf.v1"`. Canonical bytes are UTF-8 JSON with duplicate keys, floats, NaN/Infinity, and surrogate code points rejected, keys sorted bytewise, separators exactly `,` and `:`, no insignificant whitespace, and one terminal LF. `receipt_sha256` is the recomputed lowercase SHA-256 of only the canonical `receipt` bytes. `receipt` has exactly `attempt`, `base`, `bundle_staging`, `completed_at`, `early_prover`, `effective_policy`, `evidence_root_id`, `gate`, `phase_alias`, `restart_chain`, `seats`, and `wave_id`; every time is fixed-width UTC RFC3339 with six fractional digits and `Z` and is compared as a parsed instant. `base` has exactly `commit`, `tree`, `plan_sha256`, `roadmap_sha256`, `final_audit`, and `final_evidence` and binds the audited exact-`M` commit/tree and plan/roadmap bytes. The wrapper, its parent event, `FH`, `F`, and the receipt itself are absent from the hashed receipt bytes and from every retained reference, so the producer graph is acyclic and neither event nor receipt self-references.

The producer retains beneath the immutable coordinator-supplied canonical evidence root for the matching `evidence_root_id` the exact final-audit and final-evidence bytes, every early/seat execution attestation, rendered prompt, and native result, every canonical reducer artifact embedding exact raw review text, the canonical bundle, early receipt, every seat receipt, the complete restart-chain records, and the typed policy resolver input/output bytes. Every retained file reference has exactly `path`, `bytes`, and `sha256`; its path is a nonempty normalized immutable UTF-8 relative locator with no absolute form, backslash, empty segment, `.`/`..` segment, or symlink at any ancestor. Before append, the producer opens each reference without following symlinks, proves that it resolves beneath that evidence root to a coordinator-owned regular file that is not group/other-writable, reads and retains the bytes, and closes every descriptor. From those retained bytes—not wrapper booleans or reviewer summaries—it independently recomputes path containment, integer byte counts, lowercase SHA-256 values, strict canonical JSON, common base and bundle equality, producer identities, prompt-bound lens/seat/bundle facts, native citations and total status/outcome mapping, parsed chronology, roles, complete restart semantics, and the effective typed parameterized policy. Composition/auth preflight writes each execution attestation and binds the distinct rendered prompt before launch; the worktree executor, invoker, or native-fill binder writes each native result after termination; only afterward may a separate reducer create an artifact, and that reducer cannot create or rewrite any producer or prompt record.

`early_prover` has exactly `artifact`, `binding_prover`, `capability`, `completed_at`, `outcome`, `receipt`, `role`, `seat`, `started_at`, `usable`, and `vendor`; those values derive from strict canonical `v10.review-early-prover-artifact.v1`, its distinct prelaunch `v10.review-early-prover-execution-attestation.v1`, distinct rendered prompt, and distinct post-termination `v10.review-early-prover-native-result.v1`. The artifact exact keys and producer schemas are those frozen by REVIEWTRUTH: preflight supplies Codex identity plus `role="early_prover"`, `capability="can_probe"`, and `binding_prover=false`; the rendered prompt binds the live-probe lens, seat instance, output citation grammar, and both required final-artifact refs; the native result supplies status, exact raw probe report, start/completion instants, unique native identity, and canonical `EVIDENCE_REF` citations exactly equal to both final artifacts; and only a substantive non-elided grounded report ending with exact `PROBE_STATUS: CLEAR` derives usable `outcome="CLEAR"`. Opaque/self-authored artifacts, reducer-only grounding, padded terminal tokens, embedded elision, absent/swapped/aliased prompt or producer records, missing/wrong prompt markers or native citations, or any mirror disagreement fail. Its strict canonical receipt mirrors only those derived facts plus the same phase/wave/attempt/base. `bundle_staging` has exactly `bundle`, `early_artifact`, `early_receipt`, and `staged_at`; both early references equal the `early_prover` references exactly, and `early_prover.completed_at < bundle_staging.staged_at`. The referenced bundle is canonical `v10.review-evidence-bundle.v1` JSON with exactly `schema`, `base`, and sorted unique `entries`; its `base` equals the receipt base and its direct entries include the exact final-audit, final-evidence, early-receipt, early-artifact, early-execution-attestation, early-rendered-prompt, and early-native-result references. It contains no receipt or bundle self-digest. The early Codex CLEAR is therefore staged into this exact sole evidence-bearing Option-2 bundle before any critic starts; every critic and Fable consumes only that same bundle plus its read-only referenced bytes by reference, with no arbitrary working-tree or shared-development-database execution.

`seats` is the fixed roadmap-specific ordered four-entry array for Grok, GPT-5.6 Sol, Gemini, and Fable. Each strict entry has exactly `artifact`, `binding_prover`, `capability`, `completed_at`, `consumed_bundle`, `counts_toward_floor`, `lens`, `material_findings`, `outcome`, `position`, `receipt`, `role`, `seat`, `started_at`, `usable`, `vendor`, and `verdict`; its reducer `v10.review-seat-artifact.v1` has exactly `attempt`, `base`, `binding_prover`, `capability`, `completed_at`, `consumed_bundle`, `effort`, `execution_attestation`, `grounding`, `harness`, `lens`, `material_findings`, `model`, `native_result`, `outcome`, `phase_alias`, `position`, `rendered_prompt`, `review_text`, `role`, `schema`, `seat`, `seat_instance_id`, `started_at`, `status`, `vendor`, and `wave_id`. Each artifact references a distinct immutable prelaunch `v10.review-seat-execution-attestation.v1`, rendered prompt, and post-termination `v10.review-seat-native-result.v1`. The producer derives roster/model/role/capability/binding from preflight; counts the lens only after the prompt bytes contain the exact lens/seat/bundle/output-grammar/required-evidence markers; derives status, exact raw text, bundle, chronology, and unique native identity from the invoker/native-binder record; maps `OK`, `UNAVAILABLE`, `ERROR`, `TIMEOUT`, `REFUSED`, `CAPPED`, and `EMPTY` one-to-one onto the seven typed outcomes; and derives grounding only from canonical native `EVIDENCE_REF` lines exactly naming both final artifacts. The reducer must mirror all of those facts before verdict, substance, findings, usability, and floor eligibility are derived. The last nonempty line must full-match only `AGREE`, `PARTIALLY AGREE`, or `DISAGREE` after the optional exact `VERDICT:` label and formatting trim. Prefix/suffix verdicts, any embedded `[elided]`, `<elided>`, standalone `...`, or `elided`/`omitted` marker, zero-byte/noncanonical or self-authored artifacts, reducer-only grounding, missing/wrong prompt markers or native citations, missing/swapped/aliased prompt or producer records, empty/verdict-only or ungrounded reviews, duplicate seat/native identities, and outer producer/identity/outcome/verdict/vendor/lens/capability/text/status/chronology/bundle substitutions fail before append. The canonical receipt mirrors only those independently derived values plus the same phase/wave/attempt/base. Positions 1 through 3 are critics with `binding_prover=false`; position 4 is Fable, the only `role="binding_prover"` and only `binding_prover=true`, and its native start instant is strictly after every critic completion instant. Every counting critic and Fable starts strictly after bundle staging and derives `consumed_bundle` exactly equal to `bundle_staging.bundle`. Any finding or contradiction invalidates every AGREE in that attempt and restarts the full early-prover/critics/Fable wave with a changed bundle; no seat result carries forward, and `restart_chain` must completely bind every superseded attempt and its reason before the final finding-free, contradiction-free authorizing attempt. The producer tests must include padded elision, artifact-only vote manufacture, reducer-only grounding, omitted prompt lens markers, and cross-class status/outcome relabeling as literal RED-before-implementation mutations without adding new policy constants or changing `PANEL_LEGS`.

`effective_policy` has exactly `consensus`, `gate`, `on_shortfall`, `required_lens_coverage`, `required_prover`, `required_vendors`, `resolver_input`, and `resolver_output`. For this plan the effective roadmap facts are the fixed seat order above, `gate="pre-merge-CR"`, the shipped defaults `required_vendors=3`, `required_lens_coverage=3`, and `required_prover=true`, GPT-5.6 Sol and Fable each deriving `outcome="reviewed"`, `usable=true`, and `verdict="AGREE"`, and Fable alone supplying the prover fact. They are derived by re-hashing and strictly parsing the retained resolver plus the full execution-attestation/rendered-prompt/native-result/artifact chain, cross-checking the mirrored receipts, and re-running the typed resolver, not hardcoded as runtime-policy constants or trusted from receipt assertions. The shared policy machinery remains parameterized for all four gates; the shipped plan-ratify, design-ratify, pre-merge-CR, and release-dispatch defaults remain 3/3/true, and a valid explicit boolean `required_prover=false` override removes only the prover shortfall. `PANEL_LEGS` and all non-review goldens remain unchanged.

Prompt-marker families must have exactly the expected members, so an extra conflicting lens, seat, bundle, output-grammar, or required-evidence marker fails even when the expected marker remains present. Native `EVIDENCE_REF` lines establish grounding but are removed before the substantive-content floor is measured; a citation-only probe or review cannot count. The sorted native citation list must equal exactly the two staged final-artifact references, so a third valid bundled citation also fails.

Only after all descriptors are closed and every independent recomputation above succeeds may the strict event be appended. It is the only event carrying this schema anywhere in the row, has `transition=completed`, preserves the prior lifecycle as an exact prefix, uses the same executor writer as the unique executing event, carries the same nonempty `metadata.phase_completion_landing.run_id` as that executing event's `metadata.run_id`, has `at` strictly after the validated `review_wave.receipt.completed_at`, and makes row `status=completed` and `updated_at=at`. It is absent at `M`; no field or retained byte object may name `FH`, `F`, the parent event, the future control head, or a future merge SHA.

The coordinator commits only that manifest delta as single-parent control head `FH` whose sole parent is `M`, then lands a distinct manifest-only two-parent closeout-control merge `F` with ordered parents exactly `[M,FH]`. Both `M..FH` and `M..F` must name only `plans/manifest.json`; every non-manifest blob and tree entry is byte-identical to audited `M`; the unique completed event is added in `FH` and remains byte-semantically unchanged in `F` and fetched canonical `main`. A merge race, same-value `M`/`F`, arbitrary ancestor, wrong phase/digest/outcome, missing/duplicate/drifted event, extra lifecycle mutation, non-manifest delta, one-parent/octopus/reordered merge, or an `FH` not parented only by `M` blocks completion. Only `F`, not `M`, is HARDEN's dependency-completion landing for REVIEWTRUTH.

The newest immutable local-three review at
`.phase-loop/reviews/v10-harden-plan-panel.json` has file SHA-256
`724fdf39c3bd23459988f7f1b0f1a3fea278c56930b6b16c28998738a4c59ead`.
It reviewed predecessor plan SHA-256
`5e234a6c104d10fa7b452ed9afa975b2dadf2a87483dc24caeb350352e139f25`,
roadmap SHA-256 `4d652aaff71b484806ea6d1770c9475e0c1e8de90c39e5447c6fadb8d0fa2c6f`,
bundle SHA-256 `8fe0649119d6909a0e41034115d4e1f2ba6a0795f53f20f51d7ae4705da27c1b`
(`168897` bytes), and instructions SHA-256
`41371fc43a293e7323265d3cd28422af266146f756b2d4c110d3f661ac034354`.
All three available legs returned usable `AGREE`; Fable was absent. That unanimous local-three
result is retained exactly as immutable, non-authorizing predecessor evidence. It does not
approve this changed roadmap or rebound plan digest, and a fresh full four-seat exact-digest
panel remains mandatory before SL-0.

The current artifact at that same path has SHA-256
`6d18cbedf3e793c839dcd4a89883c2b5e82281e98e23fce7e0cfc68419cae7f5`.
It reviewed plan SHA-256
`f60b9373066b9537f0ea5e78b78b2462dc535cbb04d86e1fa384a14f4bee48da`,
roadmap SHA-256 `158c9f28857ef1df02a6b8ca72aef93f3a8a2acc8e591ca6adc70dd53ddb854d`,
bundle SHA-256 `de0338490aeb6fbf82b72a28d8a6a3205b9a79d9348990548794b6580f03fb4d`
(`172064` bytes), and instructions SHA-256
`41371fc43a293e7323265d3cd28422af266146f756b2d4c110d3f661ac034354`.
Grok returned usable `DISAGREE`, GPT-5.6 Sol returned usable `AGREE`, and the
Gemini leg was unusable/degraded. The artifact therefore authorizes nothing. Grok
proved that the precomposition/public-board refusal contract changes reachable
success tests outside the nine-path inventory; this repair expands the frozen test
ownership from the complete live corpus rather than adding a compatibility bypass.

HARDEN now begins only after the exact two-parent FABPUB landing, which transitively contains the
LEGIBLE, PROOFGATE, and CONFORM landings. Before any lifecycle transition or SL-0 write, the
coordinator fetches that canonical base, reruns the real disposable manifest lifecycle
simulation, rechecks every owned-path/source anchor and all 16-key sibling rows, and regenerates
the tests-only baseline if any upstream byte changed. REVIEWTRUTH is explicitly downstream of
HARDEN, so its remaining durable-record, target-rule, and merge-topology gates cannot block this
phase; the `agent-harness#398` human ratification itself is already satisfied.

The live standalone CLI calls `compose_review_board()` before `invoke_board()`,
and the composer can call each reachable capability record's `auth_ok()` while
selecting seats. HARDEN therefore treats pre-composition authorization as part
of the isolation boundary, not as an invoker-only concern. The CLI must obtain
an operation-bound isolation/broker authorization before it enters board
composition; `compose_review_board()` must validate that authorization—or
obtain the same authorization for a direct production caller—before it performs
an availability probe, capability-registry lookup, `auth_ok()` call, seat
construction, provider/subscription lookup, or other composition side effect.
The authorization is then carried into `invoke_board()`, which revalidates it
before artifact/context resolution, gateway/research discovery, subscription
access, provider routing, auth preflight, or launch. These invoker checks remain
defense in depth; they never substitute for the earlier CLI/composition gate.

The external coordinator also owns every mandatory four-seat plan,
implementation, and post-landing review. The pre-implementation plan and
tests-only panels necessarily predate the HARDEN boundary and are TDD/governance
preconditions only; they cannot be replayed or counted as post-implementation
isolation evidence. At exact implementation head `I` and exact canonical-main
head `M`, direct invocation of the current subscription subprocess routes is
forbidden. The coordinator instead launches the newly implemented repo-local
isolated-panel boundary from a clean worktree at that exact head. Fable, Sol,
Gemini, and Grok each run as a supported review-leg route: an untrusted
`linux_bwrap_v1` review environment sees only an immutable staged snapshot,
approved staged context refs, read-only tools, run-local scratch, and a typed
Unix inference socket; a distinct trusted parent control plane retains the
first-party subscription transport/auth and permits only the intended inference
RPC through an exact seat-specific broker adapter. API-key fallback remains
disabled.

`PanelRequest.context_refs` remains an input-routing API, not an isolation
primitive: every ref is copied and hash-verified before launch, and the review
leg sees only its contained `/review` destination. Prompts, ref names, CLI
flags, staged CWDs, and route labels cannot establish isolation. The four exact
`I`/`M` panel routes are normalized supported rows in the live route registry
and fleet checklist, carry direct mutation and credentialed-side-effect probe
attestations, and contribute to `EC-HARDEN-5`; they are not relabeled or
excepted as external governance. All other review routes satisfy the identical
boundary/transport contract or refuse before authentication lookup, session
creation, broker connection, or child launch.

No already-loaded process may attest a candidate that changes any runner,
verification, or reducer surface it imported. After the external coordinator
freezes and pushes the exact candidate, it starts a new repo-local phase-loop
process at that clean fetched head. After merge, it terminates that process and
starts a second new repo-local process at the exact clean server-recorded
canonical-main head. Only those new runtimes may export
`PHASE_LOOP_RUN_DIR`, create canonical JUnit/evidence in their own run
directories, or attest their loaded heads and modules.

`SL-0` freezes a test-owned activation guard. Before implementation,
`PHASE_LOOP_TDD_EXPECT_HARDEN=1` deterministically activates every new and
opposite-behavior assertion so its intended RED result can be captured. With
that variable absent on the tests-only main, exactly the frozen new-test nodeid
set skips while all 105 migrated tests execute their unchanged legacy
assertion branches. `SL-2` later installs the production capability marker;
the same immutable tests then activate the HARDEN branches by default.
`SL-1.8`, `SL-2.6`, and the clean checkpoint proof explicitly set
`PHASE_LOOP_TDD_EXPECT_HARDEN=1` so the interim lane gates are executable
independently of import timing. The final clean exact-`I` and exact-`M` proofs
remove that environment activation, require
`HARDEN_CAPABILITY_VERSION == 1`, and still require 126 passed with zero skips.
No production lane owns an `SL-0` test path. A correction to any frozen test or
guard returns execution to `SL-0`, creates a new tests-only commit, re-runs
every affected RED falsifier, and re-panels the new exact digest before
production resumes.

## Interface Freeze Gates

- None. The roadmap declares `Produces: (none)` for HARDEN; the contracts below
  are phase-internal proof obligations and must not be promoted into a
  cross-phase IF gate.

## Lane Index & Dependencies

SL-0 — Test contract, falsifiers, and panelled RED landing
  Depends on: (none)
  Blocks: SL-1, SL-2, SL-3
  Parallel-safe: no

SL-1 — Review staging and fleet isolation
  Depends on: SL-0
  Blocks: SL-3
  Parallel-safe: yes

SL-2 — Reconcile, goal-coverage, interpreter, and runner sequencing hardening
  Depends on: SL-0
  Blocks: SL-3
  Parallel-safe: yes

SL-3 — Fresh-process candidate/post-landing evidence and documentation reducer
  Depends on: SL-0, SL-1, SL-2
  Blocks: (none)
  Parallel-safe: no

The ownership inventory is exact and digest-bound. Each digest below is
SHA-256 over the listed repo-relative paths sorted bytewise, UTF-8 encoded, one
path per line, with a final newline:

- phase-owned paths: 46;
  `453bbecfdbcc6570e8cd04d68b45097a1c05022691919b5296ae0c36d7f0eb47`
- tests-only paths: 26;
  `1c89c155544538b7a79f6333c5e8ff7bc30ddca808e9b0d229b91ed54394f250`
- functional checkpoint `SL-1` + `SL-2` source paths: 18;
  `b20d6f20a8a073d4c5401143bd72850b69bc1e1661668bd7f3d3e5c628d58d03`

The sole ownership exception is the runner-owned lifecycle-control path
`plans/manifest.json`. No `SL-*` lane owns or may edit, stage, or commit it, and
it is not added to any phase/test/checkpoint path inventory. The external
coordinator may admit only the exact `update_lifecycle` deltas above at the
explicit pre-`SL-0` and terminal control boundaries. At every lane, checkpoint,
candidate, and exact-`M` dirty-path gate the manifest must already be clean and
equal to the applicable server-landed control blob; treating arbitrary
manifest dirt as planning/control state is forbidden.

## Lanes

### SL-0 — Test contract, falsifiers, and panelled RED landing

- **Scope**: Land only the complete HARDEN regression/mutation test set, every production-reachable existing public-board execution contract that must migrate, the classified pure public-board controls, the deterministic activation guard, and runner-owned RED evidence before any production, script, or changelog change.
- **Owned files**: `phase-loop-runtime/tests/harden_tdd_guard.py`, `phase-loop-runtime/tests/test_advisor_board_advisory_mode.py`, `phase-loop-runtime/tests/test_advisor_board_backcompat.py`, `phase-loop-runtime/tests/test_advisor_board_backing_homebrew.py`, `phase-loop-runtime/tests/test_advisor_board_backing_omnigent.py`, `phase-loop-runtime/tests/test_advisor_board_cli_legacy.py`, `phase-loop-runtime/tests/test_advisor_board_composition.py`, `phase-loop-runtime/tests/test_advisor_board_config.py`, `phase-loop-runtime/tests/test_advisor_board_golden.py`, `phase-loop-runtime/tests/test_advisor_board_integration.py`, `phase-loop-runtime/tests/test_advisor_board_live_research.py`, `phase-loop-runtime/tests/test_advisor_board_observability.py`, `phase-loop-runtime/tests/test_advisor_board_presets.py`, `phase-loop-runtime/tests/test_advisor_board_research.py`, `phase-loop-runtime/tests/test_advisor_board_resolver.py`, `phase-loop-runtime/tests/test_goal_coverage.py`, `phase-loop-runtime/tests/test_harden_evidence_verifier.py`, `phase-loop-runtime/tests/test_panel_invoker.py`, `phase-loop-runtime/tests/test_panel_leg_failure_diagnostic.py`, `phase-loop-runtime/tests/test_panel_native_fill_183.py`, `phase-loop-runtime/tests/test_panel_streaming_verdicts.py`, `phase-loop-runtime/tests/test_phase_loop_injection.py`, `phase-loop-runtime/tests/test_ratification_policy.py`, `phase-loop-runtime/tests/test_reconcile_portability_85c.py`, `phase-loop-runtime/tests/test_review_leg_sandbox.py`, `phase-loop-runtime/tests/test_verification_interpreter_guard_221.py`
- **Interfaces provided**: `HARDEN-test-freeze`, `HARDEN-TDD-activation-contract`, `HARDEN-node-partition-contract`, `HARDEN-RED-evidence`, `HARDEN-post-suite-sequencing-contract`
- **Interfaces consumed**: `HARDEN-roadmap-obligations` (pre-existing), `HARDEN-live-source-anchors` (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Freeze the guard, all `SL-0.1`–`SL-0.5` HARDEN regression/mutation selectors, the exact 126-nodeid inventory partitioned as 115 `SL-1` nodes + 7 `SL-2` nodes + 4 `SL-3` evidence nodes, the exact 21-nodeid default skip set, all 105 migrated assertion branches, the 134-caller execution/pure classification, and the fresh-process/manifest falsifiers. In the already-owned `phase-loop-runtime/tests/test_harden_evidence_verifier.py`, the future completion-control scope explicitly includes `test_harden_completion_event_rejects_missing_duplicate_wrong_phase_or_drift`, `test_harden_completion_event_rejects_plan_roadmap_evidence_panel_or_required_fact_mismatch`, and `test_harden_completion_merge_rejects_wrong_order_parent_count_or_non_manifest_delta`, plus a positive `M -> FH -> F` fixture proving the full preflight-attestation → rendered-prompt → native-result → reducer-artifact chain for early Codex, critics, and native Fable; producer-derived identity/capability/binding/status/raw-text/chronology/bundle; prompt-bound lens/seat/bundle; native exact `EVIDENCE_REF` grounding; total status-to-outcome derivation; exact terminal grammar and non-elided substance excluding citation lines; event absence at `M`; exact addition at `FH`; byte-semantic preservation at `F`; unchanged non-manifest blobs; and no self-referential `FH`/`F` field. The unchanged named falsifiers first retain literal RED fixtures for `[elided]` plus 41 padding bytes ending in `AGREE`, an all-AGREE synthetic four-seat artifact/receipt set with no producer records, a reducer-only grounded generic Fable `AGREE`, a citation-only native body ending in `AGREE`, a substantive native body citing both final artifacts plus a third valid bundled artifact, prompts omitting declared lenses, a prompt carrying both the expected and an extra conflicting marker, and every cross-class status/outcome relabel, then reject exact-verdict suffixes, missing/malformed/extra/wrong native citations, prompt marker/ref omission, duplication, substitution, or aliasing, opaque early artifacts, absent/swapped/aliased producer records, producer/identity/text/status/chronology/bundle substitutions, and duplicate native-result IDs. These tests land in SL-0 and are not written by this planning repair.
  - impl: Land the tests-only commit and runner metadata in `SL-0.6`.
  - verify: Prove default-main compatibility plus activated per-selector/per-case RED and positive controls with raw and structured evidence in `SL-0.7`.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-0.1 | test | — | the guard, all nineteen audited `test_advisor_board_*`/public-invoker modules in the exact owned inventory, `test_review_leg_sandbox.py`, and `test_phase_loop_injection.py` | the exact 100 execution-affecting public callers, the separate exact 54 pure/static controls, their literal 20-node intersection and 134-node union, three guarded staging migrations, the existing ordering/refusal cases, `test_public_invoke_revalidates_operation_bound_authorization_before_any_effect`, `PublicBoardAuthorizationTests::test_sanctioned_hermetic_authorization_transport_preserves_public_success_contracts`, and all staging/fleet falsifiers | Run exact `SL1_NODEIDS` for the frozen 115-node phase partition and, as a distinct command, exact `PURE_CONTROL_NODEIDS` under `PHASE_LOOP_HARDEN_PROOF_MODE=pure_control`; no module glob, `-k`, collection-derived selector, or broad-suite result may substitute for either literal tuple |
| SL-0.2 | test | — | `phase-loop-runtime/tests/test_reconcile_portability_85c.py` | `test_reconcile_main_loop_paths_are_cwd_independent`, `test_relative_automation_artifact_is_repo_anchored_not_cwd_anchored` | `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_reconcile_portability_85c.py -q -k "cwd_independent or repo_anchored"` |
| SL-0.3 | test | — | `phase-loop-runtime/tests/test_goal_coverage.py` | guarded existing `test_legacy_no_ids_no_evidence_no_block`, guarded existing `test_unresolvable_plan_legacy_does_not_block`, `test_goal_coverage_enforce_blocks_every_zero_declared_phase_at_every_completion_gate`, `test_goal_coverage_all_bare_legacy_is_distinct_warns_by_default_and_blocks_under_enforce` | `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_goal_coverage.py -q -k "legacy_no_ids_no_evidence_no_block or unresolvable_plan_legacy_does_not_block or enforce_blocks_every_zero_declared or all_bare_legacy_is_distinct"` |
| SL-0.4 | test | — | `phase-loop-runtime/tests/test_verification_interpreter_guard_221.py` | `test_argument_consuming_bash_options_and_profile_patch_version_fail_closed` | `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_verification_interpreter_guard_221.py -q -k argument_consuming_bash_options_and_profile_patch_version_fail_closed` |
| SL-0.5 | test | — | `phase-loop-runtime/tests/harden_tdd_guard.py`, `phase-loop-runtime/tests/test_harden_evidence_verifier.py` | existing evidence/chronology/manifest falsifiers plus the three exact completion-event/topology falsifiers named above and their positive `M -> FH -> F` control | `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_harden_evidence_verifier.py -q` |
| SL-0.6 | impl | SL-0.1, SL-0.2, SL-0.3, SL-0.4, SL-0.5 | all `SL-0` owned test paths only | frozen tests-only PR and landed commit | Only after the manifest-only lifecycle-control PR `L` has landed and the fetched target is clean, open and merge a tests-only PR into that exact target branch. It changes no source, executable, changelog, roadmap, manifest, or lifecycle-control path. Record server-returned tests-PR number, target/base/head ref names and object IDs, merge commit, merged time, exact test-tree blob IDs, and commit SHA; prove `L` is in the target ancestry and `plans/manifest.json` equals the landed `L` blob. Do not create or push the distinct implementation branch until the server reports the tests PR merged and its commit reachable from the target branch head. |
| SL-0.7 | verify | SL-0.6 | all `SL-0` owned test paths only | default skip/migration proof, activated per-selector/per-case RED, landed-base topology, and exact positive controls | Fetch the server-recorded post-merge target head and prove the tests commit is its ancestor. With activation absent, require the exact 105 migrated nodeids to pass and the exact 21 new nodeids—and no migrated nodeid—to skip. Then set `PHASE_LOOP_TDD_EXPECT_HARDEN=1`, collect exactly the same 126 nodeids, and run every nodeid plus every frozen `RED_CASES_BY_NODEID` case separately against that landed pre-implementation base. Every execution-capable public migration must fail only at its explicit missing sanctioned authorization/transport or parse-before-auth assertion; the two new refusal nodes fail at their named zero-effect anchors. In a separate process with both `PHASE_LOOP_TDD_EXPECT_HARDEN=1` and `PHASE_LOOP_HARDEN_PROOF_MODE=pure_control`, import and pass exactly the literal 54 `PURE_CONTROL_NODEIDS` to pytest and write only `harden-pure-control-red.xml`; require 54 passed exactly once, zero skipped/xfailed/errors, and zero capability/auth/session/provider/broker/callback/spawn canaries. The 20 overlapping nodeids must fail at their execution anchors in the ordinary activated RED records and pass at their pure anchors in this separate JUnit. Bind the pure-control command argv, guard/test blobs, exact target head, proof mode, tuple/count/digest, XML digest, and parsed testcase set in coordinator evidence. Reject a broad/focused XML, reused path/digest, missing proof mode, runtime collection, module glob, `-k`, or future discovered test as a substitute. Require intended RED assertion failures with zero skip, xfail, collection, import, setup, or teardown errors; record raw stdout/stderr, asserted source anchor, applied mutation/case, exit status, and JUnit in canonical `.phase-loop/` evidence. The coordinator may create the implementation branch only after the guard's exact inventories, raw anchors, and positive controls pass this gate. |

`SL-0` is a complete tests-only landing, not an additive-selector landing.
`phase-loop-runtime/tests/harden_tdd_guard.py` is the single test-owned guard.
It freezes nine literal, reviewable nodeid tuples plus the case map:
`EXPECTED_PHASE_NODEIDS` (126 entries), `SL1_NODEIDS` (the 115 review/staging/public-API
nodes), `SL2_NODEIDS` (the 7 reconcile/goal/interpreter nodes),
`SL3_EVIDENCE_NODEIDS` (the 4 evidence/lifecycle nodes),
`DEFAULT_SKIP_NODEIDS` (21 entries), `PUBLIC_BOARD_EXECUTION_NODEIDS` (100
entries), `PURE_CONTROL_NODEIDS` (54 entries),
`EXECUTION_PURE_OVERLAP_NODEIDS` (20 entries),
`PUBLIC_BOARD_CALLER_NODEIDS` (134 entries), and `RED_CASES_BY_NODEID` (every
parameter/case identifier and its raw source anchor). Every tuple is a literal,
sorted, duplicate-free constant with an exact count and sorted-LF SHA-256; no
tuple is produced from pytest collection, a module glob, `-k`, a future test,
or a runtime registry. The three lane partitions
are pairwise disjoint and their union equals `EXPECTED_PHASE_NODEIDS`; no task
may run or claim a different partition. The guard reports HARDEN active only when
`PHASE_LOOP_TDD_EXPECT_HARDEN == "1"` or
`phase_loop_runtime.verification_evidence.HARDEN_CAPABILITY_VERSION == 1`.
No other environment value, branch name, Git dirtiness, import failure, or
model/runner assertion activates the new contract.
`PHASE_LOOP_HARDEN_PROOF_MODE=pure_control` is a test-only selector, not an
activation path: it is valid only while HARDEN is already active, rejects every
other nonempty value, and lets the 20 overlapping nodeids exercise their pure
arm while the ordinary activated run exercises their execution arm. Each pure
test opts into the helper explicitly; a global or autouse fixture is forbidden.
New test modules import only the guard and pre-existing seams at module scope;
any capability-specific lookup stays inside the activated test body, after the
new-nodeid skip decision, so the inactive default can never fail collection.

The 105 migrated nodeids are retained verbatim and never skipped. With HARDEN
inactive, they execute their byte-for-byte legacy assertion bodies; with HARDEN
active, the same nodeids execute the opposite HARDEN assertions:

- `phase-loop-runtime/tests/test_review_leg_sandbox.py::test_stage_review_tree_is_gitignore_aware_working_tree_copy`
- `phase-loop-runtime/tests/test_review_leg_sandbox.py::test_resolve_codex_review_stage_materializes_then_cleans`
- `phase-loop-runtime/tests/test_review_leg_sandbox.py::test_panel_leg_review_dir_never_contains_the_repo`
- `phase-loop-runtime/tests/test_goal_coverage.py::GoalCoverageCloseoutTest::test_legacy_no_ids_no_evidence_no_block`
- `phase-loop-runtime/tests/test_goal_coverage.py::GoalCoverageCloseoutGateTest::test_unresolvable_plan_legacy_does_not_block`

The other 100 migrated nodeids are the exact execution-affecting public-board
call inventory derived from a fresh runtime trace over nineteen existing test
modules. That trace completed with 304 passed, two intentional skips, 17 passed
subtests, and zero failures. The sorted module list has SHA-256
`262a2c0e653b9dc1e98f2c815918d2a35e8377377d344026affe7154d1b8ea34`; its
complete collected 306-node corpus has sorted-LF SHA-256
`4789528566ada4e92cdf0ba6324704a60697f4166c25985ddc78c2da6ccda656`;
all 134 callers have sorted-LF SHA-256
`cecbef4c0f550f16a0e5e033be9d88216dcd7a8b9d127f6c91c920cd2359bb6e`.
The classified 100-node execution-affecting set—`invoke_board`, live/default
composition, and default-auth `load_boards`—has sorted-LF SHA-256
`90e36e87f2d93504c63bfefd850bdceb9c3cc869f62c7969b5815e2e49950ac7`.
The 54-node pure/static-control set—pure config parse/validation, injected
hermetic composition, static preset/catalog construction, and `resolve_board`
over constructed data—has sorted-LF SHA-256
`7d4b4f994f04b0926d0318fd5d7d983c0a81488d171c0755e94d9b1c8b66eef4`;
20 nodeids deliberately occur in both sets and have sorted-LF SHA-256
`3ce722d31e283cd455b3c7d23ed3d755e076e0fd09402518fbe9c10ba11488d6`;
their union is exactly all 134 callers, and neither set is inferred from future tests. The exact topology is
`100 + 54 - 20 = 134`: all 100 execution nodeids are members of
`SL1_NODEIDS`; the 20 overlap nodeids are already among those 100 and are not
additive phase nodes; and the other 34 pure-only nodeids are outside
`EXPECTED_PHASE_NODEIDS`. `harden_tdd_guard.py` freezes all four literal
classification tuples and requires the exact execution/pure intersection to
equal `EXECUTION_PURE_OVERLAP_NODEIDS`, their union to equal
`PUBLIC_BOARD_CALLER_NODEIDS`, all execution nodeids to be members of
`SL1_NODEIDS`, the pure/phase intersection to equal the overlap tuple, and the
pure-minus-phase difference to contain exactly 34 nodeids. Each
legitimate hermetic execution test must explicitly construct the sanctioned
operation-bound authorization and transport fixture while retaining its original
result/order/degradation/observability assertions. Pure controls remain
authorization-free and prove zero capability/auth/session/provider/broker/
callback/spawn effects. No global/autouse fixture, injected spawn, gateway,
adapter, or direct public entrypoint may manufacture or bypass authorization.
The two new refusal nodeids table-loop missing, forged, stale, wrong-head,
wrong-route, wrong-operation, replayed, and already-consumed authorizations at
the public `compose_review_board` and `invoke_board` seams and require zero
availability/auth lookup, session creation, broker/gateway/research access,
child spawn, callback, sink, or provider effect. A sanctioned positive control
enters the same public API with a fresh operation-bound authorization and
hermetic transport, proves the path was reached, and preserves the pre-HARDEN
semantic assertions.

The classification falsifiers mutate one obligation at a time. Removing,
duplicating, or reclassifying any execution, pure, overlap, or union node must
break the literal count/digest or set equations; moving any of the 34 pure-only
nodes into the phase inventory must break the pure-only difference; disabling
one auth/session/provider/broker/callback/spawn canary must make its matching
pure test fail; and routing any of the 20 overlap nodeids through its execution
arm in pure-control mode must fail the exact-54 run. Replacing the dedicated
pure XML with focused or broad XML, reusing an XML digest/path across stages,
dropping or duplicating a testcase, accepting skip/xfail/error, deriving the
selector from current collection, or adding a future collected test must be
rejected. Positive controls prove the unchanged literal 54-run passes while a
new unrelated collected test is ignored and while the ordinary activated run
still reaches every overlap execution anchor.

The exact inactive default skip set is the following twenty-one new nodeids—no
glob, marker-wide skip, module skip, runtime-derived registry list, or future
test is admitted implicitly:

- `phase-loop-runtime/tests/test_review_leg_sandbox.py::test_review_stage_rejects_every_escape_form_before_launch`
- `phase-loop-runtime/tests/test_review_leg_sandbox.py::test_review_isolation_registry_matrix_blocks_live_repo_and_privileged_side_effects`
- `phase-loop-runtime/tests/test_review_leg_sandbox.py::test_review_capability_registry_set_equality_covers_every_product_and_advisor_route`
- `phase-loop-runtime/tests/test_review_leg_sandbox.py::test_every_executable_review_route_requires_equivalent_contained_boundary_or_refuses_before_launch`
- `phase-loop-runtime/tests/test_review_leg_sandbox.py::test_review_snapshot_materializes_repo_and_context_refs_without_live_access`
- `phase-loop-runtime/tests/test_phase_loop_injection.py::test_claude_channel_requires_matching_sidecar_review_attestation_before_send`
- `phase-loop-runtime/tests/test_review_leg_sandbox.py::test_review_stage_crash_recovery_removes_only_journaled_paths`
- `phase-loop-runtime/tests/test_review_leg_sandbox.py::test_review_prompt_argv_cwd_and_env_omit_live_repo`
- `phase-loop-runtime/tests/test_advisor_board_composition.py::AuthAwareCompositionTests::test_harden_preflight_authorizes_before_every_capability_auth_ok`
- `phase-loop-runtime/tests/test_advisor_board_cli_legacy.py::AdvisorBoardCliTest::test_cli_harden_preflight_authorizes_before_compose_and_invoke`
- `phase-loop-runtime/tests/test_panel_invoker.py::PanelInvokerTest::test_public_invoke_revalidates_operation_bound_authorization_before_any_effect`
- `phase-loop-runtime/tests/test_advisor_board_integration.py::PublicBoardAuthorizationTests::test_sanctioned_hermetic_authorization_transport_preserves_public_success_contracts`
- `phase-loop-runtime/tests/test_reconcile_portability_85c.py::test_reconcile_main_loop_paths_are_cwd_independent`
- `phase-loop-runtime/tests/test_reconcile_portability_85c.py::test_relative_automation_artifact_is_repo_anchored_not_cwd_anchored`
- `phase-loop-runtime/tests/test_goal_coverage.py::test_goal_coverage_enforce_blocks_every_zero_declared_phase_at_every_completion_gate`
- `phase-loop-runtime/tests/test_goal_coverage.py::test_goal_coverage_all_bare_legacy_is_distinct_warns_by_default_and_blocks_under_enforce`
- `phase-loop-runtime/tests/test_verification_interpreter_guard_221.py::test_argument_consuming_bash_options_and_profile_patch_version_fail_closed`
- `phase-loop-runtime/tests/test_harden_evidence_verifier.py::test_harden_evidence_verifier_rejects_each_missing_or_forged_obligation`
- `phase-loop-runtime/tests/test_harden_evidence_verifier.py::test_harden_evidence_verifier_rejects_pretest_target_base_and_pr_range_tests`
- `phase-loop-runtime/tests/test_harden_evidence_verifier.py::test_harden_fresh_process_lifecycle_rejects_self_wrong_head_or_non_two_parent_merge`
- `phase-loop-runtime/tests/test_harden_evidence_verifier.py::test_harden_manifest_gate_rejects_malformed_or_stale_phase_entry`

The guard asserts that the migrated and skipped phase sets are disjoint and their
union is exactly 126. It separately asserts the classified public caller-set
counts, tuple digests, exact intersection/union equalities, intentional 20-node
execution/pure overlap, and 34-node pure-only difference. The 54-node
pure-control proof is never a fourth phase partition and never changes the
sealed `115 + 7 + 4 = 126` phase inventory.
On the landed tests-only base with activation absent, the focused phase JUnit
must contain exactly 105 passed and twenty-one skipped testcases, with the skip
set byte-for-byte equal to `DEFAULT_SKIP_NODEIDS`. With
`PHASE_LOOP_TDD_EXPECT_HARDEN=1`, collection must still equal the same 126
nodeids; all 126 execute and fail at their intended HARDEN assertion with zero
skipped, xfailed, collection, import, setup, or teardown errors. The runner then
uses `RED_CASES_BY_NODEID` to run every parameter/case separately, so aggregate
failure cannot hide a surviving case. It first asserts the frozen source anchor,
applies/selects exactly one case, runs exactly one nodeid, and retains raw
stdout/stderr plus structured JUnit. After implementation installs the
capability marker, the immutable 126-nodeid focused run must report exactly
126 passed and zero skipped; the candidate and post-landing broad JUnit files
must each contain every expected nodeid exactly once with zero skipped.
Ordinary default tests-only CI is GREEN with the marker absent: all 105 migration
branches pass and only the exact twenty-one-nodeid set skips. No `xfail` is
permitted. No collection/import failure is a RED result or a compatibility
escape.

The active branches preserve the settled HARDEN semantics: the two goal tests
block every all-bare/zero-ID completion route under enforce while retaining the
warn/default legacy control; the panel/staging tests assert the exact committed
or index-tree identity plus approved contained `context_refs`; and unrelated
working-tree/untracked drift cannot change that identity. No implementation PR
may edit, rename, repair, regenerate, or alter the guard, inventories, assertion
branches, docstrings/helpers, nodeids, or test blobs.

The sorted newline-terminated 126-nodeid inventory has SHA-256
`6b642b3a4a7f22b51c41c5a84383a09833b8af0c57e1a10e9c97cd2e3c623728`.
For non-executable historical comparison only, relative to the predecessor
latest-panel 24-node plan, the increase is exactly 102: 100
execution-affecting existing callers migrate in place and two new public
refusal/fixture nodeids join the two ordering nodes already planned. Relative
to the contract predecessor's 22-node inventory, `nodeid_delta` is exactly 104.
The twenty-one new nodeids are the default skip set; all 105 migrated nodeids
remain the default-green legacy set.

| Obligation | Required pre-implementation anchor | Per-parameter mutation and observable |
|---|---|---|
| staged-tree containment | `copytree(..., symlinks=True)` and `copy2(..., follow_symlinks=False)` are present | Absolute link, upward-relative link, chained link, symlinked directory ancestor, broken/cyclic link, non-git fallback link, `..`/absolute staged path, and special-file inputs each reach the staging seam and are rejected before child launch; an in-root regular file and an explicitly materialized in-root link remain positive controls. |
| pre-composition isolation authorization | `_advisor_board_command()` calls live/default composition before `invoke_board()`; live/default composition can call `default_board_auth_ok()`, which calls a capability record's `auth_ok()`; pure parser/preset/resolver paths have no execution effect | The CLI, bare live/default composer, config-loaded live composer, and invoker are exercised as separate frozen execution cases. An ordered event canary requires `preflight_started` then `preflight_authorized` before the first capability availability probe, registry/provider lookup, `auth_ok()` call, session/seat construction, subscription access, or invoker entry. Denied or forged authorization returns the typed non-human block and proves zero auth/provider/subscription/composition/invoker side effects. Config syntax/shape errors are parsed and rejected before live composition, also with zero auth effects. Removing only the CLI preflight still fails direct live-composer cases; removing only composer preflight still fails CLI/config-live cases. Injected hermetic composition, static presets/catalogs, and `resolve_board` remain authorization-free positive controls and prove no capability/auth/session/provider/broker/callback/spawn effect. Invoker revalidation is independently mutated and must still fail before artifact/context, Omnigent, research, seat-env, leg-auth, provider, or spawn work. |
| review fleet isolation | review-capable records come from `capability_registry()` plus the Advisor Board harness, compatibility, auth, backing, native-host, live Omnigent-catalog, and scoped-research registries; CLI specs use live `wrapped_cwd`; `context_refs` exposes live absolute paths; and current Fable/Sol/Gemini/Grok panel legs run subscription-authenticated host subprocesses | Every normalized product and advisor review route reaches preflight. A credentialless command adapter may execute only inside the exact Linux bubblewrap boundary below. The four mandatory Fable/Sol/Gemini/Grok subscription seats must be supported through the same untrusted review-leg boundary plus seat-specific `parent_unix_broker_v1` inference adapters, and the exact-`I`/`M` panels must use those rows. Every other provider-backed, API-key, native-host, Omnigent, research, or otherwise broker-incompatible route satisfies the same contract or refuses before credential lookup, session creation, broker connection, or child launch. Manual/nonlaunch proves no child or capability is created. Removing or adding one live registry route without an equal checklist row, executing a refused row, excluding a mandatory panel seat, or counting an unisolated/legacy panel record as route conformance fails. |
| contained review snapshot | current review prompts either expose live paths or reduce the workspace to a bundle, while `context_refs` emits live absolute paths and instructs the reviewer to open them | The launcher materializes the exact candidate Git tree plus every approved context ref into run-owned immutable paths, rewrites all review-leg-visible prompt/ref/workspace paths to those copies, and records each original logical label with source/destination SHA-256 provenance. Positive controls open and cite a candidate source symbol and a context-ref sentinel through the rewritten paths. Absolute/upward/chained/ancestor symlinks, special files, path races, or digest mismatches refuse before launch; negative controls cannot resolve or mutate either live original. Bundle-only remains an optional input, never the sole workspace when repository/context inspection is required. `context_refs`, a prompt, CLI flags, a staged CWD, or a model/tool allowlist without the proved OS/broker boundary is never isolation evidence. |
| crash cleanup | stage creation occurs before `launch_with_spec` cleanup and exact materialized paths are tracked | Normal return, resolver failure, timeout, interrupt, and a parent-process crash are injected separately. Recovery removes only journaled run-owned stage/config/home roots; a lookalike live directory is the positive non-removal control. |
| CWD-independent reconcile | `roadmap_paths_match` and `_normalize_automation_event` accept relative persisted paths | The same ledger bytes are reconciled from repo root and an unrelated CWD. Relative identity fields are rejected identically; relative `automation.artifact` resolves only against the absolute stored repo; relocated absolute roots with equal repo-relative roadmap subpaths remain accepted. |
| enforce goal coverage | zero/unknown declarations can reach `not_applicable()` or a confirmed-legacy skip | Preflight, canonical closeout, delegated/resume completion, and missing-plan closeout each receive every zero-declared form—including a syntactically valid all-bare legacy phase—plus ambiguous, unparseable, and missing-plan declarations under `PHASE_LOOP_ACCEPTANCE_ENFORCE=block`; every case must return a non-human `contract_bug`. The all-bare case must remain distinguishable from parse failure, but only warn/default mode is its nonblocking positive control; the same all-bare phase must never pass an enforce completion gate. |
| Bash/profile bypass | `_relogin_shell_shim` does not consume Bash argument-taking `-o option-name`, `+o option-name`, `-O shopt-option`, `+O shopt-option`, `--rcfile file`/`--rcfile=file`, or `--init-file file`/`--init-file=file`, and absent nominal minors can evade patch bounds | Every frozen argument-taking form locates the true `-c` payload only after consuming its argument; missing option names/files, ambiguous `--`, and malformed or unlocatable payloads fail closed. Under `<3.11.5`, a profile-introduced absent `python3.11 == 3.11.9` is shadowed/rejected; direct argv, non-login, satisfying-present, absolute-interpreter, and ordinary `bash -lc` controls retain their existing results. |
| evidence verifier and fresh-process lifecycle | the executable is absent, the current runtime does not export `PHASE_LOOP_RUN_DIR`, and the ordinary implementation child writes all lanes before the coordinator can observe an intermediate tree | Fixture mutations separately forge external coordinator identity, server PR identity, ordered two-parent merges, target-base ancestry, actual PR range, lifecycle timestamps, process PID/nonce, loaded-head/module digests, distinct PR/branch identity, test/guard blobs and 115/7/4 node partitions, all five exact-54 pure-control proofs, plan digest, GPT-5.6 Terra author-vendor independence, RED anchor/result, checkpoint/final commit trees and ancestry, snapshot provenance, pre-composition authorization traces, four mandatory isolated-seat attestations, registry/checklist equality, route refusal accounting, and either verification seal. The integration falsifier rejects a missing, forged, duplicated, dirty, or unlanded executing-control append; any child or pre-change-runtime transition/self-attestation; a synthetic or laundered checkpoint; a checkpoint containing `SL-3` or omitting changed `SL-1`/`SL-2` paths; candidate evidence from a process not freshly loaded at exact pushed `I`; post-landing evidence from the candidate process or a process not freshly loaded at exact canonical `M`; a missing/forged transition, isolated-panel record, suite JUnit, dedicated pure-control JUnit, fleet checklist, evidence file, or parent hash; a pure XML whose path or digest equals a focused/broad XML, whose exact tuple is not 54 passed once each, whose proof mode/head/process does not match its lifecycle stage, or whose selector came from collection; an auth/provider/subscription/composition event preceding authorization; an unisolated mandatory seat; and any merge or terminal `complete` before the corresponding audit and completed-control landing. Its positive control proves the only accepted lifecycle is exact executing append and manifest-only control merge `L`; tests merge, activated 126-node RED, and exact-54 pure GREEN; Terra child exit without commit; coordinator-created actual `SL-1`+`SL-2` checkpoint `C` with a clean manifest; a clean exact-`C` process proving 115 green + 7 green + exact 4 RED and a separate exact-54 pure GREEN while the verifier is absent from `C`; coordinator admission of only the quarantined `SL-3` verifier/docs as direct child `I`; a new clean exact-`I` process proving all 126 green plus a distinct exact-54 pure GREEN with environment activation absent; external coordinator push/transition; fresh exact-candidate 126/broad/exact-54 suites and isolated four-seat panel, reduction, and audit; candidate-process exit and exact two-parent implementation merge; then fresh exact-main 126/broad/exact-54 suites and isolated four-seat panel, reduction, final audit; exact completed append and manifest-only closeout merge `F`; and only then completion. |
| phase-plan manifest gate | `update_lifecycle()` normally appends an `executing` event without copying immutable plan metadata and rewrites `plans/manifest.json` before lane work | The current-manifest command must reject malformed JSON, structural/per-entry validation errors, a missing/duplicate/conflicting HARDEN identity row, stale HARDEN `file`, `phase_alias`, `roadmap_ref.file`, or lane metadata, and any missing, duplicate, identity-conflicting, malformed, or payload-drifted contract-bearing lifecycle record. It locates the sole immutable contract by `harden_plan_contract_record_id=v10-HARDEN.harden-plan-contract.v1`, never by latest-event position; seals every contract field other than the separately checked current plan digest; and rejects any mismatch in the current roadmap digest, exact 46 owned / 26 tests-only / 18 checkpoint path lists and digests, 126-node/115-7-4/21-skip/104-delta contract, complete 306-node corpus, literal 100 execution / 54 pure / 20 overlap / 134 union tuple counts and digests, the exact intersection/union/pure-only equations, 34 pure-only count, five required pure-control proof stages, or Terra/scheduler/subscription/no-release policy. The fixture must also exercise the normal committed → executing append and committed → executing → completed sequence through the byte-identical lookup. It rejects a wrong writer/run identity, an appended contract copy, a lifecycle/status/timestamp mismatch, arbitrary manifest dirt, an unlanded pre-`SL-0` control delta, or any implementation/checkpoint head whose clean manifest blob is not descended from server-landed `L`. The frozen fixture drives the same phase-specific gate with one mutation at a time and requires a typed non-zero result; committed, clean post-`L` executing, and exact terminal-control forms are the only positive controls. The coordinator must reseal `plans/manifest.json` with the new overlap digest, pure-only topology/proof fields, current plan digest, and final contract payload SHA before this command can pass; the plan intentionally does not invent those manifest values. |

Before `SL-0.6`, the external coordinator panels the exact plan digest and exact
tests-only diff by reference with Fable 5, GPT-5.6 Sol, Gemini 3.6 Flash, and
Grok 4.5. Fable and Sol must both produce usable reviews; all four must actually
review. Because these two reviews precede the implementation of the isolation
boundary, they are TDD/governance prerequisites only and supply no
`EC-HARDEN-5` evidence; they can never be reused as the exact-`I` or exact-`M`
panel. Any material finding changes the digest and requires a complete re-panel.
The tests-only PR and the later implementation PR must have distinct
server-recorded PR numbers and head branches. The tests-only commit must already
be in the implementation PR's server-recorded target branch before the
implementation branch is created or either production lane is dispatched.

### SL-1 — Review staging and fleet isolation

- **Scope**: Close every staged-tree escape and enforce one fleet-wide review boundary across all supported product-loop, advisor-board, and mandatory four-seat exact-head panel routes.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `phase-loop-runtime/src/phase_loop_runtime/launcher.py`, `phase-loop-runtime/src/phase_loop_runtime/injection.py`, `phase-loop-runtime/src/phase_loop_runtime/harness_env_signatures.py`, `phase-loop-runtime/src/phase_loop_runtime/capability_registry.py`, `phase-loop-runtime/src/phase_loop_runtime/claude_channel_sidecar.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/__init__.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/backing.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/config.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/presets.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/resolver.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- **Interfaces provided**: `precomposition-review-authorization`, `review-isolation-boundary`, `trusted-provider-control-plane`, `four-seat-isolated-panel`, `review-fleet-checklist-evidence`
- **Interfaces consumed**: `HARDEN-test-freeze`, `HARDEN-RED-evidence`
- **Parallel-safe**: yes
- **Tasks**:
  - test: Confirm the `SL-1.1` review selectors remain frozen from `SL-0`.
  - impl: Implement contained staging, review-route isolation, pre-composition authorization, and journaled cleanup in `SL-1.2`–`SL-1.7`.
  - verify: Run the complete review matrix command in `SL-1.8`.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-1.1 | test | — | all `SL-0` review test paths, read-only | frozen review selectors | Confirm every review selector is unchanged from the `SL-0` commit before implementation. |
| SL-1.2 | impl | SL-1.1 | `phase-loop-runtime/src/phase_loop_runtime/launcher.py` | staged-tree containment | Validate every enumerated source and destination lexically and after resolution. Materialize safe in-root links as contained regular content or reject; reject every absolute/upward/chained/ancestor escape, special file, and non-git fallback escape before launch; remove the partial stage on every `BaseException`. |
| SL-1.3 | impl | SL-1.1 | `phase-loop-runtime/src/phase_loop_runtime/launcher.py`, `phase-loop-runtime/src/phase_loop_runtime/injection.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` | immutable snapshot and path-isolation matrix | Before prompt/context/argv construction, resolve the declared candidate to an exact Git tree identity—server head tree for a committed/PR review or a launcher-recorded index tree for an exact staged candidate—and materialize that complete tree plus every caller-approved `context_ref` into run-owned staged paths. Preserve each original logical label, but rewrite every child-visible workspace, prompt, manifest, and ref path to the contained copy. Record source identity/path, destination-relative path, kind, bytes, and source/destination SHA-256 in launcher-owned provenance; require equality before launch. Reject lexical/resolved escapes, symlink chains/ancestors, special files, source races, collisions, and digest drift. For a supported executable route, invoke the exact bubblewrap boundary frozen below, mount the finished snapshot read-only at `/review`, make `/review` the child CWD/workspace, and refuse if any live original remains visible in CWD, argv, prompt/context, environment, mounts, or tool policy. A review bundle may accompany the snapshot but cannot replace repository or approved-context material the review contract requires. |
| SL-1.4 | impl | SL-1.1 | `phase-loop-runtime/src/phase_loop_runtime/harness_env_signatures.py`, `phase-loop-runtime/src/phase_loop_runtime/capability_registry.py`, `phase-loop-runtime/src/phase_loop_runtime/launcher.py`, `phase-loop-runtime/src/phase_loop_runtime/claude_channel_sidecar.py` | OS-boundary, credential-transport, and tool-isolation matrix | Add route declarations `review_boundary=linux_bwrap_v1` and `review_transport=none|parent_unix_broker_v1`. `none` is permitted only for a credentialless/no-network command adapter. Under `parent_unix_broker_v1`, the attacker-controlled review leg is a separate bubblewrap process with immutable `/review`, read-only tools, run-local scratch, no live repo/original ref, no ambient home/config/credential, no direct network, and no host escape. It sees only `/run/review-broker/socket` plus a non-secret route/session identifier. A distinct trusted coordinator/parent control plane owns subscription auth and provider egress, verifies `SO_PEERCRED`, accepts only a typed `ReviewInferenceRequest` binding seat, model, immutable input/provenance digest, conversation turn, and output limit, and returns only provider text/status/provenance. It rejects arbitrary URLs, provider/method substitution, host commands, tool execution, credential reads/returns, mutation operations, and all non-inference RPCs. Implement and prove exact first-party subscription adapters for Fable 5, GPT-5.6 Sol, Gemini 3.6 Flash, and Grok 4.5; the underlying transport process is parent-controlled and may perform only that intended inference. The four adapters must complete without placing a credential file, API key, OAuth token, inherited auth socket, ambient home, or provider network capability in the review-leg namespace. Build the review-leg environment from an allowlist and keep its prompt/tool namespace/argv/environment/snapshot/home/config/logs secret-free. Route-specific flags remain defense in depth. Return typed non-human `review_gate_block` before auth lookup/session creation/broker connection/child launch when any required platform, boundary, transport, adapter, sidecar, or direct probe is unproved; normalize persisted closeout blockers to `blocker_class=contract_bug`. |
| SL-1.5 | impl | SL-1.4 | `phase-loop-runtime/src/phase_loop_runtime/cli.py`, all six owned `advisor_board/{__init__,composition,config,presets,resolver,backing}.py` public construction surfaces, `phase-loop-runtime/src/phase_loop_runtime/capability_registry.py`, `phase-loop-runtime/src/phase_loop_runtime/launcher.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` | pre-composition isolation/broker authorization, classified public API migration, and pre-auth ordering | Mint an opaque, operation-bound `precomposition-review-authorization` only after the exact platform, `linux_bwrap_v1`, broker-adapter, direct-probe, and route-refusal prerequisites are proved. `_advisor_board_command()` obtains it after regular-file validation but before live/default composition, passes it through that path, and supplies it again to `invoke_board()`. Live/default `compose_review_board` and `load_boards` modes validate or explicitly obtain the same sanctioned authorization before their first capability availability/registry/`auth_ok`/session/construction effect; config syntax and shape validation happen first and can reject without authorization or effects. Every public `invoke_board()` independently revalidates before artifact/context, Omnigent/gateway/research, auth/session/provider, callback, or spawn work. Pure config validation, injected hermetic composition, static presets/catalogs, and `resolve_board` over constructed data stay authorization-free and effect-free; none may invoke a board. Injected spawn/gateway/adapters cannot bypass validation. Legitimate hermetic execution tests pass an explicit sanctioned authorization/transport fixture and preserve their prior assertions; pure controls retain auth-free assertions; no autouse/global shim is permitted. Missing, forged, stale, wrong-head/route/operation, replayed, or consumed authorization returns typed non-human `review_gate_block`/`contract_bug` with every auth/provider/subscription/session/composition/callback/spawn canary untouched. The frozen new nodeids and all 100 execution-affecting public callers run these cases through `RED_CASES_BY_NODEID`; the separate literal 54-node pure-control command proves all pure arms GREEN and effect-free, including the pure arm of each of the 20 overlapping nodeids, while the ordinary phase command proves their execution arms. Ordered execution traces require `preflight_started`, `preflight_authorized`, then—and only then—the first permitted effect. |
| SL-1.6 | impl | SL-1.4, SL-1.5 | `phase-loop-runtime/src/phase_loop_runtime/advisor_board/backing.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/capability_registry.py`, `phase-loop-runtime/src/phase_loop_runtime/launcher.py` | complete live review-route registry and honest support/refusal | Produce one normalized route registry from every `capability_registry()` record supporting `review` (including command/manual and Claude route/mode expansion), every Advisor Board route expressible through the live harness/compatibility registries, auth lanes, provider backings, native-host state, scoped-research state, and live Omnigent catalog, and the four brokered Fable/Sol/Gemini/Grok panel-seat routes. Apply the frozen support/refusal table below literally. Candidate and canonical-main panels must invoke these same four supported rows through the exact-head repo-local boundary; their per-seat boundary/broker/probe attestations are checklist evidence, not an exclusion. A refused executable row satisfies the safety invariant only by proving that no credential lookup, session, broker connection, child, or side effect occurred; it is never reported as a supported conforming route. Manual/nonlaunch remains an evidenced non-executable row. Compare normalized registry keys with checklist keys by exact set equality so additions, omissions, duplicates, an unisolated or missing mandatory seat, an executed refused row, and a panel record without matching supported rows fail closed. API-key fallback is disabled throughout HARDEN. |
| SL-1.7 | impl | SL-1.1 | `phase-loop-runtime/src/phase_loop_runtime/launcher.py` | crash/recovery cleanup | Journal exact run-owned stage, home, config, and context roots before child launch; clean them on normal return, resolver failure, timeout, interrupt, and next-run recovery after parent crash; never infer ownership from basename, glob, or a live path. |
| SL-1.8 | verify | SL-1.2, SL-1.3, SL-1.4, SL-1.5, SL-1.6, SL-1.7 | all `SL-1` owned source paths | exact 115-node review/public-API matrix plus separate exact-54 pure controls | Set `PHASE_LOOP_TDD_EXPECT_HARDEN=1`, import literal `SL1_NODEIDS` from the frozen guard, and invoke pytest with exactly those 115 nodeids plus `--junitxml=<checkpoint-run-dir>/harden-sl1.xml`; require exactly 115 passed, zero skipped/xfailed/errors, explicit sanctioned fixtures on all 100 execution-affecting callers, zero-effect refusal traces, ordered pre-auth traces for every live composition/invocation case, and JUnit nodeid set equality. Then run a distinct process with `PHASE_LOOP_HARDEN_PROOF_MODE=pure_control`, exact literal `PURE_CONTROL_NODEIDS`, and a distinct diagnostic XML; require all 54 pure controls GREEN/effect-free and the pure arm of all 20 overlaps reached. This child result is diagnostic only. The authoritative 115 and 54 results are rerun by the external coordinator's clean exact-`C` process; exact-`I` and exact-`M` remove the activation variable, retain only the test-only proof-mode selector for the separate pure command, and prove capability-marker activation with zero skips. |

The exact current product-loop matrix is sixteen cells, but it is only one
projection of the live review-capability registry. The test derives normalized
route keys from `capability_registry()`, Claude route/mode registries, the
Advisor Board harness/compatibility/auth/backing registries, native-host and
scoped-research state, and the live Omnigent catalog. Exact set equality with
the checklist means any newly reachable route fails closed until its posture is
declared and proved. HARDEN lands this honest matrix:

| Executor / surface | HARDEN posture | Exact reason |
|---|---|---|
| credentialless typed command adapter | **supported on probed Linux only** | Runs inside `linux_bwrap_v1` with `review_transport=none`; arbitrary/provider/networked templates refuse. |
| mandatory Fable 5, GPT-5.6 Sol, Gemini 3.6 Flash, and Grok 4.5 panel seats | **supported on probed Linux only** | Each review leg runs inside `linux_bwrap_v1` and reaches only its seat-specific typed inference method through `parent_unix_broker_v1`; the trusted parent retains first-party subscription auth/transport. Exact-`I` and exact-`M` panels must use these four rows and all four direct-probe attestations. |
| manual/nonlaunch | **supported non-executable** | Creates no child, credential, workspace, broker, or side effect. |
| direct codex CLI product review | **refused** | `--sandbox read-only` and `--ignore-user-config` do not provide the complete review-leg/broker boundary; only the brokered Sol panel adapter above is supported. |
| direct Claude print, Channel, and Agent View across solo/subagent/agent-team | **refused** | Permission/tool flags and Channel bearer handling do not place the complete reviewer process tree behind the common boundary/broker; only the brokered Fable panel adapter above is supported. |
| direct gemini/agy and grok CLI review | **refused** | Staged CWD and tool allowlists are not an OS boundary; only the brokered Gemini and Grok panel adapters above are supported. |
| OpenCode CLI and Pi Agent | **refused** | No proved credentialless broker adapter and no equivalent attested OS boundary. |
| other Advisor Board homebrew subscription routes | **refused** | The mutable direct launch surface has no proved broker adapter; the four mandatory brokered panel rows above are the only supported subscription routes in HARDEN. |
| every API-key fallback route | **refused** | HARDEN preserves subscription-only governance and never injects API keys. |
| Omnigent, native-host, scoped-research, gateway, and compatibility routes | **refused** | No gateway/native attestation is accepted as equivalent until it proves the same mount, transport, secret-context, probe, and cleanup observables. |

`linux_bwrap_v1` is literal, not descriptive shorthand. Preflight requires
`sys.platform == "linux"`, a realpath-resolved `bwrap` on `PATH`, successful
`bwrap --version`, readable user/mount/PID/network namespace support, and a
successful no-network smoke using `bwrap --die-with-parent --new-session
--unshare-user --unshare-pid --unshare-ipc --unshare-uts --unshare-net` with
read-only binds for only the required system runtime roots, `--proc /proc`,
`--dev /dev`, a tmpfs `/tmp`, run-owned tmpfs home/config, the immutable
snapshot read-only at `/review`, and `--chdir /review`. Host `/home`, `/mnt`,
`/run`, `/var/run`, the live repository, original context refs, credential
stores, and unrelated paths are never bound. The preflight also requires
AF_UNIX plus `SO_PEERCRED` support and, for `parent_unix_broker_v1`, a
route-specific fake-broker round trip in which the review-leg adapter completes
with no credential source. This credentialless boundary/fake-broker proof is
the pre-composition authorization and must finish without a capability-registry
auth call, provider process, subscription lookup, network access, session, or
seat construction. Only after that authorization exists may capability
`auth_ok()` run; only after authentication may the trusted parent perform the
exact transport probe showing that the typed intended-inference RPC reaches the
selected first-party subscription route. macOS, Windows, Linux without the
namespace smoke, and any non-mandatory route missing a proved broker adapter are
refused before authentication, snapshot disclosure to a child, or
process/session creation; a missing Fable/Sol/Gemini/Grok adapter blocks HARDEN
rather than downgrading or refusing that mandatory seat.

Before every supported review-leg launch, direct canaries inside the exact namespace
must read the snapshot sentinel, write only run-owned home/tmp, fail to
`stat`/write the live repo and context-ref originals, fail non-broker network
connects, observe the exact allowlisted environment with no secret-shaped key,
and—when a broker is declared—connect only to the run-owned Unix socket. The
launcher records argv, resolved `bwrap` identity/version, namespace inode IDs,
mountinfo reduced to paths/modes, child CWD, environment-key set, broker
protocol/peer identity, tool-policy digest, provenance digest, probe results,
and cleanup in `review_boundary_attestation.v1`. A CLI permission flag, prompt,
staged CWD, canary without path entry, or child self-report cannot populate
these fields.

The review-leg environment is allowlist-built, not ambient-env-minus-a-few
keys. It may contain `PATH`, `LANG`, `LC_*`, `TERM`, `TMPDIR`, `USER`, `SHELL`,
`PHASE_LOOP_CHILD`, non-secret runner correlation IDs, run-local `HOME`,
`XDG_CONFIG_HOME`, `XDG_CACHE_HOME`, `XDG_DATA_HOME`, and a non-secret
`PHASE_LOOP_REVIEW_BROKER=/run/review-broker/socket` only for a proved broker
adapter. Subscription tokens, API keys, gateway credentials, provider headers,
auth helper paths, and other secrets never enter the process namespace,
environment, argv, prompt, tool results, snapshot, or logs.
Provider subscription state and
`PHASE_LOOP_CLAUDE_CHANNEL_BEARER_TOKEN` remain usable only inside the trusted
parent control plane and never enter a review-leg process; Channel becomes a
conforming seat only through the Fable broker adapter, not through its direct
product route.

`provider_control_plane_v1` is the other side of that boundary. For each seat,
the immutable coordinator starts a fixed-digest adapter in a run-owned empty
CWD with no repository, snapshot, context-ref, shell/tool namespace, GitHub,
SSH, package-publish, cloud, database, or 1Password capability. Its allowlisted
inputs are the validated `ReviewInferenceRequest`, that seat's parent-only
subscription handle, the exact provider/model route, and correlation limits;
its only outputs are provider text/status/provenance. The adapter invokes an
inference-only, tool-disabled provider transport and rejects any provider tool
request, arbitrary command, alternate endpoint/model/provider, auth export, or
non-inference operation. Provider egress is coordinator-owned and constrained
to the exact intended subscription inference route. The untrusted review leg
can request another inference turn only through the typed broker; it cannot
address the transport process, auth store, endpoint, or host directly. A route
whose current subscription CLI cannot be driven under this exact adapter must
be repaired in `SL-1`; for a mandatory seat it blocks HARDEN rather than
falling back to the unsafe direct CLI.

Every review route must remove API-key/auth/header/alternate-endpoint variables,
including `OPENAI_API_KEY`, the complete
`CLAUDE_SUBSCRIPTION_BLOCKED_ENV_VARS` set, `GEMINI_API_KEY`,
`GOOGLE_API_KEY`, `GOOGLE_GENERATIVE_AI_API_KEY`, `XAI_API_KEY`, and
`GROK_API_KEY`; mutation credentials and helpers including `GH_TOKEN`,
`GITHUB_TOKEN`, `GIT_ASKPASS`, `SSH_ASKPASS`, `SSH_AUTH_SOCK`,
`GIT_SSH_COMMAND`, `KUBECONFIG`, `NETRC`, `NPM_TOKEN`, `NODE_AUTH_TOKEN`,
`PYPI_API_TOKEN`, `TWINE_PASSWORD`, and `OP_*`; and the `AWS_*`, `AZURE_*`,
`GOOGLE_APPLICATION_CREDENTIALS`, `GCLOUD_*`, `VERCEL_*`, `SUPABASE_*`,
`CLOUDFLARE_*`, `DOCKER_*`, database URL/password/token, and generic
`*_API_KEY`/`*_TOKEN`/`*_SECRET`/`*_PASSWORD` families without exception in the
reviewer environment.
Shared `~/.netrc`, git credential helpers, keyrings, SSH keys/agents, gh config,
cloud configs, package-publisher configs, and 1Password sockets are absent from
the run-local home/config view.

The fleet test injects fake `git`, `gh`, `ssh`, credential-helper/keyring,
`curl`, `npm`, `twine`, cloud CLI, and `op` canaries. For the supported command
route and separately for each of Fable, Sol, Gemini, and Grok, a direct
review-leg probe attempts live-tree write/delete, git commit/tag/config,
HTTPS/SSH push, GitHub mutation, package publish, cloud mutation, secret
retrieval, arbitrary broker method/provider/URL substitution, and non-broker
network/host escape. Every attempt must enter its intended probe and be denied
before any canary records a side effect; the only positive credentialed action
is the parent-recorded intended inference RPC for that exact seat. Each
mandatory seat also proves it can read/cite the immutable snapshot through
read-only tools and return a usable provider response without credential or
network capability in the review-leg namespace. For every refused route, a
preflight probe proves refusal happened before auth lookup, session/broker
creation, or child launch. A missing direct probe for any of the four seats, an
executed refused row, a refusal mislabeled supported, a mandatory panel record
without the four matching supported checklist rows, or route/checklist set
mismatch fails. No real external mutation is performed.

### SL-2 — Reconcile, goal-coverage, interpreter, and runner sequencing hardening

- **Scope**: Make main-loop attribution CWD-independent, enforce non-vacuous goal declarations on every completion path, close both `Consiliency/agent-harness#241` login-shell bypass classes, and add the capability marker plus validation for the external-coordinator checkpoint/fresh-process/post-suite lifecycle.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/runtime_paths.py`, `phase-loop-runtime/src/phase_loop_runtime/reconcile.py`, `phase-loop-runtime/src/phase_loop_runtime/goal_coverage.py`, `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py`
- **Interfaces provided**: `path-and-verification-hardening`, `HARDEN-capability-v1`, `external-coordinator-checkpoint-validation`, `external-coordinator-transition-validation`, `runner-owned-run-dir-export`, `runner-owned-post-suite-reduction`
- **Interfaces consumed**: `HARDEN-test-freeze`, `HARDEN-TDD-activation-contract`, `HARDEN-node-partition-contract`, `HARDEN-RED-evidence`, `HARDEN-post-suite-sequencing-contract`
- **Parallel-safe**: yes
- **Tasks**:
  - test: Confirm the `SL-2.1` reconcile, goal, interpreter, and runner-sequencing selectors remain frozen from `SL-0`.
  - impl: Implement CWD-independent attribution, enforced goal coverage, interpreter guards, the production capability marker, coordinator-transition validation, run-directory export, and post-suite sequencing in `SL-2.2`–`SL-2.5`.
  - verify: Run only the exact 7-node `SL2_NODEIDS` partition that `SL-2` can make green in `SL-2.6`; keep all 4 `SL3_EVIDENCE_NODEIDS` RED until `SL-3.2` creates their executable.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-2.1 | test | — | all `SL-0` reconcile, goal, interpreter, and evidence-verifier test paths, read-only | frozen 7-node `SL2_NODEIDS` partition and still-RED 4-node `SL3_EVIDENCE_NODEIDS` partition | Confirm every selector, partition, and blob ID is unchanged from the `SL-0` commit before implementation. |
| SL-2.2 | impl | SL-2.1 | `phase-loop-runtime/src/phase_loop_runtime/runtime_paths.py`, `phase-loop-runtime/src/phase_loop_runtime/reconcile.py` | CWD-independent attribution | Require persisted repo/roadmap identity fields to be absolute before matching; retain relocated absolute-root equivalence only through identical repo-relative roadmap subpaths and existing SHA provenance. Resolve relative `automation.artifact` against the trusted absolute stored repo, never ambient CWD; reject escape, tilde, symlink-rebind, malformed, and mismatched identities without crashing the main loop. |
| SL-2.3 | impl | SL-2.1 | `phase-loop-runtime/src/phase_loop_runtime/goal_coverage.py`, `phase-loop-runtime/src/phase_loop_runtime/runner.py` | enforce completion matrix | Return a typed declaration state that distinguishes declared IDs, syntactically valid all-bare legacy, zero match, ambiguous match, parse failure, and missing plan. Warn/default mode is the only nonblocking legacy path. Under `PHASE_LOOP_ACCEPTANCE_ENFORCE=block`, every state with zero declared EC-IDs—including valid all-bare legacy—and every ambiguous, unparseable, or missing-plan state returns non-human `contract_bug` at preflight, canonical closeout, delegated/resume completion, and missing-plan closeout. Distinct classification must never become an enforce pass-through. |
| SL-2.4 | impl | SL-2.1 | `phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py` | Bash/profile bypass matrix | Model and consume `-o option-name`, `+o option-name`, `-O shopt-option`, `+O shopt-option`, `--rcfile file`/`--rcfile=file`, and `--init-file file`/`--init-file=file` before locating the true `-c`; preserve combined login flags; fail closed on missing option arguments, ambiguous `--`, or an unlocatable payload. Under patch-level bounds, conservatively shadow nominal version names absent at resolve time so a profile cannot introduce an unsupported patch after shim construction; emit a clear warning for the conservative block. |
| SL-2.5 | impl | SL-2.1 | `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py` | capability activation, external checkpoint/transition validation, run-dir export, post-suite reduction, and final audit | Install literal `HARDEN_CAPABILITY_VERSION = 1` in `verification_evidence.py`; this is the only production activation read by the frozen guard. Parse the HARDEN lifecycle/post-suite contract separately from `## Verification` and `automation.suite_command`. Do not make the implementation child or already-loaded parent commit, push, author a checkpoint/transition, reload, self-reexec, attest changed bytes, or complete. On a fresh repo-local `resume`, accept only the exact external-coordinator-authored transition path supplied in non-secret `PHASE_LOOP_HARDEN_COORDINATOR_TRANSITION`; require it beneath canonical `.phase-loop/runs/`, then recompute its coordinator executable/package identity, actual checkpoint `C`, direct-child candidate `I`, exact staged path sets and residual hashes, clean checkpoint/final worktree/process results, pre/post Git identities, remote candidate object, plan/roadmap/manifest/test digests, implementation launch PID/times/artifact hashes, rejected false-complete/reopen record, and old-process death. Fail closed unless the coordinator package root is outside the worktree, `C` and `I` have the required ancestry/tree/path shapes, the candidate worktree is clean, local HEAD equals fetched remote `I`, loaded repo-local `cli.py`/`advisor_board/composition.py`/`panel_invoker.py`/`runner.py`/`verification_evidence.py`/verifier/launcher hashes equal Git blobs at `I`, and candidate PID/start nonce differs from coordinator, implementation, and checkpoint processes. Before invoking any extracted command or `automation.suite_command`, set `PHASE_LOOP_RUN_DIR` explicitly in the subprocess environment to the current runner-owned artifacts root and derive `PHASE_LOOP_HARDEN_PURE_JUNIT` only from the validated transition stage: `harden-pure-control-candidate.xml` at candidate `I` or `harden-pure-control-main.xml` at canonical `M`; reject an operator/model-supplied alternate basename and never infer either path from CWD. Candidate audit stops nonterminal; a separately launched exact-`M` process validates a coordinator-authored post-landing transition the same way. Persist process identities, transition/argv/exit data, and verification/log/JUnit/checklist/panel/evidence paths and hashes in parent-owned metadata. Treat missing/child-authored/stale checkpoint or transition, synthetic/laundered ancestry, same-process cycle, stale/wrong head/module, pre-seal call, missing output, forged hash/identity, non-zero reducer, or audit mismatch as non-human `repeated_verification_failure`. |
| SL-2.6 | verify | SL-2.2, SL-2.3, SL-2.4, SL-2.5 | all `SL-2` owned source paths and frozen `SL-0` tests read-only | exact 7-node non-evidence `SL-2` partition | Set `PHASE_LOOP_TDD_EXPECT_HARDEN=1`, import literal `SL2_NODEIDS` from the frozen guard, and invoke pytest with exactly those 7 nodeids plus `--junitxml=<checkpoint-run-dir>/harden-sl2.xml`. Require set equality with the two reconcile nodeids, four goal nodeids (two migrated plus two new), and one interpreter nodeid; JUnit must report exactly 7 passed, zero skipped/xfailed/errors. Do not run or require any `SL3_EVIDENCE_NODEIDS` in this command: the external coordinator's clean exact-`C` process runs those four separately and requires intended RED because `verify_harden_evidence.py` is absent from `C`. Exact-`I` and exact-`M` remove the environment variable and prove production-marker activation. |

### SL-3 — Fresh-process candidate/post-landing evidence and documentation reducer

- **Scope**: Admit the quarantined HARDEN chronology/evidence executable and changelog only after an actual clean `SL-1`+`SL-2` checkpoint proves 115 + 7 green and exact 4 RED, then prove all 126 frozen nodes green at a new clean direct-child head and let the immutable external coordinator drive push plus fresh candidate/post-landing verification.
- **Owned files**: `phase-loop-runtime/scripts/verify_harden_evidence.py`, `CHANGELOG.md`
- **Interfaces provided**: `HARDEN-closeout-evidence`, `HARDEN-no-spec-delta`
- **Interfaces consumed**: `HARDEN-test-freeze`, `HARDEN-TDD-activation-contract`, `HARDEN-node-partition-contract`, `HARDEN-RED-evidence`, `review-isolation-boundary`, `trusted-provider-control-plane`, `four-seat-isolated-panel`, `review-fleet-checklist-evidence`, `path-and-verification-hardening`, `HARDEN-capability-v1`, `external-coordinator-checkpoint-validation`, `external-coordinator-transition-validation`, `runner-owned-run-dir-export`, `runner-owned-post-suite-reduction`
- **Parallel-safe**: no
- **Tasks**:
  - test: After the implementation child exits without committing, let only the external coordinator create actual checkpoint `C` from the exact `SL-1`+`SL-2` staging set and prove 115 + 7 green plus the exact 4 evidence nodes RED and the separate exact 54 pure controls GREEN from a clean exact-`C` worktree/process in `SL-3.1`.
  - impl: After that checkpoint proof, admit only the already-written, digest-quarantined verifier and changelog into direct-child commit `I` in `SL-3.2`–`SL-3.3`; do not let the coordinator rewrite their bytes.
  - verify: From a new clean exact-`I` worktree/process with environment activation absent, run the exact all-126/zero-skip gate plus a distinct exact-54 pure-control gate in `SL-3.4`, then let only the external coordinator push and repeat both focused and pure-control proofs at candidate `I` and canonical `M`—including the isolated exact four-seat panels—in `SL-3.5`–`SL-3.6`.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-3.1 | test | SL-1.8, SL-2.6 | `phase-loop-runtime/tests/harden_tdd_guard.py`, `phase-loop-runtime/tests/test_harden_evidence_verifier.py` (read-only) | exact checkpoint 115-green + 7-green + 4-RED plus exact-54 pure proof | After the GPT-5.6 Terra implementation child has written every `SL-1`–`SL-3` owned path and the pre-change runtime/child have exited without a commit, the external coordinator records the complete dirty path/digest set. It first proves `plans/manifest.json` is clean, equals the server-landed executing-control blob descended from `L`, and is absent from the dirty and cached sets. It stages only the literal eighteen `SL-1`+`SL-2` source paths enumerated below, proves the cached path set equals the recorded changed subset and excludes all `SL-0`, `SL-3`, lifecycle-control, and unowned paths, and creates actual checkpoint commit `C` directly atop the fetched post-tests target `T`. The original implementation worktree must then retain exactly the two unchanged, digest-matched `SL-3` residual paths and no other Git-visible dirt; `plans/manifest.json` is not a third residual. In a separate clean detached exact-`C` worktree and fresh process, set `PHASE_LOOP_TDD_EXPECT_HARDEN=1`; run exact `SL1_NODEIDS` and require 115 passed/0 skipped, exact `SL2_NODEIDS` and require 7 passed/0 skipped, then exact `SL3_EVIDENCE_NODEIDS` and every frozen case and require intended assertion RED with zero skip/xfail/collection/import/setup/teardown errors. The `SL-1` result contains all 100 execution-affecting public migrations, the execution arms of the 20 overlaps, the two new refusal/fixture nodeids, both ordering nodeids, and complete CLI/live-default/denial/invoker traces; it does not claim the 34 pure-only nodes outside the phase inventory. In another distinct exact-`C` subprocess with activation retained and `PHASE_LOOP_HARDEN_PROOF_MODE=pure_control`, run exactly literal `PURE_CONTROL_NODEIDS` and write `harden-pure-control-c.xml`; require 54 passed once each, including every overlap pure arm, with zero effects/skips/xfails/errors. Bind both subprocesses to exact `C`, the frozen guard/test blobs, argv and XML digests; reject collection-derived selectors or any focused/broad XML substitution. Prove `verify_harden_evidence.py` is absent from tree `C`. Child checks, the dirty original worktree, and the already-loaded pre-change runtime cannot satisfy this gate. |
| SL-3.2 | impl | SL-3.1 | `phase-loop-runtime/scripts/verify_harden_evidence.py` | candidate/post-landing chronology and evidence verifier | Preserve the child-written script bytes and pre-checkpoint digest without coordinator edits. After the clean exact-`C` proof passes, stage this path together with `CHANGELOG.md` and create direct-child commit `I`. The executable has an explicit `--lifecycle-stage candidate|post_landing`; both stages require parent-supplied run directory, sealed `verification.json`, structured broad-suite, exact-126 focused, and dedicated exact-54 pure-control JUnit, runner-reduced fleet checklist, output path, plan, roadmap, phase, repository, external coordinator transition, isolated four-seat panel record, exact checkpoint/final commit trees, and exact process/head/module identities. Candidate mode writes only `harden-candidate-evidence.json`; post-landing mode additionally requires and revalidates candidate evidence/hashes and writes only final `harden-evidence.json`. It derives Git/forge ancestry, exact `L -> T -> C -> I` commit/path shapes, the normal executing lifecycle event and clean landed manifest blob, ordered control/tests/implementation PR-merge parents, path ownership, manifest state, both nodeid contracts, five stage-specific pure-control proofs, transition authorship/identity, all four isolated-seat attestations, and route-checklist evidence; exits non-zero with typed findings for any missing, mismatched, substituted/reused XML, child/self-reported-only, stale-process/run/head, synthetic/laundered checkpoint, one-parent/squash/rebase merge, unisolated/excluded panel seat, or forged obligation; and never discovers another run, trusts CLI booleans/counts, infers selectors from collection, runs as an ordinary suite command, amends `verification.json`, or writes tracked files. |
| SL-3.3 | impl | SL-3.1 | `CHANGELOG.md` | Unreleased note | Preserve the child-written changelog bytes and pre-checkpoint digest without coordinator edits; stage it only with `verify_harden_evidence.py` after `SL-3.1`. Its concise Unreleased note covers contained review staging/fleet isolation, isolated four-seat subscription panels, CWD-independent reconcile attribution, non-vacuous enforce goal coverage, and login-shell interpreter hardening. Do not edit roadmap/spec/contract/version/release-pin surfaces. |
| SL-3.4 | verify | SL-3.2, SL-3.3 | all phase-owned paths and frozen `SL-0` tests, read-only | exact all-126 plus exact-54 pre-push gate | Require `I` to be an actual commit with sole parent `C`, cached/residual admission exactly `{phase-loop-runtime/scripts/verify_harden_evidence.py, CHANGELOG.md}`, and no amendment, rebase, squash, cherry-pick, stash/patch replay, replacement ref, synthetic `commit-tree`, or history rewrite. In a new clean detached exact-`I` worktree/process—not the dirty original, child, pre-change runtime, or exact-`C` process—remove `PHASE_LOOP_TDD_EXPECT_HARDEN`, assert `HARDEN_CAPABILITY_VERSION == 1`, import literal `EXPECTED_PHASE_NODEIDS`, and invoke pytest with exactly those 126 nodeids plus `--junitxml=<coordinator-run-dir>/harden-phase-focused.xml`. Require exact partition equality `115 + 7 + 4 = 126` and JUnit exactly 126 passed, zero skipped/xfailed/errors. In a distinct subprocess at the same exact `I`, keep the activation variable absent, set only `PHASE_LOOP_HARDEN_PROOF_MODE=pure_control`, pass exactly literal `PURE_CONTROL_NODEIDS`, and write `harden-pure-control-i.xml`; require exact 54 passed and bind its argv/head/process/guard/XML identities separately from the focused proof. Only both clean exact-head results authorize push/transition. A failure returns to the GPT-5.6 Terra child for a fresh dirty output and restarts the actual `C`/`I` chronology; no partial green, broad-suite substitution, reused XML, worktree, or process is admissible. |
| SL-3.5 | verify | SL-3.4 | all phase-owned paths plus coordinator and candidate runner evidence, read-only | externally pushed candidate and fresh exact-candidate proof | After `SL-3.4` passes, the external coordinator—not the child or old runtime—pushes exact `I`, verifies the remote object, records/rejects any old-runtime false `complete`, reopens it with the existing `phase-loop reopen` command after the tree is clean, proves old PIDs/locks gone, and writes the run-owned external transition binding `T`, `C`, and `I`. It launches a distinct repo-local process with `PYTHONPATH=phase-loop-runtime/src` at exact clean fetched `I` and the exact transition path. That process validates and copies the transition into its run-owned input area, exports its run dir, runs every ordinary verification command, exact 126 focused tests, the broad suite, and a distinct exact 54 `PURE_CONTROL_NODEIDS` command writing `harden-pure-control-candidate.xml`; it seals all three JUnit classes plus `verification.json` and enters a bounded fail-closed `awaiting_external_review` wait without exiting or changing HEAD. The pure command has activation absent, proof mode set, exact tuple argv, and independent path/digest/head/process bindings. The coordinator then starts the exact-`I` repo-local isolated-panel boundary: all four Fable/Sol/Gemini/Grok seats receive only immutable staged exact-`I` inputs, run their direct mutation/credentialed-side-effect probes, and perform intended inference only through their supported parent-broker adapters. The sealed panel record cross-links the four supported fleet-checklist rows and is written into the candidate run's declared input path. The same still-live candidate process validates it, reduces/audits candidate evidence, records nonterminal `candidate_audit=passed`, and exits. Timeout, wrong writer/path/digest, XML substitution/reuse, process exit, changed HEAD, direct legacy panel launch, missing/refused/excepted seat, or failed boundary/broker/probe attestation fails. Any change or material finding invalidates `I` and restarts the actual `C`/`I` chronology; merge is forbidden until this gate passes. |
| SL-3.6 | verify | SL-3.5 | all phase-owned paths plus candidate and canonical-main runner evidence, read-only | exact two-parent landing, fresh canonical-main proof, and strict completion-control topology | The external coordinator merges only exact reviewed `I` with the required two-parent topology, proves the candidate process exited, fetches server canonical main `M`, prepares an exact clean worktree, and writes a post-landing transition. It starts another distinct repo-local process at `M` with modules loaded from `M`. Repeat manifest/plan/roadmap validation, environment-activation-absent exact 126-node focused and broad compatible suites, the separate marker-activated exact 54 `PURE_CONTROL_NODEIDS` run writing `harden-pure-control-main.xml`, Ruff, and the mandatory exact-`M` receipt-bearing review wave through the exact-`M` repo-local isolated-panel boundary with four direct mutation/credentialed-side-effect probes and supported broker rows. The usable early Codex preflight/prompt/native/CLEAR artifact and receipt are staged in the exact immutable Option-2 bundle before all critics; every critic consumes that same bundle read-only by reference through its own preflight/prompt/native/reducer chain; Fable starts only after all critics complete and binds through its prompt/native report chain; and any contradiction or material finding invalidates every AGREE and repeats the entire early-prover/critics/Fable wave with a changed bundle. Then run post-suite fleet/final reduction and parent audit. Focused JUnit contains all 126 frozen nodeids exactly once with zero skipped; pure-control JUnit separately contains exactly the literal 54 once each and has a distinct path/digest, exact-`M` process/head binding, proof mode, and zero effects/skips/xfails/errors. Only after closing every retained-reference descriptor and independently recomputing containment, bytes, hashes, canonical JSON, common base/bundle, prompt-bound lens/seat/bundle, native citations, total status/outcome mapping, producer identity, status/raw text, exact terminal/non-elision facts, chronology, roles, restart semantics, typed effective parameterized policy, usable Sol/Fable `AGREE`, and Fable-only binding may this process authorize the normal completed lifecycle append carrying the exact nested `v10.phase-completion-landing.v1`/`v10.review-wave-receipt.v1` contract. It first verifies the lifecycle-control, tests-only, and implementation ordered two-parent PR merges, actual `L -> T -> C -> I` ancestry, both isolated exact-head panels, and the complete lifecycle below. Terminal `complete` remains withheld until the external coordinator creates single-parent `FH`, lands ordered `[M,FH]` manifest-only `F`, reopens the event from `M`/`FH`/`F`/fetched main, and proves every non-manifest blob is identical to audited `M`. |

The coordinator's checkpoint staging command names exactly these eighteen
`SL-1`+`SL-2` source paths and no glob:

- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/__init__.py`
- `phase-loop-runtime/src/phase_loop_runtime/cli.py`
- `phase-loop-runtime/src/phase_loop_runtime/launcher.py`
- `phase-loop-runtime/src/phase_loop_runtime/injection.py`
- `phase-loop-runtime/src/phase_loop_runtime/harness_env_signatures.py`
- `phase-loop-runtime/src/phase_loop_runtime/capability_registry.py`
- `phase-loop-runtime/src/phase_loop_runtime/claude_channel_sidecar.py`
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/backing.py`
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py`
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/config.py`
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/presets.py`
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/resolver.py`
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- `phase-loop-runtime/src/phase_loop_runtime/runtime_paths.py`
- `phase-loop-runtime/src/phase_loop_runtime/reconcile.py`
- `phase-loop-runtime/src/phase_loop_runtime/goal_coverage.py`
- `phase-loop-runtime/src/phase_loop_runtime/runner.py`
- `phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py`

Before staging, the coordinator records the changed subset and SHA-256 for every
phase-owned dirty path. It separately proves `plans/manifest.json` is clean,
matches the server-landed `L` descendant blob, and is absent from both dirty
and cached sets. It invokes `git add --` with only the eighteen literals, then
requires the cached name set to equal the previously recorded changed subset
within that exact list. It refuses an empty checkpoint, a cached
`SL-0`/`SL-3`/lifecycle-control/unowned path, an unstaged changed
`SL-1`/`SL-2` path, or any manifest delta. Commit
`C` has sole parent `T`, the fetched target head containing the two-parent tests
merge. After `C`, porcelain status in the implementation worktree must name
exactly `phase-loop-runtime/scripts/verify_harden_evidence.py` and
`CHANGELOG.md`; their bytes and hashes must equal the child-exit record, and the
manifest must remain clean. Ignored
run-owned `.phase-loop/` evidence stays outside Git and is bound separately.
The detached checkpoint worktree is created from commit `C`, is clean before
and after its proof, cannot see the original worktree's two residual paths, and
is removed only after its process exits and evidence is sealed.

Only after `SL-3.1` passes may the coordinator invoke `git add --` with exactly
the verifier and changelog literals. The cached name set must equal those two
paths, the bytes must still match the child-exit hashes, and direct-child commit
`I` must have sole parent `C`. The coordinator never amends either commit and
never uses rebase, squash, cherry-pick, stash/patch replay, replacement refs,
`commit-tree`, or another synthetic-history mechanism to manufacture the
intermediate state. Both clean proof worktrees are materialized from real
commits; no dirty-tree checkout, index-only tree, file hiding, or post-hoc
history rewrite can satisfy the chronology.

`verify_harden_evidence.py` accepts only the fresh parent process's canonical
current HARDEN run directory and parent-materialized inputs beneath it. It never
discovers another run or trusts a path, count, digest, boolean, process identity,
or Git/forge identity supplied only by model output. Candidate and post-landing
stages must jointly prove all of the following from Git, server-returned forge
metadata, process startup records, and sealed runner artifacts:

1. The exact plan digest received an external-coordinator four-vendor
   true-by-reference phase-plan review with Fable and Sol usable, four actual
   reviewing seats, API-key fallback disabled, and no unresolved material
   finding. The exact test/guard digest received the same governance panel
   before tests landed. These pre-implementation records precede the HARDEN
   boundary and therefore do not appear in the route registry/checklist or
   satisfy `EC-HARDEN-5`; they cannot substitute for either isolated exact-head
   panel.
2. The unique HARDEN row in `plans/manifest.json` passes structural and
   per-entry validation and exactly names this plan, phase, roadmap, and
   `SL-0`–`SL-3`. It searches every lifecycle event for either
   `harden_plan_contract_record_id` or `harden_plan_contract`, requires exactly
   one contract-bearing event, and requires identity
   `v10-HARDEN.harden-plan-contract.v1`; it never reads the contract by latest
   event position. The sealed immutable payload binds the current plan and
   current roadmap digests; 46 owned, 26 tests-only, and 18 checkpoint paths
   plus their sorted-newline SHA-256 values; the 126-node inventory digest and
   exact 115/7/4 partition; the two pre-auth ordering nodeids, public-corpus,
   literal 100 execution / 54 pure / 20 overlap / 134 union tuple counts and
   digests, their exact set equations, 34 pure-only difference, and the five
   required pure-control proof stages; Terra whole-phase
   authorship; both schedulers off; subscription-only auth; and no release/tag.
   The normal `executing` event is later, carries only the exact executor run
   metadata, and is landed in `L` before tests branch creation. Malformed JSON,
   a bad sibling row, missing/duplicate/conflicting HARDEN row, a missing,
   duplicate, malformed, identity-conflicting, or payload-drifted
   contract-bearing record, stale file/alias/roadmap/lane metadata,
   count/digest drift, an invalid lifecycle sequence/status/timestamp, or a
   plan digest still bound to the latest-panel `DISAGREE` bytes is a typed
   failure. The byte-identical contract lookup appears in both frontmatter and
   `## Verification`; its sealed result is required at the clean checkpoint,
   pre-push, candidate, exact-`M`, and terminal-control heads.
3. `harden_tdd_guard.py` and all 26 sealed tests-only paths have the landed
   tests-only blob IDs. The guard's literal inventories are exactly 126 expected
   nodeids, partitioned without overlap as `SL1_NODEIDS=115`,
   `SL2_NODEIDS=7`, and `SL3_EVIDENCE_NODEIDS=4`, plus 21 default skips and 105
   migrated branches. The tests-only default JUnit is exactly 105
   passed/21 skipped with the exact skip set. Activated RED collection is the
   same 126; every nodeid
   and every frozen case has intended assertion-failure raw output and JUnit
   with zero skip/xfail/collection/setup errors. A clean exact-`C` process with
   `PHASE_LOOP_TDD_EXPECT_HARDEN=1` records `SL-1.8` as exactly 115 green,
   `SL-2.6` as exactly 7 green, and `SL-3.1` as the exact 4 RED while the
   executable is absent from tree `C`. The preimplementation RED process and
   exact-`C` process separately run literal `PURE_CONTROL_NODEIDS` and seal
   `harden-pure-control-red.xml` and `harden-pure-control-c.xml`, each with
   exactly 54 passed once, no skip/xfail/error, proof mode set, and zero effect
   canaries. Only a distinct clean exact-`I` process, after direct-child commit
   `I` introduces the executable, records all 126 green with the environment
   activation absent and separately seals `harden-pure-control-i.xml` with the
   exact 54. Candidate and post-landing focused JUnit each repeat the same 126
   exactly once, all passed, zero skipped, with the environment activation
   absent and production marker present; their fresh processes also create
   distinct exact-54 `harden-pure-control-candidate.xml` and
   `harden-pure-control-main.xml`. Every pure XML is bound to its exact head,
   process, argv, guard/test blobs, tuple digest, and lifecycle stage and must
   differ in path and digest from focused and broad XML.
4. Server-returned forge metadata identifies distinct tests-only and
   implementation PR numbers/head branches, plus the distinct runner-owned
   lifecycle-control PR, and records repository, URL,
   target/base/head refs and object IDs, reviewed heads, states, merge commits,
   and lifecycle times. The lifecycle-control PR changes only
   `plans/manifest.json` by the exact `update_lifecycle` executing delta and
   lands as `L` before the tests branch exists. The tests branch is created
   from the fetched post-`L` target. The implementation remote branch did not
   exist before the tests PR merged and was created only from the fetched
   post-test target head after activated RED passed.
5. Ordered two-parent topology is exact, not merely reachability. Let `B` be the
   lifecycle-control PR target object, `LH` its manifest-only reviewed head,
   and `L` its merge commit; `git cat-file`/forge metadata must prove `L` has
   exactly ordered parents `[B, LH]`, `B..LH` changes only
   `plans/manifest.json`, and that blob is exactly the allowed committed →
   executing API delta. Let `TH` be the tests PR reviewed head and `TM` its
   merge commit;
   `git cat-file`/forge metadata must prove `TM` has exactly ordered parents
   `[L, TH]`. Let `T` be the fetched post-tests target/implementation branch
   point, `C` the actual checkpoint whose sole parent is `T`, and `I` the
   reviewed/pushed direct child whose sole parent is `C`. Tree `C` contains
   exactly the changed `SL-1`+`SL-2` paths and no `SL-0`/`SL-3` change; the
   `C..I` range contains exactly the verifier and changelog. Let `P` be the
   server canonical-main object immediately before implementation merge and
   `M` the server-recorded merge/canonical-main head; `M` must have exactly
   ordered parents `[P, I]`. Squash, rebase, octopus, synthetic replacement,
   rewritten checkpoint, reversed/wrong parents, or a later main head fails.
   After the exact-`M` final audit, let `FH` be the closeout-control branch
   commit whose sole parent is `M` and whose sole change is the exact executing
   → completed `update_lifecycle` delta with the strict completion payload, and
   `F` the server closeout-control merge; `F` has
   exactly ordered parents `[M, FH]`, differs from `M` only in
   `plans/manifest.json`, and preserves every runtime, test, plan, roadmap, and
   phase-owned blob from `M`. The event is absent at `M`, added exactly once at
   `FH`, and byte-semantically identical at `FH`, `F`, and fetched main.
   `L` and `TM` are ancestors of `T`, `C`, `I`, `P`, and `M`. The actual
   implementation PR range is derived from server identities; it and the forge
   file set contain no `SL-0` path, tests-only commit, or manifest-control
   change, and every frozen test/guard blob remains identical. A
   `base -> tests -> implementation`
   branch whose PR targets the pre-test base fails even if the tests commit is
   elsewhere in the head ancestry.
6. Lifecycle order is strict and digest-bound:
   coordinator identity freeze → external phase-plan panel → external
   manifest pre-image freeze → normal executor `executing` append → exact
   manifest-only control PR merge `L` → clean post-`L` target → external
   tests/guard panel → tests PR merge `TM` → default 105-pass/21-skip proof →
   activated raw 126-node RED completion → exact-54 pure-control RED-stage
   GREEN proof → implementation branch creation →
   GPT-5.6 Terra implementation child writes all owned paths under manual
   closeout and exits without commit → old runtime exit/false-complete rejection
   → coordinator records dirty paths/hashes → coordinator stages the exact
   `SL-1`+`SL-2` set and commits actual checkpoint `C` → clean exact-`C` process
   records 115-node `SL-1` green, including the complete public-API migration
   and pre-auth ordering → 7-node `SL-2` green → exact evidence 4 RED with
   verifier absent → distinct exact-54 pure-control `C` proof GREEN →
   coordinator stages only unchanged verifier/docs and commits direct-child
   `I` → distinct clean exact-`I` process records all 126 green and distinct
   exact-54 pure controls GREEN with environment activation absent →
   coordinator push/remote proof and
   external transition write → distinct repo-local candidate process startup at
   `I` → candidate manifest/focused/broad/exact-54-pure/Ruff seal → isolated exact-`I`
   Fable/Sol/Gemini/Grok panel with four supported checklist rows and direct
   probes → candidate reduction/audit → candidate process exit →
   coordinator-owned implementation PR merge `M` → distinct post-landing
   process startup at `M` → post-landing manifest/focused/broad/exact-54-pure/Ruff seal →
   isolated exact-`M` four-seat panel with the same boundary → final
   reduction/audit → exact manifest-only completed-control PR merge `F` →
   terminal `complete`. Each event carries
   coordinator-observed time, prior-event hash, plan/test/checkpoint/candidate
   digest, and server object IDs; absent, duplicate, out-of-order, or post-dated
   evidence fails.
7. The immutable external coordinator, implementation launch, checkpoint
   verifier, exact-`I` pre-push verifier, candidate verifier, and post-landing
   verifier have distinct recorded PID/start nonce values. The coordinator
   record proves its console script and imported
   package root are outside the HARDEN worktree and byte-identical from initial
   dispatch through final audit. The implementation launch record comes only
   from existing `launch.json`/terminal/event artifacts and is never a handoff.
   The checkpoint process starts/ends clean at exactly `C`; the pre-push and
   candidate processes start/end clean at exactly `I`; the post-landing process
   starts/ends clean at exactly `M`. Their repo-local `cli.py`, `runner.py`,
   `verification_evidence.py`, verifier, launcher, capability registry, Advisor
   Board composition, and panel-invoker boundary bytes hash to the corresponding
   Git blobs. Any old-runtime terminal `complete` after
   changed imported bytes is explicitly rejected and manually reopened; a
   process that changes/checks out a new head after startup exits and can attest
   neither head.
8. All test/source/script/changelog changes use the one coordinator-recorded
   Codex GPT-5.6 Terra author vendor. The broad compatible suite, separate
   exact-54 pure-control command, and all ordinary verification commands
   seal green before either isolated exact-head implementation panel.
   Author-vendor seats are advisory only and the non-author seats satisfy
   governed quorum. A finding/fix invalidates `C`, `I`, their clean-process
   results, seal/panel/audit, and forces the Terra child plus the full
   actual checkpoint/direct-child chronology to restart.
9. The launcher-owned immutable-snapshot manifest covers the exact candidate or
   canonical-main Git tree and every approved context ref, preserves logical
   labels, and proves source/destination path, kind, bytes, and SHA-256 equality.
   Positive controls for every mandatory seat open candidate code and context
   refs only through rewritten contained `/review` paths; negative controls
   prove live originals unreachable and unmodifiable. The review-leg namespace
   has read-only tools, no direct network, credentials, privileged side-effect
   capability, or host escape. `context_refs`, prompts, CLI flags, staged CWD,
   naming, and tool allowlists cannot populate the boundary attestation.
10. Every normalized live product-plus-advisor review route has exactly one
    runner-observed posture: supported executable, refused prelaunch, or
    nonlaunch. The supported credentialless command route carries the exact
    `linux_bwrap_v1` mount/namespace/env/probe/cleanup attestation. Fable, Sol,
    Gemini, and Grok are four mandatory supported executable rows; each carries
    the same review-leg attestation, its exact `parent_unix_broker_v1` adapter
    proof, direct mutation/credentialed-side-effect probes, intended-inference
    RPC evidence, and candidate/main panel cross-link. The provider
    subscription auth/transport stays in the trusted coordinator/parent control
    plane and is never review-leg capability. Refused routes prove zero auth
    lookup, session, broker connection, child, and side effect. Checklist and
    registry keys are exactly equal. Refusal satisfies the safety invariant
    only because the route did not execute; it never counts as supported-route
    conformance. A mandatory seat that is refused, excepted, relabeled, absent,
    or launched directly through the legacy subprocess route leaves
    `EC-HARDEN-5` UNMET.

Candidate mode writes only
`.phase-loop/runs/<candidate-run-id>/harden-candidate-evidence.json`; post-landing
mode writes only `.phase-loop/runs/<main-run-id>/harden-evidence.json`. Each
fresh parent creates its own `harden-compatible-suite.xml`,
`harden-phase-focused.xml`, stage-specific `harden-pure-control-*.xml`,
`harden-fleet-checklist.json`, verification artifact, and parent audit record.
The post-landing parent copies the candidate evidence and coordinator transition
into its run-owned input area only after verifying the coordinator/candidate
recorded SHA-256 values, then revalidates all candidate bytes and server
identities. Missing evidence is a failed criterion, never an operational
exemption.
`Consiliency/agent-harness#361` may record a standing residual but cannot turn
`EC-HARDEN-5` green.

## Fresh-Process Exact-Head Verification and Landing

This is an immutable external-coordinator protocol with one pre-change
implementation runtime, one clean exact-`C` checkpoint verifier process, one
clean exact-`I` pre-push verifier process, and two sealed repo-runtime processes
at exact `I` and exact `M`. The external coordinator is the roadmap-owned v10
control process, not a new HARDEN executable. It uses existing installed
surfaces: `codex-phase-loop --version`, `run/resume --closeout-mode manual`,
`state --json`, `monitor --once --json`, `reopen --reason`, canonical
`.phase-loop/runs/**` launch/heartbeat/terminal artifacts, ordinary Git
commits/worktrees, Git/forge metadata, and the Advisor Board
`PanelRequest.context_refs` API. No current runner pause is assumed: current
ordinary execution writes all lanes before phase verification, so the
coordinator creates and verifies the real intermediate commit after the child
exits. Its resolved console script and imported package files are outside the
worktree and digest-frozen before dispatch. `automation.suite_command` and
commands extracted from `## Verification` are pass-1 verification; no ordinary
command may invoke `verify_harden_evidence.py`, read an unsealed current-run
artifact, or claim post-suite output as suite evidence.

0. **Land the normal lifecycle append before lane work.** After validating the
   plan, proving the clean manifest pre-image is row-stable under the production
   serializer, and passing the disposable exact
   `committed -> executing -> completed` simulation with zero sibling drift, the
   installed executor calls
   `update_lifecycle()` once for slug `v10-HARDEN`, transition `executing`,
   writer `codex-execute-phase`, and exact metadata
   `{"run_id": <run-id>, "phase_alias": "HARDEN"}`. Before any `SL-0` file is
   written, the coordinator requires `plans/manifest.json` to be the sole dirty
   path and validates the parsed/canonical delta against the API: only the
   unique HARDEN row status, updated timestamp, and one appended event may
   differ; the previous lifecycle prefix, stable contract-bearing record, all
   other HARDEN fields, and every sibling row are unchanged. It commits only
   that path on a separate control branch, opens and merges a distinct
   two-parent manifest-only PR as `L`, fetches the exact target, and proves a
   clean tree whose manifest blob equals `L`. The tests branch is created only
   from that post-`L` target. No lane or Terra child owns this transition, and
   no allowlisting of later manifest dirt is permitted.

1. **One child, no self-attestation.** The external coordinator launches exactly
   one GPT-5.6 Terra implementation process through the already-installed
   pre-change runtime with `--closeout-mode manual`, `--lane-scheduler off`, and
   `--phase-scheduler off`.
   That runtime does not export `PHASE_LOOP_RUN_DIR`, so the frontmatter
   command's explicit `mktemp` fallback is bootstrap-only and never lifecycle
   evidence. The child writes all `SL-1`, `SL-2`, and `SL-3` owned paths, runs
   useful diagnostic checks, and exits. It must not commit, stage for the
   coordinator, push, transition, attest, panel, merge, or complete. Neither its
   checks nor the already-loaded runtime can satisfy the 115/7/4 chronology.
2. The coordinator waits for the installed runtime and implementation child to
   exit and proves their PID/process-group/locks are gone. Any old-runtime
   terminal `complete` is classified `false_complete_rejected` because its
   imported runner/reducer identities predate the dirty output. It validates
   frozen `SL-0` blobs, proves the manifest is clean and equal to the landed
   `L`-descended executing blob, and records the exact phase-owned dirty
   path/digest set. Using only
   the eighteen literal source paths above, it stages the recorded changed
   `SL-1`+`SL-2` subset and creates actual checkpoint commit `C` with sole parent
   `T`; all `SL-3` bytes remain unchanged and dirty in the original worktree.
   It creates a separate clean detached exact-`C` worktree and starts a fresh
   process there. With `PHASE_LOOP_TDD_EXPECT_HARDEN=1`, that process runs exact
   115 green, exact 7 green, and exact 4 intended RED, proves the verifier absent
   from `C`, then runs a distinct subprocess with
   `PHASE_LOOP_HARDEN_PROOF_MODE=pure_control` and literal
   `PURE_CONTROL_NODEIDS`, seals `harden-pure-control-c.xml` with exactly 54
   passed and independent argv/head/process/guard/XML bindings, and exits. The
   original dirty tree, implementation child, and old runtime are never
   evidence sources for this gate.
3. Only after the exact-`C` proof passes, the coordinator verifies that the
   original worktree's only Git-visible dirt is the unchanged verifier and
   changelog and that `plans/manifest.json` is clean at the landed executing
   blob. It stages exactly those two literals and creates actual commit `I`
   with sole parent `C`. A new clean detached exact-`I` worktree and new process
   remove `PHASE_LOOP_TDD_EXPECT_HARDEN`, assert the production capability
   marker, and prove exact all-126/zero-skip plus a distinct marker-activated
   exact-54 `PURE_CONTROL_NODEIDS` run in `harden-pure-control-i.xml`. The
   coordinator then pushes exact
   `I`, verifies `git ls-remote` equals `I`, and invokes the existing
   `phase-loop reopen --phase HARDEN --reason
   "pre-change runtime cannot attest HARDEN candidate"` on the now-clean tree if
   reconciliation still reports the rejected false completion. No amend,
   rebase, squash, cherry-pick, stash/patch replay, replacement ref,
   `commit-tree`, dirty-worktree proof, or reused process is admissible.
4. The coordinator writes
   `.phase-loop/runs/<transition-id>/harden-coordinator-transition.json` from
   its own process. The sealed record contains coordinator executable/package
   realpaths, version/Git identity/file hashes/PID/start nonce; manifest
   pre/post blobs, exact executing event, lifecycle-control PR/merge `L`, and
   the clean post-`L` target identity; implementation
   launch artifact paths/hashes and child-exit dirty manifest; rejected
   false-complete/manual-reopen event; exact `L`/`T`/`C`/`I` parents, trees, staged
   path sets, residual hashes, clean worktree/process identities and 115/7/4/126
   results; all preimplementation, `C`, and `I` exact-54 pure-control command,
   tuple, XML, and fresh-head bindings; candidate branch/remote proof; plan,
   roadmap, manifest, guard/test
   blob digests; and old-process death. A child/model-produced record, a
   coordinator root inside the worktree, an unsealed/mutable coordinator
   identity, synthetic/laundered history, or a value not recomputable from
   Git/forge/process/run artifacts fails.
5. The coordinator prepares the exact clean fetched `I` worktree and launches:

   `PHASE_LOOP_HARDEN_COORDINATOR_TRANSITION=<absolute-coordinator-transition> PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.cli resume --repo . --roadmap specs/phase-plans-v10.md --phase HARDEN --governed --executor codex --model gpt-5.6-terra --effort high --lane-scheduler off --phase-scheduler off --closeout-mode manual --max-phases 1`

   The new repo-local runtime validates the transition and loaded module/Git
   identities before dispatch, then copies those exact bytes into its run-owned
   input area and records the source/destination hashes. Only after that check
   does its new
   `SL-2.5` path export `PHASE_LOOP_RUN_DIR=<candidate-run-dir>` to verification
   subprocesses, record `verification_stage=pre_seal`, run dependency refresh,
   exact 126-node focused, every ordinary command, the broad compatible suite
   under `not dotfiles_integration`, and the separate exact 54-node pure-control
   command writing `harden-pure-control-candidate.xml`, then seal/validate
   `verification.json` and all three JUnit classes. The bootstrap fallback is forbidden
   in candidate/post-landing evidence: canonical JUnit must be under the
   exported runner-owned directory. The focused command removes
   `PHASE_LOOP_TDD_EXPECT_HARDEN`, requires marker activation, and reports exact
   126 passed/zero skipped. The pure command also removes the activation
   variable, requires marker activation, sets only the test-owned proof mode,
   passes exactly literal `PURE_CONTROL_NODEIDS`, and reports 54 passed/zero
   skipped with a path and digest distinct from focused and broad JUnit.
6. The candidate runtime enters a bounded `awaiting_external_review` wait while
   remaining alive at unchanged `I`; it accepts only the declared run-owned
   panel-record path written by the immutable external coordinator. The
   coordinator launches a fresh exact-`I` repo-local isolated-panel boundary,
   not the legacy installed panel subprocess path. It sets
   `allow_api_key_fallback=False`; materializes the exact `I` tree and every
   approved `PanelRequest.context_refs` input into immutable `/review` paths;
   starts separate no-network/no-credential `linux_bwrap_v1` review legs for
   Fable, Sol, Gemini, and Grok; and keeps subscription auth/transport in the
   trusted parent control plane behind each exact typed broker adapter. Each
   seat must pass its direct mutation/credentialed-side-effect probes before
   returning a usable review. The sealed panel record binds each reviewed
   ref/hash, exact `I`, loaded boundary-module digests, plan digest, four
   supported route/checklist identities, boundary/broker/probe attestations,
   reviewed status/verdict/anchors, and author-vendor independence. A wait
   timeout, candidate exit, wrong writer/path/digest, changed HEAD, direct legacy
   route, refused/excepted/missing seat, or failed probe fails closed.
7. After a clean isolated panel, the fresh candidate runtime validates the
   coordinator panel record, reduces the honest supported/refused fleet
   checklist with the four panel-seat rows included, invokes:

   `phase-loop-runtime/scripts/verify_harden_evidence.py --lifecycle-stage candidate --repo . --roadmap specs/phase-plans-v10.md --plan plans/phase-plan-v10-HARDEN.md --phase HARDEN --run-dir <candidate-run-dir> --verification-json <candidate-run-dir>/verification.json --junit-xml <candidate-run-dir>/harden-compatible-suite.xml --pure-control-junit <candidate-run-dir>/harden-pure-control-candidate.xml --fleet-checklist <candidate-run-dir>/harden-fleet-checklist.json --coordinator-transition <candidate-run-dir>/harden-coordinator-transition.json --governance-panel <candidate-run-dir>/harden-governance-panel.json --output <candidate-run-dir>/harden-candidate-evidence.json`

   and performs a parent-owned candidate audit. Passed candidate audit records
   `awaiting_phase_closeout`, never `complete`, then exits. A fix invalidates
   `C`, `I`, all clean-process results, seals, and panels and restarts with a new
   GPT-5.6 Terra child at step 1.
8. The external coordinator merges only exact `I` with ordered parents `[P,I]`,
   proves the candidate process gone, fetches server canonical main `M`,
   prepares a clean exact-`M` worktree, and writes a new post-landing transition.
   It launches the same repo-local command shape with the new exact transition.
   Startup fails closed unless local/remote `M`, the lifecycle-control,
   tests-only, and implementation ordered two-parent PR merges, actual
   `L -> T -> C -> I` ancestry, coordinator identity, and loaded
   repo-local module hashes all match and the PID/nonce is distinct from every
   earlier process.
9. The post-landing runtime repeats manifest, plan, roadmap, environment-
   activation-absent exact 126-node focused, broad compatible, exact 54-node
   pure-control in `harden-pure-control-main.xml`, Ruff, and exported-run-dir
   seal/JUnit validation. The coordinator then runs the
   mandatory exact-`M` Fable/Sol/Gemini/Grok panel through a fresh exact-`M`
   repo-local isolated-panel boundary with the same four supported rows,
   immutable staged inputs, parent-controlled subscription inference adapters,
   and direct mutation/credentialed-side-effect probes. It reduces a new fleet
   checklist and invokes:

   `phase-loop-runtime/scripts/verify_harden_evidence.py --lifecycle-stage post_landing --repo . --roadmap specs/phase-plans-v10.md --plan plans/phase-plan-v10-HARDEN.md --phase HARDEN --run-dir <main-run-dir> --verification-json <main-run-dir>/verification.json --junit-xml <main-run-dir>/harden-compatible-suite.xml --pure-control-junit <main-run-dir>/harden-pure-control-main.xml --fleet-checklist <main-run-dir>/harden-fleet-checklist.json --coordinator-transition <main-run-dir>/harden-coordinator-transition.json --governance-panel <main-run-dir>/harden-governance-panel.json --candidate-evidence <main-run-dir>/harden-candidate-evidence.json --output <main-run-dir>/harden-evidence.json`

   The parent-owned `_audit_harden_post_suite_outputs()` re-opens both seals, all
   checkpoint/pre-push/focused/broad JUnit files, all five stage-specific
   exact-54 pure-control JUnit files, both checklists/evidence
   records, both external transition records, both isolated-panel records and
   their eight seat attestations, and server metadata; recomputes every hash,
   exact digest, coordinator/process/head/module identity, checkpoint/final
   commit tree/path/ancestry, ordered PR-merge parent, registry set, node
   partition/count/status, pure-control literal tuple/count/digest and exact
   intersection/union/pure-only equations, proof mode, XML non-substitution,
   fresh process/head bindings, boundary/broker/probe result, and lifecycle edge; and
   matches them to parent state. Missing outputs return
   `post_suite_output_missing`; changed bytes/hashes return
   `post_suite_hash_mismatch`; stale coordinator/process/run/head/plan/roadmap/
   manifest/test/registry/cross-file identity returns
   `post_suite_identity_mismatch`; child-authored/self verification returns
   `self_verification_cycle`; synthetic or wrong checkpoint history returns
   `harden_checkpoint_history_mismatch`; wrong PR merge parents return
   `harden_merge_parent_mismatch`; an unisolated panel seat returns
   `review_boundary_attestation_failed`; and early completion returns
   `terminal_complete_before_final_audit`. These normalize to non-human
   `blocker_class=repeated_verification_failure`. Only the fresh exact-`M`
   process with `final_audit.status=passed` may authorize the terminal
   lifecycle-control landing; every failure retains the run-owned artifacts for
   diagnosis.
10. After that exact-`M` audit passes, the executor performs its normal
    `update_lifecycle(..., "completed", "codex-execute-phase", metadata)` in a
    separate clean control worktree rooted at `M`, where `metadata` carries the
    exact `v10.phase-completion-landing.v1` payload frozen above and no future
    `FH` or `F` identity. The coordinator applies the same exact-delta
    validator, requires the strict event absent at `M`, commits only
    `plans/manifest.json` as `FH` with sole parent `M`, and lands a distinct
    manifest-only two-parent closeout PR as `F`. It proves ordered parents
    `[M, FH]`; `M..FH` and `M..F` each contain only the manifest; the prior
    lifecycle is an exact prefix; the event is new and unique at `FH`; its
    exact `phase_completion_landing` key set and sole nested `review_wave`
    evidence, strict receipt/base/bundle/seat/restart/policy shapes, retained raw
    artifacts and receipts, complete changed-bundle restart semantics,
    early-Codex CLEAR-before-critics chronology, all-critics-before-Fable
    chronology, typed effective policy, usable `AGREE` Fable/Sol facts, and
    Fable-only binding all recompute from the retained final bytes after every
    descriptor is closed; no retained object names the event, `FH`, or `F`; the event is
    byte-semantically identical at `FH`, `F`, and fetched main; and every
    non-manifest blob equals audited `M`. The still-fresh exact-`M` parent may
    emit terminal `complete` only after this server proof; its loaded runtime
    modules are exact because `M` and `F` have identical code blobs. Any extra
    delta, failed/duplicate/drifted transition, merge race, wrong topology or
    digest/outcome, or changed non-manifest blob blocks and requires a new clean
    exact-head audit rather than relabeling `F`.

## Execution Policy

- work-unit defaults: work-unit=`lane_execute`, effort=`high`, unsupported=`inherit_default`, inherit-default=`true`
- execute: executor=`codex`, model=`gpt-5.6-terra`, effort=`high`, work-unit=`lane_execute`, unsupported=`fallback`, fallback=`gpt-5.6-terra`, reason=`HARDEN is the Terra whole-phase authorship slot`
- SL-3: executor=`codex`, model=`gpt-5.6-terra`, work-unit=`phase_reducer`, effort=`high`, unsupported=`fallback`, fallback=`gpt-5.6-terra`, reason=`Terra-authored checkpoint/direct-child reduction plus candidate and post-landing fresh-process evidence after both functional lanes`

Policy precedence is CLI/operator override, this phase-plan policy, roadmap
policy, Dispatch Hints, then registry defaults. HARDEN is explicitly assigned
to Codex GPT-5.6 Terra for the whole code-writing phase: Terra authors the
tests-only RED lane and every implementation/reducer lane. No other vendor may
author a HARDEN code or test path. Cross-vendor lane rotation, the runtime lane
scheduler, and the runtime phase scheduler remain off. Terra-native workers are
allowed only with coordinator-owned independent worktrees and the disjoint
ownership above; the external coordinator alone performs the governed
commit/push/merge operations.

## Execution Notes

- Before any test work, the external coordinator records its immutable
  out-of-worktree identity and panels the exact SHA-256 of this plan by true
  `context_refs` with Fable 5, GPT-5.6 Sol, Gemini 3.6 Flash, and Grok 4.5.
  Fable and Sol are mandatory reviewing seats; API-key fallback is disabled and
  a degraded 3-of-4 result blocks. Because the boundary does not exist yet,
  this pre-implementation record is a TDD/governance prerequisite, never
  `EC-HARDEN-5` route evidence and never a substitute for the isolated exact-`I`
  or exact-`M` panel. The prior exact-digest `DISAGREE` record remains immutable
  historical evidence bound to its reviewed predecessor digest; it is not
  relabeled as approval, and this repaired digest requires a fresh unanimous
  panel before dispatch.
- After that exact-plan panel and before any test write, the installed executor
  first proves the checked-in manifest is production-serializer row-stable and
  that disposable real-API simulations of both HARDEN transitions preserve
  every sibling row exactly, then performs its normal `committed -> executing`
  manifest lifecycle update. The
  external coordinator treats `plans/manifest.json` as a single runner-owned
  control path, not a HARDEN lane path: it accepts only the exact API delta,
  lands it alone through the distinct two-parent control PR `L`, fetches the
  post-`L` target, and requires a clean tree. The tests-only and implementation
  PRs may not contain or repair the manifest. At checkpoint `C`, direct-child
  `I`, candidate, and exact-`M`, any manifest dirt is an ownership failure, not
  a planning/control exemption. After the exact-`M` audit, the normal completed
  append must likewise land alone as `F` before terminal `complete`.
- `SL-0` lands literally as tests only. No production source, executable,
  changelog, roadmap, manifest, or closeout implementation may share that
  commit. Land the test-owned guard and immutable tests through their own
  two-parent tests-only PR into the exact clean post-`L` target branch. On the fetched
  post-merge target, prove the marker-absent 105-pass/21-skip default and then the
  activated 126-nodeid/per-case intended RED results. Only after that may the
  coordinator create a distinct implementation branch from that head and later
  open the distinct implementation PR. Server-recorded PR target/base/head
  identities, ordered parents, lifecycle, actual PR range, and PR file set are
  evidence; local branch shape or a user-supplied base SHA is not.
- `SL-1` and `SL-2` are write-disjoint. Lane order does not waive the Terra
  whole-phase author policy or authorize lane/phase scheduler fanout.
- HARDEN is not write-disjoint from the current `CONFORM`, `FABPUB`, `LEGIBLE`,
  `PROOFGATE`, and `REVIEWTRUTH` phase plans. The overlapping phase-owned paths
  are `CHANGELOG.md`,
  `phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py`,
  `phase-loop-runtime/src/phase_loop_runtime/cli.py`,
  `phase-loop-runtime/src/phase_loop_runtime/goal_coverage.py`,
  `phase-loop-runtime/src/phase_loop_runtime/launcher.py`,
  `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`,
  `phase-loop-runtime/src/phase_loop_runtime/runner.py`,
  `phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py`,
  `phase-loop-runtime/tests/test_goal_coverage.py`, and
  `phase-loop-runtime/tests/test_review_leg_sandbox.py`. The roadmap serializes
  LEGIBLE → (PROOFGATE ∥ CONFORM) → FABPUB → HARDEN → REVIEWTRUTH. HARDEN fetches
  the exact post-FABPUB target and regenerates/reverifies the tests-only baseline before
  `SL-0`; REVIEWTRUTH cannot begin until HARDEN's two-parent landing exists.
  Scheduler-off status alone is not collision evidence.
- The GPT-5.6 Terra implementation child writes all phase-owned implementation
  paths and returns once; it may not stage for the coordinator, commit, push,
  transition, attest, panel, merge, or complete. The pre-change runtime runs
  with manual closeout, its missing `PHASE_LOOP_RUN_DIR` uses only the
  non-evidence bootstrap fallback, and any stale-module `complete` is rejected.
  After both old processes exit, the external coordinator alone creates actual
  checkpoint `C` from the exact `SL-1`+`SL-2` path list while retaining only the
  unchanged verifier/docs as dirty residuals. A separate clean exact-`C`
  worktree/process proves activated 115 + 7 green and exact 4 RED with the
  verifier absent, then seals a distinct exact-54 pure-control GREEN JUnit. The
  coordinator then stages exactly the residual two paths
  into direct-child `I`; a new clean exact-`I` process removes the environment
  activation and proves marker-driven all-126 GREEN plus a distinct exact-54
  pure-control GREEN JUnit. Only then may the
  coordinator push `I`, manually reopen a rejected false closeout, and write
  the transition. No loaded parent or child attestation is accepted, and no
  synthetic/re-written history can replace the two real commits.
  The fresh exact-candidate runtime exports its run directory and runs the
  complete compatible suite, exact 126 focused, and distinct exact-54 pure
  controls before its four-seat panel or merge. That panel
  runs through the exact-`I` isolation boundary and all four supported brokered
  seats. It exits before coordinator merge, and a second fresh
  exact-canonical-main runtime repeats the compatible, exact-126, exact-54, and
  isolated exact-`M` panel proofs. A repair, checkout, commit, XML substitution,
  direct legacy panel launch, or failed
  boundary/broker probe in either verifier process invalidates its evidence and
  restarts the `C`/`I` chronology.
- Both phase-loop scheduler controls are literal `off` for every HARDEN launch:
  `--lane-scheduler off --phase-scheduler off`. HARDEN performs no version
  bump, release dispatch, package publication, tag creation, or tag push.
- Execute, repair, plan, roadmap, and maintain-skills behavior are positive
  controls. Review-only CWD/environment/tool/auth changes must not leak into
  another product action.
- A reviewer subprocess or shell inside `linux_bwrap_v1` is permitted. A
  provider-backed route is supported only when the attacker-controlled
  review-leg process proves the common boundary and reaches a typed intended-
  inference-only method through `parent_unix_broker_v1`; otherwise it refuses
  before auth/session/broker/child. The trusted parent may retain first-party
  subscription auth and provider transport for intended inference only. It may
  not expose arbitrary provider methods, URLs, host commands, tools,
  credentials, or side-effect RPCs to the review leg. Fable, Sol, Gemini, and
  Grok must all be supported and directly probed at exact `I` and `M`; none may
  be refused, excepted, or relabeled. `context_refs`, route-specific CLI flags,
  prompts, CWDs, tool allowlists, and names cannot substitute. A live-repo
  mutation, credentialed/privileged side effect, live-root reachability,
  ambient credential source, direct/non-broker egress, host escape, or
  unjournaled cleanup path is forbidden.
- The phase produces no visible avatar/browser-media render;
  `visual_render_declared` remains false and image evidence is not required.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- target surfaces: `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `phase-loop-runtime/src/phase_loop_runtime/launcher.py`, `phase-loop-runtime/src/phase_loop_runtime/injection.py`, `phase-loop-runtime/src/phase_loop_runtime/harness_env_signatures.py`, `phase-loop-runtime/src/phase_loop_runtime/capability_registry.py`, `phase-loop-runtime/src/phase_loop_runtime/claude_channel_sidecar.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/backing.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/runtime_paths.py`, `phase-loop-runtime/src/phase_loop_runtime/reconcile.py`, `phase-loop-runtime/src/phase_loop_runtime/goal_coverage.py`, `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py`, `phase-loop-runtime/scripts/verify_harden_evidence.py`, `CHANGELOG.md`
- evidence paths: `plans/phase-plan-v10-HARDEN.md`, `plans/manifest.json`, `phase-loop-runtime/tests/harden_tdd_guard.py`, `phase-loop-runtime/tests/test_advisor_board_cli_legacy.py`, `phase-loop-runtime/tests/test_advisor_board_composition.py`, `phase-loop-runtime/tests/test_review_leg_sandbox.py`, `phase-loop-runtime/tests/test_phase_loop_injection.py`, `phase-loop-runtime/tests/test_reconcile_portability_85c.py`, `phase-loop-runtime/tests/test_goal_coverage.py`, `phase-loop-runtime/tests/test_verification_interpreter_guard_221.py`, `phase-loop-runtime/tests/test_harden_evidence_verifier.py`, `.phase-loop/events.jsonl`, `.phase-loop/runs/**/verification.json`, `.phase-loop/runs/**/harden-checkpoint-evidence.json`, `.phase-loop/runs/**/harden-prepush-evidence.json`, `.phase-loop/runs/**/harden-sl1.xml`, `.phase-loop/runs/**/harden-sl2.xml`, `.phase-loop/runs/**/harden-sl3-red.xml`, `.phase-loop/runs/**/harden-phase-focused.xml`, `.phase-loop/runs/**/harden-compatible-suite.xml`, `.phase-loop/runs/**/harden-pure-control-red.xml`, `.phase-loop/runs/**/harden-pure-control-c.xml`, `.phase-loop/runs/**/harden-pure-control-i.xml`, `.phase-loop/runs/**/harden-pure-control-candidate.xml`, `.phase-loop/runs/**/harden-pure-control-main.xml`, `.phase-loop/runs/**/launch.json`, `.phase-loop/runs/**/terminal-summary.json`, `.phase-loop/runs/**/harden-coordinator-transition.json`, `.phase-loop/runs/**/harden-governance-panel.json`, `.phase-loop/runs/**/review-boundary-attestation*.json`, `.phase-loop/runs/**/harden-fleet-checklist.json`, `.phase-loop/runs/**/harden-candidate-evidence.json`, `.phase-loop/runs/**/harden-evidence.json`
- redaction posture: `metadata_only`
- downstream handling: `none`

## Verification

**Coordinator reseal complete:** `plans/manifest.json` carries the literal
100/54/20/134 tuple counts and digests, 34 pure-only count, explicit pure-control
proof mode, distinct-JUnit contract, and five-stage proof list. The frontmatter
and manifest verification commands bind one payload SHA while independently
recomputing the current plan digest.

- `PYTHONPATH=phase-loop-runtime/src python3 skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py plans/phase-plan-v10-HARDEN.md`
- `PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.cli validate-roadmap specs/phase-plans-v10.md`
- `PYTHONPATH=phase-loop-runtime/src python3 -c 'from pathlib import Path; from phase_loop_runtime.plan_manifest import read_manifest, validate_manifest; p = Path("plans").joinpath("manifest.json"); v = validate_manifest(p); assert v.valid, "; ".join(v.errors); plan_file = Path("plans").joinpath("phase-plan-v10-HARDEN.md").as_posix(); roadmap_file = Path("specs").joinpath("phase-plans-v10.md").as_posix(); matches = [e for e in read_manifest(Path(".")).plans if e.file == plan_file]; assert len(matches) == 1, f"expected one HARDEN manifest row, got {len(matches)}"; e = matches[0]; actual = (e.phase_alias, e.roadmap_ref.file if e.roadmap_ref else None, e.lanes); expected = ("HARDEN", roadmap_file, ("SL-0", "SL-1", "SL-2", "SL-3")); assert actual == expected, f"stale HARDEN manifest row: {actual!r}"'`
- `PYTHONPATH=phase-loop-runtime/src python3 -c 'import hashlib, json; from pathlib import Path; from phase_loop_runtime.plan_manifest import validate_manifest; p = Path("plans").joinpath("manifest.json"); plan_file = Path("plans").joinpath("phase-plan-v10-HARDEN.md"); roadmap_file = Path("specs").joinpath("phase-plans-v10.md"); v = validate_manifest(p); assert v.valid, "; ".join(v.errors); doc = json.loads(p.read_text()); rows = [r for r in doc["plans"] if r.get("slug") == "v10-HARDEN" or r.get("file") == plan_file.as_posix() or r.get("phase_alias") == "HARDEN"]; assert len(rows) == 1, f"expected one HARDEN identity row, got {len(rows)}"; r = rows[0]; assert (r.get("slug"), r.get("file"), r.get("phase_alias"), (r.get("roadmap_ref") or {}).get("file"), r.get("lanes")) == ("v10-HARDEN", plan_file.as_posix(), "HARDEN", roadmap_file.as_posix(), ["SL-0", "SL-1", "SL-2", "SL-3"]); events = r.get("lifecycle"); assert isinstance(events, list) and events; bearing = [e for e in events if isinstance(e, dict) and isinstance(e.get("metadata"), dict) and ("harden_plan_contract" in e["metadata"] or "harden_plan_contract_record_id" in e["metadata"])]; assert len(bearing) == 1, f"expected one HARDEN contract-bearing record, got {len(bearing)}"; event = bearing[0]; assert events[0] is event and event.get("transition") == "committed" and event.get("by") == "codex-plan-phase"; metadata = event["metadata"]; assert metadata.get("harden_plan_contract_record_id") == "v10-HARDEN.harden-plan-contract.v1"; c = metadata.get("harden_plan_contract"); assert isinstance(c, dict); transitions = [e.get("transition") for e in events]; assert transitions in (["committed"], ["committed", "executing"], ["committed", "executing", "completed"]), transitions; assert r.get("status") == transitions[-1] and r.get("updated_at") == events[-1].get("at"); executing = [e for e in events if e.get("transition") == "executing"]; assert len(executing) == (0 if transitions == ["committed"] else 1); assert not executing or (executing[0].get("by") == "codex-execute-phase" and executing[0].get("metadata", {}).get("phase_alias") == "HARDEN" and isinstance(executing[0].get("metadata", {}).get("run_id"), str) and executing[0]["metadata"]["run_id"]); payload = {k: value for k, value in c.items() if k != "plan_sha256"}; assert hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest() == "79c4bb52ebe25573c6d4eb98da1fc8ca0a90c2caea3a58badd8204577c061908"; digest = lambda xs: hashlib.sha256((chr(10).join(xs) + chr(10)).encode()).hexdigest(); assert c["plan_sha256"] == hashlib.sha256(plan_file.read_bytes()).hexdigest(); assert c["roadmap_sha256"] == hashlib.sha256(roadmap_file.read_bytes()).hexdigest() == "b26b4fd76efb7882578eae5e102fd577b26e66f590a531d3b3a738d840e5106e"; assert (len(c["owned_paths"]), c["owned_paths_count"], digest(c["owned_paths"]), c["owned_paths_sha256"]) == (46, 46, "453bbecfdbcc6570e8cd04d68b45097a1c05022691919b5296ae0c36d7f0eb47", "453bbecfdbcc6570e8cd04d68b45097a1c05022691919b5296ae0c36d7f0eb47"); assert (len(c["test_paths"]), c["test_paths_count"], digest(c["test_paths"]), c["test_paths_sha256"]) == (26, 26, "1c89c155544538b7a79f6333c5e8ff7bc30ddca808e9b0d229b91ed54394f250", "1c89c155544538b7a79f6333c5e8ff7bc30ddca808e9b0d229b91ed54394f250"); assert (len(c["checkpoint_paths"]), c["checkpoint_paths_count"], digest(c["checkpoint_paths"]), c["checkpoint_paths_sha256"]) == (18, 18, "b20d6f20a8a073d4c5401143bd72850b69bc1e1661668bd7f3d3e5c628d58d03", "b20d6f20a8a073d4c5401143bd72850b69bc1e1661668bd7f3d3e5c628d58d03"); assert (c["expected_nodeids"], c["sl1_nodeids"], c["sl2_nodeids"], c["sl3_evidence_nodeids"], c["default_skip_nodeids"], c["nodeid_delta"], c["nodeid_inventory_sha256"]) == (126, 115, 7, 4, 21, 104, "6b642b3a4a7f22b51c41c5a84383a09833b8af0c57e1a10e9c97cd2e3c623728"); assert (c["public_board_corpus_modules"], c["public_board_corpus_modules_sha256"], c["public_board_corpus_nodeids"], c["public_board_corpus_nodeids_sha256"], c["public_board_migrated_nodeids"], c["public_board_migrated_nodeids_sha256"]) == (19, "262a2c0e653b9dc1e98f2c815918d2a35e8377377d344026affe7154d1b8ea34", 306, "4789528566ada4e92cdf0ba6324704a60697f4166c25985ddc78c2da6ccda656", 100, "90e36e87f2d93504c63bfefd850bdceb9c3cc869f62c7969b5815e2e49950ac7"); assert (c["public_board_execution_nodeids"], c["public_board_pure_control_nodeids"], c["public_board_execution_pure_overlap_nodeids"], c["public_board_callers"], c["public_board_pure_only_nodeids"]) == (100, 54, 20, 134, 34); assert c["public_board_execution_pure_overlap_nodeids_sha256"] == "3ce722d31e283cd455b3c7d23ed3d755e076e0fd09402518fbe9c10ba11488d6"; assert (c["pure_control_proof_mode"], c["pure_control_junit_contract"], c["pure_control_proof_stages"]) == ("PHASE_LOOP_HARDEN_PROOF_MODE=pure_control", "distinct_from_focused_and_broad", ["preimplementation_red", "checkpoint_c", "prepush_i", "candidate_i", "canonical_m"])'`
- `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -c 'import os, subprocess, sys, tempfile; from pathlib import Path; from harden_tdd_guard import EXPECTED_PHASE_NODEIDS, SL1_NODEIDS, SL2_NODEIDS, SL3_EVIDENCE_NODEIDS; assert len(EXPECTED_PHASE_NODEIDS) == 126 and len(SL1_NODEIDS) == 115 and len(SL2_NODEIDS) == 7 and len(SL3_EVIDENCE_NODEIDS) == 4; assert set(EXPECTED_PHASE_NODEIDS) == set(SL1_NODEIDS) | set(SL2_NODEIDS) | set(SL3_EVIDENCE_NODEIDS); assert not (set(SL1_NODEIDS) & set(SL2_NODEIDS) or set(SL1_NODEIDS) & set(SL3_EVIDENCE_NODEIDS) or set(SL2_NODEIDS) & set(SL3_EVIDENCE_NODEIDS)); root = os.environ.get("PHASE_LOOP_RUN_DIR"); junit = Path(root).joinpath("harden-phase-focused.xml") if root else Path(tempfile.mkdtemp(prefix="harden-bootstrap-focused-")).joinpath("harden-phase-focused.xml"); raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", *EXPECTED_PHASE_NODEIDS, "-q", f"--junitxml={junit}"]))'`
- `env -u PHASE_LOOP_TDD_EXPECT_HARDEN PHASE_LOOP_HARDEN_PROOF_MODE=pure_control PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -c 'import hashlib, os, subprocess, sys, tempfile; from pathlib import Path; from harden_tdd_guard import EXPECTED_PHASE_NODEIDS, PUBLIC_BOARD_EXECUTION_NODEIDS, PURE_CONTROL_NODEIDS, EXECUTION_PURE_OVERLAP_NODEIDS, PUBLIC_BOARD_CALLER_NODEIDS; digest = lambda xs: hashlib.sha256((chr(10).join(xs) + chr(10)).encode()).hexdigest(); assert (len(PUBLIC_BOARD_EXECUTION_NODEIDS), len(PURE_CONTROL_NODEIDS), len(EXECUTION_PURE_OVERLAP_NODEIDS), len(PUBLIC_BOARD_CALLER_NODEIDS)) == (100, 54, 20, 134); assert len(set(PURE_CONTROL_NODEIDS) - set(EXPECTED_PHASE_NODEIDS)) == 34; assert set(PUBLIC_BOARD_EXECUTION_NODEIDS) & set(PURE_CONTROL_NODEIDS) == set(EXECUTION_PURE_OVERLAP_NODEIDS); assert set(PUBLIC_BOARD_EXECUTION_NODEIDS) | set(PURE_CONTROL_NODEIDS) == set(PUBLIC_BOARD_CALLER_NODEIDS); assert set(PURE_CONTROL_NODEIDS) & set(EXPECTED_PHASE_NODEIDS) == set(EXECUTION_PURE_OVERLAP_NODEIDS); assert all(len(xs) == len(set(xs)) and tuple(xs) == tuple(sorted(xs)) for xs in (PUBLIC_BOARD_EXECUTION_NODEIDS, PURE_CONTROL_NODEIDS, EXECUTION_PURE_OVERLAP_NODEIDS, PUBLIC_BOARD_CALLER_NODEIDS)); assert digest(PUBLIC_BOARD_EXECUTION_NODEIDS) == "90e36e87f2d93504c63bfefd850bdceb9c3cc869f62c7969b5815e2e49950ac7"; assert digest(PURE_CONTROL_NODEIDS) == "7d4b4f994f04b0926d0318fd5d7d983c0a81488d171c0755e94d9b1c8b66eef4"; assert digest(EXECUTION_PURE_OVERLAP_NODEIDS) == "3ce722d31e283cd455b3c7d23ed3d755e076e0fd09402518fbe9c10ba11488d6"; assert digest(PUBLIC_BOARD_CALLER_NODEIDS) == "cecbef4c0f550f16a0e5e033be9d88216dcd7a8b9d127f6c91c920cd2359bb6e"; root = os.environ.get("PHASE_LOOP_RUN_DIR"); junit = Path(root).joinpath("harden-pure-control-candidate.xml") if root else Path(tempfile.mkdtemp(prefix="harden-bootstrap-pure-")).joinpath("harden-pure-control-candidate.xml"); focused = Path(root).joinpath("harden-phase-focused.xml") if root else None; broad = Path(root).joinpath("harden-compatible-suite.xml") if root else None; assert junit not in {focused, broad}; raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", *PURE_CONTROL_NODEIDS, "-q", f"--junitxml={junit}"]))'`
- `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_advisor_board_cli_legacy.py phase-loop-runtime/tests/test_advisor_board_composition.py -q -k "test_cli_harden_preflight_authorizes_before_compose_and_invoke or test_harden_preflight_authorizes_before_every_capability_auth_ok"`
- `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration"`
- `ruff check phase-loop-runtime/src/phase_loop_runtime phase-loop-runtime/scripts`
- `git diff --check`
- `git diff --cached --check`

The frontmatter `automation.suite_command` is an executable fail-fast composite:
it first runs the same stable-identity HARDEN contract lookup listed in
`## Verification`, then runs the broad compatible suite and distinct exact-54
pure-control suite with separate structured JUnit.
That lookup validates the entire manifest, selects one row across the stable
slug/file/phase identities, requires exactly one contract-bearing event with
record id `v10-HARDEN.harden-plan-contract.v1`, validates the lifecycle
sequence/status/timestamps, seals the complete contract payload other than the
separately recomputed plan digest, and never assumes the contract event is
latest. Thus committed planning, clean post-`L` executing, candidate/exact-`M`
executing, and terminal completed-control commands consume the same lookup;
missing, duplicate, conflicting, or drifted records fail before tests. The
pre-change bootstrap
runtime does not export `PHASE_LOOP_RUN_DIR`, so that first pass uses `mktemp`
and is explicitly non-evidence. Candidate and post-landing runtimes contain the
new export path and must write JUnit beneath their parent-owned run directory;
the evidence verifier rejects the fallback there. The exact-`C` process first
proves activated 115 + 7 green and exact 4 RED with the verifier absent, then
separately proves exact 54 pure controls GREEN. A different clean exact-`I`
process then removes the environment activation and proves all 126 green plus
a distinct exact-54 pure-control JUnit after direct-child `I` introduces the
verifier. Candidate and post-landing exact 126-node and exact-54 pure-control
commands also run with environment activation absent before the broad suite;
the production marker supplies activation and only the pure command sets the
test-owned proof mode. Both fresh runtimes seal all distinct JUnit artifacts
before their isolated exact-head panel. HARDEN chronology, raw RED, author
independence, crash
cleanup, four-seat boundary/broker probes, and fleet evidence become decidable
  only through the two post-suite reductions and fresh-parent audits above; they
  must never be represented as pre-seal suite evidence. Verification also rejects
  every former flat completion shape: `metadata.phase_completion_landing` must
  expose exactly the REVIEWTRUTH key set with `review_wave` as its sole review
  evidence, and the fresh parent must derive the closed-descriptor file facts,
  canonical receipt and bundle, full restart chain, parsed chronology and roles,
  typed parameterized policy, usable Sol/Fable `AGREE`, and Fable-only binding
  from retained bytes without event, receipt, `FH`, or `F` self-reference.

## Acceptance Criteria

- [ ] EC-HARDEN-0 — proven by the frozen guard's default 105-pass/21-skip JUnit, activated 126-nodeid and per-case raw intended-RED/JUnit records, separate preimplementation exact-54 pure-control GREEN JUnit, and passed fresh-parent `_audit_harden_post_suite_outputs()` plus terminal lifecycle-control audit; the audits must prove immutable tests/guard; exact manifest validation through the stable unique contract record, including fail-closed missing/duplicate/conflict/drift cases, canonical sixteen-key current-row normalization, production-serializer parsed-row stability, disposable real-API `committed -> executing -> completed` simulation with zero sibling drift, 46/26/18 path counts and SHA-256 values, the public-corpus/migration digests, the 126-node inventory digest, literal 100 execution / 54 pure / 20 overlap / 134 union tuple counts and digests, exact intersection/union equations, and 34 pure-only difference; the normal executing append as the sole pre-lane dirty path; exact manifest-only ordered two-parent control merge `L` before tests branch creation; ordered two-parent tests and implementation PR merges; implementation PR range excluding every `SL-0` path, the tests-only commit, and `plans/manifest.json`; immutable out-of-worktree coordinator identity; manual closeout plus rejected/manually reopened old-runtime false completion; whole-phase GPT-5.6 Terra child exit without commit; both runtime schedulers off; coordinator-only commits/push/merge; no release/tag/publish action; actual direct ancestry `L -> T -> C -> I`; checkpoint `C` containing exactly changed `SL-1`+`SL-2` paths while the manifest is clean; unchanged two-path `SL-3` residual containment with no hidden third manifest residual; no synthetic/history-laundering mechanism; a distinct clean exact-`C` process proving activated exact 115 green + 7 green + 4 RED with verifier absent plus separate exact-54 pure GREEN; a distinct clean exact-`I` process proving environment-activation-absent all 126 green plus separate exact-54 pure GREEN only after verifier/docs commit `I`; distinct candidate/main processes and exact loaded heads/modules each proving exact 126 focused, broad compatible, and separate exact-54 pure GREEN under distinct XML paths/digests; exported run dirs only in new runtimes; broad compatible and exact-54 pure suites before each isolated exact-head four-seat panel; candidate `--lifecycle-stage candidate` evidence; post-landing `--lifecycle-stage post_landing` evidence; rejection of collection-derived selectors, autouse authorization, broad/focused XML substitution, reused path/digest, wrong proof mode, missing/duplicate/skip/xfail/error testcase, stale process/head, or future-test inference; exact strict `v10.phase-completion-landing.v1` completed append absent at `M`, added at single-parent `FH`, and preserved at manifest-only ordered two-parent closeout merge `F` and fetched main, with the exact REVIEWTRUTH metadata key set and sole nested `v10.review-wave-receipt.v1` review evidence; immutable early/seat execution attestations, native results, reducer artifacts with exact raw text, canonical bundle, mirrored receipts, complete restart chain, and typed resolver bytes under the evidence root; literal RED then GREEN rejection of padded elision and synthetic artifact-only votes; closed descriptors plus independent containment, byte, hash, canonical-JSON, common-base/bundle, producer-identity, exact-terminal/non-elision, parsed-chronology, role, restart, and effective-policy recomputation; early Codex CLEAR staged before all critics; the same read-only by-reference bundle consumed by every critic; Fable starting after every critic; full changed-bundle wave restart after any contradiction or material finding; usable `AGREE` Fable/Sol and Fable-only binding derived as effective roadmap facts with parameterized runtime policy and valid `required_prover=false`; no parent-event, receipt, `FH`, or `F` self-reference; unchanged `PANEL_LEGS` and non-review goldens; and every non-manifest blob preserved from audited `M`; and the lifecycle normal executing append → control merge `L` → tests merge → activated 126 RED + exact-54 pure GREEN → Terra child exit → real checkpoint `C` → clean 115/7/4 + exact-54 pure proof → real direct-child `I` → clean all-126 + exact-54 pure proof → push/transition → fresh candidate focused/broad/exact-54 suite/isolated four-seat panel/audit → ordered two-parent implementation merge → fresh canonical-main focused/broad/exact-54 suite/isolated exact-head four-seat panel/final audit → strict completed-control `FH`/`F` → terminal complete
- [ ] EC-HARDEN-1 — proven by `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_review_leg_sandbox.py -q -k review_stage_rejects_every_escape_form_before_launch`
- [ ] EC-HARDEN-2 — proven by `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_reconcile_portability_85c.py -q -k "cwd_independent or repo_anchored"`
- [ ] EC-HARDEN-3 — proven by `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_goal_coverage.py -q -k "enforce_blocks_every_zero_declared or all_bare_legacy_is_distinct"`; both selected tests must pass, and the all-bare test must prove warn/default is nonblocking while every enforce completion gate returns non-human `contract_bug`
- [ ] EC-HARDEN-4 — proven by `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_verification_interpreter_guard_221.py -q -k argument_consuming_bash_options_and_profile_patch_version_fail_closed`; the selector must enumerate `-o option-name`, `+o option-name`, `-O shopt-option`, `+O shopt-option`, `--rcfile file`/`--rcfile=file`, and `--init-file file`/`--init-file=file`
- [ ] EC-HARDEN-5 — proven jointly by the exact public-board selector command `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_advisor_board_cli_legacy.py::AdvisorBoardCliTest::test_cli_harden_preflight_authorizes_before_compose_and_invoke phase-loop-runtime/tests/test_advisor_board_composition.py::AuthAwareCompositionTests::test_harden_preflight_authorizes_before_every_capability_auth_ok phase-loop-runtime/tests/test_review_leg_sandbox.py phase-loop-runtime/tests/test_phase_loop_injection.py -q -k "harden_preflight_authorizes or review_isolation_registry_matrix or review_capability_registry_set_equality or every_executable_review_route or review_snapshot_materializes or review_prompt_argv_cwd_and_env or crash_recovery"`, the separately sealed literal `PURE_CONTROL_NODEIDS` command at preimplementation, exact `C`, exact `I`, candidate `I`, and canonical `M`, and the passed runner-owned post-suite final audit; the guard must prove exact 100 execution / 54 pure / 20 overlap / 134 union tuple counts and digests, `execution & pure == overlap`, `execution | pure == union`, `execution <= SL1`, `pure & EXPECTED_PHASE_NODEIDS == overlap`, and exactly 34 pure-only nodeids outside the 126-node phase inventory; every dedicated pure JUnit must contain exactly the same literal 54 once each, zero skip/xfail/error and zero capability/auth/session/provider/broker/callback/spawn canaries, with its command argv, proof mode, guard/test blobs, XML digest, fresh process, and exact head bound; the 20 overlaps must reach the execution arm in the ordinary phase run and the pure arm only in the separate proof-mode run; no autouse/global authorization fixture, collection-derived selector, module glob, `-k`, future collected test, broad/focused XML substitution, reused path/digest, or self-reported count is admissible; for CLI, bare-default, explicit-auth, and config-loaded composition, the credentialless isolation/broker preflight must run and authorize the operation before the first availability/registry/provider lookup, capability `auth_ok()` invocation, subscription access, seat construction, or other composition side effect, while denial/forgery proves none of those canaries fires; `invoke_board()` independently revalidates the authorization before artifact/context, gateway/research, seat-env/auth, provider/broker/session, or spawn work; the credentialless command adapter executes only after exact Linux/bubblewrap/namespace/probe success; Fable 5, GPT-5.6 Sol, Gemini 3.6 Flash, and Grok 4.5 are all mandatory supported subscription-only routes whose exact-`I` and exact-`M` panel legs receive only immutable staged snapshots/context refs, read-only tools, no live repo, mutation credentials, privileged side-effect capability, direct network, or host escape, and whose parent-controlled first-party subscription transport/auth exposes only the typed intended-inference RPC through exact `parent_unix_broker_v1` adapters; all four carry direct live-tree mutation and credentialed-side-effect probe attestations at both heads; every other executable provider/API-key/native/gateway/research route satisfies the same isolation or refuses before auth/session/broker/child; manual remains nonlaunch; refusal satisfies the invariant only through non-execution and is never mislabeled supported conformance; checklist/live-registry set equality includes and cross-links the four mandatory panel rows; no `context_refs`, CLI flag, prompt, naming distinction, residual register, pre-seal result, invoker-only preflight, or self-reported closeout field is a satisfaction route
