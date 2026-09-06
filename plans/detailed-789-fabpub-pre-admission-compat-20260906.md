# Detailed plan: FABPUB pre-admission runtime-compatibility guard, sealed-inventory worktree lifecycle, and the pre-admission owner recovery decision

status: approved-by-maintainer 2026-09-06 — C decision = C-keep (permanent ambiguity preserved; recorded operator override is the recovery path); D deferred to its own plan; no runtime edits made
owner: claude-plan-detailed (Claude Code session `session_01Rv2aKsUWdEKoWfB5PTpD1B`)
issue: Consiliency/agent-harness#789 (impact already cleared by the recorded operator override → Consiliency/omniagent-plus#28)
base: `463b90c34860d002a4670fe5b7f429322d72ab1e` (origin/main, 2026-09-06)
landing tier: `plan` — 4/4 cross-vendor AGREE under `plans/decision-interim-president-ratification-20260904.md` (Consiliency/agent-harness#773); ledger row on landing

## Task

Consiliency/agent-harness#789 acceptance list, verbatim intent: (1) reproduce an old admission reader meeting the
newer optional `binding` field AFTER owner acquisition and assert the owner/admission/evidence/transaction/adapter
chronology; (2) prevent an unsupported installed runtime from entering ownership/provider mutation against a newer
store schema, reporting an actionable compatibility failure BEFORE durable owner acquisition; (3) reconcile the
supported operator recovery policy for a demonstrably pre-admission failure without weakening the permanent-ambiguity
contract; (4) give worktree paths captured by a sealed bootstrap inventory a supported lifecycle; (5) recovery
positive control + true unknown-effect negative controls.

## Research summary (all anchors read in this session at base `463b90c3`)

- Admission log deserialisation is `LinearizableAdmissionStore._records`
  (`phase-loop-runtime/src/phase_loop_runtime/convergence/broker/admission.py:150-171`): `AdmissionRecord(**raw)` at
  `:170` with NO store- or record-level schema marker (`admissions.jsonl` is bare JSONL; the only `schema` markers in
  the broker are the FABPUB live-cutover documents, `live.py:312,454,589,695,1199,1945,2050`). An unknown key raises
  a bare `TypeError` — the incident's exact failure. `phase_loop_runtime.__version__` is `0.7.14` on main AND in
  the stale install, so a version number cannot discriminate this skew; only the record shape can.
- Publish ordering in `BrokerService._fresh_publish` (`verbs.py:450-509`): `_validated_envelope` → read owner
  (`:452`) → `_block_unsealed_owner` (`:457`) → `epoch_blocked` (`:459`) → **durable
  `append_adapter_start_owner` (`:474`)** → `admission_store.admit_next` (`:490`, first read of `admissions.jsonl`)
  → `record_intent` (`:500`) → `_crash_at("after_broker_intent_before_adapter_started")` (`:504`) →
  `validate_adapter_start_owner` (`:505`) → `ADAPTER_STARTED` → `adapter.execute` (`:526`). The store is first READ
  only after the owner is durable — that ordering is the defect for acceptance item (2).
- `_block_unsealed_owner` (`verbs.py:363-411`): an unsealed owner whose `effect_key` has no evidence record gets
  `PROVIDER_CALL_IN_FLIGHT` then `OUTCOME_AMBIGUOUS_BLOCKED` with reference `unsealed-adapter-start-owner`
  (`:395-408`). `OUTCOME_AMBIGUOUS_BLOCKED` has no transition out (`evidence.py:225-230`, `live.py:1367-1368`) and
  `BrokerEvidenceStore.epoch_blocked` (`evidence.py:85-95`) is repository-partition-scoped and permanent.
- **Frozen contract collision.** `tests/test_fabpub_shared_epoch.py::test_fabpub_shared_adapter_start_fence_blocks_competing_train_before_and_after_possible_provider_effect`
  (`:1909-2010`, count-guarded in `tests/_fabpub_tdd_guard.py:210,348,400,555`) crashes train A
  `after="adapter_start_owner"` — i.e. owner durable, admission NOT reached, the ah#789 chronology exactly — and
  asserts train B promotes that owner to `OUTCOME_AMBIGUOUS_BLOCKED` (`:1981-1989`) and that no later attempt clears
  it (`:1991-2010`). Retiring a pre-admission owner as no-effect therefore contradicts a ratified EC-FABPUB frozen
  test, not merely current code.
- Sealed-inventory worktree rows (`live.py:2303-2309`) carry `worktree`, `canonical_repository_identity`,
  `namespace_root` (= `<git-common-dir>/phase-loop-fabpub-broker-v1`), `classification`, `files`. Identity is
  `sha256(CanonicalRepositoryIdentity.v1 {git_common_dir, git_object_format})` (`live.py:301-318`) — a function of
  the COMMON dir, not the worktree path. `_revalidate_bootstrap_sources` (`live.py:2470-2505`) re-snapshots
  `row["worktree"]` (`:2496-2498`) and `WriterGenerationLatch.open(worktree)` (`:2604`) opens latches by that
  path; both fail in `_git_out` (`live.py:109-117`) with "No such file" once the worktree is pruned — the incident's
  step 2. Verified on this host: `git -C <common-dir> rev-parse --path-format=absolute --git-common-dir` and
  `--show-object-format` succeed inside the common dir itself, so identity is recoverable from
  `Path(row["namespace_root"]).parent` without the worktree.
- The host inventory `~/.local/state/phase-loop/fabpub/authority-v1/fabpub-host-bootstrap-20260904.bootstrap-inventory.json`
  pins `/mnt/HC_Volume_105438154/worktrees/{agent-harness-fabpub-bootstrap-clean,omniagent-plus-omnigent-v0-12}`;
  both currently exist (restored + locked by the incident responder). Not to be edited by this plan.
- The only adapter entry that is NOT preceded by `record_intent` is the non-publish legacy seam
  (`verbs.py:582-596`), which never writes an adapter-start owner; owners are written only from `_fresh_publish`
  (`:474`, `:488`).
- Existing crash-injection fixture to reuse: `_execute_with_crash(service, request, after="adapter_start_owner")`
  (`test_fabpub_shared_epoch.py:2165-2181`), which monkeypatches `evidence_module.append_adapter_start_owner`.

## Scope decision

Three concerns → **three PRs**, all `production_code` tier except where noted, stacked in the order below. Per
`AGENTS.md` plan discipline this plan pins inputs (base SHA, frozen-test node ids, message strings) and never its own
future SHAs/commit counts. New tests go in NEW files so the count-guarded FABPUB corpus (`_fabpub_tdd_guard.py`) is
untouched; a node id must not collide with any frozen inventory (see [[test-name-leaks-into-another-phases-frozen-corpus]]).

### Workstream A — pre-admission runtime-compatibility guard (acceptance items 1, 2)

`phase-loop-runtime/src/phase_loop_runtime/convergence/broker/admission.py` (modify)
- `AdmissionStoreIncompatible(PermissionError)` — add — typed, actionable failure: message names the store path,
  the record sequence, the unknown/missing field names, and `phase_loop_runtime.__version__` +
  `Path(phase_loop_runtime.__file__)` (so a stale `uv tool` install is identifiable from the message; the version
  string alone is not discriminating, see research). Subclass of `PermissionError` so every existing
  `except PermissionError` fail-closed path keeps failing closed.
- `_records` (`:150-171`) — modify — wrap each `AdmissionRecord(**raw)` / `ReadmitAdmissionBinding(**b)` /
  request-dataclass construction; translate `TypeError` into `AdmissionStoreIncompatible` carrying the offending
  keys (`set(raw) - {f.name for f in dataclasses.fields(AdmissionRecord)}`). No tolerance/ignore of unknown keys —
  strict, as today, just typed.
- `probe_readable()` — add — read-only: takes the store lock (`admissions.lock`, shared with the owner file,
  `verbs.py:106`), calls `_records()`, releases; returns the record count. Creates nothing (must not call
  `_authorize()`'s `mkdir`; guard on `self.path.exists()` first). This is the EARLY, actionable refusal only — it
  does not close the race on its own (next bullet + the `verbs.py` precondition).
- Unknown-key extraction is per constructor, not top-level only: `AdmissionRecord`, `ReadmitAdmissionBinding`
  (`:155`), and the three request dataclasses (`DeltaReadmitAuthority` `:163`, `AdmissionRequest` `:165`,
  `PreAdmissionEnvelope` `:167`) each get `set(raw_dict) - {f.name for f in dataclasses.fields(cls)}` at their
  own construction site, so the message names the nested field that broke.

`phase-loop-runtime/src/phase_loop_runtime/convergence/broker/verbs.py` (modify)
- `_fresh_publish` (`:450`) — modify — call `self.admission_store.probe_readable()` and
  `self.evidence_store.replay()` (already read-only) BEFORE `read_adapter_start_owner` at `:452`, so an
  incompatible reader fails at the first line, before `_block_unsealed_owner` and before the durable owner write at
  `:474`. `AdmissionStoreIncompatible` propagates unchanged (it is a `PermissionError`, the publish surface's
  existing refusal type).
- Check/use race (round-1 F1, sharpened by round-2 sol #1): the probe releases `admissions.lock`;
  `append_adapter_start_owner` (`:95-121`) re-acquires it; `admit_next` (`:494`) acquires it a third time. The
  unsealed owner is NOT an exclusion for every admission writer — `readmit_advanced_head` (`:226`,
  `admit_next(auth)`, the delta-readmit path that writes `binding`-bearing records) and the non-publish `admit`
  (`:582`) never consult the owner — so a newer-runtime readmit can land an incompatible record between our owner
  write and our `admit_next`, and the incident chronology (owner durable, then `TypeError`) recurs. A precondition
  inside the owner write alone does not close this. Close it with ONE critical section, the idiom the store already
  uses (`seal_adapter_start_owner(..., lock_held=True)` `:154/:171`, `live.py:3288-3291`):
  - `append_adapter_start_owner` and `admit_next` (`admission.py:177`) each gain `lock_held: bool = False`
    (skip their own `open`+`flock` when held; `admissions.lock` is the SAME file for both stores,
    `admission.py:117`, `evidence.py:58`, so a nested acquisition through a second descriptor would deadlock —
    that is why the flag, not a re-entrant lock).
  - `_fresh_publish` acquires `admissions.lock` once around today's `:474-:496` and, in order: (1)
    `self.admission_store._records()` — compatibility validation in-lock (`_records` is lock-free,
    `admission.py:149`; nothing it calls takes the lock); (2) in-lock owner re-read; if an UNSEALED foreign owner is
    present, release the lock and take today's `_block_unsealed_owner` refusal path unchanged (`:363-411` takes the
    same lock itself, so it must run outside the section; it never leads to an admission); (3)
    `append_adapter_start_owner(..., lock_held=True)`; (4) `admit_next(..., lock_held=True)` with today's
    `precondition` (transaction state). Release. Owner and admission are now allocated under one acquisition, so no
    writer of any version can interleave a record between them.
  - `_block_unsealed_owner`, `record_intent` (`:500`) and the adapter ordering are byte-identical.
  - Deterministic regression (see tests): the readmit interleaving is reproduced by monkeypatching
    `admission_store._records` to append the incompatible line the FIRST time it is called (i.e. after the early
    probe passed, before the section's own validation) — the section must refuse with the owner file absent.
- Keep `record_intent`/adapter ordering byte-identical (Workstream C depends on nothing here).

`phase-loop-runtime/tests/test_fabpub_admission_compat_789.py` (create) — tests_only lane, RED-first
- `test_incompatible_admission_record_refused_before_owner_acquisition` — build a routed store via the same
  `_service`/`_publish_transaction_request` helpers the shared-epoch tests use (import them; do not copy), append one
  raw admission line with an extra key (`"future_field": 1`) to `admissions.jsonl`, run `service.execute(request)`,
  assert `AdmissionStoreIncompatible` whose message names `future_field`, then assert the CHRONOLOGY:
  `adapter-start-owner.json` absent, `evidence.jsonl` unchanged, `admissions.jsonl` byte-identical, transaction
  state still `COMMITTED_HEAD_RESOLVED`, adapter call count 0.
- `test_legacy_reader_shape_reproduces_incident` — the acceptance item (1) reproduction: monkeypatch
  `admission_module.AdmissionRecord` with a frozen copy lacking `binding` (a dataclass with fields
  `sequence, epoch, request`), seed one `binding`-bearing record, and assert the same typed refusal + chronology.
  Falsifier for A (RUN it, record the anchor; round-2 sol #2 — the early probe alone is NOT discriminating once
  the in-section validation exists): disable BOTH defenses — revert the early probe AND remove step (1) — → this
  test must fail on the owner-file-absent assertion (owner written, then `TypeError`), which is the incident
  replayed. With only the probe reverted the test stays green, and that is the point of step (1).
- `test_incompatible_reader_performs_no_mutation_before_owner_path` — the early probe's OWN property (issue item
  2: "prevent unsupported installed runtimes from entering ownership/provider MUTATION"): seed an unsealed foreign
  owner with no evidence record plus one incompatible admission line; `service.execute` must raise
  `AdmissionStoreIncompatible` with `evidence.jsonl` byte-identical — without the probe the reader reaches
  `_block_unsealed_owner` (`:457`) and appends `PROVIDER_CALL_IN_FLIGHT`/`OUTCOME_AMBIGUOUS_BLOCKED` records
  (`:395-408`) before ever touching the admission log. Falsifier (RUN it): revert the early probe → `evidence.jsonl`
  grows, test RED. This is why the probe is kept even though the critical section carries the owner guarantee.
- `test_probe_readable_creates_nothing` — probe against a never-created store root leaves the root absent.
- `test_incompatible_record_landing_after_probe_still_refused_before_owner_write` — the concurrent-writer
  regression (F1), deterministic: monkeypatch `admission_store.probe_readable` to append the `future_field` line to
  `admissions.jsonl` AFTER returning success (the store mutates after the early probe), run `service.execute`,
  assert `AdmissionStoreIncompatible`, `adapter-start-owner.json` absent, no admission appended. Falsifier (RUN
  it): remove step (1) (the in-section `_records()` validation) → owner file present, test RED.
- `test_readmit_writer_cannot_interleave_between_owner_and_admission` — the round-2 interleaving: two
  `BrokerService`s over one store; wrap the first's `admission_store._records` so that its in-section call blocks
  on a `threading.Event` while a second thread runs `readmit_advanced_head` with a `binding`-bearing authority;
  the readmit must BLOCK on `admissions.lock` (assert it has not returned after the event fires and the first
  service's `admit_next` completed), and the first publish allocates its admission with exactly one record between
  its owner write and its admission. Falsifier (RUN it): restore the two separate lock acquisitions (`lock_held`
  False at both sites) → the readmit returns first and the publish fails after its owner is durable.
- Positive control: a compatible store still publishes exactly once (reuse the existing publish-through-`admit_next`
  path from `test_fabpub_broker_envelope_publish_allocates_through_admit_next`, `:1763`).

### Workstream B — sealed-inventory worktree lifecycle (acceptance item 4)

Chosen option: make the inventory's `worktree` path **non-load-bearing** for identity revalidation and latch access;
the repository is identified by its recorded common dir. Rejected alternatives: (i) "block the prune with an
actionable reason" — the runtime cannot intercept `git worktree remove`/`prune`, so the block would be advisory
only; (ii) "reviewed inventory migration" — the sealed inventory digest covers the path
(`live.py:2404-2405`, `_inventory_digest`), so migration means a re-seal + journal transition — a larger contract
change than the incident justifies, and it would still break on the NEXT prune. The board should confirm (B) is a
contract clarification, not a weakening: identity was never path-derived (`live.py:301-318`).

`phase-loop-runtime/src/phase_loop_runtime/convergence/broker/live.py` (modify)
- `_inventory_row_repository(row: dict) -> Path` — add — returns `Path(row["worktree"])` when
  `is_git_repository(...)` (`:3105`) holds; else `Path(row["namespace_root"]).parent` when that common dir exists
  and `git -C <it> rev-parse --git-common-dir` resolves to itself; else raises `LegacyCutoverConflict` with an
  actionable message ("sealed inventory row for <identity> names pruned worktree <path> and its repository common
  dir <common> is gone; restore the repository or rotate the authority") — the fail-closed branch.
- `_revalidate_bootstrap_sources` (`:2496-2498`) — modify — snapshot via `_inventory_row_repository(row)`; the
  identity equality at `:2501` is unchanged (that is the property; the path is not).
- Bootstrap resume latch opening (`:2603-2609`) — modify — `WriterGenerationLatch.open(_inventory_row_repository(row))`
  and `await_quiescent(worktree=...)` likewise. Audit every other `row["worktree"]` reader (`:1801,1820,1969,1977,
  2498,2589,2603`) and route each through the helper; list them in the PR body with the line each became.
- Emit one structured warning (existing report/journal mechanism, not print) when the helper falls back to the
  common dir, so drift is visible without being fatal.

`phase-loop-runtime/tests/test_fabpub_inventory_worktree_lifecycle_789.py` (create) — RED-first
- Seal a zero-history bootstrap inventory over a LINKED worktree (`git worktree add` of a tmp repo), then
  `git worktree remove` it, then run the resume/revalidation path: must succeed, identity equal, warning emitted.
- Negative: delete the main repository (common dir) too → `LegacyCutoverConflict` with the actionable message; no
  journal transition written.
- Negative: make the helper's fallback resolve to a DIFFERENT repository — point `namespace_root` at a path whose
  `rev-parse --git-common-dir` differs from the sealed row's common dir → "repository identity changed after seal"
  fires (proves the helper did not loosen identity; equality at `:2501` is the property).
- Stated limit (round-1 finding F2, carried not claimed): a different repository re-created at the SAME common-dir
  path with the same object format has the SAME `CanonicalRepositoryIdentity.v1` (`live.py:301-318` hashes only
  `git_common_dir` + `git_object_format`), so it is undetectable TODAY at base and B neither fixes nor worsens it.
  Do not write a test that promises that refusal.
- Helper self-check uses `git -C <common> rev-parse --path-format=absolute --git-common-dir` (or `.resolve()` on
  the output): from inside the common dir plain `rev-parse --git-common-dir` prints `.`.
- Falsifier (RUN it): revert the helper to `row["worktree"]` → first test fails in `_git_out` with the incident's
  "No such file" text.

### Workstream C — pre-admission owner recovery policy (acceptance items 3, 5) — DECIDED: C-keep (see `status:`)

This is a frozen-contract question (see research, collision with `test_fabpub_shared_adapter_start_fence_…`
`:1981-1989`). Two admissible positions were put to the maintainer; **C-keep was chosen 2026-09-06**. C-change is
kept below only so the board's rejection stays on the record.

- **C-keep (recommended).** Keep "owner durable ⇒ possible provider effect ⇒ permanent ambiguity". Rationale: the
  chronology proof ("no intent record ⇒ adapter never entered") is only as strong as the WEAKEST runtime version that
  can write owners into the shared store, and this incident is precisely a version-skew incident; a future skewed
  writer with different ordering would turn intent-absence into a false no-effect proof. Workstream A removes the
  recurrence (the reader now fails before the owner write), so the class of pre-admission ambiguities this incident
  created should not recur from THIS cause. The supported operator recovery is then what ah#789 recorded: a
  documented, recorded, one-time operator override outside the governed path, plus the partition consequence below.
  Deliverables under C-keep: `docs/` operator note + the ah#789 ambiguity record left permanent + the controls
  below (tests_only lane, `phase-loop-runtime/tests/test_fabpub_recovery_controls_789.py`, create):
  - negative (unknown effect stays unknown): a partition holding an `OUTCOME_AMBIGUOUS_BLOCKED` record refuses a
    fresh publish for the exact intended branch with `git ls-remote`/the adapter's remote probe monkeypatched to
    raise — proves the refusal never consults the remote (issue item 3: "never infer no-effect from remote absence
    or timeout"); the blocked record is byte-identical afterwards (`evidence.py:230` has no transition out).
  - positive, "without weakening fencing for unrelated operations": two repository partitions in one authority
    root; block the first, publish through the second → exactly one admission + one adapter call, first still
    blocked (`epoch_blocked` scope, `evidence.py:85-95`). Reuse the multi-repository fixture shape of
    `test_fabpub_global_legacy_cutover_partitions_multiple_repositories_…` (`test_fabpub_shared_epoch.py:2700`).
  - **Carried, not discharged (round-1 finding F3):** item (5)'s FIRST half — "a completed recovery can publish
    the exact intended branch once" — has no governed path under C-keep; the only governed recovery is partition
    rotation (Workstream D), which is deferred. That positive control is carried to the D plan, and
    Consiliency/agent-harness#789 stays OPEN after A, B and the C-keep deliverables land. Whether to amend item (5)
    instead is the maintainer's call; this plan records the carry and claims nothing for it.
- **C-change.** Amend the frozen contract so an unsealed owner with NO evidence record for its `effect_key` is
  retired `NO_EFFECT_TERMINAL_PROVEN` (reference `pre-admission-owner-no-intent`) by `_block_unsealed_owner`, derived
  ONLY from local durable chronology (`record_intent` `:498` precedes adapter entry `:526`; owners are written only at
  `:474/:488`). Requires: (a) editing the frozen test's `before_provider_effect` branch — an `sl0_repairs` append on
  `plans/manifest.json` (`v10-FABPUB`, precedent Consiliency/agent-harness#614) and a re-derivation of any digest
  the guard pins over that test body (`test_fabpub_guard_vector_digests_match_inline_vectors`, `:843`); (b) a
  positive control (crash after owner, then a fresh publish admits once and publishes exactly one branch); (c)
  negative controls: intent present + no terminal ⇒ still ambiguous; an existing `OUTCOME_AMBIGUOUS_BLOCKED` record
  is never transitioned (`evidence.py:230`); the recovery path never consults a remote (`git ls-remote` monkeypatched
  to raise ⇒ unaffected); (d) falsifier: move `record_intent` after `adapter.execute` ⇒ the positive control must
  go RED. Not recommended for the reason above; listed so the board rejects it on the record rather than by silence.

Neither option rewrites transaction `b72b68ff…`'s record; it stays permanent under both.

### Workstream D — permanently blocked repository partition (consequence of C-keep) — DESIGN NOTE ONLY

Under C-keep the omniagent-plus partition (`1da3e343…`) is permanently `epoch_blocked` (`evidence.py:85-95`), so
governed FABPUB publication for that repository is closed under the current authority. The supported way out is a
reviewed **partition rotation** (retire the blocked partition into `historical_evidence_roots`, onboard a fresh
receipt for the same canonical identity) — this is the "replacement authority root" the incident responder
correctly refused to improvise. Out of scope here; if the maintainer wants it, it is its own detailed plan
(touches `live.py` receipts/journal + zero-history onboarding, `live.py:2380-2420`, `:3200-3215`).

## Documentation impact
- `CHANGELOG.md` `## [Unreleased]` — add — one entry per landed workstream (A: typed pre-admission compatibility
  refusal; B: inventory worktree path no longer load-bearing), citing Consiliency/agent-harness#789.
- `docs/` — add (C-keep only) — operator note: what a pre-admission ambiguity is, why it is permanent, the recorded
  override procedure, and the partition-rotation pointer (D).
- `plans/manifest.json` — add — `type=detailed` entry for this plan (`plan-manifest append`), and an
  `sl0_repairs` append on `v10-FABPUB` ONLY if C-change is chosen.
- `specs/phase-plans-v10.md` — none (LEGIBLE-owned; nothing here changes a roadmap goal).

## Dependencies & order
1. Maintainer approval of this plan (this document) → plan-tier board (4/4) → land.
2. Operational prerequisite, already authorized: re-pin the installed `phase-loop-runtime` to current main so the
   host stops running the pre-ah#288 reader (`uv tool install --force
   "git+https://github.com/Consiliency/agent-harness@<main sha>#subdirectory=phase-loop-runtime"`; NOT from the
   dirty `~/code/agent-harness` checkout). Record the resulting `uv-receipt.toml` source in the PR body of A.
3. PR-A (tests_only lane first, RED observed, then production) — independent of B.
4. PR-B — independent of A; may run in parallel.
5. C decision → C-keep: docs PR (docs_only, admin-merge after completed CR); C-change: its own plan amendment
   + tests_only + production PRs, after A lands.
6. After B lands: the two locked host worktrees may be unlocked/pruned (needs a separate yes; not part of any PR).

## Verification
- Suite (CI-faithful recipe, installed venv): `cd phase-loop-runtime && PYTHONPATH=$PWD/tests
  /mnt/workspace/venvs/ah-779-ci/bin/python -m pytest tests/test_fabpub_admission_compat_789.py
  tests/test_fabpub_inventory_worktree_lifecycle_789.py tests/test_fabpub_recovery_controls_789.py tests/test_fabpub_shared_epoch.py
  tests/test_fabpub_zero_history_bootstrap.py -p no:cacheprovider -o addopts="" -q` — frozen corpus counts
  unchanged (`test_fabpub_guard_nodeid_inventories_are_disjoint_and_counted` green).
- Each falsifier above RUN and its anchor recorded in the PR body (never "should fail").
- Chronology witness for A: after the refusal, `ls <store>/adapter-start-owner.json` → absent; `wc -l
  admissions.jsonl evidence.jsonl` unchanged.
- Host reproduction (read-only, after re-pin): `phase-loop … resume` against the saved transaction
  `b72b68ff…` must now refuse with the permanent-block message from the NEW reader (no `TypeError`), and must not
  write anything under the checkpoint root — proves the skew is gone and the record is untouched.

## Acceptance criteria
- [ ] An admission record with an unknown field makes `_fresh_publish` raise `AdmissionStoreIncompatible` naming the
      field and the runtime location, with `adapter-start-owner.json` absent and `admissions.jsonl`/`evidence.jsonl`
      byte-identical afterwards (falsified by removing BOTH the early probe and the in-section validation — owner
      file present; falsified for the probe alone by `evidence.jsonl` growing).
- [ ] Owner write and admission allocation in `_fresh_publish` happen under one `admissions.lock` acquisition:
      the readmit-interleaving test blocks the competing writer until the publish's admission is durable
      (falsified by restoring the separate acquisitions).
- [ ] The incident chronology (legacy reader without `binding`, store with `binding`) is reproduced by a test that
      fails at base `463b90c3` (owner written) and passes after PR-A.
- [ ] A sealed inventory whose `worktree` path was pruned revalidates and resumes with identity equality intact
      when the common dir exists, and fails closed with the actionable message when it does not.
- [ ] Frozen FABPUB corpus node ids and counts are unchanged by PR-A and PR-B; `_fabpub_tdd_guard.py` untouched.
- [ ] The maintainer's C decision is recorded in this plan's `status:` line before any C work starts; transaction
      `b72b68ff…`'s `outcome_ambiguous_blocked` record is byte-identical before and after every PR here.
- [ ] Issue item (5): the recovery-controls tests above pass; the "publish the exact intended branch once"
      positive control is recorded as carried to the Workstream D plan (ah#789 left open), not claimed here.

## Execution Policy
- execute: effort=high, reason=shared-store concurrency and a frozen fail-closed contract; A and B are small
  diffs but every line is on the fencing path.
